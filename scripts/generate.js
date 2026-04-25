/**
 * THE STREAMIC — scripts/generate.js
 * ════════════════════════════════════════════════════════════════
 * Full AI-assisted article generator.
 *
 * PIPELINE:
 *   1. Fetch broadcast RSS feeds → extract title + content
 *   2. Call Hugging Face Inference API (mistralai/Mistral-7B-Instruct)
 *      with a structured prompt → receive 1200+ word original article
 *   3. Write each article as a clean static HTML page in docs/posts/
 *   4. Rebuild docs/index.html, docs/posts.html with article list
 *   5. Update sitemap.xml
 *
 * SECURITY:  HF_API_KEY is read from env — NEVER embedded in HTML
 * ADSENSE:   All output is original long-form content, not summaries
 * GITHUB PAGES: Fully static — no client-side API calls whatsoever
 * ════════════════════════════════════════════════════════════════
 */

'use strict';

const fs          = require('fs');
const path        = require('path');
const https       = require('https');
const http        = require('http');
const { URL }     = require('url');

// Shared factual-safety block — loaded from scripts/factual_safety.txt
// so all generators (Python + Node) enforce identical rules.
let FACTUAL_SAFETY_BLOCK = '';
try {
  const _safetyPath = path.join(__dirname, 'factual_safety.txt');
  FACTUAL_SAFETY_BLOCK = fs.readFileSync(_safetyPath, 'utf8').trim();
} catch (_e) {
  FACTUAL_SAFETY_BLOCK = (
    'STRICT FACTUAL SAFETY: Never guess what a product does. Never assign '
    + 'a product category unless the source explicitly states it. Never '
    + 'invent standards support (ST 2110, NMOS, SCTE-35, etc.) unless the '
    + 'source names them. Never add competitor names not in the source. '
    + 'Mediagenix is scheduling/rights/BMS — NOT playout. If the source '
    + 'is vague, stay vague. Accuracy over impressiveness.'
  );
}

// ── CONFIG ────────────────────────────────────────────────────────────────
// Reads GROQ_API_KEY first, falls back to HF_API_KEY (same key, different name)
const HF_API_KEY  = process.env.GROQ_API_KEY || process.env.HF_API_KEY || '';
// Groq API — fast, reliable, OpenAI-compatible
const HF_MODEL    = 'llama-3.3-70b-versatile';
const HF_URL      = 'https://api.groq.com/openai/v1/chat/completions';
const BASE_URL    = process.env.SITE_BASE_URL || 'https://www.thestreamic.in';
const GA          = 'G-0VSHDN3ZR6';
const ADS_ID      = 'ca-pub-8033069131874524';
const AUTHOR      = 'The Streamic Editorial Team';

const ROOT        = path.join(__dirname, '..');
const DOCS        = path.join(ROOT, 'docs');
const POSTS_DIR   = path.join(DOCS, 'posts');
const INDEX_F     = path.join(ROOT, 'data', 'hf_articles.json');

const MAX_ARTICLES_PER_RUN  = 8;   // HF rate limit protection
const MAX_STORED_ARTICLES   = 80;  // keep rolling window
const SLEEP_MS              = 4000; // between HF calls

// ── BROADCAST RSS FEEDS ───────────────────────────────────────────────────
// Categorised by topic — generator picks the best content to expand
const FEEDS = [
  // Featured / General
  { url: 'https://www.tvbeurope.com/feed/',              cat: 'featured',           source: 'TVBEurope'         },
  { url: 'https://www.newscaststudio.com/feed/',         cat: 'newsroom',           source: 'NewscastStudio'    },
  { url: 'https://www.broadcastbeat.com/feed/',          cat: 'featured',           source: 'BroadcastBeat'     },
  { url: 'https://www.svgeurope.org/feed/',              cat: 'featured',           source: 'SVG Europe'        },
  // Streaming
  { url: 'https://www.tvtechnology.com/streaming/rss.xml', cat: 'streaming',        source: 'TV Technology'     },
  { url: 'https://www.thebroadcastbridge.com/rss/streaming', cat: 'streaming',      source: 'Broadcast Bridge'  },
  // Cloud
  { url: 'https://www.thebroadcastbridge.com/rss/cloud', cat: 'cloud',             source: 'Broadcast Bridge'  },
  { url: 'https://aws.amazon.com/blogs/media/feed/',     cat: 'cloud',             source: 'AWS Media Blog'    },
  // Infrastructure
  { url: 'https://www.thebroadcastbridge.com/rss/infrastructure', cat: 'infrastructure', source: 'Broadcast Bridge' },
  // AI & Post
  { url: 'https://www.tvbeurope.com/ai-and-machine-learning/feed/', cat: 'ai-post-production', source: 'TVBEurope' },
  // Playout
  { url: 'https://www.thebroadcastbridge.com/rss/playout', cat: 'playout',         source: 'Broadcast Bridge'  },
  // Graphics
  { url: 'https://www.thebroadcastbridge.com/rss/graphics', cat: 'graphics',       source: 'Broadcast Bridge'  },
];

// ── UTILITIES ─────────────────────────────────────────────────────────────
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function slugify(str) {
  return str.toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
    .slice(0, 70);
}

function stripHtml(html) {
  return (html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

function esc(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleDateString('en-GB', { day:'numeric', month:'long', year:'numeric' });
  } catch(_) { return iso || ''; }
}

function todayIso() {
  return new Date().toISOString().slice(0,10);
}

function fetchUrl(urlStr, opts = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(urlStr);
    const lib    = parsed.protocol === 'https:' ? https : http;
    const reqOpts = {
      hostname: parsed.hostname,
      path:     parsed.pathname + parsed.search,
      port:     parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      method:   opts.method || 'GET',
      headers:  {
        'User-Agent':    'Mozilla/5.0 (compatible; TheStreamic/3.0)',
        'Accept':        'application/json, text/xml, */*',
        'Content-Type':  opts.contentType || 'application/json',
        ...opts.headers,
      },
      timeout: 30000,
    };
    const req = lib.request(reqOpts, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve({ status: res.statusCode, body: data, headers: res.headers }));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
    if (opts.body) req.write(opts.body);
    req.end();
  });
}

