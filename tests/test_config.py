"""MonitorConfig parsing."""

import argparse
import unittest

from radixview.config import MonitorConfig


def _args(server: str, api_key=None, view_port=8765) -> argparse.Namespace:
    return argparse.Namespace(server=server, api_key=api_key, view_port=view_port)


class TestMonitorConfig(unittest.TestCase):
    def test_from_args_strips_trailing_slash(self):
        config = MonitorConfig.from_args(_args("http://127.0.0.1:30000/"))
        self.assertEqual(config.server, "http://127.0.0.1:30000")
        self.assertIsNone(config.api_key)
        self.assertEqual(config.view_port, 8765)

    def test_accepts_https_and_an_ipv6_host(self):
        config = MonitorConfig.from_args(_args("https://[::1]:30000"))
        self.assertEqual(config.server, "https://[::1]:30000")

    def test_keeps_the_api_key_and_view_port(self):
        config = MonitorConfig.from_args(_args("http://h:30000", "sk", view_port=0))
        self.assertEqual(config.api_key, "sk")
        self.assertEqual(config.view_port, 0)

    def test_an_empty_api_key_means_none(self):
        config = MonitorConfig.from_args(_args("http://h:30000", api_key=""))
        self.assertIsNone(config.api_key)

    def test_rejects_urls_that_cannot_be_fetched(self):
        for server in ["", "127.0.0.1:30000", "localhost:30000", "ftp://h", "http://"]:
            with self.subTest(server=server), self.assertRaises(ValueError):
                MonitorConfig.from_args(_args(server))


if __name__ == "__main__":
    unittest.main()
