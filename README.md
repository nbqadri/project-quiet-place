# YouTube Shorts Auto-Generator — Calm Reflections

Automatically generate, render, and upload branded YouTube Shorts from a single topic.
Each video features an AI-generated quote, stock images with cross-dissolve transitions,
background music, a branded intro, letter-by-letter quote reveal, attribution, and a
call-to-action segment.

---

## Project Structure

```
youtube_shorts_generator/
├── main.py                       # CLI entry-point and pipeline orchestrator
├── config.py                     # All settings loaded from .env
├── claude_generator.py           # Generates quotes, titles, pinned comments via Claude API
├── asset_fetcher.py              # Downloads and caches images from Pexels (100 per batch)
├── music_selector.py             # Matches local music tracks to topic via keyword scoring
├── video_builder.py              # FFmpeg rendering: xfade transitions + text overlays
├── youtube_uploader.py           # OAuth2 upload, playlist, scheduling, comments
├── requirements.txt
├── .env.example                  # Copy to .env and fill in your keys
│
├── pending_comments.json         # Auto-created: stores pinned comments for scheduled videos
├── youtube_token.json            # Auto-created: upload/playlist token (device flow)
├── youtube_comment_token.json    # Auto-created: comment token (browser flow)
├── client_secrets.json           # TV & Limited Input devices credential (upload)
├── client_secrets_comments.json  # Web application credential (comments)
│
├── assets/
│   ├── images/                   # Downloaded images, one subfolder per topic
│   │   └── yoga_music/           # assets/images/yoga_music/1234567.jpg
│   ├── music/                    # Local MP3/WAV tracks from YouTube Audio Library
│   │   └── music_tags.json       # Optional: tag tracks by mood for smart matching
│   └── youtube_CTA/              # Images used as the final video segment (CTA background)
│
├── fonts/
│   └── NotoSans-Bold.ttf         # Optional: falls back to Georgia → Arial → DejaVu
│
└── output/                       # Rendered MP4s organised by topic
    └── yoga_music/
        ├── Yoga_Music_01.mp4     # Rendered video
        ├── Yoga_Music_01.json    # Companion metadata (title, description, tags, comment)
        └── uploaded/
            ├── Yoga_Music_02.mp4 # Moved here after confirmed upload
            └── Yoga_Music_02.json
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

### 3. Optional — Add a font

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

### YouTube — Two separate OAuth credentials are required

#### Credential 1 — Upload + Playlist (TV & Limited Input devices)
Used for: uploading videos, adding to playlist, scheduling

1. [console.cloud.google.com](https://console.cloud.google.com) → Enable **YouTube Data API v3**
2. APIs & Services → Credentials → **+ Create Credentials → OAuth 2.0 Client ID**
3. Application type: **TV and Limited Input devices**
4. Download JSON → save as `client_secrets.json`
5. OAuth consent screen → add scope: `https://www.googleapis.com/auth/youtube`
6. Publish the app (or add your Gmail as a test user)

#### Credential 2 — Comments (Web application)
Used for: posting and pinning comments (`youtube.force-ssl` scope is blocked in device flow)

1. Same project → **+ Create Credentials → OAuth 2.0 Client ID**
2. Application type: **Web application**
3. Authorised redirect URIs → add: `http://localhost:8080`
4. Download JSON → save as `client_secrets_comments.json`
5. OAuth consent screen → add scope: `https://www.googleapis.com/auth/youtube.force-ssl`

#### Why two credentials?
Google permanently blocks the `youtube.force-ssl` scope from the device code flow (TV credential).
The only way to obtain it is via a browser redirect, which requires a Web application credential.
Both tokens are saved locally and refresh automatically — the browser prompt is one-time only.

| Token file | Credential type | Scope | Used for |
|------------|----------------|-------|---------|
| `youtube_token.json` | TV & Limited Input | `youtube` | Upload, playlist |
| `youtube_comment_token.json` | Web application | `youtube.force-ssl` | Post + pin comments |

---

## Environment Variables

Copy `.env.example` → `.env` and fill in:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
PEXELS_API_KEY=xxxxxxxx

# YouTube credentials
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json
YOUTUBE_COMMENT_SECRETS_FILE=client_secrets_comments.json

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

# Related videos — one linked randomly in each video description
# Use just the video ID from the URL (after ?v= or youtu.be/)
YOUTUBE_RELATED_VIDEO_IDS=abc123xyz,def456uvw,ghi789rst

