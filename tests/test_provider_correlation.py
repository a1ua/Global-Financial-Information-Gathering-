from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.correlation import (response_id_sha256, validate_call_correlation,
                                          validate_provider_response)
from test_llm import NOW, REQUEST


class ProviderCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.db'
        self.digest = response_id_sha256('completion-synthetic-001')
        self.policy = Policy(enabled=True, max_retries=0)

    def tearDown(self):
        self.temp.cleanup()

    def client(self, response=None, transport=None, policy=None):
        return ModelClient(self.path, policy or self.policy, transport or (
            lambda *_: response or ModelResponse('{"category":"macro"}', 10, 8, self.digest)), clock=lambda: NOW)

    def generate(self, client):
        return client.generate({'is_synthetic': True}, **REQUEST)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM calls ORDER BY rowid')]

    def test_hash_and_strict_optional_object(self):
        self.assertEqual(self.digest, hashlib.sha256(b'completion-synthetic-001').hexdigest())
        for value in (None, '', True, {}, 'a'*257, 'white space', '\nsecret', '中文', '\ud800'):
            with self.subTest(value=type(value)), self.assertRaisesRegex(ValueError, '^provider_correlation_invalid$'):
                response_id_sha256(value)
        good = {'schema_version': 'provider-response-correlation/0.1', 'response_id_sha256': self.digest,
                'input_tokens': 10, 'output_tokens': 8}
        validate_provider_response(good)
        for change in ({'extra': 1}, {'input_tokens': True}, {'output_tokens': 0},
                       {'response_id_sha256': self.digest.upper()}, {'schema_version': 'unknown'}):
            with self.assertRaises(ValueError):
                validate_provider_response({**good, **change})
        for call in ({'status':'failed','input_tokens':10,'output_tokens':8},
                     {'status':'succeeded','input_tokens':True,'output_tokens':8},
                     {'status':'succeeded','input_tokens':11,'output_tokens':8}, {}, None, []):
            with self.assertRaisesRegex(ValueError, '^provider_correlation_invalid$'):
                validate_call_correlation({'provider_response': good}, call)

    def test_success_cache_keeps_original_call_and_metadata(self):
        client = self.client()
        first = self.generate(client)
        before = self.rows()
        second = self.generate(client)
        self.assertEqual((second.call_id, second.cache_hit), (first.call_id, True))
        self.assertEqual(self.rows(), before)
        row = before[0]
        value = json.loads(row['request_metadata'])['provider_response']
        self.assertEqual((value['response_id_sha256'], value['input_tokens'], value['output_tokens']),
                         (self.digest, 10, 8))
        self.assertEqual((row['charged_tokens'], row['status']), (18, 'succeeded'))
        self.assertNotIn('completion-synthetic-001', row['request_metadata'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)

    def test_missing_id_is_explicit_unavailable_and_no_usage_remains_absent(self):
        self.generate(self.client(ModelResponse('{"category":"macro"}', 10, 8)))
        self.assertIsNone(json.loads(self.rows()[0]['request_metadata'])['provider_response']['response_id_sha256'])
        client = self.client(ModelResponse('{"category":"macro"}'))
        client.generate({'is_synthetic':True, 'case':2}, **REQUEST)
        self.assertNotIn('provider_response', json.loads(self.rows()[1]['request_metadata']))

    def test_legacy_cache_is_not_backfilled(self):
        client = self.client()
        first = self.generate(client)
        row = self.rows()[0]
        metadata = json.loads(row['request_metadata'])
        del metadata['provider_response']
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE calls SET request_metadata=?', (json.dumps(metadata),))
            db.commit()
        before = self.rows()
        self.assertEqual(self.generate(client).call_id, first.call_id)
        self.assertEqual(self.rows(), before)

    def test_invalid_hash_and_output_keep_full_reservation_without_correlation(self):
        cases = [(ModelResponse('{"category":"macro"}', 10, 8, 'secret-id'), 'invalid_provider_response'),
                 (ModelResponse('{"category":"wrong"}', 10, 8, self.digest), 'output_schema_mismatch')]
        client = self.client()
        for index, (response, error) in enumerate(cases):
            client.transport = lambda *_, r=response: r
            with self.assertRaisesRegex(ModelError, '^'+error+'$'):
                client.generate({'is_synthetic':True, 'case':index}, **REQUEST)
            row = self.rows()[-1]
            self.assertEqual((row['charged_tokens'], row['charged_cost']), (row['reserved_tokens'], row['reserved_cost']))
            self.assertIsNone(row['output_text'])
            self.assertNotIn('provider_response', json.loads(row['request_metadata']))

    def test_retry_has_distinct_calls_and_only_success_is_correlated(self):
        responses = iter([TimeoutError('private marker'), ModelResponse('{"category":"macro"}', 10, 8, self.digest)])
        def transport(*_):
            result = next(responses)
            if isinstance(result, Exception):
                raise result
            return result
        client = self.client(transport=transport, policy=replace(self.policy, max_retries=1))
        self.generate(client)
        failed, success = self.rows()
        self.assertNotEqual(failed['call_id'], success['call_id'])
        self.assertEqual((failed['attempt'], success['attempt']), (1, 2))
        self.assertNotIn('provider_response', json.loads(failed['request_metadata']))
        self.assertIn('provider_response', json.loads(success['request_metadata']))
        self.assertEqual(failed['charged_cost'], failed['reserved_cost'])

    def test_success_update_and_cache_are_transactional(self):
        client = self.client()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER reject_cache BEFORE INSERT ON cache BEGIN SELECT RAISE(ABORT, 'private marker'); END")
            db.commit()
        with self.assertRaisesRegex(ModelError, '^ledger_error$'):
            self.generate(client)
        row = self.rows()[0]
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['charged_cost'], row['reserved_cost'])
        self.assertNotIn('provider_response', json.loads(row['request_metadata']))
        self.assertIsNone(row['output_text'])

    def test_corrupt_cached_correlation_is_rejected(self):
        client = self.client()
        self.generate(client)
        row = self.rows()[0]
        metadata = json.loads(row['request_metadata'])
        metadata['provider_response']['input_tokens'] = 11
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE calls SET request_metadata=?', (json.dumps(metadata),))
            db.commit()
        with self.assertRaisesRegex(ModelError, '^cache_integrity_error$'):
            self.generate(client)


if __name__ == '__main__':
    unittest.main()
