import assert from "assert";

import {
  clip,
  hitsLine,
  nodeMeta,
  nodeTitle,
  blockMeta,
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
    nodeMeta(node("1..3", null, { blocks: 3, tokens: 192, medium: "CPU_PINNED" })),
    "3 blocks · 192 tok · CPU_PINNED",
  );
  assert.strictEqual(nodeMeta(node("1", null, { medium: "" })), "64 tok");
  assert.strictEqual(
    nodeMeta(node("missing:1137640873890580499", null, { missing: true })),
    "parent …90580499",
  );
});

test("statsLine mentions missing parents only when there are some", () => {
  assert.strictEqual(
    statsLine({ blocks: 4, tokens: 256, nodes: 2, missing: 0 }),
    "4 blocks · 256 tok · 2 nodes",
  );
  assert.strictEqual(
    statsLine({ blocks: 4, tokens: 256, nodes: 2, missing: 1 }),
    "4 blocks · 256 tok · 2 nodes · 1 missing",
  );
});

test("hitsLine and blockMeta", () => {
  assert.strictEqual(hitsLine("", []), "");
  assert.strictEqual(hitsLine("x", []), "no hits");
  assert.strictEqual(hitsLine("x", ["1", "2"]), "2 hits");
  assert.strictEqual(
    blockMeta({ tokens: 64, medium: "GPU", hash: "-2285270490815386373" }),
    "64 tok · GPU · …15386373",
  );
  assert.strictEqual(blockMeta({ tokens: 1, medium: "", hash: "7" }), "1 tok · - · 7");
  assert.strictEqual(shortHash(42), "42");
});
