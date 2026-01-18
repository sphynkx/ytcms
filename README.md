This is supplemental service for [YurTube app](https://github.com/sphynkx/yurtube) for WebVTT-captions generation. Based on faster-whisper, gRPC+protobuf, Redis.

## Install and config
If ffmpeg andd its devel-packages not installed:
```bash
sudo dnf install --nogpgcheck   https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install -y ffmpeg ffmpeg-devel pkgconf-pkg-config redis python3 python3-devel gcc gcc-c++ grpcurl
```

Next:
```bash
cd /opt
git clone https://github.com/sphynkx/ytcms
cd ytcms
mkdir models
wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin -O models/lid.176.bin
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

Default config is 127.0.0.1:9099 but you may reconfigure it to multiserver configuration and redefine other params via `.env`:
```conf
YTCMS_WORKER_CONCURRENCY=2
YTCMS_MODEL=large-v3
YTCMS_COMPUTE_TYPE=float32

# Transcription parameters
YTCMS_BEAM_SIZE=8
YTCMS_VAD_FILTER=true
YTCMS_TEMPERATURE=0.2
YTCMS_COMPRESSION_RATIO_THRESHOLD=2.2
YTCMS_LOG_PROB_THRESHOLD=-1.0
YTCMS_NO_SPEECH_THRESHOLD=0.6
YTCMS_PATIENCE=1
YTCMS_PROGRESS_ASSUMED_MAX_SEGS=20
YTCMS_CONDITION_ON_PREVIOUS_TEXT=false
YTCMS_SUPPRESS_BLANK=true

# Mixed-language mode
##YTCMS_INITIAL_PROMPT="Transcribe the following audio in its spoken language. Do not translate."
YTCMS_MIXED_CHUNK_SEC=30
YTCMS_MIXED_OVERLAP_SEC=2
YTCMS_MIXED_RETRY_ISOLATED_LANG=true
YTCMS_MIXED_LOOKBEHIND_SEC=1.0
YTCMS_MAX_SEGMENT_SEC=10
YTCMS_MAX_SEGMENT_CHARS=50
YTCMS_SUBSEG_MAX_CHARS=50
YTCMS_SUBSEG_MAX_SEC=6
YTCMS_DISCLAIMER_MAX_SEC=4
YTCMS_FILTER_NOISE_SEGMENTS=true
# FastText
YTCMS_LID_ENABLED=true
YTCMS_LID_MODEL_PATH=/opt/ytcms/models/lid.176.bin
YTCMS_LID_CONFIDENCE=0.85
YTCMS_LID_FAVOR_NEIGHBORS=true
```

Make first run manually to initially download big model files:
```bash
export YTCMS_TOKEN="MY_SECRET_TOKEN"
python -m ytcms.server.run_server --host 0.0.0.0 --port 9099
```
or via `./run.sh`

__Note:__ At first run service downloads model and put it to
 `~/.cache/huggingface`. If you modify config and set another model - may be need to delete this cache before service rerun.
 

## Run via systemd
```bash
cp install/ytcms.service /etc/systemd/system/ytcms.service
sudo systemctl daemon-reload
sudo systemctl enable --now ytcms.service
sudo systemctl status ytcms.service
journalctl -u ytcms.service -f
```

## Run via docker
As above:
```bash
git clone https://github.com/sphynkx/ytcms
cd ytcms
mkdir models
curl -L -o models/lid.176.bin https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
```
And:
```bash
cd install/docker
docker-compose up -d --build
docker-compose logs -f
```

## Test
Health check/show methods via reflections:
```bash
dnf -y install grpcurl
grpcurl -plaintext 127.0.0.1:9099 list
grpcurl -plaintext 127.0.0.1:9099 list ytcms.CaptionsService
```

Put in the root service dir some short video file and run test:
```bash
source .venv/bin/activate
python -m client.sample_client --host 127.0.0.1 --port 9099 --token CHANGE_ME --video ./test.webm --video-id testvid1 --lang auto --task transcribe
```
You may see transcribe progress and finally output WebVTT content.
