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
"""Turn stored token ids back into text through the server's tokenizer.

``/detokenize`` uses the same tokenizer the server encoded the prompt
with, so RadixView does not need the model files locally.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from radixview.fetch import open_url

logger = logging.getLogger(__name__)

_CACHE_LIMIT = 4096
_TIMEOUT_S = 5


class Detokenizer:
    """Cache of ``/detokenize`` results for one SGLang server."""

    def __init__(self, server: str, api_key: Optional[str] = None):
        self._url = f"{server}/detokenize"
        self._headers = _headers(api_key)
        self._cache: dict[tuple[int, ...], str] = {}
        self._disabled = False
        self._warned = False

    def decode(self, token_ids: object) -> Optional[str]:
        """Text for one page of token ids, or None when it cannot be decoded."""
        ids = _token_ids(token_ids)
        if ids is None or self._disabled:
            return None
        cached = self._cache.get(ids)
        if cached is not None:
            return cached
        text = self._fetch(ids)
        if text is not None:
            self._store(ids, text)
        return text

    def _fetch(self, token_ids: tuple[int, ...]) -> Optional[str]:
        body = json.dumps(
            {"tokens": list(token_ids), "skip_special_tokens": False}
        ).encode()
        request = urllib.request.Request(self._url, data=body, headers=self._headers)
        try:
            with open_url(request, timeout=_TIMEOUT_S) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            self._fail(exc.code, str(exc))
            return None
        except (OSError, ValueError) as exc:
            self._fail(None, str(exc))
            return None
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            self._fail(None, "response has no text")
            return None
        self._warned = False
        return text

    def _store(self, token_ids: tuple[int, ...], text: str) -> None:
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[token_ids] = text

    def _fail(self, status: Optional[int], detail: str) -> None:
        if status in (404, 405):
            self._disabled = True
            logger.warning("server has no /detokenize endpoint; logging token ids")
            return
        if self._warned:
            return
        self._warned = True
        logger.warning("detokenize failed: %s", detail)


def _headers(api_key: Optional[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _token_ids(raw: object) -> Optional[tuple[int, ...]]:
    if not isinstance(raw, list) or not raw:
        return None
    if any(_bad_id(item) for item in raw):
        return None
    return tuple(raw)


def _bad_id(item: object) -> bool:
    return isinstance(item, bool) or not isinstance(item, int)
