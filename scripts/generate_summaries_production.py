#!/usr/bin/env python3
"""
generate_summaries.py — The Streamic
=====================================
Elite article engine: turns high-priority scaffold articles into
state-of-the-art broadcast & media technology features.

Changes from v1:
  • New SYSTEM_PROMPT — Senior Broadcast & Media Systems Architect persona
  • New 6-section article structure (Introduction, Technical Breakdown,
    How It Works in Real Life, Why It Matters, Reality Check, Future Outlook)
  • Target 800–1000 words with engagement-first writing rules
  • Execution gated on needs_gemini = True (set by rewrite_feed.py)
  • MAX_PER_RUN reduced to 5 (free-tier safe, high-quality focus)
  • REPROCESS_THRESHOLD raised to 700 words to match new target
  • All other config, retry logic, file handling unchanged
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

GROQ_MODEL          = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_FALLBACK_MODEL = os.environ.get("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant").strip()

GROQ_API_URL = os.environ.get(
    "GROQ_API_URL",
    "https://api.groq.com/openai/v1/chat/completions",
).strip()

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"
SUMMARIES_DIR = DATA_DIR / "summaries"

# Raised to match 800–1000 word target
REPROCESS_THRESHOLD = int(os.environ.get("REPROCESS_THRESHOLD", "700"))
REQUIRE_HEADINGS    = os.environ.get("REQUIRE_HEADINGS", "true").lower() in {"1", "true", "yes", "y"}

# ↓ 3–5 per run: free-tier safe, quality-first
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "5"))

REQUEST_TIMEOUT = int(os.environ.get("GROQ_TIMEOUT", "90"))
# Raised for 800–1000 word target
MAX_TOKENS  = int(os.environ.get("GROQ_MAX_TOKENS", "1400"))
TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.55"))

SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

_BANNED_GENERIC_PHRASES = [
    "in today\'s evolving landscape",
    "this highlights the importance of",
    "game-changing solution",
    "cutting-edge technology",
    "revolutionary approach",
    "exciting announcement",
    "it is worth noting",
]

_WORKFLOW_SIGNALS = [
    "ingest", "playout", "archive", "newsroom", "mcr", "pcr",
    "cdn", "viewer", "m\u0101m", "mam", "nrcs", "st 2110", "ndi", "sdi",
]

# ── Elite Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Senior Broadcast & Media Systems Architect, Technical Editor, and content specialist writing for The Streamic (thestreamic.in).

Your readers include CTOs, broadcast engineers, media technology directors, newsroom leads, playout specialists, post-production supervisors, and OTT platform architects. They want sharp analysis, useful workflow context, and an honest technical read — not a rewritten press release.

Your writing style:
- Write like a human expert explaining a system to a smart colleague during a real project discussion
- Use natural, varied sentence lengths — short punches mixed with longer technical reasoning
- Keep paragraphs short; white space improves readability
- Use concrete workflow examples instead of abstract claims
- Be candid about trade-offs, integration friction, vendor hype, and operational risk
- Keep the prose readable enough for non-engineers without dumbing down the technical content

Natural transitions you may use:
"In practice, this means..."
"For broadcast teams, the interesting question is..."
"Here's where it gets complicated..."
"This changes the calculus for..."
"The real bottleneck isn't X, it's Y."
"In practical terms..."
"Here's where things get interesting..."

ANTI-GENERIC RULES:
Never use phrases like:
- "In today's evolving landscape..."
- "This highlights the importance of..."
- "Game-changing solution..."
- "Cutting-edge technology..."
- "Revolutionary approach..."
- "Exciting announcement..."
- "It is worth noting..."

Every paragraph must contain either:
- a real technical explanation, or
- a real operational implication

READABILITY RULES:
- Keep paragraphs to roughly 2–5 lines
- Avoid repeating the same sentence structure
- Explain jargon in plain English when it first matters
- Make the article engaging to read, not dry or bloated

VENDOR REALISM RULE:
Use real systems where relevant rather than generic placeholders:
- Avid Media Composer, Nexis, MediaCentral, Cloud UX, Interplay
- Vizrt, Viz Engine, Viz Pilot, Chyron
- Pebble, Harmonic, Mediagenix
- EVS, Grass Valley, Ross, Sony
- Adobe Premiere Pro, DaVinci Resolve
- AWS Media Services, Azure, Google Cloud

SYSTEM FLOW RULE:
At least once in the article, explicitly describe a realistic end-to-end workflow:
Input → Processing → System → Output

Examples:
- ingest → AI tagging → MAM → newsroom search → playout
- live feed → ST 2110 network → production switcher → playout → CDN → viewer
"""


