"""
asset_fetcher.py – Download and cache images from Pexels.

Folder structure:
    assets/images/<topic_slug>/   ← one folder per topic
        1234567.jpg
        8901234.jpg
        ...

If a topic folder already exists and has enough images, downloads are skipped.
Quotes are always freshly generated (handled in claude_generator.py).
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests

from config import (
    PEXELS_API_KEY,
    PEXELS_PHOTO_URL,
    PEXELS_PER_PAGE,
    IMAGES_DIR,
    IMAGES_PER_VIDEO,
    MAX_RETRIES,
    RETRY_DELAY,
)

log = logging.getLogger(__name__)

# Minimum images we want cached per topic before skipping download
MIN_IMAGES_PER_TOPIC = 20


# ─── Public API ───────────────────────────────────────────────────────────────

def topic_image_dir(topic: str) -> Path:
    """Return (and create) the image subfolder for this topic."""
    slug = _slugify(topic)
    folder = IMAGES_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch_images(
    keywords: list[str],
    topic: str,
    used_ids: set[str],
    count: int = IMAGES_PER_VIDEO,
) -> list[Path]:
    """
    Return *count* image Paths for the given topic.

    - If the topic folder already has >= MIN_IMAGES_PER_TOPIC images, skip download.
    - Otherwise fetch from Pexels and save into assets/images/<topic_slug>/.
    - Always avoids IDs already used in this run (used_ids).
    """
    folder = topic_image_dir(topic)
    existing = _images_in_folder(folder)

    if len(existing) >= MIN_IMAGES_PER_TOPIC:
        log.info(
            "Topic '%s' already has %d cached images – skipping download.",
            topic, len(existing),
        )
    else:
        if PEXELS_API_KEY:
            log.info(
                "Topic '%s' has %d images (need %d) – fetching from Pexels …",
                topic, len(existing), MIN_IMAGES_PER_TOPIC,
            )
            _fetch_from_pexels(keywords, topic, folder, existing)
            existing = _images_in_folder(folder)   # refresh after download
        else:
            log.warning("PEXELS_API_KEY not set – using whatever is cached.")

    # Pick *count* images not already used this run
    selected = _pick_unused(existing, used_ids, count)

    # If still short, allow reuse from the folder (different video same topic)
    if len(selected) < count:
        log.debug("Not enough unused images; allowing reuse from topic folder.")
        selected = _pick_any(existing, count)

    if not selected:
        raise RuntimeError(
            f"No images available for topic '{topic}'. "
            f"Check your PEXELS_API_KEY or add images manually to {folder}."
        )

    log.info("Selected %d image(s) from %s", len(selected), folder)
    return selected[:count]


def register_used(paths: list[Path], used_ids: set[str]) -> None:
    """Record file stems so future videos in this run avoid duplicates."""
    for p in paths:
        used_ids.add(p.stem)


# ─── Pexels fetch ─────────────────────────────────────────────────────────────

def _fetch_from_pexels(
    keywords: list[str],
    topic: str,
    folder: Path,
    existing: list[Path],
) -> None:
    existing_ids = {p.stem for p in existing}
    needed = MIN_IMAGES_PER_TOPIC - len(existing)
    downloaded = 0

    # Try topic first, then individual keywords as fallback queries
    queries = [topic] + [" ".join(keywords[:3])] + keywords[:5]
    queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))

    for query in queries:
        if downloaded >= needed:
            break

        headers = {"Authorization": PEXELS_API_KEY}
        params  = {"query": query, "per_page": PEXELS_PER_PAGE, "orientation": "portrait"}

        photos = []
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(PEXELS_PHOTO_URL, headers=headers, params=params, timeout=20)
                resp.raise_for_status()
                photos = resp.json().get("photos", [])
                break
            except Exception as exc:
                log.warning("Pexels attempt %d/%d for '%s': %s", attempt, MAX_RETRIES, query, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        for photo in photos:
            if downloaded >= needed:
                break
            pid = str(photo["id"])
            if pid in existing_ids:
                continue
            url  = photo["src"].get("large2x") or photo["src"].get("original")
            dest = folder / f"{pid}.jpg"
            if _download_file(url, dest):
                existing_ids.add(pid)
                downloaded += 1

    log.info("Downloaded %d new image(s) for topic '%s'.", downloaded, topic)


def _download_file(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        log.debug("  ↓ %s", dest.name)
        return True
    except Exception as exc:
        log.warning("Download failed %s: %s", url, exc)
        return False


# ─── Selection helpers ────────────────────────────────────────────────────────

def _images_in_folder(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )


def _pick_unused(images: list[Path], used_ids: set[str], count: int) -> list[Path]:
    return [p for p in images if p.stem not in used_ids][:count]


def _pick_any(images: list[Path], count: int) -> list[Path]:
    """Return up to *count* images, cycling if necessary."""
    if not images:
        return []
    result = []
    while len(result) < count:
        result.extend(images)
    return result[:count]


# ─── Slug helper ──────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert a topic string to a safe folder name: 'Yoga Music' → 'yoga_music'."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text[:60]   # cap length for Windows path limits
