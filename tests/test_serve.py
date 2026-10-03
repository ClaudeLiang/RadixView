"""End to end: /server_info discovery, a live PUB socket, and the log."""

import threading
import time
import unittest

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


class TestServe(unittest.TestCase):
    def setUp(self):
        self.context = zmq.Context()
        self.pub = self.context.socket(zmq.PUB)
        self.port = self.pub.bind_to_random_port("tcp://127.0.0.1")

    def tearDown(self):
        self.context.destroy(linger=0)

    def test_logs_events_from_a_live_publisher(self):
        info = {"kv_events": kv_events(endpoint_port_base=self.port, dp_size=1)}
        stop = threading.Event()
        with InfoServer(info) as server, self.assertLogs("radixview", "INFO") as logs:
            thread = threading.Thread(
                target=serve, args=(MonitorConfig(server=server.url), stop)
            )
            thread.start()
            try:
                self._publish_until_logged(logs)
            finally:
                stop.set()
                thread.join(_TIMEOUT_S)
        self.assertFalse(thread.is_alive())
        self.assertIn("page=64 dp=1", logs.output[0])
        self.assertIn(f"tcp://127.0.0.1:{self.port}", logs.output[1])
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