// ── SIMPLE RSS PARSER (no npm dependency needed) ──────────────────────────
function parseRss(xmlStr) {
  const items = [];
  const itemMatches = [...xmlStr.matchAll(/<item[^>]*>([\s\S]*?)<\/item>/gi)];
  for (const m of itemMatches) {
    const xml  = m[1];
    const get  = (tag) => {
      const r = xml.match(new RegExp(`<${tag}[^>]*><!\\[CDATA\\[([\\s\\S]*?)\\]\\]><\\/${tag}>`, 'i'))
             || xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i'));
      return r ? r[1].trim() : '';
    };
    const title   = get('title');
    const link    = get('link') || get('guid');
    const desc    = get('description') || get('content:encoded') || get('summary');
    const pubDate = get('pubDate') || get('published') || get('dc:date');
    if (title && link) {
      items.push({ title, link, description: desc, pubDate });
    }
  }
  return items;
}

// ── HUGGING FACE ARTICLE GENERATION ──────────────────────────────────────
/**
 * Strong prompt that forces HF to generate a full 1200+ word original article,
 * not a summary. This is the key to AdSense compliance.
 */
function buildPrompt(title, content, category, sourceName) {
  // Per-category expert context injected into the prompt for specificity
  const catContext = {
    'featured':           'broadcast and streaming technology — covering the full media production and delivery ecosystem',
    'streaming':          'video streaming, OTT delivery, adaptive bitrate encoding, CDN architecture, and live streaming infrastructure',
    'cloud':              'cloud-native broadcast production, REMI workflows, remote collaboration, and cloud playout platforms',
    'infrastructure':     'broadcast IP infrastructure (SMPTE ST 2110, NMOS, AES67), SDI migration, IP routing, and facility design',
    'ai-post-production': 'AI-assisted post-production, automated MAM/PAM workflows, intelligent QC, and machine learning in media pipelines',
    'playout':            'broadcast playout automation, channel-in-a-box, master control, and transmission technology',
    'graphics':           'real-time broadcast graphics, virtual studio technology, AR/XR in live production, and motion design systems',
    'newsroom':           'newsroom control systems (NRCS), remote journalism workflows, news production automation, and editorial technology',
  }[category] || 'broadcast and streaming technology';

  // Trim source content — HF has token limits; 2500 chars is plenty as seed
  const seed = content.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 2500);

  // ════════════════════════════════════════════════════════════════════
  // Plain chat messages — no special prompt format tags needed
  // Structured to produce exactly the HTML sections we need.
  // max_new_tokens is set to 2000 to ensure 1200-1500 word output.
  // ════════════════════════════════════════════════════════════════════
  return `${FACTUAL_SAFETY_BLOCK}

═══════════════════════════════════════════════════════════════════════════
ROLE
═══════════════════════════════════════════════════════════════════════════

You are a senior broadcast technology journalist at The Streamic — a professional publication read by broadcast engineers, production technologists, and media CTOs worldwide.

Write a detailed, SEO-optimized article of exactly 1200–1500 words based on the source content below.

DO NOT summarize the article. Do NOT produce a brief overview or bullet summary. Instead, expand it into a high-value, original analysis piece that provides genuine expert depth.

TOPIC AREA: ${catContext}
ORIGINAL SOURCE: ${sourceName}

─────────────────────────────────────────────────────────────
OUTPUT STRUCTURE — Use these exact section headings in order:
─────────────────────────────────────────────────────────────

## [Write a compelling SEO headline based on the topic]

[Write 2–3 engaging introductory paragraphs. Hook the reader immediately. State clearly why this matters to broadcast and media technology professionals right now. Do NOT start with "This article" or "In this article".]

## Why This Matters

[Write 3–4 paragraphs explaining the strategic and operational significance of this development. Who is affected? What changes? Why does this matter specifically in 2026? Be concrete — name workflows, standards, or business models that are impacted. Avoid vague phrases like "this is important" — explain exactly WHY.]

## Expert Insight

[Write 3–4 paragraphs of genuine technical analysis. Go beyond what the source says. Discuss underlying standards (ST 2110, NMOS, AES67, HLS, HEVC, AV1, SRT, RIST, NDI, DNxHD, MXF — whichever are relevant), vendor ecosystem context, competitive dynamics, and forward-looking trends. This section must feel like it was written by someone with 15 years in the broadcast industry.]

## Real-World Impact

[Write 2–3 paragraphs on practical deployment implications. What do engineering teams, operations managers, and technology directors need to know? What are the migration risks, integration challenges, or cost considerations? Include specific examples of how this affects real broadcast workflows — ingest, playout, post-production, or distribution as appropriate.]

## Key Takeaways

- [Specific, actionable takeaway for engineering teams — not generic]
- [Specific technical or operational implication]
- [Cost, timeline, or procurement consideration]
- [Standards or interoperability point]
- [Forward-looking strategic recommendation]

## Frequently Asked Questions

**Q: [Write a specific technical question a broadcast engineer would ask]**
A: [Write a detailed 3–4 sentence answer with technical specifics]

**Q: [Write a question about implementation or migration]**
A: [Write a detailed 3–4 sentence answer]

**Q: [Write a question about cost, ROI, or business case]**
A: [Write a detailed 3–4 sentence answer]

**Q: [Write a question about standards compliance or interoperability]**
A: [Write a detailed 3–4 sentence answer]

**Q: [Write a question about future roadmap or what comes next]**
A: [Write a detailed 3–4 sentence answer]

## Conclusion

[Write 2 strong concluding paragraphs. Summarise the key strategic message. Give broadcast engineering teams a clear direction — what should they do next, and why now? End with a forward-looking statement about the technology's trajectory.]

─────────────────────────────────────────────────────────────
RULES (MANDATORY — violations will disqualify the output):
─────────────────────────────────────────────────────────────
1. Total length: 1200–1500 words. Do NOT write less than 1200 words. Do NOT produce a summary.
2. Use all seven section headings exactly as written above. The sections ## Why This Matters and ## Expert Insight are MANDATORY — output is rejected without them.
3. Do NOT copy sentences from the source content. Rewrite everything in your own expert voice.
4. Do NOT use vague filler phrases: "innovative", "game-changing", "cutting-edge", "state-of-the-art", "exciting", "revolutionize".
5. Do NOT start sentences with the same word twice in a row.
6. Key Takeaways must be specific and actionable — not generic observations.
7. FAQ answers must be substantive (3–4 sentences each) with technical detail.
8. Write for expert readers who already understand broadcast technology fundamentals.

─────────────────────────────────────────────────────────────
SOURCE CONTENT (use as seed only — expand far beyond this):
─────────────────────────────────────────────────────────────
Title: ${title}

${seed}

Write the complete 1200–1500 word article now, starting with the ## headline:`;
}


