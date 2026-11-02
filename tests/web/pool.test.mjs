import assert from "assert";

import { pagesByHash, releaseText, shownReleases, slotFields } from "../../radixview/web/js/pool.mjs";
import { test } from "./harness.mjs";

test("slotFields names the copy source and the page the way the block panel does", () => {
  const page = { id: "1..4", at: 1, blocks: 4, tokens: 256 };
  const fields = slotFields(
    {
      pool: "device",
      slot: 4,
      role: "checkpoint",
      hash: "-2285270490815386373",
      seqlen: 128,
    },
    page,
  );
  assert.strictEqual(fields.page, "2/4 …15386373");
  assert.strictEqual(fields.pageTitle, "-2285270490815386373");
  assert.strictEqual(fields.seqlen, "128");
  assert.strictEqual(fields.seqlenTitle, "this node is 256 tok");
  assert.strictEqual(fields.node, "1..4");
  assert.strictEqual(fields.from, "");

  const copy = slotFields({
    pool: "device",
    slot: 1,
    role: "request",
    req: "abc",
    src_pool: "device",
    src_slot: 4,
  });
  assert.strictEqual(copy.role, "request · abc");
  assert.strictEqual(copy.from, "device 4");
  assert.strictEqual(copy.page, "");
  assert.strictEqual(copy.node, "");

  const unlocated = slotFields({
    pool: "host",
    slot: 2,
    role: "checkpoint",
    hash: "-2285270490815386373",
    seqlen: 64,
  });
  assert.strictEqual(unlocated.page, "…15386373");
  assert.strictEqual(unlocated.seqlenTitle, "");
  assert.strictEqual(unlocated.node, "");
});

test("pagesByHash joins a checkpoint hash to its visual node", () => {
  const pages = pagesByHash([
    { id: "9", blocks: 1, tokens: 64, mamba: [{ at: 0, hash: "9" }] },
  ]);
  assert.strictEqual(pages.get("9").id, "9");
  assert.strictEqual(pages.get("9").at, 0);
});

test("shownReleases keeps live mismatches, newest first", () => {
  const rows = [
    { reason: "path_cap", kv: true, slot: 1 },
    { reason: "evict_device", kv: false, slot: 2 },
    { reason: "request_done", slot: 3 },
    { reason: "evict_host", kv: true, slot: 4 },
  ];
  rows.push(
    ...Array.from({ length: 6 }, (_, index) => ({ kv: true, slot: index + 5 })),
  );
  assert.deepStrictEqual(
    shownReleases(rows).map((row) => row.slot),
    [10, 9, 8, 7, 6, 5, 4, 1],
  );
  assert.strictEqual(
    releaseText({ pool: "device", slot: 5, reason: "path_cap", hash: "9", seqlen: 640 }),
    "path_cap · device 5 · 9 · 640 tok",
  );
});
