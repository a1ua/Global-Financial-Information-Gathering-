from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from market_intel.contracts.synthetic_extraction import evaluate_synthetic_extraction


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "config" / "synthetic-extraction-evaluation.example.json"
CUTOFF = "2026-11-06T00:05:03.000Z"
EXPECTED = [
    {"case_number": 2, "status": "incorrect", "expected_category": "policy", "proposed_category": "macro"},
    {"case_number": 3, "status": "invalid", "expected_category": "macro", "proposed_category": None},
    {"case_number": 4, "status": "missing", "expected_category": "calendar", "proposed_category": None},
]


class ScoreDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.raw = SAMPLE.read_bytes()
        self.cases = json.loads(self.raw)

    def run_cli(self, source, *flags):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "market_intel", "evaluate-synthetic-extraction",
             "--input", str(source), "--cutoff", CUTOFF, *flags],
            cwd=self.workdir, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
        )

    def test_actual_cli_combines_diagnostics_and_provenance_without_disclosing_text(self):
        default = self.run_cli(SAMPLE)
        extended = self.run_cli(SAMPLE, "--include-diagnostics", "--include-provenance")
        self.assertEqual((default.returncode, default.stderr, extended.returncode, extended.stderr),
                         (0, "", 0, ""))
        default_report = json.loads(default.stdout)
        report = json.loads(extended.stdout)
        self.assertNotIn("diagnostics", default_report)
        self.assertEqual(report.pop("diagnostics"), EXPECTED)
        self.assertEqual(report.pop("provenance"), {
            "input_sha256": sha256(self.raw).hexdigest(), "cutoff": CUTOFF,
        })
        self.assertEqual(report, default_report)
        self.assertEqual(default_report["counts"],
                         {"total": 4, "correct": 1, "incorrect": 1, "invalid": 1, "missing": 1})
        for case in self.cases:
            raw = case["reference_bundle"]["raw"]
            for value in (raw["raw_item_id"], raw["normalized_text"], raw["content_sha256"]):
                self.assertNotIn(value, extended.stdout)
        self.assertNotIn(self.cases[2]["proposal"]["quote"], extended.stdout)
        self.assertEqual(SAMPLE.read_bytes(), self.raw)
        self.assertEqual(list(self.workdir.iterdir()), [])

    def test_api_diagnostics_follow_input_positions_but_aggregates_do_not(self):
        ordered = evaluate_synthetic_extraction(self.cases, cutoff=CUTOFF, include_diagnostics=True)
        reversed_report = evaluate_synthetic_extraction(self.cases[::-1], cutoff=CUTOFF,
                                                        include_diagnostics=True)
        self.assertEqual(ordered.pop("diagnostics"), EXPECTED)
        self.assertEqual(reversed_report.pop("diagnostics"), [
            {**expected, "case_number": position}
            for position, expected in enumerate(reversed(EXPECTED), 1)
        ])
        self.assertEqual(ordered, reversed_report)
        self.assertEqual(self.cases, json.loads(self.raw))

    def test_api_diagnostics_are_empty_for_an_empty_or_correct_only_batch(self):
        for cases in ([], self.cases[:1]):
            with self.subTest(count=len(cases)):
                extended = evaluate_synthetic_extraction(cases, cutoff=CUTOFF, include_diagnostics=True)
                self.assertEqual(extended.pop("diagnostics"), [])
                self.assertEqual(extended, evaluate_synthetic_extraction(cases, cutoff=CUTOFF))

    def test_api_diagnostics_switch_requires_a_boolean(self):
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "^synthetic_extraction_evaluation_invalid$"):
                evaluate_synthetic_extraction([], cutoff=CUTOFF, include_diagnostics=value)

    def test_rejected_batch_does_not_print_partially_collected_diagnostics(self):
        source = self.workdir / "private-batch.json"
        payload = json.dumps([*self.cases, self.cases[-1]], ensure_ascii=False).encode("utf-8")
        source.write_bytes(payload)
        proc = self.run_cli(source, "--include-diagnostics", "--include-provenance")
        self.assertEqual((proc.returncode, proc.stdout), (1, ""))
        self.assertEqual(json.loads(proc.stderr)["reason"], "synthetic_extraction_evaluation_invalid")
        for value in (source.name, self.cases[-1]["reference_bundle"]["raw"]["raw_item_id"],
                      "diagnostics", "provenance", sha256(payload).hexdigest()):
            self.assertNotIn(value, proc.stderr)
        self.assertEqual(source.read_bytes(), payload)
