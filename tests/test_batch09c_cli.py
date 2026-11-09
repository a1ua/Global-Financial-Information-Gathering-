from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.offline import connect, ingest_fixture


class Batch09CCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "source"
        self.bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        db = connect(self.workspace / "market.db")
        try:
            ingest_fixture(db, self.bundle, self.workspace)
        finally:
            db.close()

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        original_get = os.environ.get

        def guarded_get(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                raise AssertionError("must not read key")
            return original_get(name, default)

        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                "market_intel.cli.os.environ.get", side_effect=guarded_get), patch(
                "market_intel.cli.connect", side_effect=AssertionError("must not open mutating store")), patch(
                "market_intel.cli.ModelClient", side_effect=AssertionError("must not call model")), patch(
                "socket.create_connection", side_effect=AssertionError("must not use network")):
            code = main(list(map(str, args)))
        text = stdout.getvalue() or stderr.getvalue()
        for value in (self.bundle["event"]["title"], self.bundle["raw"]["normalized_text"], "https://"):
            self.assertNotIn(value, text)
        return code, json.loads(text)

    def freeze(self, destination, *args):
        return self.invoke("freeze-evidence-candidates", "--workspace", self.workspace,
                           "--cutoff", "2026-11-07T00:00:00Z", "--destination", destination, *args)

    def state(self):
        return {p.relative_to(self.workspace).as_posix(): p.read_bytes()
                for p in self.workspace.rglob("*") if p.is_file()}

    def test_explicit_synthetic_full_flow_and_offline_verification(self):
        before = self.state()
        frozen, replay = self.root / "frozen", self.root / "replay"
        code, result = self.freeze(frozen, "--include-synthetic")
        self.assertEqual((code, result["status"], result["selected_count"]), (0, "frozen", 1))
        manifest = frozen / "candidate-manifest.json"
        code, result = self.invoke("verify-evidence-candidates", "--workspace", self.workspace, "--manifest", manifest)
        self.assertEqual((code, result["status"], result["data_status"]), (0, "verified_inputs", "synthetic"))
        code, result = self.invoke("replay-evidence-candidates", "--workspace", self.workspace,
                                   "--manifest", manifest, "--destination", replay)
        self.assertEqual((code, result["status"]), (0, "replayed"))
        self.assertEqual(before, self.state())
        self.workspace.rename(self.root / "unavailable")
        code, result = self.invoke("verify-candidate-replay", "--replay", replay)
        self.assertEqual((code, result["status"], result["selected_count"]), (0, "verified_replay", 1))
        self.assertFalse(result["model_called"])
        self.assertFalse(result["content_support_reviewed"])

    def test_default_empty_freeze_verify_replay_success(self):
        frozen, replay = self.root / "empty", self.root / "empty-replay"
        self.assertEqual(self.freeze(frozen)[1]["selected_count"], 0)
        manifest = frozen / "candidate-manifest.json"
        self.assertEqual(self.invoke("verify-evidence-candidates", "--workspace", self.workspace,
                                     "--manifest", manifest)[1]["data_status"], "empty")
        self.assertEqual(self.invoke("replay-evidence-candidates", "--workspace", self.workspace,
                                     "--manifest", manifest, "--destination", replay)[0], 0)
        self.assertEqual(self.invoke("verify-candidate-replay", "--replay", replay)[1]["selected_count"], 0)

    def test_invalid_input_and_existing_destination_fail_without_overwriting(self):
        target = self.root / "new-parent" / "invalid"
        self.assertEqual(self.freeze(target, "--max-candidates", 101)[0], 1)
        self.assertFalse(target.parent.exists())
        target = self.root / "existing"
        target.mkdir()
        (target / "keep").write_text("unchanged", encoding="utf-8")
        self.assertEqual(self.freeze(target)[0], 1)
        self.assertEqual((target / "keep").read_text(), "unchanged")
        secret = self.root / "secret-marker-manifest.json"
        secret.write_text('{"untrusted":"sensitive-body-marker"}', encoding="utf-8")
        code, result = self.invoke("verify-evidence-candidates", "--workspace", self.workspace, "--manifest", secret)
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertNotIn("secret-marker", json.dumps(result))
        self.assertNotIn("sensitive-body-marker", json.dumps(result))

    def test_tampered_replay_and_missing_source_reject(self):
        frozen, replay = self.root / "frozen", self.root / "replay"
        self.freeze(frozen, "--include-synthetic")
        manifest = frozen / "candidate-manifest.json"
        self.invoke("replay-evidence-candidates", "--workspace", self.workspace,
                    "--manifest", manifest, "--destination", replay)
        (replay / "extra").write_text("unexpected", encoding="utf-8")
        self.assertEqual(self.invoke("verify-candidate-replay", "--replay", replay)[0], 1)
        self.workspace.rename(self.root / "unavailable")
        self.assertEqual(self.invoke("verify-evidence-candidates", "--workspace", self.workspace,
                                     "--manifest", manifest)[0], 1)


if __name__ == "__main__":
    unittest.main()
