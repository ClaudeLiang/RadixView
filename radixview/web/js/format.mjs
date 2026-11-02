// Text shown on nodes, in the header, and in the detail panel.

export function clip(text, limit) {
  const chars = Array.from(text || "");
  if (chars.length <= limit) return chars.join("");
  return chars.slice(0, limit).join("") + "…";
}

export function nodeTitle(node) {
  if (node.missing) return "Cached earlier";
  return node.preview || "(empty)";
}

export function nodeMeta(node) {
  if (node.missing) return "parent " + shortHash(node.id.slice("missing:".length));
  const parts = [];
  if (node.blocks > 1) parts.push(node.blocks + " blocks");
  parts.push(node.tokens + " tok");
  const label = mediaLabel(node.media);
  if (label) parts.push(label);
  const mamba = mambaLabel(node);
  if (mamba) parts.push(mamba);
  return parts.join(" · ");
}

function mambaLabel(node) {
  const marks = node.mamba;
  if (!marks || !marks.length) return "";
  const covered = new Set(marks.map((mark) => mark.at)).size;
  if (!node.blocks || covered >= node.blocks) return "mamba";
  return "mamba " + covered + "/" + node.blocks;
}

// The server sends stats.tiers already in tier order.
export function statsLine(stats) {
  const parts = [
    stats.blocks + " blocks",
    stats.tokens + " tok",
    stats.nodes + " nodes",
  ];
  if (stats.missing) parts.push(stats.missing + " missing");
  for (const [name, tier] of Object.entries(stats.tiers || {})) {
    parts.push(name + " " + tier.blocks + " blocks (" + tier.tokens + " tok)");
  }
  const mamba = mambaStats(stats.mamba);
  if (mamba) parts.push(mamba);
  return parts.join(" · ");
}

const POOL_RANK = { device: 0, host: 1, ckpt: 2 };

// Occupied/size for each announced pool. The three pools number slots
// separately, so a single used/size sum hides which one is full.
export function poolOccupancy(mamba) {
  if (!mamba || !mamba.pools) return "";
  const names = Object.keys(mamba.pools).sort(poolOrder);
  if (!names.length) return "";
  const used = {};
  for (const row of mamba.slots || []) {
    used[row.pool] = (used[row.pool] || 0) + 1;
  }
  return names.map((name) => name + " " + (used[name] || 0) + "/" + mamba.pools[name]).join(" · ");
}

function poolOrder(left, right) {
  const rank = (name) => (name in POOL_RANK ? POOL_RANK[name] : 9);
  const gap = rank(left) - rank(right);
  if (gap) return gap;
  return left < right ? -1 : left > right ? 1 : 0;
}

function mambaStats(mamba) {
  const line = poolOccupancy(mamba);
  return line ? "mamba " + line : "";
}

function mediaLabel(media) {
  if (!media || !media.length) return "";
  return media.join("+");
}

export function hitsLine(query, ids) {
  if (!query) return "";
  return ids.length ? ids.length + " hits" : "no hits";
}

export function blockMeta(block) {
  const parts = [mediaLabel(block.media) || "-", block.tokens + " tok", shortHash(block.hash)];
  const marks = (block.mamba || []).map((row) => row.pool + " " + row.slot);
  if (marks.length) parts.push(marks.join(", "));
  return parts.join(" · ");
}

export function shortHash(hash) {
  const text = String(hash);
  if (text.length <= 10) return text;
  return "…" + text.slice(-8);
}
