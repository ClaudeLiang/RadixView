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
"""Mamba pool occupancy, joined to the radix tree by the last page hash.

Device, host, and int8 checkpoint slots live in three id spaces. Host slots
are numbered from 0; device and checkpoint slots reserve 0 and publish from 1.
A checkpoint names the published hash of the KV page it covers. A request slot
and a ping-pong slot do not, so they stay in the pool table and off the tree.
"""

from __future__ import annotations

from typing import Optional

from radixview.wire import format_event

_LOG_CAP = 200
_RELEASE_CAP = 32
_POOLS = frozenset({"device", "host", "ckpt"})
_ROLES = frozenset({"request", "ping_pong", "checkpoint"})
# Frees that drop mamba state without a matching KV removal.
_KEPT_REASONS = frozenset({"path_cap", "evict_device", "evict_host"})


class MambaBook:
    """Occupied slots, the event log, and frees that left their KV page."""

    def __init__(self) -> None:
        self.sizes: dict[str, int] = {}
        self.slots: dict[tuple[str, int], dict] = {}
        self.log: list[str] = []
        self.releases: list[dict] = []

    def apply(self, event: dict) -> bool:
        """Apply one mamba event. Malformed events are ignored."""
        if not isinstance(event, dict):
            return False
        handler = _HANDLERS.get(event.get("type"))
        if handler is None:
            return False
        try:
            line = handler(self, event)
        except (TypeError, ValueError):
            return False
        if line is None:
            return False
        self._remember(line)
        return True

    def drop_slots(self) -> None:
        """Forget occupancy after ``AllBlocksCleared``. Pool sizes stay."""
        self.slots.clear()
        self.log.clear()
        self.releases.clear()

    def copy(self) -> MambaBook:
        other = MambaBook()
        other.sizes = dict(self.sizes)
        other.slots = {key: dict(row) for key, row in self.slots.items()}
        other.log = list(self.log)
        other.releases = [dict(row) for row in self.releases]
        return other

    def forget_absent(self, blocks: dict) -> bool:
        """Drop frees whose page is no longer in the tree."""
        kept = [row for row in self.releases if _page_resident(row, blocks)]
        if len(kept) == len(self.releases):
            return False
        self.releases = kept
        return True

    def public(self) -> dict:
        rows = [_public_slot(self.slots[key]) for key in sorted(self.slots)]
        releases = [dict(row) for row in self.releases]
        return {
            "pools": dict(self.sizes),
            "slots": rows,
            "log": list(self.log),
            "releases": releases,
        }

    def located(self, runs: dict) -> dict[str, list[dict]]:
        """Checkpoint marks, keyed by the visual node that holds the page."""
        by_hash = _checkpoints_by_hash(self.slots)
        found = {}
        for run_id, run in runs.items():
            marks = _run_marks(run, by_hash)
            if marks:
                found[run_id] = marks
        return found

    def _remember(self, line: str) -> None:
        self.log.append(line)
        del self.log[:-_LOG_CAP]

    def forget_release(self, pool: str, digest: str) -> None:
        self.releases = [
            row
            for row in self.releases
            if not (row.get("pool") == pool and row.get("hash") == digest)
        ]

    def _remember_release(self, row: dict) -> None:
        if row["reason"] not in _KEPT_REASONS or "hash" not in row:
            return
        self.forget_release(row["pool"], row["hash"])
        self.releases.append(row)
        del self.releases[:-_RELEASE_CAP]


def _alloc(book: MambaBook, event: dict) -> Optional[str]:
    row = _occupied(event)
    key = (row["pool"], row["slot"])
    if book.slots.get(key) == row:
        return None
    book.slots[key] = row
    if row["role"] == "checkpoint" and row["hash"]:
        book.forget_release(row["pool"], row["hash"])
    return format_event(event)


def _free(book: MambaBook, event: dict) -> str:
    row = _freed(event)
    current = book.slots.pop((row["pool"], row["slot"]), None)
    _fill_from_slot(row, current)
    book._remember_release(row)
    return format_event(event)


def _bind(book: MambaBook, event: dict) -> str:
    pool, slot = _pool(event.get("pool")), _slot(event.get("slot"))
    digest = _required_hash(event.get("block_hash"))
    seqlen = _required_int(event.get("seqlen"))
    if not isinstance(event.get("op"), str) or not event["op"]:
        raise ValueError("bind needs an op")
    row = book.slots.setdefault((pool, slot), _blank(pool, slot))
    row["role"] = "checkpoint"
    row["hash"] = digest
    row["seqlen"] = seqlen
    req = _text(event.get("req"))
    if req is not None:
        row["req"] = req
    book.forget_release(pool, digest)
    return format_event(event)


