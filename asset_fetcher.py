"""
asset_fetcher.py – Download and cache images from Pexels.

Images are cached in /assets/images using a content-addressed filename derived
from the Pexels photo ID.  A lightweight JSON cache index prevents re-downloading
the same asset across runs.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
import hashlib

import requests

from config import (
    PEXELS_API_KEY,
    PEXELS_PHOTO_URL,
    PEXELS_PER_PAGE,
    IMAGES_DIR,
    IMAGES_PER_VIDEO,
    CACHE_DB,
    MAX_RETRIES,
    RETRY_DELAY,
)

log = logging.getLogger(__name__)

# ─── Cache helpers ────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_DB.exists():
        try:
            return json.loads(CACHE_DB.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_DB.write_text(json.dumps(cache, indent=2))


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_images(
    keywords: list[str],
    topic: str,
    used_ids: set[str],
    count: int = IMAGES_PER_VIDEO,
) -> list[Path]:
    """
    Return *count* image Paths for the given keywords, avoiding IDs in *used_ids*.
    Falls back to cached assets if Pexels is unavailable.
    """
    cache = _load_cache()
    query = _build_query(keywords, topic)
    images: list[Path] = []

    if PEXELS_API_KEY:
        images = _fetch_from_pexels(query, used_ids, count, cache)
    
    # If we couldn't get enough online, pad from cache
    if len(images) < count:
        cached_extras = _images_from_cache(cache, used_ids, count - len(images))
        images.extend(cached_extras)

    # Last resort – use any image already on disk
    if not images:
        images = _images_from_disk(used_ids, count)

    if not images:
        raise RuntimeError(
            f"No images available for query '{query}'. "
            "Add images manually to assets/images/ or set PEXELS_API_KEY."
        )

    log.info("Resolved %d image(s) for query '%s'", len(images), query)
    return images[:count]


def register_used(paths: list[Path], used_ids: set[str]) -> None:
    """Record newly used image file stems so future videos avoid duplicates."""
    for p in paths:
        used_ids.add(p.stem)


# ─── Internals ────────────────────────────────────────────────────────────────

def _build_query(keywords: list[str], topic: str) -> str:
    parts = [topic] + keywords[:3]
    return " ".join(dict.fromkeys(parts))   # deduplicate while preserving order


def _fetch_from_pexels(
    query: str,
    used_ids: set[str],
    count: int,
    cache: dict,
) -> list[Path]:
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": PEXELS_PER_PAGE,
        "orientation": "portrait",
    }

    photos = []
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                PEXELS_PHOTO_URL, headers=headers, params=params, timeout=20
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            break
        except Exception as exc:
            log.warning("Pexels attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    paths: list[Path] = []
    for photo in photos:
        if len(paths) >= count:
            break
        pid = str(photo["id"])
        if pid in used_ids:
            continue

        dest = IMAGES_DIR / f"{pid}.jpg"
        if dest.exists():
            cache[pid] = str(dest)
            paths.append(dest)
            used_ids.add(pid)
            continue

        # Download
        url = photo["src"].get("large2x") or photo["src"].get("original")
        downloaded = _download_file(url, dest)
        if downloaded:
            cache[pid] = str(dest)
            paths.append(dest)
            used_ids.add(pid)

    _save_cache(cache)
    return paths


def _download_file(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        log.debug("Downloaded %s → %s", url, dest.name)
        return True
    except Exception as exc:
        log.warning("Failed to download %s: %s", url, exc)
        return False


def _images_from_cache(cache: dict, used_ids: set[str], count: int) -> list[Path]:
    paths = []
    for pid, path_str in cache.items():
        if pid in used_ids:
            continue
        p = Path(path_str)
        if p.exists():
            paths.append(p)
            used_ids.add(pid)
        if len(paths) >= count:
            break
    return paths


def _images_from_disk(used_ids: set[str], count: int) -> list[Path]:
    """Return any .jpg/.png files found in IMAGES_DIR not already used."""
    paths = []
    for p in IMAGES_DIR.iterdir():
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and p.stem not in used_ids:
            paths.append(p)
            used_ids.add(p.stem)
        if len(paths) >= count:
            break
    return paths
