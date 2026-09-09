(function () {
  // Fleet nav renderer -- Tier-1, byte-identical across every site
  // (promoted 2026-08-26; this file is generic, no site content lives here).
  // window.SITE + window.MENU come from js/nav-config.js, loaded on the page
  // BEFORE this script -- same per-repo un-synced sibling-data pattern as
  // _fleet_config.py / agent_roster_loader.py. Replaces the inlined nav
  // ddf-generate-pages.py used to stamp into every page.
  //
  // NOTE (2026-08-26): the prior header here claimed this file "replaces
  // js/mobile-nav.js... removing it is a no-op behaviourally" -- that was
  // WRONG. 5 live pages (happy-valley-goose-bay, karen-pomeroy, labrador,
  // north-west-river, roberta-primmer) still load js/mobile-nav.js instead
  // of this renderer and were never converted. Flagged, not fixed here --
  // converting those 5 is its own follow-up, not bundled into this ship.
  //
  // p/r are path-prefix shorthand used inline below (topBarHTML) -- pure
  // syntax sugar, identical on every site, not part of SITE/MENU config.
  var p = '/pages/', r = '/';

  // Ship 5 (2026-09-08, Convention #74 fail-safe): window.SITE/window.MENU
  // come from js/nav-config.js loaded immediately before this script -- but
  // several generator paths (Goose Bay listing-detail pages, /listings/
  // index pages, Avalon's 613 property/ pages) never emit that tag, and
  // this file used to read window.SITE/window.MENU with NO guard -- MENU
  // being undefined threw at parse time (MENU.map below), which killed the
  // whole IIFE before injectNav() was ever wired up: no nav, no top bar, no
  // region strip, no CTA, nothing. Root cause belongs in each generator
  // (emit nav-config.js like Gander's community/detail pages already do);
  // this is the belt-and-braces backstop so a page missing it still gets
  // SOMETHING live instead of a blank header. Fallback SITE carries generic
  // brand fields only (no per-site NAP guess) -- turner-network.js is still
  // the source of truth for per-site address/phone once window.TURNER_SITE
  // is set correctly.
  var SITE = window.SITE || {
    logo: '', brandSub: 'Royal LePage', address: '', email: '',
    facebook: '#', instagram: '#', youtube: '#',
    ctaHref: p + 'contact.html', phoneTel: '7092567999', phone: '709-256-7999'
  };
  var MENU = Array.isArray(window.MENU) ? window.MENU : [];
  if (!window.SITE || !Array.isArray(window.MENU)) {
    try { console.warn('[nav.js] window.SITE/window.MENU missing on this page -- nav-config.js was not loaded before nav.js. Rendering a minimal fallback nav; fix the page\'s generator to emit nav-config.js.'); } catch (e) {}
  }

  var fbSVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>';
  var phoneSVG = '<svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.88.37 1.73.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c1.08.33 1.93.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>';
  var igSVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c2.717 0 3.056.01 4.122.06 1.065.05 1.79.217 2.428.465.66.254 1.216.598 1.772 1.153a4.908 4.908 0 0 1 1.153 1.772c.247.637.415 1.363.465 2.428.05 1.066.06 1.405.06 4.122 0 2.717-.01 3.056-.06 4.122-.05 1.065-.218 1.79-.465 2.428a4.883 4.883 0 0 1-1.153 1.772 4.915 4.915 0 0 1-1.772 1.153c-.637.247-1.363.415-2.428.465-1.066.05-1.405.06-4.122.06-2.717 0-3.056-.01-4.122-.06-1.065-.05-1.79-.218-2.428-.465a4.89 4.89 0 0 1-1.772-1.153 4.904 4.904 0 0 1-1.153-1.772c-.248-.637-.415-1.363-.465-2.428-.05-1.066-.06-1.405-.06-4.122 0-2.717.01-3.056.06-4.122.05-1.065.217-1.79.465-2.428a4.88 4.88 0 0 1 1.153-1.772A4.897 4.897 0 0 1 5.45 2.525c.638-.248 1.362-.415 2.428-.465C8.944 2.01 9.283 2 12 2zm0 1.802c-2.67 0-2.986.01-4.04.059-.976.045-1.505.207-1.858.344-.466.181-.8.398-1.15.748-.35.35-.566.683-.747 1.15-.137.353-.3.882-.344 1.857-.049 1.055-.06 1.37-.06 4.04 0 2.67.01 2.986.06 4.04.045.976.207 1.505.344 1.858.181.466.398.8.748 1.15.35.35.683.566 1.15.747.353.137.882.3 1.857.344 1.054.049 1.37.06 4.04.06 2.67 0 2.987-.01 4.04-.06.976-.045 1.505-.207 1.858-.344.466-.181.8-.398 1.15-.748.35-.35.566-.683.747-1.15.137-.353.3-.882.344-1.857.049-1.054.06-1.37.06-4.04 0-2.67-.01-2.986-.06-4.04-.045-.976-.207-1.505-.344-1.858a3.09 3.09 0 0 0-.748-1.15 3.09 3.09 0 0 0-1.15-.747c-.353-.137-.882-.3-1.857-.344-1.054-.049-1.37-.06-4.04-.06zM12 6.865a5.135 5.135 0 1 1 0 10.27 5.135 5.135 0 0 1 0-10.27zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm5.338-9.87a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4z"/></svg>';
  var ytSVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 12a29 29 0 0 0 .46 5.58A2.78 2.78 0 0 0 3.4 19.6C5.12 20 12 20 12 20s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2A29 29 0 0 0 23 12a29 29 0 0 0-.46-5.58zM9.75 15.02V8.98L15.5 12l-5.75 3.02z"/></svg>';

  function flat(it) { return '<a href="' + it[1] + '">' + it[0] + '</a>'; }
  function submenu(it) {
    var sc = '';
    for (var i = 0; i < it.children.length; i++) sc += flat(it.children[i]);
    return '<div class="nav-submenu"><a href="' + it.href + '">' + it.label + '</a>' +
      '<div class="nav-submenu-content">' + sc + '</div></div>';
  }
  function dropdown(label, href, items) {
    var content = '';
    for (var i = 0; i < items.length; i++) content += (items[i].children ? submenu(items[i]) : flat(items[i]));
    // A top-level dropdown's own label can ALSO be a real link (Gander's
    // Listings/Communities: href set alongside items) -- desktop click
    // navigates there (dropdown opens on :hover, not click); mobile tap
    // still toggles the dropdown regardless, since the tap handler below
    // calls preventDefault() unconditionally on mobile. Falls back to '#'
    // when no href is given, unchanged for every site that doesn't need it.
    var labelHTML = href
      ? '<a href="' + href + '" aria-expanded="false" role="button">' + label + '</a>'
      : '<a href="#" aria-expanded="false" role="button">' + label + '</a>';
    return '<li class="nav-dropdown">' + labelHTML +
      '<div class="nav-dropdown-content">' + content + '</div></li>';
  }
  function menuItem(m) { return m.items ? dropdown(m.label, m.href, m.items) : '<li><a href="' + m.href + '">' + m.label + '</a></li>'; }

  // Resolves a registry entry by site_key -- NEVER by using a site_key as a
  // direct TURNER_REGIONS[...] object key (the registry is keyed by
  // territory). Territory and site_key are the same string for every live
  // Turner region (gander/avalon/goosebay) but NOT for Labrador West
  // (territory "labrador-city", site_key "labwest") or the hub (no
  // territory at all -- it's the network hub, not a geography, so it's
  // deliberately absent from the registry). A direct reg[siteKey] lookup
  // silently returns undefined for either, which is why every lookup of
  // "the region for site X" in this file -- X being the current site OR
  // the #via= site a visitor arrived from -- goes through this function.
  function regionBySiteKey(siteKey) {
    var reg = window.TURNER_REGIONS;
    if (!siteKey || !reg) return null;
    for (var k in reg) { if (reg[k] && reg[k].site_key === siteKey) return reg[k]; }
    return null;
  }
  function currentRegion() { return regionBySiteKey(window.TURNER_SITE); }

  // Region tag (August design canvas, 2026-08-26 -- decided then, never
  // shipped; shipped now as part of "Turner NL -- One Site, Five Domains",
  // 2026-09-09). Reads the SAME nav_label the region strip below already
  // shows, rather than inventing a second short-form label to maintain.
  // Empty/missing on a page that hasn't picked up window.TURNER_REGIONS or
  // window.TURNER_SITE yet, or on the hub (no region of its own) -- renders
  // nothing rather than "undefined".
  function regionTagHTML() {
    var here = currentRegion();
    if (!here || !here.nav_label) return '';
    var muted = here.state !== 'live' ? ' muted' : '';
    return '<span class="nav-region-tag' + muted + '">' + here.nav_label + '</span>';
  }

  // A FUNCTION, not a baked string constant -- regionTagHTML() reads
  // window.TURNER_REGIONS, which is NOT guaranteed to exist yet at the
  // moment this module's top level runs. nav.js and nav-config.js load
  // WITHOUT defer on several generator paths while regions-data.js loads
  // WITH defer -- deferred scripts always run after non-deferred ones,
  // regardless of source order, so a baked-at-parse-time string would
  // silently freeze the tag empty for the page's whole life even on a
  // site with the registry loaded (caught live on a real Avalon listing
  // page during this ship's own verification pass, not by reading code).
  // Called fresh inside injectNav() below, same as regionStripHTML().
  function topBarHTML() {
    return '<div style="display:flex;align-items:center">' +
      '<a href="' + r + 'index.html" class="nav-brand">' +
        (SITE.logo ? '<img src="' + SITE.logo + '" alt="Royal LePage" width="40" height="40" style="margin-right:10px;vertical-align:middle;">' : '') +
        '<span class="nav-brand-name">Turner <span>Realty</span></span></a>' +
      '<span class="nav-brand-rlp">' + SITE.brandSub + '</span>' + regionTagHTML() + '</div>' +
    '<div class="nav-top-right">' +
      '<a href="' + p + 'contact.html" class="nav-top-info">' + SITE.address + '</a>' +
      '<div class="nav-top-divider"></div>' +
      '<a href="mailto:' + SITE.email + '" class="nav-top-info">' + SITE.email + '</a>' +
      '<div class="nav-top-divider"></div>' +
      '<div class="nav-top-social">' +
        '<a href="' + SITE.facebook + '" target="_blank" rel="noopener" aria-label="Facebook">' + fbSVG + '</a>' +
        '<a href="' + SITE.instagram + '" target="_blank" rel="noopener" aria-label="Instagram">' + igSVG + '</a>' +
        '<a href="' + SITE.youtube + '" target="_blank" rel="noopener" aria-label="YouTube">' + ytSVG + '</a>' +
      '</div>' +
    '</div>';
  }

  var navMainHTML =
    '<button class="nav-toggle" aria-label="Toggle navigation" type="button"><span></span><span></span><span></span></button>' +
    '<ul class="nav-main-links">' + MENU.map(menuItem).join('') + '</ul>' +
    '<div class="nav-main-right">' +
      '<a href="' + SITE.ctaHref + '" class="nav-cta-outline">Free Evaluation</a>' +
      '<a href="tel:' + SITE.phoneTel + '" class="nav-phone-pill">' + phoneSVG +
        '<span class="nav-phone-num">' + SITE.phone + '</span></a>' +
    '</div>';

  function closeAllDropdowns(scope) {
    var od = scope.querySelectorAll('.nav-dropdown.open');
    for (var i = 0; i < od.length; i++) od[i].classList.remove('open');
  }

  // Ship 4 (2026-08-26): the always-present region strip -- "Serving:
  // Gander and Area / Avalon / Labrador", current site highlighted via the
  // already-set window.TURNER_SITE (same source of truth turner-network.js
  // already reads -- no second site-identity signal invented). Labrador
  // West is DELIBERATELY absent here per Mike's own decision on the design
  // canvas: it's recruiting-only today (no listings, no dedicated agent),
  // and this strip is presented as live coverage -- it still belongs in
  // the network-strip grid and the provincial-site region picker, just not
  // here. One shared component on all 3 sites, not a per-site fork.
  // Ship 6 (2026-09-08, fleet review Part C): REGIONS now derives from
  // window.TURNER_REGIONS (js/regions-data.js, emitted from the fleet-canonical
  // tools/regions.json -- see tools/emit-regions-js.py). This array is a
  // FALLBACK ONLY, for the rare page that hasn't picked up regions-data.js yet
  // (Convention #74) -- it must never drift from the registry's own 'live'
  // regions, but the registry is the source of truth now, not this file.
  // 2026-08-26 (later) precedent this replaces: 2 peer Royal LePage brokerages,
  // NOT Turner-operated (tools/regions.json operator:"peer"); Lewisporte/
  // Twillingate stay Turner's own (Gander/Crystal Hynes) despite Generation
  // Realty's own site also listing them -- Mike's explicit call, 2026-08-26:
  // "Gander right now should supersede anything Generation Realty is doing
  // until we bring them into the fold."
  var FALLBACK_REGIONS = [
    { site: 'gander',   site_key: 'gander',   label: 'Gander and Area', url: 'https://realestategander.com/' },
    { site: 'avalon',   site_key: 'avalon',   label: 'Avalon',     url: 'https://avalonrealestate.ca/' },
    { site: 'goosebay', site_key: 'goosebay', label: 'Labrador',   url: 'https://goosebayrealestate.ca/' },
    { site: 'grand-falls-windsor',     site_key: null, label: 'Grand Falls',  url: 'https://generationrealty.ca/' },
    { site: 'corner-brook-west-coast', site_key: null, label: 'Corner Brook', url: 'https://royallepagenlrealty.ca/' }
  ];

  function liveRegions() {
    var reg = window.TURNER_REGIONS;
    if (!reg || typeof reg !== 'object') {
      try { console.warn('[nav.js] window.TURNER_REGIONS missing -- falling back to the last-known-good region list. Add js/regions-data.js before nav.js.'); } catch (e) {}
      return FALLBACK_REGIONS;
    }
    var keys = Object.keys(reg).filter(function (k) { return reg[k] && reg[k].state === 'live'; });
    keys.sort(function (a, b) { return (reg[a].order || 0) - (reg[b].order || 0); });
    return keys.map(function (k) {
      return { site: k, site_key: reg[k].site_key || null, label: reg[k].nav_label || reg[k].label || k, url: (reg[k].domain || '') + '/' };
    });
  }

  // Page-kind route map (Ship 7, 2026-09-09, fleet review Part C / Slice 3
  // decision (b) -- Mike picked the recommendation on the canvas). Every
  // live+turner region in tools/regions.json now carries a routes{} map
  // (home/listings/market/sell -> path); this figures out what KIND of
  // page the visitor is currently on by matching location.pathname against
  // the CURRENT site's own routes, so a hop to a sibling region can land on
  // the same kind of page there (Sell -> Sell) instead of always the
  // homepage. Peer regions (operator:"peer") and anything without a routes
  // map (recruiting regions, the hub, Labrador West) never get this
  // treatment -- their strip links stay plain, always-home hops.
  function currentPageKind() {
    var here = currentRegion();
    if (!here || !here.routes) return 'home';
    var path = window.location.pathname;
    var kinds = ['listings', 'market', 'sell']; // 'home' is the fallback, checked last
    for (var i = 0; i < kinds.length; i++) {
      var target = here.routes[kinds[i]];
      if (target && path.indexOf(target) === 0) return kinds[i];
    }
    return 'home';
  }

  // Builds the href + #via= hash for a hop to a sibling LIVE region, per the
  // route map above. Peer regions (no routes{}, no site_id) get their plain
  // domain link with no #via= -- the arrival cue only ever fires for a real
  // Turner-to-Turner hop, never for a click that leaves the network.
  function regionHref(region, kind, fromSiteKey) {
    if (!region.routes || !region.site_id) return region.domain || '#';
    var path = region.routes[kind] || region.routes.home || '/';
    return region.domain.replace(/\/$/, '') + path + '#via=' + fromSiteKey;
  }

  function regionStripHTML() {
    var cur = window.TURNER_SITE;
    var kind = currentPageKind();
    // "Choose your region:" only when this site has no region of its own
    // (the hub). A real region with no strip entry (Labrador West) still
    // reads "Serving:" -- it gets a badge instead, not the chooser label.
    var isChooser = !currentRegion();
    var links = liveRegions().map(function (r) {
      var isCurrent = !!r.site_key && r.site_key === cur;
      if (isCurrent) return '<a href="#" class="current">' + r.label + '</a>';
      // r.site is the territory key liveRegions() just iterated TURNER_REGIONS
      // BY, so this is a plain, always-correct lookup -- unlike
      // currentRegion()/regionBySiteKey above, which resolve an ARBITRARY
      // site (the current one, or a #via= one) that isn't already sitting
      // in a territory-keyed loop.
      var reg = (window.TURNER_REGIONS && window.TURNER_REGIONS[r.site]) || null;
      var href = reg ? regionHref(reg, kind, cur) : r.url;
      var peerCls = (reg && reg.operator === 'peer') ? ' peer' : '';
      return '<a href="' + href + '"' + (peerCls ? ' class="' + peerCls.trim() + '"' : '') + '>' + r.label + '</a>';
    }).join('');
    var label = isChooser ? 'Choose your region:' : 'Serving:';
    var badge = (cur === 'labwest') ? '<span class="strip-badge">Labrador West &middot; recruiting</span>' : '';
    return '<span class="region-strip-label">' + label + '</span>' + links + badge;
  }

  // Arrival cue (Ship 7, decision (a) -- a slim toast under the strip,
  // recommended on the canvas and picked by Mike). Fires only when the URL
  // carries #via=<territory> from a same-network hop (regionHref above is
  // the only thing that ever writes that hash). Reads the FROM region's own
  // name from the registry, not from the current site's data. Strips the
  // hash via replaceState right after reading it so a reload or back/
  // forward navigation never re-shows the same cue twice (Conv #115-style
  // idempotency, applied to a URL fragment instead of a DB sentinel).
  function viaFromHash() {
    var m = /^#via=([a-z0-9-]+)$/.exec(window.location.hash);
    return m ? m[1] : null;
  }
  // fromSiteKey is whatever regionHref() wrote into #via= -- window.TURNER_SITE
  // (a site_key) at the time the visitor clicked, NEVER a territory key --
  // so this resolves it the same way currentRegion() resolves the current
  // site, not via a direct TURNER_REGIONS[...] lookup.
  function cueHTML(fromSiteKey) {
    var from = regionBySiteKey(fromSiteKey);
    var here = currentRegion();
    if (!from || !here) return '';
    var kind = currentPageKind();
    var landed = (here.routes && here.routes[kind] && window.location.pathname.indexOf(here.routes[kind]) === 0)
      ? kind : 'home';
    var pageNote = (landed === 'home' && kind !== 'home')
      ? ' (no ' + kind + ' page there, so: homepage)'
      : (landed === 'home' ? '' : ' · ' + landed);
    var domain = (here.domain || '').replace(/^https?:\/\//, '');
    var backHref = regionHref(from, 'home', window.TURNER_SITE);
    return '<div class="nav-cue" role="status">' +
      '<span>Now on <b>' + here.nav_label + '</b> <span class="dom">&mdash; ' + domain + pageNote + '</span></span>' +
      '<a class="nav-cue-back" href="' + backHref + '">&larr; Back to ' + from.nav_label + '</a>' +
      '<button class="nav-cue-x" aria-label="Dismiss" type="button">&times;</button>' +
    '</div>';
  }

  function injectNav() {
    var topBar = document.querySelector('.nav-top-bar');
    if (!topBar) { topBar = document.createElement('div'); topBar.className = 'nav-top-bar'; document.body.insertBefore(topBar, document.body.firstChild); }
    topBar.innerHTML = topBarHTML();
    var regionStrip = document.querySelector('.region-strip');
    if (!regionStrip) { regionStrip = document.createElement('div'); regionStrip.className = 'region-strip'; topBar.parentNode.insertBefore(regionStrip, topBar.nextSibling); }
    regionStrip.innerHTML = regionStripHTML();

    // Arrival cue -- lives between the strip and the main bar, matching the
    // canvas's chrome order. Only ever rendered for a real #via= hop; a
    // normal page load has nothing here (no element created at all).
    var existingCue = document.querySelector('.nav-cue');
    if (existingCue) existingCue.parentNode.removeChild(existingCue);
    var viaTerritory = viaFromHash();
    if (viaTerritory) {
      var cueMarkup = cueHTML(viaTerritory);
      if (cueMarkup) {
        var cueWrap = document.createElement('div');
        cueWrap.innerHTML = cueMarkup;
        var cueEl = cueWrap.firstChild;
        regionStrip.parentNode.insertBefore(cueEl, regionStrip.nextSibling);
        var hideCue = function () { if (cueEl && cueEl.parentNode) cueEl.parentNode.removeChild(cueEl); };
        var xBtn = cueEl.querySelector('.nav-cue-x');
        if (xBtn) xBtn.addEventListener('click', hideCue);
        setTimeout(hideCue, 5000);
      }
      // Strip #via= immediately so a reload, a bookmark, or browser
      // back/forward never re-shows the same cue (Conv #115-style
      // idempotency, applied to a URL fragment instead of a DB sentinel).
      try { window.history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) { /* very old browsers: hash just stays, harmless */ }
    }

    var mainBar = document.querySelector('.nav-main-bar');
    if (!mainBar) { mainBar = document.createElement('nav'); mainBar.className = 'nav-main-bar'; regionStrip.parentNode.insertBefore(mainBar, (document.querySelector('.nav-cue') || regionStrip).nextSibling); }
    mainBar.innerHTML = navMainHTML;

    // Ship 5 (2026-09-08): fleet-wide skip link, injected once here instead
    // of relying on each generator/hand-authored page to add its own (that
    // hand-authored pattern is why coverage was 3% on Goose Bay / 21% on
    // Gander / 62% on Avalon, and inconsistent even where present -- Gander
    // alone has 1440 hand-authored .skip-nav anchors against only 1013
    // pages carrying the #main-content target they point at). Inserted as
    // the true first element in <body> -- ahead of the nav bars this
    // function just placed there -- so it's first in keyboard tab order.
    // Idempotent like every block above/below; targets #main-content where
    // a page has it, harmless where it doesn't (main.css's .skip-nav:focus
    // rule is already fleet-wide Tier-1, unchanged here).
    if (!document.querySelector('.skip-nav')) {
      var skip = document.createElement('a');
      skip.className = 'skip-nav';
      skip.href = '#main-content';
      skip.textContent = 'Skip to content';
      skip.style.cssText = 'position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden;';
      document.body.insertBefore(skip, document.body.firstChild);
    }

    var toggle = mainBar.querySelector('.nav-toggle'), links = mainBar.querySelector('.nav-main-links');

    // Hamburger — verbatim from mobile-nav.js incl. the scroll-lock sync (2026-05-29 page-freeze fix)
    if (toggle && links) {
      document.body.classList.toggle('nav-menu-open', links.classList.contains('open'));
      toggle.addEventListener('click', function () {
        links.classList.toggle('open');
        toggle.classList.toggle('active');
        var isOpen = links.classList.contains('open');
        document.body.classList.toggle('nav-menu-open', isOpen);
        if (!isOpen) closeAllDropdowns(mainBar);
      });
    }
    // Dropdown tap (mobile only ≤1024 — desktop uses :hover)
    var dt = mainBar.querySelectorAll('.nav-dropdown > a');
    for (var i = 0; i < dt.length; i++) (function (trigger) {
      trigger.addEventListener('click', function (e) {
        if (window.innerWidth <= 1024) {
          e.preventDefault();
          var parent = trigger.parentElement;
          var od = mainBar.querySelectorAll('.nav-dropdown.open');
          for (var j = 0; j < od.length; j++) if (od[j] !== parent) od[j].classList.remove('open');
          parent.classList.toggle('open');
        }
      });
    })(dt[i]);
    // Submenu tap (mobile only)
    var st = mainBar.querySelectorAll('.nav-submenu > a');
    for (var s = 0; s < st.length; s++) (function (trigger) {
      trigger.addEventListener('click', function (e) {
        if (window.innerWidth <= 1024) { e.preventDefault(); trigger.parentElement.classList.toggle('open'); }
      });
    })(st[s]);
    // Close menu/dropdowns on outside tap (mobile)
    document.addEventListener('click', function (e) {
      if (window.innerWidth <= 1024 && !(e.target.closest && e.target.closest('.nav-main-bar'))) {
        closeAllDropdowns(mainBar);
        if (links && links.classList.contains('open')) {
          links.classList.remove('open');
          if (toggle) toggle.classList.remove('active');
          document.body.classList.remove('nav-menu-open');
        }
      }
    });
    // Close after tapping a real DESTINATION link. Excludes dropdown-label
    // triggers (".nav-dropdown > a") even when they carry a real href (a
    // top-level dropdown item can now navigate on desktop hover-click,
    // e.g. Gander's Listings/Communities) -- without this exclusion,
    // tapping such a label on mobile fires BOTH handlers on the same
    // click: the dropdown-tap-handler above opens the dropdown, then this
    // one immediately closes the whole menu again, netting out to
    // "nothing visibly happens." (Ported from Gander's original nav.js,
    // which caught this by live-testing, not by reading code.)
    if (links) {
      var ra = links.querySelectorAll('a[href]:not([href="#"])');
      for (var a = 0; a < ra.length; a++) (function (link) {
        if (link.parentElement && link.parentElement.classList.contains('nav-dropdown')) return;
        link.addEventListener('click', function () {
          if (window.innerWidth <= 1024) {
            links.classList.remove('open');
            if (toggle) toggle.classList.remove('active');
            document.body.classList.remove('nav-menu-open');
            closeAllDropdowns(mainBar);
          }
        });
      })(ra[a]);
    }
    // Highlight current page (Avalon)
    var here = window.location.pathname.split('/').pop() || 'index.html';
    var allLinks = mainBar.querySelectorAll('a[href]');
    for (var k = 0; k < allLinks.length; k++) {
      var href = allLinks[k].getAttribute('href');
      if (href && href !== '#' && href.split('/').pop() === here) allLinks[k].setAttribute('aria-current', 'page');
    }

    // Portal P1 (2026-08-18): tell nav-auth.js the nav bars were just
    // (re)written via innerHTML, so it can (re)append the state-aware
    // Sign in / My Account entry that innerHTML replacement wipes.
    try { document.dispatchEvent(new CustomEvent('turner:nav-injected')); } catch (e) { /* old browsers: link renders on DOMContentLoaded instead */ }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', injectNav);
  else injectNav();
})();
