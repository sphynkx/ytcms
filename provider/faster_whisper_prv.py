import asyncio
from typing import Any, Dict, List, Tuple, Optional, Callable
from faster_whisper import WhisperModel

# For very ancient CPUz.. May expand with int8_float16 ..
_SUPPORTED = {"int8", "float32"}


def _sanitize_compute_type(ct: str) -> str:
    return ct if ct in _SUPPORTED else "int8"


def _safe_progress(cb: Callable[[float], None], value: float) -> None:
    try:
        cb(value)
    except Exception:
        pass


class FasterWhisperProvider:
    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        compute_type = _sanitize_compute_type(compute_type)
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

    async def transcribe(
        self,
        video_path: str,
        lang: str,
        task: str,
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Performs transcription. Updates progress at each segment.
        progress: 0.05 start -> up to 0.90 during segments -> 0.95 postprocess -> 1.0 completion (in queue_job).
        """
        if task not in ("transcribe", "translate"):
            task = "transcribe"

        def _run():
            if progress_cb:
                _safe_progress(progress_cb, 0.05)

            segments_iter, info = self._model.transcribe(
                video_path,
                language=None if lang == "auto" else lang,
                task=task,
                beam_size=1,
                vad_filter=True,
            )

            duration = float(info.duration or 0.0)
            segs: List[Dict[str, Any]] = []

            # If duration unknown (0), make a rough linear estimate of up to ~20 segments.
            assumed_max_segs = 20.0

            for seg in segments_iter:
                segs.append({
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": seg.text.strip()
                })

                if progress_cb:
                    if duration > 0:
                        frac = min(max(float(seg.end) / duration, 0.0), 1.0)
                        p = 0.05 + 0.85 * frac
                    else:
                        # trying to fix bad progress on sample_client.. but unsuccessful
                        p = 0.05 + 0.85 * (len(segs) / assumed_max_segs)

                    p = min(p, 0.9)
                    _safe_progress(progress_cb, p)

            if progress_cb:
                _safe_progress(progress_cb, 0.9)

            meta = {
                "model": self.model_name,
                "device": self.device,
                "compute_type": self.compute_type,
                "segments": len(segs),
                "duration_sec": duration,
                "lang_requested": lang,
                "lang_detected": info.language,
                "task": task,
            }
            return segs, meta

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)


_provider_singleton: FasterWhisperProvider | None = None


def get_provider(model: str, device: str, compute_type: str) -> FasterWhisperProvider:
    global _provider_singleton
    if _provider_singleton is None:
        _provider_singleton = FasterWhisperProvider(model, device, compute_type)
    return _provider_singleton