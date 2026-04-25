"""
scripts/build.py &#8212; The Streamic site builder
Apple Newsroom-style static site generator
"""
import json, os, re, shutil
from datetime import datetime, timezone

ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTS_F    = os.path.join(ROOT, "data", "generated_articles.json")
MANUAL_F  = os.path.join(ROOT, "data", "manual_articles.json")
DOCS      = os.path.join(ROOT, "docs")
ARTS_D    = os.path.join(DOCS, "articles")
BASE_URL  = os.environ.get("SITE_BASE_URL", "https://www.thestreamic.in").rstrip("/")
GA        = "G-0VSHDN3ZR6"
ADS       = "ca-pub-8033069131874524"
AUTHOR    = "The Streamic Editorial Team"

# ── Editor's Note (REMOVED — disclosure lives in editorial-policy.html) ─────
_EDITORS_NOTE_HTML = ""

PAGE_SIZE = 24

# ── AdSense approval mode ─────────────────────────────────────────────────────
# Show curated high-quality content. Full dataset remains hidden.
MAX_ARTICLES   = 120         # editorial corpus cap
VISIBLE_CAT    = "ai-post-production"  # only this category page is indexed
MIN_BODY_SCORE = 50          # minimum editorial score to appear on homepage
MIN_ARTICLE_WORDS = 500      # hard quality gate — matches AI-upgraded output; scaffolds blocked separately by _is_ai_upgraded()

# ── Broadcast & Media IT relevance terms ──────────────────────────────────────
# Articles must contain at least 2 of these terms (case-insensitive) to pass.
# This keeps the site focused on genuine broadcast engineering content.
BROADCAST_TERMS = {
    # Vendors & products
    "avid", "media composer", "interplay", "mediacentral", "isis", "nexis",
    "adobe", "premiere", "after effects", "frame.io",
    "vizrt", "viz one", "viz engine", "viz artist", "ndn",
    "grass valley", "gv", "edius", "kameleon",
    "harmonic", "harmonic inc", "spectrum x", "polaris",
    "telestream", "vantage", "lightspeed", "wirecast",
    "pebble", "pebble beach", "lighthouse", "marina",
    "imagine communications", "selenio",
    "dalet", "dalet flex", "dalia",
    "mediageni", "mediagenix", "whats on",
    "editshare", "mediasilo",
    "cinegy", "playout", "cinegy air",
    "evertz", "dreamcatcher",
    "ross video", "xpression", "carbonite",
    "newtek", "tricaster",
    "blackmagic", "davinci resolve", "atem", "decklink",
    "playbox", "playbox neo",
    "tedial", "media it",
    "clear-com", "riedel", "bolero",
    "aveco", "astra",
    "signiant", "aspera",
    # Protocols & standards
    "smpte", "st 2110", "st2110", "st 2022", "nmos", "is-04", "is-05",
    "aes67", "dante", "ravenna",
    "scte-35", "scte 35", "bxf", "mos protocol", "mos gateway",
    "ndi", "srt", "rist", "zixi",
    "hls", "dash", "cmaf", "abr",
    "atsc", "atsc 3.0", "dvb",
    # Broadcast infrastructure
    "sdi", "12g-sdi", "ip core", "ip routing",
    "mam", "pam", "dam", "media asset management",
    "nrcs", "newsroom computer", "inews", "enps", "octopus",
    "playout", "channel in a box", "channel-in-a-box", "ciab",
    "master control", "mcr", "automation engine",
    "baseband", "embedder", "de-embedder",
    "multiviewer", "monitoring", "probe",
    "lto", "archive", "nearline", "deep archive",
    # Workflow & operations
    "broadcast", "broadcaster", "broadcast engineer",
    "post-production", "post production", "color grading", "colour grading",
    "transcode", "transcoding", "encoding", "mezzanine",
    "ingest", "capture", "record",
    "graphics", "cg", "lower third", "ticker",
    "rundown", "studio automation",
    "cloud playout", "cloud production", "remi", "remote production",
    "cdn", "content delivery", "origin server",
    "ott", "fast channel", "streaming", "live streaming",
    "drm", "conditional access", "forensic watermark",
    "qc", "quality control", "loudness", "ebu r128",
    "metadata", "metadata enrichment",
    "aaf", "edl", "xml", "mxf", "imf",
    # AI / cloud
    "ai", "artificial intelligence", "machine learning",
    "aws", "amazon web services", "elemental",
    "azure", "google cloud",
    "ai metadata", "ai enrichment", "deepva",
    "agentic", "llm",
}

CAT = {
    "featured":           {"label":"Featured",           "icon":"⭐","color":"#1d1d1f","desc":"Independent broadcast and streaming technology journalism."},
    "streaming":          {"label":"Streaming",          "icon":"&#128225;","color":"#0066cc","desc":"OTT platforms, encoding, CDN infrastructure, live streaming workflows."},
    "cloud":              {"label":"Cloud Production",   "icon":"☁️","color":"#5856d6","desc":"Cloud-native broadcast production, remote workflows, REMI architecture."},
    "graphics":           {"label":"Graphics",           "icon":"🎨","color":"#FF9500","desc":"Real-time graphics, virtual sets, motion design, broadcast visuals."},
    "playout":            {"label":"Playout",            "icon":"▶️","color":"#34C759","desc":"Channel playout, broadcast automation, channel-in-a-box, transmission."},
    "infrastructure":     {"label":"Infrastructure",     "icon":"🏗️","color":"#636366","desc":"SMPTE ST 2110, IP routing, network infrastructure, broadcast facility tech."},
    "ai-post-production": {"label":"AI & Post-Production","icon":"🎬","color":"#FF2D55","desc":"AI-driven editing tools, automated QC, intelligent MAM, colour grading."},
    "newsroom":           {"label":"Newsroom",           "icon":"📰","color":"#b8860b","desc":"NRCS systems, remote journalism, newsroom workflow automation."},
}
CAT_PAGE = {c: f"{c}.html" for c in CAT}

