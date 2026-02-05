import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, AsyncIterator

import grpc

from config import get_settings
from jobs.storage import storage
from proto import ytcms_pb2, ytcms_pb2_grpc

settings = get_settings()
logger = logging.getLogger("server")


def _norm_rel(p: str) -> str:
    s = (p or "").replace("\\", "/").strip().lstrip("/")
    parts = [x for x in s.split("/") if x and x != "."]
    return "/".join(parts)


def _join_rel(a: str, b: str) -> str:
    a2 = _norm_rel(a)
    b2 = _norm_rel(b)
    if not a2:
        return b2
    if not b2:
        return a2
    return f"{a2}/{b2}"


def _map_status_to_state(raw: str) -> int:
    st = (raw or "").strip().upper()
    if st in ("QUEUED",):
        return ytcms_pb2.JobStatus.QUEUED
    if st in ("PROCESSING", "RUNNING"):
        return ytcms_pb2.JobStatus.RUNNING
    if st in ("DONE",):
        return ytcms_pb2.JobStatus.DONE
    if st in ("ERROR", "FAILED", "FAIL"):
        return ytcms_pb2.JobStatus.FAILED
    if st in ("CANCELED", "CANCELLED"):
        return ytcms_pb2.JobStatus.CANCELED
    return ytcms_pb2.JobStatus.STATE_UNSPECIFIED


def _parse_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _parse_float(val: Any, default: float) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _job_snapshot(job_id: str, job_info: Dict[str, Any]) -> ytcms_pb2.JobStatus:
    raw_status = job_info.get("status") or ""
    percent = _parse_int(job_info.get("percent"), -1)
    if percent < 0:
        percent = 0
    if percent > 100:
        percent = 100

    err = (job_info.get("error") or "").strip()
    msg = ""
    state = _map_status_to_state(raw_status)
    if state == ytcms_pb2.JobStatus.FAILED and err:
        msg = err

    st = ytcms_pb2.JobStatus(
        job_id=job_id,
        state=state,
        percent=percent,
        message=msg,
    )
    if err:
        st.error.CopyFrom(ytcms_pb2.JobError(code="error", message=err))
    return st


