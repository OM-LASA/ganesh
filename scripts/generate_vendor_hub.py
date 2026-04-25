"""
scripts/generate_vendor_hub.py
================================
Generates a "Key Broadcast Systems Hub" page for thestreamic.in.

Calls the Gemini 2.5 Pro API once per vendor to produce high-quality,
technically-authoritative HTML blocks — then assembles them into a
complete static page and registers it in the build system.

Usage:
    python3 scripts/generate_vendor_hub.py

Requires:
    GEMINI_API_KEY environment variable set.

Outputs:
    docs/broadcast-systems-hub.html   — final static page
    data/vendor_hub.json              — cached raw blocks (re-used on rebuild)

Rate-limit strategy:
    gemini-2.5-pro: 10 RPM / 100 RPD free tier
    SLEEP_SECS=7   → ~8.5 RPM — safely under limit
    13 vendors × 7s ≈ ~91s total runtime
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
ROOT        = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS        = os.path.join(ROOT, "docs")
DATA_DIR    = os.path.join(ROOT, "data")
HUB_JSON    = os.path.join(DATA_DIR, "vendor_hub.json")
HUB_HTML    = os.path.join(DOCS, "broadcast-systems-hub.html")

# ── API config ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")

# NOTE: "gemini-3.1-pro" does not exist as of 2026.
# The correct stable production model is "gemini-2.5-pro".
# Update this string if Google releases a newer stable version.
GEMINI_PRO_MODEL = "gemini-2.5-pro"
GEMINI_PRO_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_PRO_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

SLEEP_SECS  = 7      # seconds between API calls — keeps under 10 RPM free-tier limit
MAX_RETRIES = 2      # retries on rate-limit (429) only

# ── Site metadata ─────────────────────────────────────────────────────────────
BASE_URL    = "https://www.thestreamic.in"
GA          = "G-0VSHDN3ZR6"
ADS         = "ca-pub-8033069131874524"
AUTHOR      = "The Streamic Editorial Team"

# ══════════════════════════════════════════════════════════════════════════════
# VENDOR REGISTRY
# Each entry: (vendor_name, product_name, category_hint)
# category_hint is passed to Gemini as context — not shown to users verbatim.
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# MASTER VENDOR REGISTRY — 50 broadcast systems across all major categories
#
# WEEKLY AUTOMATION STRATEGY:
#   - WEEKLY_NEW = 5 new vendors per weekend run
#   - REFRESH_WEEKS = 8 — regenerate entries older than 8 weeks to keep fresh
#   - Each Saturday at 08:30 UTC, generate.yml triggers mode=vendor_hub
#   - New vendors are picked from VENDORS in order; oldest cached get refreshed
#   - Running all 50 takes ~350s — done in one run on a fresh cache
#
# To add new vendors: append to VENDORS list below. They will be picked up
# automatically on the next Saturday run.
# ══════════════════════════════════════════════════════════════════════════════

VENDORS = [
    # ── Post-Production / NLE ─────────────────────────────────────────────
    ("Avid",              "Media Composer",                    "NLE / Post-Production"),
    ("Avid",              "Interplay Production (PAM)",        "Production Asset Management"),
    ("Avid",              "MediaCentral Platform",             "Media Operations Platform"),
    ("Avid",              "iNEWS Newsroom Computer System",    "Newsroom Computer System (NRCS)"),
    ("Adobe",             "Premiere Pro",                      "NLE / Post-Production"),
    ("Adobe",             "After Effects",                     "Motion Graphics / VFX"),
    ("Autodesk",          "Smoke",                             "NLE / Finishing"),
    ("DaVinci Resolve",   "Blackmagic Studio (DaVinci)",       "NLE / Colour Grading"),
    ("Blackmagic Design", "ATEM Production Switcher",          "Live Production / Switching"),

    # ── MAM / PAM / Archive ───────────────────────────────────────────────
    ("Dalet",             "Galaxy Five (MAM/Newsroom)",        "MAM / Newsroom Integration"),
    ("Dalet",             "Flex Cloud MAM",                    "Cloud-Native Media Asset Management"),
    ("Grass Valley",      "STRATUS (MAM)",                     "Media Asset Management"),
    ("Grass Valley",      "AMPP (Cloud Production Platform)",  "Cloud Production Platform"),
    ("EditShare",         "Flow (MAM/PAM)",                    "Production Asset Management"),
    ("EditShare",         "EFS Shared Storage",                "High-Performance Shared Storage"),
    ("Vizrt",             "Viz One (MAM)",                     "Media Asset Management"),
    ("IPV",               "Curator (MAM)",                     "Browser-Based MAM"),
    ("Storx / SGL",       "FlashNet Archive",                  "Near-Line Archive / LTO Management"),
    ("Sony",              "Ci Media Cloud",                    "Cloud MAM / Collaboration"),
    ("Quantum",           "StorNext File System",              "High-Performance Shared Storage"),

    # ── Live Production / Replay / Routing ────────────────────────────────
    ("EVS",               "XS-VIA Live Production Server",     "Live Production / Slow-Motion Replay"),
    ("EVS",               "Cerebrum Broadcast Controller",     "Broadcast Facility Control"),
    ("EVS",               "IPDirector (Live MAM)",             "Live Content Management"),
    ("Ross Video",        "Ultrix Carbonite Switcher",         "Live Production / IP Routing"),
    ("Ross Video",        "Xpression Graphics",                "Real-Time Graphics / CG"),
    ("Snell Advanced Media","ICE Channel-in-a-Box",            "Channel in a Box / Playout"),
    ("Lawo",              "mc² Audio Production Console",      "IP Audio Production Console"),
    ("Lawo",              "VSM Broadcast Controller",          "Broadcast Facility Control"),
    ("Calrec",            "Brio Audio Console",                "IP Audio Production Console"),

    # ── Graphics ──────────────────────────────────────────────────────────
    ("Vizrt",             "Viz Pilot / Viz Engine",            "Real-Time Graphics"),
    ("Vizrt",             "Viz Mosart Newsroom Automation",    "Newsroom Production Automation"),
    ("Chyron",            "Lyric / PRIME Graphics",            "Real-Time Broadcast CG"),
    ("Singular.live",     "Cloud Graphics Platform",           "Cloud-Native Live Graphics"),

    # ── Playout / Automation ──────────────────────────────────────────────
    ("Pebble Beach",      "Lighthouse Playout Automation",     "Channel Playout Automation"),
    ("Pebble Beach",      "Marina Cloud Playout",              "Cloud-Native Channel Playout"),
    ("Grass Valley",      "iTX Integrated Playout",            "Integrated Playout"),
    ("Harmonic",          "Polaris Playout (Cloud)",           "Cloud Playout / FAST Channel Delivery"),
    ("Cinegy",            "Cinegy Air (Software Playout)",     "Software-Defined Playout"),
    ("Imagine Communications","Selenio MCP Playout",           "Multi-Channel Playout"),
    ("WideOrbit",         "WO Traffic & Billing",              "Traffic / Ad Sales System"),

    # ── Encoding / Transcoding / QC ───────────────────────────────────────
    ("Telestream",        "Vantage Media Processing",          "Transcoding / Workflow Automation"),
    ("Telestream",        "Aurora Automated QC",               "Automated Quality Control"),
    ("Telestream",        "Cloud Port (Cloud Transcoding)",    "Cloud Transcoding"),
    ("Venera Technologies","Pulsar File-Based QC",             "File-Based Automated QC"),
    ("Interra Systems",   "ORION-OTT Stream Monitor",         "OTT / IPTV Quality Monitoring"),

    # ── IP Infrastructure / Signal Transport ──────────────────────────────
    ("Nevion",            "VideoIPath (IP Signal Management)", "IP Broadcast Signal Management"),
    ("Riedel",            "MediorNet (IP Signal Transport)",   "Signal Distribution / Intercom"),
    ("Matrox",            "ConvertIP (SDI-to-IP Gateway)",     "SDI-to-ST2110 Gateway"),
    ("AJA Video",         "IPT / IPR (IP Gateway Series)",     "SDI-to-IP Gateway"),
    ("Imagine Communications","Selenio Network Processor",     "Signal Processing / IP Conversion"),

    # ── Cloud / Streaming / OTT ───────────────────────────────────────────
    ("Harmonic",          "VOS360 Cloud Video Platform",       "Cloud Encoding / OTT Delivery"),
    ("AWS Elemental",     "MediaLive & MediaConnect",          "Cloud Live Encoding / Contribution"),
    ("Brightcove",        "Video Cloud Platform",              "OTT / VOD Platform"),
    ("Bitmovin",          "Video Encoding & Player",           "Cloud Encoding / Adaptive Bitrate"),
    ("Haivision",         "SRT Gateway / Makito Encoder",      "Low-Latency IP Contribution Encoding"),
    ("Wowza",             "Wowza Streaming Engine",            "Live Streaming Server / Origin"),
    ("Mux",               "Mux Video API",                     "Developer-First Video API Platform"),
]

# ── Weekly automation config ─────────────────────────────────────────────────
# How many NEW vendors to generate per weekend run.
# 5 new × 2 calls each × 7s = 70s per run — safe under 10 RPM Pro limit.
# Full 50-vendor list takes ~700s on a cold cache (first ever run).
WEEKLY_NEW      = 5     # new vendors per scheduled Saturday run

# Regenerate cached entries older than this many weeks to keep content fresh.
REFRESH_WEEKS   = 8     # 8 weeks = ~2 months before a brief is refreshed

# Safety cap — never spend more than this many Pro API calls in one run.
# Protects quota when running manually with full cold cache.
MAX_CALLS_PER_RUN = 25  # 25 × 2 calls each × 7s ≈ 350s per run

_SYSTEM_PROMPT = FACTUAL_SAFETY_BLOCK + """

