from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main


EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "weekly-review.synthetic.example.json"


class WeeklyReviewMarkdownTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.source = Path(directory) / "weekly.json"
        self.example = json.loads(EXAMPLE.read_bytes())
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("unexpected database")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("unexpected network")))

    def invoke(self, *options):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(["summarize-synthetic-week", "--input", str(self.source),
                         "--week-monday", "2026-11-09", *options])
        return code, output.getvalue(), errors.getvalue()

    def test_markdown_matches_json_and_leaves_input_intact(self):
        raw = EXAMPLE.read_bytes()
        self.source.write_bytes(raw)
        default = self.invoke()
        explicit = self.invoke("--format", "json")
        self.assertEqual(default, explicit)
        self.assertEqual((default[0], default[2]), (0, ""))
        summary = json.loads(default[1])
        code, markdown, errors = self.invoke("--format", "markdown")
        self.assertEqual((code, errors), (0, ""))
        self.assertTrue(markdown.startswith("# Synthetic weekly review\n"))
        self.assertIn("Receipt week starting 2026-11-09 (Asia/Shanghai)", markdown)
        self.assertIn("| Total | Calculated | Pending | Unavailable |", markdown)
        counts = summary["counts"]
        row = " | ".join(str(counts[key]) for key in ("total", "calculated", "pending", "unavailable"))
        self.assertIn(f"| {row} |", markdown)
        protocol, = summary["protocols"]
        self.assertIn(f"`{protocol['evaluation_protocol_sha256']}`", markdown)
        self.assertIn(protocol["mean_car"], markdown)
        self.assertEqual(self.source.read_bytes(), raw)

    def test_pending_only_mean_is_unavailable(self):
        self.source.write_text(json.dumps(self.example[1:]), encoding="utf-8")
        code, markdown, errors = self.invoke("--format", "markdown")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("| 1 | 0 | 1 | 0 |", markdown)
        self.assertIn("N/A", markdown)
        self.assertNotIn("0.00000000", markdown)

    def test_markdown_preserves_distinct_protocols_in_stable_order(self):
        self.example[0]["evaluation_protocol_sha256"] = "d" * 64
        self.source.write_text(json.dumps(self.example), encoding="utf-8")
        code, markdown, errors = self.invoke("--format", "markdown")
        self.assertEqual((code, errors), (0, ""))
        pending = f"`{'c' * 64}`"
        calculated = f"`{'d' * 64}`"
        self.assertLess(markdown.index(pending), markdown.index(calculated))
        self.source.write_text(json.dumps(self.example[::-1]), encoding="utf-8")
        self.assertEqual(self.invoke("--format", "markdown"), (code, markdown, errors))

    def test_empty_report_has_zero_counts_and_no_protocols(self):
        self.source.write_text("[]", encoding="utf-8")
        code, markdown, errors = self.invoke("--format", "markdown")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("| 0 | 0 | 0 | 0 |", markdown)
        self.assertIn("No evaluation protocols.", markdown)
