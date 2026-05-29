"""
config.py – Central configuration for YouTube Shorts Generator.
All API keys, paths, and video settings are managed here.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ─── API Keys ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY: str    = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_SECRETS_FILE: str = os.getenv(
    "YOUTUBE_CLIENT_SECRETS_FILE", "client_secrets.json"
)

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.resolve()
ASSETS_DIR = BASE_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
MUSIC_DIR  = ASSETS_DIR / "music"
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR  = BASE_DIR / "fonts"
CTA_DIR    = ASSETS_DIR / "youtube_CTA"

for _dir in (IMAGES_DIR, MUSIC_DIR, OUTPUT_DIR, FONTS_DIR, CTA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ─── Claude ───────────────────────────────────────────────────────────────────
CLAUDE_MODEL      = "claude-sonnet-4-5"
CLAUDE_MAX_TOKENS = 4096
NUM_QUOTES        = 9

# ─── Pexels ───────────────────────────────────────────────────────────────────
PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PEXELS_PER_PAGE  = 30
IMAGES_PER_VIDEO = 4

# Image refresh: download a fresh batch if existing images are older than this
IMAGE_REFRESH_DAYS  = 30      # days before triggering a new download batch
IMAGE_BATCH_SIZE    = 100     # images to download per batch (initial + refresh)

# ─── Video ────────────────────────────────────────────────────────────────────
VIDEO_WIDTH    = 1080
VIDEO_HEIGHT   = 1920
VIDEO_DURATION = 40
VIDEO_FPS      = 30
MUSIC_VOLUME   = 0.20

# Font
FONT_FILE  = FONTS_DIR / "NotoSans-Bold.ttf"
FONT_SIZE  = 72
FONT_COLOR = "white"
BOX_COLOR  = "0x000000@0.55"

# ─── Branding ─────────────────────────────────────────────────────────────────
BRAND_TITLE    = os.getenv("BRAND_TITLE",    "CALM")
BRAND_SUBTITLE = os.getenv("BRAND_SUBTITLE", "REFLECTIONS")
CTA_TEXT       = os.getenv("CTA_TEXT",       "Subscribe for daily reflections")

# ─── YouTube ──────────────────────────────────────────────────────────────────
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",   # covers upload + playlist + comments
]
YOUTUBE_TOKEN_FILE          = BASE_DIR /"youtube_token.json"
YOUTUBE_CATEGORY_ID         = "22"
YOUTUBE_PRIVACY             = "public"
YOUTUBE_CHANNEL_ID          = os.getenv("YOUTUBE_CHANNEL_ID",  "")
YOUTUBE_PLAYLIST_ID         = os.getenv("YOUTUBE_PLAYLIST_ID", "")

# Schedule: upload as private, go public after a random delay of 1–10 days.
# Set YOUTUBE_SCHEDULE=true to enable. Videos are uploaded as private and
# a publishAt time is set in the future.
YOUTUBE_SCHEDULE            = os.getenv("YOUTUBE_SCHEDULE", "false").lower() == "true"
YOUTUBE_SCHEDULE_MIN_DAYS   = int(os.getenv("YOUTUBE_SCHEDULE_MIN_DAYS", "1"))
YOUTUBE_SCHEDULE_MAX_DAYS   = int(os.getenv("YOUTUBE_SCHEDULE_MAX_DAYS", "10"))

# Related videos: list of your existing YouTube video IDs to link in descriptions.
# Comma-separated in .env: YOUTUBE_RELATED_VIDEO_IDS=abc123,def456,ghi789
_related_raw                = os.getenv("YOUTUBE_RELATED_VIDEO_IDS", "")
YOUTUBE_RELATED_VIDEO_IDS: list[str] = [
    v.strip() for v in _related_raw.split(",") if v.strip()
]

# ─── Retry ────────────────────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAY = 2
