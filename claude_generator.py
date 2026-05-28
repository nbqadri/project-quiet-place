"""
claude_generator.py – Generate inspirational quotes via the Anthropic Claude API.
Quotes always include an attribution (author name, cultural proverb, etc.)
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
)

log = logging.getLogger(__name__)


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_quotes(topic: str) -> list[dict]:
    """
    Generate NUM_QUOTES inspirational quotes for *topic*.

    Returns a list of dicts:
        [{
            "quote":       "The quieter you become...",
            "attribution": "— Rumi",
            "keywords":    ["stillness", "calm", "meditation"]
        }, ...]
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
    return f"""You are a creative writer specialising in short, powerful inspirational quotes for social media videos.

Topic: "{topic}"

Generate exactly {NUM_QUOTES} unique, uplifting quotes that are:
- Between 10 and 20 words each
- Relevant to the topic
- Diverse in style (poetic, direct, metaphorical)
- Attributed to a real person, cultural source, or tradition
  Examples of attribution styles:
    "— Rumi"
    "— Martin Luther King Jr."
    "— Ancient Chinese Proverb"
    "— Lao Tzu"
    "— Maya Angelou"
    "— Japanese Zen Saying"
    "— Stoic Philosophy"
    "— Thich Nhat Hanh"
  Use REAL attributions that genuinely match the quote's spirit.
  If a quote is original/generic, attribute it to a fitting cultural tradition.

Also provide 3–5 single-word keywords per quote for image searching.

Respond ONLY with a valid JSON array – no markdown fences, no extra text:
[
  {{
    "quote": "The full quote text here.",
    "attribution": "— Author or Source",
    "keywords": ["keyword1", "keyword2", "keyword3"]
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
        lines = text.splitlines()
        text  = "\n".join(l for l in lines if not l.startswith("```")).strip()

    quotes = json.loads(text)
    if not isinstance(quotes, list):
        raise ValueError("Expected a JSON array from Claude.")

    validated = []
    for item in quotes:
        if isinstance(item, dict) and "quote" in item:
            validated.append({
                "quote":       str(item["quote"]).strip(),
                "attribution": str(item.get("attribution", "")).strip(),
                "keywords":    [str(k).lower() for k in item.get("keywords", [])],
            })
    if not validated:
        raise ValueError("No valid quote objects in Claude response.")
    return validated


def _fallback_quotes(topic: str) -> list[dict]:
    generic = [
        ("The journey of a thousand miles begins with a single breath.",
         "— Lao Tzu", ["journey", "calm", "start"]),
        ("Peace is not found – it is cultivated from within.",
         "— Thich Nhat Hanh", ["peace", "inner", "calm"]),
        ("Let stillness be your greatest teacher today.",
         "— Ancient Zen Saying", ["stillness", "meditation", "wisdom"]),
        ("Every exhale releases what no longer serves you.",
         "— Yoga Philosophy", ["breathe", "release", "yoga"]),
        ("Strength grows in the moments you think you cannot go on.",
         "— Ancient Greek Proverb", ["strength", "resilience", "power"]),
        ("Your body hears everything your mind says – speak kindly.",
         "— Naomi Judd", ["mindfulness", "body", "mind"]),
        ("Slow down. The present moment is where magic lives.",
         "— Eckhart Tolle", ["present", "slow", "magic"]),
        ("Growth and comfort cannot coexist.",
         "— Ginni Rometty", ["growth", "change", "challenge"]),
        ("Breathe in possibility. Breathe out fear.",
         "— Stoic Philosophy", ["breathe", "possibility", "courage"]),
    ]
    return [
        {"quote": q, "attribution": attr, "keywords": kw + [topic.lower().split()[0]]}
        for q, attr, kw in generic[:NUM_QUOTES]
    ]
