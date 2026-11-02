// Pool panel fields. The table is current occupancy. Releases are frees that
// dropped a mamba slot and left the KV page in the tree.

import { shortHash } from "./format.mjs";

export function pagesByHash(nodes) {
  const found = new Map();
  for (const node of nodes || []) {
    for (const mark of node.mamba || []) {
      if (mark.hash == null) continue;
      found.set(String(mark.hash), {
        id: node.id,
        at: mark.at,
        blocks: node.blocks,
        tokens: node.tokens,
      });
    }
  }
  return found;
}

export function slotFields(row, page) {
  const hash = row.hash == null ? "" : String(row.hash);
  return {
    pool: row.pool || "",
    slot: row.slot == null ? "" : String(row.slot),
    role: row.req ? row.role + " · " + row.req : (row.role || ""),
    roleTitle: row.req ? String(row.req) : "",
    from: sourceOf(row),
    page: pageText(hash, page),
    pageTitle: hash,
    seqlen: row.seqlen == null ? "" : String(row.seqlen),
    seqlenTitle: page ? "this node is " + page.tokens + " tok" : "",
    node: page ? page.id : "",
  };
}

export function shownReleases(releases) {
  const kept = [];
  for (const row of releases || []) {
    if (row.kv === true) kept.push(row);
  }
  return kept.reverse();
}

export function releaseText(row) {
  const parts = [row.reason || "free", (row.pool || "") + " " + row.slot];
  if (row.hash != null) parts.push(shortHash(row.hash));
  if (row.seqlen != null) parts.push(row.seqlen + " tok");
  return parts.join(" · ");
}

function sourceOf(row) {
  if (row.src_slot == null) return "";
  if (row.src_pool) return row.src_pool + " " + row.src_slot;
  return String(row.src_slot);
}

function pageText(hash, page) {
  if (!hash) return "";
  const label = shortHash(hash);
  if (!page || page.blocks == null) return label;
  return (page.at + 1) + "/" + page.blocks + " " + label;
}
