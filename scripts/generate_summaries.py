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

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

# Shared factual-safety block — single source of truth across all generators
try:
    import sys as _sys_ps
    _sys_ps.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prompt_safety import FACTUAL_SAFETY_BLOCK
except ImportError:
    FACTUAL_SAFETY_BLOCK = ""

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
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "8"))

REQUEST_TIMEOUT = int(os.environ.get("GROQ_TIMEOUT", "90"))
# Raised for 800–1000 word target
MAX_TOKENS  = int(os.environ.get("GROQ_MAX_TOKENS", "1400"))
TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.35"))
TOP_P              = float(os.environ.get("GROQ_TOP_P", "0.9"))
FREQUENCY_PENALTY  = float(os.environ.get("GROQ_FREQUENCY_PENALTY", "0.2"))

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

SYSTEM_PROMPT = FACTUAL_SAFETY_BLOCK + """

═══════════════════════════════════════════════════════════════════════════
ROLE & OUTPUT STRUCTURE
═══════════════════════════════════════════════════════════════════════════

You are a Senior Broadcast & Media Systems Architect writing a
publication-ready analysis article for The Streamic (thestreamic.in)
based on the source press release provided.

Your readers: CTOs, broadcast engineers, media technology directors, newsroom leads, playout specialists, post-production supervisors, and OTT platform architects. They want clear, factual analysis — not a rewritten press release, not marketing hype, not invented technical detail.

═══════════════════════════════════════════════════════════════════════════
STRICT FACTUAL SAFETY RULES — THESE ARE NON-NEGOTIABLE
═══════════════════════════════════════════════════════════════════════════

1. NEVER guess or assume what a product or company does. Only use capabilities
   that are EXPLICITLY stated in the source text provided below.

2. NEVER assign a product category (playout, MCR, NRCS, storage, scheduling,
   traffic, graphics, MAM, PAM, switcher, router, etc.) unless the press
   release clearly states that category. If the source does not say what
   category a product belongs to, describe it using neutral terms:
   "solution", "platform", "suite", "framework", "product", "system".

3. NEVER misclassify vendors. Known correct categorizations to respect:
   • Mediagenix — scheduling / rights / metadata / BMS. NOT playout. NOT MCR.
   • Avid iNews, ENPS, Octopus, Dalet — NRCS (newsroom computer systems).
   • Avid Media Composer — NLE (editing).
   • Avid Nexis — shared storage (not MAM, not archive).
   • Avid MediaCentral — collaboration / workflow layer.
   • Vizrt Viz Engine, Chyron — real-time graphics / render engines.
   • Vizrt Viz Pilot — graphics control (not playout).
   • Pebble, Imagine, Grass Valley Morpheus, Harmonic Polaris — playout automation.
   • Harmonic VOS — video processing / encoding / CDN delivery.
   • EVS — live production / replay servers.
   • Grass Valley, Ross, Sony — switchers, cameras, routing.
   • AWS MediaLive, MediaPackage, MediaConvert, MediaTailor — cloud media services.
   If a vendor is not on this safe list, describe their product using ONLY
   the words the press release itself uses. Do not infer its category.

4. NEVER invent integrations, standards support, or features. Do NOT claim
   the product supports ST 2110, SCTE-35, NMOS, NDI, AES67, SMPTE standards,
   cloud deployment, AI features, or any specific protocol unless the source
   text explicitly names that standard or feature. If the press release does
   not mention ST 2110, do not write "supports ST 2110." Same for every
   other technical claim.

5. NEVER add competitor names, comparison vendors, or adjacent systems
   unless they appear in the source text. If the release mentions only
   Bitcentral, do not mention Avid, Dalet, ENPS, or Octopus for "context."

6. If the source text is vague or ambiguous, STAY VAGUE. Do not fill the
   gap with plausible-sounding technical detail. Write conservatively.

7. NEVER invent workflow diagrams that involve specific named vendors not
   in the source. Generic pipelines (ingest → processing → playout → CDN)
   are acceptable ONLY if you do not name specific products at each stage.

═══════════════════════════════════════════════════════════════════════════
ARTICLE STYLE REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════

Tone: simple, factual, practical. Newsroom-friendly. Professional.
Neutral journalistic voice — do NOT praise, endorse, or promote the vendor.
Simply explain what they announced and why it matters to broadcasters.

Structure:
  1. Short intro summarizing what the vendor announced (2 short paragraphs).
  2. Key themes of the announcement (2–4 short sections with <h2> headings).
  3. Product/solution breakdown using ONLY capabilities the release states.
  4. Practical impact for broadcasters, media organizations, or operations.

Readability:
- Paragraphs 2–5 lines each.
- Explain jargon in plain English the first time a term appears.
- Short punchy sentences mixed with longer analytical ones.
- Avoid hype phrases: "game-changing", "cutting-edge", "revolutionary",
  "exciting", "in today's evolving landscape", "it is worth noting",
  "this highlights the importance of".

Every paragraph must contain either:
- a fact drawn directly from the source text, OR
- a genuinely grounded operational implication for broadcasters.

═══════════════════════════════════════════════════════════════════════════
SAFETY OVERRIDE
═══════════════════════════════════════════════════════════════════════════

If any part of the press release is unclear or you are uncertain about a
technical claim, WRITE CONSERVATIVELY. Skip the detail. Better to say
less than to invent something wrong. A factual 700-word article is worth
more than an impressive 1000-word article that misclassifies a vendor.

ARTICLE STRUCTURE — use exactly these six <h2> sections in this order,
with the EXACT heading text provided (do NOT substitute synonyms or
rearrange the header wording):

<h2>{H1}</h2>
Hook the reader quickly. Do not summarise the press release. Explain why a broadcast engineer, operations lead, or CTO should care now. What pressure, bottleneck, or workflow problem does this story speak to? 2–3 paragraphs.

<h2>{H2}</h2>
Give the technical breakdown using ONLY capabilities the source text states. Explain where this fits in a general broadcast workflow using generic stage names (ingest, processing, playout, delivery) — do NOT invent specific named vendors at each stage unless they appear in the source. If the source is too vague to support a technical breakdown, keep this section brief and factual rather than filling it with invented detail. 2–3 paragraphs.

<h2>{H3}</h2>
Describe a realistic workflow scenario in a newsroom, control room, ingest-to-playout chain, live production, post-production, or cloud environment — whichever best fits. Make it concrete and practical. 2–3 paragraphs.

<h2>{H4}</h2>
Explain where the real ROI is. What gets faster, cheaper, more reliable, or easier to scale? What manual work, infrastructure burden, or operational risk is reduced — and what new dependencies might be introduced? 2–3 paragraphs.

<h2>{H5}</h2>
Be honest. What is still unclear, overstated, incomplete, or difficult to integrate? What vendor bias, lock-in, operational complexity, skills gap, or standards challenge should technical teams keep in mind? 2 paragraphs.

<h2>{H6}</h2>
Give the strategic read. Is this something teams should adopt now, test in a pilot, or watch carefully? What does it suggest about where broadcast and media technology are heading next? 1–2 paragraphs.

Begin generating the article now based ONLY on the source text provided.
"""


