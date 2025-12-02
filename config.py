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
        # Base model/device
        self.model = os.getenv("YTCMS_MODEL", "tiny").strip()
        self.device = os.getenv("YTCMS_DEVICE", "cpu").strip()
        self.compute_type = os.getenv("YTCMS_COMPUTE_TYPE", "int8").strip()

        # auth
        self.token = os.getenv("YTCMS_TOKEN", "CHANGE_ME").strip()

        # Redis
        self.redis_url = os.getenv("YTCMS_REDIS_URL", "redis://localhost:6379/0").strip()

        # limits/workers/statuses
        self.max_in_memory_video_bytes = int(os.getenv("YTCMS_MAX_VIDEO_BYTES", "524288000"))  # 500MB
        self.worker_concurrency = int(os.getenv("YTCMS_WORKER_CONCURRENCY", "1"))
        self.status_push_interval = float(os.getenv("YTCMS_STATUS_PUSH_INTERVAL", "1.0"))

        # temp directory
        self.temp_dir = os.getenv("YTCMS_TEMP_DIR", "/tmp/ytcms")

        # logging
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

        # Progress euristics when duration == 0
        self.progress_assumed_max_segs = int(os.getenv("YTCMS_PROGRESS_ASSUMED_MAX_SEGS", "20"))

        # Disable context carry-over if needed
        self.condition_on_previous_text = _parse_bool(os.getenv("YTCMS_CONDITION_ON_PREVIOUS_TEXT", "true"), True)

        # Decoder extras
        self.suppress_blank = _parse_bool(os.getenv("YTCMS_SUPPRESS_BLANK", "false"), False)
        self.initial_prompt = os.getenv("YTCMS_INITIAL_PROMPT", "").strip()

        # Mixed-language mode (chunk-based)
        # Chunk size in seconds for mixed mode
        self.mixed_chunk_sec = int(os.getenv("YTCMS_MIXED_CHUNK_SEC", "30"))
        # Overlap in seconds between chunks (helps reduce boundary artifacts)
        self.mixed_overlap_sec = int(os.getenv("YTCMS_MIXED_OVERLAP_SEC", "0"))
        # Retry isolated chunk language: if chunk language differs from both neighbors which agree, re-run chunk with neighbor language
        self.mixed_retry_isolated_lang = _parse_bool(os.getenv("YTCMS_MIXED_RETRY_ISOLATED_LANG", "true"), True)
        # Lookbehind (seconds of audio prepended to each chunk to avoid cutting beginnings of words)
        self.mixed_lookbehind_sec = float(os.getenv("YTCMS_MIXED_LOOKBEHIND_SEC", "1.0"))

        # Post-processing tuning (segment splitting / filtering)
        # Maximum duration (sec) of final segment before forced split
        self.max_segment_sec = float(os.getenv("YTCMS_MAX_SEGMENT_SEC", "10"))
        # Maximum characters per final segment
        self.max_segment_chars = int(os.getenv("YTCMS_MAX_SEGMENT_CHARS", "140"))
        # Maximum characters per sub-segment while splitting long segments using word timestamps
        self.subseg_max_chars = int(os.getenv("YTCMS_SUBSEG_MAX_CHARS", "70"))
        # Maximum duration (sec) of sub-segment (word-based slicing)
        self.subseg_max_sec = float(os.getenv("YTCMS_SUBSEG_MAX_SEC", "6"))
        # Max seconds from start to consider and remove disclaimer hallucinations
        self.disclaimer_max_sec = float(os.getenv("YTCMS_DISCLAIMER_MAX_SEC", "4"))
        # Filter noise segments (like '____', '---', mostly punctuation)
        self.filter_noise_segments = _parse_bool(os.getenv("YTCMS_FILTER_NOISE_SEGMENTS", "true"), True)

        # Language ID (fastText)
        self.lid_enabled = _parse_bool(os.getenv("YTCMS_LID_ENABLED", "false"), False)
        self.lid_model_path = os.getenv("YTCMS_LID_MODEL_PATH", "").strip()
        self.lid_confidence = float(os.getenv("YTCMS_LID_CONFIDENCE", "0.70"))
        self.lid_favor_neighbors = _parse_bool(os.getenv("YTCMS_LID_FAVOR_NEIGHBORS", "true"), True)

        # === NEW QUEUE SETTINGS ===
        self.redis_queue_key = os.getenv("YTCMS_REDIS_QUEUE_KEY", "ytcms:queue:tasks")
        self.redis_job_prefix = os.getenv("YTCMS_REDIS_JOB_PREFIX", "ytcms:job:")
        self.redis_pub_channel = os.getenv("YTCMS_REDIS_PUB_CHANNEL", "ytcms:notifications")


@lru_cache()
def get_settings() -> Settings:
    return Settings()