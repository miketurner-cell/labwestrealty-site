/* app-shell.js — the installable client app shell (fleet canonical, 3 sites).
 *
 * Loaded (defer) wherever js/nav-auth.js is loaded. Zero dependencies.
 * Convention #74 fail-safe throughout: the website is complete without this
 * file; it only ever ADDS.
 *
 * What it does, in order:
 *   1. Detects "standalone" (installed-to-home-screen) mode and stamps
 *      html[data-app-mode="standalone"|"browser"] + data-app-platform, which
 *      is the single CSS/JS hook every other surface keys on.
 *   2. Injects the web-app manifest + theme-color meta at runtime on pages
 *      whose generator didn't bake them (the baked snippet carries data-baked).
 *   3. Registers /sw.js.
 *   4. Captures Android/Chrome's beforeinstallprompt, tracks appinstalled.
 *   5. Fires GA4 app_open (once per session) / app_first_open (once ever)
 *      in standalone — the iOS proxy for an install, which iOS never reports.
 *   6. Shows a non-nagging install CTA (account page always; listing pages
 *      after 3 listing views; never on the homepage; never in standalone;
 *      dismiss = 30 days).
 *   7. In standalone, mounts a bottom tab bar (Back · Home · Search · Saved ·
 *      Alerts · Account) — iOS standalone has no browser back button.
 *
 * Why sign-in is different in standalone: an iOS home-screen app has its OWN
 * storage partition, and a magic link tapped in Mail completes in Safari, not
 * here. The sign-in surfaces (saved-search.js, vow-gate.js, home-sold.js,
 * account.html) read TurnerApp.isStandalone() and go code-first. See
 * ~/.claude/plans/can-we-make-an-sprightly-floyd.md.
 */
