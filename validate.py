"""
validate.py — Pre-render asset validation and dry-run.

Checks all assets referenced by a script and reports:
  - Whether the Voicebox TTS server is reachable
  - Missing backgrounds, sprites, audio files, image overlays, font
  - Which missing audio files can be auto-generated via Voicebox

Usage:
    # As CLI (dry-run, exits 0 if clean, 1 if blocking errors)
    python validate.py scripts/episode1.md

    # From render.py (or any other module)
    from validate import validate
    report = validate("scripts/episode1.md")
    if report.blocking_errors:
        sys.exit(1)
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

import config
import tts
from parse import parse_script, resolve_asset_path


# ── Report dataclass ──────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    """Structured result of a pre-render validation pass."""

    script_ok: bool = False
    voicebox_running: bool = False
    voicebox_profiles: list[dict] = field(default_factory=list)
    backgrounds_ok: bool = False
    font_ok: bool = False

    missing_sprites: list[str] = field(default_factory=list)       # character names
    missing_images: list[str] = field(default_factory=list)        # image file paths
    missing_audio: list[str] = field(default_factory=list)         # audio file paths
    generatable_audio: list[dict] = field(default_factory=list)    # {path, character, line}

    parse_error: str = ""    # non-empty when script failed to parse

    @property
    def blocking_errors(self) -> list[str]:
        """Issues that will prevent the render from completing."""
        errors: list[str] = []

        if not self.script_ok:
            errors.append(f"Script could not be parsed: {self.parse_error}")
            return errors   # can't check anything else

        if not self.backgrounds_ok:
            errors.append(f"No background MP4s found in {config.BACKGROUNDS_DIR}")

        # Audio that is missing AND cannot be auto-generated is fatal
        generatable_paths = {g["path"] for g in self.generatable_audio}
        unresolvable = [p for p in self.missing_audio if p not in generatable_paths]
        for p in unresolvable:
            errors.append(f"Audio missing (no TTS fallback): {p}")

        return errors

    @property
    def warnings(self) -> list[str]:
        """Issues that degrade quality but won't crash the render."""
        w: list[str] = []
        if not self.font_ok:
            w.append(
                f"Font not found at {config.SUBTITLE_FONT} — "
                "Pillow fallback will be used (low quality)"
            )
        for name in self.missing_sprites:
            w.append(f"Sprite missing: assets/characters/{name}.png")
        for path in self.missing_images:
            w.append(f"Image overlay missing: {path}")
        if self.generatable_audio:
            w.append(
                f"{len(self.generatable_audio)} audio file(s) missing — "
                "will be generated via Voicebox before rendering"
            )
        return w


# ── Public API ────────────────────────────────────────────────────────────────

def validate(script_path: str) -> ValidationReport:
    """Run a full pre-render validation pass and return a structured report.

    Args:
        script_path: Path to the .md script file.

    Returns:
        A ValidationReport with all findings populated.
    """
    report = ValidationReport()

    # ── Parse script ─────────────────────────────────────────────────────────
    try:
        timeline = parse_script(script_path)
        report.script_ok = True
    except Exception as exc:
        report.parse_error = str(exc)
        return report

    dialogue_events = [e for e in timeline if e["type"] == "dialogue"]
    image_events    = [e for e in timeline if e["type"] == "image"]

    # ── Voicebox health check ─────────────────────────────────────────────────
    profiles = tts.list_profiles()
    report.voicebox_running = profiles is not None
    report.voicebox_profiles = profiles or []

    # ── Backgrounds ──────────────────────────────────────────────────────────
    bg_dir = Path(config.BACKGROUNDS_DIR)
    bg_files = list(bg_dir.glob("*.mp4")) + list(bg_dir.glob("*.MP4"))
    report.backgrounds_ok = len(bg_files) > 0

    # ── Font ─────────────────────────────────────────────────────────────────
    report.font_ok = Path(config.SUBTITLE_FONT).exists()

    # ── Sprites and audio (per character / per dialogue event) ───────────────
    seen_characters: set[str] = set()

    for event in dialogue_events:
        char = event["character"]
        audio = event["audio"]

        # Check sprite once per character
        if char not in seen_characters:
            seen_characters.add(char)
            sprite = Path(config.CHARACTERS_DIR) / f"{char}.png"
            if not sprite.exists():
                report.missing_sprites.append(char)

        # Check audio
        if not Path(audio).exists():
            report.missing_audio.append(audio)
            # Can we auto-generate it? Voicebox must be running and have a
            # profile whose name matches the character name exactly.
            if report.voicebox_running and any(
                p.get("name", "").lower() == char.lower()
                for p in report.voicebox_profiles
            ):
                report.generatable_audio.append({
                    "path":      audio,
                    "character": char,
                    "line":      event["line"],
                })

    # ── Image overlays ───────────────────────────────────────────────────────
    for event in image_events:
        if resolve_asset_path(event["file"]) is None:
            report.missing_images.append(event["file"])

    return report


# ── CLI printer ───────────────────────────────────────────────────────────────

def print_report(report: ValidationReport, script_path: str = "") -> None:
    """Print a human-readable validation report to stdout."""
    width = 54
    print(f"\nValidating: {script_path}")
    print("─" * width)

    def ok(msg: str)   -> None: print(f"  [ OK ]  {msg}")
    def warn(msg: str) -> None: print(f"  [WARN]  {msg}")
    def err(msg: str)  -> None: print(f"  [ ERR]  {msg}")

    # Script
    if report.script_ok:
        ok(f"Script parsed successfully")
    else:
        err(f"Script parse failed: {report.parse_error}")
        print("─" * width)
        print("Cannot continue — fix the script and try again.\n")
        return

    # Voicebox
    if report.voicebox_running:
        profile_count = len(report.voicebox_profiles)
        ok(f"Voicebox running at {config.VOICEBOX_URL} ({profile_count} profile(s))")
    else:
        warn(f"Voicebox NOT running at {config.VOICEBOX_URL}")

    # Backgrounds
    if report.backgrounds_ok:
        ok(f"Backgrounds found in {config.BACKGROUNDS_DIR}")
    else:
        err(f"No backgrounds found in {config.BACKGROUNDS_DIR}")

    # Font
    if report.font_ok:
        ok(f"Font: {config.SUBTITLE_FONT}")
    else:
        warn(f"Font not found: {config.SUBTITLE_FONT} (Pillow fallback)")

    # Sprites
    if not report.missing_sprites:
        ok("All character sprites present")
    else:
        for name in report.missing_sprites:
            warn(f"Sprite missing: assets/characters/{name}.png")

    # Audio
    if not report.missing_audio:
        ok("All audio files present")
    else:
        generatable_paths = {g["path"] for g in report.generatable_audio}
        for path in report.missing_audio:
            if path in generatable_paths:
                warn(f"Audio missing (will generate): {path}")
            else:
                err(f"Audio missing (no fallback):   {path}")

    # Image overlays
    if not report.missing_images:
        ok("All image overlays present")
    else:
        for path in report.missing_images:
            err(f"Image overlay missing: {path}")

    # Summary
    print("─" * width)
    blocking = report.blocking_errors
    warnings = report.warnings
    if not blocking:
        print(f"  Ready to render.")
        if warnings:
            print(f"  {len(warnings)} warning(s) — render will proceed with degraded output.")
    else:
        print(f"  {len(blocking)} blocking error(s) — fix these before rendering:")
        for e in blocking:
            print(f"    • {e}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    script = sys.argv[1] if len(sys.argv) > 1 else "scripts/episode1.md"
    report = validate(script)
    print_report(report, script)
    sys.exit(1 if report.blocking_errors else 0)
