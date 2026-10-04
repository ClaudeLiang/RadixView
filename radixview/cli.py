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
"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, Optional

from radixview.config import MonitorConfig
from radixview.serve import serve
from radixview.version import __version__

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radixview",
        description="Show KV-cache events from a SGLang server.",
    )
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:30000",
        help="Base URL of the SGLang HTTP server.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key of the SGLang server, if it was started with --api-key.",
    )
    parser.add_argument(
        "--view-port",
        type=_port,
        default=8765,
        help="Port for the radix tree page, on every interface. 0 picks a free port.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"radixview {__version__}",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = MonitorConfig.from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    _run(serve, config)


def _run(target: Callable[..., None], *args: object) -> None:
    try:
        target(*args)
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)


def _port(raw: str) -> int:
    value = int(raw)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"port must be in 0..65535, got {value}")
    return value
