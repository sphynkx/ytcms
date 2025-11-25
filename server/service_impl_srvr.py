import grpc
from jobs.queue_job import JobQueue
from config import get_settings
import captions_pb2, captions_pb2_grpc

class CaptionsServiceImpl(captions_pb2_grpc.CaptionsServiceServicer):
    def __init__(self, queue: JobQueue) -> None:
        self.queue = queue

    async def Submit(self, request_iterator, context):
        request_id_first = None
        job_id_final = None
        async for chunk in request_iterator:
            if request_id_first is None:
                request_id_first = chunk.request_id
            job_id = await self.queue.create_or_append(
                video_id=chunk.video_id,
                lang=chunk.lang or "auto",
                task=chunk.task or "transcribe",
                chunk=chunk.data,
                last=chunk.last
            )
            if job_id:
                job_id_final = job_id
        if not job_id_final:
            return captions_pb2.SubmitReply(
                request_id=request_id_first or "",
                job_id="",
                status="error",
                error="No last chunk received"
            )
        return captions_pb2.SubmitReply(
            request_id=request_id_first or "",
            job_id=job_id_final,
            status="queued"
        )

    async def GetStatus(self, request, context):
        job = self.queue.get(request.job_id)
        if not job:
            context.abort(grpc.StatusCode.NOT_FOUND, "Job not found")
        return captions_pb2.JobStatusReply(
            job_id=job.job_id,
            status=job.status,
            progress=job.progress,
            task=job.task,
            error=job.error or ""
        )

    async def StreamStatus(self, request, context):
        settings = get_settings()
        job = self.queue.get(request.job_id)
        if not job:
            context.abort(grpc.StatusCode.NOT_FOUND, "Job not found")
        while True:
            yield captions_pb2.JobStatusReply(
                job_id=job.job_id,
                status=job.status,
                progress=job.progress,
                task=job.task,
                error=job.error or ""
            )
            if job.status in ("done", "error"):
                break
            await grpc.aio.sleep(settings.status_push_interval)

    async def GetResult(self, request, context):
        job = self.queue.get(request.job_id)
        if not job:
            context.abort(grpc.StatusCode.NOT_FOUND, "Job not found")
        if job.status != "done":
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"Job not ready ({job.status})")
        reply = captions_pb2.ResultReply(
            job_id=job.job_id,
            detected_lang=job.meta.get("lang_detected", "unknown"),
            vtt=job.vtt or "",
            model=job.meta.get("model", ""),
            device=job.meta.get("device", ""),
            compute_type=job.meta.get("compute_type", ""),
            duration_sec=job.meta.get("duration_sec", 0.0),
            task=job.task
        )
        for seg in job.segments:
            s = reply.segments.add()
            s.start = seg["start"]
            s.end = seg["end"]
            s.text = seg["text"]
        return reply