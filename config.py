import os
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

def _load_dotenv() -> None:
    project_root = Path(__file__).resolve().parent
    env_path = os.getenv("YTCMS_DOTENV_PATH", str(project_root / ".env"))
    load_dotenv(env_path, override=False)

_load_dotenv()


def _parse_bool(val: str, default: bool) -> bool:
    if val is None:
        return default
    v = val.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


class Settings:
    def __init__(self) -> None:
        self.model = os.getenv("YTCMS_MODEL", "tiny").strip()
        self.device = os.getenv("YTCMS_DEVICE", "cpu").strip()
        self.compute_type = os.getenv("YTCMS_COMPUTE_TYPE", "int8").strip()

        # auth
        self.token = os.getenv("YTCMS_TOKEN", "CHANGE_ME").strip()

        self.redis_url = os.getenv("YTCMS_REDIS_URL", "redis://localhost:6379/0").strip()

        # limits/workers/statuses
        self.max_in_memory_video_bytes = int(os.getenv("YTCMS_MAX_VIDEO_BYTES", "524288000"))  # 500MB
        self.worker_concurrency = int(os.getenv("YTCMS_WORKER_CONCURRENCY", "1"))
        self.status_push_interval = float(os.getenv("YTCMS_STATUS_PUSH_INTERVAL", "1.0"))

        self.temp_dir = os.getenv("YTCMS_TEMP_DIR", "/tmp/ytcms")

        self.log_level = os.getenv("YTCMS_LOG_LEVEL", "INFO").upper()

        # gRPC host/port (for run.sh)
        self.host = os.getenv("YTCMS_HOST", "0.0.0.0")
        self.port = int(os.getenv("YTCMS_PORT", "9099"))

        # Transcribe params
        self.beam_size = int(os.getenv("YTCMS_BEAM_SIZE", "5"))
        self.vad_filter = _parse_bool(os.getenv("YTCMS_VAD_FILTER", "false"), False)
        self.temperature = float(os.getenv("YTCMS_TEMPERATURE", "0.0"))
        self.compression_ratio_threshold = float(os.getenv("YTCMS_COMPRESSION_RATIO_THRESHOLD", "2.4"))
        self.log_prob_threshold = float(os.getenv("YTCMS_LOG_PROB_THRESHOLD", "-1.0"))
        self.no_speech_threshold = float(os.getenv("YTCMS_NO_SPEECH_THRESHOLD", "0.6"))
        self.patience = int(os.getenv("YTCMS_PATIENCE", "1"))

        # Preogress euristics when duration == 0
        self.progress_assumed_max_segs = int(os.getenv("YTCMS_PROGRESS_ASSUMED_MAX_SEGS", "20"))


@lru_cache()
def get_settings() -> Settings:
    return Settings()