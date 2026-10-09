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
"""Serve the tree page over synthetic agent traffic. No SGLang server needed."""

from __future__ import annotations

import argparse
import logging
import threading
from typing import Optional

from examples.demo.traffic import run_demo
from radixview.server import start_server, stop_server
from radixview.tree import CacheTree


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.demo",
        description="Serve the RadixView page over synthetic agent traffic.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=8765,
        help="Local port for the page. 0 picks a free port.",
    )
    parser.add_argument(
        "--blocks",
        type=_positive,
        default=400,
        help="How many cache blocks to keep.",
    )
    return parser


def serve_demo(port: int, blocks: int, stop: Optional[threading.Event] = None) -> None:
    """Serve the page until ``stop``. Without ``stop`` this does not return."""
    tree = CacheTree()
    httpd = start_server(tree, port)
    try:
        run_demo(tree, stop or threading.Event(), blocks)
    finally:
        stop_server(httpd)


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    try:
        serve_demo(args.port, args.blocks)
    except KeyboardInterrupt:
        pass


def _port(raw: str) -> int:
    value = int(raw)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"port must be in 0..65535, got {value}")
    return value


def _positive(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


if __name__ == "__main__":
    main()
