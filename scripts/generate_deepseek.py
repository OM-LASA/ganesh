#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_deepseek.py — Tier-3 article generator using DeepSeek-R1 Reasoner

Pipeline position: runs AFTER Gemini (tier 1) AND Groq (tier 2) as the
final fallback for any scaffold articles still pending upgrade. The
DeepSeek-R1 ("Reasoner") model uses chain-of-thought reasoning before
emitting final text, which produces higher factual accuracy than
single-pass models — especially on dense technical material like
broadcast IT press releases.

Why DeepSeek-R1 as tier 3:
  - Free-tier API generous enough for 5-10 articles per build
  - Reasoning model → "thinks" before writing, catches its own errors
  - OpenAI-compatible REST → trivial to plug into existing pipeline
  - Same NotebookLM protocol as Gemini and Groq (prompt_safety.py import)

Priority order across the full pipeline:
  1. Gemini (generate_gemini.py)       — best quality, daily quota
  2. Groq   (generate_summaries.py)    — fast, high throughput
  3. DeepSeek-R1 (this file)           — last-resort accuracy catch-up

Every tier explicitly SKIPS articles written by a higher tier, so the
three generators cooperate without overwriting each other. The key
field is `generated_by`:
  - "gemini-*"           → skip by Groq AND DeepSeek
  - "generate_summaries_groq" → skip by DeepSeek
  - "generate_deepseek_r1"    → skip by all future reruns

Recommended settings (per DeepSeek official guidance for technical
analysis work):
  Model:            deepseek-reasoner
  Temperature:      0.1     (low = accuracy, no hallucination)
  Top-P:            0.95    (allow natural language in analogies)
  Presence Penalty: 0.1     (encourage wider technical vocabulary)

Environment:
  DEEPSEEK_API_KEY        — required; set via GitHub Actions secret
  DEEPSEEK_MAX_PER_RUN    — default 5; free-tier safe
  DEEPSEEK_TIMEOUT        — default 180s (Reasoner is slower than Llama)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests

# ── Shared NotebookLM protocol ───────────────────────────────────────────────
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prompt_safety import FACTUAL_SAFETY_BLOCK
except ImportError:
    FACTUAL_SAFETY_BLOCK = ""

# ── Config ────────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner").strip()
DEEPSEEK_API_URL = os.environ.get(
    "DEEPSEEK_API_URL",
    "https://api.deepseek.com/v1/chat/completions",
).strip()

# Recommended tuning for technical accuracy (per DeepSeek guidance)
TEMPERATURE       = float(os.environ.get("DEEPSEEK_TEMPERATURE", "0.1"))
TOP_P             = float(os.environ.get("DEEPSEEK_TOP_P", "0.95"))
PRESENCE_PENALTY  = float(os.environ.get("DEEPSEEK_PRESENCE_PENALTY", "0.1"))
MAX_TOKENS        = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "2000"))

# Free-tier safe; Reasoner is slower (~20-30s per article) due to
# chain-of-thought reasoning, so keep per-run count modest.
MAX_PER_RUN = int(os.environ.get("DEEPSEEK_MAX_PER_RUN", "5"))
REQUEST_TIMEOUT = int(os.environ.get("DEEPSEEK_TIMEOUT", "180"))
INTER_CALL_SLEEP = int(os.environ.get("DEEPSEEK_SLEEP", "3"))

# Quality thresholds (same as other tiers)
REPROCESS_THRESHOLD = int(os.environ.get("REPROCESS_THRESHOLD", "700"))
REQUIRE_HEADINGS    = os.environ.get("REQUIRE_HEADINGS", "true").lower() in {"1","true","yes","y"}

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"