(function () {
  "use strict";
  if (window.TurnerApp) return;

  var CSS_URL = "/css/app-shell.css?v=20261006-app9";
  var SW_URL = "/sw.js";
  var MANIFEST_URL = "/app.webmanifest";
  var ICON_192 = "/images/app-icon-192.png";
  var THEME = "#EA002A";
  var DISMISS_DAYS = 30;
  var LISTING_VIEWS_BEFORE_CTA = 3;

  var ls = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  var ss = {
    get: function (k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { sessionStorage.setItem(k, v); } catch (e) {} }
  };

  // ── Keyboard watch (shared snippet, fleet 2026-10-06) ───────────────────
  // Same block is carried by js/app-shell.js, js/mobile-action-bar.js and
  // js/chat-widget.js; whichever runs first installs it (window.__tnrKbWatch).
  // Sets html.tnr-kb-open while a phone keyboard is up: the visual viewport is
  // much shorter than the layout viewport, OR (touch devices) a text field has
  // focus. CSS keyed on that class hides the sticky Call/Text/Book bar, the
  // chat launcher, the "Get the app" card and the Registry pill; the chat
  // panel sizes itself to the visual viewport. Fires "tnr:keyboard".
  (function () {
    if (window.__tnrKbWatch) return;
    window.__tnrKbWatch = true;
    var root = document.documentElement, vv = window.visualViewport;
    var on = false, focused = false, timer = null, touch = false;
    try { touch = (navigator.maxTouchPoints || 0) > 0 || (window.matchMedia && window.matchMedia("(pointer:coarse)").matches); } catch (e) {}
    function isField(el) {
      if (!el || el.nodeType !== 1) return false;
      if (el.tagName === "TEXTAREA") return !el.readOnly;
      if (el.tagName === "INPUT") return !/^(button|checkbox|radio|submit|reset|file|image|range|color|hidden|date|time|datetime-local|month|week)$/i.test(el.type || "text");
      return !!el.isContentEditable;
    }
    function update() {
      var shrunk = !!vv && vv.scale <= 1.02 && (window.innerHeight - vv.height) > 150;
      var now = shrunk || (touch && focused);
      if (now === on) return;
      on = now;
      root.classList.toggle("tnr-kb-open", on);
      try { window.dispatchEvent(new CustomEvent("tnr:keyboard", { detail: { open: on } })); } catch (e) {}
    }
    document.addEventListener("focusin", function (e) { focused = isField(e.target); update(); });
    document.addEventListener("focusout", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { focused = isField(document.activeElement); update(); }, 80);
    });
    if (vv) vv.addEventListener("resize", update);
  })();

  // ── 1. Detection ───────────────────────────────────────────────────────
  var ua = navigator.userAgent || "";
  function isIOS() {
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }
  function isAndroid() { return /Android/i.test(ua); }
  function isSafari() { return isIOS() && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|FBAN|FBAV|Instagram/.test(ua); }

  // ?src=app / ?src=app-shortcut / ?src=push are GA4 attribution only — they
  // are NOT proof of an install. The manifest's start_url/shortcuts and a
  // push notification's click-through both carry ?src=..., but so does any
  // ordinary browser tab that follows a link with that query string (e.g.
  // pages/get-the-app.html's Sign in button, a shared push-deeplink) — none
  // of those mean the page is running installed. Bug 2026-09-20: this used
  // to sessionStorage-latch app mode off ?src alone, which meant clicking
  // "Sign in" on get-the-app.html in a normal desktop/iPad browser tab
  // silently hid the site's whole top nav + region strip + footer for the
  // rest of that tab's life (css/app-shell.css hides them in standalone,
  // and hides the standalone-only tab bar too at >=900px, leaving NO
  // navigation at all). Real install detection lives in isStandalone()
  // below and does not depend on this query string.
  //
  // ?appmode=1 / ?appmode=0 is the explicit, harmless test hook (no real
  // link ever sets it) for exercising standalone mode from a normal tab.
  try {
    var appmodeParam = new URLSearchParams(location.search).get("appmode");
    if (appmodeParam === "1") ss.set("tnr-app-test", "1");
    else if (appmodeParam === "0") { try { sessionStorage.removeItem("tnr-app-test"); } catch (e) {} }
    // Heal any tab stuck by the old ?src=app/app-shortcut/push latch.
    try { sessionStorage.removeItem("tnr-app-mode"); } catch (e) {}
  } catch (e) {}

  function isStandalone() {
    try {
      if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) return true;
      if (window.matchMedia && window.matchMedia("(display-mode: minimal-ui)").matches) return true;
    } catch (e) {}
    if (navigator.standalone === true) return true;
    if (ss.get("tnr-app-test") === "1") return true;
    return false;
  }
  function isInstalled() { return isStandalone() || ls.get("tnr-app-installed") === "1"; }

  var standalone = isStandalone();
  // The app's own pages (pages/app.html) always run with the app chrome —
  // tab bar, app-mode copy — even when opened in a plain browser tab.
  try { if (document.body && document.body.getAttribute("data-app-shell") === "always") standalone = true; } catch (e) {}
  var platform = isIOS() ? "ios" : (isAndroid() ? "android" : "other");
  try {
    document.documentElement.setAttribute("data-app-mode", standalone ? "standalone" : "browser");
    document.documentElement.setAttribute("data-app-platform", platform);
  } catch (e) {}

  // ── 2. Manifest / meta injection (best-effort for un-baked pages) ─────
  function ensureHead() {
    try {
      var head = document.head;
      if (!head) return;
      if (!head.querySelector('link[rel="manifest"]')) {
        var l = document.createElement("link"); l.rel = "manifest"; l.href = MANIFEST_URL; head.appendChild(l);
      }
      if (!head.querySelector('meta[name="theme-color"]')) {
        var m = document.createElement("meta"); m.name = "theme-color"; m.content = THEME; head.appendChild(m);
      }
    } catch (e) {}
  }

  // ── 3. Service worker ─────────────────────────────────────────────────
  var swRegistration = null;
  var swReady = new Promise(function (resolve) {
    var secure = location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1";
    if (!("serviceWorker" in navigator) || !secure) { resolve(null); return; }
    var go = function () {
      navigator.serviceWorker.register(SW_URL, { scope: "/" }).then(function (reg) {
        swRegistration = reg; resolve(reg);
      }).catch(function (err) {
        try { console.warn("TurnerApp: service worker registration failed:", err); } catch (e) {}
        resolve(null);
      });
    };
    if (document.readyState === "complete") go(); else window.addEventListener("load", go);
  });

  // ── GA4 helper ────────────────────────────────────────────────────────
  function ga(name, params) {
    try {
      if (typeof window.gtag !== "function") return;
      var p = params || {};
      p.app_platform = platform;
      p.app_mode = standalone ? "standalone" : "browser";
      window.gtag("event", name, p);
    } catch (e) {}
  }

  // ── 4. Install prompt capture ─────────────────────────────────────────
  var deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredPrompt = e;
    ga("app_install_available");
    maybeShowCta();
  });
  window.addEventListener("appinstalled", function () {
    ls.set("tnr-app-installed", "1");
    ga("app_installed");
    hideInstallCta();
  });
  function canPromptInstall() { return !!deferredPrompt; }
  function promptInstall() {
    if (!deferredPrompt) return Promise.resolve("unavailable");
    var ev = deferredPrompt; deferredPrompt = null;
    try { ev.prompt(); } catch (e) { return Promise.resolve("unavailable"); }
    return (ev.userChoice || Promise.resolve({ outcome: "dismissed" })).then(function (c) {
      var outcome = (c && c.outcome) || "dismissed";
      ga("app_install_prompt_" + outcome);
      return outcome;
    }).catch(function () { return "dismissed"; });
  }

  // ── 5. Standalone analytics ───────────────────────────────────────────
  if (standalone) {
    try { if (typeof window.gtag === "function") window.gtag("set", "user_properties", { app_mode: "standalone" }); } catch (e) {}
    if (!ss.get("tnr-app-open-counted")) {
      ss.set("tnr-app-open-counted", "1");
      ga("app_open", { page_path: location.pathname });
    }
    if (!ls.get("tnr-app-first-open")) {
      ls.set("tnr-app-first-open", String(Date.now()));
      ls.set("tnr-app-installed", "1");
      ga("app_first_open");
    }
  }

  // ── CSS loader ────────────────────────────────────────────────────────
  var cssLoaded = false;
  function ensureCss() {
    if (cssLoaded) return;
    cssLoaded = true;
    try {
      var l = document.createElement("link"); l.rel = "stylesheet"; l.href = CSS_URL;
      document.head.appendChild(l);
    } catch (e) {}
  }

  // ── 6. Install CTA ────────────────────────────────────────────────────
  var ctaEl = null;
  // The chat launcher (js/chat-widget.js) lifts itself above this card while
  // both show; tell it whenever the card appears or goes away.
  function floatingChanged() { try { window.dispatchEvent(new CustomEvent("tnr:floating")); } catch (e) {} }
  function pathIsListing() { return /^\/(listings|property)\//.test(location.pathname) || /\/listing-detail\.html$/.test(location.pathname); }
  function pathIsAccount() { return /\/pages\/(account|app|saved|get-the-app)\.html$/.test(location.pathname); }
  function pathIsHome() { return location.pathname === "/" || location.pathname === "/index.html"; }
  function manifestBaked() { try { return !!document.querySelector('link[rel="manifest"][data-baked]'); } catch (e) { return false; } }

  // Count listing views (browser mode only) — the CTA waits for 3.
  if (!standalone && pathIsListing()) {
    var n = parseInt(ls.get("tnr-app-views") || "0", 10) || 0;
    ls.set("tnr-app-views", String(n + 1));
  }

  // FORM_CLEAR (redesign 2026-10-09, Mike D-1009-77 item 5): with the switch on
  // (window.SITE.formClear === 'on', or ?formclear=on; ?formclear=off forces it off)
  // the card never shows on a listing or property page before real engagement.
  // REAL ENGAGEMENT = ALL of: (1) 2 or more page views in this browser session,
  // counted here on every page that loads this file; (2) 20 seconds on this page;
  // (3) no form field has focus right now. The card is also hidden by CSS while a
  // form is in view (html.tnr-form-clear). Switch off = the rules above, unchanged.
  var FC_MIN_VIEWS = 2, FC_MIN_MS = 20000, FC_T0 = Date.now(), FC_PV = 0;
  var FC_ON = /[?&]formclear=on(&|$)/.test(location.search || "") ||
    (!!(window.SITE && window.SITE.formClear === "on") && !/[?&]formclear=off(&|$)/.test(location.search || ""));
  if (FC_ON) {
    FC_PV = (parseInt(ss.get("tnr-pv") || "0", 10) || 0) + 1;
    ss.set("tnr-pv", String(FC_PV));
  }
  function fcFieldFocused() {
    var a = document.activeElement;
    return !!a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== "hidden";
  }
  function fcEngaged() {
    return FC_PV >= FC_MIN_VIEWS && (Date.now() - FC_T0) >= FC_MIN_MS && !fcFieldFocused();
  }
  if (FC_ON) {
    // re-check when the 20 s are up and whenever a field loses focus
    setTimeout(function () { maybeShowCta(); }, FC_MIN_MS + 100);
    document.addEventListener("focusout", function () { setTimeout(function () { maybeShowCta(); }, 400); });
  }

  function ctaAllowedHere() {
    if (standalone || isInstalled()) return false;
    if (FC_ON && pathIsListing() && !fcEngaged()) return false;
    if (window.innerWidth >= 900) return false;
    if (pathIsHome()) return false;
    if (!manifestBaked()) return false;
    var dismissed = parseInt(ls.get("tnr-a2hs-dismissed") || "0", 10) || 0;
    if (dismissed && (Date.now() - dismissed) < DISMISS_DAYS * 86400000) return false;
    if (pathIsAccount()) return true;
    if (pathIsListing()) return (parseInt(ls.get("tnr-app-views") || "0", 10) || 0) >= LISTING_VIEWS_BEFORE_CTA;
    return false;
  }
  function installSteps() {
    if (isIOS()) {
      if (!isSafari()) return "Open this page in <b>Safari</b>, then tap <b>Share</b> and <b>Add to Home Screen</b>.";
      return "Tap <b>Share</b> <span aria-hidden=\"true\">&#x2191;</span> then <b>Add to Home Screen</b>.";
    }
    if (deferredPrompt) return "Get the app on your home screen — listings, saved homes and alerts in one tap.";
    return "In Chrome, open the <b>&#8942;</b> menu and tap <b>Install app</b> or <b>Add to Home screen</b>.";
  }
  function showInstallCta(opts) {
    opts = opts || {};
    if (ctaEl) { ctaEl.classList.add("is-visible"); floatingChanged(); return ctaEl; }
    ensureCss();
    ctaEl = document.createElement("div");
    ctaEl.id = "tnr-install-cta";
    ctaEl.setAttribute("role", "region");
    ctaEl.setAttribute("aria-label", "Get the app");
    ctaEl.innerHTML =
      '<img src="' + ICON_192 + '" alt="" width="40" height="40">' +
      '<div class="tnr-install-body"><strong>' + (opts.title || "Get the app on your phone") + '</strong>' +
      '<div class="tnr-install-steps">' + installSteps() + '</div></div>' +
      (deferredPrompt ? '<button type="button" class="tnr-install-btn">Install</button>' : '') +
      '<button type="button" class="tnr-install-dismiss" aria-label="Dismiss">&times;</button>';
    document.body.appendChild(ctaEl);
    // Sit above anything else pinned to the bottom edge (the listing page's
    // own CTA bar, the lead-form sticky bar, the BoldTrail "Call / Text"
    // iframe from widgetbe.com) instead of underneath it.
    try {
      var clearance = 0;
      Array.prototype.forEach.call(document.body.children, function (el) {
        // The card must not stack on the floating widgets that now stack on IT.
        if (el === ctaEl || el.id === "tnr-tabbar" || el.id === "tc-bubble" || el.id === "tc-panel" || el.id === "tc-registry-pill") return;
        var cs = window.getComputedStyle(el);
        if (cs.position !== "fixed" || cs.display === "none") return;
        var b = parseInt(cs.bottom, 10);
        if (isNaN(b) || b > 20) return;
        var h = el.offsetHeight || 0;
        if (h > 0 && h < 160) clearance = Math.max(clearance, b + h);
      });
      if (clearance) ctaEl.style.bottom = "calc(" + (clearance + 10) + "px + env(safe-area-inset-bottom, 0px))";
    } catch (e) {}
    var btn = ctaEl.querySelector(".tnr-install-btn");
    if (btn) btn.addEventListener("click", function () { ga("app_install_cta_click"); promptInstall(); });
    ctaEl.querySelector(".tnr-install-dismiss").addEventListener("click", function () {
      ls.set("tnr-a2hs-dismissed", String(Date.now()));
      ga("app_install_cta_dismiss");
      hideInstallCta();
    });
    ctaEl.classList.add("is-visible");
    floatingChanged();
    ga("app_install_cta_shown");
    return ctaEl;
  }
  function hideInstallCta() { if (ctaEl) { ctaEl.classList.remove("is-visible"); floatingChanged(); } }
  function maybeShowCta() { if (ctaAllowedHere()) showInstallCta(); }

  // ── 7. Standalone tab bar ─────────────────────────────────────────────
  var ICONS = {
    back: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
    home: '<svg viewBox="0 0 24 24"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    saved: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z"/></svg>',
    account: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/></svg>'
  };
  // Four tabs (design canvas "Turner Realty App", 2026-09-13): Home is the
  // personal feed on pages/app.html; alerts arrive there and are managed
  // under Account, so there is no separate Alerts tab.
  var TABS = [
    { key: "home", label: "Home", href: "/pages/app.html", match: function (p) { return /\/pages\/app\.html$/.test(p) || p === "/" || p === "/index.html"; } },
    { key: "search", label: "Search", href: "/listings/", match: function (p) { return /^\/(listings|property)\//.test(p) && p.indexOf("/listings/sold") !== 0; } },
    { key: "saved", label: "Saved", href: "/pages/saved.html", match: function (p) { return /\/pages\/saved\.html$/.test(p); } },
    { key: "account", label: "Account", href: "/pages/account.html", match: function (p) { return /\/pages\/account\.html$/.test(p); } }
  ];
  function mountTabBar() {
    if (document.getElementById("tnr-tabbar")) return;
    ensureCss();
    var nav = document.createElement("nav");
    nav.id = "tnr-tabbar";
    nav.setAttribute("aria-label", "App navigation");
    var html = '<button type="button" data-tab="back" aria-label="Back"' + (window.history.length > 1 ? '' : ' hidden') + '>' + ICONS.back + '<span>Back</span></button>';
    TABS.forEach(function (t) {
      var active = t.match(location.pathname) ? " is-active" : "";
      html += '<a href="' + t.href + '" data-tab="' + t.key + '" class="' + active.trim() + '"' + (active ? ' aria-current="page"' : '') + '>' + ICONS[t.key] + '<span>' + t.label + '</span></a>';
    });
    nav.innerHTML = html;
    document.body.appendChild(nav);
    nav.querySelector('[data-tab="back"]').addEventListener("click", function () { window.history.back(); });
  }

  // ── Search screen (app mode) ──────────────────────────────────────────
  // /listings/ already carries the full search shell; in app mode it is the
  // Search tab. Mark the body so css/app-shell.css can restyle the topbar,
  // move the count + Map toggle into their own row under the chips, and
  // float the drawer's own "Save this search" button above the tab bar
  // (moving the element keeps listings-index.js's click handlers).
  function mountSearchChrome() {
    var shell = document.querySelector(".ldisc-shell");
    if (!shell) return;
    document.body.classList.add("tnr-app-search");
    ensureCss();
    try {
      var topbar = shell.querySelector(".ldisc-topbar");
      var count = shell.querySelector(".ldisc-result-count");
      var toggle = shell.querySelector(".ldisc-view-toggle");
      var chips = shell.querySelector(".ldisc-chips");
      if (topbar && count && toggle && !topbar.querySelector(".tnr-search-meta")) {
        var meta = document.createElement("div");
        meta.className = "tnr-search-meta";
        meta.appendChild(count); meta.appendChild(toggle);
        if (chips && chips.parentNode === topbar) topbar.insertBefore(meta, chips.nextSibling); else topbar.appendChild(meta);
      }
      var save = shell.querySelector(".ldisc-rail .ldisc-save-search");
      if (save && !document.getElementById("tnr-save-pill")) {
        var pill = document.createElement("div");
        pill.id = "tnr-save-pill";
        pill.appendChild(save);
        document.body.appendChild(pill);
      }
    } catch (e) { /* Conv #74: the page still works as the plain search shell */ }
  }

  // ── Listing screen (app mode) ─────────────────────────────────────────
  // Listing detail pages keep their generator markup; css/app-shell.css
  // turns the gallery into a full-bleed hero, and this overlays back /
  // share / save on it by MOVING the page's own share + save buttons
  // (their handlers — listing-share.js, favorites.js — travel with them).
  function mountListingChrome() {
    var shell = document.querySelector(".lst-shell");
    var wrap = shell && shell.querySelector(".lst-gallery-wrap");
    if (!shell || !wrap || document.querySelector(".tnr-hero-actions")) return;
    document.body.classList.add("tnr-app-listing");
    ensureCss();
    try {
      var bar = document.createElement("div");
      bar.className = "tnr-hero-actions";
      var back = document.createElement("button");
      back.type = "button"; back.className = "tnr-hero-btn"; back.setAttribute("aria-label", "Back");
      back.innerHTML = ICONS.back;
      back.addEventListener("click", function () {
        if (window.history.length > 1) window.history.back(); else window.location.href = "/listings/";
      });
      var right = document.createElement("div");
      right.className = "tnr-hero-right";
      var share = shell.querySelector(".lst-share-row .lst-share-btn");
      var fav = shell.querySelector(".lst-share-row .lst-fav-btn");
      if (share) right.appendChild(share);
      if (fav) right.appendChild(fav);
      bar.appendChild(back); bar.appendChild(right);
      wrap.appendChild(bar);
      // The generator's breadcrumb is an unclassed inline-styled <nav>
      // above the gallery; the hero's Back button replaces it here.
      Array.prototype.forEach.call(document.querySelectorAll("nav:not([class])"), function (n) {
        if (/Listings/.test(n.textContent || "")) n.hidden = true;
      });
    } catch (e) { /* Conv #74: the page still works as the plain listing page */ }
  }

  // ── Account screen (app mode) ─────────────────────────────────────────
  // pages/account.html stays the real sign-in-gated account page (reachable
  // from a plain browser tab too); in app mode it becomes the Account tab.
  // Inject an avatar into the existing .acc-hero once a session resolves
  // (mirrors Home/Saved's #ah-avatar), and let css/app-shell.css's
  // body.tnr-app-account rules do the rest (hide the sections now owned by
  // the Home/Saved tabs, restyle what's left into compact cards).
  function mountAccountChrome() {
    if (!/\/pages\/account\.html$/.test(location.pathname)) return;
    document.body.classList.add("tnr-app-account");
    ensureCss();
    if (!window.TurnerAuth) return;
    var paint = function (u) {
      var hero = document.querySelector(".acc-hero");
      if (!hero || hero.querySelector(".acc-hero-avatar")) return;
      var av = document.createElement("div");
      av.className = "acc-hero-avatar";
      av.textContent = (u && u.email) ? String(u.email).charAt(0).toUpperCase() : "";
      hero.insertBefore(av, hero.firstChild);
    };
    window.TurnerAuth.ready.then(function () {
      var u = window.TurnerAuth.getUser && window.TurnerAuth.getUser();
      if (u) paint(u);
    });
    window.TurnerAuth.onAuthChange(function (event, session) {
      if (session && session.user) paint(session.user);
    });
  }

  // ── Boot ──────────────────────────────────────────────────────────────
  function boot() {
    ensureHead();
    if (standalone) {
      mountTabBar();
      mountSearchChrome();
      mountListingChrome();
      mountAccountChrome();
    } else {
      maybeShowCta();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();

  window.TurnerApp = {
    isStandalone: isStandalone,
    isIOS: isIOS,
    isAndroid: isAndroid,
    isSafari: isSafari,
    isInstalled: isInstalled,
    canPromptInstall: canPromptInstall,
    promptInstall: promptInstall,
    showInstallCta: showInstallCta,
    hideInstallCta: hideInstallCta,
    installSteps: installSteps,
    swReady: swReady,
    get swRegistration() { return swRegistration; },
    ga: ga
  };
})();
