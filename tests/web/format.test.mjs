import assert from "assert";

import {
  clip,
  hitsLine,
  nodeMeta,
  nodeTitle,
  blockMeta,
  poolOccupancy,
  shortHash,
  statsLine,
} from "../../radixview/web/js/format.mjs";
import { node, test } from "./harness.mjs";

test("clip counts characters, not UTF-16 units", () => {
  assert.strictEqual(clip("abcdef", 3), "abc…");
  assert.strictEqual(clip("😀😀😀", 2), "😀😀…");
  assert.strictEqual(clip("short", 16), "short");
  assert.strictEqual(clip(null, 4), "");
});

test("nodeTitle falls back for empty and missing nodes", () => {
  assert.strictEqual(nodeTitle(node("1", null)), "text 1");
  assert.strictEqual(nodeTitle(node("1", null, { preview: "" })), "(empty)");
  assert.strictEqual(
    nodeTitle(node("missing:9", null, { missing: true })),
    "Cached earlier",
  );
});

test("nodeMeta shows blocks only for a collapsed chain", () => {
  assert.strictEqual(nodeMeta(node("1", null)), "64 tok · GPU");
  assert.strictEqual(
    nodeMeta(node("1..3", null, { blocks: 3, tokens: 192, media: ["CPU"] })),
    "3 blocks · 192 tok · CPU",
  );
  assert.strictEqual(
    nodeMeta(node("1", null, { media: ["GPU", "CPU"] })),
    "64 tok · GPU+CPU",
  );
  assert.strictEqual(nodeMeta(node("1", null, { media: [] })), "64 tok");
  assert.strictEqual(
    nodeMeta(node("missing:1137640873890580499", null, { missing: true })),
    "parent …90580499",
  );
  assert.strictEqual(
    nodeMeta(node("1..4", null, {
      blocks: 4,
      tokens: 256,
      mamba: [{ at: 1, pool: "device", slot: 4, hash: "2" }],
    })),
    "4 blocks · 256 tok · GPU · mamba 1/4",
  );
  assert.strictEqual(
    nodeMeta(node("1", null, { mamba: [{ at: 0, pool: "device", slot: 2 }] })),
    "64 tok · GPU · mamba",
  );
});

test("statsLine leads with the logical size, then each tier", () => {
  const gpu = { blocks: 4, tokens: 256 };
  const cpu = { blocks: 1, tokens: 64 };
  assert.strictEqual(
    statsLine({ blocks: 4, tokens: 256, nodes: 2, missing: 0, tiers: { GPU: gpu } }),
    "4 blocks · 256 tok · 2 nodes · GPU 4 blocks (256 tok)",
  );
  assert.strictEqual(
    statsLine({ blocks: 4, tokens: 256, nodes: 2, missing: 1, tiers: { GPU: gpu, CPU: cpu } }),
    "4 blocks · 256 tok · 2 nodes · 1 missing · GPU 4 blocks (256 tok) · CPU 1 blocks (64 tok)",
  );
  assert.strictEqual(
    statsLine({ blocks: 0, tokens: 0, nodes: 0, missing: 0, tiers: {} }),
    "0 blocks · 0 tok · 0 nodes",
  );
  assert.strictEqual(
    statsLine({
      blocks: 4,
      tokens: 256,
      nodes: 2,
      missing: 0,
      tiers: { GPU: gpu },
      mamba: { pools: {}, slots: [{ slot: 1 }] },
    }),
    "4 blocks · 256 tok · 2 nodes · GPU 4 blocks (256 tok)",
  );
  assert.strictEqual(
    statsLine({
      blocks: 4,
      tokens: 256,
      nodes: 2,
      missing: 0,
      tiers: { GPU: gpu },
      mamba: {
        pools: { device: 8 },
        slots: [{ pool: "device", slot: 1 }, { pool: "device", slot: 2 }],
      },
    }),
    "4 blocks · 256 tok · 2 nodes · GPU 4 blocks (256 tok) · mamba device 2/8",
  );
  assert.strictEqual(
    statsLine({
      blocks: 4,
      tokens: 256,
      nodes: 2,
      missing: 0,
      tiers: {},
      mamba: {
        pools: { host: 4, device: 8 },
        slots: [{ pool: "device", slot: 1 }],
      },
    }),
    "4 blocks · 256 tok · 2 nodes · mamba device 1/8 · host 0/4",
  );
  assert.strictEqual(
    poolOccupancy({ pools: { ckpt: 2, device: 8 }, slots: [] }),
    "device 0/8 · ckpt 0/2",
  );
});

test("hitsLine and blockMeta", () => {
  assert.strictEqual(hitsLine("", []), "");
  assert.strictEqual(hitsLine("x", []), "no hits");
  assert.strictEqual(hitsLine("x", ["1", "2"]), "2 hits");
  assert.strictEqual(
    blockMeta({ tokens: 64, media: ["GPU"], hash: "-2285270490815386373" }),
    "GPU · 64 tok · …15386373",
  );
  assert.strictEqual(
    blockMeta({ tokens: 64, media: ["GPU", "CPU"], hash: "7" }),
    "GPU+CPU · 64 tok · 7",
  );
  assert.strictEqual(blockMeta({ tokens: 1, media: [], hash: "7" }), "- · 1 tok · 7");
  assert.strictEqual(
    blockMeta({
      tokens: 64,
      media: ["GPU"],
      hash: "8",
      mamba: [{ pool: "device", slot: 17 }],
    }),
    "GPU · 64 tok · 8 · device 17",
  );
  assert.strictEqual(shortHash(42), "42");
});
