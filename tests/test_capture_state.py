import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.pipeline.capture_state import checkpoint, complete, discover, fail, pending


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE raw_items(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE event_versions(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE availability_receipts(event_version_id TEXT PRIMARY KEY REFERENCES event_versions(id),committed_at TEXT NOT NULL);
CREATE TABLE capture_sources(source_id TEXT PRIMARY KEY,last_successful_scan_at TEXT NOT NULL,scan_items INTEGER NOT NULL,consumed_through_queue_id INTEGER,last_completed_at TEXT);
CREATE TABLE capture_observations(source_id TEXT NOT NULL REFERENCES capture_sources(source_id),source_item_key TEXT NOT NULL,last_fingerprint TEXT NOT NULL,observation_no INTEGER NOT NULL,last_observed_at TEXT NOT NULL,PRIMARY KEY(source_id,source_item_key));
CREATE TABLE capture_queue(queue_id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL REFERENCES capture_sources(source_id),source_item_key TEXT NOT NULL,observation_no INTEGER NOT NULL,fingerprint TEXT NOT NULL,item_json TEXT NOT NULL,observed_at TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','done')),attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,event_version_id TEXT REFERENCES event_versions(id),completed_at TEXT,UNIQUE(source_id,source_item_key,observation_no));
CREATE INDEX capture_pending ON capture_queue(source_id,state,queue_id);
"""


def item(key="k1", title="标题A"):
    return {"source_item_key": key, "original_url": "https://example.com/" + key,
            "title": title, "normalized_text": "未经保留许可的正文摘录",
            "source_time_text": "Fri, 06 Nov 2026 08:00:00 GMT",
            "source_published_at": "2026-11-06T08:00:00Z", "source_time_precision": "second",
            "source_timezone": "GMT", "time_parse_status": "parsed"}


T1 = "2026-11-07T00:00:00Z"
T2 = "2026-11-07T00:01:00Z"
T3 = "2026-11-07T00:02:00Z"


class CaptureStateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def tearDown(self):
        self.db.close()

    def event(self, title="标题A", key="k1", source="s1", version=1, receipt=True):
        event_id = "ev_" + source + "_" + key + "_" + str(version)
        raw_id = "raw_" + source + "_" + key + "_" + str(version)
        raw = {"source_id": source, "source_item_key": key, "title": title,
               "normalized_text": title, "storage_policy": "metadata_only", "is_synthetic": False}
        event = {"event_id": "event_" + source + "_" + key, "version": version,
                 "title": title, "fact_summary": title, "input_raw_item_ids": [raw_id], "is_synthetic": False}
        with self.db:
            self.db.execute("INSERT INTO raw_items VALUES (?,?)", (raw_id, json.dumps(raw)))
            self.db.execute("INSERT INTO event_versions VALUES (?,?)", (event_id, json.dumps(event)))
            if receipt:
                self.db.execute("INSERT INTO availability_receipts VALUES (?,?)", (event_id, T1))
        return event_id

    def test_entire_snapshot_queued_before_limited_consumption(self):
        result = discover(self.db, "s1", [item("k" + str(n)) for n in range(8)], T1)
        self.assertEqual(result["discovered"], 8)
        self.assertEqual(len(pending(self.db, "s1", 2)), 2)
        self.assertEqual(checkpoint(self.db, "s1")["pending"], 8)

    def test_metadata_only_persists_title_not_description(self):
        value = item()
        before = copy.deepcopy(value)
        discover(self.db, "s1", [value], T1)
        queued = pending(self.db, "s1", 1)[0]
        self.assertEqual(queued["item"]["normalized_text"], value["title"])
        self.assertNotIn(value["normalized_text"], self.db.execute("SELECT item_json FROM capture_queue").fetchone()[0])
        self.assertEqual(value, before)

    def test_unchanged_full_rescan_does_not_enqueue(self):
        discover(self.db, "s1", [item()], T1)
        result = discover(self.db, "s1", [item()], T2)
        self.assertEqual(result, {"discovered": 0, "unchanged": 1, "scan_items": 1, "duplicates": 0})
        self.assertEqual(checkpoint(self.db, "s1")["pending"], 1)

    def test_exact_snapshot_duplicates_collapse(self):
        result = discover(self.db, "s1", [item(), item()], T1)
        self.assertEqual(result, {"discovered": 1, "unchanged": 0, "scan_items": 2, "duplicates": 1})

    def test_conflicting_titles_in_snapshot_reject_everything(self):
        with self.assertRaisesRegex(ValueError, "conflicting_snapshot_item"):
            discover(self.db, "s1", [item(), item(title="标题B")], T1)
        self.assertIsNone(checkpoint(self.db, "s1")["last_successful_scan_at"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0], 0)

    def test_bad_later_item_leaves_previous_checkpoint(self):
        discover(self.db, "s1", [item()], T1)
        bad = item("k3")
        del bad["source_item_key"]
        before = checkpoint(self.db, "s1")
        with self.assertRaisesRegex(ValueError, "invalid_capture_item_shape"):
            discover(self.db, "s1", [item("k2"), bad], T2)
        self.assertEqual(checkpoint(self.db, "s1"), before)

    def test_unsafe_url_rejected_before_queue_or_checkpoint_changes(self):
        discover(self.db, "s1", [item()], T1)
        before = checkpoint(self.db, "s1")
        for url in ("https://username:password@example.com/private", "http://127.0.0.1/local", "javascript:alert(1)"):
            bad = item("k3")
            bad["original_url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                discover(self.db, "s1", [item("k2"), bad], T2)
            self.assertEqual(checkpoint(self.db, "s1"), before)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0], 1)

    def test_database_failure_rolls_back_whole_discovery(self):
        discover(self.db, "s1", [item()], T1)
        self.db.execute("CREATE TRIGGER reject_bad BEFORE INSERT ON capture_queue WHEN NEW.source_item_key='k3' BEGIN SELECT RAISE(ABORT,'test_failure'); END")
        before = checkpoint(self.db, "s1")
        with self.assertRaises(sqlite3.IntegrityError):
            discover(self.db, "s1", [item("k2"), item("k3")], T2)
        self.assertEqual(checkpoint(self.db, "s1"), before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM capture_observations").fetchone()[0], 1)

    def test_revision_and_reversion_both_queued_in_order(self):
        discover(self.db, "s1", [item()], T1)
        discover(self.db, "s1", [item(title="标题B")], T2)
        discover(self.db, "s1", [item()], T3)
        self.assertEqual(self.db.execute("SELECT observation_no FROM capture_queue ORDER BY queue_id").fetchall(), [(1,), (2,), (3,)])
        for title, version in (("标题A", 1), ("标题B", 2), ("标题A", 3)):
            head = pending(self.db, "s1", 10)
            self.assertEqual(len(head), 1)
            self.assertEqual(head[0]["observation_no"], version)
            complete(self.db, head[0]["queue_id"], self.event(title=title, version=version))
        self.assertEqual(checkpoint(self.db, "s1")["done"], 3)

    def test_failed_head_blocks_only_same_source_item(self):
        discover(self.db, "s1", [item(), item("k2")], T1)
        discover(self.db, "s1", [item(title="标题B")], T2)
        rows = pending(self.db, "s1", 10)
        fail(self.db, rows[0]["queue_id"], "contract_error")
        retry = pending(self.db, "s1", 10)
        self.assertEqual([row["source_item_key"] for row in retry], ["k2", "k1"])
        failed = next(row for row in retry if row["source_item_key"] == "k1")
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(failed["last_error"], "contract_error")
        self.assertEqual(failed["observation_no"], 1)

    def test_limit_one_failure_does_not_starve_healthier_heads_across_runs(self):
        discover(self.db, "s1", [item(), item("k2"), item("k3")], T1)
        failed = pending(self.db, "s1", 1)[0]
        fail(self.db, failed["queue_id"], "persistent_error")
        next_run = pending(self.db, "s1", 1)[0]
        self.assertEqual(next_run["source_item_key"], "k2")
        complete(self.db, next_run["queue_id"], self.event(key="k2"))
        third_run = pending(self.db, "s1", 1)[0]
        self.assertEqual(third_run["source_item_key"], "k3")
        complete(self.db, third_run["queue_id"], self.event(key="k3"))
        self.assertEqual(pending(self.db, "s1", 1)[0]["queue_id"], failed["queue_id"])
        self.assertIsNone(checkpoint(self.db, "s1")["consumed_through_queue_id"])

    def test_attempted_failure_can_be_excluded_without_starving_other_items(self):
        discover(self.db, "s1", [item(), item("k2"), item("k3")], T1)
        discover(self.db, "s1", [item(title="标题B")], T2)
        first = pending(self.db, "s1", 1)[0]
        fail(self.db, first["queue_id"], "contract_error")
        remaining = pending(self.db, "s1", 2, exclude_queue_ids={first["queue_id"]})
        self.assertEqual([row["source_item_key"] for row in remaining], ["k2", "k3"])
        self.assertNotIn(2, [row["observation_no"] for row in remaining])
        complete(self.db, remaining[0]["queue_id"], self.event(key="k2"))
        complete(self.db, remaining[1]["queue_id"], self.event(key="k3"))
        self.assertEqual(checkpoint(self.db, "s1")["pending"], 2)
        self.assertIsNone(checkpoint(self.db, "s1")["consumed_through_queue_id"])
        self.assertEqual(pending(self.db, "s1", 1)[0]["queue_id"], first["queue_id"])

    def test_exclusions_do_not_modify_or_claim_queue(self):
        discover(self.db, "s1", [item(), item("k2")], T1)
        original = pending(self.db, "s1", 2)
        excluded = [row["queue_id"] for row in original]
        before = checkpoint(self.db, "s1")
        self.assertEqual(pending(self.db, "s1", 5, exclude_queue_ids=excluded), [])
        self.assertEqual(checkpoint(self.db, "s1"), before)
        self.assertEqual(original, pending(self.db, "s1", 2))

    def test_complete_requires_committed_receipt(self):
        discover(self.db, "s1", [item()], T1)
        head = pending(self.db, "s1", 1)[0]
        event_id = self.event(receipt=False)
        with self.assertRaisesRegex(ValueError, "capture_receipt_required"):
            complete(self.db, head["queue_id"], event_id)
        self.assertEqual(checkpoint(self.db, "s1")["pending"], 1)
        self.assertIsNone(checkpoint(self.db, "s1")["consumed_through_queue_id"])

    def test_complete_rejects_uncommitted_content_transaction(self):
        discover(self.db, "s1", [item()], T1)
        event_id = self.event()
        self.db.execute("UPDATE capture_sources SET scan_items=scan_items")
        with self.assertRaisesRegex(ValueError, "clean_transaction"):
            complete(self.db, pending(self.db, "s1", 1)[0]["queue_id"], event_id)
        self.db.rollback()

    def test_content_mismatch_cannot_mark_done(self):
        discover(self.db, "s1", [item()], T1)
        event_id = self.event(title="标题B")
        with self.assertRaisesRegex(ValueError, "content_mismatch"):
            complete(self.db, pending(self.db, "s1", 1)[0]["queue_id"], event_id)
        self.assertEqual(checkpoint(self.db, "s1")["done"], 0)

    def test_historical_matching_receipt_cannot_replace_latest_event(self):
        discover(self.db, "s1", [item()], T1)
        old = self.event()
        self.event(title="标题B", version=2)
        with self.assertRaisesRegex(ValueError, "latest_event_required"):
            complete(self.db, pending(self.db, "s1", 1)[0]["queue_id"], old)

    def test_cannot_complete_later_revision_first(self):
        discover(self.db, "s1", [item()], T1)
        discover(self.db, "s1", [item(title="标题B")], T2)
        later_id = self.db.execute("SELECT MAX(queue_id) FROM capture_queue").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "item_order_violation"):
            complete(self.db, later_id, self.event(title="标题B", version=2))

    def test_consumption_checkpoint_is_contiguous_not_max_done(self):
        discover(self.db, "s1", [item(), item("k2"), item("k3")], T1)
        rows = pending(self.db, "s1", 3)
        complete(self.db, rows[1]["queue_id"], self.event(key="k2"))
        self.assertIsNone(checkpoint(self.db, "s1")["consumed_through_queue_id"])
        complete(self.db, rows[0]["queue_id"], self.event())
        self.assertEqual(checkpoint(self.db, "s1")["consumed_through_queue_id"], rows[1]["queue_id"])
        fail(self.db, rows[2]["queue_id"], "transient_error")
        self.assertEqual(checkpoint(self.db, "s1")["consumed_through_queue_id"], rows[1]["queue_id"])

    def test_completion_is_idempotent_but_cannot_change_reference(self):
        discover(self.db, "s1", [item()], T1)
        queue_id = pending(self.db, "s1", 1)[0]["queue_id"]
        event_id = self.event()
        complete(self.db, queue_id, event_id)
        before = checkpoint(self.db, "s1")
        complete(self.db, queue_id, event_id)
        self.assertEqual(checkpoint(self.db, "s1"), before)
        with self.assertRaisesRegex(ValueError, "completion_conflict"):
            complete(self.db, queue_id, "another_event")
        with self.assertRaisesRegex(ValueError, "already_done"):
            fail(self.db, queue_id, "late_failure")

    def test_source_checkpoints_are_separate(self):
        discover(self.db, "s1", [item()], T1)
        discover(self.db, "s2", [item()], T2)
        complete(self.db, pending(self.db, "s2", 1)[0]["queue_id"], self.event(source="s2"))
        self.assertIsNone(checkpoint(self.db, "s1")["consumed_through_queue_id"])
        self.assertEqual(checkpoint(self.db, "s1")["last_successful_scan_at"], T1)
        self.assertEqual(checkpoint(self.db, "s2")["done"], 1)

    def test_pending_survives_process_connection_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            first = sqlite3.connect(path)
            first.executescript(SCHEMA)
            discover(first, "s1", [item(), item("k2")], T1)
            first.close()
            second = sqlite3.connect(path)
            try:
                self.assertEqual(len(pending(second, "s1", 20)), 2)
                self.assertEqual(checkpoint(second, "s1")["last_successful_scan_at"], T1)
            finally:
                second.close()

    def test_no_open_transaction_survives_validation_or_sql_failure(self):
        with self.assertRaises(ValueError):
            discover(self.db, "s1", [item(), item(title="B")], T1)
        self.assertFalse(self.db.in_transaction)
        discover(self.db, "s1", [item()], T2)
        with self.assertRaisesRegex(ValueError, "stale_capture_snapshot"):
            discover(self.db, "s1", [item("k2")], T1)
        self.assertFalse(self.db.in_transaction)

    def test_invalid_limits_queue_ids_and_error_text_rejected(self):
        for limit in (True, 0, -1, "1"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                pending(self.db, "s1", limit)
        for queue_id in (False, 0, -1, "1"):
            with self.subTest(queue_id=queue_id), self.assertRaises(ValueError):
                fail(self.db, queue_id, "error")
        with self.assertRaisesRegex(ValueError, "reason_code_required"):
            fail(self.db, 1, "untrusted\nbody")
        for exclusions in (None, "1", 1, [False], [-1], ["1"]):
            with self.subTest(exclusions=exclusions), self.assertRaises(ValueError):
                pending(self.db, "s1", 1, exclude_queue_ids=exclusions)

    def test_metadata_changes_do_not_fake_title_revision(self):
        discover(self.db, "s1", [item()], T1)
        changed = item()
        changed["source_time_text"] = "corrected metadata"
        changed["normalized_text"] = "new body that is not retained"
        result = discover(self.db, "s1", [changed], T2)
        self.assertEqual(result["discovered"], 0)
        self.assertEqual(result["unchanged"], 1)

    def test_empty_scan_is_successful_discovery_not_consumption(self):
        discover(self.db, "s1", [], T1)
        result = checkpoint(self.db, "s1")
        self.assertEqual(result["scan_items"], 0)
        self.assertEqual(result["last_successful_scan_at"], T1)
        self.assertIsNone(result["consumed_through_queue_id"])


if __name__ == "__main__":
    unittest.main()
