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
PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_SECRETS_FILE: str = os.getenv(
    "YOUTUBE_CLIENT_SECRETS_FILE", "client_secrets.json"
)

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = BASE_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
MUSIC_DIR = ASSETS_DIR / "music"
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR = BASE_DIR / "fonts"
CACHE_DB = ASSETS_DIR / "cache.json"

CTA_DIR = ASSETS_DIR / "youtube_CTA"

for _dir in (IMAGES_DIR, MUSIC_DIR, OUTPUT_DIR, FONTS_DIR, CTA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ─── Claude ───────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_MAX_TOKENS = 1024
NUM_QUOTES = 9           # 8–10 quotes per run

# ─── Pexels ───────────────────────────────────────────────────────────────────
PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PEXELS_PER_PAGE = 30
IMAGES_PER_VIDEO = 4     # images used per video (Ken Burns cycle)

# ─── Video ────────────────────────────────────────────────────────────────────
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_DURATION = 40       # seconds
VIDEO_FPS = 30
MUSIC_VOLUME = 0.20       # 20 % of original volume

# Font settings – fallback to system font if custom not present
# Recommended: download a serif font e.g. PlayfairDisplay-Bold.ttf or Georgia
FONT_FILE = FONTS_DIR / "NotoSans-Bold.ttf"
FONT_SIZE = 72
FONT_COLOR = "white"
BOX_COLOR = "0x000000@0.55"   # semi-transparent black box behind text

# ─── Branding ─────────────────────────────────────────────────────────────────
BRAND_TITLE    = os.getenv("BRAND_TITLE",    "CALM")          # large title on intro card
BRAND_SUBTITLE = os.getenv("BRAND_SUBTITLE", "REFLECTIONS")   # subtitle below title
CTA_TEXT       = os.getenv("CTA_TEXT",       "Subscribe for daily reflections")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

# ─── YouTube ──────────────────────────────────────────────────────────────────
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_TOKEN_FILE = BASE_DIR / "youtube_token.json"
YOUTUBE_CATEGORY_ID = "22"   # People & Blogs (safe default)
YOUTUBE_PRIVACY = "public"   # public | private | unlisted

# ─── Retry ────────────────────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAY = 2   # seconds between retries
