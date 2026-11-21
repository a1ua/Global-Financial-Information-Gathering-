from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main


EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "weekly-review.synthetic.example.json"


class WeeklyReviewCLITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.source = Path(directory) / "weekly.json"
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("unexpected database")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("unexpected network")))

    def invoke(self, monday="2026-11-09"):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(["summarize-synthetic-week", "--input", str(self.source),
                         "--week-monday", monday])
        return code, output.getvalue(), errors.getvalue()

    def test_sample_summary_leaves_original_bytes_intact(self):
        raw = EXAMPLE.read_bytes()
        self.source.write_bytes(raw)
        code, output, errors = self.invoke()
        self.assertEqual((code, errors), (0, ""))
        summary = json.loads(output)
        expected_counts = {"total": 2, "calculated": 1, "pending": 1, "unavailable": 0}
        self.assertEqual(summary["schema_version"], "synthetic-weekly-review/0.1")
        self.assertTrue(summary["is_synthetic"])
        self.assertEqual(summary["week_monday"], "2026-11-09")
        self.assertEqual(summary["counts"], expected_counts)
        self.assertEqual(summary["protocols"], [{
            "evaluation_protocol_sha256": "c" * 64,
            "counts": expected_counts,
            "mean_car": "0.15000000",
        }])
        self.assertEqual(self.source.read_bytes(), raw)

    def test_malformed_json_and_invalid_week_have_sanitized_errors(self):
        self.source.write_bytes(b'{"value":"private-fixture-marker","value":1}')
        code, output, errors = self.invoke()
        self.assertEqual((code, output), (1, ""))
        self.assertEqual(json.loads(errors)["reason"], "weekly_review_input_invalid")
        self.assertNotIn("private-fixture-marker", errors)
        self.assertNotIn(str(self.source), errors)

        self.source.write_bytes(EXAMPLE.read_bytes())
        code, output, errors = self.invoke("2026-11-10")
        self.assertEqual((code, output), (1, ""))
        self.assertEqual(json.loads(errors)["reason"], "synthetic_weekly_review_invalid")
