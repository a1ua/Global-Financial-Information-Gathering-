import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from market_intel.contracts.candidate_snapshot import canonical_json
from market_intel.ops import candidate_snapshot as module
from market_intel.store import connect, insert_immutable
from test_evidence_candidates import CUTOFF, fixture


class CandidateArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.workspace = self.base / "source"
        self.workspace.mkdir()
        self.db = connect(self.workspace / "market.db")
        self.bundle = fixture()
        self.add(self.bundle)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, bundle):
        with self.db:
            for key, table, identity in (("raw", "raw_items", "raw_item_id"),
                                         ("event", "event_versions", "event_version_id"),
                                         ("evidence", "evidence", "evidence_id")):
                insert_immutable(self.db, table, identity, bundle[key])
            if not bundle["event"]["is_synthetic"]:
                self.db.execute("INSERT INTO availability_receipts VALUES(?,?)",
                                (bundle["event"]["event_version_id"], "2026-11-09T00:00:01Z"))
        path = self.workspace / bundle["raw"]["content_ref"]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(bundle["raw"]["normalized_text"].encode())

    def freeze(self, name="frozen", **kwargs):
        target = self.base / name
        result = module.freeze_candidate_snapshot(self.workspace, target, CUTOFF,
                                                   include_synthetic=True, **kwargs)
        return target / module.MANIFEST_FILE, result

    def replay(self):
        manifest, frozen = self.freeze()
        target = self.base / "replay"
        result = module.replay_candidate_snapshot(self.workspace, manifest, target)
        return target, result, frozen

    def rewrite(self, path, transform):
        value = json.loads(path.read_text(encoding="utf-8"))
        transform(value)
        path.write_text(canonical_json(value), encoding="utf-8")

    def test_freeze_uses_one_plan_and_saves_only_canonical_metadata(self):
        with patch.object(module, "plan_evidence_candidates", wraps=module.plan_evidence_candidates) as planner:
            manifest, result = self.freeze()
        self.assertEqual(planner.call_count, 1)
        self.assertEqual([p.name for p in manifest.parent.iterdir()], [module.MANIFEST_FILE])
        data = manifest.read_bytes()
        self.assertNotIn(self.bundle["raw"]["normalized_text"].encode(), data)
        self.assertNotIn(b"https://", data)
        self.assertEqual(data, canonical_json(json.loads(data)).encode())
        self.assertEqual((result["status"], result["selected_count"], result["model_called"]), ("frozen", 1, False))
        verified = module.verify_candidate_snapshot_file(self.workspace, manifest)
        self.assertEqual(verified["status"], "verified_inputs")
        self.assertEqual(verified["input_manifest_sha256"], result["input_manifest_sha256"])

    def test_replay_loads_once_and_verifies_without_source_or_planner(self):
        with patch.object(module, "load_candidate_snapshot_inputs", wraps=module.load_candidate_snapshot_inputs) as loader:
            target, result, frozen = self.replay()
        self.assertEqual(loader.call_count, 1)
        data = (target / module.INPUTS_FILE).read_bytes()
        self.assertIn(self.bundle["raw"]["normalized_text"].encode(), data)
        self.assertEqual(result["replay_sha256"], hashlib.sha256(data).hexdigest())
        self.db.close()
        self.assertTrue(self.workspace.resolve().is_relative_to(self.base.resolve()))
        shutil.rmtree(self.workspace)
        with patch.object(module, "load_candidate_snapshot_inputs", side_effect=AssertionError("source access")), \
                patch.object(module, "plan_evidence_candidates", side_effect=AssertionError("new plan")):
            verified = module.verify_candidate_replay(target)
        self.assertEqual((verified["status"], verified["data_status"], verified["is_synthetic"]),
                         ("verified_replay", "synthetic", True))
        self.assertEqual(verified["input_manifest_sha256"], frozen["input_manifest_sha256"])
        self.assertEqual(verified["replay_sha256"], result["replay_sha256"])

    def test_empty_and_mixed_labels_are_explicit(self):
        manifest, _ = self.freeze(max_candidates=0)
        empty = self.base / "empty"
        module.replay_candidate_snapshot(self.workspace, manifest, empty)
        result = module.verify_candidate_replay(empty)
        self.assertEqual((result["selected_count"], result["data_status"], result["is_synthetic"], result["mixed_test_data"]),
                         (0, "empty", False, False))
        self.add(fixture("real", synthetic=False))
        manifest, _ = self.freeze("mixed-frozen")
        mixed = self.base / "mixed"
        module.replay_candidate_snapshot(self.workspace, manifest, mixed)
        result = module.verify_candidate_replay(mixed)
        self.assertEqual((result["data_status"], result["is_synthetic"], result["mixed_test_data"]), ("mixed", False, True))

    def test_new_version_and_old_time_backfill_do_not_replan_replay(self):
        manifest, frozen = self.freeze()
        self.add(fixture("a", version=2))
        self.add(fixture("backfill", at="2026-11-08T00:00:00Z"))
        target = self.base / "replay"
        with patch.object(module, "plan_evidence_candidates", side_effect=AssertionError("replanned")):
            module.replay_candidate_snapshot(self.workspace, manifest, target)
        inputs = json.loads((target / module.INPUTS_FILE).read_bytes())
        self.assertEqual(len(inputs["bundles"]), 1)
        self.assertEqual(inputs["bundles"][0]["event"]["version"], 1)
        self.assertEqual(module.verify_candidate_replay(target)["input_manifest_sha256"], frozen["input_manifest_sha256"])

    def test_existing_destinations_are_not_overwritten(self):
        manifest, _ = self.freeze()
        original = manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            self.freeze()
        self.assertEqual(manifest.read_bytes(), original)
        target = self.base / "existing"
        target.mkdir()
        (target / "sentinel").write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            module.replay_candidate_snapshot(self.workspace, manifest, target)
        self.assertEqual((target / "sentinel").read_text(), "keep")

    def test_role_overlap_is_rejected_without_creating_parents(self):
        manifest, _ = self.freeze()
        for target in (self.workspace / "new-parent/new", manifest.parent / "new-parent/new"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "directories_overlap"):
                    module.replay_candidate_snapshot(self.workspace, manifest, target)
                self.assertFalse(target.parent.exists())
        with self.assertRaises(ValueError):
            module.freeze_candidate_snapshot(self.workspace, self.workspace / "freeze", CUTOFF, include_synthetic=True)
        self.assertFalse((self.workspace / "freeze").exists())
        with self.assertRaises(ValueError):
            module.replay_candidate_snapshot(self.workspace, manifest, manifest)

    def test_selected_source_failure_does_not_create_parent(self):
        manifest, _ = self.freeze()
        (self.workspace / self.bundle["raw"]["content_ref"]).write_text("changed", encoding="utf-8")
        target = self.base / "new-parent/replay"
        with self.assertRaises(ValueError):
            module.replay_candidate_snapshot(self.workspace, manifest, target)
        self.assertFalse(target.parent.exists())

    def test_write_capacity_checks_happen_before_new_parents(self):
        target = self.base / "new-freeze-parent/frozen"
        with patch.object(module, "MANIFEST_LIMIT", 10):
            with self.assertRaisesRegex(ValueError, "capacity_exceeded"):
                module.freeze_candidate_snapshot(self.workspace, target, CUTOFF, include_synthetic=True)
        self.assertFalse(target.parent.exists())
        manifest, _ = self.freeze()
        target = self.base / "new-replay-parent/replay"
        with patch.object(module, "INPUTS_LIMIT", 10):
            with self.assertRaisesRegex(ValueError, "capacity_exceeded"):
                module.replay_candidate_snapshot(self.workspace, manifest, target)
        self.assertFalse(target.parent.exists())

    def test_read_capacity_is_enforced_for_manifest_and_inputs(self):
        target, _, _ = self.replay()
        with patch.object(module, "MANIFEST_LIMIT", 10):
            with self.assertRaisesRegex(ValueError, "capacity_exceeded"):
                module.verify_candidate_snapshot_file(self.workspace, target / module.MANIFEST_FILE)
        with patch.object(module, "INPUTS_LIMIT", 10):
            with self.assertRaisesRegex(ValueError, "capacity_exceeded"):
                module.verify_candidate_replay(target)

    def test_strict_json_rejects_duplicate_nonfinite_and_unicode_without_echo(self):
        manifest, _ = self.freeze()
        for invalid in (b'{"secret-marker":0,"secret-marker":1}', b'{"secret-marker":NaN}',
                        b'{"secret-marker":"\\ud800"}', b'\xffsecret-marker', b'{"secret-marker":1e999}'):
            manifest.write_bytes(invalid)
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError) as caught:
                    module.verify_candidate_snapshot_file(self.workspace, manifest)
                self.assertNotIn("secret-marker", str(caught.exception))

    def test_replay_inventory_rejects_missing_extra_directory_and_partial(self):
        target, _, _ = self.replay()
        extra = target / "extra"
        extra.mkdir()
        with self.assertRaisesRegex(ValueError, "inventory_invalid"):
            module.verify_candidate_replay(target)
        extra.rmdir()
        (target / module.INPUTS_FILE).unlink()
        with self.assertRaisesRegex(ValueError, "inventory_invalid"):
            module.verify_candidate_replay(target)
        with self.assertRaises(ValueError):
            module.verify_candidate_replay(self.base / "missing")

    def test_offline_rejects_extra_bundle_fields_modified_text_and_receipt(self):
        target, _, _ = self.replay()
        path = target / module.INPUTS_FILE
        original = path.read_bytes()
        for change in (lambda x: x["bundles"][0].update(extra="secret-marker"),
                       lambda x: x["bundles"][0]["raw"].update(normalized_text="secret-marker"),
                       lambda x: x["bundles"][0].update(receipt_committed_at="2026-11-09T00:00:00Z"),
                       lambda x: x.update(extra=True),
                       lambda x: x.update(input_manifest_sha256="0" * 64),
                       lambda x: x.update(bundles=[])):
            path.write_bytes(original)
            self.rewrite(path, change)
            with self.assertRaises(ValueError) as caught:
                module.verify_candidate_replay(target)
            self.assertNotIn("secret-marker", str(caught.exception))

    def test_offline_rejects_reordered_bundles(self):
        self.add(fixture("b"))
        target, _, _ = self.replay()
        self.rewrite(target / module.INPUTS_FILE, lambda x: x["bundles"].reverse())
        with self.assertRaisesRegex(ValueError, "descriptor_mismatch"):
            module.verify_candidate_replay(target)

    def test_replay_hash_covers_actual_bytes_and_noncanonical_json_is_readable(self):
        target, result, _ = self.replay()
        path = target / module.INPUTS_FILE
        payload = json.loads(path.read_bytes())
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        path.write_bytes(data)
        verified = module.verify_candidate_replay(target)
        self.assertNotEqual(verified["replay_sha256"], result["replay_sha256"])
        self.assertEqual(verified["replay_sha256"], hashlib.sha256(data).hexdigest())

    def test_publication_interruption_leaves_rejected_partial_directory_without_repair(self):
        manifest, _ = self.freeze()
        target = self.base / "partial"
        with patch.object(module.os, "fsync", side_effect=OSError("secret-marker")):
            with self.assertRaisesRegex(ValueError, "io_error") as caught:
                module.replay_candidate_snapshot(self.workspace, manifest, target)
        self.assertNotIn("secret-marker", str(caught.exception))
        self.assertTrue((target / module.MANIFEST_FILE).exists())
        with self.assertRaises(ValueError):
            module.verify_candidate_replay(target)
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            module.replay_candidate_snapshot(self.workspace, manifest, target)

    def test_concurrent_destination_claim_fails_without_overwrite(self):
        manifest, _ = self.freeze()
        target = self.base / "race"
        publish = module._publish

        def competitor(destination, files):
            destination.mkdir()
            (destination / "sentinel").write_text("keep", encoding="utf-8")
            return publish(destination, files)

        with patch.object(module, "_publish", side_effect=competitor):
            with self.assertRaises(ValueError):
                module.replay_candidate_snapshot(self.workspace, manifest, target)
        self.assertEqual((target / "sentinel").read_text(), "keep")
        self.assertEqual(len(list(target.iterdir())), 1)

    def test_linked_parent_and_manifest_file_are_rejected(self):
        manifest, _ = self.freeze()
        linked = self.base / "linked"
        try:
            linked.symlink_to(manifest.parent, target_is_directory=True)
        except OSError:
            self.skipTest("OS does not permit symlink creation")
        with self.assertRaisesRegex(ValueError, "link_forbidden"):
            module.verify_candidate_snapshot_file(self.workspace, linked / module.MANIFEST_FILE)
        with self.assertRaisesRegex(ValueError, "link_forbidden"):
            module.replay_candidate_snapshot(self.workspace, manifest, linked / "nested/replay")
        linked.unlink()
        linked.symlink_to(manifest)
        with self.assertRaisesRegex(ValueError, "link_forbidden"):
            module.verify_candidate_snapshot_file(self.workspace, linked)

    @unittest.skipUnless(os.name == "nt", "Windows junction-specific check")
    def test_actual_windows_junction_parent_is_rejected(self):
        manifest, _ = self.freeze()
        linked = self.base / "junction"
        receipt = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(manifest.parent)],
                                 capture_output=True)
        self.assertEqual(receipt.returncode, 0, "junction creation failed")
        try:
            with self.assertRaisesRegex(ValueError, "link_forbidden"):
                module.verify_candidate_snapshot_file(self.workspace, linked / module.MANIFEST_FILE)
            with self.assertRaisesRegex(ValueError, "link_forbidden"):
                module.replay_candidate_snapshot(self.workspace, manifest, linked / "nested/replay")
        finally:
            # Remove only the verified junction itself, never recurse into its target.
            linked.rmdir()


if __name__ == "__main__":
    unittest.main()
