from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Job:
    job_id: str
    video_id: str
    lang: str
    task: str
    status: str = "queued"        # queued|processing|done|error
    progress: float = 0.0
    error: Optional[str] = None
    segments: List[Dict[str, float]] = field(default_factory=list)
    meta: Dict[str, float] = field(default_factory=dict)
    vtt: Optional[str] = None
    file_path: Optional[str] = None
    finished_upload: bool = False