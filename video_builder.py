"""
video_builder.py – Build a 40-second vertical YouTube Short.

Timeline:
  0s   – 4.5s  : Branded intro "CALM / REFLECTIONS" fades in, holds, fades out
  4.5s – 18s   : Quote reveals line-by-line (fast typewriter)
  18s  – 30s   : Full quote + attribution hold on screen
  30s  – 40s   : CTA image (from assets/youtube_CTA/) plays as the final
                 background image with Ken Burns, subscribe text overlaid
  38.5s– 40s   : Fade to black

CTA image is simply the last segment in the image sequence — no overlay
complexity, same Ken Burns treatment as every other image.
"""

import logging
import random
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
    OUTPUT_DIR,
    BRAND_TITLE,
    BRAND_SUBTITLE,
    CTA_TEXT,
    CTA_DIR,
)

log = logging.getLogger(__name__)

# ── Timeline (seconds) ────────────────────────────────────────────────────────
INTRO_FADE_IN   = 1.0
INTRO_HOLD      = 2.5
INTRO_FADE_OUT  = 1.0
INTRO_END       = INTRO_FADE_IN + INTRO_HOLD + INTRO_FADE_OUT   # 4.5s

QUOTE_START     = INTRO_END          # 4.5s
QUOTE_REVEAL    = 13.5               # seconds to type out all lines
CTA_START       = 30.0               # when CTA text fades in
VIDEO_FADE_OUT  = 1.5

# ── Visual ────────────────────────────────────────────────────────────────────
TITLE_FONT_SIZE = 110
SUBTITLE_SIZE   = 38
QUOTE_FONT_SIZE = 62
ATTR_FONT_SIZE  = 40
CTA_FONT_SIZE   = 34

ZOOM_SPEED = 0.0003
MAX_ZOOM   = 1.12

_CTA_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ─── Public API ───────────────────────────────────────────────────────────────

def pick_cta_image() -> Optional[Path]:
    """Randomly select one image from assets/youtube_CTA/, or None if empty."""
    candidates = [
        p for p in CTA_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _CTA_EXTS
    ]
    if not candidates:
        log.warning(
            "No CTA images found in %s – last background image will be reused. "
            "Add PNG/JPG files there to show a custom CTA background.", CTA_DIR
        )
        return None
    chosen = random.choice(candidates)
    log.info("CTA image selected: %s", chosen.name)
    return chosen