# ── Tier-3 gating: skip articles already handled by Gemini or Groq ────────────
def needs_deepseek(article: dict[str, Any]) -> bool:
    """Return True if this article should be processed by DeepSeek-R1.

    Strict gating — DeepSeek ONLY handles scaffolds that neither Gemini
    nor Groq processed. This prevents triple-generation waste and protects
    higher-tier content from being overwritten.
    """
    gen_by = (article.get("generated_by") or "").lower()

    # Tier-1 (Gemini) output: sacred, never touch.
    if gen_by.startswith("gemini"):
        return False

    # Tier-2 (Groq) output: also sacred.
    if "groq" in gen_by:
        return False

    # Tier-3 output: already done.
    if "deepseek" in gen_by:
        return False

    # Editorial content: protected regardless of who/what set it.
    if article.get("is_editorial") or article.get("editorial"):
        return False

    # Only scaffolds are eligible.
    is_scaffold = gen_by in ("", "rewrite_feed_local", "rewrite_feed")
    if not is_scaffold:
        return False

    body = article.get("body_html", "") or ""
    wc   = int(article.get("word_count", 0) or 0)

    if not body or len(body.strip()) < 100:
        return True
    if wc < REPROCESS_THRESHOLD:
        return True
    if REQUIRE_HEADINGS and "<h2" not in body.lower():
        return True
    return False


# ── System prompt (NotebookLM protocol + DeepSeek-specific framing) ──────────
SYSTEM_PROMPT = FACTUAL_SAFETY_BLOCK + """

═══════════════════════════════════════════════════════════════════════════
DEEPSEEK-R1 REASONING MODE
═══════════════════════════════════════════════════════════════════════════

You are the DeepSeek-R1 Reasoner model. Before writing the article, use
your chain-of-thought reasoning to verify:

  1. Every factual claim traces to a specific line in the source text.
     If a claim does not, DO NOT include it. Move the unanswered question
     to the Blind Spots section instead.

  2. Every vendor or product mentioned is categorized correctly per the
     safe list in the core rules above. If uncertain about a vendor's
     product category, use neutral terms ("solution", "platform") and
     flag it in Blind Spots.

  3. Every technical term is paired with an analogy on first mention.

  4. The [Source N] citations at the end map exactly to real sources
     provided in the user message.

Your reasoning phase is internal — do NOT include <think> tags or
reasoning traces in the final output. Emit only the structured HTML
article body following the required output structure.

Begin reasoning, then produce the article based ONLY on the source text
provided in the user message.
"""


# ── User prompt builder ──────────────────────────────────────────────────────
def build_user_prompt(article: dict[str, Any]) -> str:
    """Pack all source material into a single structured user message."""
    title    = article.get("title", "") or ""
    slug     = article.get("slug", "") or ""
    category = article.get("category", "") or ""
    source   = article.get("source", "") or article.get("site", "") or ""
    source_url = article.get("url", "") or article.get("link", "") or ""
    published  = article.get("date", "") or article.get("published", "") or ""
    existing_body = article.get("body_html", "") or article.get("body", "") or ""

    # Strip HTML tags from existing body to feed as plain source text
    plain = re.sub(r"<[^>]+>", " ", existing_body)
    plain = re.sub(r"\s+", " ", plain).strip()

    return f"""SOURCE MATERIAL — use ONLY this text, no outside knowledge.

Title: {title}
Vendor/Publisher: {source}
URL: {source_url}
Date: {published}
Category: {category}
Slug: {slug}

Original source body:
---
{plain}
---

Generate the article following the NotebookLM protocol defined in the
system prompt. Structure: Quick Hit → What Happened → Tech Spec →
So What? (Human Impact) → Blind Spots → Sources. Every claim must
carry an inline [Source N] citation. The Sources section at the end
must list the actual source above as [Source 1].

Output HTML body only — no <html>, <head>, <title>, or byline tags."""


