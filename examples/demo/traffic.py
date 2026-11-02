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
"""Synthetic agent traffic for the tree page, without a SGLang server.

Prompts come from ``corpus.json``. Every session shares one system prompt
and tool list, then grows its own turns. Some turns are regenerated, which
forks the tree; one chain hangs off a parent stored before the subscription,
and the oldest leaves are evicted once the cache is full. Events go through
``CacheTree`` exactly like the ones decoded from ZMQ.
"""

from __future__ import annotations

import json
import logging
import random
import threading
from pathlib import Path
from typing import Optional

from radixview.tree import CacheTree

logger = logging.getLogger(__name__)

BLOCK_TOKENS = 64
MISSING_PARENT = 7_000_000_000_000_000_001
_CORPUS = Path(__file__).with_name("corpus.json")

_NEW_SESSION = 0.3
_REGENERATE = 0.15
_HOST_MEDIUM = 0.1
_CHECKPOINT_SLOTS = range(2, 9)


def load_corpus(path: Path = _CORPUS) -> dict:
    """The mock prompts. Edit the JSON, not this module, to change the text."""
    return json.loads(path.read_text(encoding="utf-8"))


class DemoTraffic:
    """Feeds a ``CacheTree`` with agent-like ``BlockStored`` and ``BlockRemoved``."""

    def __init__(
        self,
        tree: CacheTree,
        blocks: int = 400,
        seed: int = 0,
        corpus: Optional[dict] = None,
    ) -> None:
        self._tree = tree
        self._limit = blocks
        self._rng = random.Random(seed)
        self._corpus = corpus if corpus is not None else load_corpus()
        self._texts: dict[int, str] = {}
        self._parent: dict[int, Optional[int]] = {}
        self._kids: dict[int, int] = {}
        self._leaves: dict[int, None] = {}
        self._pinned: set[int] = set()
        self._root: Optional[int] = None
        # Checkpoint slots come from a fixed range, never ``_rng``. The tree
        # shape tests depend on the prompt RNG staying on the same sequence.
        self._checkpoints: list[int] = []
        self._checkpoint_of: dict[int, int] = {}
        self._hash_of: dict[int, int] = {}

    @property
    def blocks(self) -> int:
        return len(self._parent)

    def populate(self) -> None:
        """Store the shared prefix, one orphan chain, and sessions up to the limit."""
        self._tree.apply_mamba(
            {"type": "MambaSnapshot", "pools": {"device": 8}, "slots": []}
        )
        shared = self._corpus["system"] + self._corpus["tools"]
        self._root = self._store(None, shared, "GPU")
        self._pinned.update(self._parent)
        self._store(MISSING_PARENT, self._corpus["orphan"], "GPU")
        while self.blocks < self._limit:
            self.add_turn()

    def step(self) -> None:
        """One tick of live traffic: a new turn, then eviction down to the limit."""
        self.add_turn()
        while self.blocks > self._limit and self._evict_oldest():
            pass

    def add_turn(self) -> None:
        topic = self._rng.choice(self._corpus["topics"])
        count = self._rng.randint(1, 3)
        replies = self._rng.sample(self._corpus["replies"], count)
        texts = [self._rng.choice(self._corpus["questions"])] + replies
        medium = "CPU_PINNED" if self._rng.random() < _HOST_MEDIUM else "GPU"
        filled = [text.format(topic=topic) for text in texts]
        self._store(self._turn_parent(), filled, medium)

    def decode(self, token_ids: list) -> Optional[str]:
        return self._texts.get(token_ids[0]) if token_ids else None

    def _turn_parent(self) -> Optional[int]:
        roll = self._rng.random()
        leaves = list(self._leaves)
        if roll < _NEW_SESSION or not leaves:
            return self._root
        leaf = self._rng.choice(leaves)
        if roll < _NEW_SESSION + _REGENERATE and self._parent[leaf] in self._parent:
            return self._parent[leaf]
        return leaf

    def _store(self, parent: Optional[int], texts: list, medium: str) -> int:
        hashes, token_ids = [], []
        cursor = parent
        for text in texts:
            block_hash = self._rng.getrandbits(64) - 2**63
            token_ids.extend(self._block_tokens(text))
            self._link(block_hash, cursor)
            hashes.append(block_hash)
            cursor = block_hash
        self._tree.apply_stored(_stored(hashes, parent, token_ids, medium), self.decode)
        self._bind_tail(cursor)
        return cursor

    def _block_tokens(self, text: str) -> list[int]:
        key = len(self._texts) + 1
        self._texts[key] = text
        return [key] + [0] * (BLOCK_TOKENS - 1)

    def _link(self, block_hash: int, parent: Optional[int]) -> None:
        self._parent[block_hash] = parent
        self._kids[block_hash] = 0
        self._leaves[block_hash] = None
        if parent in self._kids:
            self._kids[parent] += 1
            self._leaves.pop(parent, None)

    def _evict_oldest(self) -> bool:
        victim = next(
            (block for block in self._leaves if block not in self._pinned), None
        )
        if victim is None:
            return False
        self._drop(victim)
        return True

    def _drop(self, victim: int) -> None:
        del self._leaves[victim]
        del self._kids[victim]
        self._release_if_bound(victim, "evict_device")
        parent = self._parent.pop(victim)
        self._tree.remove([victim])
        if parent not in self._kids:
            return
        self._kids[parent] -= 1
        if self._kids[parent] == 0:
            self._leaves[parent] = None

    def _bind_tail(self, block_hash: Optional[int]) -> None:
        """One device checkpoint on the last page, plus the live COW slot."""
        if block_hash is None:
            return
        if len(self._checkpoints) >= len(_CHECKPOINT_SLOTS):
            self._release_checkpoint(self._checkpoints.pop(0), "path_cap")
        slot = self._free_checkpoint_slot()
        self._checkpoints.append(slot)
        self._checkpoint_of[block_hash] = slot
        self._hash_of[slot] = block_hash
        self._tree.apply_mamba(_mamba_alloc(slot, "checkpoint", "acquire"))
        self._tree.apply_mamba(_mamba_bind(slot, block_hash, self._seqlen(block_hash)))
        self._tree.apply_mamba(_mamba_cow(slot))

    def _free_checkpoint_slot(self) -> int:
        used = set(self._checkpoints)
        return next(slot for slot in _CHECKPOINT_SLOTS if slot not in used)

    def _release_if_bound(self, block_hash: int, reason: str) -> None:
        slot = self._checkpoint_of.get(block_hash)
        if slot is None:
            return
        self._checkpoints = [item for item in self._checkpoints if item != slot]
        self._release_checkpoint(slot, reason)

    def _release_checkpoint(self, slot: int, reason: str) -> None:
        block_hash = self._hash_of.pop(slot, None)
        if block_hash is not None:
            self._checkpoint_of.pop(block_hash, None)
        seqlen = None if block_hash is None else self._seqlen(block_hash)
        self._tree.apply_mamba(_mamba_free(slot, reason, block_hash, seqlen))

    def _seqlen(self, block_hash: Optional[int]) -> int:
        total = 0
        cursor = block_hash
        seen: set[int] = set()
        while cursor in self._parent and cursor not in seen:
            seen.add(cursor)
            total += BLOCK_TOKENS
            cursor = self._parent[cursor]
        return total


