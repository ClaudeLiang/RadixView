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
"""Radix tree rebuilt from KV-cache events.

A straight chain of blocks collapses into one visual node while the blocks
occupy the same tiers, so a long prompt does not become a long line of boxes.
A branch, or a change of tier, starts a new node. A block whose parent was
stored before the subscriber attached hangs off a placeholder node marked
``missing``.

One block hash can occupy more than one tier. ``BlockStored`` adds the
event's tier and decodes text only when the block has none yet.
``BlockRemoved`` drops that tier, and drops the block once none remain. A
removal without a tier drops every copy; one whose tier is unreadable, such
as an empty string, is ignored. Tier names are upper-cased, and SGLang's
``CPU_PINNED`` host memory is stored as ``CPU``.

Readers get an immutable view that is rebuilt only after a mutation, so a
page polling once a second costs nothing while the cache is idle.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from radixview.mamba import MambaBook

Decode = Callable[[list], Optional[str]]

_PREVIEW_CHARS = 80
_SEARCH_LIMIT = 500
_TIER_ORDER = ("GPU", "CPU", "DISK", "EXTERNAL")
_TIER_ALIASES = {"CPU_PINNED": "CPU"}
_MISSING_PREFIX = "missing:"


@dataclass(frozen=True, slots=True)
class Block:
    """One radix block and every tier it currently occupies."""

    hash: str
    parent: Optional[str]
    text: str
    tokens: int
    media: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TreeView:
    """Visual nodes for one version of the tree."""

    version: int
    nodes: list[dict]
    stats: dict
    runs: dict[str, tuple[Block, ...]]
    haystacks: dict[str, str]
    owner: dict[str, str]


class CacheTree:
    """Resident blocks keyed by the block hash from the event."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._blocks: dict[str, Block] = {}
        self._mamba = MambaBook()
        self._version = 0
        self._view: Optional[TreeView] = None

    def apply_stored(self, event: dict, decode: Optional[Decode] = None) -> None:
        """Add the tiers of one ``BlockStored`` event."""
        specs = _stored_specs(event)
        if not specs:
            return
        known = self._known_texts(specs)
        incoming = [_incoming(spec, known.get(spec.hash), decode) for spec in specs]
        with self._lock:
            if _commit_all(self._blocks, incoming):
                self._version += 1

    def remove(self, hashes: list, medium: Optional[str] = None) -> None:
        """Drop one tier, or every tier when ``medium`` is ``None``."""
        keys = [key for key in map(_hash_key, hashes) if key is not None]
        tier = None if medium is None else _medium_name(medium)
        if not keys or (medium is not None and tier is None):
            return
        with self._lock:
            changed = _drop_all(self._blocks, keys, tier)
            changed = self._mamba.forget_absent(self._blocks) or changed
            if changed:
                self._version += 1

    def clear(self) -> None:
        """Drop every block, for ``AllBlocksCleared`` or a publisher restart.

        Mamba slots, the pool log, and kept-page frees go with the blocks.
        Pool sizes stay, so the next snapshot still knows how big each pool is.
        """
        with self._lock:
            self._blocks.clear()
            self._mamba.drop_slots()
            self._version += 1

    def apply_mamba(self, event: dict) -> None:
        """Record one mamba alloc, free, bind, or snapshot. Never raises."""
        with self._lock:
            changed = self._mamba.apply(event)
            self._mamba.forget_absent(self._blocks)
            if changed:
                self._version += 1

    def snapshot(self, since: Optional[int] = None) -> dict:
        """Visual nodes, or only the version when ``since`` is current."""
        view = self.view()
        if since == view.version:
            return {"version": view.version, "unchanged": True}
        return {"version": view.version, "nodes": view.nodes, "stats": view.stats}

    def blocks_of(self, node_id: str) -> list[dict]:
        """Every block inside one visual node, in prefix order."""
        view = self.view()
        marks = _checkpoints(view.stats["mamba"]["slots"])
        return [
            _block_detail(block, marks.get(block.hash))
            for block in view.runs.get(node_id, ())
        ]

    def locate(self, node_id: str) -> Optional[str]:
        """The visual node that now holds the first block of ``node_id``.

        Node ids change when a chain splits or joins, so the page uses this
        to keep its selection. ``None`` when that block is gone.
        """
        return self.view().owner.get(_first_hash(node_id))

    def node_blocks(self) -> dict:
        """Every visual node and the blocks inside it, for download.

        A node with ``missing`` set has an empty ``blocks`` list. It stands
        for a parent that was stored before the subscriber attached.
        """
        view = self.view()
        marks = _checkpoints(view.stats["mamba"]["slots"])
        nodes = [_exported_node(node, view.runs, marks) for node in view.nodes]
        return {
            "version": view.version,
            "stats": _exported_stats(view.stats),
            "nodes": nodes,
            "mamba": _exported_mamba(view.stats["mamba"]),
        }

    def search(self, query: str) -> list[str]:
        """Ids of the visual nodes whose block text contains ``query``."""
        needle = query.strip().lower()
        if not needle:
            return []
        view = self.view()
        hits = [node_id for node_id, text in view.haystacks.items() if needle in text]
        return hits[:_SEARCH_LIMIT]

    def view(self) -> TreeView:
        """The current view, rebuilt only when the blocks changed."""
        with self._lock:
            if self._view is not None and self._view.version == self._version:
                return self._view
            blocks = dict(self._blocks)
            book = self._mamba.copy()
            version = self._version
        view = _build_view(blocks, version, book)
        with self._lock:
            if version == self._version:
                self._view = view
        return view

    def _known_texts(self, specs: list[_Spec]) -> dict[str, str]:
        with self._lock:
            found = [self._blocks.get(spec.hash) for spec in specs]
        return {block.hash: block.text for block in found if block and block.text}


