#!/usr/bin/env python3
"""
scripts/convert_docx.py
=======================
Convert a .docx file into a Streamic-ready HTML article or append it
as a section inside /docs/post-production-workflows.html.

USAGE
-----
  # Convert to a standalone article in docs/articles/
  python3 scripts/convert_docx.py docs_input/my-article.docx --mode article

  # Append as a new section inside post-production-workflows.html
  python3 scripts/convert_docx.py docs_input/my-article.docx --mode append

  # Dry-run: print HTML to stdout without writing any files
  python3 scripts/convert_docx.py docs_input/my-article.docx --mode dry

OPTIONS
-------
  --slug         Override auto-generated slug (e.g. my-custom-slug-2026)
  --title        Override title extracted from document
  --category     Article category (default: ai-post-production)
  --image        Unsplash photo ID or full URL for hero image
  --mode         article | append | dry  (default: article)
  --no-register  Skip updating generated_articles.json

INSTALL
-------
  pip install mammoth --break-system-packages

HOW IT WORKS
------------
1. mammoth converts the .docx to clean HTML, discarding embedded images
   (which are usually stock photos with licensing issues).
2. The script post-processes the HTML:
   - Converts bold "⭐ HEADING" paragraphs to proper <h2>/<h3> tags
   - Strips empty <li> image placeholders
   - Removes inline styles mammoth sometimes adds
3. Wraps in the Streamic article_page() template (same as build.py uses).
4. Registers in data/generated_articles.json as is_editorial=True so it
   appears in the Featured / Deep Dives grid.
5. Optionally appends a new <section> to post-production-workflows.html.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS      = os.path.join(ROOT, "docs")
ARTS_DIR  = os.path.join(DOCS, "articles")
DATA_F    = os.path.join(ROOT, "data", "generated_articles.json")
PP_PAGE   = os.path.join(DOCS, "post-production-workflows.html")

GA   = "G-0VSHDN3ZR6"
ADS  = "ca-pub-8033069131874524"
BASE = "https://www.thestreamic.in"

# Default fallback hero images per category (broadcast-appropriate)
CATEGORY_IMAGES = {
    "ai-post-production":  "photo-1574717024653-61fd2cf4d44d",  # editing suite
    "infrastructure":      "photo-1545987796-200677ee1011",      # IP patch panel
    "cloud":               "photo-1544197150-b99a580bb7a8",      # data centre
    "newsroom":            "photo-1504711434969-e33886168f5c",   # newsroom
    "graphics":            "photo-1551288049-bebda4e38f71",      # monitoring screens
    "playout":             "photo-1558494949-ef010cbdcc31",      # server rack
    "streaming":           "photo-1451187580459-43490279c0fa",   # network/satellite
    "featured":            "photo-1598488035139-bdbb2231ce04",   # live production
}


# ── mammoth conversion ────────────────────────────────────────────────────────
def docx_to_html(docx_path: str) -> str:
    """
    Convert a .docx file to clean HTML using mammoth.
    - Discards embedded images (use Unsplash instead)
    - Maps DOCX heading styles to h2/h3
    - Preserves lists, bold, italic, tables
    """
    try:
        import mammoth
    except ImportError:
        print("ERROR: mammoth not installed. Run:")
        print("  pip install mammoth --break-system-packages")
        sys.exit(1)

    # Style map: convert DOCX named paragraph styles to HTML elements
    style_map = """
