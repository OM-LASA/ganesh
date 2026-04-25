#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_openrouter.py — Tier-3 generator using OpenRouter's FREE models

Pipeline position: runs AFTER Gemini (tier-1) AND Groq (tier-2) as the
final fallback for any scaffold articles still pending upgrade.

Why OpenRouter as tier-3:
  - FREE access to DeepSeek-R1 Reasoner (same model, $0 cost)
  - Aggregates many free reasoning models — auto-cascades if one fails
  - OpenAI-compatible REST API — same payload shape as DeepSeek/Groq
  - One account, one key, multiple models

Free models tried in order for each article:
  1. deepseek/deepseek-r1:free         — reasoning, highest quality
  2. deepseek/deepseek-chat:free       — V3 chat, fast fallback
  3. google/gemini-2.0-flash-exp:free  — Gemini on different quota

Setup (one-time, FREE, no card):
  1. Sign up at https://openrouter.ai
  2. Create API key at https://openrouter.ai/keys
  3. GitHub repo → Settings → Secrets and variables → Actions →
     "New repository secret" → Name: OPENROUTER_API_KEY, Value: your key

CRITICAL QUALITY PRINCIPLES:
  - Temperature LOCKED at 0.1 — free models tend toward laziness/hype,
    low temp is the only way to preserve factual accuracy
  - Strict NotebookLM validation gates — every output must have:
      * ≥4 <h2> sections
      * <h3>Sources</h3> block with [Source N] mapping
      * <h2>Blind Spots</h2> section
      * ≥2 inline [Source N] citations
      * ≥400 words
    If any gate fails, the article stays a scaffold (no partial quality).
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
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_API_URL = os.environ.get(
    "OPENROUTER_API_URL",
    "https://openrouter.ai/api/v1/chat/completions",
).strip()

# Free model cascade — tried in order until one succeeds for a given article.
_DEFAULT_MODELS = [
    # April 2026 verified free models on OpenRouter. DeepSeek R1 and
    # Gemini 2.0 Flash Exp moved off free tier in Q1 2026. Current
    # strongest free reasoning models, tried in order:
    "openrouter/free",                              # auto-router: best available
    "nvidia/nemotron-3-super-120b-a12b:free",       # 120B MoE, reasoning
    "openai/gpt-oss-120b:free",                     # 117B MoE, configurable reasoning
    "meta-llama/llama-3.3-70b-instruct:free",       # proven workhorse
    "qwen/qwen3-next-80b-a3b-instruct:free",        # 80B, instruction-tuned
]
OPENROUTER_MODELS = [
    m.strip() for m in
    os.environ.get("OPENROUTER_MODELS", ",".join(_DEFAULT_MODELS)).split(",")
    if m.strip()
]

# LOCKED tuning — do NOT raise temperature. Free models hallucinate at higher T.
TEMPERATURE       = float(os.environ.get("OPENROUTER_TEMPERATURE", "0.35"))
TOP_P             = float(os.environ.get("OPENROUTER_TOP_P", "0.9"))
FREQUENCY_PENALTY = float(os.environ.get("OPENROUTER_FREQUENCY_PENALTY", "0.2"))
PRESENCE_PENALTY  = float(os.environ.get("OPENROUTER_PRESENCE_PENALTY", "0.0"))
MAX_TOKENS       = int(os.environ.get("OPENROUTER_MAX_TOKENS", "2000"))

MAX_PER_RUN      = int(os.environ.get("OPENROUTER_MAX_PER_RUN", "5"))
REQUEST_TIMEOUT  = int(os.environ.get("OPENROUTER_TIMEOUT", "180"))
INTER_CALL_SLEEP = int(os.environ.get("OPENROUTER_SLEEP", "4"))

# OpenRouter recommends these headers for rate-limit priority & attribution.
APP_TITLE       = os.environ.get("OPENROUTER_APP_TITLE", "The Streamic")
APP_REFERER     = os.environ.get("OPENROUTER_REFERER", "https://www.thestreamic.in")

# Quality thresholds (SAME as other tiers — non-negotiable)
REPROCESS_THRESHOLD = int(os.environ.get("REPROCESS_THRESHOLD", "700"))
REQUIRE_HEADINGS    = os.environ.get("REQUIRE_HEADINGS", "true").lower() in {"1","true","yes","y"}

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"


# ── Tier-3 gating: skip anything already handled by Gemini or Groq ────────────
def needs_openrouter(article: dict[str, Any]) -> bool:
    """Return True if this article should be processed by OpenRouter tier-3.

    Strict gating — OpenRouter ONLY handles scaffolds that neither Gemini
    nor Groq processed. This prevents triple-generation waste and protects
    higher-tier content from being overwritten.
    """
    gen_by = (article.get("generated_by") or "").lower()

    # Tier-1 Mistral output: sacred.
    if gen_by.startswith("mistral"):
        return False

    # Tier-1 (Gemini) output: sacred.
    if gen_by.startswith("gemini"):
        return False

    # Tier-2 (Groq) output: sacred.
    if "groq" in gen_by:
        return False

    # Already handled by a previous OpenRouter/DeepSeek run: sacred.
    if "deepseek" in gen_by or "openrouter" in gen_by:
        return False

    # Editorial content: protected regardless of how it got here.
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


