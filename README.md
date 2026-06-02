# YouTube Shorts Auto-Generator — Calm Reflections

Automatically generate, render, and upload branded YouTube Shorts from a single topic.
Each video features an AI-generated quote, stock images, background music, a branded intro,
letter-by-letter quote reveal, and a call-to-action segment.

---

## Project Structure

```
youtube_shorts_generator/
├── main.py                   # CLI entry-point and pipeline orchestrator
├── config.py                 # All settings loaded from .env
├── claude_generator.py       # Generates quotes, titles, and pinned comments via Claude API
├── asset_fetcher.py          # Downloads and caches images from Pexels (100 per batch)
├── music_selector.py         # Matches local music tracks to topic via keyword scoring
├── video_builder.py          # FFmpeg rendering: static images + xfade + text overlays
├── youtube_uploader.py       # OAuth2 upload, playlist, scheduling, comments
├── requirements.txt
├── .env.example              # Copy to .env and fill in your keys
├── pending_comments.json     # Auto-created: stores pinned comments for scheduled videos
├── youtube_token.json        # Auto-created after first OAuth login
├── client_secrets.json       # Download from Google Cloud Console (not in repo)
│
├── assets/
│   ├── images/               # Downloaded images, one subfolder per topic
│   │   └── yoga_music/       # e.g. assets/images/yoga_music/1234567.jpg
│   ├── music/                # Your local MP3/WAV tracks from YouTube Audio Library
│   │   └── music_tags.json   # Optional: tag tracks by mood for smart matching
│   └── youtube_CTA/          # Images used as the final video segment (CTA background)
│
├── fonts/
│   └── NotoSans-Bold.ttf     # Optional: custom font (falls back to Georgia/Arial)
│
└── output/                   # Rendered MP4s, organised by topic
    └── yoga_music/
        ├── Yoga_Music_01.mp4
        └── uploaded/
            └── Yoga_Music_02.mp4   ← moved here after confirmed upload
```

---

## Requirements

| Tool | Version |
|------|---------|
| Python | 3.10+ |
| FFmpeg | 5.0+ (must be in PATH) |

---

## Installation

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install FFmpeg

**Windows:** Download from https://ffmpeg.org/download.html → add to PATH
**macOS:** `brew install ffmpeg`
**Linux:** `sudo apt install ffmpeg`

Verify: `ffmpeg -version`

### 3. Optional: Add a font

Download **NotoSans-Bold.ttf** or **Georgia.ttf** and place in `fonts/`.
Falls back to system fonts automatically (Georgia → Arial → DejaVu).

---

## API Keys & Credentials

### Anthropic Claude (required)
1. Sign up at https://console.anthropic.com/
2. Create an API key
3. Add to `.env`: `ANTHROPIC_API_KEY=sk-ant-xxx`

### Pexels (required for images)
1. Sign up at https://www.pexels.com/api/ (free)
2. Add to `.env`: `PEXELS_API_KEY=xxx`

### YouTube Data API v3 (required for upload)
1. Go to https://console.cloud.google.com/
2. Create a project → Enable **YouTube Data API v3**
3. APIs & Services → Credentials → **+ Create Credentials → OAuth 2.0 Client ID**
4. Application type: **TV and Limited Input devices** ← important
5. Download JSON → save as `client_secrets.json` in project root
6. OAuth consent screen → add scope: `https://www.googleapis.com/auth/youtube`
7. Publish the app (or add your Gmail as a test user)

---

## Environment Variables

Copy `.env.example` → `.env` and fill in:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
PEXELS_API_KEY=xxxxxxxx
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json

# Branding
BRAND_TITLE=CALM
BRAND_SUBTITLE=REFLECTIONS
CTA_TEXT=Subscribe for daily reflections

# YouTube
YOUTUBE_PLAYLIST_ID=PLq5iQVvHtVDVLjsFmZ-rqXZqtm5qBq_oJ
YOUTUBE_CHANNEL_ID=UCxxxxxxxxxxxxxxxxxxxx

# Scheduling (uploads as private, auto-publishes after random 1–10 days)
YOUTUBE_SCHEDULE=true
YOUTUBE_SCHEDULE_MIN_DAYS=1
YOUTUBE_SCHEDULE_MAX_DAYS=10

# Related videos — one is linked randomly in each video description
# Use just the video ID from the URL (the part after ?v= or youtu.be/)
YOUTUBE_RELATED_VIDEO_IDS=Ui9w4VEH3iA,xxxxxxx,yyyyyyy

