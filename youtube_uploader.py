"""
youtube_uploader.py – Upload MP4 videos to YouTube via the YouTube Data API v3.

Authentication flow:
  1. First run opens a browser for OAuth2 consent.
  2. Token is saved to youtube_token.json for subsequent runs.
  3. Token is refreshed automatically when expired.

Prerequisites:
  - Enable YouTube Data API v3 in Google Cloud Console.
  - Download OAuth 2.0 client credentials as client_secrets.json.
  - Set YOUTUBE_CLIENT_SECRETS_FILE in your .env (default: client_secrets.json).
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

from config import (
    YOUTUBE_CLIENT_SECRETS_FILE,
    YOUTUBE_TOKEN_FILE,
    YOUTUBE_SCOPES,
    YOUTUBE_CATEGORY_ID,
    YOUTUBE_PRIVACY,
    MAX_RETRIES,
    RETRY_DELAY,
)

log = logging.getLogger(__name__)

_OAUTH_TOKEN_URL   = "https://oauth2.googleapis.com/token"
_OAUTH_DEVICE_URL  = "https://oauth2.googleapis.com/device/code"
_UPLOAD_URL        = "https://www.googleapis.com/upload/youtube/v3/videos"
_METADATA_URL      = "https://www.googleapis.com/youtube/v3/videos"

# ─── Public API ───────────────────────────────────────────────────────────────

def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
) -> Optional[str]:
    """
    Upload *video_path* to YouTube.  Returns the YouTube video ID on success.
    Prints a warning and returns None if credentials are not configured.
    """
    secrets = _load_client_secrets()
    if not secrets:
        log.warning(
            "YouTube upload skipped – %s not found. "
            "See docs for OAuth2 setup.", YOUTUBE_CLIENT_SECRETS_FILE
        )
        return None

    token = _get_valid_token(secrets)
    if not token:
        return None

    video_id = _resumable_upload(token, video_path, title, description, tags)
    return video_id


def generate_metadata(topic: str, quote: str, index: int) -> dict:
    """Build YouTube title, description, and tags for a quote video."""
    title = f"{topic} – Inspirational Shorts #{index}"[:100]

    description = (
        f'"{quote}"\n\n'
        f"🎵 Relaxing background music to uplift your day.\n"
        f"📌 Topic: {topic}\n\n"
        f"#Shorts #Motivation #Inspiration #{topic.replace(' ', '')} "
        f"#PositiveVibes #DailyQuotes"
    )

    tags = (
        [topic]
        + topic.lower().split()
        + ["shorts", "motivation", "inspiration", "quotes", "dailyquotes",
           "positivity", "mindset", "wellness"]
    )
    # YouTube tag limit: 500 characters total, each tag ≤ 30 chars
    tags = list(dict.fromkeys(t[:30] for t in tags))[:30]

    return {"title": title, "description": description, "tags": tags}


# ─── OAuth2 helpers ───────────────────────────────────────────────────────────

def _load_client_secrets() -> Optional[dict]:
    path = Path(YOUTUBE_CLIENT_SECRETS_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # Support both "web" and "installed" credential types
        return data.get("installed") or data.get("web")
    except Exception as exc:
        log.error("Failed to parse %s: %s", YOUTUBE_CLIENT_SECRETS_FILE, exc)
        return None


def _get_valid_token(secrets: dict) -> Optional[str]:
    """Return a valid access token, refreshing or re-authorising as needed."""
    stored = _load_stored_token()

    if stored and _token_valid(stored):
        return stored["access_token"]

    if stored and stored.get("refresh_token"):
        refreshed = _refresh_token(secrets, stored["refresh_token"])
        if refreshed:
            return refreshed

    # Full device-code flow (works headlessly)
    return _device_code_flow(secrets)


def _load_stored_token() -> Optional[dict]:
    if YOUTUBE_TOKEN_FILE.exists():
        try:
            return json.loads(YOUTUBE_TOKEN_FILE.read_text())
        except Exception:
            pass
    return None


def _save_token(token_data: dict) -> None:
    YOUTUBE_TOKEN_FILE.write_text(json.dumps(token_data, indent=2))


def _token_valid(token_data: dict) -> bool:
    expires_at = token_data.get("expires_at", 0)
    return time.time() < expires_at - 60   # 60-second buffer


def _refresh_token(secrets: dict, refresh_token: str) -> Optional[str]:
    try:
        resp = requests.post(
            _OAUTH_TOKEN_URL,
            data={
                "client_id":     secrets["client_id"],
                "client_secret": secrets["client_secret"],
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        token_data = {
            "access_token":  data["access_token"],
            "refresh_token": refresh_token,
            "expires_at":    time.time() + data.get("expires_in", 3600),
        }
        _save_token(token_data)
        log.debug("Access token refreshed.")
        return data["access_token"]
    except Exception as exc:
        log.warning("Token refresh failed: %s", exc)
        return None


def _device_code_flow(secrets: dict) -> Optional[str]:
    """OAuth2 device-code flow – works in terminal / headless environments."""
    try:
        resp = requests.post(
            _OAUTH_DEVICE_URL,
            data={
                "client_id": secrets["client_id"],
                "scope":     " ".join(YOUTUBE_SCOPES),
            },
            timeout=20,

        )
        resp.raise_for_status()
        device_data = resp.json()
    except Exception as exc:
        log.error("Device code request failed: %s", exc)
        print("Status code:", resp.status_code)  # temp for debugging, remove later
        print("Response body:", resp.text) # temp for debugging, remove later
        return None

    print(
        f"\n{'─'*60}\n"
        f"YouTube OAuth2 – Open this URL in your browser:\n"
        f"  {device_data['verification_url']}\n"
        f"Enter code: {device_data['user_code']}\n"
        f"{'─'*60}\n"
    )

    interval = device_data.get("interval", 5)
    expires  = time.time() + device_data.get("expires_in", 300)

    while time.time() < expires:
        time.sleep(interval)
        try:
            resp = requests.post(
                _OAUTH_TOKEN_URL,
                data={
                    "client_id":     secrets["client_id"],
                    "client_secret": secrets["client_secret"],
                    "device_code":   device_data["device_code"],
                    "grant_type":    "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=20,
            )
            data = resp.json()
            if "access_token" in data:
                token_data = {
                    "access_token":  data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_at":    time.time() + data.get("expires_in", 3600),
                }
                _save_token(token_data)
                log.info("YouTube authorisation successful.")
                return data["access_token"]
            if data.get("error") not in ("authorization_pending", "slow_down"):
                log.error("OAuth error: %s", data)
                return None
        except Exception:
            pass

    log.error("Device code expired without user authorisation.")
    return None


# ─── Upload ───────────────────────────────────────────────────────────────────

def _resumable_upload(
    token: str,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
) -> Optional[str]:
    """Initiate a resumable upload and stream the file."""
    metadata = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus":          YOUTUBE_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }

    # Step 1 – get the upload URI
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            init_resp = requests.post(
                _UPLOAD_URL,
                headers={
                    "Authorization":   f"Bearer {token}",
                    "Content-Type":    "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(video_path.stat().st_size),
                },
                params={"uploadType": "resumable", "part": "snippet,status"},
                json=metadata,
                timeout=30,
            )
            init_resp.raise_for_status()
            upload_uri = init_resp.headers["Location"]
            break
        except Exception as exc:
            log.warning("Upload init attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                log.error("Failed to initialise upload.")
                return None

    # Step 2 – stream the file
    file_size = video_path.stat().st_size
    log.info("Uploading %s (%.1f MB) …", video_path.name, file_size / 1_048_576)

    try:
        with video_path.open("rb") as fh:
            upload_resp = requests.put(
                upload_uri,
                headers={
                    "Content-Length": str(file_size),
                    "Content-Type":   "video/mp4",
                },
                data=fh,
                timeout=600,   # 10 minutes for large files
            )
        upload_resp.raise_for_status()
        video_id = upload_resp.json().get("id", "unknown")
        log.info("Uploaded → https://youtu.be/%s", video_id)
        return video_id
    except Exception as exc:
        log.error("Upload failed: %s", exc)
        return None