═══════════════════════════════════════════════════════════════════════════
VENDOR HUB ROLE
═══════════════════════════════════════════════════════════════════════════

You are a Lead Broadcast Integration Architect with 15 years of hands-on experience designing and commissioning broadcast facilities — in server rooms, OB trucks, master control suites, and cloud-native media workflows. You have integrated these systems personally and understand exactly how they behave on a live network.

Your audience: systems engineers, broadcast CTOs, and technical directors who are evaluating integration complexity and architectural fit. They do not need marketing copy. They need to know how a system actually works.

ABSOLUTE STYLE RULES — violating any of these is unacceptable:
- NEVER use: "industry-leading", "proven", "innovative", "seamless", "powerful", "cutting-edge", "state-of-the-art", "world-class", "robust", "leverage", "synergy", "best-in-class", "game-changing", "revolutionary"
- Write in the present tense as though describing a live system you are currently working on
- Be specific: use exact protocol names, port numbers, API types, codec names, and standards references where they apply
- If a system has a known real-world limitation or integration pain point, say so plainly
- No introductory fluff. Start the h3 tag immediately.

OUTPUT FORMAT: Valid HTML only. No markdown. No ```html wrappers. No preamble text before the h3 tag."""


# ══════════════════════════════════════════════════════════════════════════════
# PER-VENDOR PROMPT TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════
_VENDOR_PROMPT = """Generate a technical engineering brief for the following broadcast system.

Vendor: {vendor}
Product: {product}
Category hint: {category}

Output this exact HTML structure with no deviations. Replace all bracketed placeholders with real, specific technical content:

<h3>{vendor} {product}</h3>
<p><strong>Category:</strong> {category}</p>

<h4>The Baseline</h4>
<p>[EXACTLY 2 sentences. Define what this system does at a network and signal-processing level. Be specific: mention the underlying architecture (client-server, microservices, hardware appliance), primary connectivity (Ethernet, SDI, fibre), and the core data types it handles (MXF, AAF, XML, REST, SOAP, proprietary protocol). No marketing language.]</p>

<h4>Engineering &amp; Integration Brief</h4>
<ul>
  <li><strong>Protocols &amp; APIs:</strong> [Specify every integration interface this system exposes or consumes: REST API version, SOAP endpoints, MOS protocol (MOS 2.8.5/3.0), NMOS IS-04/IS-05, BXF traffic exchange, SMPTE ST 2110 streams, 12G-SDI/HD-SDI I/O, SNMP/MIBII for monitoring, syslog endpoints, or any vendor-specific SDK. List them all — an integration engineer needs this to plan their middleware.]</li>
  <li><strong>Hybrid Cloud &amp; AI Deployment:</strong> [Describe precisely how this system operates in a hybrid on-premises/cloud or AI-assisted environment: cloud module availability, container support (Kubernetes/Docker), AI-assisted features (auto-tagging, QC, metadata extraction), interoperability with AWS Elemental / Azure Media Services / GCP, and any latency or bandwidth constraints that affect cloud viability. If the system has no meaningful cloud integration, state that clearly and explain the architectural reason.]</li>
  <li><strong>Known Integration Complexities:</strong> [One bullet of honest engineering detail: a real interoperability issue, a configuration dependency (e.g., requires a dedicated broker service, specific NIC firmware version, PTP grandmaster configuration), or a workflow constraint that engineers encounter in practice and that vendor documentation frequently under-describes.]</li>
</ul>

<hr>

Output the HTML block above only. Nothing before the h3 tag. Nothing after the hr tag."""


# ══════════════════════════════════════════════════════════════════════════════
# GEMINI API CALL
# ══════════════════════════════════════════════════════════════════════════════
def _parse_retry_wait(error_body: str) -> float:
    """Extract retry-after seconds from a 429 response body."""
    m = re.search(r"retry.after[:\s]+(\d+)", error_body.lower())
    if m: return float(m.group(1)) + 2
    m = re.search(r"(\d+)\s*second", error_body.lower())
    if m: return float(m.group(1)) + 2
    return 35.0  # conservative default


def gemini_call(vendor: str, product: str, category: str) -> str:
    """
    Call Gemini 2.5 Pro with the vendor prompt.
    Returns raw HTML string from the model.
    Raises RuntimeError on unrecoverable errors.
    """
    user_prompt = _VENDOR_PROMPT.format(
        vendor=vendor, product=product, category=category
    )

    payload = json.dumps({
        "system_instruction": {
            "parts": [{"text": _SYSTEM_PROMPT}]
        },
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature":     0.25,   # lower temp = more consistent structured output
            "maxOutputTokens": 800,    # enough for 3-bullet technical block
        }
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                GEMINI_PRO_URL, data=payload, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                status = r.status
                body   = r.read().decode("utf-8")

            if status == 200:
                data = json.loads(body)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                # Strip any accidental markdown code fences
                text = re.sub(r"```html?\n?|```\n?", "", text).strip()
                return text

            raise RuntimeError(f"HTTP {status}: {body[:200]}")

        except urllib.error.HTTPError as ex:
            body = ex.read().decode("utf-8", errors="replace")

            if ex.code == 429:
                body_lower = body.lower()
                if any(k in body_lower for k in ["daily", "quota", "resource_exhausted", "per day"]):
                    raise RuntimeError(
                        f"DAILY_QUOTA_EXHAUSTED for {vendor} {product}. "
                        "Gemini free tier resets at midnight Pacific Time (08:00 UTC). "
                        "Remaining vendors will be skipped — run again tomorrow."
                    )
                wait = _parse_retry_wait(body)
                wait = min(wait, 40)
                print(f"      ⏱  Rate limited — waiting {wait:.0f}s (attempt {attempt+1}/{MAX_RETRIES+1})...")
                time.sleep(wait)
                continue

            if attempt < MAX_RETRIES:
                time.sleep(4)
                continue

            raise RuntimeError(f"Gemini API HTTP {ex.code}: {body[:300]}")

        except Exception as ex:
            if attempt < MAX_RETRIES:
                time.sleep(4)
                continue
            raise RuntimeError(f"Gemini call error: {ex}")

    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded for {vendor} {product}")


# ══════════════════════════════════════════════════════════════════════════════
# HTML PAGE ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════
def _build_hub_page(vendor_blocks: list[dict]) -> str:
    """
    Assembles vendor blocks into a full static HTML page matching
    thestreamic.in style (same head, nav, footer pattern as other pages).
    """
    today     = datetime.now(timezone.utc).strftime("%B %d, %Y")
    year      = datetime.now().year
    canon_url = f"{BASE_URL}/broadcast-systems-hub.html"

    # Group blocks by category for the Table of Contents
    categories: dict[str, list[dict]] = {}
    for b in vendor_blocks:
        cat = b.get("category", "Other")
        categories.setdefault(cat, []).append(b)

    # ── Table of Contents ──────────────────────────────────────────────────
    toc_items = ""
    for cat, items in categories.items():
        cat_anchor = cat.lower().replace(" ", "-").replace("/", "-").replace("(", "").replace(")", "")
        toc_items += f'<li><strong>{cat}</strong><ul style="margin:4px 0 8px 16px">'
        for item in items:
            slug = f"{item["vendor"]}-{item["product"]}".lower()
            slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
            toc_items += f'<li><a href="#{slug}" style="color:var(--blue);text-decoration:none">{item["vendor"]} {item["product"]}</a></li>'
        toc_items += "</ul></li>"

    # ── Content blocks — bento cards (generated content only) ─────────────
    #
    # Design principle: bento cards activate ONLY for vendors that have been
    # processed by Gemini. Each Saturday batch of 5 adds new bento cards to
    # the top of each category section. Vendors without generated content are
    # NOT shown in the Gemini-generated page (they appear in the static hub).
    #
    content_html = ""
    prev_cat = None
    for b in vendor_blocks:
        cat = b.get("category", "Other")
        if cat != prev_cat:
            cat_anchor = cat.lower().replace(" ", "-").replace("/", "-").replace("(", "").replace(")", "")
            content_html += f"""
<div id="{cat_anchor}" style="margin-top:52px;padding-top:20px;border-top:2px solid var(--ink)">
  <h2 style="font-family:var(--serif);font-size:clamp(20px,2.5vw,28px);letter-spacing:-.03em;margin:0 0 4px">{cat}</h2>
  <p style="font-size:13px;color:var(--ink4);margin:0 0 32px">Engineering briefs for {cat} systems &mdash; researched and written by the Gemini 2.5 Pro pipeline, reviewed by The Streamic editorial team</p>
</div>"""
            prev_cat = cat

        slug = f"{b['vendor']}-{b['product']}".lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
        vendor_safe = b.get("vendor","").replace('"', '&quot;')
        product_safe = b.get("product","").replace('"', '&quot;')
        cat_safe = b.get("category","").replace('"', '&quot;')

        # Bento card wrapping the Gemini-generated HTML block
        content_html += f"""
<div id="{slug}" class="vendor-bento-card" style="background:var(--white);border:1px solid var(--line);border-radius:14px;padding:28px 32px;margin-bottom:20px;transition:box-shadow .2s;position:relative">
  <div style="position:absolute;top:0;left:0;right:0;height:5px;background:var(--blue);border-radius:14px 14px 0 0"></div>
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:20px;margin-top:8px">
    <div>
      <span style="font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:1.2px;color:var(--ink4);display:block;margin-bottom:4px">{vendor_safe}</span>
      <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--blue);background:#f0f7ff;padding:2px 8px;border-radius:4px">{cat_safe}</span>
    </div>
    <span style="font-size:10px;color:var(--ink4);background:var(--bg);padding:3px 10px;border-radius:20px;font-weight:700;white-space:nowrap">AI-researched</span>
  </div>
{b.get("html", "<p>Content not generated.</p>")}
</div>"""

    # ── Schema markup ──────────────────────────────────────────────────────
    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": "Key Broadcast Systems Hub: Engineering Reference for System Integrators",
        "description": "Technical integration briefs for major broadcast vendors including Avid, EVS, Vizrt, Grass Valley, Dalet, Pebble Beach, Harmonic, Telestream, Ross Video, and Nevion.",
        "url": canon_url,
        "author": {"@type": "Organization", "name": "The Streamic"},
        "publisher": {"@type": "Organization", "name": "The Streamic", "url": BASE_URL},
        "datePublished": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "dateModified":  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })

    # ── Full page ──────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <script>
    window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
    gtag('consent','default',{{'analytics_storage':'denied','ad_storage':'denied',
    'ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500}});
  </script>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA}"></script>
  <script>gtag('js',new Date());gtag('config','{GA}');</script>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADS}" crossorigin="anonymous"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Broadcast Systems Deep Dives: AI-Researched Vendor Briefs | The Streamic</title>
  <meta name="description" content="Technical integration briefs for major broadcast vendors: Avid Media Composer, EVS XS-VIA, Vizrt, Grass Valley STRATUS, Dalet Galaxy, Pebble Beach, Harmonic VOS360, Telestream Vantage, and more.">
  <meta name="robots" content="index,follow">
  <meta name="author" content="{AUTHOR}">
  <link rel="canonical" href="{canon_url}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="Broadcast Systems Integration Hub | The Streamic">
  <meta property="og:description" content="Engineering integration briefs for Avid, EVS, Vizrt, Grass Valley, Dalet, Pebble Beach, Harmonic, Telestream, and more.">
  <meta property="og:url" content="{canon_url}">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="style.css">
  <style>
    /* ── Hub-specific overrides ── */
    /* bento card hover */
    .vendor-bento-card:hover {{
      box-shadow:0 6px 24px rgba(0,0,0,.08) !important;
    }}
    .hub-toc {{
      background:#f5f5f7;border-radius:14px;padding:28px 32px;
      margin:32px 0 48px;font-size:14px;
    }}
    .hub-toc h3 {{
      font-family:var(--serif);font-size:18px;margin:0 0 16px;color:var(--ink)
    }}
    .hub-toc ul {{ margin:0;padding-left:0;list-style:none }}
    .hub-toc li {{ margin-bottom:6px }}
    /* Vendor block internal styles */
    #hub-content h3 {{
      font-family:var(--serif);font-size:clamp(16px,1.8vw,20px);
      color:var(--ink);margin:0 0 4px;letter-spacing:-.02em
    }}
    #hub-content h4 {{
      font-size:11px;font-weight:800;text-transform:uppercase;
      letter-spacing:1px;color:var(--blue);margin:20px 0 8px
    }}
    #hub-content p {{ font-size:14.5px;color:var(--ink2);line-height:1.75;margin:0 0 12px }}
    #hub-content ul {{ padding-left:18px;margin:0 0 12px }}
    #hub-content li {{ font-size:14px;color:var(--ink2);line-height:1.7;margin-bottom:8px }}
    #hub-content hr {{ border:0;border-top:1px solid var(--bg);margin:20px 0 0 }}
    /* hide the last hr inside each card */
    #hub-content .vendor-card > hr:last-child {{ display:none }}
    .vendor-count-badge {{
      display:inline-block;background:var(--blue);color:#fff;
      font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;
      margin-left:10px;vertical-align:middle;letter-spacing:.3px
    }}
    .hub-updated {{
      font-size:11px;color:var(--ink4);margin-top:6px;display:block
    }}
    @media(max-width:680px) {{
      #hub-content .vendor-card {{ padding:20px 18px }}
    }}
  </style>
</head>
<body>
<nav class="nav">
  <div class="nav-inner">
    <a href="featured.html" class="nav-logo">
      <img src="assets/logo.png" alt="" onerror="this.style.display='none'" aria-hidden="true">
      <span>The Streamic</span>
    </a>
    <ul class="nav-links">
      <li><a href="featured.html">Home</a></li>
      <li><a href="ai-post-production.html">AI in Broadcasting</a></li>
      <li><a href="howto.html">How-To Guides</a></li>
      <li><a href="broadcast-systems-hub.html" class="active">Systems Hub</a></li>
    </ul>
    <div class="nav-right">
      <a href="about.html" class="nav-desk">About</a>
      <button class="nav-toggle" aria-label="Menu" onclick="document.querySelector('.nav-mob').classList.toggle('open')">
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-mob">
    <a href="featured.html">Home</a>
    <a href="ai-post-production.html">AI in Broadcasting</a>
    <a href="howto.html">How-To Guides</a>
    <a href="broadcast-systems-hub.html">Systems Hub</a>
    <a href="about.html">About</a>
    <a href="contact.html">Contact</a>
  </div>
</nav>

<main>
  <div class="w" style="padding:52px 0 80px;max-width:900px">

    <!-- Page header -->
    <div style="margin-bottom:40px">
      <span style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:1.2px;color:var(--blue);display:block;margin-bottom:12px">Reference</span>
      <h1 style="font-family:var(--serif);font-size:clamp(26px,4vw,44px);letter-spacing:-.04em;color:var(--ink);margin:0 0 16px;line-height:1.1">
        Key Broadcast Systems Hub
        <span class="vendor-count-badge">{len(vendor_blocks)} systems</span>
      </h1>
      <p style="font-size:16px;color:var(--ink2);line-height:1.7;max-width:680px;margin-bottom:12px">
        Engineering integration briefs for the systems that run professional broadcast facilities in 2026 —
        from NLE and MAM platforms to IP signal transport, playout automation, and cloud encoding.
        Each entry covers the actual integration interfaces, protocol stack, and real-world deployment constraints.
      </p>
      <span class="hub-updated">Last generated: {today} by The Streamic Editorial Team using Gemini {GEMINI_PRO_MODEL}</span>
    </div>

    <!-- Editorial transparency note -->
    <div style="background:#f0f7ff;border-left:4px solid var(--blue);border-radius:0 10px 10px 0;padding:16px 20px;margin-bottom:40px;font-size:13.5px;color:var(--ink2)">
      <strong style="color:var(--ink)">How this content is produced:</strong>
      These briefs are generated using an AI language model with a strict technical editorial prompt reviewed by The Streamic's broadcast engineering team.
      Vendor mentions reflect genuine engineering relevance. No vendor has paid for inclusion or influenced content.
      See our <a href="editorial-policy.html" style="color:var(--blue)">Editorial Policy</a> for full disclosure.
    </div>

    <!-- Table of Contents -->
    <div class="hub-toc">
      <h3>Table of Contents</h3>
      <ul>{toc_items}</ul>
    </div>

    <!-- Vendor blocks -->
    <div id="hub-content">
{content_html}
    </div>

    <!-- Author bio -->
    <div class="art-author-bio" style="margin-top:52px">
      <div class="bio-avatar">S</div>
      <div class="bio-body">
        <strong class="bio-name">Prerak K Mehta</strong>
        <span class="bio-title">Founder, The Streamic &middot; Dublin, Ireland</span>
        <p class="bio-text">Broadcast technology professional with total 25+ years of IT and 20 years of Media/Post Production &amp; Broadcast IT systems experience. He covers broadcast engineering, streaming, infrastructure, and media technology trends for The Streamic.</p>
      </div>
    </div>

  </div>
</main>

<script type="application/ld+json">{schema}</script>

<footer class="footer">
  <div class="footer-grid">
    <div>
      <div class="footer-brand">The Streamic</div>
      <p class="footer-tag">Independent broadcast &amp; streaming technology journalism for engineers and media professionals.</p>
    </div>
    <div class="footer-col">
      <h4>Coverage</h4>
      <a href="ai-post-production.html">AI in Broadcasting</a>
      <a href="howto.html">How-To Guides</a>
      <a href="broadcast-systems-hub.html">Systems Hub</a>
    </div>
    <div class="footer-col">
      <h4>Site</h4>
      <a href="about.html">About</a>
      <a href="contact.html">Contact</a>
      <a href="editorial-policy.html">Editorial Policy</a>
      <a href="privacy.html">Privacy Policy</a>
      <a href="terms.html">Terms of Use</a>
    </div>
    <div class="footer-col">
      <h4>Follow</h4>
      <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer">&#x1D54F; @thestreamic</a>
      <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer">in TheStreamic</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>&copy; {year} The Streamic &mdash; thestreamic.in. All rights reserved.</span>
    <span>Independent broadcast technology journalism. All trademarks belong to their respective owners.</span>
  </div>
</footer>

<div id="ts-cookie">
  <div class="cookie-in">
    <div class="cookie-txt">
      <strong>We use cookies</strong>
      Analytics and advertising cookies improve your experience.
      <a href="/privacy.html">Privacy Policy</a>
    </div>
    <div class="cookie-btns">
      <button class="cookie-no" onclick="tsCC(false)">Reject optional</button>
      <button class="cookie-ok" onclick="tsCC(true)">Accept all</button>
    </div>
  </div>
</div>
<script>
(function(){{
  var K='ts_cc',s=localStorage.getItem(K),b=document.getElementById('ts-cookie');
  if(!s&&b)b.style.display='block';
  window.tsCC=function(ok){{
    localStorage.setItem(K,ok?'granted':'denied');
    if(b)b.style.display='none';
    if(typeof gtag!='undefined')gtag('consent','update',{{
      analytics_storage:ok?'granted':'denied',ad_storage:ok?'granted':'denied',
      ad_user_data:ok?'granted':'denied',ad_personalization:ok?'granted':'denied'}});
  }};
  if(s==='granted'&&typeof gtag!='undefined')gtag('consent','update',{{
    analytics_storage:'granted',ad_storage:'granted',
    ad_user_data:'granted',ad_personalization:'granted'}});
}})();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    """
    Weekly automation mode:
      - Loads cache from data/vendor_hub.json
      - Identifies vendors that are:
          (a) Not yet generated (new additions to VENDORS list), OR
          (b) Generated but older than REFRESH_WEEKS (stale — regenerate for freshness)
      - Processes up to WEEKLY_NEW new + any stale vendors, capped at MAX_CALLS_PER_RUN
      - Rebuilds the full HTML page including all cached + newly generated vendors
      - Prints a clear summary of what ran, what was cached, what is pending
    """
    from datetime import timedelta

    # Detect if running in scheduled/CI mode or manual mode
    is_ci = os.environ.get("CI", "") == "true" or os.environ.get("GITHUB_ACTIONS", "") == "true"
    run_mode = os.environ.get("VENDOR_HUB_MODE", "weekly")  # "weekly" | "full" | "refresh_all"

    print("=== generate_vendor_hub.py ===")
    print(f"Mode: {run_mode} | Model: {GEMINI_PRO_MODEL}")
    print(f"Master vendor list: {len(VENDORS)} | WEEKLY_NEW: {WEEKLY_NEW} | REFRESH_WEEKS: {REFRESH_WEEKS}")

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS, exist_ok=True)

    # ── Load existing cache ────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    cached: dict[str, dict] = {}  # key → {html, generated_at}

    if os.path.exists(HUB_JSON):
        try:
            with open(HUB_JSON, encoding="utf-8") as f:
                raw = json.load(f)
            for entry in raw.get("vendors", []):
                if not entry.get("html"):
                    continue
                key = f"{entry['vendor']}|{entry['product']}"
                cached[key] = {
                    "html":         entry["html"],
                    "vendor":       entry["vendor"],
                    "product":      entry["product"],
                    "category":     entry.get("category", ""),
                    "generated_at": entry.get("generated_at", ""),
                }
            print(f"Cache loaded: {len(cached)} vendors from {HUB_JSON}")
        except Exception as ex:
            print(f"Cache load warning: {ex} — starting fresh")

    # ── Categorise vendors from master list ───────────────────────────────
    stale_cutoff = now_utc - timedelta(weeks=REFRESH_WEEKS)
    new_vendors   = []   # not yet in cache
    stale_vendors = []   # in cache but generated_at older than REFRESH_WEEKS

    for vendor, product, category in VENDORS:
        key = f"{vendor}|{product}"
        if key not in cached:
            new_vendors.append((vendor, product, category))
        else:
            gen_at_str = cached[key].get("generated_at", "")
            if gen_at_str:
                try:
                    gen_dt = datetime.fromisoformat(gen_at_str.replace("Z", "+00:00"))
                    if gen_dt < stale_cutoff:
                        stale_vendors.append((vendor, product, category))
                except Exception:
                    pass  # can't parse date — treat as fresh

    print(f"\nVendor status:")
    print(f"  New (not yet generated): {len(new_vendors)}")
    print(f"  Stale (>{REFRESH_WEEKS} weeks old, will refresh): {len(stale_vendors)}")
    print(f"  Fresh (cached, skip):    {len(cached) - len(stale_vendors)}")

    # ── Build work queue for this run ─────────────────────────────────────
    if run_mode == "full" or run_mode == "refresh_all":
        # Manual full run: process everything up to MAX_CALLS_PER_RUN
        # "refresh_all" forces stale vendors to be regenerated too
        work_queue = (new_vendors + stale_vendors)[:MAX_CALLS_PER_RUN]
        # For full mode, if no new/stale, regenerate oldest cached entries
        if not work_queue and run_mode == "full":
            all_keys = [(k, v.get("generated_at","")) for k,v in cached.items()]
            all_keys.sort(key=lambda x: x[1])
            oldest_keys = {k for k,_ in all_keys[:MAX_CALLS_PER_RUN]}
            work_queue = [(v["vendor"], v["product"], v["category"])
                          for k,v in cached.items() if k in oldest_keys]
    else:
        # Weekly scheduled mode: WEEKLY_NEW new + up to 2 stale refreshes
        new_this_run   = new_vendors[:WEEKLY_NEW]
        stale_this_run = stale_vendors[:2]  # refresh 2 oldest stale per week
        work_queue     = (new_this_run + stale_this_run)[:MAX_CALLS_PER_RUN]

    if not work_queue:
        print(f"\n✅ All {len(VENDORS)} vendors are fresh — nothing to generate this run.")
        print(f"   Next refresh due in ~{REFRESH_WEEKS} weeks for oldest entries.")
    else:
        print(f"\nThis run: {len(work_queue)} vendors to generate/refresh")
        print(f"  Estimated time: ~{len(work_queue) * (SLEEP_SECS * 2)}s")

    # ── Process work queue ────────────────────────────────────────────────
    new_calls   = 0
    errors      = 0
    quota_hit   = False

    for vendor, product, category in work_queue:
        key   = f"{vendor}|{product}"
        label = f"[{new_calls+errors+1}/{len(work_queue)}] {vendor} — {product}"
        action = "REFRESH" if key in cached else "NEW    "

        if quota_hit:
            print(f"  SKIP   {label}  (quota exhausted — resume tomorrow after 08:00 UTC)")
            errors += 1
            continue

        print(f"  {action} {label}")
        try:
            html = gemini_call(vendor, product, category)
            if "<h3>" not in html:
                print(f"      ⚠  Response missing <h3> — flagging incomplete")
                html = f"<h3>{vendor} {product}</h3>\n<p><em>Content incomplete. Will retry on next run.</em></p>\n<hr>"

            cached[key] = {
                "html":         html,
                "vendor":       vendor,
                "product":      product,
                "category":     category,
                "generated_at": now_utc.isoformat(),
            }
            new_calls += 1
            print(f"      ✓  {len(html)} chars — saved to cache")

            # Persist cache immediately after every call
            _save_json(list(cached.values()))
            time.sleep(SLEEP_SECS)

        except RuntimeError as ex:
            errors += 1
            err_str = str(ex)
            if "DAILY_QUOTA_EXHAUSTED" in err_str:
                quota_hit = True
                print(f"      ✗  QUOTA HIT — {ex}")
                print(f"         Gemini resets midnight PT = 08:00 UTC = 13:30 IST.")
                print(f"         Already-cached vendors saved. Re-trigger 'vendor_hub' tomorrow.")
            else:
                print(f"      ✗  ERROR: {ex}")
            _save_json(list(cached.values()))

    # ── Build the full HTML page from entire cache (not just this run) ────
    # Sort vendors by master list order so page structure is consistent week to week
    master_order = {f"{v}|{p}": i for i, (v, p, _) in enumerate(VENDORS)}
    all_cached_blocks = sorted(
        cached.values(),
        key=lambda b: master_order.get(f"{b['vendor']}|{b['product']}", 9999)
    )

    if not all_cached_blocks:
        print("\n⚠  No vendor content in cache — HTML page not written.")
        sys.exit(1)

    print(f"\nBuilding hub page from {len(all_cached_blocks)}/{len(VENDORS)} vendors...")
    hub_html = _build_hub_page(all_cached_blocks)
    with open(HUB_HTML, "w", encoding="utf-8") as f:
        f.write(hub_html)

    # ── Summary ────────────────────────────────────────────────────────────
    pending = [v for v, p, _ in VENDORS if f"{v}|{p}" not in cached]
    print(f"""
✅ Run complete:
   Generated this run: {new_calls}
   Errors / skipped:   {errors}
   Total in cache:     {len(cached)}/{len(VENDORS)} vendors
   Pending (future):   {len(pending)} vendors
   HTML page:          {HUB_HTML}
   JSON cache:         {HUB_JSON}""")

    if pending:
        print(f"\n   Next {min(WEEKLY_NEW, len(pending))} vendors on next Saturday run:")
        for v, p, _ in pending[:WEEKLY_NEW]:
            print(f"     - {v} {p}")

    if quota_hit:
        print("\n⏰ Quota reminder: resets 08:00 UTC = 13:30 IST")
        print("   Re-trigger Actions → Run workflow → vendor_hub")


def _save_json(vendor_list: list[dict]) -> None:
    """Persist cache to JSON. Called after every successful API call."""
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model":        GEMINI_PRO_MODEL,
        "total":        len(vendor_list),
        "complete":     sum(1 for v in vendor_list if v.get("html")),
        "vendors":      vendor_list,
    }
    with open(HUB_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
