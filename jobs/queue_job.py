import os
import time
import logging
import threading
import asyncio
from faster_whisper import WhisperModel
import fasttext

from config import get_settings
from jobs.storage import storage

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level), format='[ytcms-worker] %(message)s')
logger = logging.getLogger("worker")

class JobQueue:
    """
    Manages background workers that process jobs from Redis.
    Replaces the old in-memory queue logic with a Redis polling mechanism.
    """
    def __init__(self):
        self.workers = []
        self.running = False

    async def init(self):
        """
        Initialization if needed.
        Currently no-op as storage is initialized globally.
        """
        pass

    async def start_workers(self):
        """
        Starts the worker threads based on worker_concurrency.
        """
        self.running = True
        for i in range(settings.worker_concurrency):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()
            self.workers.append(t)
        logger.info(f"Started {len(self.workers)} worker threads.")

    async def stop(self):
        """
        Signals workers to stop.
        """
        logger.info("Stopping workers...")
        self.running = False

    async def close(self):
        """
        Waits for workers to join (graceful shutdown).
        """
        for t in self.workers:
            if t.is_alive():
                t.join(timeout=1.0)
        logger.info("Workers stopped.")

    def _worker_loop(self, worker_id):
        """
        The main loop running inside a thread.
        """
        logger.info(f"Worker-{worker_id} started.")
        
        # 1. Load Models (Once per thread)
        try:
            model, lid_model = self._load_models()
        except Exception as e:
            logger.critical(f"Worker-{worker_id} failed to load models: {e}")
            return

        # 2. Processing Loop
        while self.running:
            try:
                # Blocking wait for task
                job_id = storage.pop_task()
                if not job_id:
                    # If queue is empty or timeout, loop again
                    continue

                self._process_job(job_id, model, lid_model)

            except Exception as e:
                logger.error(f"Worker-{worker_id} loop error: {e}")
                time.sleep(1)

    def _load_models(self):
        logger.info(f"Loading Whisper model: {settings.model} ({settings.device})...")
        model = WhisperModel(
            settings.model,
            device=settings.device,
            compute_type=settings.compute_type,
            download_root=settings.temp_dir # Using temp dir or model path
        )
        
        lid_model = None
        if settings.lid_enabled:
            if os.path.exists(settings.lid_model_path):
                logger.info(f"Loading LID model: {settings.lid_model_path}")
                lid_model = fasttext.load_model(settings.lid_model_path)
            else:
                logger.warning(f"LID model not found at {settings.lid_model_path}")
        
        return model, lid_model

    def _process_job(self, job_id, model, lid_model):
        # 1. Fetch Info
        job_info = storage.get_job_info(job_id)
        if not job_info:
            logger.error(f"Job {job_id} popped but not found in storage.")
            return

        video_id = job_info.get("video_id")
        file_path = job_info.get("file_path")
        lang_req = job_info.get("lang")
        task = job_info.get("task")

        logger.info(f"Processing job_id={job_id} video_id={video_id} task={task} lang={lang_req}")
        storage.update_status(job_id, "PROCESSING")

        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Audio file not found: {file_path}")

            # 2. Transcribe
            start_time = time.time()
            
            # Handle auto language
            language_arg = None if lang_req == "auto" else lang_req

            # (Optional) LID Logic could go here if you want pre-check using lid_model
            # For now, relying on Whisper's auto-detect or explicit lang

            segments, info = model.transcribe(
                file_path,
                beam_size=settings.beam_size,
                vad_filter=settings.vad_filter,
                task=task,
                language=language_arg
            )

            # 3. Format VTT
            vtt_lines = ["WEBVTT\n"]
            for segment in segments:
                start = self._format_timestamp(segment.start)
                end = self._format_timestamp(segment.end)
                text = segment.text.strip()
                vtt_lines.append(f"{start} --> {end}\n{text}\n")
            
            result_vtt = "\n".join(vtt_lines)
            duration = time.time() - start_time
            
            logger.info(f"Done job_id={job_id}. Duration: {duration:.2f}s")
            storage.update_status(job_id, "DONE", result_text=result_vtt)

        except Exception as e:
            logger.error(f"Failed job_id={job_id}: {e}")
            storage.update_status(job_id, "ERROR", error_msg=str(e))
        
        finally:
            # Cleanup
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