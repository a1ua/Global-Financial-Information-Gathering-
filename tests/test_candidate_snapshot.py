import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.contracts.candidate_snapshot import payload_sha256
from market_intel.pipeline import candidate_snapshot as module
from market_intel.pipeline.evidence_candidates import plan_evidence_candidates
from market_intel.store import connect, insert_immutable
from test_evidence_candidates import fixture, CUTOFF


class CandidateSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "market.db")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, bundle, receipt=None):
        with self.db:
            for key, table, identity in (("raw", "raw_items", "raw_item_id"),
                                         ("event", "event_versions", "event_version_id"),
                                         ("evidence", "evidence", "evidence_id")):
                insert_immutable(self.db, table, identity, bundle[key])
            if receipt is not None:
                self.db.execute("INSERT INTO availability_receipts VALUES(?,?)",
                                (bundle["event"]["event_version_id"], receipt))
        path = self.root / bundle["raw"]["content_ref"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bundle["raw"]["normalized_text"].encode("utf-8"))

    def freeze(self, **kwargs):
        result = plan_evidence_candidates(self.root, CUTOFF, **kwargs)
        return {"schema_version": "evidence-candidate-snapshot/0.1",
                "input_manifest": result["input_manifest"],
                "input_manifest_sha256": result["input_manifest_sha256"]}

    def load(self, snapshot):
        return module.load_candidate_snapshot_inputs(self.root, snapshot)

    def mutate(self, table, key, payload):
        with self.db:
            self.db.execute("DROP TRIGGER IF EXISTS " + table + "_no_update")
            self.db.execute("UPDATE " + table + " SET payload=? WHERE id=?", (payload, key))

    def test_exact_old_input_survives_new_version_and_backfill(self):
        original = fixture("a", event_id="shared")
        self.add(original)
        snapshot = self.freeze(include_synthetic=True)
        self.add(fixture("new", 2, "shared", "2026-11-09T01:00:00Z"))
        self.add(fixture("backfill", at="2026-11-09T00:00:00Z"))
        fresh = self.freeze(include_synthetic=True)
        self.assertNotEqual(snapshot["input_manifest_sha256"], fresh["input_manifest_sha256"])
        with patch("market_intel.pipeline.evidence_candidates.plan_evidence_candidates", side_effect=AssertionError), \
             patch("market_intel.pipeline.evidence_candidates._bundles", side_effect=AssertionError):
            loaded = self.load(snapshot)
        self.assertEqual(loaded["bundles"][0], {**original, "receipt_committed_at": None})
        self.assertEqual(loaded["verification"]["input_manifest_sha256"], snapshot["input_manifest_sha256"])

    def test_unrelated_bad_payload_is_not_parsed(self):
        self.add(fixture("a"))
        snapshot = self.freeze(include_synthetic=True)
        bad = fixture("unrelated")
        self.add(bad)
        # Structurally invalid JSON object while SQLite's JSON-based index stays valid.
        self.mutate("event_versions", bad["event"]["event_version_id"],
                    json.dumps({"event_version_id": "unrelated", "private": "do-not-echo"}))
        self.assertEqual(self.load(snapshot)["verification"]["selected_count"], 1)

    def test_real_receipt_string_is_exact_not_just_equal_instant(self):
        self.add(fixture(synthetic=False), "2026-11-09T00:00:01Z")
        snapshot = self.freeze()
        self.assertEqual(self.load(snapshot)["bundles"][0]["receipt_committed_at"], "2026-11-09T00:00:01Z")
        with self.db:
            self.db.execute("DROP TRIGGER receipts_no_update")
            self.db.execute("UPDATE availability_receipts SET committed_at='2026-11-09T00:00:01.000000Z'")
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_descriptor_mismatch$"):
            self.load(snapshot)

    def test_real_missing_and_invalid_receipt_reject(self):
        self.add(fixture(synthetic=False), "2026-11-09T00:00:01Z")
        snapshot = self.freeze()
        with self.db:
            self.db.execute("DROP TRIGGER receipts_no_delete")
            self.db.execute("DELETE FROM availability_receipts")
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_receipt_missing$"):
            self.load(snapshot)
        with self.db:
            self.db.execute("INSERT INTO availability_receipts VALUES('event_a_1','invalid-private-value')")
        with self.assertRaises(ValueError) as caught:
            self.load(snapshot)
        self.assertNotIn("private", str(caught.exception))

    def test_synthetic_ignores_receipt_and_checks_latest_object_time(self):
        bundle = fixture()
        bundle["evidence"]["available_at"] = "2026-11-09T01:00:00Z"
        self.add(bundle, "invalid-private-receipt")
        snapshot = self.freeze(include_synthetic=True)
        result = self.load(snapshot)
        self.assertIsNone(result["bundles"][0]["receipt_committed_at"])
        self.assertEqual(snapshot["input_manifest"]["candidates"][0]["effective_available_at"],
                         "2026-11-09T01:00:00.000000Z")

    def test_exact_selected_payload_hash_change_rejects(self):
        self.add(fixture())
        snapshot = self.freeze(include_synthetic=True)
        for table, key, record in (("raw_items", "raw_a_1", "raw"),
                                   ("event_versions", "event_a_1", "event"),
                                   ("evidence", "evidence_a_1", "evidence")):
            original = fixture()[record]
            altered = copy.deepcopy(original)
            field = "source_item_key" if record == "raw" else "title" if record == "event" else "claim_key"
            altered[field] = "changed"
            self.mutate(table, key, json.dumps(altered))
            with self.subTest(table=table), self.assertRaises(ValueError):
                self.load(snapshot)
            self.mutate(table, key, json.dumps(original))

    def test_selected_duplicate_json_keys_reject_without_private_values(self):
        self.add(fixture())
        snapshot = self.freeze(include_synthetic=True)
        payload = json.dumps(fixture()["raw"])
        self.mutate("raw_items", "raw_a_1", payload[:-1] + ',"title":"do-not-echo-private"}')
        with self.assertRaises(ValueError) as caught:
            self.load(snapshot)
        self.assertNotIn("private", str(caught.exception))

    def test_fk_columns_match_descriptor_even_with_valid_fk_targets(self):
        self.add(fixture("a"))
        self.add(fixture("b"))
        snapshot = self.freeze(include_synthetic=True, max_candidates=1)
        with self.db:
            self.db.execute("DROP TRIGGER evidence_no_update")
            self.db.execute("UPDATE evidence SET raw_item_id='raw_b_1' WHERE id='evidence_a_1'")
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_identity_invalid$"):
            self.load(snapshot)

    def test_global_foreign_key_failure_rejects_even_empty_snapshot(self):
        snapshot = self.freeze()
        self.db.execute("PRAGMA foreign_keys=OFF")
        with self.db:
            self.db.execute("INSERT INTO availability_receipts VALUES('missing','2026-11-09T00:00:01Z')")
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_foreign_keys_invalid$"):
            self.load(snapshot)

    def test_metadata_summary_and_empty_mixed_labels(self):
        empty = self.load(self.freeze())["verification"]
        self.assertEqual((empty["data_status"], empty["is_synthetic"], empty["mixed_test_data"]), ("empty", False, False))
        self.add(fixture("a"))
        self.add(fixture("b", synthetic=False), "2026-11-09T00:00:01Z")
        snapshot = self.freeze(include_synthetic=True)
        summary = module.verify_candidate_snapshot(self.root, snapshot)
        self.assertEqual((summary["data_status"], summary["is_synthetic"], summary["mixed_test_data"]), ("mixed", False, True))
        for forbidden in ("Synthetic evidence", "https://", "bundles", "normalized_text"):
            self.assertNotIn(forbidden, json.dumps(summary))
        self.assertFalse(summary["model_called"])
        self.assertFalse(summary["content_support_reviewed"])

    def test_invalid_snapshot_checked_before_opening_database(self):
        snapshot = self.freeze()
        snapshot["input_manifest_sha256"] = "0" * 64
        with patch.object(module.sqlite3, "connect", side_effect=AssertionError), self.assertRaises(ValueError):
            self.load(snapshot)

    def test_selected_missing_reference_rejects_without_fallback(self):
        self.add(fixture())
        snapshot = self.freeze(include_synthetic=True)
        snapshot["input_manifest"]["candidates"][0]["event_version_id"] = "not_present"
        snapshot["input_manifest_sha256"] = payload_sha256(snapshot["input_manifest"])
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_reference_missing$"):
            self.load(snapshot)

    def test_private_io_error_is_sanitized(self):
        self.add(fixture())
        snapshot = self.freeze(include_synthetic=True)
        with patch.object(module, "_file", side_effect=OSError("private-path-and-content")), \
             self.assertRaisesRegex(ValueError, "^candidate_snapshot_io_error$"):
            self.load(snapshot)

    def test_single_transaction_query_only_and_static_hashes(self):
        self.add(fixture())
        snapshot = self.freeze(include_synthetic=True)
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        original = module._load
        observed = []
        def inspect(db, *args):
            observed.append((db.in_transaction, db.execute("PRAGMA query_only").fetchone()[0]))
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM capture_sources")
            return original(db, *args)
        with patch.object(module, "_load", side_effect=inspect):
            self.load(snapshot)
        self.assertEqual(observed, [(True, 1)])
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_wal_commit_does_not_change_pinned_selected_payload(self):
        self.db.execute("PRAGMA journal_mode=WAL")
        self.add(fixture())
        snapshot = self.freeze(include_synthetic=True)
        original = module._payload
        changed = False
        def replace_after_read(db, table, key, identity):
            nonlocal changed
            result = original(db, table, key, identity)
            if not changed:
                changed = True
                altered = fixture()["raw"]
                altered["source_item_key"] = "changed-after-pinned-read"
                self.mutate("raw_items", "raw_a_1", json.dumps(altered))
            return result
        with patch.object(module, "_payload", side_effect=replace_after_read):
            self.assertEqual(self.load(snapshot)["verification"]["selected_count"], 1)
        with self.assertRaises(ValueError):
            self.load(snapshot)

    def test_missing_content_bad_bytes_and_file_link_reject(self):
        bundle = fixture()
        self.add(bundle)
        snapshot = self.freeze(include_synthetic=True)
        path = self.root / bundle["raw"]["content_ref"]
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_content_invalid$"):
            self.load(snapshot)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_file_invalid$"):
            self.load(snapshot)
        path.write_bytes(bundle["raw"]["normalized_text"].encode())
        with patch("market_intel.ops.backup._linked", side_effect=lambda p: p == path), \
             self.assertRaisesRegex(ValueError, "^candidate_snapshot_file_invalid$"):
            self.load(snapshot)

    def test_schema_missing_workspace_and_private_io_errors(self):
        missing = self.root / "missing"
        with self.assertRaises(ValueError):
            module.verify_candidate_snapshot(missing, self.freeze())
        self.assertFalse(missing.exists())
        with self.db:
            self.db.execute("PRAGMA user_version=3")
        with self.assertRaisesRegex(ValueError, "^candidate_snapshot_schema_unsupported$"):
            self.load(self.freeze_from_empty())
        with patch.object(module.sqlite3, "connect", side_effect=sqlite3.OperationalError("private-value")), \
             self.assertRaisesRegex(ValueError, "^candidate_snapshot_database_error$"):
            self.load(self.freeze_from_empty())

    def freeze_from_empty(self):
        manifest = {"schema_version": "evidence-candidate-input/0.1", "selection_version": "latest-available/0.1",
                    "cutoff": CUTOFF, "max_candidates": 5, "include_synthetic": False, "candidates": []}
        return {"schema_version": "evidence-candidate-snapshot/0.1", "input_manifest": manifest,
                "input_manifest_sha256": payload_sha256(manifest)}


if __name__ == "__main__":
    unittest.main()
