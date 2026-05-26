"""
main.py – CLI entry-point for the YouTube Shorts auto-generator.

Usage:
  python main.py --topic "Relaxing Yoga Music"
  python main.py --topic "Morning Motivation" --no-upload
  python main.py --topic "Stoic Wisdom" --count 5 --privacy private
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Import project modules (config first so logging is initialised)
import config  # noqa: F401 — side-effect: configures logging
from claude_generator import generate_quotes
from asset_fetcher import fetch_images, register_used
from music_selector import select_track
from video_builder import build_video
from youtube_uploader import upload_video, generate_metadata

log = logging.getLogger(__name__)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and upload YouTube Shorts from a topic.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--topic", "-t",
        required=True,
        help='Content topic, e.g. "Relaxing Yoga Music"',
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=config.NUM_QUOTES,
        help="Number of videos to generate",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip YouTube upload (render only)",
    )
    parser.add_argument(
        "--privacy",
        choices=["public", "private", "unlisted"],
        default=config.YOUTUBE_PRIVACY,
        help="YouTube video privacy setting",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=config.OUTPUT_DIR,
        help="Directory for rendered MP4 files",
    )
    return parser.parse_args()


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def sanitise_filename(topic: str) -> str:
    """Convert topic to a safe filename prefix."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in topic.replace(" ", "_"))


def run(args: argparse.Namespace) -> None:
    topic      = args.topic.strip()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    file_prefix = sanitise_filename(topic)

    log.info("═" * 60)
    log.info("Topic    : %s", topic)
    log.info("Videos   : %d", args.count)
    log.info("Upload   : %s", "No" if args.no_upload else "Yes")
    log.info("Privacy  : %s", args.privacy)
    log.info("Output   : %s", output_dir)
    log.info("═" * 60)

    # ── 1. Generate quotes ────────────────────────────────────────────────────
    log.info("Step 1/4 – Generating quotes with Claude …")
    all_quotes = generate_quotes(topic)
    quotes = all_quotes[: args.count]
    log.info("Using %d quotes.", len(quotes))

    used_image_ids: set[str] = set()   # track downloaded images across videos
    results: list[dict] = []

    for idx, item in enumerate(quotes, start=1):
        quote    = item["quote"]
        keywords = item.get("keywords", [])

        log.info("")
        log.info("── Video %d/%d ──────────────────────────", idx, len(quotes))
        log.info("Quote: %s", quote)

        # ── 2. Fetch images ───────────────────────────────────────────────────
        log.info("Step 2 – Fetching images …")
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
        log.info("Step 4 – Rendering video → %s …", output_path.name)
        try:
            build_video(images, quote, music_path, output_path)
        except Exception as exc:
            log.error("Video rendering failed for video %d: %s", idx, exc)
            continue

        # ── 5. Generate metadata ──────────────────────────────────────────────
        metadata = generate_metadata(topic, quote, idx)
        log.info("Title: %s", metadata["title"])

        # ── 6. Upload to YouTube ──────────────────────────────────────────────
        video_id = None
        if not args.no_upload:
            log.info("Step 5 – Uploading to YouTube …")
            # Override privacy if CLI flag differs from config default
            import config as _cfg
            _cfg.YOUTUBE_PRIVACY = args.privacy

            video_id = upload_video(
                output_path,
                metadata["title"],
                metadata["description"],
                metadata["tags"],
            )

        results.append(
            {
                "index":     idx,
                "quote":     quote,
                "file":      str(output_path),
                "video_id":  video_id,
                "metadata":  metadata,
            }
        )

        # Small pause between videos to avoid hammering APIs
        if idx < len(quotes):
            time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("")
    log.info("═" * 60)
    log.info("DONE – %d/%d videos produced.", len(results), len(quotes))
    for r in results:
        yt_link = (
            f"https://youtu.be/{r['video_id']}" if r["video_id"] else "not uploaded"
        )
        log.info("  [%02d] %s | %s", r["index"], Path(r["file"]).name, yt_link)
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