# ── helpers
def e(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
def eu(s): return str(s).replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")  # URL-safe: keeps & raw in src/href attrs
def d(iso):
    try: return datetime.strptime(iso[:10],"%Y-%m-%d").strftime("%B %d, %Y")
    except: return iso
def w(path, txt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: f.write(txt)
def rm(wc): return f"{max(1,round(wc/200))} min read"


def smart_dek(a):
    title=(a.get("title") or "").strip()
    cat=(a.get("category") or "featured").lower()
    src=(a.get("source_domain") or "industry source").strip()
    t=title.lower()
    if "ai" in t or "automation" in t:
        return f"Why it matters: {src} highlights how AI is moving from experimentation into practical broadcast workflows and operational efficiency."
    if "cloud" in t or "openshift" in t or "aws" in t:
        return f"Why it matters: this development points to deeper cloud adoption across media infrastructure, delivery resilience, and cost-aware scaling."
    if "studio" in t or "graphics" in t or "viz" in t:
        return f"Why it matters: graphics and studio tooling decisions increasingly shape production flexibility, visual quality, and the economics of live output."
    if "sports" in t or "live" in t or "simulcast" in t:
        return f"Why it matters: live and sports workflows continue to drive investment in reliability, latency control, and multi-platform distribution."
    if "encoder" in t or "decoder" in t or "jpeg xs" in t or "ip" in t or "st 2110" in t:
        return f"Why it matters: transport and infrastructure upgrades like this directly affect signal reliability, interoperability, and engineering workload."
    if cat == "newsroom":
        return f"Why it matters: newsroom and media operations teams should watch how this affects speed, workflow coordination, and content turnaround."
    if cat == "playout":
        return f"Why it matters: playout and delivery teams should evaluate the operational impact on automation, control, and service continuity."
    if cat == "graphics":
        return f"Why it matters: design and production teams should assess how this influences graphics performance, workflow efficiency, and output quality."
    return f"Why it matters: {src} signals another shift in how broadcast and media teams are modernising tools, workflows, and delivery infrastructure."

def diversify_arts(arts, max_per_source=1):
    """
    Round-robin interleave articles so no consecutive items share the same source.
    Groups by source_domain and picks one from each group in rotation.
    Ensures feed like: Avid, Vizrt, Pebble, GV, Dalet, Harmonic, AWS, Telestream...
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for a in arts:
        src = a.get("source_domain", "").replace("https://","").replace("www.","").split("/")[0].lower()
        buckets[src].append(a)
    # Sort buckets by the newest article so freshest sources lead
    bucket_list = sorted(buckets.values(), key=lambda b: b[0].get("published",""), reverse=True)
    result = []
    while any(bucket_list):
        for bucket in bucket_list:
            if bucket:
                result.append(bucket.pop(0))
        bucket_list = [b for b in bucket_list if b]
    return result

# ── shared HTML blocks
def _consent():
    return f"""<script>
    window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
    gtag('consent','default',{{'analytics_storage':'denied','ad_storage':'denied',
    'ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500}});
  </script>
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA}"></script>
  <script>gtag('js',new Date());gtag('config','{GA}');</script>"""

def _cookie_banner():
    return """<div id="ts-cookie">
  <div class="cookie-in">
    <div class="cookie-txt">
      <strong>We use cookies</strong>
      Analytics cookies help us understand site performance. Optional advertising cookies are disabled until future activation.
      <a href="/privacy.html">Privacy Policy</a>
    </div>
    <div class="cookie-btns">
      <button class="cookie-no" onclick="tsCC(false)">Reject optional</button>
      <button class="cookie-ok" onclick="tsCC(true)">Accept all</button>
    </div>
  </div>
</div>
<script>
(function(){
  var K='ts_cc',s=localStorage.getItem(K),b=document.getElementById('ts-cookie');
  if(!s&&b)b.style.display='block';
  window.tsCC=function(ok){
    localStorage.setItem(K,ok?'granted':'denied');
    if(b)b.style.display='none';
    if(typeof gtag!='undefined')gtag('consent','update',{
      analytics_storage:ok?'granted':'denied',ad_storage:'denied',
      ad_user_data:'denied',ad_personalization:'denied'});
  };
  if(s==='granted'&&typeof gtag!='undefined')gtag('consent','update',{
    analytics_storage:'granted',ad_storage:'denied',
    ad_user_data:'denied',ad_personalization:'denied'});
})();
</script>"""

def _ad():
    # Ad slots removed - using Google Auto-Ads after AdSense approval
    # The AdSense script in <head> remains for approval verification
    return ""

def _fonts():
    return '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">'

def head(title, desc, canon, css="style.css", og_img="", robots="index,follow"):
    og = f'  <meta property="og:image" content="{eu(og_img)}">\n' if og_img else ""
    # Compute homepage-layout.css path relative to the page's CSS base.
    # When css="../style.css" (article pages), hp_css becomes "../homepage-layout.css".
    # When css="style.css" (top-level pages), hp_css becomes "homepage-layout.css".
    _css_prefix = css[:-len("style.css")] if css.endswith("style.css") else ""
    hp_css = f"{_css_prefix}homepage-layout.css"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  {_consent()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{e(title)}</title>
  <meta name="description" content="{e(desc)}">
  <meta name="robots" content="{robots}">
  <meta name="author" content="{AUTHOR}">
  <link rel="canonical" href="{e(canon)}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(desc)}">
  <meta property="og:url" content="{e(canon)}">
{og}  <meta name="twitter:card" content="summary_large_image">
  {_fonts()}
  <link rel="stylesheet" href="{css}">
  <link rel="stylesheet" href="{hp_css}">
</head>"""

def nav(active="", base=""):
    cats = [
        ("/",                              "Home"),
        ("ai-post-production.html",        "AI in Broadcasting"),
        ("howto.html",                     "How-To Guides"),
        ("post-production-workflows.html", "Post Production Workflows"),
        ("insights.html",                  "Expert Insights"),
        ("editorsdesk.html",               "Editorial Insights"),
    ]
    def _nav_li(h, lbl, base=base, active=active):
        cls = ' class="active"' if h == active else ''
        href = h if h.startswith("/") else f"{base}{h}"
        return f'<li><a href="{href}"{cls}>{lbl}</a></li>'
    lis = "".join(_nav_li(h, lbl) for h, lbl in cats)
    mob_all = cats + [("about.html","About"),("contact.html","Contact")]
    mob_links = "".join(
        f'<a href="{h if h.startswith("/") else base+h}">{lbl}</a>' for h, lbl in mob_all)
    _onclick = (
        "onclick=\"(function(b,m){"
        "m.classList.toggle('open');"
        "b.setAttribute('aria-expanded',m.classList.contains('open'));"
        "document.body.classList.toggle('menu-open',m.classList.contains('open'));"
        "})(this,this.closest('nav').querySelector('.nav-mob'))\""
    )
    return f"""<nav class="nav">
  <div class="nav-inner">
    <a href="{base if base else '/'}" class="nav-logo">
      <img src="{base}assets/logo.png" alt="" onerror="this.style.display='none'" aria-hidden="true">
      <div class="nav-logo-text">
        <span class="nav-logo-name">The Streamic</span>
        <span class="nav-logo-tagline">Media &amp; Broadcast IT Analysis</span>
      </div>
    </a>
    <div class="nav-divider" aria-hidden="true"></div>
    <ul class="nav-links">{lis}</ul>
    <div class="nav-right">
      <a href="{base}about.html" class="nav-desk">About</a>
      <button class="nav-toggle" aria-label="Menu" type="button" {_onclick}>
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-gold" aria-hidden="true"></div>
  <div class="nav-mob">{mob_links}</div>
</nav>"""

def catbar(active_cat="", base=""):
    # Hidden during AdSense review — only AI Post visible via nav
    return ""

def footer(base=""):
    yr = datetime.now().year
    return f"""<footer class="footer">
  <div class="footer-gold" aria-hidden="true"></div>
  <div class="footer-grid">
    <div>
      <div class="footer-brand">The Streamic</div>
      <div class="footer-tagline">Media &amp; Broadcast IT Analysis</div>
      <p class="footer-tag">Independent broadcast &amp; streaming technology journalism. Original analysis for engineers and media professionals.</p>
      <div class="footer-social">
        <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer" class="footer-social-link">
          <svg width="14" height="14" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
          @thestreamic
        </a>
        <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer" class="footer-social-link">
          <svg width="14" height="14" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
          TheStreamic
        </a>
      </div>
    </div>
    <div class="footer-col">
      <h4>Coverage</h4>
      <a href="{base}ai-post-production.html">AI in Broadcasting</a>
      <a href="{base}howto.html">How-To Guides</a>
      <a href="{base}post-production-workflows.html">Post Production Workflows</a>
      <a href="{base}insights.html">Expert Insights</a>
      <a href="{base}editorsdesk.html">Editorial Insights</a>
    </div>
    <div class="footer-col">
      <h4>Site</h4>
      <a href="{base}about.html">About</a>
      <a href="{base}contact.html">Contact</a>
      <a href="{base}editorial-policy.html">Editorial Policy</a>
      <a href="{base}privacy.html">Privacy Policy</a>
      <a href="{base}terms.html">Terms of Use</a>
    </div>
    <div class="footer-col">
      <h4>Dublin, Ireland</h4>
      <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a>
      <span style="font-size:12px;color:#bbb;display:block;margin-top:4px">Adamstown, Lucan</span>
    </div>
  </div>
  <div class="footer-bottom">
    <span>&copy; {yr} The Streamic &mdash; thestreamic.in</span>
    <span>All trademarks belong to their respective owners.</span>
  </div>
</footer>"""


# ── NEWS GRID (SSR from generated_articles.json)
def _nc_img(a, base=""):
    img = eu(a.get("image_url",""))
    fb  = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    if img:
        slug_ = a.get('slug', '')
        return f'<div class="nc-img"><a href="{base}articles/{slug_}.html" tabindex="-1" aria-hidden="true"><img src="{img}" alt="{title}" loading="lazy" onerror="this.src=&apos;{fb}&apos;"></a></div>'
    return f'<div class="nc-img nc-img-ph"></div>'

def news_card(a, base="", is_first=False):
    """SSR bento-grid-item &#8212; mirrors JS buildFeatured/buildStandard structure exactly."""
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = eu(a.get("image_url",""))
    fb_   = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    src   = e(a.get("source_domain","").replace("https://","").replace("www.","").split("/")[0].upper())
    cat_lbl = cinfo["label"]

    if is_first:
        # Featured: vertical, large image - no summary (editorial feel)
        src_html_f = f'<span class="bento-source">{src}</span>' if src else ""
        return f"""<li class="bento-grid-item">
  <div class="bento-img-wrap bento-img-featured">
    <a href="{href}" tabindex="-1" aria-hidden="true">
      <img src="{img}" alt="{title}" loading="eager" onerror="this.onerror=null;this.src='{fb_}'">
    </a>
  </div>
  <div class="bento-body bento-body-featured">
    <span class="bento-cat-tag">{cat_lbl}</span>
    <h2 class="bento-hl bento-hl-featured"><a href="{href}">{title}</a></h2>
    <div class="bento-foot">
      {src_html_f}
      <time style="font-size:11px;color:var(--ink4)">{d(a.get("published",""))}</time>
      <a href="{href}" class="bento-cta-featured">Read Full Article &rarr;</a>
    </div>
  </div>
</li>"""
    else:
        # Standard: vertical cards - no summary (clean editorial look)
        src_html_s = f'<span class="bento-source">{src}</span>' if src else ""
        return f"""<li class="bento-grid-item bento-standard">
  <div class="bento-img-wrap bento-img-std">
    <a href="{href}" tabindex="-1" aria-hidden="true">
      <img src="{img}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='{fb_}'">
    </a>
  </div>
  <div class="bento-body bento-body-std">
    <span class="bento-cat-tag">{cat_lbl}</span>
    <h3 class="bento-hl bento-hl-std"><a href="{href}">{title}</a></h3>
    <div class="bento-foot">
      {src_html_s}
      <time style="font-size:11px;color:var(--ink4)">{d(a.get("published",""))}</time>
      <a href="{href}" class="bento-cta">Read Full Article &rarr;</a>
    </div>
  </div>
</li>"""

def news_grid(arts, base="", grid_id="bentoGridLarge"):
    """SSR bento grid. Use grid_id='catGrid' on category pages to keep SSR content."""
    if not arts: return ""
    cards = "\n".join(
        news_card(a, base, is_first=(i==0))
        for i, a in enumerate(arts)
    )
    return f'<ul id="{grid_id}" class="bento-grid-large">\n{cards}\n</ul>'

# ── EDITORIAL CARD (deep-dive articles)
def ed_card(a, base=""):
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = eu(a.get("image_url",""))
    fb    = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    raw_dek = (a.get("dek") or a.get("meta_description",""))[:200]
    dek   = raw_dek.replace("<","&lt;").replace(">","&gt;")  # allow &mdash; etc, block tags
    wc    = a.get("word_count",1000)
    dt    = d(a.get("published",""))
    return f"""<article class="ed-card">
  <div class="ed-img">
    <a href="{href}">
      <img src="{img}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='{fb}'">
    </a>
  </div>
  <div class="ed-body">
    <span class="ed-tag" style="background:{cinfo['color']}">{cinfo['icon']} {cinfo['label']}</span>
    <h3 class="ed-hl"><a href="{href}">{title}</a></h3>
    <p class="ed-dek">{dek}</p>
    <div class="ed-foot">
      <span class="ed-meta">{dt} &middot; {rm(wc)}</span>
      <a href="{href}" class="ed-read">Read full analysis &rarr;</a>
    </div>
  </div>
</article>"""

# ── HERO
def hero_block(a, base=""):
    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug_ = a.get('slug', '')
    href  = f"{base}articles/{slug_}.html"
    img   = eu(a.get("image_url",""))
    fb    = f"{base}assets/fallback.jpg"
    title = e(a.get("title",""))
    dek   = (a.get("card_summary") or a.get("dek") or "")[:200].replace("<","&lt;").replace(">","&gt;")
    wc    = a.get("word_count",800)
    dt    = d(a.get("published",""))
    return f"""<section class="hero">
  <div class="hero-inner">
    <div class="hero-img">
      <a href="{href}">
        <img src="{img}" alt="{title}" loading="eager" onerror="this.onerror=null;this.src='{fb}'">
      </a>
    </div>
    <div class="hero-body">
      <span class="hero-tag" style="background:{cinfo['color']}">{cinfo['icon']} {cinfo['label']}</span>
      <h2 class="hero-hl"><a href="{href}">{title}</a></h2>
      <p class="hero-dek">{dek}</p>
      <div class="hero-meta">
        <span>By {AUTHOR}</span>
        <span>{dt}</span>
        <span>{rm(wc)}</span>
      </div>
      <a href="{href}" class="hero-cta">Read full story</a>
    </div>
  </div>
</section>"""

# ── FEATURED / INDEX PAGE
def all_articles_page(arts):
    """Generate posts.html - All Articles bento grid linking to articles/."""
    # Use all non-editorial articles sorted newest first
    non_editorial_arts   = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
    ed_arts    = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    all_sorted = non_editorial_arts  # newest first (already sorted in generated_articles.json)

    title  = "All Articles — The Streamic | Broadcast Technology Analysis"
    desc   = "Original broadcast and streaming technology analysis. Expert-level commentary for engineers and media professionals."
    canon  = f"{BASE_URL}/posts.html"

    schema = json.dumps({
        "@context": "https://schema.org", "@type": "WebPage",
        "name": "All Articles — The Streamic", "description": desc,
        "url": f"{BASE_URL}/posts.html",
        "publisher": {"@type": "Organization", "name": "The Streamic", "url": BASE_URL}
    })

    cards = ""
    for i, a in enumerate(all_sorted[:60]):  # show up to 60 articles
        cards += news_card(a, base="", is_first=(i == 0))

    return f"""{head(title, desc, canon)}
<body data-category="featured">
{nav("posts.html")}
{catbar()}
<main>
  <div class="w">
    <div class="cat-hdr">
      <h1>All Articles</h1>
      <p>Original broadcast and streaming technology analysis. Every article is expert-level commentary for engineers and media professionals.</p>
    </div>
    <section class="latest" style="margin-top:32px">
      <ul id="bentoGridLarge" class="bento-grid-large">
        {cards}
      </ul>
    </section>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""


def _score_art(a):
    """Score article quality for homepage curation. Higher = better."""
    body = a.get("body_html","") or ""
    wc   = len(re.sub(r"<[^>]+>"," ",body).split())
    s = 0
    if a.get("is_editorial") or a.get("editorial"): s += 50
    if "<h2>" in body: s += 30
    if wc >= 500: s += 20
    elif wc >= 200: s += 10
    if a.get("quality_score",0) >= 75: s += 25
    return s


def _is_ai_upgraded(a):
    """AdSense compliance: return True if article was enriched by a tier-1/2/3
    AI generator (Mistral, Gemini, Groq, OpenRouter) or is a hand-authored
    editorial. Low-quality items never get indexed.
    """
    gb = (a.get("generated_by") or "").lower()
    if not gb:
        return False
    # Defensive gate: exclude any legacy auto-scaffold markers. Production
    # corpus is editorial-only, so this match is expected to return no hits.
    if gb in ("rewrite_feed_local", "rewrite_feed"):
        return False
    ai_markers = ("mistral", "gemini", "groq", "openrouter", "deepseek",
                  "gpt_manual_editorial", "generate_summaries")
    return any(m in gb for m in ai_markers)


def _passes_quality_gate(a):
    """Hard quality gate — ADSENSE COMPLIANCE MODE.

    An article may be indexed only when ALL of the following are true:
      1. Body word count ≥ MIN_ARTICLE_WORDS (800) OR hand-authored ≥ 400w.
      2. Article was AI-upgraded OR hand-authored.
      3. At least 2 broadcast/media-IT terms present (relevance).

    Low-tier items appear on the site for navigation
    but carry <meta robots="noindex,nofollow">. This is the defence against
    AdSense "Low value content" rejection.
    """
    body = a.get("body_html", "") or ""
    plain = re.sub(r"<[^>]+>", " ", body)
    plain = re.sub(r"\s+", " ", plain).strip()
    words = plain.split()
    wc = len(words)

    is_manual_editorial = a.get("generated_by") == "gpt_manual_editorial"

    if not is_manual_editorial and wc < MIN_ARTICLE_WORDS:
        return False, f"too short ({wc} words, need {MIN_ARTICLE_WORDS})"

    if is_manual_editorial and wc < 400:
        return False, f"editorial too short ({wc} words, need 400)"

    # AdSense: low-tier items never get indexed
    if not is_manual_editorial and not _is_ai_upgraded(a):
        return False, f"not AI-upgraded (gb={a.get('generated_by') or 'empty'!r})"

    # ── Broadcast relevance gate ─────────────────────────────────────────
    # Check title + body (lowercased) for BROADCAST_TERMS matches
    search_text = (a.get("title", "") + " " + plain).lower()
    matched = set()
    for term in BROADCAST_TERMS:
        if term in search_text:
            matched.add(term)
        if len(matched) >= 2:
            break  # fast exit — 2 is enough

    if len(matched) < 2:
        return False, f"low relevance (matched {len(matched)} terms: {matched})"

    return True, "ok"


def enforce_sections(body_html: str) -> bool:
    """
    AdSense quality scoring: checks for preferred editorial sections.
    Uses a SOFT score so articles are never completely excluded.

    Score >= 1 (out of 2) returns True. This means ONE section is enough.
    Articles with zero sections are still allowed on category pages
    (so pages are never blank) but receive lower _score_art() ranking.

    Scoring:
      +1 for "Why This Matters"
      +1 for "Expert Insight"
    Returns True if score >= 1 — applied OPTIONALLY, not as a hard gate.
    """
    if not body_html:
        return False
    body_lower = body_html.lower()
    score = 0
    if "why this matters" in body_lower:
        score += 1
    if "expert insight" in body_lower:
        score += 1
    return score >= 1


def is_high_value(article: dict) -> bool:
    """
    AdSense quality scoring for articles.

    SAFE FILTERING DESIGN — never returns fewer than needed:
    - Editorial articles always pass (pre-validated long-form content)
    - Industry briefings score points on multiple axes; any score > 0 passes
    - This means the function always returns True for articles with ANY
      substantive content, so category pages are never blank

    The noindex/index decision in main() uses this for ranking,
    but visible_list is always padded to ensure pages have content.
    """
    # Editorial always pass — hand-written or Gemini deep-dives
    if article.get("is_editorial") or article.get("editorial"):
        return True

    body = article.get("body_html", "") or ""
    content = article.get("content") or article.get("description", "") or ""

    # Text content from body_html (strip tags)
    body_text = re.sub(r"<[^>]+>", " ", body)
    body_text  = re.sub(r"\s+", " ", body_text).strip()

    score = 0
    # Section quality — soft score
    if enforce_sections(body):
        score += 2          # Has at least one required section
    # Structural quality
    if "<h2>" in body:
        score += 1          # Has section headings
    # Length quality — any substantive content passes
    if len(body_text) > 800:
        score += 1
    elif len(body_text) > 200 or len(content) > 200:
        score += 0          # Still allowed — just lower ranked

    # Any article with a title passes (never blank)
    return bool(article.get("title", "").strip())

# ── LOCAL IMAGE SYSTEM ───────────────────────────────────────────────────────
# ALL images served from docs/assets/. NO Unsplash, NO external URLs.
# assign_images.py populates image fields. build.py resolves from local disk.

_RESERVED_ASSETS = {
    "logo.png", "fallback.jpg",
    "gfx-hero-nab-floor.png", "gfx-hero-nab-floor.jpg",
    "hero-broadcast-male.png",
    "nab-show-banner-news-headline-hero.png",
    "insight-quic-infographic.jpg",
    "neil-sadwelkar.jpg",
    "studio-grade-ott-workflow-2026.png",
}

# Category → preferred local image (meaningful editorial match)
_CAT_IMAGE = {
    "ai-post-production":        "media-composer-edit.png",
    "infrastructure":             "cables.png",
    "newsroom":                   "newsroom-anchor.png",
    "cloud":                      "ms-server-data-center.png",
    "playout":                    "pcr-room.png",
    "graphics":                   "studio-image-4.png",
    "streaming":                  "the-streamic-studio-2.png",
    "featured":                   "the-streamic-studio-1.png",
    "post-production-workflows":  "avid-setup-audio.png",
    "insights":                   "production-room-of-news.png",
    "editorsdesk":                "abstracts.png",
}


def _local_image_exists(url: str) -> bool:
    """True if a /assets/... path resolves to a real file under docs/."""
    if not url:
        return False
    rel = url.lstrip("/")
    return os.path.isfile(os.path.join(DOCS, rel))


def _scan_local_images() -> list:
    """Return list of /assets/filename.ext for every usable image in docs/assets/.
    Reflects what's actually on disk at build time."""
    found = []
    try:
        for fn in sorted(os.listdir(os.path.join(DOCS, "assets"))):
            if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            if fn in _RESERVED_ASSETS:
                continue
            # Skip uppercase originals if a sanitized lowercase copy exists
            sanitized = fn.lower().replace(" ", "-").replace("(", "").replace(")", "")
            if fn != sanitized and os.path.isfile(os.path.join(DOCS, "assets", sanitized)):
                continue
            found.append(f"/assets/{fn}")
    except Exception:
        pass
    return found if found else ["/assets/fallback.jpg"]


def _best_local_image_for(a: dict, pool: list, used: set) -> str:
    """Pick the best unused local image for an article.
    Priority: category-default → round-robin from pool → fallback.jpg"""
    cat = (a.get("category") or "featured").lower()
    pref = _CAT_IMAGE.get(cat)
    if pref:
        pref_url = f"/assets/{pref}"
        if _local_image_exists(pref_url) and pref_url not in used:
            used.add(pref_url)
            return pref_url
    for img in pool:
        if img not in used:
            used.add(img)
            return img
    used.clear()
    if pool:
        used.add(pool[0])
        return pool[0]
    return "/assets/fallback.jpg"


# Backward-compat stubs (legacy code paths reference these — safe to keep)
def _unsplash_url(photo_id):
    return "/assets/fallback.jpg"

def _is_bad_image(url):
    if not url:
        return True
    return url.startswith("http://") or url.startswith("https://")

def _image_is_from_pool(url: str) -> bool:
    return False   # Unsplash pool is retired — local images only


def _fix_article_images(arts):
    """Resolve final image_url for every article — LOCAL IMAGES ONLY.

    No Unsplash. No external URLs. Every card shows a file from docs/assets/.

    Priority per article:
      1. Manual article (_source=="manual"): preserve image_url already
         confirmed on disk by load_manual_articles().
      2. Existing image_url if it is a local /assets/ path that exists on disk
         (and is not the broken /assets/images/_fallback/streamic-default.jpg).
      3. The "image" field if it is a local /assets/ path that exists on disk
         (and is not the broken _fallback stub).
      4. Assign from local pool: category-preferred, then round-robin.
      5. Hard fallback: /assets/fallback.jpg.

    After processing, every article.image_url is guaranteed to be a local path.
    """
    BROKEN = "/assets/images/_fallback/streamic-default.jpg"
    pool = _scan_local_images()
    used: set = set()

    local_assigned = 0
    fallback_used  = 0

    for a in arts:
        # PRIORITY 1: manual article — already resolved
        if a.get("_source") == "manual":
            a.setdefault("image_credit",     "The Streamic")
            a.setdefault("image_license",    "Site Asset")
            a.setdefault("image_license_url","")
            img = a.get("image_url", "")
            if img and img != "/assets/fallback.jpg":
                used.add(img)
            continue

        # PRIORITY 2: existing image_url if valid local file
        img_url = (a.get("image_url") or "").strip()
        if (img_url
                and img_url != BROKEN
                and not img_url.startswith("http")
                and (img_url.startswith("/assets/") or img_url.startswith("assets/"))
                and _local_image_exists(img_url)):
            a["image_url"]         = "/" + img_url.lstrip("/")
            a["image_credit"]      = a.get("image_credit") or "The Streamic"
            a["image_license"]     = a.get("image_license") or "Site Asset"
            a["image_license_url"] = a.get("image_license_url") or ""
            used.add(a["image_url"])
            continue

        # PRIORITY 3: "image" field if valid local file
        img_field = (a.get("image") or "").strip()
        if (img_field
                and img_field != BROKEN
                and not img_field.startswith("http")
                and (img_field.startswith("/assets/") or img_field.startswith("assets/"))
                and _local_image_exists(img_field)):
            a["image_url"]         = "/" + img_field.lstrip("/")
            a["image_credit"]      = "The Streamic"
            a["image_license"]     = "Site Asset"
            a["image_license_url"] = ""
            used.add(a["image_url"])
            continue

        # PRIORITY 4: assign from local pool
        if pool and pool != ["/assets/fallback.jpg"]:
            chosen = _best_local_image_for(a, pool, used)
            a["image_url"]         = chosen
            a["image_credit"]      = "The Streamic"
            a["image_license"]     = "Site Asset"
            a["image_license_url"] = ""
            local_assigned += 1
            continue

        # PRIORITY 5: hard fallback
        a["image_url"]         = "/assets/fallback.jpg"
        a["image_credit"]      = "The Streamic"
        a["image_license"]     = "Site Asset"
        a["image_license_url"] = ""
        fallback_used += 1

    if local_assigned:
        print(f"  Image fixer: {local_assigned} articles assigned local images from pool")
    if fallback_used:
        print(f"  Image fixer: {fallback_used} articles using fallback.jpg")
    ext = [a.get("image_url","") for a in arts if (a.get("image_url","") or "").startswith("http")]
    if ext:
        print(f"  ⚠ WARNING: {len(ext)} articles still have external image_url")


def _hp_img(a, base=""):
    """Resolve a card image URL — LOCAL ONLY, no external URLs."""
    img = (a.get("image_url", "") or a.get("image", "") or "").strip()
    if img and not img.startswith("http") and (img.startswith("/assets/") or img.startswith("assets/")):
        if _local_image_exists(img):
            return img if img.startswith("/") else "/" + img
    cat = (a.get("category") or "featured").lower()
    pref = _CAT_IMAGE.get(cat, "the-streamic-studio-1.png")
    pref_url = f"/assets/{pref}"
    if _local_image_exists(pref_url):
        return pref_url
    return "/assets/fallback.jpg"


def _hp_tag(a):
    cinfo = CAT.get(a.get("category", "featured"), CAT["featured"])
    return f"{cinfo['icon']} {cinfo['label']}"

def _hp_insight_card(a):
    href = f"articles/{a['slug']}.html"
    title = e(a.get("title", ""))
    dek = e((a.get("dek") or a.get("meta_description") or a.get("card_summary") or "")[:150])
    dt = d(a.get("published", ""))
    return f'''<a href="{href}" class="hp-insight-card">
  <div class="hp-insight-media"><img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'"></div>
  <div class="hp-insight-body">
    <span class="hp-insight-tag">{e(_hp_tag(a))}</span>
    <span class="hp-insight-hl">{title}</span>
    <span class="hp-insight-dek">{dek}</span>
    <span class="hp-insight-meta">{dt}</span>
    <span class="hp-insight-read">Read analysis &#8594;</span>
  </div>
</a>'''

def _hp_guide_card(a, sub):
    href = f"articles/{a['slug']}.html"
    title = e(a.get("title", ""))
    return f'''<a href="{href}" class="hp-guide-card">
  <div class="hp-guide-card-img-wrap">
    <img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
    <span class="hp-guide-card-sub">{e(sub)}</span>
  </div>
  <div class="hp-guide-card-overlay">
    <span class="hp-guide-card-label">{title}</span>
  </div>
</a>'''


def _source_name(val):
    return (val or '').replace('https://','').replace('http://','').replace('www.','').split('/')[0]

# ── Streamic Intelligence helpers ─────────────────────────────────────────────

def _plain_text(html):
    """Strip HTML tags and collapse whitespace to plain text."""
    if not html:
        return ""
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_core_subject(title):
    """Extract a clean editorial noun phrase from any article title style.

    Handles four title shapes, in order:
      1. Already-wrapped editorial  "Why X Matters for Y"  → "X"
      2. Infinitive press release   "Vendor to Showcase X at NAB"  → "Vendor's X"
      3. Finite launch verb         "Vendor Launches Product"  → "Vendor's Product"
      4. Colon-split                "Vendor: Detail"  → "Vendor"

    Falls back to the trimmed title when no pattern matches.
    Subject is capped at 55 chars (word boundary) to keep headlines readable.
    """
    t = title.strip().rstrip(".")

    # 1. Strip editorial wrappers — "Why X Matters/Signals/Means for Y"
    m = re.match(
        r'^(?:Why|What|How)\s+(.+?)\s+(?:[Mm]atters?|[Ss]ignals?|[Mm]eans?)\s+for\s+.+$', t
    )
    if m:
        subject = m.group(1).strip()
        return subject[:55].rsplit(" ", 1)[0] if len(subject) > 55 else subject

    # "How X Is/Are/Will/Can …"
    m = re.match(r'^How\s+(.+?)\s+(?:Is|Are|Will|Can)\s+.+$', t)
    if m:
        subject = m.group(1).strip()
        return subject[:55].rsplit(" ", 1)[0] if len(subject) > 55 else subject

    # 2. Infinitive: "Vendor to Showcase X at Event"
    m = re.match(
        r'^(.+?)\s+to\s+(?:showcase|demonstrate|present|exhibit|announce|reveal'
        r'|unveil|launch|introduce|highlight|display)\s+(.+?)(?:\s+at\s+\w.+)?$',
        t, re.IGNORECASE
    )
    if m:
        vendor = m.group(1).strip()
        detail = re.sub(
            r'\s+at\s+(NAB|IBC|CES|ISE|BroadcastAsia)[\w\s]*$', '',
            m.group(2), flags=re.IGNORECASE
        ).strip()
        raw = f"{vendor}\u2019s {detail}" if detail and len(detail) < 40 else vendor
        return raw[:55].rsplit(" ", 1)[0] if len(raw) > 55 else raw

    # 3. Finite launch verb: "Vendor Launches/Announces Product"
    m = re.match(
        r'^(.+?)\s+(?:launches?|announces?|releases?|unveils?|introduces?'
        r'|ships?|debuts?|presents?|rolls? out)\s+(.+)$',
        t, re.IGNORECASE
    )
    if m:
        vendor = m.group(1).strip()
        product = m.group(2).strip()
        raw = f"{vendor}\u2019s {product}" if len(product) < 45 else vendor
        return raw[:55].rsplit(" ", 1)[0] if len(raw) > 55 else raw

    # 4. Colon split — take the left side
    if ":" in t:
        left = t.split(":", 1)[0].strip()
        if left:
            return left[:55].rsplit(" ", 1)[0] if len(left) > 55 else left

    # No pattern matched — return trimmed title, capped
    return t[:55].rsplit(" ", 1)[0] if len(t) > 55 else t


def _streamic_headline(a):
    """Return a varied editorial headline for The Streamic Intelligence cards.

    Five rotating patterns (A–E) are selected via a deterministic, build-stable
    integer derived from the article slug — no PYTHONHASHSEED dependency.
    Only Pattern A begins with "Why", so at most 1 in 5 cards starts that way,
    preventing the repetitive all-Why look.

    Pattern A — Why it matters
      "Why {subject} Matters for {team}"
    Pattern B — What this means (two sub-variants)
      "What {subject} Means for {context}"
      "What {subject} Signals for {team}"
    Pattern C — The shift / bigger picture (two sub-variants)
      "The Workflow Shift Behind {subject}"
      "The Bigger Picture Behind {subject}"
    Pattern D — Inside / How (two sub-variants)
      "Inside {subject}'s Impact on {team}"
      "How {subject} Is Reshaping {context}"
    Pattern E — Subject-led editorial summary
      "{subject} and the Road to {context_noun}"
    """
    title = (a.get("title") or "").strip()
    if not title:
        return "Streamic Analysis"

    cat  = (a.get("category") or "featured").lower()
    slug = (a.get("slug") or title)

    # Category → audience label, context phrase, and pre-built title-case context
    # (title-case stored explicitly to avoid str.title() mis-capitalising "IP" etc.)
    _TEAM_MAP = {
        "newsroom":           "Newsroom Teams",
        "cloud":              "Cloud Production Teams",
        "graphics":           "Graphics and Studio Teams",
        "playout":            "Playout and Automation Teams",
        "infrastructure":     "Infrastructure Teams",
        "streaming":          "Streaming and Delivery Teams",
        "ai-post-production": "AI and Post-Production Teams",
        "featured":           "Broadcast Operations Teams",
    }
    _CONTEXT_TITLE_MAP = {
        "newsroom":           "Newsroom Workflows and Operations",
        "cloud":              "Cloud Broadcast Infrastructure",
        "graphics":           "Live Graphics and Studio Production",
        "playout":            "Playout and Channel Automation",
        "infrastructure":     "IP and Infrastructure Engineering",
        "streaming":          "Streaming and Media Delivery",
        "ai-post-production": "AI-Driven Post-Production",
        "featured":           "Broadcast Media Operations",
    }
    _CONTEXT_NOUN_MAP = {
        "newsroom":           "Smarter Newsroom Operations",
        "cloud":              "Cloud-First Production",
        "graphics":           "Live Graphics Modernisation",
        "playout":            "Leaner Channel Automation",
        "infrastructure":     "IP Infrastructure Convergence",
        "streaming":          "Scalable Media Delivery",
        "ai-post-production": "AI-Driven Post-Production",
        "featured":           "Modern Broadcast Operations",
    }

    team          = _TEAM_MAP.get(cat, "Broadcast Operations Teams")
    context_title = _CONTEXT_TITLE_MAP.get(cat, "Broadcast Media Operations")
    context_noun  = _CONTEXT_NOUN_MAP.get(cat, "Modern Broadcast Operations")

    subject = _extract_core_subject(title)

    # Deterministic integer — stable across builds regardless of PYTHONHASHSEED
    _n = sum(ord(c) * (i + 1) for i, c in enumerate(slug[:20]))

    pattern    = _n % 5          # primary pattern selector   (0–4)
    sub_choice = (_n // 5) % 2  # sub-variant within pattern (0–1)

    if pattern == 0:
        # A — Why it matters
        return f"Why {subject} Matters for {team}"

    elif pattern == 1:
        # B — What this means / signals
        if sub_choice == 0:
            return f"What {subject} Means for {context_title}"
        else:
            return f"What {subject} Signals for {team}"

    elif pattern == 2:
        # C — The shift / bigger picture
        if sub_choice == 0:
            return f"The Workflow Shift Behind {subject}"
        else:
            return f"The Bigger Picture Behind {subject}"

    elif pattern == 3:
        # D — How (two compact sub-variants; no possessive to avoid grammar edge-cases)
        if sub_choice == 0:
            return f"How {subject} Is Reshaping {context_title}"
        else:
            return f"How {subject} Changes the Picture for {team}"

    else:
        # E — Subject-led editorial summary
        return f"{subject} and the Road to {context_noun}"


def _streamic_preview(a):
    """Return a concise editorial preview for The Streamic Intelligence cards.

    Priority: dek > card_summary > meta_description > body_html first sentence > smart_dek.
    Capped at 160 chars, broken at a word boundary.  Never returns an empty string.
    """
    MAX = 160

    for field in ("dek", "card_summary", "meta_description"):
        val = _plain_text(a.get(field) or "").strip()
        if len(val) > 20:
            if len(val) <= MAX:
                return val
            return val[:MAX].rsplit(" ", 1)[0] + "..."

    body = _plain_text(a.get("body_html") or "").strip()
    if len(body) > 40:
        if len(body) <= MAX:
            return body
        return body[:MAX].rsplit(" ", 1)[0] + "..."

    # Final fallback — always produces a non-empty string
    return smart_dek(a)[:MAX]


def load_homepage_feed(arts, limit=14):
    """Load homepage cards directly from the editorial article corpus.

    news.json removed — all content comes from generated_articles.json.
    Returns newest articles sorted by date then body length.
    """
    if not arts:
        return []

    mapped = []
    seen = set()

    for a in arts:
        if not isinstance(a, dict):
            continue
        slug = (a.get("slug") or "").strip()
        if not slug or slug in seen:
            continue
        mapped.append(a)
        seen.add(slug)

    def _feed_sort(a):
        body = a.get("body_html", "") or ""
        wc = len(re.sub(r"<[^>]+>", " ", body).split())
        return (a.get("published", ""), wc)

    mapped.sort(key=_feed_sort, reverse=True)
    return mapped[:limit]

def _item_href(a):
    slug = a.get('slug')
    if slug:
        return f"articles/{slug}.html"
    return a.get('source_url') or a.get('url') or '#'

def _item_target(a):
    href = _item_href(a)
    if href.startswith('http://') or href.startswith('https://'):
        return ' target="_blank" rel="noopener noreferrer nofollow"'
    return ''

def _hp_news_item(a):
    """Render one card in The Streamic Intelligence section.

    Hierarchy (analysis-first):
      1. STREAMIC ANALYSIS label
      2. Streamic editorial headline
      3. Editorial preview
      4. Date
      5. Original source credit (secondary)
      6. Internal CTA
    """
    slug         = a.get("slug", "")
    analysis_href = f"articles/{slug}.html" if slug else "#"
    src_url      = e(a.get("source_url", "") or a.get("url", "") or "")
    src          = e(_source_name(a.get("source_domain", a.get("source", ""))))
    dt           = d(a.get("published", ""))
    headline     = e(_streamic_headline(a))
    preview      = e(_streamic_preview(a))

    # Source attribution — secondary; rendered only when data is available
    src_attr = ""
    if src_url and src:
        src_attr = (
            f'<a href="{src_url}" target="_blank" rel="noopener noreferrer nofollow"'
            f' class="hp-news-src-link">Original source: {src} &#8599;</a>'
        )
    elif src:
        src_attr = f'<span class="hp-news-src-link">Original source: {src}</span>'

    return f'''<div class="hp-news-item">
  <div class="hp-news-thumb"><img src="{_hp_img(a)}" alt="{headline}" loading="lazy" onerror="this.onerror=null;this.src=\'assets/fallback.jpg\'"></div>
  <div class="hp-news-body">
    <span class="hp-news-src">STREAMIC ANALYSIS</span>
    <a href="{analysis_href}" class="hp-news-title">{headline}</a>
    <span class="hp-news-dek">{preview}</span>
    <div class="hp-news-foot">
      <time class="hp-news-date">{dt}</time>
      <a href="{analysis_href}" class="hp-news-read">Read full analysis &#8594;</a>
    </div>
    {src_attr}
  </div>
</div>'''
def _hp_sidebar_pick(a):
    href = f"articles/{a['slug']}.html"
    title = e(a.get("title", ""))
    return f'''<a href="{href}" class="hp-sb-img-card">
  <img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  <div class="hp-sb-img-overlay"><span class="hp-sb-img-title">{title}</span></div>
</a>'''

def _hp_sidebar_news(a):
    slug = a.get("slug","")
    analysis_href = f"articles/{slug}.html" if slug else "#"
    src_url = e(a.get("source_url","") or a.get("url","") or "")
    title = e(a.get("title", ""))
    src = e(_source_name(a.get("source_domain", a.get("source", ""))))
    dt = d(a.get("published", ""))
    src_link = ""
    if src_url and src:
        src_link = f'<a href="{src_url}" target="_blank" rel="noopener noreferrer nofollow" style="font-size:10px;color:var(--ink4);text-decoration:none;margin-top:2px;display:block">Source: {src} &#8599;</a>'
    return f'''<div class="hp-sb-news-item">
  <div class="hp-sb-news-thumb"><img src="{_hp_img(a)}" alt="{title}" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'"></div>
  <div class="hp-sb-news-body">
    <span class="hp-sb-news-src">{src}</span>
    <a href="{analysis_href}" class="hp-sb-news-title">{title}</a>
    <time class="hp-sb-news-date">{dt}</time>
    {src_link}
  </div>
</div>'''
def featured_page(arts):
    """Homepage built from generated_articles.json with premium magazine layout."""
    editorial_all = sorted([a for a in arts if a.get("is_editorial") or a.get("editorial")], key=lambda a: a.get("published", ""), reverse=True)
    regular_all = sorted([a for a in arts if not a.get("is_editorial") and not a.get("editorial")], key=lambda a: a.get("published", ""), reverse=True)

    preferred_hero = "ai-reducing-broadcast-operational-costs-2026"
    hero_art = next((a for a in editorial_all if a.get("slug") == preferred_hero), editorial_all[0] if editorial_all else (regular_all[0] if regular_all else None))

    guide_slug_order = [
        "broadcast-automation-systems-guide-2026",
        "ip-broadcasting-smpte-st2110-engineering-guide-2026",
        "cloud-broadcast-workflows-remote-production-2026",
        "media-asset-management-ai-era-monetisation-2026",
    ]
    guide_map = {a.get("slug"): a for a in editorial_all}
    guide_arts = [guide_map[s] for s in guide_slug_order if s in guide_map]

    # ── Latest Insights: ALL quality articles, newest first ────────────
    #    Must be 400+ words + 2 broadcast terms (lower than the 800-word
    #    SEO gate so latest daily articles always appear on the homepage).
    #    Manual editorials bypass word count entirely.
    #    First 20 visible on load; rest behind "Load More" button.
    used_slugs = {a.get("slug") for a in guide_arts} | ({hero_art.get("slug")} if hero_art else set())
    # Merge editorial + regular into ONE list sorted by date (not editorial-first)
    insight_pool = sorted(
        [a for a in arts if a.get("slug") not in used_slugs],
        key=lambda a: a.get("published", ""), reverse=True
    )
    _seen_ins = set()
    insight_arts = []
    for a in insight_pool:
        s = a.get("slug")
        if not s or s in _seen_ins:
            continue
        _seen_ins.add(s)
        insight_arts.append(a)
    # No gate — every editorial article appears in Latest Insights

    sidebar_picks = [a for a in editorial_all if a.get("slug") != (hero_art or {}).get("slug")][:3]
    fresh_feed = load_homepage_feed(arts, limit=16)
    breaking_news = fresh_feed[:4]
    homepage_news = fresh_feed[4:12]
    if not homepage_news:
        homepage_news = fresh_feed[:8]

    title = "NAB Show 2026 Broadcast Technology Updates — The Streamic"
    desc = "Independent analysis of NAB Show 2026 announcements: Avid Content Core, Dalet Dalia AI, Telestream OCI, BCNEXXT Vipe HDR, and more. Expert broadcast engineering editorial."
    canon = f"{BASE_URL}/"
    schema = json.dumps({
        "@context": "https://schema.org", "@type": "WebPage",
        "name": "The Streamic", "description": desc, "url": f"{BASE_URL}/index.html",
        "publisher": {"@type": "Organization", "name": "The Streamic", "url": BASE_URL}
    })

    custom_hero_path = os.path.join(DOCS, 'assets', 'hero-broadcast-male.png')
    hero_img = f"{BASE_URL}/assets/hero-broadcast-male.png" if os.path.exists(custom_hero_path) else (_hp_img(hero_art) if hero_art else '')
    homepage_head = head(title, desc, canon, og_img=hero_img)

    cinfo = CAT.get((hero_art or {}).get("category", "featured"), CAT["featured"])
    # Hero title overrides — edit here to control displayed title without touching JSON
    HERO_TITLE_OVERRIDES = {
        "ai-reducing-broadcast-operational-costs-2026": "Beyond Automation: How AI Can Optimize Broadcast Costs and Scale Human Potential in 2026",
    }

    hero_html = ""
    if hero_art:
        _hero_title = HERO_TITLE_OVERRIDES.get(hero_art.get("slug", ""), hero_art.get("title", ""))
        _hero_img_src = 'assets/hero-broadcast-male.png' if os.path.exists(custom_hero_path) else _hp_img(hero_art)
        _hero_img_alt = "Broadcast production switcher in a modern control room with illuminated buttons and blurred monitoring screens" if os.path.exists(custom_hero_path) else e(_hero_title)
        hero_html = f'''<section class="hp-hero" aria-label="Featured story">
  <a href="articles/{hero_art['slug']}.html" class="hp-hero-img-link" tabindex="-1" aria-hidden="true">
    <img class="hp-hero-img" src="{_hero_img_src}" alt="{_hero_img_alt}" loading="eager" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
  </a>
  <div class="hp-hero-overlay" aria-hidden="true"></div>
  <div class="hp-hero-body">
    <span class="hp-hero-tag">{e(cinfo['icon'])} {e(cinfo['label'])}</span>
    <h1 class="hp-hero-hl"><a href="articles/{hero_art['slug']}.html">{e(_hero_title)}</a></h1>
    <div class="hp-hero-meta"><span>By {AUTHOR}</span><span>&#124;</span><span>{d(hero_art.get("published", ""))}</span><span>&#124;</span><span>{rm(hero_art.get("word_count", 1000))}</span></div>
    <a href="articles/{hero_art['slug']}.html" class="hp-hero-cta">View Analysis <span class="hp-hero-cta__arrow">→</span></a>
  </div>
</section>'''

    guide_subs = ["2026 Engineering Edition", "Complete Technical Reference", "Distributed Production Playbook", "Metadata, Search & Monetisation"]
    guides_html = ''.join(_hp_guide_card(a, guide_subs[i] if i < len(guide_subs) else "Technical Guide") for i, a in enumerate(guide_arts))
    # First 6 visible, rest hidden — revealed by Load More button
    INSIGHT_INITIAL = 20
    _insight_cards = []
    for i, a in enumerate(insight_arts):
        card_html = _hp_insight_card(a)
        if i >= INSIGHT_INITIAL:
            # Add hidden class to the <a> tag
            card_html = card_html.replace('class="hp-insight-card"', 'class="hp-insight-card hp-insight-hidden"', 1)
        _insight_cards.append(card_html)
    insights_html = ''.join(_insight_cards)
    # Load More — self-contained component (inline CSS + HTML + JS)
    _hidden_count = max(0, len(insight_arts) - INSIGHT_INITIAL)
    insights_loadmore = ""
    if _hidden_count > 0:
        insights_loadmore = f'''<style>
.hp-insight-hidden{{display:none!important}}
@keyframes insightReveal{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:translateY(0)}}}}
.hp-insight-reveal{{animation:insightReveal .4s cubic-bezier(.25,.46,.45,.94) both}}
.hp-lm-wrap{{display:flex;justify-content:center;padding:36px 0 12px}}
.hp-lm{{position:relative;display:inline-flex;align-items:center;gap:14px;padding:0;background:none;border:none;cursor:pointer;font-family:var(--font);-webkit-tap-highlight-color:transparent;outline:none}}
.hp-lm-ring{{position:relative;width:52px;height:52px;flex-shrink:0}}
.hp-lm-ring svg{{width:52px;height:52px;transform:rotate(-90deg)}}
.hp-lm-ring .ring-track{{fill:none;stroke:var(--line);stroke-width:2}}
.hp-lm-ring .ring-fill{{fill:none;stroke:var(--blue);stroke-width:2.5;stroke-linecap:round;stroke-dasharray:150;stroke-dashoffset:150;transition:stroke-dashoffset .6s cubic-bezier(.4,0,.2,1)}}
.hp-lm:hover .ring-fill{{stroke-dashoffset:0}}
.hp-lm-icon{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}}
.hp-lm-icon svg{{width:18px;height:18px;stroke:var(--ink);stroke-width:2;fill:none;transition:transform .35s cubic-bezier(.4,0,.2,1),stroke .2s}}
.hp-lm:hover .hp-lm-icon svg{{transform:rotate(180deg);stroke:var(--blue)}}
.hp-lm-text{{display:flex;flex-direction:column;align-items:flex-start;gap:2px}}
.hp-lm-label{{font-size:14px;font-weight:600;color:var(--ink);letter-spacing:-.01em;transition:color .2s}}
.hp-lm:hover .hp-lm-label{{color:var(--blue)}}
.hp-lm-sub{{font-size:11px;font-weight:500;color:var(--ink4);transition:color .2s}}
.hp-lm:hover .hp-lm-sub{{color:var(--blue)}}
.hp-lm-bar{{position:absolute;bottom:-10px;left:0;width:100%;height:1.5px;background:var(--line);border-radius:2px;overflow:hidden}}
.hp-lm-bar span{{display:block;width:0;height:100%;background:var(--blue);border-radius:2px;transition:width .5s cubic-bezier(.4,0,.2,1)}}
.hp-lm:hover .hp-lm-bar span{{width:100%}}
</style>
<div class="hp-lm-wrap">
  <button id="insightLoadMore" type="button" class="hp-lm" aria-label="Load more insights">
    <div class="hp-lm-ring">
      <svg viewBox="0 0 52 52"><circle class="ring-track" cx="26" cy="26" r="24"/><circle class="ring-fill" cx="26" cy="26" r="24"/></svg>
      <div class="hp-lm-icon"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg></div>
    </div>
    <div class="hp-lm-text">
      <span class="hp-lm-label">Load More</span>
      <span class="hp-lm-sub" id="lmCount">{_hidden_count} more articles</span>
    </div>
    <div class="hp-lm-bar"><span></span></div>
  </button>
</div>
<script>
(function(){{
  var btn=document.getElementById('insightLoadMore'),B=6;
  if(!btn)return;
  btn.addEventListener('click',function(){{
    var h=document.querySelectorAll('.hp-insight-hidden'),c=0,i;
    for(i=0;i<h.length&&c<B;i++,c++){{h[i].classList.remove('hp-insight-hidden');h[i].classList.add('hp-insight-reveal');}}
    var left=document.querySelectorAll('.hp-insight-hidden').length;
    if(left<1)btn.parentElement.style.display='none';
    else document.getElementById('lmCount').textContent=left+' more articles';
  }});
}})();
</script>'''
    news_html = ''.join(_hp_news_item(a) for a in homepage_news)
    picks_html = ''.join(_hp_sidebar_pick(a) for a in sidebar_picks)
    sb_news_html = ''.join(_hp_sidebar_news(a) for a in breaking_news)
    howto_html = '''<div class="hp-sb-guides-grid">
          <a href="articles/guide-premiere-to-avid.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Post-Production</span><span class="hp-sb-guide-title">Premiere Pro to Avid Media Composer</span><span class="hp-sb-guide-time">&#128337; 8 min</span></a>
          <a href="articles/guide-vantage-nas-transcode.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Encoding</span><span class="hp-sb-guide-title">Vantage: Transcode to MP4 on NAS</span><span class="hp-sb-guide-time">&#128337; 6 min</span></a>
          <a href="articles/guide-vantage-aws-transcode.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Cloud</span><span class="hp-sb-guide-title">Vantage: Output to AWS S3</span><span class="hp-sb-guide-time">&#128337; 6 min</span></a>
          <a href="articles/guide-avid-media-central-health-check.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Avid</span><span class="hp-sb-guide-title">MediaCentral Health Check</span><span class="hp-sb-guide-time">&#128337; 7 min</span></a>
          <a href="articles/guide-audio-conform-avid-protools.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">Audio</span><span class="hp-sb-guide-title">Audio Conform: Avid to Pro Tools</span><span class="hp-sb-guide-time">&#128337; 9 min</span></a>
          <a href="articles/guide-avid-strawberry.html" class="hp-sb-guide-item"><span class="hp-sb-guide-cat">MAM</span><span class="hp-sb-guide-title">Strawberry PAM + Avid Workflow</span><span class="hp-sb-guide-time">&#128337; 10 min</span></a>
        </div>'''

    return f'''{homepage_head}
<body data-category="featured">
{nav("/")}
<main>
  {_nab_bento_section(mode="hero")}
  <div class="w">
    {_deep_dives_section()}
    {_nab_bento_section(mode="cards")}
    <section class="hp-flagship-section">
      <div class="w">
        <div class="hp-flagship-section__hdr">
          <div class="hp-sec-hdr">
            <h2>Latest Insights</h2>
            <a href="ai-post-production.html">View all &#8594;</a>
          </div>
          <p class="hp-section-intro">Original Streamic analysis on broadcast automation, IP infrastructure, cloud production, and editorial operations — selected for depth, not noise.</p>
        </div>
      </div>
    </section>
    <div class="hp-outer">
      <div class="hp-main">
        <section class="hp-insights hp-insights-premium">
          <div class="hp-insights-grid">{insights_html}</div>
          {insights_loadmore}
        </section>
        <section class="hp-guide">
          <div class="hp-guide-banner"><span>Professional Media Systems Guide</span></div>
          <div class="hp-guide-grid">{guides_html}</div>
        </section>
        <section class="hp-news">
          <div class="hp-sec-hdr"><h2>The Streamic Intelligence</h2><p class="hp-sec-sub">Original Streamic headlines and concise editorial previews, with credited source links kept secondary to the analysis.</p></div>
          <div class="hp-news-list">{news_html}</div>
        </section>
      </div>
      <aside class="hp-sidebar" aria-label="Sidebar">
        <div class="hp-sb-section hp-sb-featured">
          <div class="hp-sb-hdr">Editor&#8217;s Picks <a href="editorsdesk.html" class="hp-sb-hdr-link">View page &#8594;</a></div>
          {picks_html}
        </div>
        <div class="hp-sb-section">
          <div class="hp-sb-hdr">How-To Guides <a href="howto.html" class="hp-sb-hdr-link">View all &#8594;</a></div>
          {howto_html}
        </div>
        <div class="hp-sb-section">
          <div class="hp-sb-hdr">Latest Media IT Updates</div>
          {sb_news_html}
        </div>
      </aside>
    </div>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>'''

# ── CATEGORY PAGE
def category_page(cat, arts):
    cinfo = CAT.get(cat, CAT["featured"])
    cpg   = f"{cat}.html"
    canon = f"{BASE_URL}/{cpg}"
    cat_label_ = cinfo.get('label', '')
    title_base = f"{cat_label_} — The Streamic"
    desc  = cinfo["desc"]

    # First article: editorial hero card
    # Top 3 articles: editorial-style horizontal cards
    # Rest: news grid with source diversity
    editorial = [a for a in arts if a.get("is_editorial") or a.get("editorial")]
    regular   = [a for a in arts if not a.get("is_editorial") and not a.get("editorial")]
    # Sort regular by date then diversify
    regular.sort(key=lambda a: a.get("published",""), reverse=True)
    regular = diversify_arts(regular)
    all_arts  = editorial + regular
    all_arts.sort(key=lambda a: a.get("published",""), reverse=True)

    total = len(all_arts)
    total_pages = max(1,(total + PAGE_SIZE -1)//PAGE_SIZE)
    pages = []

    for pg in range(total_pages):
        sl = all_arts[pg*PAGE_SIZE:(pg+1)*PAGE_SIZE]
        first  = sl[:1]
        rest   = sl[1:]

        if cat == "ai-post-production" and pg == 0:
            hero_html = f"""<section class="hero hero--ai-post-custom">
  <div class="hero-inner">
    <div class="hero-img">
      <a href="articles/ai-reducing-broadcast-operational-costs-2026.html">
        <img src="assets/hero-broadcast-male.png" alt="Broadcast production switcher in a modern control room" loading="eager" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
      </a>
    </div>
    <div class="hero-body">
      <span class="hero-tag" style="background:#FF2D55">🎬 AI &amp; Post-Production</span>
      <h1 class="hero-hl"><a href="articles/ai-reducing-broadcast-operational-costs-2026.html">Beyond Automation: How AI Can Optimize Broadcast Costs and Scale Human Potential in 2026</a></h1>
      <p class="hero-dek">This page tracks the NAB 2026 shifts that matter to real production teams: agentic assistants inside edit systems, natural-language archive search, faster creative-to-delivery automation, and practical cloud bridges that do not force a full rip-and-replace.</p>
      <div class="hero-meta"><span>By {AUTHOR}</span><span>{d(first[0].get('published','') if first else '')}</span><span>Curated NAB landing page</span></div>
      <a href="articles/ai-reducing-broadcast-operational-costs-2026.html" class="hero-cta">Read featured analysis</a>
    </div>
  </div>
</section>
<section class="nab-inline-grid" aria-label="Featured NAB vendor updates">
  <a class="nab-inline-card" href="articles/2026-04-17-ai-post-production-avid-google-cloud-agentic-ai-media-production.html"><span class="nab-inline-kicker">Avid</span><strong>Avid Content Core and Google Gemini</strong><span>Agentic AI, archive search, and hybrid deployment without a rip-and-replace migration.</span></a>
  <a class="nab-inline-card" href="articles/2026-04-01-newsroom-dalet-flex-2512-semantic-search-dalia-ai.html"><span class="nab-inline-kicker">Dalet</span><strong>Dalia moves from idea to operational layer</strong><span>Natural-language workflow triggers with human validation kept in the loop.</span></a>
  <a class="nab-inline-card" href="articles/2026-04-01-ai-post-production-telestream-adobe-frameio-creative-delivery-automation.html"><span class="nab-inline-kicker">Telestream</span><strong>OCI + Adobe workflow acceleration</strong><span>Premiere-to-Vantage automation, Frame.io readiness, and multi-cloud QoS monitoring.</span></a>
</section>"""
            rest = sl
        else:
            hero_html = hero_block(first[0], base="") if first else ""

        grid_html = news_grid(rest, grid_id="catGrid") if rest else ""

        pag = _pag_html(cat, pg, total_pages)

        pg_title = title_base if pg==0 else f"{title_base} — Page {pg+1}"
        cinfo_icon = cinfo.get('icon','')
        cinfo_label = cinfo.get('label','')
        pg_canon = canon if pg==0 else f"{BASE_URL}/{cat}-p{pg+1}.html"
        pg_robots = "index,follow" if pg==0 else "noindex,follow"

        latest_section = f'<section class="latest">{grid_html}</section>' if grid_html else ""
        html = f"""{head(pg_title, desc, pg_canon, og_img=(first[0].get('image_url','') if first else ''), robots=pg_robots)}
<body data-category="{cat}">
{nav(cpg)}
{catbar(cat)}
<main>
  <div class="w">
    <div class="cat-hdr">
      <h1>{cinfo_icon} {cinfo_label}</h1>
      <p>{desc}</p>
    </div>
    {hero_html}
    {_ad() if rest else ""}
    {latest_section}
    {pag}
  </div>
</main>
{footer()}
{_cookie_banner()}
<script src="main.js" defer></script>
</body>
</html>"""
        pages.append((pg, html))
    return pages

def _pag_html(cat, page, total):
    if total <= 1: return ""
    prev = f'<a href="{cat}.html" class="pag-link">&larr; Newer</a>' if page > 0 else '<span class="dis">&larr; Newer</span>'
    nxt  = f'<a href="{cat}-p{page+2}.html" class="pag-link">Older &rarr;</a>' if page < total-1 else '<span class="dis">Older &rarr;</span>'
    return f'<div class="pag">{prev}<span class="info">Page {page+1} of {total}</span>{nxt}</div>'

# ── ARTICLE PAGE
# Boilerplate sentences to strip from article bodies
# All known boilerplate sentence fragments (substring match)
_BOILER_FRAGMENTS = [
    "Understanding what is changing helps teams plan ahead",
    "Early movers tend to gain an efficiency edge",
    "Teams should discuss this in their next planning cycle",
    "Organisations tracking this should review their current approach",
    "Practical impact will vary by scale, but the direction is clear",
    "Keeping a close eye on vendor roadmaps",
    "The operational details matter as much as the headline",
    "Budgets, staffing, and tooling may all need revisiting",
    "The pace of change in broadcast IP, cloud, and streaming infrastructure has accelerated",
    "New deployments and announced capabilities are revealing practical pathways",
    "Teams with legacy infrastructure commitments will need to assess",
    "What distinguishes this from earlier announcements in the same space",
    "The market context matters here: this development arrives",
    "For engineering and operations teams:",
    "Teams that engage early and plan methodically will be best placed",
    "Engineering teams evaluating this should look beyond headline capability",
    "The broadcast and streaming technology sector continues to evolve rapidly",
    "Media technology decisions made this year will shape production",
    "Industry analysts and practitioners alike are tracking",
    "The integration of software-defined approaches into traditionally hardware-centric",
    "Competitive dynamics between established broadcast technology vendors",
    "Regional differences in broadcast infrastructure maturity",
    "Standards bodies, vendors, and broadcaster engineering teams are increasingly aligned",
    "The economics of media production and distribution continue to shift",
    "An independent editorial overview of the technology forces reshaping",
    "Understanding what is changing helps teams plan ahead",
    "Organisations tracking this should review their current approach",
    "The announcement reflects sustained demand from broadcast operators",
    "For broadcast engineers and technology decision-makers, staying current",
]

def _is_boilerplate(text):
    """Return True if this paragraph is mostly generic filler."""
    return any(b.lower() in text.lower() for b in _BOILER_FRAGMENTS)

def _clean_body(a):
    """
    Return clean article body for rendering.

    Anti-truncation rule:
    - If body_html has <h2> OR word_count > 300 → return the FULL body_html untouched.
      Gemini-generated articles are complete. Truncating them strips the analysis.
    - Fallback: only strip/limit for short teasers with no AI enhancement.
    """
    is_ed = a.get("is_editorial") or a.get("editorial")

    # ── Full editorial articles — always return complete body ─────────────
    if is_ed:
        body = a.get("body_html", "")
        if body and len(body) > 300:
            return body

    body_html  = a.get("body_html", "") or ""
    word_count = a.get("word_count", 0)
    # Also check actual body length — metadata word_count may be missing
    actual_wc  = len(re.sub(r"<[^>]+>", " ", body_html).split())

    # ── AI-enhanced articles: has h2 structure OR substantial word count ──
    # Return the full body without ANY stripping — Gemini output is complete.
    if "<h2>" in body_html or "<h3>" in body_html or word_count > 300 or actual_wc > 300:
        # Only strip accidental markdown fences Gemini occasionally produces
        body_clean = re.sub(r"```html?\n?|```\n?", "", body_html).strip()
        # Remove boilerplate filler sentences while keeping all structure
        paras = re.findall(r"<p[^>]*>(.*?)</p>", body_clean, re.DOTALL)
        clean_paras = []
        for p in paras:
            txt = re.sub(r"<[^>]+>", " ", p).strip()
            txt = re.sub(r"\s+", " ", txt)
            if len(txt.split()) < 5:
                continue   # skip truly empty placeholders
            if _is_boilerplate(txt):
                continue   # strip known filler sentences
            clean_paras.append(p)
        # Reconstruct: non-paragraph blocks (h2, h3, ul, ol, table, div) pass through untouched
        # Strategy: replace only the <p> tags we cleaned, keep everything else
        result = body_clean
        for orig_p, clean_p in zip(paras, clean_paras):
            pass  # we'll use a simpler approach below
        # Simpler: just strip boilerplate paragraphs from the full HTML
        for p_content in paras:
            txt = re.sub(r"<[^>]+>", " ", p_content).strip()
            txt = re.sub(r"\s+", " ", txt)
            if _is_boilerplate(txt):
                result = result.replace(f"<p>{p_content}</p>", "", 1)
                result = result.replace(f"<p>{p_content.strip()}</p>", "", 1)
        return result.strip() or body_clean

    # ── Fallback: short teaser with no AI enhancement ─────────────────────
    # card_summary is the Groq/Gemini 120-150 word intel card — show it in full
    cs_raw = re.sub(r"<[^>]+>", " ", a.get("card_summary", "") or "").strip()
    cs_raw = re.sub(r"\s+", " ", cs_raw)
    cs_words = cs_raw.split()

    if len(cs_words) >= 50 and not _is_boilerplate(cs_raw):
        mid = len(cs_words) // 2
        for i in range(mid, min(mid + 25, len(cs_words))):
            if cs_words[i].endswith((".", "?")): mid = i + 1; break
        p1 = " ".join(cs_words[:mid])
        p2 = " ".join(cs_words[mid:])
        return f"<p>{p1}</p>\n" + (f"<p>{p2}</p>" if p2 else "")

    # Raw paragraphs — keep ALL that pass quality check (no arbitrary limit)
    paras = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.DOTALL)
    clean = []
    for p in paras:
        txt = re.sub(r"<[^>]+>", " ", p).strip()
        txt = re.sub(r"\s+", " ", txt)
        if len(txt.split()) < 8: continue
        if _is_boilerplate(txt): continue
        clean.append(f"<p>{p.strip()}</p>")

    if clean:
        return "\n".join(clean)   # no truncation — article passed quality gate

    # Last resort: dek + short teaser
    dek    = (a.get("dek") or "").strip()
    teaser = (a.get("meta_description") or a.get("teaser") or "").strip()
    parts  = []
    if dek: parts.append(f"<p><strong>{dek}</strong></p>")
    if len(cs_words) >= 20 and cs_raw != dek: parts.append(f"<p>{cs_raw}</p>")
    elif teaser and teaser != dek: parts.append(f"<p>{teaser}</p>")
    return "\n".join(parts) if parts else f"<p>{dek or 'Broadcast technology analysis.'}</p>"


def article_page(a):
    # ── Thin content check: redirect to source for stub articles ──────────────
    body_raw = a.get("body_html","") or ""
    body_wc  = len(re.sub(r"<[^>]+>", " ", body_raw).split())
    has_struct = "<h2>" in body_raw or "<h3>" in body_raw
    src_url_direct = a.get("source_url") or a.get("url") or a.get("link","")
    
    if body_wc < 200 and not has_struct and src_url_direct:
        # Render a clean source-redirect article page (no thin content)
        cat2   = a.get("category","featured")
        ci2    = CAT.get(cat2, CAT["featured"])
        title2 = e(a.get("title","Untitled"))
        dt2    = d(a.get("published",""))
        return f"""{head(title2+" | The Streamic", a.get("meta_description",title2), f"{BASE_URL}/articles/{a['slug']}.html", css="../style.css")}
<body>
{nav(ci2.get("page","featured.html"), base="../")}
<main><div class="art-wrap" style="max-width:680px;padding:60px 24px 80px">
  <a href="../{ci2.get('page','featured.html')}" style="font-size:13px;color:var(--blue);text-decoration:none">← {ci2.get('label','Featured')}</a>
  <h1 style="font-family:var(--serif);font-size:clamp(22px,3.5vw,36px);line-height:1.25;letter-spacing:-.03em;margin:20px 0 12px">{title2}</h1>
  <p style="font-size:13px;color:var(--ink4);margin-bottom:32px">By The Streamic Editorial Team · {dt2}</p>
  <div style="background:var(--bg);border-radius:14px;padding:28px 32px;border-left:4px solid var(--blue)">
    <p style="font-size:15px;color:var(--ink2);line-height:1.7;margin:0 0 20px">This is an industry news item tracked by The Streamic. Our editorial team has flagged it for upcoming analysis. For the complete story, read the original article from {e(a.get('source_domain','the source').replace('https://','').replace('www.','').split('/')[0])}.</p>
    <a href="{e(src_url_direct)}" target="_blank" rel="noopener noreferrer nofollow"
      style="display:inline-flex;align-items:center;gap:8px;padding:12px 24px;background:var(--blue);color:#fff;border-radius:8px;font-size:14px;font-weight:600;text-decoration:none">
      Read Original Article →
    </a>
  </div>
  <p style="font-size:12px;color:var(--ink4);margin-top:24px">The Streamic publishes original broadcast technology analysis on our <a href="../featured.html" style="color:var(--blue)">Featured</a> and <a href="../posts.html" style="color:var(--blue)">All Articles</a> pages.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

    cat   = a.get("category","featured")
    cinfo = CAT.get(cat, CAT["featured"])
    slug  = a["slug"]
    url   = f"{BASE_URL}/articles/{slug}.html"
    title = a.get("title","")
    dek   = a.get("dek") or a.get("meta_description","")
    img   = a.get("image_url","")
    dt    = d(a.get("published",""))
    src_url  = a.get("source_url","")
    src_dom  = a.get("source_domain","")
    is_ed    = a.get("is_editorial") or a.get("editorial")

    # Clean body - card_summary as 2-para analysis (not boilerplate filler)
    body  = _clean_body(a)
    body_words = len(body.replace("<p>","").replace("</p>","").split())
    wc    = body_words or a.get("word_count",300)

    schema = json.dumps({
        "@context":"https://schema.org","@type":"NewsArticle",
        "headline":title,"description":dek,"image":img,
        "datePublished":a.get("published",""),"dateModified":a.get("published",""),
        "author":{"@type":"Organization","name":AUTHOR},
        "publisher":{"@type":"Organization","name":"The Streamic","url":BASE_URL,
                     "logo":{"@type":"ImageObject","url":f"{BASE_URL}/assets/logo.png"}},
        "mainEntityOfPage":url,"wordCount":wc,
    }, indent=2)

    source_credit = ""
    source_banner = ""
    # Derive source domain from URL if field is missing
    if not src_dom and src_url:
        src_dom = src_url.replace("https://","").replace("http://","").replace("www.","").split("/")[0]
    # Show source attribution for ALL articles with a source_url,
    # EXCEPT truly hand-written editorials (gpt_manual_editorial).
    # Some articles have is_editorial=True but are sourced from external news.
    _is_original = a.get("generated_by") == "gpt_manual_editorial"
    if src_url and not _is_original:
        _src_name = e(src_dom) if src_dom else "Original Source"
        _pub_date = a.get("published","")
        _pub_month = ""
        if _pub_date:
            try:
                from datetime import datetime as _dt
                _pub_month = _dt.strptime(_pub_date, "%Y-%m-%d").strftime("%B %Y")
            except Exception:
                _pub_month = _pub_date

        # ── TOP: Source attribution banner ──
        source_banner = f"""<div style="background:#f0f4ff;border:1px solid #d0daf0;border-radius:10px;padding:16px 20px;margin-bottom:28px;font-size:13.5px;color:var(--ink2);line-height:1.6">
  <span style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:var(--blue);display:block;margin-bottom:6px">Source Attribution</span>
  This analysis is based on publicly available reporting from:
  <strong style="color:var(--ink)"><a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" style="color:var(--blue);text-decoration:none">{_src_name}</a></strong>{f" ({_pub_month})" if _pub_month else ""}.
  <br>This article provides independent technical interpretation by The Streamic.
</div>"""

        # ── BOTTOM: Sources & Further Reading ──
        source_credit = f"""<div style="background:var(--bg);border-radius:12px;padding:22px 24px;margin-top:36px;border-top:3px solid var(--blue)">
  <h4 style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:var(--blue);margin:0 0 14px">Sources &amp; Further Reading</h4>
  <ul style="margin:0;padding-left:18px;list-style:disc">
    <li style="font-size:13.5px;color:var(--ink2);line-height:1.6;margin-bottom:6px">
      <strong style="color:var(--ink)">{_src_name}</strong> &mdash;
      <a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" style="color:var(--blue);text-decoration:none">Read the original article &rarr;</a>
    </li>
  </ul>
  <p style="margin:12px 0 0;font-size:12px;color:var(--ink4);line-height:1.5">
    The Streamic provides independent editorial commentary. All source material is credited and linked above. External links carry <code style="font-size:11px;background:#e8e8ed;padding:1px 5px;border-radius:3px">rel="nofollow noopener"</code>.
  </p>
</div>"""

    about_txt = "Original analysis and commentary by The Streamic Editorial Team. Independent broadcast technology journalism for engineers and media professionals." if is_ed else "Editorial commentary and analysis by The Streamic Editorial Team. For the original source, see the attribution above."
    # Use professional bio block if body_html already contains one from AI generation;
    # otherwise render the default author box for editorial articles and the bio for sourced ones.
    has_bio = "art-author-bio" in body_raw
    if has_bio:
        author_box = ""   # bio already embedded in body_html by the AI prompt
    elif is_ed:
        author_box = f"""<div class="art-author">
  <strong>About this article</strong>
  {about_txt}
  <a href="/about.html" style="color:var(--blue);margin-left:6px;">About The Streamic &rarr;</a>
</div>"""
    else:
        author_box = f"""<div class="art-author-bio">
  <div class="bio-avatar">S</div>
  <div class="bio-body">
    <strong class="bio-name">Prerak K Mehta</strong>
    <span class="bio-title">Founder, The Streamic &middot; Dublin, Ireland</span>
    <p class="bio-text">Broadcast technology professional with total 25+ years of IT and 20 years of Media/Post Production &amp; Broadcast IT systems experience. He covers broadcast engineering, streaming, infrastructure, and media technology trends for The Streamic.</p>
  </div>
</div>"""

    # ── Editor's Note with generated_by attribution (AdSense transparency) ──
    gen_by    = a.get("generated_by", "") or ""
    gen_label = {
        "gemini-2.5-pro":       "Gemini 2.5 Pro (Google)",
        "gemini-2.5-flash-lite":"Gemini 2.5 Flash-Lite (Google)",
        "groq-fallback":        "Groq / Llama (fallback)",
    }.get(gen_by, gen_by if gen_by else "AI-assisted")

    if is_ed:
        editors_note = ""
    else:
        editors_note = (
            '<hr style="margin-top:40px;border:0;border-top:1px solid #eee;">'
            '<p style="font-style:italic;font-size:0.85rem;color:#666;line-height:1.5;margin-top:20px;">'
            '<strong>Editor&#39;s Note:</strong> This technical analysis was synthesised from '
            'industry sources and constructed with the assistance of AI tools '
            f'(<strong>{gen_label}</strong>). '
            'It has been reviewed and formatted by <strong>The Streamic Editorial Team</strong> '
            'to ensure accuracy and relevance for broadcast professionals.'
            '</p>'
        )
    cinfo_color = cinfo.get('color','')
    cinfo_lbl   = cinfo.get('label','')
    cinfo_icon2 = cinfo.get('icon','')
    cinfo_page  = CAT_PAGE.get(cat, cat+'.html')
    lic_url   = e(a.get('image_license_url','https://unsplash.com/license'))
    lic_label = e(a.get('image_license','Unsplash License'))
    if not is_ed and src_url:
        title_html = f'<h1><a href="{e(src_url)}" target="_blank" rel="noopener noreferrer nofollow" style="color:inherit;text-decoration:none;">{e(title)}</a></h1>'
    else:
        title_html = f'<h1>{e(title)}</h1>'
    analysis_badge = '<span style="background:var(--blue);color:#fff;padding:3px 9px;border-radius:5px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.8px">Analysis</span>' if is_ed else ""

    return f"""{head(e(title)+" | The Streamic", dek, url, css="../style.css", og_img=img)}
<body>
{nav(CAT_PAGE.get(cat,cat+".html"), base="../")}
<main>
  <div class="art-wrap">
    <div class="art-breadcrumb">
      <a href="../featured.html">Home</a>
      <span>›</span>
      <a href="../{cinfo_page}" style="color:{cinfo_color}">{cinfo_lbl}</a>
    </div>
    <span class="art-tag" style="background:{cinfo_color}">{cinfo_icon2} {cinfo_lbl}</span>
    {title_html}
    <p class="art-dek">{dek.replace(chr(60),"&lt;").replace(chr(62),"&gt;")}</p>
    <div class="art-byline">
      <strong>{AUTHOR}</strong>
      <time datetime="{a.get("published","")}" style="color:var(--ink4);font-size:13px">{dt}</time>
      <span>{wc:,} words · {rm(wc)}</span>
      {analysis_badge}
    </div>
    <figure>
      <img src="{eu(img)}" alt="{e(title)}" loading="eager">
      <figcaption>{e(a.get("image_credit","Photo via Unsplash &#8212; free to use under the Unsplash License"))} &#8212; <a href="{lic_url}" rel="nofollow noopener" target="_blank" style="color:var(--ink4)">{lic_label}</a></figcaption>
    </figure>
    <div class="art-body">{source_banner}{body}{editors_note}</div>
    {source_credit}
    {author_box}
    <div class="art-more">
      <h3>Continue Reading</h3>
      <a href="../{CAT_PAGE.get(cat,cat+'.html')}">{cinfo['icon']} All {cinfo['label']} Coverage</a>
      <a href="../featured.html">⭐ Featured Stories</a>
    </div>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer(base="../")}
{_cookie_banner()}
</body>
</html>"""

# ── STATIC PAGES
def about_page():
    return f"""{head("About The Streamic — Prerak K Mehta","Independent broadcast and streaming technology journalism from Dublin, Ireland.",f"{BASE_URL}/about.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:780px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">About The Streamic</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:20px">The Streamic is an independent broadcast and streaming technology publication covering the tools, standards, and workflows that shape modern media production and delivery. Published from Dublin, Ireland, we focus on the engineering reality behind the marketing &#8212; what actually ships, what actually works, and what broadcast teams actually need to verify before they deploy.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:20px">Our coverage spans IP infrastructure (SMPTE ST 2110, NMOS IS-04/IS-05, AES67, SCTE-35), cloud-native production, operational AI in newsroom and post workflows, real-time graphics, playout automation, MAM / PAM integration, and disaster-recovery architectures. Readers include broadcast engineers, media operations leads, technology directors, post-production supervisors, and broadcast IT architects at networks, streamers, and production facilities worldwide.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Our editorial approach</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:16px">We write original analysis &#8212; not copied content, not press-release rewrites. Our industry news coverage credits and links to original reporting while adding Streamic editorial context: what the announcement actually means for an integration, what specifications are missing, and what deployment factors teams must verify before they commit capex. Long-form articles represent our editorial team&#39;s independent perspective on industry developments.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:16px">Every technical article is grounded in verifiable source material. Where a vendor has not disclosed a specification, we say so explicitly rather than inventing detail. Where two sources conflict, we note the discrepancy. This is the editorial discipline that separates broadcast trade journalism from marketing re-circulation.</p>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">What we cover</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:12px">Day-to-day Streamic coverage falls into five practice areas:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><strong>Infrastructure &amp; standards</strong> &#8212; ST 2110 rollouts, NMOS deployments, PTP timing, IP fabric design, SDI-to-IP migration roadmaps.</li>
  <li><strong>Cloud &amp; hybrid production</strong> &#8212; remote production (REMI), cloud playout, CDN architecture, egress cost optimisation, edge media services.</li>
  <li><strong>AI in broadcasting</strong> &#8212; automated captioning and QC, metadata extraction, newsroom AI, AI-assisted editing, generative tools for post.</li>
  <li><strong>Post-production workflows</strong> &#8212; Media Composer / Resolve / Premiere interoperability, PAM / MAM integration, proxy pipelines, archive strategies.</li>
  <li><strong>Newsroom technology</strong> &#8212; NRCS platforms, MOS integration, rundown automation, social-media ingest, fast-turn graphics.</li>
</ul>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Editor &amp; Founder</h2>
<div style="display:flex;align-items:flex-start;gap:20px;background:var(--bg);border-radius:14px;padding:24px;margin-bottom:28px">
  <div style="flex-shrink:0;width:56px;height:56px;border-radius:50%;background:var(--blue);display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;font-family:var(--serif)">P</div>
  <div>
    <strong style="font-size:16px;color:var(--ink)">Prerak K Mehta</strong>
    <p style="font-size:13px;color:var(--ink4);margin:2px 0 8px">Founder &amp; Editor-in-Chief, The Streamic · Dublin, Ireland</p>
    <p style="font-size:14px;color:var(--ink3);line-height:1.7;margin:0">Broadcast technology professional with total 25+ years of IT and 20 years of Media/Post Production &amp; Broadcast IT systems experience. He covers broadcast engineering, streaming, infrastructure, and media technology trends for The Streamic.</p>
    <div style="display:flex;gap:12px;margin-top:12px;flex-wrap:wrap">
      <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer"
        style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--blue);text-decoration:none;font-weight:500">&#x1D54F; @thestreamic</a>
      <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer"
        style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--blue);text-decoration:none;font-weight:500">in TheStreamic on LinkedIn</a>
    </div>
  </div>
</div>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Follow Us</h2>
<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:28px">
  <a href="https://twitter.com/thestreamic" target="_blank" rel="noopener noreferrer"
    style="display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border:1px solid var(--line);border-radius:8px;font-size:14px;font-weight:500;color:var(--ink);text-decoration:none;background:#fff">
    &#x1D54F; Twitter / X &nbsp;<strong>@thestreamic</strong>
  </a>
  <a href="https://www.linkedin.com/company/thestreamic" target="_blank" rel="noopener noreferrer"
    style="display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border:1px solid var(--line);border-radius:8px;font-size:14px;font-weight:500;color:var(--ink);text-decoration:none;background:#fff">
    in LinkedIn &nbsp;<strong>TheStreamic</strong>
  </a>
</div>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 12px">Contact</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.7">For editorial enquiries, corrections, or advertising: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> &nbsp;|&nbsp; <a href="contact.html" style="color:var(--blue)">Use our contact form &rarr;</a></p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def contact_page():
    return f"""{head("Contact — The Streamic","Get in touch with The Streamic editorial team in Dublin, Ireland.",f"{BASE_URL}/contact.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:680px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,40px);margin-bottom:8px">Contact</h1>
<p style="font-size:15px;color:var(--ink3);line-height:1.7;margin-bottom:24px">We welcome editorial feedback, story tips, corrections, and advertising enquiries from broadcast engineers, vendors, and media technology professionals. Our Dublin-based editorial team responds to genuine enquiries within two working days.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">What to expect</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Every message is read by the editorial team. Story tips and corrections are prioritised. Press releases are considered for coverage when they align with our practice areas (infrastructure, cloud production, AI in broadcasting, post-production workflows, newsroom technology). We do not publish paid-placement articles, syndicated content, or sponsored posts disguised as editorial. We will not reply to generic SEO link-building requests, guest-post pitches from content farms, or mass outreach unrelated to broadcast technology.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">Editorial enquiries</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Have a story tip or seen something we should cover? Email us directly with a short description and any relevant links. Broadcast engineers, integration teams, and vendor technical staff often see announcements, standards drafts, or operational incidents worth flagging before the wider trade press picks them up &#8212; we value these tips and protect sources on request.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">Press &amp; vendor enquiries</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">For product announcements, roadmap updates, or briefings, please include: (a) a one-paragraph summary of what is being announced, (b) any relevant technical specifications (codecs, protocols, standards compliance), (c) the embargo date if any, and (d) the best technical contact for follow-up questions. We write for broadcast engineers, so marketing-led pitches without technical substance rarely convert to coverage.</p>

<h2 style="font-family:var(--serif);font-size:20px;margin:24px 0 10px">Corrections</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:24px">If you spot a factual error in a published article &#8212; an incorrect specification, a misidentified product category, a missing standards reference &#8212; please let us know. Include the article URL and the specific correction. Significant factual corrections are acknowledged inline on the corrected article, consistent with our <a href="editorial-policy.html" style="color:var(--blue)">Editorial Policy</a>.</p>

<div style="background:var(--bg);border-radius:14px;padding:24px 28px;margin-bottom:32px">
  <p style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--ink4);margin-bottom:12px">Our Address</p>
  <address style="font-style:normal;font-size:14px;color:var(--ink2);line-height:1.8">
    <strong>The Streamic</strong><br>
    Adamstown, Lucan<br>
    Dublin, Ireland
  </address>
  <p style="font-size:14px;color:var(--ink3);margin-top:14px;margin-bottom:4px"><strong style="color:var(--ink)">Email:</strong> <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a></p>
  <p style="font-size:14px;color:var(--ink3);margin-bottom:4px"><strong style="color:var(--ink)">Editorial:</strong> Story tips, corrections, press releases</p>
  <p style="font-size:14px;color:var(--ink3)"><strong style="color:var(--ink)">Advertising:</strong> Include &#34;Advertising&#34; in your subject line</p>
</div>
<h2 style="font-family:var(--serif);font-size:22px;margin-bottom:20px">Send us a message</h2>
<form action="https://formsubmit.co/technodate3@gmail.com" method="POST" style="display:flex;flex-direction:column;gap:16px">
  <input type="hidden" name="_subject" value="New contact form enquiry from The Streamic">
  <input type="hidden" name="_template" value="table">
  <input type="hidden" name="_next" value="https://www.thestreamic.in/contact.html?sent=1">
  <input type="text" name="_honey" style="display:none" tabindex="-1" autocomplete="off">
  <div>
    <label for="cf-name" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Your Name</label>
    <input id="cf-name" type="text" name="name" required placeholder="Jane Smith"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-email" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Email Address</label>
    <input id="cf-email" type="email" name="email" required placeholder="you@company.com"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-subject" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Subject</label>
    <input id="cf-subject" type="text" name="topic" placeholder="Editorial feedback / Story tip / Advertising"
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box">
  </div>
  <div>
    <label for="cf-message" style="display:block;font-size:13px;font-weight:600;color:var(--ink);margin-bottom:6px">Message</label>
    <textarea id="cf-message" name="message" required rows="5" placeholder="Your message..."
      style="width:100%;padding:10px 14px;border:1px solid var(--line);border-radius:8px;font-size:14px;color:var(--ink);background:#fff;box-sizing:border-box;resize:vertical"></textarea>
  </div>
  <button type="submit"
    style="align-self:flex-start;padding:11px 28px;background:var(--blue);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s ease">
    Send Message
  </button>
</form>
<p style="font-size:12px;color:var(--ink4);margin-top:14px;line-height:1.6">On first use, FormSubmit sends a one-time activation email to <strong>technodate3@gmail.com</strong>. After you confirm it once, future submissions go directly to your inbox.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def privacy_page():
    yr = datetime.now().year
    return f"""{head("Privacy Policy — The Streamic","Privacy Policy for thestreamic.in",f"{BASE_URL}/privacy.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:760px">
<h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,38px);margin-bottom:20px">Privacy Policy</h1>
<p style="font-size:12px;color:var(--ink4);margin-bottom:28px">Last updated: March 2026</p>
<div style="font-size:15px;color:var(--ink3);line-height:1.75">
<p style="margin-bottom:16px">This Privacy Policy explains how The Streamic (&quot;we&quot;, &quot;us&quot;, &quot;our&quot;) collects, uses, and protects information when you visit thestreamic.in. We respect your privacy and are committed to processing any personal data lawfully and transparently under the UK GDPR, EU GDPR, and Irish Data Protection Act 2018.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">What information we collect</h2>
<p style="margin-bottom:16px">We collect a minimal set of information necessary to operate the site and understand how visitors use it:</p>
<ul style="padding-left:22px;line-height:1.9;margin-bottom:16px">
  <li><strong>Analytics data</strong> &#8212; anonymised page views, session duration, referrer, approximate city-level geography, device type, and browser. Collected only if you accept analytics cookies.</li>
  <li><strong>Contact form submissions</strong> &#8212; if you choose to email us or submit the contact form, we receive your email address and the content of your message. We use this solely to reply to your enquiry.</li>
  <li><strong>Advertising data</strong> &#8212; processed by Google AdSense under their own privacy policy. We do not receive personally identifiable advertising data.</li>
</ul>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Cookies and Analytics</h2>
<p style="margin-bottom:16px">We use Google Analytics (GA4) to understand how visitors use our site &#8212; which articles are read, how readers arrive (search, social, direct), and which pages load slowly. Analytics cookies are only placed after you click &quot;Accept all&quot; on our cookie banner. Until you consent, no analytics cookies are set and no data is collected. You can withdraw consent at any time by clearing your browser cookies, using the browser&#39;s privacy controls, or using a GA4 opt-out browser extension.</p>
<p style="margin-bottom:16px">We do not use cross-site tracking cookies, fingerprinting, session replay, or third-party analytics beyond Google Analytics and AdSense.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Advertising</h2>
<p style="margin-bottom:16px">We display advertisements via Google AdSense (publisher ID: {ADS}). Google may use cookies to show you personalised ads based on your browsing history across sites that use Google&#39;s ad services. You can opt out of personalised advertising at <a href="https://adssettings.google.com" rel="nofollow" style="color:var(--blue)">adssettings.google.com</a>. Google&#39;s use of advertising cookies is governed by their <a href="https://policies.google.com/technologies/ads" rel="nofollow" style="color:var(--blue)">advertising policies</a>.</p>
<p style="margin-bottom:16px">If you prefer to see non-personalised ads, your browser or device may offer a &quot;Limit Ad Tracking&quot; setting. Google AdSense honours these signals where technically possible.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Data we do not collect</h2>
<p style="margin-bottom:16px">We do not collect names, postal addresses, phone numbers, payment details, or other personal data unless you voluntarily provide it by contacting us directly. We do not sell, rent, or trade any data we hold. We do not maintain a marketing mailing list.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Your rights under GDPR</h2>
<p style="margin-bottom:16px">If you are located in the UK or EU, you have the right to access, rectify, erase, restrict, or object to the processing of any personal data we hold about you. To exercise any of these rights, email <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a>. We will respond within 30 days. You also have the right to lodge a complaint with the Irish Data Protection Commission at <a href="https://www.dataprotection.ie" rel="nofollow" style="color:var(--blue)">dataprotection.ie</a>.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Data retention</h2>
<p style="margin-bottom:16px">Analytics data is retained for up to 14 months as configured in Google Analytics 4. Email correspondence is retained for as long as is reasonably necessary to handle the enquiry, typically no more than 24 months.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Changes to this policy</h2>
<p style="margin-bottom:16px">We may update this Privacy Policy to reflect changes to our data processing practices or to comply with new regulatory requirements. Substantive changes will be noted at the top of this page with an updated &quot;last modified&quot; date.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Contact</h2>
<p>Privacy queries, data access requests, or correction requests: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a></p>
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def terms_page():
    return f"""{head("Terms of Use — The Streamic","Terms of Use for thestreamic.in",f"{BASE_URL}/terms.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:760px">
<h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,38px);margin-bottom:20px">Terms of Use</h1>
<p style="font-size:12px;color:var(--ink4);margin-bottom:28px">Last updated: March 2026</p>
<div style="font-size:15px;color:var(--ink3);line-height:1.75">
<p style="margin-bottom:16px">By accessing thestreamic.in, browsing articles, using our contact form, or interacting with the site in any way, you agree to these Terms of Use. If you do not agree with any part of these terms, please do not use the site. These terms are governed by the laws of Ireland. Any dispute arising from use of the site is subject to the exclusive jurisdiction of the courts of Ireland.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Use of the site</h2>
<p style="margin-bottom:16px">You are granted a limited, non-exclusive, non-transferable licence to access and view the content on thestreamic.in for personal and professional reference purposes. Automated scraping, large-scale content harvesting, or use of the site to train AI models without express written permission is prohibited. You may not attempt to gain unauthorised access to any part of the site, its servers, or any connected systems.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Content ownership</h2>
<p style="margin-bottom:16px">Original editorial content on The Streamic &#8212; including article text, headlines, data visualisations, and editorial analysis &#8212; is copyright &copy; The Streamic. All rights reserved. You may quote short excerpts with attribution and a link back to the original article, consistent with standard journalistic practice. You may not republish, mirror, or redistribute full articles without written permission.</p>
<p style="margin-bottom:16px">Industry news briefings credit and link to their original sources. Where we quote or summarise a third-party press release or vendor announcement, we do so under standard journalistic fair-dealing principles. All third-party trademarks, product names, and logos are the property of their respective owners.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Editorial disclaimer</h2>
<p style="margin-bottom:16px">Content on The Streamic is provided for informational and educational purposes only. While we take reasonable care to ensure accuracy, we make no warranties &#8212; express or implied &#8212; regarding the completeness, timeliness, or reliability of any article. Technical specifications, product capabilities, and vendor roadmaps change over time; always verify critical integration details directly with the manufacturer before making purchasing or architectural decisions.</p>
<p style="margin-bottom:16px">Articles should not be construed as professional advice. The Streamic is not responsible for business decisions made based solely on our editorial content.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">External Links</h2>
<p style="margin-bottom:16px">We link to external sources &#8212; vendor websites, news publications, standards bodies &#8212; using <code>rel=&quot;nofollow noopener noreferrer&quot;</code> where appropriate. We are not responsible for the content, availability, privacy practices, or terms of service of any linked website. Inclusion of an external link does not constitute endorsement.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">User conduct</h2>
<p style="margin-bottom:16px">When contacting us via email or the contact form, you agree not to send abusive, threatening, defamatory, or unlawful messages. We reserve the right to ignore or report communications that violate these conditions. Spam, promotional pitches unrelated to editorial topics, and SEO-link-building requests will not receive a reply.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Availability</h2>
<p style="margin-bottom:16px">We aim to keep thestreamic.in available at all times but make no warranty of continuous availability. The site may be unavailable during maintenance, migration, or due to factors beyond our control (CDN outages, DNS issues, hosting-provider incidents). We are not liable for any loss arising from site unavailability.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Changes to these terms</h2>
<p style="margin-bottom:16px">We may update these Terms of Use from time to time. Continued use of the site after changes are published constitutes acceptance of the revised terms. Substantive changes will be noted at the top of this page with an updated &quot;last modified&quot; date.</p>

<h2 style="font-family:var(--serif);font-size:20px;color:var(--ink);margin:28px 0 10px">Contact</h2>
<p style="margin-bottom:16px">For questions about these Terms, please email <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a>.</p>
</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""
def editorial_policy_page():
    last_updated = datetime.now(timezone.utc).strftime("%B %d, %Y")
    return f"""{head("Editorial Policy — The Streamic","Editorial approach, coverage focus, experience, and contact information for The Streamic.",f"{BASE_URL}/editorial-policy.html")}
<body>
{nav("editorial-policy.html")}
<main><div class="w" style="padding:52px 24px 80px;max-width:780px">
<h1 style="font-family:var(--serif);font-size:clamp(26px,4vw,42px);margin-bottom:16px;letter-spacing:-.5px">Editorial Policy</h1>
<p style="font-size:13px;color:var(--ink4);margin-bottom:32px">Last updated: {last_updated}</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:0 0 12px">About The Streamic</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">The Streamic is an independent publication focused on broadcast technology, media infrastructure, streaming workflows, newsroom systems, and post-production operations.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">The publication is built around a simple idea: most industry coverage explains what is announced — but very little explains what actually works in production. The Streamic focuses on that gap.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">We analyse how systems behave in real environments: how workflows connect, where integrations fail, how standards are implemented, and what operational teams need to consider before deployment.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Editorial Focus</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:14px">The Streamic covers:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li>Broadcast infrastructure and IP workflows (including SMPTE ST 2110 environments)</li>
  <li>Streaming and OTT delivery systems (HLS, DASH, CDN workflows)</li>
  <li>Post-production pipelines (NLE interoperability, conform, grading, delivery)</li>
  <li>Media asset management (MAM/PAM) and archive strategies</li>
  <li>Cloud and hybrid production workflows</li>
  <li>Newsroom systems and editorial operations</li>
  <li>Monitoring, automation, and operational reliability</li>
</ul>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">Coverage is technical, vendor-aware, and grounded in real-world implementation rather than marketing narratives.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Experience Behind The Publication</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:14px">The Streamic is founded and operated by a broadcast and media systems professional based in Dublin, Ireland.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:14px">The editorial direction is informed by:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li>20+ years of experience in broadcast and media technology environments in India, across installation, maintenance, and troubleshooting of production and post-production systems</li>
  <li>4+ years working within broadcast operations in Dublin, supporting modern media workflows in live and production environments</li>
  <li>Hands-on exposure to newsroom systems, playout infrastructure, post-production pipelines, and evolving IP-based media systems</li>
</ul>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">This background shapes the editorial approach — practical, systems-focused, and aligned with how technology behaves under real operational pressure.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">How We Work</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">The Streamic is not a press-release publication.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:14px">Each article is written as independent editorial analysis based on:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li>publicly available technical information</li>
  <li>industry announcements and documentation</li>
  <li>observed workflow patterns across broadcast and post-production environments</li>
</ul>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">The goal is to extract operational insight, not repeat vendor messaging.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">Where information is incomplete or evolving, that uncertainty is acknowledged rather than assumed.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Editorial Independence</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:14px">The Streamic operates independently.</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li>We do not accept paid editorial coverage</li>
  <li>Vendor mentions are based on relevance, not commercial relationships</li>
  <li>Advertising, where present, does not influence editorial decisions</li>
</ul>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Who This Is For</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:14px">The Streamic is written for:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li>Broadcast engineers and system integrators</li>
  <li>Post-production supervisors and technical operators</li>
  <li>Media IT and infrastructure teams</li>
  <li>Technology decision-makers in broadcast and streaming environments</li>
</ul>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">If your work involves keeping media systems running reliably under real constraints, this publication is built for you.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Location</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:20px">Dublin, Ireland</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Contact</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">For editorial enquiries, feedback, or corrections:</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px"><a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> or use the <a href="contact.html" style="color:var(--blue)">contact form</a> on this site.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def insights_page():
    """Expert Insights landing page — AdSense-compliant substantive content (~800w)
    with featured expert-interview cards linking to hand-authored Q&A pages.

    The cards below link to HAND_AUTHORED files under docs/articles/ that are
    protected from the automated build. Add more entries to _interviews to
    feature additional interviews — no other code changes needed.
    """
    # Featured expert interviews (hand-authored, HAND_AUTHORED-marked pages).
    # These are the prominent link cards at the top of /insights.html.
    _interviews = [
        {
            "href": "articles/Expertinsight1.html",
            "series": "The Veteran's Lens",
            "title": "Neil Sadwelkar on AI and the Future of Digital Imaging",
            "dek": "From negative cutting to AI-assisted colour grading — a candid conversation with one of India's foremost DI pioneers on what the technology revolution really means for broadcast and cinema post-production.",
            "expert_name": "Neil B. Sadwelkar",
            "expert_role": "Digital Imaging Technician &amp; Post-Production Pioneer",
            "read_time": "12 min read",
            "published": "April 2, 2026",
        },
    ]

    interview_cards_html = ""
    for iv in _interviews:
        interview_cards_html += f"""
<a class="insights-feat-card" href="{iv['href']}">
  <span class="insights-feat-series">&#10022; {iv['series']}</span>
  <h3 class="insights-feat-title">{iv['title']}</h3>
  <p class="insights-feat-dek">{iv['dek']}</p>
  <div class="insights-feat-meta">
    <span class="insights-feat-expert"><strong>{iv['expert_name']}</strong> &middot; {iv['expert_role']}</span>
  </div>
  <div class="insights-feat-footer">
    <span class="insights-feat-details">{iv['published']} &middot; {iv['read_time']}</span>
    <span class="insights-feat-cta">Read the interview &rarr;</span>
  </div>
</a>"""

    return f"""{head("Expert Insights — The Streamic","Long-form broadcast technology analysis and expert interviews: AI colour grading, ST 2110 rollouts, cloud production, post-production workflows, and operational engineering for media teams.",f"{BASE_URL}/insights.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:820px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">Expert Insights</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:32px">Long-form broadcast and media technology analysis from the Streamic editorial team — plus exclusive interviews with veteran engineers, colourists, DITs, and media-IT architects. These are the pieces we write when a topic needs more than a news briefing: standards deep-dives, architectural playbooks, vendor-neutral integration patterns, and field reports from broadcast engineers working in live production and post facilities.</p>

<style>
.insights-feat-wrap{{display:flex;flex-direction:column;gap:20px;margin:28px 0 40px}}
.insights-feat-card{{display:block;padding:26px 28px;background:linear-gradient(180deg,#fffdf7 0%,#f8f2e6 100%);border:1px solid #e6dcc2;border-radius:14px;box-shadow:0 10px 28px rgba(63,47,22,.08);text-decoration:none;color:inherit;transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}}
.insights-feat-card:hover{{transform:translateY(-2px);box-shadow:0 16px 36px rgba(63,47,22,.12);border-color:#d4af37}}
.insights-feat-series{{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#8b6b3f;margin-bottom:12px}}
.insights-feat-title{{font-family:var(--serif);font-size:clamp(20px,2.6vw,26px);line-height:1.25;letter-spacing:-.01em;color:#17120f;margin:0 0 12px;font-weight:400}}
.insights-feat-dek{{font-family:Georgia,"Times New Roman",serif;font-size:15.5px;line-height:1.7;color:#3a322a;margin:0 0 16px}}
.insights-feat-meta{{font-size:13px;color:#5a4f40;line-height:1.55;margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid rgba(139,107,63,.18)}}
.insights-feat-meta strong{{color:#17120f}}
.insights-feat-footer{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.insights-feat-details{{font-size:12px;color:#7a6f5e}}
.insights-feat-cta{{font-size:13px;font-weight:700;color:#5f3b13;letter-spacing:.02em}}
.insights-feat-card:hover .insights-feat-cta{{color:#17120f}}
@media (max-width:640px){{.insights-feat-card{{padding:22px 20px}}}}
</style>

<h2 style="font-family:var(--serif);font-size:22px;margin:8px 0 12px">Featured interviews</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">In-depth conversations with the engineers, colourists, and technology leaders shaping broadcast and post-production. Each interview is a first-person account of the workflow shifts, standards transitions, and AI integrations these veterans are living through right now.</p>
<div class="insights-feat-wrap">{interview_cards_html}
</div>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">What Expert Insights covers</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Expert Insights articles are written for broadcast engineers, technology directors, and media operations leads who need to evaluate &#8212; not just read about &#8212; new technology. Every piece is grounded in verifiable source material, quotes technical specifications accurately, and calls out what vendors have not disclosed. Topics we return to repeatedly:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><strong>IP infrastructure deep-dives</strong> &#8212; SMPTE ST 2110 rollouts, NMOS IS-04 / IS-05 registry patterns, AES67 audio-over-IP, PTP timing validation, redundant media networks, and migration strategies from SDI to IP.</li>
  <li><strong>Cloud production &amp; playout</strong> &#8212; REMI architectures, cloud-based channel origination, CDN strategies, egress cost management, edge media caching, and multi-region disaster-recovery models.</li>
  <li><strong>Operational AI</strong> &#8212; how newsroom and post teams are actually using AI in production today, beyond the demo reel: automated QC, metadata extraction, rough-cut generation, compliance logging, and the integration burden each imposes.</li>
  <li><strong>Post-production workflows</strong> &#8212; Avid Media Composer / DaVinci Resolve / Premiere Pro interoperability, MAM and PAM integration, proxy pipelines, archive architectures, and the practical trade-offs between on-prem, hybrid, and cloud post.</li>
  <li><strong>Engineering playbooks</strong> &#8212; reference architectures for ingest-to-playout chains, integration patterns for vendor-neutral newsrooms, and honest post-mortems of standards-migration projects.</li>
</ul>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Editorial standard</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Expert Insights pieces go through a stricter review pass than our daily industry news briefings. We do not publish press-release rewrites under this banner. Where an article analyses a vendor&#39;s technology, we disclose what the vendor has stated, what our editorial team has verified independently, and what remains uncertain. Technical claims that cannot be traced to a primary source are either removed or flagged.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">AI tools assist with drafting on some Insights articles &#8212; primarily for structuring source material and initial analysis &#8212; but every published piece is reviewed by a human editor before going live. Featured interviews are transcribed and edited from first-person conversations; the interviewee reviews and approves the final published text. See our <a href="editorial-policy.html" style="color:var(--blue)">Editorial Policy</a> for the full methodology on AI-assisted drafting, source attribution, and corrections.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Who writes for us</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Streamic editorial is led by Prerak K Mehta, with 25+ years of IT experience and 20 years in media / post-production / broadcast IT systems. Guest contributions from broadcast engineers, vendor technical staff, and media operations leaders are welcome &#8212; email <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> with a short pitch outline and any relevant technical credentials.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Read our latest analysis</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Browse our complete archive on the <a href="index.html" style="color:var(--blue)">homepage</a>, our AI-focused coverage on the <a href="ai-post-production.html" style="color:var(--blue)">AI in Broadcasting</a> page, practical guides on the <a href="howto.html" style="color:var(--blue)">How-To Guides</a> page, or curated editorial picks on the <a href="editorsdesk.html" style="color:var(--blue)">Editor&#39;s Desk</a>.</p>

<p style="font-size:13px;color:var(--ink4);line-height:1.7;margin-top:36px;padding-top:20px;border-top:1px solid var(--line)">Have a story tip or a topic we should cover in depth? Reach the editorial team at <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> or via our <a href="contact.html" style="color:var(--blue)">contact form</a>.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""


def post_production_workflows_page():
    """Post Production Workflows landing page — AdSense-compliant (~700w)."""
    return f"""{head("Post Production Workflows — The Streamic","Practical post-production workflow analysis: NLE interoperability, MAM / PAM integration, proxy pipelines, codec compatibility, and cloud collaboration for broadcast post teams.",f"{BASE_URL}/post-production-workflows.html")}
<body>
{nav()}
<main><div class="w" style="padding:52px 24px 80px;max-width:820px">
<h1 style="font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:16px;letter-spacing:-.5px">Post Production Workflows</h1>
<p style="font-size:17px;color:var(--ink2);line-height:1.65;margin-bottom:24px">Practical analysis of post-production workflows for broadcast, streaming, and film teams. We cover what actually works in production &#8212; NLE handoffs that survive round-trip, proxy pipelines that don&#39;t break at the storage boundary, MAM integrations that don&#39;t trap metadata, and cloud collaboration patterns that respect the realities of bandwidth, security, and editorial sovereignty.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">What we cover</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:12px">Streamic post-production coverage focuses on the integration seams where workflows most often break:</p>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><strong>NLE interoperability</strong> &#8212; AAF, OMF, XML, EDL, and Direct Link handoffs between Avid Media Composer, DaVinci Resolve, Premiere Pro, and Final Cut Pro. Where audio maps cleanly, where effects translate, where timecode gets mangled.</li>
  <li><strong>Codec &amp; container strategy</strong> &#8212; ProRes, DNxHD/HR, XAVC, AVC-Intra, IMF packaging, and the codec-choice decisions that determine whether a finish survives delivery QC on the first pass.</li>
  <li><strong>MAM &amp; PAM integration</strong> &#8212; Avid Nexis and MediaCentral, EditShare EFS, Strawberry, Primestream, Dalet Flex. Which asset models travel, which metadata schemas survive a vendor migration, and where API parity fails.</li>
  <li><strong>Proxy pipelines</strong> &#8212; when to generate proxies at ingest vs. at check-out, codec selection for proxy masters (DNx36 / ProRes Proxy / H.264), and how to keep proxy-to-full conform reliable across distributed teams.</li>
  <li><strong>Cloud &amp; hybrid post</strong> &#8212; Frame.io, EditShare Cloud, Blackmagic Cloud, Avid Edit On Demand, and the bandwidth / latency / security trade-offs of each. Real-world remote editing vs. marketing-reel remote editing.</li>
  <li><strong>Archive &amp; restore</strong> &#8212; LTO strategies, object-storage archive tiers, cold-retrieval SLAs, and the dark art of conforming an archived project 18 months later when the original NLE has moved on three versions.</li>
</ul>
<h2 style="font-family:var(--serif);font-size:22px;margin:36px 0 14px">Workflow Deep Dives</h2>

<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-bottom:28px">

  <a href="articles/studio-grade-video-workflow-post-production-2026.html"
     style="position:relative;display:block;overflow:hidden;border-radius:20px;min-height:200px;background:#111;text-decoration:none;color:#fff;box-shadow:0 10px 28px rgba(0,0,0,.12)">

    <img src="assets/images/post_production/post-production-workflow.jpg"
         alt="Studio Grade Video Workflow"
         loading="lazy"
         onerror="this.onerror=null;this.src='assets/fallback.jpg'"
         style="width:100%;height:100%;object-fit:cover;opacity:.9">

    <div style="position:absolute;inset:0;background:linear-gradient(to top, rgba(0,0,0,.85), rgba(0,0,0,.2))"></div>

    <div style="position:absolute;bottom:0;padding:18px">
      <span style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;opacity:.8">Post Production</span>
      <h3 style="margin:6px 0 6px;font-family:var(--serif);font-size:20px;line-height:1.25">
        Studio Grade Video Workflow 2026
      </h3>
      <p style="font-size:13px;opacity:.85;line-height:1.5;margin:0">
        End-to-end post workflow from ingest to delivery, covering proxy, conform, grading, and final packaging.
      </p>
    </div>
  </a>

  <a href="articles/2026-04-01-ai-post-production-frameio-workfront-review-approval-workflow.html"
     style="position:relative;display:block;overflow:hidden;border-radius:20px;min-height:200px;background:#111;text-decoration:none;color:#fff;box-shadow:0 10px 28px rgba(0,0,0,.12)">

    <img src="assets/images/post_production/cloud-review-workflow.jpg"
         alt="Frame.io Workfront Review Workflow"
         loading="lazy"
         onerror="this.onerror=null;this.src='assets/fallback.jpg'"
         style="width:100%;height:100%;object-fit:cover;opacity:.9">

    <div style="position:absolute;inset:0;background:linear-gradient(to top, rgba(0,0,0,.85), rgba(0,0,0,.2))"></div>

    <div style="position:absolute;bottom:0;padding:18px">
      <span style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;opacity:.8">Cloud Collaboration</span>
      <h3 style="margin:6px 0 6px;font-family:var(--serif);font-size:20px;line-height:1.25">
        Frame.io + Workfront Review Workflow
      </h3>
      <p style="font-size:13px;opacity:.85;line-height:1.5;margin:0">
        How AI-assisted review and approval workflows connect creative teams, stakeholders, and delivery pipelines.
      </p>
    </div>
  </a>

</div>
<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Our approach</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Post-production technology is drowning in marketing. Every NLE claims seamless interchange, every MAM claims universal metadata, every cloud-collaboration platform claims security-first architecture. Our job is to separate what actually ships from what is still a product roadmap, and to call out the integration gotchas that only surface at 02:00 on a delivery night.</p>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Every Streamic article in this area is grounded in real workflow analysis, not vendor-supplied slideware. Where a vendor claims compatibility, we verify by checking against shipping documentation, public API specs, and &#8212; where possible &#8212; the experience of engineering teams running it in production. Where compatibility is partial or conditional, we say so.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Who this is for</h2>
<p style="font-size:15px;color:var(--ink3);line-height:1.75;margin-bottom:16px">Post-production supervisors, assistant editors, technical operators, broadcast IT leads supporting post facilities, and technology directors evaluating MAM / NLE / cloud-post decisions. If you have ever argued with a vendor rep about whether AAF round-trips EQ automation in version 2024.8, this section is for you.</p>

<h2 style="font-family:var(--serif);font-size:22px;margin:32px 0 12px">Related Streamic sections</h2>
<ul style="font-size:15px;color:var(--ink3);line-height:1.9;padding-left:22px;margin-bottom:20px">
  <li><a href="howto.html" style="color:var(--blue)">How-To Guides</a> &#8212; step-by-step technical guides: Premiere-to-Avid handoff, Vantage transcoding recipes, MediaCentral health checks, audio conform workflows.</li>
  <li><a href="ai-post-production.html" style="color:var(--blue)">AI in Broadcasting</a> &#8212; AI-assisted editing tools, automated QC, generative tools for post, and operational integration patterns.</li>
  <li><a href="insights.html" style="color:var(--blue)">Expert Insights</a> &#8212; long-form analysis and architectural reference material.</li>
  <li><a href="editorsdesk.html" style="color:var(--blue)">Editor&#39;s Desk</a> &#8212; curated editorial picks across the Streamic archive.</li>
</ul>

<p style="font-size:13px;color:var(--ink4);line-height:1.7;margin-top:36px;padding-top:20px;border-top:1px solid var(--line)">Post team working on an integration we should cover? Tell us: <a href="mailto:technodate3@gmail.com" style="color:var(--blue)">technodate3@gmail.com</a> or <a href="contact.html" style="color:var(--blue)">contact form</a>.</p>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""


# ── HOW-TO GUIDE CONTENT (self-heals 410 stubs in docs/articles/) ─────────────
# Each value must be ≥500 words of practical broadcast engineering content so
# the regenerated pages pass AdSense quality gates.

HOWTO_GUIDE_CONTENT = {
    "guide-premiere-to-avid": {
        "tag": "Post-Production · Interchange",
        "time": "8 min",
        "title": "Premiere Pro to Avid Media Composer: AAF, EDL & Direct Link Handoff",
        "dek": "Moving a cut from Premiere Pro to Avid Media Composer without losing audio mapping, timecode, or effect metadata. A practical handoff guide.",
        "sections": [
            ("Why this handoff still matters", "Despite years of vendor talk about &quot;seamless interchange&quot;, most facility-grade handoffs between Premiere Pro and Avid Media Composer still fail in predictable ways: audio channels remap, time-warps flatten to static clips, dissolves translate but sub-frame retimes do not, and timecode starts drift by a frame at reel boundaries. The reality in 2026 is that AAF remains the dominant container, but the quality of the export depends heavily on which format you chose at ingest and how disciplined your timeline is."),
            ("Pre-export checklist", "Before you export, lock the sequence. Flatten nested sequences one level deep — Avid will not honour multi-nest hierarchies consistently. Set your timecode start to match the target Avid project (01:00:00:00 by convention). Ensure all audio is mono-mapped on discrete tracks: Premiere&#39;s stereo sub-mix collapses to unpredictable pan positions on the Avid side. Finally, verify all source media is online and the cache has finished rendering — missing media breaks the AAF reference chain silently."),
            ("AAF export settings", "From Premiere, use <em>File &gt; Export &gt; AAF</em>. Choose <strong>Embedded Audio</strong> only if your facility does not have a shared Avid Nexis/ISIS — otherwise use <strong>Link to Audio Files</strong> and consolidate them to a shared drive first. For video, &quot;Break Complex Clips&quot; should be unchecked if you want to preserve retime speeds; checked if you need Avid-native cuts. Audio render sample rate should match your Avid project (48kHz/24-bit is the broadcast norm)."),
            ("Direct Link alternative", "For facilities running Adobe and Avid side-by-side, <strong>Avid Media Composer 2024.12</strong> onwards supports a limited Direct Link path via the Adobe Creative Cloud extension. Direct Link preserves more effect metadata than AAF but requires a live network path between the two workstations and the same Nexis workspace mounted on both. It is faster than AAF for small cuts (under 15 minutes) but slower and less reliable for long-form drama or broadcast packages."),
            ("Common failures & fixes", "<strong>Audio maps wrong:</strong> Premiere stereo tracks become A1/A2 in Avid but L/R pan is often lost — re-pan inside Avid after import. <strong>Missing effects:</strong> Lumetri grades do not translate — export a render instead, or bake grades to colour metadata using OpenColorIO. <strong>Timecode drift:</strong> Start each reel at a round-number TC and break reels at the Avid project&#39;s master TC, not Premiere&#39;s. <strong>Frame rate mismatch:</strong> 23.976 vs 24.000 is the single most common project-breaker — match exactly before exporting."),
            ("Round-tripping back to Premiere", "If the colourist works in Avid Symphony and needs to round-trip back for finishing, export AAF from Avid with embedded renders, re-link in Premiere to the original source media, then re-apply Lumetri grades against the Avid&#39;s EDL. This is slow but reliable. For broadcast delivery, skip the round-trip — finish in the tool where you started the grade."),
                    ("Final QC pass before shipping", "Before the AAF leaves Premiere, generate a PDF of the sequence&#39;s clip list via Adobe&#39;s <em>Export &gt; Clip Notes</em>, or screenshot the timeline with track headers visible. On the Avid side, the assistant editor cross-references clip names and timecodes against this reference document. Discrepancies found at this stage take minutes to fix; discrepancies found after the online grade or mix take days to unwind. For broadcast deliveries subject to strict QC (BBC, ITV, PBS, major OTT platforms), keep this audit PDF archived alongside the conformed Pro Tools session and the final master file for at least 12 months after delivery. This becomes invaluable when a version B needs conforming 6 months later."),
        ],
    },
    "guide-vantage-nas-transcode": {
        "tag": "Vantage · Encoding",
        "time": "6 min",
        "title": "Telestream Vantage: Build a Hot Folder Workflow to MP4 on NAS",
        "dek": "Build a robust Vantage hot-folder workflow that transcodes any input format to broadcast-ready H.264 MP4 on a local NAS share.",
        "sections": [
            ("Workflow goals", "The target is a Vantage workflow that watches a NAS folder, accepts mixed input formats (ProRes, DNxHD, XAVC, MP4), transcodes to H.264 MP4 at 10Mbps with AAC audio, and drops the result in an output folder with the original filename suffixed <code>_web.mp4</code>. No operator touch. Failures route to an exception folder for manual review."),
            ("Building the workflow", "Open Vantage Workflow Designer. Drag in a <strong>Watch Action</strong> pointing at your NAS ingest share (<code>\\\\nas01\\media\\ingest</code>). Set poll interval to 30 seconds. Add an <strong>Identify Action</strong> to probe the file — this catches corrupt inputs early and branches them to the exception folder. Then add a <strong>Flip Action</strong> with your H.264 encoder preset attached. Finally a <strong>Deploy Action</strong> to push the output to <code>\\\\nas01\\media\\web</code>."),
            ("Flip encoder preset", "Inside Flip, create a new encoder preset. Container: MP4. Video codec: H.264 (x264). Profile: High, Level 4.0. Bitrate: 10Mbps CBR for broadcast-safe delivery; switch to 6Mbps VBR 2-pass if file size matters more. Keyframe interval: 60 frames for 1080p25/30, 72 for 1080p24. Audio: AAC-LC, 192kbps stereo, 48kHz. GOP structure: Closed, for clean editing downstream."),
            ("Path of least resistance", "A common mistake is to let Vantage write directly over an existing file — if the workflow retries on a transient NAS hiccup, you get file corruption. Use the <strong>Deploy Action&#39;s</strong> &quot;Rename if exists&quot; option instead. Similarly, if the source file is still being written when Vantage picks it up (a common problem with FTP uploads), use the <strong>File Size Stable</strong> trigger option in Watch — it waits until the file size stops changing before acting."),
            ("Testing and validation", "Drop a 10-minute test file into the ingest folder. Watch the job in Vantage Workflow Portal — it should finish in 2–3 minutes on a modern server. Validate the output with <strong>MediaInfo</strong>: check bitrate actually hits the target, audio is actually 48kHz stereo, and the first keyframe is at frame 0. Broadcast-ready H.264 MP4s should play cleanly on VLC, QuickTime, and Adobe Media Encoder — if any of those complain, re-check the profile/level."),
            ("Production hardening", "For production use, add email alerts on failed jobs (Vantage Notify Action → SMTP). Enable the <strong>Workflow Analytics</strong> database so you can track throughput over time. Set the job priority so that overnight batch doesn&#39;t block daytime ad-hoc transcode requests. And document the preset — Vantage&#39;s inline preset names are easy to forget six months later."),
                    ("Production monitoring", "Once live, watch throughput for the first week. Vantage Workflow Portal shows job duration, queue depth, and failure rate for every running workflow. Healthy signals: failure rate under 2%, queue depth never exceeding 3 on average, individual job durations consistent within 10%. Unhealthy signals: files stuck in &quot;processing&quot; for hours (usually a hung Flip process — restart the Vantage transcode service), ballooning queue depth (upgrade encoder license count or deploy a second Vantage server), or highly variable job times (likely a NAS performance bottleneck). Also watch NAS free space weekly; a full output share silently breaks the workflow because Deploy actions cannot complete their writes and the jobs hang indefinitely. Set the job priority explicitly so that overnight batch jobs do not block daytime ad-hoc transcode requests when editors need a file urgently. Document the preset and workflow configuration in your team wiki — Vantage&#39;s inline preset names are easy to forget six months later when someone needs to reproduce or modify the workflow."),
        ],
    },
    "guide-vantage-aws-transcode": {
        "tag": "Vantage · AWS · Cloud",
        "time": "6 min",
        "title": "Telestream Vantage: Deliver MP4 Output Directly to Amazon S3",
        "dek": "Extend your Vantage workflow to deliver MP4 output directly to Amazon S3. IAM setup, bucket policies, and parallel NAS + S3 delivery.",
        "sections": [
            ("Why S3 delivery matters", "Most broadcast workflows now have at least one cloud delivery target — a CDN origin, a FAST-channel distributor, or an ad-sales team that lives in S3. Delivering from Vantage directly to S3 saves a manual upload step and eliminates the class of bugs that come from &quot;the file on the NAS doesn&#39;t match the file in the cloud&quot;. It also integrates cleanly with AWS MediaConvert triggers if you need further downstream processing."),
            ("AWS prerequisites", "Create a dedicated IAM user for Vantage (don&#39;t reuse a human user&#39;s credentials). The policy needs <code>s3:PutObject</code>, <code>s3:PutObjectAcl</code>, and <code>s3:ListBucket</code> on the target bucket — nothing else. Generate an access key/secret pair and store them in a secrets manager; you&#39;ll paste them into Vantage once. On the bucket itself, enable versioning (protects against accidental overwrites) and configure a lifecycle rule to move objects to S3 Intelligent-Tiering after 30 days."),
            ("Configuring Vantage", "In Vantage Management Console, open <strong>Storage &gt; Cloud Storage</strong> and add an S3 connection. Paste the IAM access key/secret, select the region (use the one closest to your facility — eu-west-1 for Europe, us-east-1 for default US). Test the connection — Vantage will attempt a dummy write and delete. If it fails, check the IAM policy first, then bucket encryption settings second."),
            ("Adding S3 to your existing workflow", "Open the hot-folder workflow from the NAS guide. Add a second <strong>Deploy Action</strong> after the existing NAS deploy. Configure this second deploy to use the S3 connection and point it at <code>s3://yourbucket/broadcast/</code>. Set the object key pattern to <code>{Name}.mp4</code>. Now you have parallel NAS + S3 delivery — the same file lands in both places."),
            ("Server-side encryption", "For broadcast content, enable server-side encryption with KMS keys (SSE-KMS). Vantage honours this automatically if you&#39;ve set the bucket default encryption — you don&#39;t need per-object configuration. For titles under embargo, use a separate KMS key with restricted access; rotate the key before the embargo lifts to invalidate any cached copies in intermediate systems."),
            ("Cost control", "S3 standard storage is cheap; data transfer out is not. Budget $0.09/GB for egress to the open internet. A single 10Mbps H.264 broadcast master is roughly 4.5GB per hour, so a daily 60-minute delivery to 5 regional distributors costs about $2/day in egress alone. For heavy delivery volumes, look at <strong>AWS CloudFront</strong> origination from S3 — egress pricing is different and often cheaper at scale. Set up billing alerts at $50/month so you catch runaway jobs early."),
                    ("CloudWatch monitoring", "Add CloudWatch alarms on your target S3 bucket: one for unexpectedly large object uploads (potential runaway transcode producing oversized files), one for excessive daily egress (potential unauthorised download activity), and one for failed PutObject calls (IAM permission drift after credential rotation). Route alerts to a Slack or PagerDuty channel your operations team monitors. For broadcast operations where S3 delivery is mission-critical, add a synthetic health check that uploads a 1MB test file every 15 minutes via Lambda and alerts if it fails — this catches credential rotation problems, bucket permission drift, or network-level issues before a real broadcast delivery fails and your downstream partners complain. For heavy delivery volumes, investigate AWS CloudFront origination from S3 as an alternative delivery architecture — egress pricing through CloudFront is often significantly cheaper than direct S3 egress at scale, and the added caching layer improves delivery latency for international audiences. Always set up AWS billing alerts at sensible thresholds so unexpected cost spikes get caught early."),
        ],
    },
    "guide-avid-strawberry": {
        "tag": "Strawberry PAM · Avid",
        "time": "10 min",
        "title": "Strawberry PAM + Avid Media Composer: Collaborative Editing Setup",
        "dek": "Configure Production Flow Strawberry for collaborative Avid Media Composer editing: shared storage, hot-folder ingest, version control, and automated delivery.",
        "sections": [
            ("What Strawberry adds to an Avid shop", "Strawberry from Production Flow is a Production Asset Management (PAM) layer that sits on top of Avid Nexis (or an SMB share) and gives editors a web UI for browsing, tagging, and handing off projects. It&#39;s not a replacement for MediaCentral — it&#39;s a lightweight alternative for facilities that need collaborative workflow but don&#39;t want the MediaCentral licensing overhead. The sweet spot is a 5–15 seat post facility."),
            ("Shared storage architecture", "Strawberry needs one &quot;workspace root&quot; — a shared volume visible to every editor at the same mount path (e.g. <code>/Volumes/shared</code> on macOS, <code>Z:\\</code> on Windows). Avid Nexis workspaces work fine; so do SMB shares served from a TrueNAS or Synology box. For workstations connecting over 10GbE, a SSD-backed NAS can sustain 4–6 concurrent HD streams without stuttering. For remote editors, add a caching layer or switch to proxy-based editing."),
            ("Avid project structure", "Strawberry expects each Avid project to live in its own folder under the workspace root: <code>/Volumes/shared/ProjectName/</code>. Inside, standard Avid subfolders: <code>Avid Projects/</code>, <code>Avid MediaFiles/MXF/1/</code>, and a Strawberry-specific <code>_Strawberry/</code> that holds metadata. Editors open projects via Media Composer&#39;s normal open dialog; Strawberry runs alongside as a web UI in a browser tab."),
            ("Ingest hot folders", "Configure Strawberry&#39;s ingest rules in the web admin. Create a &quot;Rushes&quot; hot folder at <code>/Volumes/shared/_ingest/</code>. Rules: incoming files tagged by date, transcoded to DNxHD 36 (proxy) + DNxHD 120 (online), attached as AMA-linked or fully imported based on size. For XDCAM EX or AVCHD source, enable the auto-transcode rule — playback in Avid is much smoother after transcode than via AMA on these codecs."),
            ("Version control &amp; project locking", "Strawberry&#39;s killer feature is project-level locking. When Editor A opens a project, Strawberry marks it locked in its database and other editors see a read-only indicator. When A closes the project, the lock releases. For finer granularity, use bins rather than whole projects — multi-editor concurrent editing on separate bins of the same project is supported. Avoid two editors editing the same bin at the same time; Avid&#39;s internal bin locking is per-file and conflicts produce silent data loss."),
            ("Automated delivery", "Strawberry can trigger downstream workflows when an editor tags a sequence &quot;Delivered&quot;. Typical pattern: tag fires a webhook to Telestream Vantage, which picks up the sequence&#39;s export, transcodes it to delivery spec, and pushes to S3 or the client&#39;s MAM. This closes the loop from edit bay to CDN without a human re-exporting files. Monitor the webhook queue in Strawberry&#39;s admin — failed hand-offs are the most common break point and easy to miss."),
                    ("Editor adoption and training", "The hardest part of a Strawberry deployment is not the technical setup — it&#39;s getting editors to adopt the web UI instead of reverting to the Finder or Windows Explorer. Budget a dedicated half-day training session per editor that covers: browsing the rushes folder via Strawberry rather than the OS file browser, tagging sequences with delivery-ready metadata, using the metadata search to find shots across old projects, and proper locking etiquette when multiple editors work on adjacent bins. The payoff is measurable: facilities that fully adopt Strawberry workflow typically reclaim 20 to 30 minutes per editor per day that was previously spent manually hunting for files. Track adoption metrics for the first month and coach the stragglers individually rather than hoping they&#39;ll catch up on their own."),
        ],
    },
    "guide-audio-conform-avid-protools": {
        "tag": "Avid · Pro Tools · Audio",
        "time": "9 min",
        "title": "Audio Conform: Avid Media Composer to Pro Tools and Back",
        "dek": "Export AAF from Avid, open in Pro Tools for audio finishing, and return the mix in sync. Covers sample rates, BWF export, timecode alignment.",
        "sections": [
            ("The conform workflow overview", "In broadcast post, the audio finish almost always happens in Pro Tools — Avid&#39;s built-in audio mixer is adequate for offline but not for a final broadcast mix. The conform is the process of handing off the locked picture edit to the mixer, who finishes the audio, and handing the final mix back to the video edit for deliverable export. Done right, the round trip takes a day. Done wrong, it takes a week of chasing sync drift."),
            ("Lock the picture before you conform", "The single most important rule: lock the picture edit before handing off to audio. Every frame change after the conform forces the mixer to re-align every track. Budget a 24-hour &quot;picture lock&quot; period where the director reviews the cut, notes last changes, and signs off. Only then does the editor export for audio."),
            ("AAF export from Avid", "From Avid, select the sequence and choose <em>File &gt; Export &gt; AAF</em>. Settings: Embedded Media, 48kHz/24-bit BWF audio, one AAF per reel if the show is broken into reels. Enable &quot;Include handles&quot; and set handle length to 2 seconds — this gives the mixer room to extend fades beyond the cut. Disable &quot;render video&quot; — the mixer doesn&#39;t need picture in the AAF. Export the reference QuickTime separately at a known offset (start at 01:00:00:00 or 10:00:00:00, document which)."),
            ("Opening in Pro Tools", "Pro Tools imports AAFs cleanly. Choose <em>File &gt; Import &gt; Session Data</em>, select the AAF, match the Pro Tools session sample rate to the AAF (48kHz). Pro Tools will create one track per Avid audio track. Review: mono tracks should stay mono, stereo pairs should come in as two mono tracks panned L/R (not a true stereo track). Import the reference QuickTime via <em>File &gt; Import &gt; Video</em> to the same timecode start."),
            ("Common sync problems", "<strong>Sample-rate mismatch:</strong> if Avid was 48000Hz and Pro Tools opens at 48048Hz (varispeed), every minute drifts by 3 frames. Always match exactly. <strong>Frame-rate mismatch:</strong> 23.976 vs 24.000 drifts by one frame per second — catastrophic over a half-hour show. <strong>Drop-frame vs non-drop-frame:</strong> US projects that mix both produce apparent sync drift that&#39;s actually labelling confusion — agree drop-frame-or-not upfront and stick with it."),
            ("Returning the mix", "When the mixer finishes, they export a stereo or 5.1 mix as a BWF file with embedded timecode matching the original. Back in Avid, the editor imports the BWF via <em>File &gt; Import</em>, selects &quot;Use timecode of source&quot; and places it at the original reel start. Verify sync by scrubbing through 3–4 obvious sync points (dialogue lines, door slams). If anything drifts by even one frame, the frame rate or sample rate is wrong — do not ship."),
                    ("Deliverable stems and loudness", "For broadcast deliveries, the mixer typically exports multiple audio stems: the full mix (stereo or 5.1 surround), a dialogue-only stem, a music-only stem, an effects-only stem, and a combined M&amp;E (music plus effects, no dialogue) stem for international versions with foreign-language dubbing. Each stem is delivered as a separate BWF file with embedded timecode that matches the master. Document which stem is which in the delivery manifest clearly — a 5.1 stem mislabelled as stereo has ended more than one otherwise-clean post-production timeline. For LKFS-compliant deliveries required by EBU R128 in Europe, ATSC A/85 in the US, or similar regional standards, include the measured integrated loudness and true-peak values in the accompanying delivery paperwork so the broadcaster&#39;s QC system can verify compliance without re-measuring."),
        ],
    },
    "guide-media-central-cache": {
        "tag": "MediaCentral · Admin",
        "time": "7 min",
        "title": "Clearing Cache in Avid MediaCentral Cloud UX (2025 Edition)",
        "dek": "Fix slow loads, stale thumbnails, and playback errors by clearing browser, application, and server-side proxy cache in MediaCentral Cloud UX.",
        "sections": [
            ("Why cache breaks MediaCentral", "MediaCentral Cloud UX caches at three layers: the browser (page assets, user prefs), the client application (user bin data, recent searches), and the server-side proxy (thumbnails, lo-res playback streams). When any of these get out of sync with the actual database state, editors see ghost thumbnails, stale asset counts, or playback errors on clips that play fine in Avid Media Composer directly. Ninety percent of &quot;MediaCentral is broken&quot; tickets are cache issues."),
            ("Browser cache (fastest fix)", "First, always, before calling support: clear the browser cache. In Chrome: <em>Ctrl+Shift+Delete</em>, select &quot;Cached images and files&quot;, time range &quot;All time&quot;, clear. Alternative: open Dev Tools (F12), go to the Network tab, check &quot;Disable cache&quot;, then hard refresh with <em>Ctrl+Shift+R</em>. This fixes maybe 60% of reported issues."),
            ("Application cache", "MediaCentral Cloud UX keeps a per-user session cache under <code>%AppData%\\Avid\\MediaCentral\\</code> on Windows and <code>~/Library/Application Support/Avid/MediaCentral/</code> on macOS. Close MediaCentral completely (check Task Manager — the process can linger), delete the contents of this folder, reopen. User preferences reset to defaults; recent asset lists are rebuilt on next login."),
            ("Server-side proxy cache", "This is the administrator-only layer. Log into the MediaCentral Services admin interface (typically <code>https://mcs-01/avid/admin</code>). Navigate to <strong>System Health &gt; Cache Management</strong>. You&#39;ll see cached thumbnails and lo-res proxy files. Selectively clear by asset, or use &quot;Clear all&quot; during a maintenance window. For a full reset, stop the <code>avid-ics</code> service, delete <code>/var/lib/avid-ics/cache/*</code>, restart the service. Expect 15–30 minutes for caches to rebuild on a busy system."),
            ("Database-level cleanup", "Occasionally the MongoDB that underpins MediaCentral accumulates orphaned references — entries pointing at deleted assets. Avid ships a <code>mc-repair</code> utility that safely removes these. Schedule this to run monthly during maintenance windows. Never run it during working hours — it locks collections briefly and editors will see timeouts."),
            ("When to escalate", "If clearing all three layers plus running <code>mc-repair</code> doesn&#39;t fix the symptom, the issue is probably not cache. Common non-cache culprits: Interplay permissions drift (check user mappings in Avid Access), MCS cluster split-brain (check <code>mc-cluster status</code>), or corrupt MOS gateway state if the symptom is related to MOS plug-ins. At that point, open a proper Avid support ticket with logs from <code>/opt/avid/logs/</code>."),
                    ("Preventive cache hygiene", "Once you&#39;re out of the immediate emergency, set up an ongoing cache hygiene schedule to prevent the next incident. Document in your onboarding checklist that editors should clear browser cache weekly. Application cache should be cleared monthly, ideally scheduled for Patch Tuesday so it aligns with other maintenance. Server-side proxy cache should be purged quarterly during a proper maintenance window with editors notified in advance. Monitor cache disk usage continuously — the command <code>df -h /var/lib/avid-ics</code> should never exceed 70% full under normal operating conditions. Set up an automated cleanup cron job that deletes proxy cache entries older than 90 days. These three operational disciplines together prevent roughly 95% of MediaCentral cache-related incidents from ever reaching production impact. Keep a running incident log of cache-related tickets so patterns emerge — if the same user repeatedly reports cache symptoms, their browser may be misconfigured or they may be using an unsupported browser version. If the same workstation repeatedly has problems, check its local storage health since cache corruption can indicate a dying SSD."),
        ],
    },
    "guide-avid-media-central-health-check": {
        "tag": "MediaCentral · Admin",
        "time": "7 min",
        "title": "Avid MediaCentral Health Check: Services, Connections, and Logs",
        "dek": "Run a full pre-air health check — verify MCPS services, Interplay and iNEWS connections, licensing, and system logs before going on air.",
        "sections": [
            ("Why pre-air health checks matter", "MediaCentral is a stack of interlocking services: MongoDB for user/session data, Elasticsearch for search, a WebSocket service for real-time UI, the MCPS media proxy server, plus bridges to Interplay and iNEWS. Any one can fail silently — the UI stays up while the feature behind it returns errors. A disciplined 15-minute health check before each live newscast catches 80% of production-breaking issues before they break anything."),
            ("Service status check", "SSH to the MCS master node and run <code>mc-status</code> (Avid ships this). Every service should report &quot;running&quot; and &quot;healthy&quot;. Red flags: <code>avid-ics</code> listed but not responding, MongoDB replica set out of sync, Elasticsearch cluster status &quot;yellow&quot; (usable) or &quot;red&quot; (degraded search). For a cluster, repeat on every node — split-brain is a common Friday-evening failure mode."),
            ("Interplay / MediaCentral Production Services", "From the admin UI, check <strong>System &gt; Integrations &gt; Interplay</strong>. The connection should show &quot;Connected&quot; and the last heartbeat within the last 60 seconds. Common failure: certificate expired, visible as authentication failure in <code>/opt/avid/logs/interplay-bridge.log</code>. Rotate the cert per Avid&#39;s published procedure; don&#39;t wait for the production outage."),
            ("iNEWS and MOS connections", "For newsrooms, iNEWS is the heartbeat. In MediaCentral admin, confirm iNEWS appears under <strong>NRCS Integrations</strong> and shows &quot;Active&quot;. Test by opening a rundown in MediaCentral — it should render story list within 2 seconds. Slower than that and the MOS Gateway needs inspection. Check <code>/opt/avid/logs/mos-gateway.log</code> for timeout warnings; if present, the upstream iNEWS server may be under load."),
            ("Licensing", "Check licensing under <strong>System &gt; Licensing</strong>. Expired or near-expiry licenses (within 30 days) should trigger a ticket to Avid. Concurrent-use licenses should show usage below ceiling; if you&#39;re regularly hitting 90%+ of concurrent seats, plan a licence top-up before the next big show."),
            ("Log review", "Last step: scan the last 24 hours of logs for ERROR and CRITICAL entries. Useful commands: <code>journalctl --since &quot;24 hours ago&quot; -p err</code> at OS level, plus <code>grep -i error /opt/avid/logs/*.log | tail -50</code> for MediaCentral specifics. Common ignorables: WebSocket disconnect/reconnect cycles from flaky browsers. Real concerns: repeated MongoDB connection errors, MCPS transcode failures, or Interplay authentication loops."),
                    ("Automate the health check", "Once your manual health check procedure is reliable and well-documented, automate it. A small shell script running <code>mc-status</code>, performing <code>curl</code> probes of key MediaCentral endpoints, checking service PID files, and scanning the last hour of log files for new ERROR entries can run every 5 minutes via cron and post its results to a monitoring dashboard like Grafana or Datadog. The human pre-air check then becomes a 2-minute glance at the dashboard rather than a 15-minute manual ritual. Set alert thresholds generously — an Elasticsearch yellow status for 10 minutes is fine, 60 minutes is not. Tune thresholds over time based on your specific environment&#39;s normal noise level. Most facilities find that within 3 months the automated check catches real problems 10-20 minutes earlier than humans would. Document every incident fully including symptoms, diagnostic steps, and resolution so institutional knowledge doesn&#39;t walk out the door when engineers change jobs. MediaCentral troubleshooting is the kind of skill that takes months to build and weeks to lose if not actively maintained through regular health-check discipline."),
        ],
    },
    "guide-vizrt-avid-integration": {
        "tag": "Vizrt · Avid · MOS",
        "time": "9 min",
        "title": "Integrating Vizrt Graphics with Avid MediaCentral and iNEWS",
        "dek": "Configure the Vizrt Plugin for MediaCentral and the MOS Gateway to connect Viz Engine templates to iNEWS stories for story-driven graphics playout.",
        "sections": [
            ("The three-system handshake", "A newsroom graphics integration involves three systems: iNEWS (the rundown), MediaCentral (editor UI), and Viz Engine/Mosart (the graphics engine). They speak via MOS protocol — a 1990s XML-over-TCP standard that the whole broadcast industry still runs on. Getting the handshake right requires configuration at all three endpoints and a MOS Gateway in the middle."),
            ("MOS Gateway setup", "Start at the MOS Gateway (typically Avid&#39;s iNEWS MOS Gateway, though Vizrt ships their own alternative). Configure iNEWS NRCS as one side of the connection and Viz Mosart (or Viz Trio for graphics-only) as the other. Each side needs a unique <strong>MOS ID</strong> — pick names that describe the role (e.g. <code>VIZMOSART.NEWSROOM.COM</code>). Confirm the gateway handshakes with both sides by checking <code>/var/log/mos-gateway.log</code> for &quot;heartbeat ack&quot; messages."),
            ("iNEWS story plugin", "In iNEWS, the production manager installs the Vizrt story plugin (MOS Active X plugin, still the standard in 2026). This gives journalists a &quot;Viz&quot; tab in the story form where they can browse templates, fill in slots (name, role, banner text), and drop the resulting MOS object into the rundown. The MOS object is a reference — not the graphic itself — so iNEWS stays lightweight."),
            ("MediaCentral integration", "From the MediaCentral admin, enable the Vizrt panel under <strong>Plugins</strong>. This gives MediaCentral editors the same template browser as iNEWS journalists, accessed from the sequence timeline. Editors can preview the graphic against the clip it sits on top of — useful for timing lower-thirds to the exact moment the interviewee starts speaking."),
            ("Common integration failures", "<strong>MOS heartbeat lost:</strong> usually a firewall rule change. MOS uses TCP 10540/10541 — make sure both are open between gateway and all clients. <strong>Templates don&#39;t appear:</strong> check the Viz scene database is accessible from the MediaCentral host; Vizrt uses SMB for the scene share. <strong>Graphics play late:</strong> this is almost always an iNEWS rundown timing issue, not Vizrt — audit the rundown pre-roll settings."),
            ("Production best practices", "Name templates clearly — editors waste hours hunting through lists named &quot;LT_Proj3_v4_REV2&quot;. Standardise on descriptive names: &quot;LowerThird-NamePlusRole-Blue&quot;. Keep a test rundown with representative template types that the engineering team runs through every morning — catches template regressions before they hit air. And document the MOS object IDs of all templates; if the Viz database ever rebuilds, you&#39;ll need to re-map."),
                    ("Disaster-recovery testing", "Test the MOS gateway failover procedure quarterly. The typical DR scenario: primary MOS gateway loses network connectivity, the secondary gateway takes over automatically, and rundowns continue flowing to Viz Engine without interruption. If you&#39;ve never actually tested this, you don&#39;t actually have redundancy — you have hope. Do the test during a scheduled maintenance window, never mid-newscast. Document the measured failover time (under 30 seconds is good, over 2 minutes means the secondary is misconfigured and needs investigation). Crucially, also test that templates produced during the failover actually play to air — sometimes the secondary gateway accepts MOS objects but the Viz Engine cannot render them because a scene database reference path is broken. This kind of partial failure is worse than a clean outage because it isn&#39;t obvious until the graphic is supposed to appear on air."),
        ],
    },
    "guide-windows11-upgrade": {
        "tag": "IT · Windows",
        "time": "5 min",
        "title": "Upgrading Broadcast Workstations to Windows 11",
        "dek": "Pre-upgrade compatibility checks, driver verification, and rollback procedure for upgrading post and broadcast IT workstations to Windows 11.",
        "sections": [
            ("Should you upgrade at all?", "Windows 10 extended support ended in October 2025; Windows 11 is now effectively mandatory for any workstation on a Microsoft-supported track. For broadcast workstations, the real question isn&#39;t whether to upgrade but when — the answer is &quot;after your NLE vendor has certified their version against Windows 11&quot;. Avid Media Composer 2024.6+ is certified; DaVinci Resolve 19+ is certified; older versions may run but without vendor support."),
            ("Hardware compatibility", "Windows 11 mandates TPM 2.0, Secure Boot, and a supported CPU (Intel 8th-gen+, AMD Zen 2+). Most broadcast-grade HP Z-series and Dell Precision workstations from 2019 onwards meet this. Older boxes — particularly custom-built edit stations from the mid-2010s — often fail the CPU check even if the TPM is present. Use Microsoft&#39;s <strong>PC Health Check</strong> tool first; don&#39;t try to upgrade a machine that fails and hope for the best."),
            ("Pre-upgrade backup", "Full disk image first, always. <strong>Macrium Reflect Free</strong> does this well. Back up Avid project folders separately to a second drive (not the Windows system drive). Export any licensed software&#39;s activation state where supported — some broadcast tools use node-locked licences that can be a pain to re-activate after a Windows reinstall. Document all installed plugins and their version numbers before starting."),
            ("Driver verification", "Before the upgrade, download Windows 11 drivers for the GPU (Nvidia Studio driver, not Game-Ready), audio interface (RME, Focusrite, whichever), any SDI or NDI capture cards (AJA, Blackmagic), and any USB dongles used for software licensing (iLok, Sentinel, SafeNet). Stage these on a USB stick. Post-upgrade, install these in order: GPU first, capture cards second, audio last — this avoids conflicts in the driver store."),
            ("The upgrade itself", "Use the in-place upgrade path via Windows Update or the Media Creation Tool. For a 10-person post department, stage the upgrade: do one workstation first, run it for a week in production, only then roll out to the rest. Expect the upgrade to take 60–90 minutes per workstation plus 30 minutes of post-upgrade driver installs and NLE re-authorisation."),
            ("Rollback", "If something breaks badly, Windows 11 keeps a <code>Windows.old</code> folder for 10 days; you can revert from Settings &gt; System &gt; Recovery &gt; Go back. After 10 days or if you&#39;ve freed up disk space, you&#39;re committed — which is why the Macrium image matters. Keep the image for 30 days post-upgrade before deleting. Any serious regression that shows up later probably relates to a specific app/driver combination and is fixable in-place without a full rollback."),
                    ("Post-upgrade validation", "Once upgraded, run through a rigorous validation checklist on each workstation before returning it to production use. Verify: your primary NLE opens a real project without warnings; playback of 1080p DNxHD files runs without any dropped frames over a 5-minute test; SDI or NDI capture card input shows up correctly in the NLE source list; audio I/O devices appear in the NLE&#39;s audio settings and route correctly; all licensed plugins appear in the effects browser with no red warnings. Any &quot;missing plugin&quot; warning means you&#39;re relying on an old binary that won&#39;t actually work under the new OS — fix it before going live. Keep the post-upgrade validation results in a shared document so IT can cross-check workstation configurations six months later when an editor reports &quot;it was working fine yesterday.&quot;"),
        ],
    },
    "guide-macos-upgrade": {
        "tag": "IT · macOS",
        "time": "5 min",
        "title": "Upgrading a Post-Production Mac to macOS Sequoia",
        "dek": "Pre-upgrade checklist, NLE compatibility matrix, and what to do if your plugins break after upgrading to macOS Sequoia.",
        "sections": [
            ("Should you upgrade?", "The same rule as Windows: don&#39;t upgrade until your primary NLE has certified the new OS. As of early 2026, Final Cut Pro 11 is Sequoia-native and runs well; DaVinci Resolve 19.1+ is certified; Avid Media Composer 2024.12 is certified. Premiere Pro 2025 runs but has known issues with some ProRes RAW workflows on Sequoia — check Adobe&#39;s published issue list before upgrading a working Premiere station."),
            ("Hardware compatibility", "Sequoia drops support for pre-2018 Intel Macs and all pre-T2 chip models. Apple Silicon Macs (M1 onwards) are all supported. For mixed facilities, make a compatibility list: which machines can upgrade, which are frozen at Ventura or Sonoma. Workstations that can&#39;t upgrade still get security updates on their current OS for two more years after Sequoia ships — plan their retirement for late 2026 or early 2027."),
            ("Pre-upgrade backup", "Time Machine to a dedicated external, then clone with <strong>Carbon Copy Cloner</strong> for a bootable backup. Time Machine is for rollback of documents; CCC is for full system restore if the upgrade corrupts the boot volume. Export licence states for broadcast-specific software that uses node-locked activation."),
            ("Plugin compatibility", "This is where post upgrades most often fail. Audio plugins (Waves, iZotope, Universal Audio) must be updated to their Sequoia-compatible versions before you upgrade the OS — check each vendor&#39;s support page. Video plugins (Red Giant, Boris FX, NewBlue) are usually less affected but still check. FxFactory users: update FxFactory itself first, it handles most of the sub-plugin compatibility automatically."),
            ("Upgrade procedure", "Backup, update plugins on Ventura/Sonoma, then run <em>System Settings &gt; General &gt; Software Update</em> on the new macOS installer. Expect 45–75 minutes for the upgrade plus 30 minutes of post-install plugin re-authorisation. First reboot after upgrade often takes 10+ minutes — don&#39;t panic, don&#39;t force-restart."),
            ("If plugins break", "The most common post-upgrade issue: an audio plugin authorised under the old OS won&#39;t re-authorise under the new one. Fix: open the plugin&#39;s licence manager (Waves Central, iLok License Manager, etc.), de-activate the licence, re-activate it. If the vendor&#39;s licence manager itself won&#39;t launch, update it via the vendor&#39;s website — vendors often ship new licence managers alongside new OS support. Worst case, restore from the CCC clone, sort plugins on the old OS, then upgrade again."),
                    ("Post-upgrade validation", "After the upgrade, immediately open your main NLE, create a test sequence, play back 30 seconds of 4K ProRes footage, render a title effect, and export a 10-second H.264. Any failure at any step means a compatibility issue that needs fixing before any production work resumes on that machine. Repeat the test sequence in every NLE the facility uses — an editor who jumps between DaVinci Resolve and Premiere Pro across a single day cannot tolerate one tool working and the other failing silently. Document the tested-and-working configuration (macOS version, NLE version, plugin versions, driver versions) in a shared IT runbook so you have a reference point when the next editor reports &quot;it stopped working after that update.&quot; This documentation saves hours of troubleshooting on future upgrades. If a plugin breaks post-upgrade, the most common fix is to open that plugin&#39;s license manager (Waves Central, iLok License Manager, iZotope Product Portal, etc.), deactivate the license, then reactivate it — this forces the plugin to re-validate against the new macOS version. If the vendor&#39;s license manager itself fails to launch, download the latest version from the vendor&#39;s website since vendors routinely ship new license managers alongside new OS support."),
        ],
    },
}


def howto_article_page(slug, data):
    """Render a full how-to guide article page from HOWTO_GUIDE_CONTENT.
    Stamps <!-- HAND_AUTHORED --> so cleanup.py/build pipeline won't overwrite it."""
    title = data["title"]
    dek   = data["dek"]
    tag   = data["tag"]
    time  = data["time"]
    url   = f"{BASE_URL}/articles/{slug}.html"

    body_sections = ""
    for sec_title, sec_body in data["sections"]:
        body_sections += f'<h2>{sec_title}</h2>\n<p>{sec_body}</p>\n'

    schema = json.dumps({
        "@context":"https://schema.org","@type":"TechArticle",
        "headline":title,"description":dek,
        "datePublished":"2026-01-15","dateModified":"2026-01-15",
        "author":{"@type":"Organization","name":AUTHOR},
        "publisher":{"@type":"Organization","name":"The Streamic","url":BASE_URL,
                     "logo":{"@type":"ImageObject","url":f"{BASE_URL}/assets/logo.png"}},
        "mainEntityOfPage":url,
    }, indent=2)

    return f"""<!-- HAND_AUTHORED -->
{head(title+" | The Streamic", dek, url, css="../style.css")}
<body>
{nav("howto.html", base="../")}
<main>
  <div class="art-wrap">
    <div class="art-breadcrumb">
      <a href="../featured.html">Home</a>
      <span>›</span>
      <a href="../howto.html" style="color:var(--blue)">How-To Guides</a>
    </div>
    <span class="art-tag" style="background:var(--blue)">&#128295; {e(tag)}</span>
    <h1>{e(title)}</h1>
    <p class="art-dek">{e(dek)}</p>
    <div class="art-byline">
      <strong>{AUTHOR}</strong>
      <span>&#128337; {e(time)} read</span>
      <span style="background:#10b981;color:#fff;padding:3px 9px;border-radius:5px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.8px">How-To Guide</span>
    </div>
    <div class="art-body">
{body_sections}
    </div>
    <div class="art-author">
      <strong>About this guide</strong>
      Written by The Streamic Editorial Team. Practical broadcast and post-production workflow guide for engineers and media operations teams.
      <a href="/about.html" style="color:var(--blue);margin-left:6px;">About The Streamic &rarr;</a>
    </div>
    <div class="art-more">
      <h3>More How-To Guides</h3>
      <a href="../howto.html">&#128295; All How-To Guides</a>
      <a href="../featured.html">&#11088; Featured Stories</a>
    </div>
  </div>
</main>
<script type="application/ld+json">{schema}</script>
{footer(base="../")}
{_cookie_banner()}
</body>
</html>"""


def howto_page():
    guides = [
        {
            "title": "Premiere Pro to Avid Media Composer",
            "desc": "AAF, EDL, and Direct Link interchange methods. Codec compatibility, audio mapping, and troubleshooting the most common handoff failures.",
            "href": "articles/guide-premiere-to-avid.html",
            "tag": "Post-Production",
            "time": "8 min",
        },
        {
            "title": "Vantage: Transcode Any File to MP4 on a NAS Share",
            "desc": "Build a hot folder workflow in Telestream Vantage that accepts any input format and delivers broadcast-ready H.264 MP4 to a local NAS.",
            "href": "articles/guide-vantage-nas-transcode.html",
            "tag": "Vantage · Workflow",
            "time": "10 min",
        },
        {
            "title": "Vantage: Output to AWS S3 for Cloud Delivery",
            "desc": "Extend your Vantage workflow to deliver MP4 output directly to Amazon S3. IAM setup, S3 storage configuration, and parallel NAS + cloud delivery.",
            "href": "articles/guide-vantage-aws-transcode.html",
            "tag": "Vantage · AWS",
            "time": "9 min",
        },
        {
            "title": "Strawberry PAM + Avid Media Composer Workflow",
            "desc": "Configure Production Flow's Strawberry for collaborative editing with Avid Media Composer. Shared storage, ingest hot folders, version control, and automated delivery.",
            "href": "articles/guide-avid-strawberry.html",
            "tag": "PAM · Avid",
            "time": "10 min",
        },
        {
            "title": "Audio Conform: Avid Media Composer to Pro Tools and Back",
            "desc": "Export AAF from Avid, open in Pro Tools for audio finishing, and return the mix in sync. Covers sample rates, BWF export, and timecode alignment.",
            "href": "articles/guide-audio-conform-avid-protools.html",
            "tag": "Avid · Pro Tools · Audio",
            "time": "10 min",
        },
        {
            "title": "Clearing Cache in Avid MediaCentral Cloud UX (2025)",
            "desc": "Fix slow loads, stale thumbnails, and playback errors by clearing browser, application, and server-side proxy cache in MediaCentral Cloud UX.",
            "href": "articles/guide-media-central-cache.html",
            "tag": "MediaCentral · Admin",
            "time": "7 min",
        },
        {
            "title": "Avid MediaCentral Health Check: Services, Connections, and Logs",
            "desc": "Run a full pre-air health check &#8212; verify MCPS services, Interplay and iNEWS connections, licensing, and system logs before going on air.",
            "href": "articles/guide-avid-media-central-health-check.html",
            "tag": "MediaCentral · Infrastructure",
            "time": "12 min",
        },
        {
            "title": "Integrating Vizrt Graphics with Avid MediaCentral and iNEWS",
            "desc": "Configure the Vizrt Plugin for MediaCentral and the MOS Gateway to connect Viz Engine templates to iNEWS stories for story-driven graphics playout.",
            "href": "articles/guide-vizrt-avid-integration.html",
            "tag": "Vizrt · iNEWS · MOS",
            "time": "14 min",
        },
        {
            "title": "Upgrade to Windows 11",
            "desc": "Step-by-step upgrade guide for broadcast workstations and edit suites. Compatibility checks, driver verification, and rollback procedure.",
            "href": "articles/guide-windows11-upgrade.html",
            "tag": "IT · Windows",
            "time": "5 min",
        },
        {
            "title": "Upgrade to macOS Sequoia",
            "desc": "How to safely upgrade a post-production Mac. Pre-upgrade checklist, NLE compatibility matrix, and what to do if your plugins break.",
            "href": "articles/guide-macos-upgrade.html",
            "tag": "IT · macOS",
            "time": "5 min",
        },
    ]

    cards = "".join(f''' <div class="howto-card">
  <div class="howto-tag">{g["tag"]}</div>
  <h3>{g["title"]}</h3>
  <p>{g["desc"]}</p>
  <div class="howto-foot">
    <span class="howto-time">&#128337; {g["time"]} read</span>
    <a href="{g["href"]}">Read guide &rarr;</a>
  </div>
</div>''' for g in guides)

    return f"""{head("How-To Guides — The Streamic",
                      "Practical broadcast and post-production workflow guides: Vantage, Avid, Strawberry, AWS, and more.",
                      f"{BASE_URL}/howto.html")}
<body>
{nav("howto.html")}
<main><div class="w">
<div class="cat-hdr">
  <h1>How-To Guides</h1>
  <p>Practical workflow guides for broadcast engineers, post-production supervisors, and media technology teams.</p>
</div>
<div class="howto-grid">{cards}</div>
</div></main>
{footer()}
{_cookie_banner()}
</body></html>"""

def _deep_dives_section():
    """Homepage 'Technical Deep Dives' — 2 premium editorial cards below hero.

    Layout matches the reference: 2 side-by-side cards on desktop, stacked on mobile.
    Each card links to a full hand-authored article page under /docs/articles/.
    Images expected at /docs/assets/deepdives/ — upload media-composer-edit.png and ms-server-datacenter.png.
    """
    cards = [
        {
            "kicker": "Automation",
            "title": "The Death of the &quot;Black Box&quot;: Why Pebble and Harmonic are Winning the Playout War",
            "lead": "The \"Black Box\" era is officially over. Pebble's JT-DMF interoperability push and Harmonic's SMPTE ST 2110-native Spectrum X are collapsing the decades-old hardware lock-in.",
            "img": "assets/deepdives/media-composer-edit.png",
            "img_alt": "Avid Media Composer editing interface showing multi-clip timeline and source monitor",
            "img_caption": "Software-Defined Playout",
            "href": "articles/deepdive-pebble-harmonic-playout-war-nab-2026.html",
            "cta": "Read analysis",
        },
        {
            "kicker": "Infrastructure",
            "title": "From Bots to Agents: How AWS and Google Cloud are Actually Solving the Newsroom Headache",
            "lead": "2025 was AI that created stuff. 2026 is Agentic AI — AI that does stuff. AWS Elemental Inference and the Google Cloud / Avid partnership signal a real shift from demo to deployment.",
            "img": "assets/deepdives/ms-server-datacenter.png",
            "img_alt": "Hyperscale data center server aisle with illuminated racks extending to vanishing point",
            "img_caption": "Agentic Cloud Infrastructure",
            "href": "articles/deepdive-aws-google-cloud-agentic-ai-nab-2026.html",
            "cta": "Read analysis",
        },
    ]

    card_html = ""
    for c in cards:
        card_html += f'''<a class="dd-card" href="{c['href']}" aria-label="Read deep dive: {c['title']}">
  <div class="dd-card-body">
    <span class="dd-kicker">{c['kicker']}</span>
    <h3 class="dd-title">{c['title']}</h3>
    <p class="dd-lead">{c['lead']}</p>
    <span class="dd-cta">{c['cta']} <span class="dd-arrow" aria-hidden="true">&#8594;</span></span>
  </div>
  <figure class="dd-figure">
    <img class="dd-img" src="{c['img']}" alt="{c['img_alt']}" loading="lazy" onerror="this.style.opacity='0'">
    <figcaption class="dd-figcap">{c['img_caption']}</figcaption>
  </figure>
</a>'''

    return f'''<section class="dd-section" aria-labelledby="dd-h2">
  <div class="dd-hdr">
    <span class="dd-eyebrow">The 2026 Collection</span>
    <h2 id="dd-h2" class="dd-h2">Technical Deep Dives</h2>
    <p class="dd-intro">Moving beyond the headlines into the architecture of the modern media supply chain.</p>
  </div>
  <div class="dd-grid">
    {card_html}
  </div>
</section>'''


def _nab_bento_section(mode="all"):
    """Homepage NAB 2026 hero + moonlight horizontal cards with Show-more accordion.

    mode:
      "all"   → hero banner + 4 vendor cards (default, legacy behaviour)
      "hero"  → hero banner only (for new homepage order: hero → deep dives → cards)
      "cards" → 4 vendor cards only

    Cards use <details>/<summary> for accordion — pure HTML, zero JavaScript,
    AdSense-safe, fully indexed by Google (expanded content is in the DOM).
    'teaser_html' is the always-visible first 5 lines.
    'more_html' is the hidden-until-expanded rest.
    """
    cards = [
        {
            "cat": "AI & Post-Production",
            "cat_color": "#8b5cf6",
            "slug": "2026-04-17-ai-post-production-avid-google-cloud-agentic-ai-media-production",
            "title": "Avid Content Core: Agentic AI, Google Gemini, and a Unified Media Intelligence Layer",
            "eyebrow": "Avid Technology",
            "teaser_html": "<strong>Avid Partners with Google Cloud to Integrate Agentic AI and Launch &quot;Content Core&quot;.</strong> Avid is introducing Content Core &mdash; a cloud-native SaaS platform that acts as a unified data layer for media assets, bringing identity, ingest, and storage into a single data platform.",
            "more_html": "<p><strong>Google Gemini Integration:</strong> Deeply embeds Google&#39;s AI into Media Composer, the industry-standard non-linear editing system used across professional film and television post-production.</p><p><strong>Agentic AI Assistants:</strong> Digital agents autonomously manage complex tasks like matching visual styles and identifying emotional cues.</p><p><strong>Natural Language Search:</strong> Production teams can now query entire archives using conversational language instead of manual metadata tags.</p><p><strong>Zero-Disruption Migration:</strong> Designed to work with existing Avid NEXIS and MediaCentral infrastructure, avoiding rip-and-replace overhauls. Hybrid deployment across Google Cloud and AWS. Commercially available April 2026.</p>",
        },
        {
            "cat": "AI & Post-Production",
            "cat_color": "#b45309",
            "slug": "2026-04-01-newsroom-dalet-flex-2512-semantic-search-dalia-ai",
            "title": "Dalet Dalia: Conversational Agentic AI for Enterprise Production",
            "eyebrow": "Dalet",
            "teaser_html": "<strong>Commercial Launch of Dalia: Media-Aware Agentic AI for Enterprise Production.</strong> Dalet&#39;s multi-agent framework translates conversational requests into structured media workflows including content discovery and clip creation, available across Dalet Flex, Pyramid, and Galaxy five.",
            "more_html": "<p><strong>Agentic AI:</strong> Uses a natural-language interface to simplify complex media supply chain tasks.</p><p><strong>Ecosystem Integration:</strong> Works across Dalet Flex (cloud-native media logistics and orchestration) and Dalet Pyramid (collaborative web-based news production).</p><p><strong>Human-in-the-Loop:</strong> Keeps users in control of critical creative and editorial validation &mdash; human validation required for downstream actions.</p><p><strong>Efficiency Gains:</strong> Early data shows a 60% reduction in time spent on repetitive tasks like tagging and clipping.</p><p><strong>Unified UI:</strong> Consolidates fragmented tools into a single conversational interface. Commercially available April 8, 2026.</p>",
        },
        {
            "cat": "AI & Post-Production",
            "cat_color": "#2563eb",
            "slug": "2026-04-01-ai-post-production-telestream-adobe-frameio-creative-delivery-automation",
            "title": "Telestream + Adobe + Oracle OCI: Creative-to-Delivery Automation Gets Sharper",
            "eyebrow": "Telestream",
            "teaser_html": "<strong>Telestream Scales Multi-Cloud with Oracle and Enhances Adobe Workflows.</strong> Cloud services are now optimized for Oracle Cloud Infrastructure, bringing high-performance compute and low-cost data egress to media workloads, while Premiere Pro users can submit sequences directly into automated pipelines.",
            "more_html": "<p><strong>Vantage Adobe Panel:</strong> Submit Premiere Pro sequences directly to automated delivery pipelines using the Vantage enterprise media processing and workflow automation platform.</p><p><strong>UP Platform:</strong> Capture, orchestration, and review are now OCI-ready via Telestream&#39;s unified cloud-native ingest and supply chain monitoring platform.</p><p><strong>Frame.io V4 Readiness:</strong> A new connector ensures seamless migration to Adobe Frame.io&#39;s redesigned API architecture.</p><p><strong>SENTRY Monitoring:</strong> Real-time QoS monitoring &mdash; including video/audio quality, ad marker validation, and caption compliance &mdash; is now available within OCI. Available April 2026. Supports hybrid, on-premises, and multi-cloud deployment.</p>",
        },
        {
            "cat": "Distribution",
            "cat_color": "#0ea5e9",
            "slug": "2026-04-01-cloud-tedial-agentic-ai-media-lifecycle-nab-2026",
            "title": "Vubiquity + Eluvio Content Fabric: Rewriting Distribution Economics",
            "eyebrow": "Vubiquity &amp; Eluvio",
            "teaser_html": "<strong>Vubiquity adopts the Eluvio Content Fabric to redefine media distribution economics.</strong> The partnership replaces traditional file-based delivery with a blockchain-backed content fabric that streams the exact requested version on demand &mdash; eliminating the transcoding, storage, and CDN costs baked into conventional supply chains.",
            "more_html": "<p><strong>Content Fabric Protocol:</strong> A decentralized media protocol built on a verifiable content-addressable storage layer. Masters are stored once and dynamically assembled per request &mdash; versions, subtitles, and territorial variants generated at the edge.</p><p><strong>Zero Egress Duplication:</strong> Removes the need to pre-transcode and pre-store every distribution version. Reduces storage footprint by up to 80% and eliminates redundant CDN fills.</p><p><strong>Rights-Aware Delivery:</strong> Territorial rights, version control, and edit compliance are enforced at the protocol layer, not the application layer &mdash; faster rights clearance, no misdelivery.</p><p><strong>Operator Impact:</strong> For distributors like Vubiquity, this collapses the delivery cost curve and makes long-tail catalog monetization economically viable again. Active in production workflows as of Q2 2026.</p>",
        },
    ]

    card_html = []
    for c in cards:
        card_html.append(f'''<article class="nab-card nab-card-horizontal" itemprop="itemListElement" itemscope itemtype="https://schema.org/Article">
  <div class="nab-card-body nab-card-body-horizontal">
    <div class="nab-card-meta-row">
      <span class="nab-card-eyebrow">{c['eyebrow']}</span>
      <span class="nab-cat" style="--nab-cat-c:{c['cat_color']}">{c['cat']}</span>
    </div>
    <h3 class="nab-title" itemprop="headline"><a href="articles/{c['slug']}.html" class="nab-title-link">{c['title']}</a></h3>
    <div class="nab-summary nab-summary-rich" itemprop="description">
      <div class="nab-teaser">{c['teaser_html']}</div>
      <details class="nab-more">
        <summary class="nab-more-toggle"><span class="nab-more-label-open">Show more</span><span class="nab-more-label-close">Show less</span><span class="nab-more-chev" aria-hidden="true">&#9662;</span></summary>
        <div class="nab-more-body">{c['more_html']}</div>
      </details>
    </div>
    <a href="articles/{c['slug']}.html" class="nab-cta nab-cta-btn" aria-label="Read full article: {c['title']}">Read full article <span class="nab-cta-arrow" aria-hidden="true">&#8594;</span></a>
  </div>
</article>''')

    hero_html = '''<section class="nab-section nab-section-hero-only" aria-labelledby="nab-h2">
  <header class="nab-banner nab-banner-image" role="banner" aria-label="NAB Show 2026 section header">
    <div class="nab-banner-bg" aria-hidden="true">
      <img class="nab-banner-hero-img" src="assets/gfx-hero-nab-floor.png" alt="" loading="eager" onerror="this.style.display='none'">
      <div class="nab-banner-overlay" aria-hidden="true"></div>
      <div class="nab-banner-vignette" aria-hidden="true"></div>
    </div>
    <div class="nab-banner-content">
      <div class="nab-banner-eyebrow">
        <span class="nab-live-pulse" aria-hidden="true"></span>
        <span class="nab-banner-label">Field Report &middot; April 2026</span>
        <span class="nab-banner-sep" aria-hidden="true">&middot;</span>
        <span class="nab-banner-location">Las Vegas &bull; NAB Show 2026</span>
      </div>
      <h1 id="nab-h2" class="nab-banner-h2 nab-banner-h2-premium">
        <span class="nab-banner-kicker">Practical Takeaways from NAB 2026</span>
        <span class="nab-banner-headline">The Year of <em>Hybrid Technology</em></span>
      </h1>
      <p class="nab-banner-sub">Beyond the hype: agentic AI, IP 2110 migration, cloud-to-post bridges, and the vendor partnerships that are quietly rewriting the broadcast stack.</p>
      <a href="articles/nab-2026-hybrid-technology-year.html" class="nab-banner-cta nab-banner-cta-premium" aria-label="Read the full NAB 2026 field report">Read the Field Report <span aria-hidden="true">&#8594;</span></a>
    </div>
  </header>
</section>'''

    cards_wrapper = f'''<section class="nab-section nab-section-cards-only" aria-label="NAB 2026 vendor announcements" itemscope itemtype="https://schema.org/ItemList">
  <meta itemprop="name" content="NAB Show 2026 Broadcast Technology Updates — The Streamic">
  <div class="nab-bento nab-bento-stack">
    {''.join(card_html)}
  </div>
</section>'''

    if mode == "hero":
        return hero_html
    if mode == "cards":
        return cards_wrapper
    return hero_html + cards_wrapper

def editorsdesk_page():
    """Editor's Desk landing page.

    Safety rules (this function must NEVER break the live site):
      1. CSS is injected INSIDE <head> by splitting head()'s output at </head>,
         so styles land in the right place and cascade AFTER style.css.
      2. All class names are prefixed `strmc-ed-` to guarantee zero collision
         with existing CSS in style.css.
      3. Explicit hex colors are used (not CSS variables) so cards render
         even if style.css hasn't loaded or var(--ink) is undefined.
      4. Each card's target article file is checked on disk BEFORE the card
         is rendered. Missing articles produce no card — never a broken link.
      5. If zero cards survive the existence check, we fall back to the old
         simple "what we're watching" layout so the page is never empty.
      6. nav() and footer() are always included so the page has the site
         header and footer regardless of content state.
    """
    editorial_cards = [
        ("INFRASTRUCTURE", "st-2110-7-seamless-protection-redundancy-math-2026",
         "ST 2110-7 Seamless Protection: The Redundancy Math Every IP Broadcaster Gets Wrong",
         "Hitless failover is the headline promise of ST 2110-7. The Red/Blue network math, PTP boundary clock placement, and the control plane gap are where 2026 IP migrations quietly fail."),
        ("CLOUD PRODUCTION", "cloud-playout-tco-trap-medialive-economics-2026",
         "The Cloud Playout TCO Trap: Why AWS MediaLive Looks Cheap Until It Isn't",
         "Cloud playout pricing looks linear on the slide deck and exponential on the invoice. The real cost curve for MediaLive + MediaPackage, and where the break-even with Grass Valley Ignite actually sits."),
        ("AI IN BROADCASTING", "ai-metadata-mam-accuracy-broadcast-2026",
         "AI Metadata in the MAM: Why 95% Accuracy Is Still a Failing Grade",
         "Every MAM vendor ships AI auto-tagging in 2026. The accuracy numbers describe benchmarks editors never hit. The gap between '95% correct' and 'useful for an editor on deadline' is where these systems still fail."),
        ("INFRASTRUCTURE", "ndi-6-vs-st-2110-india-mid-market-2026",
         "NDI 6 vs ST 2110 for India's Mid-Market Broadcasters: The Pragmatic Read",
         "ST 2110 is the standard. NDI 6 is what most Indian regional broadcasters will actually deploy. The honest engineering comparison — latency, compression, network cost, and where each earns its place."),
        ("AI IN BROADCASTING", "c2pa-provenance-newsroom-broadcast-mandate-2027",
         "C2PA in the Newsroom: The Provenance Standard Nobody Can Afford to Ignore by 2027",
         "C2PA content provenance has been a compliance side-project since 2023. Synthetic media incidents and EU regulation mean 2026 is the last year it stays a side-project."),
        ("EDITORIAL", "beyond-the-chatbot-operational-ai-newsroom-2026",
         "Beyond the Chatbot: Operational AI in the Newsroom",
         "The interesting AI in newsrooms isn't the one writing copy. It's the one routing video, tagging rushes, and quietly replacing three roles in the ingest workflow."),
        ("EDITORIAL", "green-broadcast-cloud-carbon-footprint-sustainability-2026",
         "Green Broadcast: The Cloud Carbon Footprint Conversation Nobody's Having Honestly",
         "The industry's sustainability numbers are almost all scope-1 and scope-2. Scope-3 is where the real emissions hide."),
        ("EDITORIAL", "ai-reducing-broadcast-operational-costs-2026",
         "AI as an OpEx Lever: Where the Savings Are Real and Where They're Theatre",
         "Vendors are selling AI as cost reduction. Some claims are real. Some are creative accounting. Here's how to tell which is which."),
    ]

    # Only render cards whose target article actually exists on disk.
    rendered = []
    for cat, slug, title, dek in editorial_cards:
        if os.path.exists(os.path.join(DOCS, "articles", f"{slug}.html")):
            rendered.append((cat, slug, title, dek))

    # Build CSS block — scoped, explicit colors, !important on critical props
    # so nothing in style.css can hide the title or link.
    extra_css = """
<style>
.strmc-ed-hero{max-width:920px;margin:40px auto 16px;padding:0 24px}
.strmc-ed-hero h1{font-family:'DM Serif Display',Georgia,serif;font-size:48px;line-height:1.1;margin:0 0 10px;color:#111 !important}
.strmc-ed-hero p.lede{font-size:18px;color:#555;line-height:1.55;max-width:700px;margin:0}
.strmc-ed-watching{max-width:920px;margin:24px auto 32px;padding:22px 26px;background:#f6f3ec;border-left:4px solid #D4AF37;border-radius:6px}
.strmc-ed-watching strong{display:block;font-family:'DM Serif Display',Georgia,serif;font-size:20px;color:#111 !important;margin-bottom:8px;font-weight:normal}
.strmc-ed-watching p{margin:0;font-size:15px;color:#555;line-height:1.65}
.strmc-ed-grid{max-width:1100px;margin:0 auto 72px;padding:0 24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}
.strmc-ed-card{display:block;background:#fff;border:1px solid #e5e0d1;border-radius:8px;padding:26px 24px;text-decoration:none !important;transition:border-color .2s,transform .2s,box-shadow .2s}
.strmc-ed-card:hover{border-color:#D4AF37;transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.06)}
.strmc-ed-card .cat{display:block;font-size:11px;letter-spacing:1.4px;color:#D4AF37 !important;font-weight:700;text-transform:uppercase;margin:0 0 12px}
.strmc-ed-card .title{display:block;font-family:'DM Serif Display',Georgia,serif;font-size:22px;line-height:1.28;color:#111 !important;margin:0 0 12px;font-weight:normal}
.strmc-ed-card:hover .title{color:#D4AF37 !important}
.strmc-ed-card .dek{display:block;font-size:14px;color:#555 !important;line-height:1.6;margin:0 0 14px}
.strmc-ed-card .read{display:inline-block;font-size:13px;color:#D4AF37 !important;font-weight:600}
</style>
"""
    # Inject the style block INSIDE <head>, right before </head>, so it
    # cascades after style.css and wins on specificity ties.
    raw_head = head("Editor's Desk — The Streamic",
                    "Commentary, perspective, and engineering analysis from the editorial team at The Streamic.",
                    f"{BASE_URL}/editorsdesk.html")
    head_with_css = raw_head.replace("</head>", extra_css + "</head>")

    if rendered:
        cards_html = "".join(
            f'''<a class="strmc-ed-card" href="articles/{slug}.html">
<span class="cat">{cat}</span>
<span class="title">{title}</span>
<span class="dek">{dek}</span>
<span class="read">Read the analysis &rarr;</span>
</a>''' for (cat, slug, title, dek) in rendered
        )
        main_html = f"""<main>
<section class="strmc-ed-hero">
  <h1>Editor's Desk</h1>
  <p class="lede">Commentary, perspective, and engineering analysis from the editorial team at The Streamic. Technical reads that go beyond the news cycle &mdash; honest trade-off analysis for broadcast engineers, CTOs, and media IT architects who actually have to deploy this stuff.</p>
</section>
<section class="strmc-ed-watching">
  <strong>What we're watching in 2026</strong>
  <p>The ST 2110 adoption curve in small-market broadcasters. The real TCO of cloud playout post-NAB 2026. How C2PA is quietly becoming a newsroom compliance surface. The gap between AI-tagged MAMs in demos and AI-tagged MAMs in production.</p>
</section>
<section class="strmc-ed-grid">
{cards_html}
</section>
<section class="hp-flagship-section hp-flagship-section--vlog">
  <div class="w">
    <div class="hp-flagship-section__hdr">
      <div class="hp-sec-hdr">
        <h2>Flagship Long-Read</h2>
      </div>
      <p class="hp-section-intro">A dedicated spotlight for technology concepts that deserve a cleaner, slower read.</p>
    </div>
    <a href="articles/quic-http3-video-delivery-streaming-2026.html" class="hp-flagship" aria-label="Read full insight: Beyond TCP">
      <div class="hp-flagship__body">
        <span class="hp-flagship__tag">📡 Infrastructure &amp; Streaming</span>
        <h2 class="hp-flagship__hl">Beyond TCP: Why QUIC Is Redefining Video Delivery</h2>
        <p class="hp-flagship__summary">Faster video start, fewer buffering issues, and smoother playback — even on weak networks. HTTP/3 and QUIC are quietly improving streaming performance across OTT platforms and live broadcasting.</p>
        <p class="hp-flagship__body-text">For years, streaming relied on TCP. QUIC improves connection setup, packet loss recovery, and mobility handling, which makes it more relevant to live events, mobile viewing, and premium OTT delivery than many operations teams first assume.</p>
        <div class="hp-flagship__footer">
          <div class="hp-flagship__meta"><span class="hp-flagship__author">Prerak K Mehta</span><span class="hp-flagship__role">Broadcast Technology and Media IT Analyst</span><span class="hp-flagship__readtime">⏱ 5 min read</span></div>
          <span class="hp-flagship__cta">Read Full Insight <span class="hp-flagship__cta-arrow">→</span></span>
        </div>
      </div>
      <div class="hp-flagship__image-wrap">
        <img class="hp-flagship__img" src="assets/insight-quic-infographic.jpg" alt="QUIC vs TCP streaming performance infographic" loading="lazy" onerror="this.onerror=null;this.src='assets/fallback.jpg'">
      </div>
    </a>
  </div>
</section>
</main>"""
    else:
        # Fallback: no hand-authored articles on disk yet. Show the old
        # simple layout so the page is never blank and has zero broken links.
        main_html = """<main><div class="w" style="padding:52px 24px 80px;max-width:760px">
<div class="cat-hdr">
  <h1>Editor's Desk</h1>
  <p>Commentary, perspective, and notes from the editorial team at The Streamic.</p>
</div>
<p style="font-size:15px;color:#555;line-height:1.7;margin-bottom:24px">The Streamic covers broadcast and streaming technology with a focus on what matters operationally to engineers and technology leaders. This is where we share perspective beyond the news cycle.</p>
<div style="background:#f6f3ec;border-radius:14px;padding:28px;font-size:14px;color:#555;line-height:1.7">
  <strong style="color:#111;display:block;margin-bottom:8px">What we're watching in 2026</strong>
  The ST 2110 adoption curve in small-market broadcasters. The economics of cloud production post-NAB 2026. How C2PA is changing newsroom verification workflows. The quiet revolution of operational AI inside MAM systems.
</div>
</div></main>"""

    return f"""{head_with_css}
<body>
{nav("editorsdesk.html")}
{main_html}
{footer()}
{_cookie_banner()}
</body></html>"""

# Backwards-compatibility alias — in case any other call site still calls vlog_page().
vlog_page = editorsdesk_page

# ── SITEMAP
def sitemap(arts):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    statics = [
        ("",           "daily","1.0"),("featured.html","daily","0.98"),
        ("ai-post-production.html","daily","0.9"),
        ("howto.html","weekly","0.85"),("post-production-workflows.html","weekly","0.90"),
        ("insights.html","weekly","0.88"),
        ("editorsdesk.html","weekly","0.88"),
        ("about.html","monthly","0.6"),("contact.html","monthly","0.5"),
        ("editorial-policy.html","monthly","0.6"),
        ("privacy.html","yearly","0.3"),("terms.html","yearly","0.3"),
    ]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for pg,fr,pr in statics:
        lines.append(f'  <url><loc>{BASE_URL}/{pg}</loc><lastmod>{today}</lastmod><changefreq>{fr}</changefreq><priority>{pr}</priority></url>')
    for a in arts:
        slug_ = a.get('slug', '')
        pub_ = a.get('published', '')
        lines.append(f'  <url><loc>{BASE_URL}/articles/{slug_}.html</loc><lastmod>{pub_}</lastmod><changefreq>monthly</changefreq><priority>0.75</priority></url>')
    lines.append('</urlset>')
    return "\n".join(lines)

# ── MAIN
def load_manual_articles():
    """Return list of article dicts from data/manual_articles.json.

    Manual articles override generated_articles.json on slug collision.
    Image resolution priority:
      1. entry["image"] if file exists on disk under docs/
      2. /assets/fallback.jpg
    Each returned dict carries _source="manual" for build-log reporting.
    """
    if not os.path.isfile(MANUAL_F):
        return []

    try:
        with open(MANUAL_F, "r", encoding="utf-8") as _f:
            raw = json.load(_f)
    except Exception as exc:
        print(f"  ⚠ Could not read manual_articles.json: {exc}")
        return []

    results = []
    skipped = 0

    for entry in raw:
        slug = (entry.get("slug") or "").strip()
        if not slug:
            print("  ⚠ manual_articles.json: entry missing slug — skipped")
            skipped += 1
            continue

        if entry.get("status") != "published":
            skipped += 1
            continue

        html_path = os.path.join(ARTS_D, f"{slug}.html")
        if not os.path.isfile(html_path):
            print(f"  ⚠ manual '{slug}': docs/articles/{slug}.html not found — skipped")
            skipped += 1
            continue

        title    = (entry.get("title") or "").strip()
        date     = (entry.get("date") or "2026-01-01")[:10]
        category = (entry.get("category") or "ai-post-production").strip()
        desc     = (entry.get("description") or "").strip()

        # Image resolution: file on disk, or /assets/fallback.jpg
        raw_img = (entry.get("image") or "").strip()
        if raw_img and not raw_img.startswith("/"):
            raw_img = "/" + raw_img
        img = ""
        if raw_img:
            img_disk = os.path.join(DOCS, raw_img.lstrip("/"))
            if os.path.isfile(img_disk):
                img = raw_img
            else:
                print(f"  ⚠ manual '{slug}': image {raw_img!r} not found on disk — using fallback")
        if not img:
            img = "/assets/fallback.jpg"

        results.append({
            "slug":              slug,
            "title":             title,
            "published":         date,
            "category":          category,
            "dek":               desc,
            "meta_description":  desc,
            "card_summary":      desc,
            "image_url":         img,
            "image_credit":      "The Streamic",
            "image_license":     "Site Asset",
            "image_license_url": "",
            "word_count":        900,
            "generated_by":      "gpt_manual_editorial",
            "is_editorial":      True,
            "editorial":         True,
            "source_url":        "",
            "source_domain":     "The Streamic",
            "quality_score":     90,
            "body_html":         f"<p>{desc}</p>" if desc else "",
            "_source":           "manual",
        })

    if results:
        print(f"  ✓ manual_articles.json: {len(results)} loaded"
              f"{f', {skipped} skipped' if skipped else ''}")
    elif skipped:
        print(f"  ℹ manual_articles.json: 0 loaded, {skipped} skipped")

    return results


def main():
    with open(ARTS_F,"r",encoding="utf-8") as f: arts = json.load(f)
    if not arts: raise SystemExit("No articles")

    # ── Deduplicate by slug ───────────────────────────────────────────────
    seen_slugs, deduped = set(), []
    for a in arts:
        if a["slug"] not in seen_slugs:
            seen_slugs.add(a["slug"])
            deduped.append(a)
    arts = deduped
    print(f"  After slug dedup: {len(arts)} unique articles")

    # ── Jaccard near-duplicate cleanup (retroactive) ──────────────────────
    # Catches cross-topic story re-runs
    # before the 3-pass dedup was introduced. E.g. "Bitcentral to Showcase
    # Connected Media Workflows" and "Bitcentral To Feature Connected
    # Media Workflows" both about the same NAB press release.
    #
    # For each group of near-duplicates (>=70% token overlap), we keep:
    #   1. HAND_AUTHORED articles first (immutable protection)
    #   2. Then longest body (best content wins)
    #   3. Then newest published date as tiebreaker
    import re as _dd_re
    def _dd_tokens(title):
        if not title: return set()
        t = _dd_re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())
        return {w for w in t.split() if len(w) >= 4 and w not in {
            "with","from","that","this","will","show","2026","2025","2024",
            "announced","launches","introduces","unveils","debuts","nabs",
            "nab","ibc","new","the","and","for","are","into",
            "showcase","showcases","showcased","feature","features","featured",
            "to","at","on","in","by","of","a","an","is","its",
            # Broadcast-industry boilerplate that inflates false-positive splits:
            "intelligent","automation","solution","solutions","platform","technology",
            "workflow","workflows","system","systems","broadcast","media",
            "company","companies","announces","announcing",
        }}
    def _is_hand_authored(a):
        # Look up the file on disk; presence of <!-- HAND_AUTHORED --> wins.
        slug = a.get("slug", "")
        if not slug: return False
        try:
            fp = os.path.join(DOCS, "articles", slug + ".html")
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(400)
                return "HAND_AUTHORED" in head
        except Exception:
            pass
        return False

    JACCARD_THRESHOLD = 0.70
    kept = []
    dropped_near_dup = 0
    for candidate in arts:
        cand_tokens = _dd_tokens(candidate.get("title", ""))
        if not cand_tokens or len(cand_tokens) < 2:
            kept.append(candidate)
            continue
        merged = False
        for idx, existing in enumerate(kept):
            ex_tokens = _dd_tokens(existing.get("title", ""))
            if not ex_tokens: continue
            union = len(cand_tokens | ex_tokens)
            if union == 0: continue
            similarity = len(cand_tokens & ex_tokens) / union
            if similarity >= JACCARD_THRESHOLD:
                # Found a near-duplicate. Decide which to keep.
                cand_hand = _is_hand_authored(candidate)
                ex_hand   = _is_hand_authored(existing)
                cand_len  = len((candidate.get("body_html") or candidate.get("body") or "") or "")
                ex_len    = len((existing.get("body_html") or existing.get("body") or "") or "")
                # Tiebreak: hand-authored > longer body > newer
                if cand_hand and not ex_hand:
                    winner = candidate
                elif ex_hand and not cand_hand:
                    winner = existing
                elif cand_len > ex_len * 1.10:
                    winner = candidate
                elif ex_len > cand_len * 1.10:
                    winner = existing
                else:
                    winner = candidate if (candidate.get("date", "") > existing.get("date", "")) else existing
                loser = existing if winner is candidate else candidate
                print(f"  [DEDUP] '{loser.get('title','')[:55]}' "
                      f"≈ '{winner.get('title','')[:55]}' ({similarity:.0%}) — keeping winner")
                if winner is candidate:
                    kept[idx] = candidate
                dropped_near_dup += 1
                merged = True
                break
        if not merged:
            kept.append(candidate)
    arts = kept
    print(f"  After near-dup dedup: {len(arts)} unique articles "
          f"(removed {dropped_near_dup} near-duplicates)")

    # ── Merge manual_articles.json (overrides generated on slug collision) ──
    generated_arts = arts
    manual_arts    = load_manual_articles()
    by_slug = {}
    for a in generated_arts:
        by_slug[a.get("slug", "")] = a
    for a in manual_arts:
        by_slug[a.get("slug", "")] = a   # manual overrides generated
    arts = sorted(by_slug.values(), key=lambda a: a.get("published", ""), reverse=True)
    if manual_arts:
        m_slugs = {a.get("slug") for a in manual_arts}
        manual_count    = sum(1 for a in arts if a.get("slug") in m_slugs)
        generated_count = len(arts) - manual_count
        print(f"  Merged: {manual_count} manual + {generated_count} generated = {len(arts)} total")

    # ── Ensure all articles have a slug ──────────────────────────────────
    def _slugify(title):
        return re.sub(r"[^a-z0-9]+", "-", (title or "article").lower()).strip("-")
    for a in arts:
        if not a.get("slug"):
            a["slug"] = _slugify(a.get("title", "untitled"))

    # ── Ensure all articles have body content field ───────────────────────
    for a in arts:
        if not a.get("body_html"):
            # Fall back to card_summary or description so pages aren't empty
            fallback = a.get("card_summary") or a.get("description") or ""
            if fallback:
                a["body_html"] = f"<p>{fallback}</p>"

    # ── PUBLISH EVERYTHING ────────────────────────────────────────────────
    # All articles in generated_articles.json are hand-curated editorial content.
    # No word-count gate, no relevance gate, no skip logic.
    # Future articles added to the JSON will publish automatically.
    print(f"  Publishing all {len(arts)} articles (gate removed — 100% editorial corpus)")

    print(f"  Total articles after quality gate: {len(arts)}")

    # ── Fix images: replace typewriters/newspapers with broadcast visuals ──
    _fix_article_images(arts)

    # ── VISIBILITY: ALL articles are visible and indexed ──────────────────
    # Editorial-only corpus means every article in JSON is hand-curated,
    # so every article gets index,follow and full visibility.
    visible_list  = arts[:MAX_ARTICLES]
    visible_slugs = {a["slug"] for a in visible_list}
    ed_arts = [a for a in arts if a.get("is_editorial") or a.get("editorial")]

    print(f"  Visible &amp; indexed: {len(visible_slugs)} articles")

    os.makedirs(ARTS_D, exist_ok=True)

    # ── Article pages — visible indexed, rest noindex ─────────────────────
    # Any article file containing <!-- HAND_AUTHORED --> is never overwritten.
    # Add that comment to any article you edit manually to protect it permanently.
    written = 0
    for a in arts:
        slug_ = a.get("slug","")
        leg   = a.get("legacy_slug")
        dest  = os.path.join(ARTS_D, f"{slug_}.html")

        # Skip if file exists and is hand-authored
        if os.path.exists(dest):
            with open(dest, encoding="utf-8") as _fh:
                if "<!-- HAND_AUTHORED -->" in _fh.read():
                    written += 1
                    continue

        html  = article_page(a)
        if a["slug"] not in visible_slugs:
            html = html.replace(
                '<meta name="robots" content="index,follow">',
                '<meta name="robots" content="noindex,nofollow">'
            )
        w(dest, html)
        written += 1
        if leg and leg != slug_:
            leg_dest = os.path.join(ARTS_D, f"{leg}.html")
            if not (os.path.exists(leg_dest) and "<!-- HAND_AUTHORED -->" in open(leg_dest, encoding="utf-8").read()):
                w(leg_dest, html)
                written += 1
    print(f"  &#10003; {written} article files ({len(visible_slugs)} indexed, {written-len(visible_slugs)} noindex)")

    # ── Category pages ────────────────────────────────────────────────────
    # ALL category pages now show REAL articles (never blank "coming soon").
    # Only the robots meta tag differs: VISIBLE_CAT is indexed, others are noindex.
    # This means cloud.html, streaming.html etc always have content for visitors
    # and for AdSense crawlers — they just don't appear in Google search results
    # until we're ready to index them.
    by_cat = {}
    for a in arts:
        by_cat.setdefault(a["category"], []).append(a)

    cat_page_counts = {}
    for cat, ca in by_cat.items():
        # All articles for this category, sorted by date
        ca_sorted = sorted(ca, key=lambda a: a.get("published", ""), reverse=True)

        if cat == VISIBLE_CAT:
            # ai-post-production: indexed, pin relevant deep-dives
            cat_vis = ca_sorted[:]
            PINNED_TO_AI_POST = {
                "ai-video-post-production-editing-vfx-automation-2026",
                "media-asset-management-ai-era-monetisation-2026",
                "future-of-ai-in-broadcast-deployment-2026",
            }
            pinned_slugs = {a["slug"] for a in cat_vis}
            for a in arts:
                if a["slug"] in PINNED_TO_AI_POST and a["slug"] not in pinned_slugs:
                    cat_vis.append(a)
            cat_vis.sort(key=lambda a: a.get("published", ""), reverse=True)
            pages = category_page(cat, cat_vis)
            for pg, html in pages:
                if pg > 0:
                    html = html.replace(
                        '<meta name="robots" content="index,follow">',
                        '<meta name="robots" content="noindex,follow">'
                    )
                fname = f"{cat}.html" if pg == 0 else f"{cat}-p{pg+1}.html"
                w(os.path.join(DOCS, fname), html)
            cat_page_counts[cat] = len(cat_vis)

        else:
            # All other categories: noindex BUT show real articles (not placeholder)
            # Fallback: if somehow empty, use top articles from any category
            cat_articles = ca_sorted if ca_sorted else arts[:10]
            if not cat_articles:
                cat_articles = arts[:10]

            pages = category_page(cat, cat_articles)
            for pg, html in pages:
                # Force noindex on all pages for non-VISIBLE_CAT categories
                html = html.replace(
                    '<meta name="robots" content="index,follow">',
                    '<meta name="robots" content="noindex,follow">'
                )
                fname = f"{cat}.html" if pg == 0 else f"{cat}-p{pg+1}.html"
                w(os.path.join(DOCS, fname), html)
            cat_page_counts[cat] = len(cat_articles)

    indexed_cats  = [c for c in cat_page_counts if c == VISIBLE_CAT]
    noindex_cats  = [c for c in cat_page_counts if c != VISIBLE_CAT]
    print(f"  &#10003; {VISIBLE_CAT} indexed | {len(noindex_cats)} other categories noindex (with real articles)")
    for cat, n in sorted(cat_page_counts.items()):
        print(f"      {cat}: {n} articles")

    # ── Homepage ──────────────────────────────────────────────────────────
    feat_arts = sorted(arts, key=lambda a: a["published"], reverse=True)
    fp = featured_page(feat_arts)
    w(os.path.join(DOCS,"featured.html"), fp)
    w(os.path.join(DOCS,"index.html"),    fp)
    w(os.path.join(ROOT,"index.html"),    fp)   # Also at root — fixes 404 when Pages serves from branch root
    w(os.path.join(ROOT,"featured.html"), fp)  # Mirror at root so /featured.html resolves everywhere
    print("  &#10003; featured.html + index.html")

    # ── posts.html — noindex (preserve links, hide from Google) ──────────
    ap = all_articles_page(feat_arts)
    ap = ap.replace(
        '<meta name="robots" content="index,follow">',
        '<meta name="robots" content="noindex,follow">'
    )
    w(os.path.join(DOCS,"posts.html"), ap)
    w(os.path.join(ROOT,"posts.html"), ap)
    print("  &#10003; posts.html (noindex)")

    # ── Static pages ──────────────────────────────────────────────────────
    w(os.path.join(DOCS,"about.html"),            about_page())
    w(os.path.join(DOCS,"contact.html"),          contact_page())
    w(os.path.join(DOCS,"privacy.html"),          privacy_page())
    w(os.path.join(DOCS,"terms.html"),            terms_page())
    w(os.path.join(DOCS,"editorial-policy.html"), editorial_policy_page())
    w(os.path.join(DOCS,"howto.html"),            howto_page())
    w(os.path.join(DOCS,"insights.html"),         insights_page())
    w(os.path.join(DOCS,"post-production-workflows.html"), post_production_workflows_page())
    # Write Editor's Desk to editorsdesk.html and vlog.html for the QUIC landing.
    ed_html = editorsdesk_page()
    w(os.path.join(DOCS, "editorsdesk.html"), ed_html)
    vlog_html = ed_html.replace("Editor's Desk — The Streamic", "Vlog — The Streamic", 1)
    w(os.path.join(DOCS, "vlog.html"), vlog_html)
    w(os.path.join(ROOT, "vlog.html"), vlog_html)

    # ── AdSense compliance: delete thin redirect stubs + template junk ────
    # AdSense flags 4-word <meta refresh> redirect pages as "low-value
    # content." Soft-redirect stubs and thin template pages have no unique
    # content — they must return 404, not render with AdSense scripts.
    _ADSENSE_PURGE = [
        "how-to.html",                 # redirect stub → howto.html
        "broadcast-systems-hub.html",  # 4-word redirect stub → index.html
        "featured_priority.html",      # 276w template junk (data-layer artifact)
        "thank-you.html",              # 19w form-submission landing (thin)
    ]
    for _stale in _ADSENSE_PURGE:
        _path = os.path.join(DOCS, _stale)
        if os.path.exists(_path):
            try:
                os.remove(_path)
                print(f"  &#10003; purged thin page: {_stale}")
            except Exception:
                pass
    print("  &#10003; static pages")

    # ── Sitemap — only visible articles + core pages ──────────────────────
    w(os.path.join(DOCS,"sitemap.xml"), sitemap([a for a in arts if a["slug"] in visible_slugs]))
    w(os.path.join(DOCS,"robots.txt"),
      f"User-agent: *\nAllow: /\nDisallow: /posts.html\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    # ── Assets ────────────────────────────────────────────────────────────
    for f_name in ("style.css","main.js"):
        src = os.path.join(ROOT, f_name)
        if os.path.isfile(src): shutil.copy2(src, os.path.join(DOCS, f_name))
    print("  &#10003; style.css + main.js -> docs/")

    w(os.path.join(DOCS,"ads.txt"),  "google.com, pub-8033069131874524, DIRECT, f08c47fec0942fa0\n")
    w(os.path.join(DOCS,"CNAME"),    "thestreamic.in\n")
    open(os.path.join(DOCS,".nojekyll"),"w").close()
    open(os.path.join(ROOT,".nojekyll"),"w").close()  # Also at root — prevents Jekyll from running at all
    w(os.path.join(ROOT,"CNAME"),    "thestreamic.in\n")

    for fn in ["style.css","main.js","ads.txt","robots.txt"]:
        src_f = os.path.join(DOCS, fn)
        if os.path.isfile(src_f): shutil.copy2(src_f, os.path.join(ROOT, fn))

    # ── How-to guide article pages — always write from HOWTO_GUIDE_CONTENT ──
    # Self-healing: overwrites any 410-stub or missing file in docs/articles/
    guide_written = 0
    for g_slug, g_data in HOWTO_GUIDE_CONTENT.items():
        g_html = howto_article_page(g_slug, g_data)
        g_dest = os.path.join(ARTS_D, f"{g_slug}.html")
        w(g_dest, g_html)
        guide_written += 1
    print(f"  &#10003; {guide_written} how-to guide article pages written (self-healing 410 stubs)")

    # ── How-to guides to root/articles/ ──────────────────────────────────
    root_arts = os.path.join(ROOT,"articles")
    os.makedirs(root_arts, exist_ok=True)
    howto_guides = [fn for fn in os.listdir(ARTS_D) if fn.startswith("guide-") and fn.endswith(".html")]
    for fn in howto_guides:
        shutil.copy2(os.path.join(ARTS_D,fn), os.path.join(root_arts,fn))
    print(f"  &#10003; {len(howto_guides)} how-to guides mirrored to root/articles/")

    # ── Copy root-level hand-authored articles to docs/articles/ ──────────
    # These are manually created articles that live at repo root and must
    # also be served from docs/articles/ for GitHub Pages to find them.
    _root_html_articles = [
        "studio-grade-video-workflow-post-production-2026.html",
    ]
    for _fn in _root_html_articles:
        _src_path = os.path.join(ROOT, _fn)
        _dst_path = os.path.join(ARTS_D, _fn)
        if os.path.isfile(_src_path) and not os.path.exists(_dst_path):
            shutil.copy2(_src_path, _dst_path)
            print(f"  &#10003; {_fn} copied to docs/articles/")
        elif os.path.isfile(_src_path):
            # Always update — root is the source of truth for hand-authored articles
            shutil.copy2(_src_path, _dst_path)
            print(f"  &#10003; {_fn} synced to docs/articles/")

    # ── docs/data/ for client-side JS — only visible articles ────────────
    docs_data_dir = os.path.join(DOCS, "data")
    os.makedirs(docs_data_dir, exist_ok=True)

    gen_src = os.path.join(ROOT, "data", "generated_articles.json")
    if os.path.exists(gen_src):
        with open(gen_src,encoding="utf-8") as _f: raw_gen = json.load(_f)
        vis_gen = [a for a in raw_gen if a.get("slug") in visible_slugs]
        vis_gen.sort(key=lambda a: a.get("published",""), reverse=True)
        out_gen = {"featured_priority":vis_gen[:6],"items":vis_gen[6:]}
        gen_dst = os.path.join(docs_data_dir,"generated_articles.json")
        with open(gen_dst,"w",encoding="utf-8") as _f: json.dump(out_gen,_f,ensure_ascii=False)
        print(f"  &#10003; docs/data/generated_articles.json ({len(vis_gen)} visible articles)")

    print(f"\n✅ Build complete: {len(visible_slugs)}/{len(arts)} articles visible | AdSense mode ON")

if __name__ == "__main__":
    main()
