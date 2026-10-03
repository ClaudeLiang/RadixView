# Copyright 2026 RadixView Authors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Discover the ZMQ endpoints a SGLang server is publishing on.

``/server_info`` advertises a bind address. The host half is a wildcard
(``*``, ``0.0.0.0``, or ``[::]``), which cannot be dialed. Subscribers
replace it with the host of the server URL they already use for HTTP.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

_RESTART = (
    "restart it with "
    '--kv-events-config \'{"publisher":"zmq","endpoint":"tcp://*:5557"}\'; '
    "a process that is already running does not pick the flag up"
)
# SGLang binds its PUB socket only on these hosts. On any other host it
# connects instead, and a dialing subscriber can never reach it.
_WILDCARD_HOSTS = ("*", "0.0.0.0", "[::]")


@dataclass(frozen=True, slots=True)
class RankPublisher:
    """One DP rank's PUB socket."""

    dp_rank: int
    endpoint: str
    topic: str


@dataclass(frozen=True, slots=True)
class PublisherSet:
    """Every rank of one SGLang server."""

    block_size: int
    ranks: tuple[RankPublisher, ...]


def load_publishers(server: str, api_key: Optional[str] = None) -> PublisherSet:
    """Fetch ``/server_info`` and return one endpoint per DP rank."""
    info = _get_json(f"{server}/server_info", api_key)
    return publishers_from_info(server, info)


def publishers_from_info(server: str, info: dict) -> PublisherSet:
    """Build dial addresses from an already-fetched ``/server_info`` body.

    ``server`` is a base URL already validated by ``MonitorConfig``.
    """
    kv = _kv_block(info)
    _require_wildcard_host(kv)
    host = _dial_host(server)
    base = _as_int(kv, "endpoint_port_base")
    dp_size = _positive(_as_int(kv, "dp_size"), "dp_size")
    block_size = _positive(_as_int(kv, "block_size"), "block_size")
    topic = _topic(kv)
    ranks = tuple(_rank_publisher(host, base, topic, rank) for rank in range(dp_size))
    return PublisherSet(block_size=block_size, ranks=ranks)


def _get_json(url: str, api_key: Optional[str]) -> dict:
    request = urllib.request.Request(url, headers=_auth_headers(api_key))
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"failed to fetch {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return payload


def _auth_headers(api_key: Optional[str]) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _kv_block(info: dict) -> dict:
    """The structured ``kv_events`` block, or one built from the raw CLI string.

    Older servers dump ``--kv-events-config`` as ``kv_events_config`` and do
    not build the structured block.
    """
    kv = info.get("kv_events")
    if isinstance(kv, dict):
        return _require_zmq(kv, "kv_events")
    cfg = _config_dict(info.get("kv_events_config"))
    if cfg is None:
        raise RuntimeError(_not_publishing(info))
    return _describe(info, cfg)


def _require_zmq(kv: dict, where: str) -> dict:
    if kv.get("publisher") != "zmq":
        raise RuntimeError(
            f"{where}.publisher is {kv.get('publisher')!r}, expected 'zmq'"
        )
    return kv


def _config_dict(raw: object) -> Optional[dict]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"kv_events_config is not JSON: {exc}") from exc
    if isinstance(raw, dict):
        return raw
    return None


def _not_publishing(info: dict) -> str:
    configured = info.get("kv_events_config", "<absent>")
    return (
        "this server's /server_info has no KV-event publisher "
        f"(kv_events={info.get('kv_events')!r}, kv_events_config={configured!r}). "
        + _RESTART
    )


def _describe(info: dict, cfg: dict) -> dict:
    _require_zmq(cfg, "kv_events_config")
    host, port = _split_tcp(cfg.get("endpoint"))
    return {
        "publisher": "zmq",
        "endpoint_host": host,
        "endpoint_port_base": port,
        "topic": cfg.get("topic") or "",
        "block_size": _event_block_size(info),
        "dp_size": _dp_size(info),
    }


def _split_tcp(endpoint: object) -> tuple[str, int]:
    if not isinstance(endpoint, str) or not endpoint.startswith("tcp://"):
        raise RuntimeError(
            f"kv_events_config.endpoint must be tcp://, got {endpoint!r}"
        )
    host, port = _host_port(endpoint[len("tcp://") :])
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise RuntimeError(
            f"kv_events_config.endpoint has no usable port: {endpoint!r}"
        )
    return host, int(port)


def _host_port(address: str) -> tuple[str, str]:
    if address.startswith("["):
        host, sep, rest = address[1:].partition("]")
        port = rest[1:] if sep and rest.startswith(":") else ""
        return f"[{host}]", port
    host, sep, port = address.rpartition(":")
    if not sep:
        return address, ""
    return host, port


def _event_block_size(info: dict) -> int:
    page_size = info.get("page_size")
    dcp_size = info.get("dcp_size", 1)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        raise RuntimeError(
            f"server_info page_size must be a positive int, got {page_size!r}"
        )
    if isinstance(dcp_size, bool) or not isinstance(dcp_size, int) or dcp_size <= 0:
        raise RuntimeError(
            f"server_info dcp_size must be a positive int, got {dcp_size!r}"
        )
    return page_size * dcp_size


def _dp_size(info: dict) -> int:
    value = info.get("dp_size", 1)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"server_info dp_size must be an int, got {value!r}")
    return value


def _require_wildcard_host(kv: dict) -> None:
    host = kv.get("endpoint_host")
    if host not in _WILDCARD_HOSTS:
        raise RuntimeError(
            f"KV event endpoint host {host!r} is not a wildcard, so SGLang "
            "connects to it instead of listening; use an endpoint such as "
            "tcp://*:5557"
        )


def _dial_host(server: str) -> str:
    host = urlparse(server).hostname
    if ":" in host:
        return f"[{host}]"
    return host


def _topic(kv: dict) -> str:
    topic = kv.get("topic") or ""
    if not isinstance(topic, str):
        raise RuntimeError("kv_events.topic must be a string")
    return topic


def _as_int(kv: dict, name: str) -> int:
    value = kv.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"kv_events.{name} must be an int")
    return value


def _positive(value: int, name: str) -> int:
    if value <= 0:
        raise RuntimeError(f"kv_events.{name} must be positive, got {value}")
    return value


def _rank_publisher(host: str, base: int, topic: str, rank: int) -> RankPublisher:
    port = base + rank
    if not 1 <= port <= 65535:
        raise RuntimeError(f"KV event port {port} for dp_rank={rank} is out of range")
    return RankPublisher(dp_rank=rank, endpoint=f"tcp://{host}:{port}", topic=topic)
