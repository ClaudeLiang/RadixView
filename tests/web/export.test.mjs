import assert from "assert";

import { exportBody, exportFilename } from "../../radixview/web/js/export.mjs";
import { test } from "./harness.mjs";

test("exportFilename names the tree version", () => {
  assert.strictEqual(exportFilename(3), "radixview-node-blocks-v3.json");
  assert.strictEqual(exportFilename(0), "radixview-node-blocks-v0.json");
});

test("exportBody is pretty JSON with a trailing newline", () => {
  const text = exportBody({
    version: 1,
    nodes: [{ id: "7", blocks: [{ text: "你好" }] }],
  });
  assert.strictEqual(
    text,
    '{\n  "version": 1,\n  "nodes": [\n    {\n      "id": "7",\n      "blocks": [\n        {\n          "text": "你好"\n        }\n      ]\n    }\n  ]\n}\n',
  );
});
