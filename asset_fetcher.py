"""
asset_fetcher.py – Download and cache images from Pexels.

Folder structure:
    assets/images/<topic_slug>/
        1234567.jpg
        8901234.jpg
        batch_meta.json   ← tracks when each batch was downloaded

Batch logic:
  - First run: download IMAGE_BATCH_SIZE (100) images
  - If most recent batch is older than IMAGE_REFRESH_DAYS (30): download another
    100 WITHOUT deleting old ones — pool just gets bigger over time
  - Each video picks IMAGES_PER_VIDEO (4) images randomly from the full pool
  - Cross-video duplicates avoided within a single run via used_ids set
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from config import (
    PEXELS_API_KEY,
    PEXELS_PHOTO_URL,
    PEXELS_PER_PAGE,
    IMAGES_DIR,
    IMAGES_PER_VIDEO,
    IMAGE_BATCH_SIZE,
    IMAGE_REFRESH_DAYS,
    MAX_RETRIES,
    RETRY_DELAY,
)

log = logging.getLogger(__name__)

_BATCH_META_FILE = "batch_meta.json"
_IMG_EXTS        = {".jpg", ".jpeg", ".png"}


# ─── Public API ───────────────────────────────────────────────────────────────

def topic_image_dir(topic: str) -> Path:
    folder = IMAGES_DIR / _slugify(topic)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch_images(
    keywords: list[str],
    topic: str,
    used_ids: set[str],
    count: int = IMAGES_PER_VIDEO,
) -> list[Path]:
    """
    Return *count* image Paths for the topic.

    Downloads a fresh batch of IMAGE_BATCH_SIZE if:
      - No images exist yet (first run)
      - Most recent batch is older than IMAGE_REFRESH_DAYS days

    Old images are NEVER deleted — the pool grows over time.
    """
    folder = topic_image_dir(topic)
    meta   = _load_meta(folder)

    # ── Decide whether to download ────────────────────────────────────────────
    existing = _images_in_folder(folder)

    if not existing:
        log.info("Topic '%s': no images yet — downloading first batch of %d.", topic, IMAGE_BATCH_SIZE)
        _download_batch(keywords, topic, folder, meta)
    elif _batch_is_stale(meta):
        age_days = _latest_batch_age_days(meta)
        log.info(
            "Topic '%s': images are %d days old (threshold: %d) — downloading fresh batch. "
            "Existing %d images kept.",
            topic, age_days, IMAGE_REFRESH_DAYS, len(existing),
        )
        _download_batch(keywords, topic, folder, meta)
    else:
        age_days = _latest_batch_age_days(meta)
        log.info(
            "Topic '%s': %d cached images (%d days old) — skipping download.",
            topic, len(existing), age_days,
        )

    # Refresh list after potential download
    existing = _images_in_folder(folder)

    if not existing:
        raise RuntimeError(
            f"No images for topic '{topic}'. Check PEXELS_API_KEY or add images to {folder}."
        )

    # ── Select images for this video ──────────────────────────────────────────
    unused = [p for p in existing if p.stem not in used_ids]

    if len(unused) < count:
        # Pool exhausted for this run — allow reuse
        log.debug("Image pool nearly exhausted; allowing reuse.")
        unused = existing

    import random
    selected = random.sample(unused, min(count, len(unused)))
    log.info("Selected %d/%d images from pool for topic '%s'", len(selected), len(existing), topic)
    return selected


def register_used(paths: list[Path], used_ids: set[str]) -> None:
    for p in paths:
        used_ids.add(p.stem)


# ─── Download ─────────────────────────────────────────────────────────────────

def _download_batch(
    keywords: list[str],
    topic: str,
    folder: Path,
    meta: dict,
) -> None:
    """Download up to IMAGE_BATCH_SIZE images into folder, skipping existing IDs."""
    existing_ids = {p.stem for p in _images_in_folder(folder)}
    queries      = _build_queries(keywords, topic)
    downloaded   = 0
    target       = IMAGE_BATCH_SIZE

    for query in queries:
        if downloaded >= target:
            break

        page = 1
        while downloaded < target:
            photos = _pexels_search(query, page)
            if not photos:
                break

            for photo in photos:
                if downloaded >= target:
                    break
                pid = str(photo["id"])
                if pid in existing_ids:
                    continue
                url  = photo["src"].get("large2x") or photo["src"].get("original")
                dest = folder / f"{pid}.jpg"
                if _download_file(url, dest):
                    existing_ids.add(pid)
                    downloaded += 1

            # Move to next page if Pexels has more results
            if len(photos) < PEXELS_PER_PAGE:
                break
            page += 1

    log.info("Downloaded %d new image(s) for topic '%s'.", downloaded, topic)

    # Record this batch timestamp
    now = datetime.now(timezone.utc).isoformat()
    if "batches" not in meta:
        meta["batches"] = []
    meta["batches"].append({"downloaded_at": now, "count": downloaded})
    _save_meta(folder, meta)


def _pexels_search(query: str, page: int = 1) -> list[dict]:
    if not PEXELS_API_KEY:
        return []
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                PEXELS_PHOTO_URL,
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "per_page": PEXELS_PER_PAGE,
                        "orientation": "portrait", "page": page},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json().get("photos", [])
        except Exception as exc:
            log.warning("Pexels attempt %d/%d for '%s': %s", attempt, MAX_RETRIES, query, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return []


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


# ─── Batch metadata ───────────────────────────────────────────────────────────

def _load_meta(folder: Path) -> dict:
    path = folder / _BATCH_META_FILE
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"batches": []}


def _save_meta(folder: Path, meta: dict) -> None:
    (folder / _BATCH_META_FILE).write_text(json.dumps(meta, indent=2))


def _batch_is_stale(meta: dict) -> bool:
    """True if the most recent batch is older than IMAGE_REFRESH_DAYS."""
    batches = meta.get("batches", [])
    if not batches:
        return True
    latest_str = batches[-1].get("downloaded_at", "")
    if not latest_str:
        return True
    try:
        latest = datetime.fromisoformat(latest_str)
        age    = (datetime.now(timezone.utc) - latest).days
        return age >= IMAGE_REFRESH_DAYS
    except Exception:
        return True


def _latest_batch_age_days(meta: dict) -> int:
    batches = meta.get("batches", [])
    if not batches:
        return 999
    try:
        latest = datetime.fromisoformat(batches[-1]["downloaded_at"])
        return (datetime.now(timezone.utc) - latest).days
    except Exception:
        return 999


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _images_in_folder(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _IMG_EXTS
    )


def _build_queries(keywords: list[str], topic: str) -> list[str]:
    queries = [topic, " ".join(keywords[:3])] + keywords[:5]
    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text[:60]
