from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelError


class IdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.db"

    def tearDown(self):
        self.temp.cleanup()

    def test_identity_is_stable_and_creation_does_not_consume_budget_clock(self):
        def forbidden_clock():
            raise AssertionError("creation must use real UTC")
        client = ModelClient(self.path, clock=forbidden_clock)
        self.assertEqual(client.ledger_id, ModelClient(self.path).ledger_id)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_existing_instance_rejects_deleted_database_without_recreating_it(self):
        client = ModelClient(self.path)
        self.path.unlink()
        with self.assertRaisesRegex(ModelError, "bound_ledger_missing"):
            client.usage("2026-11-08")
        self.assertFalse(self.path.exists())

    def test_existing_instance_rejects_replaced_valid_database(self):
        client = ModelClient(self.path)
        other_path = self.path.with_name("other.db")
        other = ModelClient(other_path)
        other_path.replace(self.path)
        with self.assertRaisesRegex(ModelError, "ledger_identity_mismatch"):
            client.usage("2026-11-08")
        self.assertEqual(ModelClient(self.path).ledger_id, other.ledger_id)

    def test_invalid_identity_is_not_repaired(self):
        ModelClient(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM ledger_identity")
        with self.assertRaisesRegex(ModelError, "ledger_identity_invalid"):
            ModelClient(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_identity").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
