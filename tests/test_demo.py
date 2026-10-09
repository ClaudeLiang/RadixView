"""Synthetic agent traffic, kept outside the radixview library."""

import contextlib
import io
import json
import re
import threading
import time
import unittest
import urllib.request
from unittest import mock

from examples.demo import BLOCK_TOKENS, MISSING_PARENT, DemoTraffic, run_demo
from examples.demo.__main__ import build_parser, main, serve_demo
from examples.demo.traffic import load_corpus
from radixview.tree import CacheTree

_TIMEOUT_S = 10


def _populated(blocks=400, seed=0):
    tree = CacheTree()
    traffic = DemoTraffic(tree, blocks, seed)
    traffic.populate()
    return tree, traffic


def _page_url(logs) -> str:
    for line in logs.output:
        match = re.search(r"tree page (http://\S+)", line)
        if match:
            return match.group(1).replace("://0.0.0.0:", "://127.0.0.1:", 1)
    raise AssertionError("the tree page was not started")


def _wait_for_blocks(logs, blocks: int) -> dict:
    deadline = time.monotonic() + _TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            url = _page_url(logs)
        except AssertionError:
            time.sleep(0.05)
            continue
        with urllib.request.urlopen(url + "/api/tree") as response:
            snapshot = json.load(response)
        if snapshot["stats"]["blocks"] >= blocks:
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"the tree never reached {blocks} blocks")


class TestDemoTraffic(unittest.TestCase):
    def test_fills_the_cache_to_the_limit(self):
        tree, traffic = _populated(blocks=400)
        stats = tree.snapshot()["stats"]
        self.assertGreaterEqual(stats["blocks"], 400)
        self.assertEqual(stats["blocks"], traffic.blocks)
        self.assertEqual(stats["tokens"], stats["blocks"] * BLOCK_TOKENS)

    def test_sessions_share_the_system_prompt(self):
        tree, _ = _populated()
        corpus = load_corpus()
        nodes = tree.snapshot()["nodes"]
        roots = [node for node in nodes if node["parent"] is None]
        prompt = next(node for node in roots if not node["missing"])
        self.assertEqual(prompt["blocks"], len(corpus["system"]) + len(corpus["tools"]))
        self.assertTrue(prompt["preview"].startswith("System:"))
        children = [node for node in nodes if node["parent"] == prompt["id"]]
        self.assertGreater(len(children), 10)

    def test_one_chain_hangs_off_a_missing_parent(self):
        tree, _ = _populated()
        nodes = tree.snapshot()["nodes"]
        ghost = next(node for node in nodes if node["missing"])
        self.assertEqual(ghost["id"], f"missing:{MISSING_PARENT}")
        orphan = next(node for node in nodes if node["parent"] == ghost["id"])
        self.assertTrue(orphan["preview"].startswith("User:"))

    def test_every_block_has_text_and_a_known_medium(self):
        tree, _ = _populated()
        view = tree.view()
        blocks = [block for run in view.runs.values() for block in run]
        self.assertTrue(all(block.text for block in blocks))
        self.assertEqual({block.medium for block in blocks}, {"GPU", "CPU_PINNED"})

    def test_the_same_seed_builds_the_same_tree(self):
        first, _ = _populated(seed=3)
        second, _ = _populated(seed=3)
        self.assertEqual(first.snapshot()["nodes"], second.snapshot()["nodes"])

    def test_live_steps_evict_the_oldest_leaves(self):
        tree, traffic = _populated(blocks=200)
        before = set(tree.view().runs)
        for _ in range(100):
            traffic.step()
        stats = tree.snapshot()["stats"]
        self.assertLessEqual(stats["blocks"], 200)
        self.assertEqual(stats["blocks"], traffic.blocks)
        self.assertNotEqual(set(tree.view().runs), before)
        self.assertTrue(tree.search(load_corpus()["system"][0]))

    def test_a_tiny_cache_keeps_only_the_pinned_prefix(self):
        tree, traffic = _populated(blocks=1)
        for _ in range(5):
            traffic.step()
        shared = load_corpus()
        self.assertEqual(
            tree.snapshot()["stats"]["blocks"],
            len(shared["system"]) + len(shared["tools"]),
        )

    def test_decode_unknown_tokens(self):
        _, traffic = _populated(blocks=1)
        self.assertIsNone(traffic.decode([]))
        self.assertIsNone(traffic.decode([10**9]))

    def test_a_large_cache(self):
        tree, _ = _populated(blocks=20000)
        stats = tree.snapshot()["stats"]
        self.assertGreaterEqual(stats["blocks"], 20000)
        self.assertLess(stats["nodes"], stats["blocks"])


class TestRunDemo(unittest.TestCase):
    def test_steps_every_interval_until_stopped(self):
        stop = threading.Event()
        steps = []

        def step(_traffic):
            steps.append(1)
            if len(steps) == 3:
                stop.set()

        with mock.patch.object(DemoTraffic, "step", step):
            with self.assertLogs("examples.demo.traffic", "INFO") as logs:
                run_demo(CacheTree(), stop, blocks=50, interval_s=0.001)
        self.assertEqual(len(steps), 3)
        self.assertIn("demo traffic blocks=", logs.output[0])

    def test_serves_the_page_without_a_server(self):
        stop = threading.Event()
        with self.assertLogs("radixview.server", "INFO") as logs:
            thread = threading.Thread(target=serve_demo, args=(0, 60, stop))
            thread.start()
            try:
                snapshot = _wait_for_blocks(logs, 60)
            finally:
                stop.set()
                thread.join(_TIMEOUT_S)
        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(snapshot["stats"]["blocks"], 60)
        self.assertEqual(snapshot["stats"]["missing"], 1)


class TestDemoCommand(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.port, 8765)
        self.assertEqual(args.blocks, 400)

    def test_rejects_bad_numbers(self):
        for argv in [["--port", "70000"], ["--port", "-1"], ["--blocks", "0"]]:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit) as ctx:
                        build_parser().parse_args(argv)
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(argv[0], stderr.getvalue())

    @mock.patch("examples.demo.__main__.serve_demo")
    def test_main_serves_the_parsed_arguments(self, serve):
        main(["--port", "9", "--blocks", "50"])
        serve.assert_called_once_with(9, 50)

    @mock.patch("examples.demo.__main__.serve_demo", side_effect=KeyboardInterrupt)
    def test_ctrl_c_exits_quietly(self, _serve):
        main([])


if __name__ == "__main__":
    unittest.main()
