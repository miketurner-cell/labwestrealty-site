/* viewpoint-price.js — VOW-gated sold-price reveal for /property/ pages.
   The sold price lives ONLY in the RLS-gated Supabase `viewpoint_prices`
   table and is fetched client-side AFTER sign-in (TurnerAuth magic link).
   It is NEVER in any public file or the indexed HTML — anonymous reads are
   RLS-blocked (verified []). Reuses window.TurnerAuth (js/auth.js).
   Convention #74: if the SDK / TurnerAuth is absent, the static sign-in CTA
   already in the markup stays untouched. Convention #75: two-path init —
   check getSession() now AND subscribe to onAuthChange for the magic-link
   return. */
(function () {
  var box = document.querySelector('.viewpoint-price-gated');
  if (!box) return;
  if (!window.TurnerAuth || window.TurnerAuth._stub) return;  // keep static CTA
  var mls  = box.getAttribute('data-mls')  || '';
  var addr = box.getAttribute('data-addr') || 'this property';
  if (!mls) return;

  function esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }
  function fmt(n) { var v = Number(n); return isFinite(v) ? '$' + v.toLocaleString('en-CA', { maximumFractionDigits: 0 }) : null; }

  function showPrice(price) {
    var p = fmt(price);
    box.innerHTML =
      '<div class="vp-lock">Sold price</div>' +
      '<div class="vp-price-big">' + (p || 'Price unavailable') + '</div>' +
      '<div class="vp-price-note">NLAR MLS® sold record · shown to registered members</div>';
  }
  function showNoPrice() {
    box.innerHTML =
      '<div class="vp-lock">Sold price</div>' +
      '<p class="vp-gate-p">No sold price is on record for this property.</p>';
  }
  function fetchReveal() {
    var c = window.TurnerAuth._client;
    if (!c) return;
    c.from('viewpoint_prices').select('close_price').eq('mls', mls).maybeSingle()
      .then(function (res) {
        if (res && res.data && res.data.close_price != null) showPrice(res.data.close_price);
        else showNoPrice();
      })
      .catch(function () { /* leave the static CTA in place */ });
  }

  // hashErrorMessage() copied verbatim from js/vow-gate.js (Conv #148 --
  // same wording everywhere a hash-carried auth error can surface).
  function hashErrorMessage(code) {
    if (code === "otp_expired") {
      return "That sign-in link expired or was already used \u2014 enter your email and we'll send a fresh one.";
    }
    return "That sign-in link didn't work \u2014 enter your email and we'll send a fresh one.";
  }

  function showSignIn() {
    // 2026-08-26 (Ship 5, sign-in-v2 pass): parity with vow-gate.js /
    // saved-search.js -- this gate previously had NONE of those fixes, so a
    // consumer bouncing here off an expired link (or just typing a garbage
    // address -- the old validation was `if (!email) return;`, i.e. no
    // validation at all) saw a bare form with zero explanation.
    var hashErr = (window.TurnerAuth && window.TurnerAuth.hashError) || null;
    var prefillEmail = "";
    try { prefillEmail = localStorage.getItem("tnr-auth-email") || ""; } catch (e) {}

    box.innerHTML =
      (hashErr
        ? '<p class="vp-gate-error" style="color:#ff8a8a;font-size:13px;margin:0 0 10px;">' + esc(hashErrorMessage(hashErr)) + '</p>'
        : '') +
      '<div class="vp-lock">🔒 Sold price — members only</div>' +
      '<div class="vp-gate-h">Sign in to see what ' + esc(addr) + ' sold for</div>' +
      '<p class="vp-gate-p">Sold prices in Newfoundland &amp; Labrador aren’t public. ' +
      'Enter your email for a free sign-in link — the same data REALTORS® use.</p>' +
      '<form class="vp-gate-form" novalidate>' +
      '<input type="email" required placeholder="you@email.com" aria-label="Email address" class="vp-gate-input" value="' + esc(prefillEmail) + '">' +
      '<button type="submit" class="vp-gate-cta">Email me the link →</button>' +
      // Optional, never pre-checked (CASL): registering is not consent to be
      // called. Ticking it is what turns a registration into a routed lead.
      // Inline-styled on purpose -- css/viewpoint.css is emitted by the
      // generator and its ?v= is hardcoded in THREE places, so a CSS change
      // costs a 3-site cache-bust for one checkbox.
      '<label class="vp-gate-consent" style="display:flex;gap:8px;align-items:flex-start;margin:10px 0 0;font-size:12px;line-height:1.45;color:#c9c9c9;text-align:left;cursor:pointer;">' +
      '<input type="checkbox" class="vp-gate-optin" style="margin-top:2px;flex:0 0 auto;">' +
      '<span>Have a Turner agent reach out about what my home is worth.</span>' +
      '</label>' +
      '</form>' +
      '<div class="vp-gate-msg" role="status"></div>';
    var form = box.querySelector('.vp-gate-form');
    var msg = box.querySelector('.vp-gate-msg');
    setTimeout(function () {
      var emailEl = box.querySelector('.vp-gate-input');
      if (emailEl) emailEl.focus();
    }, 50);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var email = (box.querySelector('.vp-gate-input').value || '').trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        msg.textContent = 'Please enter a valid email address.';
        return;
      }
      try { localStorage.setItem('lst-return-to', window.location.href); } catch (_) {}
      // Stash what they were looking at so auth.js can raise a lead once the
      // magic link proves the address. localStorage (not session) because the
      // link frequently opens a new tab.
      try {
        var optIn = box.querySelector('.vp-gate-optin');
        localStorage.setItem('tnr-vow-lead-ctx', JSON.stringify({
          email: email,
          consent: !!(optIn && optIn.checked),
          mls: mls || '',
          addr: addr || '',
          page: window.location.href,
          ts: Date.now()
        }));
      } catch (e) { /* never block the sign-in */ }
      msg.textContent = 'Sending…';
      window.TurnerAuth.sendMagicLink(email, { emailRedirectTo: window.location.href })
        .then(function (r) {
          if (r && r.error) {
            msg.textContent = 'Couldn’t send — ' + ((r.error && r.error.message) || 'please try again') + '.';
            return;
          }
          // Same localStorage key vow-gate.js and the account modal write --
          // shared prefill across every auth surface on the site.
          try { localStorage.setItem('tnr-auth-email', email); } catch (e) {}
          renderCheckEmail(email);
        })
        .catch(function () { msg.textContent = 'Couldn’t send — please try again.'; });
    });
  }

  // "Check your email" state -- code entry + real resend, mirroring
  // vow-gate.js's renderCheckEmail (2026-08-25/26 sign-in-v2 pass).
  function renderCheckEmail(email) {
    var hasCodeVerify = !!(window.TurnerAuth
      && typeof window.TurnerAuth.verifyOtpCode === "function");
    box.innerHTML =
      '<div class="vp-lock">Check your email</div>' +
      '<p class="vp-gate-p">We sent a sign-in link to <strong>' + esc(email) + '</strong>. ' +
      'Click the link to unlock the sold price' + (hasCodeVerify ? ', or use the code below.' : '.') + '</p>' +
      (hasCodeVerify ?
        '<div style="margin-top:12px;">' +
          '<p style="font-size:13px;color:#c9c9c9;margin-bottom:8px;">Or enter the 8-digit code from the email:</p>' +
          '<form class="vp-code-form" autocomplete="one-time-code" novalidate style="display:flex;gap:8px;">' +
            '<input class="vp-code-input" name="code" type="text" inputmode="numeric" maxlength="8" ' +
              'autocomplete="one-time-code" placeholder="8-digit code" style="flex:1;min-width:0;">' +
            '<button type="submit" class="vp-gate-cta" style="flex:0 0 auto;">Verify</button>' +
          '</form>' +
          '<p class="vp-code-error" style="color:#ff8a8a;font-size:13px;margin-top:6px;"></p>' +
        '</div>'
        : '') +
      '<p style="margin-top:14px;font-size:13px;color:#c9c9c9;">Didn’t see it? Check your spam or junk folder first.</p>' +
      '<p style="margin-top:6px;font-size:13px;">' +
        '<a href="#" class="vp-resend">Send it again</a> · ' +
        '<a href="#" class="vp-try-different">try a different email address</a>.' +
      '</p>';

    var tryDifferent = box.querySelector('.vp-try-different');
    if (tryDifferent) {
      tryDifferent.addEventListener('click', function (ev) {
        ev.preventDefault();
        showSignIn();
      });
    }

    var resendBtn = box.querySelector('.vp-resend');
    var resendCooldownUntil = 0;
    if (resendBtn) {
      resendBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        if (Date.now() < resendCooldownUntil) return;
        var originalText = resendBtn.textContent;
        resendCooldownUntil = Date.now() + 45000;
        resendBtn.textContent = 'Sending…';
        window.TurnerAuth.sendMagicLink(email, { emailRedirectTo: window.location.href })
          .then(function (r) {
            if (r && r.error) {
              resendBtn.textContent = originalText;
              resendCooldownUntil = 0;
              return;
            }
            resendBtn.textContent = 'Sent ✓';
            setTimeout(function () { resendBtn.textContent = originalText; }, 45000);
          })
          .catch(function () {
            resendBtn.textContent = originalText;
            resendCooldownUntil = 0;
          });
      });
    }

    if (hasCodeVerify) {
      var codeForm = box.querySelector('.vp-code-form');
      var codeInput = box.querySelector('.vp-code-input');
      var codeErr = box.querySelector('.vp-code-error');
      codeForm.addEventListener('submit', function (ev) {
        ev.preventDefault();
        if (codeErr) codeErr.textContent = '';
        var code = (codeInput.value || '').replace(/\s+/g, '');
        if (!code) {
          if (codeErr) codeErr.textContent = 'Enter the code from the email.';
          return;
        }
        var submitBtn = codeForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Verifying…';
        window.TurnerAuth.verifyOtpCode(email, code).then(function (r) {
          if (r && r.error) {
            if (codeErr) codeErr.textContent = "That code didn't match \u2014 check the newest email or request a new link.";
            submitBtn.disabled = false;
            submitBtn.textContent = 'Verify';
            return;
          }
          // Success -- window.TurnerAuth's onAuthChange handler (already
          // wired below) fires SIGNED_IN and this gate's own listener calls
          // fetchReveal() -- nothing else to do here.
        }).catch(function () {
          if (codeErr) codeErr.textContent = "That code didn't match \u2014 check the newest email or request a new link.";
          submitBtn.disabled = false;
          submitBtn.textContent = 'Verify';
        });
      });
    }
  }

  window.TurnerAuth.ready.then(function () {
    if (window.TurnerAuth.getSession()) fetchReveal();
    else showSignIn();
    window.TurnerAuth.onAuthChange(function () {
      if (window.TurnerAuth.getSession()) fetchReveal();
    });
  });
})();
