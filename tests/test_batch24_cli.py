from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main


class MarketReplayCLITests(unittest.TestCase):
    def test_verify_after_original_input_is_moved(self):
        example = Path(__file__).resolve().parents[1] / "config" / "market-replay.synthetic.example.json"
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "source.json"
            target = folder / "replay"
            shutil.copyfile(example, source)
            output = StringIO()
            with (redirect_stdout(output),
                  patch("market_intel.cli.connect", side_effect=AssertionError("unexpected database")),
                  patch("socket.create_connection", side_effect=AssertionError("unexpected network"))):
                code = main(["create-synthetic-market-replay", "--input", str(source),
                             "--destination", str(target)])
                self.assertEqual(code, 0)
                source.rename(folder / "moved.json")
                code = main(["verify-synthetic-market-replay", "--replay", str(target)])
                self.assertEqual(code, 0)
            created, verified = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual((created["status"], verified["status"]), ("created", "verified"))
            self.assertEqual(created["snapshot_sha256"], verified["snapshot_sha256"])
            self.assertEqual((verified["selected_count"], verified["missing_count"]), (1, 1))
