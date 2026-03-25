# Clip Generator

Generates vertical short-form MP4 videos (1080×1920, 9:16, 30 fps) for TikTok, YouTube Shorts, and Instagram Reels from simple markdown script files. Characters talk over gameplay footage with karaoke-style subtitles.

## How it works

1. You write a **script** (`.md` file) with dialogue lines and optional image overlays
2. You provide **TTS audio** files (one MP3 per dialogue line, pre-generated)
3. The pipeline parses the script → transcribes audio with Whisper → composites everything → exports H.264

```
Script (.md)  +  Audio (.mp3)  +  Background (.mp4)  +  Character sprites (.png)
       └──────────────────────────────────┬──────────────────────────────────────┘
                                    render.py
                                          │
                                    output/*.mp4
```

## Install

```bash
pip install moviepy openai-whisper Pillow numpy imageio-ffmpeg
```

## Usage

```bash
python render.py scripts/episode1.md              # output → output/episode1.mp4
python render.py scripts/episode1.md custom.mp4   # custom output path
```

## Asset structure

You need to populate the `assets/` folder before rendering. Here is everything required:

```
assets/
├── backgrounds/        ← gameplay footage (landscape MP4s, any resolution)
│   └── minecraft.mp4
│   └── subway_surfers.mp4
│
├── characters/         ← character sprites (PNG with transparency)
│   └── peter.png
│   └── stewie.png
│
├── audio/              ← TTS audio, one MP3 per dialogue line
│   └── peter_001.mp3   ← Peter's 1st line
│   └── peter_002.mp3   ← Peter's 2nd line
│   └── stewie_001.mp3  ← Stewie's 1st line
│   └── stewie_002.mp3
│   └── ...
│
├── fonts/
│   └── bold.ttf        ← subtitle font (any bold TTF; fallback = low-quality bitmap)
│
└── pictures/           ← graph/image overlays referenced in scripts
    └── intro_chart.png
    └── inflation_graph.png
```

### Backgrounds

- Any landscape MP4 — the renderer crops it to fill 9:16 automatically (scale-to-cover, never letterboxed)
- One background is picked at random per render
- You can have as many as you want in `assets/backgrounds/`

### Character sprites

- PNG files with **RGBA transparency** (transparent background)
- Named exactly as they appear in the script: `[peter]` → `assets/characters/peter.png`
- They are scaled to ~45% of frame width by default (configurable in `config.py`)
- First character encountered in the script goes on the **left**, second on the **right**

### Audio files

- One MP3 per dialogue line, named `<character>_<NNN>.mp3` (zero-padded 3-digit index)
- The index counts that character's lines in order from the top of the script
- Generate these with any TTS tool (ElevenLabs, edge-tts, etc.) before rendering
- Missing audio files produce a warning but don't crash — that clip is skipped

### Font

- Put any bold TTF at `assets/fonts/bold.ttf`
- If missing, Pillow's built-in bitmap font is used (tiny and ugly — always supply a real font)

### Pictures / image overlays

- Any image format Pillow supports (PNG, JPG, WebP, etc.)
- Referenced in the script by path relative to `assets/` or the project root
- Scaled to fill the frame while preserving aspect ratio

## Writing scripts

Scripts live in `scripts/`. See `scripts/episode1.md` for a working example.

```
# This is a comment — ignored by the parser

[img: "pictures/intro_chart.png" 4s]       ← show image for 4 seconds

[peter] : Hey Stewie have you seen this     ← Peter speaks
[stewie] : Yes it is remarkable             ← Stewie speaks
[peter] : I know right                      ← Peter's 2nd line → peter_002.mp3
```

**Rules:**
- `[character]` names are case-insensitive and map to sprite + audio files
- Audio files are auto-matched by order: first `[peter]` line → `peter_001.mp3`, second → `peter_002.mp3`, etc.
- Image overlays display for the specified duration with no audio
- Order in the file = strict order in the video

## Whisper cache

Whisper transcription (used for word-level subtitle timing) runs once per audio file and caches the result in `cache/`. Subsequent renders are instant.

To re-transcribe a file, delete its cache entry:
```bash
rm cache/peter_001.json
```

## Monitoring progress

While a render is running, a live status file is written at `output/<job>.status.json`.

```bash
# watch live in another terminal
watch -n1 "jq '.stage, .step_label, (.percent|tostring)+\"%\"' output/episode1.status.json"

# or use the built-in viewer
python progress.py
```

Pipeline stages in order: `PARSING` → `ALIGNING` → `BACKGROUND` → `COMPOSITING` → `EXPORTING` → `DONE`

## Configuration

All tuneable values are in `config.py`. Key ones:

| Setting | Default | What it does |
|---------|---------|--------------|
| `WHISPER_MODEL` | `"base"` | Whisper model size — `tiny` is fast, `large` is accurate |
| `CHARACTER_SCALE` | `0.45` | Sprite size (fraction of frame width) |
| `CHARACTER_X_LEFT` | `80` | X position of left speaker |
| `CHARACTER_X_RIGHT` | `600` | X position of right speaker |
| `SUBTITLE_Y` | `1150` | Vertical position of subtitles |
| `SUBTITLE_HIGHLIGHT_COLOR` | `(255,220,0)` | Active word color (yellow) |
| `GRAPH_Y_CENTER` | `600` | Vertical center of image overlays |

## Project structure

| File | Role |
|------|------|
| `render.py` | Entry point — composes and exports the video |
| `config.py` | All settings, sizes, colors, paths |
| `parse.py` | Converts the `.md` script into a timeline |
| `align.py` | Runs Whisper to get per-word timestamps |
| `progress.py` | Progress tracking and status file viewer |
