This is supplemental service for [YurTube app](https://github.com/sphynkx/yurtube) for WebVTT-captions generation. Based on faster-whisper, gRPC+protobuf, Redis.

## Install and config
If ffmpeg andd its devel-packages not installed:
```bash
sudo dnf install --nogpgcheck   https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install -y ffmpeg ffmpeg-devel pkgconf-pkg-config
```

Next:
```bash
cd /opt
git clone https://github.com/sphynkx/ytcms
cd ytcms
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r install/requirements.txt
```

Optionaly - edit `proto/captions.proto` and generate stubs:
```bash
python -m grpc_tools.protoc  -I proto --python_out=. --grpc_python_out=. proto/captions.proto
```

Make sure that `captions_pb2.py` and `captions_pb2_grpc.py` have been created in the root service dir.

Optionally edit `config.py` - port, model etc.. And run:
```bash
export YTCMS_TOKEN="MY_SECRET_TOKEN"
python -m ytcms.server.run_server --host 0.0.0.0 --port 9099
```
or via `./run.sh`


## Test
Put in the root service dir some short video file and run test:
```bash
source .venv/bin/activate
python -m client.sample_client --host 127.0.0.1 --port 9099 --token CHANGE_ME --video ./test.webm --video-id testvid1 --lang auto --task transcribe
```
You may see transcribe progress and finally output WebVTT content.
