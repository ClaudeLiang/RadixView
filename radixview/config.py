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
"""Process configuration for one SGLang server."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

_SCHEMES = ("http", "https")


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    """The SGLang server to watch.

    KV-event ports come from that server's ``/server_info``. The dial host
    is this URL's host, so a wildcard bind address is never used as a
    destination.
    """

    server: str
    api_key: Optional[str] = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> MonitorConfig:
        server = args.server.rstrip("/")
        parsed = urlparse(server)
        if parsed.scheme not in _SCHEMES or not parsed.hostname:
            raise ValueError(
                f"--server must be an http(s) URL with a host, got {args.server!r}"
            )
        return cls(server=server, api_key=args.api_key or None)
