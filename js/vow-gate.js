/**
 * VOW Gate — Supabase Auth-backed sign-in gate for sold-listings access.
 *
 * REWRITTEN 2026-05-19 for Phase B1. The previous version used a Netlify-
 * Forms-backed email+name+consent form that stored a `vow_gate_v1` token
 * in localStorage. That worked on a single device but failed on mobile
 * when the user originally registered on desktop (or vice versa) — Mike's
 * mobile-VOW-broken pain point.
 *
 * New flow:
 *   1. On page load, check TurnerAuth.getSession() (window.TurnerAuth from js/auth.js)
 *   2. Authenticated → unlock (dispatch vow:unlocked, hide gate)
 *   3. Not authenticated → render minimal sign-in UI: email input + "Send sign-in link"
 *   4. User submits email → TurnerAuth.sendMagicLink(email) → show "Check your email" state
 *   5. User clicks link in email (any device) → Supabase auto-detects token in URL hash
 *      → SIGNED_IN event fires → onAuthChange handler unlocks the page
 *
 * Cross-device works because each device authenticates independently against
 * the same Supabase user. Sign in on phone → phone has session. Sign in on
 * desktop with same email → desktop also has its own session. Both unlock.
 *
 * The vow:unlocked event signature stays identical so js/sold-listings.js
 * and js/sold-detail.js need ZERO changes (Convention #75 two-path init).
 *
 * Legacy localStorage fallback: if TurnerAuth is the stub (Supabase SDK
 * missing) AND the legacy `vow_gate_v1` token is still present (from a
 * previous registration), accept it for backward compat. This avoids
 * locking out users who registered under the old flow.
 *
 * Dependencies (in load order):
 *   1. https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2  (CDN)
 *   2. /js/auth.js                                          (TurnerAuth)
 *   3. /js/vow-gate.js                                      (this file)
 *
 * Convention compliance:
 *   - #18 — silent-degraded-output guarded: TurnerAuth stub triggers legacy
 *           fallback, not silent broken UI
 *   - #74 — fail-safe at every layer (missing SDK, missing TurnerAuth,
 *           missing session, sendMagicLink network error)
 *   - #75 — Two-path init: ready Promise + auth-state event listener
 */

