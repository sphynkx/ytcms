import logging
import os
import uuid
import grpc
from proto import captions_pb2
from proto import captions_pb2_grpc
from config import get_settings
from jobs.storage import storage

settings = get_settings()
logger = logging.getLogger("server")

class CaptionsServiceImpl(captions_pb2_grpc.CaptionsServiceServicer):
    def __init__(self, queue):
        self.queue = queue

    async def Submit(self, request_iterator, context):
        job_id = uuid.uuid4().hex
        temp_path = os.path.join(settings.temp_dir, f"{job_id}.bin")
        
        video_id = "unknown"
        lang = "auto"
        task = "transcribe"

        try:
            if not os.path.exists(settings.temp_dir):
                os.makedirs(settings.temp_dir)

            with open(temp_path, "wb") as f:
                async for chunk in request_iterator:
                    f.write(chunk.data)
                    video_id = chunk.video_id
                    lang = chunk.lang
                    task = chunk.task
            
            file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
            logger.info(f"Upload received job_id={job_id} video_id={video_id} size={file_size_mb:.2f}MB")

            storage.create_job(job_id, video_id, temp_path, lang, task)

            return captions_pb2.SubmitReply(
                job_id=job_id, 
                status="queued",
                percent=-1
            )

        except Exception as e:
            logger.error(f"Submit failed: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return captions_pb2.SubmitReply()

    async def GetStatus(self, request, context):
        job_info = storage.get_job_info(request.job_id)
        
        if not job_info:
            return captions_pb2.JobStatusReply(
                job_id=request.job_id,
                status="fail",
                error="Job not found",
                progress=0.0,
                percent=-1
            )
        
        raw_status = job_info.get("status", "UNKNOWN")
        
        # Map statuses to lowercase
        api_status = "wait"
        if raw_status == "QUEUED":
            api_status = "wait" # was "queued"
        elif raw_status == "PROCESSING":
            api_status = "processing"
        elif raw_status == "DONE":
            api_status = "done"
        elif raw_status == "ERROR":
            api_status = "error"
        
        # Get int percentage
        try:
            percent = int(job_info.get("percent", -1))
        except (ValueError, TypeError):
            percent = -1
        
        # Calc float progress (0.0 - 1.0)
        progress_float = 0.0
        if percent > 0:
            progress_float = float(percent) / 100.0
            
        task_str = job_info.get("task", "transcribe")

        return captions_pb2.JobStatusReply(
            job_id=request.job_id,
            status=api_status,
            progress=progress_float,
            task=task_str,
            error=job_info.get("error", ""),
            percent=percent
        )

    async def GetResult(self, request, context):
        job_info = storage.get_job_info(request.job_id)
        
        if not job_info:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Job not found")
            return captions_pb2.ResultReply()

        status = job_info.get("status")
        
        if status != "DONE":
            # Return empty vtt if not done
            return captions_pb2.ResultReply(job_id=request.job_id, vtt="")

        return captions_pb2.ResultReply(
            job_id=request.job_id,
            vtt=job_info.get("result", ""),
            task=job_info.get("task", "transcribe"),
            model=settings.model,
            device=settings.device,
            compute_type=settings.compute_type
        )