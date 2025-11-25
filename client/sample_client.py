import argparse
import grpc
import os
import time
import captions_pb2, captions_pb2_grpc

'''
For tests.. Maybe delete further.
Put some little *.webm and:
source .venv/bin/activate
python -m client.sample_client --host 127.0.0.1 --port 9099 --token CHANGE_ME --video ./test_short.webm --video-id testvid1 --lang auto --task transcribe

will output transcribe progres, the VTT output.
Progress still bad works with tiny model
'''

def chunk_file(path: str, chunk_size: int = 2_000_000):
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data

def gen_upload(video_path, video_id, lang, task):
    request_id = os.urandom(6).hex()
    parts = list(chunk_file(video_path))
    total = len(parts)
    for idx, data in enumerate(parts, start=1):
        yield captions_pb2.UploadChunk(
            request_id=request_id,
            video_id=video_id,
            lang=lang,
            task=task,
            data=data,
            last=(idx == total),
            filename=os.path.basename(video_path)
        )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9099)
    ap.add_argument("--token", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--video-id", default="vid1")
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--task", default="transcribe", choices=["transcribe","translate"])
    ap.add_argument("--wait", type=float, default=1.5)
    args = ap.parse_args()

    channel = grpc.insecure_channel(f"{args.host}:{args.port}")
    stub = captions_pb2_grpc.CaptionsServiceStub(channel)
    md = [("authorization", f"Bearer {args.token}")]

    print("Submitting job...")
    submit_reply = stub.Submit(gen_upload(args.video, args.video_id, args.lang, args.task), metadata=md)
    if submit_reply.status != "queued":
        print("Submit failed:", submit_reply.error)
        return
    print("Job queued:", submit_reply.job_id)

    while True:
        status = stub.GetStatus(captions_pb2.JobStatusRequest(job_id=submit_reply.job_id), metadata=md)
        print(f"Status={status.status} progress={status.progress*100:.1f}%")
        if status.status in ("done", "error"):
            break
        time.sleep(args.wait)

    if status.status == "done":
        result = stub.GetResult(captions_pb2.ResultRequest(job_id=submit_reply.job_id), metadata=md)
        print("Detected language:", result.detected_lang)
        print("Segments:", len(result.segments))
        print("VTT preview:\n", "\n".join(result.vtt.splitlines()))
    else:
        print("Job failed:", status.error)

if __name__ == "__main__":
    main()