"""
video_builder.py – Build a 40-second vertical YouTube Short using FFmpeg.

Pipeline per video:
  1. Scale each image to 1080×1920 (cover / crop)
  2. Apply Ken Burns (slow zoom + pan) for VIDEO_DURATION / IMAGES_PER_VIDEO seconds each
  3. Concatenate image clips
  4. Overlay centred quote text with a semi-transparent background box
  5. Add fade-in / fade-out (0.8 s each)
  6. Mix in background music at reduced volume, trimmed to VIDEO_DURATION seconds
  7. Encode as H.264 / AAC MP4
"""

import logging
import math
import subprocess
import shutil
import textwrap
from pathlib import Path
from typing import Optional

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_DURATION,
    VIDEO_FPS,
    MUSIC_VOLUME,
    FONT_FILE,
    FONT_SIZE,
    FONT_COLOR,
    BOX_COLOR,
    OUTPUT_DIR,
)

log = logging.getLogger(__name__)

FADE_DURATION = 0.8           # seconds for fade-in / fade-out
ZOOM_SPEED    = 0.0003        # Ken Burns zoom increment per frame
MAX_ZOOM      = 1.12          # max zoom factor


# ─── Public API ───────────────────────────────────────────────────────────────

def build_video(
    images: list[Path],
    quote: str,
    music: Optional[Path],
    output_path: Path,
) -> Path:
    """
    Render a single 40-second Short and write it to *output_path*.
    Returns the output Path on success, raises on failure.
    """
    ffmpeg = _require_ffmpeg()

    seg_duration = VIDEO_DURATION / len(images)

    # Build complex filtergraph
    filter_complex, n_streams = _build_filter(images, quote, seg_duration)

    cmd = _build_command(
        ffmpeg=ffmpeg,
        images=images,
        music=music,
        filter_complex=filter_complex,
        n_image_streams=n_streams,
        output_path=output_path,
    )

    log.debug("FFmpeg command:\n%s", " ".join(str(a) for a in cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("FFmpeg stderr:\n%s", result.stderr[-3000:])
        raise RuntimeError(f"FFmpeg failed (exit {result.returncode}). See logs above.")

    log.info("Video written → %s", output_path)
    return output_path


# ─── FFmpeg command assembly ──────────────────────────────────────────────────

def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise EnvironmentError(
            "FFmpeg not found in PATH. Install it: https://ffmpeg.org/download.html"
        )
    return path


def _build_filter(
    images: list[Path],
    quote: str,
    seg_duration: float,
) -> tuple[str, int]:
    """
    Build the -filter_complex string.
    Returns (filter_str, number_of_image_inputs).
    """
    parts: list[str] = []
    seg_frames = int(seg_duration * VIDEO_FPS)

    # 1. Per-image: scale → Ken Burns → trim
    for i, _ in enumerate(images):
        # Alternate zoom direction for variety
        if i % 2 == 0:
            zoom_expr = f"min(1+{ZOOM_SPEED}*on,{MAX_ZOOM})"
            x_expr = f"iw/2-(iw/zoom/2)"
            y_expr = f"ih/2-(ih/zoom/2)"
        else:
            zoom_expr = f"min(1+{ZOOM_SPEED}*on,{MAX_ZOOM})"
            x_expr = f"iw/2-(iw/zoom/2)+{0.03}*iw*(on/{seg_frames})"
            y_expr = f"ih/2-(ih/zoom/2)"

        parts.append(
            f"[{i}:v]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
            f":d={seg_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
            f"trim=duration={seg_duration:.3f},"
            f"setpts=PTS-STARTPTS"
            f"[v{i}];"
        )

    # 2. Concatenate image segments
    concat_inputs = "".join(f"[v{i}]" for i in range(len(images)))
    parts.append(
        f"{concat_inputs}concat=n={len(images)}:v=1:a=0[base];"
    )

    # 3. Fade-in / fade-out on video
    parts.append(
        f"[base]"
        f"fade=t=in:st=0:d={FADE_DURATION},"
        f"fade=t=out:st={VIDEO_DURATION - FADE_DURATION:.3f}:d={FADE_DURATION}"
        f"[faded];"
    )

    # 4. Quote text overlay with background box
    safe_quote = _escape_ffmpeg_text(quote)
    wrapped   = _wrap_quote(quote)
    safe_wrapped = _escape_ffmpeg_text(wrapped)

    box_h = FONT_SIZE * (wrapped.count("\n") + 1) * 1.6
    box_y = f"(h-{int(box_h)})/2"

    parts.append(
        f"[faded]"
        f"drawbox=x=0:y={box_y}:w=iw:h={int(box_h)}"
        f":color={BOX_COLOR}:t=fill,"
        f"drawtext=text='{safe_wrapped}'"
        f":fontfile='{_font_path()}':"
        f"fontsize={FONT_SIZE}:fontcolor={FONT_COLOR}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:"
        f"line_spacing=18:"
        f"shadowcolor=black@0.7:shadowx=2:shadowy=2"
        f"[out]"
    )

    return "\n".join(parts), len(images)


def _build_command(
    ffmpeg: str,
    images: list[Path],
    music: Optional[Path],
    filter_complex: str,
    n_image_streams: int,
    output_path: Path,
) -> list:
    cmd: list = [ffmpeg, "-y"]

    # Image inputs (loop each so zoompan has enough frames)
    for img in images:
        cmd += ["-loop", "1", "-i", str(img)]

    # Music input
    has_music = music and music.exists()
    if has_music:
        cmd += ["-i", str(music)]

    cmd += ["-filter_complex", filter_complex]

    # Map video
    cmd += ["-map", "[out]"]

    # Map + process audio
    if has_music:
        audio_idx = n_image_streams   # 0-based index of the music input
        cmd += [
            "-map", f"{audio_idx}:a",
            "-af",
            f"afade=t=in:st=0:d={FADE_DURATION},"
            f"afade=t=out:st={VIDEO_DURATION - FADE_DURATION:.3f}:d={FADE_DURATION},"
            f"volume={MUSIC_VOLUME},"
            f"atrim=duration={VIDEO_DURATION}",
        ]

    cmd += [
        "-t", str(VIDEO_DURATION),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-r", str(VIDEO_FPS),
        "-movflags", "+faststart",
    ]

    if has_music:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]

    cmd.append(str(output_path))
    return cmd


# ─── Text helpers ─────────────────────────────────────────────────────────────

def _wrap_quote(quote: str, width: int = 28) -> str:
    """Wrap quote to fit within the video width."""
    return "\n".join(textwrap.wrap(quote, width=width))


def _escape_ffmpeg_text(text: str) -> str:
    """Escape characters special to FFmpeg drawtext."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\u2019")   # replace straight apostrophe with curly
        .replace(":",  "\\:")
        .replace(",",  "\\,")
    )


def _font_path() -> str:
    """Return a font path that FFmpeg can use, falling back to a system font."""
    if FONT_FILE.exists():
        return str(FONT_FILE)

    # Common system font fallbacks
    fallbacks = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",           # macOS
        "C:/Windows/Fonts/arialbd.ttf",                  # Windows
    ]
    for fb in fallbacks:
        if Path(fb).exists():
            return fb

    # Last resort – let FFmpeg use its default (may not render on all systems)
    log.warning(
        "No font found. Download NotoSans-Bold.ttf to %s for best results.", FONT_FILE
    )
    return ""
