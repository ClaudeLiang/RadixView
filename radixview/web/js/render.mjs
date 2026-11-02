// Canvas drawing. Only boxes inside the viewport are drawn, edges go out in
// one stroked path per opacity, and text is skipped when zoomed far out.

import { clip, nodeMeta, nodeTitle } from "./format.mjs";
import { NODE_H, NODE_W } from "./layout.mjs";
import { TEXT_MIN_ZOOM, boxVisible, worldRect } from "./viewport.mjs";

const TITLE_CHARS = 16;
const BAR_W = 4;
const DIM_ALPHA = 0.25;

export function drawScene(ctx, scene, view, screen, theme) {
  const ratio = theme.ratio || 1;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, screen.width, screen.height);
  ctx.setTransform(ratio * view.z, 0, 0, ratio * view.z, ratio * view.x, ratio * view.y);
  const rect = worldRect(view, screen);
  const dimmed = dimmedByTier(scene.nodes, scene.tiers);
  const edges = drawEdges(ctx, scene, rect, view, theme, dimmed);
  const shown = scene.nodes.filter((node) => boxVisible(scene.layout.positions.get(node.id), rect));
  const text = view.z >= TEXT_MIN_ZOOM;
  for (const node of shown) {
    drawNode(ctx, node, scene, { theme, text, z: view.z, dimmed });
  }
  ctx.globalAlpha = 1;
  return { nodes: shown.length, edges, text };
}

function drawEdges(ctx, scene, rect, view, theme, dimmed) {
  const { positions, parentOf } = scene.layout;
  const bright = [];
  const faded = [];
  for (const [id, parent] of parentOf) {
    const from = positions.get(parent);
    const to = positions.get(id);
    if (!edgeVisible(from, to, rect)) continue;
    const fade = scene.highlight || (dimmed && (dimmed.has(id) || dimmed.has(parent)));
    (fade ? faded : bright).push([from, to]);
  }
  ctx.strokeStyle = theme.edge;
  ctx.lineWidth = 1.25 / view.z;
  strokeEdges(ctx, bright, 1);
  strokeEdges(ctx, faded, DIM_ALPHA);
  return bright.length + faded.length;
}

function strokeEdges(ctx, edges, alpha) {
  if (!edges.length) return;
  ctx.beginPath();
  for (const [from, to] of edges) {
    const x1 = from.x + NODE_W;
    const y1 = from.y + NODE_H / 2;
    const y2 = to.y + NODE_H / 2;
    const mid = (x1 + to.x) / 2;
    ctx.moveTo(x1, y1);
    ctx.bezierCurveTo(mid, y1, mid, y2, to.x, y2);
  }
  ctx.globalAlpha = alpha;
  ctx.stroke();
}

function edgeVisible(from, to, rect) {
  const top = Math.min(from.y, to.y);
  const bottom = Math.max(from.y, to.y) + NODE_H;
  return from.x < rect.x + rect.w && to.x + NODE_W > rect.x
    && top < rect.y + rect.h && bottom > rect.y;
}

function drawNode(ctx, node, scene, opts) {
  const point = scene.layout.positions.get(node.id);
  paintBox(ctx, node, scene, opts, point);
  paintBar(ctx, node, point, opts);
  paintMamba(ctx, node, point, opts.theme);
  if (opts.text) paintLabel(ctx, node, point, opts.theme);
}

function paintBox(ctx, node, scene, opts, point) {
  const selected = node.id === scene.selected;
  ctx.globalAlpha = nodeAlpha(node, scene, opts.dimmed);
  ctx.fillStyle = opts.theme.node;
  ctx.strokeStyle = nodeStroke(node, scene, opts.theme);
  ctx.lineWidth = (selected ? 2 : 1) / opts.z;
  ctx.setLineDash(node.missing ? [4 / opts.z, 3 / opts.z] : []);
  roundRect(ctx, point.x, point.y, NODE_W, NODE_H, 8);
  ctx.fill();
  ctx.stroke();
  ctx.setLineDash([]);
}

function paintBar(ctx, node, point, opts) {
  if (node.missing || !node.media || !node.media.length) return;
  // Zoomed out, the rounded corner is under a pixel; skip the costly clip.
  const rounded = opts.text;
  if (rounded) {
    ctx.save();
    roundRect(ctx, point.x, point.y, NODE_W, NODE_H, 8);
    ctx.clip();
  }
  const slice = NODE_H / node.media.length;
  node.media.forEach((name, index) => {
    ctx.fillStyle = tierColor(name, opts.theme);
    const y = point.y + index * slice;
    const height = index === node.media.length - 1 ? point.y + NODE_H - y : slice;
    ctx.fillRect(point.x, y, BAR_W, height);
  });
  if (rounded) ctx.restore();
}

function paintMamba(ctx, node, point, theme) {
  const marks = node.mamba;
  if (!marks || !marks.length) return;
  const covered = new Set(marks.map((mark) => mark.at)).size;
  ctx.fillStyle = theme.mamba;
  const count = Math.min(covered, 6);
  for (let index = 0; index < count; index += 1) {
    ctx.fillRect(point.x + NODE_W - 14 - index * 10, point.y + 8, 8, 4);
  }
}

function tierColor(name, theme) {
  if (name === "GPU") return theme.gpu;
  if (name === "CPU") return theme.cpu;
  return theme.other;
}

function paintLabel(ctx, node, point, theme) {
  ctx.fillStyle = node.missing ? theme.missing : theme.text;
  ctx.font = "13px " + theme.font;
  ctx.fillText(clip(nodeTitle(node), TITLE_CHARS), point.x + 16, point.y + 27);
  ctx.fillStyle = theme.muted;
  ctx.font = "12px " + theme.font;
  ctx.fillText(nodeMeta(node), point.x + 16, point.y + 48);
}

function nodeAlpha(node, scene, dimmed) {
  const missed = scene.highlight && !scene.highlight.has(node.id);
  if (missed || (dimmed && dimmed.has(node.id))) return DIM_ALPHA;
  return 1;
}

function dimmedByTier(nodes, tiers) {
  if (!tiers) return null;
  const names = Object.keys(tiers);
  const enabled = names.filter((name) => tiers[name]);
  if (enabled.length === names.length) return null;
  const off = (node) => !node.missing && !(node.media || []).some((name) => enabled.includes(name));
  return new Set(nodes.filter(off).map((node) => node.id));
}

function nodeStroke(node, scene, theme) {
  if (node.id === scene.selected) return theme.accent;
  if (scene.highlight && scene.highlight.has(node.id)) return theme.hit;
  if (scene.path && scene.path.has(node.id)) return theme.accent;
  return node.missing ? theme.missing : theme.nodeLine;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
