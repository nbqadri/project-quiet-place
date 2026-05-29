"""
main.py – CLI entry-point for the YouTube Shorts auto-generator.

Output folder structure:
    output/
    └── yoga_music/
        ├── Yoga_Music_01.mp4
        └── uploaded/
            └── Yoga_Music_02.mp4

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
                        help='Content topic e.g. "Relaxing Yoga Music"')
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
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text[:60]


def topic_output_dir(topic: str) -> Path:
    folder = config.OUTPUT_DIR / slugify(topic)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def uploaded_dir(output_folder: Path) -> Path:
    folder = output_folder / "uploaded"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def move_to_uploaded(video_path: Path) -> Path:
    dest = uploaded_dir(video_path.parent) / video_path.name
    shutil.move(str(video_path), str(dest))
    log.info("Moved → %s", dest)
    return dest


def sanitise_filename(topic: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in topic.replace(" ", "_"))


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    topic       = args.topic.strip()
    output_dir  = topic_output_dir(topic)
    file_prefix = sanitise_filename(topic)
    img_folder  = topic_image_dir(topic)

    log.info("═" * 60)
    log.info("Topic    : %s", topic)
    log.info("Videos   : %d", args.count)
    log.info("Upload   : %s", "No" if args.no_upload else "Yes")
    log.info("Privacy  : %s", args.privacy)
    log.info("Schedule : %s", f"random {config.YOUTUBE_SCHEDULE_MIN_DAYS}–{config.YOUTUBE_SCHEDULE_MAX_DAYS} days" if config.YOUTUBE_SCHEDULE else "off (publish immediately)")
    log.info("Playlist : %s", config.YOUTUBE_PLAYLIST_ID or "not set")
    log.info("Related  : %d video(s) in pool", len(config.YOUTUBE_RELATED_VIDEO_IDS))
    log.info("Output   : %s", output_dir)
    log.info("Images   : %s", img_folder)
    log.info("═" * 60)

    # ── 0. CTA image (one per run) ────────────────────────────────────────────
    cta_image = pick_cta_image()
    log.info("CTA image  : %s", cta_image.name if cta_image else "none")

    # ── 1. Generate quotes (always fresh) ────────────────────────────────────
    log.info("Step 1 – Generating fresh quotes + titles + comments with Claude …")
    all_quotes = generate_quotes(topic)
    quotes     = all_quotes[: args.count]
    log.info("Generated %d quotes.", len(quotes))

    used_image_ids: set[str] = set()
    results: list[dict]      = []

    for idx, item in enumerate(quotes, start=1):
        quote           = item["quote"]
        attribution     = item.get("attribution", "")
        keywords        = item.get("keywords", [])
        video_title     = item.get("title", "")
        pinned_comment  = item.get("pinned_comment", "")

        log.info("")
        log.info("── Video %d/%d ──────────────────────────", idx, len(quotes))
        log.info("Title  : %s", video_title)
        log.info("Quote  : %s", quote)
        log.info("By     : %s", attribution)

        # ── 2. Images ─────────────────────────────────────────────────────────
        log.info("Step 2 – Resolving images …")
        try:
            images = fetch_images(keywords, topic, used_image_ids)
            register_used(images, used_image_ids)
        except RuntimeError as exc:
            log.error("Image fetch failed: %s – skipping video %d.", exc, idx)
            continue

        # ── 3. Music ──────────────────────────────────────────────────────────
        log.info("Step 3 – Selecting music …")
        music_path = select_track(keywords, topic)

        # ── 4. Render ─────────────────────────────────────────────────────────
        output_path = output_dir / f"{file_prefix}_{idx:02d}.mp4"
        log.info("Step 4 – Rendering → %s …", output_path.name)
        try:
            build_video(
                images, quote, attribution, music_path,
                output_path, cta_image=cta_image
            )
        except Exception as exc:
            log.error("Rendering failed for video %d: %s", idx, exc)
            continue

        # ── 5. Metadata ───────────────────────────────────────────────────────
        metadata = generate_metadata(topic, quote, video_title, idx)
        log.info("YT Title : %s", metadata["title"])

        # ── 6. Upload → playlist → comment ───────────────────────────────────
        video_id   = None
        final_path = output_path

        if not args.no_upload:
            config.YOUTUBE_PRIVACY = args.privacy
            log.info("Step 5 – Uploading …")
            video_id = upload_video(
                output_path,
                metadata["title"],
                metadata["description"],
                metadata["tags"],
                pinned_comment=pinned_comment,
            )
            if video_id:
                final_path = move_to_uploaded(output_path)

        results.append({
            "index":          idx,
            "title":          metadata["title"],
            "quote":          quote,
            "file":           str(final_path),
            "video_id":       video_id,
            "uploaded":       video_id is not None,
            "pinned_comment": pinned_comment,
        })

        if idx < len(quotes):
            time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("")
    log.info("═" * 60)
    log.info("DONE – %d/%d videos produced.", len(results), len(quotes))
    for r in results:
        yt     = f"https://youtu.be/{r['video_id']}" if r["video_id"] else "not uploaded"
        loc    = "uploaded/" + Path(r["file"]).name if r["uploaded"] else Path(r["file"]).name
        log.info("  [%02d] %s", r["index"], r["title"])
        log.info("       %s → %s", loc, yt)
    log.info("")
    log.info("Output  : %s", output_dir)
    log.info("Images  : %s", img_folder)
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