class CaptionsServiceImpl(ytcms_pb2_grpc.CaptionsServiceServicer):
    def __init__(self, queue):
        self.queue = queue

    async def SubmitJob(self, request: ytcms_pb2.SubmitJobRequest, context) -> ytcms_pb2.JobAck:
        try:
            video_id = (request.video_id or "").strip()
            if not video_id:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="video_id is required")

            lang = (request.lang or "auto").strip() or "auto"
            task = (request.task or "transcribe").strip() or "transcribe"
            idem = (request.idempotency_key or "").strip()

            # validate source
            if not request.source or not request.source.storage:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="source.storage is required")
            src_addr = (request.source.storage.address or "").strip()
            if not src_addr:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="source.storage.address is required")

            src_rel = _norm_rel(request.source.rel_path)
            if not src_rel:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="source.rel_path is required")

            # validate output
            if not request.output or not request.output.storage:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="output.storage is required")
            out_addr = (request.output.storage.address or "").strip()
            if not out_addr:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="output.storage.address is required")

            out_base = _norm_rel(request.output.base_rel_dir)
            if not out_base:
                # fallback: derive "{storage_rel}/captions" from source path dirname
                if "/" in src_rel:
                    base = src_rel.rsplit("/", 1)[0]
                else:
                    base = ""
                out_base = _join_rel(base, "captions")

            # Fixed artifact names (must match YurTube app expectations)
            vtt_rel = _join_rel(out_base, "captions.vtt")
            meta_rel = _join_rel(out_base, "captions.meta.json")

            job_id = uuid.uuid4().hex

            storage.create_job_v2(
                job_id=job_id,
                video_id=video_id,
                lang=lang,
                task=task,
                source={
                    "address": src_addr,
                    "tls": bool(request.source.storage.tls),
                    "token": (request.source.storage.token or ""),
                    "rel_path": src_rel,
                },
                output={
                    "address": out_addr,
                    "tls": bool(request.output.storage.tls),
                    "token": (request.output.storage.token or ""),
                    "base_rel_dir": out_base,
                },
                vtt_rel_path=vtt_rel,
                meta_rel_path=meta_rel,
                idempotency_key=idem,
            )

            logger.info(f"SubmitJob accepted job_id={job_id} video_id={video_id} src={src_rel} out={out_base} lang={lang} task={task}")
            return ytcms_pb2.JobAck(job_id=job_id, accepted=True, reused=False, message="queued")

        except Exception as e:
            logger.error(f"SubmitJob failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return ytcms_pb2.JobAck(accepted=False, reused=False, message=str(e))

    async def WatchJob(self, request: ytcms_pb2.WatchJobRequest, context) -> AsyncIterator[ytcms_pb2.JobEvent]:
        job_id = (request.job_id or "").strip()
        if not job_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("job_id is required")
            return

        # 1) initial snapshot
        if bool(request.send_initial):
            job_info = storage.get_job_info(job_id) or {}
            if job_info:
                yield ytcms_pb2.JobEvent(status=_job_snapshot(job_id, job_info))
            else:
                yield ytcms_pb2.JobEvent(
                    status=ytcms_pb2.JobStatus(
                        job_id=job_id,
                        state=ytcms_pb2.JobStatus.FAILED,
                        percent=0,
                        message="Job not found",
                        error=ytcms_pb2.JobError(code="not_found", message="Job not found"),
                    )
                )
                return

        # 2) stream updates from redis pubsub
        ps = storage.pubsub()
        ps.subscribe(settings.redis_pub_channel)

        last_emit_ts = 0.0
        try:
            while True:
                if context.cancelled():
                    return

                msg = ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not msg:
                    # keepalive: optionally re-emit state every N seconds if you want
                    continue

                try:
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", "ignore")
                    event = json.loads(data or "{}")
                except Exception:
                    continue

                if (event.get("job_id") or "") != job_id:
                    continue

                raw_status = event.get("status") or ""
                percent = _parse_int(event.get("percent"), -1)
                if percent < 0:
                    percent = 0
                if percent > 100:
                    percent = 100
                err = (event.get("error") or "").strip()

                st = ytcms_pb2.JobStatus(
                    job_id=job_id,
                    state=_map_status_to_state(raw_status),
                    percent=int(percent),
                    message=err if err else "",
                )
                if err:
                    st.error.CopyFrom(ytcms_pb2.JobError(code="error", message=err))

                yield ytcms_pb2.JobEvent(status=st)

                if st.state in (ytcms_pb2.JobStatus.DONE, ytcms_pb2.JobStatus.FAILED, ytcms_pb2.JobStatus.CANCELED):
                    return

        finally:
            try:
                ps.close()
            except Exception:
                pass

    async def GetResult(self, request: ytcms_pb2.GetResultRequest, context) -> ytcms_pb2.JobResult:
        job_id = (request.job_id or "").strip()
        if not job_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("job_id is required")
            return ytcms_pb2.JobResult()

        job_info = storage.get_job_info(job_id)
        if not job_info:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Job not found")
            return ytcms_pb2.JobResult(
                state=ytcms_pb2.JobStatus.FAILED,
                message="Job not found",
                error=ytcms_pb2.JobError(code="not_found", message="Job not found"),
            )

        state = _map_status_to_state(job_info.get("status") or "")
        err = (job_info.get("error") or "").strip()

        return ytcms_pb2.JobResult(
            state=state,
            message=err if err else "",
            error=ytcms_pb2.JobError(code="error", message=err) if err else None,  # optional field
            detected_lang=(job_info.get("detected_lang") or "").strip(),
            vtt_rel_path=_norm_rel(job_info.get("vtt_rel_path") or ""),
            meta_rel_path=_norm_rel(job_info.get("meta_rel_path") or ""),
            duration_sec=_parse_float(job_info.get("duration_sec"), 0.0),
            model=(job_info.get("model") or "").strip(),
            device=(job_info.get("device") or "").strip(),
            compute_type=(job_info.get("compute_type") or "").strip(),
            task=(job_info.get("task") or "").strip(),
        )