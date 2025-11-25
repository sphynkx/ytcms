#!/bin/sh
source .venv/bin/activate
## Optionally, run once - to generate proto/captions_pb2.py and proto/captions_pb2_grpc.py if not exist:
##python -m grpc_tools.protoc  -I proto --python_out=. --grpc_python_out=. proto/captions.proto

#
python run.py --host 0.0.0.0 --port 9099
