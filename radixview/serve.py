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
"""Run the KV-event subscriber and the tree page.

Discovers publishers from ``{server}/server_info``, logs each
``BlockStored``, ``BlockRemoved``, and ``AllBlocksCleared``, and keeps the
resulting radix tree for the page.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from radixview.config import MonitorConfig
from radixview.discover import load_publishers
from radixview.server import start_server, stop_server
from radixview.subscribe import listen
from radixview.text import Detokenizer
from radixview.tree import CacheTree

logger = logging.getLogger(__name__)


def serve(config: MonitorConfig, stop: Optional[threading.Event] = None) -> None:
    """Subscribe to ``config.server`` until ``stop``.

    Without ``stop`` this blocks until the caller is interrupted.
    """
    publishers = load_publishers(config.server, config.api_key)
    logger.info(
        "watching %s page=%s dp=%s",
        config.server,
        publishers.block_size,
        len(publishers.ranks),
    )
    tree = CacheTree()
    httpd = start_server(tree, config.view_port)
    try:
        listen(publishers, stop, Detokenizer(config.server, config.api_key), tree)
    finally:
        stop_server(httpd)
