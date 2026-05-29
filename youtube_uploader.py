"""
youtube_uploader.py – Upload MP4 videos to YouTube via the YouTube Data API v3.

Post-upload actions:
  1. Add video to playlist        (YOUTUBE_PLAYLIST_ID)
  2. Post + pin a comment         (pinned_comment text)
  3. Schedule go-live             (YOUTUBE_SCHEDULE=true, random 1–10 days)

Quota cost per video:
  Upload          : 1,600 units
  Playlist insert :    50 units
  Post comment    :    50 units
  Pin comment     :    50 units
  Total           : ~1,750 units  (≈5 videos/day on free tier)
"""

import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from config import (
    YOUTUBE_CLIENT_SECRETS_FILE,
    YOUTUBE_TOKEN_FILE,
    YOUTUBE_SCOPES,
    YOUTUBE_CATEGORY_ID,
    YOUTUBE_PRIVACY,
    YOUTUBE_PLAYLIST_ID,
    YOUTUBE_SCHEDULE,
    YOUTUBE_SCHEDULE_MIN_DAYS,
    YOUTUBE_SCHEDULE_MAX_DAYS,
    YOUTUBE_RELATED_VIDEO_IDS,
    MAX_RETRIES,
    RETRY_DELAY,
)

log = logging.getLogger(__name__)

_TOKEN_URL    = "https://oauth2.googleapis.com/token"
_DEVICE_URL   = "https://oauth2.googleapis.com/device/code"
_UPLOAD_URL   = "https://www.googleapis.com/upload/youtube/v3/videos"
_PLAYLIST_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
_COMMENT_URL  = "https://www.googleapis.com/youtube/v3/commentThreads"
_MODERATE_URL = "https://www.googleapis.com/youtube/v3/comments"


# ─── Public API ───────────────────────────────────────────────────────────────

def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    pinned_comment: str = "",
) -> Optional[str]:
    """
    Upload video, schedule it, add to playlist, post + pin comment.
    Returns YouTube video ID on success, None on failure.
    """
    secrets = _load_client_secrets()
    if not secrets:
        log.warning("YouTube upload skipped – %s not found.", YOUTUBE_CLIENT_SECRETS_FILE)
        return None

    token = _get_valid_token(secrets)
    if not token:
        return None

    # Determine publish time
    publish_at, days_offset = _schedule_publish_time()

    # 1. Upload
    video_id = _resumable_upload(
        token, video_path, title, description, tags, publish_at
    )
    if not video_id:
        return None

    if publish_at:
        log.info(
            "Scheduled to go public in %d day(s) on %s",
            days_offset,
            publish_at.strftime("%Y-%m-%d %H:%M UTC"),
        )

    # 2. Add to playlist
    if YOUTUBE_PLAYLIST_ID:
        _add_to_playlist(token, video_id, YOUTUBE_PLAYLIST_ID)

    # 3. Post + pin comment
    if pinned_comment:
        comment_id = _post_comment(token, video_id, pinned_comment)
        if comment_id:
            _pin_comment(token, comment_id)

    return video_id


def generate_metadata(
    topic: str,
    quote: str,
    title: str,
    index: int,
) -> dict:
    """Build YouTube title, description, and tags."""
    yt_title = (title or f"{topic} – Inspirational Shorts #{index}")[:100]

    # Pick a related video to link (random each time)
    related_line = ""
    if YOUTUBE_RELATED_VIDEO_IDS:
        vid = random.choice(YOUTUBE_RELATED_VIDEO_IDS)
        related_line = f"\n▶ Watch this next → https://youtu.be/{vid}\n"

    description = (
        f'"{quote}"\n\n'
        f"🎵 Calm background music to uplift your day.\n"
        f"📌 Topic: {topic}\n"
        f"{related_line}\n"
        f"#Shorts #Motivation #Inspiration #{topic.replace(' ', '')} "
        f"#PositiveVibes #DailyQuotes #CalmReflections"
    )

    tags = (
        [topic]
        + topic.lower().split()
        + ["shorts", "motivation", "inspiration", "quotes", "dailyquotes",
           "positivity", "mindset", "wellness", "calmreflections"]
    )
    tags = list(dict.fromkeys(t[:30] for t in tags))[:30]

    return {"title": yt_title, "description": description, "tags": tags}


# ─── Scheduling ───────────────────────────────────────────────────────────────

