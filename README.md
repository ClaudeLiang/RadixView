# RadixView

RadixView logs [SGLang](https://github.com/sgl-project/sglang) KV-cache events. It can run on another machine from the GPU server: the event stream is a ZMQ PUB socket. It does not route requests and it does not read the server's radix tree in-process.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.10 or newer.

## Run

Start SGLang with KV events bound on a wildcard host. With a concrete host such as `tcp://127.0.0.1:5557` the publisher connects instead of binding, and RadixView refuses to start.

```bash
python -m sglang.launch_server \
  --model-path MODEL_PATH \
  --kv-events-config '{"publisher":"zmq","endpoint":"tcp://*:5557"}'
```

Then, from this machine or another one that can reach the server:

```bash
radixview --server http://GPU_HOST:30000
```

Add `--api-key KEY` if SGLang was started with `--api-key`.

RadixView reads `kv_events` from `/server_info` and subscribes to `tcp://GPU_HOST:<port_base + dp_rank>` for every DP rank. Each `BlockStored`, `BlockRemoved`, and `AllBlocksCleared` is written to the log. Token ids are previewed, not printed in full. A skipped sequence number is logged as a gap, and a sequence number that goes back as a publisher restart.

Start RadixView before the server, or restart the server after it is up. A prefix stored before the subscriber attached is not part of the stream.

The events carry prompt token ids and are not encrypted. Do not publish the port on an open network.

## Development

Formatting and lint follow SGLang: Apache-2.0 file headers, ruff format (line length 88), isort with the black profile, and the ruff rules `F401`, `F821`, `F823`, and `UP037`. Ruff's `C901` also keeps every function's cyclomatic complexity at or below 10.

```bash
pre-commit install
pre-commit run --all-files
python -m unittest discover -s tests
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
