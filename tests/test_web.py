"""Runs the page tests in tests/web with Node, on snapshots from demo traffic."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from examples.demo import DemoTraffic
from radixview.tree import CacheTree

_RUNNER = Path(__file__).with_name("web") / "run.mjs"
_MOCKS = {"demo": 400, "large": 20000}


def _write_mocks(directory: str) -> None:
    for name, pages in _MOCKS.items():
        tree = CacheTree()
        DemoTraffic(tree, pages, seed=1).populate()
        Path(directory, f"{name}.json").write_text(
            json.dumps(tree.snapshot(), ensure_ascii=False), encoding="utf-8"
        )


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TestWeb(unittest.TestCase):
    def test_page_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_mocks(directory)
            result = subprocess.run(
                ["node", str(_RUNNER)],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "RADIXVIEW_MOCK_DIR": directory},
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
