#!/usr/bin/env python3
"""
admin_publish.py — Streamic admin dashboard backend (GitHub Actions runner).

Two modes, dispatched via workflow_dispatch input `action`:

  ACTION=generate
    Reads inputs: model, source_url, source_title, category, word_target
    Calls Gemini or Mistral with the FACTUAL_SAFETY_BLOCK prompt
    Writes the generated article JSON to /tmp/generated-article.json
    GitHub Actions uploads this as artifact "generated-article" for the
    dashboard to download and populate the editor with.

  ACTION=publish
    Reads input: article_payload (base64-encoded JSON from dashboard)
    Decodes the payload (slug, title, category, body_html, source_url, etc.)
    Adds the article to data/generated_articles.json
    Renders docs/articles/{slug}.html using build.py's article_page() so the
    full Streamic header/footer/CSS template wraps the content
    Commits and pushes — site rebuilds via the existing build workflow

The dashboard NEVER holds API keys for Gemini/Mistral. They live in GitHub
Secrets and only this script (running in a workflow runner) can read them.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = REPO_ROOT / "data" / "generated_articles.json"
ARTICLES_DIR = REPO_ROOT / "docs" / "articles"
SCRIPTS_DIR = REPO_ROOT / "scripts"
ARTIFACT_OUT = Path("/tmp/generated-article.json")

# ── Env / config ───────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

GEMINI_MODEL = "gemini-2.0-flash"
MISTRAL_MODEL = "mistral-large-latest"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Factual safety prompt (fallback if file missing) ───────────────────────
DEFAULT_SAFETY = """You are a Senior Technical Editor for The Streamic, an
independent broadcast and media-IT publication. Write a high-quality,
factually accurate article based ONLY on the source material provided.

CRITICAL RULES:
- Use ONLY facts present in the source. Do NOT invent vendor names, product
  features, or specifications.
- Avoid filler phrases like "in today's fast-paced world" or "revolutionary."
- Do NOT use "[Source N]" inline citation markers.
- Use <h2> and <h3> for structure. Use <p> for paragraphs. No <h1>.
- Where the source is vague, say so explicitly rather than fabricating detail.
- Output clean HTML fragments only — no <!DOCTYPE>, no <html>, no <body>.

ARTICLE STRUCTURE — use these sections in order:
<h2>The Quick Hit</h2>      (1 paragraph: what happened, why it matters now)
<h2>Technical Deep Dive</h2> (2-3 paragraphs: how it works, what's specified)
<h2>Deployment Roadmap</h2>  (1-2 paragraphs: how teams would adopt this)
<h2>Operational Wins</h2>    (1 paragraph: real-world impact for engineers)

Begin generating the article now based ONLY on the source text provided.
"""


def load_safety_prompt() -> str:
    """Load factual_safety.txt from scripts/ if available, else use default."""
    safety_file = SCRIPTS_DIR / "factual_safety.txt"
    if safety_file.exists():
        return safety_file.read_text(encoding="utf-8")
    return DEFAULT_SAFETY


# ───────────────────────────────────────────────────────────────────────────
#  SOURCE FETCH (lightweight scrape of the original article)
# ───────────────────────────────────────────────────────────────────────────
def fetch_source_text(url: str, max_chars: int = 8000) -> str:
    """Fetch and lightly clean the source article text."""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StreamicAdminBot/1.0)"},
            timeout=20,
        )
        r.raise_for_status()
        html = r.text
        # Strip scripts, styles, nav, footer, aside
        html = re.sub(r"<(script|style|nav|footer|aside|form)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        # Strip all tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[warn] Source fetch failed: {e}", file=sys.stderr)
        return ""


# ───────────────────────────────────────────────────────────────────────────
#  GENERATE — call Gemini or Mistral
# ───────────────────────────────────────────────────────────────────────────
def call_gemini(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in repo secrets")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": system_prompt + "\n\n---\n\n" + user_prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.35,
            "topP": 0.9,
            "maxOutputTokens": max_tokens,
        },
    }
    r = requests.post(url, json=payload, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Gemini API error {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini returned unexpected shape: {json.dumps(data)[:300]}") from e


def call_mistral(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set in repo secrets")
    url = "https://api.mistral.ai/v1/chat/completions"
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.35,
        "top_p": 0.9,
        "max_tokens": max_tokens,
    }
    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"Mistral API error {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Mistral returned unexpected shape: {json.dumps(data)[:300]}") from e


def call_groq(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    """Groq Cloud — most generous free tier (14,400 req/day on llama-3.3-70b).

    Free at https://console.groq.com/keys — set GROQ_API_KEY in repo secrets.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set in repo secrets")
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.35,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "frequency_penalty": 0.2,
    }
    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"Groq API error {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Groq returned unexpected shape: {json.dumps(data)[:300]}") from e


