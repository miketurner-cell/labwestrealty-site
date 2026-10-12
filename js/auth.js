/**
 * TurnerAuth — Supabase Auth wrapper for Phase B1 sign-in flow.
 *
 * Built 2026-05-19. Replaces the legacy localStorage-cookie VOW gate
 * (js/vow-gate.js) which was per-device-only — broken on mobile when
 * the user originally registered on desktop, and vice versa.
 *
 * New model:
 *   - User enters email in sign-in modal
 *   - Supabase sends magic link (via Supabase's built-in SMTP for now;
 *     custom SMTP via Postmark configurable in Supabase Auth settings
 *     when Day 8-10 matcher cron lands)
 *   - User clicks magic link on whichever device they want — token lands
 *     in URL hash, Supabase detects it, session set on that device
 *   - Cross-device works: sign in on phone, then sign in on desktop with
 *     the same email — both devices get their own session, both unlock
 *
 * Exposes `window.TurnerAuth` with stable surface:
 *   - ready          : Promise<void>          — resolves when client + session loaded
 *   - getSession()   : Session | null         — current auth session
 *   - getUser()      : User | null            — current user
 *   - sendMagicLink(email, options) : Promise<{ data, error }>
 *   - verifyOtpCode(email, code) : Promise<{ data, error }>
 *   - signInWithPassword(email, password) : Promise<{ data, error }>
 *   - updatePassword(newPassword) : Promise<{ data, error }> (requires an active session)
 *   - signOut()      : Promise<void>
 *   - onAuthChange(cb) : unsubscribe()        — subscribe to sign-in/sign-out events
 *
 * Dependencies:
 *   - Supabase JS SDK loaded BEFORE this file via CDN:
 *       <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>
 *
 * Convention compliance:
 *   - #14 — script tracked + asset references match
 *   - #15 — site-specific (anon key is the Gander site's publishable key
 *           which is shared across all 3 listings-feed sites per the
 *           Phase B1 shared-Supabase-project decision A2)
 *   - #19 — no existing pipeline change; net-new file
 *   - #74 — fail-safe: missing Supabase SDK → console warn, expose stub
 *           that returns null session so vow-gate.js falls back to legacy
 *           email-form flow gracefully
 *   - #75 — Two-path init pattern: dispatch ready event + expose Promise
 */

