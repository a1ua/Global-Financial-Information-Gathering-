from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.contracts.synthetic_extraction import evaluate_synthetic_extraction


class SyntheticScoreCLITests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "demo.json"
        self.reference = json.loads(fixture.read_text(encoding="utf-8"))
        self.cutoff = self.reference["raw"]["available_at"]
        workdir = self.enterContext(tempfile.TemporaryDirectory())
        self.source = Path(workdir) / "synthetic-evaluation.json"
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("unexpected network")))
        self.enterContext(patch("sqlite3.connect", side_effect=AssertionError("unexpected database")))
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("unexpected workspace")))

    def arguments(self, cutoff=None):
        return ["evaluate-synthetic-extraction", "--input", str(self.source),
                "--cutoff", self.cutoff if cutoff is None else cutoff]

    def invoke(self, cutoff=None):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(self.arguments(cutoff))
        return code, output.getvalue(), errors.getvalue()

    def assert_invalid(self, reason, marker=None, *, cutoff=None):
        code, output, errors = self.invoke(cutoff=cutoff)
        self.assertEqual((code, output), (1, ""))
        self.assertEqual(json.loads(errors)["reason"], reason)
        self.assertNotIn(self.source.name, errors)
        if marker is not None:
            self.assertNotIn(marker, errors)

    def test_module_and_in_process_outputs_match_api_without_writes(self):
        def case(raw_id, proposal):
            reference = deepcopy(self.reference)
            reference["raw"]["raw_item_id"] = raw_id
            reference["event"]["input_raw_item_ids"] = [raw_id]
            reference["evidence"]["raw_item_id"] = raw_id
            return {"reference_bundle": reference, "expected_category": "company", "proposal": proposal}

        fixed = self.reference["raw"]
        valid = {
            "schema_version": "synthetic-extraction-proposal/0.1", "is_synthetic": True,
            "raw_item_id": "raw_good_proposal", "content_sha256": fixed["content_sha256"],
            "normalization_version": fixed["normalization_version"], "category": "company",
            "start": 0, "end": 2, "quote": fixed["normalized_text"][:2],
        }
        cases = [case("raw_missing_proposal", None),
                 case("raw_bad_proposal", {"quote": "private-proposal-marker"}),
                 case("raw_good_proposal", valid)]
        raw = json.dumps(cases, ensure_ascii=False).encode("utf-8")
        self.source.write_bytes(raw)
        expected = evaluate_synthetic_extraction(cases, cutoff=self.cutoff)
        code, output, errors = self.invoke()
        self.assertEqual((code, errors, json.loads(output)), (0, "", expected))
        self.assertNotIn("private-proposal-marker", output)
        self.assertEqual(expected["counts"],
                         {"total": 3, "correct": 1, "incorrect": 0, "invalid": 1, "missing": 1})

        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "market_intel", *self.arguments()],
                              cwd=self.source.parent, env={**os.environ, "PYTHONPATH": str(root / "src")},
                              capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual((proc.returncode, proc.stderr, json.loads(proc.stdout)), (0, "", expected))
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])

    def test_file_size_limit_is_inclusive(self):
        maximum = 1_048_576
        raw = b"[]" + b" " * (maximum - 2)
        self.source.write_bytes(raw)
        code, output, errors = self.invoke()
        self.assertEqual((code, errors, json.loads(output)),
                         (0, "", evaluate_synthetic_extraction([], cutoff=self.cutoff)))
        self.source.write_bytes(raw + b" ")
        self.assert_invalid("synthetic_extraction_input_too_large")

    def test_malformed_json_errors_do_not_echo_text_or_paths(self):
        malformed = (b'{"field":"private-json-marker","field":1}', b'[NaN]', b'["\xff"]', b"[")
        for raw in malformed:
            with self.subTest(raw=raw):
                self.source.write_bytes(raw)
                self.assert_invalid("synthetic_extraction_input_invalid", "private-json-marker")

    def test_valid_json_bad_batch_and_cutoff_are_rejected(self):
        self.source.write_bytes(b'{"marker":"private-batch-marker"}')
        self.assert_invalid("synthetic_extraction_evaluation_invalid", "private-batch-marker")
        self.source.write_bytes(b"[]")
        self.assert_invalid("synthetic_extraction_evaluation_invalid", "private-cutoff-marker",
                            cutoff="private-cutoff-marker")
