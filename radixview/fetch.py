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
"""HTTP requests to the SGLang server.

``urllib`` sends every request through ``http_proxy``/``https_proxy`` unless
the host is in ``no_proxy``, and ``127.0.0.1`` is usually not. A proxy then
answers for the local server, often with 403. Loopback hosts are always
dialed directly.
"""

from __future__ import annotations

import ipaddress
import urllib.request
from http.client import HTTPResponse
from typing import Optional
from urllib.parse import urlparse

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def open_url(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    """``urlopen`` that skips proxies for loopback hosts."""
    if is_loopback(urlparse(request.full_url).hostname):
        return _DIRECT.open(request, timeout=timeout)
    return urllib.request.build_opener().open(request, timeout=timeout)


def is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
