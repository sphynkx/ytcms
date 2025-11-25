import asyncio
from typing import Any, Dict, List, Tuple, Optional, Callable
from faster_whisper import WhisperModel
from config import get_settings

# Supported compute types (keep minimal and safe)
_SUPPORTED = {"int8", "float32"}


def _sanitize_compute_type(ct: str) -> str:
    return ct if ct in _SUPPORTED else "int8"


def _safe_progress(cb: Callable[[float], None], value: float) -> None:
    # Never raise from progress callback
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

        # Create model with provided settings
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

        # Minimal, safe debug info without touching private attributes
        try:
            size_label = getattr(self._model, "model_size", "unknown")
        except Exception:
            size_label = "unknown"
        print(f"[ytcms] Model loaded name={model_name} size_label={size_label} device={device} compute_type={compute_type}")

    async def transcribe(
        self,
        video_path: str,
        lang: str,
        task: str,
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Performs transcription with parameters from Settings.
        Progress convention: 0.05 at start -> up to 0.90 while iterating segments ->
        0.95 for post-processing -> 1.0 is set by queue worker on completion.
        """
        settings = get_settings()

        if task not in ("transcribe", "translate"):
            task = "transcribe"

        def _run():
            if progress_cb:
                _safe_progress(progress_cb, 0.05)

            segments_iter, info = self._model.transcribe(
                video_path,
                language=None if lang == "auto" else lang,
                task=task,
                beam_size=settings.beam_size,
                vad_filter=settings.vad_filter,
                temperature=settings.temperature,
                compression_ratio_threshold=settings.compression_ratio_threshold,
                log_prob_threshold=settings.log_prob_threshold,
                no_speech_threshold=settings.no_speech_threshold,
                patience=settings.patience,
            )

            duration = float(info.duration or 0.0)
            segs: List[Dict[str, Any]] = []
            assumed_max_segs = float(settings.progress_assumed_max_segs)

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
                        # Fallback progress when duration is unknown
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
                # Echo actual decoding params for auditing
                "beam_size": settings.beam_size,
                "vad_filter": settings.vad_filter,
                "temperature": settings.temperature,
                "compression_ratio_threshold": settings.compression_ratio_threshold,
                "log_prob_threshold": settings.log_prob_threshold,
                "no_speech_threshold": settings.no_speech_threshold,
                "patience": settings.patience,
            }
            return segs, meta

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)


_provider_singleton: FasterWhisperProvider | None = None


def get_provider(model: str, device: str, compute_type: str) -> FasterWhisperProvider:
    # Simple singleton provider
    global _provider_singleton
    if _provider_singleton is None:
        _provider_singleton = FasterWhisperProvider(model, device, compute_type)
    return _provider_singleton