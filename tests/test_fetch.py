"""Requests to a loopback server never go through http_proxy."""

import json
import unittest
import urllib.error
import urllib.request
from unittest import mock

from fake_sglang import InfoServer, kv_events

from radixview.discover import load_publishers
from radixview.fetch import is_loopback, open_url


class TestIsLoopback(unittest.TestCase):
    def test_loopback_hosts(self):
        for host in [
            "127.0.0.1",
            "127.0.0.2",
            "localhost",
            "LOCALHOST",
            "::1",
            "[::1]",
        ]:
            with self.subTest(host=host):
                self.assertTrue(is_loopback(host))

    def test_other_hosts(self):
        for host in [None, "", "10.0.0.1", "0.0.0.0", "gpu-host", "::"]:
            with self.subTest(host=host):
                self.assertFalse(is_loopback(host))


class TestOpenUrl(unittest.TestCase):
    def setUp(self):
        self.proxy = self._serve(InfoServer({"error": "Forbidden"}, status=403))
        self.server = self._serve(InfoServer({"kv_events": kv_events(dp_size=1)}))
        env = {
            "http_proxy": self.proxy.url,
            "HTTP_PROXY": self.proxy.url,
            "no_proxy": "",
            "NO_PROXY": "",
        }
        patcher = mock.patch.dict("os.environ", env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _serve(self, server):
        server.__enter__()
        self.addCleanup(server.__exit__, None, None, None)
        return server

    def test_the_proxy_would_answer_403(self):
        request = urllib.request.Request(self.server.url + "/server_info")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.build_opener().open(request, timeout=5)
        ctx.exception.close()
        self.assertEqual(ctx.exception.code, 403)
        self.assertEqual(len(self.proxy.headers), 1)

    def test_a_loopback_server_is_dialed_directly(self):
        request = urllib.request.Request(self.server.url + "/server_info")
        with open_url(request, timeout=5) as response:
            self.assertIn("kv_events", json.load(response))
        self.assertEqual(self.proxy.headers, [])

    def test_discovery_ignores_the_proxy(self):
        publishers = load_publishers(self.server.url)
        self.assertEqual(len(publishers.ranks), 1)


if __name__ == "__main__":
    unittest.main()
