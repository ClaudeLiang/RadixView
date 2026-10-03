import assert from "assert";

import { NODE_H, NODE_W, layoutTree } from "../../radixview/web/js/layout.mjs";
import {
  MAX_ZOOM,
  MIN_ZOOM,
  TEXT_MIN_ZOOM,
  boxVisible,
  centerOn,
  fitView,
  hitTest,
  initialView,
  panBy,
  toWorld,
  worldRect,
  zoomAt,
} from "../../radixview/web/js/viewport.mjs";
import { mockSnapshot, node, test } from "./harness.mjs";

const SCREEN = { width: 1000, height: 600 };

test("initialView shows a small tree whole", () => {
  const layout = layoutTree([node("r", null), node("a", "r")]);
  assert.deepStrictEqual(initialView(layout, SCREEN), fitView(layout.width, layout.height, SCREEN));
  assert.deepStrictEqual(initialView(layoutTree([]), SCREEN), { x: 40, y: 40, z: 1 });
});

test("initialView keeps a wide tree readable around its first root", () => {
  const layout = layoutTree(mockSnapshot("demo").nodes);
  assert.ok(fitView(layout.width, layout.height, SCREEN).z < TEXT_MIN_ZOOM);
  const view = initialView(layout, SCREEN);
  assert.ok(view.z >= TEXT_MIN_ZOOM);
  const root = layout.positions.get(layout.roots[0]);
  const left = root.x * view.z + view.x;
  const middle = (root.y + NODE_H / 2) * view.z + view.y;
  assert.strictEqual(left, 40);
  assert.strictEqual(middle, SCREEN.height / 2);
});

test("panBy moves without zooming", () => {
  assert.deepStrictEqual(panBy({ x: 1, y: 2, z: 0.5 }, 10, -20), { x: 11, y: -18, z: 0.5 });
});

test("fitView centers a small tree without blowing it up", () => {
  const view = fitView(NODE_W, NODE_H, SCREEN);
  assert.strictEqual(view.z, 1.15);
  assert.strictEqual(view.x, (SCREEN.width - NODE_W * view.z) / 2);
  assert.strictEqual(view.y, (SCREEN.height - NODE_H * view.z) / 2);
});

test("fitView shrinks a wide tree into the screen", () => {
  const view = fitView(9200, 400, SCREEN);
  assert.ok(view.z < 0.11);
  assert.ok(9200 * view.z <= SCREEN.width);
  assert.strictEqual(fitView(1e7, 400, SCREEN).z, MIN_ZOOM);
  assert.deepStrictEqual(fitView(0, 0, SCREEN), { x: 40, y: 40, z: 1 });
  assert.deepStrictEqual(fitView(100, 100, { width: 0, height: 0 }), { x: 40, y: 40, z: 1 });
});

test("zoomAt keeps the point under the cursor fixed and clamps", () => {
  const view = { x: 10, y: 20, z: 1 };
  const before = toWorld(view, 300, 200);
  const zoomed = zoomAt(view, 1.5, 300, 200);
  const after = toWorld(zoomed, 300, 200);
  assert.ok(Math.abs(before.x - after.x) < 1e-9);
  assert.ok(Math.abs(before.y - after.y) < 1e-9);
  assert.strictEqual(zoomAt(view, 100, 0, 0).z, MAX_ZOOM);
  assert.strictEqual(zoomAt(view, 1e-6, 0, 0).z, MIN_ZOOM);
});

test("centerOn puts a box in the middle of the screen", () => {
  const view = centerOn({ x: 0, y: 0, z: 0.5 }, { x: 1000, y: 400 }, SCREEN);
  const middle = toWorld(view, SCREEN.width / 2, SCREEN.height / 2);
  assert.strictEqual(middle.x, 1000 + NODE_W / 2);
  assert.strictEqual(middle.y, 400 + NODE_H / 2);
  assert.strictEqual(view.z, 0.5);
});

test("boxVisible culls boxes outside the world rect", () => {
  const rect = worldRect({ x: -100, y: 0, z: 2 }, SCREEN);
  assert.deepStrictEqual(rect, { x: 50, y: 0, w: 500, h: 300 });
  assert.ok(boxVisible({ x: 0, y: 0 }, rect));
  assert.ok(!boxVisible({ x: 600, y: 0 }, rect));
  assert.ok(!boxVisible({ x: 0, y: 400 }, rect));
  assert.ok(!boxVisible({ x: -NODE_W, y: 0 }, rect));
});

test("hitTest finds the box under a screen point", () => {
  const positions = new Map([["a", { x: 0, y: 0 }], ["b", { x: 400, y: 0 }]]);
  const view = { x: 10, y: 10, z: 0.5 };
  assert.strictEqual(hitTest(positions, view, 15, 15), "a");
  assert.strictEqual(hitTest(positions, view, 10 + 410 * 0.5, 15), "b");
  assert.strictEqual(hitTest(positions, view, 10 + 300 * 0.5, 15), null);
});
