# -*- coding: utf-8 -*-
"""
scripts/generate_gemini.py
===========================
Uses Google Gemini 1.5 Flash API to transform short RSS teasers into
600-word technical broadcast briefings.

Acts as a REDUNDANT pipeline alongside generate_summaries.py (Groq).
If Groq hits rate limits, Gemini keeps the site fresh.

Usage:
  GEMINI_API_KEY=xxx python3 scripts/generate_gemini.py

GitHub Actions:
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  run: python3 scripts/generate_gemini.py || echo "Gemini step skipped"

Output per article (data/summaries/<slug>.json):
  {
    "slug": "...",
    "card_summary": "...",
    "body_html": "<h2>...</h2><h3>...</h3><ul>...</ul>",
    "word_count": 620,
    "generated_by": "gemini-2.5-flash-lite"
  }

Idempotent -- skips slugs that already have a summary file.
Rate limit: time.sleep(4) between calls (Gemini free tier: 15 RPM).
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Shared factual-safety block — single source of truth across all generators
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prompt_safety import FACTUAL_SAFETY_BLOCK
except ImportError:
    FACTUAL_SAFETY_BLOCK = ""

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT          = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEWS_F        = os.path.join(ROOT, "data", "news.json")
GEN_ARTS_F    = os.path.join(ROOT, "data", "generated_articles.json")
SUMMARIES_DIR = os.path.join(ROOT, "data", "summaries")
os.makedirs(SUMMARIES_DIR, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ENABLE_GEMINI_PREMIUM = os.environ.get("ENABLE_GEMINI_PREMIUM", "true").lower() == "true"

# ── DUAL MODEL STRATEGY ───────────────────────────────────────────────────────
# Flash-Lite: 15 RPM / 1,000 RPD -- use for ALL regular summaries (220 articles)
# Pro:        10 RPM / 100 RPD   -- reserve ONLY for top "featured" pillar posts
#
# Limits reset at Midnight Pacific Time (PT).
# If running from India (IST = PT + 13.5h), your PT midnight = 13:30 IST next day.
# Plan runs accordingly: morning IST run hits yesterday's quota; afternoon is fresh.
#
# NOTE: "gemini-3.1-flash-lite" doesn't exist as of 2026.
# Correct model strings used below. Update if Google releases newer versions.

# ── Model selection ───────────────────────────────────────────────────────────
# gemini-2.5-pro: stable, free tier, 10 RPM / 100 RPD.
# We use Pro for ALL visible articles -- the extra quality is worth the budget.
# With <=22 visible RSS articles and 100 RPD limit, we can fully process
# the visible set in one run, then sit idle on subsequent runs until new
# articles enter the visible pool.
#
# gemini-2.5-flash-lite is removed -- it was hitting 1,000 RPD limit at item 10
# because it was being called for ALL 400 articles, not just the 22 visible ones.
# That bug is fixed: generate_gemini.py now only processes visible_slugs.

GEMINI_PRO_MODEL = "gemini-2.5-pro"   # stable free tier -- 10 RPM / 100 RPD

GEMINI_PRO_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_PRO_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

# Keep aliases -- nothing else in the codebase should break
GEMINI_FLASH_LITE_MODEL = GEMINI_PRO_MODEL   # redirect to Pro
GEMINI_FLASH_LITE_URL   = GEMINI_PRO_URL
GEMINI_MODEL            = GEMINI_PRO_MODEL
GEMINI_URL              = GEMINI_PRO_URL

# All visible articles get Pro treatment -- no tier split needed
PRO_CATEGORIES = set()   # not used; every article uses Pro
PRO_BUDGET_PER_RUN = 22  # safety ceiling = max visible RSS articles

MAX_PER_RUN  = int(os.environ.get("GEMINI_MAX_PER_RUN", "2"))
SLEEP_SECS   = float(os.environ.get("GEMINI_SLEEP_SECS", "8"))
SLEEP_PRO    = SLEEP_SECS

MAX_ITEMS_PER_RUN  = MAX_PER_RUN
USE_GROQ_FALLBACK  = False   # Groq is for card summaries only -- not full articles

# Skip articles already processed at 800+ words by Gemini Pro -- saves quota
GEMINI_QUALITY_THRESHOLD = 70

try:
    import requests as _requests
    _USE_REQUESTS = True
except ImportError:
    _USE_REQUESTS = False

# ── Broadcast relevance filter ────────────────────────────────────────────────
_BROADCAST_SIGNALS = [
    "broadcast", "streaming", "codec", "encoder", "decoder", "nab", "ibc",
    "ott", "cdn", "video", "audio", "production", "playout", "camera",
    "studio", "graphics", "newsroom", "mam", "pam", "nmos", "st 2110",
    "sdi", "ip workflow", "cloud production", "media", "television", "tv",
    "satellite", "transmission", "post-production", "editing", "vfx",
    "signal", "ingest", "workflow", "encoding", "encode", "stream",
    "jpeg xs", "ip media", "live ip", "hevc", "h.264", "av1", "hls", "srt",
    "rist", "ndi", "mxf", "dnxhd", "channel", "intercom", "remi",
]
_OFF_TOPIC = [
    "led wall sleep", "retail led", "sleep study", "fashion week",
    "luxury hotel", "real estate", "restaurant", "fitness app",
    "cryptocurrency", "nft ", "web3 ", "samsung led sleep",
]


# ── Technical Domain Classifier ───────────────────────────────────────────────
# Determines whether an article is Broadcast (Live/Signals), Media IT, or Security
# so the AI writes with the right terminology -- no cross-contamination.

_BROADCAST_SIGNALS = [
    "st 2110","smpte 2110","ndi","srt","genlock","12g-sdi","3g-sdi","hd-sdi",
    "sdi","aja","blackmagic","frame-accurate","frame accuracy","jpeg xs","jpeg2000",
    "rist","aes67","dante","live production","ob van","remi","studio","camera",
    "playout","master control","router","multiviewer","intercom","clear-com",
    "riedel","evertz","grass valley","snell","imagine","miranda","vizrt","chyron",
    "broadcast transmit","satellite uplink","encoder hardware","decoder hardware",
    "transport stream","mpeg-ts","hls ingest","live stream","live encode",
]
_MEDIA_IT_SIGNALS = [
    "mam","media asset management","s3","object storage","kubernetes","k8s",
    "microservices","api","rest api","cloud","aws","azure","gcp","cdn",
    "workflow","orchestration","egress","transcoding","vod","ott platform",
    "media supply chain","post-production","nle","avid","premiere","resolve",
    "storage","nas","san","archive","lto","ingest pipeline","qc","quality control",
    "metadata","cms","headless","containerized","docker","ci/cd","devops",
    "media io","media services","elemental","mediaconvert","ffmpeg","bitmovin",
    "telestream","vantage","harmonic","ateme","wowza","brightcove","kaltura",
]
_SECURITY_SIGNALS = [
    "security","cybersecurity","zero trust","drm","watermark","forensic",
    "aes-256","encryption","soc2","iso 27001","gdpr","breach","vulnerability",
    "ransomware","phishing","authentication","oauth","saml","mfa","2fa",
    "firewall","vpn","intrusion","pen test","audit","compliance","patch",
    "signal phishing","russian","fbi","hack","malware","threat",
]

def classify_domain(title: str, teaser: str) -> str:
    """Returns 'BROADCAST', 'MEDIA_IT', or 'SECURITY'."""
    text = (title + " " + teaser).lower()
    broadcast_score = sum(1 for s in _BROADCAST_SIGNALS if s in text)
    media_it_score  = sum(1 for s in _MEDIA_IT_SIGNALS  if s in text)
    security_score  = sum(1 for s in _SECURITY_SIGNALS  if s in text)
    if security_score >= 2:
        return "SECURITY"
    if broadcast_score >= media_it_score:
        return "BROADCAST"
    return "MEDIA_IT"

_DOMAIN_CONTEXT = {
    "BROADCAST": {
        "label": "Broadcast (Live/Signals)",
        "focus": "real-time transport, latency, signal integrity, and frame-accuracy",
        "terms": "ST 2110, NDI, SRT, Genlock, 12G-SDI, JPEG XS, AES67, RIST, NMOS",
        "guardrail": "Primary focus is live signal transport and latency. Reference cloud/MAM only if the article specifically covers hybrid or cloud-connected live production. Do not force cloud or Kubernetes references for pure hardware/signal topics.",
        "roi": "reduced transmission cost, lower latency than satellite/fibre, simplified signal routing, and reduced hardware rack footprint"
    },
    "MEDIA_IT": {
        "label": "Media IT (Storage/Workflow/Cloud)",
        "focus": "scalability, data integrity, workflow automation, and total cost of ownership",
        "terms": "Object Storage (S3), Microservices, Kubernetes, MAM, Egress Costs, API Orchestration, ST 2110 (for ingest), NMOS (for discovery)",
        "guardrail": "Primary focus is file-based workflow and cloud infrastructure. ST 2110 and NMOS may appear where relevant for ingest or playout integration \u2014 do not force them into pure software/storage contexts.",
        "roi": "reduced operational overhead, faster content delivery, lower infrastructure costs, and eliminated manual QC effort"
    },
    "SECURITY": {
        "label": "Security & Compliance",
        "focus": "risk mitigation, threat surface reduction, and regulatory compliance in broadcast environments",
        "terms": "Zero Trust, DRM, Forensic Watermarking, AES-256 Encryption, SOC2 Compliance, NIST, CDN security, broadcast signal integrity",
        "guardrail": "Frame security risks practically for broadcast operations. Reference specific broadcast-relevant threat vectors (signal interception, content piracy, newsroom systems) where relevant. Do not make unverified attribution claims.",
        "roi": "reduced breach risk, lower content piracy losses, compliance with broadcast licensing obligations, and lower cyber insurance premiums"
    }
}

_MANDATORY_FOOTER = ''  # REMOVED — no per-article AI disclaimer (see editorial-policy.html)

def is_broadcast_relevant(title: str, teaser: str = "") -> bool:
    text = (title + " " + teaser).lower()
    if any(k in text for k in _OFF_TOPIC):
        return False
    return any(k in text for k in _BROADCAST_SIGNALS)


# ── Quality gate (mirrors generate_summaries.py logic) ───────────────────────
_STANCE_SIGNALS = [
    "in practice", "the trade-off", "trade-off here", "real challenge",
    "what gets missed", "overhyped", "most engineers", "engineers should",
    "the risk here", "worth flagging", "i'd expect", "i'd recommend",
    "my view", "bluntly", "frankly",
]

_GENERIC_FULL = [
    "this reflects a growing", "this highlights the importance",
    "organizations should consider", "in today's landscape",
    "important to note", "rapidly evolving", "plays a key role",
    "it is worth noting", "this underscores", "in the current environment",
    "the ever-evolving", "rapidly evolving field",
]

def validate_body_quality(body_html: str, domain_terms: str) -> tuple:
    """Returns (is_valid, failures_list). Aligned with 6-section <h2> structure."""
    failures = []
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if wc < 700:
        failures.append(f"Too short: {wc} words (target 850+)")
    # New structure uses <h2> for all 6 sections
    if len(re.findall(r"<h2", body_html, re.IGNORECASE)) < 5:
        failures.append("Fewer than 5 <h2> sections (expected 6)")
    terms_list = [t.strip().lower() for t in domain_terms.split(",") if t.strip()]
    if sum(1 for t in terms_list if t in body_html.lower()) < 2:
        failures.append("Fewer than 2 domain terms")
    if sum(1 for p in _GENERIC_FULL if p in body_html.lower()) >= 2:
        failures.append("Generic phrases detected")
    if not any(s in body_html.lower() for s in _STANCE_SIGNALS):
        failures.append("No editorial stance detected")
    # Mandatory system flow check
    if "→" not in body_html and "->" not in body_html:
        failures.append("Missing mandatory system-flow arrow notation")
    return len(failures) == 0, failures


def compute_quality_score(body_html: str, card_summary: str) -> int:
    """0–100 quality score aligned with 6-section h2 structure."""
    score = 0
    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if wc >= 850:   score += 30
    elif wc >= 700: score += 15
    h2s = len(re.findall(r"<h2", body_html, re.IGNORECASE))
    if h2s >= 6:   score += 25
    elif h2s >= 4: score += 15
    if not any(p in body_html.lower() for p in _GENERIC_FULL): score += 20
    if any(s in body_html.lower() for s in _STANCE_SIGNALS):   score += 15
    if card_summary and len(card_summary.split()) >= 80:        score += 10
    return min(score, 100)


def needs_gemini_processing(slug: str) -> tuple:
    """
    Decide whether Gemini Pro should (re)process this article.
    Returns (should_process: bool, reason: str).

    Process if ANY of:
    1. No summary file exists at all
    2. body_html is missing or empty
    3. word_count < 800  -- forces upgrade of thin Groq/RSS stubs
    4. generated_by is not "gemini-2.5-pro"  -- upgrades Flash-Lite or Groq articles
    5. <h2> missing from body_html  -- unstructured content
    6. needs_gemini=True flag set by Groq quality gate

    Skip only if: generated_by="gemini-2.5-pro" AND word_count>=800 AND has <h2>
    """
    sp = summary_path(slug)
    if not os.path.exists(sp):
        return True, "no_summary"
    try:
        with open(sp, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return True, "corrupt_summary"

    body_html  = s.get("body_html") or ""
    word_count = s.get("word_count", 0)
    gen_by     = s.get("generated_by", "")

    # Tier-1 Mistral output: sacred — do not reprocess.
    # Mistral runs first in the cascade with NotebookLM protocol + live
    # source-page grounding, so its output is tier-1 quality.
    if gen_by.startswith("mistral") and word_count >= 400:
        return False, f"protected_mistral_{word_count}w"

    # Missing body -- definitely needs processing
    if not body_html.strip():
        return True, "no_body_html"

    # Thin content -- upgrade stub articles regardless of who generated them
    if word_count < 800:
        return True, f"thin_content_{word_count}w"

    # Not generated by Gemini Pro -- upgrade Flash-Lite and Groq articles
    if gen_by != "gemini-2.5-pro":
        return True, f"upgrade_from_{gen_by or 'unknown'}"

    # Missing structure — articles should have all 6 <h2> sections
    if "<h2>" not in body_html and "<h2 " not in body_html:
        return True, "no_h2_structure"

    # Explicitly flagged by Groq quality gate
    if s.get("needs_gemini"):
        return True, "groq_flagged"

    # Already high-quality Gemini Pro output -- skip
    return False, f"gemini_pro_complete_{word_count}w"


# ── Slug helper ───────────────────────────────────────────────────────────────
def make_slug(title: str, pub_date: str, cat: str = "") -> str:
    date_part  = (pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cat_part   = re.sub(r"[^\w]", "-", (cat or "").lower()).strip("-")[:12]
    title_part = re.sub(r"[^\w\s-]", "", title.lower())
    title_part = re.sub(r"[\s_]+", "-", title_part).strip("-")
    prefix     = f"{date_part}-{cat_part}-" if cat_part else f"{date_part}-"
    return f"{prefix}{title_part[:65 - len(prefix)]}"


# ── Summary file helpers ──────────────────────────────────────────────────────
def summary_path(slug: str) -> str:
    return os.path.join(SUMMARIES_DIR, f"{slug}.json")

def summary_exists(slug: str) -> bool:
    return os.path.exists(summary_path(slug))

def save_summary(slug: str, card_summary: str, body_html: str, qs: int = None,
                 model: str = "gemini-2.5-flash-lite"):
    """Save Gemini-generated summary. Records which model produced it."""
    wc   = len(re.sub(r"<[^>]+>", " ", body_html).split())
    if qs is None:
        qs = compute_quality_score(body_html, card_summary)
    data = {
        "slug":          slug,
        "card_summary":  card_summary,
        "body_html":     body_html,
        "word_count":    wc,
        "quality_score": qs,
        "needs_gemini":  False,
        "generated_by":  model,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }
    with open(summary_path(slug), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Gemini API call with retry ────────────────────────────────────────────────
def _parse_wait(msg: str) -> float:
    """Extract retry-after seconds from Gemini/Google 429 response."""
    m = re.search(r"retry.after[:\s]+(\d+)", msg.lower())
    if m:
        return float(m.group(1)) + 2
    m = re.search(r"(\d+)\s*second", msg.lower())
    if m:
        return float(m.group(1)) + 2
    return 32.0  # short default -- resets within 60s


def gemini_call(prompt: str, max_retries: int = 2, use_pro: bool = True) -> str:
    """Call Gemini 2.5 Pro API. All articles use Pro.
    use_pro param kept for API compatibility but ignored (always Pro).
    Bails immediately on daily quota exhaustion.
    """
    url          = GEMINI_PRO_URL if use_pro else GEMINI_FLASH_LITE_URL
    model_label  = "Pro" if use_pro else "Flash-Lite"
    max_tokens   = 1800 if use_pro else 1200   # Pro can go deeper
    payload = json.dumps({
        "system_instruction": {
            "parts": [{"text": FACTUAL_SAFETY_BLOCK + "\n\n" + (
                "You are a named senior analyst at The Streamic with 15+ years in broadcast "
                "engineering, OTT infrastructure, and media systems. "
                "You write for broadcast CTOs, streaming architects, and media engineers who "
                "make real purchasing and architecture decisions. "
                "You are NOT generating analysis from an article -- you are interpreting an "
                "industry signal, forming an expert viewpoint, and explaining what engineers "
                "should DO with this information. "
                "Be decisive and opinionated when justified. Prioritise insight over structure. "
                "Write like a human expert, not a system. Vary sentence structure naturally. "
                "Use domain-specific terminology: HLS, MPEG-DASH, AV1, HEVC, DRM, CDN, SSAI, "
                "Zero Trust, ST 2110, NMOS, SRT, JPEG XS, MAM, SMPTE, OTT, REMI. "
                "NEVER use: delivers, seamless, game-changer, highlights, underscores, reflects, "
                "in today's landscape, rapidly evolving, plays a key role, delve into, "
                "this article explores, innovative, important to note."
            )}]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.3,
            "maxOutputTokens": max_tokens,
        }
    }).encode()

    headers = {"Content-Type": "application/json"}

    for attempt in range(max_retries):
        try:
            try:
                import requests as _req
                resp = _req.post(url, data=payload, headers=headers, timeout=30)
                status = resp.status_code
                body   = resp.text
            except Exception:
                import urllib.request
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=30) as r:
                    status = r.status
                    body   = r.read().decode()

            if status == 200:
                data = json.loads(body)
                return data["candidates"][0]["content"]["parts"][0]["text"]

            if status == 429:
                body_lower = body.lower()
                # Daily quota exhausted -- no point retrying at all
                if any(p in body_lower for p in [
                    "daily", "per day", "resource_exhausted",
                    "quota exceeded", "limit exceeded", "free tier"
                ]):
                    raise RuntimeError(f"DAILY_QUOTA_EXHAUSTED_{model_label}: {body[:120]}")
                # Per-minute limit -- wait and retry once
                wait = _parse_wait(body)
                wait = min(wait, 35)  # never wait more than 35s
                print(f"      ⏱ Gemini {model_label} rate limit. Waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
                continue

            raise RuntimeError(f"Gemini {model_label} HTTP {status}: {body[:200]}")

        except RuntimeError as ex:
            if "DAILY_QUOTA_EXHAUSTED" in str(ex):
                raise  # propagate immediately -- caller handles bail
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"Gemini {model_label}: max retries ({max_retries}) exceeded")
        except Exception as ex:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"Gemini {model_label} error: {ex}")

    raise RuntimeError(f"Gemini: max retries ({max_retries}) exceeded")



def build_article_prompt(title: str, teaser: str, source: str, category: str) -> str:
    """
    Elite Broadcast & Media Systems Architect prompt — The Streamic (v3, Apr 2026).

    6-section fixed structure with mandatory system-flow diagram, anti-generic rules,
    readability rules, vendor realism, and decision-maker output.

    Word target: 850–1000 words.
    Output: HTML only. No markdown. No preamble before first <h2>.
    Note: build.py appends source attribution + Sources block automatically — do NOT emit those.
    """
    domain = classify_domain(title, teaser)
    ctx    = _DOMAIN_CONTEXT[domain]

    # Topic-aware technical depth instruction injected into Technical Breakdown section
    _DEPTH = {
        "BROADCAST": (
            "Focus depth on: SMPTE ST 2110 transport layers (2110-20 video, 2110-30 audio, "
            "2110-40 ancillary), PTP/IEEE 1588 timing, SDI-to-IP migration trade-offs, "
            "software-defined routing behaviour, and redundancy/failover design under "
            "live production conditions."
        ),
        "MEDIA_IT": (
            "Focus depth on: MAM/PAM integration (Avid Interplay, Dalet), ingest pipeline "
            "design, object storage tiering (S3/nearline/LTO), orchestration (Kubernetes, "
            "microservices), and how file-based workflow automation reduces manual QC effort "
            "and operational overhead."
        ),
        "SECURITY": (
            "Focus depth on: broadcast-specific threat surfaces (signal interception, "
            "newsroom credential exposure, content piracy), Zero Trust architecture in "
            "media environments, DRM (Widevine, PlayReady, FairPlay), forensic watermarking, "
            "and how these controls fit into a live broadcast operations workflow."
        ),
    }.get(domain, "Focus on the most relevant broadcast infrastructure layers this story touches.")

    _TEMPLATE = (
        FACTUAL_SAFETY_BLOCK + "\n\n"
        "You are a Senior Broadcast & Media Systems Architect and Technical Editor with 20+ years "
        "of hands-on experience in IP video, SMPTE ST 2110, MAM/PAM, playout automation, "
        "newsroom systems, and cloud-native broadcast workflows. You write for The Streamic "
        "(thestreamic.in) — an independent editorial publication for broadcast engineers, "
        "CTOs, streaming architects, and media IT professionals."
        "\n\nYour reader is both a broadcast CTO who knows the technology AND a media executive "
        "who needs to understand the business impact. Write so both get value."

        "\n\n======================================================================"
        "\nCRITICAL RULES (NON-NEGOTIABLE)"
        "\n======================================================================"
        "\n- DO NOT summarise the source sentence-by-sentence. Extract the signal, interpret "
        "  it like an engineer, rebuild with new structure and deeper analysis."
        "\n- Add missing technical context where the source is shallow."
        "\n- 100% original wording — no phrase longer than 8 words copied from the source."
        "\n- Output VALID HTML only. No markdown fences. No backticks. Start with <h2>."
        "\n- Minimum 850 words. Target 900–1000 words."
        "\n- No SOURCES section — added automatically by the publishing pipeline."
        "\n- No top attribution banner — also added automatically."

        "\n\n======================================================================"
        "\nANTI-GENERIC RULE (STRICT)"
        "\n======================================================================"
        "\nNEVER use these phrases or any close variant:"
        "\n  ✗ \"This highlights the importance\""
        "\n  ✗ \"In today's evolving landscape\""
        "\n  ✗ \"Rapidly changing industry\""
        "\n  ✗ \"It is worth noting\""
        "\n  ✗ \"Game-changer\" / \"seamless\" / \"innovative\" / \"revolutionary\""
        "\n  ✗ \"Industry-leading\" / \"best-in-class\" / \"robust\" / \"leverage\" / \"unlock\""
        "\n  ✗ \"This underscores\" / \"this reflects\" / \"organizations should consider\""
        "\nEvery paragraph must contain EITHER a real technical explanation OR a real-world "
        "operational implication. No paragraph may exist solely to transition or summarise."

        "\n\n======================================================================"
        "\nREADABILITY RULE"
        "\n======================================================================"
        "\n- Maximum paragraph length: 4–5 lines"
        "\n- Mix short punchy sentences with longer analytical ones"
        "\n- Never repeat the same idea in different words"
        "\n- Break complex ideas into steps — not run-on sentences"
        "\n- Write like a broadcast engineer explaining a real project to a colleague"

        "\n\n======================================================================"
        "\nVENDOR REALISM RULE"
        "\n======================================================================"
        "\nReference 2–3 real systems naturally where accurate and relevant:"
        "\n  Editing/MAM:    Avid Media Composer, Nexis, MediaCentral, Dalet, Interplay"
        "\n  Graphics:       Vizrt, Chyron, Unreal Engine AR"
        "\n  Playout:        Pebble Control, Harmonic Spectrum, Mediagenix WHATS'On"
        "\n  Streaming:      AWS MediaConnect, MediaLive, Elemental"
        "\n  Newsroom:       iNews, Dalet Newsroom, MediaCentral Newsroom"
        "\n  Infrastructure: SMPTE ST 2110, AES67, Dante, NDI, SRT, NMOS IS-04/05"
        "\n  Live/Control:   EVS, Ross Video, Grass Valley, Riedel, Imagine Communications"
        "\nDo NOT force vendor names in where they don't naturally fit."

        "\n\n======================================================================"
        "\nDOMAIN CONTEXT (weave in naturally — do not list verbatim)"
        "\n======================================================================"
        "\n- Domain:     __LABEL__"
        "\n- Focus:      __FOCUS__"
        "\n- Terminology: __TERMS__"
        "\n- Guardrail:  __GUARDRAIL__"
        "\n- ROI angle:  __ROI__"
        "\n- Technical depth instruction: __DEPTH__"

        "\n\n======================================================================"
        "\nINPUT SOURCE"
        "\n======================================================================"
        "\n- Source publication: __SOURCE__"
        "\n- Category: __CATEGORY__"
        "\n- Title: __TITLE__"
        "\n- Source content: __TEASER__"

        "\n\n======================================================================"
        "\nARTICLE STRUCTURE — use exactly these six <h2> sections in this order"
        "\n======================================================================"

        "\n\n<h2>Introduction</h2>"
        "\nHook the reader. Do NOT open with a summary of the announcement. Open with the "
        "real operational or engineering tension this story responds to. Why does a broadcast "
        "engineer or CTO need to read this today? What problem does it address? 2–3 paragraphs."

        "\n\n<h2>Technical Breakdown</h2>"
        "\nExplain the relevant layers of the broadcast chain this story touches. Show how "
        "systems connect end-to-end — not isolated components. Only include layers that are "
        "actually relevant to this topic. Use the TECHNICAL DEPTH INSTRUCTION above to guide "
        "what to cover. Include correct broadcast/media terminology throughout. 3–4 paragraphs."

        "\n\n<h2>Real Workflow Impact</h2>"
        "\nDescribe a concrete, realistic workflow this story affects — newsroom-to-air, "
        "PCR/MCR control room operation, ingest-to-playout chain, or cloud production pipeline. "
        "Show the before-and-after. Make it feel like a real broadcast operation, not a case study."
        "\n\nMANDATORY — include at least one full system flow using this arrow notation:"
        "\n  Input → Processing → System → Output"
        "\nExamples:"
        "\n  Live feed → ST 2110 core → playout automation → CDN → viewer"
        "\n  Wire ingest → iNews NRCS → MOS → production switcher → transmission"
        "\n  Camera → EVS replay → MediaCentral → playout → archive"
        "\n2–3 paragraphs."

        "\n\n<h2>Practical Impact</h2>"
        "\nWhere is the real ROI? What specifically gets faster, cheaper, or more reliable? "
        "What operational burden does this remove — or introduce? Cover: cost, efficiency, "
        "scalability, and operational resilience. Be precise. No vendor language."
        "\n\nMust include a DECISION-MAKER answer (can be woven into prose, not a list):"
        "\n  • Should this be adopted now, piloted, or watched?"
        "\n  • Where does the ROI actually appear in the workflow?"
        "\n  • What specific problem does it definitively solve?"
        "\n2–3 paragraphs."

        "\n\n<h2>Reality Check</h2>"
        "\nBe honest. What are the real limitations? What is overstated in the announcement? "
        "What integration challenges, vendor lock-in risks, or missing dependencies should "
        "engineers know about? What is NOT mentioned that a practitioner would ask about? "
        "2 paragraphs."

        "\n\n<h2>Why This Matters</h2>"
        "\nLong-term signal: what does this tell us about where broadcast technology is heading? "
        "How does it fit the larger shift — IP infrastructure, cloud-native production, "
        "AI-assisted workflows, or streaming-first delivery? What is the strategic read "
        "for engineering leads? 1–2 paragraphs."

        "\n\n======================================================================"
        "\nFINAL VALIDATION before writing"
        "\n======================================================================"
        "\n+ Does the intro open with tension/relevance — not a press release summary?"
        "\n+ Are all six sections present?"
        "\n+ Does Real Workflow Impact contain at least one arrow-notation system flow?"
        "\n+ Does Practical Impact answer: adopt/pilot/wait, where is ROI, what problem solved?"
        "\n+ Does Reality Check name at least one real limitation or risk?"
        "\n+ Is the body 850+ words?"
        "\n+ Are 2–3 real vendor or standard names referenced naturally?"
        "\n+ Zero generic phrases from the banned list?"
        "\n\nWrite the full article now. Start immediately with <h2>Introduction</h2>:"
    )

    return (
        _TEMPLATE
        .replace("__LABEL__",    ctx["label"])
        .replace("__FOCUS__",    ctx["focus"])
        .replace("__TERMS__",    ctx["terms"])
        .replace("__GUARDRAIL__", ctx["guardrail"])
        .replace("__ROI__",      ctx["roi"])
        .replace("__DEPTH__",    _DEPTH)
        .replace("__SOURCE__",   source)
        .replace("__CATEGORY__", category)
        .replace("__TITLE__",    title)
        .replace("__TEASER__",   teaser)
    )


def build_card_prompt(title: str, teaser: str, source: str) -> str:
    """
    Expert intelligence card — opinionated analyst voice, not a summary.
    Shown on homepage cards (~120–150 words, plain text, 2 paragraphs).
    Anti-generic and stance rules match the main article prompt.
    """
    domain = classify_domain(title, teaser)
    ctx    = _DOMAIN_CONTEXT[domain]

    return f"""{FACTUAL_SAFETY_BLOCK}

