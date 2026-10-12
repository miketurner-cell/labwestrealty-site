/* listings-filter.js — minimal client-side filter for Avalon /listings/
 *
 * Shipped 2026-05-15 to close the same critical consumer bug Gander
 * shipped earlier today (commit dfaf23758): the homepage search form
 * posts ?q=<text> to /listings/, but Avalon /listings/ is the simpler
 * server-rendered chip+grid pattern with no filter UI. Pre-fix, every
 * homepage-search attempt landed on the unfiltered 1439-card page.
 *
 * Avalon architecture is simpler than Gander's discovery shell — all
 * cards are inline HTML (no JS data fetch). This script:
 *   1. Reads ?q= on page load
 *   2. If MLS_RE (6-8 digits) → instant redirect to the matching card's URL
 *   3. Otherwise → walks .lst-card elements, hides ones whose textContent
 *      (address + city + MLS#) doesn't include the query substring
 *   4. Inserts a results banner at top of .lst-card-grid with count +
 *      Clear button (removes ?q= + restores all cards)
 *
 * Convention #74 fail-safe: if there's no ?q= or no .lst-card-grid in
 * the DOM, the script does nothing and the page renders unchanged.
 *
 * Convention #82 cache-bust: script loaded with ?v=20260515-search-fix
 * stamp so existing Netlify max-age=14400 caches don't keep serving
 * an old version on the next fix.
 */
