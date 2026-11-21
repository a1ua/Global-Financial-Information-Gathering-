import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from market_intel.ops.market_replay import create_market_replay, verify_market_replay
from test_market_snapshot import CUTOFF, END, INSTRUMENT, START, calendar, version


class MarketReplayTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.source = self.root / "source.json"
        self.destination = self.root / "replay"
        self.artifact = self.destination / "market-replay.json"
        self.active = version()
        self.future = version(available="2026-10-09T08:00:01Z")
        self.input = {
            "calendar_source": calendar(),
            "instrument_id": INSTRUMENT,
            "bars": [self.future, self.active],
            "cutoff": CUTOFF,
            "start_date": START,
            "end_date": END,
        }
        self.write_json(self.source, self.input)

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_replay_only_copies_selected_versions_and_survives_source_removal(self):
        original_source = self.source.read_bytes()
        created = create_market_replay(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), original_source)
        original_artifact = self.artifact.read_bytes()
        replay = json.loads(original_artifact)
        self.assertEqual(replay["bars"], [self.active])
        self.assertEqual(replay["snapshot"]["missing_sessions"], ["2026-10-09"])
        self.assertEqual(replay["calendar_source"], self.input["calendar_source"])
        self.source.unlink()
        verified = verify_market_replay(self.destination)
        self.assertEqual(verified, {
            "schema_version": "synthetic-market-replay-info/0.1",
            "status": "verified",
            "snapshot_sha256": created["snapshot_sha256"],
            "selected_count": 1,
            "missing_count": 1,
            "is_synthetic": True,
        })
        self.assertEqual(self.artifact.read_bytes(), original_artifact)

    def test_tampered_unselected_and_duplicate_rows_rejected(self):
        create_market_replay(self.source, self.destination)
        original = self.artifact.read_bytes()
        changed = {**self.active, "bar": {**self.active["bar"], "close": "3"}}
        for rows in ([changed], [], [self.active, self.future], [self.active, self.active]):
            with self.subTest(rows=rows):
                payload = json.loads(original)
                payload["bars"] = rows
                self.write_json(self.artifact, payload)
                with self.assertRaisesRegex(ValueError, "^market_replay_invalid$"):
                    verify_market_replay(self.destination)

    def test_partial_directory_and_extra_file_are_rejected(self):
        self.destination.mkdir()
        with self.assertRaisesRegex(ValueError, "^market_replay_invalid$"):
            verify_market_replay(self.destination)
        second = self.root / "new-replay"
        create_market_replay(self.source, second)
        (second / "unexpected.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "^market_replay_invalid$"):
            verify_market_replay(second)

    def test_invalid_input_rejected_before_creating_parents(self):
        destination = self.root / "new-parent" / "replay"
        with self.subTest("unknown key"):
            self.write_json(self.source, {**self.input, "extra": None})
            with self.assertRaisesRegex(ValueError, "^market_replay_invalid$"):
                create_market_replay(self.source, destination)
        with self.subTest("duplicate key"):
            self.source.write_bytes(b'{"calendar_source":0,"calendar_source":1}')
            with self.assertRaisesRegex(ValueError, "^market_replay_invalid$"):
                create_market_replay(self.source, destination)
        with self.subTest("byte limit"):
            self.source.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "^market_replay_invalid$"):
                create_market_replay(self.source, destination)
        self.assertFalse(destination.parent.exists())

    def test_cannot_replace_existing_destination(self):
        create_market_replay(self.source, self.destination)
        original = self.artifact.read_bytes()
        with self.assertRaisesRegex(ValueError, "^market_replay_destination_exists$"):
            create_market_replay(self.source, self.destination)
        self.assertEqual(self.artifact.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
