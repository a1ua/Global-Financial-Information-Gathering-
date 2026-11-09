from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.ops import audit_journal as audit
from market_intel.ops.audit_journal import append_observation, verify_audit_journal


def observation(number=0, *, ledger="a"):
    return {"schema_version": "ledger-audit-observation/0.1", "statement_sha256": f"{number:064x}",
            "evidence_sha256": "0" * 64,
            "preview": {"schema_version": "ledger-reconciliation-preview/0.1", "status": "matched_estimates",
                        "ledger_id": "ledger_" + ledger * 32, "utc_day": "2026-11-09", "currency": "CNY",
                        "provider": "mock", "evidence_kind": "synthetic", "read_only": True,
                        "evidence_authenticated": False, "settlement_allowed": False,
                        "local_calls": 1, "statement_records": 1, "missing_records": 0,
                        "pending_calls": 0, "difference_records": 0,
                        "local_estimated_micro_units": 104, "statement_micro_units": 104,
                        "delta_micro_units": 0}}


class AuditJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "journal" / "audit.db"

    def tearDown(self):
        self.temp.cleanup()

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM audit_events ORDER BY seq")]

    def mutate(self, column, value):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TRIGGER audit_events_no_update")
            db.execute(f"UPDATE audit_events SET {column}=? WHERE seq=1", (value,))
            db.execute(audit._TRIGGERS["audit_events_no_update"])

    def test_record_deduplicate_and_verify_without_authenticity(self):
        first = append_observation(self.path, observation())
        before = self.path.read_bytes()
        second = append_observation(self.path, observation())
        self.assertEqual((first["status"], second["status"]), ("recorded", "already_recorded"))
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual((first["seq"], second["events"]), (1, 1))
        verified = verify_audit_journal(self.path)
        self.assertEqual(verified["status"], "verified_local_chain")
        self.assertEqual(self.path.read_bytes(), before)
        for result in (first, second, verified):
            for key in ("trusted_high_water", "settlement_allowed", "switch_allowed"):
                self.assertIs(result[key], False)
        row = self.rows()[0]
        material = {key: value for key, value in row.items() if key != "event_sha256"}
        canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), row["event_sha256"])

    def test_changed_observation_and_multiple_ledgers_share_global_sequence(self):
        a = append_observation(self.path, observation())
        value = observation()
        value["preview"].update(status="incomplete", pending_calls=1)
        b = append_observation(self.path, value)
        c = append_observation(self.path, observation(1, ledger="b"))
        self.assertEqual([a["seq"], b["seq"], c["seq"]], [1, 2, 3])
        self.assertEqual(self.rows()[1]["previous_sha256"], a["event_sha256"])
        self.assertEqual(verify_audit_journal(self.path)["events"], 3)

    def test_sql_update_delete_and_replace_cannot_change_history(self):
        append_observation(self.path, observation())
        before = self.rows()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA recursive_triggers=OFF")
            for sql in ("UPDATE audit_events SET recorded_at='private text'", "DELETE FROM audit_events"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
                db.rollback()
            for command in ("INSERT OR REPLACE", "REPLACE"):
                for unique in ("seq", "event_id", "observation_key", "event_sha256"):
                    row = dict(before[0])
                    row.update(seq=2, event_id="audit_" + "b" * 32, observation_key="c" * 64,
                               event_sha256="d" * 64, previous_sha256=before[0]["event_sha256"])
                    row[unique] = before[0][unique]
                    with self.subTest(command=command, unique=unique), self.assertRaises(sqlite3.IntegrityError):
                        db.execute(command + " INTO audit_events VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
                    db.rollback()
        self.assertEqual(self.rows(), before)
        self.assertEqual(verify_audit_journal(self.path)["events"], 1)

    def test_missing_or_replaced_protective_trigger_is_rejected(self):
        append_observation(self.path, observation())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TRIGGER audit_events_no_delete")
            db.execute("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT 1; END")
        for operation in (lambda: verify_audit_journal(self.path), lambda: append_observation(self.path, observation())):
            with self.assertRaisesRegex(ValueError, "^audit_journal_schema_invalid$"):
                operation()

    def test_tampering_is_detected_before_idempotency_lookup(self):
        append_observation(self.path, observation())
        self.mutate("event_sha256", "f" * 64)
        with self.assertRaisesRegex(ValueError, "^audit_journal_chain_invalid$"):
            append_observation(self.path, observation())

    def test_bad_payload_and_noncanonical_payload_are_rejected(self):
        append_observation(self.path, observation())
        original = self.rows()[0]["payload"]
        for payload in ('{"private":"sensitive', original + " ", original.replace('"read_only":true', '"read_only":1')):
            self.mutate("payload", payload)
            with self.subTest(payload=payload[:16]), self.assertRaisesRegex(ValueError, "^audit_journal_(payload|chain)_invalid$"):
                verify_audit_journal(self.path)

    def test_wrong_key_identity_previous_hash_and_time_are_rejected(self):
        append_observation(self.path, observation())
        original = self.rows()[0]
        for column, value in (("observation_key", "f" * 64), ("ledger_id", "ledger_" + "b" * 32),
                              ("previous_sha256", "e" * 64), ("recorded_at", "2026-11-09T10:00:00+00:00")):
            self.mutate(column, value)
            with self.subTest(column=column), self.assertRaisesRegex(ValueError, "^audit_journal_(chain|time)_invalid$"):
                verify_audit_journal(self.path)
            self.mutate(column, original[column])

    def test_clock_regression_rejects_new_append_but_duplicate_needs_no_clock(self):
        with patch.object(audit, "_now", return_value="2070-01-01T00:00:00Z"):
            append_observation(self.path, observation())
        with patch.object(audit, "_now", return_value="2069-12-31T23:59:59Z"):
            with self.assertRaisesRegex(ValueError, "^audit_journal_clock_regression$"):
                append_observation(self.path, observation(1))
        with patch.object(audit, "_now", side_effect=AssertionError("duplicate must not use clock")):
            self.assertEqual(append_observation(self.path, observation())["status"], "already_recorded")
        self.assertEqual(len(self.rows()), 1)

    def test_parallel_append_and_duplicate_are_serialized(self):
        append_observation(self.path, observation())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: append_observation(self.path, observation(n)), [1, 2, 3, 4, 1, 2, 3, 4]))
        self.assertEqual(sum(r["status"] == "recorded" for r in results), 4)
        self.assertEqual(verify_audit_journal(self.path)["events"], 5)
        self.assertEqual([r["seq"] for r in self.rows()], list(range(1, 6)))

    def test_verify_missing_does_not_create_and_existing_empty_is_not_initialized(self):
        with self.assertRaisesRegex(ValueError, "^audit_journal_missing$"):
            verify_audit_journal(self.path)
        self.assertFalse(self.path.parent.exists())
        self.path.parent.mkdir()
        self.path.touch()
        with self.assertRaisesRegex(ValueError, "^audit_journal_schema_invalid$"):
            append_observation(self.path, observation())
        self.assertEqual(self.path.read_bytes(), b"")

    def test_unknown_schema_and_corrupt_file_are_not_overwritten(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"private corrupt database")
        before = self.path.read_bytes()
        for fn in (lambda: append_observation(self.path, observation()), lambda: verify_audit_journal(self.path)):
            with self.assertRaisesRegex(ValueError, "^audit_journal_database_error$"):
                fn()
        self.assertEqual(self.path.read_bytes(), before)

    def test_capacity_boundaries_and_contradictory_preview(self):
        value = observation()
        value["preview"].update(local_calls=10**7, statement_records=10**7,
                                local_estimated_micro_units=10**19, statement_micro_units=10**19)
        self.assertEqual(append_observation(self.path, value)["status"], "recorded")
        for changes in ({"local_calls": 10**7 + 1}, {"local_estimated_micro_units": 10**19 + 1},
                        {"local_calls": True}, {"statement_micro_units": -1}, {"pending_calls": 2 * 10**7},
                        {"difference_records": -1}, {"read_only": 1}, {"evidence_authenticated": True},
                        {"settlement_allowed": True}, {"utc_day": "2026-11-09T00:00:00Z"},
                        {"delta_micro_units": 1}, {"status": "verified"}):
            bad = deepcopy(value)
            bad["preview"].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "^audit_observation_invalid$"):
                append_observation(self.path, bad)
        bad = observation()
        bad["preview"].update(statement_micro_units=105, delta_micro_units=1)
        with self.assertRaisesRegex(ValueError, "^audit_observation_invalid$"):
            append_observation(self.path, bad)

    def test_zero_counts_require_zero_totals_and_strict_fields(self):
        value = observation()
        value["preview"].update(local_calls=0, statement_records=0, local_estimated_micro_units=0, statement_micro_units=0)
        self.assertEqual(append_observation(self.path, value)["status"], "recorded")
        cases = []
        extra = observation(); extra["secret"] = "synthetic-private-text"; cases.append(extra)
        extra = observation(); extra["preview"]["extra"] = 1; cases.append(extra)
        extra = observation(); extra["statement_sha256"] = "not a hash"; cases.append(extra)
        extra = deepcopy(value); extra["preview"].update(local_estimated_micro_units=1, statement_micro_units=1); cases.append(extra)
        for bad in cases:
            with self.assertRaisesRegex(ValueError, "^audit_observation_invalid$"):
                append_observation(self.path, bad)

    def test_valid_partial_and_offsetting_difference_observations(self):
        value = observation()
        value["preview"].update(local_calls=2, missing_records=1, status="incomplete",
                                local_estimated_micro_units=208, delta_micro_units=-104)
        append_observation(self.path, value)
        value["preview"].update(statement_records=2, missing_records=0, difference_records=2,
                                statement_micro_units=208, delta_micro_units=0, status="differences")
        self.assertEqual(append_observation(self.path, value)["seq"], 2)

    def test_full_old_chain_rollback_cannot_be_detected_without_external_anchor(self):
        append_observation(self.path, observation())
        old = self.root / "old.db"
        shutil.copyfile(self.path, old)
        append_observation(self.path, observation(1))
        self.assertEqual(verify_audit_journal(self.path)["events"], 2)
        shutil.copyfile(old, self.path)
        result = verify_audit_journal(self.path)
        self.assertEqual((result["status"], result["events"]), ("verified_local_chain", 1))
        self.assertFalse(result["trusted_high_water"])
        self.assertFalse(result["switch_allowed"])

    def test_database_busy_and_private_errors_are_fixed_codes(self):
        append_observation(self.path, observation())
        with patch.object(audit.sqlite3, "connect", side_effect=sqlite3.OperationalError("private sql content")):
            with self.assertRaisesRegex(ValueError, "^audit_journal_database_error$"):
                verify_audit_journal(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(ValueError, "^audit_journal_busy$"):
                append_observation(self.path, observation(1))
            db.rollback()

    def test_symbolic_ancestor_is_rejected_before_creation(self):
        with patch.object(audit, "_linked", side_effect=lambda p: p == self.path.parent):
            with self.assertRaisesRegex(ValueError, "^audit_journal_link_forbidden$"):
                append_observation(self.path, observation())
        self.assertFalse(self.path.parent.exists())


if __name__ == "__main__":
    unittest.main()