(function () {
  "use strict";

  // ── Legacy compat ──
  var LEGACY_KEY = "vow_gate_v1";

  // ── DOM ──
  var gateEl = document.getElementById("vow-gate");
  var pageEl = document.getElementById("page");
  var userStrip = document.getElementById("user-strip");

  // Container we'll replace with the new sign-in UI. The existing form
  // (Netlify Forms, 4 fields) is fully replaced in this rewrite.
  var cardEl = gateEl ? gateEl.querySelector(".vow-card") : null;

  if (!gateEl || !pageEl || !cardEl) {
    console.warn("VOW gate: required DOM elements missing; skipping.");
    return;
  }

  // Where sign-in brings the visitor back to (D-1009-69 item 7): a valid
  // ?next= on this page (a card elsewhere sent them here to sign in), else
  // this page. TurnerAuth.returnTarget() validates it to this site only.
  function returnHere() {
    try {
      if (window.TurnerAuth && window.TurnerAuth.returnTarget) return window.TurnerAuth.returnTarget();
    } catch (e) { /* fall through */ }
    return window.location.href;
  }
  function emailLinkOpts(app) {
    return app ? { emailRedirectTo: window.location.origin + "/pages/account.html?src=applink" }
               : { emailRedirectTo: returnHere() };
  }

  // ── Soft gate (Mobile+iPad review B6, 2026-09-17) ──────────────────────
  // Old behavior: this full-screen modal rendered on top of EVERYTHING the
  // instant the script ran, so a first-time visitor to /listings/sold/ saw
  // only a sign-up card -- not even that sold listings exist. Verified
  // before changing this: the #vow-gate/#page/.vow-card markup this file
  // requires (the guard just above) exists ONLY on /listings/sold/,
  // listings/sold/detail.html, and the per-city sold rollups -- every other
  // page that loads vow-gate.js (individual active-listing pages, the agent
  // dashboard) has none of these elements and already bails out above. So
  // softening the gate here is correctly scoped to the sold-listings family
  // without needing a new per-page marker.
  //
  // New model: the underlying page is ALWAYS visible. Ungated fields
  // (address, photos, sold date, property type, beds/baths, DOM) render
  // normally; js/sold-listings.js and js/sold-detail.js are responsible for
  // keeping the actual sold PRICE -- the only field CREA Rule 5(k) requires
  // behind registration -- out of the page for an unauthenticated visitor,
  // rendering a "Sign in to see sold price" tap target in its place. That
  // tap calls window.TurnerVowGate.open() (defined below), which is the
  // ONLY thing that changed: WHEN this modal shows, never HOW sign-in works.
  pageEl.classList.add("live");
  gateEl.style.display = "none";

  // ── Way out + header stays usable (D-1009-55, 2026-10-09) ─────────────
  // The sign-in card used to open as a full-screen fixed overlay at
  // z-index 9999 with no close control: it covered the site header and the
  // only exits were signing in or reloading. Now: (1) the overlay starts
  // BELOW the header (top = the header's bottom edge) and one z-step under
  // it, so the nav, its menu and its links stay clickable; (2) the card
  // carries a visible close button and a "Back to listings" link; (3)
  // Escape and a click on the dimmed backdrop also close it. Closing only
  // hides the card -- the sold price is still withheld by sold-listings.js /
  // sold-detail.js for a signed-out visitor; nothing here touches that.
  var lastFocus = null;
  function headerBottom() {
    var nav = document.querySelector(".nav-main-bar");
    if (!nav) return { top: 0, z: 0 };
    var r = nav.getBoundingClientRect();
    var z = parseInt(window.getComputedStyle(nav).zIndex, 10);
    return { top: Math.max(0, Math.round(r.bottom)), z: isNaN(z) ? 0 : z };
  }
  function placeBelowHeader() {
    var h = headerBottom();
    gateEl.style.top = h.top + "px";
    gateEl.style.zIndex = String(h.z > 1 ? h.z - 1 : 999);
    cardEl.style.maxHeight = "calc(100dvh - " + (h.top + 32) + "px)";
  }
  function closeGate() {
    gateEl.style.display = "none";
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
  }
  function gateIsOpen() { return gateEl.style.display !== "none"; }
  function ensureExit() {
    if (cardEl.querySelector(".vow-x")) return;
    var x = document.createElement("button");
    x.type = "button";
    x.className = "vow-x";
    x.setAttribute("aria-label", "Close sign-in");
    x.innerHTML = "&times;";
    x.addEventListener("click", closeGate);
    cardEl.insertBefore(x, cardEl.firstChild);
    var back = document.createElement("a");
    back.className = "vow-back";
    back.href = "/listings/";
    back.textContent = "Back to listings";
    cardEl.appendChild(back);
  }
  (function wireExit() {
    var st = document.createElement("style");
    st.id = "vow-exit-styles";
    st.textContent =
      ".vow-x{position:sticky;top:0;float:right;margin:-18px -18px 0 8px;width:40px;height:40px;" +
        "border:0;border-radius:50%;background:rgba(160,160,160,.18);color:inherit;font-size:26px;" +
        "line-height:1;cursor:pointer;z-index:2;}" +
      ".vow-x:hover,.vow-x:focus-visible{background:rgba(160,160,160,.38);}" +
      ".vow-back{display:block;clear:both;margin-top:18px;text-align:center;font-size:14px;" +
        "font-weight:600;color:inherit;text-decoration:underline;}";
    document.head.appendChild(st);
    gateEl.setAttribute("role", "dialog");
    gateEl.setAttribute("aria-modal", "true");
    gateEl.addEventListener("click", function (ev) { if (ev.target === gateEl) closeGate(); });
    document.addEventListener("keydown", function (ev) {
      if ((ev.key === "Escape" || ev.key === "Esc") && gateIsOpen()) closeGate();
    });
    window.addEventListener("resize", function () { if (gateIsOpen()) placeBelowHeader(); });
    // The header is built by nav.js after this script may already have opened the card (the 401 path opens it on first paint), so
    // re-measure when the page finishes loading and whenever the header's own size changes.
    window.addEventListener("load", function () { if (gateIsOpen()) placeBelowHeader(); });
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { if (gateIsOpen()) placeBelowHeader(); });
      ro.observe(document.body);
      var hdrEls = document.querySelectorAll(".nav-top-bar,.nav-main-bar");
      for (var i = 0; i < hdrEls.length; i++) ro.observe(hdrEls[i]);
    }
    // renderSignIn / the check-email step replace the card's innerHTML;
    // re-attach the exit controls whenever they are wiped.
    new MutationObserver(function () { if (gateIsOpen()) ensureExit(); })
      .observe(cardEl, { childList: true });
  })();

  function openGate(initialError) {
    lastFocus = document.activeElement;
    placeBelowHeader();
    gateEl.style.display = "";
    renderSignIn(initialError);
    ensureExit();
    var x = cardEl.querySelector(".vow-x");
    if (x && x.focus) { try { x.focus({ preventScroll: true }); } catch (e) {} }
  }
  window.TurnerVowGate = window.TurnerVowGate || {};
  window.TurnerVowGate.open = openGate;

  // page_view fires unconditionally -- top of the VOW-gate funnel, whether
  // the visitor ends up seeing the gate (not signed in) or unlocking
  // immediately (already authenticated). Fired once per page load, no
  // dedup needed -- a real page load is a real page_view.
  fireFunnelEvent("page_view");

  // ── Helpers ──
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // A hash-carried auth error (Supabase redirects with #error_code=...
  // on an expired or already-used link) used to be silently dropped --
  // the gate just re-rendered a bare sign-in form with zero explanation,
  // which is exactly what "keeps bringing me back to the sign-up page"
  // looks like from the outside. Give it a real, actionable message.
  function hashErrorMessage(code) {
    if (code === "otp_expired") {
      return "That sign-in link expired or was already used \u2014 enter your email and we'll send a fresh one.";
    }
    return "That sign-in link didn't work \u2014 enter your email and we'll send a fresh one.";
  }

  // ── Funnel beacon (Batch D2, 2026-08-05) ──────────────────────────────
  // First-party instrumentation for the VOW signup funnel -- no third-party
  // tracker belongs on a VOW-gated page (verified before building: this page
  // loaded zero analytics of any kind). Mirrors sendVowLeadBeacon's exact
  // shape (text/plain safelisted Blob -> no CORS preflight; a real fetch
  // fallback when sendBeacon is unavailable) but posts to the funnel-event
  // endpoint, not lead-receive. Derives site_id from the hostname rather
  // than window.TURNER_SITE -- that global is set by turner-network.js,
  // which this page does not load (confirmed before writing this: the
  // sold-listings template loads footer.js, not turner-network.js), so a
  // hostname-based derivation is the reliable one here.
  function siteIdFromHost() {
    var h = window.location.hostname || "";
    if (h.indexOf("avalonrealestate") !== -1) return "avalonrealestate";
    if (h.indexOf("goosebayrealestate") !== -1) return "goosebayrealestate";
    return "realestategander";
  }

  function fireFunnelEvent(eventName, email) {
    try {
      var payload = {
        event: eventName,
        email: email || "",
        site: siteIdFromHost(),
        path: window.location.pathname
      };
      // Attribution + GA mirror (registration_form_view / registration_submit)
      // live once, in auth.js's window.TurnerFunnel (redesign slice 1).
      if (window.TurnerFunnel) window.TurnerFunnel.extend(payload);
      var body = JSON.stringify(payload);
      var endpoint = "https://realestategander.com/.netlify/functions/vow-funnel-event";
      if (navigator.sendBeacon) {
        navigator.sendBeacon(endpoint, new Blob([body], { type: "text/plain;charset=UTF-8" }));
      } else {
        fetch(endpoint, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: body, keepalive: true, mode: "cors"
        }).catch(function () {});
      }
    } catch (e) { /* a funnel beacon must never break the gate it measures */ }
  }

  function unlock(state) {
    gateEl.style.display = "none";
    pageEl.classList.add("live");
    renderUserStrip(state);
    document.dispatchEvent(new CustomEvent("vow:unlocked", { detail: state }));
  }

  function renderUserStrip(state) {
    if (!userStrip || !state) return;
    var displayName = state.email || "Signed in";
    userStrip.innerHTML =
      '<span>Signed in as ' + escapeHtml(displayName) + '</span>' +
      '<button id="vow-logout" type="button">Sign out</button>';
    var logoutBtn = document.getElementById("vow-logout");
    if (logoutBtn) {
      logoutBtn.addEventListener("click", function () {
        if (window.TurnerAuth && !window.TurnerAuth._stub) {
          window.TurnerAuth.signOut().then(function () {
            try { localStorage.removeItem(LEGACY_KEY); } catch (e) {}
            location.reload();
          });
        } else {
          // Legacy fallback: just clear the localStorage token
          try { localStorage.removeItem(LEGACY_KEY); } catch (e) {}
          location.reload();
        }
      });
    }
  }

  // ── Social sign-on (Phase B1.5, 2026-05-29) ──
  // Cuts signup friction on the VOW sold funnel: one tap → Google → unlocked,
  // no email round-trip. Providers must be enabled in the Supabase dashboard
  // (Authentication → Providers) with their OAuth client ID/secret. We render
  // ONLY configured providers so a button never appears for one that would
  // error. Add { id: "facebook", label: "Continue with Facebook" } here once
  // Facebook Login is set up in Supabase + the Meta app.
  // 2026-08-26 -- Meta Business Verification is "In review" (Ship 7a): the
  // connected business portfolio must clear KYB before the app's `email`
  // permission works at Standard access, so a Facebook sign-in click today
  // dead-ends at Meta's disabled consent screen. Hide the button rather than
  // delete it -- flip this flag true + bump the cache-bust stamp on every
  // vow-gate.js reference once verification clears, no other code change.
  var FB_LOGIN_ENABLED = false;
  var SOCIAL_PROVIDERS = [
    { id: "google", label: "Continue with Google" }
  ];
  if (FB_LOGIN_ENABLED) {
    SOCIAL_PROVIDERS.push({ id: "facebook", label: "Continue with Facebook" });
  }

  function injectSocialStyles() {
    if (document.getElementById("vow-social-styles")) return;
    var st = document.createElement("style");
    st.id = "vow-social-styles";
    st.textContent =
      // 2026-09-16 mobile pass: the page-level .vow-card rule caps at 92vh,
      // which on iOS Safari is taller than the visible viewport once the
      // toolbar is counted -- the submit button sat below the fold. dvh
      // tracks the real visible height; older engines ignore the line.
      ".vow-card{max-height:calc(100dvh - 32px);overflow:auto;-webkit-overflow-scrolling:touch;}" +
      ".vow-social{display:flex;flex-direction:column;gap:10px;margin-bottom:16px;}" +
      ".vow-social-btn{display:flex;align-items:center;justify-content:center;gap:10px;" +
        "width:100%;padding:12px 16px;border:1px solid #dadce0;border-radius:10px;" +
        "background:#fff;color:#1f1f1f;font-size:15px;font-weight:600;cursor:pointer;" +
        "font-family:inherit;line-height:1.2;" +
        "transition:background .15s ease,border-color .15s ease,box-shadow .15s ease;}" +
      ".vow-social-btn:hover{background:#f7f8fa;border-color:#c8ccd1;box-shadow:0 1px 3px rgba(0,0,0,.14);}" +
      ".vow-social-btn:disabled{opacity:.6;cursor:default;box-shadow:none;}" +
      ".vow-social-btn svg{flex:0 0 auto;display:block;}" +
      ".vow-or{display:flex;align-items:center;text-align:center;color:#9aa0a6;" +
        "font-size:13px;letter-spacing:.03em;text-transform:uppercase;margin:2px 0 14px;}" +
      ".vow-or::before,.vow-or::after{content:'';flex:1;height:1px;background:rgba(160,160,160,.4);}" +
      ".vow-or::before{margin-right:12px;}.vow-or::after{margin-left:12px;}";
    document.head.appendChild(st);
  }

  function providerSvg(id) {
    if (id === "google") {
      return '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">' +
        '<path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.17-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.79 2.72v2.26h2.9c1.7-1.57 2.69-3.88 2.69-6.62z"/>' +
        '<path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.81.54-1.84.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.96v2.33A9 9 0 0 0 9 18z"/>' +
        '<path fill="#FBBC05" d="M3.95 10.7a5.4 5.4 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.07l2.99-2.33z"/>' +
        '<path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.45 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l2.99 2.32C4.66 5.16 6.65 3.58 9 3.58z"/>' +
        '</svg>';
    }
    // Facebook mark added 2026-08-05 -- the button previously rendered with no
    // logo at all (providerSvg only ever handled "google").
    if (id === "facebook") {
      return '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">' +
        '<path fill="#1877F2" d="M18 9a9 9 0 1 0-10.4 8.9v-6.3H5.3V9h2.3V7a3.2 3.2 0 0 1 3.4-3.5c1 0 2 .18 2 .18v2.2h-1.13c-1.11 0-1.46.69-1.46 1.4V9h2.48l-.4 2.6h-2.08v6.3A9 9 0 0 0 18 9z"/>' +
        '</svg>';
    }
    return "";
  }

  // Returns the social-buttons HTML block, or "" when auth is the stub
  // (Supabase SDK missing) or no providers configured — so we never render a
  // button that can't function. Email magic-link stays the always-on path.
  function renderSocialBlock() {
    if (!window.TurnerAuth || window.TurnerAuth._stub
        || typeof window.TurnerAuth.signInWithProvider !== "function"
        || !SOCIAL_PROVIDERS.length) {
      return "";
    }
    var btns = "";
    for (var i = 0; i < SOCIAL_PROVIDERS.length; i++) {
      var p = SOCIAL_PROVIDERS[i];
      btns += '<button type="button" class="vow-social-btn" data-provider="'
        + escapeHtml(p.id) + '">' + providerSvg(p.id)
        + '<span>' + escapeHtml(p.label) + '</span></button>';
    }
    return '<div class="vow-social">' + btns + '</div><div class="vow-or">or</div>';
  }

  function wireSocialButtons(showError) {
    var btns = cardEl.querySelectorAll(".vow-social-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function () {
        var self = this;
        var provider = self.getAttribute("data-provider");
        if (showError) showError("");
        self.disabled = true;
        // Mirror the email flow's return-to capture so the post-auth handler
        // in auth.js can navigate back (Convention #74 same-origin guard on read).
        try { localStorage.setItem("lst-return-to", returnHere()); } catch (e) {}
        // Mirror the email flow's lead context too -- without this, every
        // Google/Facebook registration was invisible to the CRM. Email is
        // unknown at click time on this path; auth.js's SIGNED_IN handler fills
        // it in from the authenticated session (currentUser.email fallback).
        try {
          var optInEl = document.getElementById("vow-optin");
          var mktgEl = document.getElementById("vow-mktg");
          localStorage.setItem("tnr-vow-lead-ctx", JSON.stringify({
            email: "",
            consent: !!(optInEl && optInEl.checked),
            marketing: !!(mktgEl && mktgEl.checked),
            mls: "",
            addr: "",
            page: window.location.href,
            ts: Date.now()
          }));
        } catch (e) { /* never block the sign-in */ }
        // signup_start: the social path's equivalent of the email form
        // submit -- email is unknown at click time (auth.js's SIGNED_IN
        // handler fills it from the session once the provider callback
        // returns), so this fires with no email, matching the ctx-write
        // just above which does the same.
        fireFunnelEvent("signup_start");
        window.TurnerAuth.signInWithProvider(provider).then(function (result) {
          if (result && result.error) {
            if (showError) showError(result.error.message || "Could not start sign-in. Please try again.");
            self.disabled = false;
          }
          // Success → browser redirects to the provider; nothing else to do.
        }).catch(function (err) {
          console.warn("VOW gate: signInWithProvider failed:", err);
          if (showError) showError("Could not start sign-in. Please try again.");
          self.disabled = false;
        });
      });
    }
  }

  // ── Sign-in UI rendering ──

  // Installed-app (standalone) detection -- 2026-09-13 client app. An iOS
  // home-screen app has its OWN storage partition; a magic link tapped in
  // Mail signs Safari in, not the app. So in standalone mode every sign-in
  // surface goes CODE-FIRST (the 8-digit code is the same OTP as the link;
  // verifying either consumes it). Inline fallback covers a stale-cached
  // page that never loaded js/app-shell.js (Conv #74).
  function isAppMode() {
    try {
      if (window.TurnerApp && typeof window.TurnerApp.isStandalone === "function") return !!window.TurnerApp.isStandalone();
      if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) return true;
      return navigator.standalone === true;
    } catch (e) { return false; }
  }

  function renderSignIn(initialError) {
    var app = isAppMode();
    var sendLabel = app ? "Email me a code" : "Send sign-in link";
    // gate_view: the visitor is NOT already authenticated and is about to
    // see the actual sign-in form -- the true second funnel step (distinct
    // from page_view, which fires even for an already-signed-in visitor
    // who never sees this UI at all). Session-scoped once-only guard
    // (2026-08-26) -- a bare re-render (the "try a different email
    // address" bounce-back, or a SIGNED_OUT re-render) used to double- and
    // triple-count this event; a NEW email attempt or a genuinely fresh
    // page load still each get their own real session. Deliberately its
    // own key, not auth.js's tnr-auth-counted -- that key gates a
    // DIFFERENT event (the SIGNED_IN sign_up/login dedupe) and reusing it
    // here would silently break that guard.
    try {
      if (!sessionStorage.getItem("tnr-gate-view-counted")) {
        sessionStorage.setItem("tnr-gate-view-counted", "1");
        fireFunnelEvent("gate_view");
      }
    } catch (e) { fireFunnelEvent("gate_view"); }
    // Email prefill (2026-08-26) -- the address is stored on a successful
    // send (see authReady.then below) so a bounce back to this form (e.g.
    // after an expired-link error) doesn't make the visitor retype it.
    var prefillEmail = "";
    try { prefillEmail = localStorage.getItem("tnr-auth-email") || ""; } catch (e) {}
    injectSocialStyles();
    cardEl.innerHTML =
      '<h1>Sign in to see NL sold prices</h1>' +
      '<p class="vow-sub">' +
        'Newfoundland &amp; Labrador is one of the few markets where sold ' +
        'prices stay private. See the same data REALTORS&reg; use to price ' +
        'homes &mdash; sign in once, then browse the full sold archive on ' +
        'any device. Free.' +
      '</p>' +
      renderSocialBlock() +
      '<form id="vow-form" autocomplete="on" novalidate>' +
        '<div>' +
          '<label for="vow-email">Email address</label>' +
          '<input id="vow-email" name="email" type="email" required ' +
            'autocomplete="email" placeholder="you@example.com" value="' +
            escapeHtml(prefillEmail) + '">' +
        '</div>' +
        '<label for="vow-optin" class="vow-optin-label" style="display:flex;gap:9px;align-items:flex-start;margin:4px 0 8px;font-size:13px;line-height:1.45;cursor:pointer;">' +
          '<input type="checkbox" id="vow-optin" name="agent_consent" style="margin-top:3px;flex:0 0 auto;">' +
          '<span>Have a Turner agent reach out about what my home is worth.</span>' +
        '</label>' +
        // W3.6 (2026-08-24): EXPRESS marketing consent, unchecked by default.
        // The base signup grants sold-data access only (no marketing consent);
        // this checkbox is the CASL-clean way a registrant opts into ongoing
        // email — it becomes casl_consent='express_marketing' at intake and is
        // the front door that grows the autosend cohort.
        '<label for="vow-mktg" class="vow-optin-label" style="display:flex;gap:9px;align-items:flex-start;margin:0 0 14px;font-size:13px;line-height:1.45;cursor:pointer;">' +
          '<input type="checkbox" id="vow-mktg" name="marketing_optin" style="margin-top:3px;flex:0 0 auto;">' +
          '<span>Email me local market updates and sold-price news &mdash; unsubscribe anytime.</span>' +
        '</label>' +
        '<button type="submit" class="vow-submit" id="vow-submit">' +
          sendLabel +
        '</button>' +
        '<div class="vow-error" id="vow-error"></div>' +
        '<p class="vow-fineprint">' +
          (app
            ? 'We&rsquo;ll email you an 8-digit code &mdash; enter it here in the app. No password to remember. '
            : 'We&rsquo;ll email you a one-time sign-in link. No password to ' +
              'remember. Works across phone + desktop &mdash; sign in once on ' +
              'each device you want. ') +
          'Sold-listing data provided under the CREA ' +
          'Virtual Office Website (VOW) rules and the NLAR IDX/VOW feed ' +
          'agreement.' +
        '</p>' +
      '</form>';

    var formEl = document.getElementById("vow-form");
    var emailEl = document.getElementById("vow-email");
    var submitBtn = document.getElementById("vow-submit");
    var errorEl = document.getElementById("vow-error");

    function showError(msg) { if (errorEl) errorEl.textContent = msg || ""; }

    if (initialError) showError(initialError);

    wireSocialButtons(showError);

    formEl.addEventListener("submit", function (ev) {
      ev.preventDefault();
      showError("");

      var email = (emailEl.value || "").trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showError("Please enter a valid email address.");
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Sending…";

      // signup_start: a valid email was submitted -- the visitor genuinely
      // began the signup process (as opposed to merely viewing the gate).
      fireFunnelEvent("signup_start", email);

      // Tier 1.9 fix 2026-05-19: capture pre-auth URL so the post-auth
      // SIGNED_IN handler in auth.js can navigate back to it. Convention
      // #74 fail-safe — only same-origin URLs are honored on the read side.
      try {
        localStorage.setItem("lst-return-to", returnHere());
      } catch (e) { /* no-op — localStorage may be disabled */ }

      // Lead context for auth.js to raise once the magic link proves the
      // address. No MLS here -- this gate is page-level, not per-property.
      try {
        var optInEl = document.getElementById("vow-optin");
        var mktgEl = document.getElementById("vow-mktg");
        localStorage.setItem("tnr-vow-lead-ctx", JSON.stringify({
          email: email,
          consent: !!(optInEl && optInEl.checked),
            marketing: !!(mktgEl && mktgEl.checked),
          mls: "",
          addr: "",
          page: window.location.href,
          ts: Date.now()
        }));
      } catch (e) { /* never block the sign-in */ }

      // Installed app: the emailed link can't sign the app in (it opens
      // Safari) -- send Safari to the account page with ?src=applink so it
      // can explain, and keep the app on the code path.
      var authReady = (window.TurnerAuth && window.TurnerAuth.sendMagicLink)
        ? window.TurnerAuth.sendMagicLink(email, emailLinkOpts(app))
        : Promise.resolve({
            data: null,
            error: { message: "Auth not available" }
          });

      authReady.then(function (result) {
        if (result && result.error) {
          showError(result.error.message || (app ? "Could not send the code." : "Could not send sign-in link."));
          submitBtn.disabled = false;
          submitBtn.textContent = sendLabel;
          return;
        }
        try { localStorage.setItem("tnr-auth-email", email); } catch (e) {}
        renderCheckEmail(email);
      }).catch(function (err) {
        console.warn("VOW gate: sendMagicLink failed:", err);
        showError(app ? "Could not send the code. Please try again." : "Could not send sign-in link. Please try again.");
        submitBtn.disabled = false;
        submitBtn.textContent = sendLabel;
      });
    });
  }

  function renderCheckEmail(email) {
    // Fallback OTP-code path (2026-08-25) -- opening the link in a
    // different browser/app/device is the normal iPhone Mail-app
    // pattern; the code is a channel-independent second way in. Hidden
    // when verifyOtpCode is absent -- an older cached auth.js from
    // before this shipped, Convention #74.
    var hasCodeVerify = !!(window.TurnerAuth
      && typeof window.TurnerAuth.verifyOtpCode === "function");
    var app = isAppMode();
    cardEl.innerHTML =
      (app
        ? '<h1>Enter your code</h1>' +
          '<p class="vow-sub">' +
            'We emailed an 8-digit code to <strong>' + escapeHtml(email) + '</strong>. ' +
            '<strong>Enter the code below &mdash; don&rsquo;t tap the link in the email</strong> ' +
            '(the link opens Safari, not this app).' +
          '</p>'
        : '<h1>Check your email</h1>' +
          '<p class="vow-sub">' +
            'We sent a sign-in link to <strong>' + escapeHtml(email) + '</strong>. ' +
            'Click the link to unlock sold prices &mdash; the link works on whichever ' +
            'device you open it on. You can close this tab.' +
          '</p>') +
      (hasCodeVerify ?
        '<div class="vow-code-block" style="margin-top:18px;">' +
          '<p class="vow-sub" style="font-size:13px;color:var(--muted);margin-bottom:8px;">' +
            (app ? 'Enter the 8-digit code from the email:' : 'Or enter the 8-digit code from the email:') +
          '</p>' +
          '<form id="vow-code-form" autocomplete="one-time-code" novalidate style="display:block;">' +
            '<input id="vow-code" name="code" type="text" inputmode="numeric" maxlength="8" ' +
              'autocomplete="one-time-code" placeholder="12345678" aria-label="8-digit code" ' +
              'style="width:100%;box-sizing:border-box;font-size:24px;letter-spacing:0.22em;text-align:center;padding:14px 12px;">' +
            '<button type="submit" class="vow-submit" id="vow-code-submit" style="margin-top:10px;">Verify</button>' +
          '</form>' +
          '<div class="vow-error" id="vow-code-error"></div>' +
        '</div>'
        : '') +
      (app
        ? '<p class="vow-sub" style="margin-top:18px;font-size:13px;color:var(--muted);">' +
            'Tapped the link by mistake? That signed you in to Safari, not the app, and used up the code &mdash; ' +
            '<a href="#" id="vow-resend-btn">send a new code</a> and enter it here.' +
          '</p>'
        : '<p class="vow-sub" style="margin-top:18px;font-size:13px;color:var(--muted);">' +
            'Didn&rsquo;t see it? Check your spam or junk folder first.' +
          '</p>') +
      '<p class="vow-sub" style="margin-top:8px;font-size:13px;color:var(--muted);">' +
        (app ? 'Didn&rsquo;t see it? Check your spam or junk folder, or ' : '<a href="#" id="vow-resend-btn">Send it again</a> &middot; ') +
        '<a href="#" id="vow-try-different">try a different email address</a>.' +
      '</p>';
    if (app) setTimeout(function () { var c = document.getElementById("vow-code"); if (c) c.focus(); }, 80);
    var tryDifferentLink = document.getElementById("vow-try-different");
    if (tryDifferentLink) {
      tryDifferentLink.addEventListener("click", function (ev) {
        ev.preventDefault();
        renderSignIn();
      });
    }
    // Real resend (2026-08-26) -- the old #vow-resend link was id'd
    // "resend" but its handler just dropped back to a blank form
    // (renderSignIn()); this one actually re-sends to the SAME address,
    // with a 45s cooldown so it can't be hammered.
    var resendBtn = document.getElementById("vow-resend-btn");
    var resendCooldownUntil = 0;
    if (resendBtn) {
      resendBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (Date.now() < resendCooldownUntil) return;
        var originalText = resendBtn.textContent;
        resendCooldownUntil = Date.now() + 45000;
        resendBtn.textContent = "Sending\u2026";
        var sendFn = (window.TurnerAuth && window.TurnerAuth.sendMagicLink)
          ? window.TurnerAuth.sendMagicLink(email, emailLinkOpts(app))
          : Promise.resolve({ data: null, error: { message: "Auth not available" } });
        sendFn.then(function (result) {
          if (result && result.error) {
            resendBtn.textContent = originalText;
            resendCooldownUntil = 0;
            return;
          }
          resendBtn.textContent = "Sent \u2713";
          setTimeout(function () {
            resendBtn.textContent = originalText;
          }, 45000);
        }).catch(function () {
          resendBtn.textContent = originalText;
          resendCooldownUntil = 0;
        });
      });
    }
    if (hasCodeVerify) {
      var codeForm = document.getElementById("vow-code-form");
      var codeEl = document.getElementById("vow-code");
      var codeSubmit = document.getElementById("vow-code-submit");
      var codeErrorEl = document.getElementById("vow-code-error");
      codeForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        if (codeErrorEl) codeErrorEl.textContent = "";
        var code = (codeEl.value || "").replace(/\s+/g, "");
        if (!code) {
          if (codeErrorEl) codeErrorEl.textContent = "Enter the code from the email.";
          return;
        }
        codeSubmit.disabled = true;
        codeSubmit.textContent = "Verifying\u2026";
        var codeErrMsg = app
          ? "That code didn't match \u2014 check the newest email or send a new code."
          : "That code didn't match \u2014 check the newest email or request a new link.";
        window.TurnerAuth.verifyOtpCode(email, code).then(function (result) {
          if (result && result.error) {
            if (codeErrorEl) codeErrorEl.textContent = codeErrMsg;
            codeSubmit.disabled = false;
            codeSubmit.textContent = "Verify";
            return;
          }
          // Success -> the onAuthChange SIGNED_IN handler below unlocks
          // the page; nothing else to do here.
        }).catch(function (err) {
          console.warn("VOW gate: verifyOtpCode failed:", err);
          if (codeErrorEl) codeErrorEl.textContent = codeErrMsg;
          codeSubmit.disabled = false;
          codeSubmit.textContent = "Verify";
        });
      });
    }
  }

  // ── Legacy fallback for users registered under old localStorage flow ──
  function loadLegacyState() {
    try {
      var raw = localStorage.getItem(LEGACY_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (parsed && parsed.passed === true) return parsed;
    } catch (e) {}
    return null;
  }

  // ── Initial state resolution ──

  // If TurnerAuth isn't even loaded (script error?), fall back to legacy
  // localStorage cookie. This is the absolute defensive floor.
  if (!window.TurnerAuth) {
    var legacy = loadLegacyState();
    if (legacy) {
      unlock(legacy);
      return;
    }
    console.warn("VOW gate: TurnerAuth not present + no legacy state; the auth.js script tag is missing so sign-in itself won't work, but the page stays browsable -- window.TurnerVowGate.open() is still wired for whenever the visitor taps the locked price.");
    // No auto-open here (2026-09-17, B6) -- see the soft-gate note above.
    return;
  }

  // Wait for TurnerAuth to finish loading the initial session.
  window.TurnerAuth.ready.then(function () {
    var session = window.TurnerAuth.getSession();
    if (session && session.user) {
      // Already signed in → unlock immediately.
      // Mirror legacy state shape so user-strip + downstream listeners
      // get the same `email` field they expect.
      unlock({
        passed: true,
        email: session.user.email,
        source: "supabase"
      });
      return;
    }

    // Not signed in. Check legacy localStorage for grandfathered users.
    var legacy = loadLegacyState();
    if (legacy) {
      // Honor legacy registration to avoid locking out anyone who registered
      // under the old flow. They'll see content but if they sign out + back
      // in, they'll move to the new Supabase-backed session.
      unlock(legacy);
      return;
    }

    // First-time visitor + not signed in (2026-09-17, B6): stop forcing the
    // modal open on a cold arrival -- the page is already browsable (see
    // the soft-gate block above) and the visitor opens the gate themselves
    // by tapping a locked price. EXCEPTION: a hash-carried auth error means
    // they just landed back from an expired/already-used magic-link email
    // -- that's a sign-in attempt already in progress, so surface the
    // explanation right away instead of silently dropping it (this closes
    // the original "keeps bringing me back to the sign-up page" loop for
    // that failure mode, same as before this change).
    if (window.TurnerAuth.hashError) {
      openGate(hashErrorMessage(window.TurnerAuth.hashError));
    }
  });

  // Subscribe to auth state changes — this is what fires when the user
  // clicks the magic link in their email and lands back on the page with
  // the token in URL hash. Supabase processes the hash, sets the session,
  // emits SIGNED_IN, this handler runs, page unlocks.
  window.TurnerAuth.onAuthChange(function (event, session) {
    if (event === "SIGNED_IN" && session && session.user) {
      // Clean the URL hash (token-bearing) so refresh doesn't re-process.
      if (window.location.hash && window.location.hash.indexOf("access_token") !== -1) {
        try {
          history.replaceState(null, "", window.location.pathname + window.location.search);
        } catch (e) {}
      }
      unlock({
        passed: true,
        email: session.user.email,
        source: "supabase"
      });
    } else if (event === "SIGNED_OUT") {
      // 2026-09-17 (B6): signing out reverts to the same soft-gated,
      // browsable-with-locked-price state as a fresh anonymous visit --
      // it does NOT force the full-screen wall back open. The page stays
      // "live"; js/sold-listings.js / js/sold-detail.js re-lock the price
      // affordance themselves the next time they render a row (they check
      // live auth state, not a cached flag). The gate simply closes and
      // waits to be opened again on demand.
      gateEl.style.display = "none";
      if (userStrip) userStrip.innerHTML = "";
    }
  });
})();
