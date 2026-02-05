import os
import time
import logging
import threading
import asyncio
import tempfile
import subprocess

from config import get_settings
from jobs.storage import storage
from provider.faster_whisper_prv import get_provider

from utils.ytstorage_client import download_to_file, mkdirs, upload_bytes

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level), format='%(asctime)s [ytcms-worker] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("worker")


def _parse_bool01(v: str) -> bool:
    return str(v or "").strip() in ("1", "true", "True", "yes", "on")


def _norm_rel(p: str) -> str:
    return (p or "").replace("\\", "/").strip().lstrip("/")


def _ffmpeg_extract_audio(src_video_abs: str, dst_wav_abs: str) -> None:
    """
    Extract mono 16kHz wav for whisper.
    You can later tune via SubmitJobRequest.options.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", src_video_abs,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        dst_wav_abs,
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({p.returncode}): {p.stderr.decode('utf-8', 'ignore')[:2000]}")


class JobQueue:
    def __init__(self):
        self.workers = []
        self.running = False

    async def init(self):
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
        lang_req = job_info.get("lang") or "auto"
        task = job_info.get("task") or "transcribe"

        src_address = job_info.get("src_address") or ""
        src_tls = _parse_bool01(job_info.get("src_tls"))
        src_token = job_info.get("src_token") or ""
        src_rel_path = _norm_rel(job_info.get("src_rel_path") or "")

        out_address = job_info.get("out_address") or ""
        out_tls = _parse_bool01(job_info.get("out_tls"))
        out_token = job_info.get("out_token") or ""
        out_base_rel_dir = _norm_rel(job_info.get("out_base_rel_dir") or "")

        vtt_rel_path = _norm_rel(job_info.get("vtt_rel_path") or "")
        meta_rel_path = _norm_rel(job_info.get("meta_rel_path") or "")

        logger.info(f"Processing job_id={job_id} video_id={video_id} task={task} lang={lang_req} src={src_rel_path}")

        storage.update_status(job_id, status="PROCESSING", percent=0)

        tmpdir = tempfile.mkdtemp(prefix="ytcms_")
        src_video_abs = os.path.join(tmpdir, "source.video")
        audio_abs = os.path.join(tmpdir, "audio.wav")

        try:
            # 1) download
            download_to_file(
                address=src_address,
                tls=src_tls,
                token=src_token,
                rel_path=src_rel_path,
                dst_abs=src_video_abs,
            )

            # 2) extract audio
            _ffmpeg_extract_audio(src_video_abs, audio_abs)

            start_time = time.time()

            def progress_callback(p_float: float):
                pct = int(p_float * 100)
                if pct > 100:
                    pct = 100
                storage.update_status(job_id, percent=pct)

            segs, meta = await provider.transcribe(
                video_path=audio_abs,
                lang=lang_req,
                task=task,
                progress_cb=progress_callback,
            )

            # 3) build VTT
            vtt_lines = ["WEBVTT\n"]
            for s in segs:
                start_s = self._format_timestamp(float(s["start"]))
                end_s = self._format_timestamp(float(s["end"]))
                text = (s.get("text") or "").strip()
                vtt_lines.append(f"{start_s} --> {end_s}\n{text}\n")
            vtt_payload = "\n".join(vtt_lines)
            if not vtt_payload.endswith("\n"):
                vtt_payload += "\n"

            duration = time.time() - start_time

            # 4) write artifacts to ytstorage (fixed paths)
            mkdirs(address=out_address, tls=out_tls, token=out_token, rel_dir=out_base_rel_dir, exist_ok=True)
            upload_bytes(address=out_address, tls=out_tls, token=out_token, rel_path=vtt_rel_path, payload=vtt_payload.encode("utf-8"), overwrite=True)

            meta_obj = {
                "video_id": video_id,
                "lang": (meta.get("lang") if isinstance(meta, dict) else None) or lang_req,
                "model": meta.get("model") if isinstance(meta, dict) else settings.model,
                "device": meta.get("device") if isinstance(meta, dict) else settings.device,
                "compute_type": meta.get("compute_type") if isinstance(meta, dict) else settings.compute_type,
                "duration_sec": float(meta.get("duration_sec")) if isinstance(meta, dict) and meta.get("duration_sec") else None,
                "task": task,
                "source": "ytcms",
                "job_id": job_id,
            }
            upload_bytes(address=out_address, tls=out_tls, token=out_token, rel_path=meta_rel_path, payload=(__import__("json").dumps(meta_obj)).encode("utf-8"), overwrite=True)

            storage.update_status(
                job_id,
                status="DONE",
                percent=100,
                result_meta={
                    "detected_lang": meta_obj["lang"],
                    "duration_sec": meta_obj.get("duration_sec") or "",
                    "model": meta_obj.get("model") or "",
                    "device": meta_obj.get("device") or "",
                    "compute_type": meta_obj.get("compute_type") or "",
                },
            )

            logger.info(f"Done job_id={job_id} time={duration:.2f}s vtt={vtt_rel_path}")

        except Exception as e:
            logger.error(f"Failed job_id={job_id}: {e}")
            storage.update_status(job_id, status="ERROR", error_msg=str(e))
        finally:
            try:
                for fn in (audio_abs, src_video_abs):
                    if os.path.exists(fn):
                        os.remove(fn)
            except Exception:
                pass
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    def _format_timestamp(self, seconds: float):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:06.3f}"