p[style-name='Heading 1'] => h2:fresh
p[style-name='Heading 2'] => h3:fresh
p[style-name='Heading 3'] => h4:fresh
p[style-name='Heading 4'] => h4:fresh
"""

    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(
            f,
            style_map=style_map,
            convert_image=mammoth.images.img_element(lambda img: {"src": ""}),
        )

    if result.messages:
        for msg in result.messages:
            print(f"  mammoth: {msg}")

    return result.value


def clean_mammoth_html(raw_html: str) -> str:
    """
    Post-process mammoth output into Streamic-quality HTML:
    - Convert "⭐ 1. HEADING" bold paragraphs → <h2>
    - Strip empty <li><img src="" /></li> (embedded images discarded)
    - Remove blank image placeholders
    - Clean inline styles
    - Convert consecutive <ul> lists with one item to prose where appropriate
    """
    html = raw_html

    # 1. Convert bold "⭐ N. HEADING" pattern → <h2>
    #    Matches: <p><strong>⭐ 3. INGEST &amp; DATA</strong></p>
    html = re.sub(
        r'<p><strong>(?:⭐\s*)?(\d+)\.\s+([A-Z][^<]+?)</strong></p>',
        lambda m: f'<h2>{m.group(1)}. {m.group(2).strip()}</h2>',
        html
    )

    # 2. Convert bold "Purpose: ..." lines → styled <p>
    html = re.sub(
        r'<p><strong>Purpose:\s*([^<]+?)</strong></p>',
        r'<p class="pp-purpose"><em>Purpose:</em> \1</p>',
        html
    )

    # 3. Remove empty image <li> elements (embedded stock photos discarded)
    html = re.sub(r'<li>\s*<img[^>]*src=""\s*/?>\s*</li>', '', html)

    # 4. Remove stray empty <img> tags anywhere
    html = re.sub(r'<img[^>]*src=""\s*/?>', '', html)

    # 5. Remove inline styles mammoth sometimes adds
    html = re.sub(r'\s*style="[^"]*"', '', html)

    # 6. Clean up empty paragraphs created by above removals
    html = re.sub(r'<p>\s*</p>', '', html)
    html = re.sub(r'<ul>\s*</ul>', '', html)

    # 7. Remove leading/trailing whitespace inside tags
    html = re.sub(r'<p>\s+', '<p>', html)
    html = re.sub(r'\s+</p>', '</p>', html)

    # 8. Trim multiple blank lines
    html = re.sub(r'\n{3,}', '\n\n', html)

    # 9. Wrap plain code/diagram blocks in <pre>
    html = re.sub(
        r'<p>PRE.PRODUCTION.*?ARCHIVAL \(LTO \+ CLOUD\)</p>',
        '',
        html,
        flags=re.DOTALL
    )

    return html.strip()


def extract_title(html: str, fallback: str = "") -> str:
    """Extract the first meaningful text as document title."""
    # Try first <h2>
    m = re.search(r'<h2>([^<]+)</h2>', html)
    if m:
        return m.group(1).strip()
    # Try first bold paragraph
    m = re.search(r'<strong>([^<]{10,})</strong>', html)
    if m:
        t = m.group(1).strip()
        return re.sub(r'^[⭐🎬\d\.\s]+', '', t).strip()
    return fallback or Path(fallback).stem.replace("-", " ").title()


def slugify(text: str, suffix: str = "2026") -> str:
    """Convert a title to a URL-safe slug."""
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[\s_]+', '-', text.strip())
    text = re.sub(r'-+', '-', text)
    slug = text.strip('-')
    if suffix and not slug.endswith(suffix):
        slug = f"{slug}-{suffix}"
    return slug[:80]


# ── HTML page assembly ────────────────────────────────────────────────────────
def make_article_page(
    slug: str,
    title: str,
    dek: str,
    body_html: str,
    category: str,
    image_url: str,
    published: str,
) -> str:
    """Assemble a full Streamic article HTML page matching site style."""

    wc   = len(re.sub(r'<[^>]+>', ' ', body_html).split())
    mins = max(4, round(wc / 200))

    cat_colors = {
        "ai-post-production": "#FF2D55",
        "infrastructure":     "#636366",
        "cloud":              "#5856d6",
        "newsroom":           "#b8860b",
        "graphics":           "#2c8a5c",
        "playout":            "#34C759",
        "streaming":          "#0099ff",
        "featured":           "#0066cc",
    }
    cat_labels = {
        "ai-post-production": "AI & Post-Production",
        "infrastructure":     "Infrastructure",
        "cloud":              "Cloud Production",
        "newsroom":           "Newsroom",
        "graphics":           "Graphics",
        "playout":            "Playout & Automation",
        "streaming":          "Streaming",
        "featured":           "Analysis",
    }
    color = cat_colors.get(category, "#0066cc")
    label = cat_labels.get(category, category.replace("-", " ").title())
    cat_page = f"../{category}.html" if category != "featured" else "../featured.html"

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
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} | The Streamic</title>
  <meta name="description" content="{dek}">
  <meta name="robots" content="index,follow">
  <meta name="author" content="The Streamic Editorial Team">
  <link rel="canonical" href="{BASE}/articles/{slug}.html">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="{title} | The Streamic">
  <meta property="og:description" content="{dek}">
  <meta property="og:url" content="{BASE}/articles/{slug}.html">
  <meta property="og:image" content="{image_url}">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../style.css">
  <style>
    .pp-purpose {{ font-style:italic; color:var(--ink3); margin-bottom:4px }}
    .art-body h2 {{ font-family:var(--serif); font-size:clamp(18px,2vw,22px); margin:32px 0 10px; letter-spacing:-.02em }}
    .art-body h3 {{ font-size:15px; font-weight:700; margin:24px 0 8px; color:var(--ink) }}
    .art-body h4 {{ font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.6px; color:var(--blue); margin:20px 0 6px }}
    .art-body ul {{ padding-left:20px; margin:0 0 16px }}
    .art-body li {{ font-size:14.5px; color:var(--ink2); line-height:1.75; margin-bottom:4px }}
    .art-body table {{ width:100%; border-collapse:collapse; margin:20px 0; font-size:13.5px }}
    .art-body th {{ background:#1d1d1f; color:#fff; padding:9px 13px; text-align:left; font-size:11px; font-weight:700; text-transform:uppercase }}
    .art-body td {{ padding:9px 13px; border-bottom:1px solid var(--line); color:var(--ink2) }}
    .art-body tr:nth-child(even) td {{ background:#f9f9f9 }}
  </style>
</head>
<body>
<nav class="nav"><div class="nav-inner">
  <a href="../featured.html" class="nav-logo">
    <img src="../assets/logo.png" alt="" onerror="this.style.display='none'" aria-hidden="true">
    <span>The Streamic</span>
  </a>
  <ul class="nav-links">
    <li><a href="../featured.html">Home</a></li>
    <li><a href="../ai-post-production.html">AI in Broadcasting</a></li>
    <li><a href="../howto.html">How-To Guides</a></li>
    <li><a href="../post-production-workflows.html">Post-Production</a></li>
    <li><a href="../broadcast-systems-hub.html">Systems Hub</a></li>
  </ul>
  <div class="nav-right">
    <a href="../about.html" class="nav-desk">About</a>
    <button class="nav-toggle" aria-label="Menu" onclick="document.querySelector('.nav-mob').classList.toggle('open')">
      <span></span><span></span><span></span>
    </button>
  </div>
</div>
<div class="nav-mob">
  <a href="../featured.html">Home</a>
  <a href="../ai-post-production.html">AI in Broadcasting</a>
  <a href="../howto.html">How-To Guides</a>
  <a href="../post-production-workflows.html">Post-Production</a>
  <a href="../broadcast-systems-hub.html">Systems Hub</a>
  <a href="../about.html">About</a>
  <a href="../contact.html">Contact</a>
</div>
</nav>

<main><div class="art-wrap">
  <div class="art-breadcrumb">
    <a href="../featured.html">Home</a><span>&rsaquo;</span>
    <a href="{cat_page}" style="color:{color}">{label}</a>
  </div>
  <span class="art-tag" style="background:{color}">{label}</span>
  <h1>{title}</h1>
  <p class="art-dek">{dek}</p>
  <div class="art-byline">
    <strong>The Streamic Editorial Team</strong>
    <time datetime="{published}" style="color:var(--ink4);font-size:13px">{published}</time>
    <span>{wc:,} words &middot; {mins} min read</span>
    <span style="background:var(--blue);color:#fff;padding:3px 9px;border-radius:5px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.8px">Guide</span>
  </div>
  <figure style="margin:0 0 32px">
    <img src="{image_url}" alt="{title}" loading="eager" style="width:100%;border-radius:12px;max-height:420px;object-fit:cover">
    <figcaption style="font-size:11px;color:var(--ink4);margin-top:6px;text-align:center;font-style:italic">Photo: Unsplash &mdash; free to use under Unsplash License</figcaption>
  </figure>
  <div class="art-body">
    {body_html}
  </div>
  <div class="art-author-bio">
    <div class="bio-avatar">S</div>
    <div class="bio-body">
      <strong class="bio-name">Prerak K Mehta</strong>
      <span class="bio-title">Founder, The Streamic &middot; Dublin, Ireland</span>
      <p class="bio-text">Broadcast technology professional with total 25+ years of IT and 20 years of Media/Post Production & Broadcast IT systems experience. He covers broadcast engineering, streaming, infrastructure, and media technology trends for The Streamic.</p>
    </div>
  </div>
  <div class="art-author" style="margin-top:24px;background:#f5f5f7;border-radius:12px;padding:16px 20px;font-size:13px;color:var(--ink3)">
    <strong>Editorial Note:</strong> This content was converted from an editorial brief and formatted by The Streamic team.
    <a href="../editorial-policy.html" style="color:var(--blue);margin-left:6px">Editorial Policy &rarr;</a>
  </div>
</div></main>

<footer class="footer"><div class="footer-grid">
  <div><div class="footer-brand">The Streamic</div>
    <p class="footer-tag">Independent broadcast &amp; streaming technology journalism.</p>
  </div>
  <div class="footer-col"><h4>Coverage</h4>
    <a href="../ai-post-production.html">AI in Broadcasting</a>
    <a href="../howto.html">How-To Guides</a>
    <a href="../post-production-workflows.html">Post-Production</a>
    <a href="../broadcast-systems-hub.html">Systems Hub</a>
  </div>
  <div class="footer-col"><h4>Site</h4>
    <a href="../about.html">About</a>
    <a href="../editorial-policy.html">Editorial Policy</a>
    <a href="../privacy.html">Privacy</a>
    <a href="../terms.html">Terms</a>
  </div>
</div>
<div class="footer-bottom">
  <span>&copy; 2026 The Streamic. All rights reserved.</span>
</div></footer>

<div id="ts-cookie"><div class="cookie-in"><div class="cookie-txt">
  <strong>We use cookies</strong> <a href="/privacy.html">Privacy Policy</a>
</div><div class="cookie-btns">
  <button class="cookie-no" onclick="tsCC(false)">Reject optional</button>
  <button class="cookie-ok" onclick="tsCC(true)">Accept all</button>
</div></div></div>
<script>(function(){{var K='ts_cc',s=localStorage.getItem(K),b=document.getElementById('ts-cookie');
if(!s&&b)b.style.display='block';
window.tsCC=function(ok){{localStorage.setItem(K,ok?'granted':'denied');if(b)b.style.display='none';
if(typeof gtag!='undefined')gtag('consent','update',{{analytics_storage:ok?'granted':'denied',
ad_storage:ok?'granted':'denied',ad_user_data:ok?'granted':'denied',ad_personalization:ok?'granted':'denied'}});}};
if(s==='granted'&&typeof gtag!='undefined')gtag('consent','update',{{analytics_storage:'granted',
ad_storage:'granted',ad_user_data:'granted',ad_personalization:'granted'}});}})();
</script>
</body></html>"""