# ── Rotating section headers (AdSense templated-content compliance) ──────────
# Each of the six section SLOTS has the same editorial function across every
# article, but we rotate the exact HEADING TEXT across a pool of synonyms so
# that no single phrase (e.g. "Why This Matters Right Now") recurs across
# many articles at scale. AdSense flags repeated H2 headers across 30+
# articles as templated content; this rotation breaks that pattern while
# preserving editorial consistency.
#
# Rotation is deterministic per-article (seeded by slug+title hash) so the
# same article always regenerates with the same headers — no churn in
# Search Console from header text drifting between builds.
SECTION_HEADER_POOL = {
    "H1": [  # Slot 1: the editorial hook
        "Why This Matters Right Now",
        "The Signal Behind the Announcement",
        "What Broadcasters Should Care About",
        "The Strategic Context",
        "Reading Between the Press-Release Lines",
        "Why Engineering Teams Are Watching This",
    ],
    "H2": [  # Slot 2: technical breakdown
        "Under the Hood: How It Actually Works",
        "The Technical Architecture",
        "Inside the Technology Stack",
        "How the Integration Actually Works",
        "The Engineering Layer",
        "What's Really Happening in the Pipeline",
    ],
    "H3": [  # Slot 3: operational scenario
        "What This Looks Like in a Real Broadcast Operation",
        "In a Live Production Environment",
        "A Practical Workflow Scenario",
        "How This Plays Out in the Control Room",
        "In the Newsroom and Post Bay",
        "Where This Lands in Daily Operations",
    ],
    "H4": [  # Slot 4: business impact
        "The Practical Impact: Cost, Speed, and Scale",
        "Cost, Speed, and Operational Scale",
        "Where the ROI Actually Lives",
        "The Business Case in Plain Numbers",
        "Operational Wins and Trade-Offs",
        "What This Changes for the Bottom Line",
    ],
    "H5": [  # Slot 5: honest critique
        "The Reality Check",
        "What the Press Release Didn't Say",
        "Caveats and Open Questions",
        "The Engineering Gotchas",
        "What to Verify Before Deploying",
        "The Honest Read",
    ],
    "H6": [  # Slot 6: strategic forward-look
        "Where This Goes from Here",
        "The Road Ahead",
        "What Comes Next for Broadcast Teams",
        "The Strategic Outlook",
        "Looking Beyond the Launch",
        "What Teams Should Watch Next",
    ],
}


