from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "config" / "synthetic-extraction-evaluation.example.json"
CUTOFF = "2026-11-06T00:05:03.000Z"


class EvaluationProvenanceCLITests(unittest.TestCase):
    def setUp(self):
        workdir = self.enterContext(tempfile.TemporaryDirectory())
        self.workdir = Path(workdir)

    def run_cli(self, source, *, provenance=False, cutoff=CUTOFF):
        args = [
            sys.executable, "-X", "utf8", "-m", "market_intel",
            "evaluate-synthetic-extraction", "--input", str(source), "--cutoff", cutoff,
        ]
        if provenance:
            args.append("--include-provenance")
        return subprocess.run(
            args, cwd=self.workdir, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
        )

    def read_report(self, source, *, provenance=False, cutoff=CUTOFF):
        proc = self.run_cli(source, provenance=provenance, cutoff=cutoff)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        return json.loads(proc.stdout)

    def test_batch37_sample_keeps_default_report_and_exact_provenance(self):
        raw = SAMPLE.read_bytes()
        default = self.read_report(SAMPLE)
        extended = self.read_report(SAMPLE, provenance=True)
        self.assertNotIn("provenance", default)
        self.assertEqual(default["schema_version"], "synthetic-extraction-evaluation/0.1")
        self.assertEqual(
            default["counts"],
            {"total": 4, "correct": 1, "incorrect": 1, "invalid": 1, "missing": 1},
        )
        self.assertEqual(extended.pop("provenance"), {
            "input_sha256": sha256(raw).hexdigest(),
            "cutoff": CUTOFF,
        })
        self.assertEqual(extended, default)
        self.assertEqual(SAMPLE.read_bytes(), raw)
        self.assertEqual(list(self.workdir.iterdir()), [])

    def test_equivalent_json_bytes_and_cutoff_spelling_remain_distinguishable(self):
        original = SAMPLE.read_bytes()
        variants = [original, b"\n" + original + b" "]
        cutoffs = [CUTOFF, "2026-11-06T00:05:03Z"]
        source = self.workdir / "sample.json"
        reports = []
        for raw in variants:
            source.write_bytes(raw)
            for cutoff in cutoffs:
                report = self.read_report(source, provenance=True, cutoff=cutoff)
                self.assertEqual(report.pop("provenance"), {
                    "input_sha256": sha256(raw).hexdigest(),
                    "cutoff": cutoff,
                })
                reports.append(report)
                self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(reports, [reports[0]] * 4)
        self.assertEqual(list(self.workdir.iterdir()), [source])

    def test_rejected_inputs_do_not_emit_provenance_or_private_data(self):
        source = self.workdir / "private-source.json"
        bad_json = b'{"a":"private-payload-marker","a":1}'
        cases = (
            (bad_json, CUTOFF, "synthetic_extraction_input_invalid"),
            (SAMPLE.read_bytes(), "2026-11-06T00:05:02.999999Z", "synthetic_extraction_evaluation_invalid"),
        )
        for raw, cutoff, reason in cases:
            with self.subTest(reason=reason):
                source.write_bytes(raw)
                proc = self.run_cli(source, provenance=True, cutoff=cutoff)
                self.assertEqual((proc.returncode, proc.stdout), (1, ""))
                self.assertEqual(json.loads(proc.stderr)["reason"], reason)
                for private_value in (source.name, "private-payload-marker", "provenance", sha256(raw).hexdigest()):
                    self.assertNotIn(private_value, proc.stderr)
                self.assertEqual(source.read_bytes(), raw)
