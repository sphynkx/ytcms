import json
import time
import redis
from typing import Any, Optional, Dict

from config import get_settings

settings = get_settings()


class Storage:
    def __init__(self):
        self.r = redis.from_url(settings.redis_url, decode_responses=True)

    def _job_key(self, job_id: str) -> str:
        return f"{settings.redis_job_prefix}{job_id}"

    def create_job_v2(
        self,
        *,
        job_id: str,
        video_id: str,
        lang: str,
        task: str,
        source: Dict[str, Any],
        output: Dict[str, Any],
        vtt_rel_path: str,
        meta_rel_path: str,
        idempotency_key: str = "",
    ) -> None:
        job_data = {
            "job_id": job_id,
            "video_id": video_id,
            "lang": lang,
            "task": task,
            "status": "QUEUED",
            "percent": -1,
            "created_at": time.time(),
            "error": "",
            "idempotency_key": idempotency_key or "",

            # source refs
            "src_address": source.get("address", ""),
            "src_tls": "1" if bool(source.get("tls")) else "0",
            "src_token": source.get("token", ""),
            "src_rel_path": source.get("rel_path", ""),

            # output refs
            "out_address": output.get("address", ""),
            "out_tls": "1" if bool(output.get("tls")) else "0",
            "out_token": output.get("token", ""),
            "out_base_rel_dir": output.get("base_rel_dir", ""),

            # resolved artifact paths (fixed names)
            "vtt_rel_path": vtt_rel_path,
            "meta_rel_path": meta_rel_path,

            # result meta
            "detected_lang": "",
            "duration_sec": "",
            "model": "",
            "device": "",
            "compute_type": "",
        }

        self.r.hset(self._job_key(job_id), mapping=job_data)
        self.r.rpush(settings.redis_queue_key, job_id)
        self.publish_status(job_id, video_id, "QUEUED", percent=-1)

    def get_job_info(self, job_id: str) -> dict:
        return self.r.hgetall(self._job_key(job_id))

    def update_status(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        percent: Optional[int] = None,
        error_msg: Optional[str] = None,
        result_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        key = self._job_key(job_id)

        update_data = {}
        if status is not None:
            update_data["status"] = status
        if percent is not None:
            update_data["percent"] = int(percent)
        if error_msg is not None:
            update_data["error"] = error_msg

        if result_meta:
            for k in ("detected_lang", "duration_sec", "model", "device", "compute_type"):
                if k in result_meta and result_meta[k] is not None:
                    update_data[k] = str(result_meta[k])

        if update_data:
            self.r.hset(key, mapping=update_data)

        if status is None:
            status = self.r.hget(key, "status")
        if percent is None:
            p_val = self.r.hget(key, "percent")
            percent = int(p_val) if p_val else -1
        video_id = self.r.hget(key, "video_id")
        self.publish_status(job_id, video_id, status, error=error_msg, percent=percent)

    def publish_status(self, job_id: str, video_id: str, status: str, error: str = None, percent: int = -1):
        message = {
            "job_id": job_id,
            "video_id": video_id,
            "status": status,
            "percent": percent,
            "timestamp": time.time(),
        }
        if error:
            message["error"] = error
        self.r.publish(settings.redis_pub_channel, json.dumps(message))

    def pop_task(self):
        try:
            item = self.r.blpop(settings.redis_queue_key, timeout=1)
            if item:
                return item[1]
        except redis.RedisError:
            return None
        return None

    def pubsub(self):
        return self.r.pubsub()


storage = Storage()