(function () {
  "use strict";

  /* RETURN-PATH:BEGIN (D-1009-69 item 7, sites 2026-10-09)
   * Where a visitor goes after signing in or registering. Every caller that
   * stores `lst-return-to`, passes `emailRedirectTo`, or reads a `?next=`
   * parameter goes through these functions, so the rule lives in one
   * place: a return target is a path on THIS site, never another origin.
   *
   *   safeReturnPath(raw)  -> "/path?query#hash" on this origin, or null.
   *     Rejects other origins ("https://evil.example/", "//evil.example"),
   *     non-http(s) schemes ("javascript:", "data:"), backslashes and
   *     control characters (browsers fold "/\evil.example" into a
   *     protocol-relative URL), credentials in the URL, and anything over
   *     2048 characters.
   *   returnTarget()       -> the absolute URL to come back to: a valid
   *     `?next=` on the current page (set by a card's "Sign in" link that
   *     sends the visitor to the sold archive or the account page), else
   *     the current page itself.
   *   afterSignInTarget(stored, loc) -> where SIGNED_IN navigates (below).
   * tools/tests/return-path-test.mjs evaluates this block as-is.
   */
  function safeReturnPath(raw, origin) {
    if (typeof raw !== "string") return null;
    var s = raw.trim();
    if (!s || s.length > 2048) return null;
    if (/[\u0000-\u001f\u007f\\]/.test(s)) return null;
    origin = origin || window.location.origin;
    var u;
    try { u = new URL(s, origin + "/"); } catch (e) { return null; }
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    if (u.origin !== origin) return null;
    if (u.username || u.password) return null;
    return u.pathname + u.search + u.hash;
  }
  function returnTarget() {
    try {
      var next = new URLSearchParams(window.location.search).get("next");
      var p = next ? safeReturnPath(next) : null;
      if (p) return window.location.origin + p;
    } catch (e) { /* fall through to this page */ }
    return window.location.href;
  }
  // After SIGNED_IN: the absolute URL to go to, or null to stay. `stored` is
  // what the sign-in start left in localStorage["lst-return-to"] (a card's
  // property, or the gate's page); a bad or missing one falls back to a
  // `?next=` on the current page (the emailed link opened on another device,
  // which has nothing stored). Never another origin; never the same page.
  function afterSignInTarget(stored, loc) {
    loc = loc || window.location;
    var path = stored ? safeReturnPath(stored, loc.origin) : null;
    if (!path) {
      try {
        var next = new URLSearchParams(loc.search || "").get("next");
        path = next ? safeReturnPath(next, loc.origin) : null;
      } catch (e) { path = null; }
    }
    if (!path) return null;
    var dest = loc.origin + path;
    return dest === loc.href ? null : dest;
  }
  /* RETURN-PATH:END */

  // ── Email typo guard self-loader (2026-08-26, Ship 2 of the sign-in-v2
  // pass) ──
  // Mirrors js/boldtrail-forms.js:loadEmailTypoGuard() exactly (derive the
  // sibling path from THIS script's own src, so it resolves at any depth).
  // auth.js loads on every auth surface (vow-gate, account.html, /property/)
  // -- most of which never load boldtrail-forms.js -- so this closes the
  // "typo'd email on the sold gate" gap without editing a single page.
  // email-typo-guard.js is self-idempotent (window.__etgInstalled guards
  // install(); the querySelector check here guards against a duplicate
  // <script> tag if boldtrail-forms.js's own loader already appended one).
  (function loadEmailTypoGuard() {
    try {
      if (window.EmailTypoGuard) return;
      var self = document.currentScript;
      if (!self || !self.src) return;                    // can't derive path -- skip silently
      var src = self.src.split("?")[0].replace(/auth\.js$/, "email-typo-guard.js");
      if (src === self.src.split("?")[0]) return;         // unexpected filename -- skip
      if (document.querySelector('script[src^="' + src + '"]')) return;
      var s = document.createElement("script");
      s.src = src + "?v=20260826-signin2";
      s.async = true;
      document.head.appendChild(s);
    } catch (e) {
      // Convention #74 -- a guard that fails to load must never break auth.
    }
  })();

  // ── Funnel attribution: window.TurnerFunnel (redesign slice 1, 2026-10-05) ──
  // Why: 7 Sep-4 Oct, GA showed 8 sign_up users against 33 registrations in
  // vow_funnel_events, and nothing recorded where a registrant came from or
  // what they did next. Every vow-funnel-event sender (this file, vow-gate.js,
  // home-sold.js, sold-alerts-optin.js) passes its payload through
  // TurnerFunnel.extend(payload), which adds:
  //   client_id   random id kept in localStorage, so a signup_start and its
  //               signup_complete join without an email (same browser only;
  //               "" when storage is blocked, never a per-page throwaway id).
  //   landing_path, referrer_host, utm_source/medium/campaign
  //               from the first page this browser tab loaded auth.js on. If
  //               that page was reached from another page on this site (most
  //               guide pages don't load auth.js), the referring path is the
  //               landing path and referrer_host is "(internal)". GA4 keeps
  //               its own native landing page and source either way.
  //   reg_path    where the sign-in form was submitted. signup_start saves the
  //               context (tnr-reg-ctx, 24 h) so the completion beacon -- which
  //               usually fires on another page, often a new tab opened from
  //               the email -- carries the context of the START, not the tab.
  // extend() also mirrors two steps to GA4: gate_view -> registration_form_view
  // and signup_start -> registration_submit; sign_up / login fire below.
  // Paths without query or hash, and hosts only: no email or typed text,
  // because the same values go to GA. Installed BEFORE the SDK check, so it
  // also works when auth.js falls back to its stub.
  (function installFunnelContext() {
    if (window.TurnerFunnel) return;
    function sGet(kind, k) { try { return window[kind].getItem(k); } catch (e) { return null; } }
    function sPut(kind, k, v) { try { window[kind].setItem(k, v); return true; } catch (e) { return false; } }
    function clean(v, n) { return v ? String(v).replace(/[^\w.\-+ ]/g, "").slice(0, n || 80) : ""; }
    function ga(name, params) {
      try { if (typeof window.gtag === "function") window.gtag("event", name, params || {}); } catch (e) {}
    }

    var clientId = sGet("localStorage", "tnr-cid") || "";
    if (!/^[a-z0-9]{16,40}$/.test(clientId)) {
      clientId = "";
      try {
        var a = new Uint8Array(12);
        window.crypto.getRandomValues(a);
        for (var i = 0; i < a.length; i++) clientId += ("0" + a[i].toString(16)).slice(-2);
      } catch (e) {
        clientId = (Date.now().toString(36) + Math.random().toString(36).slice(2) + "0000000000").slice(0, 24);
      }
      if (!sPut("localStorage", "tnr-cid", clientId) || sGet("localStorage", "tnr-cid") !== clientId) clientId = "";
    }

    var attr = null;
    try { attr = JSON.parse(sGet("sessionStorage", "tnr-attr") || "null"); } catch (e) { attr = null; }
    if (!attr || typeof attr !== "object") {
      attr = { landing_path: (window.location.pathname || "/").slice(0, 200), referrer_host: "",
               utm_source: "", utm_medium: "", utm_campaign: "" };
      try {
        var sp = new URLSearchParams(window.location.search || "");
        attr.utm_source = clean(sp.get("utm_source"));
        attr.utm_medium = clean(sp.get("utm_medium"));
        attr.utm_campaign = clean(sp.get("utm_campaign"));
      } catch (e) {}
      try {
        if (document.referrer) {
          var ref = new URL(document.referrer);
          if (ref.host === window.location.host) {
            attr.landing_path = (ref.pathname || "/").slice(0, 200);
            attr.referrer_host = "(internal)";
          } else {
            attr.referrer_host = clean(ref.hostname.replace(/^www\./, ""), 120);
          }
        }
      } catch (e) {}
      sPut("sessionStorage", "tnr-attr", JSON.stringify(attr));
    }

    function regContext() {
      try {
        var c = JSON.parse(sGet("localStorage", "tnr-reg-ctx") || "null");
        if (c && c.at && (Date.now() - c.at) < 24 * 60 * 60 * 1000) return c;
      } catch (e) {}
      return null;
    }

    function extend(payload) {
      try {
        var ev = payload && payload.event;
        var src = attr;
        if (ev === "signup_start") {
          var saved = {};
          for (var k in attr) if (Object.prototype.hasOwnProperty.call(attr, k)) saved[k] = attr[k];
          saved.reg_path = (window.location.pathname || "/").slice(0, 200);
          saved.at = Date.now();
          sPut("localStorage", "tnr-reg-ctx", JSON.stringify(saved));
          src = saved;
          ga("registration_submit", { registration_page: saved.reg_path, landing_page: saved.landing_path });
        } else if (ev === "signup_complete" || ev === "signin_complete") {
          src = regContext() || attr;
        } else if (ev === "gate_view") {
          ga("registration_form_view", { registration_page: (window.location.pathname || "/").slice(0, 200) });
        }
        payload.client_id = clientId;
        payload.landing_path = src.landing_path || "";
        payload.referrer_host = src.referrer_host || "";
        payload.utm_source = src.utm_source || "";
        payload.utm_medium = src.utm_medium || "";
        payload.utm_campaign = src.utm_campaign || "";
        payload.reg_path = src.reg_path || "";
      } catch (e) { /* attribution never breaks a beacon */ }
      return payload;
    }

    // Same-tab follow-on actions after a registration (save_search,
    // favorite_add, alert opt-ins, generate_lead) carry after_registration.
    if (sGet("sessionStorage", "tnr-just-registered") === "1") {
      try { if (typeof window.gtag === "function") window.gtag("set", { after_registration: "yes" }); } catch (e) {}
    }

    window.TurnerFunnel = {
      extend: extend,
      regContext: regContext,
      clientId: function () { return clientId; },
      markRegistered: function () {
        sPut("sessionStorage", "tnr-just-registered", "1");
        try { if (typeof window.gtag === "function") window.gtag("set", { after_registration: "yes" }); } catch (e) {}
      }
    };
  })();

  // ── Configuration ──
  // Publishable key is intentionally PUBLIC per Supabase docs:
  // https://supabase.com/docs/guides/api/api-keys
  // RLS policies protect data; this key only allows operations
  // explicitly permitted by RLS for the anonymous role.
  var SUPABASE_URL = "https://mpzuxamyhzqsrsuelvlq.supabase.co";
  var SUPABASE_ANON_KEY = "sb_publishable_NReIINWVCZnIQpVoq9uu4w_OXoBPlaL";

  // ── Defensive: bail if SDK not loaded ──
  if (typeof window.supabase === "undefined" || !window.supabase.createClient) {
    console.warn("TurnerAuth: Supabase SDK not loaded; auth.js will expose stub.");
    window.TurnerAuth = {
      _stub: true,
      ready: Promise.resolve(),
      safeReturnPath: safeReturnPath,
      returnTarget: returnTarget,
      getSession: function () { return null; },
      soldFetch: function (url, opts) { return fetch(url, opts); },
      getUser: function () { return null; },
      sendMagicLink: function () {
        return Promise.resolve({
          data: null,
          error: { message: "Auth not available (SDK missing)" }
        });
      },
      verifyOtpCode: function () {
        return Promise.resolve({
          data: null,
          error: { message: "Auth not available (SDK missing)" }
        });
      },
      signInWithPassword: function () {
        return Promise.resolve({
          data: null,
          error: { message: "Auth not available (SDK missing)" }
        });
      },
      // Fail-open TRUE (not false): if this reported false, agent-gate.js
      // would treat every account as password-less and show the code path
      // regardless -- exactly right when the SDK itself is down, since the
      // code path is the only thing that could possibly work anyway.
      hasPassword: function () { return Promise.resolve(true); },
      updatePassword: function () {
        return Promise.resolve({
          data: null,
          error: { message: "Auth not available (SDK missing)" }
        });
      },
      signInWithProvider: function () {
        return Promise.resolve({
          data: null,
          error: { message: "Auth not available (SDK missing)" }
        });
      },
      signOut: function () { return Promise.resolve(); },
      onAuthChange: function () { return function () {}; }
    };
    return;
  }

  // ── Initialize Supabase client ──
  var client = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
      persistSession: true,        // store session in localStorage
      autoRefreshToken: true,      // refresh access tokens automatically
      detectSessionInUrl: true,    // capture magic-link tokens from URL hash
      flowType: "pkce"             // PKCE flow (secure for SPAs/browsers)
    }
  });

  // ── Session state ──
  var currentSession = null;
  var currentUser = null;
  var listeners = [];

  // ── Legacy VOW gate shim ──
  // Downstream renderers (js/listing-detail-sold.js, js/agent-sales.js,
  // js/sold-listings.js, future surfaces) follow the Convention #75
  // two-path init pattern keyed on the legacy `vow_gate_v1` localStorage
  // entry + the `vow:unlocked` DOM event. To make Supabase auth state
  // propagate site-wide without modifying every renderer, mirror the
  // Supabase session into the legacy signals here. One source of truth
  // (Supabase) → two compatible surfaces (legacy localStorage + legacy
  // event). When sign-out fires, clear the shim so locked state returns.
  var LEGACY_KEY = "vow_gate_v1";

  function writeLegacyShim(session) {
    if (!session || !session.user) return;
    try {
      localStorage.setItem(LEGACY_KEY, JSON.stringify({
        passed: true,
        email: session.user.email || "",
        source: "supabase"
      }));
    } catch (e) {
      // localStorage unavailable (private browsing, quota) — fine,
      // event-driven path still fires below.
    }
  }

  function clearLegacyShim() {
    try { localStorage.removeItem(LEGACY_KEY); } catch (e) {}
  }

  function dispatchLegacyUnlock(session) {
    if (!session || !session.user) return;
    try {
      document.dispatchEvent(new CustomEvent("vow:unlocked", {
        detail: { passed: true, email: session.user.email || "", source: "supabase" }
      }));
    } catch (e) {
      // CustomEvent constructor unavailable on ancient browsers — skip
      // event path; localStorage shim still unlocks renderers on next load.
    }
  }

  // Initial session resolution. Supabase auto-detects URL-hash tokens
  // during client construction (detectSessionInUrl), so by the time we
  // call getSession() the magic-link callback (if present) has been
  // processed.
  // Cross-context sign-in support (2026-08-25) -- under
  // flowType:"pkce" a magic-link's ?code= can only be exchanged in the
  // SAME browser that requested it (the code-verifier lives in THAT
  // browser's storage) -- opening the link in a different browser, app,
  // or private tab (the normal iPhone Mail-app pattern) silently fails:
  // no error, no session, the gate just re-renders the sign-in form.
  // Fix: emails also carry a #token_hash=...&type=... fragment (the
  // documented Supabase cross-client pattern), which verifyOtp() can
  // redeem with NO stored verifier -- works in any context. flowType
  // stays "pkce" (OAuth/Google/Facebook are same-browser and
  // unaffected); old ConfirmationURL links already in flight keep
  // working same-browser via detectSessionInUrl, untouched below.
  var hashError = null;
  function parseHashParams() {
    var out = {};
    var raw = (window.location.hash || "").replace(/^#/, "");
    if (!raw) return out;
    raw.split("&").forEach(function (pair) {
      var idx = pair.indexOf("=");
      if (idx < 0) return;
      out[decodeURIComponent(pair.slice(0, idx))] =
        decodeURIComponent(pair.slice(idx + 1).replace(/\+/g, " "));
    });
    return out;
  }
  function cleanAuthHash() {
    try {
      history.replaceState(null, "",
        window.location.pathname + window.location.search);
    } catch (e) {
      window.location.hash = "";
    }
  }
  var hashParams = parseHashParams();
  var initialSessionPromise;
  if (hashParams.token_hash) {
    // supabase-js verifyOtp() does NOT reject on an API-level failure --
    // an already-used/expired token_hash resolves NORMALLY with
    // {data:null, error:{...}}. The original .catch()-only handling here
    // never saw that shape, so a re-opened/consumed link silently fell
    // through to a bare sign-in form with zero explanation -- the exact
    // original bug, reproduced live 2026-08-25 by re-navigating to an
    // already-consumed token_hash link. Both the resolved-with-error
    // case AND a genuine network-level rejection now set hashError.
    initialSessionPromise = client.auth.verifyOtp({
      token_hash: hashParams.token_hash,
      type: hashParams.type || "email"
    }).then(function (result) {
      if (result && result.error) {
        console.warn("TurnerAuth: verifyOtp(token_hash) returned an error:", result.error);
        hashError = (result.error && result.error.code) || "otp_expired";
      }
    }).catch(function (err) {
      console.warn("TurnerAuth: verifyOtp(token_hash) threw:", err);
      hashError = hashError || "otp_expired";
    }).then(function () {
      cleanAuthHash();
      return client.auth.getSession();
    });
  } else if (hashParams.error_code || hashParams.error) {
    hashError = hashParams.error_code || hashParams.error;
    cleanAuthHash();
    initialSessionPromise = client.auth.getSession();
  } else {
    initialSessionPromise = client.auth.getSession();
  }

  var readyPromise = initialSessionPromise.then(function (result) {
    currentSession = (result && result.data) ? result.data.session : null;
    currentUser = currentSession ? currentSession.user : null;
    if (currentSession) {
      // Returning visitor — propagate to legacy surfaces immediately so
      // server-rendered locked-state cards swap to unlocked on first paint.
      writeLegacyShim(currentSession);
      dispatchLegacyUnlock(currentSession);
    }
    return currentSession;
  }).catch(function (err) {
    console.warn("TurnerAuth: initial getSession failed:", err);
    return null;
  });

  // ── GA4 event helper — Phase B1 Day 11-14 ────────────────────────
  // Convention #74 fail-safe: typeof check protects against gtag not yet
  // loaded (site-wide gtag.js may race with this script's IIFE). Events
  // never break the auth flow.
  function gaEvent(name, params) {
    try {
      if (typeof window.gtag === "function") {
        window.gtag("event", name, params || {});
      }
    } catch (e) { /* analytics never breaks the page */ }
  }

  // Subscribe to auth-state changes (sign-in, sign-out, token refresh).
  // Internal listener updates module-level state + fans out to public
  // subscribers via onAuthChange().
  client.auth.onAuthStateChange(function (event, session) {
    currentSession = session || null;
    currentUser = currentSession ? currentSession.user : null;
    // Legacy shim mirror: SIGNED_IN / TOKEN_REFRESHED / INITIAL_SESSION
    // all carry a non-null session → propagate; SIGNED_OUT / USER_DELETED
    // clear it. This is what makes "sign in once, everything unlocks
    // site-wide" actually happen without modifying any renderer.
    if (event === "SIGNED_OUT" || event === "USER_DELETED") {
      clearLegacyShim();
      gaEvent("sign_out", { method: "supabase_magic_link" });
    } else if (currentSession) {
      writeLegacyShim(currentSession);
      dispatchLegacyUnlock(currentSession);
      // GA4 sign_up / login events. CRITICAL: Supabase fires SIGNED_IN on
      // EVERY page load that restores a persisted session (and on tab
      // refocus / token recovery), not just on a genuine fresh sign-in.
      // The old `if (event === "SIGNED_IN")` guard re-fired sign_up on
      // every page view — 18 signed-in users produced 3,826 sign_up
      // events (212 each), polluting the GA4 key-event metric (diagnosed
      // 2026-06-17). Two guards now:
      //   (1) sessionStorage dedupe — fire at most once per browser
      //       session, killing the per-page-load re-fire.
      //   (2) created_at recency — count a true `sign_up` (new VOW
      //       registration) only when the account was created in the last
      //       10 min; a returning user fires `login` (non-key) instead.
      // No email or email domain goes to GA (redesign slice 1, 2026-10-05,
      // Mike: "Drop email_domain from GA events"). registration_page and
      // landing_page come from TurnerFunnel (paths only).
      if (event === "SIGNED_IN") {
        try {
          if (!sessionStorage.getItem("tnr-auth-counted")) {
            sessionStorage.setItem("tnr-auth-counted", "1");
            var email = (currentUser && currentUser.email) || "";
            var createdMs = (currentUser && currentUser.created_at)
              ? new Date(currentUser.created_at).getTime() : 0;
            var isNewUser = createdMs && (Date.now() - createdMs) < 10 * 60 * 1000;
            var regCtx = (window.TurnerFunnel && window.TurnerFunnel.regContext()) || {};
            gaEvent(isNewUser ? "sign_up" : "login", {
              method: "supabase_magic_link",
              registration_page: regCtx.reg_path || window.location.pathname,
              landing_page: regCtx.landing_path || ""
            });
            if (isNewUser && window.TurnerFunnel) window.TurnerFunnel.markRegistered();
            // Batch D2 (2026-08-05) funnel beacon -- fires in the EXACT same
            // isNewUser-gated block as the GA4 sign_up event above, for the
            // same reason: this whole block already carries the dedup guard
            // (sessionStorage) that prevents it firing on every session
            // restore, and isNewUser is what distinguishes a genuine fresh
            // registration from a returning user's SIGNED_IN re-fire. Never
            // gate this on its own separate condition -- reusing the proven
            // guard is what keeps this from repeating the 3,826-event
            // pollution bug this exact block was rewritten to fix.
            if (isNewUser) {
              fireFunnelEvent("signup_complete", email);
            } else {
              // Ship 6 (2026-08-26 sign-in-v2 pass) -- the funnel had a
              // start (signup_start) with NO terminal event for a
              // RETURNING user's successful sign-in, which is exactly why
              // Gander (21%) and Goose Bay (8%) looked far worse than
              // Avalon (62%) in the completion rate -- most of their
              // traffic is re-signing-in, and re-signing-in was invisible.
              // Rides the SAME dedup guard as signup_complete above, for
              // the same reason that block already exists: this whole
              // branch only runs once per real sign-in.
              fireFunnelEvent("signin_complete", email);
            }
          }
        } catch (e) { /* sessionStorage blocked -> skip metric, never break auth */ }
        // Tier 1.9 fix 2026-05-19: post-auth navigation back to the URL
        // the consumer was on pre-sign-in. vow-gate.js writes
        // localStorage["lst-return-to"] before sending the magic link.
        // Convention #74 fail-safe — only same-origin URLs are honored
        // to prevent open-redirect attacks via crafted magic-link emails.
        // ── VOW signup -> lead ──────────────────────────────────
        // Fires HERE, not at form submit: clicking the magic link is what
        // proves the address is theirs. Runs BEFORE the lst-return-to block
        // below because that block NAVIGATES, which would kill an in-flight
        // request -- hence sendBeacon, which is built to survive unload.
        // Whole thing is best-effort: a lead must never break sign-in.
        // Shared beacon sender -- both branches below (the normal ctx-present
        // path and the cross-device fallback) build one of these and fire it.
        // Batch D2 (2026-08-05) funnel beacon helper -- byte-identical logic to
// vow-gate.js's own fireFunnelEvent (Convention #15, deliberately
// duplicated rather than shared: these are two separate IIFEs on the
// same page, and a new shared asset would need its own tracking + a
// 3-site cache-bust for one small helper). Keep the two copies in step.
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
  } catch (e) { /* a funnel beacon must never break sign-in */ }
}
function sendVowLeadBeacon(email, consent, note, page, marketing) {
          var body = JSON.stringify({
            source: "web",
            email: email,
            // Consent rides source_form_id: the '-consent' variant is what
            // pages the office, and the distinction stays queryable later.
            source_form_id: consent ? "vow-signup-consent" : "vow-signup",
            agent_consent: !!consent,
            // W3.6: the express marketing checkbox — lead-receive maps this to
            // casl_consent='express_marketing' (true CASL express consent).
            marketing_optin: !!marketing,
            auth_user_id: (currentUser && currentUser.id) || "",
            note: note,
            lead_source: "VOW registration",
            referer_url: page || "",
            tag: ["VOW", "sold-archive"]
          });
          var endpoint = "https://realestategander.com/.netlify/functions/lead-receive";
          var sent = false;
          if (navigator.sendBeacon) {
            // text/plain is CORS-safelisted so the beacon needs no preflight
            // (beacons cannot preflight -- application/json here would fail
            // silently on every cross-origin send from Avalon/Goosebay).
            // lead-receive parses the body with JSON.parse regardless.
            sent = navigator.sendBeacon(endpoint,
              new Blob([body], { type: "text/plain;charset=UTF-8" }));
          }
          if (!sent) {
            fetch(endpoint, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: body,
              keepalive: true,
              mode: "cors"
            }).catch(function () { /* best effort */ });
          }
        }
        try {
          var vowRaw = localStorage.getItem("tnr-vow-lead-ctx");
          if (vowRaw) {
            // Clear FIRST, unconditionally -- a malformed or stale context
            // must never be retried on every subsequent page load.
            localStorage.removeItem("tnr-vow-lead-ctx");
            var vow = JSON.parse(vowRaw);
            var fresh = vow && vow.ts && (Date.now() - vow.ts) < 24 * 60 * 60 * 1000;
            var addr = (currentUser && currentUser.email) || (vow && vow.email) || "";
            if (fresh && addr) {
              var note = vow.mls
                ? ("Registered to see the sold price of " + (vow.addr || "a property") +
                   " (MLS " + vow.mls + ")")
                : "Registered to browse sold listings";
              sendVowLeadBeacon(addr, vow.consent, note, vow.page || "", vow.marketing);
            }
          } else if (isNewUser && currentUser && currentUser.email) {
            // Cross-device fallback -- the ctx lives in localStorage on whichever
            // device/tab the sign-in form or social button was used, and the magic
            // link routinely opens on a DIFFERENT device (or a private tab, or a
            // localStorage write that failed). Without this, that registration was
            // silently invisible to the CRM. isNewUser (account created <10min ago,
            // computed just above for the GA metric) is what keeps this from firing
            // on every ordinary page load by a long-since-registered returning user.
            // Consent is unknown on this path, so it defaults to quiet/no-consent --
            // never assumed opt-in.
            sendVowLeadBeacon(currentUser.email, false, "Registered to browse sold listings", window.location.href);
          }
        } catch (e) { /* never break auth over a lead */ }

        try {
          // Where to go now: the target stored when the sign-in started
          // (a card's property, or the page the gate was on), else a
          // `?next=` on this page (the emailed link opened on another
          // device, so this device has nothing stored). Both go through
          // safeReturnPath(): this site's paths only (D-1009-69 item 7).
          var stored = null;
          try {
            stored = localStorage.getItem("lst-return-to");
            if (stored) localStorage.removeItem("lst-return-to");
          } catch (e) { /* storage blocked: fall back to ?next= */ }
          var dest = afterSignInTarget(stored);
          if (dest) window.location.href = dest;
        } catch (e) { /* no-op — bad URL or localStorage error */ }
      }
    }
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](event, currentSession); }
      catch (e) { console.warn("TurnerAuth: listener threw:", e); }
    }
  });

  // ── Public API ──

  /**
   * Request a magic link be sent to `email`. Supabase sends via the
   * configured SMTP provider (built-in by default; Postmark when wired
   * in Day 8-10 matcher cron config).
   *
   * Options:
   *   - emailRedirectTo: URL to return user to after click (default: current page)
   *   - createUser: boolean (default true) — auto-create account if email is new
   */
  function sendMagicLink(email, options) {
    options = options || {};
    var otpOptions = {
      // Strip any existing #fragment -- the token_hash email template
      // appends its own hash on top of this URL, and a stray fragment
      // here (e.g. a deep link) would collide with it.
      emailRedirectTo: options.emailRedirectTo ||
        window.location.href.split("#")[0],
      shouldCreateUser: options.createUser !== false
    };
    // Newsletter signup + future opt-in tagging (Conv #15 active drift item
    // 2026-05-20). When caller passes options.data, forward to Supabase OTP
    // call so the user's raw_user_meta_data carries the flag (e.g.,
    // {subscribed_to_alerts: true, signup_source: "newsletter"}). Used by
    // js/newsletter-signup.js to flag newsletter-only Phase B1 users so
    // the daily-alerts matcher can split personalized vs. generic digests.
    if (options.data && typeof options.data === "object") {
      otpOptions.data = options.data;
    }
    return client.auth.signInWithOtp({
      email: String(email || "").trim(),
      options: otpOptions
    });
  }

  /**
   * Verify an OTP code (the "Or enter the code from the email" fallback)
   * against `email`. No PKCE verifier needed -- works in any browser/app
   * context, which is the whole point of offering it. On success Supabase
   * auto-persists the session and onAuthStateChange fires SIGNED_IN
   * exactly like a normal sign-in; callers don't handle the session
   * directly, they react to the SIGNED_IN listener like everywhere else.
   */
  function verifyOtpCode(email, code) {
    return client.auth.verifyOtp({
      email: String(email || "").trim(),
      token: String(code || "").trim(),
      type: "email"
    });
  }

  /**
   * Does `email` already have a password set? Anon-callable, narrow
   * boolean RPC (public._agent_has_password). It returns false for
   * "no such user", "user exists, no password" and "rate limit hit",
   * but `true` DOES confirm that an account with a password exists for
   * that email, so it reveals that much to anyone who asks. That is
   * bounded server-side by two limits (migration
   * 2026-10-05_agent_has_password_ip_limit.sql): 5 checks per 5 minutes
   * per email and 20 per 5 minutes per caller IP; over either limit it
   * answers false. Used by agent-gate.js to decide whether
   * the emailed sign-in code should be the everyday path (no password
   * yet) or a deliberate "forgot password" reset (password already set)
   * -- Mike's 2026-09-05 directive that a code/magic-link should not
   * stay an every-time alternate front door into archived deal docs
   * once a real password exists.
   *
   * Fails OPEN to false on any network/RPC error -- a check that can't
   * complete must never block the one sign-in path that's guaranteed to
   * work (the code), per Convention #74.
   */
  function hasPassword(email) {
    return client.rpc("_agent_has_password", { p_email: String(email || "").trim() })
      .then(function (res) {
        return !!(res && res.data === true);
      })
      .catch(function () { return false; });
  }

  /**
   * Sign in with email + password. Added 2026-08-26 for agents (self-
   * serve after first setting one via updatePassword below) so a
   * session doesn't depend on receiving a fresh email every time.
   * Never rejects on a bad password -- resolves {data:null,error} like
   * every other verb here, so callers use one error-handling shape.
   */
  function signInWithPassword(email, password) {
    return client.auth.signInWithPassword({
      email: String(email || "").trim(),
      password: String(password || "")
    });
  }

  /**
   * Set (or replace) the CURRENT SESSION's password. Requires an active
   * session -- that's the whole security model: an agent proves email
   * ownership via magic link or the 8-digit code first, THEN sets a
   * password, exactly like "forgot password" flows everywhere else.
   * No separate reset-by-email path exists; this IS the reset path.
   */
  function updatePassword(newPassword) {
    return client.auth.updateUser({ password: String(newPassword || "") });
  }

  /**
   * Begin OAuth sign-in with a social provider ("google", "facebook", ...).
   * Supabase redirects the browser to the provider, then back to
   * options.redirectTo (default: current page) after consent. The returning
   * redirect carries the session; detectSessionInUrl + onAuthStateChange
   * unlock the page exactly like the magic-link flow — so downstream
   * renderers (sold-listings.js, sold-detail.js, agent-sales.js) need ZERO
   * changes (Convention #75).
   *
   * The provider must be enabled in the Supabase dashboard (Authentication
   * → Providers) with its OAuth client ID + secret. Until then Supabase
   * returns an error and the email magic-link path stays fully available
   * (the social button surfaces the error inline, never blocks the page).
   */
  function signInWithProvider(provider, options) {
    options = options || {};
    return client.auth.signInWithOAuth({
      provider: String(provider || ""),
      options: {
        redirectTo: options.redirectTo || window.location.href
      }
    });
  }

  /** Returns the current Session object, or null if not signed in. */
  function getSession() { return currentSession; }

  /** Returns the current User object, or null if not signed in. */
  function getUser() { return currentUser; }

  /** Signs the user out (clears local session). Returns Promise. */
  function signOut() {
    return client.auth.signOut().then(function () {
      currentSession = null;
      currentUser = null;
    });
  }

  /**
   * Subscribe to auth-state changes. Callback receives (event, session)
   * where event is one of SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED, etc.
   * Returns an unsubscribe function.
   */
  function onAuthChange(callback) {
    listeners.push(callback);
    return function unsubscribe() {
      var idx = listeners.indexOf(callback);
      if (idx >= 0) listeners.splice(idx, 1);
    };
  }

  // ── Expose ──
  // hashError is a GETTER, not a plain data property: the token_hash
  // error path (above) sets it asynchronously inside a Promise .then(),
  // which resolves AFTER this object literal would otherwise have
  // already captured a stale (null) snapshot of the closure variable.
  // A getter always reads the current value, however it was set.
  // Site review item 3 (2026-09-29): the sold JSON files answer only a signed-in
  // request. Waits for the session, then sends its bearer token. A signed-out
  // caller gets 401 {error:'sign_in_required', rows: []}.
  function soldFetch(url, opts) {
    opts = opts || {};
    return readyPromise.then(function () {
      var s = getSession();
      var h = {};
      var src = opts.headers || {};
      for (var k in src) { if (Object.prototype.hasOwnProperty.call(src, k)) h[k] = src[k]; }
      if (s && s.access_token) h.Authorization = 'Bearer ' + s.access_token;
      var o = {};
      for (var j in opts) { if (Object.prototype.hasOwnProperty.call(opts, j)) o[j] = opts[j]; }
      o.headers = h;
      o.cache = 'no-store';
      return fetch(url, o);
    });
  }

  window.TurnerAuth = {
    _client: client,                  // escape hatch for advanced callers
    ready: readyPromise,
    getSession: getSession,
    getUser: getUser,
    safeReturnPath: safeReturnPath,
    returnTarget: returnTarget,
    soldFetch: soldFetch,
    sendMagicLink: sendMagicLink,
    verifyOtpCode: verifyOtpCode,
    hasPassword: hasPassword,
    signInWithPassword: signInWithPassword,
    updatePassword: updatePassword,
    get hashError() { return hashError; },
    signInWithProvider: signInWithProvider,
    signOut: signOut,
    onAuthChange: onAuthChange
  };

  // Dispatch a DOM event when ready (alternative to ready promise for
  // listeners that prefer event-driven init — mirrors the vow:unlocked
  // pattern in vow-gate.js).
  readyPromise.then(function () {
    document.dispatchEvent(new CustomEvent("turnerauth:ready", {
      detail: { session: currentSession, user: currentUser }
    }));
  });
})();
