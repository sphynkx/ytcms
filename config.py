import os
from functools import lru_cache

class Settings:
    def __init__(self) -> None:
        self.model = os.getenv("YTCMS_MODEL", "tiny").strip()
        self.device = os.getenv("YTCMS_DEVICE", "cpu").strip()
        self.compute_type = os.getenv("YTCMS_COMPUTE_TYPE", "int8").strip()
        self.token = os.getenv("YTCMS_TOKEN", "CHANGE_ME").strip()
        self.redis_url = os.getenv("YTCMS_REDIS_URL", "redis://localhost:6379/0").strip()
        self.max_in_memory_video_bytes = int(os.getenv("YTCMS_MAX_VIDEO_BYTES", "524288000"))  # 500MB
        self.worker_concurrency = int(os.getenv("YTCMS_WORKER_CONCURRENCY", "1"))
        self.status_push_interval = float(os.getenv("YTCMS_STATUS_PUSH_INTERVAL", "1.0"))
        self.temp_dir = os.getenv("YTCMS_TEMP_DIR", "/tmp/ytcms")
        self.log_level = os.getenv("YTCMS_LOG_LEVEL", "INFO").upper()

@lru_cache()
def get_settings() -> Settings:
    return Settings()