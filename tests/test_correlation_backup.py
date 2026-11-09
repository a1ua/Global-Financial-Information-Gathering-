from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelResponse, Policy
from market_intel.llm.correlation import response_id_sha256
from market_intel.ops.llm_backup import create_ledger_backup, restore_ledger_backup, verify_ledger_backup
from test_llm import NOW, REQUEST


class CorrelationBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'source' / 'llm-state.db'
        client = ModelClient(self.path, Policy(enabled=True, max_retries=0),
                             lambda *_: ModelResponse('{"category":"macro"}', 10, 8, response_id_sha256('synthetic-completion')),
                             clock=lambda: NOW)
        self.call_id = client.generate({'is_synthetic':True}, **REQUEST).call_id

    def tearDown(self):
        self.temp.cleanup()

    def metadata(self, path):
        with closing(sqlite3.connect(path)) as db:
            return db.execute('SELECT request_metadata FROM calls WHERE call_id=?', (self.call_id,)).fetchone()[0]

    def mutate(self, value):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE calls SET request_metadata=? WHERE call_id=?', (json.dumps(value), self.call_id))
            db.commit()

    def test_backup_restore_preserve_metadata_bytes_and_identity(self):
        original = self.metadata(self.path)
        result = create_ledger_backup(self.path, self.root / 'backup')
        self.assertEqual(result['database_schema_version'], 3)
        verify_ledger_backup(self.root / 'backup')
        restore_ledger_backup(self.root / 'backup', self.root / 'restore')
        self.assertEqual(self.metadata(self.root / 'backup' / 'ledger.db'), original)
        self.assertEqual(self.metadata(self.root / 'restore' / 'ledger.db'), original)

    def test_legacy_missing_field_remains_compatible(self):
        value = json.loads(self.metadata(self.path))
        del value['provider_response']
        self.mutate(value)
        create_ledger_backup(self.path, self.root / 'backup')
        self.assertNotIn('provider_response', json.loads(self.metadata(self.root / 'backup' / 'ledger.db')))

    def test_invalid_optional_objects_are_not_accepted_by_backup(self):
        original = json.loads(self.metadata(self.path))
        variants = [None, {}, {**original['provider_response'], 'extra': True},
                    {**original['provider_response'], 'input_tokens': 11},
                    {**original['provider_response'], 'output_tokens': True},
                    {**original['provider_response'], 'response_id_sha256': 'raw-secret-marker'}]
        for index, response in enumerate(variants):
            with self.subTest(index=index):
                value = copy.deepcopy(original)
                value['provider_response'] = response
                self.mutate(value)
                with self.assertRaisesRegex(ValueError, '^ledger_backup_correlation_invalid$'):
                    create_ledger_backup(self.path, self.root / ('invalid-' + str(index)))

    def test_pending_or_failed_cannot_have_success_correlation(self):
        for status in ('pending', 'failed'):
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('UPDATE calls SET status=?', (status,))
                db.commit()
            with self.assertRaisesRegex(ValueError, '^ledger_backup_correlation_invalid$'):
                create_ledger_backup(self.path, self.root / status)


if __name__ == '__main__':
    unittest.main()