def build_user_prompt(title: str, source_text: str, category: str, topic_type: str, keywords: list) -> str:
    keywords_str = ", ".join(keywords) if keywords else "broadcast technology"

    depth_instruction = {
        "ai_metadata": (
            "Focus technical depth on AI inference pipelines, metadata schema design "
            "(Dublin Core, EBUCore, IPTC where relevant), confidence scoring, human-in-the-loop review, "
            "archive searchability, newsroom retrieval speed, and how AI tagging connects ingest, MAM/PAM, NRCS, and playout."
        ),
        "newsroom_workflow": (
            "Focus technical depth on NRCS architecture (Avid iNews, ENPS, Octopus, Dalet, MediaCentral, Cloud UX), "
            "MOS integration, rundown-to-production flow, wire and agency ingest, editorial collaboration, "
            "and the pressure points around speed-to-air, verification, and control-room coordination."
        ),
        "broadcast_infrastructure": (
            "Focus technical depth on SMPTE ST 2110 transport, PTP/IEEE 1588 timing, NMOS discovery/control, "
            "SDI-to-IP migration, hybrid SDI/IP design, signal integrity, multivendor interoperability, "
            "PCR/MCR routing, resilience, and operational fault domains."
        ),
        "streaming_delivery": (
            "Focus technical depth on HLS/DASH/CMAF packaging, CDN origin/edge design, ABR ladder strategy, "
            "end-to-end latency, DRM (Widevine, PlayReady, FairPlay), SSAI, player behaviour, monitoring, "
            "and how streaming architecture changes cost, quality, and scale."
        ),
        "cloud_production": (
            "Focus technical depth on AWS/Azure/GCP media orchestration, MediaConnect/MediaLive/MediaConvert equivalents, "
            "containerised or microservice-based workflows, storage and egress economics, failover logic, "
            "hybrid on-prem/cloud integration, and operational observability."
        ),
        "postproduction": (
            "Focus technical depth on editing workflows across Avid Media Composer, Adobe Premiere Pro, and DaVinci Resolve; "
            "shared storage performance (Nexis, SAN/NAS, object storage proxies), colour pipelines such as ACES and HDR mastering, "
            "audio mixing and loudness compliance, and handoff into finishing and distribution."
        ),
        "playout_automation": (
            "Focus technical depth on playlist scheduling, channel branding, automation architectures using Pebble, Harmonic, and Mediagenix, "
            "MCR redundancy, SCTE-35, graphics insertion, disaster recovery, compliance logging, and on-air resilience."
        ),
        "storage_management": (
            "Focus technical depth on online/nearline/archive tiers, NVMe vs SAN vs NAS vs object storage, "
            "Avid Nexis and other shared-storage environments, LTO and deep archive workflows, ingest pipeline design, "
            "MAM integration, and retrieval SLAs for live and historical content."
        ),
    }.get(topic_type, (
        "Focus technical depth on the most relevant parts of the broadcast and media chain: live production, newsroom systems, "
        "editing, graphics, storage, playout, delivery, and cloud integration. Use only the layers that genuinely fit the story."
    ))

    return f"""Write a high-quality technical article for The Streamic based on the following news item.

Title: {title}
Category: {category}
Topic type: {topic_type}
Technical keywords detected: {keywords_str}

Source content:
{source_text}

---

{depth_instruction}

---

EDITORIAL GOAL:
Produce an article that feels useful to a CTO, credible to a broadcast engineer, and still clear to a smart non-engineer. The article must be interesting to read, technically grounded, and operationally useful.

COVERAGE RULE:
Where relevant, connect the story to real broadcast and media systems such as:
- live production and PCR workflows
- MCR and playout control
- Vizrt / Chyron graphics
- EVS replay or live operations
- Avid Nexis / MediaCentral / Cloud UX / Interplay
- Adobe Premiere Pro / DaVinci Resolve / Avid Media Composer
- Pebble / Harmonic / Mediagenix playout
- ST 2110 / NMOS / NDI / SDI / AES67 / Dante
- HLS / DASH / CMAF / CDN / DRM / SSAI
- AWS Media Services and hybrid cloud workflows

Do not force all of these. Use only what is genuinely relevant to the story.

ARTICLE STRUCTURE — use exactly these six <h2> sections:

<h2>Why This Matters Right Now</h2>
Hook the reader quickly. Do not summarise the press release. Explain why a broadcast engineer, operations lead, or CTO should care now. What pressure, bottleneck, or workflow problem does this story speak to? 2–3 paragraphs.

<h2>Under the Hood: How It Actually Works</h2>
Give the technical breakdown. Explain where this sits in the signal path, data flow, or operational stack. Show the relevant systems and how they connect end-to-end. Compare the likely before-and-after architecture where useful. Include at least one explicit system flow in the form Input → Processing → System → Output. 3–4 paragraphs.

<h2>What This Looks Like in a Real Broadcast Operation</h2>
Describe a realistic workflow scenario in a newsroom, control room, ingest-to-playout chain, live production, post-production, or cloud environment — whichever best fits. Make it concrete and practical. 2–3 paragraphs.

<h2>The Practical Impact: Cost, Speed, and Scale</h2>
Explain where the real ROI is. What gets faster, cheaper, more reliable, or easier to scale? What manual work, infrastructure burden, or operational risk is reduced — and what new dependencies might be introduced? 2–3 paragraphs.

<h2>The Reality Check</h2>
Be honest. What is still unclear, overstated, incomplete, or difficult to integrate? What vendor bias, lock-in, operational complexity, skills gap, or standards challenge should technical teams keep in mind? 2 paragraphs.

<h2>Where This Goes from Here</h2>
Give the strategic read. Is this something teams should adopt now, test in a pilot, or watch carefully? What does it suggest about where broadcast and media technology are heading next? 1–2 paragraphs.

---

OUTPUT REQUIREMENTS:

1. Return ONLY valid HTML fragments. No <!DOCTYPE>, no <html>, no <head>. Start directly with an <h2> or <p> tag.
2. All prose paragraphs must sit inside the six sections above. No bullet lists anywhere.
3. Target 800–1000 words total. Dense, useful, readable.
4. Use correct broadcast terminology throughout where relevant: ST 2110, NMOS, NDI, SDI, AES67, HLS, DASH, CMAF, ABR, MAM, PAM, NRCS, MCR, PCR, playout, ingest, archive, graphics, replay, OTT, etc.
5. Do NOT copy or paraphrase the source sentence-by-sentence. Fully transform it into original analysis.
6. No byline, no article title, no preamble — body sections only.
7. Keep the tone authoritative but readable. No marketing language. No filler.
8. At least two paragraphs should include concrete vendor or system references where relevant rather than generic terms.
9. Every paragraph must contain either a technical explanation or a real operational implication.
10. Keep paragraphs compact and easy to scan.

Begin the article now:
"""


