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
    YOUTUBE_COMMENT_SECRETS_FILE,
    YOUTUBE_TOKEN_FILE,
    YOUTUBE_SCOPES,
    YOUTUBE_COMMENT_SCOPES,
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
    # If video is scheduled (private), comments can't be posted until it goes live.
    # Save to pending_comments.json and post later via --post-comments flag.
    if pinned_comment:
        if publish_at:
            _save_pending_comment(video_id, pinned_comment, publish_at)
            log.info(
                "Comment saved to pending_comments.json – post after %s when video goes live.",
                publish_at.strftime("%Y-%m-%d %H:%M UTC"),
            )
        else:
            comment_token = _get_comment_token()
            if comment_token:
                comment_id = _post_comment(comment_token, video_id, pinned_comment)
                if comment_id:
                    _pin_comment(comment_token, comment_id)
            else:
                log.warning("Comment token unavailable — comment not posted for %s.", video_id)

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


# ─── Comment token (browser flow, Web application credential) ────────────────

_COMMENT_TOKEN_FILE = None   # set lazily from config

def _comment_token_file() -> "Path":
    from config import BASE_DIR
    return BASE_DIR / "youtube_comment_token.json"


def _load_comment_secrets() -> Optional[dict]:
    path = Path(YOUTUBE_COMMENT_SECRETS_FILE)
    if not path.exists():
        log.warning(
            "Comment secrets file '%s' not found. "
            "Create a Web application OAuth credential and download it as '%s'. "
            "See README for instructions.",
            YOUTUBE_COMMENT_SECRETS_FILE,
            YOUTUBE_COMMENT_SECRETS_FILE,
        )
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("web") or data.get("installed")
    except Exception as exc:
        log.error("Failed to parse %s: %s", YOUTUBE_COMMENT_SECRETS_FILE, exc)
        return None


def _get_comment_token() -> Optional[str]:
    """
    Get a valid access token for comment operations.
    Uses a separate Web application credential + browser-based auth flow
    because youtube.force-ssl scope is not available in the device code flow.
    """
    token_file = _comment_token_file()

    # Try stored comment token first
    if token_file.exists():
        try:
            stored = json.loads(token_file.read_text())
            if time.time() < stored.get("expires_at", 0) - 60:
                return stored["access_token"]
            # Try refresh
            if stored.get("refresh_token"):
                secrets = _load_comment_secrets()
                if secrets:
                    refreshed = _refresh_comment_token(secrets, stored["refresh_token"])
                    if refreshed:
                        return refreshed
        except Exception:
            pass

    # Full browser auth
    secrets = _load_comment_secrets()
    if not secrets:
        return None
    return _browser_auth_flow(secrets)


def _refresh_comment_token(secrets: dict, refresh_token: str) -> Optional[str]:
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
        token_data = {
            "access_token":  data["access_token"],
            "refresh_token": refresh_token,
            "expires_at":    time.time() + data.get("expires_in", 3600),
        }
        _comment_token_file().write_text(json.dumps(token_data, indent=2))
        log.debug("Comment token refreshed.")
        return data["access_token"]
    except Exception as exc:
        log.warning("Comment token refresh failed: %s", exc)
        return None