def _pick_headers(seed_text: str) -> dict:
    """Deterministically pick one header per slot from SECTION_HEADER_POOL.

    Seeding by slug+title hash ensures the same article always gets the
    same headers on regeneration — stable across builds, which Google
    Search Console prefers (no thrashing on H2 changes).
    """
    seed_int = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed_int)
    return {slot: rng.choice(options) for slot, options in SECTION_HEADER_POOL.items()}


def build_system_prompt(slug: str = "", title: str = "") -> str:
    """Return SYSTEM_PROMPT with rotating H2 headers substituted for this article."""
    seed = f"{slug}|{title}"
    headers = _pick_headers(seed) if seed.strip("|") else _pick_headers("default")
    return SYSTEM_PROMPT.format(**headers)


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

---

OUTPUT REQUIREMENTS:

1. Return ONLY valid HTML fragments. No <!DOCTYPE>, no <html>, no <head>. Start directly with an <h2> or <p> tag.
2. All prose paragraphs must sit inside the six sections above. No bullet lists anywhere.
3. Target 800–1000 words total. Dense, useful, readable.
4. Use correct broadcast terminology throughout where relevant: ST 2110, NMOS, NDI, SDI, AES67, HLS, DASH, CMAF, ABR, MAM, PAM, NRCS, MCR, PCR, playout, ingest, archive, graphics, replay, OTT, etc.
5. Do NOT copy or paraphrase the source sentence-by-sentence. Fully transform it into original analysis.
6. No byline, no article title, no preamble — body sections only.
7. Keep the tone authoritative but readable. No marketing language. No filler.
8. CRITICAL: Do NOT add vendor or product names that are NOT in the source text. If the press release only names Bitcentral, do not mention Avid, Vizrt, Mediagenix, Pebble, Harmonic, or any other vendor to "add context." Adding unrelated vendor names is the #1 cause of factual errors in AI-generated broadcast articles.
9. Every paragraph must contain either a technical explanation or a real operational implication.
10. Keep paragraphs compact and easy to scan.

