/**
 * Labrador West (labwestrealty.com) site config + nav data -- consumed
 * by the shared js/nav.js renderer (Tier-1, byte-identical across the
 * fleet). This file is deliberately UN-synced -- every site has its own
 * copy, same shape as _fleet_config.py / agent_roster_loader.py's
 * per-repo sibling-data pattern. Load this script BEFORE js/nav.js on
 * every page.
 *
 * Slice 3 step 4 (2026-09-09): Labrador West previously hand-baked its
 * own nav in 3 structurally distinct variants across 11 pages (see
 * [[nl-network-portal]] memory for the full catalog) -- this file plus
 * js/nav.js/js/footer.js replace all of them with the same shared
 * chrome the 3 spoke sites already use. Menu items + footer columns
 * extracted VERBATIM from the existing baked nav/footer (Variant 1, the
 * 9-page standard), not redesigned -- this site keeps its own
 * recruiting-focused menu, per the canvas's decision (d). No physical
 * office (recruiting-only, per CLAUDE.md); NAP borrowed from Gander HQ,
 * matching what this site's own pre-existing footer already showed.
 * No real social accounts exist for this sub-brand (verified against
 * the existing pages before this ship -- none were linked anywhere) --
 * '#' placeholders match js/nav.js's own FALLBACK_SITE convention for
 * "no real account", not a broken link left by mistake.
 */
(function () {
  'use strict';

  var p = '', r = '';

  var SITE = {
    brandSub: 'Royal LePage',
    logo: r + 'images/rlp-logo.png',
    address: '204 Airport Blvd, Gander',
    email: 'miketurner@royallepage.ca',
    phone: '709-256-7999', phoneTel: '7092567999',
    facebook: '#', instagram: '#', youtube: '#',
    ctaHref: p + 'contact.html'
  };

  // Top-level MENU entries are {label, href} objects (nav.js's menuItem()
  // reads m.label/m.href directly) -- NOT [label, href] tuples, which are
  // only valid inside a dropdown's own items[] array. Preserves the exact
  // 6-item list the old baked nav (Variant 1) already showed, in order.
  var MENU = [
    { label: 'Home', href: r + 'index.html' },
    { label: 'Why Join', href: p + 'why-join.html' },
    { label: 'Get Licensed', href: p + 'become-a-realtor.html' },
    { label: 'About Turner', href: p + 'about-turner.html' },
    { label: 'The Market', href: p + 'labrador-west.html' },
    { label: 'Contact', href: p + 'contact.html' }
  ];

  // Consumed by the shared js/footer.js. Content extracted verbatim from
  // the existing baked footer -- same Avalon-gap fix as the hub's
  // FOOTER (the Turner Network column was missing Avalon on every
  // page).
  var FOOTER = {
    copyright: '&copy; 1998&ndash;{year} Royal LePage Turner Realty (2014) Inc. Labrador West office recruiting licensed REALTORS&reg;.',
    columns: [
      { heading: 'Recruiting', links: [
        ['Why Join', p + 'why-join.html'],
        ['Get Licensed', p + 'become-a-realtor.html'],
        ['About Turner', p + 'about-turner.html'],
        ['The Market', p + 'labrador-west.html'],
        ['Contact', p + 'contact.html']
      ] },
      { heading: 'Turner Network', links: [
        ['Gander Office', 'https://realestategander.com'],
        ['Avalon / St. John&rsquo;s', 'https://avalonrealestate.ca'],
        ['Happy Valley&ndash;Goose Bay', 'https://goosebayrealestate.ca'],
        ['Main Network', 'https://royallepageturner.com']
      ] }
    ]
  };

  window.SITE = SITE;
  window.MENU = MENU;
  window.FOOTER = FOOTER;
})();
