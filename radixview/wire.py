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
"""Decode the SGLang KV-event ZMQ frame.

A published message is three frames: topic, an 8-byte big-endian sequence
number, and a msgpack payload. The payload is a positional array
``[timestamp, events, attn_dp_rank]``. Current SGLang sends each event as a
map tagged with ``type``. Older servers send a tagged array whose first
element is ``BlockStored``, ``BlockRemoved``, or ``AllBlocksCleared``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import msgspec

_PREVIEW = 8


@dataclass(frozen=True, slots=True)
class DecodedBatch:
    """One published batch; ``events`` are still the raw event maps."""

    seq: int
    ts: float
    attn_dp_rank: Optional[int]
    events: tuple[dict, ...]


def decode_multipart(frames: list[bytes]) -> DecodedBatch:
    """Decode one ``SUB`` multipart message."""
    _require_frames(frames)
    ts, events, rank = _batch(msgspec.msgpack.decode(frames[2]))
    return DecodedBatch(
        seq=_sequence(frames[1]),
        ts=ts,
        attn_dp_rank=rank,
        events=events,
    )


def sequence_break(last_seq: dict[int, int], rank: int, seq: int) -> Optional[str]:
    """Record ``seq`` for ``rank`` and describe any break in the stream.

    The first sequence observed for a rank is never a break: a subscriber
    that attaches late starts in the middle of the stream. A sequence that
    does not move forward means the publisher restarted its counter.
    """
    previous = last_seq.get(rank)
    last_seq[rank] = seq
    if previous is None or seq == previous + 1:
        return None
    if seq <= previous:
        return f"publisher restarted: {previous} -> {seq}"
    return f"sequence gap: {previous} -> {seq}"


def format_event(event: dict, text: Optional[str] = None) -> str:
    """One log record for a decoded event.

    ``text`` is the detokenized prompt for a ``BlockStored`` event. Without
    it, the token ids are previewed instead of printed in full.
    """
    kind = str(event.get("type", "unknown"))
    if kind == "BlockStored":
        return _format_stored(event, text)
    formatter = _FORMATTERS.get(kind, _format_unknown)
    return formatter(event)


def _require_frames(frames: list[bytes]) -> None:
    if len(frames) != 3:
        raise ValueError(f"expected 3 ZMQ frames, got {len(frames)}")


def _sequence(raw: bytes) -> int:
    if len(raw) != 8:
        raise ValueError("sequence frame must be 8 bytes")
    return int.from_bytes(raw, "big")


def _batch(raw: object) -> tuple[float, tuple[dict, ...], Optional[int]]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("KV event batch must be a positional array")
    return _timestamp(raw[0]), _events(raw[1]), _attn_dp_rank(raw)


def _timestamp(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("batch timestamp is not a number")
    return float(raw)


def _events(raw: object) -> tuple[dict, ...]:
    if not isinstance(raw, list):
        raise ValueError("event batch is missing the events array")
    return tuple(_event(item) for item in raw)


# Positional fields of the array encoding, after the leading type tag.
# Medium arrived later, and a trailing metadata map may carry cache_salt, so
# both are optional tails rather than required slots.
_ARRAY_FIELDS = {
    "BlockStored": (
        "block_hashes",
        "parent_block_hash",
        "token_ids",
        "block_size",
        "lora_id",
        "medium",
    ),
    "BlockRemoved": ("block_hashes", "medium"),
    "AllBlocksCleared": (),
}


def _event(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and raw and isinstance(raw[0], str):
        return _event_array(raw)
    raise ValueError(f"event is not a map or tagged array, got {type(raw).__name__}")


def _event_array(raw: list) -> dict:
    kind = raw[0]
    fields = _ARRAY_FIELDS.get(kind, ())
    event = {"type": kind}
    for name, value in zip(fields, raw[1:]):
        event[name] = value
    _cache_salt(event, raw[1 + len(fields) :])
    return event


def _cache_salt(event: dict, extra: list) -> None:
    if not extra or not isinstance(extra[0], dict):
        return
    salt = extra[0].get("cache_salt")
    if salt is not None:
        event["cache_salt"] = salt


def _attn_dp_rank(raw: list) -> Optional[int]:
    if len(raw) < 3 or raw[2] is None:
        return None
    if isinstance(raw[2], bool) or not isinstance(raw[2], int):
        raise ValueError("attn_dp_rank is not an int")
    return raw[2]


_TEXT_LIMIT = 2000
_EXTRA_FIELDS = ("lora_id", "cache_salt", "session_id")


def _format_stored(event: dict, text: Optional[str]) -> str:
    head = "stored " + " ".join(_stored_fields(event))
    body = _stored_body(event, text)
    if not body:
        return head
    return f"{head}\n  {body}"


def _stored_fields(event: dict) -> list[str]:
    tokens = _as_list(event.get("token_ids"))
    hashes = _as_list(event.get("block_hashes"))
    fields = [f"blocks={len(hashes)}", f"tokens={len(tokens)}"]
    _append_page(fields, event.get("block_size"))
    fields.append(f"medium={_or_dash(event.get('medium'))}")
    fields.append(f"parent={_or_dash(event.get('parent_block_hash'))}")
    _append_single_hash(fields, hashes)
    fields.extend(_extras(event))
    return fields


def _append_page(fields: list[str], block_size: object) -> None:
    if block_size is not None:
        fields.append(f"page={block_size}")


def _append_single_hash(fields: list[str], hashes: list) -> None:
    if len(hashes) == 1:
        fields.append(f"hash={hashes[0]}")


def _extras(event: dict) -> list[str]:
    return [
        f"{name}={event[name]}" for name in _EXTRA_FIELDS if event.get(name) is not None
    ]


def _stored_body(event: dict, text: Optional[str]) -> str:
    if text is not None:
        return _one_line(text)
    return _id_preview(_as_list(event.get("token_ids")))


def _one_line(text: str) -> str:
    flat = text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
    if len(flat) <= _TEXT_LIMIT:
        return flat
    return f"{flat[:_TEXT_LIMIT]}...({len(flat)} chars)"


def _id_preview(tokens: list) -> str:
    if not tokens:
        return ""
    return f"token_ids={_preview(tokens)}"


def _or_dash(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def _format_removed(event: dict) -> str:
    hashes = _as_list(event.get("block_hashes"))
    return (
        f"removed blocks={len(hashes)} medium={_or_dash(event.get('medium'))} "
        f"hashes={_preview(hashes)}"
    )


def _format_cleared(_event: dict) -> str:
    return "cleared"


def _format_unknown(event: dict) -> str:
    kind = event.get("type", "unknown")
    fields = sorted(key for key in event if key != "type")
    return f"{kind} fields={fields}"


def _as_list(raw: object) -> list:
    if isinstance(raw, list):
        return raw
    return []


def _preview(values: list) -> str:
    head = values[:_PREVIEW]
    if len(values) <= _PREVIEW:
        return str(head)
    return f"{head}...({len(values)})"


_FORMATTERS = {
    "BlockRemoved": _format_removed,
    "AllBlocksCleared": _format_cleared,
}
