"""Command-line parsing and exit behavior."""

import contextlib
import io
import unittest
from unittest import mock

from radixview import cli
from radixview.config import MonitorConfig
from radixview.version import __version__


class TestBuildParser(unittest.TestCase):
    def test_defaults(self):
        args = cli.build_parser().parse_args([])
        self.assertEqual(args.server, "http://127.0.0.1:30000")
        self.assertIsNone(args.api_key)

    def test_version(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as ctx:
            cli.build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"radixview {__version__}")


@mock.patch("logging.basicConfig")
@mock.patch.object(cli, "serve")
class TestMain(unittest.TestCase):
    def test_serves_the_parsed_config(self, serve, _basic_config):
        cli.main(["--server", "http://h:1/", "--api-key", "sk"])
        serve.assert_called_once_with(MonitorConfig(server="http://h:1", api_key="sk"))

    def test_a_bad_url_is_a_usage_error(self, serve, _basic_config):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--server", "localhost:30000"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("http(s) URL", stderr.getvalue())
        serve.assert_not_called()

    def test_a_discovery_failure_exits_without_a_traceback(self, serve, _basic_config):
        serve.side_effect = RuntimeError("failed to fetch")
        with self.assertLogs("radixview.cli", "ERROR") as logs:
            with self.assertRaises(SystemExit) as ctx:
                cli.main([])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("failed to fetch", logs.output[0])

    def test_ctrl_c_exits_quietly(self, serve, _basic_config):
        serve.side_effect = KeyboardInterrupt
        cli.main([])


if __name__ == "__main__":
    unittest.main()
