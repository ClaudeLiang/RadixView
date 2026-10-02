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
"""Run the KV-event subscriber.

Discovers publishers from ``{server}/server_info`` and logs each
``BlockStored``, ``BlockRemoved``, and ``AllBlocksCleared``.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from radixview.config import MonitorConfig
from radixview.discover import load_publishers
from radixview.subscribe import listen

logger = logging.getLogger(__name__)


def serve(config: MonitorConfig, stop: Optional[threading.Event] = None) -> None:
    """Subscribe to ``config.server`` and log KV-cache events until ``stop``.

    Without ``stop`` this blocks until the caller is interrupted.
    """
    publishers = load_publishers(config.server, config.api_key)
    logger.info(
        "server=%s block_size=%s dp_size=%s",
        config.server,
        publishers.block_size,
        len(publishers.ranks),
    )
    listen(publishers, stop)
