/**
 * Phase B1 Day 5-7 — Saved searches controller + auth badge + sign-in modal.
 *
 * Spec: _research/Phase_B1_Auth_Saved_Searches_Alerts_Design_Spec_2026-05-18.md
 * Day 5-7 scope: Save This Search button on /listings/ + /listings/discover/,
 * Supabase-backed persistence, /account/ list/edit/delete/run, top-nav
 * Sign-in entry point. Day 8-10 (matcher cron) builds on this foundation.
 *
 * Exposes:
 *   window.SavedSearch = {
 *     save(name, criteria) -> Promise<{data, error}>
 *     list()               -> Promise<rows>
 *     update(id, patch)    -> Promise<{data, error}>
 *     remove(id)           -> Promise<{data, error}>
 *     openSignIn(opts)     -> opens magic-link modal
 *     toast(msg)           -> floating confirmation
 *   }
 *
 * Architecture:
 *   - Uses window.TurnerAuth.* (Supabase wrapper from js/auth.js).
 *   - Anonymous calls return errors; UI prompts sign-in modal.
 *   - SITE_ID derived from window.TURNER_SITE (matches turner-network.js
 *     site keys: 'gander' | 'goosebay' | 'avalon') → Supabase site_id
 *     value ('realestategander' | 'goosebayrealestate' | 'avalonrealestate').
 *
 * Convention compliance:
 *   - #14 — script is tracked + CSS sibling tracked
 *   - #15 — site-aware via TURNER_SITE constant; Convention #15 propagation
 *           to Avalon + Goosebay = copy-paste once their auth.js is wired
 *   - #19 — purely additive; no existing surface modified
 *   - #74 — fail-safe at every Supabase call (network errors caught and
 *           reported to the UI via toast or modal-error, never crash the page)
 *   - #75 — two-path init: turnerauth:ready event + TurnerAuth.ready promise
 *   - #91 — all selectors prefixed (.tnr-, .acc-ss-, .ldisc-save-search-)
 *           with CSS in css/auth.css (not inline). Class-set audited.
 *   - #106 — auth.js URL stamp updates whenever this script's behavior
 *           changes the legacy-shim contract.
 */