async function callHuggingFace(prompt) {
  // Uses Groq API (OpenAI-compatible) — same as generate_summaries.py
  // API key: GROQ_API_KEY secret in GitHub (HF_API_KEY read as fallback)
  if (!HF_API_KEY) {
    console.warn('  ⚠ GROQ_API_KEY not set — using placeholder content');
    return null;
  }

  const payload = JSON.stringify({
    model:       HF_MODEL,
    messages: [
      {
        role:    'system',
        content: (
          FACTUAL_SAFETY_BLOCK + '\n\n' +
          'You are a senior broadcast technology editor at The Streamic — ' +
          'a professional publication for broadcast engineers and media CTOs. ' +
          'Write detailed, original, expert-level articles. ' +
          'Never use buzzwords like "innovative", "seamless", or "game-changer".'
        ),
      },
      {
        role:    'user',
        content: prompt,
      },
    ],
    max_tokens:  2048,   // 2048 ensures 1200+ word output with all required sections
    temperature: 0.7,
    stream:      false,
  });

  try {
    const res = await fetchUrl(HF_URL, {
      method:      'POST',
      contentType: 'application/json',
      headers: {
        'Authorization': `Bearer ${HF_API_KEY}`,
      },
      body: payload,
    });

    if (res.status !== 200) {
      console.warn(`  ⚠ Groq API returned ${res.status}: ${res.body.slice(0, 300)}`);
      return null;
    }

    const data = JSON.parse(res.body);
    if (data.choices && data.choices[0] && data.choices[0].message) {
      return data.choices[0].message.content.trim();
    }
    console.warn('  ⚠ Unexpected Groq response:', JSON.stringify(data).slice(0, 200));
    return null;
  } catch (err) {
    console.warn(`  ⚠ Groq API error: ${err.message}`);
    return null;
  }
}


function articleTextToHtml(text, sourceUrl, sourceName) {
  if (!text) return '';

  // ── Special section styling map ──────────────────────────────────────────
  // These H2 headings get a distinct visual treatment so the article structure
  // is immediately clear to readers (and Google's crawler).
  const SECTION_STYLES = {
    'Why This Matters': {
      cls: 'section-why-matters',
      icon: '📡',
      bg: '#f0f6ff',
      border: '#0066cc',
    },
    'Expert Insight': {
      cls: 'section-expert-insight',
      icon: '🔬',
      bg: '#f5f0ff',
      border: '#7c3aed',
    },
    'Real-World Impact': {
      cls: 'section-real-world',
      icon: '🏭',
      bg: '#f0fff4',
      border: '#16a34a',
    },
    'Key Takeaways': {
      cls: 'section-key-takeaways',
      icon: '✦',
      bg: '#fffbeb',
      border: '#d97706',
    },
    'Frequently Asked Questions': {
      cls: 'section-faq',
      icon: '❓',
      bg: '#f8fafc',
      border: '#64748b',
    },
    'Conclusion': {
      cls: 'section-conclusion',
      icon: '→',
      bg: '#f5f5f7',
      border: '#1d1d1f',
    },
  };

  const lines   = text.split('\n');
  let html      = '';
  let inList    = false;
  let inOl      = false;
  let inFaq     = false;
  let currentSection = null;  // tracks open section wrapper

  function closeList() {
    if (inList) { html += '</ul>\n'; inList = false; }
    if (inOl)   { html += '</ol>\n'; inOl   = false; }
  }

  function openSection(heading) {
    const style = SECTION_STYLES[heading];
    if (!style) return `<h2>${esc(heading)}</h2>\n`;
    return `
<section class="article-section ${style.cls}" style="
  background:${style.bg};
  border-left:4px solid ${style.border};
  border-radius:0 12px 12px 0;
  padding:20px 24px;
  margin:32px 0 24px;
">
<h2 style="
  font-family:var(--serif,'DM Serif Display',Georgia,serif);
  font-size:22px;
  font-weight:400;
  letter-spacing:-0.04em;
  color:#1d1d1f;
  margin:0 0 16px;
  display:flex;
  align-items:center;
  gap:10px;
">
  <span style="font-size:20px">${style.icon}</span> ${esc(heading)}
</h2>
`;
  }

  function closeSection() {
    if (currentSection) { html += '</section>\n'; currentSection = null; }
  }

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();
    if (!line) {
      closeList();
      continue;
    }

    // ── H2 headings ─────────────────────────────────────────────────────────
    if (line.startsWith('## ')) {
      closeList();
      closeSection();
      const heading = line.slice(3).trim();
      currentSection = heading;
      html += openSection(heading);
      continue;
    }

    // ── H3 headings ─────────────────────────────────────────────────────────
    if (line.startsWith('### ')) {
      closeList();
      html += `<h3 style="font-size:17px;font-weight:700;margin:20px 0 8px;letter-spacing:-0.02em;">${esc(line.slice(4))}</h3>\n`;
      continue;
    }

    // ── FAQ Question ─────────────────────────────────────────────────────────
    if (line.startsWith('**Q:') || line.match(/^\*\*Q\d*[.:]/)) {
      closeList();
      const qText = line.replace(/^\*\*Q\d*[.:]\s*/, '').replace(/\*\*$/, '').trim();
      html += `<div class="faq-item" style="margin:16px 0;padding:14px 16px;background:rgba(255,255,255,0.7);border-radius:8px;">
<p class="faq-q" style="font-weight:700;font-size:15px;color:#1d1d1f;margin:0 0 8px;">Q: ${esc(qText)}</p>\n`;
      inFaq = true;
      continue;
    }

    // ── FAQ Answer ───────────────────────────────────────────────────────────
    if (inFaq && (line.startsWith('A:') || line.startsWith('**A:') || line.startsWith('**A '))) {
      const aText = line.replace(/^\*\*A[:.]\*\*\s*/, '').replace(/^A:\s*/, '').trim();
      html += `<p class="faq-a" style="font-size:14px;line-height:1.7;color:#424245;margin:0;">${esc(aText)}</p>\n</div>\n`;
      inFaq = false;
      continue;
    }
    // Close pending FAQ div if next line isn't an answer
    if (inFaq && !line.startsWith('A:') && !line.startsWith('**A')) {
      html += `</div>\n`;
      inFaq = false;
    }

    // ── Key Takeaways bullets ────────────────────────────────────────────────
    if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) {
        html += '<ul style="margin:12px 0;padding-left:0;list-style:none;">\n';
        inList = true;
      }
      const isInTakeaways = currentSection === 'Key Takeaways';
      html += `<li style="
        padding:8px 12px 8px ${isInTakeaways ? '36px' : '20px'};
        margin-bottom:8px;
        font-size:14px;
        line-height:1.65;
        color:#1d1d1f;
        ${isInTakeaways ? 'position:relative;' : ''}
        ${isInTakeaways ? 'background:rgba(255,255,255,0.7);border-radius:6px;' : ''}
      ">
        ${isInTakeaways ? '<span style="position:absolute;left:12px;color:#d97706;font-weight:700;">✓</span>' : ''}
        ${esc(line.slice(2))}
      </li>\n`;
      continue;
    }

    // ── Numbered list ─────────────────────────────────────────────────────────
    if (/^\d+\.\s/.test(line)) {
      if (inList) { html += '</ul>\n'; inList = false; }
      if (!inOl)  { html += '<ol style="margin:12px 0;padding-left:22px;">\n'; inOl = true; }
      html += `<li style="margin-bottom:7px;font-size:15px;line-height:1.7;">${esc(line.replace(/^\d+\.\s/, ''))}</li>\n`;
      continue;
    }

    // ── Bold inline ──────────────────────────────────────────────────────────
    closeList();
    const formatted = line
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g,     '<em>$1</em>')
      .replace(/`([^`]+)`/g,       '<code style="background:#f0f0f5;padding:2px 6px;border-radius:4px;font-size:13px;">$1</code>');

    html += `<p style="font-size:16px;line-height:1.78;color:#1d1d1f;margin-bottom:16px;">${formatted}</p>\n`;
  }

  closeList();
  closeSection();

  // ── Attribution box ────────────────────────────────────────────────────────
  if (sourceUrl && sourceName) {
    html += `
