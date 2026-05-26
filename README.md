# YouTube Shorts Auto-Generator

Automatically generate and upload vertical YouTube Shorts videos from a single topic.  
Each video features an AI-generated inspirational quote, stock images with Ken Burns animation, and background music.

---

## Project Structure

```
youtube_shorts_generator/
├── main.py                  # CLI entry-point & pipeline orchestrator
├── config.py                # All settings, paths, and env-var loading
├── claude_generator.py      # Generate quotes via Claude API
├── asset_fetcher.py         # Download & cache images from Pexels
├── music_selector.py        # Keyword-based music track matching
├── video_builder.py         # FFmpeg video rendering (Ken Burns, text, audio)
├── youtube_uploader.py      # OAuth2 upload to YouTube Data API v3
├── requirements.txt
├── .env.example             # Copy → .env and fill in your keys
├── assets/
│   ├── images/              # Auto-populated image cache
│   └── music/               # ← Place your MP3/WAV files here
│       └── music_tags.json  # Optional: tag tracks by mood/keyword
├── fonts/
│   └── NotoSans-Bold.ttf    # Optional: custom font for quote text
└── output/                  # Rendered MP4 files land here
```

---

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ | |
| FFmpeg | 5.0+ | Must be in system PATH |
| pip packages | see `requirements.txt` | `pip install -r requirements.txt` |

---

## Installation

### 1. Clone / copy the project

```bash
git clone <your-repo>
cd youtube_shorts_generator
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install FFmpeg

**macOS (Homebrew)**
```bash
brew install ffmpeg
```

**Ubuntu / Debian**
```bash
sudo apt update && sudo apt install -y ffmpeg
```

**Windows**  
Download from https://ffmpeg.org/download.html and add `ffmpeg.exe` to your PATH.

Verify:
```bash
ffmpeg -version
```

### 4. Add a font (recommended)

Download **NotoSans-Bold.ttf** (free, Google Fonts) and place it in `fonts/`.

```bash
# Linux quick install
sudo apt install fonts-noto
cp /usr/share/fonts/truetype/noto/NotoSans-Bold.ttf fonts/
```

If no font is found the system falls back to DejaVu or a platform default.

---

## API Keys & Credentials

### Anthropic Claude (required for quote generation)

1. Sign up at https://console.anthropic.com/
2. Create an API key
3. Add to `.env`:  `ANTHROPIC_API_KEY=sk-ant-xxx…`

### Pexels (required for images)

1. Sign up at https://www.pexels.com/api/ (free tier is generous)
2. Copy your API key
3. Add to `.env`:  `PEXELS_API_KEY=xxx…`

### YouTube Data API v3 (optional – required for upload)

1. Go to https://console.cloud.google.com/
2. Create / select a project → **Enable YouTube Data API v3**
3. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
4. Application type: **Desktop app** (or TV & Limited Input Device for headless)
5. Download the JSON → save as `client_secrets.json` in the project root
6. Add to `.env`:  `YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json`

First upload will open a browser (or print a device-code URL for headless servers)  
for one-time authorisation.  The token is then cached in `youtube_token.json`.

---

## Environment Variables

Copy `.env.example` → `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PEXELS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json
LOG_LEVEL=INFO
```

---

## Background Music

1. Download free tracks from [YouTube Audio Library](https://www.youtube.com/audiolibrary)
2. Place `.mp3` (or `.wav`, `.m4a`) files in `assets/music/`
3. **Optional**: Edit `assets/music/music_tags.json` to tag each track with  
   mood/keyword arrays for smarter matching:

```json
{
  "chill_morning.mp3": ["yoga", "calm", "breathe", "meditation"]
}
```

Without tags the system matches on filenames, then picks randomly.

---

## Run

### Basic usage (render + upload)

```bash
python main.py --topic "Relaxing Yoga Music"
```

### Render only (no YouTube upload)

```bash
python main.py --topic "Morning Motivation" --no-upload
```

### Custom number of videos

```bash
python main.py --topic "Stoic Wisdom" --count 5
```

### Upload as private (review before publishing)

```bash
python main.py --topic "Daily Affirmations" --privacy private
```

### Custom output directory

```bash
python main.py --topic "Nature Sounds" --output-dir ~/Desktop/shorts
```

### All options

```
usage: main.py [-h] --topic TOPIC [--count COUNT] [--no-upload]
               [--privacy {public,private,unlisted}] [--output-dir OUTPUT_DIR]
```

---

## Output

```
output/
├── Relaxing_Yoga_Music_01.mp4   ← quote 1
├── Relaxing_Yoga_Music_02.mp4   ← quote 2
…
└── Relaxing_Yoga_Music_09.mp4
```

Each video:
- **Resolution**: 1080×1920 (9:16 vertical)
- **Duration**: exactly 40 seconds
- **Video**: H.264 / CRF 22 / fast preset
- **Audio**: AAC 192 kbps at 20% volume
- **Effects**: Ken Burns zoom/pan, 0.8 s fade-in/out, text shadow + contrast box

---

## Modules at a Glance

| Module | Responsibility |
|--------|---------------|
| `config.py` | Single source of truth for all settings; loads `.env` |
| `claude_generator.py` | Calls Claude Messages API to generate N quote+keyword pairs |
| `asset_fetcher.py` | Searches Pexels, downloads images, maintains a local cache to avoid duplicates |
| `music_selector.py` | Scores local tracks against keywords via `music_tags.json` or filename; falls back to random |
| `video_builder.py` | Constructs an FFmpeg `filter_complex` for Ken Burns, text overlay, fades, and audio mix |
| `youtube_uploader.py` | Handles OAuth2 device-code flow, token refresh, and resumable MP4 upload |
| `main.py` | CLI parser, pipeline orchestrator, summary logger |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `FFmpeg not found` | Install FFmpeg and ensure it's in PATH |
| `No images available` | Check your `PEXELS_API_KEY` or add images manually to `assets/images/` |
| `Font not found` warning | Download `NotoSans-Bold.ttf` to `fonts/` |
| YouTube auth loop | Delete `youtube_token.json` and re-authenticate |
| Claude quota exceeded | Check your Anthropic account; the built-in fallback quotes will be used |
| Video encoding errors | Run with `LOG_LEVEL=DEBUG` to see the full FFmpeg command |

---

## License

MIT – free to use and modify.
