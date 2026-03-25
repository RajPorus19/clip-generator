# Brainrot Generator — Claude Code Guide

## What this project does
Generates vertical short-form MP4 videos (1080×1920, 9:16, 30 fps) for TikTok,
YouTube Shorts, and Instagram Reels from custom markdown script files.

## Entry point
```bash
python render.py scripts/episode1.md              # output → output/episode1.mp4
python render.py scripts/episode1.md custom.mp4   # explicit output path
```

## Module responsibilities
| File | Role |
|------|------|
| `config.py` | **Single source of truth** for all sizes, colors, paths, model names |
| `parse.py` | `.md` script → ordered timeline list |
| `align.py` | Whisper transcription → word timestamp JSON (with cache) |
| `render.py` | Compose everything → export H.264 MP4 |
| `progress.py` | Pipeline progress tracker — TTY output + `output/<job>.status.json` |

## Asset layout
```
assets/
  backgrounds/   *.mp4   landscape gameplay clips (auto-selected at random)
  characters/    *.png   RGBA sprites  (peter.png, stewie.png, …)
  audio/         *.mp3   TTS lines named  <character>_<NNN>.mp3
  pictures/      *.*     graph / image overlays referenced in scripts
  fonts/         bold.ttf  subtitle font (required; fallback = Pillow default)
```

## Script format
```
# comment line (ignored)
[img: "pictures/graph.png" 5s]          ← image overlay for 5 seconds
[peter] : Hello Stewie how are you      ← dialogue line
[stewie] : I am doing great thank you   ← dialogue line
```
- Characters map to `assets/characters/<name>.png` and `assets/audio/<name>_NNN.mp3`
- Image path is relative to project root **or** `assets/`
- Order in file = strict order in video

## Cache
- Whisper results are stored in `cache/<stem>.json`
- Delete a cache file to force re-transcription of that audio file only

## Install
```bash
pip install moviepy openai-whisper Pillow numpy imageio-ffmpeg
```

## Progress tracking

Every render job writes a live status file at `output/<job>.status.json`.
It is updated atomically (tmp-file + rename) at every stage and sub-step transition.

**Watch from another terminal:**
```bash
# one-shot read
cat output/episode1.status.json

# live poll every second
watch -n1 cat output/episode1.status.json

# pretty-print with jq
watch -n1 "jq '.stage, .step_label, (.percent|tostring)+\"%\"' output/episode1.status.json"

# built-in summary viewer
python progress.py output/episode1.status.json
# or auto-discover latest job:
python progress.py
```

**Pipeline stages (in order):**
1. `PARSING` — reading and validating the script
2. `ALIGNING` — Whisper transcription (per-file sub-steps)
3. `BACKGROUND` — loading and cropping gameplay clip
4. `COMPOSITING` — building all layers (per-event sub-steps)
5. `EXPORTING` — FFmpeg encode
6. `DONE` / `ERROR` — terminal states

**Status JSON fields:**
| Field | Meaning |
|-------|---------|
| `stage` | Current pipeline stage name |
| `stage_detail` | Human-readable detail (file path, count, etc.) |
| `step` / `step_total` | Sub-step progress within the current stage |
| `step_label` | Short description of the current sub-step |
| `percent` | 0–100 overall completion estimate |
| `elapsed_s` | Seconds since render started |
| `started_at` / `updated_at` | ISO-8601 UTC timestamps |
| `finished` | `true` when job has ended (success or error) |

**TTY output** uses ANSI colors and a `[████░░░░]` progress bar per stage.
Colors are automatically disabled when stdout is not a TTY (e.g. CI logs).

## Key constraints
- **Never hardcode** dimensions, colors, or paths in `render.py` — always use `config.py`
- Background clips are always **cropped to fill** 9:16 (scale-to-cover) — never letterboxed or pillarboxed
- Whisper is **never run twice** on the same audio file — cache check in `align.py`; first run is slow, all subsequent runs are instant (reads JSON from `cache/`)
- Timeline order is **strictly preserved** — no reordering at render time
- Output must be **H.264** with `-movflags +faststart` and correct vertical scale metadata
- Character PNGs use **RGBA transparency** composited over the background
- **Speaker positions** — the first character encountered in the script gets the left side (`CHARACTER_X_LEFT`), the second gets the right (`CHARACTER_X_RIGHT`); positions are fixed for the whole video
- **Missing assets** — missing audio, sprite, or image files produce a warning log but do not crash; the clip is silently skipped so the rest of the video still renders
- **Font fallback** — if `assets/fonts/bold.ttf` is not found, Pillow's built-in bitmap font is used automatically; it is small and low quality, so always supply a real TTF for production

## Compositing layer order

Enforced in `render.py` — layers are kept in **separate z-buckets** and always composited in this order, regardless of script order:

| Z | Bucket | Rule |
|---|--------|------|
| 1 | Background | Always at the bottom — everything else can cover it |
| 2 | Character sprites | Above background — **exactly one character visible at a time** (the currently speaking one); each sprite clip lasts exactly as long as the character's audio line |
| 3 | Image overlays | Above characters — covers background and sprites |
| 4 | Subtitles | **Always topmost** — never hidden by anything, including images |

**Subtitle position avoidance** — subtitles are on top but must not visually overlap an active image. `_subtitle_y(block_h, image_rect)` in `render.py` shifts the subtitle below the image (preferred) or above it if below doesn't fit. `make_subtitle_clip` accepts an optional `image_rect: tuple[int, int, int, int]` for this purpose.

**Implementation:** `character_layers`, `image_layers`, and `subtitle_layers` are accumulated separately during the compositing loop and concatenated in z-order:
```python
[bg_clip] + character_layers + image_layers + subtitle_layers
```

**Never flatten these into a single list** — doing so would break the z-ordering guarantee.

## Image overlay sizing rules

Enforced in `make_image_overlay_clip` in `render.py`:

- Image is scaled **as large as possible** to fill the available area
- Available area = full frame minus `GRAPH_PADDING` on every side (left, right, top, bottom)
- Scale factor = `min(max_w / img.width, max_h / img.height)` — whichever axis is the binding constraint
- **Aspect ratio is NEVER changed** — this rule must never be broken
- Image is centered both horizontally and vertically within the full frame
- Works for any input size: tiny thumbnails scale up; huge images scale down; square, portrait, and landscape all handled correctly

## Config knobs worth knowing
| Setting | Default | Effect |
|---------|---------|--------|
| `WHISPER_MODEL` | `"base"` | Accuracy vs speed tradeoff |
| `CHARACTER_SCALE` | `0.45` | Sprite size relative to frame width |
| `SUBTITLE_HIGHLIGHT_COLOR` | `(255,220,0)` | Active word color |
| `CHARACTER_X_LEFT/RIGHT` | `80/600` | Speaker horizontal positions |
| `SUBTITLE_Y` | `1150` | Subtitle block vertical anchor |
| `GRAPH_Y_CENTER` | `600` | Image overlay vertical center |