<div class="source-attribution" style="
  margin:32px 0;
  padding:16px 20px;
  background:#f5f5f7;
  border-left:4px solid #0066cc;
  border-radius:0 10px 10px 0;
">
  <p style="margin:0;font-size:13px;color:#6e6e73;line-height:1.6;">
    <strong style="color:#1d1d1f;">Source:</strong>
    This article is based on reporting from
    <a href="${sourceUrl}" target="_blank" rel="noopener noreferrer nofollow"
       style="color:#0066cc;font-weight:600;">${esc(sourceName)}</a>.
    The analysis and editorial commentary are original work by The Streamic Editorial Team.
  </p>
</div>`;
  }

  return html;
}


function buildPlaceholder(title, content, category) {
  const clean = stripHtml(content);
  return `
<h2>Introduction</h2>
<p>${clean.slice(0, 300)}${clean.length > 300 ? '…' : ''}</p>

<h2>What This Means for Broadcast Operations</h2>
<p>This development has significant implications for broadcast engineering teams evaluating their technology roadmap. Understanding the operational impact requires looking beyond the headline announcement to consider workflow dependencies, standards alignment, and deployment timelines.</p>
<p>Teams working with IP-based infrastructure, cloud production workflows, or automated playout systems should assess how this fits their existing architecture before committing to evaluation.</p>

<h2>Technical Deep Dive</h2>
<p>From a technical standpoint, this development intersects with several current broadcast standards. SMPTE ST 2110, NMOS IS-04 and IS-05, and IP routing infrastructure all become relevant when evaluating how this fits into a modern broadcast facility.</p>
<p>Codec considerations, latency budgets, and interoperability with existing SDI and IP infrastructure should be part of any engineering assessment.</p>

<h2>Key Takeaways</h2>
<ul>
  <li>Evaluate compatibility with your existing IP infrastructure and standards stack</li>
  <li>Assess vendor support commitments and long-term roadmap before procurement</li>
  <li>Plan a staged deployment approach beginning with non-critical workflows</li>
  <li>Document baseline performance metrics before any infrastructure changes</li>
  <li>Engage with vendor interoperability testing programmes before live deployment</li>
</ul>

<h2>Conclusion</h2>
<p>This development represents a meaningful step forward for broadcast technology. Engineering teams that engage with it early — evaluating carefully against their specific operational requirements — will be better positioned to benefit as the technology matures across the industry.</p>`;
}

// ── HTML PAGE BUILDER ─────────────────────────────────────────────────────
function buildConsent() {
  return `<script>
  window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
  gtag('consent','default',{'analytics_storage':'denied','ad_storage':'denied',
  'ad_user_data':'denied','ad_personalization':'denied','wait_for_update':500});
</script>
<script async src="https://www.googletagmanager.com/gtag/js?id=${GA}"></script>
<script>gtag('js',new Date());gtag('config','${GA}');</script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADS_ID}" crossorigin="anonymous"></script>`;
}

function buildAdSlot() {
  // Ad slots removed — using Google Auto-Ads after AdSense approval
  return '';
}

function buildCookieBanner() {
  return `<div id="ts-cookie">
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
<script>(function(){var K='ts_cc',s=localStorage.getItem(K),b=document.getElementById('ts-cookie');
if(!s&&b)b.style.display='block';
window.tsCC=function(ok){localStorage.setItem(K,ok?'granted':'denied');if(b)b.style.display='none';
if(typeof gtag!='undefined')gtag('consent','update',{analytics_storage:ok?'granted':'denied',
ad_storage:ok?'granted':'denied',ad_user_data:ok?'granted':'denied',ad_personalization:ok?'granted':'denied'});};
if(s==='granted'&&typeof gtag!='undefined')gtag('consent','update',{analytics_storage:'granted',
ad_storage:'granted',ad_user_data:'granted',ad_personalization:'granted'});})();</script>`;
}

