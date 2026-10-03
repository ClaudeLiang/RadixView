// Entry point: node tests/web/run.mjs (tests/test_web.py runs it with mocks).

import { run } from "./harness.mjs";
import "./format.test.mjs";
import "./layout.test.mjs";
import "./viewport.test.mjs";
import "./render.test.mjs";

run().then((failed) => {
  process.exitCode = failed ? 1 : 0;
});
