from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.client import ObservedTransportError
from market_intel.llm.correlation import validate_provider_failure, validate_call_correlation
from test_llm import NOW, REQUEST


HASH = 'a' * 64


class FailureCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'ledger.db'

    def tearDown(self):
        self.temp.cleanup()

    def client(self, transport, retries=0):
        return ModelClient(self.path, Policy(enabled=True,max_retries=retries),transport,clock=lambda:NOW)

    def run_failure(self, client):
        with self.assertRaises(ModelError):
            client.generate({'is_synthetic':True},**REQUEST)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM calls ORDER BY rowid')]

    def assert_full(self,row):
        self.assertEqual((row['charged_tokens'],row['charged_cost']),(row['reserved_tokens'],row['reserved_cost']))
        for key in ('input_tokens','output_tokens','output_text','output_sha256'):
            self.assertIsNone(row[key])

    def test_pure_schema_and_state_are_strict(self):
        good={'schema_version':'provider-failure-correlation/0.1','response_id_sha256':HASH}
        validate_provider_failure(good)
        for bad in (None,{}, {**good,'extra':1},{**good,'response_id_sha256':None},
                    {**good,'response_id_sha256':'secret'},{**good,'response_id_sha256':HASH.upper()}):
            with self.assertRaisesRegex(ValueError,'^provider_correlation_invalid$'):
                validate_provider_failure(bad)
        valid={'status':'failed','input_tokens':None,'output_tokens':None}
        validate_call_correlation({'provider_failure':good},valid)
        for row in ({},None,{**valid,'status':'succeeded'},{**valid,'input_tokens':0}):
            with self.assertRaisesRegex(ValueError,'^provider_correlation_invalid$'):
                validate_call_correlation({'provider_failure':good},row)
        with self.assertRaises(ValueError):
            validate_call_correlation({'provider_failure':good,'provider_response':None},valid)

    def test_error_carrier_is_bounded_without_raw_fields(self):
        error=ObservedTransportError('deepseek_invalid_usage',HASH)
        self.assertEqual(str(error),'deepseek_invalid_usage')
        self.assertEqual(vars(error),{'response_id_sha256':HASH})
        for code,digest in (('private path','a'*64),('A','a'*64),('a'*81,HASH),('valid',None),('valid','raw-secret')):
            with self.assertRaisesRegex(ModelError,'^invalid_provider_observation$'):
                ObservedTransportError(code,digest)

    def test_observed_error_is_failed_full_cost_no_cache(self):
        def transport(*_):
            raise ObservedTransportError('deepseek_invalid_usage',HASH)
        self.run_failure(self.client(transport,retries=2))
        rows=self.rows()
        self.assertEqual(len(rows),1)
        self.assert_full(rows[0])
        self.assertEqual(json.loads(rows[0]['request_metadata'])['provider_failure']['response_id_sha256'],HASH)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cache').fetchone()[0],0)

    def test_mutated_error_hash_is_dropped_and_code_sanitized(self):
        for index,digest in enumerate((None,'secret marker')):
            error=ObservedTransportError('safe_code',HASH)
            error.response_id_sha256=digest
            def transport(*_,error=error):
                raise error
            client=self.client(transport)
            with self.assertRaisesRegex(ModelError,'^transport_error$'):
                client.generate({'is_synthetic':True,'case':index},**REQUEST)
            row=self.rows()[-1]
            self.assert_full(row)
            self.assertNotIn('provider_failure',json.loads(row['request_metadata']))

    def test_retry_does_not_inherit_hash_and_success_is_separate(self):
        responses=iter([ModelResponse('{"category":"wrong"}',10,8,HASH),TimeoutError('private'),
                        ModelResponse('{"category":"macro"}',10,8,'b'*64)])
        def transport(*_):
            response=next(responses)
            if isinstance(response,Exception):
                raise response
            return response
        client=self.client(transport,retries=2)
        result=client.generate({'is_synthetic':True},**REQUEST)
        first,second,success=self.rows()
        self.assert_full(first)
        self.assert_full(second)
        self.assertIn('provider_failure',json.loads(first['request_metadata']))
        self.assertNotIn('provider_failure',json.loads(second['request_metadata']))
        self.assertNotIn('provider_failure',json.loads(success['request_metadata']))
        self.assertEqual(success['charged_tokens'],18)
        before=self.rows()
        self.assertEqual(client.generate({'is_synthetic':True},**REQUEST).call_id,result.call_id)
        self.assertEqual(self.rows(),before)

    def test_invalid_response_hash_never_saved(self):
        self.run_failure(self.client(lambda *_:ModelResponse('{"category":"wrong"}',10,8,'secret')))
        row=self.rows()[0]
        self.assert_full(row)
        self.assertNotIn('provider_failure',json.loads(row['request_metadata']))

    def test_failure_update_rollback_leaves_pending_without_observation(self):
        client=self.client(lambda *_:ModelResponse('{"category":"wrong"}',10,8,HASH))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER reject_failure BEFORE UPDATE ON calls WHEN NEW.status='failed' BEGIN SELECT RAISE(ABORT,'private'); END")
            db.commit()
        with self.assertRaisesRegex(ModelError,'^ledger_error$'):
            client.generate({'is_synthetic':True},**REQUEST)
        row=self.rows()[0]
        self.assertEqual(row['status'],'pending')
        self.assert_full(row)
        self.assertNotIn('provider_failure',json.loads(row['request_metadata']))

    def test_plain_error_cannot_smuggle_observation_attribute(self):
        error=ModelError('private_marker')
        error.response_id_sha256=HASH
        def transport(*_):
            raise error
        self.run_failure(self.client(transport))
        row=self.rows()[0]
        self.assertNotIn('provider_failure',json.loads(row['request_metadata']))
        self.assertEqual(row['error_code'],'transport_error')


if __name__=='__main__':
    unittest.main()
