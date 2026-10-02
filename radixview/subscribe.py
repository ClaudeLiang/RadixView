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
"""Subscribe to one server's KV-event publishers and log each event.

The publisher drops messages at its own high-water mark. This process only
connects, so a slow log line cannot stall the SGLang scheduler.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import zmq

from radixview.discover import PublisherSet, RankPublisher
from radixview.wire import decode_multipart, format_event, sequence_break

logger = logging.getLogger(__name__)

_RECEIVE_HWM = 10_000
_POLL_MS = 1000


def listen(publishers: PublisherSet, stop: Optional[threading.Event] = None) -> None:
    """Log every event from ``publishers`` until ``stop`` is set.

    Without ``stop`` this blocks until the caller is interrupted.
    """
    if stop is None:
        stop = threading.Event()
    context = zmq.Context()
    try:
        poller, rank_of = _register(context, publishers)
        _poll(poller, rank_of, stop)
    finally:
        context.destroy(linger=0)


def _register(
    context: zmq.Context, publishers: PublisherSet
) -> tuple[zmq.Poller, dict[zmq.Socket, int]]:
    poller = zmq.Poller()
    rank_of = {}
    for rank in publishers.ranks:
        sock = _connect(context, rank)
        poller.register(sock, zmq.POLLIN)
        rank_of[sock] = rank.dp_rank
    return poller, rank_of


def _connect(context: zmq.Context, rank: RankPublisher) -> zmq.Socket:
    sock = context.socket(zmq.SUB)
    sock.setsockopt(zmq.RCVHWM, _RECEIVE_HWM)
    sock.setsockopt(zmq.SUBSCRIBE, rank.topic.encode())
    sock.connect(rank.endpoint)
    logger.info(
        "subscribed dp_rank=%s endpoint=%s topic=%r",
        rank.dp_rank,
        rank.endpoint,
        rank.topic,
    )
    return sock


def _poll(
    poller: zmq.Poller, rank_of: dict[zmq.Socket, int], stop: threading.Event
) -> None:
    last_seq: dict[int, int] = {}
    while not stop.is_set():
        for sock, _event in poller.poll(_POLL_MS):
            _handle(sock.recv_multipart(), rank_of[sock], last_seq)


def _handle(frames: list[bytes], socket_rank: int, last_seq: dict[int, int]) -> None:
    try:
        batch = decode_multipart(frames)
    except ValueError as exc:
        logger.warning("dropped malformed batch on dp_rank=%s: %s", socket_rank, exc)
        return
    rank = socket_rank if batch.attn_dp_rank is None else batch.attn_dp_rank
    discontinuity = sequence_break(last_seq, rank, batch.seq)
    if discontinuity is not None:
        logger.warning("dp_rank=%s %s", rank, discontinuity)
    for event in batch.events:
        logger.info(
            "dp_rank=%s seq=%s ts=%s %s",
            rank,
            batch.seq,
            batch.ts,
            format_event(event),
        )
