#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_tone.py — Generate ONE sample article with the new tone tuning
before deploying to the full pipeline.

Runs Mistral against a single test scaffold (the Avid Content Core
article you flagged) and prints the output so you can eyeball the
new tone vs. the old "think of it like" pattern.

Usage (GitHub Actions manual step, or local):
    export MISTRAL_API_KEY=<your key>
    python3 scripts/verify_tone.py

What to look for in the output:
    ✓ NO "think of it like" anywhere
    ✓ NO "essentially a..." / "imagine a..." / "basically..."
    ✓ NO [Source 1] stamped after every single sentence — once per paragraph is ideal
    ✓ Technical terms explained through function, not analogy
    ✓ Professional trade-journal voice (reads like TVTech / The Broadcast Bridge)

After verification, if the tone looks correct:
    → Upload the 5 staged files to GitHub via web UI
    → Next scheduled build will regenerate all eligible articles with the new tone
"""

import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the updated Mistral generator
import importlib.util
spec = importlib.util.spec_from_file_location("m", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "generate_mistral.py"))
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass

if not m.MISTRAL_API_KEY:
    print("⚠ MISTRAL_API_KEY not set.")
    print("  Set it with: export MISTRAL_API_KEY=<your key>")
    sys.exit(1)

# Fixture: the exact Avid Content Core article you flagged with bad tone
test_article = {
    "slug": "test-avid-content-core",
    "title": "Avid Connects its News Platforms With Avid Content Core for 2026 NAB Show",
    "category": "newsroom",
    "source": "TV Technology",
    "source_url": "https://www.tvtechnology.com/news/avid-connects-its-news-platforms-with-avid-content-core-for-2026-nab-show",
    "url": "https://www.tvtechnology.com/news/avid-connects-its-news-platforms-with-avid-content-core-for-2026-nab-show",
    "date": "2026-04-13",
    "published": "2026-04-13",
    "body_html": (
        "<p>Avid will demonstrate at the 2026 NAB Show how its news platforms — "
        "Avid iNews, MediaCentral, and related production tools — now integrate "
        "with Avid Content Core. The integration targets post-production "
        "pipelines running Avid Media Composer with Avid Nexis storage, or "
        "Blackmagic Design's DaVinci Resolve with SAN-attached media. "
        "Workflow pain points addressed include ingest throughput, proxy "
        "workflow design, audio conformance (AES67 / loudness compliance), "
        "and export-to-delivery speed.</p>"
    ),
    "generated_by": "rewrite_feed_local",
    "word_count": 120,
}

print("=" * 72)
print("TONE VERIFICATION — generating single sample with NEW tuning")
print("=" * 72)
print(f"\nTuning: T={m.TEMPERATURE} / top_p={m.TOP_P} / "
      f"freq_penalty={m.FREQUENCY_PENALTY}")
print(f"Model cascade: {' → '.join(m.MISTRAL_MODELS)}\n")

body = m.call_with_cascade(m.SYSTEM_PROMPT, m.build_user_prompt(test_article))
if not body:
    print("✗ Generation failed — check API key + quota.")
    sys.exit(1)

reason = m.validate(body)
if reason:
    print(f"⚠ Output failed validation: {reason}")
    print("    (article would stay scaffold in real pipeline)\n")

# Extract tone metrics
plain = re.sub(r"<[^>]+>", " ", body)
plain = re.sub(r"\s+", " ", plain).strip()

think_of_it_count = len(re.findall(r"think of it like", body, re.I))
essentially_a_count = len(re.findall(r"essentially a", body, re.I))
imagine_a_count = len(re.findall(r"imagine a", body, re.I))
basically_count = len(re.findall(r"basically", body, re.I))
citation_count = len(re.findall(r"\[Source\s*\d+\]", body))
paragraph_count = len(re.findall(r"</p>|<h2|<h3", body))
words = len(plain.split())

print("=" * 72)
print("TONE METRICS")
print("=" * 72)
print(f"  Word count:            {words}")
print(f"  Citations [Source N]:  {citation_count}")
print(f"  Paragraph/section tags: {paragraph_count}")
print(f"  Citations per para:    "
      f"{citation_count/max(paragraph_count,1):.2f}  (target ~1.0)")
print()
print("  PATRONIZING PHRASE CHECK (all should be 0):")
print(f"    'think of it like':  {think_of_it_count}")
print(f"    'essentially a':     {essentially_a_count}")
print(f"    'imagine a':         {imagine_a_count}")
print(f"    'basically':         {basically_count}")

all_clean = (think_of_it_count == 0 and essentially_a_count == 0
             and imagine_a_count == 0 and basically_count == 0)
print()
print("  TONE VERDICT:  " + ("✓ CLEAN — ready to deploy" if all_clean
      else "✗ STILL CONTAINS PATRONIZING PHRASES — review before deploy"))

print()
print("=" * 72)
print("GENERATED ARTICLE BODY (first 2500 chars)")
print("=" * 72)
print(body[:2500])
if len(body) > 2500:
    print(f"\n... [{len(body) - 2500} more chars]")
print()
print("=" * 72)
print("DEPLOYMENT DECISION")
print("=" * 72)
if all_clean and not reason:
    print("  ✓ Tone is clean + validation passes — safe to deploy all 5 files")
else:
    print("  ⚠ Review output above before deploying")
