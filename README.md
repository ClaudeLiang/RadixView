# RadixView

RadixView shows the KV cache of a running [SGLang](https://github.com/sgl-project/sglang) server. It subscribes to the server's ZMQ event stream, logs each stored, removed, and cleared page, and draws the radix tree at `http://<host>:8765`.

It can run on another machine from the GPU server. It does not route requests, and it does not read the server's radix tree in-process.

## Try the page

No GPU and no model required. From a checkout:

```bash
pip install -e ".[dev]"
python -m examples.demo
```

Open `http://127.0.0.1:8765`, or `http://<host>:8765` from another machine. The demo fills the tree with synthetic agent traffic: one shared system prompt, many sessions, a few regenerated turns, and eviction once the cache is full. `--pages 20000` keeps a larger cache. `--port` changes the port.

Prompt text for the demo is `examples/demo/corpus.json`. The generator is `examples/demo/traffic.py`. Neither is imported by the library.

## Watch a SGLang server

Start SGLang with KV events bound on a wildcard host. A concrete host such as `tcp://127.0.0.1:5557` makes the publisher connect instead of bind, and RadixView refuses to start.

```bash
python -m sglang.launch_server \
  --model-path MODEL_PATH \
  --kv-events-config '{"publisher":"zmq","endpoint":"tcp://*:5557"}'
```

Then, from this machine or another one that can reach the server:

```bash
radixview --server http://GPU_HOST:30000
```

Add `--api-key KEY` when SGLang was started with `--api-key`. The page listens on every interface at `--view-port` (8765 by default): open `http://<the host running RadixView>:8765`.

RadixView reads `/server_info` and subscribes to `tcp://GPU_HOST:<port_base + dp_rank>` for every data-parallel rank. Stored token ids are turned back into text through that server's `/detokenize` endpoint. A skipped sequence number is logged as a gap, and a sequence number that goes backwards is logged as a publisher restart.

Start RadixView before the traffic you care about, or restart the server after RadixView is up. A prefix stored earlier is not in the stream; the page draws it as a dashed node.

The events carry prompt token ids and are not encrypted. Do not publish the port on an open network.

## The page

The tree reads left to right, like a prompt. A straight chain of pages collapses into one node; a branch stays a separate node. Click a node for the text of each page. The search box matches the full page text, not only the preview.

Drag or scroll to pan. Cmd/Ctrl + scroll zooms. `F` fits the tree. `Esc` closes the detail panel.

## Repository

| Path | What changes there |
| --- | --- |
| `radixview/discover.py` | Finding ZMQ endpoints in `/server_info` |
| `radixview/wire.py` | Decoding an event batch |
| `radixview/subscribe.py` | The subscriber and the log line |
| `radixview/text.py` | `/detokenize` |
| `radixview/tree.py` | The radix tree built from events |
| `radixview/server.py` | the tree page and `/api/*` |
| `radixview/web/` | The page. No build step. Labels are in `web/js/format.mjs` |
| `examples/demo/` | Synthetic traffic. Not part of the library |
| `tests/` | Python tests. `tests/web/` tests the page modules |

`radixview/web/js/layout.mjs`, `viewport.mjs`, and `render.mjs` are pure and have no DOM. `main.mjs` wires them to the page.

## Development

Style follows SGLang: Apache-2.0 file headers, ruff format at line length 88, isort with the black profile, and ruff rules `F401`, `F821`, `F823`, and `UP037`. Ruff's `C901` keeps every function's cyclomatic complexity below 10.

```bash
pre-commit install
pre-commit run --all-files
python -m unittest discover -s tests
```

The page tests run under Node, through `tests/test_web.py`, on snapshots generated from the demo. They are skipped when `node` is not installed. Running the page itself does not need Node.

## License

Apache License 2.0. See [LICENSE](LICENSE).