# ── Helpers (unchanged from v1) ───────────────────────────────────────────────

def needs_reprocessing(article: dict[str, Any]) -> bool:
    """Return True if this article needs Groq enrichment."""
    # Must be flagged by rewrite_feed.py
    if not article.get("needs_gemini"):
        return False
    # Must not already be editorial-quality
    if article.get("is_editorial") or article.get("editorial"):
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


def count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return len(text.split()) if text else 0


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def extract_source_text(article: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("dek", "meta_description", "card_summary"):
        value = article.get(key)
        if value:
            parts.append(strip_html(str(value)))
    body = article.get("body_html", "")
    if body:
        plain = strip_html(body)
        if len(plain) > 80:
            parts.append(plain)
    source_url = article.get("source_url")
    if source_url:
        parts.append(f"Original source URL: {source_url}")
    source_domain = article.get("source_domain")
    if source_domain:
        parts.append(f"Source domain: {source_domain}")
    title = article.get("title", "")
    if not parts and title:
        parts.append(title)
    merged = "\n\n".join([p for p in parts if p]).strip()
    return merged[:12000]


def extract_message_content(data: dict[str, Any]) -> Optional[str]:
    try:
        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
            joined = "".join(parts).strip()
            return joined or None
        return None
    except Exception:
        return None


def post_chat_completion(
    model: str, title: str, source_text: str,
    category: str, topic_type: str, keywords: list
) -> Optional[str]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt(title, source_text, category, topic_type, keywords)},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "n": 1,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        body = resp.text[:500].replace("\n", " ")
        raise requests.exceptions.HTTPError(
            f"{resp.status_code} {resp.reason} — {body}", response=resp
        )
    return extract_message_content(resp.json())


