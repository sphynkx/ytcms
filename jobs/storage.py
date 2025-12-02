import json
import time
import redis
from config import get_settings

settings = get_settings()

class Storage:
    def __init__(self):
        # decode_responses=True is important!!
        self.r = redis.from_url(settings.redis_url, decode_responses=True)

    def _job_key(self, job_id: str) -> str:
        return f"{settings.redis_job_prefix}{job_id}"

    def create_job(self, job_id: str, video_id: str, file_path: str, lang: str, task: str):
        """Create task record"""
        job_data = {
            "job_id": job_id,
            "video_id": video_id,
            "file_path": file_path,
            "lang": lang,
            "task": task,
            "status": "QUEUED",
            "percent": -1,
            "created_at": time.time(),
            "result": "",
            "error": ""
        }
        
        self.r.hset(self._job_key(job_id), mapping=job_data)
        self.r.rpush(settings.redis_queue_key, job_id)
        self.publish_status(job_id, video_id, "QUEUED", percent=-1)

    def get_job_info(self, job_id: str) -> dict:
        return self.r.hgetall(self._job_key(job_id))

    def update_status(self, job_id: str, status: str = None, percent: int = None, result_text: str = None, error_msg: str = None):
        key = self._job_key(job_id)
        
        update_data = {}
        if status is not None:
            update_data["status"] = status
        if percent is not None:
            update_data["percent"] = percent
        if result_text is not None:
            update_data["result"] = result_text
        if error_msg is not None:
            update_data["error"] = error_msg
            
        if update_data:
            self.r.hset(key, mapping=update_data)
        
        # Get real data for notif.
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
            "timestamp": time.time()
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

storage = Storage()