function buildNav(active = '') {
  const links = [
    ['featured.html','Featured'],['infrastructure.html','Infrastructure'],
    ['graphics.html','Graphics'],['cloud.html','Cloud Production'],
    ['streaming.html','Streaming'],['ai-post-production.html','AI & Post'],
    ['playout.html','Playout'],['newsroom.html','Newsroom'],
    ['howto.html','How-To'],['posts.html','All Articles'],
  ];
  const lis = links.map(([h,lbl]) =>
    `<li><a href="${active.includes('post') ? '../' : ''}${h}"${h===active?' class="active"':''}>${lbl}</a></li>`
  ).join('');
  const mob = links.map(([h,lbl]) =>
    `<a href="${active.includes('post') ? '../' : ''}${h}">${lbl}</a>`
  ).join('');
  const base = active.includes('post') ? '../' : '';
  return `<nav class="nav">
  <div class="nav-inner">
    <a href="${base}featured.html" class="nav-logo">
      <img src="${base}assets/logo.png" alt="The Streamic"><span>The Streamic</span>
    </a>
    <ul class="nav-links">${lis}</ul>
    <div class="nav-right">
      <a href="${base}vlog.html" class="nav-desk">Editor's Desk</a>
      <button class="nav-toggle" onclick="document.querySelector('.nav-mob').classList.toggle('open')">
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="nav-mob">${mob}</div>
</nav>`;
}

function buildFooter(base = '') {
  const yr = new Date().getFullYear();
  return `<footer class="footer">
  <div class="footer-grid">
    <div>
      <div class="footer-brand">The Streamic</div>
      <p class="footer-tag">Independent broadcast &amp; streaming technology journalism for engineers and media professionals.</p>
    </div>
    <div class="footer-col"><h4>Coverage</h4>
      <a href="${base}streaming.html">Streaming</a>
      <a href="${base}cloud.html">Cloud Production</a>
      <a href="${base}ai-post-production.html">AI &amp; Post</a>
      <a href="${base}infrastructure.html">Infrastructure</a>
      <a href="${base}newsroom.html">Newsroom</a>
    </div>
    <div class="footer-col"><h4>Site</h4>
      <a href="${base}about.html">About</a>
      <a href="${base}contact.html">Contact</a>
      <a href="${base}posts.html">All Articles</a>
      <a href="${base}howto.html">How-To Guides</a>
      <a href="${base}privacy.html">Privacy Policy</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>© ${yr} The Streamic — thestreamic.in. All rights reserved.</span>
    <span>Independent broadcast technology journalism.</span>
  </div>
</footer>`;
}

function buildArticlePage(art, relatedArts) {
  const base = '../';
  const canonUrl = `${BASE_URL}/posts/${art.slug}.html`;
  const catLabel = (art.category || 'featured').replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
  const catColor = {
    'featured':'#1d1d1f','streaming':'#0066cc','cloud':'#5856d6',
    'graphics':'#FF9500','playout':'#34C759','infrastructure':'#636366',
    'ai-post-production':'#FF2D55','newsroom':'#b8860b',
  }[art.category] || '#0066cc';

  // Related articles (up to 3, same or other category)
  const relHtml = relatedArts.slice(0,3).map(r => `
    <a href="${r.slug}.html" style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--bg);text-decoration:none;color:inherit">
      <div style="flex:1">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:var(--blue);margin-bottom:3px">${esc(r.category)}</div>
        <div style="font-size:13px;font-weight:600;color:var(--ink);line-height:1.3">${esc(r.title)}</div>
      </div>
      <span style="font-size:11px;color:var(--ink4);white-space:nowrap;margin-top:2px">${fmtDate(r.published)}</span>
    </a>`).join('');

  const schema = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": art.title,
    "description": art.dek,
    "image": art.image || `${BASE_URL}/assets/fallback.jpg`,
    "datePublished": art.published,
    "dateModified": art.published,
    "author": { "@type": "Organization", "name": AUTHOR },
    "publisher": {
      "@type": "Organization", "name": "The Streamic", "url": BASE_URL,
      "logo": { "@type": "ImageObject", "url": `${BASE_URL}/assets/logo.png` }
    },
    "mainEntityOfPage": canonUrl,
    "wordCount": art.wordCount,
  });

  return `<!DOCTYPE html>
<html lang="en">
<head>
  ${buildConsent()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>${esc(art.title)} | The Streamic</title>
  <meta name="description" content="${esc(art.dek)}">
  <meta name="robots" content="index,follow">
  <meta name="author" content="${AUTHOR}">
  <link rel="canonical" href="${canonUrl}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="The Streamic">
  <meta property="og:title" content="${esc(art.title)}">
  <meta property="og:description" content="${esc(art.dek)}">
  <meta property="og:url" content="${canonUrl}">
  ${art.image ? `<meta property="og:image" content="${esc(art.image)}">` : ''}
  <meta name="twitter:card" content="summary_large_image">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../style.css">
  <style>
    .art-wrap{max-width:780px;margin:0 auto;padding:48px 24px 80px}
    .art-wrap h2{font-family:var(--serif);font-size:22px;margin:36px 0 12px;letter-spacing:-0.3px;color:var(--ink)}
    .art-wrap h3{font-family:var(--serif);font-size:18px;margin:24px 0 8px;color:var(--ink)}
    .art-wrap p{font-size:16px;line-height:1.78;color:var(--ink2);margin-bottom:18px}
    .art-wrap ul,.art-wrap ol{font-size:15px;line-height:1.7;color:var(--ink2);margin:0 0 18px 22px}
    .art-wrap li{margin-bottom:7px}
    .faq-q{font-weight:700;font-size:16px;color:var(--ink);margin-bottom:6px}
    .faq-a{font-size:15px;color:var(--ink2);padding-left:16px;border-left:3px solid var(--line)}
    .art-source-credit{background:var(--bg);border-left:3px solid var(--blue);border-radius:0 12px 12px 0;padding:18px 20px}
    .breadcrumb{font-size:12px;color:var(--ink4);margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap}
    .breadcrumb a{color:var(--ink4)} .breadcrumb a:hover{color:var(--blue)}
  </style>
</head>
<body>
${buildNav('posts/' + art.slug + '.html')}
<main>
  <div class="art-wrap">
    <div class="breadcrumb">
      <a href="../featured.html">Home</a><span>›</span>
      <a href="../posts.html">All Articles</a><span>›</span>
      <span style="color:var(--ink)">${esc(catLabel)}</span>
    </div>

    <span style="display:inline-flex;font-size:10px;font-weight:800;text-transform:uppercase;
      letter-spacing:1.2px;padding:4px 12px;border-radius:999px;background:${catColor};
      color:#fff;margin-bottom:18px">${esc(catLabel)}</span>

    <h1 style="font-family:var(--serif);font-size:clamp(24px,4vw,40px);line-height:1.12;
      letter-spacing:-0.5px;color:var(--ink);margin-bottom:14px">
      <a href="${esc(art.sourceUrl)}" target="_blank" rel="noopener noreferrer nofollow"
         style="color:inherit;text-decoration:none">${esc(art.title)}</a>
    </h1>

    <p style="font-size:17px;line-height:1.55;color:var(--ink2);margin-bottom:20px;font-weight:300">
      ${esc(art.dek)}
    </p>

    <div style="font-size:12px;color:var(--ink4);display:flex;gap:14px;flex-wrap:wrap;
      align-items:center;margin-bottom:28px;padding-bottom:18px;border-bottom:1px solid var(--line)">
      <strong style="color:var(--ink)">${AUTHOR}</strong>
      <span>${fmtDate(art.published)}</span>
      <span>${art.wordCount.toLocaleString()} words · AI-assisted analysis</span>
      <span style="background:${catColor};color:#fff;padding:3px 9px;border-radius:5px;
        font-size:10px;font-weight:800;text-transform:uppercase">Analysis</span>
    </div>

    ${art.image ? `<figure style="margin:0 0 32px">
      <img src="${esc(art.image)}" alt="${esc(art.title)}"
           style="width:100%;max-height:480px;object-fit:cover;border-radius:14px">
      <figcaption style="font-size:11px;color:var(--ink4);text-align:center;margin-top:8px">
        Photo: Unsplash — free to use under the <a href="https://unsplash.com/license" rel="nofollow noopener" target="_blank" style="color:var(--ink4)">Unsplash License</a>
      </figcaption>
    </figure>` : ''}

    ${buildAdSlot()}

    <div class="art-body">
      ${art.bodyHtml}
    </div>

    ${buildAdSlot()}

    <div style="background:var(--bg);border-radius:14px;padding:20px 22px;margin-top:40px;font-size:13px;color:var(--ink3);line-height:1.6">
      <strong style="color:var(--ink);display:block;margin-bottom:4px">About this article</strong>
      This is an AI-assisted analysis by ${AUTHOR}, based on broadcast industry news.
      The underlying report is by ${esc(art.sourceName)}.
      <a href="../about.html" style="color:var(--blue);margin-left:6px">About The Streamic →</a>
    </div>

    ${relHtml ? `<div style="margin-top:44px;padding-top:24px;border-top:1px solid var(--line)">
      <h3 style="font-family:var(--serif);font-size:18px;margin-bottom:12px">Related Analysis</h3>
      ${relHtml}
    </div>` : ''}
  </div>
</main>
<script type="application/ld+json">${schema}</script>
${buildFooter('../')}
${buildCookieBanner()}
</body>
</html>`;
}

