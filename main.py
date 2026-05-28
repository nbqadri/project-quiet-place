"""
main.py – CLI entry-point for the YouTube Shorts auto-generator.

Output folder structure:
    output/
    └── yoga_music/           ← rendered videos (topic subfolder)
        ├── Yoga_Music_01.mp4
        ├── Yoga_Music_02.mp4
        └── uploaded/         ← moved here after successful YouTube upload
            └── Yoga_Music_01.mp4

Usage:
  python main.py --topic "Relaxing Yoga Music"
  python main.py --topic "Morning Motivation" --no-upload
  python main.py --topic "Stoic Wisdom" --count 5 --privacy private
"""

import argparse
import logging
import re
import shutil
import sys
import time
from pathlib import Path

import config
from claude_generator import generate_quotes
from asset_fetcher import fetch_images, register_used, topic_image_dir
from music_selector import select_track
from video_builder import build_video, pick_cta_image
from youtube_uploader import upload_video, generate_metadata

log = logging.getLogger(__name__)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and upload YouTube Shorts from a topic.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", "-t", required=True,
                        help='Content topic, e.g. "Relaxing Yoga Music"')
    parser.add_argument("--count", "-n", type=int, default=config.NUM_QUOTES,
                        help="Number of videos to generate")
    parser.add_argument("--no-upload", action="store_true",
                        help="Skip YouTube upload (render only)")
    parser.add_argument("--privacy", choices=["public", "private", "unlisted"],
                        default=config.YOUTUBE_PRIVACY,
                        help="YouTube video privacy setting")
    return parser.parse_args()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """'Yoga Music' → 'yoga_music'"""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text[:60]


def topic_output_dir(base: Path, topic: str) -> Path:
    """Return output/<topic_slug>/ and create it."""
    folder = base / slugify(topic)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def uploaded_dir(output_folder: Path) -> Path:
    """Return output/<topic_slug>/uploaded/ and create it."""
    folder = output_folder / "uploaded"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def move_to_uploaded(video_path: Path) -> Path:
    """Move a rendered video into the uploaded/ subfolder."""
    dest_folder = uploaded_dir(video_path.parent)
    dest = dest_folder / video_path.name
    shutil.move(str(video_path), str(dest))
    log.info("Moved → %s", dest)
    return dest


def sanitise_filename(topic: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in topic.replace(" ", "_"))


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    topic       = args.topic.strip()
    output_dir  = topic_output_dir(config.OUTPUT_DIR, topic)
    file_prefix = sanitise_filename(topic)
    img_folder  = topic_image_dir(topic)

    log.info("═" * 60)
    log.info("Topic    : %s", topic)
    log.info("Videos   : %d", args.count)
    log.info("Upload   : %s", "No" if args.no_upload else "Yes")
    log.info("Privacy  : %s", args.privacy)
    log.info("Output   : %s", output_dir)
    log.info("Images   : %s", img_folder)
    log.info("═" * 60)

    # ── 0. Pick CTA image once per run (shared across all videos) ───────────
    cta_image = pick_cta_image()
    if cta_image:
        log.info("CTA image  : %s", cta_image.name)
    else:
        log.info("CTA image  : none (text-only CTA)")

    # ── 1. Generate quotes (always fresh) ────────────────────────────────────
    log.info("Step 1/4 – Generating fresh quotes with Claude …")
    all_quotes = generate_quotes(topic)
    quotes = all_quotes[: args.count]
    log.info("Generated %d quotes.", len(quotes))

    used_image_ids: set[str] = set()
    results: list[dict] = []

    for idx, item in enumerate(quotes, start=1):
        quote    = item["quote"]
        keywords = item.get("keywords", [])

        log.info("")
        log.info("── Video %d/%d ──────────────────────────", idx, len(quotes))
        log.info("Quote: %s", quote)

        # ── 2. Fetch / use cached images ─────────────────────────────────────
        log.info("Step 2 – Resolving images …")
        try:
            images = fetch_images(keywords, topic, used_image_ids)
            register_used(images, used_image_ids)
        except RuntimeError as exc:
            log.error("Image fetch failed: %s – skipping video %d.", exc, idx)
            continue

        # ── 3. Select music ───────────────────────────────────────────────────
        log.info("Step 3 – Selecting music track …")
        music_path = select_track(keywords, topic)

        # ── 4. Render video ───────────────────────────────────────────────────
        output_path = output_dir / f"{file_prefix}_{idx:02d}.mp4"
        log.info("Step 4 – Rendering → %s …", output_path.name)
        try:
            build_video(images, quote, item.get("attribution", ""), music_path, output_path, cta_image=cta_image)
        except Exception as exc:
            log.error("Rendering failed for video %d: %s", idx, exc)
            continue

        # ── 5. Metadata ───────────────────────────────────────────────────────
        metadata = generate_metadata(topic, quote, idx)
        log.info("Title: %s", metadata["title"])

        # ── 6. Upload & move ──────────────────────────────────────────────────
        video_id     = None
        final_path   = output_path

        if not args.no_upload:
            log.info("Step 5 – Uploading to YouTube …")
            config.YOUTUBE_PRIVACY = args.privacy
            video_id = upload_video(
                output_path,
                metadata["title"],
                metadata["description"],
                metadata["tags"],
            )
            if video_id:
                # Move to uploaded/ subfolder only on confirmed upload
                final_path = move_to_uploaded(output_path)

        results.append({
            "index":      idx,
            "quote":      quote,
            "file":       str(final_path),
            "video_id":   video_id,
            "uploaded":   video_id is not None,
            "metadata":   metadata,
        })

        if idx < len(quotes):
            time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("")
    log.info("═" * 60)
    log.info("DONE – %d/%d videos produced.", len(results), len(quotes))
    for r in results:
        status = f"https://youtu.be/{r['video_id']}" if r["video_id"] else "not uploaded"
        location = "uploaded/" + Path(r["file"]).name if r["uploaded"] else Path(r["file"]).name
        log.info("  [%02d] %s → %s", r["index"], location, status)
    log.info("")
    log.info("Output folder : %s", output_dir)
    log.info("Image cache   : %s", img_folder)
    log.info("═" * 60)


# ─── Entry-point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        log.exception("Unhandled error: %s", exc)
        sys.exit(1)