def _mamba_alloc(slot: int, role: str, reason: str) -> dict:
    return {
        "type": "MambaAlloc",
        "pool": "device",
        "slot": slot,
        "role": role,
        "reason": reason,
    }


def _mamba_bind(slot: int, block_hash: int, seqlen: int) -> dict:
    return {
        "type": "MambaBind",
        "pool": "device",
        "slot": slot,
        "block_hash": block_hash,
        "seqlen": seqlen,
        "op": "donate",
    }


def _mamba_cow(src: int) -> dict:
    return {
        "type": "MambaAlloc",
        "pool": "device",
        "slot": 1,
        "role": "request",
        "reason": "cow",
        "src_pool": "device",
        "src_slot": src,
    }


def _mamba_free(
    slot: int, reason: str, block_hash: Optional[int], seqlen: Optional[int]
) -> dict:
    event = {
        "type": "MambaFree",
        "pool": "device",
        "slot": slot,
        "role": "checkpoint",
        "reason": reason,
    }
    if block_hash is not None:
        event["block_hash"] = block_hash
    if seqlen is not None:
        event["seqlen"] = seqlen
    return event


def run_demo(
    tree: CacheTree,
    stop: threading.Event,
    blocks: int = 400,
    seed: int = 0,
    interval_s: float = 1.0,
) -> None:
    """Populate ``tree`` and keep it changing every ``interval_s`` until ``stop``."""
    traffic = DemoTraffic(tree, blocks, seed)
    traffic.populate()
    logger.info("demo traffic blocks=%s", traffic.blocks)
    while not stop.wait(interval_s):
        traffic.step()


def _stored(hashes: list, parent: Optional[int], token_ids: list, medium: str) -> dict:
    return {
        "type": "BlockStored",
        "block_hashes": hashes,
        "parent_block_hash": parent,
        "token_ids": token_ids,
        "block_size": BLOCK_TOKENS,
        "medium": medium,
    }