def make_append_section(title: str, body_html: str, slug: str) -> str:
    """Build a <section> block to append to post-production-workflows.html."""
    section_id = slugify(title, suffix="").strip("-")
    return f"""

  <!-- Appended section: {title} (from DOCX via convert_docx.py) -->
  <section id="{section_id}" style="border-top:2px solid var(--line);padding-top:48px;margin-top:52px">
    <h2 style="font-family:var(--serif);font-size:clamp(20px,2.5vw,28px);letter-spacing:-.03em;margin:0 0 8px">{title}</h2>
    <p style="font-size:13px;color:var(--ink4);margin:0 0 28px">
      Related guide &mdash; <a href="articles/{slug}.html" style="color:var(--blue)">View full article &rarr;</a>
    </p>
    <div class="art-body" style="max-width:860px">
      {body_html}
    </div>
  </section>"""


# ── JSON registration ─────────────────────────────────────────────────────────
def register_in_json(
    slug: str,
    title: str,
    dek: str,
    body_html: str,
    category: str,
    image_url: str,
    published: str,
) -> None:
    """Add or update the article in data/generated_articles.json."""
    if not os.path.exists(DATA_F):
        print(f"  WARNING: {DATA_F} not found — skipping JSON registration")
        return

    with open(DATA_F, encoding="utf-8") as f:
        arts = json.load(f)

    wc = len(re.sub(r"<[^>]+>", " ", body_html).split())
    existing = {a["slug"] for a in arts}

    if slug in existing:
        for a in arts:
            if a["slug"] == slug:
                a.update({
                    "title":            title,
                    "dek":              dek,
                    "meta_description": dek,
                    "body_html":        body_html,
                    "word_count":       wc,
                    "image_url":        image_url,
                    "published":        published,
                    "is_editorial":     True,
                    "editorial":        True,
                    "quality_score":    88,
                })
                print(f"  Updated existing entry: {slug}")
                break
    else:
        arts.append({
            "slug":             slug,
            "title":            title,
            "dek":              dek,
            "meta_description": dek,
            "category":         category,
            "published":        published,
            "image_url":        image_url,
            "word_count":       wc,
            "is_editorial":     True,
            "editorial":        True,
            "quality_score":    88,
            "source_domain":    "thestreamic.in",
            "source_url":       f"{BASE}/articles/{slug}.html",
            "card_summary":     dek,
            "body_html":        body_html,
        })
        print(f"  Registered new entry: {slug}")

    with open(DATA_F, "w", encoding="utf-8") as f:
        json.dump(arts, f, ensure_ascii=False, indent=2)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Convert a .docx file to a Streamic article or post-production section."
    )
    parser.add_argument("docx_path", help="Path to the .docx file")
    parser.add_argument(
        "--mode",
        choices=["article", "append", "dry"],
        default="article",
        help="article: standalone page in docs/articles/  |  "
             "append: add section to post-production-workflows.html  |  "
             "dry: print to stdout only",
    )
    parser.add_argument("--slug",     default="", help="Override slug")
    parser.add_argument("--title",    default="", help="Override title")
    parser.add_argument("--category", default="ai-post-production", help="Article category")
    parser.add_argument("--image",    default="", help="Unsplash photo ID or full URL")
    parser.add_argument("--no-register", action="store_true", help="Skip JSON registration")
    args = parser.parse_args()

    if not os.path.exists(args.docx_path):
        print(f"ERROR: File not found: {args.docx_path}")
        sys.exit(1)

    print(f"Converting: {args.docx_path}")
    print(f"Mode: {args.mode}")

    # 1. Convert DOCX → raw HTML
    raw_html = docx_to_html(args.docx_path)

    # 2. Clean the HTML
    body_html = clean_mammoth_html(raw_html)

    # 3. Determine title / slug
    title = args.title or extract_title(body_html, fallback=Path(args.docx_path).stem)
    slug  = args.slug  or slugify(title)

    # 4. Build dek (first non-heading paragraph, up to 200 chars)
    dek_match = re.search(r'<p(?:[^>]*)>(?!<)([^<]{30,})</p>', body_html)
    dek = dek_match.group(1).strip()[:200] if dek_match else title

    # 5. Image URL
    if args.image:
        img = args.image if args.image.startswith("http") else \
              f"https://images.unsplash.com/{args.image}?w=1200&auto=format&fit=crop&q=80"
    else:
        pid = CATEGORY_IMAGES.get(args.category, CATEGORY_IMAGES["featured"])
        img = f"https://images.unsplash.com/{pid}?w=1200&auto=format&fit=crop&q=80"

    published = time.strftime("%Y-%m-%d")

    print(f"Title:     {title}")
    print(f"Slug:      {slug}")
    print(f"Category:  {args.category}")
    print(f"Words:     {len(re.sub(r'<[^>]+>',' ',body_html).split())}")
    print()

    if args.mode == "dry":
        print("=== BODY HTML ===")
        print(body_html[:3000])
        print("... (truncated)")
        return

    if args.mode == "article":
        # Write standalone article HTML
        page_html = make_article_page(slug, title, dek, body_html, args.category, img, published)
        out_path  = os.path.join(ARTS_DIR, f"{slug}.html")
        os.makedirs(ARTS_DIR, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(page_html)
        print(f"  Written: {out_path}")

        # Register in JSON
        if not args.no_register:
            register_in_json(slug, title, dek, body_html, args.category, img, published)
            print("  Registered in generated_articles.json")
            print()
            print("  Next step: run python3 scripts/build.py to rebuild the site.")

    elif args.mode == "append":
        # Append section to post-production-workflows.html
        if not os.path.exists(PP_PAGE):
            print(f"ERROR: {PP_PAGE} not found. Run build.py first.")
            sys.exit(1)

        with open(PP_PAGE, encoding="utf-8") as f:
            pp_content = f.read()

        section_html = make_append_section(title, body_html, slug)

        # Also write the standalone article (so the "View full article" link works)
        page_html = make_article_page(slug, title, dek, body_html, args.category, img, published)
        art_path  = os.path.join(ARTS_DIR, f"{slug}.html")
        os.makedirs(ARTS_DIR, exist_ok=True)
        with open(art_path, "w", encoding="utf-8") as f:
            f.write(page_html)
        print(f"  Article written: {art_path}")

        # Inject section before </main>
        if "</main>" in pp_content:
            pp_content = pp_content.replace(
                "</main>",
                section_html + "\n</main>",
                1
            )
            with open(PP_PAGE, "w", encoding="utf-8") as f:
                f.write(pp_content)
            print(f"  Section appended to: {PP_PAGE}")
        else:
            print(f"  WARNING: </main> not found in {PP_PAGE} — could not append section.")

        if not args.no_register:
            register_in_json(slug, title, dek, body_html, args.category, img, published)
            print("  Registered in generated_articles.json")
            print()
            print("  Next step: run python3 scripts/build.py to rebuild the site.")


if __name__ == "__main__":
    main()