Begin the article now:
"""


# ── Helpers (unchanged from v1) ───────────────────────────────────────────────

def needs_reprocessing(article: dict[str, Any]) -> bool:
    """Return True if this article needs Groq enrichment.

    GEMINI-FIRST PRIORITY: If generated_by starts with 'gemini', skip —
    Gemini is the preferred model. Groq only fills the gaps Gemini missed
    (typically because Gemini hit its daily quota cap).

    SELF-HEALING: detects scaffolds by generated_by, NOT by needs_gemini flag.
    """
    gen_by = (article.get("generated_by") or "").lower()

    # Gemini-first: never overwrite a Gemini-generated article with Groq.
    # Tier-1 Mistral output: sacred.
    if gen_by.startswith("mistral"):
        return False

    if gen_by.startswith("gemini"):
        return False

    # DeepSeek/OpenRouter-generated articles are also protected.
    if "deepseek" in gen_by or "openrouter" in gen_by:
        return False

    is_scaffold = gen_by in ("", "rewrite_feed_local", "rewrite_feed")

    # Editorial content is protected across all tiers.
    if article.get("is_editorial") or article.get("editorial"):
        if not is_scaffold:
            return False
        # Even scaffolds marked editorial are protected — these are
        # typically hand-authored stubs awaiting manual expansion.
        return False

    if not is_scaffold:
        if (article.get("is_editorial") or article.get("editorial")):
            return False

    body = article.get("body_html", "") or ""
    wc   = int(article.get("word_count", 0) or 0)

    if is_scaffold:
        if not body or len(body.strip()) < 100:
            return True
        if wc < REPROCESS_THRESHOLD:
            return True
        if REQUIRE_HEADINGS and "<h2" not in body.lower():
            return True
        return False

    if not article.get("needs_gemini"):
        return False
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
        "top_p": TOP_P,
        "frequency_penalty": FREQUENCY_PENALTY,
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

    # Payload-size guard: the 8B fallback has a 6000 TPM limit.
    # Our NotebookLM safety block (~2000 tokens) plus source text plus
    # output budget (1400 tokens) routinely pushes past this. Estimate
    # total tokens = (system_prompt_chars + source_chars) / 3.5 + max_tokens.
    # If it would exceed 5800 tokens, skip the fallback entirely.
    FALLBACK_TPM_LIMIT = 5800
    est_prompt_tokens = (len(SYSTEM_PROMPT) + len(source_text) + 500) // 3
    est_total_tokens = est_prompt_tokens + MAX_TOKENS
    skip_fallback = est_total_tokens > FALLBACK_TPM_LIMIT

    for model_index, model in enumerate(models_to_try, start=1):
        # Skip fallback model if payload is too large for its TPM limit
        if model_index > 1 and skip_fallback:
            print(f"  [SKIP] Fallback model {model} would exceed TPM "
                  f"(est {est_total_tokens} tok > {FALLBACK_TPM_LIMIT}) — article stays scaffold")
            return None
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
            time.sleep(15)  # TPM rate-limit pacing (was 1.5s)
            continue

        wc       = count_words(new_body)
        h2_count = len(re.findall(r"<h2\b", new_body, flags=re.IGNORECASE))

        # Quality gates — updated for 800–1000 word target
        if wc < 600:
            print(f"    [WARN] Generated body only {wc} words (target 800–1000) — skipping")
            processed += 1
            time.sleep(15)
            continue

        if h2_count < 4:
            print(f"    [WARN] Generated body has {h2_count}/4 H2 sections (min) — skipping")
            processed += 1
            time.sleep(15)
            continue

        if has_too_many_generic_phrases(new_body):
            print("    [WARN] Generated body still contains too many generic phrases — skipping")
            processed += 1
            time.sleep(15)
            continue

        if not has_workflow_context(new_body):
            print("    [WARN] Generated body lacks enough workflow context — skipping")
            processed += 1
            time.sleep(15)
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
        time.sleep(15)   # TPM rate-limit pacing — prevents 429 cascades

    if changed > 0:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"\n[DONE] Enriched {changed} articles → saved to {ARTICLES_FILE}")
    else:
        print("\n[DONE] No articles changed (all Groq calls returned empty or below quality threshold)")


if __name__ == "__main__":
    main()
