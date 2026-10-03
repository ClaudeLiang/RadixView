"""The local server answers the tree API and the static page files."""

import json
import socket
import unittest
import urllib.error
import urllib.request

from radixview.server import WEB_ROOT, start_server, stop_server
from radixview.tree import CacheTree


def _tree():
    tree = CacheTree()
    tree.apply_stored(
        {
            "block_hashes": [7, 8],
            "parent_block_hash": None,
            "token_ids": [1, 2],
            "block_size": 1,
            "medium": "GPU",
        },
        lambda tokens: f"page {tokens[0]}",
    )
    return tree


class TestServer(unittest.TestCase):
    def setUp(self):
        self.httpd = start_server(_tree(), 0)
        self.addCleanup(stop_server, self.httpd)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def _get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.headers["Content-Type"], response.read()

    def _json(self, path):
        content_type, body = self._get(path)
        self.assertTrue(content_type.startswith("application/json"))
        return json.loads(body)

    def _status(self, path):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get(path)
        return ctx.exception.code

    def test_index_links_the_split_assets(self):
        content_type, body = self._get("/")
        self.assertTrue(content_type.startswith("text/html"))
        self.assertIn(b'href="/style.css"', body)
        self.assertIn(b'src="/js/main.mjs"', body)

    def test_every_asset_is_served_with_its_type(self):
        types = {".css": "text/css", ".html": "text/html", ".mjs": "text/javascript"}
        for path in WEB_ROOT.rglob("*.*"):
            with self.subTest(path=path.name):
                url = "/" + path.relative_to(WEB_ROOT).as_posix()
                content_type, body = self._get(url)
                self.assertTrue(content_type.startswith(types[path.suffix]))
                self.assertEqual(body, path.read_bytes())

    def test_files_outside_the_web_root_are_not_served(self):
        for path in ["/../tree.py", "/js/../../server.py", "/%2e%2e/tree.py"]:
            with self.subTest(path=path):
                self.assertEqual(self._status(path), 404)

    def test_unknown_paths_are_404(self):
        for path in ["/missing.css", "/js/", "/api/nope", "/server.py"]:
            with self.subTest(path=path):
                self.assertEqual(self._status(path), 404)

    def test_tree_snapshot_and_since(self):
        snapshot = self._json("/api/tree")
        self.assertEqual(snapshot["stats"]["pages"], 2)
        self.assertEqual(snapshot["nodes"][0]["id"], "7..8")
        unchanged = self._json(f"/api/tree?since={snapshot['version']}")
        self.assertEqual(unchanged, {"version": snapshot["version"], "unchanged": True})
        self.assertIn("nodes", self._json("/api/tree?since=oops"))

    def test_run_pages(self):
        pages = self._json("/api/run?id=7..8")["pages"]
        self.assertEqual([page["text"] for page in pages], ["page 1", "page 2"])
        self.assertEqual(self._json("/api/run")["pages"], [])

    def test_search(self):
        query = urllib.request.quote("page 2")
        self.assertEqual(self._json(f"/api/search?q={query}")["ids"], ["7..8"])
        self.assertEqual(self._json("/api/search")["ids"], [])


class TestStartServer(unittest.TestCase):
    def test_a_busy_port_disables_the_page(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            with self.assertLogs("radixview.server", "ERROR"):
                httpd = start_server(CacheTree(), busy.getsockname()[1])
        self.assertIsNone(httpd)
        stop_server(httpd)


if __name__ == "__main__":
    unittest.main()
