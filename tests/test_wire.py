"""Decode and summarize KV-event frames."""

import unittest

import msgspec
from fake_sglang import (
    AllBlocksCleared,
    BlockRemoved,
    BlockStored,
    KVEventBatch,
    frames,
)

from radixview.wire import decode_multipart, format_event, sequence_break


def _stored(**overrides) -> BlockStored:
    fields = {
        "block_hashes": [9],
        "parent_block_hash": None,
        "token_ids": [1, 2],
        "block_size": 2,
        "lora_id": None,
    }
    fields.update(overrides)
    return BlockStored(**fields)


def _raw(seq: int, payload: object) -> list[bytes]:
    return [b"", seq.to_bytes(8, "big"), msgspec.msgpack.encode(payload)]


class TestDecode(unittest.TestCase):
    def test_decodes_what_sglang_publishes(self):
        batch = KVEventBatch(
            ts=1.5,
            events=[
                _stored(medium="GPU", session_id="s"),
                BlockRemoved(block_hashes=[9]),
                AllBlocksCleared(),
            ],
            attn_dp_rank=1,
        )
        decoded = decode_multipart(frames(4, batch, topic=b"kv"))
        self.assertEqual(decoded.seq, 4)
        self.assertEqual(decoded.ts, 1.5)
        self.assertEqual(decoded.attn_dp_rank, 1)
        stored, removed, cleared = decoded.events
        self.assertEqual(stored["type"], "BlockStored")
        self.assertEqual(stored["token_ids"], [1, 2])
        self.assertEqual(stored["medium"], "GPU")
        self.assertNotIn("cache_salt", stored)
        self.assertEqual(removed, {"type": "BlockRemoved", "block_hashes": [9]})
        self.assertEqual(cleared, {"type": "AllBlocksCleared"})

    def test_rank_may_be_null_or_omitted(self):
        for payload in [[0.0, [], None], [0.0, []]]:
            with self.subTest(payload=payload):
                batch = decode_multipart(_raw(0, payload))
                self.assertIsNone(batch.attn_dp_rank)
                self.assertEqual(batch.events, ())

    def test_rejects_a_malformed_message(self):
        cases = {
            "two frames": [b"", b"\x00" * 8],
            "short sequence": [b"", b"\x00", msgspec.msgpack.encode([0.0, []])],
            "not msgpack": [b"", b"\x00" * 8, b"\xc1"],
            "batch is a map": _raw(0, {"ts": 0.0}),
            "batch too short": _raw(0, [0.0]),
            "bool timestamp": _raw(0, [True, []]),
            "string timestamp": _raw(0, ["now", []]),
            "events not a list": _raw(0, [0.0, {}]),
            "event not a map": _raw(0, [0.0, [["BlockStored"]]]),
            "bool rank": _raw(0, [0.0, [], True]),
            "string rank": _raw(0, [0.0, [], "0"]),
        }
        for name, message in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                decode_multipart(message)


class TestSequenceBreak(unittest.TestCase):
    def test_first_sequence_and_the_next_one_are_contiguous(self):
        last = {}
        self.assertIsNone(sequence_break(last, 0, 5))
        self.assertIsNone(sequence_break(last, 0, 6))

    def test_a_skip_is_a_gap(self):
        last = {}
        sequence_break(last, 0, 1)
        self.assertEqual(sequence_break(last, 0, 4), "sequence gap: 1 -> 4")

    def test_a_reset_is_a_restart(self):
        last = {}
        sequence_break(last, 0, 7)
        self.assertEqual(sequence_break(last, 0, 0), "publisher restarted: 7 -> 0")
        self.assertIsNone(sequence_break(last, 0, 1))

    def test_ranks_are_tracked_separately(self):
        last = {}
        sequence_break(last, 0, 3)
        self.assertIsNone(sequence_break(last, 1, 0))
        self.assertIsNone(sequence_break(last, 0, 4))


class TestFormatEvent(unittest.TestCase):
    def _decoded(self, event) -> dict:
        batch = KVEventBatch(ts=0.0, events=[event])
        return decode_multipart(frames(0, batch)).events[0]

    def test_stored_preview_does_not_dump_the_whole_token_list(self):
        event = _stored(block_hashes=[1, 2], token_ids=list(range(20)), lora_id=3)
        line = format_event(self._decoded(event))
        self.assertIn("blocks=2", line)
        self.assertIn("tokens=20", line)
        self.assertIn("lora_id=3", line)
        self.assertIn("medium=None", line)
        self.assertIn("...(20)", line)
        self.assertNotIn("19", line)

    def test_a_short_list_is_printed_whole(self):
        line = format_event(self._decoded(_stored(token_ids=list(range(8)))))
        self.assertIn("token_ids=[0, 1, 2, 3, 4, 5, 6, 7]", line)
        self.assertNotIn("...", line)

    def test_stored_tolerates_missing_lists(self):
        line = format_event({"type": "BlockStored", "token_ids": None})
        self.assertIn("blocks=0 tokens=0", line)

    def test_removed_and_cleared(self):
        event = BlockRemoved(block_hashes=[7], medium="CPU_PINNED")
        removed = format_event(self._decoded(event))
        self.assertIn("BlockRemoved blocks=1", removed)
        self.assertIn("CPU_PINNED", removed)
        cleared = format_event(self._decoded(AllBlocksCleared()))
        self.assertEqual(cleared, "AllBlocksCleared")

    def test_an_unknown_event_lists_its_fields(self):
        line = format_event({"type": "BlockMoved", "to": "DISK", "block_hashes": []})
        self.assertEqual(line, "BlockMoved fields=['block_hashes', 'to']")
        self.assertEqual(format_event({}), "unknown fields=[]")


if __name__ == "__main__":
    unittest.main()
