"""
tts.py — Client for the local Voicebox TTS server.

Voicebox must be running at config.VOICEBOX_URL (default: http://localhost:8000).
Voice profiles are matched to characters by name (case-insensitive).

Public API:
    is_running()                                  -> bool
    list_profiles()                               -> list[dict]
    find_profile(name)                            -> dict | None
    generate(profile_id, text, dest_path, lang)   -> Path
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

import config


def list_profiles() -> list[dict] | None:
    """Return available voice profiles from GET /profiles.

    Returns:
        List of profile dicts, or None if the server is unreachable.
    """
    try:
        with urllib.request.urlopen(
            f"{config.VOICEBOX_URL}/profiles", timeout=5
        ) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError):
        return None


def is_running() -> bool:
    """Return True if the Voicebox server is reachable."""
    return list_profiles() is not None


def find_profile(name: str) -> dict | None:
    """Return the first Voicebox profile whose name matches (case-insensitive).

    Args:
        name: Character name to look up (e.g. "peter").

    Returns:
        The profile dict, or None if the server is unreachable or no match found.
    """
    for profile in (list_profiles() or []):
        if profile.get("name", "").lower() == name.lower():
            return profile
    return None


def generate(
    profile_id: str,
    text: str,
    dest_path: str | Path,
    language: str = "en",
) -> Path:
    """Generate speech via POST /generate/stream and write WAV bytes to dest_path.

    Uses the synchronous streaming endpoint so no polling is required.

    Args:
        profile_id: Voicebox voice profile UUID.
        text:       Text to synthesize.
        dest_path:  Destination file path (written as WAV).
        language:   BCP-47 language tag (default "en").

    Returns:
        Path to the written file.

    Raises:
        urllib.error.HTTPError: If the server returns a non-2xx status.
        urllib.error.URLError:  If the server is unreachable.
    """
    body = json.dumps(
        {"profile_id": profile_id, "text": text, "language": language}
    ).encode()

    req = urllib.request.Request(
        f"{config.VOICEBOX_URL}/generate/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        audio_bytes = resp.read()

    out = Path(dest_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to a .tmp file then rename so partial files are never
    # visible to the reader (mirrors the pattern used in progress.py)
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(audio_bytes)
    tmp.replace(out)

    return out
