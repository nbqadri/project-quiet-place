"""
video_builder.py – Build a 40-second vertical YouTube Short.

Background strategy:
  - Each image is perfectly static (zero motion) — no zoompan, no jitter
  - Clean cross-dissolve (xfade) transitions between images
  - Renders 3–4x faster than zoompan

Timeline:
  0s   – 4.5s  : Branded intro fades in, holds, fades out
  4.5s – 18s   : Quote reveals line-by-line (typewriter)
  18s  – 30s   : Full quote + attribution holds
  30s  – 40s   : CTA image as last segment + subscribe text fades in
  38.5s– 40s   : Fade to black
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
INTRO_FADE_IN  = 1.0
INTRO_HOLD     = 2.5
INTRO_FADE_OUT = 1.0
INTRO_END      = INTRO_FADE_IN + INTRO_HOLD + INTRO_FADE_OUT   # 4.5s

QUOTE_START    = INTRO_END     # 4.5s
QUOTE_REVEAL   = 13.5
CTA_START      = 30.0
VIDEO_FADE_OUT = 1.5

# ── Cross-dissolve ────────────────────────────────────────────────────────────
XFADE_DURATION = 0.8   # seconds for dissolve — longer = smoother transition feel

# ── Visual ────────────────────────────────────────────────────────────────────
TITLE_FONT_SIZE = 110
SUBTITLE_SIZE   = 38
QUOTE_FONT_SIZE = 62
ATTR_FONT_SIZE  = 40
CTA_FONT_SIZE   = 34

_CTA_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ─── Public API ───────────────────────────────────────────────────────────────

def pick_cta_image() -> Optional[Path]:
    """Randomly select one image from assets/youtube_CTA/."""
    candidates = [
        p for p in CTA_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _CTA_EXTS
    ]
    if not candidates:
        log.warning("No CTA images in %s – last background image reused.", CTA_DIR)
        return None
    chosen = random.choice(candidates)
    log.info("CTA image: %s", chosen.name)
    return chosen


def build_video(
    images: list[Path],
    quote: str,
    attribution: str,
    music: Optional[Path],
    output_path: Path,
    cta_image: Optional[Path] = None,
) -> Path:
    ffmpeg     = _require_ffmpeg()
    font       = _font_path()
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


# ─── Image sequence ───────────────────────────────────────────────────────────

def _build_image_sequence(
    images: list[Path],
    cta_image: Optional[Path],
) -> list[Path]:
    """Regular images fill 0–30s, CTA image fills 30–40s."""
    if cta_image is None or not cta_image.exists():
        return list(images)

    n_other   = len(images)
    cta_slots = max(round(n_other * (VIDEO_DURATION - CTA_START) / CTA_START), 1)
    result    = list(images) + [cta_image] * cta_slots

    log.debug(
        "Sequence: %d regular + %d CTA = %d total segments",
        n_other, cta_slots, len(result),
    )
    return result


# ─── Filter graph ─────────────────────────────────────────────────────────────

def _build_filter(
    all_images: list[Path],
    quote: str,
    attribution: str,
    font: str,
) -> str:
    n        = len(all_images)
    parts: list[str] = []
    font_arg = f":fontfile='{font}'" if font else ""

    # ── Timing ────────────────────────────────────────────────────────────────
    # With xfade the images overlap at transitions so total wall time stays
    # exactly VIDEO_DURATION:
    #
    #   total = n * seg_dur - (n-1) * XFADE_DURATION = VIDEO_DURATION
    #   seg_dur = (VIDEO_DURATION + (n-1) * XFADE_DURATION) / n
    #
    seg_dur = (VIDEO_DURATION + (n - 1) * XFADE_DURATION) / n

    # ── 1. Scale every image to exact frame size — completely static ──────────
    for i in range(n):
        parts.append(
            f"[{i}:v]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"setsar=1,"
            f"setpts=PTS-STARTPTS,"
            f"fps=fps={VIDEO_FPS}"
            f"[img{i}];"
        )

    # ── 2. Chain xfade dissolves ──────────────────────────────────────────────
    # xfade offset = time at which the TRANSITION STARTS.
    # For image i (0-based), its segment starts at i*(seg_dur - XFADE_DURATION)
    # and the transition to the NEXT image starts at the end of image i's
    # unique (non-overlapping) portion.
    #
    # offset_i = i * (seg_dur - XFADE_DURATION)
    #
    # We chain pairs: [prev][imgN] → xfade → [xfN]
    # The output of each xfade is the accumulated video up to that point,
    # so the offset is cumulative from the START of the whole stream.

    if n == 1:
        parts.append("[img0]copy[base];")
    else:
        # First transition: img0 → img1
        offset_0 = seg_dur - XFADE_DURATION
        parts.append(
            f"[img0][img1]"
            f"xfade=transition=dissolve"
            f":duration={XFADE_DURATION:.3f}"
            f":offset={offset_0:.4f}"
            f"[xf1];"
        )
        for i in range(2, n):
            in_label  = f"[xf{i-1}]"
            out_label = f"[xf{i}]" if i < n - 1 else "[base]"
            # Each subsequent offset advances by one non-overlapping segment
            offset_i  = i * (seg_dur - XFADE_DURATION)
            parts.append(
                f"{in_label}[img{i}]"
                f"xfade=transition=dissolve"
                f":duration={XFADE_DURATION:.3f}"
                f":offset={offset_i:.4f}"
                f"{out_label};"
            )

    # ── 3. Trim to exact duration + global video fade-out ─────────────────────
    parts.append(
        f"[base]"
        f"trim=duration={VIDEO_DURATION:.3f},"
        f"setpts=PTS-STARTPTS,"
        f"fade=t=out:st={VIDEO_DURATION - VIDEO_FADE_OUT:.3f}:d={VIDEO_FADE_OUT:.3f}"
        f"[bg];"
    )

    # ── 4. Branded intro overlay ──────────────────────────────────────────────
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

    # ── 5. Quote — line-by-line typewriter reveal ─────────────────────────────
    wrapped_lines = _wrap_quote(quote)
    n_lines       = len(wrapped_lines)
    line_height   = QUOTE_FONT_SIZE * 1.55
    total_text_h  = n_lines * line_height
    base_y        = int((VIDEO_HEIGHT - total_text_h) / 2) - 60
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
        y_expr  = f"{base_y}+{int(li * line_height)}"
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
    attr_y = base_y + int(n_lines * line_height) + 20

    parts.append(
        f"[withquote]"
        f"drawtext=text='{_esc(attribution)}'{font_arg}"
        f":fontsize={ATTR_FONT_SIZE}:fontcolor=white@0.85"
        f":x=(w-text_w)/2:y={attr_y}"
        f":shadowcolor=black@0.5:shadowx=2:shadowy=2"
        f":alpha='{attr_alpha}'"
        f"[withattr];"
    )

    # ── 7. CTA text ───────────────────────────────────────────────────────────
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

    # Give each image slightly more than its segment duration so xfade
    # never runs out of frames. seg_dur + XFADE_DURATION is a safe ceiling.
    seg_dur   = (VIDEO_DURATION + (len(all_images) - 1) * XFADE_DURATION) / len(all_images)
    img_dur   = seg_dur + XFADE_DURATION + 0.5   # 0.5s extra safety margin

    for img in all_images:
        cmd += ["-loop", "1", "-t", f"{img_dur:.3f}", "-i", str(img)]

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