# Logging
LOG_LEVEL=INFO
```

---

## Background Music

1. Download free tracks from https://www.youtube.com/audiolibrary
2. Place `.mp3` files in `assets/music/`
3. Optionally edit `assets/music/music_tags.json` to tag tracks by mood:

```json
{
  "chill_morning.mp3": ["yoga", "calm", "breathe", "meditation"],
  "epic_rise.mp3":     ["motivation", "power", "energy", "strength"]
}
```

Without tags the system matches on filenames, then picks randomly.

---

## CTA Images

Place PNG/JPG images in `assets/youtube_CTA/`.
One is picked randomly per run and used as the **final background image** during the
subscribe segment (last ~8 seconds). Design at 1080×1920px for best results.

---

## Usage

### Generate and upload videos
```bash
python main.py --topic "Yoga Music"
```

### Render only — upload later
```bash
python main.py --topic "Morning Motivation" --no-upload
```
A companion `.json` file is saved alongside each `.mp4` containing the title,
description, tags, quote, and pinned comment — ready for upload later.

### Upload already-rendered videos
```bash
python main.py --topic "Morning Motivation" --upload-only
```
Scans `output/morning_motivation/` for any unuploaded `.mp4` files, reads their
companion `.json` for metadata, uploads each one, and moves them to `uploaded/`.
No re-rendering, no Claude or Pexels API calls.

### Specify number of videos
```bash
python main.py --topic "Stoic Wisdom" --count 3
```

### Upload as unlisted (review before publishing)
```bash
python main.py --topic "Daily Affirmations" --privacy unlisted
```

### Upload already-rendered videos as private
```bash
python main.py --topic "Yoga Music" --upload-only --privacy private
```

### Post pending pinned comments (run after scheduled videos go live)
```bash
python main.py --post-comments
```

---

## Video Timeline (40 seconds)

| Time | Content |
|------|---------|
| 0s – 1s | "CALM / REFLECTIONS" fades in |
| 1s – 3.5s | Brand holds on screen |
| 3.5s – 4.5s | Brand fades out |
| 4.5s – 18s | Quote appears line-by-line (typewriter effect) |
| 18s – 30s | Full quote + attribution holds |
| 30s – 40s | CTA image appears, subscribe text fades in |
| 38.5s – 40s | Fade to black |

---

## Image Caching

Images are stored in `assets/images/<topic_slug>/` — one folder per topic.

| Scenario | Behaviour |
|----------|-----------|
| New topic | Downloads 100 images from Pexels |
| Same topic, < 30 days old | Uses cached images, skips download |
| Same topic, ≥ 30 days old | Downloads another 100 alongside existing ones |

The pool grows over time — old images are never deleted.

---

## Output Structure

```
output/
├── yoga_music/
│   ├── Yoga_Music_01.mp4       ← rendered, pending upload
│   ├── Yoga_Music_01.json      ← metadata: title, description, quote, pinned comment
│   └── uploaded/
│       ├── Yoga_Music_02.mp4   ← moved here after confirmed YouTube upload
│       └── Yoga_Music_02.json  ← companion JSON moved alongside MP4
└── morning_motivation/
    └── ...
```

Each `.json` contains:
```json
{
  "topic":          "Yoga Music",
  "title":          "Find Stillness in the Noise",
  "quote":          "The quieter you become, the more you can hear.",
  "attribution":    "— Ram Dass",
  "description":    "Full YouTube description...",
  "tags":           ["yoga", "calm", "shorts"],
  "pinned_comment": "Silence is where answers live. #CalmReflections",
  "rendered_at":    "2026-05-30T14:22:00Z",
  "uploaded":       true,
  "video_id":       "abc123xyz",
  "uploaded_at":    "2026-05-30T15:10:00Z"
}
```

---

## Scheduled Uploads & Pinned Comments

When `YOUTUBE_SCHEDULE=true`:
- Video uploads as **private** with a `publishAt` timestamp (random 1–10 days)
- YouTube automatically makes it public at that time
- Pinned comment is saved to `pending_comments.json` (can't post on private videos)
- Run `python main.py --post-comments` after videos go live to post + pin them

---

## Quota Usage (YouTube Data API v3)

| Action | Quota units |
|--------|------------|
| Upload video | 1,600 |
| Add to playlist | 50 |
| Post comment | 50 |
| Pin comment | 50 |
| **Total per video** | **~1,750** |

Free daily quota: **10,000 units** → approximately **5 videos per day**.

---

## Modules

| File | Responsibility |
|------|---------------|
| `config.py` | All settings, paths, env vars |
| `claude_generator.py` | Claude API: quote, attribution, title, keywords, pinned comment |
| `asset_fetcher.py` | Pexels download with pagination, 100-image batches, 30-day refresh |
| `music_selector.py` | Keyword scoring against music_tags.json, filename fallback, random |
| `video_builder.py` | FFmpeg filter graph: xfade transitions, drawtext overlays, audio mix |
| `youtube_uploader.py` | OAuth2 device flow, upload, playlist, scheduling, comments |
| `main.py` | CLI, pipeline orchestration, metadata JSON saving, upload-only mode |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `FFmpeg not found` | Install FFmpeg and add to PATH |
| `No images available` | Check `PEXELS_API_KEY` or add images to `assets/images/<topic>/` |
| `Font not found` warning | Add `NotoSans-Bold.ttf` to `fonts/` folder |
| YouTube 400 on auth | Make sure credential type is **TV and Limited Input devices** |
| YouTube 403 on playlist/comment | Scope must be `https://www.googleapis.com/auth/youtube` — delete `youtube_token.json` and re-auth |
| Comments 403 | Enable comments in YouTube Studio → Settings → Community |
| Pinned comment not posted | Video was scheduled — run `python main.py --post-comments` after it goes live |
| `--upload-only` skips a video | No companion `.json` found — only works for videos rendered by this tool |
| Claude JSON parse error | Increase `CLAUDE_MAX_TOKENS` in `config.py` (should be 4096) |
| Only 20 images downloaded | Old `asset_fetcher.py` — replace with latest version |

---

## License

MIT — free to use and modify.
