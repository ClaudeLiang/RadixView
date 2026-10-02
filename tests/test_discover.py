"""Publisher discovery from /server_info."""

import unittest

from fake_sglang import InfoServer, kv_events

from radixview.discover import load_publishers, publishers_from_info

_SERVER = "http://127.0.0.1:30000"


def _info(**overrides) -> dict:
    return {"kv_events": kv_events(**overrides)}


class TestPublishersFromInfo(unittest.TestCase):
    def test_dials_the_server_host_not_the_wildcard(self):
        publishers = publishers_from_info("http://10.0.0.8:30000", _info())
        self.assertEqual(publishers.block_size, 64)
        self.assertEqual(
            [rank.endpoint for rank in publishers.ranks],
            ["tcp://10.0.0.8:5557", "tcp://10.0.0.8:5558"],
        )
        self.assertEqual([rank.dp_rank for rank in publishers.ranks], [0, 1])

    def test_accepts_every_wildcard_host(self):
        for host in ["*", "0.0.0.0", "[::]"]:
            with self.subTest(host=host):
                publishers = publishers_from_info(_SERVER, _info(endpoint_host=host))
                self.assertEqual(publishers.ranks[0].endpoint, "tcp://127.0.0.1:5557")

    def test_brackets_an_ipv6_host(self):
        publishers = publishers_from_info("http://[::1]:30000", _info(dp_size=1))
        self.assertEqual(publishers.ranks[0].endpoint, "tcp://[::1]:5557")

    def test_keeps_a_nonempty_topic(self):
        publishers = publishers_from_info(_SERVER, _info(topic="kv-events"))
        self.assertEqual(publishers.ranks[0].topic, "kv-events")

    def test_a_null_topic_subscribes_to_everything(self):
        publishers = publishers_from_info(_SERVER, _info(topic=None))
        self.assertEqual(publishers.ranks[0].topic, "")

    def test_rejects_a_server_that_is_not_publishing(self):
        for info in [{}, {"kv_events": None}]:
            with self.subTest(info=info), self.assertRaises(RuntimeError):
                publishers_from_info(_SERVER, info)

    def test_rejects_a_publisher_that_is_not_zmq(self):
        with self.assertRaisesRegex(RuntimeError, "publisher"):
            publishers_from_info(_SERVER, _info(publisher="custom"))

    def test_rejects_a_connect_style_endpoint(self):
        with self.assertRaisesRegex(RuntimeError, "not a wildcard"):
            publishers_from_info(_SERVER, _info(endpoint_host="10.0.0.8"))

    def test_rejects_malformed_fields(self):
        cases = {
            "missing port": {"endpoint_port_base": None},
            "bool port": {"endpoint_port_base": True},
            "string dp_size": {"dp_size": "2"},
            "zero dp_size": {"dp_size": 0},
            "negative block_size": {"block_size": -1},
            "non-string topic": {"topic": 7},
            "port past u16": {"endpoint_port_base": 65535},
        }
        for name, overrides in cases.items():
            with self.subTest(name), self.assertRaises(RuntimeError):
                publishers_from_info(_SERVER, _info(**overrides))


class TestLoadPublishers(unittest.TestCase):
    def test_fetches_server_info(self):
        with InfoServer(_info(dp_size=1)) as server:
            publishers = load_publishers(server.url)
        self.assertEqual(len(publishers.ranks), 1)
        self.assertNotIn("Authorization", server.headers[0])

    def test_sends_the_api_key(self):
        with InfoServer(_info()) as server:
            load_publishers(server.url, api_key="sk")
        self.assertEqual(server.headers[0]["Authorization"], "Bearer sk")

    def test_reports_fetch_failures(self):
        cases = {
            "unauthorized": InfoServer({"error": "Unauthorized"}, status=401),
            "not json": InfoServer(b"<html>"),
            "not an object": InfoServer([1, 2]),
        }
        for name, info_server in cases.items():
            with self.subTest(name), info_server as server:
                with self.assertRaises(RuntimeError):
                    load_publishers(server.url)

    def test_reports_an_unreachable_server(self):
        with InfoServer(_info()) as server:
            url = server.url
        with self.assertRaisesRegex(RuntimeError, "failed to fetch"):
            load_publishers(url)


if __name__ == "__main__":
    unittest.main()
