import os
import time
import logging
import threading
from faster_whisper import WhisperModel
import fasttext

from config import get_settings
from jobs.storage import storage

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level), format='[ytcms-worker] %(message)s')
logger = logging.getLogger("worker")

class Worker:
    def __init__(self):
        self.model = None
        self.lid_model = None
        self.running = True

    def load_models(self):
        """ Load models (Whisper + LID)"""
        logger.info(f"Loading Whisper model: {settings.model} ({settings.device})...")
        self.model = WhisperModel(
            settings.model,
            device=settings.device,
            compute_type=settings.compute_type,
            download_root=settings.model_path
        )
        logger.info("Whisper model loaded.")

        if settings.lid_enabled:
            logger.info(f"Loading LID model: {settings.lid_model_path}...")
            if os.path.exists(settings.lid_model_path):
                self.lid_model = fasttext.load_model(settings.lid_model_path)
                logger.info("LID model loaded.")
            else:
                logger.warning(f"LID model not found at {settings.lid_model_path}, LID disabled.")

    def run(self):
        """
        Main worker cycle: get tasks from Redis and process
        """
        self.load_models()
        logger.info("Worker started and waiting for tasks...")

        while self.running:
            try:
                job_id = storage.pop_task()
                if not job_id:
                    continue

                self.process_job(job_id)

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(1)

    def process_job(self, job_id: str):
        # 1. Read task info
        job_info = storage.get_job_info(job_id)
        if not job_info:
            logger.error(f"Job {job_id} popped but not found in Hash.")
            return

        video_id = job_info.get("video_id")
        file_path = job_info.get("file_path")
        lang_req = job_info.get("lang")
        task = job_info.get("task")

        logger.info(f"Processing job_id={job_id} video_id={video_id} task={task} lang={lang_req}")

        # 2. Set PROCESSING status
        storage.update_status(job_id, "PROCESSING")

        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Audio file not found: {file_path}")

            # 3. run Whisper
            start_time = time.time()
            
            # If lang='auto', Whisper receives None for autodetect
            language_arg = None if lang_req == "auto" else lang_req

            segments, info = self.model.transcribe(
                file_path,
                beam_size=settings.beam_size,
                vad_filter=settings.vad_filter,
                task=task,
                language=language_arg
            )

            # 4. Form VTT
            vtt_lines = ["WEBVTT\n"]
            for segment in segments:
                start = self.format_timestamp(segment.start)
                end = self.format_timestamp(segment.end)
                text = segment.text.strip()
                vtt_lines.append(f"{start} --> {end}\n{text}\n")
            
            result_vtt = "\n".join(vtt_lines)
            duration = time.time() - start_time
            
            logger.info(f"Done job_id={job_id}. Duration: {duration:.2f}s")

            # 5. Set DONE status and save result into Redis
            storage.update_status(job_id, "DONE", result_text=result_vtt)

        except Exception as e:
            logger.error(f"Failed job_id={job_id}: {e}")
            storage.update_status(job_id, "ERROR", error_msg=str(e))
        
        finally:
            # Remove temp file
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass

    def format_timestamp(self, seconds: float):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:06.3f}"

def start_worker_thread():
    worker = Worker()
    worker.run()