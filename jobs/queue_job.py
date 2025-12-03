import os
import time
import logging
import threading
import asyncio
from datetime import timedelta

from config import get_settings
from jobs.storage import storage
from provider.faster_whisper_prv import get_provider

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level), format='%(asctime)s [ytcms-worker] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("worker")

class JobQueue:
    def __init__(self):
        self.workers = []
        self.running = False
        
    async def init(self):
        # Init provider once on start
        logger.info("Initializing Provider (loading model into shared memory)...")
        get_provider(settings.model, settings.device, settings.compute_type)
        logger.info("Provider initialized.")

    async def start_workers(self):
        await self.init()

        self.running = True
        for i in range(settings.worker_concurrency):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()
            self.workers.append(t)
        logger.info(f"Started {len(self.workers)} worker threads.")

    async def stop(self):
        logger.info("Stopping workers...")
        self.running = False

    async def close(self):
        for t in self.workers:
            if t.is_alive():
                t.join(timeout=1.0)
        logger.info("Workers stopped.")

    def _worker_loop(self, worker_id):
        logger.info(f"Worker-{worker_id} started.")
        
        provider = get_provider(settings.model, settings.device, settings.compute_type)
        
        while self.running:
            try:
                job_id = storage.pop_task()
                if not job_id:
                    continue

                asyncio.run(self._process_job(job_id, provider))

            except Exception as e:
                logger.error(f"Worker-{worker_id} loop error: {e}")
                time.sleep(1)

    async def _process_job(self, job_id, provider):
        job_info = storage.get_job_info(job_id)
        if not job_info:
            logger.error(f"Job {job_id} popped but not found in storage.")
            return

        video_id = job_info.get("video_id")
        file_path = job_info.get("file_path")
        lang_req = job_info.get("lang")
        task = job_info.get("task")

        logger.info(f"Processing job_id={job_id} video_id={video_id} task={task} lang={lang_req}")
        
        # Set status PROCESSING, 0%
        storage.update_status(job_id, status="PROCESSING", percent=0)

        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Audio file not found: {file_path}")

            start_time = time.time()
            
            # Callback for percentage update in Redis
            def progress_callback(p_float: float):
                pct = int(p_float * 100)
                if pct > 100: pct = 100
                
                # Update Redis
                storage.update_status(job_id, status=None, percent=pct)

            # Call provider
            # provider.transcribe returns (segs, meta)
            segs, meta = await provider.transcribe(
                video_path=file_path,
                lang=lang_req,
                task=task,
                progress_cb=progress_callback
            )
            
            # Convert result to VTT string
            vtt_lines = ["WEBVTT\n"]
            for s in segs:
                start_s = self._format_timestamp(float(s["start"]))
                end_s = self._format_timestamp(float(s["end"]))
                text = s["text"].strip()
                vtt_lines.append(f"{start_s} --> {end_s}\n{text}\n")
            
            result_vtt = "\n".join(vtt_lines)
            duration = time.time() - start_time
            
            logger.info(f"Done job_id={job_id}. Time: {duration:.2f}s")
            
            # DONE, 100%
            storage.update_status(job_id, status="DONE", percent=100, result_text=result_vtt)

        except Exception as e:
            logger.error(f"Failed job_id={job_id}: {e}")
            storage.update_status(job_id, status="ERROR", error_msg=str(e))
        
        finally:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass

    def _format_timestamp(self, seconds: float):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:06.3f}"