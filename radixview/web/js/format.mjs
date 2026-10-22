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
  return parts.join(" · ");
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
  return parts.join(" · ");
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
  return [mediaLabel(block.media) || "-", block.tokens + " tok", shortHash(block.hash)].join(" · ");
}

export function shortHash(hash) {
  const text = String(hash);
  if (text.length <= 10) return text;
  return "…" + text.slice(-8);
}
