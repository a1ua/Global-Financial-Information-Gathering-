import copy
import hashlib
import unittest
from unittest.mock import patch
from urllib.error import URLError

from market_intel.llm import ModelError
from market_intel.llm.client import ObservedTransportError
from market_intel.llm.deepseek import DeepSeekTransport
from test_deepseek import FakeOpener, FakeResponse, REQUEST, completion


class DeepSeekFailureCorrelationTests(unittest.TestCase):
    def invoke_error(self, value, code, *, observed=False, status=200):
        response = FakeResponse(value, status=status)
        transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(response))
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            with self.assertRaisesRegex(ModelError, "^" + code + "$") as raised:
                transport(copy.deepcopy(REQUEST), 20)
        error = raised.exception
        self.assertEqual(isinstance(error, ObservedTransportError), observed)
        self.assertTrue(response.closed)
        self.assertNotIn("synthetic-api-key", str(error))
        if observed:
            self.assertEqual(error.response_id_sha256, hashlib.sha256(value["id"].encode()).hexdigest())
            self.assertEqual(set(vars(error)), {"response_id_sha256"})
            self.assertEqual(error.args, (code,))
            self.assertNotIn(value["id"], repr(error))
            self.assertNotIn("private-body-marker", repr(vars(error)))
        else:
            self.assertFalse(hasattr(error, "response_id_sha256"))
        return error

    def test_incomplete_finish_keeps_safe_hash_only(self):
        value = completion(id="synthetic-completion-failed")
        value["choices"][0].update(finish_reason="length")
        value["choices"][0]["message"]["content"] = "private-body-marker"
        self.invoke_error(value, "deepseek_incomplete_response", observed=True)

    def test_incomplete_usage_keeps_hash_and_does_not_retain_usage(self):
        for usage in (None, {}, {"prompt_tokens": True, "completion_tokens": 8, "total_tokens": 9},
                      {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 1}):
            with self.subTest(usage=usage):
                self.invoke_error(completion(id="synthetic-usage-failed", usage=usage),
                                  "deepseek_invalid_usage", observed=True)

    def test_content_limit_inside_parsed_response_can_keep_hash(self):
        value = completion(id="synthetic-content-limit")
        value["choices"][0]["message"]["content"] = "x" * (REQUEST["max_output_bytes"] + 1)
        self.invoke_error(value, "deepseek_response_too_large", observed=True)

    def test_missing_or_invalid_id_does_not_replace_original_error(self):
        for identity in (None, True, "private marker", "A" * 257, "秘密", ""):
            value = completion(id=identity)
            value["choices"][0]["finish_reason"] = "length"
            with self.subTest(identity_type=type(identity).__name__):
                self.invoke_error(value, "deepseek_incomplete_response")
        value = completion()
        value["usage"] = {}
        self.invoke_error(value, "deepseek_invalid_usage")
        value = completion(id="private marker", usage={})
        self.invoke_error(value, "deepseek_invalid_usage")

    def test_wrong_model_and_bad_json_cannot_create_observation(self):
        self.invoke_error(completion(id="synthetic-id", model="other-model"), "deepseek_model_mismatch")
        self.invoke_error(b'{"id":"synthetic-id","model":"deepseek-flash",', "deepseek_invalid_response")
        self.invoke_error(b'{"id":"synthetic-id","id":"second"}', "deepseek_invalid_response")

    def test_http_wire_limit_timeout_and_network_do_not_keep_hash(self):
        self.invoke_error(completion(id="synthetic-http-failure"), "deepseek_authentication_failed", status=401)
        self.invoke_error(b"x" * (REQUEST["max_output_bytes"] + 65537), "deepseek_response_too_large")
        for exception, expected in ((TimeoutError("private timeout"), TimeoutError),
                                    (URLError("private network"), ModelError)):
            transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(error=exception))
            with self.assertRaises(expected) as raised:
                transport(copy.deepcopy(REQUEST), 20)
            self.assertFalse(isinstance(raised.exception, ObservedTransportError))
            self.assertFalse(hasattr(raised.exception, "response_id_sha256"))
            self.assertNotIn("private", str(raised.exception))

    def test_failure_never_reads_headers_and_ignores_request_id(self):
        class ForbiddenHeaders(FakeResponse):
            @property
            def headers(self):
                raise AssertionError("headers forbidden")

            def getheader(self, *args):
                raise AssertionError("header request id forbidden")

        value = completion(id="synthetic-header-ignored", request_id="unverified-request")
        value["choices"][0]["finish_reason"] = "length"
        response = ForbiddenHeaders(value)
        transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(response))
        with self.assertRaises(ObservedTransportError) as raised:
            transport(copy.deepcopy(REQUEST), 20)
        self.assertEqual(raised.exception.response_id_sha256,
                         hashlib.sha256(value["id"].encode()).hexdigest())
        self.assertNotIn("unverified-request", repr(vars(raised.exception)))
        self.assertTrue(response.closed)

    def test_unknown_model_error_is_not_promoted(self):
        transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener())
        with patch.object(transport, "_parse_result", side_effect=ModelError("unrecognized_safe_code")):
            with self.assertRaisesRegex(ModelError, "^unrecognized_safe_code$") as raised:
                transport._parse(completion(id="synthetic-id"), copy.deepcopy(REQUEST))
        self.assertNotIsInstance(raised.exception, ObservedTransportError)


if __name__ == "__main__":
    unittest.main()