@dataclass(frozen=True, slots=True)
class _Spec:
    hash: str
    parent: Optional[str]
    tokens: list
    medium: str


def _stored_specs(event: dict) -> list[_Spec]:
    hashes = [key for key in map(_hash_key, _as_list(event.get("block_hashes"))) if key]
    chunks = _chunks(
        _as_list(event.get("token_ids")), len(hashes), event.get("block_size")
    )
    medium = _stored_medium(event.get("medium"))
    parent = _hash_key(event.get("parent_block_hash"))
    specs = []
    for key, tokens in zip(hashes, chunks):
        specs.append(_Spec(hash=key, parent=parent, tokens=tokens, medium=medium))
        parent = key
    return specs


def _chunks(tokens: list, count: int, block_size: object) -> list[list]:
    if count <= 1:
        return [tokens]
    size = block_size if isinstance(block_size, int) and block_size > 0 else 1
    starts = [index * size for index in range(count)]
    ends = starts[1:] + [len(tokens)]
    return [tokens[start:end] for start, end in zip(starts, ends)]


def _incoming(spec: _Spec, text: Optional[str], decode: Optional[Decode]) -> Block:
    if text is None:
        text = _decoded(spec.tokens, decode)
    return Block(spec.hash, spec.parent, text, len(spec.tokens), (spec.medium,))


def _decoded(tokens: list, decode: Optional[Decode]) -> str:
    if decode is None or not tokens:
        return ""
    return decode(tokens) or ""


def _commit_all(blocks: dict[str, Block], incoming: list[Block]) -> bool:
    changed = False
    for block in incoming:
        changed |= _commit(blocks, block)
    return changed


def _commit(blocks: dict[str, Block], incoming: Block) -> bool:
    current = blocks.get(incoming.hash)
    merged = incoming if current is None else _merge(current, incoming)
    if merged == current:
        return False
    blocks[incoming.hash] = merged
    return True


def _merge(current: Block, incoming: Block) -> Block:
    return Block(
        current.hash,
        current.parent if current.parent is not None else incoming.parent,
        current.text or incoming.text,
        current.tokens or incoming.tokens,
        _union(current.media, incoming.media),
    )


def _drop_all(blocks: dict[str, Block], keys: list[str], medium: Optional[str]) -> bool:
    changed = False
    for key in keys:
        changed |= _drop_one(blocks, key, medium)
    return changed


