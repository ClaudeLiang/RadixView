import assert from "assert";

import { layoutTree } from "../../radixview/web/js/layout.mjs";
import { drawScene } from "../../radixview/web/js/render.mjs";
import { TEXT_MIN_ZOOM, fitView, initialView } from "../../radixview/web/js/viewport.mjs";
import { THEME, mockSnapshot, node, recordingContext, test } from "./harness.mjs";

const SCREEN = { width: 1200, height: 800 };

function scene(nodes, extra = {}) {
  return { nodes, layout: layoutTree(nodes), selected: null, path: null, highlight: null, ...extra };
}

function draw(sceneValue, view) {
  const recorder = recordingContext();
  const result = drawScene(recorder.ctx, sceneValue, view, SCREEN, THEME);
  return { ...recorder, result };
}

test("draws every node, edge, title, and meta of a small tree", () => {
  const nodes = [
    node("r", null, { preview: "System prompt", pages: 5, tokens: 320 }),
    node("a", "r"),
    node("missing:9", null, { missing: true, preview: "", pages: 0, tokens: 0 }),
  ];
  const { result, named } = draw(scene(nodes), { x: 20, y: 20, z: 1 });
  assert.deepStrictEqual(result, { nodes: 3, edges: 1, text: true });
  const texts = named("fillText").map((call) => call[1]);
  assert.ok(texts.includes("System prompt"));
  assert.ok(texts.includes("5 pages · 320 tok · GPU"));
  assert.ok(texts.includes("Cached earlier"));
  assert.strictEqual(named("bezierCurveTo").length, 1);
  assert.strictEqual(named("stroke").length, 4, "one edge path plus one per node");
});

test("missing parents get a dashed border", () => {
  const nodes = [node("missing:9", null, { missing: true }), node("a", "missing:9")];
  const { named } = draw(scene(nodes), { x: 0, y: 0, z: 1 });
  const dashes = named("setLineDash").map((call) => call[1].length);
  assert.deepStrictEqual(dashes, [2, 0, 0, 0]);
});

test("the selection, its path, and search hits change the border", () => {
  const nodes = [node("r", null), node("a", "r"), node("b", "r")];
  const strokes = [];
  const recorder = recordingContext();
  const ctx = new Proxy(recorder.ctx, {
    set(target, prop, value) {
      if (prop === "strokeStyle") strokes.push(value);
      target[prop] = value;
      return true;
    },
  });
  const value = scene(nodes, { selected: "a", path: new Set(["r", "a"]), highlight: new Set(["b"]) });
  drawScene(ctx, value, { x: 0, y: 0, z: 1 }, SCREEN, THEME);
  assert.deepStrictEqual(strokes, [THEME.edge, THEME.accent, THEME.accent, THEME.hit]);
});

test("search dims everything that does not match", () => {
  const nodes = [node("r", null), node("a", "r")];
  const alphas = [];
  const recorder = recordingContext();
  const ctx = new Proxy(recorder.ctx, {
    set(target, prop, value) {
      if (prop === "globalAlpha") alphas.push(value);
      target[prop] = value;
      return true;
    },
  });
  drawScene(ctx, scene(nodes, { highlight: new Set(["a"]) }), { x: 0, y: 0, z: 1 }, SCREEN, THEME);
  assert.deepStrictEqual(alphas, [0.25, 0.25, 1, 1]);
});

test("the demo snapshot overview draws every node and edge", () => {
  const snapshot = mockSnapshot("demo");
  const value = scene(snapshot.nodes);
  const view = fitView(value.layout.width, value.layout.height, SCREEN);
  const { result } = draw(value, view);
  assert.strictEqual(result.nodes, snapshot.nodes.length);
  assert.strictEqual(result.edges, value.layout.parentOf.size);
  assert.strictEqual(result.text, view.z >= TEXT_MIN_ZOOM);
});

test("the demo snapshot opens with readable text on the system prompt", () => {
  const value = scene(mockSnapshot("demo").nodes);
  const { result, named } = draw(value, initialView(value.layout, SCREEN));
  const texts = named("fillText").map((call) => call[1]);
  assert.strictEqual(result.text, true);
  assert.ok(texts.some((text) => text.startsWith("System:")));
  assert.ok(texts.some((text) => text.startsWith("User:")));
});

test("a large tree only draws what is on screen", () => {
  const snapshot = mockSnapshot("large");
  const value = scene(snapshot.nodes);
  const { result, named } = draw(value, { x: 0, y: 0, z: 1 });
  assert.ok(snapshot.nodes.length > 2000);
  assert.ok(result.nodes > 0 && result.nodes < 60, `drew ${result.nodes} nodes`);
  assert.ok(result.edges < 60, `drew ${result.edges} edges`);
  assert.strictEqual(named("fillText").length, result.nodes * 2);
});

test("zoomed far out, a large tree draws boxes without text, fast", () => {
  const snapshot = mockSnapshot("large");
  const value = scene(snapshot.nodes);
  const view = fitView(value.layout.width, value.layout.height, SCREEN);
  const started = Date.now();
  const { result, named } = draw(value, view);
  const elapsed = Date.now() - started;
  assert.strictEqual(result.text, false);
  assert.strictEqual(named("fillText").length, 0);
  assert.ok(elapsed < 500, `drawing took ${elapsed}ms`);
});
