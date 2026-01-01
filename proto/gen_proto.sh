#!/usr/bin/env bash
set -euo pipefail

# Generate stubs from captions.proto
# Make sure that captions.proto is identical to one from yurtube app!!

cd "$(dirname "$0")"

source ../.venv/bin/activate 

python -m grpc_tools.protoc \
  -I . \
  --python_out=. \
  --grpc_python_out=. \
  captions.proto

sed -i 's/^import captions_pb2 as captions__pb2/from . import captions_pb2 as captions__pb2/' captions_pb2_grpc.py

echo "Generated: captions_pb2.py captions_pb2_grpc.py in $(pwd)"