def _drop_one(blocks: dict[str, Block], key: str, medium: Optional[str]) -> bool:
    block = blocks.get(key)
    if block is None:
        return False
    if medium is None:
        del blocks[key]
        return True
    return _drop_tier(blocks, block, medium)


def _drop_tier(blocks: dict[str, Block], block: Block, medium: str) -> bool:
    if medium not in block.media:
        return False
    left = tuple(name for name in block.media if name != medium)
    if not left:
        del blocks[block.hash]
    else:
        blocks[block.hash] = _without_tier(block, left)
    return True


def _without_tier(block: Block, media: tuple[str, ...]) -> Block:
    return Block(block.hash, block.parent, block.text, block.tokens, media)


def _build_view(blocks: dict[str, Block], version: int, book: MambaBook) -> TreeView:
    runs = _runs(blocks)
    owner = {block.hash: run_id for run_id, run in runs.items() for block in run}
    nodes = [_node(run_id, run, owner) for run_id, run in runs.items()]
    nodes.extend(_placeholders(nodes))
    _stamp(nodes, book.located(runs))
    haystacks = {
        run_id: "\n".join(block.text for block in run).lower()
        for run_id, run in runs.items()
    }
    stats = _stats(blocks, nodes)
    stats["mamba"] = book.public()
    _mark_kept_pages(stats["mamba"], owner)
    return TreeView(version, nodes, stats, runs, haystacks, owner)


def _mark_kept_pages(mamba: dict, owner: dict[str, str]) -> None:
    """Name the visual node that still holds a released checkpoint's page."""
    for row in mamba.get("releases", []):
        key = row.get("hash")
        if not isinstance(key, str):
            continue
        node = owner.get(key)
        row["kv"] = node is not None
        if node is not None:
            row["node"] = node


def _stamp(nodes: list[dict], located: dict[str, list[dict]]) -> None:
    for node in nodes:
        marks = located.get(node["id"])
        if marks:
            node["mamba"] = marks


def _runs(blocks: dict[str, Block]) -> dict[str, tuple[Block, ...]]:
    children = _children(blocks)
    seen: set[str] = set()
    runs: dict[str, tuple[Block, ...]] = {}
    stack = [block.hash for block in blocks.values() if block.parent not in blocks]
    stack.reverse()
    while stack:
        head = stack.pop()
        if head in seen:
            continue
        run = _unary_run(head, children, blocks, seen)
        runs[_run_id(run)] = tuple(blocks[key] for key in run)
        stack.extend(reversed(children[run[-1]]))
    return runs


