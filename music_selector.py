"""
music_selector.py – Match a local music track to the current topic/quote.

Music files live in /assets/music.  You can optionally create a metadata sidecar
file (music_tags.json) to associate moods/keywords with each track.  Without the
sidecar the selector falls back to keyword matching on the filename itself, and
ultimately to a random pick.

Example music_tags.json structure (place in /assets/music/):
{
  "chill_vibes.mp3":    ["calm", "chill", "meditation", "yoga", "relax"],
  "epic_rise.mp3":      ["motivation", "power", "energy", "strength"],
  "morning_light.mp3":  ["morning", "peaceful", "nature", "breathe"]
}
"""

import json
import logging
import random
from pathlib import Path
from typing import Optional

from config import MUSIC_DIR

log = logging.getLogger(__name__)

_SUPPORTED_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}
_TAGS_FILE = MUSIC_DIR / "music_tags.json"


# ─── Public API ───────────────────────────────────────────────────────────────

def select_track(keywords: list[str], topic: str) -> Optional[Path]:
    """
    Return the best-matching music track Path for the given keywords + topic.

    Matching priority:
      1. Scored match against music_tags.json (if present)
      2. Keyword match against track filenames
      3. Random pick from available tracks
      4. None if /assets/music is empty (caller must handle gracefully)
    """
    tracks = _available_tracks()
    if not tracks:
        log.warning("No music tracks found in %s – video will have no background music.", MUSIC_DIR)
        return None

    search_terms = _normalise_terms(keywords, topic)

    # 1. Sidecar metadata match
    track = _match_via_tags(tracks, search_terms)
    if track:
        log.info("Music (tags match): %s", track.name)
        return track

    # 2. Filename keyword match
    track = _match_via_filename(tracks, search_terms)
    if track:
        log.info("Music (filename match): %s", track.name)
        return track

    # 3. Random fallback
    track = random.choice(tracks)
    log.info("Music (random fallback): %s", track.name)
    return track


# ─── Internals ────────────────────────────────────────────────────────────────

def _available_tracks() -> list[Path]:
    return [
        p for p in MUSIC_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
    ]


def _normalise_terms(keywords: list[str], topic: str) -> set[str]:
    terms: set[str] = set()
    for word in [topic] + keywords:
        for part in word.lower().split():
            terms.add(part.strip(".,!?\"'"))
    return terms


def _load_tags() -> dict[str, list[str]]:
    if _TAGS_FILE.exists():
        try:
            return json.loads(_TAGS_FILE.read_text())
        except Exception as exc:
            log.debug("Could not load music_tags.json: %s", exc)
    return {}


def _match_via_tags(tracks: list[Path], terms: set[str]) -> Optional[Path]:
    tags = _load_tags()
    if not tags:
        return None

    best_path: Optional[Path] = None
    best_score = 0

    track_map = {t.name: t for t in tracks}

    for filename, tag_list in tags.items():
        if filename not in track_map:
            continue
        score = len(terms & {t.lower() for t in tag_list})
        if score > best_score:
            best_score = score
            best_path = track_map[filename]

    return best_path if best_score > 0 else None


def _match_via_filename(tracks: list[Path], terms: set[str]) -> Optional[Path]:
    best_path: Optional[Path] = None
    best_score = 0

    for track in tracks:
        stem_words = set(track.stem.lower().replace("-", " ").replace("_", " ").split())
        score = len(terms & stem_words)
        if score > best_score:
            best_score = score
            best_path = track

    return best_path if best_score > 0 else None