def _browser_auth_flow(secrets: dict) -> Optional[str]:
    """
    Standard OAuth2 browser redirect flow for Web application credentials.
    Opens a browser, captures the redirect on localhost:8080.
    Used only for comment tokens (youtube.force-ssl scope).
    """
    import socket
    import threading
    import webbrowser
    import urllib.parse

    redirect_uri = "http://localhost:8080"
    scope        = " ".join(YOUTUBE_COMMENT_SCOPES)

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={urllib.parse.quote(secrets['client_id'])}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(scope)}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    auth_code: list[str] = []

    def _handle(conn: socket.socket) -> None:
        try:
            data = conn.recv(4096).decode("utf-8", errors="ignore")
            for line in data.splitlines():
                if line.startswith("GET "):
                    qs     = line.split(" ")[1].lstrip("/?")
                    params = urllib.parse.parse_qs(qs)
                    if "code" in params:
                        auth_code.append(params["code"][0])
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
                b"<html><body><h2>Comment auth successful!</h2>"
                b"<p>You can close this tab.</p></body></html>"
            )
        except Exception:
            pass
        finally:
            conn.close()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("localhost", 8080))
    except OSError:
        log.error("Port 8080 in use — close other applications and retry.")
        return None
    server.listen(1)
    server.settimeout(120)

    print("\n" + "─"*60)
    print("Comment OAuth – opening browser for one-time authorisation...")
    print("If browser does not open, visit this URL manually:")
    print(f"  {auth_url}")
    print("─"*60 + "\n")

    webbrowser.open(auth_url)

    try:
        conn, _ = server.accept()
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()
        for _ in range(50):
            if auth_code:
                break
            time.sleep(0.1)
    except socket.timeout:
        log.error("Timed out waiting for browser auth (2 min limit).")
        return None
    finally:
        server.close()

    if not auth_code:
        log.error("No auth code received.")
        return None

    # Exchange code for tokens
    try:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "code":          auth_code[0],
                "client_id":     secrets["client_id"],
                "client_secret": secrets["client_secret"],
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        token_data = {
            "access_token":  data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at":    time.time() + data.get("expires_in", 3600),
        }
        _comment_token_file().write_text(json.dumps(token_data, indent=2))
        log.info("Comment token saved to youtube_comment_token.json")
        return data["access_token"]
    except Exception as exc:
        log.error("Comment token exchange failed: %s", exc)
        return None


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
    # Request scopes for device code — youtube.force-ssl must be combined with youtube
    # (requesting force-ssl alone causes invalid_scope 400)
    device_scopes = " ".join(YOUTUBE_SCOPES)
    try:
        resp = requests.post(
            _DEVICE_URL,
            data={
                "client_id": secrets["client_id"],
                "scope":     device_scopes,
            },
            timeout=20,
        )
        if resp.status_code == 400 and "invalid_scope" in resp.text:
            # Fallback: request only the base youtube scope for device code
            log.warning("Full scope request rejected — falling back to base youtube scope for device auth.")
            resp = requests.post(
                _DEVICE_URL,
                data={
                    "client_id": secrets["client_id"],
                    "scope":     "https://www.googleapis.com/auth/youtube",
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


# ─── Pending comments ────────────────────────────────────────────────────────

from config import BASE_DIR as _BASE_DIR
_PENDING_FILE = _BASE_DIR / "pending_comments.json"


def _save_pending_comment(
    video_id: str,
    comment: str,
    publish_at: datetime,
) -> None:
    """Append a comment to pending_comments.json for later posting."""
    existing = []
    if _PENDING_FILE.exists():
        try:
            existing = json.loads(_PENDING_FILE.read_text())
        except Exception:
            pass
    existing.append({
        "video_id":   video_id,
        "comment":    comment,
        "publish_at": publish_at.isoformat(),
        "posted":     False,
    })
    _PENDING_FILE.write_text(json.dumps(existing, indent=2))
    log.debug("Pending comment saved for video %s", video_id)


def post_pending_comments() -> None:
    """
    Read pending_comments.json and post any comments whose video is now public.

    Uses the YouTube API to check actual video status rather than comparing
    timestamps — so it works even if YouTube published the video early or late.
    Call this via:  python main.py --post-comments
    """
    if not _PENDING_FILE.exists():
        log.info("No pending_comments.json found — nothing to post.")
        return

    entries = json.loads(_PENDING_FILE.read_text())
    pending = [e for e in entries if not e.get("posted")]

    if not pending:
        log.info("No pending comments to post.")
        return

    log.info("Checking %d pending comment(s) …", len(pending))

    secrets = _load_client_secrets()
    if not secrets:
        log.error("client_secrets.json not found — cannot post comments.")
        return

    token = _get_valid_token(secrets)
    if not token:
        return

    posted_count  = 0
    skipped_count = 0

    for entry in entries:
        if entry.get("posted"):
            continue

        video_id = entry["video_id"]
        status   = _get_video_status(token, video_id)

        if status is None:
            log.warning("Could not fetch status for video %s — skipping.", video_id)
            skipped_count += 1
            continue

        if status != "public":
            log.info(
                "Video %s is '%s' (not yet public) — skipping.",
                video_id, status,
            )
            skipped_count += 1
            continue

        log.info("Video %s is public — posting comment …", video_id)
        comment_token = _get_comment_token()
        if not comment_token:
            log.error("Could not get comment token — skipping comment for %s.", video_id)
            skipped_count += 1
            continue
        comment_id = _post_comment(comment_token, video_id, entry["comment"])
        if comment_id:
            _pin_comment(comment_token, comment_id)
            entry["posted"] = True
            posted_count += 1
        else:
            skipped_count += 1

    _PENDING_FILE.write_text(json.dumps(entries, indent=2))
    log.info(
        "Done — posted: %d, still pending: %d.",
        posted_count, skipped_count,
    )


def _get_video_status(token: str, video_id: str) -> Optional[str]:
    """
    Fetch the privacyStatus of a video via the YouTube API.
    Returns 'public', 'private', 'unlisted', or None on error.
    """
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            headers={"Authorization": f"Bearer {token}"},
            params={"part": "status", "id": video_id},
            timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            log.warning("Video %s not found in YouTube API response.", video_id)
            return None
        return items[0]["status"]["privacyStatus"]
    except Exception as exc:
        log.warning("Could not fetch status for video %s: %s", video_id, exc)
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