def make_slug(date_str: str, category: str, title: str) -> str:
    title_slug = re.sub(r"[^\w\s-]", "", title.lower())
    title_slug = re.sub(r"\s+", "-", title_slug).strip("-")
    return f"{date_str}-{category}-{title_slug[:60].rstrip('-')}"


def do_generate(args: dict) -> None:
    """ACTION=generate — call the chosen LLM and write artifact for dashboard."""
    model = (args.get("model") or "groq").lower()
    source_url = args.get("source_url", "").strip()
    source_title = args.get("source_title", "").strip()
    category = args.get("category", "newsroom").strip()
    word_target = int(args.get("word_target") or "800")

    print(f"[generate] model={model} url={source_url[:80]} cat={category} target={word_target}w")

    if not source_url or not source_title:
        raise RuntimeError("Missing source_url or source_title")

    # 1. Fetch source
    print(f"[generate] Fetching source page…")
    source_text = fetch_source_text(source_url)
    if not source_text:
        # Fall back to using the title alone — model has less context but won't crash
        source_text = f"(Source page could not be fetched. Working from headline only.)\n\nHeadline: {source_title}"

    # 2. Build prompts
    system_prompt = load_safety_prompt()
    user_prompt = (
        f"SOURCE ARTICLE\n"
        f"Title: {source_title}\n"
        f"URL: {source_url}\n"
        f"Category: {category}\n"
        f"Target length: ~{word_target} words.\n\n"
        f"--- SOURCE TEXT ---\n{source_text}\n--- END SOURCE ---\n\n"
        f"Write a {word_target}-word Streamic editorial analysis based ONLY on the above source. "
        f"Use the section structure from the system prompt. Output HTML fragments only."
    )

    # 3. Call the chosen model
    print(f"[generate] Calling {model} ({len(user_prompt)} chars in prompt)…")
    if model == "gemini":
        body_html = call_gemini(system_prompt, user_prompt)
    elif model == "groq":
        body_html = call_groq(system_prompt, user_prompt)
    else:  # default: mistral
        body_html = call_mistral(system_prompt, user_prompt)

    # 4. Clean and structure
    # Strip any code fences the model might add
    body_html = re.sub(r"^```(?:html)?\s*", "", body_html.strip())
    body_html = re.sub(r"\s*```$", "", body_html)
    # Strip Mistral's [Source N] markers (defensive — prompt forbids them)
    body_html = re.sub(r"\s*\[Source\s+\d+\]", "", body_html)
    # Strip trailing Sources/References block if model added one
    body_html = re.sub(
        r"\n*<h[23]>\s*(?:Sources?|References)\s*</h[23]>\s*.*?$",
        "",
        body_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    word_count = len(re.sub(r"<[^>]+>", " ", body_html).split())
    print(f"[generate] Generated {word_count} words")

    # 5. Write artifact for dashboard
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    slug = make_slug(today, category, source_title)
    result = {
        "slug": slug,
        "title": source_title,
        "category": category,
        "source_url": source_url,
        "body_html": body_html,
        "word_count": word_count,
        "generated_by": f"admin-{model}",
        "model": model,
    }
    ARTIFACT_OUT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[generate] Wrote artifact to {ARTIFACT_OUT}")


# ───────────────────────────────────────────────────────────────────────────
#  PUBLISH — wrap with build.py article_page() and commit
# ───────────────────────────────────────────────────────────────────────────
def do_publish(args: dict) -> None:
    """ACTION=publish — decode payload, render via article_page(), commit."""
    payload_b64 = args.get("article_payload", "").strip()
    if not payload_b64:
        raise RuntimeError("Missing article_payload")

    # Decode dashboard payload
    try:
        payload_json = base64.b64decode(payload_b64).decode("utf-8")
        article = json.loads(payload_json)
    except Exception as e:
        raise RuntimeError(f"Could not decode article_payload: {e}") from e

    # Required fields
    for k in ("slug", "title", "category", "body_html"):
        if not article.get(k):
            raise RuntimeError(f"Missing required field: {k}")

    slug = article["slug"]
    print(f"[publish] slug={slug}")
    print(f"[publish] title={article['title'][:80]}")
    print(f"[publish] category={article['category']}")
    print(f"[publish] body_html: {len(article['body_html'])} chars")

    # Compute word_count
    body_text = re.sub(r"<[^>]+>", " ", article["body_html"])
    article["word_count"] = len(body_text.split())

    # Defaults for fields build.py expects
    article.setdefault("published", "")
    article.setdefault("source_domain", "")
    article.setdefault("source_url", "")
    article.setdefault("generated_by", "admin-dashboard")
    article.setdefault("is_editorial", False)
    article.setdefault("image_url", "")

    # 1. Append to data/generated_articles.json (replace if slug exists)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DATA_FILE.exists():
        all_articles = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        all_articles = []

    existing_idx = next((i for i, a in enumerate(all_articles) if a.get("slug") == slug), -1)
    if existing_idx >= 0:
        all_articles[existing_idx] = article
        print(f"[publish] Replaced existing entry at index {existing_idx}")
    else:
        all_articles.insert(0, article)
        print(f"[publish] Inserted new entry at top")

    DATA_FILE.write_text(json.dumps(all_articles, indent=2), encoding="utf-8")
    print(f"[publish] Updated {DATA_FILE} ({len(all_articles)} total articles)")

    # 2. Render the article HTML using build.py's article_page()
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import build  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"Cannot import scripts/build.py: {e}") from e

    # Mark this article as a "keeper" for Stage 1 by treating it as gpt_manual_editorial
    # OR by ensuring it survives the keep rule. We take the conservative approach:
    # set is_editorial=True so it survives the Stage 1 purge.
    article["is_editorial"] = True

    html = build.article_page(article)

    # 3. Write the HTML file
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.html"
    # Add HAND_AUTHORED marker so build.py never overwrites this article
    if "<!-- HAND_AUTHORED -->" not in html:
        html = html.replace("<head>", "<head>\n<!-- HAND_AUTHORED -->", 1)
    out_path.write_text(html, encoding="utf-8")
    print(f"[publish] Wrote {out_path} ({len(html)} bytes)")

    print(f"[publish] DONE. Article will be live after next site rebuild.")


# ───────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ───────────────────────────────────────────────────────────────────────────
def main():
    action = os.environ.get("ACTION", "").lower().strip()
    if not action:
        raise RuntimeError("ACTION env var required (generate|publish)")

    # All workflow inputs come in as INPUT_* env vars (lowercase)
    args = {
        k[6:].lower(): v
        for k, v in os.environ.items()
        if k.startswith("INPUT_")
    }

    if action == "generate":
        do_generate(args)
    elif action == "publish":
        do_publish(args)
    else:
        raise RuntimeError(f"Unknown ACTION: {action}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        sys.exit(1)
