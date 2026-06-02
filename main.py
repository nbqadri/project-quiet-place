"""
main.py – CLI entry-point for the YouTube Shorts auto-generator.

Usage:
  python main.py --topic "Yoga Music"                  # generate + upload
  python main.py --topic "Yoga Music" --no-upload      # render only
  python main.py --topic "Yoga Music" --upload-only    # upload already-rendered videos
  python main.py --post-comments                       # post pending pinned comments

Output folder structure:
    output/
    └── yoga_music/
        ├── Yoga_Music_01.mp4        ← rendered video
        ├── Yoga_Music_01.json       ← metadata saved at render time
        └── uploaded/
            ├── Yoga_Music_02.mp4    ← moved here after confirmed upload
            └── Yoga_Music_02.json   ← moved alongside the MP4
"""

import argparse
import json
import logging
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from claude_generator import generate_quotes
from asset_fetcher import fetch_images, register_used, topic_image_dir
from music_selector import select_track
from video_builder import build_video, pick_cta_image
from youtube_uploader import upload_video, generate_metadata, post_pending_comments

log = logging.getLogger(__name__)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and upload YouTube Shorts from a topic.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", "-t", required=False, default=None,
                        help='Content topic e.g. "Relaxing Yoga Music"')
    parser.add_argument("--count", "-n", type=int, default=config.NUM_QUOTES,
                        help="Number of videos to generate")
    parser.add_argument("--no-upload", action="store_true",
                        help="Render videos only — skip YouTube upload")
    parser.add_argument("--upload-only", action="store_true",
                        help="Upload already-rendered videos from output/<topic>/ without re-rendering")
    parser.add_argument("--privacy", choices=["public", "private", "unlisted"],
                        default=config.YOUTUBE_PRIVACY,
                        help="YouTube video privacy setting")
    parser.add_argument("--post-comments", action="store_true",
                        help="Post pending pinned comments for videos that are now live")
    return parser.parse_args()


# ─── Path helpers ─────────────────────────────────────────────────────────────

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


def sanitise_filename(topic: str) -> str:
    return "".join(
        c if c.isalnum() or c == "_" else "_"
        for c in topic.replace(" ", "_")
    )


# ─── Metadata JSON helpers ─────────────────────────────────────────────────────

def metadata_path(video_path: Path) -> Path:
    """Return the companion JSON path for a given MP4 path."""
    return video_path.with_suffix(".json")


