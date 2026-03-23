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
SUBTITLE_Y = 1150                   # Y position of subtitle text block
SUBTITLE_FONT = "assets/fonts/bold.ttf"
SUBTITLE_FONT_SIZE = 72
SUBTITLE_COLOR = (255, 255, 255)            # inactive word color (white)
SUBTITLE_HIGHLIGHT_COLOR = (255, 220, 0)    # active word color (yellow)
SUBTITLE_MAX_WIDTH = 960                    # max px width before wrapping
SUBTITLE_BG_ALPHA = 160                     # 0-255 alpha for background rect
SUBTITLE_BG_PADDING = 20                    # px padding around text block
SUBTITLE_LINE_SPACING = 10                  # extra px between wrapped lines

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

# ── Whisper ───────────────────────────────────────────────────────────────────
WHISPER_MODEL = "base"              # tiny | base | small | medium | large
