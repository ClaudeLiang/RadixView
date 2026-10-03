// Pan and zoom. A view maps world point p to screen point p * z + (x, y).

import { NODE_H, NODE_W } from "./layout.mjs";

export const MIN_ZOOM = 0.05;
export const MAX_ZOOM = 2.5;
export const TEXT_MIN_ZOOM = 0.45;
const READ_ZOOM = 0.8;
const FIT_MAX_ZOOM = 1.15;
const FIT_PAD = 40;

// The whole tree when it is readable that way, otherwise the first root at
// reading size on the left edge.
export function initialView(layout, screen) {
  const fit = fitView(layout.width, layout.height, screen);
  const root = layout.positions.get(layout.roots[0]);
  if (fit.z >= TEXT_MIN_ZOOM || !root) return fit;
  return {
    x: FIT_PAD - root.x * READ_ZOOM,
    y: screen.height / 2 - (root.y + NODE_H / 2) * READ_ZOOM,
    z: READ_ZOOM,
  };
}

export function fitView(width, height, screen) {
  if (!width || !screen.width || !screen.height) return { x: FIT_PAD, y: FIT_PAD, z: 1 };
  const z = clampZoom(Math.min(
    (screen.width - 2 * FIT_PAD) / width,
    (screen.height - 2 * FIT_PAD) / height,
    FIT_MAX_ZOOM,
  ));
  return {
    x: Math.max(FIT_PAD / 2, (screen.width - width * z) / 2),
    y: Math.max(FIT_PAD / 2, (screen.height - height * z) / 2),
    z,
  };
}

export function zoomAt(view, factor, px, py) {
  const z = clampZoom(view.z * factor);
  return {
    x: px - ((px - view.x) * z) / view.z,
    y: py - ((py - view.y) * z) / view.z,
    z,
  };
}

export function panBy(view, dx, dy) {
  return { x: view.x + dx, y: view.y + dy, z: view.z };
}

export function centerOn(view, point, screen) {
  return {
    x: screen.width / 2 - (point.x + NODE_W / 2) * view.z,
    y: screen.height / 2 - (point.y + NODE_H / 2) * view.z,
    z: view.z,
  };
}

export function toWorld(view, sx, sy) {
  return { x: (sx - view.x) / view.z, y: (sy - view.y) / view.z };
}

export function worldRect(view, screen) {
  const { x, y } = toWorld(view, 0, 0);
  return { x, y, w: screen.width / view.z, h: screen.height / view.z };
}

export function boxVisible(point, rect) {
  return point.x < rect.x + rect.w && point.x + NODE_W > rect.x
    && point.y < rect.y + rect.h && point.y + NODE_H > rect.y;
}

export function hitTest(positions, view, sx, sy) {
  const { x, y } = toWorld(view, sx, sy);
  for (const [id, point] of positions) {
    if (x >= point.x && x <= point.x + NODE_W && y >= point.y && y <= point.y + NODE_H) {
      return id;
    }
  }
  return null;
}

function clampZoom(z) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));
}
