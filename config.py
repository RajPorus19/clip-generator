"""
config.py — Single source of truth for all project settings.
All render.py, parse.py, and align.py values come from here.
"""

# ── Output ──────────────────────────────────────────────────────────────────
RESOLUTION = (1080, 1920)   # (width, height)
FPS = 30

# ── Background ───────────────────────────────────────────────────────────────
BACKGROUND_CROP = "center"          # crop landscape gameplay to vertical center

# ── Character layout ─────────────────────────────────────────────────────────
CHARACTER_ZONE_Y = 1300             # Y anchor for character sprites (top of sprite)
CHARACTER_SCALE = 0.45              # scale factor relative to frame width
CHARACTER_X_LEFT = 80               # X position for left-side speaker
CHARACTER_X_RIGHT = 600             # X position for right-side speaker

# ── Subtitles ────────────────────────────────────────────────────────────────
SUBTITLE_Y = 60                     # Y position of subtitle text block (top of frame)
SUBTITLE_FONT = "assets/fonts/bold.ttf"
SUBTITLE_FONT_SIZE = 120
SUBTITLE_COLOR = (255, 255, 255)            # word color (white)
SUBTITLE_HIGHLIGHT_COLOR = (255, 220, 0)    # active word color (yellow)
SUBTITLE_STROKE_WIDTH = 6                   # black outline thickness in pixels
SUBTITLE_WORDS_PER_CHUNK = 3               # max words shown at once

# ── Graph / image overlays ────────────────────────────────────────────────────
GRAPH_PADDING = 60                  # horizontal padding on each side
GRAPH_Y_CENTER = 600                # vertical center of graph overlay

# ── Paths ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output/"
CACHE_DIR = "cache/"
ASSETS_DIR = "assets/"
BACKGROUNDS_DIR = "assets/backgrounds/"
CHARACTERS_DIR = "assets/characters/"
AUDIO_DIR = "assets/audio/"

# ── Audio ─────────────────────────────────────────────────────────────────────
AUDIO_EXT = "mp3"           # file extension for audio files
AUDIO_TAIL_PADDING = 0.15   # seconds of silence kept after the last spoken word

# ── Whisper ───────────────────────────────────────────────────────────────────
WHISPER_MODEL = "base"              # tiny | base | small | medium | large

# ── Voicebox TTS ──────────────────────────────────────────────────────────────
VOICEBOX_URL = "http://localhost:17493"  # base URL of the local Voicebox server
# Voice profiles are matched to characters by name — no manual mapping needed.
