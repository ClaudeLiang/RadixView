// Entry point: node tests/web/run.mjs. Tests on demo snapshots are skipped
// unless tests/test_web.py runs this with RADIXVIEW_MOCK_DIR set.

import { run } from "./harness.mjs";
import "./format.test.mjs";
import "./pool.test.mjs";
import "./export.test.mjs";
import "./layout.test.mjs";
import "./viewport.test.mjs";
import "./render.test.mjs";

run().then((failed) => {
  process.exitCode = failed ? 1 : 0;
});
