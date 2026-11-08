from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from market_intel.llm import ModelClient, ModelError, ModelResponse, Policy
from market_intel.llm.client import estimate_cost
from market_intel.llm.deepseek import DeepSeekTransport
from test_deepseek import FakeOpener, FakeResponse, completion


REQUEST = {"system_prompt": "Return JSON from synthetic data only.",
           "prompt_version": "synthetic/1", "rules_version": "synthetic/1",
           "output_schema": {"type": "object", "properties": {"category": {"type": "string"}},
                             "required": ["category"], "additionalProperties": False},
           "schema_version": "category/1", "parameters": {"temperature": 0}}
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def cny_policy(**changes):
    values = {"enabled": True, "budget_currency": "CNY", "daily_micro_units": 10_000_000,
              "input_micro_units_per_million_tokens": 2_000_000,
              "output_micro_units_per_million_tokens": 8_000_000, "max_retries": 0,
              "max_input_tokens": 16384}
    values.update(changes)
    return Policy(**values)


class CNYTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "llm-state.db"

    def tearDown(self):
        self.temp.cleanup()

    def client(self, policy=None, transport=None):
        return ModelClient(self.path, policy or cny_policy(), transport or (
            lambda *_: ModelResponse('{"category":"other"}', 20, 8)), clock=lambda: NOW)

    def generate(self, client, title="synthetic"):
        return client.generate({"title": title, "is_synthetic": True}, **REQUEST)

    def row(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute("SELECT * FROM calls ORDER BY rowid LIMIT 1").fetchone())

    def test_ten_yuan_and_individual_ceiling_are_exact(self):
        self.assertEqual(cny_policy().daily_limit, 10_000_000)
        self.assertEqual(estimate_cost(1, 1, 1, 1), 2)
        self.assertEqual(estimate_cost(500_000, 500_000, 1, 1), 2)
        self.assertEqual(estimate_cost(20, 8, 2_000_000, 8_000_000), 104)

    def test_cny_usage_is_never_labelled_usd(self):
        client = self.client()
        self.generate(client)
        usage = client.usage("2026-11-08")
        self.assertEqual(usage["currency"], "CNY")
        self.assertEqual(usage["charged_micro_cny"], 104)
        self.assertNotIn("charged_micro_usd", usage)
        self.assertEqual(usage["usage_reported_micro_cny"], 104)
        metadata = json.loads(self.row()["request_metadata"])
        self.assertEqual(metadata["budget_currency"], "CNY")
        self.assertEqual(metadata["input_micro_units_per_million_tokens"], 2_000_000)

    def test_retries_preserve_unknown_currency_budget(self):
        def timeout(*_):
            raise TimeoutError("never record this external text")
        client = self.client(replace(cny_policy(), max_retries=1), timeout)
        with self.assertRaisesRegex(ModelError, "transport_timeout"):
            self.generate(client)
        usage = client.usage("2026-11-08")
        self.assertEqual(usage["calls"], 2)
        self.assertGreater(usage["reserved_or_unknown_micro_cny"], 0)
        self.assertEqual(usage["charged_micro_cny"], usage["reserved_or_unknown_micro_cny"])
        self.assertNotIn(b"never record", self.path.read_bytes())

    def test_same_day_currency_change_cannot_reset_budget(self):
        self.generate(self.client())
        usd = self.client(Policy(enabled=True, max_retries=0))
        with self.assertRaisesRegex(ModelError, "daily_budget_policy_changed"):
            self.generate(usd, "different request")
        self.assertEqual(usd.usage("2026-11-08")["currency"], "CNY")

    def test_v1_migration_preserves_usd_calls_caps_and_pending(self):
        old = self.client(Policy(enabled=True, max_retries=0))
        self.generate(old)
        with closing(sqlite3.connect(self.path)) as db, db:
            before = db.execute("SELECT * FROM calls").fetchall()
            caps = db.execute("SELECT day,token_cap,cost_cap FROM days").fetchall()
            db.execute("ALTER TABLE days DROP COLUMN currency")
            db.execute("PRAGMA user_version=1")
        migrated = self.client(Policy(enabled=True, max_retries=0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT * FROM calls").fetchall(), before)
            self.assertEqual(db.execute("SELECT day,token_cap,cost_cap FROM days").fetchall(), caps)
            self.assertEqual(db.execute("SELECT currency FROM days").fetchone()[0], "USD")
        self.assertEqual(migrated.usage("2026-11-08")["charged_micro_usd"], 28)
        self.assertTrue(self.generate(migrated).cache_hit)

    def test_small_currency_budget_denies_before_transport(self):
        called = []
        client = self.client(cny_policy(daily_micro_units=1), lambda *_: called.append(True))
        with self.assertRaisesRegex(ModelError, "budget_exceeded"):
            self.generate(client)
        self.assertEqual(called, [])

    def test_invalid_currency_units_and_deepseek_cap_rejected(self):
        cases = ({"budget_currency": []}, {"budget_currency": "EUR"},
                 {"budget_currency": "CNY"}, {"daily_micro_units": True},
                 {"daily_micro_units": 10, "input_micro_units_per_million_tokens": 1},
                 {"provider": "deepseek", "model": "deepseek-flash", "enabled": True})
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ModelError):
                Policy(**values)
        with self.assertRaisesRegex(ModelError, "authorized_limit"):
            cny_policy(provider="deepseek", model="deepseek-flash", daily_micro_units=10_000_001)
        with self.assertRaisesRegex(ModelError, "upper_bound"):
            cny_policy(provider="deepseek", model="deepseek-flash", input_micro_units_per_million_tokens=1)

    def test_deepseek_uses_exact_transport_bound_and_persists_no_key(self):
        opener = FakeOpener(FakeResponse(completion()))
        transport = DeepSeekTransport("synthetic-cny-key", opener=opener)
        client = self.client(cny_policy(provider="deepseek", model="deepseek-flash"), transport)
        self.generate(client)
        row = self.row()
        metadata = json.loads(row["request_metadata"])
        wire = opener.requests[0][0].data
        self.assertEqual(metadata["input_bound"], len(wire) + 4096)
        self.assertEqual(row["reserved_tokens"], len(wire) + 4096 + 512)
        self.assertEqual(row["charged_cost"], 104)
        self.assertNotIn(b"synthetic-cny-key", self.path.read_bytes())

    def test_non_deepseek_transport_cannot_bypass_provider_checks(self):
        client = self.client(cny_policy(provider="deepseek", model="deepseek-flash"))
        with self.assertRaisesRegex(ModelError, "deepseek_transport_required"):
            self.generate(client)

    def test_provider_error_keeps_reservation_and_safe_reason(self):
        opener = FakeOpener(FakeResponse(b"private-provider-error", status=401))
        transport = DeepSeekTransport("synthetic-cny-key", opener=opener)
        client = self.client(cny_policy(provider="deepseek", model="deepseek-flash"), transport)
        with self.assertRaisesRegex(ModelError, "deepseek_authentication_failed"):
            self.generate(client)
        row = self.row()
        self.assertEqual(row["charged_cost"], row["reserved_cost"])
        self.assertEqual(row["error_code"], "deepseek_authentication_failed")
        self.assertNotIn(b"private-provider-error", self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
