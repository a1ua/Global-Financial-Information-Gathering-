from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.offline import connect, ingest_fixture


class Batch09BCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "fixture"
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        db = connect(self.workspace / "market.db")
        try:
            ingest_fixture(db, self.bundle, self.workspace)
        finally:
            db.close()

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *extra, workspace=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        original_get = os.environ.get
        def guarded_get(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                raise AssertionError("must not read key")
            return original_get(name, default)
        args = ["evidence-candidate-plan", "--workspace", str(workspace or self.workspace),
                "--cutoff", "2026-11-07T00:00:00Z", *map(str, extra)]
        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                "market_intel.cli.os.environ.get", side_effect=guarded_get), patch(
                "market_intel.cli.connect", side_effect=AssertionError("must not use mutating connect")), patch(
                "market_intel.cli.ModelClient", side_effect=AssertionError("must not create model client")), patch(
                "socket.create_connection", side_effect=AssertionError("must not use network")):
            code = main(args)
        text = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(text), text

    def snapshot(self):
        return {p.relative_to(self.workspace).as_posix(): p.read_bytes()
                for p in self.workspace.rglob("*") if p.is_file()}

    def test_default_excludes_synthetic_without_reading_key_or_creating_ledger(self):
        before = self.snapshot()
        code, result, _ = self.invoke()
        self.assertEqual((code, result["selected_count"], result["excluded_synthetic_count"]), (0, 0, 1))
        self.assertEqual(result["data_status"], "empty")
        self.assertFalse(result["model_called"])
        self.assertFalse(result["is_synthetic"])
        self.assertEqual(self.snapshot(), before)

    def test_explicit_fixture_plan_hashes_exact_versions_without_content_output(self):
        before = self.snapshot()
        code, result, text = self.invoke("--include-synthetic")
        self.assertEqual((code, result["data_status"], result["selected_count"]), (0, "synthetic", 1))
        entry = result["input_manifest"]["candidates"][0]
        self.assertEqual(entry["event_version_id"], self.bundle["event"]["event_version_id"])
        self.assertIsNone(entry["receipt_committed_at"])
        encoded = json.dumps(result["input_manifest"], ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(result["input_manifest_sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertNotIn(self.bundle["event"]["title"], text)
        self.assertNotIn(self.bundle["raw"]["normalized_text"], text)
        self.assertNotIn("https://", text)
        self.assertNotIn(str(self.workspace), text)
        self.assertEqual(self.snapshot(), before)

    def test_missing_workspace_is_not_initialized(self):
        missing = self.root / "missing"
        code, result, text = self.invoke(workspace=missing)
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertFalse(missing.exists())
        self.assertNotIn(str(missing), text)

    def test_missing_latest_eligible_file_fails_even_at_zero_cap(self):
        raw_file = self.workspace / self.bundle["raw"]["content_ref"]
        raw_file.unlink()
        code, result, _ = self.invoke("--include-synthetic", "--max-candidates", 0)
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertFalse(raw_file.exists())

    def test_invalid_cutoff_and_limits_do_not_write(self):
        before = self.snapshot()
        for args in (("--cutoff", "2026-11-07"), ("--max-candidates", -1), ("--max-candidates", 101)):
            self.assertEqual(self.invoke(*args)[0], 1)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