def _children(blocks: dict[str, Block]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {key: [] for key in blocks}
    for block in blocks.values():
        if block.parent in children:
            children[block.parent].append(block.hash)
    return children


def _unary_run(
    head: str,
    children: dict[str, list[str]],
    blocks: dict[str, Block],
    seen: set[str],
) -> list[str]:
    run = []
    cursor = head
    while cursor not in seen:
        run.append(cursor)
        seen.add(cursor)
        nxt = _same_tier_child(cursor, children, blocks)
        if nxt is None:
            break
        cursor = nxt
    return run


def _same_tier_child(
    cursor: str, children: dict[str, list[str]], blocks: dict[str, Block]
) -> Optional[str]:
    kids = children[cursor]
    if len(kids) != 1:
        return None
    nxt = kids[0]
    if blocks[nxt].media != blocks[cursor].media:
        return None
    return nxt


def _run_id(run: list[str]) -> str:
    if len(run) == 1:
        return run[0]
    return f"{run[0]}..{run[-1]}"


def _node(run_id: str, run: tuple[Block, ...], owner: dict[str, str]) -> dict:
    first = run[0]
    return {
        "id": run_id,
        "parent": _visual_parent(first.parent, owner),
        "preview": _preview(first.text),
        "blocks": len(run),
        "tokens": sum(block.tokens for block in run),
        "media": list(first.media),
        "missing": False,
    }


def _visual_parent(parent: Optional[str], owner: dict[str, str]) -> Optional[str]:
    if parent is None:
        return None
    return owner.get(parent, _MISSING_PREFIX + parent)


def _first_hash(node_id: str) -> str:
    return node_id.removeprefix(_MISSING_PREFIX).split("..", 1)[0]


def _preview(text: str) -> str:
    line = " ".join(text.split())
    if len(line) <= _PREVIEW_CHARS:
        return line
    return line[:_PREVIEW_CHARS] + "…"


def _placeholders(nodes: list[dict]) -> list[dict]:
    present = {node["id"] for node in nodes}
    wanted = {
        node["parent"]
        for node in nodes
        if node["parent"] is not None and node["parent"] not in present
    }
    return [_placeholder(node_id) for node_id in sorted(wanted)]


def _placeholder(node_id: str) -> dict:
    return {
        "id": node_id,
        "parent": None,
        "preview": "",
        "blocks": 0,
        "tokens": 0,
        "media": [],
        "missing": True,
    }


def _stats(blocks: dict[str, Block], nodes: list[dict]) -> dict:
    return {
        "blocks": len(blocks),
        "tokens": sum(block.tokens for block in blocks.values()),
        "nodes": len(nodes),
        "missing": sum(1 for node in nodes if node["missing"]),
        "tiers": _tiers(blocks),
    }


def _tiers(blocks: dict[str, Block]) -> dict[str, dict]:
    counts: dict[str, list[int]] = {}
    for block in blocks.values():
        for name in block.media:
            tier = counts.setdefault(name, [0, 0])
            tier[0] += 1
            tier[1] += block.tokens
    return {
        name: {"blocks": counts[name][0], "tokens": counts[name][1]}
        for name in _tier_names(counts)
    }


def _tier_names(counts: dict[str, list[int]]) -> list[str]:
    ordered = [name for name in _TIER_ORDER if name in counts]
    ordered.extend(sorted(name for name in counts if name not in _TIER_ORDER))
    return ordered


def _block_detail(block: Block, mamba: Optional[list] = None) -> dict:
    detail = {
        "hash": block.hash,
        "text": block.text,
        "tokens": block.tokens,
        "media": list(block.media),
    }
    if mamba:
        detail["mamba"] = mamba
    return detail


def _exported_node(
    node: dict, runs: dict[str, tuple[Block, ...]], marks: dict[str, list]
) -> dict:
    return {
        "id": node["id"],
        "parent": node["parent"],
        "missing": node["missing"],
        "media": node["media"],
        "blocks": [
            _block_export(block, marks.get(block.hash))
            for block in runs.get(node["id"], ())
        ],
    }


def _block_export(block: Block, mamba: Optional[list] = None) -> dict:
    detail = {
        "hash": block.hash,
        "parent": block.parent,
        "text": block.text,
        "tokens": block.tokens,
        "media": list(block.media),
    }
    if mamba:
        detail["mamba"] = mamba
    return detail


def _checkpoints(slots: list[dict]) -> dict[str, list]:
    found: dict[str, list] = {}
    for row in slots:
        if row.get("role") == "checkpoint" and row.get("hash"):
            found.setdefault(row["hash"], []).append(_slot_mark(row))
    return found


def _slot_mark(row: dict) -> dict:
    return {
        "pool": row["pool"],
        "slot": row["slot"],
        "seqlen": row.get("seqlen"),
        "hash": row["hash"],
    }


def _exported_stats(stats: dict) -> dict:
    exported = dict(stats)
    exported["mamba"] = _exported_mamba(stats["mamba"])
    return exported


def _exported_mamba(mamba: dict) -> dict:
    return {"pools": mamba["pools"], "slots": mamba["slots"]}


def _union(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(left) | set(right), key=_tier_rank))


def _tier_rank(name: str) -> tuple:
    try:
        return (0, _TIER_ORDER.index(name))
    except ValueError:
        return (1, name)


def _stored_medium(raw: object) -> str:
    return _medium_name(raw) or "GPU"


def _medium_name(raw: object) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    text = raw.strip().upper()
    if not text:
        return None
    return _TIER_ALIASES.get(text, text)


def _hash_key(raw: object) -> Optional[str]:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return str(raw)


def _as_list(raw: object) -> list:
    if isinstance(raw, list):
        return raw
    return []
