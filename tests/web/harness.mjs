// Minimal test runner, so the page tests need nothing beyond Node itself.

import { readFileSync } from "fs";

const cases = [];
const FULL_RUN = "python -m unittest discover -s tests -p test_web.py";

class Skip extends Error {}

export function test(name, fn) {
  cases.push({ name, fn });
}

export async function run() {
  let failed = 0;
  let skipped = 0;
  for (const { name, fn } of cases) {
    try {
      await fn();
      console.log("ok   " + name);
    } catch (error) {
      if (error instanceof Skip) {
        skipped += 1;
        console.log("SKIP " + name + " (" + error.message + ")");
        continue;
      }
      failed += 1;
      console.log("FAIL " + name + "\n" + error.stack);
    }
  }
  const passed = cases.length - failed - skipped;
  console.log(`${passed} passed, ${skipped} skipped, ${failed} failed`);
  if (skipped) console.log("Run every test on demo snapshots with: " + FULL_RUN);
  return failed;
}

// Snapshots written by tests/test_web.py from examples/demo traffic.
export function mockSnapshot(name) {
  const dir = process.env.RADIXVIEW_MOCK_DIR;
  if (!dir) throw new Skip("needs demo snapshots");
  return JSON.parse(readFileSync(`${dir}/${name}.json`, "utf8"));
}

// A 2D context that records every call instead of drawing.
export function recordingContext() {
  const calls = [];
  const state = {};
  const ctx = new Proxy(state, {
    get(target, prop) {
      if (prop in target) return target[prop];
      return (...args) => calls.push([prop, ...args]);
    },
    set(target, prop, value) {
      target[prop] = value;
      return true;
    },
  });
  const named = (name) => calls.filter((call) => call[0] === name);
  return { ctx, calls, named };
}

export const THEME = {
  ratio: 2,
  font: "sans-serif",
  text: "#e8e9ed",
  muted: "#9aa1ad",
  accent: "#9eb7ef",
  missing: "#d2b36a",
  node: "#22262e",
  nodeLine: "#3c4452",
  edge: "#4c5566",
  hit: "#7fd1a8",
  gpu: "#9eb7ef",
  cpu: "#e0b15a",
  other: "#7f8794",
};

export function node(id, parent, extra = {}) {
  return {
    id,
    parent,
    preview: "text " + id,
    blocks: 1,
    tokens: 64,
    media: ["GPU"],
    missing: false,
    ...extra,
  };
}