(function () {
  "use strict";

  // ── Site id mapping (TURNER_SITE → Supabase site_id) ──
  var SITE_ID_MAP = {
    "gander":   "realestategander",
    "goosebay": "goosebayrealestate",
    "avalon":   "avalonrealestate"
  };
  var SITE_ID = SITE_ID_MAP[(window.TURNER_SITE || "").toLowerCase()] || "realestategander";

  // ── State ──
  var modalEl = null;
  var toastTimer = null;

  // ─────────────────────────────────────────────────────────────────────
  // Toast helper
  // ─────────────────────────────────────────────────────────────────────
  function toast(msg) {
    // Clear any previous toast first
    var existing = document.querySelector(".tnr-toast");
    if (existing) existing.remove();
    if (toastTimer) clearTimeout(toastTimer);
    var el = document.createElement("div");
    el.className = "tnr-toast";
    el.textContent = msg;
    document.body.appendChild(el);
    toastTimer = setTimeout(function () { if (el.parentNode) el.remove(); }, 4200);
  }

  // 2026-08-19 (W2, portal entry points) -- innerHTML variant so a toast
  // can carry a real link (e.g. "Manage in your account"). NEVER pass
  // unescaped user input here -- any interpolated value (search name,
  // etc.) must go through esc() first, same discipline as every other
  // innerHTML build in this file.
  function toastHtml(html) {
    var existing = document.querySelector(".tnr-toast");
    if (existing) existing.remove();
    if (toastTimer) clearTimeout(toastTimer);
    var el = document.createElement("div");
    el.className = "tnr-toast";
    el.innerHTML = html;
    document.body.appendChild(el);
    toastTimer = setTimeout(function () { if (el.parentNode) el.remove(); }, 4200);
  }

  // ─────────────────────────────────────────────────────────────────────
  // Modal helper (sign-in OR save-search prompt OR delete confirm)
  // ─────────────────────────────────────────────────────────────────────
  function closeModal() {
    if (modalEl && modalEl.parentNode) modalEl.remove();
    modalEl = null;
  }
  // opts.signin marks the SIGN-IN modal specifically (vs. the save-search
  // naming prompt / delete-confirm, which also use this same helper) --
  // Sign-in screen (design canvas "Turner Realty App" · Sign in, 2026-09-13):
  // in the installed app this modal goes full-screen with a brand header,
  // matching the canvas, instead of a small centered card. The brand block
  // is a SIBLING of .tnr-modal (not inside it), so renderCheckEmailModal()/
  // renderPasswordModal() -- which only replace .tnr-modal's innerHTML --
  // never disturb it across the form -> code -> password state changes.
  function openModal(innerHtml, opts) {
    closeModal();
    opts = opts || {};
    modalEl = document.createElement("div");
    modalEl.className = "tnr-modal-backdrop" + (opts.signin ? " tnr-modal--signin" : "");
    var brand = (opts.signin && isAppMode())
      ? '<div class="tnr-modal-signin-brand"><img src="/images/app-icon-192.png" alt="" width="56" height="56"></div>'
      : "";
    modalEl.innerHTML =
      brand +
      '<div class="tnr-modal" role="dialog" aria-modal="true">' +
        '<button class="tnr-modal-close" aria-label="Close">&times;</button>' +
        innerHtml +
      '</div>';
    modalEl.addEventListener("click", function (e) {
      if (e.target === modalEl) closeModal();
    });
    modalEl.querySelector(".tnr-modal-close").addEventListener("click", closeModal);
    document.addEventListener("keydown", function escHandler(e) {
      if (e.key === "Escape") {
        closeModal();
        document.removeEventListener("keydown", escHandler);
      }
    });
    document.body.appendChild(modalEl);
    return modalEl;
  }

  // ─────────────────────────────────────────────────────────────────────
  // Sign-in modal (entry from auth badge + save-search prompt when
  // user is not signed in)
  // ─────────────────────────────────────────────────────────────────────
  //
  // hashErrorMessage() copied verbatim from js/vow-gate.js (Conv #148 --
  // same wording everywhere a hash-carried auth error can surface, never
  // reinvented per-surface).
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

  function hashErrorMessage(code) {
    if (code === "otp_expired") {
      return "That sign-in link expired or was already used \u2014 enter your email and we'll send a fresh one.";
    }
    return "That sign-in link didn't work \u2014 enter your email and we'll send a fresh one.";
  }

  function openSignIn(opts) {
    opts = opts || {};
    var app = isAppMode();
    var headline = opts.headline || "Sign in to your account";
    var reason   = opts.reason   || (app
      ? "We&rsquo;ll email you an 8-digit code. Enter it here to sign in &mdash; no password needed."
      : "We&rsquo;ll email you a one-time sign-in link. No password to remember &mdash; works across phone + desktop.");
    // In the installed app the emailed LINK can't sign the app in (it opens
    // Safari); if the user taps it anyway, land Safari on the account page
    // with ?src=applink so it can explain what happened.
    // Otherwise the link returns here -- or, on a page reached with ?next=
    // (the nav "Sign in" link, D-1009-69 item 7), to that page of this site.
    var redirectTo = opts.redirectTo || (app ? (window.location.origin + "/pages/account.html?src=applink") :
      ((window.TurnerAuth && window.TurnerAuth.returnTarget) ? window.TurnerAuth.returnTarget() : window.location.href));
    var sendLabel = app ? "Email me a code" : "Send sign-in link";

    // 2026-08-26 (Ship 4, sign-in-v2 pass): parity with vow-gate.js -- this
    // modal previously had NONE of the hashError/prefill/resend/code fixes
    // that vow-gate.js got in the PKCE fix + the following pass, so a
    // consumer bouncing here off an expired link saw a bare form with zero
    // explanation. window.TurnerAuth && ... guards an older cached auth.js
    // that predates the hashError getter (Conv #74).
    var hashErr = (window.TurnerAuth && window.TurnerAuth.hashError) || null;
    var prefillEmail = "";
    try { prefillEmail = localStorage.getItem("tnr-auth-email") || ""; } catch (e) {}

    openModal(
      '<h2>' + headline + '</h2>' +
      '<p>' + reason + '</p>' +
      (hashErr
        ? '<p class="tnr-modal-error" style="margin-bottom:12px;">' + esc(hashErrorMessage(hashErr)) + '</p>'
        : '') +
      '<form id="tnr-signin-form" autocomplete="on" novalidate>' +
        '<label for="tnr-signin-email">Email address</label>' +
        '<input id="tnr-signin-email" type="email" required ' +
          'autocomplete="email" placeholder="you@example.com" value="' + esc(prefillEmail) + '">' +
        '<button type="submit" class="tnr-modal-submit" id="tnr-signin-submit">' +
          sendLabel +
        '</button>' +
        '<div class="tnr-modal-error" id="tnr-signin-error"></div>' +
        '<p class="tnr-modal-fineprint" id="tnr-signin-pw-row"' + (app ? '' : ' hidden') + '>' +
          '<a href="#" id="tnr-signin-use-password">Have a password? Sign in with it</a>' +
        '</p>' +
        '<p class="tnr-modal-fineprint">' +
          'Sign-in unlocks the full sold-listing archive, saved searches, ' +
          'and email alerts. Sold data is provided under the CREA Virtual ' +
          'Office Website rules and the NLAR IDX/VOW feed agreement.' +
        '</p>' +
      '</form>',
      { signin: true }
    );

    var form = document.getElementById("tnr-signin-form");
    var emailEl = document.getElementById("tnr-signin-email");
    var submitBtn = document.getElementById("tnr-signin-submit");
    var errEl = document.getElementById("tnr-signin-error");

    setTimeout(function () { emailEl.focus(); }, 50);

    // Password path (secondary). Browser mode: revealed only once the
    // address is known to have a password (Mike 2026-09-05: the code/link
    // stays the everyday consumer path). App mode: always offered, since
    // the link path is unavailable there.
    var pwRow = document.getElementById("tnr-signin-pw-row");
    var pwLink = document.getElementById("tnr-signin-use-password");
    if (!app && pwRow && window.TurnerAuth && typeof window.TurnerAuth.hasPassword === "function") {
      emailEl.addEventListener("blur", function () {
        var e = (emailEl.value || "").trim();
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) return;
        window.TurnerAuth.hasPassword(e).then(function (has) { if (has) pwRow.hidden = false; });
      });
    }
    if (pwLink) {
      pwLink.addEventListener("click", function (ev) {
        ev.preventDefault();
        renderPasswordModal((emailEl.value || "").trim(), redirectTo);
      });
    }

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      errEl.textContent = "";
      var email = (emailEl.value || "").trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        errEl.textContent = "Please enter a valid email address.";
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = "Sending…";
      var p = (window.TurnerAuth && window.TurnerAuth.sendMagicLink)
        ? window.TurnerAuth.sendMagicLink(email, { emailRedirectTo: redirectTo })
        : Promise.resolve({ data: null, error: { message: "Auth not available" } });
      p.then(function (result) {
        if (result && result.error) {
          errEl.textContent = result.error.message || (app ? "Could not send the code." : "Could not send sign-in link.");
          submitBtn.disabled = false;
          submitBtn.textContent = sendLabel;
          return;
        }
        // Same localStorage key vow-gate.js writes -- prefill is shared
        // across every auth surface on the site, not just this modal.
        try { localStorage.setItem("tnr-auth-email", email); } catch (e) {}
        renderCheckEmailModal(email, redirectTo);
      }).catch(function (err) {
        console.warn("SavedSearch.openSignIn: sendMagicLink failed:", err);
        errEl.textContent = app ? "Could not send the code. Please try again." : "Could not send sign-in link. Please try again.";
        submitBtn.disabled = false;
        submitBtn.textContent = sendLabel;
      });
    });
  }

  // Email + password sign-in (2026-09-13). Reached only via the "Have a
  // password?" link; never the default path for consumers.
  function renderPasswordModal(email, redirectTo) {
    if (!modalEl) return;
    modalEl.querySelector(".tnr-modal").innerHTML =
      '<button class="tnr-modal-close" aria-label="Close">&times;</button>' +
      '<h2>Sign in with your password</h2>' +
      '<form id="tnr-pw-form" autocomplete="on" novalidate>' +
        '<label for="tnr-pw-email">Email address</label>' +
        '<input id="tnr-pw-email" type="email" required autocomplete="username" value="' + esc(email || "") + '">' +
        '<label for="tnr-pw-pass" style="margin-top:10px;">Password</label>' +
        '<input id="tnr-pw-pass" type="password" required autocomplete="current-password">' +
        '<button type="submit" class="tnr-modal-submit" id="tnr-pw-submit">Sign in</button>' +
        '<div class="tnr-modal-error" id="tnr-pw-error"></div>' +
        '<p class="tnr-modal-fineprint"><a href="#" id="tnr-pw-back">No password? Email me a code instead</a></p>' +
      '</form>';
    modalEl.querySelector(".tnr-modal-close").addEventListener("click", closeModal);
    var back = document.getElementById("tnr-pw-back");
    if (back) back.addEventListener("click", function (ev) { ev.preventDefault(); openSignIn({ redirectTo: redirectTo }); });
    var f = document.getElementById("tnr-pw-form");
    var eEl = document.getElementById("tnr-pw-email");
    var pEl = document.getElementById("tnr-pw-pass");
    var btn = document.getElementById("tnr-pw-submit");
    var err = document.getElementById("tnr-pw-error");
    setTimeout(function () { (email ? pEl : eEl).focus(); }, 50);
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      err.textContent = "";
      var e = (eEl.value || "").trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) { err.textContent = "Please enter a valid email address."; return; }
      if (!(window.TurnerAuth && typeof window.TurnerAuth.signInWithPassword === "function")) {
        err.textContent = "Password sign-in isn't available right now \u2014 email yourself a code instead.";
        return;
      }
      btn.disabled = true; btn.textContent = "Signing in\u2026";
      window.TurnerAuth.signInWithPassword(e, pEl.value || "").then(function (result) {
        if (result && result.error) {
          err.textContent = "That didn't match \u2014 try again, or email yourself a code instead.";
          btn.disabled = false; btn.textContent = "Sign in";
          return;
        }
        try { localStorage.setItem("tnr-auth-email", e); } catch (e2) {}
        closeModal();
      }).catch(function () {
        err.textContent = "Could not sign in. Please try again.";
        btn.disabled = false; btn.textContent = "Sign in";
      });
    });
  }

  // "Check your email" modal state -- code entry + real resend, mirroring
  // vow-gate.js's renderCheckEmail (2026-08-25/26). Split out of
  // openSignIn's success handler so "try a different email address" can
  // call back into openSignIn() cleanly (same round-trip vow-gate.js uses).
  function renderCheckEmailModal(email, redirectTo) {
    var hasCodeVerify = !!(window.TurnerAuth
      && typeof window.TurnerAuth.verifyOtpCode === "function");
    var app = isAppMode();
    var codeBlock = hasCodeVerify ?
          '<div class="tnr-modal-code-block" style="margin-top:14px;">' +
            '<p style="font-size:13px;color:#666;margin-bottom:8px;">' + (app ? 'Enter the 8-digit code from the email:' : 'Or enter the 8-digit code from the email:') + '</p>' +
            '<form id="tnr-signin-code-form" autocomplete="one-time-code" novalidate style="display:block;">' +
              '<input id="tnr-signin-code" name="code" type="text" inputmode="numeric" maxlength="8" ' +
                'autocomplete="one-time-code" placeholder="12345678" aria-label="8-digit code" style="width:100%;box-sizing:border-box;font-size:24px;letter-spacing:0.22em;text-align:center;padding:14px 12px;">' +
              '<button type="submit" class="tnr-modal-submit" id="tnr-signin-code-submit" style="margin-top:10px;">Verify</button>' +
            '</form>' +
            '<div class="tnr-modal-error" id="tnr-signin-code-error"></div>' +
          '</div>'
          : '';
    var intro = app
      ? '<h2>Enter your code</h2>' +
        '<p>We emailed an 8-digit code to <strong>' + esc(email) + '</strong>. ' +
        '<strong>Enter the code below &mdash; don&rsquo;t tap the link in the email</strong> ' +
        '(the link opens Safari, not this app).</p>'
      : '<h2>Check your email</h2>' +
        '<p>We sent a sign-in link to <strong>' + esc(email) + '</strong>. ' +
        'Click the link to sign in' + (hasCodeVerify ? ', or use the code below.' : '.') +
        ' You can close this window once you\'re signed in.</p>';
    var recovery = app
      ? '<p style="margin-top:14px;font-size:13px;color:#666;">Tapped the link by mistake? That signed you in to Safari, not the app, and used up the code &mdash; ' +
        '<a href="#" id="tnr-signin-resend">send a new code</a> and enter it here.</p>' +
        '<p style="margin-top:6px;font-size:13px;color:#666;">Didn&rsquo;t see it? Check your spam or junk folder, or ' +
        '<a href="#" id="tnr-signin-try-different">try a different email address</a>.</p>'
      : '<p style="margin-top:14px;font-size:13px;color:#666;">Didn&rsquo;t see it? Check your spam or junk folder first.</p>' +
        '<p style="margin-top:6px;font-size:13px;">' +
          '<a href="#" id="tnr-signin-resend">Send it again</a> &middot; ' +
          '<a href="#" id="tnr-signin-try-different">try a different email address</a>.' +
        '</p>';
    modalEl.querySelector(".tnr-modal").innerHTML =
      '<button class="tnr-modal-close" aria-label="Close">&times;</button>' +
      '<div class="tnr-modal-success">' +
        (app ? '' : '<div class="tnr-modal-success-icon">&#10003;</div>') +
        intro +
        codeBlock +
        recovery +
      '</div>';
    if (app) setTimeout(function () { var c = document.getElementById("tnr-signin-code"); if (c) c.focus(); }, 80);
    modalEl.querySelector(".tnr-modal-close").addEventListener("click", closeModal);

    var tryDifferent = document.getElementById("tnr-signin-try-different");
    if (tryDifferent) {
      tryDifferent.addEventListener("click", function (ev) {
        ev.preventDefault();
        openSignIn({ redirectTo: redirectTo });
      });
    }

    var resendBtn = document.getElementById("tnr-signin-resend");
    var resendCooldownUntil = 0;
    if (resendBtn) {
      resendBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (Date.now() < resendCooldownUntil) return;
        var originalText = resendBtn.textContent;
        resendCooldownUntil = Date.now() + 45000;
        resendBtn.textContent = "Sending\u2026";
        var send = (window.TurnerAuth && window.TurnerAuth.sendMagicLink)
          ? window.TurnerAuth.sendMagicLink(email, { emailRedirectTo: redirectTo })
          : Promise.resolve({ data: null, error: { message: "Auth not available" } });
        send.then(function (result) {
          if (result && result.error) {
            resendBtn.textContent = originalText;
            resendCooldownUntil = 0;
            return;
          }
          resendBtn.textContent = "Sent \u2713";
          setTimeout(function () { resendBtn.textContent = originalText; }, 45000);
        }).catch(function () {
          resendBtn.textContent = originalText;
          resendCooldownUntil = 0;
        });
      });
    }

    if (hasCodeVerify) {
      var codeForm = document.getElementById("tnr-signin-code-form");
      var codeEl = document.getElementById("tnr-signin-code");
      var codeSubmit = document.getElementById("tnr-signin-code-submit");
      var codeErrEl = document.getElementById("tnr-signin-code-error");
      codeForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        if (codeErrEl) codeErrEl.textContent = "";
        var code = (codeEl.value || "").replace(/\s+/g, "");
        if (!code) {
          if (codeErrEl) codeErrEl.textContent = "Enter the code from the email.";
          return;
        }
        codeSubmit.disabled = true;
        codeSubmit.textContent = "Verifying\u2026";
        var codeErrMsg = app
          ? "That code didn't match \u2014 check the newest email or send a new code."
          : "That code didn't match \u2014 check the newest email or request a new link.";
        window.TurnerAuth.verifyOtpCode(email, code).then(function (result) {
          if (result && result.error) {
            if (codeErrEl) codeErrEl.textContent = codeErrMsg;
            codeSubmit.disabled = false;
            codeSubmit.textContent = "Verify";
            return;
          }
          // Success -- the site-wide onAuthChange handler (auth.js) fires
          // SIGNED_IN and refreshes whatever surface is listening; the
          // modal's job here is just to get out of the way.
          closeModal();
        }).catch(function (err) {
          console.warn("SavedSearch.openSignIn: verifyOtpCode failed:", err);
          if (codeErrEl) codeErrEl.textContent = codeErrMsg;
          codeSubmit.disabled = false;
          codeSubmit.textContent = "Verify";
        });
      });
    }
  }

  // ─────────────────────────────────────────────────────────────────────
  // Supabase CRUD wrappers (require signed-in TurnerAuth client)
  // ─────────────────────────────────────────────────────────────────────
  function client() {
    return window.TurnerAuth && window.TurnerAuth._client;
  }
  function userId() {
    var u = window.TurnerAuth && window.TurnerAuth.getUser && window.TurnerAuth.getUser();
    return u ? u.id : null;
  }

  // ── GA4 event helper — Phase B1 Day 11-14 ────────────────────────
  // Mirror of the gaEvent() in js/auth.js. Convention #74 fail-safe.
  // Convention #15 cross-file drift candidate: any change to either
  // helper needs to land in both files in the same commit.
  function gaEvent(name, params) {
    try {
      if (typeof window.gtag === "function") {
        window.gtag("event", name, params || {});
      }
    } catch (e) { /* analytics never breaks the page */ }
  }

  function save(name, criteria, cadence, opts) {
    opts = opts || {};
    var c = client();
    var uid = userId();
    if (!c || !uid) {
      return Promise.resolve({ data: null, error: { message: "Sign in required" } });
    }
    var cad = coerceCadence(cadence);
    var row = {
      user_id: uid,
      site_id: SITE_ID,
      name: String(name || "Untitled search").trim().slice(0, 200),
      criteria: criteria || {},
      cadence: cad
    };
    // Alert Setup v2 catch-up choice (2026-06-12): NULL last_alerted_at means
    // the matcher treats EVERYTHING currently matching as new (the catch-up
    // batch, capped to newest 8 by the broad-search rail). "Only new from
    // today" stamps now() so only post-signup listings alert.
    if (opts.catchup === false) {
      row.last_alerted_at = new Date().toISOString();
    }
    return c.from("saved_searches").insert(row).select().single().then(function (r) {
      if (!r.error && r.data) {
        // GA4 save_search event — Phase B1 Day 11-14. Emit which chips
        // / filters were active as event params so Mike can see in GA4
        // which filter dimensions drive saves (waterfront vs price vs
        // beds, etc.). Keeps the funnel signal granular.
        var ch = criteria || {};
        gaEvent("save_search", {
          chip_under_price:    ch.chipUnderPrice ? 1 : 0,
          chip_new_construction: ch.chipNewConstruction ? 1 : 0,
          chip_pre_construction: ch.chipPreConstruction ? 1 : 0,
          chip_just_listed:    ch.chipJustListed ? 1 : 0,
          chip_price_drop:     ch.chipPriceDrop ? 1 : 0,
          chip_virtual_tour:   ch.chipVirtualTour ? 1 : 0,
          chip_waterfront:     ch.chipWaterfront ? 1 : 0,
          chip_ocean_view:     ch.chipOceanView ? 1 : 0,
          chip_cottage:        ch.chipCottage ? 1 : 0,
          chip_open_house:     ch.chipOpenHouse ? 1 : 0,
          has_price_range:     (ch.priceMin || ch.priceMax) ? 1 : 0,
          has_beds_min:        ch.bedsMin ? 1 : 0,
          has_baths_min:       ch.bathsMin ? 1 : 0,
          has_text_query:      ch.textQuery ? 1 : 0,
          has_polygon:         (ch.polygon && ch.polygon.length) ? 1 : 0,
          ptype_count:         (ch.ptypes && ch.ptypes.length) || 0,
          alert_catchup:       (opts.catchup === false) ? 0 : 1
        });
      }
      return { data: r.data, error: r.error };
    }).catch(function (err) {
      return { data: null, error: { message: err.message || "Save failed" } };
    });
  }

  function list() {
    var c = client();
    var uid = userId();
    if (!c || !uid) return Promise.resolve([]);
    return c.from("saved_searches")
      .select("*")
      .eq("site_id", SITE_ID)
      .order("created_at", { ascending: false })
      .then(function (r) { return r.data || []; })
      .catch(function () { return []; });
  }

  function update(id, patch) {
    var c = client();
    var uid = userId();
    if (!c || !uid) return Promise.resolve({ error: { message: "Sign in required" } });
    return c.from("saved_searches").update(patch).eq("id", id).select().single().then(function (r) {
      return { data: r.data, error: r.error };
    }).catch(function (err) {
      return { data: null, error: { message: err.message || "Update failed" } };
    });
  }

  function remove(id) {
    var c = client();
    var uid = userId();
    if (!c || !uid) return Promise.resolve({ error: { message: "Sign in required" } });
    return c.from("saved_searches").delete().eq("id", id).then(function (r) {
      return { data: r.data, error: r.error };
    }).catch(function (err) {
      return { data: null, error: { message: err.message || "Delete failed" } };
    });
  }

  // ─────────────────────────────────────────────────────────────────────
  // Save-this-search prompt (used by /listings/ + /listings/discover/)
  // Alert Management UX 2026-06-10 — Decisions A1 (cadence tiers) +
  // C1 (auto-name + cadence picker) + D1 (update-in-place via
  // opts.updateId, set by listings-index.js when ?edit_search= present).
  // ─────────────────────────────────────────────────────────────────────
  function fmtPriceK(n) {
    if (n >= 1000000) return "$" + (Math.round(n / 100000) / 10) + "M";
    return "$" + Math.round(n / 1000) + "K";
  }

  // Auto-generated search name from the active criteria, e.g.
  // "Gander · 3+ bd · under $300K". Falls back to "All listings".
  function autoName(c) {
    if (!c) return "All listings";
    var parts = [];
    if (c.textQuery) {
      var tq = String(c.textQuery).trim();
      if (tq) parts.push(tq.charAt(0).toUpperCase() + tq.slice(1));
    }
    if (c.ptypes && c.ptypes.length) parts.push(c.ptypes.join("/"));
    if (c.bedsMin)  parts.push(c.bedsMin + "+ bd");
    if (c.bathsMin) parts.push(c.bathsMin + "+ ba");
    var pMax = c.priceMax || c.chipUnderPrice || null;
    if (c.priceMin && pMax)  parts.push(fmtPriceK(c.priceMin) + "–" + fmtPriceK(pMax));
    else if (pMax)           parts.push("under " + fmtPriceK(pMax));
    else if (c.priceMin)     parts.push("over " + fmtPriceK(c.priceMin));
    if (c.chipNewConstruction) parts.push("New construction");
    if (c.chipPreConstruction) parts.push("Pre-construction");
    if (c.chipJustListed)      parts.push("Just listed");
    if (c.chipPriceDrop)       parts.push("Price drop");
    if (c.chipVirtualTour)     parts.push("Virtual tour");
    if (c.chipWaterfront)      parts.push("Waterfront");
    if (c.chipOceanView)       parts.push("Ocean view");
    if (c.chipCottage)         parts.push("Cottage country");
    if (c.chipOpenHouse)       parts.push("Open house");
    if (c.domMax)              parts.push("new (" + c.domMax + "d)");
    if (c.polygon && c.polygon.length) parts.push("Custom area");
    if (!parts.length) return "All listings";
    return parts.join(" · ").substring(0, 80);
  }

  // Alerts v2 I4 (2026-07-24): 'weekly' joined the cadence set (matcher runs a
  // Saturday leg) but no consumer surface offered it, and the old coercion —
  // anything-not-instant/off becomes daily — silently downgraded it. One
  // helper now guards every cadence read so a supported choice cannot be
  // quietly rewritten.
  var CADENCES = ["instant", "daily", "weekly", "off"];
  function coerceCadence(c) {
    return CADENCES.indexOf(c) >= 0 ? c : "daily";
  }

  // Cadence picker — Daily preselected (Decision A1); Instant is the
  // urgency opt-up; Weekly is the low-volume option; Off = save-without-alerts.
  var CADENCE_OPTIONS = [
    { value: "daily",   label: "Daily",   desc: "A morning digest of new matches" },
    { value: "instant", label: "Instant", desc: "The moment it’s listed — best for serious buyers" },
    { value: "weekly",  label: "Weekly",  desc: "One summary on Saturday mornings" },
    { value: "off",     label: "Off",     desc: "Save without alerts" }
  ];
  function cadencePickerHtml(selected) {
    var sel = coerceCadence(selected);
    var html = '<div class="tnr-ss-cadence" role="radiogroup" aria-label="Alert frequency">';
    CADENCE_OPTIONS.forEach(function (opt) {
      html +=
        '<label class="tnr-ss-cadence-opt">' +
          '<input type="radio" name="tnr-ss-cadence" value="' + opt.value + '"' +
            (opt.value === sel ? ' checked' : '') + '>' +
          '<span class="tnr-ss-cadence-copy">' +
            '<strong>' + opt.label + '</strong>' +
            '<small>' + opt.desc + '</small>' +
          '</span>' +
        '</label>';
    });
    return html + '</div>';
  }

  // ── SMS upsell — the moment-of-intent placement (spec 2026-06-11) ──
  // Right after a successful save: if the user has no text alerts yet,
  // pitch the 15-minute text promise inline (no trip to /account/).
  // Opting in stores sms_phone + CASL consent in user_metadata AND flips
  // this search to instant cadence (the 15-min promise requires it).
  var SMS_CONSENT_TEXT = "I agree to receive text-message alerts from Royal LePage Turner Realty " +
    "when new listings match my saved searches. Message and data rates may apply. " +
    "Reply STOP at any time to unsubscribe.";

  function userHasSms() {
    var u = window.TurnerAuth && window.TurnerAuth.getUser && window.TurnerAuth.getUser();
    var m = (u && u.user_metadata) || {};
    return !!(m.sms_phone && m.sms_consent);
  }

  function openSmsUpsell(searchName, searchId, cadence) {
    var supaClient = client();
    if (!supaClient) { toast('Saved \u201c' + searchName + '\u201d.'); return; }
    gaEvent("sms_upsell_shown", { placement: "save-search" });
    openModal(
      '<h2>\u26a1 Add Listing Text Alerts?</h2>' +
      '<p>New listings matching \u201c' + esc(searchName) + '\u201d, texted to you ' +
        '<strong>within 15 minutes</strong> of hitting the market (business hours). ' +
        'No NL competitor offers this \u2014 be the first to know.</p>' +
      '<form id="tnr-sms-form" novalidate>' +
        '<label for="tnr-sms-phone">Cell number</label>' +
        '<input id="tnr-sms-phone" type="tel" autocomplete="tel" placeholder="709-555-1234" maxlength="20">' +
        '<label style="display:flex;gap:8px;align-items:flex-start;margin:10px 0 0;color:#bbb;font-size:0.8rem;cursor:pointer;">' +
          '<input id="tnr-sms-consent" type="checkbox" style="margin-top:3px;">' +
          '<span>' + SMS_CONSENT_TEXT + '</span>' +
        '</label>' +
        '<button type="submit" class="tnr-modal-submit" id="tnr-sms-submit">Turn on text alerts</button>' +
        '<div class="tnr-modal-error" id="tnr-sms-error"></div>' +
        '<p class="tnr-modal-fineprint" style="text-align:center;">' +
          '<a href="#" id="tnr-sms-skip" style="color:#888;">No thanks \u2014 email is fine</a></p>' +
      '</form>'
    );
    var form = document.getElementById("tnr-sms-form");
    var errEl = document.getElementById("tnr-sms-error");
    var btn = document.getElementById("tnr-sms-submit");
    document.getElementById("tnr-sms-skip").addEventListener("click", function (ev) {
      ev.preventDefault(); closeModal(); toast('Saved \u201c' + searchName + '\u201d.');
    });
    form.addEventListener("submit", function (ev) {
      ev.preventDefault(); errEl.textContent = "";
      var e164 = normalizePhone(document.getElementById("tnr-sms-phone").value);
      if (!e164) { errEl.textContent = "Please enter a valid 10-digit phone number."; return; }
      if (!document.getElementById("tnr-sms-consent").checked) {
        errEl.textContent = "Please check the consent box to receive texts."; return;
      }
      btn.disabled = true; btn.textContent = "Turning on\u2026";
      supaClient.auth.updateUser({ data: {
        sms_phone: e164,
        sms_consent: { granted_at: new Date().toISOString(), source: "save-search-upsell", text: SMS_CONSENT_TEXT }
      } }).then(function (r) {
        if (r.error) { errEl.textContent = r.error.message || "Could not save."; btn.disabled = false; btn.textContent = "Turn on Listing Text Alerts"; return; }
        gaEvent("sms_optin", { placement: "save-search" });
        // The 15-min promise rides instant cadence — flip this search if needed.
        var done = function () {
          closeModal();
          toast('\u26a1 Listing Text Alerts ON \u2014 \u201c' + searchName + '\u201d will text you within 15 minutes of new matches.');
        };
        if (searchId && cadence !== "instant") {
          update(searchId, { cadence: "instant" }).then(done, done);
        } else { done(); }
      }).catch(function () {
        errEl.textContent = "Could not save \u2014 please try again.";
        btn.disabled = false; btn.textContent = "Turn on Listing Text Alerts";
      });
    });
  }

  function promptSaveSearch(criteriaProvider, suggestedName, opts) {
    // criteriaProvider: a function returning the current filterState object
    // (called lazily so the snapshot reflects state at click time, not
    // earlier). opts.updateId (Decision D1): PATCH that saved_searches row
    // instead of INSERT — listings-index.js passes it when the page was
    // opened from an account-row "Edit criteria" link (?edit_search={id}).
    opts = opts || {};
    var uid = userId();
    if (!uid) {
      openSignIn(opts.intent === "sms" ? {
        headline: "Step 1 of 2: create your free account",
        reason: "Text alerts need an account first (Canada\u2019s anti-spam law &mdash; you confirm by email, then add your cell). " +
                "Enter your email and we\u2019ll send a sign-in link; the text-alert setup continues right after."
      } : {
        headline: "Sign in to save this search",
        reason: "Save your filters &mdash; get an email when a new listing matches. Works across phone + desktop."
      });
      return;
    }

    var critNow = (typeof criteriaProvider === "function") ? criteriaProvider() : (criteriaProvider || {});

    function openSaveModal(defaultName, defaultCadence, updateId) {
      var isUpdate = !!updateId;
      var smsIntent = opts.intent === "sms" && !isUpdate;
      openModal(
        '<h2>' + (isUpdate ? 'Update this search' : (smsIntent ? '\ud83d\udcf1 Set up Listing Text Alerts' : 'Save this search')) + '</h2>' +
        '<p>' + (isUpdate
          ? 'Your saved search will use the filters currently applied on this page.'
          : (smsIntent
            ? '<strong>Step 1:</strong> save a search \u2014 this is what we watch the market for. ' +
              '<strong>Step 2</strong> (next screen): add your cell number. ' +
              'New matches get texted to you within 15 minutes (business hours).'
            : 'Name your search and pick how fast you want to hear about new matches.')) + '</p>' +
        '<form id="tnr-ss-form" novalidate>' +
          '<label for="tnr-ss-name">Search name</label>' +
          '<input id="tnr-ss-name" type="text" required maxlength="200" ' +
            'value="' + esc(defaultName || "") + '">' +
          '<label class="tnr-ss-cadence-title">' + (smsIntent ? 'Listing Text Alerts \u2014 how fast? (Instant = texts within 15 min)' : 'Listing Email Alerts') + '</label>' +
          cadencePickerHtml(defaultCadence) +
          '<button type="submit" class="tnr-modal-submit" id="tnr-ss-submit">' +
            (isUpdate ? 'Update search' : (smsIntent ? 'Save & continue to text setup \u2192' : 'Save search')) +
          '</button>' +
          '<div class="tnr-modal-error" id="tnr-ss-error"></div>' +
          '<p class="tnr-modal-fineprint">' +
            'Change frequency, pause, or delete anytime from ' +
            '<a href="/pages/account.html">your account</a>.' +
          '</p>' +
        '</form>'
      );

      var form = document.getElementById("tnr-ss-form");
      var nameEl = document.getElementById("tnr-ss-name");
      var submitBtn = document.getElementById("tnr-ss-submit");
      var errEl = document.getElementById("tnr-ss-error");

      setTimeout(function () { nameEl.focus(); nameEl.select(); }, 50);

      function fail(msg) {
        errEl.textContent = msg;
        submitBtn.disabled = false;
        submitBtn.textContent = isUpdate ? "Update search" : (smsIntent ? "Save & continue to text setup \u2192" : "Save search");
      }
      function doInsert(name, crit, cadence) {
        save(name, crit, cadence, { catchup: opts.catchup }).then(function (result) {
          if (result.error) {
            fail(result.error.message || "Could not save search.");
            return;
          }
          var sid = result.data && result.data.id;
          function afterInsert() {
            closeModal();
            if (cadence !== "off" && !userHasSms()) {
              // SMS upsell at the moment of intent (spec 2026-06-11)
              openSmsUpsell(name, sid, cadence);
              return;
            }
            var cadMsg = cadence === "off" ? "alerts off"
                       : cadence === "instant" ? "instant alerts on"
                       : "daily alerts on";
            toastHtml('Saved “' + esc(name) + '” — ' + cadMsg + '. ' +
              '<a href="/pages/account.html">Manage in your account</a>.');
          }
          // "Watch this community" links (Batch W5, 2026-08-19) pass
          // opts.alertTypes so a status=sold/both search also alerts on
          // SOLD activity, not just "new" -- mirrors js/sold-alerts-optin.js's
          // save()-then-update() pattern (that file's own comment: creates a
          // saved_searches row with alert_types:['sold']). Conv #74: an
          // update failure never blocks the save confirmation the user sees.
          if (sid && Array.isArray(opts.alertTypes) && opts.alertTypes.length) {
            update(sid, { alert_types: opts.alertTypes }).then(afterInsert).catch(afterInsert);
          } else {
            afterInsert();
          }
        });
      }

      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        errEl.textContent = "";
        var name = (nameEl.value || "").trim();
        if (!name) { errEl.textContent = "Please enter a name."; return; }
        var cadEl = form.querySelector('input[name="tnr-ss-cadence"]:checked');
        var cadence = cadEl ? cadEl.value : "daily";
        submitBtn.disabled = true;
        submitBtn.textContent = "Saving…";
        var crit = (typeof criteriaProvider === "function") ? criteriaProvider() : (criteriaProvider || {});
        if (isUpdate) {
          update(updateId, { name: name, criteria: crit, cadence: cadence }).then(function (r) {
            if (r.error) {
              // Conv #74 fail-safe: PATCH failed (row deleted, RLS, etc.) —
              // fall back to the normal save flow so the work isn't lost.
              doInsert(name, crit, cadence);
              return;
            }
            closeModal();
            toast('Updated “' + name + '”');
          });
        } else {
          doInsert(name, crit, cadence);
        }
      });
    }

    if (opts.updateId) {
      // Update mode: pull the existing row so name + cadence prefill from
      // what the user saved. Row missing (deleted / wrong account) →
      // fall back to a normal save (Conv #74).
      list().then(function (rows) {
        var row = null;
        for (var i = 0; i < rows.length; i++) {
          if (String(rows[i].id) === String(opts.updateId)) { row = rows[i]; break; }
        }
        if (row) {
          openSaveModal(row.name || autoName(critNow), row.cadence || "daily", row.id);
        } else {
          openSaveModal((suggestedName || "").trim() || autoName(critNow), opts.defaultCadence || "daily", null);
        }
      });
      return;
    }
    openSaveModal((suggestedName || "").trim() || autoName(critNow), opts.defaultCadence || "daily", null);
  }

  // ─────────────────────────────────────────────────────────────────────
  // /account/ page: render saved searches list
  // ─────────────────────────────────────────────────────────────────────
  // ─────────────────────────────────────────────────────────────────────
  // /account/ Text Alerts (SMS) preferences — CASL express opt-in.
  // Stored in Supabase auth user_metadata (sms_phone E.164 + sms_consent
  // {granted_at, source, text}); the daily matcher reads them via the
  // admin users API and sends a Twilio SMS alongside the email digest.
  // Mike directive 2026-06-10; spec 2026-05-23. Conv #74: no client ->
  // card simply doesn't render.
  function normalizePhone(raw) {
    var d = String(raw || "").replace(/\D/g, "");
    if (d.length === 10) return "+1" + d;
    if (d.length === 11 && d.charAt(0) === "1") return "+" + d;
    return null;
  }

  function renderSmsPrefs(containerEl) {
    var supaClient = client();
    var user = window.TurnerAuth && window.TurnerAuth.getUser && window.TurnerAuth.getUser();
    if (!supaClient || !user || !containerEl) return;
    if (document.getElementById("acc-sms-card")) return; // idempotent
    var meta = (user.user_metadata) || {};
    var phone = meta.sms_phone || "";
    var consented = !!meta.sms_consent;
    var CONSENT_TEXT = "I agree to receive text-message alerts from Royal LePage Turner Realty " +
      "when new listings match my saved searches. Message and data rates may apply. " +
      "Reply STOP at any time to unsubscribe.";
    var card = document.createElement("div");
    card.id = "acc-sms-card";
    card.style.cssText = "margin-top:22px;padding:18px;border:1px solid #2a2a2a;border-radius:10px;background:#161616;";
    card.innerHTML =
      '<h3 style="margin:0 0 6px;font-family:Raleway,sans-serif;font-weight:800;color:#fff;">Listing Text Alerts</h3>' +
      '<p style="margin:0 0 12px;color:#999;font-size:0.88rem;">Get a text when new listings match your saved searches (alongside the daily email).</p>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">' +
        '<input id="acc-sms-phone" type="tel" placeholder="709-555-1234" value="' + esc(phone) + '" ' +
          'style="flex:1;min-width:180px;padding:10px 12px;border-radius:6px;border:1px solid #333;background:#0f0f0f;color:#fff;">' +
        '<button id="acc-sms-save" class="acc-ss-action acc-ss-action--primary" style="padding:10px 18px;">Save</button>' +
      '</div>' +
      '<label style="display:flex;gap:8px;align-items:flex-start;margin-top:10px;color:#bbb;font-size:0.82rem;cursor:pointer;">' +
        '<input id="acc-sms-consent" type="checkbox"' + (consented ? " checked" : "") + ' style="margin-top:3px;">' +
        '<span>' + CONSENT_TEXT + '</span>' +
      '</label>' +
      '<p id="acc-sms-status" style="margin:8px 0 0;color:#7a7;font-size:0.82rem;"></p>';
    containerEl.parentNode ? containerEl.parentNode.insertBefore(card, containerEl.nextSibling)
                           : containerEl.appendChild(card);
    var statusEl = card.querySelector("#acc-sms-status");
    card.querySelector("#acc-sms-save").addEventListener("click", function () {
      var rawPhone = card.querySelector("#acc-sms-phone").value;
      var wantConsent = card.querySelector("#acc-sms-consent").checked;
      var e164 = normalizePhone(rawPhone);
      if (wantConsent && !e164) {
        statusEl.style.color = "#d66";
        statusEl.textContent = "Please enter a valid 10-digit phone number.";
        return;
      }
      var data = wantConsent
        ? { sms_phone: e164,
            sms_consent: { granted_at: new Date().toISOString(), source: "account-page", text: CONSENT_TEXT } }
        : { sms_phone: e164 || null, sms_consent: null };
      supaClient.auth.updateUser({ data: data }).then(function (r) {
        if (r.error) {
          statusEl.style.color = "#d66";
          statusEl.textContent = "Save failed: " + (r.error.message || "error");
        } else {
          statusEl.style.color = "#7a7";
          statusEl.textContent = wantConsent
            ? "Text alerts ON — you'll get an SMS when new matches appear."
            : "Listing Text Alerts off.";
        }
      });
    });
  }

  // ─────────────────────────────────────────────────────────────────────
  // Alert Management UX 2026-06-10 — account-row management (Decision E1).
  // Cadence pill (tap cycles Instant→Daily→Off), Pause/Resume, criteria
  // chips, live match-count chip, Edit-criteria link, Subscriptions block.
  // ─────────────────────────────────────────────────────────────────────

  // Pause support flips false if the saved_searches.paused_at column
  // hasn't landed in the DB yet (schema PATCH may trail this JS ship —
  // Conv #74: hide the control gracefully instead of erroring forever).
  var pauseSupported = true;

  // Tap cycle per spec Decision E1: Instant → Daily → Off → Instant.
  function cadenceLabel(cad) {
    return cad === "instant" ? "Instant alerts"
         : cad === "weekly"  ? "Weekly alerts"
         : cad === "off"     ? "Alerts off"
         : "Daily alerts";
  }

  // Alerts v2 I4: an explicit <select> replaces the tap-to-cycle pill. The
  // pill made you guess how many taps reached the option you wanted, and with
  // four cadences that is worse, not better — a cycle also cannot show the
  // choices that exist. A select states them.
  function cadencePillHtml(cadence) {
    var cad = coerceCadence(cadence);
    var html = '<select class="acc-ss-cadence acc-ss-cadence--' + cad + '" data-act="cadence" ' +
               'aria-label="Alert frequency">';
    CADENCE_OPTIONS.forEach(function (o) {
      html += '<option value="' + o.value + '"' + (o.value === cad ? ' selected' : '') + '>' +
              cadenceLabel(o.value) + '</option>';
    });
    return html + '</select>';
  }

  function criteriaEditUrl(c, id) {
    var base = criteriaToUrl(c);
    return base + (base.indexOf("?") >= 0 ? "&" : "?") + "edit_search=" + encodeURIComponent(id);
  }

  // ── Portal P1 (2026-08-18): per-search alert-type + channel controls ──
  // The columns (alert_types text[], channel_email, channel_sms) and the
  // engine's four pools (new/price_drop/back_on_market/sold) have been live
  // since Alerts v2 / Batch A — this is the first CONSUMER control surface
  // for them. Writes ride the existing own-row UPDATE policy.
  var ALERT_TYPE_OPTIONS = [
    { value: "new",            label: "New listings" },
    { value: "price_drop",     label: "Price drops" },
    { value: "back_on_market", label: "Back on market" },
    { value: "sold",           label: "Recently sold" }
  ];
  function alertPrefsHtml(r) {
    var types = Array.isArray(r.alert_types) && r.alert_types.length ? r.alert_types : ["new"];
    var html = '<div class="acc-ss-prefs" style="grid-column:1/-1;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;padding-top:10px;margin-top:10px;border-top:1px solid rgba(255,255,255,0.08);font-size:0.82rem;">';
    html += '<span style="opacity:0.55;">Tell me about:</span>';
    ALERT_TYPE_OPTIONS.forEach(function (o) {
      html += '<label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;">' +
        '<input type="checkbox" data-act="alert-type" value="' + o.value + '"' +
        (types.indexOf(o.value) >= 0 ? ' checked' : '') + '> ' + o.label + '</label>';
    });
    html += '<span style="opacity:0.55;margin-left:auto;">Via:</span>';
    html += '<label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;">' +
      '<input type="checkbox" data-act="channel-email"' + (r.channel_email !== false ? ' checked' : '') + '> Email</label>';
    // SMS: toggling OFF is always allowed (withdrawing consent). Toggling ON
    // is only offered when the row already carries a confirmed phone — CASL
    // consent was captured when that phone was added. A row with no phone
    // routes to the Listing Text Alerts signup flow instead (its own consent
    // capture); a bare checkbox cannot mint consent.
    if (r.phone) {
      html += '<label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;">' +
        '<input type="checkbox" data-act="channel-sms"' + (r.channel_sms ? ' checked' : '') + '> Text</label>';
    } else {
      html += '<button type="button" class="acc-ss-action" data-act="sms-signup" style="font-size:0.78rem;">Add Listing Text Alerts</button>';
    }
    // Listing Push Alerts (client app Ship 3, 2026-09-13): a plain toggle
    // when THIS device is subscribed (js/push-alerts.js); otherwise a
    // button that starts the opt-in (permission ask is the consent). The
    // toggle is per row like Email/Text; the subscription is per device.
    if (pushEnabledOnDevice === true) {
      html += '<label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;">' +
        '<input type="checkbox" data-act="channel-push"' + (r.channel_push ? ' checked' : '') + '> Push</label>';
    } else if (pushEnabledOnDevice === false) {
      html += '<button type="button" class="acc-ss-action" data-act="push-signup" style="font-size:0.78rem;">Add Listing Push Alerts</button>';
    }
    return html + '</div>';
  }
  // null = unknown/unsupported (render nothing), true/false once PushAlerts.status() resolves.
  var pushEnabledOnDevice = null;
  function refreshPushState() {
    if (!(window.PushAlerts && window.PushAlerts.status)) return Promise.resolve(null);
    return window.PushAlerts.status().then(function (st) {
      pushEnabledOnDevice = (!st || st.capability === 'unsupported') ? null : !!st.enabled;
      return pushEnabledOnDevice;
    }).catch(function () { pushEnabledOnDevice = null; return null; });
  }

  // ── Live match-count chip — fetch /listings/data.json once, count
  //    matches per row client-side (approximate but honest: mirrors the
  //    matcher's predicates; skips polygon + a few exotic chips). ──
  var listingsCachePromise = null;
  function fetchListingsOnce() {
    if (!listingsCachePromise) {
      listingsCachePromise = fetch("/listings/data.json", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (Array.isArray(d)) return d;
          return (d && (d.listings || d.rows)) || [];
        })
        .catch(function () { return []; });
    }
    return listingsCachePromise;
  }

  // Alerts v2 I2 tail (2026-07-24): load the canonical matcher from the file
  // that already loads on every page carrying saved searches, rather than
  // editing each page. Same reasoning as js/email-typo-guard.js.
  (function loadCriteriaEngine() {
    if (window.CriteriaMatch) { return; }
    try {
      var me = document.currentScript
        || (function () { var s = document.getElementsByTagName('script');
                          for (var i = s.length - 1; i >= 0; i--) {
                            if ((s[i].src || '').indexOf('saved-search.js') >= 0) { return s[i]; }
                          } return null; })();
      var base = me && me.src ? me.src.replace(/saved-search\.js.*$/, '') : '/js/';
      var tag = document.createElement('script');
      tag.src = base + 'criteria-match.js?v=20260925-tq-token';
      tag.async = false;   // must be in place before the first count runs
      (document.head || document.documentElement).appendChild(tag);
    } catch (e) { /* Conv #74 — fall back to the local matcher below */ }
  })();

  function listingMatchesCriteria(L, c) {
    // Delegate to the ONE engine (js/criteria-match.js) whenever it is
    // present. This local copy silently ignored `cities` — and once alerts
    // started storing the town that way, the count chip on this page read
    // 299 where the alert would send 27. It also still used the retired
    // year_built >= now-5 heuristic for new construction.
    if (window.CriteriaMatch && typeof window.CriteriaMatch.listingMatches === 'function') {
      return window.CriteriaMatch.listingMatches(L, c, Date.now());
    }
    return legacyListingMatchesCriteria(L, c);
  }

  /* >>> tq-match v1 >>>
   * textQuery token matching (2026-09-25). The normalize / canon / tokenize
   * rules and the NL alias table are ported from js/site-search.js, so a
   * saved "st johns" / "sj" / "ST. JOHN`S" alerts on St. John's and a saved
   * "torbay rd" alerts on Torbay Road, the same as the search box that
   * saved it. Deliberately STRICTER than the page: every query token must
   * match a listing token EXACTLY or as a PREFIX (query token >= 3 chars),
   * with NO typo tolerance, so an alert never widens after it is saved.
   * Street queries ("torbay rd") must match as a phrase inside the street
   * name; postal tokens (A1B, A1B 3C0) match only the listing's postal code.
   * This block is byte-identical in js/criteria-match.js and
   * js/saved-search.js (tools/check-criteria-parity.mjs checks that) and
   * mirrored in tools/criteria_match.py (parity-checked on fixtures). */
  function tqNormalize(s) {
    s = String(s == null ? '' : s).toLowerCase();
    if (s.normalize) { s = s.normalize('NFD').replace(/[̀-ͯ]/g, ''); }
    s = s.replace(/['‘’`´]/g, '');
    s = s.replace(/[^a-z0-9]+/g, ' ');
    return s.replace(/^\s+|\s+$/g, '').replace(/\s+/g, ' ');
  }
  var TQ_ALIASES = {
    'saint john s': 'saint johns', 'st john s': 'saint johns', 'st johns': 'saint johns',
    'stjohns': 'saint johns', 'sj': 'saint johns', 'saint johns': 'saint johns',
    'mt pearl': 'mount pearl', 'mtpearl': 'mount pearl', 'mount pearl': 'mount pearl',
    'cbs': 'conception bay south', 'conception bay south': 'conception bay south',
    'cbn': 'conception bay north',
    'pcsp': 'portugal cove saint philips',
    'portugal cove st philips': 'portugal cove saint philips',
    'portugal cove st phillips': 'portugal cove saint philips',
    'portugal cove saint phillips': 'portugal cove saint philips',
    'portugal cove saint philips': 'portugal cove saint philips',
    'lbmcoc': 'logy bay middle cove outer cove',
    'logy bay middle cove outer cove': 'logy bay middle cove outer cove',
    'hvgb': 'happy valley goose bay', 'goose bay': 'happy valley goose bay',
    'happy valley': 'happy valley goose bay', 'happy valley goose bay': 'happy valley goose bay',
    'nwr': 'north west river', 'northwest river': 'north west river',
    'north west river': 'north west river',
    'gfw': 'grand falls windsor', 'grand falls': 'grand falls windsor',
    'grand falls windsor': 'grand falls windsor'
  };
  var TQ_ALIAS_RE = new RegExp('(^| )(' + Object.keys(TQ_ALIASES).sort(function (a, b) {
    return b.length - a.length;
  }).join('|') + ')(?= |$)', 'g');
  var TQ_SUFFIX = {
    rd: 'road', st: 'street', ave: 'avenue', av: 'avenue', dr: 'drive', cres: 'crescent',
    cr: 'crescent', pl: 'place', blvd: 'boulevard', hwy: 'highway', ln: 'lane', ct: 'court',
    pkwy: 'parkway', terr: 'terrace', ter: 'terrace', cir: 'circle', sq: 'square',
    hts: 'heights', ext: 'extension', trl: 'trail', pk: 'park', rte: 'route', crt: 'court'
  };
  var TQ_SUFFIX_WORDS = ['road', 'street', 'avenue', 'drive', 'crescent', 'place', 'boulevard',
    'highway', 'lane', 'court', 'parkway', 'terrace', 'circle', 'square', 'heights', 'extension',
    'trail', 'route', 'way', 'close', 'line', 'hill', 'park'];
  var TQ_DIRECTION = { n: 'north', s: 'south', e: 'east', w: 'west' };
  var TQ_SAINT_NAMES = ['johns', 'john', 'philips', 'phillips', 'marys', 'brides', 'georges',
    'anthony', 'lawrence', 'albans', 'brendans', 'vincents', 'shotts', 'josephs', 'pauls',
    'bernards', 'davids', 'lewis', 'jacques', 'fintans', 'kevins', 'judes', 'thomas',
    'michaels', 'clare', 'lunaire', 'teresa', 'andrews', 'patricks', 'marks', 'catherines'];
  var TQ_FSA_RE = /^[a-z]\d[a-z]$/, TQ_LDU_RE = /^\d[a-z]\d$/, TQ_POSTAL_RE = /^[a-z]\d[a-z]\d[a-z]\d$/;
  var TQ_PROVINCE_RE = /[\s,]+(nl|n\.l\.|nfld|newfoundland(\s+(and|&)\s+labrador)?)\.?\s*$/i;

  function tqCanon(s) {
    s = tqNormalize(s);
    if (!s) { return ''; }
    for (var pass = 0; pass < 2; pass++) {
      s = s.replace(TQ_ALIAS_RE, function (m, lead, key) { return lead + TQ_ALIASES[key]; });
    }
    var toks = s.split(' '), out = [];
    for (var i = 0; i < toks.length; i++) {
      var t = toks[i], next = toks[i + 1], prev = toks[i - 1];
      if (t === 'st' || t === 'ste') {
        if (next && TQ_SAINT_NAMES.indexOf(next) !== -1) { out.push('saint'); continue; }
        if (!next || TQ_DIRECTION.hasOwnProperty(next) || next === 'unit' || next === 'apt' ||
            /^\d/.test(next) || (!!prev && /^[a-z]/.test(prev))) {
          out.push('street'); continue;
        }
        out.push('saint'); continue;
      }
      if (t === 'mt') { out.push('mount'); continue; }
      if (t === 'hbr') { out.push('harbour'); continue; }
      if (i > 0 && TQ_SUFFIX.hasOwnProperty(t)) { out.push(TQ_SUFFIX[t]); continue; }
      if (i > 0 && i === toks.length - 1 && TQ_DIRECTION.hasOwnProperty(t)) { out.push(TQ_DIRECTION[t]); continue; }
      out.push(t);
    }
    return out.join(' ');
  }

  function tqTokenize(s) {
    var toks = tqCanon(s).split(' ').filter(Boolean), out = [];
    for (var i = 0; i < toks.length; i++) {
      if (TQ_FSA_RE.test(toks[i]) && toks[i + 1] && TQ_LDU_RE.test(toks[i + 1])) {
        out.push(toks[i] + toks[i + 1]); i++; continue;
      }
      out.push(toks[i]);
    }
    return out;
  }

  // Exact, or prefix when the query token is at least 3 characters.
  function tqTok(q, t) {
    return q === t || (q.length >= 3 && t.indexOf(q) === 0);
  }

  // True when the saved textQuery `raw` matches listing `L`. Fields are
  // street + city + ptype + psub (the old substring haystack) plus the
  // postal code, used ONLY by postal-shaped tokens.
  function textQueryMatches(L, raw) {
    var q = tqTokenize(raw);
    if (!q.length) { return false; }   // "!!!" matched nothing before; still nothing
    var street = tqTokenize(L.street || '');
    var hay = street
      .concat(tqTokenize(String(L.city || L.city_raw || '').replace(TQ_PROVINCE_RE, '')))
      .concat(tqTokenize(L.ptype || L.property_type || ''))
      .concat(tqTokenize(L.psub || ''));
    var postal = tqNormalize(L.postal_code || L.postal || '').replace(/ /g, '');
    var rest = q, j = -1, i, k;
    for (i = q.length - 1; i >= 1; i--) {
      if (TQ_SUFFIX_WORDS.indexOf(q[i]) !== -1) { j = i; break; }
    }
    if (j >= 1) {
      var phrase = q.slice(0, j + 1), found = false;
      for (var s = 0; !found && s + phrase.length <= street.length; s++) {
        found = true;
        for (k = 0; k < phrase.length; k++) {
          if (!tqTok(phrase[k], street[s + k])) { found = false; break; }
        }
      }
      if (!found) { return false; }
      rest = q.slice(j + 1);
    }
    for (i = 0; i < rest.length; i++) {
      var t = rest[i];
      if (TQ_POSTAL_RE.test(t)) { if (postal !== t) { return false; } continue; }
      if (TQ_FSA_RE.test(t)) { if (postal.slice(0, 3) !== t) { return false; } continue; }
      var hit = false;
      for (k = 0; k < hay.length; k++) { if (tqTok(t, hay[k])) { hit = true; break; } }
      if (!hit) { return false; }
    }
    return true;
  }
  /* <<< tq-match v1 <<< */

  function legacyListingMatchesCriteria(L, c) {
    // Mirrors tools/match-saved-searches.py listing_matches() + the
    // subset of js/listings-index.js applyFilters() that data.json
    // supports. Approximate: polygon / pre-construction / price-drop /
    // virtual-tour chips are skipped (count shown with "~" prefix).
    if (!c) return true;
    var price = (L.price != null) ? L.price : null;
    if (c.priceMin != null && (price === null || price < c.priceMin)) return false;
    if (c.priceMax != null && (price === null || price > c.priceMax)) return false;
    if (c.chipUnderPrice && (price === null || price > c.chipUnderPrice)) return false;
    if (c.bedsMin  != null && (L.beds  == null || L.beds  < c.bedsMin))  return false;
    if (c.bathsMin != null && (L.baths == null || L.baths < c.bathsMin)) return false;
    if (c.ptypes && c.ptypes.length && c.ptypes.indexOf(L.ptype) === -1) return false;
    if (c.domMax != null) {
      var t = Date.parse(L.list_date);
      if (isNaN(t) || (Date.now() - t) / 86400000 > c.domMax) return false;
    }
    // Same token match as js/criteria-match.js (tq-match block above).
    var tq = String(c.textQuery || "").trim();
    if (tq && !textQueryMatches(L, tq)) return false;
    if (c.chipWaterfront && !L.waterfront)  return false;
    if (c.chipOceanView  && !L.ocean_view)  return false;
    if (c.chipCottage    && !L.cottage)     return false;
    if (c.chipOpenHouse  && !L.open_house_next) return false;
    if (c.chipJustListed) {
      var jt = Date.parse(L.list_date);
      if (isNaN(jt) || (Date.now() - jt) > 7 * 86400000) return false;
    }
    if (c.chipNewConstruction) {
      var yb = L.year_built || 0;
      if (!yb || yb < (new Date().getFullYear() - 5)) return false;
    }
    return true;
  }

  function fillMatchCounts(containerEl, rows) {
    fetchListingsOnce().then(function (listings) {
      if (!listings || !listings.length) {
        // Cache unavailable — drop the placeholder chips quietly (Conv #74).
        containerEl.querySelectorAll(".acc-ss-chip--count").forEach(function (el) { el.remove(); });
        return;
      }
      rows.forEach(function (r) {
        var el = containerEl.querySelector('.acc-ss-chip--count[data-count-for="' + r.id + '"]');
        if (!el) return;
        var n = 0;
        try {
          for (var i = 0; i < listings.length; i++) {
            if (listingMatchesCriteria(listings[i], r.criteria || {})) n++;
          }
        } catch (e) { el.remove(); return; }
        el.textContent = "~" + n + " active now";
      });
    });
  }

  // ── Subscriptions block — alert-emails master toggle + SMS card +
  //    unsubscribe-from-all (Decision E1). Master toggle = bulk cadence
  //    PATCH (off → all searches 'off'; on → 'off' searches → 'daily'). ──
  function renderSubscriptions(containerEl, rows) {
    var old = document.getElementById("acc-subs");
    if (old) old.remove();
    var oldSms = document.getElementById("acc-sms-card");
    if (oldSms) oldSms.remove();

    var anyOn = false;
    rows.forEach(function (r) { if ((r.cadence || "daily") !== "off") anyOn = true; });

    var subs = document.createElement("div");
    subs.id = "acc-subs";
    subs.className = "acc-subs";
    subs.innerHTML =
      '<h3 class="acc-subs-title">Subscriptions</h3>' +
      '<div class="acc-subs-row">' +
        '<div class="acc-subs-copy">' +
          '<strong>Alert emails</strong>' +
          '<span>New-listing alerts for your saved searches' +
            (rows.length ? '' : ' (save a search first)') + '</span>' +
        '</div>' +
        '<button type="button" id="acc-subs-email-toggle" class="acc-subs-toggle' +
          (anyOn ? ' is-on' : '') + '" role="switch" aria-checked="' +
          (anyOn ? 'true' : 'false') + '" aria-label="Alert emails"' +
          (rows.length ? '' : ' disabled') + '>' +
          '<span class="acc-subs-knob"></span>' +
        '</button>' +
      '</div>' +
      '<div id="acc-subs-sms-mount"></div>' +
      '<p class="acc-subs-unsub-row">' +
        '<a href="#" id="acc-subs-unsub">Unsubscribe from all listing alerts</a>' +
      '</p>';
    containerEl.appendChild(subs);

    // Fold the existing Text Alerts SMS card into the block.
    renderSmsPrefs(subs.querySelector("#acc-subs-sms-mount"));

    function setAllCadence(cadence, doneMsg) {
      if (!rows.length) return;
      var ops = rows.map(function (r) { return update(r.id, { cadence: cadence }); });
      Promise.all(ops).then(function (results) {
        var failed = 0;
        results.forEach(function (r) { if (r && r.error) failed++; });
        toast(failed ? "Some searches could not be updated (" + failed + ")" : doneMsg);
        renderAccountList(containerEl); // refresh pills + toggle state
      });
    }

    subs.querySelector("#acc-subs-email-toggle").addEventListener("click", function () {
      var on = this.classList.contains("is-on");
      if (on) setAllCadence("off", "Alert emails off for all searches");
      else    setAllCadence("daily", "Daily alert emails on for all searches");
    });
    subs.querySelector("#acc-subs-unsub").addEventListener("click", function (ev) {
      ev.preventDefault();
      if (!rows.length) { toast("No saved searches to unsubscribe."); return; }
      if (!confirm("Turn off alerts for ALL saved searches? Your searches stay saved.")) return;
      setAllCadence("off", "Unsubscribed from all listing alerts");
    });
  }

  function wireAccountActions(containerEl) {
    if (containerEl.dataset.ssWired) return; // delegation wired once
    containerEl.dataset.ssWired = "1";
    // Cadence is a <select>, so it reports through change, not click.
    containerEl.addEventListener("change", function (ev) {
      var sel = ev.target;
      var act = sel && sel.getAttribute && sel.getAttribute("data-act");

      // Portal P1: alert-type checkboxes — collect the card's checked set and
      // write the whole array (server refuses an empty set client-side too:
      // zero types means the search alerts about nothing, which is what the
      // cadence Off state is for — keep the concepts distinct).
      if (act === "alert-type") {
        var typeCard = sel.closest(".acc-ss-card");
        if (!typeCard) return;
        var checked = [];
        typeCard.querySelectorAll('input[data-act="alert-type"]:checked').forEach(function (cb) {
          checked.push(cb.value);
        });
        if (!checked.length) {
          sel.checked = true; // put it back
          toast("Keep at least one alert type — use the frequency Off setting to stop all alerts.");
          return;
        }
        update(typeCard.getAttribute("data-id"), { alert_types: checked }).then(function (r) {
          if (r.error) {
            sel.checked = !sel.checked;
            toast("Could not update alert types: " + (r.error.message || "error"));
            return;
          }
          toast(sel.checked ? "Added: " + sel.value.replace(/_/g, " ") : "Removed: " + sel.value.replace(/_/g, " "));
        });
        return;
      }

      // Portal P1: channel toggles (+ push, Ship 3).
      if (act === "channel-email" || act === "channel-sms" || act === "channel-push") {
        var chCard = sel.closest(".acc-ss-card");
        if (!chCard) return;
        var patch = {};
        patch[act === "channel-email" ? "channel_email" : (act === "channel-sms" ? "channel_sms" : "channel_push")] = sel.checked;
        update(chCard.getAttribute("data-id"), patch).then(function (r) {
          if (r.error) {
            sel.checked = !sel.checked;
            toast("Could not update: " + (r.error.message || "error"));
            return;
          }
          toast(act === "channel-email"
            ? (sel.checked ? "Email alerts on" : "Email alerts off")
            : act === "channel-push"
              ? (sel.checked ? "Listing Push Alerts on for this search" : "Listing Push Alerts off for this search")
              : (sel.checked ? "Text alerts on" : "Text alerts off"));
        });
        return;
      }

      if (act !== "cadence") return;
      var card = sel.closest(".acc-ss-card");
      if (!card) return;
      var id = card.getAttribute("data-id");
      var prev = card.getAttribute("data-cadence") || "daily";
      var next = coerceCadence(sel.value);
      update(id, { cadence: next }).then(function (r) {
        if (r.error) {
          // Put the control back where it was — a select that shows a value
          // the server rejected is a lie about what we will send them.
          sel.value = prev;
          toast("Could not change alerts: " + (r.error.message || "error"));
          return;
        }
        card.setAttribute("data-cadence", next);
        sel.className = "acc-ss-cadence acc-ss-cadence--" + next;
        toast(next === "off"     ? "Alerts off for this search"
            : next === "instant" ? "Instant alerts on — the moment it's listed"
            : next === "weekly"  ? "Weekly alerts on — Saturday mornings"
            : "Daily alerts on");
      });
    });

    containerEl.addEventListener("click", function (ev) {
      var btn = ev.target.closest && ev.target.closest("[data-act]");
      if (!btn) return;
      var card = btn.closest(".acc-ss-card");
      if (!card) return;
      var id = card.getAttribute("data-id");
      var act = btn.getAttribute("data-act");

      if (act === "push-signup") {
        // Start the device opt-in; on success turn push on for THIS row.
        if (!(window.PushAlerts && window.PushAlerts.enable)) return;
        var cap = window.PushAlerts.capability();
        if (cap === 'needs-install') { window.location.href = '/pages/get-the-app.html'; return; }
        btn.disabled = true; btn.textContent = 'Turning on…';
        window.PushAlerts.enable().then(function (r) {
          if (r && r.ok) {
            update(id, { channel_push: true }).then(function () {
              toast('Listing Push Alerts on for this search');
              renderAccountList(containerEl);
            });
          } else {
            btn.disabled = false; btn.textContent = 'Add Listing Push Alerts';
            toast(r && r.reason === 'denied' ? 'Notifications are blocked in your phone settings' : 'Listing Push Alerts not turned on');
          }
        });
        return;
      }

      if (act === "sms-signup") {
        // No phone on this row — route to the Listing Text Alerts flow,
        // which owns the phone-confirm + CASL consent capture.
        if (typeof expressTextAlerts === "function") { expressTextAlerts(); }
        else { window.location.href = "/pages/text-alerts.html"; }
        return;
      }

      if (act === "delete") {
        if (!confirm("Delete this saved search? This can't be undone.")) return;
        remove(id).then(function (r) {
          if (r.error) { toast("Delete failed: " + (r.error.message || "error")); return; }
          card.remove();
          toast("Deleted");
          renderAccountList(containerEl); // refresh list + subscriptions state
        });

      } else if (act === "rename") {
        var nameEl = card.querySelector(".acc-ss-card-name");
        var currentName = nameEl.textContent;
        var newName = prompt("Rename saved search:", currentName);
        if (newName === null) return;
        newName = newName.trim();
        if (!newName || newName === currentName) return;
        update(id, { name: newName }).then(function (r) {
          if (r.error) { toast("Rename failed: " + (r.error.message || "error")); return; }
          nameEl.textContent = newName;
          toast("Renamed");
        });

      } else if (act === "pause") {
        var isPaused = card.classList.contains("acc-ss-card--paused");
        update(id, { paused_at: isPaused ? null : new Date().toISOString() }).then(function (r) {
          if (r.error) {
            var emsg = [r.error.message, r.error.details, r.error.code].join(" ");
            if (/paused_at|column|schema/i.test(emsg)) {
              // DB column not deployed yet — hide pause controls (Conv #74).
              pauseSupported = false;
              document.querySelectorAll('[data-act="pause"]').forEach(function (b) { b.remove(); });
              toast("Pause isn't available yet — set alerts to Off instead.");
            } else {
              toast("Could not update: " + (r.error.message || "error"));
            }
            return;
          }
          card.classList.toggle("acc-ss-card--paused", !isPaused);
          btn.textContent = isPaused ? "Pause" : "Resume";
          toast(isPaused ? "Alerts resumed" : "Paused — no alerts until you resume");
        });
      }
    });
  }

  function renderAccountList(containerEl) {
    if (!containerEl) return;
    // Ship 3: resolve this device's push state once, then render (the
    // per-row Push toggle depends on it). Never blocks on failure.
    if (pushEnabledOnDevice === null && window.PushAlerts && !containerEl.__pushChecked) {
      containerEl.__pushChecked = true;
      refreshPushState().then(function () { renderAccountList(containerEl); });
      return;
    }
    containerEl.innerHTML = '<p class="acc-section-sub">Loading…</p>';
    list().then(function (rows) {
      if (!rows.length) {
        containerEl.innerHTML =
          '<div class="acc-section-empty">' +
            'No saved searches yet. Run a search on ' +
            '<a href="/listings/" style="color:#EA002A;">our listings page</a>, ' +
            'apply some filters, and click <strong>Save this search</strong>.' +
          '</div>';
        renderSubscriptions(containerEl, rows);
        wireAccountActions(containerEl);
        return;
      }
      var html = '<div class="acc-ss-list">';
      rows.forEach(function (r) {
        var paused = !!r.paused_at;
        var cad = coerceCadence(r.cadence);
        html +=
          '<article class="acc-ss-card' + (paused ? ' acc-ss-card--paused' : '') + '" ' +
              'data-id="' + esc(r.id) + '" data-cadence="' + cad + '">' +
            '<div>' +
              '<h3 class="acc-ss-card-name">' + esc(r.name) + '</h3>' +
              '<div class="acc-ss-chips">' + criteriaChipsHtml(r.criteria) +
                '<span class="acc-ss-chip acc-ss-chip--count" data-count-for="' + esc(r.id) + '">&hellip;</span>' +
              '</div>' +
              '<p class="acc-ss-card-meta">' +
                (paused ? 'Paused &middot; ' : '') + 'saved ' + formatDate(r.created_at) +
              '</p>' +
            '</div>' +
            '<div class="acc-ss-card-actions">' +
              cadencePillHtml(cad) +
              '<a class="acc-ss-action acc-ss-action--primary" href="' + esc(criteriaToUrl(r.criteria)) + '">Run</a>' +
              '<a class="acc-ss-action" href="' + esc(criteriaEditUrl(r.criteria, r.id)) + '">Edit criteria</a>' +
              (pauseSupported
                ? '<button class="acc-ss-action" data-act="pause">' + (paused ? 'Resume' : 'Pause') + '</button>'
                : '') +
              '<button class="acc-ss-action" data-act="rename">Rename</button>' +
              '<button class="acc-ss-action acc-ss-action--danger" data-act="delete">Delete</button>' +
            '</div>' +
            alertPrefsHtml(r) +
          '</article>';
      });
      html += '</div>';
      containerEl.innerHTML = html;
      renderSubscriptions(containerEl, rows);
      fillMatchCounts(containerEl, rows);
      wireAccountActions(containerEl);
    });
  }

  // ─────────────────────────────────────────────────────────────────────
  // Criteria utilities
  // ─────────────────────────────────────────────────────────────────────
  // criteriaChips: the parts array behind describeCriteria — also rendered
  // as summary chips on account rows (Alert Management UX 2026-06-10).
  function criteriaChips(c) {
    if (!c) return [];
    var parts = [];
    if (c.textQuery) parts.push('"' + esc(c.textQuery) + '"');
    if (c.priceMin || c.priceMax) {
      var lo = c.priceMin ? "$" + (c.priceMin / 1000) + "k" : "any";
      var hi = c.priceMax ? "$" + (c.priceMax / 1000) + "k" : "any";
      parts.push(lo + "&ndash;" + hi);
    }
    if (c.bedsMin)  parts.push(c.bedsMin + "+ beds");
    if (c.bathsMin) parts.push(c.bathsMin + "+ baths");
    if (c.ptypes && c.ptypes.length) parts.push(c.ptypes.join(", "));
    if (c.domMax)   parts.push("new (" + c.domMax + "d)");
    if (c.chipUnderPrice)        parts.push("Under $300k");
    if (c.chipNewConstruction)   parts.push("New construction");
    if (c.chipPreConstruction)   parts.push("Pre-construction");
    if (c.chipJustListed)        parts.push("Just listed");
    if (c.chipPriceDrop)         parts.push("Price drop");
    if (c.chipVirtualTour)       parts.push("Virtual tour");
    if (c.chipWaterfront)        parts.push("Waterfront");
    if (c.chipOceanView)         parts.push("Ocean view");
    if (c.chipCottage)           parts.push("Cottage country");
    if (c.chipOpenHouse)         parts.push("Open house");
    if (c.polygon && c.polygon.length) parts.push("custom area");
    return parts;
  }

  function describeCriteria(c) {
    var parts = criteriaChips(c);
    return parts.length ? parts.join(" &middot; ") : "All listings";
  }

  function criteriaChipsHtml(c) {
    var parts = criteriaChips(c);
    if (!parts.length) parts = ["All listings"];
    var html = "";
    parts.forEach(function (p) {
      html += '<span class="acc-ss-chip">' + p + '</span>';
    });
    return html;
  }

  function criteriaToUrl(c) {
    // Serialize the full filterState to a URL the /listings/ page can
    // hydrate via listings-index.js readUrlFilters() on init. Each key
    // matches a getURLSearchParam(...) read on the consumer side.
    //
    // Convention: every active filter dimension gets a param. Empty /
    // null / false values are omitted to keep URLs short. Boolean chips
    // emit a "1" sentinel value so the consumer reads truthy → true.
    //
    // NOTE (2026-08-06): `view` (list/split/map) is deliberately NOT
    // serialized here — it's presentation state, not search criteria. A
    // saved search must reproduce WHAT the user was looking for, never
    // HOW they were looking at it. It's hydrated separately in
    // listings-index.js (view-mode initial hydration block, right before
    // this same criteria mirror is read on the consumer side) from its
    // own ?view= param + a dedicated ldisc-view-v1 localStorage key.
    //
    // SAME EXCLUSION, SAME REASON (2026-08-06 Phase 1): `status`
    // (for-sale/sold/both) is a browsing-mode switch, not a search
    // criterion — the design spec is explicit that "Save Search snapshots
    // active criteria only (never pollute the criteria engine with sold
    // semantics)". Hydrated separately from its own ?status= param
    // (read-side only, no localStorage mirror — see the status-hydration
    // block in listings-index.js).
    //
    // THIRD EXCLUSION (2026-08-06 late night, live map-move filtering):
    // `mapBounds` is live viewport state set by panning the map -- it
    // gets NO param here at all, not even its own like `status` does. A
    // saved search or a shared/bookmarked link must never pin someone to
    // wherever the map happened to be scrolled. See the matching note
    // beside filterState.mapBounds in listings-index.js.
    if (!c) return "/listings/";
    var q = [];
    if (c.textQuery)            q.push("q="          + encodeURIComponent(c.textQuery));
    // Structured towns (Alerts v2). Without this the Run button dropped the
    // town entirely and opened /listings/ unfiltered.
    if (c.cities && c.cities.length)
      q.push("cities=" + encodeURIComponent(c.cities.join(",")));
    if (c.priceMin)             q.push("price_min="  + c.priceMin);
    if (c.priceMax)             q.push("price_max="  + c.priceMax);
    if (c.bedsMin)              q.push("beds_min="   + c.bedsMin);
    if (c.bathsMin)             q.push("baths_min="  + c.bathsMin);
    if (c.ptypes && c.ptypes.length) q.push("ptypes=" + encodeURIComponent(c.ptypes.join(",")));
    if (c.domMax !== null && c.domMax !== undefined) q.push("dom_max=" + c.domMax);
    // Chip params: emit "1" sentinel for booleans, raw value for chipUnderPrice.
    if (c.chipUnderPrice)       q.push("chip_under=" + c.chipUnderPrice);
    if (c.chipNewConstruction)  q.push("chip_new=1");
    if (c.chipPreConstruction)  q.push("chip_pre=1");
    if (c.chipJustListed)       q.push("chip_just=1");
    if (c.chipPriceDrop)        q.push("chip_drop=1");
    if (c.chipVirtualTour)      q.push("chip_vt=1");
    if (c.chipWaterfront)       q.push("chip_water=1");
    if (c.chipOceanView)        q.push("chip_ocean=1");
    if (c.chipCottage)          q.push("chip_cottage=1");
    if (c.chipOpenHouse)        q.push("chip_oh=1");
    // Polygon — encode as compact "lat,lng;lat,lng;..." (avoids nested
    // JSON in URL which is brittle to parse). Consumer round-trips.
    if (c.polygon && c.polygon.length) {
      var poly = c.polygon.map(function (pt) { return pt[0] + "," + pt[1]; }).join(";");
      q.push("polygon=" + encodeURIComponent(poly));
    }
    var qs = q.length ? "?" + q.join("&") : "";
    return "/listings/" + qs;
  }

  function formatDate(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso);
      var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      return months[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
    } catch (e) { return ""; }
  }

  // ─────────────────────────────────────────────────────────────────────
  // RETIRED 2026-08-18 (portal P1): renderBadge() (already CSS-disabled
  // since 2026-05-24) and renderNavAuthLink() both removed. The nav
  // Sign in / My Account entry now has exactly ONE owner — the tiny
  // fleet-wide js/nav-auth.js, which loads on EVERY page (this file only
  // ever loaded on /listings/**, which is why the homepage, sold pages
  // and content pages had no auth entry at all). nav-auth.js re-renders
  // on the turner:nav-injected event nav.js dispatches after its
  // innerHTML injection, plus storage/vow:unlocked/auth events.
  // ─────────────────────────────────────────────────────────────────────
  // ─────────────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────────────
  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ─────────────────────────────────────────────────────────────────────
  // Boot: wait for TurnerAuth, render badge, expose API
  // ─────────────────────────────────────────────────────────────────────
  function boot() {
    if (!window.TurnerAuth) {
      // Page didn't load auth.js — degrade gracefully, no badge, no API.
      console.warn("SavedSearch: TurnerAuth not present; skipping init.");
      return;
    }
    // Portal P1 (2026-08-18): the nav auth entry is owned by js/nav-auth.js
    // now — no badge/nav-link rendering here anymore. boot() still exists to
    // keep the TurnerAuth-missing warning + any future lifecycle wiring.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // ─── Public API ────────────────────────────────────────────────────
  // Express path for /text-alerts (Gordie feedback 2026-06-12): the page IS
  // the configurer, so the "name your search" modal is redundant friction.
  // Signed out -> Step-1 sign-in modal. Signed in -> save silently (instant
  // cadence, auto name) and jump STRAIGHT to the phone step.
  function expressTextAlerts(criteriaProvider, suggestedName, opts) {
    opts = opts || {};
    var uid = userId();
    if (!uid) {
      openSignIn({
        headline: "Step 1 of 2: create your free account",
        reason: "Text alerts need an account first (Canada\u2019s anti-spam law \u2014 you confirm by email, then add your cell). " +
                "Enter your email and we\u2019ll send a sign-in link; the text-alert setup continues right after."
      });
      return;
    }
    var crit = (typeof criteriaProvider === "function") ? criteriaProvider() : (criteriaProvider || {});
    var name = (suggestedName || "").trim() || autoName(crit);
    save(name, crit, "instant", { catchup: opts.catchup }).then(function (result) {
      if (result.error) {
        toast("Could not save \u2014 " + (result.error.message || "please try again."));
        return;
      }
      if (!userHasSms()) {
        openSmsUpsell(name, result.data && result.data.id, "instant");
      } else {
        toast('\u26a1 Listing Text Alerts ON \u2014 \u201c' + name + '\u201d will text you within 15 minutes of new matches.');
      }
    });
  }


  window.SavedSearch = {
    save: save,
    list: list,
    update: update,
    remove: remove,
    promptSave: promptSaveSearch,
    expressTextAlerts: expressTextAlerts,
    openSignIn: openSignIn,
    renderAccountList: renderAccountList,
    toast: toast,
    describeCriteria: describeCriteria,
    autoName: autoName,
    criteriaToUrl: criteriaToUrl
  };

})();
