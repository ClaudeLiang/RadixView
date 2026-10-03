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

PAGE_TOKENS = 64
MISSING_PARENT = 7_000_000_000_000_000_001
_CORPUS = Path(__file__).with_name("corpus.json")

_NEW_SESSION = 0.3
_REGENERATE = 0.15
_HOST_MEDIUM = 0.1


def load_corpus(path: Path = _CORPUS) -> dict:
    """The mock prompts. Edit the JSON, not this module, to change the text."""
    return json.loads(path.read_text(encoding="utf-8"))


class DemoTraffic:
    """Feeds a ``CacheTree`` with agent-like ``BlockStored`` and ``BlockRemoved``."""

    def __init__(
        self,
        tree: CacheTree,
        pages: int = 400,
        seed: int = 0,
        corpus: Optional[dict] = None,
    ) -> None:
        self._tree = tree
        self._limit = pages
        self._rng = random.Random(seed)
        self._corpus = corpus if corpus is not None else load_corpus()
        self._texts: dict[int, str] = {}
        self._parent: dict[int, Optional[int]] = {}
        self._kids: dict[int, int] = {}
        self._leaves: dict[int, None] = {}
        self._pinned: set[int] = set()
        self._root: Optional[int] = None

    @property
    def pages(self) -> int:
        return len(self._parent)

    def populate(self) -> None:
        """Store the shared prefix, one orphan chain, and sessions up to the limit."""
        shared = self._corpus["system"] + self._corpus["tools"]
        self._root = self._store(None, shared, "GPU")
        self._pinned.update(self._parent)
        self._store(MISSING_PARENT, self._corpus["orphan"], "GPU")
        while self.pages < self._limit:
            self.add_turn()

    def step(self) -> None:
        """One tick of live traffic: a new turn, then eviction down to the limit."""
        self.add_turn()
        while self.pages > self._limit and self._evict_oldest():
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
            token_ids.extend(self._page_tokens(text))
            self._link(block_hash, cursor)
            hashes.append(block_hash)
            cursor = block_hash
        self._tree.apply_stored(_stored(hashes, parent, token_ids, medium), self.decode)
        return cursor

    def _page_tokens(self, text: str) -> list[int]:
        key = len(self._texts) + 1
        self._texts[key] = text
        return [key] + [0] * (PAGE_TOKENS - 1)

    def _link(self, block_hash: int, parent: Optional[int]) -> None:
        self._parent[block_hash] = parent
        self._kids[block_hash] = 0
        self._leaves[block_hash] = None
        if parent in self._kids:
            self._kids[parent] += 1
            self._leaves.pop(parent, None)

    def _evict_oldest(self) -> bool:
        victim = next((page for page in self._leaves if page not in self._pinned), None)
        if victim is None:
            return False
        self._drop(victim)
        return True

    def _drop(self, victim: int) -> None:
        del self._leaves[victim]
        del self._kids[victim]
        parent = self._parent.pop(victim)
        self._tree.remove([victim])
        if parent not in self._kids:
            return
        self._kids[parent] -= 1
        if self._kids[parent] == 0:
            self._leaves[parent] = None


def run_demo(
    tree: CacheTree,
    stop: threading.Event,
    pages: int = 400,
    seed: int = 0,
    interval_s: float = 1.0,
) -> None:
    """Populate ``tree`` and keep it changing every ``interval_s`` until ``stop``."""
    traffic = DemoTraffic(tree, pages, seed)
    traffic.populate()
    logger.info("demo traffic pages=%s", traffic.pages)
    while not stop.wait(interval_s):
        traffic.step()


def _stored(hashes: list, parent: Optional[int], token_ids: list, medium: str) -> dict:
    return {
        "type": "BlockStored",
        "block_hashes": hashes,
        "parent_block_hash": parent,
        "token_ids": token_ids,
        "block_size": PAGE_TOKENS,
        "medium": medium,
    }
