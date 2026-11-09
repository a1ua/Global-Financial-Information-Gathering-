from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.llm import ModelClient, ModelResponse, Policy
from market_intel.llm.binding import ensure_workspace_ledger
from market_intel.llm.correlation import response_id_sha256
from test_llm import NOW, REQUEST


class Batch10CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'bound'
        binding = ensure_workspace_ledger(self.workspace)
        self.digest = response_id_sha256('synthetic-completion-cli')
        self.client = ModelClient(binding['ledger'], Policy(enabled=True,max_retries=0),
                                  lambda *_: ModelResponse('{"category":"macro"}',10,8,self.digest), clock=lambda:NOW)
        self.result = self.client.generate({'is_synthetic':True}, **REQUEST)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, call_id=None, workspace=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = os.environ.get
        def get(name, default=None):
            if name == 'DEEPSEEK_API_KEY':
                raise AssertionError('key forbidden')
            return original(name,default)
        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                'market_intel.cli.os.environ.get',side_effect=get), patch(
                'market_intel.cli.ModelClient',side_effect=AssertionError('model forbidden')), patch(
                'market_intel.cli.connect',side_effect=AssertionError('writable store forbidden')), patch(
                'socket.create_connection',side_effect=AssertionError('network forbidden')):
            code = main(['model-call-info','--workspace',str(workspace or self.workspace),
                         '--call-id',call_id or self.result.call_id])
        text = stdout.getvalue() or stderr.getvalue()
        for secret in ('synthetic-completion-cli','"category"',REQUEST['system_prompt'],str(self.workspace)):
            self.assertNotIn(secret,text)
        return code,json.loads(text)

    def test_success_summary_is_readonly_and_never_calls_model_or_key(self):
        before = {p.name:p.read_bytes() for p in self.workspace.iterdir() if p.is_file()}
        code, result = self.invoke()
        self.assertEqual((code,result['call_id'],result['response_id_sha256']),
                         (0,self.result.call_id,self.digest))
        self.assertEqual(result['correlation_status'],'recorded')
        self.assertFalse(result['invoice_verified'])
        self.assertFalse(result['settlement_allowed'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.workspace.iterdir() if p.is_file()})

    def test_missing_workspace_and_call_id_reject_without_creating(self):
        missing = self.root/'missing'
        self.assertEqual(self.invoke(workspace=missing)[0],1)
        self.assertFalse(missing.exists())
        self.assertEqual(self.invoke(call_id='call_'+'f'*32)[0],1)
        self.assertEqual(self.invoke(call_id='private-marker/not-an-id')[0],1)

    def test_legacy_summary_does_not_backfill(self):
        path = self.workspace/'llm-state.db'
        with closing(sqlite3.connect(path)) as db:
            metadata = json.loads(db.execute('SELECT request_metadata FROM calls').fetchone()[0])
            del metadata['provider_response']
            db.execute('UPDATE calls SET request_metadata=?',(json.dumps(metadata),))
            db.commit()
        before = path.read_bytes()
        code,result = self.invoke()
        self.assertEqual((code,result['correlation_status'],result['response_id_sha256']),(0,'absent',None))
        self.assertEqual(path.read_bytes(),before)

    def test_malformed_optional_correlation_fails_without_leaking(self):
        with closing(sqlite3.connect(self.workspace/'llm-state.db')) as db:
            metadata = json.loads(db.execute('SELECT request_metadata FROM calls').fetchone()[0])
            metadata['provider_response']['response_id_sha256'] = 'private-response-marker'
            db.execute('UPDATE calls SET request_metadata=?',(json.dumps(metadata),))
            db.commit()
        code,result = self.invoke()
        self.assertEqual((code,result['status']),(1,'failed'))
        self.assertNotIn('private-response-marker',json.dumps(result))


if __name__ == '__main__':
    unittest.main()