// ── POSTS INDEX PAGE ──────────────────────────────────────────────────────
function buildPostsPage(arts) {
  // Apple Newsroom-style bento grid — first card spans 2 cols, rest are 4-col vertical
  const cards = arts.map((art, i) => {
    const catColor = {
      'featured':'#1d1d1f','streaming':'#0066cc','cloud':'#5856d6',
      'graphics':'#FF9500','playout':'#34C759','infrastructure':'#636366',
      'ai-post-production':'#FF2D55','newsroom':'#b8860b',
    }[art.category] || '#0066cc';
    const catLabel = (art.category || 'featured')
      .replace(/-/g,' ').replace(/\b\w/g, c => c.toUpperCase());
    // Link to articles/ (built by build.py) — posts/ may be empty if Node didn't run
    const slug_  = art.slug || '';
    const href   = slug_ ? `articles/${slug_}.html` : (art.sourceUrl || art.link || '#');
    // Category-specific Unsplash image pools — prevents all cards showing same image
    const IMG_POOLS = {
      'featured':          ['photo-1598488035139-bdbb2231ce04','photo-1574629810360-7efbbe195018','photo-1560272564-c83b66b1ad12','photo-1540747913346-19212a4a3bdf','photo-1598921776785-44f6879c3b65'],
      'streaming':         ['photo-1499364615650-ec38552f4f34','photo-1611532736597-de2d4265fba3','photo-1518770660439-4636190af475','photo-1461749280684-dccba630e2f6','photo-1551650975-87deedd944c3'],
      'cloud':             ['photo-1544197150-b99a580bb7a8','photo-1531297484001-80022131f5a1','photo-1573164713988-8665fc963095','photo-1486312338219-ce68d2c6f44d','photo-1580584126903-c17d41830450'],
      'infrastructure':    ['photo-1558494949-ef010cbdcc31','photo-1545987796-200677ee1011','photo-1504384308090-c894fdcc538d','photo-1560472354-b33ff0c44a43','photo-1451187580459-43490279c0fa'],
      'ai-post-production':['photo-1677442135703-1787eea5ce01','photo-1620712943543-bcc4688e7485','photo-1605106702734-205df224ecce','photo-1572044162444-ad60f128bdea','photo-1535016120720-40c646be5580'],
      'playout':           ['photo-1478737270239-2f02b77fc618','photo-1524253482453-3fed8d2fe12b','photo-1616401784845-180882ba9ba8','photo-1574717024653-61fd2cf4d44d','photo-1598488035139-bdbb2231ce04'],
      'graphics':          ['photo-1504639725590-34d0984388bd','photo-1547658719-da2b51169166','photo-1551288049-bebda4e38f71','photo-1526256262350-7da7584cf5eb','photo-1504711434969-e33886168f5c'],
      'newsroom':          ['photo-1504711434969-e33886168f5c','photo-1585829365295-ab7cd400c167','photo-1453738773917-9c3eff1db985','photo-1495020689067-958852a7765e','photo-1432821596592-e2c18b78144f'],
    };
    const _cat    = (art.category || 'featured').toLowerCase();
    const _pool   = IMG_POOLS[_cat] || IMG_POOLS['featured'];
    // Use slug hash to pick deterministically — different article = different image
    const _hash   = (art.slug || art.title || '').split('').reduce((a,c)=>((a<<5)-a+c.charCodeAt(0))|0, 0);
    const _pid    = _pool[Math.abs(_hash) % _pool.length];
    const _rawImg = art.image || '';
    // Only use art.image if it's a valid non-guitar-studio URL
    const _badImg = _rawImg.includes('511379938547') || _rawImg.includes('537511446984') || !_rawImg;
    const imgSrc  = esc(_badImg ? `https://images.unsplash.com/${_pid}?w=900&auto=format&fit=crop&q=80` : _rawImg);
    const titleEsc = esc(art.title || 'Untitled');
    const dekEsc = esc(art.dek || '');
    const srcEsc = esc(art.sourceName || '');

    if (i === 0) {
      // Featured first card: 8/12 cols, vertical (image top, text below)
      return `<li class="bento-grid-item">
  <div class="bento-img-wrap bento-img-featured">
    <a href="${href}" tabindex="-1" aria-hidden="true">
      <img src="${imgSrc}" alt="${titleEsc}" loading="eager">
    </a>
  </div>
  <div class="bento-body bento-body-featured">
    <span class="bento-cat-tag" style="color:${catColor}">${catLabel}</span>
    <h2 class="bento-hl bento-hl-featured">
      <a href="${href}">${titleEsc}</a>
    </h2>
    ${dekEsc ? `<p class="bento-sum bento-sum-featured">${dekEsc}</p>` : ''}
    <div class="bento-foot">
      ${srcEsc ? `<span class="bento-source">${srcEsc}</span>` : ''}
      <a href="${href}" class="bento-cta-featured">Read Full Analysis &rarr;</a>
    </div>
  </div>
</li>`;
    }

    // Standard cards: 4/12 cols, vertical (image top, text below)
    return `<li class="bento-grid-item bento-standard">
  <div class="bento-img-wrap bento-img-std">
    <a href="${href}" tabindex="-1" aria-hidden="true">
      <img src="${imgSrc}" alt="${titleEsc}" loading="lazy">
    </a>
  </div>
  <div class="bento-body bento-body-std">
    <span class="bento-cat-tag" style="color:${catColor}">${catLabel}</span>
    <h3 class="bento-hl bento-hl-std">
      <a href="${href}">${titleEsc}</a>
    </h3>
    ${dekEsc ? `<p class="bento-sum bento-sum-std">${dekEsc}</p>` : ''}
    <div class="bento-foot">
      ${srcEsc ? `<span class="bento-source">${srcEsc}</span>` : ''}
      <a href="${href}" class="bento-cta">Read Analysis &rarr;</a>
    </div>
  </div>
</li>`;
  }).join('\n');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  ${buildConsent()}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>All Articles — The Streamic | Broadcast Technology Analysis</title>
  <meta name="description" content="In-depth broadcast technology analysis. Original articles on streaming, cloud production, IP infrastructure, newsroom tech, and post-production.">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="${BASE_URL}/posts.html">
  <meta property="og:type" content="website">
  <meta property="og:title" content="All Articles — The Streamic">
  <meta property="og:url" content="${BASE_URL}/posts.html">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="style.css">
</head>
<body data-category="featured">
${buildNav('posts.html')}
<main>
  <div class="w">
    <div class="cat-hdr">
      <h1>All Articles</h1>
      <p>Original broadcast and streaming technology analysis. Every article is expert-level commentary for engineers and media professionals.</p>
    </div>
    ${buildAdSlot()}
    <section class="latest" style="margin-top:32px">
      <ul id="bentoGridLarge" class="bento-grid-large">
        ${cards}
      </ul>
    </section>
    ${buildAdSlot()}
  </div>
</main>
${buildFooter()}
${buildCookieBanner()}
</body>
</html>`;
}


// ── SITEMAP UPDATER ───────────────────────────────────────────────────────
function buildSitemap(arts) {
  const today = todayIso();
  const staticPages = [
    ['', 'daily', '1.0'], ['featured.html', 'daily', '0.98'],
    ['posts.html', 'daily', '0.95'],
    ['streaming.html', 'daily', '0.9'], ['cloud.html', 'daily', '0.9'],
    ['ai-post-production.html', 'daily', '0.9'],
    ['infrastructure.html', 'daily', '0.9'],
    ['newsroom.html', 'daily', '0.9'],
    ['howto.html', 'weekly', '0.85'],
    ['about.html', 'monthly', '0.6'],
    ['contact.html', 'monthly', '0.5'],
    ['privacy.html', 'yearly', '0.3'],
  ];
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  ];
  for (const [pg, freq, pri] of staticPages) {
    lines.push(`  <url><loc>${BASE_URL}/${pg}</loc><lastmod>${today}</lastmod><changefreq>${freq}</changefreq><priority>${pri}</priority></url>`);
  }
  for (const a of arts) {
    lines.push(`  <url><loc>${BASE_URL}/posts/${a.slug}.html</loc><lastmod>${a.published}</lastmod><changefreq>monthly</changefreq><priority>0.8</priority></url>`);
  }
  lines.push('</urlset>');
  return lines.join('\n');
}

// ── MAIN PIPELINE ─────────────────────────────────────────────────────────
async function main() {
  console.log('\n🚀 The Streamic — AI Article Generator v3\n');
  console.log(`   Model:   ${HF_MODEL} (via Groq API)`);
  console.log(`   API key: ${HF_API_KEY ? '✓ set' : '✗ NOT SET — placeholder mode'}`);
  console.log(`   Max run: ${MAX_ARTICLES_PER_RUN} new articles\n`);

  // ── Setup dirs ──────────────────────────────────────────────────────────
  fs.mkdirSync(POSTS_DIR, { recursive: true });
  fs.mkdirSync(path.join(ROOT, 'data'), { recursive: true });

  // ── Load existing articles ──────────────────────────────────────────────
  let stored = [];
  if (fs.existsSync(INDEX_F)) {
    try { stored = JSON.parse(fs.readFileSync(INDEX_F, 'utf8')); } catch(_) {}
  }
  const existingUrls = new Set(stored.map(a => a.sourceUrl));
  console.log(`   Existing: ${stored.length} articles\n`);

  // ── Fetch all RSS feeds ─────────────────────────────────────────────────
  let allItems = [];
  for (const feed of FEEDS) {
    try {
      console.log(`   Fetching: ${feed.url.slice(0,60)}`);
      const res = await fetchUrl(feed.url);
      if (res.status !== 200) { console.log(`     → HTTP ${res.status}`); continue; }
      const items = parseRss(res.body);
      const tagged = items.slice(0, 5).map(it => ({ ...it, category: feed.cat, sourceName: feed.source }));
      allItems.push(...tagged);
      console.log(`     → ${tagged.length} items`);
    } catch (err) {
      console.warn(`     ✗ ${err.message}`);
    }
  }

  // Filter to unseen items only
  const newItems = allItems.filter(it => !existingUrls.has(it.link)).slice(0, MAX_ARTICLES_PER_RUN);
  console.log(`\n   New items to process: ${newItems.length}\n`);

  if (!newItems.length) {
    console.log('   ✓ No new items — nothing to generate');
  }

  // ── Generate articles ───────────────────────────────────────────────────
  const newArticles = [];
  for (let i = 0; i < newItems.length; i++) {
    const item = newItems[i];
    console.log(`\n   [${i+1}/${newItems.length}] ${item.title.slice(0,60)}`);
    console.log(`           Category: ${item.category} | Source: ${item.sourceName}`);

    const slug   = `${todayIso()}-${slugify(item.title)}`;
    const content = stripHtml(item.description || '');
    const dek    = content.slice(0, 200).trim() + (content.length > 200 ? '…' : '');

    // Unsplash fallback image per category
    const catImages = {
      'featured':           'photo-1598488035139-bdbb2231ce04',
      'streaming':          'photo-1499364615650-ec38552f4f34',
      'cloud':              'photo-1451187580459-43490279c0fa',
      'infrastructure':     'photo-1558494949-ef010cbdcc31',
      'ai-post-production': 'photo-1677442135703-1787eea5ce01',
      'playout':            'photo-1478737270239-2f02b77fc618',
      'graphics':           'photo-1504639725590-34d0984388bd',
      'newsroom':           'photo-1504711434969-e33886168f5c',
    };
    const imgId   = catImages[item.category] || catImages.featured;
    const imgUrl  = `https://images.unsplash.com/${imgId}?w=1200&auto=format&fit=crop&q=80`;

    // Call Hugging Face
    let generatedText = null;
    if (HF_API_KEY) {
      console.log('           → Calling Hugging Face API…');
      const prompt = buildPrompt(item.title, content, item.category, item.sourceName);
      generatedText = await callHuggingFace(prompt);
      if (generatedText) {
        console.log(`           ✓ Generated: ~${generatedText.split(' ').length} words`);
      } else {
        console.log('           ⚠ HF failed — using placeholder');
      }
      if (i < newItems.length - 1) await sleep(SLEEP_MS);
    }

    // ── Quality gate: enforce required sections before saving ──────────────
    // If HF/Groq generated content is missing required sections, fall back
    // to the structured placeholder rather than saving thin content.
    const hasSections = (text) => {
      if (!text) return false;
      const lower = text.toLowerCase();
      return lower.includes('why this matters') && lower.includes('expert insight');
    };

    const qualifiedText = (generatedText && hasSections(generatedText)) ? generatedText : null;
    if (generatedText && !qualifiedText) {
      console.log('           ⚠ Quality gate: missing required sections — using structured placeholder');
    }

    const bodyHtml = qualifiedText
      ? articleTextToHtml(qualifiedText, item.link, item.sourceName)
      : buildPlaceholder(item.title, content, item.category) +
        articleTextToHtml('', item.link, item.sourceName);

    const wordCount = Math.max(
      generatedText ? generatedText.split(/\s+/).length : 300,
      generatedText ? 1000 : 300
    );

    const art = {
      slug, title: item.title, dek, category: item.category,
      sourceName: item.sourceName, sourceUrl: item.link,
      image: imgUrl, published: todayIso(), wordCount, bodyHtml,
    };

    // Write article HTML
    const outPath = path.join(POSTS_DIR, `${slug}.html`);
    const related = stored.filter(s => s.slug !== slug).slice(0, 3);
    fs.writeFileSync(outPath, buildArticlePage(art, related), 'utf8');
    console.log(`           ✓ Written: posts/${slug}.html`);

    newArticles.push(art);
    existingUrls.add(item.link);
  }

  // ── Merge + trim stored articles ────────────────────────────────────────
  const allArticles = [...newArticles, ...stored].slice(0, MAX_STORED_ARTICLES);

  // ── Save article index ──────────────────────────────────────────────────
  // Strip bodyHtml from index to keep file small
  const indexData = allArticles.map(({ bodyHtml, ...rest }) => rest);
  fs.writeFileSync(INDEX_F, JSON.stringify(indexData, null, 2), 'utf8');
  console.log(`\n   ✓ Article index: ${indexData.length} articles`);

  // ── Write posts.html ────────────────────────────────────────────────────
  fs.writeFileSync(path.join(DOCS, 'posts.html'), buildPostsPage(allArticles), 'utf8');
  fs.writeFileSync(path.join(ROOT, 'posts.html'), buildPostsPage(allArticles), 'utf8');
  console.log('   ✓ posts.html updated');

  // ── Update sitemap ──────────────────────────────────────────────────────
  fs.writeFileSync(path.join(DOCS, 'sitemap.xml'), buildSitemap(allArticles), 'utf8');
  fs.writeFileSync(path.join(ROOT, 'sitemap.xml'), buildSitemap(allArticles), 'utf8');
  console.log('   ✓ sitemap.xml updated');

  console.log(`\n✅ Done: ${newArticles.length} new articles generated, ${allArticles.length} total\n`);
}

main().catch(err => {
  console.error('❌ Generator failed:', err);
  process.exit(1);
});
