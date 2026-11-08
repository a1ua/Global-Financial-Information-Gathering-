from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from market_intel.capture import collect_all, collect_source, consume_pending, make_bundle, now
from market_intel.cli import main
from market_intel.offline import connect, ingest_bundle, render, replay_report
from market_intel.pipeline.capture_state import checkpoint, discover
from market_intel.transport import fetch


def item(key, title=None):
    return {"source_item_key": key, "original_url": "https://example.com/" + key,
            "title": title or "Title " + key, "normalized_text": "not retained body",
            "source_time_text": None, "source_published_at": None,
            "source_time_precision": "unknown", "source_timezone": None, "time_parse_status": "missing"}


class CaptureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = connect(self.root / "market.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def fetcher(self, data):
        return lambda: (data, {"fetched_at": now(), "http_status": 200})

    def test_limit_never_discards_tail_and_resume_never_uses_network(self):
        values = [item("k" + str(i)) for i in range(7)]
        with patch("market_intel.capture.parse_rss", return_value=values):
            first = collect_source(self.db, self.root, limit=2, fetcher=self.fetcher(b"SYNTHETIC"))
        self.assertEqual(first["discovery"]["discovered"], 7)
        self.assertEqual(first["consumed"], 2)
        self.assertEqual(first["checkpoint"]["pending"], 5)
        self.db.close()
        self.db = connect(self.root / "market.db")
        with patch("market_intel.capture.fetch", side_effect=AssertionError("resume must not fetch")):
            result = collect_source(self.db, self.root, limit=10, resume=True)
        self.assertEqual(result["inserted"], 5)
        self.assertEqual(result["checkpoint"]["pending"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM event_versions").fetchone()[0], 7)

    def test_unchanged_head_rescan_still_consumes_tail(self):
        values = [item("k" + str(i)) for i in range(5)]
        with patch("market_intel.capture.parse_rss", return_value=values):
            collect_source(self.db, self.root, limit=2, fetcher=self.fetcher(b"SYNTHETIC"))
            result = collect_source(self.db, self.root, limit=2, fetcher=self.fetcher(b"SYNTHETIC"))
        self.assertEqual(result["discovery"]["discovered"], 0)
        self.assertEqual(result["discovery"]["unchanged"], 5)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(result["checkpoint"]["pending"], 1)

    def test_partial_consumption_failure_does_not_starve_another_key(self):
        values = [item("bad"), item("good")]
        # Future source publication is rejected at ingestion, without dropping work.
        values[0].update(source_time_text="future", source_timezone="GMT", source_time_precision="second", time_parse_status="parsed",
                         source_published_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"))
        discover(self.db, "fed_press_all", values, now())
        failed = consume_pending(self.db, self.root, "fed", 1)
        self.assertEqual(len(failed["quarantined"]), 1)
        healthy = consume_pending(self.db, self.root, "fed", 1)
        self.assertEqual(healthy["consumed"], 1)
        self.assertEqual(healthy["checkpoint"]["pending"], 1)
        self.assertIsNone(healthy["checkpoint"]["consumed_through_queue_id"])

    def test_crash_after_content_commit_before_queue_complete_is_recovered(self):
        value = item("same")
        discover(self.db, "fed_press_all", [value], now())
        bundle = make_bundle(self.db, value, fetched_at=now())
        ingest_bundle(self.db, bundle, self.root)
        # Queue remains pending as if the process stopped immediately after commit.
        result = consume_pending(self.db, self.root, "fed", 5)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["checkpoint"]["pending"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM event_versions").fetchone()[0], 1)

    def test_fetch_or_parse_failure_never_advances_discovery(self):
        discover(self.db, "fed_press_all", [item("first")], now())
        before = checkpoint(self.db, "fed_press_all")
        def unavailable():
            raise OSError("network_failure")
        with self.assertRaises(OSError):
            collect_source(self.db, self.root, fetcher=unavailable)
        with self.assertRaises(ValueError):
            collect_source(self.db, self.root, fetcher=self.fetcher(b"not XML"))
        self.assertEqual(checkpoint(self.db, "fed_press_all"), before)

    def test_source_failure_does_not_stop_other_source(self):
        nbs = (Path(__file__).parent / "fixtures/sources/nbs-synthetic.html").read_bytes()
        def unavailable():
            raise OSError("feed_down")
        result = collect_all(self.db, self.root, fetchers={"fed": unavailable, "nbs": self.fetcher(nbs)})
        self.assertEqual(result["sources"][0]["status"], "failed")
        self.assertGreater(result["sources"][1]["inserted"], 0)
        payload = json.loads(self.db.execute("SELECT payload FROM event_versions LIMIT 1").fetchone()[0])
        self.assertEqual(payload["markets"], ["A"])
        self.assertEqual(payload["category"], "macro")
        path = render(self.db, self.root, now(), "mixed_sources", report_kind="source_snapshot")
        document = (path / "brief.html").read_text(encoding="utf-8")
        self.assertIn("国家统计局 · 官方来源链接", document)
        self.assertNotIn("官方 RSS 来源链接", document)

    def test_collect_all_partial_failure_cli_is_nonzero(self):
        with patch("market_intel.cli.collect_all", return_value={"status": "degraded", "sources": [{"status": "failed"}, {"status": "succeeded"}]}):
            with patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["collect-all", "--workspace", str(self.root)]), 2)

    def test_node_timeout_becomes_expected_operational_error(self):
        with patch.dict(os.environ, {"MARKET_INTEL_NODE": str(Path(__file__).resolve())}):
            with patch("market_intel.transport.subprocess.run", side_effect=subprocess.TimeoutExpired("node", 25)):
                with self.assertRaisesRegex(OSError, "node_transport_timeout"):
                    fetch("nbs", transport="node")

    def test_old_renderer_report_replays_with_unchanged_bytes(self):
        # Generate the exact old 0.2 format using a temporary frozen descriptor.
        from market_intel.offline import ingest_fixture
        bundle = json.loads((Path(__file__).parent / "fixtures/demo.json").read_text(encoding="utf-8"))
        ingest_fixture(self.db, bundle, self.root)
        current = render(self.db, self.root, "2026-11-06T00:30:00Z", "new_format")
        old = json.loads((current / "manifest.json").read_text(encoding="utf-8"))
        old.update(renderer_version="evidence-brief/0.2", template_version="evidence-brief/0.2", rules_version="strict-cutoff/0.2", report_type="offline_fixture")
        # Synthetic HTML is unchanged between 0.2 and 0.3; only metadata differs.
        old["report_id"] = "legacy"
        path = render(self.db, self.root, old["information_cutoff"], "legacy", frozen_manifest=old)
        replayed = replay_report(self.db, self.root, "legacy", self.root / "replay")
        self.assertEqual((path / "brief.html").read_bytes(), (replayed / "brief.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
