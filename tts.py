"""
tts.py — Client for the local Voicebox TTS server.

Voicebox must be running at config.VOICEBOX_URL (default: http://localhost:17493).
Voice profiles are matched to characters by name (case-insensitive).

Public API:
    is_running()                                  -> bool
    list_profiles()                               -> list[dict] | None
    find_profile(name)                            -> dict | None
    generate(profile_id, text, dest_path, lang)   -> Path
"""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

_POLL_INTERVAL = 3.0   # seconds between active-task polls


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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _post_generate(profile_id: str, text: str, language: str) -> str:
    """Submit a TTS job via POST /generate and return the job ID."""
    body = json.dumps(
        {"profile_id": profile_id, "text": text, "language": language}
    ).encode()
    req = urllib.request.Request(
        f"{config.VOICEBOX_URL}/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["id"]


def _wait_for_generation(generation_id: str) -> dict:
    """Poll /tasks/active until the job disappears, then return the history record."""
    while True:
        with urllib.request.urlopen(
            f"{config.VOICEBOX_URL}/tasks/active", timeout=10
        ) as resp:
            active = json.loads(resp.read().decode())
        active_ids = {g["task_id"] for g in active.get("generations", [])}
        if generation_id not in active_ids:
            break
        time.sleep(_POLL_INTERVAL)

    with urllib.request.urlopen(
        f"{config.VOICEBOX_URL}/history/{generation_id}", timeout=10
    ) as resp:
        data = json.loads(resp.read().decode())

    if not data.get("audio_path"):
        raise RuntimeError(
            f"Generation finished but audio_path is empty. error={data.get('error')}"
        )
    return data


def _download_audio(generation_id: str, dest: Path) -> None:
    """Stream audio bytes from GET /audio/{id} and write to dest."""
    req = urllib.request.Request(
        f"{config.VOICEBOX_URL}/audio/{generation_id}", method="GET"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with urllib.request.urlopen(req, timeout=60) as resp:
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    tmp.replace(dest)


# ── Public API ────────────────────────────────────────────────────────────────

def generate(
    profile_id: str,
    text: str,
    dest_path: str | Path,
    language: str = "en",
) -> Path:
    """Generate speech and write audio to dest_path.

    Submits a job via POST /generate, polls until done, then downloads the file.

    Args:
        profile_id: Voicebox voice profile UUID.
        text:       Text to synthesize.
        dest_path:  Destination file path.
        language:   BCP-47 language tag (default "en").

    Returns:
        Path to the written file.

    Raises:
        urllib.error.HTTPError: If the server returns a non-2xx status.
        urllib.error.URLError:  If the server is unreachable.
        RuntimeError:           If the job completes but audio is missing.
    """
    out = Path(dest_path)
    gen_id = _post_generate(profile_id, text, language)
    _wait_for_generation(gen_id)
    _download_audio(gen_id, out)
    return out
