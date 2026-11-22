from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import BytesIO, StringIO, TextIOWrapper
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import TestCase
from unittest.mock import Mock, patch

from market_intel.cli import main
from market_intel.llm.correlation import response_id_sha256


COMMAND = "hash-provider-response-id"
SAMPLE = b"fixture-Response_ID.01"


class ResponseHashCLITests(TestCase):
    def setUp(self):
        self.enterContext(patch("market_intel.cli.connect", side_effect=AssertionError("workspace opened")))
        self.enterContext(patch("market_intel.cli.DeepSeekTransport", side_effect=AssertionError("transport opened")))

    def run_cli(self, stream):
        out, err = StringIO(), StringIO()
        with patch("sys.stdin", stream), redirect_stdout(out), redirect_stderr(err):
            code = main([COMMAND])
        return code, out.getvalue(), err.getvalue()

    def assert_input_error(self, stream, expected):
        code, out, err = self.run_cli(stream)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["reason"], expected)
        self.assertNotIn(SAMPLE.decode("ascii"), err)

    def test_module_entrypoint_returns_only_the_existing_correlation_hash(self):
        source = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "market_intel", COMMAND],
            input=SAMPLE + b"\r\n", capture_output=True, check=False, timeout=15,
            env={**os.environ, "PYTHONPATH": source},
        )
        self.assertEqual((proc.returncode, proc.stderr), (0, b""))
        digest = sha256(SAMPLE).hexdigest()
        self.assertEqual(json.loads(proc.stdout), {"response_id_sha256": digest})
        self.assertEqual(response_id_sha256(SAMPLE.decode("ascii")), digest)
        self.assertNotIn(SAMPLE, proc.stdout)

    def test_maximum_id_is_accepted_with_each_supported_line_ending(self):
        identifier = b"A" * 256
        for ending in (b"", b"\n", b"\r\n"):
            with self.subTest(ending=ending), TextIOWrapper(BytesIO(identifier + ending)) as stream:
                code, out, err = self.run_cli(stream)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out), {"response_id_sha256": sha256(identifier).hexdigest()})

    def test_invalid_input_does_not_leak_into_error(self):
        for payload in (
                b"", SAMPLE + b"\r", SAMPLE + b"\n\n", SAMPLE + b"\nother",
                SAMPLE + b" ", b" " + SAMPLE, SAMPLE + b"\xff", SAMPLE + b"\x00",
                b"A" * 257, b"A" * 257 + b"\r\n"):
            with self.subTest(payload=payload), TextIOWrapper(BytesIO(payload)) as stream:
                self.assert_input_error(stream, "provider_correlation_invalid")

    def test_terminal_is_rejected_and_read_errors_are_sanitized(self):
        terminal = Mock()
        terminal.isatty.return_value = True
        self.assert_input_error(terminal, "provider_correlation_invalid")
        terminal.buffer.read.assert_not_called()

        failing = Mock()
        failing.isatty.return_value = False
        failing.buffer.read.side_effect = OSError(SAMPLE.decode("ascii"))
        self.assert_input_error(failing, "provider_response_id_input_error")
