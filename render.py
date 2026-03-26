"""
render.py — Main rendering engine for the brainrot video generator.

Orchestrates parse → align → compose → export.

Usage:
    python render.py scripts/episode1.md [output/episode1.mp4]
"""

import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
)
from moviepy.audio.AudioClip import CompositeAudioClip

import config
from parse import parse_script, resolve_asset_path
from align import ensure_alignments
from progress import Progress
from validate import validate, print_report
import tts


# ── Font singleton ────────────────────────────────────────────────────────────

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load and cache the subtitle font at a given size.

    Falls back to Pillow's default font if the TTF file is missing.

    Args:
        size: Point size for the font.

    Returns:
        A Pillow font object.
    """
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]

    font_path = Path(config.SUBTITLE_FONT)
    try:
        font = ImageFont.truetype(str(font_path), size)
    except (IOError, OSError):
        print(
            f"[render] WARNING: font not found at {font_path}. "
            "Using Pillow default font — install a TTF for better results."
        )
        font = ImageFont.load_default()

    _FONT_CACHE[size] = font
    return font


# ── Background ────────────────────────────────────────────────────────────────

def load_background(total_duration: float) -> VideoFileClip:
    """Randomly select a background MP4, crop to 9:16, loop to fill duration.

    The landscape clip is scaled so its height matches 1920, then the center
    1080 pixels are cropped horizontally (or vice-versa depending on aspect).

    Args:
        total_duration: Required duration in seconds.

    Returns:
        A MoviePy VideoFileClip ready for compositing.

    Raises:
        FileNotFoundError: If no background MP4 files are found.
    """
    bg_dir = Path(config.BACKGROUNDS_DIR)
    mp4_files = list(bg_dir.glob("*.mp4")) + list(bg_dir.glob("*.MP4"))
    if not mp4_files:
        raise FileNotFoundError(
            f"No background MP4 files found in {bg_dir}. "
            "Add gameplay footage clips to assets/backgrounds/."
        )

    chosen = random.choice(mp4_files)
    print(f"[render] Background: {chosen.name}")

    clip = VideoFileClip(str(chosen), audio=False)

    target_w, target_h = config.RESOLUTION

    # Scale so the clip fills the target frame (cover, not contain)
    src_w, src_h = clip.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    clip = clip.resized((new_w, new_h))

    # Center-crop to exact target resolution
    x1 = (new_w - target_w) // 2
    y1 = (new_h - target_h) // 2
    clip = clip.cropped(x1=x1, y1=y1, x2=x1 + target_w, y2=y1 + target_h)

    # Pick a random start point so each render uses a different portion.
    # If the background is shorter than needed, loop it first then pick randomly.
    if clip.duration < total_duration:
        clip = clip.loop(duration=clip.duration * (int(total_duration / clip.duration) + 2))

    max_start = clip.duration - total_duration
    start = random.uniform(0, max_start)
    clip = clip.subclipped(start, start + total_duration)
    print(f"[render] Background start: {start:.1f}s")

    return clip


# ── Character sprite ──────────────────────────────────────────────────────────

def make_character_clip(
    character: str,
    duration: float,
    x_pos: int,
) -> ImageClip | None:
    """Create a static ImageClip for a character sprite.

    The sprite is scaled so its width equals CHARACTER_SCALE * frame_width,
    then anchored at (x_pos, CHARACTER_ZONE_Y).

    Args:
        character: Character name.
        duration:  How long the clip should last.
        x_pos:     Left edge X coordinate.

    Returns:
        An ImageClip, or None if the sprite image is missing.
    """
    path = Path(config.CHARACTERS_DIR) / f"{character}.png"
    if not path.exists():
        print(f"[render] WARNING: character sprite not found — {path}")
        return None

    img = Image.open(path).convert("RGBA")
    target_w = int(config.RESOLUTION[0] * config.CHARACTER_SCALE)
    target_h = int(target_w * (img.height / img.width))
    img = img.resize((target_w, target_h), Image.LANCZOS)

    return (
        ImageClip(np.array(img), duration=duration)
        .with_position((x_pos, config.CHARACTER_ZONE_Y))
    )


# ── Subtitle rendering ────────────────────────────────────────────────────────



def make_subtitle_clip(
    line_text: str,
    timestamps: list[dict],
    duration: float,
    image_rect: tuple[int, int, int, int] | None = None,
) -> VideoClip:
    """Karaoke-style subtitles: 3 words at a time, white with the spoken word in yellow.

    Words are grouped into chunks of SUBTITLE_WORDS_PER_CHUNK. The visible chunk
    advances as the dialogue progresses. The currently spoken word is highlighted
    in yellow; all others in the chunk are white. Black outline on all words.
    """
    font = _get_font(config.SUBTITLE_FONT_SIZE)
    frame_w = config.RESOLUTION[0]
    line_words = line_text.split()
    n = len(line_words)
    chunk_size = config.SUBTITLE_WORDS_PER_CHUNK

    # Word start times by position
    word_starts = [
        timestamps[i]["start"] if i < len(timestamps) else float("inf")
        for i in range(n)
    ]

    # Chunks: [[w0,w1,w2], [w3,w4,w5], ...]
    chunks = [line_words[i:i + chunk_size] for i in range(0, n, chunk_size)]

    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    _, _, _, line_h = dummy_draw.textbbox((0, 0), "Ag", font=font)
    line_h += config.SUBTITLE_STROKE_WIDTH * 2 + 4   # room for stroke

    max_w = frame_w - 40   # 20px padding each side

    def _word_w(word: str) -> int:
        return dummy_draw.textbbox((0, 0), word + " ", font=font)[2]

    def _wrap(words: list[str]) -> list[list[str]]:
        """Wrap a list of words into lines that fit within max_w."""
        lines: list[list[str]] = []
        current: list[str] = []
        cur_w = 0
        for word in words:
            w = _word_w(word)
            if current and cur_w + w > max_w:
                lines.append(current)
                current = [word]
                cur_w = w
            else:
                current.append(word)
                cur_w += w
        if current:
            lines.append(current)
        return lines

    # Pre-compute wrapped layout for every chunk so canvas height is fixed
    chunk_layouts = [_wrap(chunk) for chunk in chunks]
    max_lines = max(len(layout) for layout in chunk_layouts)
    canvas_h = line_h * max_lines

    def make_frame(t: float) -> np.ndarray:
        active_idx = None
        for i, start in enumerate(word_starts):
            if start <= t:
                active_idx = i

        chunk_idx = (active_idx // chunk_size) if active_idx is not None else 0
        chunk_idx = min(chunk_idx, len(chunks) - 1)
        base_idx = chunk_idx * chunk_size
        layout = chunk_layouts[chunk_idx]

        img = Image.new("RGBA", (frame_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        flat_j = 0
        for row_i, row_words in enumerate(layout):
            row_widths = [_word_w(w) for w in row_words]
            x = (frame_w - sum(row_widths)) // 2
            y = row_i * line_h
            for word, w in zip(row_words, row_widths):
                global_idx = base_idx + flat_j
                color = (
                    config.SUBTITLE_HIGHLIGHT_COLOR + (255,)
                    if global_idx == active_idx
                    else config.SUBTITLE_COLOR + (255,)
                )
                draw.text(
                    (x, y), word, font=font,
                    fill=color,
                    stroke_width=config.SUBTITLE_STROKE_WIDTH,
                    stroke_fill=(0, 0, 0, 255),
                )
                x += w
                flat_j += 1

        return np.array(img)

    return VideoClip(make_frame, duration=duration).with_position((0, config.SUBTITLE_Y))


# ── Image overlay ─────────────────────────────────────────────────────────────

def make_image_overlay_clip(file_rel: str, duration: float) -> ImageClip | None:
    """Load an image, scale it to fit the overlay zone, center it.

    Args:
        file_rel: Relative path to the image (from project root or assets/).
        duration: How long to display the overlay.

    Returns:
        A positioned ImageClip, or None if the file is not found.
    """
    img_path = resolve_asset_path(file_rel)
    if img_path is None:
        print(f"[render] WARNING: image overlay not found — {file_rel}")
        return None

    img = Image.open(img_path).convert("RGBA")

    frame_w, frame_h = config.RESOLUTION
    max_w = frame_w - config.GRAPH_PADDING * 2
    max_h = frame_h - config.GRAPH_PADDING * 2

    # Scale up or down uniformly so the image is as large as possible
    # without exceeding either dimension — aspect ratio is NEVER changed.
    scale = min(max_w / img.width, max_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    if (new_w, new_h) != (img.width, img.height):
        img = img.resize((new_w, new_h), Image.LANCZOS)

    arr = np.array(img)
    clip = ImageClip(arr, duration=duration)

    # True center: both horizontally and vertically within the full frame
    x = (frame_w - new_w) // 2
    y = (frame_h - new_h) // 2
    clip = clip.with_position((x, y))

    return clip


# ── Speaker position assignment ───────────────────────────────────────────────

def _build_speaker_positions(timeline: list[dict]) -> dict[str, int]:
    """Assign a fixed horizontal position (left/right) to each character.

    The first character seen is placed on the left; the second on the right.
    Additional characters cycle through the two positions.

    Args:
        timeline: Full ordered timeline list.

    Returns:
        Dict mapping character name → X pixel position.
    """
    positions: dict[str, int] = {}
    sides = [config.CHARACTER_X_LEFT, config.CHARACTER_X_RIGHT]
    side_idx = 0

    for event in timeline:
        if event["type"] == "dialogue":
            char = event["character"]
            if char not in positions:
                positions[char] = sides[side_idx % 2]
                side_idx += 1

    return positions


# ── Main render pipeline ──────────────────────────────────────────────────────

def render(script_path: str, output_path: str | None = None) -> None:
    """Full render pipeline: parse → align → compose → export.

    Args:
        script_path: Path to the .md script file.
        output_path: Destination MP4 path. Defaults to output/<stem>.mp4.
    """
    stem = Path(script_path).stem
    if output_path is None:
        output_path = str(Path(config.OUTPUT_DIR) / f"{stem}.mp4")

    prog = Progress(stem, output_dir=config.OUTPUT_DIR)

    try:
        # ── 1. Parse ──────────────────────────────────────────────────────────
        prog.stage("PARSING", script_path)
        timeline = parse_script(script_path)
        if not timeline:
            prog.error("Empty timeline — nothing to render.")
            return

        dialogue_count = sum(1 for e in timeline if e["type"] == "dialogue")
        image_count    = sum(1 for e in timeline if e["type"] == "image")
        prog.info(f"{len(timeline)} events  ({dialogue_count} dialogue, {image_count} image)")

        # ── 2. Validate assets ────────────────────────────────────────────────
        prog.stage("VALIDATING", script_path)
        report = validate(script_path)

        for w in report.warnings:
            prog.warn(w)

        blocking = report.blocking_errors
        if blocking:
            for e in blocking:
                prog.warn(e)
            prog.error(f"{len(blocking)} blocking error(s) — see warnings above")
            return

        prog.info(
            f"Voicebox: {'running' if report.voicebox_running else 'not running'}  |  "
            f"{'All audio present' if not report.missing_audio else f'{len(report.missing_audio)} audio file(s) missing'}"
        )

        # ── 3. Auto-generate missing audio ────────────────────────────────────
        if report.generatable_audio:
            # Build name→profile lookup from already-fetched profiles (no extra HTTP calls)
            profile_by_name = {
                p.get("name", "").lower(): p for p in report.voicebox_profiles
            }
            prog.stage(
                "GENERATING",
                f"{len(report.generatable_audio)} audio file(s)",
                step_total=len(report.generatable_audio),
            )
            for i, item in enumerate(report.generatable_audio, start=1):
                prog.step(i, len(report.generatable_audio), Path(item["path"]).name)
                profile = profile_by_name.get(item["character"].lower())
                if profile is None:
                    prog.warn(f"No Voicebox profile named '{item['character']}' — skipping")
                    continue
                try:
                    tts.generate(profile["id"], item["line"], item["path"])
                    prog.info(f"Generated: {item['path']}")
                except Exception as exc:
                    prog.warn(f"TTS failed for {item['path']}: {exc}")

        # ── 4. Align (Whisper) ────────────────────────────────────────────────
        prog.stage("ALIGNING", f"{dialogue_count} audio file(s)", step_total=dialogue_count)
        timestamps_map = ensure_alignments(timeline, prog)

        # ── 5. Compute total duration ─────────────────────────────────────────
        total_duration = _compute_total_duration(timeline)
        prog.info(f"Total video duration: {total_duration:.2f}s")

        # ── 6. Load background ────────────────────────────────────────────────
        prog.stage("BACKGROUND", config.BACKGROUNDS_DIR)
        bg_clip = load_background(total_duration)
        prog.info(f"Loaded and cropped to {config.RESOLUTION[0]}×{config.RESOLUTION[1]}")

        # ── 7. Speaker position map ───────────────────────────────────────────
        speaker_positions = _build_speaker_positions(timeline)

        # ── 8. Build all layers ───────────────────────────────────────────────
        # Layers are kept in separate buckets so the final composite always
        # respects the z-order rules regardless of script order:
        #   background → characters → subtitles → image overlays
        prog.stage(
            "COMPOSITING",
            f"{len(timeline)} events",
            step_total=len(timeline),
        )
        character_layers: list[Any] = []
        subtitle_layers: list[Any] = []
        image_layers: list[Any] = []
        audio_clips: list[Any] = []
        time_cursor = 0.0
        # Collect image events as (start_time, max_duration, file_rel) —
        # effective durations are capped later so a new image always
        # replaces the previous one immediately, even mid-display.
        pending_images: list[tuple[float, float, str]] = []

        for event_i, event in enumerate(timeline, start=1):
            if event["type"] == "dialogue":
                label = f"[{event['character']}] {event['line'][:45]}"
                prog.step(event_i, len(timeline), label)
                time_cursor = _process_dialogue_event(
                    event,
                    time_cursor,
                    timestamps_map,
                    speaker_positions,
                    character_layers,
                    subtitle_layers,
                    audio_clips,
                    prog,
                )
            elif event["type"] == "image":
                label = f"[img] {event['file']}  {event['duration']}s"
                prog.step(event_i, len(timeline), label)
                pending_images.append((time_cursor, event["duration"], event["file"]))
                prog.info(f"[img] {event['file']}  @ {time_cursor:.2f}s  (up to {event['duration']}s)")

        # Build image clips with capped durations: each image ends at the
        # earlier of (start + max_duration) or the moment the next image starts.
        for i, (start, max_dur, file_rel) in enumerate(pending_images):
            if i + 1 < len(pending_images):
                next_start = pending_images[i + 1][0]
                effective_dur = min(max_dur, next_start - start)
            else:
                effective_dur = min(max_dur, time_cursor - start)
            effective_dur = max(effective_dur, 0.0)

            overlay = make_image_overlay_clip(file_rel, effective_dur)
            if overlay is not None:
                image_layers.append(overlay.with_start(start))
            else:
                prog.warn(f"Image overlay not found — {file_rel}")

        # ── 9. Composite (z-order: bg → characters → images → subtitles) ───────
        # Subtitles are always topmost so they're never hidden, but they are
        # positioned to avoid visually overlapping any active image (see
        # _subtitle_y() and make_subtitle_clip()).
        prog.info("Compositing all video layers...")
        final_video = CompositeVideoClip(
            [bg_clip] + character_layers + image_layers + subtitle_layers,
            size=config.RESOLUTION,
        )

        # ── 10. Attach audio ──────────────────────────────────────────────────
        if audio_clips:
            prog.info("Merging audio tracks...")
            merged_audio = CompositeAudioClip(audio_clips)
            final_video = final_video.with_audio(merged_audio)

        # ── 11. Export ────────────────────────────────────────────────────────
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        prog.stage("EXPORTING", output_path)

        final_video.write_videofile(
            output_path,
            fps=config.FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            ffmpeg_params=[
                "-vf", "scale=1080:1920",
                "-movflags", "+faststart",
            ],
            logger="bar",
        )

        prog.done(output_path)

    except Exception as exc:
        prog.error(str(exc))
        raise


# ── Event processors ──────────────────────────────────────────────────────────

def _process_dialogue_event(
    event: dict,
    time_cursor: float,
    timestamps_map: dict,
    speaker_positions: dict,
    character_layers: list,
    subtitle_layers: list,
    audio_clips: list,
    prog: "Progress",
) -> float:
    """Add character sprite, subtitle, and audio clips for a dialogue event.

    Character clip goes into character_layers (z=2).
    Subtitle clip goes into subtitle_layers (z=3).
    Only the speaking character is shown — one at a time, never two at once.

    Args:
        event:             Dialogue event dict.
        time_cursor:       Current time position in seconds.
        timestamps_map:    Audio path → word timestamp list.
        speaker_positions: Character name → X position.
        character_layers:  Z-bucket for character sprites.
        subtitle_layers:   Z-bucket for subtitle clips.
        audio_clips:       List to append new AudioFileClip objects to.
        prog:              Progress tracker instance.

    Returns:
        Updated time_cursor (advanced by audio duration).
    """
    character = event["character"]
    audio_path = event["audio"]
    line_text = event["line"]

    if not Path(audio_path).exists():
        prog.warn(f"SKIP dialogue — audio not found: {audio_path}")
        return time_cursor

    raw_audio = AudioFileClip(audio_path)

    # Trim trailing silence: use last Whisper word end + small tail buffer
    # so dialogue clips back-to-back with no dead air between lines.
    word_ts = timestamps_map.get(audio_path, [])
    if word_ts:
        trimmed = min(
            word_ts[-1]["end"] + config.AUDIO_TAIL_PADDING,
            raw_audio.duration,
        )
        audio_clip = raw_audio.subclipped(0, trimmed).with_start(time_cursor)
    else:
        audio_clip = raw_audio.with_start(time_cursor)

    duration = audio_clip.duration
    audio_clips.append(audio_clip)

    # Character sprite — visible only for the duration of this line
    x_pos = speaker_positions.get(character, config.CHARACTER_X_LEFT)
    char_clip = make_character_clip(character, duration, x_pos)
    if char_clip is not None:
        character_layers.append(char_clip.with_start(time_cursor))
    else:
        prog.warn(f"No sprite for '{character}' — skipping sprite layer")
    subtitle_clip = make_subtitle_clip(line_text, word_ts, duration)
    subtitle_layers.append(subtitle_clip.with_start(time_cursor))

    prog.info(
        f"[{character}] {line_text[:50]!r}  "
        f"@ {time_cursor:.2f}s – {time_cursor + duration:.2f}s  "
        f"({duration:.1f}s)"
    )
    return time_cursor + duration



def _compute_total_duration(timeline: list[dict]) -> float:
    """Compute total video duration by summing audio + image durations.

    For dialogue events without an existing audio file, a duration of 0 is used.

    Args:
        timeline: Full ordered timeline list.

    Returns:
        Total duration in seconds.
    """
    total = 0.0
    for event in timeline:
        if event["type"] == "dialogue":
            audio_path = event["audio"]
            if Path(audio_path).exists():
                ac = AudioFileClip(audio_path)
                total += ac.duration
                ac.close()
    return total


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Brainrot video generator")
    ap.add_argument("script", help="Path to .md script file")
    ap.add_argument("output", nargs="?", default=None, help="Output MP4 path (optional)")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Validate assets and exit without rendering",
    )
    args = ap.parse_args()

    if args.check:
        report = validate(args.script)
        print_report(report, args.script)
        sys.exit(1 if report.blocking_errors else 0)
    else:
        render(args.script, args.output)