# ── DeepSeek API call ────────────────────────────────────────────────────────
def call_deepseek(system: str, user: str) -> Optional[str]:
    """Call DeepSeek-R1 Reasoner. Returns HTML body or None on failure."""
    if not DEEPSEEK_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":             DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature":       TEMPERATURE,
        "top_p":             TOP_P,
        "presence_penalty":  PRESENCE_PENALTY,
        "max_tokens":        MAX_TOKENS,
        "stream":            False,
    }

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"    [ERROR] DeepSeek request timed out after {REQUEST_TIMEOUT}s")
        return None
    except Exception as e:
        print(f"    [ERROR] DeepSeek request failed: {e}")
        return None

    if resp.status_code != 200:
        print(f"    [ERROR] DeepSeek HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    [ERROR] Could not parse DeepSeek response: {e}")
        return None

    # R1 sometimes leaks <think>...</think> blocks despite instructions.
    # Strip them defensively.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I)
    content = content.strip()

    # Strip code fences if present.
    content = re.sub(r"^```(?:html)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    return content.strip() or None


# ── Quality gates (match other tiers) ────────────────────────────────────────
def count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def count_h2(html: str) -> int:
    return len(re.findall(r"<h2[\s>]", html, re.I))


def has_sources_section(html: str) -> bool:
    """NotebookLM protocol requires a Sources list at the end."""
    return bool(re.search(r"<h3>\s*Sources\s*</h3>", html, re.I))


def has_blind_spots_section(html: str) -> bool:
    return bool(re.search(r"<h2>\s*Blind Spots\s*</h2>", html, re.I))


def has_citations(html: str) -> bool:
    """At least 2 inline [Source N] citations."""
    return len(re.findall(r"\[Source\s*\d+\]", html)) >= 2


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    print("=== generate_deepseek.py — Tier-3 fallback (DeepSeek-R1 Reasoner) ===")

    if not DEEPSEEK_API_KEY:
        print("  ⚠ DEEPSEEK_API_KEY not set — skipping tier-3 generation")
        print("  Get a key at https://platform.deepseek.com and add as GitHub secret")
        return 0

    if not ARTICLES_FILE.exists():
        print(f"  ⚠ {ARTICLES_FILE} not found — nothing to do")
        return 0

    articles = json.loads(ARTICLES_FILE.read_text(encoding="utf-8"))
    print(f"  Loaded {len(articles)} articles")

    eligible = [a for a in articles if needs_deepseek(a)]
    print(f"  Tier-3 eligible (scaffolds untouched by Gemini + Groq): {len(eligible)}")
    print(f"  Will process up to {MAX_PER_RUN} this run "
          f"(T={TEMPERATURE}, top_p={TOP_P}, presence_penalty={PRESENCE_PENALTY})")

    if not eligible:
        print("  ✓ No articles need tier-3 processing — Gemini + Groq covered everything")
        return 0

    processed = 0
    upgraded  = 0

    for art in eligible:
        if processed >= MAX_PER_RUN:
            print(f"  [INFO] Hit MAX_PER_RUN={MAX_PER_RUN} — remaining process next run")
            break
        processed += 1
        slug = art.get("slug", "(no-slug)")
        print(f"  → [{processed}/{min(len(eligible), MAX_PER_RUN)}] Processing: {slug[:60]}")

        body = call_deepseek(SYSTEM_PROMPT, build_user_prompt(art))
        if not body:
            print("    [SKIP] DeepSeek returned nothing")
            time.sleep(INTER_CALL_SLEEP)
            continue

        # Quality gates
        wc = count_words(body)
        h2 = count_h2(body)
        if wc < 400:
            print(f"    [REJECT] Only {wc} words (need ≥400) — keeping scaffold")
            time.sleep(INTER_CALL_SLEEP)
            continue
        if h2 < 4:
            print(f"    [REJECT] Only {h2} H2 sections (need ≥4) — keeping scaffold")
            time.sleep(INTER_CALL_SLEEP)
            continue
        if not has_sources_section(body):
            print("    [REJECT] Missing Sources section — keeping scaffold")
            time.sleep(INTER_CALL_SLEEP)
            continue
        if not has_blind_spots_section(body):
            print("    [REJECT] Missing Blind Spots section — keeping scaffold")
            time.sleep(INTER_CALL_SLEEP)
            continue
        if not has_citations(body):
            print("    [REJECT] Missing inline [Source N] citations — keeping scaffold")
            time.sleep(INTER_CALL_SLEEP)
            continue

        # Commit upgrade
        art["body_html"]     = body
        art["body"]          = body
        art["word_count"]    = wc
        art["generated_by"]  = "deepseek-r1"
        art["is_editorial"]  = True
        art["needs_gemini"]  = False
        upgraded += 1
        print(f"    ✓ {wc} words, {h2} H2 sections → {slug[:60]}")
        time.sleep(INTER_CALL_SLEEP)

    # Save
    ARTICLES_FILE.write_text(
        json.dumps(articles, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[DONE] Tier-3 upgraded {upgraded}/{processed} articles → saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
