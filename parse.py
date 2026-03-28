"""
parse.py — Parses a custom markdown script file into an ordered timeline list.

Supported syntax:
    [character] : dialogue line
    [img: "path/to/image.png" 5s]

Usage:
    from parse import parse_script
    timeline = parse_script("scripts/episode1.md")
"""

import hashlib
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import config

# ── Web image cache ───────────────────────────────────────────────────────────

_WEB_IMAGE_CACHE_DIR = Path(config.CACHE_DIR) / "web_images"


def _download_web_image(url: str) -> Path | None:
    """Download a web image URL to the local cache and return its path.

    Uses a hash of the URL as the filename so repeated parses of the same
    script never re-download the same file.

    Args:
        url: HTTP/HTTPS URL to the image.

    Returns:
        Local Path to the cached file, or None on failure.
    """
    _WEB_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Preserve the original extension if present; fall back to .png
    parsed_path = urllib.parse.urlparse(url).path
    suffix = Path(parsed_path).suffix.lower() or ".png"
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    local_path = _WEB_IMAGE_CACHE_DIR / f"{url_hash}{suffix}"

    if local_path.exists():
        print(f"[parse] Web image cache hit: {local_path}")
        return local_path

    print(f"[parse] Downloading web image: {url}")
    try:
        urllib.request.urlretrieve(url, local_path)  # noqa: S310
        print(f"[parse] Saved to: {local_path}")
        return local_path
    except Exception as exc:
        print(f"[parse] WARNING: failed to download {url!r} — {exc}")
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def resolve_asset_path(file_rel: str) -> Path | None:
    """Resolve an asset path to an existing file.

    Tries the path as given first, then relative to config.ASSETS_DIR.

    Args:
        file_rel: Path as written in the script (e.g. "pictures/graph.png").

    Returns:
        The first existing Path, or None if neither candidate exists.
    """
    for candidate in (Path(file_rel), Path(config.ASSETS_DIR) / file_rel):
        if candidate.exists():
            return candidate
    return None


# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_DIALOGUE = re.compile(
    r"^\[(?P<character>[a-zA-Z0-9_]+)\]\s*:\s*(?P<line>.+)$"
)
_RE_IMAGE = re.compile(
    r'^\[img:\s*"(?P<file>[^"]+)"\s+(?P<duration>[0-9]+(?:\.[0-9]+)?)s\]$'
)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_script(script_path: str) -> list[dict[str, Any]]:
    """Parse a markdown script file into an ordered timeline.

    Each element is either:
        {"type": "dialogue", "character": str, "line": str, "audio": str}
        {"type": "image",    "file": str, "duration": float}

    Audio paths are auto-assigned as:
        assets/audio/{character}_{index:03d}.mp3
    where index is the 1-based count of that character's lines so far.

    Args:
        script_path: Path to the .md script file.

    Returns:
        Ordered list of timeline event dicts.

    Raises:
        FileNotFoundError: If the script file does not exist.
    """
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    timeline: list[dict[str, Any]] = []
    char_counters: dict[str, int] = {}   # per-character line index

    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue  # skip blanks and comments

            m_img = _RE_IMAGE.match(line)
            if m_img:
                event = _parse_image_event(m_img, lineno)
                if event:
                    timeline.append(event)
                continue

            m_dia = _RE_DIALOGUE.match(line)
            if m_dia:
                event = _parse_dialogue_event(m_dia, char_counters, lineno)
                if event:
                    timeline.append(event)
                continue

            print(f"[parse] WARNING line {lineno}: unrecognised syntax — {line!r}")

    return timeline


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_image_event(
    match: re.Match, lineno: int
) -> dict[str, Any] | None:
    """Build an image overlay event from a regex match."""
    file_rel = match.group("file")
    duration = float(match.group("duration"))

    # Download web images and replace with a local cache path
    if file_rel.startswith(("http://", "https://")):
        local = _download_web_image(file_rel)
        if local is None:
            print(f"[parse] WARNING line {lineno}: could not download web image — {file_rel}")
        else:
            file_rel = str(local)
    elif resolve_asset_path(file_rel) is None:
        print(f"[parse] WARNING line {lineno}: image file not found — {file_rel}")

    return {"type": "image", "file": file_rel, "duration": duration}


def _parse_dialogue_event(
    match: re.Match,
    char_counters: dict[str, int],
    lineno: int,
) -> dict[str, Any] | None:
    """Build a dialogue event from a regex match, auto-assigning audio path."""
    character = match.group("character").lower()
    line_text = match.group("line").strip()

    # Increment per-character counter
    char_counters[character] = char_counters.get(character, 0) + 1
    index = char_counters[character]

    audio_path = str(
        Path(config.AUDIO_DIR) / f"{character}_{index:03d}.{config.AUDIO_EXT}"
    )

    if not Path(audio_path).exists():
        print(
            f"[parse] WARNING line {lineno}: audio file not found — {audio_path}"
        )

    return {
        "type": "dialogue",
        "character": character,
        "line": line_text,
        "audio": audio_path,
    }


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    script = sys.argv[1] if len(sys.argv) > 1 else "scripts/episode1.md"
    result = parse_script(script)
    print(json.dumps(result, indent=2))