def build_video(
    images: list[Path],
    quote: str,
    attribution: str,
    music: Optional[Path],
    output_path: Path,
    cta_image: Optional[Path] = None,
) -> Path:
    """
    Render a 40-second Short.

    The CTA image (if provided) is appended as the final image segment so it
    plays naturally during the subscribe phase — no overlay, no compositing.

    Args:
        images      : Ken Burns background images (typically 4)
        quote       : Main quote text
        attribution : e.g. "— Rumi"
        music       : Background track (or None)
        output_path : Destination MP4
        cta_image   : Image from assets/youtube_CTA/ used as final segment
    """
    ffmpeg = _require_ffmpeg()
    font   = _font_path()

    # Build the full image sequence: regular images + CTA as last frame
    all_images = _build_image_sequence(images, cta_image)

    filter_complex = _build_filter(all_images, quote, attribution, font)
    cmd = _build_command(ffmpeg, all_images, music, filter_complex, output_path)

    log.debug("FFmpeg cmd:\n%s", " \\\n  ".join(str(a) for a in cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("FFmpeg stderr:\n%s", result.stderr[-4000:])
        raise RuntimeError(f"FFmpeg failed (exit {result.returncode}).")

    log.info("Video written → %s", output_path)
    return output_path


# ─── Image sequence builder ───────────────────────────────────────────────────

def _build_image_sequence(
    images: list[Path],
    cta_image: Optional[Path],
) -> list[Path]:
    """
    Return the full ordered image list for the video.

    Strategy:
      - The CTA image gets roughly the last 10 seconds (CTA_START → VIDEO_DURATION)
      - Remaining images share the earlier portion equally
      - If no CTA image, all images share the full duration as before
    """
    if cta_image is None or not cta_image.exists():
        return list(images)

    # Each segment gets equal time: VIDEO_DURATION / total_segments
    # We want CTA to cover ~10s and regular images ~30s.
    # With 4 regular images and 40s total:
    #   seg_dur = 40 / total_segments
    #   cta_slots * seg_dur ≈ 10  →  cta_slots ≈ total_segments / 4
    # Easiest: fix total segments, derive cta_slots from ratio
    n_other    = len(images)
    # Start with n_other regular slots, compute how many CTA slots to add
    # so CTA covers CTA_START → VIDEO_DURATION
    # seg_dur = VIDEO_DURATION / (n_other + cta_slots)
    # cta_slots * seg_dur = VIDEO_DURATION - CTA_START
    # → cta_slots = n_other * (VIDEO_DURATION - CTA_START) / CTA_START
    cta_duration   = VIDEO_DURATION - CTA_START          # 10s
    other_duration = CTA_START                            # 30s
    cta_slots      = max(round(n_other * cta_duration / other_duration), 1)

    # Build sequence: cycle regular images, append CTA slots at end
    other_seq = [images[i % n_other] for i in range(n_other)]
    cta_seq   = [cta_image] * cta_slots

    result = other_seq + cta_seq
    log.debug(
        "Image sequence: %d regular slot(s) + %d CTA slot(s) = %d total segments",
        len(other_seq), len(cta_seq), len(result),
    )
    return result


# ─── Filter graph ─────────────────────────────────────────────────────────────

def _build_filter(
    all_images: list[Path],
    quote: str,
    attribution: str,
    font: str,
) -> str:
    n          = len(all_images)
    seg_dur    = VIDEO_DURATION / n
    seg_frames = int(seg_dur * VIDEO_FPS)
    parts: list[str] = []
    font_arg   = f":fontfile='{font}'" if font else ""

    # ── 1. Ken Burns for every image (including CTA) ──────────────────────────
    for i in range(n):
        if i % 2 == 0:
            zoom_e = f"min(1+{ZOOM_SPEED}*on,{MAX_ZOOM})"
            x_e    = "iw/2-(iw/zoom/2)"
            y_e    = "ih/2-(ih/zoom/2)"
        else:
            zoom_e = f"min(1+{ZOOM_SPEED}*on,{MAX_ZOOM})"
            x_e    = f"iw/2-(iw/zoom/2)+0.03*iw*(on/{seg_frames})"
            y_e    = "ih/2-(ih/zoom/2)"

        parts.append(
            f"[{i}:v]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"setsar=1,"
            f"zoompan=z='{zoom_e}':x='{x_e}':y='{y_e}'"
            f":d={seg_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
            f"trim=duration={seg_dur:.3f},"
            f"setpts=PTS-STARTPTS"
            f"[v{i}];"
        )

    # ── 2. Concatenate all segments ───────────────────────────────────────────
    concat_in = "".join(f"[v{i}]" for i in range(n))
    parts.append(f"{concat_in}concat=n={n}:v=1:a=0[base];")

    # ── 3. Global fade-out ────────────────────────────────────────────────────
    parts.append(
        f"[base]"
        f"fade=t=out:st={VIDEO_DURATION - VIDEO_FADE_OUT:.3f}:d={VIDEO_FADE_OUT}"
        f"[bg];"
    )

    # ── 4. Branded intro ──────────────────────────────────────────────────────
    title_alpha = _alpha_window(0, INTRO_FADE_IN, INTRO_FADE_IN + INTRO_HOLD, INTRO_END)
    parts.append(
        f"[bg]"
        f"drawtext=text='{_esc(BRAND_TITLE)}'{font_arg}"
        f":fontsize={TITLE_FONT_SIZE}:fontcolor=white"
        f":x=(w-text_w)/2:y=(h-text_h)/2-40"
        f":shadowcolor=black@0.4:shadowx=2:shadowy=2"
        f":alpha='{title_alpha}',"
        f"drawtext=text='{_esc(BRAND_SUBTITLE)}'{font_arg}"
        f":fontsize={SUBTITLE_SIZE}:fontcolor=white"
        f":x=(w-text_w)/2:y=(h-text_h)/2+80"
        f":shadowcolor=black@0.3:shadowx=1:shadowy=1"
        f":alpha='{title_alpha}'"
        f"[branded];"
    )

    # ── 5. Quote — fast typewriter line-by-line ───────────────────────────────
    wrapped_lines = _wrap_quote(quote, width=24)
    n_lines       = len(wrapped_lines)
    line_height   = QUOTE_FONT_SIZE * 1.55
    total_text_h  = n_lines * line_height
    base_y_offset = int((VIDEO_HEIGHT - total_text_h) / 2) - 60
    time_per_line = QUOTE_REVEAL / max(n_lines, 1)

    current = "[branded]"
    for li, line in enumerate(wrapped_lines):
        line_start = QUOTE_START + li * time_per_line
        ramp       = min(0.6, time_per_line * 0.4)
        alpha      = (
            f"if(lt(t,{line_start:.3f}),0,"
            f"if(lt(t,{line_start + ramp:.3f})"
            f",(t-{line_start:.3f})/{ramp:.3f},1))"
        )
        y_expr  = f"{base_y_offset}+{int(li * line_height)}"
        out_lbl = f"[ql{li}]" if li < n_lines - 1 else "[withquote]"

        parts.append(
            f"{current}"
            f"drawtext=text='{_esc(line)}'{font_arg}"
            f":fontsize={QUOTE_FONT_SIZE}:fontcolor=white"
            f":x=(w-text_w)/2:y={y_expr}"
            f":shadowcolor=black@0.65:shadowx=3:shadowy=3"
            f":alpha='{alpha}'"
            f"{out_lbl};"
        )
        current = out_lbl

    # ── 6. Attribution ────────────────────────────────────────────────────────
    attr_start = QUOTE_START + QUOTE_REVEAL
    attr_ramp  = 0.8
    attr_alpha = (
        f"if(lt(t,{attr_start:.3f}),0,"
        f"if(lt(t,{attr_start + attr_ramp:.3f})"
        f",(t-{attr_start:.3f})/{attr_ramp:.3f},1))"
    )
    attr_y = base_y_offset + int(n_lines * line_height) + 20

    parts.append(
        f"[withquote]"
        f"drawtext=text='{_esc(attribution)}'{font_arg}"
        f":fontsize={ATTR_FONT_SIZE}:fontcolor=white@0.85"
        f":x=(w-text_w)/2:y={attr_y}"
        f":shadowcolor=black@0.5:shadowx=2:shadowy=2"
        f":alpha='{attr_alpha}'"
        f"[withattr];"
    )

    # ── 7. CTA text (fades in at CTA_START over the CTA image) ───────────────
    cta_ramp  = 1.0
    cta_alpha = (
        f"if(lt(t,{CTA_START:.3f}),0,"
        f"if(lt(t,{CTA_START + cta_ramp:.3f})"
        f",(t-{CTA_START:.3f})/{cta_ramp:.3f},1))"
    )

    parts.append(
        f"[withattr]"
        f"drawtext=text='{_esc(CTA_TEXT)}'{font_arg}"
        f":fontsize={CTA_FONT_SIZE}:fontcolor=white@0.95"
        f":x=(w-text_w)/2:y=h*0.83"
        f":shadowcolor=black@0.6:shadowx=2:shadowy=2"
        f":alpha='{cta_alpha}',"
        f"drawtext=text='▼ Subscribe'{font_arg}"
        f":fontsize={CTA_FONT_SIZE - 8}:fontcolor=white@0.80"
        f":x=(w-text_w)/2:y=h*0.83+{CTA_FONT_SIZE + 10}"
        f":shadowcolor=black@0.4:shadowx=1:shadowy=1"
        f":alpha='{cta_alpha}'"
        f"[out]"
    )

    return "\n".join(parts)


# ─── Command assembly ─────────────────────────────────────────────────────────

def _build_command(
    ffmpeg: str,
    all_images: list[Path],
    music: Optional[Path],
    filter_complex: str,
    output_path: Path,
) -> list:
    cmd: list = [ffmpeg, "-y"]

    for img in all_images:
        cmd += ["-loop", "1", "-i", str(img)]

    has_music   = music and Path(music).exists()
    music_index = len(all_images)

    if has_music:
        cmd += ["-i", str(music)]

    cmd += ["-filter_complex", filter_complex, "-map", "[out]"]

    if has_music:
        cmd += [
            "-map", f"{music_index}:a",
            "-af",
            f"afade=t=in:st=0:d=1.0,"
            f"afade=t=out:st={VIDEO_DURATION - 1.5:.3f}:d=1.5,"
            f"volume={MUSIC_VOLUME},"
            f"atrim=duration={VIDEO_DURATION}",
        ]

    cmd += [
        "-t", str(VIDEO_DURATION),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", str(VIDEO_FPS),
        "-movflags", "+faststart",
    ]
    cmd += ["-c:a", "aac", "-b:a", "192k"] if has_music else ["-an"]
    cmd.append(str(output_path))
    return cmd


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _alpha_window(
    fade_in_start: float,
    fade_in_end: float,
    fade_out_start: float,
    fade_out_end: float,
) -> str:
    ri = fade_in_end - fade_in_start
    ro = fade_out_end - fade_out_start
    return (
        f"if(lt(t,{fade_in_start}),0,"
        f"if(lt(t,{fade_in_end}),(t-{fade_in_start})/{ri:.3f},"
        f"if(lt(t,{fade_out_start}),1,"
        f"if(lt(t,{fade_out_end}),({fade_out_end}-t)/{ro:.3f},0))))"
    )


def _wrap_quote(quote: str, width: int = 24) -> list[str]:
    return textwrap.wrap(quote, width=width)


def _esc(text: str) -> str:
    return (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\u2019")
        .replace(":",  "\\:")
        .replace(",",  "\\,")
    )


def _ffmpeg_font_path(path: str) -> str:
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p


def _font_path() -> str:
    if FONT_FILE.exists():
        return _ffmpeg_font_path(str(FONT_FILE))
    fallbacks = [
        "C:/Windows/Fonts/Georgia.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Georgia.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for fb in fallbacks:
        if Path(fb).exists():
            log.debug("Using font: %s", fb)
            return _ffmpeg_font_path(fb)
    log.warning("No font found. Add NotoSerif-Bold.ttf to fonts/")
    return ""


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise EnvironmentError("FFmpeg not found in PATH.")
    return path
