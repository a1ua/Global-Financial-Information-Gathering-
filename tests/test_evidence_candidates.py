import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.pipeline import evidence_candidates as module
from market_intel.pipeline.evidence_candidates import plan_evidence_candidates
from market_intel.store import connect, insert_immutable


CUTOFF = "2026-11-09T12:00:00Z"


def fixture(key="a", version=1, event_id=None, at="2026-11-09T00:00:00Z", synthetic=True):
    bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
    raw, event, evidence = (bundle[k] for k in ("raw", "event", "evidence"))
    text = f"Synthetic evidence {key} version {version}."
    raw.update(raw_item_id=f"raw_{key}_{version}", source_item_key=f"synthetic-{key}-{version}",
               title=f"Synthetic {key}", normalized_text=text,
               content_sha256=hashlib.sha256(text.encode()).hexdigest(), is_synthetic=synthetic)
    raw["content_ref"] = f"raw/{raw['content_sha256']}.txt"
    for field in ("first_seen_at", "fetched_at", "persisted_at", "available_at"):
        raw[field] = at
    event.update(event_id=event_id or f"event_{key}", event_version_id=f"event_{key}_{version}",
                 version=version, title=f"Synthetic event {key}", fact_summary=text,
                 input_raw_item_ids=[raw["raw_item_id"]], evidence_ids=[f"evidence_{key}_{version}"],
                 processed_at=at, available_at=at, is_synthetic=synthetic)
    evidence.update(evidence_id=f"evidence_{key}_{version}", event_version_id=event["event_version_id"],
                    raw_item_id=raw["raw_item_id"], quote=text, available_at=at, is_synthetic=synthetic)
    evidence["locator"]["start"], evidence["locator"]["end"] = 0, len(text)
    if not synthetic:
        raw["storage_policy"] = "full_text"
        event.update(extraction_method="rule", extraction_quality="structurally_valid")
    return bundle


class EvidenceCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "market.db")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, bundle, receipt=None, file=True):
        with self.db:
            for key, table, identity in (("raw", "raw_items", "raw_item_id"),
                                         ("event", "event_versions", "event_version_id"),
                                         ("evidence", "evidence", "evidence_id")):
                insert_immutable(self.db, table, identity, bundle[key])
            if receipt is not None:
                self.db.execute("INSERT INTO availability_receipts VALUES(?,?)",
                                (bundle["event"]["event_version_id"], receipt))
        if file:
            path = self.root / bundle["raw"]["content_ref"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bundle["raw"]["normalized_text"].encode("utf-8"))

    def plan(self, **kwargs):
        return plan_evidence_candidates(self.root, kwargs.pop("cutoff", CUTOFF), **kwargs)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_default_excludes_synthetic_and_explicit_manifest_has_no_text(self):
        bundle = fixture()
        self.add(bundle)
        excluded = self.plan()
        self.assertEqual((excluded["selected_count"], excluded["excluded_synthetic_count"], excluded["data_status"]),
                         (0, 1, "empty"))
        result = self.plan(include_synthetic=True)
        self.assertEqual((result["selected_count"], result["data_status"], result["is_synthetic"]), (1, "synthetic", True))
        descriptor = result["input_manifest"]["candidates"][0]
        self.assertIsNone(descriptor["receipt_committed_at"])
        self.assertNotIn("Synthetic evidence", json.dumps(result))
        self.assertNotIn("https://", json.dumps(result))
        canonical = json.dumps(result["input_manifest"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(result["input_manifest_sha256"], hashlib.sha256(canonical.encode()).hexdigest())
        for record in ("raw", "event", "evidence"):
            canonical = json.dumps(bundle[record], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.assertEqual(descriptor[f"{record}_payload_sha256"], hashlib.sha256(canonical.encode()).hexdigest())

    def test_real_labels_require_receipt_and_late_receipt_does_not_release_old_cutoff(self):
        self.add(fixture("missing", synthetic=False))
        self.add(fixture("late", synthetic=False), "2026-11-10T00:00:00Z", file=False)
        result = self.plan()
        self.assertEqual((result["event_versions_count"], result["missing_receipt_count"],
                          result["after_cutoff_count"], result["selected_count"]), (2, 1, 1, 0))

    def test_invalid_early_receipt_rejects_even_at_zero_limit(self):
        self.add(fixture(synthetic=False), "2026-11-08T23:59:59Z")
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_receipt_invalid$"):
            self.plan(max_candidates=0)

    def test_timezone_missing_real_receipt_rejects_and_synthetic_receipt_is_ignored(self):
        self.add(fixture("synthetic"), "not-a-time")
        self.assertIsNone(self.plan(include_synthetic=True)["input_manifest"]["candidates"][0]["receipt_committed_at"])
        self.add(fixture("real", synthetic=False), "2026-11-09T00:00:00")
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_timestamp_invalid$"):
            self.plan()

    def test_future_latest_version_and_append_do_not_change_old_manifest(self):
        self.add(fixture("v1", event_id="event_shared", synthetic=False), "2026-11-09T00:00:01Z")
        before = self.plan()
        future = fixture("v2", 2, "event_shared", "2026-11-10T00:00:00Z", False)
        self.add(future, "2026-11-10T00:00:01Z")
        after = self.plan()
        self.assertEqual(before["input_manifest"], after["input_manifest"])
        self.assertEqual(before["input_manifest_sha256"], after["input_manifest_sha256"])
        self.assertEqual(after["after_cutoff_count"], 1)
        newest = self.plan(cutoff="2026-11-11T00:00:00Z")
        self.assertEqual(newest["input_manifest"]["candidates"][0]["version"], 2)
        self.assertEqual(newest["superseded_count"], 1)

    def test_evidence_time_not_publication_controls_effective_available_time(self):
        bundle = fixture(synthetic=False)
        bundle["evidence"]["available_at"] = "2026-11-09T12:00:00.000001Z"
        self.add(bundle, "2026-11-09T12:00:00.000001Z")
        self.assertEqual(self.plan()["after_cutoff_count"], 1)
        exact = self.plan(cutoff="2026-11-09T12:00:00.000001Z")
        self.assertEqual(exact["selected_count"], 1)
        self.assertEqual(exact["input_manifest"]["candidates"][0]["effective_available_at"],
                         "2026-11-09T12:00:00.000001Z")

    def test_invalid_future_excluded_bundle_is_still_validated_before_limit(self):
        bad = fixture(at="2026-11-10T00:00:00Z")
        bad["evidence"]["quote"] = "synthetic-private-invalid-quote"
        self.add(bad, file=False)
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_bundle_invalid$"):
            self.plan(max_candidates=0)

    def test_files_of_all_latest_candidates_are_verified_before_truncation(self):
        self.add(fixture("a"))
        tail = fixture("z", at="2026-11-09T00:01:00Z")
        self.add(tail)
        (self.root / tail["raw"]["content_ref"]).write_text("corrupt", encoding="utf-8")
        for cap in (0, 1):
            with self.subTest(cap=cap), self.assertRaisesRegex(ValueError, "^evidence_candidate_content_invalid$"):
                self.plan(max_candidates=cap, include_synthetic=True)

    def test_unavailable_raw_files_need_not_be_read(self):
        self.add(fixture("future", at="2026-11-10T00:00:00Z"), file=False)
        self.add(fixture("no_receipt", synthetic=False), file=False)
        result = self.plan(include_synthetic=True)
        self.assertEqual((result["after_cutoff_count"], result["missing_receipt_count"], result["selected_count"]), (1, 1, 0))

    def test_mixed_scope_counts_and_parsed_time_order(self):
        self.add(fixture("z", at="2026-11-09T00:00:00.000001Z", synthetic=False), "2026-11-09T00:00:00.000001Z")
        self.add(fixture("a", at="2026-11-09T00:00:00Z"))
        result = self.plan(include_synthetic=True)
        self.assertEqual((result["data_status"], result["mixed_test_data"], result["is_synthetic"]), ("mixed", True, False))
        self.assertEqual([r["event_id"] for r in result["input_manifest"]["candidates"]], ["event_a", "event_z"])
        limited = self.plan(include_synthetic=True, max_candidates=1)
        self.assertEqual((limited["eligible_events_count"], limited["limited_count"], limited["selected_count"]), (2, 1, 1))

    def test_foreign_key_columns_must_match_payload_even_when_foreign_keys_are_valid(self):
        self.add(fixture("a"))
        self.add(fixture("b"))
        with self.db:
            self.db.execute("DROP TRIGGER evidence_no_update")
            self.db.execute("UPDATE evidence SET raw_item_id='raw_b_1' WHERE id='evidence_a_1'")
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_identity_invalid$"):
            self.plan()

    def test_duplicate_logical_versions_are_rejected(self):
        self.add(fixture("a", event_id="event_shared"))
        with self.db:
            self.db.execute("DROP INDEX event_logical_version")
            self.db.execute("DROP TRIGGER event_versions_no_replace")
        self.add(fixture("b", event_id="event_shared"))
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_version_conflict$"):
            self.plan()

    def test_strict_json_rejects_duplicate_fields_without_echo(self):
        self.add(fixture())
        with self.db:
            self.db.execute("DROP TRIGGER event_versions_no_update")
            payload = self.db.execute("SELECT payload FROM event_versions").fetchone()[0]
            self.db.execute("UPDATE event_versions SET payload=?", (payload[:-1] + ',"title":"synthetic-private"}',))
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_json_invalid$"):
            self.plan()

    def test_readonly_single_transaction_preserves_static_files(self):
        self.add(fixture())
        before = self.snapshot()
        original = module._plan
        observed = []
        def inspect(db, *args):
            observed.append((db.in_transaction, db.execute("PRAGMA query_only").fetchone()[0]))
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM capture_sources")
            return original(db, *args)
        with patch.object(module, "_plan", side_effect=inspect):
            self.plan(include_synthetic=True)
        self.assertEqual(observed, [(True, 1)])
        self.assertEqual(self.snapshot(), before)

    def test_wal_concurrent_append_does_not_change_pinned_snapshot(self):
        self.db.execute("PRAGMA journal_mode=WAL")
        self.add(fixture("a"))
        original = module._bundles
        def append_after_read(db):
            result = original(db)
            self.add(fixture("b"))
            return result
        with patch.object(module, "_bundles", side_effect=append_after_read):
            first = self.plan(include_synthetic=True)
        self.assertEqual(first["event_versions_count"], 1)
        self.assertEqual(self.plan(include_synthetic=True)["event_versions_count"], 2)

    def test_links_invalid_paths_schema_and_arguments_fail_without_creation(self):
        missing = self.root / "missing"
        with self.assertRaises(ValueError):
            plan_evidence_candidates(missing, CUTOFF)
        self.assertFalse(missing.exists())
        for cap in (True, -1, 101):
            with self.subTest(cap=cap), self.assertRaisesRegex(ValueError, "^evidence_candidate_limit_invalid$"):
                self.plan(max_candidates=cap)
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_scope_invalid$"):
            self.plan(include_synthetic=1)
        with patch.object(module, "_linked", side_effect=lambda p: p == self.root.parent):
            with self.assertRaisesRegex(ValueError, "^evidence_candidate_link_forbidden$"):
                self.plan()
        with self.db:
            self.db.execute("PRAGMA user_version=3")
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_schema_unsupported$"):
            self.plan()

    def test_file_missing_escape_link_and_private_errors_are_safe(self):
        bundle = fixture()
        self.add(bundle)
        with patch.object(module, "_file", side_effect=OSError("synthetic-private-path")):
            with self.assertRaisesRegex(ValueError, "^evidence_candidate_io_error$"):
                self.plan(include_synthetic=True)
        raw_path = self.root / bundle["raw"]["content_ref"]
        with patch("market_intel.ops.backup._linked", side_effect=lambda p: p == raw_path):
            with self.assertRaisesRegex(ValueError, "^evidence_candidate_file_invalid$"):
                self.plan(include_synthetic=True)
        raw_path.unlink()
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_file_invalid$"):
            self.plan(include_synthetic=True)
        with patch.object(module.sqlite3, "connect", side_effect=sqlite3.OperationalError("synthetic-private")):
            with self.assertRaisesRegex(ValueError, "^evidence_candidate_database_error$"):
                self.plan()

    def test_content_reference_escape_is_rejected_before_file_access(self):
        bad = fixture()
        bad["raw"]["content_ref"] = "../synthetic-private.txt"
        self.add(bad, file=False)
        with self.assertRaisesRegex(ValueError, "^evidence_candidate_bundle_invalid$"):
            self.plan(include_synthetic=True)


if __name__ == "__main__":
    unittest.main()