def call_groq(
    title: str, source_text: str, category: str,
    topic_type: str = "", keywords: list = None
) -> Optional[str]:
    if not GROQ_API_KEY:
        print("  [WARN] GROQ_API_KEY not set — skipping API call")
        return None

    keywords = keywords or []
    models_to_try = []
    for m in (GROQ_MODEL, GROQ_FALLBACK_MODEL):
        if m and m not in models_to_try:
            models_to_try.append(m)

    for model_index, model in enumerate(models_to_try, start=1):
        for attempt in range(1, 3):
            try:
                if attempt > 1:
                    time.sleep(3)
                result = post_chat_completion(model, title, source_text, category, topic_type, keywords)
                if result:
                    if model_index > 1:
                        print(f"    [INFO] Used fallback model: {model}")
                    return result
                return None
            except requests.exceptions.HTTPError as e:
                msg = str(e)
                if any(code in msg for code in ("429", "500", "502", "503", "504")):
                    print(f"  [WARN] Temporary Groq HTTP issue on {model}, attempt {attempt}/2: {msg[:220]}")
                    continue
                print(f"  [ERROR] Groq HTTP error on {model}: {msg[:260]}")
                break
            except requests.exceptions.RequestException as e:
                print(f"  [WARN] Network/API error on {model}, attempt {attempt}/2: {e}")
                continue
            except Exception as e:
                print(f"  [ERROR] Groq call failed on {model}: {e}")
                break
    return None


def build_dek(title: str, body_html: str) -> str:
    plain = strip_html(body_html)
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    dek = " ".join(sentences[:2]).strip()
    if not dek:
        dek = title.strip()
    if len(dek) > 160:
        dek = dek[:157].rstrip() + "..."
    return dek


def build_meta_description(title: str, dek: str) -> str:
    base = f"{title}. {dek}".strip()
    if len(base) > 155:
        base = base[:152].rstrip() + "..."
    return base