# Logging
LOG_LEVEL=INFO
```

---

## Background Music

1. Download free tracks from https://www.youtube.com/audiolibrary
2. Place `.mp3` files in `assets/music/`
3. Optionally tag tracks in `assets/music/music_tags.json`:

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
subscribe segment (last ~8 seconds of the video). Design at 1080×1920px for best results.

---

## Usage

### Generate and upload
```bash
python main.py --topic "Yoga Music"
```

### Render only — upload later
```bash
python main.py --topic "Morning Motivation" --no-upload
```
A companion `.json` is saved alongside each `.mp4` with all metadata ready for upload.

### Upload already-rendered videos
```bash
python main.py --topic "Morning Motivation" --upload-only
```
Reads companion `.json` files, uploads each unuploaded MP4, moves to `uploaded/`.
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

### Post pending pinned comments
```bash
python main.py --post-comments
```
Checks each pending comment against the YouTube API. Posts and pins comments for
videos that are now public. Skips videos still private/scheduled. Safe to run daily.

---

## Video Timeline (40 seconds)

| Time | Content |
|------|---------|
| 0s – 1s | "CALM / REFLECTIONS" fades in |
| 1s – 3.5s | Brand holds on screen |
| 3.5s – 4.5s | Brand fades out |
| 4.5s – 18s | Quote appears line-by-line (typewriter effect) |
| 18s – 30s | Full quote + attribution holds on screen |
| 30s – 40s | CTA image plays, subscribe text fades in |
| 38.5s – 40s | Fade to black |

Background images are completely static with smooth cross-dissolve (xfade) transitions
between them — no zoom/pan effects that cause jitter.

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

## Output & Metadata

```
output/
├── yoga_music/
│   ├── Yoga_Music_01.mp4         ← rendered, not yet uploaded
│   ├── Yoga_Music_01.json        ← companion metadata
│   └── uploaded/
│       ├── Yoga_Music_02.mp4     ← moved here after confirmed upload
│       └── Yoga_Music_02.json    ← moved alongside MP4, updated with video_id
```

Each `.json` contains everything needed for upload and post-processing:

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
- Video uploads as **private** with a `publishAt` timestamp (random 1–10 days, random hour 8am–8pm UTC)
- YouTube automatically makes it public at that time
- Pinned comment is saved to `pending_comments.json` — cannot be posted on private videos
- Run `python main.py --post-comments` after videos go live to post and pin them
- The script checks actual video status via the YouTube API — no timestamp guessing

---

## Quota Usage (YouTube Data API v3)

Free daily quota: **10,000 units** — resets at midnight Pacific Time.

| Action | Quota units |
|--------|------------|
| Upload video | 1,600 |
| Add to playlist | 50 |
| Post comment | 50 |
| Pin comment | 50 |
| **Total per video** | **~1,750** |

Approximately **5 videos per day** on the free tier.
Monitor usage: Google Cloud Console → APIs & Services → YouTube Data API v3 → Quotas.

---

## Modules

| File | Responsibility |
|------|---------------|
| `config.py` | All settings, paths, env vars — single source of truth |
| `claude_generator.py` | Claude API: quote, attribution, title, keywords, pinned comment per video |
| `asset_fetcher.py` | Pexels download with pagination, 100-image batches, 30-day refresh |
| `music_selector.py` | Keyword scoring against music_tags.json, filename fallback, random pick |
| `video_builder.py` | FFmpeg filter graph: xfade transitions, drawtext overlays, audio mix |
| `youtube_uploader.py` | Two-token OAuth, upload, playlist, scheduling, comments, pending comment check |
| `main.py` | CLI, pipeline orchestration, metadata JSON saving, upload-only mode |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `FFmpeg not found` | Install FFmpeg and add to PATH |
| `No images available` | Check `PEXELS_API_KEY` or add images to `assets/images/<topic>/` |
| `Font not found` warning | Add `NotoSans-Bold.ttf` to `fonts/` folder |
| YouTube 400 on device auth | Credential type must be **TV and Limited Input devices** for `client_secrets.json` |
| YouTube 403 on upload/playlist | Delete `youtube_token.json` and re-authenticate |
| YouTube 403 on comments | Ensure `client_secrets_comments.json` exists (Web application type) and delete `youtube_comment_token.json` to re-authenticate |
| Comments still 403 after re-auth | Revoke app access at myaccount.google.com/permissions then re-authenticate |
| `force-ssl` invalid_scope error | This scope cannot be used with device flow — always use Web application credential for comments |
| Pinned comment not posted | Video is still scheduled — run `python main.py --post-comments` after it goes live |
| `--upload-only` skips a video | No companion `.json` found — only works for videos rendered by this tool |
| Claude JSON parse error | Increase `CLAUDE_MAX_TOKENS` to 4096 in `config.py` |
| Emoji encoding error on Windows | Ensure `encoding="utf-8"` in `save_metadata` and `load_metadata` in `main.py` |
| Only 20 images downloaded | Old `asset_fetcher.py` — replace with latest version (should be 100) |

---

## License

MIT — free to use and modify.
