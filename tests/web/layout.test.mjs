import assert from "assert";

import {
  COL_GAP,
  NODE_H,
  NODE_W,
  ROW_GAP,
  layoutTree,
  pathTo,
} from "../../radixview/web/js/layout.mjs";
import { mockSnapshot, node, test } from "./harness.mjs";

const STEP_X = NODE_W + COL_GAP;
const STEP_Y = NODE_H + ROW_GAP;

function assertNoOverlap(layout) {
  const columns = new Map();
  for (const point of layout.positions.values()) {
    const column = columns.get(point.x) || [];
    column.push(point.y);
    columns.set(point.x, column);
  }
  for (const ys of columns.values()) {
    ys.sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i += 1) {
      assert.ok(ys[i] - ys[i - 1] >= NODE_H, `boxes overlap at y=${ys[i]}`);
    }
  }
}

test("an empty tree has no size", () => {
  const layout = layoutTree([]);
  assert.strictEqual(layout.positions.size, 0);
  assert.strictEqual(layout.width, 0);
  assert.strictEqual(layout.height, 0);
});

test("a parent sits level with the middle of its children", () => {
  const layout = layoutTree([node("r", null), node("a", "r"), node("b", "r"), node("c", "r")]);
  const at = (id) => layout.positions.get(id);
  assert.deepStrictEqual([at("a").y, at("b").y, at("c").y], [0, STEP_Y, 2 * STEP_Y]);
  assert.deepStrictEqual(at("r"), { x: 0, y: STEP_Y });
  assert.strictEqual(at("a").x, STEP_X);
  assert.strictEqual(layout.width, 2 * STEP_X - COL_GAP);
  assert.strictEqual(layout.height, 3 * STEP_Y - ROW_GAP);
});

test("a node whose parent is absent becomes a root", () => {
  const layout = layoutTree([node("a", "gone"), node("b", "a"), node("c", null)]);
  assert.deepStrictEqual(layout.roots, ["a", "c"]);
  assert.strictEqual(layout.positions.get("a").x, 0);
  assert.strictEqual(layout.positions.get("c").x, 0);
  assert.strictEqual(layout.parentOf.get("b"), "a");
  assert.ok(!layout.parentOf.has("a"));
});

test("pathTo walks from the root down", () => {
  const layout = layoutTree([node("r", null), node("a", "r"), node("b", "a"), node("x", "r")]);
  assert.deepStrictEqual(pathTo("b", layout.parentOf), ["r", "a", "b"]);
  assert.deepStrictEqual(pathTo("r", layout.parentOf), ["r"]);
});

test("a very deep tree does not overflow the stack", () => {
  const nodes = [node("0", null)];
  for (let i = 1; i < 50000; i += 1) nodes.push(node(String(i), String(i - 1)));
  const layout = layoutTree(nodes);
  assert.strictEqual(layout.positions.size, 50000);
  assert.strictEqual(layout.height, NODE_H);
});

test("the demo snapshot lays out every node without overlap", () => {
  const snapshot = mockSnapshot("demo");
  const layout = layoutTree(snapshot.nodes);
  assert.strictEqual(layout.positions.size, snapshot.nodes.length);
  assertNoOverlap(layout);
  const roots = snapshot.nodes.filter((item) => !layout.parentOf.has(item.id));
  assert.strictEqual(roots.length, 2, "system prompt and one missing parent");
});

test("a large demo snapshot lays out quickly", () => {
  const snapshot = mockSnapshot("large");
  const started = Date.now();
  const layout = layoutTree(snapshot.nodes);
  const elapsed = Date.now() - started;
  assert.strictEqual(layout.positions.size, snapshot.nodes.length);
  assertNoOverlap(layout);
  assert.ok(elapsed < 500, `layout of ${snapshot.nodes.length} nodes took ${elapsed}ms`);
});