def build_card_summary(body_html: str) -> str:
    match = re.search(
        r"<h2[^>]*>.*?</h2>\s*<p[^>]*>(.*?)</p>",
        body_html or "",
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        text = strip_html(match.group(1))
        if len(text) > 200:
            text = text[:197].rstrip() + "..."
        return text
    match = re.search(r"<p[^>]*>(.*?)</p>", body_html or "", re.DOTALL | re.IGNORECASE)
    if match:
        text = strip_html(match.group(1))
        if len(text) > 200:
            text = text[:197].rstrip() + "..."
        return text
    return ""


def save_summary_file(
    slug: str, title: str, body_html: str, word_count: int,
    dek: str, card_summary: str, meta_description: str,
) -> None:
    summary_file = SUMMARIES_DIR / f"{slug}.json"
    with open(summary_file, "w", encoding="utf-8") as sf:
        json.dump(
            {
                "slug": slug, "title": title, "body_html": body_html,
                "word_count": word_count, "dek": dek,
                "card_summary": card_summary, "meta_description": meta_description,
            },
            sf, ensure_ascii=False, indent=2,
        )



def has_too_many_generic_phrases(html: str) -> bool:
    lower = (html or "").lower()
    hits = sum(1 for phrase in _BANNED_GENERIC_PHRASES if phrase in lower)
    return hits >= 2


def has_workflow_context(html: str) -> bool:
    lower = (html or "").lower()
    return sum(1 for token in _WORKFLOW_SIGNALS if token in lower) >= 2


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not ARTICLES_FILE.exists():
        print(f"[ERROR] {ARTICLES_FILE} not found — run rewrite_feed.py first")
        return

    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles: list[dict[str, Any]] = json.load(f)

    print(f"[INFO] Loaded {len(articles)} articles from generated_articles.json")

    # Only process articles flagged needs_gemini=True by rewrite_feed.py
    to_process = [a for a in articles if needs_reprocessing(a)]
    print(
        f"[INFO] {len(to_process)} articles eligible "
        f"(needs_gemini=True, not yet editorial, word_count < {REPROCESS_THRESHOLD})"
    )
    print(f"[INFO] Will process up to {MAX_PER_RUN} this run (free-tier safe)")

    if not to_process:
        print("[INFO] Nothing to process — all eligible articles already meet quality threshold")
        return

    processed = 0
    changed   = 0

    for article in articles:
        if not needs_reprocessing(article):
            continue
        if processed >= MAX_PER_RUN:
            print(f"[INFO] Hit MAX_PER_RUN={MAX_PER_RUN} — remaining will process on next run")
            break

        slug       = article.get("slug") or article.get("id") or "unknown"
        title      = article.get("title") or "Untitled"
        category   = article.get("category") or "Broadcast Technology"
        topic_type = article.get("topic_type") or ""
        keywords   = article.get("technical_keywords") or []

        print(f"  → [{processed + 1}/{min(len(to_process), MAX_PER_RUN)}] Processing: {slug}")
        print(f"      topic_type={topic_type}  keywords={keywords[:4]}")

        source_text = extract_source_text(article)
        new_body    = call_groq(title, source_text, category, topic_type, keywords)

        if not new_body:
            print(f"    [SKIP] Groq returned nothing for: {slug}")
            processed += 1
            time.sleep(1.5)
            continue

        wc       = count_words(new_body)
        h2_count = len(re.findall(r"<h2\b", new_body, flags=re.IGNORECASE))

        # Quality gates — updated for 800–1000 word target
        if wc < 600:
            print(f"    [WARN] Generated body only {wc} words (target 800–1000) — skipping")
            processed += 1
            time.sleep(1.5)
            continue

        if h2_count < 6:
            print(f"    [WARN] Generated body has {h2_count}/6 H2 sections — skipping")
            processed += 1
            time.sleep(1.5)
            continue

        if has_too_many_generic_phrases(new_body):
            print("    [WARN] Generated body still contains too many generic phrases — skipping")
            processed += 1
            time.sleep(1.5)
            continue

        if not has_workflow_context(new_body):
            print("    [WARN] Generated body lacks enough workflow context — skipping")
            processed += 1
            time.sleep(1.5)
            continue

        article["body_html"]        = new_body
        article["word_count"]       = wc
        article["is_editorial"]     = True
        article["editorial"]        = True
        article["analysis_level"]   = "elite_article"
        article["generated_by"]     = "generate_summaries_groq"
        article["needs_gemini"]     = False   # mark as done
        article["dek"]              = build_dek(title, new_body)
        article["meta_description"] = build_meta_description(title, article["dek"])
        article["card_summary"]     = build_card_summary(new_body)

        save_summary_file(
            slug=slug, title=title, body_html=new_body, word_count=wc,
            dek=article["dek"], card_summary=article["card_summary"],
            meta_description=article["meta_description"],
        )

        print(f"    ✓ {wc} words, {h2_count} sections → {slug}")

        processed += 1
        changed   += 1
        time.sleep(2.5)   # slightly longer pause for larger token payloads

    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed} articles → saved to {ARTICLES_FILE}")
    else:
        print("\n[DONE] No articles changed (all Groq calls returned empty or below quality threshold)")


if __name__ == "__main__":
    main()