def save_metadata(video_path: Path, data: dict) -> None:
    """Save metadata JSON alongside the rendered MP4."""
    path = metadata_path(video_path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.debug("Metadata saved → %s", path.name)


def load_metadata(video_path: Path) -> dict:
    """Load companion JSON for a video. Returns empty dict if missing."""
    path = metadata_path(video_path)
    if not path.exists():
        log.warning("No metadata file found for %s", video_path.name)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Failed to read %s: %s", path.name, exc)
        return {}


def move_to_uploaded(video_path: Path) -> Path:
    """Move MP4 and its companion JSON to the uploaded/ subfolder."""
    dest_folder = uploaded_dir(video_path.parent)

    # Move MP4
    dest_mp4 = dest_folder / video_path.name
    shutil.move(str(video_path), str(dest_mp4))

    # Move JSON if it exists
    src_json = metadata_path(video_path)
    if src_json.exists():
        dest_json = metadata_path(dest_mp4)
        shutil.move(str(src_json), str(dest_json))

    log.info("Moved → %s", dest_mp4)
    return dest_mp4


# ─── Upload-only pipeline ─────────────────────────────────────────────────────

def run_upload_only(args: argparse.Namespace) -> None:
    """
    Upload already-rendered MP4s from output/<topic>/.

    Reads the companion .json file for each MP4 to get title, description,
    tags, and pinned comment. Skips any video already in uploaded/ subfolder.
    """
    topic      = args.topic.strip()
    output_dir = topic_output_dir(topic)
    config.YOUTUBE_PRIVACY = args.privacy

    # Find all unuploaded MP4s (not inside uploaded/ subfolder)
    mp4_files = sorted(
        p for p in output_dir.iterdir()
        if p.suffix.lower() == ".mp4" and p.is_file()
    )

    if not mp4_files:
        log.info("No unuploaded MP4s found in %s", output_dir)
        return

    log.info("═" * 60)
    log.info("Topic       : %s", topic)
    log.info("Mode        : upload-only")
    log.info("Privacy     : %s", args.privacy)
    log.info("Playlist    : %s", config.YOUTUBE_PLAYLIST_ID or "not set")
    log.info("Found       : %d video(s) to upload", len(mp4_files))
    log.info("═" * 60)

    results = []
    for video_path in mp4_files:
        log.info("")
        log.info("── %s ──", video_path.name)

        # Load saved metadata
        meta = load_metadata(video_path)
        if not meta:
            log.warning("Skipping %s — no metadata file found.", video_path.name)
            log.warning("Only videos rendered by this tool have companion metadata.")
            continue

        log.info("Title   : %s", meta.get("title", ""))
        log.info("Quote   : %s", meta.get("quote", ""))

        video_id   = None
        final_path = video_path

        video_id = upload_video(
            video_path,
            meta.get("title", ""),
            meta.get("description", ""),
            meta.get("tags", []),
            pinned_comment=meta.get("pinned_comment", ""),
        )

        if video_id:
            # Update metadata with upload info
            meta["uploaded"]    = True
            meta["video_id"]    = video_id
            meta["uploaded_at"] = datetime.now(timezone.utc).isoformat()
            save_metadata(video_path, meta)

            # Move to uploaded/
            final_path = move_to_uploaded(video_path)

        results.append({
            "file":     video_path.name,
            "title":    meta.get("title", ""),
            "video_id": video_id,
            "uploaded": video_id is not None,
        })

        time.sleep(1)

    # Summary
    log.info("")
    log.info("═" * 60)
    log.info("DONE – %d/%d uploaded.", sum(1 for r in results if r["uploaded"]), len(results))
    for r in results:
        yt = f"https://youtu.be/{r['video_id']}" if r["video_id"] else "failed"
        loc = f"uploaded/{r['file']}" if r["uploaded"] else r["file"]
        log.info("  %s → %s", loc, yt)
    log.info("═" * 60)


# ─── Main pipeline ────────────────────────────────────────────────────────────

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
    log.info("Schedule : %s",
             f"random {config.YOUTUBE_SCHEDULE_MIN_DAYS}–{config.YOUTUBE_SCHEDULE_MAX_DAYS} days"
             if config.YOUTUBE_SCHEDULE else "off (publish immediately)")
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
        quote          = item["quote"]
        attribution    = item.get("attribution", "")
        keywords       = item.get("keywords", [])
        video_title    = item.get("title", "")
        pinned_comment = item.get("pinned_comment", "")

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

        # ── 5. Build and save metadata alongside the MP4 ─────────────────────
        metadata = generate_metadata(topic, quote, video_title, idx)
        meta_record = {
            "topic":          topic,
            "title":          metadata["title"],
            "quote":          quote,
            "attribution":    attribution,
            "description":    metadata["description"],
            "tags":           metadata["tags"],
            "pinned_comment": pinned_comment,
            "rendered_at":    datetime.now(timezone.utc).isoformat(),
            "uploaded":       False,
            "video_id":       None,
            "uploaded_at":    None,
        }
        save_metadata(output_path, meta_record)
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
                # Update metadata with upload confirmation
                meta_record["uploaded"]    = True
                meta_record["video_id"]    = video_id
                meta_record["uploaded_at"] = datetime.now(timezone.utc).isoformat()
                save_metadata(output_path, meta_record)

                final_path = move_to_uploaded(output_path)

        results.append({
            "index":    idx,
            "title":    metadata["title"],
            "quote":    quote,
            "file":     str(final_path),
            "video_id": video_id,
            "uploaded": video_id is not None,
        })

        if idx < len(quotes):
            time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("")
    log.info("═" * 60)
    log.info("DONE – %d/%d videos produced.", len(results), len(quotes))
    for r in results:
        yt  = f"https://youtu.be/{r['video_id']}" if r["video_id"] else "not uploaded"
        loc = "uploaded/" + Path(r["file"]).name if r["uploaded"] else Path(r["file"]).name
        log.info("  [%02d] %s", r["index"], r["title"])
        log.info("       %s → %s", loc, yt)
    log.info("")
    log.info("Output  : %s", output_dir)
    log.info("Images  : %s", img_folder)
    log.info("═" * 60)


# ─── Entry-point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        args = parse_args()

        if args.post_comments:
            post_pending_comments()

        elif args.upload_only:
            if not args.topic:
                print("error: --topic is required with --upload-only")
                sys.exit(1)
            run_upload_only(args)

        else:
            if not args.topic:
                print("error: --topic is required unless using --post-comments")
                sys.exit(1)
            run(args)

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        log.exception("Unhandled error: %s", exc)
        sys.exit(1)