═══════════════════════════════════════════════════════════════════════════
ROLE
═══════════════════════════════════════════════════════════════════════════

You are a senior broadcast technology analyst writing for The Streamic. Your readers are broadcast CTOs, streaming architects, and media engineers who make real purchasing and architecture decisions.

You are NOT summarising an article. You are interpreting an industry signal and telling engineers what it means — and what they should do with that information.

DOMAIN: {ctx['label']}
FOCUS: {ctx['focus']}
KEY TERMS: {ctx['terms']}
GUARDRAIL: {ctx['guardrail']}

SOURCE: {source}
TITLE: {title}
CONTENT: {teaser}

Write exactly 2 paragraphs of expert intelligence (120–150 words total). Plain text only — no HTML, no bullets.

PARAGRAPH 1 (55–70 words): Interpret the technical or operational signal. Not what happened — what it means architecturally or operationally. Use precise domain terminology from: {ctx['terms']}. Take a stance. Do not open with the company name.

PARAGRAPH 2 (55–70 words): Identify the real trade-off, hidden risk, or second-order effect an experienced engineer would spot. Open with a natural phrase such as "In practice, this means..." or "The trade-off here is..." or "For broadcast teams, the real question is..." — pick whichever fits the content. Do not use a template opener.

MANDATORY CHECK before submitting:
- Does it read like it was written by a person, not filled into a template? If no, rewrite.
- Does it express a clear stance or insight? If no, add one.