def _schedule_publish_time() -> tuple[Optional[datetime], int]:
    if not YOUTUBE_SCHEDULE:
        return None, 0

    days   = random.randint(YOUTUBE_SCHEDULE_MIN_DAYS, YOUTUBE_SCHEDULE_MAX_DAYS)
    hour   = random.randint(8, 20)
    minute = random.choice([0, 15, 30, 45])

    publish_at = (
        datetime.now(timezone.utc) + timedelta(days=days)
    ).replace(hour=hour, minute=minute, second=0, microsecond=0)

    return publish_at, days


# ─── Playlist ─────────────────────────────────────────────────────────────────

def _add_to_playlist(token: str, video_id: str, playlist_id: str) -> bool:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                _PLAYLIST_URL,
                headers=headers,
                params={"part": "snippet"},
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            log.info("Added to playlist %s", playlist_id)
            return True
        except Exception as exc:
            log.warning("Playlist insert attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    log.error("Failed to add video %s to playlist.", video_id)
    return False


# ─── Comments ─────────────────────────────────────────────────────────────────

def _post_comment(token: str, video_id: str, text: str) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {"snippet": {"textOriginal": text}},
        }
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                _COMMENT_URL,
                headers=headers,
                params={"part": "snippet"},
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            comment_id = resp.json()["snippet"]["topLevelComment"]["id"]
            log.info("Comment posted (id: %s)", comment_id)
            return comment_id
        except Exception as exc:
            log.warning("Comment post attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    log.error("Failed to post comment on video %s.", video_id)
    return None


def _pin_comment(token: str, comment_id: str) -> bool:
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                _MODERATE_URL + "/setModerationStatus",
                headers=headers,
                params={
                    "id":               comment_id,
                    "moderationStatus": "published",
                    "banOnReject":      False,
                },
                timeout=20,
            )
            if resp.status_code in (200, 204):
                log.info("Comment pinned.")
                return True
            resp.raise_for_status()
        except Exception as exc:
            log.warning("Pin attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    log.error("Failed to pin comment %s.", comment_id)
    return False


# ─── OAuth2 ───────────────────────────────────────────────────────────────────

def _load_client_secrets() -> Optional[dict]:
    path = Path(YOUTUBE_CLIENT_SECRETS_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("installed") or data.get("web")
    except Exception as exc:
        log.error("Failed to parse %s: %s", YOUTUBE_CLIENT_SECRETS_FILE, exc)
        return None


def _get_valid_token(secrets: dict) -> Optional[str]:
    stored = _load_stored_token()
    if stored and _token_valid(stored):
        return stored["access_token"]
    if stored and stored.get("refresh_token"):
        refreshed = _refresh_token(secrets, stored["refresh_token"])
        if refreshed:
            return refreshed
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
    return time.time() < token_data.get("expires_at", 0) - 60


def _refresh_token(secrets: dict, refresh_token: str) -> Optional[str]:
    try:
        resp = requests.post(
            _TOKEN_URL,
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
        _save_token({
            "access_token":  data["access_token"],
            "refresh_token": refresh_token,
            "expires_at":    time.time() + data.get("expires_in", 3600),
        })
        log.debug("Access token refreshed.")
        return data["access_token"]
    except Exception as exc:
        log.warning("Token refresh failed: %s", exc)
        return None


def _device_code_flow(secrets: dict) -> Optional[str]:
    """
    OAuth2 device code flow — works with 'TV and Limited Input devices' credentials.
    Prints a URL and short code; user visits google.com/device and enters the code.
    """
    try:
        resp = requests.post(
            _DEVICE_URL,
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
                _TOKEN_URL,
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
                _save_token({
                    "access_token":  data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_at":    time.time() + data.get("expires_in", 3600),
                })
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
    publish_at: Optional[datetime] = None,
) -> Optional[str]:
    if publish_at:
        status_body: dict = {
            "privacyStatus":           "private",
            "publishAt":               publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "selfDeclaredMadeForKids": False,
        }
    else:
        status_body = {
            "privacyStatus":           YOUTUBE_PRIVACY,
            "selfDeclaredMadeForKids": False,
        }

    metadata = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  YOUTUBE_CATEGORY_ID,
        },
        "status": status_body,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            init_resp = requests.post(
                _UPLOAD_URL,
                headers={
                    "Authorization":           f"Bearer {token}",
                    "Content-Type":            "application/json; charset=UTF-8",
                    "X-Upload-Content-Type":   "video/mp4",
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
                timeout=600,
            )
        upload_resp.raise_for_status()
        video_id = upload_resp.json().get("id", "unknown")
        log.info("Uploaded → https://youtu.be/%s", video_id)
        return video_id
    except Exception as exc:
        log.error("Upload failed: %s", exc)
        return None
