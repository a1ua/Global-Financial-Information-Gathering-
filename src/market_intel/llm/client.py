"""Provider-neutral model node; all transport attempts reserve budget first."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import math
import re
from pathlib import Path
import sqlite3
import uuid

from market_intel.contracts import ContractError, instant
from .correlation import validate_call_correlation, validate_response_hash


class ModelError(ValueError):
    """Stable error code, without provider payloads or exception text."""


class TransientTransportError(Exception):
    """Transport explicitly reports a retryable error; payload is never logged."""


def _fail(code):
    raise ModelError(code)


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 10**12


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("invalid_json_input")


def _strict_loads(text):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: _fail("nonfinite_json"))
    except ModelError:
        raise
    except (ValueError, TypeError, RecursionError):
        _fail("invalid_output_json")


def _safe_json(value, depth=0):
    """Reject non-JSON values and credential-bearing config keys before storage."""
    if depth > 40:
        _fail("json_depth_exceeded")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeError:
                _fail("invalid_unicode")
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _safe_json(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail("invalid_json_input")
            # Credentials belong to the injected transport, never request/config data.
            if key.lower().replace("-", "_") in {
                "api_key", "authorization", "access_token", "refresh_token",
                "password", "secret", "credential", "credentials",
            }:
                _fail("credential_field_forbidden")
            _safe_json(key)
            _safe_json(item, depth + 1)
        return
    _fail("invalid_json_input")


_SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "items",
                "enum", "minLength", "maxLength", "minimum", "maximum",
                "minItems", "maxItems", "description"}
_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def _schema(schema, depth=0):
    if depth > 20 or type(schema) is not dict or set(schema) - _SCHEMA_KEYS:
        _fail("unsupported_output_schema")
    if type(schema.get("type")) is not str or schema["type"] not in _TYPES:
        _fail("unsupported_output_schema")
    typ = schema["type"]
    allowed = {"type", "enum", "description"}
    allowed |= {"object": {"properties", "required", "additionalProperties"},
                "array": {"items", "minItems", "maxItems"},
                "string": {"minLength", "maxLength"},
                "integer": {"minimum", "maximum"},
                "number": {"minimum", "maximum"}}.get(typ, set())
    if set(schema) - allowed:
        _fail("unsupported_output_schema")
    if "description" in schema and type(schema["description"]) is not str:
        _fail("unsupported_output_schema")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        _fail("unsupported_output_schema")
    if typ == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if type(properties) is not dict or type(required) is not list:
            _fail("unsupported_output_schema")
        if any(type(k) is not str for k in required) or len(set(required)) != len(required):
            _fail("unsupported_output_schema")
        if not set(required) <= set(properties) or type(schema.get("additionalProperties", False)) is not bool:
            _fail("unsupported_output_schema")
        for child in properties.values():
            _schema(child, depth + 1)
    if typ == "array":
        if "items" not in schema:
            _fail("unsupported_output_schema")
        _schema(schema["items"], depth + 1)
    for low, high in (("minLength", "maxLength"), ("minItems", "maxItems")):
        for key in (low, high):
            if key in schema and not _integer(schema[key]):
                _fail("unsupported_output_schema")
        if low in schema and high in schema and schema[low] > schema[high]:
            _fail("unsupported_output_schema")
    for key in ("minimum", "maximum"):
        if key in schema and (type(schema[key]) not in (int, float) or (type(schema[key]) is float and not math.isfinite(schema[key]))):
            _fail("unsupported_output_schema")
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        _fail("unsupported_output_schema")


def _matches(value, schema):
    typ = schema["type"]
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    if typ == "number":
        valid = type(value) is int or (type(value) is float and math.isfinite(value))
    else:
        valid = type(value) is kinds[typ]
    if not valid:
        return False
    if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
        return False
    if typ == "object":
        props = schema.get("properties", {})
        if not set(schema.get("required", [])) <= value.keys():
            return False
        if not schema.get("additionalProperties", False) and set(value) - props.keys():
            return False
        return all(_matches(v, props[k]) for k, v in value.items() if k in props)
    if typ == "array":
        if not all(_matches(v, schema["items"]) for v in value):
            return False
        return schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10**12)
    if typ == "string":
        return schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 10**12)
    if typ in {"number", "integer"}:
        return schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf)
    return True


@dataclass(frozen=True)
class Policy:
    provider: str = "mock"
    model: str = "mock-structured-v1"
    enabled: bool = False
    daily_tokens: int = 100_000
    daily_micro_usd: int = 100_000
    max_input_bytes: int = 8192
    max_input_tokens: int = 8192
    max_output_tokens: int = 512
    max_output_bytes: int = 8192
    input_micro_usd_per_token: int = 1
    output_micro_usd_per_token: int = 1
    max_retries: int = 1
    timeout_seconds: int = 30
    budget_currency: str = "USD"
    daily_micro_units: int | None = None
    input_micro_units_per_million_tokens: int | None = None
    output_micro_units_per_million_tokens: int | None = None

    def __post_init__(self):
        for key in ("provider", "model"):
            value = getattr(self, key)
            if type(value) is not str or not value or len(value) > 128 or not all(c.isalnum() or c in "_.-/" for c in value):
                _fail("invalid_policy")
        if type(self.enabled) is not bool:
            _fail("invalid_policy")
        if self.enabled and self.provider not in {"mock", "deepseek"}:
            _fail("live_provider_not_implemented")
        if type(self.budget_currency) is not str or self.budget_currency not in {"USD", "CNY"}:
            _fail("invalid_budget_currency")
        generic = (self.daily_micro_units, self.input_micro_units_per_million_tokens,
                   self.output_micro_units_per_million_tokens)
        if any(value is not None for value in generic):
            if not all(_integer(value, 1) for value in generic):
                _fail("invalid_budget_units")
        elif self.budget_currency != "USD":
            _fail("explicit_currency_budget_required")
        for key in ("daily_tokens", "daily_micro_usd", "max_input_bytes", "max_input_tokens",
                    "max_output_tokens", "max_output_bytes", "timeout_seconds"):
            if not _integer(getattr(self, key), 1):
                _fail("invalid_policy")
        for key in ("input_micro_usd_per_token", "output_micro_usd_per_token", "max_retries"):
            if not _integer(getattr(self, key)):
                _fail("invalid_policy")
        if self.max_retries > 5 or self.timeout_seconds > 300:
            _fail("invalid_policy")
        if self.max_input_tokens * self.input_micro_usd_per_token + self.max_output_tokens * self.output_micro_usd_per_token > 10**15:
            _fail("invalid_policy")
        if self.provider == "deepseek":
            if self.model != "deepseek-flash" or self.budget_currency != "CNY":
                _fail("invalid_deepseek_policy")
            if self.daily_limit > 10_000_000:
                _fail("deepseek_budget_exceeds_authorized_limit")
            if self.input_rate < 2_000_000 or self.output_rate < 8_000_000:
                _fail("deepseek_rate_below_verified_upper_bound")

    @property
    def daily_limit(self):
        return self.daily_micro_units if self.daily_micro_units is not None else self.daily_micro_usd

    @property
    def input_rate(self):
        return (self.input_micro_units_per_million_tokens if self.input_micro_units_per_million_tokens is not None
                else self.input_micro_usd_per_token * 1_000_000)

    @property
    def output_rate(self):
        return (self.output_micro_units_per_million_tokens if self.output_micro_units_per_million_tokens is not None
                else self.output_micro_usd_per_token * 1_000_000)


def estimate_cost(input_tokens, output_tokens, input_rate, output_rate):
    """Integer currency micro-units; round each token direction upwards."""
    return ((input_tokens * input_rate + 999_999) // 1_000_000
            + (output_tokens * output_rate + 999_999) // 1_000_000)


def _ledger_identity(db):
    try:
        rows = db.execute("SELECT singleton,ledger_id,created_at FROM ledger_identity").fetchall()
        if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not str or not re.fullmatch(r"ledger_[0-9a-f]{32}", rows[0][1]):
            _fail("ledger_identity_invalid")
        instant(rows[0][2], "ledger_identity.created_at")
        return rows[0][1]
    except (sqlite3.Error, ContractError):
        raise ModelError("ledger_identity_invalid") from None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_id_sha256: str | None = None


@dataclass(frozen=True)
class CallResult:
    value: dict
    call_id: str
    cache_hit: bool


class ModelClient:
    """transport(request: dict, timeout_seconds: int) -> ModelResponse.

    Transport must enforce timeout/output-token limits, and report trusted usage
    only when its provider guarantees it. It must not log credentials/payloads.
    """

    def __init__(self, state_path, policy=None, transport=None, *, clock=None):
        self.policy = policy if policy is not None else Policy()
        if type(self.policy) is not Policy:
            _fail("invalid_policy")
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                _fail("unsupported_ledger_schema")
            if version == 0:
                db.execute("""CREATE TABLE days (
                    day TEXT PRIMARY KEY, token_cap INTEGER NOT NULL, cost_cap INTEGER NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'USD')""")
                db.execute("""CREATE TABLE calls (
                    call_id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, day TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, attempt INTEGER NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
                    reserved_tokens INTEGER NOT NULL, reserved_cost INTEGER NOT NULL,
                    charged_tokens INTEGER NOT NULL, charged_cost INTEGER NOT NULL,
                    input_tokens INTEGER, output_tokens INTEGER, output_text TEXT,
                    output_sha256 TEXT, error_code TEXT, request_metadata TEXT NOT NULL)""")
                db.execute("CREATE INDEX calls_day ON calls(day)")
                db.execute("CREATE TABLE cache (cache_key TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES calls(call_id))")
                version = 2
            elif version == 1:
                db.execute("ALTER TABLE days ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
                version = 2
            if version == 2:
                db.execute("""CREATE TABLE ledger_identity (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    ledger_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)""")
                stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
                db.execute("INSERT INTO ledger_identity VALUES(1,?,?)", ("ledger_" + uuid.uuid4().hex, stamp))
                db.execute("PRAGMA user_version=3")
            self.ledger_id = _ledger_identity(db)

    @contextmanager
    def _connect(self):
        db = None
        try:
            pinned_id = getattr(self, "ledger_id", None)
            if pinned_id:
                if not self.path.is_file():
                    _fail("bound_ledger_missing")
                db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
            else:
                db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if pinned_id and _ledger_identity(db) != pinned_id:
                _fail("ledger_identity_mismatch")
            with db:
                yield db
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", 0)
            busy = (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            raise ModelError("ledger_busy" if busy else "ledger_error") from None
        finally:
            if db is not None:
                try:
                    db.close()
                except sqlite3.Error:
                    raise ModelError("ledger_error") from None

    def _now(self):
        moment = self.clock()
        if type(moment) is not datetime or moment.tzinfo is None or moment.utcoffset() != timezone.utc.utcoffset(moment):
            _fail("utc_clock_required")
        return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def _reserve(self, key, attempt, input_bound, metadata):
        stamp = self._now()
        day = stamp[:10]
        policy = self.policy
        tokens = input_bound + policy.max_output_tokens
        cost = estimate_cost(input_bound, policy.max_output_tokens, policy.input_rate, policy.output_rate)
        call_id = "call_" + uuid.uuid4().hex
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                stored_days = [date.fromisoformat(row[0]) for row in db.execute("SELECT day FROM days")]
                current_day = date.fromisoformat(day)
            except (ValueError, TypeError):
                _fail("ledger_time_invalid")
            if stored_days and current_day < max(stored_days):
                _fail("clock_regression")
            db.execute("INSERT OR IGNORE INTO days(day,token_cap,cost_cap,currency) VALUES(?,?,?,?)",
                       (day, policy.daily_tokens, policy.daily_limit, policy.budget_currency))
            caps = db.execute("SELECT token_cap,cost_cap,currency FROM days WHERE day=?", (day,)).fetchone()
            if tuple(caps) != (policy.daily_tokens, policy.daily_limit, policy.budget_currency):
                _fail("daily_budget_policy_changed")
            used = db.execute("SELECT COALESCE(SUM(charged_tokens),0),COALESCE(SUM(charged_cost),0) FROM calls WHERE day=?", (day,)).fetchone()
            if used[0] + tokens > caps[0] or used[1] + cost > caps[1]:
                _fail("budget_exceeded")
            db.execute("""INSERT INTO calls(call_id,cache_key,day,started_at,attempt,provider,model,status,
                       reserved_tokens,reserved_cost,charged_tokens,charged_cost,request_metadata)
                       VALUES(?,?,?,?,?,?,?,'pending',?,?,?,?,?)""",
                       (call_id, key, day, stamp, attempt, policy.provider, policy.model, tokens, cost, tokens, cost, _json(metadata)))
        return call_id

    def _finish(self, call_id, status, *, response=None, output=None, error=None):
        stamp = self._now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
            if not row or row["status"] != "pending":
                _fail("invalid_call_state")
            try:
                finished = instant(stamp, "ledger.finished_at")
                started = instant(row["started_at"], "ledger.started_at")
            except ContractError:
                _fail("ledger_time_invalid")
            if finished < started:
                _fail("clock_regression")
            tokens, cost = row["reserved_tokens"], row["reserved_cost"]
            metadata = _strict_loads(row["request_metadata"])
            max_output = metadata["max_output_tokens"]
            input_rate = metadata.get("input_micro_units_per_million_tokens",
                                      metadata["input_micro_usd_per_token"] * 1_000_000)
            output_rate = metadata.get("output_micro_units_per_million_tokens",
                                       metadata["output_micro_usd_per_token"] * 1_000_000)
            incoming = outgoing = None
            if response and _integer(response.input_tokens, 1) and _integer(response.output_tokens, 1):
                incoming, outgoing = response.input_tokens, response.output_tokens
                actual_cost = estimate_cost(incoming, outgoing, input_rate, output_rate)
                if incoming <= metadata["input_bound"] and incoming + outgoing <= tokens and actual_cost <= cost and outgoing <= max_output:
                    tokens, cost = incoming + outgoing, actual_cost
                else:
                    incoming = outgoing = None
            output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest() if output is not None else None
            if status == "succeeded" and incoming is not None and outgoing is not None:
                try:
                    validate_response_hash(response.response_id_sha256)
                except ValueError:
                    _fail("invalid_provider_response")
                metadata["provider_response"] = {
                    "schema_version": "provider-response-correlation/0.1",
                    "response_id_sha256": response.response_id_sha256,
                    "input_tokens": incoming, "output_tokens": outgoing,
                }
            db.execute("""UPDATE calls SET status=?,finished_at=?,charged_tokens=?,charged_cost=?,
                       input_tokens=?,output_tokens=?,output_text=?,output_sha256=?,error_code=?,request_metadata=? WHERE call_id=?""",
                       (status, stamp, tokens, cost, incoming, outgoing, output, output_hash, error, _json(metadata), call_id))
            if status == "succeeded":
                db.execute("INSERT OR IGNORE INTO cache VALUES(?,?)", (row["cache_key"], call_id))

    def generate(self, input_data, *, system_prompt, prompt_version, rules_version,
                 output_schema, schema_version, parameters=None):
        policy = self.policy
        if not policy.enabled:
            _fail("model_disabled")
        if not callable(self.transport):
            _fail("transport_required")
        for value in (system_prompt, prompt_version, rules_version, schema_version):
            if type(value) is not str or not value.strip():
                _fail("invalid_request")
        if type(parameters if parameters is not None else {}) is not dict:
            _fail("invalid_request")
        _safe_json(input_data)
        _safe_json(output_schema)
        _safe_json(parameters)
        _schema(output_schema)
        if output_schema["type"] != "object":
            _fail("object_output_required")
        request = {"provider": policy.provider, "model": policy.model,
                   "input": input_data, "system_prompt": system_prompt,
                   "prompt_version": prompt_version, "rules_version": rules_version,
                   "output_schema": output_schema, "schema_version": schema_version,
                   "parameters": parameters or {}, "max_output_tokens": policy.max_output_tokens,
                   "max_output_bytes": policy.max_output_bytes}
        if policy.provider == "deepseek":
            from .deepseek import DeepSeekTransport
            if not isinstance(self.transport, DeepSeekTransport):
                _fail("deepseek_transport_required")
            request["transport_version"] = self.transport.version
        _safe_json(request)
        encoded = _json(request).encode("utf-8")
        # One token per UTF-8 byte is a deliberately conservative transport contract.
        input_bound = self.transport.input_token_bound(request) if policy.provider == "deepseek" else len(encoded)
        if len(encoded) > policy.max_input_bytes or not _integer(input_bound, 1) or input_bound > policy.max_input_tokens:
            _fail("input_limit_exceeded")
        key = hashlib.sha256(b"model-request/0.1\0" + encoded).hexdigest()
        metadata = {"prompt_version": prompt_version, "rules_version": rules_version,
                    "schema_version": schema_version, "parameters": parameters or {},
                    "input_sha256": hashlib.sha256(_json(input_data).encode("utf-8")).hexdigest(),
                    "prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
                    "output_schema": output_schema, "max_output_tokens": policy.max_output_tokens,
                    "max_output_bytes": policy.max_output_bytes, "input_bound": input_bound,
                    "input_micro_usd_per_token": policy.input_micro_usd_per_token,
                    "output_micro_usd_per_token": policy.output_micro_usd_per_token,
                    "budget_currency": policy.budget_currency,
                    "input_micro_units_per_million_tokens": policy.input_rate,
                    "output_micro_units_per_million_tokens": policy.output_rate,
                    "accounting_basis": "configured_rate_estimate"}
        with self._connect() as db:
            cached = db.execute("SELECT calls.* FROM cache JOIN calls USING(call_id) WHERE cache.cache_key=?", (key,)).fetchone()
        if cached:
            try:
                validate_call_correlation(_strict_loads(cached["request_metadata"]), cached)
            except (ValueError, TypeError, KeyError):
                _fail("cache_integrity_error")
            text = cached["output_text"]
            if cached["cache_key"] != key or cached["status"] != "succeeded" or type(text) is not str or hashlib.sha256(text.encode("utf-8")).hexdigest() != cached["output_sha256"]:
                _fail("cache_integrity_error")
            value = _strict_loads(text)
            if not _matches(value, output_schema):
                _fail("cache_integrity_error")
            return CallResult(value, cached["call_id"], True)
        last_error = "transport_error"
        for attempt in range(policy.max_retries + 1):
            call_id = self._reserve(key, attempt + 1, input_bound, metadata)
            response = None
            retryable = True
            try:
                # A new deep copy prevents transport mutation from changing future retries.
                response = self.transport(json.loads(encoded), policy.timeout_seconds)
            except TimeoutError:
                last_error = "transport_timeout"
            except TransientTransportError:
                last_error = "transport_transient_error"
            except ModelError as error:
                last_error = "transport_error"
                if policy.provider == "deepseek":
                    from .deepseek import ERROR_CODES
                    if str(error) in ERROR_CODES:
                        last_error = str(error)
                retryable = False
            except Exception:
                last_error = "transport_error"
                retryable = False
            else:
                try:
                    if type(response) is not ModelResponse or type(response.text) is not str:
                        _fail("invalid_transport_response")
                    try:
                        validate_response_hash(response.response_id_sha256)
                    except ValueError:
                        _fail("invalid_provider_response")
                    if (response.input_tokens is None) != (response.output_tokens is None):
                        _fail("invalid_usage")
                    if response.input_tokens is not None and (not _integer(response.input_tokens) or response.input_tokens > input_bound):
                        _fail("invalid_usage")
                    if len(response.text.encode("utf-8")) > policy.max_output_bytes:
                        _fail("output_limit_exceeded")
                    if response.output_tokens is not None and (not _integer(response.output_tokens) or response.output_tokens > policy.max_output_tokens):
                        _fail("output_token_limit_exceeded")
                    if not (_integer(response.input_tokens, 1) and _integer(response.output_tokens, 1)) and len(response.text.encode("utf-8")) > policy.max_output_tokens:
                        _fail("output_token_bound_exceeded")
                    value = _strict_loads(response.text)
                    _safe_json(value)
                    if not _matches(value, output_schema):
                        _fail("output_schema_mismatch")
                    _json(value)
                except (ModelError, UnicodeError, RecursionError) as error:
                    last_error = str(error) if type(error) is ModelError else "invalid_output_json"
                else:
                    self._finish(call_id, "succeeded", response=response, output=response.text)
                    return CallResult(value, call_id, False)
            # Failed/malformed output is not retained. Unknown spend stays reserved.
            self._finish(call_id, "failed", error=last_error)
            if not retryable:
                break
        _fail(last_error)

    def usage(self, day):
        """Return consumed plus unresolved reservations for an explicit UTC date."""
        try:
            if type(day) is not str or datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
                _fail("invalid_day")
        except (ValueError, TypeError):
            _fail("invalid_day")
        with self._connect() as db:
            bucket = db.execute("SELECT currency FROM days WHERE day=?", (day,)).fetchone()
            currency = bucket[0] if bucket else self.policy.budget_currency
            row = db.execute("""SELECT COUNT(*),COALESCE(SUM(charged_tokens),0),COALESCE(SUM(charged_cost),0),
                             COALESCE(SUM(status='pending'),0),
                             COALESCE(SUM(CASE WHEN input_tokens IS NULL THEN charged_tokens ELSE 0 END),0),
                             COALESCE(SUM(CASE WHEN input_tokens IS NOT NULL THEN charged_tokens ELSE 0 END),0),
                             COALESCE(SUM(CASE WHEN input_tokens IS NULL THEN charged_cost ELSE 0 END),0),
                             COALESCE(SUM(CASE WHEN input_tokens IS NOT NULL THEN charged_cost ELSE 0 END),0)
                             FROM calls WHERE day=?""", (day,)).fetchone()
        suffix = "micro_usd" if currency == "USD" else "micro_cny"
        result = {"calls": row[0], "charged_tokens": row[1], f"charged_{suffix}": row[2], "pending_calls": row[3],
                "accounting_basis": "configured_rate_estimate", "reserved_or_unknown_tokens": row[4],
                "usage_reported_tokens": row[5], f"reserved_or_unknown_{suffix}": row[6],
                f"usage_reported_{suffix}": row[7]}
        if currency != "USD":
            result["currency"] = currency
        return result
