import json
import time
import redis
from config import get_settings

settings = get_settings()

class Storage:
    def __init__(self):
        # decode_responses=True ensures we get strings, not bytes
        self.r = redis.from_url(settings.redis_url, decode_responses=True)

    def _job_key(self, job_id: str) -> str:
        return f"{settings.redis_job_prefix}{job_id}"

    def create_job(self, job_id: str, video_id: str, file_path: str, lang: str, task: str):
        """
        Creates a job record in Redis Hash and pushes the job_id to the processing list.
        """
        job_data = {
            "job_id": job_id,
            "video_id": video_id,
            "file_path": file_path,
            "lang": lang,
            "task": task,
            "status": "QUEUED",
            "created_at": time.time(),
            "result": "",
            "error": ""
        }
        
        # 1. Save job info to Hash
        self.r.hset(self._job_key(job_id), mapping=job_data)
        
        # 2. Push to Queue
        self.r.rpush(settings.redis_queue_key, job_id)
        
        # 3. Publish initial status
        self.publish_status(job_id, video_id, "QUEUED")

    def get_job_info(self, job_id: str) -> dict:
        """
        Returns all fields for the job from Redis.
        Returns empty dict if not found.
        """
        return self.r.hgetall(self._job_key(job_id))

    def update_status(self, job_id: str, status: str, result_text: str = None, error_msg: str = None):
        """
        Updates status in Redis and publishes a notification.
        """
        key = self._job_key(job_id)
        
        update_data = {"status": status}
        if result_text is not None:
            update_data["result"] = result_text
        if error_msg is not None:
            update_data["error"] = error_msg
            
        self.r.hset(key, mapping=update_data)
        
        # Retrieve video_id for the notification payload
        video_id = self.r.hget(key, "video_id")
        self.publish_status(job_id, video_id, status, error_msg)

    def publish_status(self, job_id: str, video_id: str, status: str, error: str = None):
        """
        Publishes a JSON message to the notifications channel.
        """
        message = {
            "job_id": job_id,
            "video_id": video_id,
            "status": status,
            "timestamp": time.time()
        }
        if error:
            message["error"] = error
            
        self.r.publish(settings.redis_pub_channel, json.dumps(message))

    def pop_task(self):
        """
        Blocking pop from the queue. Returns job_id or None.
        """
        try:
            # blpop returns (queue_name, value)
            item = self.r.blpop(settings.redis_queue_key, timeout=1)
            if item:
                return item[1] 
        except redis.RedisError:
            return None
        return None

# Global instance
storage = Storage()