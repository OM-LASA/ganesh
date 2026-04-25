#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/assign_images.py v4 — Streamic local image assigner
============================================================

Assigns images from docs/assets/ to articles in data/generated_articles.json.
NO Unsplash. NO external URLs. Only local /assets/ files.

Behaviour:
- Scans docs/assets/ and creates lowercase-hyphenated copies for any uppercase/
  spaced filenames (idempotent — safe to re-run).
- Writes BOTH "image_url" AND "image" fields as /assets/filename.ext so
  build.py._fix_article_images() finds them at Priority 2 or 3.
- Category-aware: each article first tries its category-preferred image,
  then falls back to round-robin through the deck.
- Protected slugs (deepdives, NAB, expert insight, DMF) are never touched.
- Reserved files (logos, hero images, UI assets) never used as card images.
- Articles already pointing at a valid local image are left alone.
- Idempotent: running twice produces stable output.
"""

import json, os, re, shutil, sys, random
from typing import Dict, List

ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR      = os.path.join(ROOT, "data")
ARTICLES_FILE = os.path.join(DATA_DIR, "generated_articles.json")
ASSETS_DIR    = os.path.join(ROOT, "docs", "assets")

RESERVED_FILENAMES = {
    "logo.png", "fallback.jpg",
    "gfx-hero-nab-floor.png", "gfx-hero-nab-floor.jpg",
    "hero-broadcast-male.png",
    "nab-show-banner-news-headline-hero.png",
    "insight-quic-infographic.jpg",
    "neil-sadwelkar.jpg",
    "studio-grade-ott-workflow-2026.png",
}

PROTECTED_SLUG_PATTERNS = [
    lambda s: s.startswith("deepdive-"),
    lambda s: s == "nab-2026-hybrid-technology-year",
    lambda s: s == "Expertinsight1",
    lambda s: "avid-google-cloud-agentic-ai-media-production" in s,
    lambda s: s == "dynamic-media-facilities-dmf-broadcast-infrastructure-2026",
]

CATEGORY_PREFERRED = {
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


def _sanitize(name: str) -> str:
    """'MEDIA COMPOSER EDIT.png' → 'media-composer-edit.png'"""
    base, ext = os.path.splitext(name)
    base = base.lower().strip()
    base = re.sub(r"[\s_]+", "-", base)
    base = re.sub(r"[^a-z0-9\-]", "", base)
    base = re.sub(r"-+", "-", base).strip("-")
    ext = ext.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    return f"{base}{ext}" if base else ""


def _ensure_sanitized_copies() -> List[str]:
    """For each image with spaces/uppercase, create a sanitized copy.
    Returns sorted list of usable sanitized filenames (no reserved files)."""
    if not os.path.isdir(ASSETS_DIR):
        print(f"  ⚠ Assets directory not found: {ASSETS_DIR}")
        return []

    usable: List[str] = []
    seen: set = set()

    try:
        entries = sorted(os.listdir(ASSETS_DIR))
    except Exception as e:
        print(f"  ⚠ Cannot list {ASSETS_DIR}: {e}")
        return []

    for fname in entries:
        src = os.path.join(ASSETS_DIR, fname)
        if not os.path.isfile(src):
            continue
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue

        safe = _sanitize(fname)
        if not safe:
            continue

        dest = os.path.join(ASSETS_DIR, safe)
        if fname != safe and not os.path.exists(dest):
            try:
                shutil.copy2(src, dest)
                print(f"  ↳ sanitized copy: '{fname}' → '{safe}'")
            except Exception as e:
                print(f"  ⚠ Could not copy '{fname}': {e}")
                continue

        reserved_lower = {r.lower() for r in RESERVED_FILENAMES}
        if safe not in seen and safe.lower() not in reserved_lower:
            usable.append(safe)
            seen.add(safe)

    return sorted(usable)


def _is_protected(slug: str) -> bool:
    return any(fn(slug) for fn in PROTECTED_SLUG_PATTERNS)


def _is_existing_good_local_image(image_url: str) -> bool:
    """True if article already has a valid local /assets/ image on disk."""
    if not image_url or not isinstance(image_url, str):
        return False
    if image_url.startswith("http"):
        return False
    if "_fallback" in image_url:
        return False
    rel = image_url.lstrip("/")
    if not (rel.startswith("assets/") or rel.startswith("docs/assets/")):
        return False
    rel = rel.replace("docs/", "", 1) if rel.startswith("docs/") else rel
    disk = os.path.join(ROOT, "docs", rel)
    return os.path.isfile(disk)


def main() -> int:
    print("=== assign_images.py v4 — Local-Only Image Assigner ===")
    print()

    print("Step 1: Scanning docs/assets/ and creating sanitized copies …")
    usable_files = _ensure_sanitized_copies()

    if not usable_files:
        print("  ⚠ No usable images found in docs/assets/ — skipping assignment.")
        return 0

    print(f"  ✓ {len(usable_files)} usable images available")
    print()

    if not os.path.exists(ARTICLES_FILE):
        print(f"  ⚠ {ARTICLES_FILE} not found — nothing to assign.")
        return 0

    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            articles = json.load(f)
    except Exception as e:
        print(f"  ✗ Cannot read articles JSON: {e}")
        return 1

    if not isinstance(articles, list) or not articles:
        print("  ⚠ Articles file empty or invalid.")
        return 1

    print(f"Step 2: Loaded {len(articles)} articles from generated_articles.json")
    print()

    cat_preferred: Dict[str, str] = {}
    for cat, fn in CATEGORY_PREFERRED.items():
        full = os.path.join(ASSETS_DIR, fn)
        if os.path.isfile(full):
            cat_preferred[cat] = f"/assets/{fn}"

    deck = [f"/assets/{fn}" for fn in usable_files]
    random.seed(42)  # deterministic build → same image per article each run
    random.shuffle(deck)
    deck_idx = [0]

    def _next_from_deck() -> str:
        if not deck:
            return "/assets/fallback.jpg"
        img = deck[deck_idx[0] % len(deck)]
        deck_idx[0] += 1
        return img

    print("Step 3: Assigning local images …")
    assigned = skipped_protected = skipped_existing = 0

    for art in articles:
        if not isinstance(art, dict):
            continue

        slug = (art.get("slug") or "").strip()
        cat  = (art.get("category") or "featured").lower()

        if _is_protected(slug):
            skipped_protected += 1
            continue

        if _is_existing_good_local_image(art.get("image_url", "")):
            skipped_existing += 1
            continue

        chosen = cat_preferred.get(cat) or _next_from_deck()

        # Write BOTH fields so build.py finds the image at Priority 2 or 3
        art["image_url"]         = chosen
        art["image"]             = chosen
        art["image_credit"]      = "The Streamic"
        art["image_license"]     = "Site Asset"
        art["image_license_url"] = ""

        fname_no_ext = os.path.splitext(os.path.basename(chosen))[0]
        pretty = fname_no_ext.replace("-", " ").title()
        art["image_alt"] = f"The Streamic: {pretty}"

        assigned += 1

    print(f"  ✓ Assigned:          {assigned}")
    print(f"  ○ Skipped protected: {skipped_protected}")
    print(f"  ○ Skipped existing:  {skipped_existing}")
    print()

    ext_count = sum(
        1 for a in articles
        if isinstance(a, dict) and (a.get("image_url") or "").startswith("http")
        and not _is_protected(a.get("slug", ""))
    )
    if ext_count:
        print(f"  ⚠ {ext_count} articles still have external image_url after assignment")
    else:
        print("  ✓ Verified: all assigned articles have local /assets/ images")

    try:
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Wrote data/generated_articles.json")
    except Exception as e:
        print(f"  ✗ Cannot write articles JSON: {e}")
        return 1

    print()
    print("✅ assign_images.py complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