def _snapshot(book: MambaBook, event: dict) -> Optional[str]:
    pools, slots = event.get("pools"), event.get("slots")
    if not isinstance(pools, dict) or not isinstance(slots, list):
        raise ValueError("snapshot needs pools and slots")
    sizes = {_pool(name): _size(size) for name, size in pools.items()}
    occupied = {}
    for item in slots:
        if not isinstance(item, dict):
            raise ValueError("snapshot slot is not a map")
        row = _occupied(item)
        occupied[(row["pool"], row["slot"])] = row
    same = sizes == book.sizes and occupied == book.slots
    if not same:
        book.sizes = sizes
        book.slots = occupied
    pending = len(book.releases)
    _forget_bound(book, occupied)
    if same and len(book.releases) == pending:
        return None
    return format_event(event)


def _forget_bound(book: MambaBook, occupied: dict) -> None:
    for row in occupied.values():
        if row["role"] == "checkpoint" and row["hash"]:
            book.forget_release(row["pool"], row["hash"])


def _occupied(event: dict) -> dict:
    pool, slot = _pool(event.get("pool")), _slot(event.get("slot"))
    return {
        "pool": pool,
        "slot": slot,
        "role": _role(event.get("role")),
        "req": _text(event.get("req")),
        "src_pool": _src_pool(event.get("src_pool")),
        "src_slot": _src_slot(event.get("src_slot")),
        "hash": _hash_key(event.get("block_hash")),
        "seqlen": _optional_int(event.get("seqlen")),
    }


def _freed(event: dict) -> dict:
    row = {
        "pool": _pool(event.get("pool")),
        "slot": _slot(event.get("slot")),
        "reason": _reason(event.get("reason")),
    }
    _put(row, "hash", _hash_key(event.get("block_hash")))
    _put(row, "seqlen", _optional_int(event.get("seqlen")))
    return row


def _fill_from_slot(row: dict, current: Optional[dict]) -> None:
    """A free often names only the slot. The bound page stays on the old row."""
    if not current:
        return
    if "hash" not in row:
        _put(row, "hash", current.get("hash"))
    if "seqlen" not in row:
        _put(row, "seqlen", current.get("seqlen"))


def _page_resident(row: dict, blocks: dict) -> bool:
    key = row.get("hash")
    return not isinstance(key, str) or key in blocks


def _blank(pool: str, slot: int) -> dict:
    return _occupied({"pool": pool, "slot": slot, "role": "checkpoint"})


def _public_slot(row: dict) -> dict:
    body = {"pool": row["pool"], "slot": row["slot"], "role": row["role"]}
    _put(body, "hash", row.get("hash"))
    _put(body, "seqlen", row.get("seqlen"))
    _put(body, "req", row.get("req"))
    _put(body, "src_pool", row.get("src_pool"))
    _put(body, "src_slot", row.get("src_slot"))
    return body


def _put(body: dict, name: str, value: object) -> None:
    if value is not None:
        body[name] = value


def _checkpoints_by_hash(slots: dict) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for key in sorted(slots):
        row = slots[key]
        if row["role"] == "checkpoint" and row.get("hash"):
            found.setdefault(row["hash"], []).append(row)
    return found


def _run_marks(run: tuple, by_hash: dict[str, list[dict]]) -> list[dict]:
    marks = []
    for index, block in enumerate(run):
        marks.extend(_mark(index, row) for row in by_hash.get(block.hash, ()))
    return marks


def _mark(index: int, row: dict) -> dict:
    return {
        "at": index,
        "pool": row["pool"],
        "slot": row["slot"],
        "seqlen": row.get("seqlen"),
        "hash": row["hash"],
    }


def _pool(raw: object) -> str:
    if raw not in _POOLS:
        raise ValueError("unknown mamba pool")
    return str(raw)


def _src_pool(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return _pool(raw)


def _reason(raw: object) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("reason must be a string")
    return raw


def _role(raw: object) -> str:
    if raw not in _ROLES:
        raise ValueError("unknown mamba role")
    return str(raw)


def _slot(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError("mamba slot must be a non-negative int")
    return raw


def _src_slot(raw: object) -> Optional[int]:
    if raw is None:
        return None
    return _slot(raw)


def _size(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError("mamba pool size must be a non-negative int")
    return raw


def _required_int(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError("expected a non-negative int")
    return raw


def _optional_int(raw: object) -> Optional[int]:
    if raw is None:
        return None
    return _required_int(raw)


def _required_hash(raw: object) -> str:
    key = _hash_key(raw)
    if key is None:
        raise ValueError("bind needs a block hash")
    return key


def _hash_key(raw: object) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("block hash must be an int")
    return str(raw)


def _text(raw: object) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("req must be a string")
    return raw


_HANDLERS = {
    "MambaAlloc": _alloc,
    "MambaFree": _free,
    "MambaBind": _bind,
    "MambaSnapshot": _snapshot,
}
