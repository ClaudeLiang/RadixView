"""End to end: /server_info discovery, a live PUB socket, the log, and the page."""

import json
import re
import threading
import time
import unittest
import urllib.request

import zmq
from fake_sglang import BlockStored, InfoServer, KVEventBatch, frames, kv_events

from radixview.config import MonitorConfig
from radixview.serve import serve

_TIMEOUT_S = 10


def _batch() -> KVEventBatch:
    stored = BlockStored(
        block_hashes=[1],
        parent_block_hash=None,
        token_ids=[1, 2, 3, 4],
        block_size=4,
        lora_id=None,
        medium="GPU",
    )
    return KVEventBatch(ts=1.0, events=[stored], attn_dp_rank=0)


def _page_url(logs) -> str:
    for line in logs.output:
        match = re.search(r"tree page (http://\S+)", line)
        if match:
            return match.group(1)
    raise AssertionError("the tree page was not started")


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as response:
        return json.load(response)


class TestServe(unittest.TestCase):
    def setUp(self):
        self.context = zmq.Context()
        self.pub = self.context.socket(zmq.PUB)
        self.port = self.pub.bind_to_random_port("tcp://127.0.0.1")

    def tearDown(self):
        self.context.destroy(linger=0)

    def test_logs_events_and_serves_the_tree(self):
        info = {"kv_events": kv_events(endpoint_port_base=self.port, dp_size=1)}
        stop = threading.Event()
        with InfoServer(info) as server, self.assertLogs("radixview", "INFO") as logs:
            config = MonitorConfig(server=server.url, view_port=0)
            thread = threading.Thread(target=serve, args=(config, stop))
            thread.start()
            try:
                self._publish_until_logged(logs)
                snapshot = _get_json(_page_url(logs) + "/api/tree")
                pages = _get_json(_page_url(logs) + "/api/run?id=1")["pages"]
            finally:
                stop.set()
                thread.join(_TIMEOUT_S)
        self.assertFalse(thread.is_alive())
        self.assertEqual(snapshot["stats"]["pages"], 1)
        self.assertEqual(pages[0]["text"], "hello")
        self.assertTrue(any("page=64 dp=1" in line for line in logs.output))
        self.assertTrue(
            any(f"tcp://127.0.0.1:{self.port}" in line for line in logs.output)
        )
        self.assertFalse([r for r in logs.records if r.levelname == "WARNING"])

    def _publish_until_logged(self, logs) -> None:
        # SUB connects asynchronously; PUB drops whatever it sends before then.
        deadline = time.monotonic() + _TIMEOUT_S
        seq = 0
        while not any("hello" in line for line in logs.output):
            self.assertLess(time.monotonic(), deadline, "no event was logged")
            self.pub.send_multipart(frames(seq, _batch()))
            seq += 1
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
