import json
import logging
import time
import uuid
from typing import Any, Dict

import grpc

from config import get_settings
from jobs.storage import storage
from proto import ytcms_pb2, ytcms_pb2_grpc

from utils.ytstorage_client import remove as storage_remove

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


def _job_status_from_job(job_id: str, job_info: Dict[str, Any]) -> ytcms_pb2.JobStatus:
    raw_status = job_info.get("status") or ""
    percent = _parse_int(job_info.get("percent"), -1)
    if percent < 0:
        percent = 0
    if percent > 100:
        percent = 100

    err = (job_info.get("error") or "").strip()
    state = _map_status_to_state(raw_status)

    st = ytcms_pb2.JobStatus(
        job_id=job_id,
        state=state,
        percent=percent,
        message=err if err else "",
    )
    if err:
        st.error.CopyFrom(ytcms_pb2.JobError(code="error", message=err))
    return st


class CaptionsServiceImpl(ytcms_pb2_grpc.CaptionsServiceServicer):
    def __init__(self, queue):
        self.queue = queue

    def SubmitJob(self, request: ytcms_pb2.SubmitJobRequest, context) -> ytcms_pb2.JobAck:
        try:
            video_id = (request.video_id or "").strip()
            if not video_id:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="video_id is required")

            lang = (request.lang or "auto").strip() or "auto"
            task = (request.task or "transcribe").strip() or "transcribe"
            idem = (request.idempotency_key or "").strip()

            if not request.source or not request.source.storage:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="source.storage is required")
            src_addr = (request.source.storage.address or "").strip()
            if not src_addr:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="source.storage.address is required")

            src_rel = _norm_rel(request.source.rel_path)
            if not src_rel:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="source.rel_path is required")

            if not request.output or not request.output.storage:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="output.storage is required")
            out_addr = (request.output.storage.address or "").strip()
            if not out_addr:
                return ytcms_pb2.JobAck(accepted=False, reused=False, message="output.storage.address is required")

            out_base = _norm_rel(request.output.base_rel_dir)
            if not out_base:
                base = src_rel.rsplit("/", 1)[0] if "/" in src_rel else ""
                out_base = _join_rel(base, "captions")

            # Fixed artifact names expected by YurTube app
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

            logger.info(
                f"SubmitJob accepted job_id={job_id} video_id={video_id} "
                f"src={src_rel} out={out_base} lang={lang} task={task}"
            )
            return ytcms_pb2.JobAck(job_id=job_id, accepted=True, reused=False, message="queued")

        except Exception as e:
            logger.error(f"SubmitJob failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return ytcms_pb2.JobAck(accepted=False, reused=False, message=str(e))

    def GetStatus(self, request: ytcms_pb2.GetStatusRequest, context) -> ytcms_pb2.GetStatusReply:
        job_id = (request.job_id or "").strip()
        if not job_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "job_id is required")

        job_info = storage.get_job_info(job_id)
        if not job_info:
            st = ytcms_pb2.JobStatus(
                job_id=job_id,
                state=ytcms_pb2.JobStatus.FAILED,
                percent=0,
                message="Job not found",
            )
            st.error.CopyFrom(ytcms_pb2.JobError(code="not_found", message="Job not found"))
            return ytcms_pb2.GetStatusReply(status=st)

        return ytcms_pb2.GetStatusReply(status=_job_status_from_job(job_id, job_info))

    def GetResult(self, request: ytcms_pb2.GetResultRequest, context) -> ytcms_pb2.JobResult:
        job_id = (request.job_id or "").strip()
        if not job_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "job_id is required")

        job_info = storage.get_job_info(job_id)
        if not job_info:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Job not found")
            res = ytcms_pb2.JobResult(state=ytcms_pb2.JobStatus.FAILED, message="Job not found")
            res.error.CopyFrom(ytcms_pb2.JobError(code="not_found", message="Job not found"))
            return res

        state = _map_status_to_state(job_info.get("status") or "")
        err = (job_info.get("error") or "").strip()

        res = ytcms_pb2.JobResult(
            state=state,
            message=err if err else "",
            detected_lang=(job_info.get("detected_lang") or "").strip(),
            vtt_rel_path=_norm_rel(job_info.get("vtt_rel_path") or ""),
            meta_rel_path=_norm_rel(job_info.get("meta_rel_path") or ""),
            duration_sec=_parse_float(job_info.get("duration_sec"), 0.0),
            model=(job_info.get("model") or "").strip(),
            device=(job_info.get("device") or "").strip(),
            compute_type=(job_info.get("compute_type") or "").strip(),
            task=(job_info.get("task") or "").strip(),
        )
        if err:
            res.error.CopyFrom(ytcms_pb2.JobError(code="error", message=err))
        return res

    def DeleteCaptions(self, request: ytcms_pb2.DeleteCaptionsRequest, context) -> ytcms_pb2.DeleteCaptionsReply:
        """
        Variant A: delete {storage_rel}/captions recursively in ytstorage.
        """
        try:
            if not request.storage or not (request.storage.address or "").strip():
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "storage.address is required")

            storage_rel = _norm_rel(request.storage_rel)
            if not storage_rel:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "storage_rel is required")

            captions_dir = _join_rel(storage_rel, "captions")

            storage_remove(
                address=request.storage.address,
                tls=bool(request.storage.tls),
                token=(request.storage.token or ""),
                rel_path=captions_dir,
                recursive=True,
            )

            logger.info(f"DeleteCaptions ok storage_rel={storage_rel}")
            return ytcms_pb2.DeleteCaptionsReply(ok=True, message="deleted")

        except grpc.RpcError:
            raise
        except Exception as e:
            logger.error(f"DeleteCaptions failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return ytcms_pb2.DeleteCaptionsReply(ok=False, message=str(e))