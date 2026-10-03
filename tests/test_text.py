"""Detokenizer talks to the server's /detokenize endpoint."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from radixview.text import Detokenizer


class _Server:
    def __init__(self, status: int = 200, body: object = None):
        self.calls = 0
        self.authorization = None
        self.payload = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.payload = json.loads(self.rfile.read(length))
                outer.authorization = self.headers.get("Authorization")
                outer.calls += 1
                raw = json.dumps({"text": "hello"} if body is None else body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_port}"

    def __enter__(self) -> "_Server":
        threading.Thread(
            target=self._httpd.serve_forever, args=(0.05,), daemon=True
        ).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


class TestDetokenizer(unittest.TestCase):
    def test_decodes_and_caches(self):
        with _Server() as server:
            detokenizer = Detokenizer(server.url, api_key="sk")
            self.assertEqual(detokenizer.decode([248045, 198]), "hello")
            self.assertEqual(detokenizer.decode([248045, 198]), "hello")
        self.assertEqual(server.calls, 1)
        self.assertEqual(server.authorization, "Bearer sk")
        self.assertEqual(
            server.payload, {"tokens": [248045, 198], "skip_special_tokens": False}
        )

    def test_a_missing_endpoint_disables_further_calls(self):
        with _Server(status=404, body={"error": "nope"}) as server:
            detokenizer = Detokenizer(server.url)
            with self.assertLogs("radixview.text", "WARNING") as logs:
                self.assertIsNone(detokenizer.decode([1]))
                self.assertIsNone(detokenizer.decode([2]))
        self.assertEqual(server.calls, 1)
        self.assertIn("no /detokenize", logs.output[0])

    def test_a_bad_response_is_reported_once(self):
        with _Server(body={"text": [1]}) as server:
            detokenizer = Detokenizer(server.url)
            with self.assertLogs("radixview.text", "WARNING") as logs:
                self.assertIsNone(detokenizer.decode([1]))
                self.assertIsNone(detokenizer.decode([2]))
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(server.calls, 2)

    def test_ignores_ids_that_are_not_ints(self):
        detokenizer = Detokenizer("http://127.0.0.1:9")
        self.assertIsNone(detokenizer.decode([]))
        self.assertIsNone(detokenizer.decode([True]))
        self.assertIsNone(detokenizer.decode(None))


if __name__ == "__main__":
    unittest.main()
