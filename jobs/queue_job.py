import os
import time
import logging
import threading
from datetime import timedelta
from faster_whisper import WhisperModel
import fasttext

from config import get_settings
from jobs.storage import storage

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level), format='%(asctime)s [ytcms-worker] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("worker")

class JobQueue:
    def __init__(self):
        self.workers = []
        self.running = False

    async def init(self):
        pass

    async def start_workers(self):
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
        try:
            model, lid_model = self._load_models()
        except Exception as e:
            logger.critical(f"Worker-{worker_id} failed to load models: {e}")
            return

        while self.running:
            try:
                job_id = storage.pop_task()
                if not job_id:
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
            download_root=settings.temp_dir 
        )
        
        lid_model = None
        if settings.lid_enabled:
            try:
                if os.path.exists(settings.lid_model_path):
                    logger.info(f"Loading LID model: {settings.lid_model_path}")
                    lid_model = fasttext.load_model(settings.lid_model_path)
                else:
                    logger.warning(f"LID model not found at {settings.lid_model_path}")
            except ImportError:
                logger.warning("fasttext module not installed, LID disabled")
        
        return model, lid_model

    def _process_job(self, job_id, model, lid_model):
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
            language_arg = None if lang_req == "auto" else lang_req

            segments_generator, info = model.transcribe(
                file_path,
                beam_size=settings.beam_size,
                vad_filter=settings.vad_filter,
                task=task,
                language=language_arg
            )

            total_duration = info.duration
            logger.info(f"Audio duration: {timedelta(seconds=int(total_duration))}. Language: {info.language}")

            vtt_lines = ["WEBVTT\n"]
            last_percent = 0
            
            for segment in segments_generator:
                start = self._format_timestamp(segment.start)
                end = self._format_timestamp(segment.end)
                text = segment.text.strip()
                vtt_lines.append(f"{start} --> {end}\n{text}\n")
                
                if total_duration > 0:
                    current_percent = int((segment.end / total_duration) * 100)
                    # Update Redis only if percentage grown
                    if current_percent > last_percent:
                        storage.update_status(job_id, status=None, percent=current_percent)
                        last_percent = current_percent
                        
                        if current_percent % 10 == 0:
                             logger.info(f"Job {job_id}: {current_percent}%")
            
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