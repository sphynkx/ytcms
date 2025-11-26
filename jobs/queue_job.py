import asyncio
import uuid
import os
from typing import Dict, Optional, List
from redis.asyncio import Redis
from jobs.models_job import Job
from config import get_settings
from provider.faster_whisper_prv import get_provider
from utils.vtt_ut import segments_to_vtt

JOB_HASH_PREFIX = "ytcms:job:"
JOB_QUEUE_KEY = "ytcms:jobs"
SHUTDOWN_SENTINEL = b"_shutdown_sentinel"

def _fmt_pct(x: float) -> str:
    try:
        return f"{x*100:.1f}%"
    except Exception:
        return "?"

class JobQueue:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._redis: Redis | None = None
        self._workers: List[asyncio.Task] = []
        self._stop_event = asyncio.Event()

    async def init(self):
        settings = get_settings()
        self._redis = Redis.from_url(settings.redis_url, decode_responses=False)
        os.makedirs(settings.temp_dir, exist_ok=True)

    async def close(self):
        if self._redis:
            await self._redis.close()

    async def create_or_append(
        self,
        video_id: str,
        lang: str,
        task: str,
        chunk: bytes,
        last: bool
    ) -> Optional[str]:
        async with self._lock:
            job = next((j for j in self._jobs.values()
                        if j.video_id == video_id and j.status == "queued" and not j.finished_upload), None)
            if job is None:
                job_id = uuid.uuid4().hex
                file_path = os.path.join(get_settings().temp_dir, f"{job_id}.bin")
                job = Job(job_id=job_id, video_id=video_id, lang=lang, task=task, file_path=file_path)
                self._jobs[job_id] = job
                await self._redis.hset(JOB_HASH_PREFIX + job_id, mapping={
                    b"video_id": video_id.encode(),
                    b"lang": lang.encode(),
                    b"task": task.encode(),
                    b"status": b"queued",
                    b"progress": b"0",
                    b"file_path": file_path.encode(),
                })
                print(f"[ytcms] Submit received job_id={job_id} video_id={video_id} lang={lang} task={task}")

            with open(job.file_path, "ab") as f:
                f.write(chunk)

            if last:
                job.finished_upload = True
                await self._redis.hset(JOB_HASH_PREFIX + job.job_id, mapping={b"finished_upload": b"1"})
                await self._redis.lpush(JOB_QUEUE_KEY, job.job_id.encode())
                try:
                    size_mb = os.path.getsize(job.file_path) / (1024*1024)
                except Exception:
                    size_mb = -1
                print(f"[ytcms] Upload completed job_id={job.job_id} file={job.file_path} size={size_mb:.1f}MB")
                return job.job_id
            return None

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    async def _update_progress(self, job_id: str, p: float):
        job = self._jobs.get(job_id)
        if not job or self._stop_event.is_set():
            return
        job.progress = p
        try:
            await self._redis.hset(JOB_HASH_PREFIX + job_id, mapping={b"progress": str(p).encode()})
        except Exception:
            pass  # Redis may be already closed
        print(f"[ytcms] Progress job_id={job_id} p={_fmt_pct(p)}")

    async def worker_loop(self, worker_id: int) -> None:
        settings = get_settings()
        provider = get_provider(settings.model, settings.device, settings.compute_type)
        print(f"[ytcms] Worker started id={worker_id}")

        while not self._stop_event.is_set():
            try:
                result = await self._redis.brpop(JOB_QUEUE_KEY, timeout=2)
            except Exception:
                if self._stop_event.is_set():
                    break
                continue

            if result is None:
                continue

            _, raw_job_id = result
            if raw_job_id == SHUTDOWN_SENTINEL:
                if self._stop_event.is_set():
                    break
                else:
                    continue

            job_id = raw_job_id.decode()
            job = self._jobs.get(job_id)
            if not job:
                continue

            job.status = "processing"
            job.progress = 0.05
            try:
                await self._redis.hset(JOB_HASH_PREFIX + job_id, mapping={
                    b"status": b"processing",
                    b"progress": b"0.05",
                })
            except Exception:
                pass

            print(f"[ytcms] Processing job_id={job_id} video_id={job.video_id} file={job.file_path} lang={job.lang} task={job.task}")

            loop = asyncio.get_running_loop()

            def progress_cb(p: float):
                if self._stop_event.is_set():
                    return
                if loop.is_closed():
                    return
                loop.call_soon_threadsafe(
                    asyncio.create_task,
                    self._update_progress(job_id, max(0.05, min(p, 0.9)))
                )

            try:
                segments, meta = await provider.transcribe(
                    job.file_path, job.lang, job.task, progress_cb=progress_cb
                )

                # Pre-final step
                await self._update_progress(job_id, 0.95)

                # Normalize language
                ld = meta.get("lang_detected")
                req = job.lang
                if req and req not in ("auto", "mixed"):
                    meta["lang_detected"] = req
                elif ld not in {"en", "ru", "de", "fr", "es", "it", "uk"}:
                    meta["lang_detected"] = "en"

                job.segments = segments
                job.meta = meta
                job.vtt = segments_to_vtt(segments)
                job.status = "done"
                job.progress = 1.0
                try:
                    await self._redis.hset(JOB_HASH_PREFIX + job_id, mapping={
                        b"status": b"done",
                        b"progress": b"1.0",
                        b"lang_detected": meta.get("lang_detected", "unknown").encode(),
                    })
                except Exception:
                    pass

                print(f"[ytcms] Done job_id={job_id} segs={len(segments)} lang={meta.get('lang_detected')} duration={meta.get('duration_sec')}")
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.progress = 1.0
                try:
                    await self._redis.hset(JOB_HASH_PREFIX + job_id, mapping={
                        b"status": b"error",
                        b"progress": b"1.0",
                        b"error": str(e).encode(),
                    })
                except Exception:
                    pass
                print(f"[ytcms] Error job_id={job_id} err={e}")

    async def start_workers(self) -> None:
        for i in range(get_settings().worker_concurrency):
            t = asyncio.create_task(self.worker_loop(i))
            self._workers.append(t)

    async def stop(self):
        self._stop_event.set()
        try:
            await self._redis.lpush(JOB_QUEUE_KEY, SHUTDOWN_SENTINEL)
        except Exception:
            pass
        for t in self._workers:
            try:
                await asyncio.wait_for(t, timeout=5)
            except Exception:
                t.cancel()
        self._workers.clear()