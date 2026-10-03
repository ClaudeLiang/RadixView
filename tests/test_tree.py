"""Radix tree rebuilt from KV-cache events."""

import unittest

from radixview.tree import CacheTree


def _stored(block_hash, parent, tokens=4):
    return {
        "type": "BlockStored",
        "block_hashes": [block_hash],
        "parent_block_hash": parent,
        "token_ids": list(range(tokens)),
        "block_size": tokens,
        "medium": "GPU",
    }


def _decode(text):
    def decode(_tokens):
        return text

    return decode


def _nodes(tree):
    return {node["id"]: node for node in tree.snapshot()["nodes"]}


class TestCacheTree(unittest.TestCase):
    def test_a_chain_and_its_missing_parent_collapse(self):
        tree = CacheTree()
        parent = 1137640873890580499
        hashes = [
            -2285270490815386373,
            2554827080280155894,
            5188292320627455716,
            5743247540568383516,
        ]
        texts = ["page B", "fingerprint pay", "this phone", "this device pays"]
        for block_hash, text in zip(hashes, texts):
            tree.apply_stored(_stored(block_hash, parent, tokens=64), _decode(text))
            parent = block_hash
        snapshot = tree.snapshot()
        self.assertEqual(
            snapshot["stats"], {"pages": 4, "tokens": 256, "nodes": 2, "missing": 1}
        )
        ghost = next(node for node in snapshot["nodes"] if node["missing"])
        chain = next(node for node in snapshot["nodes"] if not node["missing"])
        self.assertEqual(ghost["id"], "missing:1137640873890580499")
        self.assertIsNone(ghost["parent"])
        self.assertEqual(chain["parent"], ghost["id"])
        self.assertEqual(chain["pages"], 4)
        self.assertEqual(chain["preview"], "page B")
        pages = tree.pages_of(chain["id"])
        self.assertEqual([page["text"] for page in pages], texts)
        self.assertEqual(pages[0]["hash"], "-2285270490815386373")

    def test_a_branch_stays_visible(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("root"))
        tree.apply_stored(_stored(2, 1), _decode("left"))
        tree.apply_stored(_stored(3, 1), _decode("right"))
        nodes = _nodes(tree)
        self.assertEqual(set(nodes), {"1", "2", "3"})
        self.assertEqual(nodes["2"]["parent"], "1")
        self.assertEqual(nodes["3"]["parent"], "1")

    def test_a_chain_above_a_branch_is_one_node(self):
        tree = CacheTree()
        for block_hash, parent in [(1, None), (2, 1), (3, 2), (4, 3), (5, 3)]:
            tree.apply_stored(_stored(block_hash, parent), _decode(str(block_hash)))
        nodes = _nodes(tree)
        self.assertEqual(set(nodes), {"1..3", "4", "5"})
        self.assertEqual(nodes["4"]["parent"], "1..3")
        self.assertEqual(nodes["1..3"]["pages"], 3)

    def test_several_hashes_in_one_event_form_a_chain(self):
        tree = CacheTree()
        seen = []

        def decode(tokens):
            seen.append(list(tokens))
            return "p" + str(len(seen))

        tree.apply_stored(
            {
                "block_hashes": [10, 11],
                "parent_block_hash": None,
                "token_ids": [1, 2, 3, 4],
                "block_size": 2,
                "medium": "GPU",
            },
            decode,
        )
        self.assertEqual(seen, [[1, 2], [3, 4]])
        node = tree.snapshot()["nodes"][0]
        self.assertEqual(node["pages"], 2)
        self.assertEqual(
            [page["text"] for page in tree.pages_of(node["id"])], ["p1", "p2"]
        )

    def test_without_a_decoder_pages_have_no_text(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None))
        self.assertEqual(tree.pages_of("1")[0]["text"], "")

    def test_a_long_preview_is_one_clipped_line(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a\n" + "b" * 200))
        preview = _nodes(tree)["1"]["preview"]
        self.assertTrue(preview.startswith("a b"))
        self.assertTrue(preview.endswith("…"))
        self.assertLessEqual(len(preview), 81)

    def test_malformed_hashes_are_ignored(self):
        tree = CacheTree()
        tree.apply_stored({"block_hashes": [True, "x"], "token_ids": [1]})
        tree.apply_stored({"block_hashes": None})
        self.assertEqual(tree.snapshot()["version"], 0)
        tree.remove([True, "x"])
        self.assertEqual(tree.snapshot()["version"], 0)

    def test_removing_a_middle_page_leaves_a_missing_parent(self):
        tree = CacheTree()
        for block_hash, parent in [(1, None), (2, 1), (3, 2)]:
            tree.apply_stored(_stored(block_hash, parent), _decode("x"))
        tree.remove([2])
        nodes = _nodes(tree)
        self.assertEqual(set(nodes), {"1", "3", "missing:2"})
        self.assertEqual(nodes["3"]["parent"], "missing:2")

    def test_remove_and_clear(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        tree.apply_stored(_stored(2, 1), _decode("b"))
        tree.remove([1])
        nodes = tree.snapshot()["nodes"]
        self.assertEqual([node["id"] for node in nodes if not node["missing"]], ["2"])
        tree.clear()
        self.assertEqual(tree.snapshot()["stats"]["pages"], 0)
        self.assertEqual(tree.snapshot()["nodes"], [])

    def test_unknown_node_has_no_pages(self):
        self.assertEqual(CacheTree().pages_of("nope"), [])

    def test_a_long_chain_is_one_visual_node(self):
        tree = CacheTree()
        parent = None
        for index in range(3000):
            tree.apply_stored(_stored(index, parent, tokens=1), _decode("x"))
            parent = index
        snapshot = tree.snapshot()
        self.assertEqual(snapshot["stats"]["pages"], 3000)
        self.assertEqual(snapshot["stats"]["nodes"], 1)


class TestVersions(unittest.TestCase):
    def test_since_the_current_version_is_unchanged(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        version = tree.snapshot()["version"]
        self.assertEqual(
            tree.snapshot(since=version), {"version": version, "unchanged": True}
        )
        tree.apply_stored(_stored(2, 1), _decode("b"))
        self.assertIn("nodes", tree.snapshot(since=version))

    def test_the_view_is_reused_until_a_mutation(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        view = tree.view()
        self.assertIs(tree.view(), view)
        tree.remove([404])
        self.assertIs(tree.view(), view)
        tree.remove([1])
        self.assertIsNot(tree.view(), view)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tree = CacheTree()
        self.tree.apply_stored(_stored(1, None), _decode("system prompt"))
        self.tree.apply_stored(_stored(2, 1), _decode("Deploy rollout"))
        self.tree.apply_stored(_stored(3, 1), _decode("expense report"))

    def test_matches_any_page_case_insensitively(self):
        self.assertEqual(self.tree.search("  deploy "), ["2"])
        self.assertEqual(self.tree.search("expense"), ["3"])

    def test_a_blank_query_matches_nothing(self):
        self.assertEqual(self.tree.search("   "), [])
        self.assertEqual(self.tree.search("absent"), [])


if __name__ == "__main__":
    unittest.main()
