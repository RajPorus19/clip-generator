"""
align.py — Runs Whisper on dialogue audio files and caches word-level timestamps.

Cache files are stored in config.CACHE_DIR as JSON:
    cache/peter_001.json  →  [{"word": "hi", "start": 0.0, "end": 0.3}, ...]

Cached results are never re-computed unless the cache file is manually deleted.

Usage:
    from align import ensure_alignments
    timestamps = ensure_alignments(timeline)
    # timestamps["assets/audio/peter_001.mp3"] → list of word dicts
"""

import json
import sys
from pathlib import Path
from typing import Any

import config


# ── Public API ────────────────────────────────────────────────────────────────

def ensure_alignments(
    timeline: list[dict[str, Any]],
    prog: Any = None,
) -> dict[str, list[dict[str, float | str]]]:
    """Ensure all dialogue events have cached word timestamps.

    Loads Whisper only if at least one audio file lacks a cache entry.
    Returns a mapping from audio path → list of word timestamp dicts.

    Args:
        timeline: Ordered list of timeline events from parse.parse_script().
        prog:     Optional Progress instance for stage/step reporting.

    Returns:
        Dict keyed by audio file path, values are lists of
        {"word": str, "start": float, "end": float} dicts.
    """
    def _info(msg: str) -> None:
        if prog:
            prog.info(msg)
        else:
            print(f"[align] {msg}")

    def _warn(msg: str) -> None:
        if prog:
            prog.warn(msg)
        else:
            print(f"[align] WARNING: {msg}")

    cache_dir = Path(config.CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)

    dialogue_events = [e for e in timeline if e["type"] == "dialogue"]
    if not dialogue_events:
        return {}

    # Determine which audio files need processing
    missing: list[dict[str, Any]] = []
    cached_count = 0
    for event in dialogue_events:
        audio_path = event["audio"]
        if _cache_path(audio_path).exists():
            cached_count += 1
        else:
            missing.append(event)

    if cached_count:
        _info(f"{cached_count} file(s) already cached — skipping Whisper")

    # Load Whisper model once for all missing files
    model = None
    if missing:
        _info(f"Loading Whisper model '{config.WHISPER_MODEL}' for {len(missing)} file(s)...")
        import whisper  # lazy import — only when needed
        model = whisper.load_model(config.WHISPER_MODEL)
        _info("Model loaded.")

    total = len(dialogue_events)
    for idx, event in enumerate(dialogue_events, start=1):
        audio_path = event["audio"]
        label = Path(audio_path).name
        if prog:
            prog.step(idx, total, label)
        if not _cache_path(audio_path).exists():
            _run_whisper(model, audio_path, info_fn=_info)

    # Load all timestamps from cache
    results: dict[str, list[dict]] = {}
    for event in dialogue_events:
        audio_path = event["audio"]
        cache_file = _cache_path(audio_path)
        if cache_file.exists():
            with cache_file.open(encoding="utf-8") as fh:
                results[audio_path] = json.load(fh)
        else:
            _warn(f"No timestamps for {audio_path} (audio file missing?)")
            results[audio_path] = []

    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cache_path(audio_path: str) -> Path:
    """Return the cache JSON path for a given audio file path.

    Example: "assets/audio/peter_001.mp3" → "cache/peter_001.json"
    """
    stem = Path(audio_path).stem          # e.g. "peter_001"
    return Path(config.CACHE_DIR) / f"{stem}.json"


def _run_whisper(model: Any, audio_path: str, info_fn: Any = None) -> None:
    """Transcribe an audio file with Whisper and save word timestamps to cache.

    Args:
        model:      A loaded whisper model instance.
        audio_path: Path to the audio file to transcribe.
        info_fn:    Optional callable(str) for status messages.
    """
    def _log(msg: str) -> None:
        if info_fn:
            info_fn(msg)
        else:
            print(f"[align] {msg}")

    audio_file = Path(audio_path)
    if not audio_file.exists():
        _log(f"SKIP — audio file not found: {audio_path}")
        return

    _log(f"Transcribing {Path(audio_path).name} ...")
    result = model.transcribe(
        str(audio_file),
        word_timestamps=True,
        language="en",
        fp16=False,           # safe default; GPU users can override
    )

    words: list[dict[str, float | str]] = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            words.append(
                {
                    "word": w["word"].strip(),
                    "start": round(float(w["start"]), 4),
                    "end": round(float(w["end"]), 4),
                }
            )

    cache_file = _cache_path(audio_path)
    with cache_file.open("w", encoding="utf-8") as fh:
        json.dump(words, fh, indent=2, ensure_ascii=False)

    print(f"[align]   Cached → {cache_file}  ({len(words)} words)")


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json
    from parse import parse_script

    script = sys.argv[1] if len(sys.argv) > 1 else "scripts/episode1.md"
    timeline = parse_script(script)
    timestamps = ensure_alignments(timeline)
    print(_json.dumps(timestamps, indent=2))
