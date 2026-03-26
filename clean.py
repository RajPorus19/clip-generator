"""
clean.py — Remove generated files (audio, Whisper cache, output).

Does NOT touch assets (backgrounds, characters, pictures, fonts).

Usage:
    python clean.py          # dry run — shows what would be deleted
    python clean.py --yes    # actually delete
"""

import sys
from pathlib import Path

import config

PATTERNS = [
    (config.AUDIO_DIR,  f"*.{config.AUDIO_EXT}"),
    (config.CACHE_DIR,  "*.json"),
    (config.OUTPUT_DIR, "*.mp4"),
    (config.OUTPUT_DIR, "*.status.json"),
]


def collect() -> list[Path]:
    files = []
    for directory, pattern in PATTERNS:
        files.extend(Path(directory).glob(pattern))
    return sorted(files)


def main() -> None:
    dry_run = "--yes" not in sys.argv
    files = collect()

    if not files:
        print("Nothing to clean.")
        return

    for f in files:
        print(f"  {'[dry-run] ' if dry_run else ''}remove  {f}")

    if dry_run:
        print(f"\n{len(files)} file(s) would be removed. Run with --yes to delete.")
    else:
        for f in files:
            f.unlink()
        print(f"\n{len(files)} file(s) removed.")


if __name__ == "__main__":
    main()
