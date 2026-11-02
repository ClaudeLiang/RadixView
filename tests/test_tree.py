"""Radix tree rebuilt from KV-cache events."""

import unittest

from radixview.tree import CacheTree


def _stored(block_hash, parent, tokens=4, medium="GPU"):
    return {
        "type": "BlockStored",
        "block_hashes": [block_hash],
        "parent_block_hash": parent,
        "token_ids": list(range(tokens)),
        "block_size": tokens,
        "medium": medium,
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
        texts = ["block B", "fingerprint pay", "this phone", "this device pays"]
        for block_hash, text in zip(hashes, texts):
            tree.apply_stored(_stored(block_hash, parent, tokens=64), _decode(text))
            parent = block_hash
        snapshot = tree.snapshot()
        self.assertEqual(
            snapshot["stats"],
            {
                "blocks": 4,
                "tokens": 256,
                "nodes": 2,
                "missing": 1,
                "tiers": {"GPU": {"blocks": 4, "tokens": 256}},
                "mamba": {"pools": {}, "slots": [], "log": [], "releases": []},
            },
        )
        ghost = next(node for node in snapshot["nodes"] if node["missing"])
        chain = next(node for node in snapshot["nodes"] if not node["missing"])
        self.assertEqual(ghost["id"], "missing:1137640873890580499")
        self.assertIsNone(ghost["parent"])
        self.assertEqual(chain["parent"], ghost["id"])
        self.assertEqual(chain["blocks"], 4)
        self.assertEqual(chain["preview"], "block B")
        blocks = tree.blocks_of(chain["id"])
        self.assertEqual([block["text"] for block in blocks], texts)
        self.assertEqual(blocks[0]["hash"], "-2285270490815386373")

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
        self.assertEqual(nodes["1..3"]["blocks"], 3)

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
        self.assertEqual(node["blocks"], 2)
        self.assertEqual(
            [block["text"] for block in tree.blocks_of(node["id"])], ["p1", "p2"]
        )

    def test_without_a_decoder_blocks_have_no_text(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None))
        self.assertEqual(tree.blocks_of("1")[0]["text"], "")

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

    def test_removing_a_middle_block_leaves_a_missing_parent(self):
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
        self.assertEqual(tree.snapshot()["stats"]["blocks"], 0)
        self.assertEqual(tree.snapshot()["nodes"], [])

    def test_unknown_node_has_no_blocks(self):
        self.assertEqual(CacheTree().blocks_of("nope"), [])

    def test_node_blocks_follow_the_chain_and_keep_missing_nodes(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, 9), _decode("seen"))
        tree.apply_stored(_stored(2, 1), _decode("next"))
        document = tree.node_blocks()
        self.assertEqual(document["version"], tree.snapshot()["version"])
        self.assertEqual(document["stats"]["missing"], 1)
        self.assertEqual(document["stats"]["nodes"], len(document["nodes"]))
        blocks = sum(len(node["blocks"]) for node in document["nodes"])
        self.assertEqual(document["stats"]["blocks"], blocks)
        by_id = {node["id"]: node for node in document["nodes"]}
        self.assertEqual(by_id["missing:9"]["blocks"], [])
        self.assertTrue(by_id["missing:9"]["missing"])
        self.assertIsNone(by_id["missing:9"]["parent"])
        chain = by_id["1..2"]
        self.assertEqual(chain["parent"], "missing:9")
        self.assertEqual(chain["media"], ["GPU"])
        self.assertFalse(chain["missing"])
        self.assertEqual(
            [
                (block["hash"], block["parent"], block["text"])
                for block in chain["blocks"]
            ],
            [("1", "9", "seen"), ("2", "1", "next")],
        )
        self.assertEqual(chain["blocks"][0]["tokens"], 4)
        self.assertEqual(chain["blocks"][0]["media"], ["GPU"])

    def test_node_blocks_record_each_branch(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("root"))
        tree.apply_stored(_stored(2, 1), _decode("left"))
        tree.apply_stored(_stored(3, 1), _decode("right"))
        by_id = {node["id"]: node for node in tree.node_blocks()["nodes"]}
        self.assertIsNone(by_id["1"]["parent"])
        self.assertIsNone(by_id["1"]["blocks"][0]["parent"])
        self.assertEqual(by_id["2"]["parent"], "1")
        self.assertEqual(by_id["2"]["blocks"][0]["parent"], "1")
        self.assertEqual(by_id["2"]["blocks"][0]["text"], "left")
        self.assertEqual(by_id["3"]["blocks"][0]["text"], "right")

    def test_an_empty_tree_exports_no_nodes(self):
        document = CacheTree().node_blocks()
        self.assertEqual(document["nodes"], [])
        self.assertEqual(document["stats"]["blocks"], 0)
        self.assertEqual(document["version"], 0)

    def test_one_hash_on_two_tiers_stays_one_block(self):
        calls = []

        def decode(_tokens):
            calls.append(1)
            return "prompt"

        tree = CacheTree()
        tree.apply_stored(_stored(1, None, tokens=64), decode)
        tree.apply_stored(_stored(1, None, tokens=64, medium="CPU_PINNED"), decode)
        self.assertEqual(calls, [1])
        block = tree.blocks_of("1")[0]
        self.assertEqual(block["text"], "prompt")
        self.assertEqual(block["media"], ["GPU", "CPU"])
        stats = tree.snapshot()["stats"]
        self.assertEqual(stats["blocks"], 1)
        self.assertEqual(stats["tokens"], 64)
        self.assertEqual(stats["tiers"]["GPU"], {"blocks": 1, "tokens": 64})
        self.assertEqual(stats["tiers"]["CPU"], {"blocks": 1, "tokens": 64})

    def test_a_chain_splits_when_the_tier_changes(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        tree.apply_stored(_stored(2, 1), _decode("b"))
        tree.apply_stored(_stored(3, 2, medium="CPU_PINNED"), _decode("c"))
        nodes = _nodes(tree)
        self.assertEqual(set(nodes), {"1..2", "3"})
        self.assertEqual(nodes["1..2"]["media"], ["GPU"])
        self.assertEqual(nodes["3"]["media"], ["CPU"])
        self.assertEqual(nodes["3"]["parent"], "1..2")

    def test_removing_one_tier_leaves_the_other(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        tree.apply_stored(_stored(1, None, medium="CPU_PINNED"), _decode("a"))
        tree.remove([1], "GPU")
        self.assertEqual(_nodes(tree)["1"]["media"], ["CPU"])
        tree.remove([1], "CPU_PINNED")
        self.assertEqual(tree.snapshot()["nodes"], [])

    def test_a_removal_without_a_medium_drops_every_tier(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        tree.apply_stored(_stored(1, None, medium="CPU_PINNED"), _decode("a"))
        tree.remove([1])
        self.assertEqual(tree.snapshot()["stats"]["blocks"], 0)

    def test_removing_a_tier_the_block_is_not_on_changes_nothing(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        version = tree.snapshot()["version"]
        tree.remove([1], "DISK")
        self.assertEqual(tree.snapshot()["version"], version)
        self.assertEqual(_nodes(tree)["1"]["media"], ["GPU"])

    def test_a_removal_with_an_unreadable_medium_changes_nothing(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        version = tree.snapshot()["version"]
        for medium in ["", "  ", 5]:
            with self.subTest(medium=medium):
                tree.remove([1], medium)
                self.assertEqual(tree.snapshot()["version"], version)

    def test_tier_names_ignore_case(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        tree.apply_stored(_stored(1, None, medium="cpu_pinned"), _decode("a"))
        tree.apply_stored(_stored(1, None, medium="gpu"), _decode("a"))
        self.assertEqual(_nodes(tree)["1"]["media"], ["GPU", "CPU"])
        tree.remove([1], "Gpu")
        self.assertEqual(_nodes(tree)["1"]["media"], ["CPU"])

    def test_a_later_store_fills_in_a_parent_but_never_replaces_one(self):
        tree = CacheTree()
        tree.apply_stored(_stored(2, None), _decode("b"))
        tree.apply_stored(_stored(2, 1, medium="CPU_PINNED"), _decode("b"))
        tree.apply_stored(_stored(2, 9, medium="DISK"), _decode("b"))
        self.assertEqual(_nodes(tree)["2"]["parent"], "missing:1")

    def test_locate_follows_a_block_when_its_chain_splits_or_joins(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        tree.apply_stored(_stored(2, 1), _decode("b"))
        tree.apply_stored(_stored(3, 2), _decode("c"))
        self.assertEqual(tree.locate("1"), "1..3")
        tree.apply_stored(_stored(2, 1, medium="CPU_PINNED"), _decode("b"))
        self.assertEqual(set(_nodes(tree)), {"1", "2", "3"})
        self.assertEqual(tree.locate("1..3"), "1")
        tree.remove([2], "CPU")
        self.assertEqual(tree.locate("2"), "1..3")
        self.assertEqual(tree.locate("3"), "1..3")
        tree.remove([1])
        self.assertIsNone(tree.locate("1..3"))
        self.assertIsNone(tree.locate("missing:1"))
        self.assertEqual(tree.locate("missing:2"), "2..3")
        self.assertIsNone(tree.locate(""))

    def test_storing_the_same_tier_again_keeps_the_version(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        version = tree.snapshot()["version"]
        view = tree.view()
        tree.apply_stored(_stored(1, None), _decode("b"))
        self.assertEqual(tree.snapshot()["version"], version)
        self.assertIs(tree.view(), view)
        self.assertEqual(tree.blocks_of("1")[0]["text"], "a")

    def test_disk_stays_its_own_tier(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None, medium="DISK"), _decode("a"))
        tree.apply_stored(_stored(1, None), _decode("a"))
        self.assertEqual(_nodes(tree)["1"]["media"], ["GPU", "DISK"])
        self.assertEqual(list(tree.snapshot()["stats"]["tiers"]), ["GPU", "DISK"])

    def test_a_long_chain_is_one_visual_node(self):
        tree = CacheTree()
        parent = None
        for index in range(3000):
            tree.apply_stored(_stored(index, parent, tokens=1), _decode("x"))
            parent = index
        snapshot = tree.snapshot()
        self.assertEqual(snapshot["stats"]["blocks"], 3000)
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

    def test_matches_any_block_case_insensitively(self):
        self.assertEqual(self.tree.search("  deploy "), ["2"])
        self.assertEqual(self.tree.search("expense"), ["3"])

    def test_a_blank_query_matches_nothing(self):
        self.assertEqual(self.tree.search("   "), [])
        self.assertEqual(self.tree.search("absent"), [])


class TestMambaPool(unittest.TestCase):
    def test_a_bind_marks_the_block_inside_a_collapsed_chain(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None, tokens=64), _decode("a"))
        tree.apply_stored(_stored(2, 1, tokens=64), _decode("b"))
        tree.apply_mamba(
            {
                "type": "MambaBind",
                "pool": "device",
                "slot": 4,
                "block_hash": 2,
                "seqlen": 128,
                "op": "donate",
            }
        )
        node = _nodes(tree)["1..2"]
        self.assertEqual(
            node["mamba"],
            [{"at": 1, "pool": "device", "slot": 4, "seqlen": 128, "hash": "2"}],
        )
        self.assertNotIn("mamba", _nodes(tree).get("missing", {}))
        block = tree.blocks_of("1..2")[1]
        self.assertEqual(block["mamba"][0]["slot"], 4)
        self.assertNotIn("mamba", tree.blocks_of("1..2")[0])

    def test_a_free_drops_the_mark_and_leaves_the_block(self):
        tree = CacheTree()
        tree.apply_stored(_stored(9, None), _decode("kept"))
        tree.apply_mamba(
            {
                "type": "MambaBind",
                "pool": "device",
                "slot": 3,
                "block_hash": 9,
                "seqlen": 64,
                "op": "donate",
            }
        )
        tree.apply_mamba(
            {
                "type": "MambaFree",
                "pool": "device",
                "slot": 3,
                "role": "checkpoint",
                "reason": "path_cap",
                "block_hash": 9,
                "seqlen": 64,
            }
        )
        self.assertNotIn("mamba", _nodes(tree)["9"])
        self.assertEqual(tree.blocks_of("9")[0]["text"], "kept")
        self.assertIn("path_cap", tree.snapshot()["stats"]["mamba"]["log"][-1])
        release = tree.snapshot()["stats"]["mamba"]["releases"][-1]
        self.assertEqual(release["reason"], "path_cap")
        self.assertEqual(release["hash"], "9")
        self.assertTrue(release["kv"])
        self.assertEqual(release["node"], "9")
        tree.apply_mamba(
            {
                "type": "MambaFree",
                "pool": "device",
                "slot": 1,
                "reason": "request_done",
            }
        )
        self.assertEqual(len(tree.snapshot()["stats"]["mamba"]["releases"]), 1)

    def test_removing_the_page_drops_its_release(self):
        tree = CacheTree()
        tree.apply_stored(_stored(9, None), _decode("gone"))
        tree.apply_mamba(
            {
                "type": "MambaFree",
                "pool": "device",
                "slot": 3,
                "reason": "evict_device",
                "block_hash": 9,
                "seqlen": 64,
            }
        )
        self.assertTrue(tree.snapshot()["stats"]["mamba"]["releases"][-1]["kv"])
        tree.apply_mamba(
            {
                "type": "MambaBind",
                "pool": "device",
                "slot": 4,
                "block_hash": 9,
                "seqlen": 64,
                "op": "donate",
            }
        )
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["releases"], [])
        tree.apply_mamba(
            {
                "type": "MambaFree",
                "pool": "device",
                "slot": 4,
                "reason": "evict_device",
                "block_hash": 9,
                "seqlen": 64,
            }
        )
        self.assertEqual(len(tree.snapshot()["stats"]["mamba"]["releases"]), 1)
        tree.remove([9])
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["releases"], [])

    def test_a_snapshot_replaces_the_pool_and_clear_keeps_its_size(self):
        tree = CacheTree()
        tree.apply_mamba(
            {
                "type": "MambaAlloc",
                "pool": "device",
                "slot": 2,
                "role": "request",
                "reason": "acquire",
            }
        )
        tree.apply_mamba(
            {
                "type": "MambaSnapshot",
                "pools": {"device": 8, "host": 4},
                "slots": [
                    {
                        "pool": "host",
                        "slot": 1,
                        "role": "checkpoint",
                        "block_hash": 5,
                        "seqlen": 64,
                    }
                ],
            }
        )
        slots = tree.snapshot()["stats"]["mamba"]["slots"]
        self.assertEqual([row["pool"] for row in slots], ["host"])
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["pools"]["device"], 8)
        tree.apply_stored(_stored(5, None), _decode("page"))
        tree.apply_mamba(
            {
                "type": "MambaFree",
                "pool": "device",
                "slot": 3,
                "reason": "path_cap",
                "block_hash": 5,
                "seqlen": 64,
            }
        )
        self.assertEqual(len(tree.snapshot()["stats"]["mamba"]["releases"]), 1)
        tree.clear()
        mamba = tree.snapshot()["stats"]["mamba"]
        self.assertEqual(mamba["slots"], [])
        self.assertEqual(mamba["log"], [])
        self.assertEqual(mamba["releases"], [])
        self.assertEqual(mamba["pools"]["device"], 8)

    def test_a_bad_event_is_ignored(self):
        tree = CacheTree()
        tree.apply_mamba({"type": "MambaAlloc", "pool": "device"})
        tree.apply_mamba("nope")
        self.assertEqual(tree.snapshot()["version"], 0)
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["slots"], [])

    def test_host_slot_zero_stays_in_a_snapshot(self):
        tree = CacheTree()
        tree.apply_stored(_stored(9, None), _decode("page"))
        tree.apply_mamba(
            {
                "type": "MambaSnapshot",
                "pools": {"host": 4, "device": 8},
                "slots": [
                    {
                        "pool": "host",
                        "slot": 0,
                        "role": "checkpoint",
                        "block_hash": 9,
                        "seqlen": 64,
                    },
                    {"pool": "device", "slot": 1, "role": "request"},
                ],
            }
        )
        mamba = tree.snapshot()["stats"]["mamba"]
        self.assertEqual(
            [(row["pool"], row["slot"]) for row in mamba["slots"]],
            [("device", 1), ("host", 0)],
        )
        self.assertEqual(_nodes(tree)["9"]["mamba"][0]["slot"], 0)
        version = tree.snapshot()["version"]
        tree.apply_mamba(
            {
                "type": "MambaSnapshot",
                "pools": {"host": 4},
                "slots": [{"pool": "host", "slot": -1, "role": "checkpoint"}],
            }
        )
        self.assertEqual(tree.snapshot()["version"], version)
        self.assertEqual(len(tree.snapshot()["stats"]["mamba"]["slots"]), 2)

    def test_an_unchanged_snapshot_does_not_bump_the_version(self):
        tree = CacheTree()
        event = {
            "type": "MambaSnapshot",
            "pools": {"device": 8, "host": 4},
            "slots": [
                {
                    "pool": "host",
                    "slot": 0,
                    "role": "checkpoint",
                    "block_hash": 9,
                    "seqlen": 64,
                }
            ],
        }
        tree.apply_mamba(event)
        version = tree.snapshot()["version"]
        recorded = list(tree.snapshot()["stats"]["mamba"]["log"])
        tree.apply_mamba(event)
        self.assertEqual(tree.snapshot()["version"], version)
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["log"], recorded)
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["slots"][0]["slot"], 0)

    def test_an_unchanged_alloc_does_not_bump_the_version(self):
        tree = CacheTree()
        event = {
            "type": "MambaAlloc",
            "pool": "device",
            "slot": 1,
            "role": "request",
            "reason": "cow",
            "src_slot": 4,
            "src_pool": "device",
        }
        tree.apply_mamba(event)
        version = tree.snapshot()["version"]
        tree.apply_mamba(event)
        self.assertEqual(tree.snapshot()["version"], version)

    def test_export_carries_the_pool_without_the_live_log(self):
        tree = CacheTree()
        tree.apply_stored(_stored(7, None), _decode("page"))
        tree.apply_mamba(
            {
                "type": "MambaBind",
                "pool": "ckpt",
                "slot": 2,
                "block_hash": 7,
                "seqlen": 64,
                "op": "int8_commit",
            }
        )
        document = tree.node_blocks()
        self.assertNotIn("log", document["mamba"])
        self.assertNotIn("log", document["stats"]["mamba"])
        self.assertNotIn("releases", document["mamba"])
        self.assertNotIn("releases", document["stats"]["mamba"])
        self.assertEqual(document["mamba"]["slots"][0]["slot"], 2)
        self.assertEqual(document["nodes"][0]["blocks"][0]["mamba"][0]["pool"], "ckpt")

    def test_a_free_without_a_hash_keeps_the_bound_page(self):
        tree = CacheTree()
        tree.apply_stored(_stored(9, None), _decode("kept"))
        tree.apply_mamba(
            {
                "type": "MambaBind",
                "pool": "device",
                "slot": 3,
                "block_hash": 9,
                "seqlen": 64,
                "op": "donate",
            }
        )
        tree.apply_mamba(
            {"type": "MambaFree", "pool": "device", "slot": 3, "reason": "path_cap"}
        )
        release = tree.snapshot()["stats"]["mamba"]["releases"][-1]
        self.assertEqual(release["hash"], "9")
        self.assertEqual(release["seqlen"], 64)
        self.assertEqual(release["node"], "9")

    def test_an_alloc_with_the_same_page_drops_the_old_release(self):
        tree = CacheTree()
        tree.apply_stored(_stored(9, None), _decode("page"))
        tree.apply_mamba(
            {
                "type": "MambaFree",
                "pool": "device",
                "slot": 3,
                "reason": "path_cap",
                "block_hash": 9,
                "seqlen": 64,
            }
        )
        tree.apply_mamba(
            {
                "type": "MambaAlloc",
                "pool": "device",
                "slot": 5,
                "role": "checkpoint",
                "reason": "acquire",
                "block_hash": 9,
                "seqlen": 64,
            }
        )
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["releases"], [])

    def test_a_repeated_free_keeps_the_newest_release(self):
        tree = CacheTree()
        tree.apply_stored(_stored(9, None), _decode("page"))
        for slot in (3, 4):
            tree.apply_mamba(
                {
                    "type": "MambaFree",
                    "pool": "device",
                    "slot": slot,
                    "reason": "evict_device",
                    "block_hash": 9,
                    "seqlen": 64,
                }
            )
        releases = tree.snapshot()["stats"]["mamba"]["releases"]
        self.assertEqual([row["slot"] for row in releases], [4])

    def test_marks_follow_pool_then_slot(self):
        tree = CacheTree()
        tree.apply_stored(_stored(1, None), _decode("a"))
        for pool, slot in (("host", 1), ("ckpt", 2)):
            tree.apply_mamba(
                {
                    "type": "MambaBind",
                    "pool": pool,
                    "slot": slot,
                    "block_hash": 1,
                    "seqlen": 64,
                    "op": "donate",
                }
            )
        pools = [mark["pool"] for mark in _nodes(tree)["1"]["mamba"]]
        self.assertEqual(pools, ["ckpt", "host"])
        exported = [mark["pool"] for mark in tree.blocks_of("1")[0]["mamba"]]
        self.assertEqual(exported, pools)

    def test_a_negative_seqlen_is_ignored(self):
        tree = CacheTree()
        tree.apply_mamba(
            {
                "type": "MambaBind",
                "pool": "device",
                "slot": 1,
                "block_hash": 9,
                "seqlen": -1,
                "op": "donate",
            }
        )
        self.assertEqual(tree.snapshot()["version"], 0)
        self.assertEqual(tree.snapshot()["stats"]["mamba"]["slots"], [])


if __name__ == "__main__":
    unittest.main()
