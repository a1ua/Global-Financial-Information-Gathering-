from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.ops.llm_backup import create_ledger_backup,restore_ledger_backup,verify_ledger_backup
from test_llm import NOW,REQUEST


class FailureBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/'source.db'
        client=ModelClient(self.path,Policy(enabled=True,max_retries=0),
                           lambda *_:ModelResponse('{"category":"wrong"}',10,8,'a'*64),clock=lambda:NOW)
        with self.assertRaises(ModelError):
            client.generate({'is_synthetic':True},**REQUEST)

    def tearDown(self):
        self.temp.cleanup()

    def metadata(self,path):
        with closing(sqlite3.connect(path)) as db:
            return db.execute('SELECT request_metadata FROM calls').fetchone()[0]

    def write_metadata(self,value):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE calls SET request_metadata=?',(json.dumps(value),))
            db.commit()

    def test_backup_restore_preserve_failure_metadata_and_full_reservation(self):
        original=self.metadata(self.path)
        create_ledger_backup(self.path,self.root/'backup')
        verify_ledger_backup(self.root/'backup')
        restore_ledger_backup(self.root/'backup',self.root/'restore')
        self.assertEqual(self.metadata(self.root/'restore'/'ledger.db'),original)
        with closing(sqlite3.connect(self.root/'restore'/'ledger.db')) as db:
            self.assertEqual(db.execute('SELECT charged_cost=reserved_cost,charged_tokens=reserved_tokens,input_tokens,output_tokens FROM calls').fetchone(),(1,1,None,None))

    def test_invalid_or_mutually_exclusive_observation_rejected(self):
        original=json.loads(self.metadata(self.path))
        for index,delta in enumerate(({'provider_failure':None},
                {'provider_failure':{'schema_version':'provider-failure-correlation/0.1','response_id_sha256':None}},
                {'provider_failure':{**original['provider_failure'],'extra':True}},
                {'provider_response':{'schema_version':'provider-response-correlation/0.1','response_id_sha256':'b'*64,'input_tokens':10,'output_tokens':8}})):
            with self.subTest(index=index):
                self.write_metadata({**original,**delta})
                with self.assertRaisesRegex(ValueError,'^ledger_backup_correlation_invalid$'):
                    create_ledger_backup(self.path,self.root/('invalid-'+str(index)))

    def test_observation_cannot_release_unknown_fee(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE calls SET charged_cost=0')
            db.commit()
        with self.assertRaisesRegex(ValueError,'unknown_spend_released'):
            create_ledger_backup(self.path,self.root/'invalid-release')

    def test_legacy_failed_remains_without_observation(self):
        value=json.loads(self.metadata(self.path))
        del value['provider_failure']
        self.write_metadata(value)
        create_ledger_backup(self.path,self.root/'backup')
        self.assertNotIn('provider_failure',json.loads(self.metadata(self.root/'backup'/'ledger.db')))


if __name__=='__main__':
    unittest.main()
