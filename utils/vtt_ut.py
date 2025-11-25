from typing import List, Dict

def format_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round((t - int(t)) * 1000))
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def segments_to_vtt(segments: List[Dict[str, float]]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = format_ts(seg["start"])
        end = format_ts(seg["end"])
        text = (seg["text"] or "").replace("\r", "").strip() or "[...]"
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"