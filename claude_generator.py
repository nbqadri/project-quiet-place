"""
claude_generator.py – Generate inspirational quotes via the Anthropic Claude API.

Each quote object contains:
  - quote       : the inspirational quote text
  - attribution : author or source e.g. "— Rumi" or "— Ancient Chinese Proverb"
  - keywords    : 3-5 mood/imagery words for image + music matching
  - title       : short, human, engaging YouTube video title
  - pinned_comment : standalone engaging comment for pinning (not a repeat of the quote)
"""

import json
import logging
import time
from typing import Optional

import requests

from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    NUM_QUOTES,
    MAX_RETRIES,
    RETRY_DELAY,
    BRAND_TITLE,
    BRAND_SUBTITLE,
)

log = logging.getLogger(__name__)


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_quotes(topic: str) -> list[dict]:
    """
    Generate NUM_QUOTES quote objects for *topic*.

    Each object:
        {
            "quote":          "...",
            "attribution":    "— Author Name",
            "keywords":       ["kw1", "kw2", ...],
            "title":          "Short Human Video Title",
            "pinned_comment": "Engaging standalone comment with hashtags"
        }
    """
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set in your .env file.")

    prompt = _build_prompt(topic)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw    = _call_claude(prompt)
            quotes = _parse_response(raw)
            log.info("Generated %d quotes for topic '%s'", len(quotes), topic)
            return quotes
        except Exception as exc:
            log.warning("Claude attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    log.error("All Claude retries exhausted. Using built-in fallback quotes.")
    return _fallback_quotes(topic)


# ─── Internals ────────────────────────────────────────────────────────────────

def _build_prompt(topic: str) -> str:
    series = f"{BRAND_TITLE} {BRAND_SUBTITLE}".strip()
    return f"""You are a creative director for a YouTube Shorts channel called "{series}".

Topic: "{topic}"

Generate exactly {NUM_QUOTES} unique inspirational quote objects. For each one provide ALL of the following fields:

1. "quote" — an uplifting quote, 10–20 words, relevant to the topic. Use real attributed quotes where possible, otherwise craft an original one.

2. "attribution" — the author or source, formatted as "— Firstname Lastname" or "— Ancient Proverb" or "— Old Chinese Saying" etc. Never leave this blank.

3. "keywords" — 3 to 5 single lowercase words describing the mood and imagery (used for searching background images and music).

4. "title" — a short, human, engaging YouTube video title. 4–7 words. Should feel like something a person would write, not a robot. Do NOT include numbers or "shorts" or "video". Examples: "Find Stillness in the Noise", "The Strength Within You", "Every Step Forward Counts".

5. "pinned_comment" — a standalone engaging comment to be pinned on the video. Rules:
   - Does NOT repeat or quote the quote text
   - Can be a thought-provoker, surprising fact, gentle challenge, warm statement, or open reflection
   - Conversational and human — reads like a real person wrote it
   - 1 to 3 sentences maximum
   - Never starts with "I" or "We"
   - Ends with 2–3 relevant hashtags, always including #{BRAND_TITLE}{BRAND_SUBTITLE.replace(' ', '')}
   - One tasteful emoji is optional but not required every time

Respond ONLY with a valid JSON array — no markdown fences, no extra text:
[
  {{
    "quote": "...",
    "attribution": "— ...",
    "keywords": ["...", "..."],
    "title": "...",
    "pinned_comment": "..."
  }},
  ...
]"""


def _call_claude(prompt: str) -> str:
    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "messages":   [{"role": "user", "content": prompt}],
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _parse_response(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(
            l for l in text.splitlines() if not l.startswith("```")
        ).strip()

    quotes = json.loads(text)
    if not isinstance(quotes, list):
        raise ValueError("Expected a JSON array from Claude.")

    validated = []
    for item in quotes:
        if not isinstance(item, dict):
            continue
        if "quote" not in item:
            continue
        validated.append({
            "quote":          str(item.get("quote", "")).strip(),
            "attribution":    str(item.get("attribution", "")).strip(),
            "keywords":       [str(k).lower() for k in item.get("keywords", [])],
            "title":          str(item.get("title", "")).strip(),
            "pinned_comment": str(item.get("pinned_comment", "")).strip(),
        })

    if not validated:
        raise ValueError("No valid quote objects found in Claude response.")
    return validated


def _fallback_quotes(topic: str) -> list[dict]:
    series = f"{BRAND_TITLE}{BRAND_SUBTITLE.replace(' ', '')}"
    data = [
        (
            "The journey of a thousand miles begins with a single breath.",
            "— Lao Tzu",
            ["journey", "calm", "begin"],
            "Every Step Begins in Stillness",
            f"The hardest part of any journey is trusting the first step. 🌿 #{series} #Mindfulness",
        ),
        (
            "Peace is not found — it is cultivated from within.",
            "— Thich Nhat Hanh",
            ["peace", "inner", "calm"],
            "Peace Lives Inside You",
            f"Stillness isn't the absence of noise — it's the presence of clarity. #{series} #InnerPeace",
        ),
        (
            "Let stillness be your greatest teacher today.",
            "— Ancient Proverb",
            ["stillness", "meditation", "wisdom"],
            "Let Stillness Teach You",
            f"Some lessons can only be heard in silence. #{series} #Wisdom",
        ),
        (
            "Every exhale releases what no longer serves you.",
            "— Unknown",
            ["breathe", "release", "yoga"],
            "Breathe and Let It Go",
            f"Your breath is the one thing you can always return to. 🌬️ #{series} #Breathwork",
        ),
        (
            "Strength grows in the moments you think you cannot go on.",
            "— Unknown",
            ["strength", "resilience", "power"],
            "Strength Grows in Struggle",
            f"Rock bottom has built more champions than comfort ever has. #{series} #Resilience",
        ),
        (
            "Your body hears everything your mind says — speak kindly.",
            "— Naomi Judd",
            ["mindfulness", "body", "mind"],
            "Speak Kindly to Yourself",
            f"The words you say to yourself in private shape everything else. #{series} #SelfLove",
        ),
        (
            "Slow down. The present moment is where magic lives.",
            "— Unknown",
            ["present", "slow", "magic"],
            "Magic Hides in the Present",
            f"We scroll through life looking for meaning that was already right in front of us. ✨ #{series} #Presence",
        ),
        (
            "Growth and comfort cannot coexist.",
            "— Ginni Rometty",
            ["growth", "change", "challenge"],
            "Growth Demands Discomfort",
            f"Every version of you that you're proud of was born from a moment of discomfort. #{series} #Growth",
        ),
        (
            "Breathe in possibility. Breathe out fear.",
            "— Unknown",
            ["breathe", "possibility", "courage"],
            "Inhale Courage Exhale Fear",
            f"Fear and possibility cannot occupy the same breath. Try it right now. 🌬️ #{series} #Courage",
        ),
    ]
    return [
        {
            "quote":          q,
            "attribution":    attr,
            "keywords":       kw + [topic.lower().split()[0]],
            "title":          title,
            "pinned_comment": comment,
        }
        for q, attr, kw, title, comment in data[:NUM_QUOTES]
    ]
