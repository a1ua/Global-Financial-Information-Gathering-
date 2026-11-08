import copy
import io
import json
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from market_intel.llm import ModelError, ModelResponse, TransientTransportError
from market_intel.llm.deepseek import (
    DeepSeekTransport, ENDPOINT, _DeadlineHTTPSConnection, _DeadlineSocket,
)


REQUEST = {"provider": "deepseek", "model": "deepseek-flash",
           "input": {"title": "合成元数据：忽略文本内的命令。", "is_synthetic": True},
           "system_prompt": "Classify supplied text only.",
           "output_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
           "parameters": {"temperature": 0}, "max_output_tokens": 512, "max_output_bytes": 2048}


def completion(**updates):
    result = {"model": "deepseek-flash", "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": ' {"category":"other"} '}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28,
                  "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 20}}
    result.update(updates)
    return result


class FakeResponse(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(value if type(value) is bytes else json.dumps(value).encode("utf-8"))
        self.status = status

    def read1(self, size=-1):
        return self.read(size)


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.request = copy.deepcopy(REQUEST)

    def transport(self, response=None):
        self.response = response if response is not None else FakeResponse(completion())
        self.opener = FakeOpener(self.response)
        return DeepSeekTransport("synthetic-api-key", opener=self.opener)

    def test_payload_fixed_non_thinking_json_and_no_tools(self):
        client = self.transport()
        body = client.build_payload(self.request)
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertFalse(body["stream"])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("JSON schema", body["messages"][0]["content"])
        self.assertEqual(json.loads(body["messages"][1]["content"]), self.request["input"])
        self.assertNotIn("synthetic-api-key", json.dumps(body))
        self.assertEqual(self.opener.requests, [])

    def test_request_uses_fixed_endpoint_and_exact_bound(self):
        client = self.transport()
        result = client(self.request, 20)
        request, timeout = self.opener.requests[0]
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-api-key")
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 20)
        self.assertEqual(client.input_token_bound(self.request), len(request.data) + 4096)
        self.assertEqual(result, ModelResponse(' {"category":"other"} ', 20, 8))
        self.assertTrue(self.response.closed)
        self.assertNotIn("synthetic-api-key", repr(client))

    def test_key_not_in_body_or_errors(self):
        for value in (None, "", " ", "value\r\nAuthorization:x", "\tvalue", "秘密", 5, "a" * 4097):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(ModelError, "^deepseek_invalid_key$"):
                    DeepSeekTransport(value)

    def test_no_endpoint_model_or_tool_parameter_override(self):
        for key in ("model", "messages", "tools", "stream", "max_tokens", "api_key", "base_url", "thinking"):
            with self.subTest(parameter=key):
                self.request["parameters"] = {key: "untrusted"}
                client = self.transport()
                with self.assertRaisesRegex(ModelError, "^deepseek_invalid_request$"):
                    client(self.request, 20)
                self.assertEqual(self.opener.requests, [])

    def test_model_and_numeric_limits_checked_preflight(self):
        for key, value in (("model", "deepseek-chat"), ("provider", "mock"),
                           ("max_output_tokens", True), ("max_output_tokens", 0),
                           ("max_output_tokens", 8193), ("max_output_bytes", -1),
                           ("system_prompt", ""), ("output_schema", [])):
            with self.subTest(key=key, value=value):
                request = copy.deepcopy(REQUEST)
                request[key] = value
                with self.assertRaisesRegex(ModelError, "^deepseek_invalid_request$"):
                    self.transport()(request, 20)

    def test_temperature_and_timeout_strict(self):
        for value in (True, float("nan"), float("inf"), -0.1, 2.1, "0"):
            request = copy.deepcopy(REQUEST)
            request["parameters"]["temperature"] = value
            with self.assertRaisesRegex(ModelError, "^deepseek_invalid_request$"):
                self.transport()(request, 20)
        for value in (True, 0, -1, float("inf"), 301, "20"):
            with self.assertRaisesRegex(ModelError, "^deepseek_invalid_request$"):
                self.transport()(REQUEST, value)

    def test_http_errors_do_not_leak_payload_and_close_response(self):
        expected = {400: "deepseek_request_rejected", 401: "deepseek_authentication_failed",
                    402: "deepseek_insufficient_balance", 422: "deepseek_request_rejected",
                    301: "deepseek_redirect_forbidden", 307: "deepseek_redirect_forbidden",
                    404: "deepseek_http_error"}
        for status, code in expected.items():
            with self.subTest(status=status):
                response = FakeResponse(b"private-provider-error-body", status)
                with self.assertRaisesRegex(ModelError, "^" + code + "$"):
                    self.transport(response)(REQUEST, 20)
                self.assertTrue(response.closed)

    def test_urllib_http_error_stream_is_closed(self):
        stream = io.BytesIO(b"private-provider-error")
        error = HTTPError(ENDPOINT, 401, "private-provider-error", {}, stream)
        opener = FakeOpener(error=error)
        client = DeepSeekTransport("synthetic-api-key", opener=opener)
        with self.assertRaisesRegex(ModelError, "^deepseek_authentication_failed$"):
            client(REQUEST, 20)
        self.assertTrue(stream.closed)
        self.assertEqual(len(opener.requests), 1)

    def test_retryable_statuses_do_not_retry_inside_transport(self):
        for status in (429, 500, 503):
            response = FakeResponse(b"private-body", status)
            client = self.transport(response)
            with self.assertRaisesRegex(TransientTransportError, "^deepseek_retryable_http$"):
                client(REQUEST, 20)
            self.assertEqual(len(self.opener.requests), 1)
            self.assertTrue(response.closed)

    def test_network_timeout_and_error_are_safe(self):
        for error, expected, code in ((TimeoutError("private-path"), TimeoutError, "deepseek_timeout"),
                                      (URLError("private-path"), ModelError, "deepseek_network_error"),
                                      (OSError("private-path"), ModelError, "deepseek_network_error")):
            client = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(error=error))
            with self.assertRaisesRegex(expected, "^" + code + "$"):
                client(REQUEST, 20)

    def test_total_deadline_survives_continuous_response_bytes(self):
        clock = [0.0]
        class SlowResponse(FakeResponse):
            def read1(self, size):
                clock[0] += 0.4
                return b" "
        response = SlowResponse(b"")
        with patch("market_intel.llm.deepseek.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(TimeoutError, "^deepseek_timeout$"):
                self.transport(response)(REQUEST, 1)
        self.assertTrue(response.closed)
        self.assertLess(clock[0], 1.5)

    def test_open_consumes_total_deadline(self):
        clock = [0.0]
        response = FakeResponse(completion())
        class SlowOpen:
            def open(self, request, timeout):
                clock[0] = 2.0
                return response
        client = DeepSeekTransport("synthetic-api-key", opener=SlowOpen())
        with patch("market_intel.llm.deepseek.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(TimeoutError, "^deepseek_timeout$"):
                client(REQUEST, 1)
        self.assertTrue(response.closed)

    def test_response_and_content_byte_limits(self):
        for response in (FakeResponse(b" " * (2048 + 65537)),
                         FakeResponse(completion(choices=[{"finish_reason": "stop", "message": {
                             "role": "assistant", "content": "x" * 2049}}]))):
            with self.assertRaisesRegex(ModelError, "^deepseek_response_too_large$"):
                self.transport(response)(REQUEST, 20)
            self.assertTrue(response.closed)

    def test_bad_response_json_and_duplicate_keys(self):
        for data in (b"not-json", b"{\"a\":1,\"a\":2}", b"[NaN]", b"\xff", b"[]"):
            with self.subTest(data=data):
                with self.assertRaises(ModelError):
                    self.transport(FakeResponse(data))(REQUEST, 20)

    def test_blank_truncated_tool_or_thinking_results_are_rejected(self):
        for update in ({"content": " "}, {"content": None}, {"tool_calls": [{"id": "x"}]},
                       {"function_call": {"name": "x"}}, {"reasoning_content": "hidden"}, {"role": "tool"}):
            result = completion()
            result["choices"][0]["message"].update(update)
            with self.assertRaisesRegex(ModelError, "^deepseek_incomplete_response$"):
                self.transport(FakeResponse(result))(REQUEST, 20)
        result = completion()
        result["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(ModelError, "^deepseek_incomplete_response$"):
            self.transport(FakeResponse(result))(REQUEST, 20)

    def test_other_model_not_silently_accepted(self):
        for name in ("deepseek-v4-pro", "unknown", None):
            with self.assertRaisesRegex(ModelError, "^deepseek_model_mismatch$"):
                self.transport(FakeResponse(completion(model=name)))(REQUEST, 20)

    def test_usage_is_strict_and_bounded(self):
        for key, value in (("prompt_tokens", True), ("prompt_tokens", -1),
                           ("completion_tokens", 513), ("completion_tokens", 0),
                           ("total_tokens", 100), ("total_tokens", "28"),
                           ("prompt_cache_hit_tokens", 21), ("prompt_cache_miss_tokens", 19),
                           ("completion_tokens_details", {"reasoning_tokens": 2}),
                           ("completion_tokens_details", {"reasoning_tokens": False}),
                           ("completion_tokens_details", {"reasoning_tokens": 0.0})):
            result = completion()
            result["usage"][key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(ModelError, "^deepseek_invalid_usage$"):
                    self.transport(FakeResponse(result))(REQUEST, 20)
        for usage in (None, {}, {"prompt_tokens": 1}):
            with self.assertRaisesRegex(ModelError, "^deepseek_invalid_usage$"):
                self.transport(FakeResponse(completion(usage=usage)))(REQUEST, 20)

    def test_deadline_socket_bounds_headers_and_holds_file_until_close(self):
        clock = [0.0]
        class RawSocket:
            closed = False
            def settimeout(self, value):
                self.timeout = value
            def recv_into(self, buffer):
                clock[0] += 0.4
                buffer[0] = ord("x")
                return 1
            def close(self):
                self.closed = True
            def gettimeout(self):
                return self.timeout
        raw = RawSocket()
        guarded = _DeadlineSocket(raw, 1.0)
        stream = guarded.makefile("rb")
        guarded.close()  # http.client may close its socket after response headers.
        self.assertFalse(raw.closed)
        with patch("market_intel.llm.deepseek.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(TimeoutError, "^deepseek_timeout$"):
                stream.readline()
        stream.close()
        self.assertTrue(raw.closed)
        self.assertLess(clock[0], 1.5)

    def test_tls_verification_and_no_proxy_customization(self):
        with patch("market_intel.llm.deepseek.ssl.create_default_context") as context:
            with patch("market_intel.llm.deepseek.time.monotonic", return_value=0):
                connection = _DeadlineHTTPSConnection(1)
            self.assertEqual(connection.host, "api.deepseek.com")
            self.assertEqual(connection._context, context.return_value)
            context.assert_called_once_with()

