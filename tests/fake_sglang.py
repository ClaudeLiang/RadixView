"""The SGLang side of the wire, for tests.

The event types are copied from ``sglang/srt/disaggregation/kv_events.py``
so the tests encode exactly what a real server publishes.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional, Union

import msgspec


class EventBatch(msgspec.Struct, array_like=True, gc=False):
    ts: float
    events: list[Any]
    attn_dp_rank: Optional[int] = None


class KVCacheEvent(msgspec.Struct, omit_defaults=True, gc=False, tag=True):
    pass


class BlockStored(KVCacheEvent):
    block_hashes: list[int]
    parent_block_hash: Optional[int]
    token_ids: list[int]
    block_size: int
    lora_id: Optional[int]
    medium: Optional[str] = None
    cache_salt: Optional[str] = None
    session_id: Optional[str] = None


class BlockRemoved(KVCacheEvent):
    block_hashes: list[int]
    medium: Optional[str] = None


class AllBlocksCleared(KVCacheEvent):
    pass


class KVEventBatch(EventBatch):
    events: list[Union[BlockStored, BlockRemoved, AllBlocksCleared]]


class LegacyKVCacheEvent(msgspec.Struct, array_like=True, gc=False, tag=True):
    """Event encoding from before SGLang switched events to tagged maps."""


class LegacyBlockStored(LegacyKVCacheEvent, tag="BlockStored"):
    block_hashes: list[int]
    parent_block_hash: Optional[int]
    token_ids: list[int]
    block_size: int
    lora_id: Optional[int]
    medium: Optional[str] = None


class LegacyBlockRemoved(LegacyKVCacheEvent, tag="BlockRemoved"):
    block_hashes: list[int]
    medium: Optional[str] = None


class LegacyAllBlocksCleared(LegacyKVCacheEvent, tag="AllBlocksCleared"):
    pass


class BlockStoredMetadata(msgspec.Struct, omit_defaults=True, gc=False):
    cache_salt: str


class LegacyBlockStoredWithMetadata(LegacyBlockStored, tag="BlockStored", kw_only=True):
    metadata: BlockStoredMetadata


def frames(seq: int, batch: KVEventBatch, topic: bytes = b"") -> list[bytes]:
    """The multipart message ``ZmqEventPublisher`` sends for ``batch``."""
    return [topic, seq.to_bytes(8, "big"), msgspec.msgpack.encode(batch)]


def kv_events(**overrides) -> dict:
    """A ``/server_info`` ``kv_events`` descriptor."""
    kv = {
        "publisher": "zmq",
        "endpoint_host": "*",
        "endpoint_port_base": 5557,
        "topic": "",
        "block_size": 64,
        "dp_size": 2,
    }
    kv.update(overrides)
    return kv


class InfoServer:
    """Serve ``body`` at ``/server_info`` on a free localhost port."""

    def __init__(self, body: Any, status: int = 200):
        self.headers: list[dict[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.headers.append(dict(self.headers))
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                raw = json.dumps({"text": "hello"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_port}"

    def __enter__(self) -> "InfoServer":
        threading.Thread(
            target=self._httpd.serve_forever, args=(0.05,), daemon=True
        ).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
