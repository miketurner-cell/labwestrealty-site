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
 * No social accounts exist for this sub-brand. Until 2026-10-09 the icons
 * pointed at '#' (dead links); D-1009-17 points them at the brokerage's
 * own profiles, the same three the hub (royallepageturner-site
 * js/nav-config.js) and Gander (realestategander-site js/nav-config.js)
 * already link.
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
    facebook: 'https://www.facebook.com/realestategander', instagram: 'https://www.instagram.com/turnerrealty2014', youtube: 'https://www.youtube.com/playlist?list=PLr4XcQLT7UeO_8OZSgtx6h2N6dvsmsY_Y',
    // D-1009-17: no evaluations are offered here (no office or agent in Labrador West);
    // read by js/nav.js (SITE.ctaLabel, default 'Free Evaluation') once the fleet nav.js carries it.
    ctaLabel: 'Get in Touch',
    ctaHref: p + 'contact.html',
    // js/nav.js is one fleet file now (2026-10-08); this site's own copy used 1024 as the menu breakpoint, kept here.
    navBreakpoint: 1024,
    // The new header (redesign, D-1009-10: Lab West "as drawn"). OFF: nothing changes until Mike's GO flips this to 'v2'
    // (?header=v2 previews it on any page). Four words, one button, the phone; no search bar (this site has no listings);
    // the regions sit in the phone menu's More line (js/nav.js adds them after the two links below).
    header: 'off',
    // js/nav.js loads css/header-v2.css with this ?v= (sha256[:8] of the file; tools/tests/header-v2-test.mjs fails when it is stale and prints the value)
    header2Stamp: '4f6b917c',
    header2: {
      region: 'Labrador West &middot; recruiting',
      office: 'Royal LePage Turner Realty &middot; 204 Airport Blvd, Gander &middot; 709-256-7999',
      bar: false, signIn: false, sheetCta: true,
      ctaLabel: 'Book a confidential call',
      // the confidential broker form (D-1008-106): js/recruit-form.js opens it on this hash when its gate is open; with the
      // gate closed the visitor lands on the page, whose own button is the mailto
      ctaHref: p + 'become-a-realtor.html#confidential-inquiry',
      menu: [
        { label: 'Why join', href: p + 'why-join.html' },
        { label: 'Get licensed', href: p + 'become-a-realtor.html' },
        { label: 'The market', href: p + 'labrador-west.html' },
        { label: 'About Turner', href: p + 'about-turner.html', items: [
          ['About Turner', p + 'about-turner.html'],
          ['Contact', p + 'contact.html']
        ] }
      ],
      more: [
        ['Home', r + 'index.html'],
        ['Contact', p + 'contact.html']
      ]
    }
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
    copyright: '&copy; 1998&ndash;{year} Royal LePage Turner Realty (2014) Inc. Recruiting licensed REALTORS&reg; for Labrador West; no office in Labrador West.',
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

  // Header v2 touch-ups that are this site's own (D-1009-10), done here so the shared js/nav.js and css/header-v2.css stay byte-identical
  // fleet-wide (always-on #27): nav.js hard-codes the button's words ("Get my home's value") and a Sign in link, and its phone sheet has no
  // button (the listing sites' bottom action bar carries it; this site has none). On turner:nav-injected, and only while the new header
  // is on (html.header-v2), this applies SITE.header2.ctaLabel / signIn:false / sheetCta:true. With the switch off it does nothing.
  if (typeof document.addEventListener === 'function') document.addEventListener('turner:nav-injected', function () {
    var h2 = SITE.header2, root = document.documentElement;
    if (!h2 || !root.classList.contains('header-v2')) return;
    var cta = document.querySelector('.nav2-cta');
    if (cta && h2.ctaLabel) cta.innerHTML = h2.ctaLabel;
    if (h2.signIn === false) { var si = document.querySelector('.nav2-signin'); if (si && si.parentNode) si.parentNode.removeChild(si); }
    var links = document.querySelector('.nav2-links');
    if (h2.sheetCta === true && links && !links.querySelector('.nav2-sheet-cta')) {
      var li = document.createElement('li');
      li.className = 'nav2-sheet-cta';
      li.innerHTML = '<a href="' + (h2.ctaHref || SITE.ctaHref) + '">' + (h2.ctaLabel || cta && cta.innerHTML || '') + '</a>';
      links.appendChild(li);
    }
    if (!document.getElementById('nav2-site-style')) {
      var st = document.createElement('style');
      st.id = 'nav2-site-style';
      st.textContent = 'html.header-v2 .nav2-sheet-cta{display:none}' +
        '@media (max-width:1023px){html.header-v2 .nav2-links>li.nav2-sheet-cta{display:block;padding:4px 0 8px}' +
        'html.header-v2 .nav2-links>li.nav2-sheet-cta>a{display:flex;align-items:center;justify-content:center;min-height:48px;padding:0 20px;border:0;border-radius:999px;background:var(--h2-red);color:#fff;text-decoration:none;font:800 15px/1 Raleway,sans-serif;letter-spacing:.01em;text-transform:none}' +
        'html.header-v2 .nav2-links>li.nav2-sheet-cta>a:hover{background:var(--h2-red-hover)}}';
      document.head.appendChild(st);
    }
  });

  window.SITE = SITE;
  window.MENU = MENU;
  window.FOOTER = FOOTER;
})();
