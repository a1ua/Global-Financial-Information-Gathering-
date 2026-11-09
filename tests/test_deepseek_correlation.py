import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from market_intel.llm import ModelError
from market_intel.llm.deepseek import DeepSeekTransport
from test_deepseek import FakeOpener, FakeResponse, REQUEST, completion


class DeepSeekCorrelationTests(unittest.TestCase):
    def invoke(self, value):
        response = FakeResponse(value)
        transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(response))
        with patch("socket.create_connection", side_effect=AssertionError("no network")):
            result = transport(copy.deepcopy(REQUEST), 20)
        self.assertTrue(response.closed)
        return result

    def test_id_hashes_exact_bytes_and_does_not_return_original_id(self):
        identity = "synthetic-completion-0123456789_ABC.test"
        value = completion(id=identity, request_id="not-a-completion-id")
        result = self.invoke(value)
        self.assertEqual(result.response_id_sha256, hashlib.sha256(identity.encode("ascii")).hexdigest())
        self.assertEqual((result.input_tokens, result.output_tokens), (20, 8))
        self.assertNotIn(identity, repr(result))
        self.assertNotIn("request_id", vars(result))
        self.assertNotIn("not-a-completion-id", repr(result))
        self.assertEqual(json.loads(result.text), {"category": "other"})

    def test_missing_id_preserves_legacy_response_without_fabricating_hash(self):
        result = self.invoke(completion())
        self.assertIsNone(result.response_id_sha256)

    def test_local_id_length_boundary_is_accepted(self):
        for identity in ("x", "A" * 256):
            with self.subTest(length=len(identity)):
                result = self.invoke(completion(id=identity))
                self.assertEqual(result.response_id_sha256, hashlib.sha256(identity.encode()).hexdigest())

    def test_present_invalid_id_rejects_with_fixed_error_and_closes_response(self):
        values = (None, True, 12, 1.2, [], {}, "", "A" * 257, "private payload", "private\nmarker", "秘密", "\ud800", "../private")
        for identity in values:
            with self.subTest(identity_type=type(identity).__name__):
                response = FakeResponse(completion(id=identity))
                transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(response))
                with self.assertRaisesRegex(ModelError, "^deepseek_invalid_response$") as raised:
                    transport(copy.deepcopy(REQUEST), 20)
                self.assertNotIn("private", str(raised.exception))
                self.assertNotIn("synthetic-api-key", str(raised.exception))
                self.assertTrue(response.closed)

    def test_does_not_read_headers_or_substitute_request_id(self):
        class HeaderForbiddenResponse(FakeResponse):
            @property
            def headers(self):
                raise AssertionError("must not read headers")

            def getheader(self, *args):
                raise AssertionError("must not read HTTP request id")

        response = HeaderForbiddenResponse(completion(request_id="unverified-http-request"))
        transport = DeepSeekTransport("synthetic-api-key", opener=FakeOpener(response))
        result = transport(copy.deepcopy(REQUEST), 20)
        self.assertIsNone(result.response_id_sha256)
        self.assertTrue(response.closed)

    def test_hashing_is_only_attempted_after_existing_response_validation(self):
        value = completion(id="private marker")
        value["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(ModelError, "^deepseek_incomplete_response$"):
            self.invoke(value)
        value = completion(id="private marker")
        value["usage"]["total_tokens"] = 1
        with self.assertRaisesRegex(ModelError, "^deepseek_invalid_usage$"):
            self.invoke(value)


if __name__ == "__main__":
    unittest.main()
