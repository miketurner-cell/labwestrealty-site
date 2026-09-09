/* ═══════════════════════════════════════════════════════════════
   Turner Network Footer Strip — shared across all 5 sites.
   Injects a brand-unifying "Our Offices" strip above the existing
   native footer on each site.

   Usage on each page (before </body>):
     <link rel="stylesheet" href="/css/turner-network.css">
     <script src="/js/regions-data.js" defer></script>
     <script>window.TURNER_SITE = 'gander';</script>
     <script src="/js/turner-network.js" defer></script>

   Ship 6 (2026-09-08, fleet review Part C): OFFICES and the per-site NAP
   line now derive from window.TURNER_REGIONS (js/regions-data.js, emitted
   from the fleet-canonical tools/regions.json) instead of two hardcoded
   arrays that had already drifted once (hub + labwest were still on the
   pre-2026-08-26 build for weeks despite the fleet manifest claiming
   otherwise -- see fleet review 2026-09-08). FALLBACK_OFFICES below is the
   last-known-good array for the rare page missing regions-data.js
   (Convention #74) -- the registry is the source of truth now.

   Valid TURNER_SITE values (office_key vocabulary):
     'hub', 'gander', 'goosebay', 'labwest', 'avalon'
   If omitted, no office is highlighted.

   The strip is injected as the first child of <footer> if one exists,
   or prepended to <body> as the last-but-one element otherwise.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var FALLBACK_OFFICES = [
    { key: 'hub',      city: 'Turner Realty',      tag: 'NETWORK HUB',        url: 'royallepageturner.com',  href: 'https://royallepageturner.com' },
    { key: 'gander',   city: 'Gander',             tag: 'CENTRAL NL',         url: 'realestategander.com',   href: 'https://realestategander.com' },
    { key: 'goosebay', city: 'Happy Valley-GB',    tag: 'LABRADOR',           url: 'goosebayrealestate.ca',  href: 'https://goosebayrealestate.ca' },
    { key: 'labwest',  city: 'Labrador West',      tag: 'LABRADOR WEST',      url: 'labwestrealty.com',      href: 'https://labwestrealty.com' },
    { key: 'avalon',   city: 'Avalon / St. John\'s', tag: 'AVALON',           url: 'avalonrealestate.ca',    href: 'https://avalonrealestate.ca' }
  ];

  // 'hub' is the network's own home, not a geographic territory, so it is
  // deliberately NOT a tools/regions.json entry (that registry is
  // territories only) -- it stays a small hardcoded card, always first.
  var HUB_CARD = { key: 'hub', city: 'Turner Realty', tag: 'NETWORK HUB', url: 'royallepageturner.com', href: 'https://royallepageturner.com' };

  function officesFromRegistry() {
    var reg = window.TURNER_REGIONS;
    if (!reg || typeof reg !== 'object') {
      try { console.warn('[turner-network.js] window.TURNER_REGIONS missing -- falling back to the last-known-good office list. Add js/regions-data.js before turner-network.js.'); } catch (e) {}
      return FALLBACK_OFFICES;
    }
    var keys = Object.keys(reg).filter(function (k) { return reg[k] && reg[k].office_key; });
    keys.sort(function (a, b) { return (reg[a].order || 0) - (reg[b].order || 0); });
    var cards = keys.map(function (k) {
      var r = reg[k];
      var domain = (r.domain || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
      return { key: r.office_key, city: r.nav_label || r.label || k, tag: (r.nav_label || r.label || k).toUpperCase(), url: domain, href: r.domain };
    });
    return [HUB_CARD].concat(cards);
  }

  var currentSite = (window.TURNER_SITE || '').toLowerCase();

  // Decided 2026-08-26: one credit line everywhere -- predates the Royal
  // LePage affiliation, so it holds regardless of any future brand/marketplace
  // change (was previously Avalon-only, with Chairman's Club shown elsewhere).
  var creditLine = 'A family-owned Newfoundland brokerage, serving the province since 1998.';

  function napFromRegistry() {
    var fallback = { addr: '204 Airport Blvd, Gander, NL A1V 1L6', tel: '7092567999', phone: '709-256-7999' };
    var reg = window.TURNER_REGIONS;
    if (!reg || typeof reg !== 'object') return fallback;
    // office_key is the vocabulary TURNER_SITE speaks (matches OFFICES above);
    // find the region whose office_key equals the current site, not the
    // territory key itself (labrador-city's office_key is 'labwest', e.g.).
    var match = null;
    for (var k in reg) {
      if (reg[k] && reg[k].office_key === currentSite) { match = reg[k]; break; }
    }
    // Hub + Labrador West (no physical office) fall through to the Gander HQ
    // default -- same behaviour as before this fix; only a region with a
    // real office.phone overrides it (Avalon and Goose Bay).
    if (!match || !match.office || !match.office.phone) return fallback;
    return {
      addr: match.office.address || '',
      tel: (match.office.phone || '').replace(/\D/g, ''),
      phone: match.office.phone,
    };
  }
  var nap = napFromRegistry();

  function buildHTML() {
    var offices = officesFromRegistry();
    var cards = offices.map(function (o) {
      var isActive = o.key === currentSite;
      var tag = isActive
        ? '<span class="turner-network-active-tag">You are here</span>'
        : '';
      if (isActive) {
        return (
          '<div class="turner-network-card active" aria-current="page">' +
            '<div class="turner-network-city">' + o.city + '</div>' +
            '<div class="turner-network-url">' + o.url + '</div>' +
            tag +
          '</div>'
        );
      }
      return (
        '<a class="turner-network-card" href="' + o.href + '">' +
          '<div class="turner-network-city">' + o.city + '</div>' +
          '<div class="turner-network-url">' + o.url + '</div>' +
        '</a>'
      );
    }).join('');

    return (
      '<section class="turner-network" aria-label="Royal LePage Turner Realty office network">' +
        '<div class="turner-network-inner">' +
          '<div class="turner-network-lead">' +
            '<p class="turner-network-eyebrow">Royal LePage Turner Realty Network</p>' +
            '<h2 class="turner-network-title">Serving Newfoundland &amp; Labrador</h2>' +
            '<p class="turner-network-sub">Serving buyers and sellers from the Avalon Peninsula to the Labrador coast. ' +
            'One brokerage, one standard of service.</p>' +
          '</div>' +
          '<nav class="turner-network-grid" aria-label="Office sites">' +
            cards +
          '</nav>' +
          '<p class="turner-network-meta">' +
            '<strong>Royal LePage Turner Realty (2014) Inc.</strong>' + (nap.addr ? ' &middot; ' + nap.addr : '') + ' &middot; ' +
            '<a href="tel:' + nap.tel + '">' + nap.phone + '</a>' +
            '<br>' + creditLine +
          '</p>' +
        '</div>' +
      '</section>'
    );
  }

  function inject() {
    if (document.querySelector('.turner-network')) return; // idempotent
    var html = buildHTML();
    var existingFooter = document.querySelector('footer');
    var wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    var node = wrapper.firstChild;
    if (existingFooter && existingFooter.parentNode) {
      existingFooter.parentNode.insertBefore(node, existingFooter);
    } else {
      document.body.appendChild(node);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