FORBIDDEN PHRASES: "this highlights", "this underscores", "this reflects", "organizations should consider", "in today's landscape", "rapidly evolving", "plays a key role", "game-changer", "seamless", "delivers", "innovative", "revolutionary"

Write the 2-paragraph expert intelligence now:"""


# ── Generic output detector ───────────────────────────────────────────────────
_GENERIC_MARKERS = [
    "this reflects a growing", "in today's landscape", "it is worth noting",
    "this highlights the importance", "this underscores", "organizations should consider",
    "the ever-evolving", "rapidly evolving field",
]

def is_generic(text: str) -> bool:
    tl = text.lower()
    return sum(1 for m in _GENERIC_MARKERS if m in tl) >= 2


def fallback_card(title: str, teaser: str) -> str:
    """Use raw teaser as card summary if Gemini produces generic output."""
    text = (teaser or title or "").strip()
    sentences = re.split(r"(?<=[.!?]) +", text)
    return " ".join(sentences[:3])


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=== generate_gemini.py ===")

    if not ENABLE_GEMINI_PREMIUM:
        print("Gemini premium step disabled by default (set ENABLE_GEMINI_PREMIUM=true to enable).")
        return

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set — skipping premium Gemini step.")
        return

    # Load news.json -- handles flat list and dict-of-categories formats
    with open(NEWS_F, "r", encoding="utf-8") as f:
        news_raw = json.load(f)

    if isinstance(news_raw, list):
        news_flat = news_raw
    else:
        news_flat = []
        for cat, items in news_raw.items():
            for it in (items or []):
                it.setdefault("category", cat)
                news_flat.append(it)

    # Also load generated_articles.json for articles needing summaries
    gen_arts = []
    if os.path.exists(GEN_ARTS_F):
        with open(GEN_ARTS_F, "r", encoding="utf-8") as f:
            gen_arts = json.load(f)

    # Build processing queue using load-balancing logic:
    # Only process articles that Groq flagged as weak, or never processed, or low score.
    # Skip articles where Groq already produced high-quality output (score >= threshold).
    items_to_process = []
    seen = set()
    skipped_high_quality = 0

    # ── Load visible slugs from built site ───────────────────────────────────
    # Only process articles that are actually indexed and shown on the site.
    # The new deep-dive prompt (850+ words, 5 structured sections) is expensive
    # in quota and only makes sense for the ~35 visible RSS articles in the
    # 20-card news grid -- NOT for the 380 hidden/noindex articles.
    # Vendor hub uses its own separate generate_vendor_hub.py -- never touched here.
    DOCS_GEN_F = os.path.join(ROOT, "docs", "data", "generated_articles.json")
    visible_slugs: set = set()
    if os.path.exists(DOCS_GEN_F):
        try:
            with open(DOCS_GEN_F, encoding="utf-8") as vf:
                vis_data = json.load(vf)
            for a in vis_data.get("featured_priority", []) + vis_data.get("items", []):
                sl = a.get("slug")
                if sl and not (a.get("is_editorial") or a.get("editorial")):
                    visible_slugs.add(sl)
            print(f"  Visible RSS slugs (site output): {len(visible_slugs)}")
        except Exception as ex:
            print(f"  ⚠ Could not load visible slugs: {ex} -- processing all RSS articles")
    else:
        print(f"  ⚠ docs/data/generated_articles.json not found -- run build.py first")
        print(f"     Falling back to full RSS processing (no visibility filter)")

    # From news.json -- identify slugs that need Gemini
    for item in news_flat:
        title  = (item.get("title") or "").strip()
        teaser = (item.get("teaser") or item.get("description") or "").strip()
        cat    = (item.get("category") or "featured").strip()
        pub    = (item.get("published") or item.get("pubDate") or "")[:10]
        source = (item.get("source") or item.get("source_domain") or "")

        if not title: continue
        if not is_broadcast_relevant(title, teaser): continue

        slug = make_slug(title, pub, cat)
        if slug in seen: continue
        seen.add(slug)

        # ── Visibility gate -- skip hidden articles ────────────────────────
        # Only generate deep-dive content for articles shown on the site.
        if visible_slugs and slug not in visible_slugs:
            continue

        should_process, reason = needs_gemini_processing(slug)
        if not should_process:
            skipped_high_quality += 1
            continue

        if cat not in {"featured", "newsroom", "streaming", "cloud", "infrastructure"}:
            continue
        items_to_process.append({
            "slug": slug, "title": title, "teaser": teaser,
            "category": cat, "source": source, "reason": reason,
            "premium_score": 1 if "nab" in f"{title} {teaser}".lower() else 0,
        })

    # From generated_articles.json -- catch visible articles Groq flagged or never touched
    for a in gen_arts:
        if a.get("is_editorial") or a.get("editorial"):
            continue
        slug  = a.get("slug", "")
        if not slug or slug in seen: continue
        seen.add(slug)

        # ── Visibility gate -- same rule as above ──────────────────────────
        if visible_slugs and slug not in visible_slugs:
            continue

        should_process, reason = needs_gemini_processing(slug)
        if not should_process:
            skipped_high_quality += 1
            continue

        cat = a.get("category", "featured")
        if cat not in {"featured", "newsroom", "streaming", "cloud", "infrastructure"}:
            continue
        items_to_process.append({
            "slug":             slug,
            "title":            a.get("title", ""),
            "teaser":           a.get("dek") or a.get("meta_description") or a.get("teaser") or "",
            "category":         cat,
            "source":           a.get("source_domain") or a.get("source") or "",
            "reason":           reason,
            "premium_score":    1 if "nab" in f"{a.get('title', '')} {a.get('dek', '')}".lower() else 0,
            "needs_gemini_flag": bool(a.get("needs_gemini")),  # from rewrite_feed.py classifier
        })

    items_to_process.sort(key=lambda x: (
        x.get("needs_gemini_flag", False),   # rewrite_feed.py priority signal
        x.get("premium_score", 0),
        x.get("category") == "featured"
    ), reverse=True)
    total = len(items_to_process)
    batch = items_to_process[:MAX_ITEMS_PER_RUN]
    print(f"Items to process: {total} (this run: {len(batch)}) | "
          f"Skipped (high-quality Groq): {skipped_high_quality}")

    processed       = 0
    errors          = 0
    consec_limits   = 0
    quota_exhausted = False  # single quota flag for Gemini Pro
    _run_start      = time.time()
    _RUN_LIMIT      = 2400   # 40 min -- fits inside 45-min GitHub Actions timeout

    for item in batch:
        if time.time() - _run_start > _RUN_LIMIT:
            print(f"      ⏱ Run time limit reached. Stopping cleanly ({processed} saved).")
            break
        if consec_limits >= 2:
            print(f"      ⏱ Gemini rate limit hit {consec_limits}x in a row -- skipping run.")
            break

        # Skip remaining items gracefully if quota hit -- don't break (lets patch run)
        if quota_exhausted:
            errors += 1
            print(f"  [{processed+errors}/{len(batch)}] Skipped due to quota")
            continue

        slug     = item["slug"]
        title    = item["title"]
        teaser   = item["teaser"]
        category = item["category"]
        source   = item["source"] or "industry source"
        reason   = item.get("reason", "unknown")

        # Always use Gemini Pro -- single model, no tier split
        use_pro     = True
        model_label = "Pro"
        sleep_time  = SLEEP_PRO

        print(f"  [{processed+1}/{len(batch)}] [Pro] {title[:55]}... (reason: {reason})")

        try:
            domain = classify_domain(title, teaser)
            ctx    = _DOMAIN_CONTEXT[domain]

            # ── Step 1: Card summary -- single call, fail fast ────────────
            raw_card = gemini_call(build_card_prompt(title, teaser, source), use_pro=use_pro)
            time.sleep(sleep_time)

            if not raw_card or is_generic(raw_card):
                print(f"      ⚠ Generic card -- using fallback")
                card_summary = fallback_card(title, teaser)
            else:
                card_summary = re.sub(r"\s+", " ", raw_card).strip()

            # ── Step 2: Full article body -- single call, no retry (fail fast) ──
            raw_body  = gemini_call(build_article_prompt(title, teaser, source, category), use_pro=use_pro)
            body_html = re.sub(r"```html?\n?|```\n?", "", raw_body).strip()
            time.sleep(sleep_time)

            body_valid, failures = validate_body_quality(body_html, ctx["terms"])
            if not body_valid:
                print(f"      ⚠ Quality gate FAILED: {'; '.join(failures)} -- skipping full article save")

                # Save only card summary (if valid), do NOT overwrite body_html
                try:
                    existing_path = summary_path(slug)
                    if os.path.exists(existing_path):
                        with open(existing_path, encoding="utf-8") as ef:
                            existing_data = json.load(ef)
                    else:
                        existing_data = {}

                    existing_data["card_summary"] = card_summary
                    existing_data["generated_by"] = "gemini-partial"
                    existing_data["needs_gemini"] = True

                    with open(existing_path, "w", encoding="utf-8") as ef:
                        json.dump(existing_data, ef, indent=2, ensure_ascii=False)

                except Exception as e:
                    print(f"      ⚠ Failed partial save: {e}")

                processed += 1
                time.sleep(2)
                continue

            qs = compute_quality_score(body_html, card_summary)
            used_model = GEMINI_PRO_MODEL if use_pro else GEMINI_FLASH_LITE_MODEL
            save_summary(slug, card_summary, body_html, qs=qs, model=used_model)
            processed    += 1
            consec_limits = 0
            print(f"      ✓ saved (score={qs}/100, model={model_label}) -> data/summaries/{slug[:35]}.json")

        except Exception as ex:
            errors += 1
            err_str = str(ex)
            is_quota = ('DAILY_QUOTA_EXHAUSTED' in err_str
                        or any(k in err_str.lower() for k in ['quota', 'exhausted']))

            if is_quota:
                quota_exhausted = True
                print(f"      ✗ Gemini Pro daily quota exhausted -- {errors} errors. Resets at 08:00 UTC (13:30 IST).")
                print(f"         Run generate_gemini.py again tomorrow for remaining {len(batch)-(processed+errors)} articles.")

            elif '429' in err_str or 'rate' in err_str.lower():
                consec_limits += 1
                print(f"      ✗ Rate limit error: {ex}")
            else:
                consec_limits = 0
                print(f"      ✗ ERROR: {ex}")
            time.sleep(2)

    print(f"\n✓ Done: {processed} summaries saved, {errors} errors.")
    print(f"  Files in data/summaries/: {len(os.listdir(SUMMARIES_DIR))}")

    # Patch generated_articles.json with new Gemini summaries
    patch_generated_articles()


def patch_generated_articles():
    """Apply Gemini summaries back into generated_articles.json.

    Safety rules (prevent stale-scaffold shadow regression):
      - Only patch when the summary body is a real upgrade (word_count >= 800).
      - Copy ALL upgraded fields (body, meta, generated_by, etc.) so build.py
        and needs_gemini_processing() see a consistent upgraded state.
      - Never write empty/None values over existing article fields.
    """
    if not os.path.exists(GEN_ARTS_F):
        return

    with open(GEN_ARTS_F, "r", encoding="utf-8") as f:
        arts = json.load(f)

    UPGRADE_FIELDS = (
        "card_summary", "body_html", "word_count",
        "dek", "meta_description", "generated_by",
        "quality_score", "analysis_level", "generated_at",
    )

    patched = 0
    skipped_thin = 0
    for a in arts:
        slug = a.get("slug", "")
        if not slug:
            continue
        sp = summary_path(slug)
        if not os.path.exists(sp):
            continue
        try:
            with open(sp, encoding="utf-8") as sf:
                s = json.load(sf)
        except Exception:
            continue

        # Guard: only patch from real Gemini upgrades, never from stale stubs.
        body = s.get("body_html") or ""
        wc   = s.get("word_count", 0)
        if not body.strip() or wc < 800:
            skipped_thin += 1
            continue

        for k in UPGRADE_FIELDS:
            v = s.get(k)
            if v is not None and v != "":
                a[k] = v
        a["needs_gemini"] = False
        patched += 1

    with open(GEN_ARTS_F, "w", encoding="utf-8") as f:
        json.dump(arts, f, indent=2, ensure_ascii=False)
    print(f"  Patched {patched} articles in generated_articles.json "
          f"(skipped {skipped_thin} thin/stale summaries)")


if __name__ == "__main__":
    main()
