import logging
import os
import uuid
import grpc
import captions_pb2
import captions_pb2_grpc
from config import get_settings
from jobs.storage import storage

settings = get_settings()
logger = logging.getLogger("server")

class CaptionsServiceImpl(captions_pb2_grpc.CaptionsServiceServicer):
    def __init__(self, queue):
        # queue is passed from run.py, but we mainly use storage directly
        # We keep it to maintain signature compatibility if needed
        self.queue = queue

    async def Submit(self, request_iterator, context):
        """
        Receives file chunks, saves to disk, creates Redis job.
        Returns immediately (non-blocking).
        """
        job_id = uuid.uuid4().hex
        temp_path = os.path.join(settings.temp_dir, f"{job_id}.bin")
        
        video_id = "unknown"
        lang = "auto"
        task = "transcribe"

        try:
            # Ensure temp dir exists
            if not os.path.exists(settings.temp_dir):
                os.makedirs(settings.temp_dir)

            # Write stream to file
            with open(temp_path, "wb") as f:
                async for chunk in request_iterator:
                    f.write(chunk.data)
                    # Metadata from stream
                    video_id = chunk.video_id
                    lang = chunk.lang
                    task = chunk.task
            
            file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
            logger.info(f"Upload received job_id={job_id} video_id={video_id} size={file_size_mb:.2f}MB")

            # Create job in Redis
            storage.create_job(job_id, video_id, temp_path, lang, task)

            # Return QUEUED status immediately
            return captions_pb2.SubmitReply(job_id=job_id, status="QUEUED")

        except Exception as e:
            logger.error(f"Submit failed: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return captions_pb2.SubmitReply()

    async def GetStatus(self, request, context):
        """
        Polling method. Returns status from Redis.
        """
        job_info = storage.get_job_info(request.job_id)
        
        if not job_info:
            return captions_pb2.JobStatusReply(status="NOT_FOUND")
        
        return captions_pb2.JobStatusReply(
            job_id=request.job_id,
            status=job_info.get("status", "UNKNOWN"),
            error=job_info.get("error", "")
        )

    async def GetResult(self, request, context):
        """
        Returns VTT content if status is DONE.
        """
        job_info = storage.get_job_info(request.job_id)
        
        if not job_info:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Job not found")
            return captions_pb2.ResultReply()

        status = job_info.get("status")
        
        if status != "DONE":
            # Not ready yet
            return captions_pb2.ResultReply(
                job_id=request.job_id,
                content="",
                format="vtt" 
            )

        return captions_pb2.ResultReply(
            job_id=request.job_id,
            content=job_info.get("result", ""),
            format="vtt"
        )