# ── System prompt (NotebookLM protocol + free-model-specific discipline) ──────
SYSTEM_PROMPT = FACTUAL_SAFETY_BLOCK + """

═══════════════════════════════════════════════════════════════════════════
FREE REASONING MODEL — EXTRA DISCIPLINE
═══════════════════════════════════════════════════════════════════════════

You are running on a free-tier reasoning model. Free models have a
tendency to:
  - Cut corners on length
  - Skip the citation discipline
  - Invent technical claims not in the source
  - Substitute marketing buzzwords for real analysis

Every one of those tendencies is a fatal flaw for The Streamic. Do NOT
take the shortcut. Your output will be rejected by automated validation
gates if it fails ANY of these checks:

  ✓ At least 4 <h2> sections
  ✓ A <h3>Sources</h3> block with [Source N] entries at the end
  ✓ A <h2>Blind Spots</h2> section listing what the source did NOT say
  ✓ At least 2 inline [Source N] citations in the body
  ✓ At least 400 words of body text

If you cannot satisfy ALL 5 gates using ONLY the source material
provided, respond with less rather than inventing more. A short
honest article passes the gate. A long invented article gets rejected.

Reason first, write second. If your reasoning produces a claim that
cannot be traced to a specific line in the source, move that claim to
the Blind Spots section as an unanswered question instead.

Do NOT include any <think>...</think> tags or reasoning traces in the
final output. Emit only the structured HTML article body.

Begin generating the article now based ONLY on the source text provided
in the user message.
"""


# ── User prompt builder ──────────────────────────────────────────────────────
def build_user_prompt(article: dict[str, Any]) -> str:
    """Pack all source material into a single structured user message."""
    title      = article.get("title", "") or ""
    slug       = article.get("slug", "") or ""
    category   = article.get("category", "") or ""
    source     = article.get("source", "") or article.get("site", "") or ""
    source_url = article.get("url", "") or article.get("link", "") or ""
    published  = article.get("date", "") or article.get("published", "") or ""
    existing_body = article.get("body_html", "") or article.get("body", "") or ""

    # Strip HTML tags so source arrives as clean plain text
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
system prompt. Required structure:

  <h2>The Quick Hit</h2>          — one-sentence coffee-shop summary
  <h2>What Happened</h2>          — 2-3 facts with [Source N] citations
  <h2>The Tech Spec</h2>          — technical breakdown, analogy rule
  <h2>So What?</h2>               — practical impact for broadcasters
  <h2>Blind Spots</h2>            — 3-5 unanswered questions
  <h3>Sources</h3>                — <ol> mapping [Source N] to origin

Every factual claim carries an inline [Source N] citation. The Sources
section at the end must list the actual source above as [Source 1].

