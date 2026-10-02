"""Per-message handling in the subscriber loop."""

import unittest

from fake_sglang import AllBlocksCleared, BlockRemoved, KVEventBatch, frames

from radixview.subscribe import _handle

_LOGGER = "radixview.subscribe"


def _message(seq: int, attn_dp_rank=None, events=None) -> list[bytes]:
    if events is None:
        events = [BlockRemoved(block_hashes=[seq])]
    batch = KVEventBatch(ts=1.0, events=events, attn_dp_rank=attn_dp_rank)
    return frames(seq, batch)


class TestHandle(unittest.TestCase):
    def test_logs_one_line_per_event(self):
        events = [BlockRemoved(block_hashes=[1]), AllBlocksCleared()]
        with self.assertLogs(_LOGGER, "INFO") as logs:
            _handle(_message(3, attn_dp_rank=1, events=events), 0, {})
        self.assertEqual(len(logs.records), 2)
        self.assertIn("dp_rank=1 seq=3 ts=1.0 BlockRemoved", logs.output[0])
        self.assertIn("AllBlocksCleared", logs.output[1])

    def test_falls_back_to_the_socket_rank(self):
        last_seq = {}
        with self.assertLogs(_LOGGER, "INFO") as logs:
            _handle(_message(0), 2, last_seq)
        self.assertIn("dp_rank=2", logs.output[0])
        self.assertEqual(last_seq, {2: 0})

    def test_warns_on_a_gap_and_on_a_restart(self):
        last_seq = {}
        with self.assertLogs(_LOGGER, "WARNING") as logs:
            _handle(_message(0, attn_dp_rank=0), 0, last_seq)
            _handle(_message(5, attn_dp_rank=0), 0, last_seq)
            _handle(_message(0, attn_dp_rank=0), 0, last_seq)
        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(
            warnings,
            [
                "dp_rank=0 sequence gap: 0 -> 5",
                "dp_rank=0 publisher restarted: 5 -> 0",
            ],
        )

    def test_drops_a_malformed_batch_without_touching_the_sequence(self):
        last_seq = {0: 4}
        with self.assertLogs(_LOGGER, "WARNING") as logs:
            _handle([b"", b"\x00" * 8, b"\xc1"], 0, last_seq)
        self.assertIn("dropped malformed batch on dp_rank=0", logs.output[0])
        self.assertEqual(last_seq, {0: 4})


if __name__ == "__main__":
    unittest.main()
