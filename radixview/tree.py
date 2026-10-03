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

A straight chain of pages collapses into one visual node, so a long prompt
does not become a long line of boxes. Branch points stay separate nodes.
A page whose parent was stored before the subscriber attached hangs off a
placeholder node marked ``missing``.

Readers get an immutable view that is rebuilt only after a mutation, so a
page polling once a second costs nothing while the cache is idle.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

Decode = Callable[[list], Optional[str]]

_PREVIEW_CHARS = 80
_SEARCH_LIMIT = 500


@dataclass(frozen=True, slots=True)
class Page:
    """One resident cache page."""

    hash: str
    parent: Optional[str]
    text: str
    tokens: int
    medium: str


@dataclass(frozen=True, slots=True)
class TreeView:
    """Visual nodes for one version of the tree."""

    version: int
    nodes: list[dict]
    stats: dict
    runs: dict[str, tuple[Page, ...]]
    haystacks: dict[str, str]


class CacheTree:
    """Resident pages keyed by the block hash from the event."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pages: dict[str, Page] = {}
        self._version = 0
        self._view: Optional[TreeView] = None

    def apply_stored(self, event: dict, decode: Optional[Decode] = None) -> None:
        """Insert the pages of one ``BlockStored`` event."""
        pages = [_page(spec, decode) for spec in _stored_specs(event)]
        if not pages:
            return
        with self._lock:
            self._pages.update((page.hash, page) for page in pages)
            self._version += 1

    def remove(self, hashes: list) -> None:
        """Drop the pages named by a ``BlockRemoved`` event."""
        keys = [key for key in map(_hash_key, hashes) if key is not None]
        with self._lock:
            removed = [self._pages.pop(key, None) for key in keys]
            if any(removed):
                self._version += 1

    def clear(self) -> None:
        """Drop every page, for ``AllBlocksCleared`` or a publisher restart."""
        with self._lock:
            self._pages.clear()
            self._version += 1

    def snapshot(self, since: Optional[int] = None) -> dict:
        """Visual nodes, or only the version when ``since`` is current."""
        view = self.view()
        if since == view.version:
            return {"version": view.version, "unchanged": True}
        return {"version": view.version, "nodes": view.nodes, "stats": view.stats}

    def pages_of(self, node_id: str) -> list[dict]:
        """Every page inside one visual node, in prefix order."""
        return [_page_detail(page) for page in self.view().runs.get(node_id, ())]

    def search(self, query: str) -> list[str]:
        """Ids of the visual nodes whose page text contains ``query``."""
        needle = query.strip().lower()
        if not needle:
            return []
        view = self.view()
        hits = [node_id for node_id, text in view.haystacks.items() if needle in text]
        return hits[:_SEARCH_LIMIT]

    def view(self) -> TreeView:
        """The current view, rebuilt only when the pages changed."""
        with self._lock:
            if self._view is not None and self._view.version == self._version:
                return self._view
            pages = dict(self._pages)
            version = self._version
        view = _build_view(pages, version)
        with self._lock:
            if version == self._version:
                self._view = view
        return view


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
    medium = str(event.get("medium") or "GPU")
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


def _page(spec: _Spec, decode: Optional[Decode]) -> Page:
    text = ""
    if decode is not None and spec.tokens:
        text = decode(spec.tokens) or ""
    return Page(spec.hash, spec.parent, text, len(spec.tokens), spec.medium)


def _build_view(pages: dict[str, Page], version: int) -> TreeView:
    runs = _runs(pages)
    owner = {page.hash: run_id for run_id, run in runs.items() for page in run}
    nodes = [_node(run_id, run, owner) for run_id, run in runs.items()]
    nodes.extend(_placeholders(nodes))
    haystacks = {
        run_id: "\n".join(page.text for page in run).lower()
        for run_id, run in runs.items()
    }
    return TreeView(version, nodes, _stats(pages, nodes), runs, haystacks)


def _runs(pages: dict[str, Page]) -> dict[str, tuple[Page, ...]]:
    children = _children(pages)
    seen: set[str] = set()
    runs: dict[str, tuple[Page, ...]] = {}
    stack = [page.hash for page in pages.values() if page.parent not in pages]
    stack.reverse()
    while stack:
        head = stack.pop()
        if head in seen:
            continue
        run = _unary_run(head, children, seen)
        runs[_run_id(run)] = tuple(pages[key] for key in run)
        stack.extend(reversed(children[run[-1]]))
    return runs


def _children(pages: dict[str, Page]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {key: [] for key in pages}
    for page in pages.values():
        if page.parent in children:
            children[page.parent].append(page.hash)
    return children


def _unary_run(head: str, children: dict[str, list[str]], seen: set[str]) -> list[str]:
    run = []
    cursor = head
    while cursor not in seen:
        run.append(cursor)
        seen.add(cursor)
        if len(children[cursor]) != 1:
            break
        cursor = children[cursor][0]
    return run


def _run_id(run: list[str]) -> str:
    if len(run) == 1:
        return run[0]
    return f"{run[0]}..{run[-1]}"


def _node(run_id: str, run: tuple[Page, ...], owner: dict[str, str]) -> dict:
    first = run[0]
    return {
        "id": run_id,
        "parent": _visual_parent(first.parent, owner),
        "preview": _preview(first.text),
        "pages": len(run),
        "tokens": sum(page.tokens for page in run),
        "medium": first.medium,
        "missing": False,
    }


def _visual_parent(parent: Optional[str], owner: dict[str, str]) -> Optional[str]:
    if parent is None:
        return None
    return owner.get(parent, f"missing:{parent}")


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
        "pages": 0,
        "tokens": 0,
        "medium": "",
        "missing": True,
    }


def _stats(pages: dict[str, Page], nodes: list[dict]) -> dict:
    return {
        "pages": len(pages),
        "tokens": sum(page.tokens for page in pages.values()),
        "nodes": len(nodes),
        "missing": sum(1 for node in nodes if node["missing"]),
    }


def _page_detail(page: Page) -> dict:
    return {
        "hash": page.hash,
        "text": page.text,
        "tokens": page.tokens,
        "medium": page.medium,
    }


def _hash_key(raw: object) -> Optional[str]:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return str(raw)


def _as_list(raw: object) -> list:
    if isinstance(raw, list):
        return raw
    return []
