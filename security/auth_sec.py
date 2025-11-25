from typing import Optional
from config import get_settings

def validate_token(metadata: dict) -> bool:
    token_raw: Optional[str] = metadata.get("authorization")
    if not token_raw:
        return False
    if token_raw.lower().startswith("bearer "):
        provided = token_raw[7:].strip()
    else:
        provided = token_raw.strip()
    return provided == get_settings().token