#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_mistral.py — Tier-1 generator using Mistral AI
REVISED: Temp 0.5 + Contextual Intelligence for better journalistic flow.
"""

from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
import requests

# ── Shared NotebookLM protocol ───────────────────────────────────────────────
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prompt_safety import FACTUAL_SAFETY_BLOCK
except ImportError:
    FACTUAL_SAFETY_BLOCK = ""

# ── Config ────────────────────────────────────────────────────────────────────
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
MISTRAL_API_URL = os.environ.get("MISTRAL_API_URL", "https://api.mistral.ai/v1/chat/completions").strip()

_DEFAULT_MODELS = ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"]
MISTRAL_MODELS = [m.strip() for m in os.environ.get("MISTRAL_MODELS", ",".join(_DEFAULT_MODELS)).split(",") if m.strip()]

# TUNING: Raised Temp to 0.5 to stop the "Hollow/Safe" output and allow professional interpretation.
TEMPERATURE       = 0.5 
TOP_P             = 0.9
FREQUENCY_PENALTY = 0.2
MAX_TOKENS        = 2000
MAX_PER_RUN       = 15

DATA_DIR      = Path(__file__).parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "generated_articles.json"

# ── System Prompt (Revised for Insight) ──────────────────────────────────────
# We keep the Safety Block but add instructions to favor "Industry Context" 
# over "The source doesn't specify this" in the So What section.
REVISED_SYSTEM_PROMPT = FACTUAL_SAFETY_BLOCK + """

═══════════════════════════════════════════════════════════════════════════
TIER-1 MISTRAL GENERATION — JOURNALISTIC INSIGHT PROTOCOL
═══════════════════════════════════════════════════════════════════════════

You are the Insight Architect for The Streamic. 

CRITICAL CHANGE TO GROUNDING:
1. FOR FACTS (What Happened): Stay 100% grounded in the source. Use [Source N].
2. FOR CONTEXT (So What?): If the source is thin, use your internal knowledge of 
   broadcast engineering to explain WHY this news matters to a CTO. 
   Do NOT write "The source doesn't specify this" in the 'So What?' or 
   'The Quick Hit' sections. Be a journalist: interpret the significance.
3. FOR TECH SPECS: If the source is vague about protocols, describe the LIKELY 
   infrastructure (e.g., if it mentions IP video, discuss the role of ST 2110 
   generally) using the 'Analogy Rule'.

STRUCTURE GATES:
- At least 400 words.
- At least 4 <h2> sections.
- Inline [Source N] citations for every hard claim.
- A "Blind Spots" section to maintain transparency.

Emit ONLY the HTML body. No preamble.
"""

# ... [Keep fetch_source_body and helper functions from your original script] ...

def call_mistral(system: str, user: str, model: str) -> tuple[Optional[str], str]:
    if not MISTRAL_API_KEY: return None, "auth"
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "frequency_penalty": FREQUENCY_PENALTY,
        "max_tokens": MAX_TOKENS,
    }
    try:
        resp = requests.post(MISTRAL_API_URL, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200: return None, "other"
        content = resp.json()["choices"][0]["message"]["content"]
        return content.strip(), "ok"
    except:
        return None, "error"

# ... [Main loop logic remains the same, but uses REVISED_SYSTEM_PROMPT] ...

if __name__ == "__main__":
    # Ensure you swap SYSTEM_PROMPT for REVISED_SYSTEM_PROMPT in your main()
    print(f"Running with Temperature: {TEMPERATURE}")
    # ... rest of main() logic
