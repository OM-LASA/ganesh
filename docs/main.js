/* THE STREAMIC · main.js
   ─────────────────────────────────────────────────────────────────
   v2 — complete rewrite with all fixes
   ─────────────────────────────────────────────────────────────────
   1. window.__tsMainLoaded  guard against duplicate <script> tags
   2. initNav() fires on DOMContentLoaded INDEPENDENTLY of boot()
      - Esc key, outside-click close, link-tap close, aria state
      - Layers over inline onclick (belt + suspenders approach)
   3. boot() handles bento grid only — grid errors never block nav
   4. Load More fully working
   5. Search modal — instant client-side search from JSON
   6. Archive modal — all articles by month + category filter
   7. Keyboard: "/" opens search, Esc closes any modal
*/
(() => {
  'use strict';

  /* ── 1. Double-execution guard ──────────────────────────────── */
  if (window.__tsMainLoaded) return;
  window.__tsMainLoaded = true;

  const BUST  = Date.now();
  const BATCH = 12;

  let allItems   = [];
  let shownCount = 0;
  let lazyObs    = null;

  /* ── Fallback images by category ─────────────────────────────── */
  const FALLBACK = {
    featured:             'https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=900&q=80',
    newsroom:             'https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=900&q=80',
    playout:              'https://images.unsplash.com/photo-1478737270239-2f02b77fc618?w=900&q=80',
    infrastructure:       'https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=900&q=80',
    graphics:             'https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=900&q=80',
    cloud:                'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=900&q=80',
    streaming:            'https://images.unsplash.com/photo-1499364615650-ec38552f4f34?w=900&q=80',
    'ai-post-production': 'https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=900&q=80',
  };

  /* ── Helpers ────────────────────────────────────────────────── */
  function getImg(item) {
    const src = item.image_url || item.image || '';
    if (src && src.startsWith('http')) return src;
    return FALLBACK[(item.category || 'featured').toLowerCase().trim()] || FALLBACK.featured;
  }
  function getUrl(item)    { return item.slug ? 'articles/' + item.slug + '.html' : (item.url || item.link || item.source_url || '#'); }
  function getSrcUrl(item) { return item.source_url || item.url || item.link || '#'; }
  function isExt(url)      { return /^https?:\/\//.test(url); }

  /* ── Lazy image observer ─────────────────────────────────────── */
  function setupLazy() {
    if (!('IntersectionObserver' in window)) return null;
    return new IntersectionObserver((entries, obs) => {
      entries.forEach(e => {
        if (e.isIntersecting && e.target.dataset.src) {
          e.target.src = e.target.dataset.src;
          e.target.removeAttribute('data-src');
          obs.unobserve(e.target);
        }
      });
    }, { rootMargin: '80px', threshold: 0.01 });
  }
  function mkImg(url, alt, eager) {
    if (eager) return `<img src="${url}" alt="${alt}" loading="eager">`;
    if (lazyObs) return `<img data-src="${url}" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt="${alt}" loading="lazy" class="lz">`;
    return `<img src="${url}" alt="${alt}" loading="lazy">`;
  }
  function obsImgs(el) {
    if (!lazyObs) return;
    el.querySelectorAll('img.lz').forEach(img => lazyObs.observe(img));
  }

  /* ── Card builders ───────────────────────────────────────────── */
  function _srcTxt(item) {
    return (item.source_domain || item.source || '')
      .replace(/https?:\/\//, '').replace('www.', '').split('/')[0].toUpperCase();
  }
  function _catLbl(item) {
    return (item.category || 'featured').toLowerCase().trim()
      .replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function buildFeatured(item) {
    const li = document.createElement('li');
    li.className = 'bento-grid-item';
    const iUrl = getUrl(item), sUrl = getSrcUrl(item), img = getImg(item);
    const title  = (item.title || 'Untitled').trim();
    const tHref  = isExt(sUrl) ? sUrl : iUrl;
    const tAttr  = isExt(tHref) ? ' target="_blank" rel="noopener noreferrer nofollow"' : '';
    const cHref  = item.slug ? iUrl : sUrl;
    const cAttr  = isExt(cHref) ? ' target="_blank" rel="noopener noreferrer nofollow"' : '';
    li.innerHTML =
      `<div class="bento-img-wrap bento-img-featured">` +
        `<a href="${cHref}"${cAttr} tabindex="-1" aria-hidden="true">${mkImg(img, title, true)}</a>` +
      `</div>` +
      `<div class="bento-body bento-body-featured">` +
        `<span class="bento-cat-tag">${_catLbl(item)}</span>` +
        `<h2 class="bento-hl bento-hl-featured"><a href="${tHref}"${tAttr}>${title}</a></h2>` +
        (item.card_summary && item.slug ? `<a href="articles/${item.slug}.html" class="bento-groq-badge">✦ Read Technical Analysis</a>` : '') +
        `<div class="bento-foot">` +
          (_srcTxt(item) ? `<span class="bento-source">${_srcTxt(item)}</span>` : '') +
          `<a href="${cHref}"${cAttr} class="bento-cta-featured">${item.slug ? 'Read Full Analysis →' : 'View Original →'}</a>` +
        `</div>` +
      `</div>`;
    return li;
  }

  function buildStandard(item) {
    const li = document.createElement('li');
    li.className = 'bento-grid-item bento-standard';
    const iUrl = getUrl(item), sUrl = getSrcUrl(item), img = getImg(item);
    const title = (item.title || 'Untitled').trim();
    const tHref = isExt(sUrl) ? sUrl : iUrl;
    const tAttr = isExt(tHref) ? ' target="_blank" rel="noopener noreferrer nofollow"' : '';
    const cHref = item.slug ? iUrl : sUrl;
    const cAttr = isExt(cHref) ? ' target="_blank" rel="noopener noreferrer nofollow"' : '';
    li.innerHTML =
      `<div class="bento-img-wrap bento-img-std">` +
        `<a href="${cHref}"${cAttr} tabindex="-1" aria-hidden="true">${mkImg(img, title, false)}</a>` +
      `</div>` +
      `<div class="bento-body bento-body-std">` +
        `<span class="bento-cat-tag">${_catLbl(item)}</span>` +
        `<h3 class="bento-hl bento-hl-std"><a href="${tHref}"${tAttr}>${title}</a></h3>` +
        `<div class="bento-foot">` +
          (_srcTxt(item) ? `<span class="bento-source">${_srcTxt(item)}</span>` : '') +
          `<a href="${cHref}"${cAttr} class="bento-cta">${item.slug ? 'Read Full Article →' : 'View Source →'}</a>` +
        `</div>` +
      `</div>`;
    return li;
  }

  /* ── Batch render + Load More ────────────────────────────────── */
  function renderBatch(grid) {
    const slice = allItems.slice(shownCount, shownCount + BATCH);
    if (!slice.length) { hideMore(); return; }
    const frag = document.createDocumentFragment();
    slice.forEach((item, idx) => frag.appendChild(
      (shownCount + idx === 0) ? buildFeatured(item) : buildStandard(item)
    ));
    grid.appendChild(frag);
    obsImgs(grid);
    shownCount += slice.length;
    if (shownCount >= allItems.length) hideMore();
  }

  function hideMore() {
    const b = document.getElementById('ts-more');
    if (b && b.parentElement) b.parentElement.style.display = 'none';
  }

  function addMoreBtn(grid) {
    if (document.getElementById('ts-more')) return;
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin:40px 0;text-align:center';
    const btn = document.createElement('button');
    btn.id = 'ts-more';
    btn.textContent = 'Load More Stories';
    btn.style.cssText = 'padding:13px 44px;border-radius:999px;border:1.5px solid var(--line);background:var(--white);color:var(--ink);font-size:14px;font-weight:600;cursor:pointer;font-family:var(--font);letter-spacing:-0.02em;transition:background .15s,color .15s,border-color .15s';
    btn.onmouseover = () => { btn.style.background = 'var(--ink)'; btn.style.color = '#fff'; btn.style.borderColor = 'var(--ink)'; };
    btn.onmouseout  = () => { btn.style.background = 'var(--white)'; btn.style.color = 'var(--ink)'; btn.style.borderColor = 'var(--line)'; };
    btn.onclick = () => renderBatch(grid);
    wrap.appendChild(btn);
    grid.parentElement.appendChild(wrap);
  }

  /* ── Data loading ────────────────────────────────────────────── */
  async function loadNews() {
    for (const p of [`data/generated_articles.json?v=${BUST}`, `/data/generated_articles.json?v=${BUST}`]) {
      try {
        const r = await fetch(p); if (!r.ok) continue;
        const raw = await r.json();
        if (Array.isArray(raw)) return { featured_priority: raw.slice(0, 6), items: raw.slice(6) };
        if (raw.items !== undefined || raw.featured_priority !== undefined) return raw;
        return { featured_priority: raw.slice ? raw.slice(0, 6) : [], items: raw.slice ? raw.slice(6) : [] };
      } catch (_) {}
    }
    /* Editorial-only data mode.
       Homepage cards come from generated_articles.json via the editorial loader above. */
    throw new Error('No data source reachable');
  }

  function filterCat(items, cat) {
    if (!cat || cat === 'featured') return items;
    return items.filter(it => (it.category || '').toLowerCase().trim() === cat);
  }

  function interleave(items) {
    const g = {};
    items.forEach(it => { const k = it.source_domain || it.source || 'x'; (g[k] = g[k] || []).push(it); });
    const groups = Object.values(g), out = [];
    for (let i = 0; out.length < items.length; i++) {
      let ok = false;
      groups.forEach(arr => { if (i < arr.length) { out.push(arr[i]); ok = true; } });
      if (!ok) break;
    }
    return out;
  }

  /* ── 2. Mobile nav (runs independently of boot) ──────────────── *
   *  initNav() fires on DOMContentLoaded.                          *
   *  The inline onclick on each button handles the basic toggle.   *
   *  initNav() adds: Esc, outside-click, link-tap, aria state.     */
  function initNav() {
    const tog = document.querySelector('.nav-toggle');
    const mob = document.querySelector('.nav-mob');
    if (!tog || !mob) return;

    const openMenu  = () => { mob.classList.add('open');    document.body.classList.add('menu-open');    tog.setAttribute('aria-expanded', 'true');  };
    const closeMenu = () => { mob.classList.remove('open'); document.body.classList.remove('menu-open'); tog.setAttribute('aria-expanded', 'false'); };

    /* Replace inline onclick with full-featured handler */
    tog.onclick = e => { e.stopPropagation(); mob.classList.contains('open') ? closeMenu() : openMenu(); };

    /* Close on outside click / tap */
    document.addEventListener('click', e => {
      if (mob.classList.contains('open') && !mob.contains(e.target) && !tog.contains(e.target)) closeMenu();
    });

    /* Close when any mobile nav link is tapped */
    mob.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));

    /* Set initial aria state */
    tog.setAttribute('aria-expanded', mob.classList.contains('open') + '');
  }

  /* ── 5. Search modal ─────────────────────────────────────────── */
  let _searchIdx = null;

  async function getSearchIdx() {
    if (_searchIdx) return _searchIdx;
    for (const p of ['data/generated_articles.json', '/data/generated_articles.json']) {
      try {
        const r = await fetch(p); if (!r.ok) continue;
        const raw = await r.json();
        const items = Array.isArray(raw) ? raw : [...(raw.featured_priority || []), ...(raw.items || [])];
        _searchIdx = items.filter(a => a.slug && a.title).map(a => ({
          slug:     a.slug,
          title:    (a.title || '').trim(),
          dek:      (a.dek || a.meta_description || '').trim(),
          cat:      (a.cat_label || a.category || '').trim(),
          date:     (a.published || '').slice(0, 10),
          img:      a.image_url || '',
          _s:       ((a.title||'') + ' ' + (a.dek||'') + ' ' + (a.category||'')).toLowerCase(),
        }));
        return _searchIdx;
      } catch (_) {}
    }
    return (_searchIdx = []);
  }

  function doSearch(q, idx) {
    if (!q.trim()) return [];
    const terms = q.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return idx.filter(a => terms.every(t => a._s.includes(t))).slice(0, 28);
  }

  function renderSearchResults(results, q) {
    const el = document.getElementById('ts-sr');
    if (!el) return;
    if (!q.trim()) { el.innerHTML = ''; return; }
    if (!results.length) {
      el.innerHTML = '<p class="ts-se">No results for &ldquo;' + q + '&rdquo;</p>';
      return;
    }
    el.innerHTML = results.map(a =>
      `<a class="ts-sri" href="articles/${a.slug}.html">` +
        (a.img
          ? `<img class="ts-sri-img" src="${a.img}" alt="" loading="lazy" onerror="this.style.display='none'">`
          : '<div class="ts-sri-img ts-sri-ph"></div>') +
        `<div class="ts-sri-body">` +
          (a.cat ? `<span class="ts-sri-cat">${a.cat}</span>` : '') +
          `<span class="ts-sri-title">${a.title}</span>` +
          (a.dek ? `<span class="ts-sri-dek">${a.dek.slice(0, 110)}${a.dek.length > 110 ? '…' : ''}</span>` : '') +
          (a.date ? `<span class="ts-sri-date">${a.date}</span>` : '') +
        `</div>` +
      `</a>`
    ).join('');
  }

  function openSearch() {
    const ov = document.getElementById('ts-search-ov');
    if (!ov) return;
    ov.style.display = 'flex'; // override inline display:none
    ov.classList.add('open');
    document.body.classList.add('ts-modal-open');
    const inp = document.getElementById('ts-si');
    if (inp) { inp.value = ''; inp.focus(); }
    const sr = document.getElementById('ts-sr'); if (sr) sr.innerHTML = '';
    getSearchIdx(); // pre-warm index
  }

  function closeSearch() {
    const ov = document.getElementById('ts-search-ov');
    if (ov) { ov.style.display = 'none'; ov.classList.remove('open'); document.body.classList.remove('ts-modal-open'); }
  }

  function injectSearchUI() {
    // Search button in nav-right
    if (!document.getElementById('ts-search-btn')) {
      const navRight = document.querySelector('.nav-right');
      if (navRight) {
        const btn = document.createElement('button');
        btn.id = 'ts-search-btn';
        btn.setAttribute('aria-label', 'Search');
        btn.title = 'Search  /';
    btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;background:none;border:none;cursor:pointer;padding:6px;border-radius:8px;color:var(--ink3);flex-shrink:0;width:32px;height:32px;overflow:hidden';
        btn.innerHTML = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7.5"/><line x1="20.5" y1="20.5" x2="16.3" y2="16.3"/></svg>`;
        btn.onclick = openSearch;
        const tog = navRight.querySelector('.nav-toggle');
        navRight.insertBefore(btn, tog);
      }
    }
    // Search modal overlay
    if (document.getElementById('ts-search-ov')) return;
    const ov = document.createElement('div');
    ov.id = 'ts-search-ov';
    ov.style.cssText = 'display:none;position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.55);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);padding:80px 16px 16px;align-items:flex-start;justify-content:center;overflow-y:auto;box-sizing:border-box;';
    ov.setAttribute('role', 'dialog');
    ov.setAttribute('aria-label', 'Search');
    ov.innerHTML =
      `<div class="ts-sbox" style="background:#fff;border-radius:16px;width:100%;max-width:680px;box-shadow:0 24px 60px rgba(0,0,0,.18);overflow:hidden;display:flex;flex-direction:column;">` +
        `<div class="ts-shead" style="display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid #e5e5e5;">` +
          `<svg class="ts-sico" width="20" height="20" style="width:20px;height:20px;min-width:20px;flex-shrink:0;color:#86868b;display:block" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="7.5"/><line x1="20.5" y1="20.5" x2="16.3" y2="16.3"/></svg>` +
          `<input id="ts-si" type="search" placeholder="Search articles, topics, technology…" autocomplete="off" spellcheck="false" style="flex:1;border:none;outline:none;font-size:16px;font-family:inherit;background:transparent;color:#1d1d1f;min-width:0;">` +
          `<button class="ts-sclose" aria-label="Close" style="background:none;border:none;cursor:pointer;font-size:18px;color:#86868b;padding:4px 6px;flex-shrink:0;" onclick="(function(){var o=document.getElementById('ts-search-ov');if(o){o.style.display='none';o.classList.remove('open');document.body.classList.remove('ts-modal-open');}})()">&#10005;</button>` +
        `</div>` +
        `<div id="ts-sr" class="ts-sr"></div>` +
        `<div class="ts-shint">Press <kbd>Esc</kbd> to close &nbsp;·&nbsp; Press <kbd>/</kbd> from anywhere to open</div>` +
      `</div>`;
    document.body.appendChild(ov);

    // Backdrop click closes
    ov.addEventListener('click', e => { if (e.target === ov) closeSearch(); });

    // Clicking a result closes the modal
    ov.addEventListener('click', e => { if (e.target.closest('.ts-sri')) closeSearch(); });

    // Debounced search
    let deb;
    document.getElementById('ts-si').addEventListener('input', () => {
      clearTimeout(deb);
      deb = setTimeout(async () => {
        const q = document.getElementById('ts-si').value;
        const idx = await getSearchIdx();
        renderSearchResults(doSearch(q, idx), q);
      }, 160);
    });
  }

  /* ── 6. Archive modal ────────────────────────────────────────── */
  let _archiveData = null;

  async function getArchiveData() {
    if (_archiveData) return _archiveData;
    for (const p of ['data/generated_articles.json', '/data/generated_articles.json']) {
      try {
        const r = await fetch(p); if (!r.ok) continue;
        const raw = await r.json();
        const items = Array.isArray(raw) ? raw : [...(raw.featured_priority || []), ...(raw.items || [])];
        _archiveData = items
          .filter(a => a.slug && a.title)
          .sort((a, b) => (b.published || '').localeCompare(a.published || ''));
        return _archiveData;
      } catch (_) {}
    }
    return (_archiveData = []);
  }

  function _fmtFull(d)  { try { return new Date(d).toLocaleDateString('en-IE', { day:'numeric', month:'long', year:'numeric' }); } catch(_){ return d||''; } }
  function _fmtMonth(d) { try { return new Date(d).toLocaleDateString('en-IE', { month:'long',  year:'numeric' }); }             catch(_){ return (d||'').slice(0,7); } }

  function renderArchive(items, catFilter) {
    const el = document.getElementById('ts-arc-body');
    if (!el) return;
    const list = catFilter ? items.filter(a => (a.category || '').toLowerCase() === catFilter) : items;
    if (!list.length) { el.innerHTML = '<p class="ts-se">No articles found.</p>'; return; }

    const months = {};
    list.forEach(a => { const m = _fmtMonth(a.published); (months[m] = months[m] || []).push(a); });

    el.innerHTML = Object.entries(months).map(([m, arts]) =>
      `<div class="ts-arcm">` +
        `<h3 class="ts-arcm-hdr">${m}<span class="ts-arcm-ct">${arts.length}</span></h3>` +
        `<ul class="ts-arcl">` +
          arts.map(a =>
            `<li><a class="ts-arcli" href="articles/${a.slug}.html">` +
              `<span class="ts-arcli-cat">${(a.cat_label || a.category || '').replace(/-/g,' ')}</span>` +
              `<span class="ts-arcli-title">${a.title}</span>` +
              `<time class="ts-arcli-date">${_fmtFull(a.published)}</time>` +
            `</a></li>`
          ).join('') +
        `</ul>` +
      `</div>`
    ).join('');
  }

  function openArchive() {
    const ov = document.getElementById('ts-arc-ov');
    if (!ov) return;
    ov.style.display = 'flex'; // override inline display:none
    ov.classList.add('open');
    document.body.classList.add('ts-modal-open');
    getArchiveData().then(items => {
      renderArchive(items, '');
      const sel = document.getElementById('ts-arc-sel');
      if (sel && sel.options.length <= 1) {
        [...new Set(items.map(a => (a.category||'').toLowerCase()).filter(Boolean))].sort()
          .forEach(c => {
            const o = document.createElement('option');
            o.value = c;
            o.textContent = c.replace(/-/g,' ').replace(/\b\w/g, x => x.toUpperCase());
            sel.appendChild(o);
          });
      }
    });
  }

  function closeArchive() {
    const ov = document.getElementById('ts-arc-ov');
    if (ov) { ov.style.display = 'none'; ov.classList.remove('open'); document.body.classList.remove('ts-modal-open'); }
  }

  function injectArchiveUI() {
    // Archive link in mobile nav (appended after existing links)
    const mob = document.querySelector('.nav-mob');
    if (mob && !mob.querySelector('.ts-arc-navbtn')) {
      const a = document.createElement('a');
      a.className = 'ts-arc-navbtn';
      a.href = '#';
      a.textContent = '📁 Article Archive';
      a.onclick = e => {
        e.preventDefault();
        mob.classList.remove('open');
        document.body.classList.remove('menu-open');
        openArchive();
      };
      mob.appendChild(a);
    }

    // Archive modal overlay
    if (document.getElementById('ts-arc-ov')) return;
    const ov = document.createElement('div');
    ov.id = 'ts-arc-ov';
    ov.style.cssText = 'display:none;position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.55);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);padding:80px 16px 16px;align-items:flex-start;justify-content:center;overflow-y:auto;box-sizing:border-box;';
    ov.setAttribute('role', 'dialog');
    ov.setAttribute('aria-label', 'Article Archive');
    ov.innerHTML =
      `<div class="ts-arcbox" style="background:#fff;border-radius:16px;width:100%;max-width:760px;max-height:85vh;box-shadow:0 24px 60px rgba(0,0,0,.18);overflow:hidden;display:flex;flex-direction:column;">` +
        `<div class="ts-archdr">` +
          `<h2 class="ts-arctitle">Article Archive</h2>` +
          `<div class="ts-arccontrols">` +
            `<select id="ts-arc-sel" class="ts-arcsel"><option value="">All Categories</option></select>` +
            `<button class="ts-arcclose" aria-label="Close archive" style="background:none;border:none;cursor:pointer;font-size:18px;color:#86868b;padding:4px 6px;" onclick="(function(){var o=document.getElementById('ts-arc-ov');if(o){o.style.display='none';o.classList.remove('open');document.body.classList.remove('ts-modal-open');}})()">&#10005;</button>` +
          `</div>` +
        `</div>` +
        `<div id="ts-arc-body" class="ts-arc-body"><div class="ts-arcload">Loading archive…</div></div>` +
      `</div>`;
    document.body.appendChild(ov);

    ov.addEventListener('click', e => { if (e.target === ov) closeArchive(); });
    ov.addEventListener('click', e => { if (e.target.closest('.ts-arcli')) closeArchive(); });
    document.getElementById('ts-arc-sel').addEventListener('change', e => {
      getArchiveData().then(items => renderArchive(items, e.target.value));
    });
  }

  /* ── 7. Keyboard shortcuts ───────────────────────────────────── */
  function initKeyboard() {
    document.addEventListener('keydown', e => {
      const tag = document.activeElement ? document.activeElement.tagName : '';
      // '/' opens search (unless focus is in an input)
      if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(tag)) {
        e.preventDefault();
        openSearch();
      }
      // Esc closes any open modal or menu
      if (e.key === 'Escape') {
        closeSearch();
        closeArchive();
        const mob = document.querySelector('.nav-mob');
        const tog = document.querySelector('.nav-toggle');
        if (mob && mob.classList.contains('open')) {
          mob.classList.remove('open');
          document.body.classList.remove('menu-open');
          if (tog) tog.setAttribute('aria-expanded', 'false');
        }
      }
    });
  }

  /* ── 3. Grid boot ────────────────────────────────────────────── */
  async function boot() {
    lazyObs = setupLazy();
    const grid = document.getElementById('bentoGridLarge');
    if (!grid) return;

    const cat = (document.body.dataset.category || '').toLowerCase().trim();
    grid.innerHTML = '<li class="bento-loading">Loading latest broadcast news\u2026</li>';

    try {
      const data  = await loadNews();
      const pool  = [...(data.featured_priority || []), ...(data.items || [])];
      const valid = pool.filter(it => it.slug || it.url || it.link);

      allItems = (!cat || cat === 'featured')
        ? interleave(valid)
        : interleave(filterCat(valid, cat)).slice(1);

      if (!allItems.length) {
        grid.innerHTML = '<li class="bento-loading">No content yet. Check back soon.</li>';
        return;
      }
      grid.innerHTML = '';
      renderBatch(grid);
      if (allItems.length > BATCH) addMoreBtn(grid);

    } catch (err) {
      console.error('[Streamic]', err);
      grid.innerHTML = '<li class="bento-loading">Live feed temporarily unavailable.</li>';
    }
  }

  /* ── Entry point ─────────────────────────────────────────────── *
   * initNav fires FIRST (sync DOM) — never blocked by async data.  *
   * All UI injection + boot fires after DOMContentLoaded.          */
  function init() {
    initNav();
    injectSearchUI();
    injectArchiveUI();
    initKeyboard();
    boot();
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', init)
    : init();

})();