(function () {
  'use strict';

  var MLS_RE = /^\s*\d{6,8}\s*$/;

  function readQ() {
    try {
      return ((new URL(window.location.href)).searchParams.get('q') || '').trim();
    } catch (e) {
      return '';
    }
  }

  function applyTextFilter(q) {
    var qLower = q.toLowerCase();
    var cards = document.querySelectorAll('.lst-card-grid .lst-card');
    var visible = 0;
    cards.forEach(function (card) {
      // textContent collapses whitespace via .replace, and includes the
      // address/city/MLS# text from .lst-card-addr/.lst-card-city/.lst-card-mls
      // children (which is what we want to match against).
      var hay = card.textContent.replace(/\s+/g, ' ').toLowerCase();
      if (hay.indexOf(qLower) === -1) {
        card.style.display = 'none';
      } else {
        card.style.display = '';
        visible += 1;
      }
    });
    return { visible: visible, total: cards.length };
  }

  function showAllCards() {
    document.querySelectorAll('.lst-card-grid .lst-card').forEach(function (card) {
      card.style.display = '';
    });
  }

  function findMlsCardUrl(mls) {
    // MLS-shaped query: find a card whose href contains the MLS number,
    // return its detail-page URL for instant redirect.
    var cards = document.querySelectorAll('.lst-card-grid .lst-card .lst-card-link');
    for (var i = 0; i < cards.length; i++) {
      var href = cards[i].getAttribute('href') || '';
      if (href.indexOf('-' + mls + '.html') !== -1) {
        return href;
      }
    }
    return null;
  }

  function buildBanner(q, visible, total) {
    var banner = document.createElement('div');
    banner.id = 'lst-filter-banner';
    banner.style.cssText = (
      'background: var(--dark-card, #1a1a1a);' +
      'border: 1px solid var(--accent-red, #EA002A);' +
      'border-radius: 6px;' +
      'padding: 16px 20px;' +
      'margin: 0 auto 24px;' +
      'max-width: 1200px;' +
      'color: #fff;' +
      'font-family: Roboto, sans-serif;' +
      'display: flex;' +
      'gap: 16px;' +
      'align-items: center;' +
      'justify-content: space-between;' +
      'flex-wrap: wrap;'
    );

    var resultText = (visible === 0)
      ? ('No listings match “' + escHtml(q) + '”. Try a different city or street, or browse all listings below.')
      : ('Showing <strong>' + visible + '</strong> of <strong>' + total + '</strong> active listings matching “' + escHtml(q) + '”.');

    banner.innerHTML = (
      '<div style="flex:1;min-width:240px;font-size:0.95rem;line-height:1.5;">' + resultText + '</div>' +
      '<button type="button" id="lst-filter-clear" style="' +
        'background:#EA002A;color:#fff;border:none;padding:10px 20px;' +
        'border-radius:4px;font-family:Raleway,sans-serif;font-weight:700;' +
        'font-size:0.85rem;text-transform:uppercase;letter-spacing:0.5px;' +
        'cursor:pointer;white-space:nowrap;">' +
        'Clear search &times;' +
      '</button>'
    );
    return banner;
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;');
  }

  function clearFilter() {
    showAllCards();
    var banner = document.getElementById('lst-filter-banner');
    if (banner && banner.parentNode) { banner.parentNode.removeChild(banner); }
    try {
      var url = new URL(window.location.href);
      url.searchParams.delete('q');
      window.history.replaceState(null, '', url.toString());
    } catch (e) { /* old browser — no-op */ }
  }

  function findCityChipUrl(q) {
    // Avalon /listings/ shows the 24 newest cards but ALL 1460 listings
    // live on city pages reachable via the chip strip near the top
    // (<a href="../listings/<slug>/index.html">). If the user's query
    // matches a chip's visible text (case-insensitive substring), we
    // redirect there — the city page renders every active listing in
    // that city, which is what the user wants for queries like
    // "Mount Pearl" or "Paradise". Multi-word queries that match a
    // longer city name (e.g. "Portugal Cove" -> "Portugal Cove-St. Philip's")
    // are intentional: substring match catches them.
    var qLower = q.toLowerCase();
    var chips = document.querySelectorAll('a[href*="listings/"][href$="/index.html"], a[href*="listings/"][href$="/"]');
    var bestMatch = null;
    var bestLen = 0;
    for (var i = 0; i < chips.length; i++) {
      var chip = chips[i];
      var text = (chip.textContent || '').replace(/\s+/g, ' ').toLowerCase();
      // Strip the trailing count badge if present (e.g. "St. John's 421")
      text = text.replace(/\s+\d+\s*$/, '');
      if (text && text.indexOf(qLower) !== -1) {
        // Prefer the chip with the shortest matching text — that's the most
        // specific city match (e.g. "Paradise" beats "Paradise & Western...").
        if (bestMatch === null || text.length < bestLen) {
          bestMatch = chip;
          bestLen = text.length;
        }
      }
    }
    return bestMatch ? bestMatch.getAttribute('href') : null;
  }

  // readSearchIndex: parse the inline <script type="application/json"
  // id="lst-search-index"> emitted by build_index_page. Returns null
  // if the script element is missing (e.g. on city/rollup pages that
  // don't carry the full-inventory index). Wired 2026-05-16 so the
  // homepage form's ?q= promise resolves correctly for listings
  // outside the visible 24-card newest set.
  function readSearchIndex() {
    var el = document.getElementById('lst-search-index');
    if (!el) { return null; }
    try {
      var parsed = JSON.parse(el.textContent || '[]');
      return Array.isArray(parsed) ? parsed : null;
    } catch (e) {
      return null;
    }
  }

  // searchFullIndex: find all listings in the full-inventory index whose
  // (addr + city + mls + ptype) substring-matches the query. MLS-shaped
  // numeric queries match against just .mls for exact lookup; everything
  // else is substring match on the joined haystack.
  function searchFullIndex(idx, q) {
    var qLower = q.toLowerCase().trim();
    if (!qLower) { return []; }
    if (MLS_RE.test(qLower)) {
      // Exact MLS# match (substring match against the .mls field).
      var trimmed = qLower.trim();
      return idx.filter(function (L) {
        return String(L.mls || '').indexOf(trimmed) !== -1;
      });
    }
    return idx.filter(function (L) {
      var hay = ((L.addr  || '') + ' ' +
                 (L.city  || '') + ' ' +
                 (L.mls   || '') + ' ' +
                 (L.ptype || '')).toLowerCase();
      return hay.indexOf(qLower) !== -1;
    });
  }

  // RESULT_CARD_CAP: when full-inventory hits exceed this, we still
  // render the first N cards but the banner explains "showing N of total".
  var RESULT_CARD_CAP = 50;

  function fmtPrice(p) {
    if (p === null || typeof p === 'undefined' || p === '') { return 'Contact for price'; }
    var n = Number(p);
    if (!isFinite(n) || n <= 0) { return 'Contact for price'; }
    return '$' + n.toLocaleString('en-CA', { maximumFractionDigits: 0 });
  }

  function buildResultCard(L) {
    var bedsBaths = [];
    if (L.beds !== null && typeof L.beds !== 'undefined' && L.beds !== '') {
      bedsBaths.push('<span><strong>' + escHtml(L.beds) + '</strong>bd</span>');
    }
    if (L.baths !== null && typeof L.baths !== 'undefined' && L.baths !== '') {
      bedsBaths.push('<span><strong>' + escHtml(L.baths) + '</strong>ba</span>');
    }
    var metaHtml = bedsBaths.length ? '<div class="lst-result-meta">' + bedsBaths.join('') + '</div>' : '';
    return '<article class="lst-result-card"><a class="lst-result-link" href="' + escHtml(L.url || '#') + '"><p class="lst-result-price">' + fmtPrice(L.price) + '</p><p class="lst-result-addr">' + escHtml(L.addr || '') + '</p><p class="lst-result-city">' + escHtml(L.city || '') + ', NL</p>' + metaHtml + '<p class="lst-result-mls">MLS&reg; ' + escHtml(L.mls || '') + '</p><p class="lst-result-cta">View listing &rarr;</p></a></article>';
  }

  function renderResultCards(hits, q) {
    var grid = document.querySelector('.lst-card-grid');
    if (!grid) { return false; }
    var shown = hits.slice(0, RESULT_CARD_CAP);
    var capped = hits.length > RESULT_CARD_CAP;
    grid.querySelectorAll('.lst-card').forEach(function (card) { card.style.display = 'none'; });
    var existingHost = grid.querySelector('.lst-result-host');
    if (existingHost) { existingHost.parentNode.removeChild(existingHost); }
    var host = document.createElement('div');
    host.className = 'lst-result-host';
    host.style.cssText = 'display:contents;';
    host.innerHTML = shown.map(buildResultCard).join('');
    grid.appendChild(host);
    var existingBanner = document.getElementById('lst-filter-banner');
    if (existingBanner) { existingBanner.parentNode.removeChild(existingBanner); }
    var bannerText = capped
      ? 'Showing <strong>' + RESULT_CARD_CAP + '</strong> of <strong>' + hits.length + '</strong> listings matching &ldquo;' + escHtml(q) + '&rdquo;. Refine your search to narrow further.'
      : 'Showing <strong>' + hits.length + '</strong> listings matching &ldquo;' + escHtml(q) + '&rdquo;.';
    var banner = document.createElement('div');
    banner.id = 'lst-filter-banner';
    banner.style.cssText = 'background: var(--dark-card, #1a1a1a); border: 1px solid var(--accent-red, #EA002A); border-radius: 6px; padding: 16px 20px; margin: 0 auto 24px; max-width: 1200px; color: #fff; font-family: Roboto, sans-serif; display: flex; gap: 16px; align-items: center; justify-content: space-between; flex-wrap: wrap;';
    banner.innerHTML = '<div style="flex:1;min-width:240px;font-size:0.95rem;line-height:1.5;">' + bannerText + '</div><button type="button" id="lst-filter-clear" style="background:#EA002A;color:#fff;border:none;padding:10px 20px;border-radius:4px;font-family:Raleway,sans-serif;font-weight:700;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.5px;cursor:pointer;white-space:nowrap;">Clear search &times;</button>';
    grid.parentNode.insertBefore(banner, grid);
    var clearBtn = document.getElementById('lst-filter-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        var h = document.querySelector('.lst-result-host');
        if (h && h.parentNode) { h.parentNode.removeChild(h); }
        document.querySelectorAll('.lst-card-grid .lst-card').forEach(function (c) { c.style.display = ''; });
        var b = document.getElementById('lst-filter-banner');
        if (b && b.parentNode) { b.parentNode.removeChild(b); }
        try {
          var url = new URL(window.location.href);
          url.searchParams.delete('q');
          window.history.replaceState(null, '', url.toString());
        } catch (e) { }
      });
    }
    setTimeout(function () { banner.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 50);
    return true;
  }

  function init() {
    var q = readQ();
    if (!q) { return; }

    // ── Tier 0: full-inventory search index ──
    // If the index is present (listings/index.html only — city + rollup
    // pages don't carry it), find all matches across every active
    // listing. On a single match → instant redirect to the detail page
    // (closes the bug for queries like "147 River Road" that target a
    // listing outside the visible 24). On 2+ matches OR 0 matches,
    // fall through to the visible-24 filter + city-chip fallback below.
    var idx = readSearchIndex();
    if (idx && idx.length > 0) {
      var hits = searchFullIndex(idx, q);
      if (hits.length === 1) {
        // Single match: redirect immediately to the detail page.
        var hitUrl = hits[0].url || '';
        if (hitUrl) {
          window.location.href = hitUrl;
          return;
        }
      } else if (hits.length >= 2) {
        // 2+ matches → render result cards inline from JSON index.
        if (renderResultCards(hits, q)) {
          return;
        }
      }
      // 0 matches in index → fall through to visible-24 filter + city-chip fallback.
    }

    // ── Tier 1: MLS# instant-redirect from visible 24 cards ──
    // Kept as a fallback when search index is absent or missed.
    if (MLS_RE.test(q)) {
      var url = findMlsCardUrl(q.trim());
      if (url) {
        window.location.href = url;
        return;
      }
      // MLS# not in active inventory — fall through to text filter behaviour
      // so the user sees the banner explaining no match. (Same path Gander
      // listings-index.js takes for this case.)
    }

    var grid = document.querySelector('.lst-card-grid');
    if (!grid) { return; }

    var result = applyTextFilter(q);

    // Avalon caveat: /listings/ only renders the 24 newest cards inline,
    // not all 1460. If the text filter found 0 in the visible 24, fall
    // back to checking the city chip strip — the user might be searching
    // for a city name like "Mount Pearl" whose listings live in a chip-
    // linked city page, not in the visible newest-24 set. This delivers
    // on the homepage form's promise for city-shaped queries without
    // requiring the full-inventory search index (which is a follow-up).
    if (result.visible === 0) {
      var cityUrl = findCityChipUrl(q);
      if (cityUrl) {
        // Tack ?q= onto the city page URL so the city page can preserve
        // the search context (and the same filter JS will re-run there
        // against that city's full card set).
        var sep = (cityUrl.indexOf('?') === -1) ? '?' : '&';
        window.location.href = cityUrl + sep + 'q=' + encodeURIComponent(q);
        return;
      }
    }

    // Insert banner BEFORE the grid (or grid's parent if it's nested deep).
    var banner = buildBanner(q, result.visible, result.total);
    var anchor = grid;
    // Walk up to the first ancestor with a wider layout container so the
    // banner sits above the grid visually. .lst-section / similar.
    var parent = grid.parentNode;
    if (parent && parent.classList && parent.classList.contains('lst-card-grid-wrap')) {
      anchor = parent;
    }
    anchor.parentNode.insertBefore(banner, anchor);

    var clearBtn = document.getElementById('lst-filter-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', clearFilter);
    }

    // Scroll the banner into view so it's obvious the search applied.
    setTimeout(function () {
      banner.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
