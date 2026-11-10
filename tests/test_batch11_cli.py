from contextlib import closing,redirect_stdout,redirect_stderr
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from market_intel.cli import main
from market_intel.llm import ModelClient,ModelError,ModelResponse,Policy
from market_intel.llm.binding import ensure_workspace_ledger
from test_llm import NOW,REQUEST


class Batch11CLITests(unittest.TestCase):
    def test_failed_hash_summary_is_readonly_and_never_uses_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            bound=ensure_workspace_ledger(root)
            client=ModelClient(bound['ledger'],Policy(enabled=True,max_retries=0),
                               lambda *_:ModelResponse('private-invalid-body',10,8,'a'*64),clock=lambda:NOW)
            with self.assertRaises(ModelError):
                client.generate({'is_synthetic':True},**REQUEST)
            with closing(sqlite3.connect(bound['ledger'])) as db:
                identity=db.execute('SELECT call_id FROM calls').fetchone()[0]
            before=Path(bound['ledger']).read_bytes()
            stdout,stderr=io.StringIO(),io.StringIO()
            original_get=os.environ.get
            def guarded_get(name,default=None):
                if name=='DEEPSEEK_API_KEY':
                    raise AssertionError('key forbidden')
                return original_get(name,default)
            with redirect_stdout(stdout),redirect_stderr(stderr),patch('market_intel.cli.ModelClient',side_effect=AssertionError('model forbidden')),patch('market_intel.cli.connect',side_effect=AssertionError('writer forbidden')),patch('socket.create_connection',side_effect=AssertionError('network forbidden')),patch('market_intel.cli.os.environ.get',side_effect=guarded_get):
                code=main(['model-call-info','--workspace',str(root),'--call-id',identity])
            self.assertEqual(code,0)
            self.assertEqual(stderr.getvalue(),'')
            value=json.loads(stdout.getvalue())
            self.assertEqual((value['schema_version'],value['call_status'],value['correlation_status']),('model-call-info/0.2','failed','failure_recorded'))
            self.assertEqual(value['charged_cost_micro_units'],value['reserved_cost_micro_units'])
            self.assertFalse(value['invoice_verified'])
            self.assertFalse(value['settlement_allowed'])
            self.assertNotIn('private-invalid-body',stdout.getvalue())
            self.assertNotIn('provider_failure',stdout.getvalue())
            self.assertEqual(Path(bound['ledger']).read_bytes(),before)


if __name__=='__main__':
    unittest.main()
