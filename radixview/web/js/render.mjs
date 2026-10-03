// Canvas drawing. Only boxes inside the viewport are drawn, edges go out in
// one stroked path, and text is skipped when zoomed far out.

import { clip, nodeMeta, nodeTitle } from "./format.mjs";
import { NODE_H, NODE_W } from "./layout.mjs";
import { TEXT_MIN_ZOOM, boxVisible, worldRect } from "./viewport.mjs";

const TITLE_CHARS = 16;
const DIM_ALPHA = 0.25;

export function drawScene(ctx, scene, view, screen, theme) {
  const ratio = theme.ratio || 1;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, screen.width, screen.height);
  ctx.setTransform(ratio * view.z, 0, 0, ratio * view.z, ratio * view.x, ratio * view.y);
  const rect = worldRect(view, screen);
  const edges = drawEdges(ctx, scene, rect, view, theme);
  const shown = scene.nodes.filter((node) => boxVisible(scene.layout.positions.get(node.id), rect));
  const text = view.z >= TEXT_MIN_ZOOM;
  for (const node of shown) {
    drawNode(ctx, node, scene, { theme, text, z: view.z });
  }
  ctx.globalAlpha = 1;
  return { nodes: shown.length, edges, text };
}

function drawEdges(ctx, scene, rect, view, theme) {
  const { positions, parentOf } = scene.layout;
  let count = 0;
  ctx.beginPath();
  for (const [id, parent] of parentOf) {
    const from = positions.get(parent);
    const to = positions.get(id);
    if (!edgeVisible(from, to, rect)) continue;
    const x1 = from.x + NODE_W;
    const y1 = from.y + NODE_H / 2;
    const y2 = to.y + NODE_H / 2;
    const mid = (x1 + to.x) / 2;
    ctx.moveTo(x1, y1);
    ctx.bezierCurveTo(mid, y1, mid, y2, to.x, y2);
    count += 1;
  }
  ctx.strokeStyle = theme.edge;
  ctx.lineWidth = 1.25 / view.z;
  ctx.globalAlpha = scene.highlight ? DIM_ALPHA : 1;
  ctx.stroke();
  return count;
}

function edgeVisible(from, to, rect) {
  const top = Math.min(from.y, to.y);
  const bottom = Math.max(from.y, to.y) + NODE_H;
  return from.x < rect.x + rect.w && to.x + NODE_W > rect.x
    && top < rect.y + rect.h && bottom > rect.y;
}

function drawNode(ctx, node, scene, opts) {
  const { theme, z } = opts;
  const point = scene.layout.positions.get(node.id);
  const selected = node.id === scene.selected;
  ctx.globalAlpha = scene.highlight && !scene.highlight.has(node.id) ? DIM_ALPHA : 1;
  ctx.fillStyle = theme.node;
  ctx.strokeStyle = nodeStroke(node, scene, theme);
  ctx.lineWidth = (selected ? 2 : 1) / z;
  ctx.setLineDash(node.missing ? [4 / z, 3 / z] : []);
  roundRect(ctx, point.x, point.y, NODE_W, NODE_H, 8);
  ctx.fill();
  ctx.stroke();
  ctx.setLineDash([]);
  if (!opts.text) return;
  ctx.fillStyle = node.missing ? theme.missing : theme.text;
  ctx.font = "13px " + theme.font;
  ctx.fillText(clip(nodeTitle(node), TITLE_CHARS), point.x + 12, point.y + 27);
  ctx.fillStyle = theme.muted;
  ctx.font = "12px " + theme.font;
  ctx.fillText(nodeMeta(node), point.x + 12, point.y + 48);
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
