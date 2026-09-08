/* ═══════════════════════════════════════════════════════════════
   Turner Network Footer Strip — shared across all 5 sites.
   Injects a brand-unifying "Our Offices" strip above the existing
   native footer on each site.

   Usage on each page (before </body>):
     <link rel="stylesheet" href="/css/turner-network.css">
     <script>window.TURNER_SITE = 'gander';</script>
     <script src="/js/turner-network.js" defer></script>

   Valid TURNER_SITE values:
     'hub', 'gander', 'goosebay', 'labwest', 'avalon'
   If omitted, no office is highlighted.

   The strip is injected as the first child of <footer> if one exists,
   or prepended to <body> as the last-but-one element otherwise.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var OFFICES = [
    { key: 'hub',      city: 'Turner Realty',      tag: 'NETWORK HUB',        url: 'royallepageturner.com',  href: 'https://royallepageturner.com' },
    { key: 'gander',   city: 'Gander',             tag: 'CENTRAL NL',         url: 'realestategander.com',   href: 'https://realestategander.com' },
    { key: 'goosebay', city: 'Happy Valley-GB',    tag: 'LABRADOR',           url: 'goosebayrealestate.ca',  href: 'https://goosebayrealestate.ca' },
    { key: 'labwest',  city: 'Labrador West',      tag: 'LABRADOR WEST',      url: 'labwestrealty.com',      href: 'https://labwestrealty.com' },
    { key: 'avalon',   city: 'Avalon / St. John\'s', tag: 'AVALON',           url: 'avalonrealestate.ca',    href: 'https://avalonrealestate.ca' }
  ];

  var currentSite = (window.TURNER_SITE || '').toLowerCase();

  // Decided 2026-08-26: one credit line everywhere -- predates the Royal
  // LePage affiliation, so it holds regardless of any future brand/marketplace
  // change (was previously Avalon-only, with Chairman's Club shown elsewhere).
  var creditLine = 'A family-owned Newfoundland brokerage, serving the province since 1998.';

  // Per-site NAP for the meta line below. Hub + Labrador West (no physical
  // office) fall through to the Gander HQ default -- unchanged from before
  // this fix; only Avalon and Goose Bay were showing the wrong office.
  var SITE_NAP = {
    avalon:   { addr: '', tel: '7097256520', phone: '709-725-6520' },
    goosebay: { addr: '371 Hamilton River Road, Suite 102, Happy Valley-Goose Bay, NL A0P 1C0', tel: '7098965001', phone: '709-896-5001' }
  };
  var nap = SITE_NAP[currentSite] || { addr: '204 Airport Blvd, Gander, NL A1V 1L6', tel: '7092567999', phone: '709-256-7999' };

  function buildHTML() {
    var cards = OFFICES.map(function (o) {
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
