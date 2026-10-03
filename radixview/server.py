# Copyright 2026 RadixView Authors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Local HTTP server for the tree page.

``/api/*`` answers JSON from a ``CacheTree``. Everything else is a static
file under ``radixview/web``; the page itself has no build step.
"""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from radixview.tree import CacheTree

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().with_name("web")

_HOST = "127.0.0.1"
_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


def start_server(tree: CacheTree, port: int) -> Optional[ThreadingHTTPServer]:
    """Serve the page on ``127.0.0.1:port`` from a daemon thread.

    Returns ``None`` when the port cannot be bound, so the subscriber keeps
    logging without the page.
    """
    try:
        httpd = ThreadingHTTPServer((_HOST, port), _handler(tree))
    except OSError as exc:
        logger.error("tree page disabled, cannot bind %s:%s: %s", _HOST, port, exc)
        return None
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("tree page http://%s:%s", _HOST, httpd.server_address[1])
    return httpd


def stop_server(httpd: Optional[ThreadingHTTPServer]) -> None:
    if httpd is None:
        return
    httpd.shutdown()
    httpd.server_close()


def _handler(tree: CacheTree) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                self._reply(*_api(tree, url.path, parse_qs(url.query)))
            else:
                self._reply(*_static(url.path))

        def log_message(self, format: str, *args: object) -> None:
            pass

        def _reply(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def _api(tree: CacheTree, path: str, query: dict) -> tuple[HTTPStatus, str, bytes]:
    if path == "/api/tree":
        return _json(tree.snapshot(_since(query)))
    if path == "/api/run":
        return _json({"pages": tree.pages_of(_param(query, "id"))})
    if path == "/api/search":
        return _json({"ids": tree.search(_param(query, "q"))})
    return _not_found()


def _static(path: str) -> tuple[HTTPStatus, str, bytes]:
    target = _resolve(path)
    content_type = _CONTENT_TYPES.get(target.suffix) if target else None
    if target is None or content_type is None or not target.is_file():
        return _not_found()
    return HTTPStatus.OK, content_type, target.read_bytes()


def _resolve(path: str) -> Optional[Path]:
    relative = "index.html" if path in ("", "/") else path.lstrip("/")
    target = (WEB_ROOT / relative).resolve()
    if WEB_ROOT not in target.parents:
        return None
    return target


def _param(query: dict, name: str) -> str:
    values = query.get(name) or [""]
    return values[0]


def _since(query: dict) -> Optional[int]:
    try:
        return int(_param(query, "since"))
    except ValueError:
        return None


def _json(payload: dict) -> tuple[HTTPStatus, str, bytes]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return HTTPStatus.OK, "application/json; charset=utf-8", body.encode()


def _not_found() -> tuple[HTTPStatus, str, bytes]:
    return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