Output HTML body only — no <html>, <head>, <title>, or byline tags."""


# ── OpenRouter API call ──────────────────────────────────────────────────────
def call_openrouter(system: str, user: str, model: str) -> tuple[Optional[str], str]:
    """Call OpenRouter with a specific model.

    Returns (body_html_or_None, status_reason).
    status_reason is "ok", "rate_limit", "auth", "server", "timeout", or "other".
    Used by caller to decide whether to try next model.
    """
    if not OPENROUTER_API_KEY:
        return None, "auth"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  APP_REFERER,
        "X-Title":       APP_TITLE,
    }
    payload = {
        "model":             model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature":       TEMPERATURE,       # 0.35 — trade-journal sweet spot
        "top_p":             TOP_P,
        "frequency_penalty": FREQUENCY_PENALTY,  # 0.2 — kills [Source 1] spam
        "presence_penalty":  PRESENCE_PENALTY,
        "max_tokens":        MAX_TOKENS,
        "stream":            False,
    }

    try:
        resp = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"    [TIMEOUT] {model} after {REQUEST_TIMEOUT}s")
        return None, "timeout"
    except Exception as e:
        print(f"    [ERROR] {model} request failed: {e}")
        return None, "other"

    # Handle specific status codes
    if resp.status_code == 401:
        print(f"    [ERROR] OpenRouter 401 Unauthorized — check OPENROUTER_API_KEY")
        return None, "auth"
    if resp.status_code == 429:
        print(f"    [RATE-LIMIT] {model} — trying next free model")
        return None, "rate_limit"
    if resp.status_code == 402:
        print(f"    [ERROR] {model} requires credits (not a free model?)")
        return None, "auth"
    if resp.status_code in (500, 502, 503, 504):
        print(f"    [SERVER] {model} HTTP {resp.status_code} — trying next free model")
        return None, "server"
    if resp.status_code != 200:
        print(f"    [ERROR] {model} HTTP {resp.status_code}: {resp.text[:200]}")
        return None, "other"

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    [ERROR] Could not parse {model} response: {e}")
        return None, "other"

    # R1 sometimes leaks <think>...</think> blocks despite instructions.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I)
    content = content.strip()
    # Strip code fences if present
    content = re.sub(r"^```(?:html)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    return (content.strip() or None), "ok"


def call_with_cascade(system: str, user: str) -> Optional[str]:
    """Try each model in the cascade until one succeeds."""
    for model in OPENROUTER_MODELS:
        body, reason = call_openrouter(system, user, model)
        if body:
            return body
        # Auth failures apply to the whole key, not just one model — abort.
        if reason == "auth":
            raise RuntimeError("OPENROUTER_AUTH_FAILURE")
        # Rate-limit or server error: move to next model
        time.sleep(2)
    return None


# ── Quality gates (STRICT — non-negotiable) ───────────────────────────────────
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


def count_citations(html: str) -> int:
    """Count inline [Source N] tags."""
    return len(re.findall(r"\[Source\s*\d+\]", html))


def validate(body: str) -> Optional[str]:
    """Return None if body passes all gates; else a reason string."""
    wc = count_words(body)
    if wc < 400:
        return f"only {wc} words (need ≥400)"
    h2 = count_h2(body)
    if h2 < 4:
        return f"only {h2} <h2> sections (need ≥4)"
    if not has_sources_section(body):
        return "missing <h3>Sources</h3> section"
    if not has_blind_spots_section(body):
        return "missing <h2>Blind Spots</h2> section"
    cites = count_citations(body)
    if cites < 1:
        return f"no [Source N] citations found (need ≥1)"
    return None


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    print("=== generate_openrouter.py — Tier-3 fallback (OpenRouter free models) ===")

    if not OPENROUTER_API_KEY:
        print("  ⚠ OPENROUTER_API_KEY not set — skipping tier-3")
        print("  Get a FREE key at https://openrouter.ai/keys")
        print("  Then add to GitHub repo: Settings → Secrets → Actions → OPENROUTER_API_KEY")
        return 0

    if not ARTICLES_FILE.exists():
        print(f"  ⚠ {ARTICLES_FILE} not found — nothing to do")
        return 0

    articles = json.loads(ARTICLES_FILE.read_text(encoding="utf-8"))
    print(f"  Loaded {len(articles)} articles")

    eligible = [a for a in articles if needs_openrouter(a)]
    print(f"  Tier-3 eligible (scaffolds untouched by Gemini + Groq): {len(eligible)}")
    print(f"  Will process up to {MAX_PER_RUN} this run")
    print(f"  Tuning: T={TEMPERATURE} (LOCKED LOW), top_p={TOP_P}, presence={PRESENCE_PENALTY}")
    print(f"  Model cascade: {' → '.join(OPENROUTER_MODELS)}")

    if not eligible:
        print("  ✓ No articles need tier-3 processing — Gemini + Groq covered everything")
        return 0

    processed = 0
    upgraded  = 0
    rejected  = 0

    for art in eligible:
        if processed >= MAX_PER_RUN:
            print(f"  [INFO] Hit MAX_PER_RUN={MAX_PER_RUN} — remaining process next run")
            break
        processed += 1
        slug = art.get("slug", "(no-slug)")
        print(f"  → [{processed}/{min(len(eligible), MAX_PER_RUN)}] Processing: {slug[:60]}")

        try:
            body = call_with_cascade(SYSTEM_PROMPT, build_user_prompt(art))
        except RuntimeError as e:
            # Account-level error (401 invalid key) — abort whole run.
            print(f"\n[ABORT] {e} — tier-3 disabled for this run")
            print("[INFO] Gemini + Groq handled earlier tiers; scaffolds remain for next run")
            ARTICLES_FILE.write_text(
                json.dumps(articles, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return 0

        if not body:
            print("    [SKIP] All free models failed or rate-limited")
            time.sleep(INTER_CALL_SLEEP)
            continue

        # STRICT validation — no partial-quality output reaches the site
        reason = validate(body)
        if reason:
            print(f"    [REJECT] {reason} — article stays scaffold, will retry next run")
            rejected += 1
            time.sleep(INTER_CALL_SLEEP)
            continue

        # Commit upgrade
        wc = count_words(body)
        h2 = count_h2(body)
        cites = count_citations(body)
        art["body_html"]     = body
        art["body"]          = body
        art["word_count"]    = wc
        art["generated_by"]  = "openrouter-deepseek-r1"
        art["is_editorial"]  = True
        art["needs_gemini"]  = False
        upgraded += 1
        print(f"    ✓ {wc} words, {h2} H2, {cites} citations → {slug[:60]}")
        time.sleep(INTER_CALL_SLEEP)

    # Save
    ARTICLES_FILE.write_text(
        json.dumps(articles, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[DONE] Tier-3: {upgraded} upgraded, {rejected} rejected (failed quality gates), "
          f"{processed - upgraded - rejected} skipped (API issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
