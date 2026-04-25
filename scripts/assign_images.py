#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assign_images.py v3 — Streamic visual image assigner (Cyclic Random)
==================================================================

FIXED:
- Modified the 'No editorial images' check to prevent hard-exiting.
- Site will now build gracefully even if the assets folder is empty.
"""

import json, os, re, shutil, sys, random
from typing import Dict, List, Optional, Tuple

ROOT            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR        = os.path.join(ROOT, "data")
ARTICLES_FILE   = os.path.join(DATA_DIR, "generated_articles.json")
IMAGE_DIR_DISK  = os.path.join(ROOT, "docs", "assets")
IMAGE_URL_BASE  = "/assets"

PROTECTED_SLUG_PATTERNS = [
    lambda s: s.startswith("deepdive-"),
    lambda s: s == "nab-2026-hybrid-technology-year",
    lambda s: s == "Expertinsight1",
    lambda s: "avid-google-cloud-agentic-ai-media-production" in s,
]

RESERVED_FILENAMES = {
    "logo.png", "fallback.jpg",
    "nab_show_banner_news_headline_hero.png",
    "nab-show-banner-news-headline-hero.png",
    "gfx-hero-nab-floor.png", "gfx-hero-nab-floor.jpg",
    "hero-broadcast-male.png", "hero-broadcast-male1png",
    "insight-quic-infographic.jpg", "neil-sadwelkar.jpg",
    "studio-grade-ott-workflow-2026.png",
}

def _sanitize(name: str) -> str:
    """'MEDIA COMPOSER EDIT.png' → 'media-composer-edit.png'"""
    base, ext = os.path.splitext(name)
    base = base.lower()
    base = re.sub(r"[\s_]+", "-", base)
    base = re.sub(r"[^a-z0-9\-]", "", base)
    base = re.sub(r"-+", "-", base).strip("-")
    ext = ext.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    return f"{base}{ext}" if base else ""

def _auto_rename_uploads() -> List[str]:
    """Copy files with spaces/uppercase to sanitized names."""
    if not os.path.isdir(IMAGE_DIR_DISK):
        print(f"[WARN] Image directory not found: {IMAGE_DIR_DISK}")
        return []

    safe_list: List[str] = []
    seen: set = set()
    try:
        entries = sorted(os.listdir(IMAGE_DIR_DISK))
    except Exception as e:
        print(f"[ERROR] Cannot list {IMAGE_DIR_DISK}: {e}")
        return []

    for fname in entries:
        src = os.path.join(IMAGE_DIR_DISK, fname)
        if not os.path.isfile(src):
            continue
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        safe = _sanitize(fname)
        if not safe:
            continue
        dest = os.path.join(IMAGE_DIR_DISK, safe)
        if fname != safe and not os.path.exists(dest):
            try:
                shutil.copy2(src, dest)
                print(f"  ↳ renamed copy: '{fname}' → '{safe}'")
            except Exception as e:
                continue
        if safe not in seen and safe.lower() not in RESERVED_FILENAMES:
            safe_list.append(safe)
            seen.add(safe)
    return sorted(safe_list)

def _read_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Cannot read {path}: {e}")
        return None

def _write_json(path: str, data) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Cannot write {path}: {e}")
        return False

def _is_protected(slug: str) -> bool:
    return any(fn(slug) for fn in PROTECTED_SLUG_PATTERNS)

def _is_existing_local_image(image_url: str) -> bool:
    if not image_url or not isinstance(image_url, str):
        return False
    if not (image_url.startswith("/assets/") or image_url.startswith("assets/")):
        return False
    rel = image_url.lstrip("/")
    disk = os.path.join(ROOT, "docs", rel)
    return os.path.isfile(disk)

def main() -> int:
    print("=== assign_images.py v3 — Cyclic Random Assigner ===")
    
    print("Step 1: Scanning /docs/assets/ for images …")
    safe_files = _auto_rename_uploads()
    
    # FIXED: Changed from a hard exit to a graceful warning
    if not safe_files:
        print("  ⚠ No editorial images found in docs/assets/. Skipping image assignment step.")
        return 0 
        
    print(f"  ✓ {len(safe_files)} candidate images available.")

    print(f"Step 2: Reading {ARTICLES_FILE} …")
    articles = _read_json(ARTICLES_FILE)
    if not articles or not isinstance(articles, list):
        print("  ⚠ Articles file not found or invalid.")
        return 1
    print(f"  ✓ {len(articles)} articles loaded\n")

    print("Step 3: Assigning images (Shuffled Deck approach) …")
    assigned = skipped_protected = skipped_existing = 0

    # The Shuffled Deck logic
    image_pool = safe_files.copy()
    random.shuffle(image_pool)

    def get_next_random_image():
        nonlocal image_pool
        if not image_pool:
            # If the deck runs out, reshuffle a new deck
            image_pool = safe_files.copy()
            random.shuffle(image_pool)
        return image_pool.pop()

    for art in articles:
        if not isinstance(art, dict):
            continue
            
        slug = art.get("slug", "") or ""
        if _is_protected(slug):
            skipped_protected += 1
            continue
        if _is_existing_local_image(art.get("image_url", "")):
            skipped_existing += 1
            continue

        # Grab a unique random image from the deck
        chosen = get_next_random_image()

        if chosen:
            url = f"{IMAGE_URL_BASE}/{chosen}"
            art["image_url"]         = url
            art["image"]             = url
            art["image_credit"]      = "The Streamic"
            art["image_license"]     = "Site License"
            art["image_license_url"] = ""
            
            # Create a clean Alt Tag for SEO
            pretty = os.path.splitext(chosen)[0].replace("-", " ").title()
            art["image_alt"]         = f"Streamic technical brief: {pretty}"
            assigned += 1

    print(f"  ✓ Assigned Random Images: {assigned}")
    print(f"  ○ Skipped (protected):    {skipped_protected}")
    print(f"  ○ Skipped (existing):     {skipped_existing}\n")

    if not _write_json(ARTICLES_FILE, articles):
        return 1
    print("✓ Wrote updated generated_articles.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())
