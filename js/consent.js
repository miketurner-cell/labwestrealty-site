/* consent.js -- cookie / tracking consent for the Turner consumer sites (Tier-1, byte-identical on all 5 sites).
 *
 * Mike D-1027-13 item 8 (QA H8): Meta pixel, Google Analytics and the Follow Up Boss tracker fired on first
 * load with no notice. Also D-1027-02 (CASL / privacy basics). Plan: _research/Consent_Banner_Plan_2026-10-27.md.
 * Not legal advice; wording is for a lawyer to confirm before the switch goes to "on".
 *
 * Switch: window.TURNER_CONSENT_SWITCH, set by /data/consent-switch.js (per site, not cache-stamped, so a flip is
 * one small file). Register: CONSENT_BANNER in tools/gates.json.
 *   off     (default) nothing changes for visitors: every gated tracker is started as soon as this file runs.
 *   preview only a visitor who opened a page with ?consent=preview (kept for the tab; ?consent=off clears it)
 *           gets the banner and the gating; everyone else is exactly "off".
 *   on      every visitor: essential-only until Accept.
 *
 * How the trackers are held back (pages are static, so the hold is in the HTML):
 *   <script type="text/plain" data-consent="analytics|marketing" [data-src=URL]>...</script>
 * is inert. When the visitor has accepted (or the switch is off for them) this file re-creates each one as a real
 * script. js/analytics-events.js (Meta pixel) and js/tawk.js use TurnerCookieConsent.when() the same way.
 * Google Consent Mode v2 "basic": the four consent types are pushed as denied FIRST; gtag.js is not even
 * requested until Accept, then the four are updated to granted. Decline / no answer = gtag.js never loads.
 *
 * Choice: localStorage "tn_consent" = {v:1,c:"accepted"|"declined",t:ms}; no cookie of our own; asked again after
 * 12 months. Global Privacy Control (navigator.globalPrivacyControl) is treated as Decline with no banner.
 * Footer link: any element with data-consent-settings re-opens the banner (footer.js ships one, hidden until active).
 */
(function () {
  'use strict';
  if (window.TurnerCookieConsent) return;

  var KEY = 'tn_consent';
  var PKEY = 'tn_consent_preview';
  var TTL = 365 * 24 * 60 * 60 * 1000;
  var SW = String(window.TURNER_CONSENT_SWITCH || 'off').toLowerCase();
  var PRIVACY = window.TURNER_CONSENT_PRIVACY || '/pages/privacy-policy.html';

  function ls(op, k, v) {
    try {
      if (op === 'get') return window.localStorage.getItem(k);
      if (op === 'set') return window.localStorage.setItem(k, v);
      if (op === 'del') return window.localStorage.removeItem(k);
    } catch (e) { /* private mode: treated as no stored choice */ }
    return null;
  }
  function ss(op, k, v) {
    try {
      if (op === 'get') return window.sessionStorage.getItem(k);
      if (op === 'set') return window.sessionStorage.setItem(k, v);
      if (op === 'del') return window.sessionStorage.removeItem(k);
    } catch (e) { /* ignore */ }
    return null;
  }

  // ?consent=preview / ?consent=off, remembered for the tab.
  try {
    var m = /[?&]consent=(preview|off)\b/.exec(window.location.search || '');
    if (m) { if (m[1] === 'preview') ss('set', PKEY, '1'); else ss('del', PKEY); }
  } catch (e) { /* ignore */ }

  var active = SW === 'on' || (SW === 'preview' && ss('get', PKEY) === '1');

  // ── stored choice ───────────────────────────────────────────────
  function readChoice() {
    var raw = ls('get', KEY);
    if (!raw) return null;
    try {
      var o = JSON.parse(raw);
      if (!o || o.v !== 1 || (o.c !== 'accepted' && o.c !== 'declined')) return null;
      if (!o.t || Date.now() - o.t > TTL) return null;
      return o.c;
    } catch (e) { return null; }
  }
  var gpc = false;
  try { gpc = !!(navigator && navigator.globalPrivacyControl === true); } catch (e) { /* ignore */ }
  var state = active ? (readChoice() || (gpc ? 'declined' : null)) : 'accepted';   // inactive = legacy behaviour

  // ── Google Consent Mode v2 (defaults denied, first in the queue) ─
  var DENIED = { ad_storage: 'denied', analytics_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' };
  var GRANTED = { ad_storage: 'granted', analytics_storage: 'granted', ad_user_data: 'granted', ad_personalization: 'granted' };
  window.dataLayer = window.dataLayer || [];
  if (typeof window.gtag !== 'function') { window.gtag = function () { window.dataLayer.push(arguments); }; }
  function pushConsent(kind, vals, front) {
    var a = (function () { return arguments; })('consent', kind, vals);
    if (front) window.dataLayer.unshift(a); else window.dataLayer.push(a);
  }
  if (active) {
    var d = {}; for (var k in DENIED) d[k] = DENIED[k];
    d.wait_for_update = 500;
    pushConsent('default', d, true);          // before the page's own gtag('js') / gtag('config')
    if (state === 'accepted') pushConsent('update', GRANTED, false);
  }

  // ── run gated things ───────────────────────────────────────────
  var queue = [];
  function when(cat, fn) {
    if (typeof fn !== 'function') return;
    if (state === 'accepted') { try { fn(); } catch (e) { /* a tracker must never break a page */ } }
    else if (state === null) queue.push(fn);
    /* declined: never */
  }
  function flush() { var q = queue; queue = []; for (var i = 0; i < q.length; i++) { try { q[i](); } catch (e) { /* ignore */ } } }

  function release() {
    var nodes = document.querySelectorAll('script[type="text/plain"][data-consent]');
    for (var i = 0; i < nodes.length; i++) {
      var o = nodes[i];
      if (o.getAttribute('data-consent-done')) continue;
      o.setAttribute('data-consent-done', '1');
      var s = document.createElement('script');
      for (var j = 0; j < o.attributes.length; j++) {
        var n = o.attributes[j].name;
        if (n === 'type' || n === 'data-src' || n === 'data-consent' || n === 'data-consent-done') continue;
        s.setAttribute(n, o.attributes[j].value);
      }
      var src = o.getAttribute('data-src');
      if (src) s.src = src; else s.text = o.text || o.textContent || '';
      if (o.parentNode) o.parentNode.insertBefore(s, o.nextSibling);
    }
  }

  // The pre-Accept queue of other scripts that loaded before this file (async ones): window.__tcq.
  function drainEarly() {
    var q = window.__tcq || [];
    window.__tcq = { push: function (e) { when(e[0], e[1]); } };
    for (var i = 0; i < q.length; i++) when(q[i][0], q[i][1]);
  }

  // ── banner ─────────────────────────────────────────────────────
  var bannerEl = null, styleEl = null, onResize = null;
  var CSS =
    '#tn-consent{position:fixed;left:8px;right:8px;bottom:8px;z-index:9400;max-width:640px;margin:0 auto;box-sizing:border-box;' +
    'background:#111;color:#fff;border:1px solid #444;border-radius:12px;padding:10px 12px;font:13px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.35)}' +
    '#tn-consent p{margin:0 0 8px}#tn-consent a{color:#fff;text-decoration:underline}' +
    '#tn-consent .tn-c-row{display:flex;gap:8px}' +
    '#tn-consent button{flex:1 1 0;min-height:44px;border-radius:8px;border:2px solid #fff;font:600 15px/1 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer;background:#fff;color:#111}' +
    '#tn-consent button.tn-c-yes{background:#ea002a;border-color:#ea002a;color:#fff}' +
    '#tn-consent button:focus-visible{outline:3px solid #ffbf47;outline-offset:2px}' +
    'html.tn-consent-open #tnr-install-cta,html.tn-consent-open #tc-bubble,html.tn-consent-open #tc-panel{display:none!important}' +
    'html.tn-consent-on [data-consent-settings]{display:inline!important}' +
    '@media (min-width:769px){#tn-consent{left:16px;right:auto;bottom:16px;margin:0;width:420px}}';

  function placeBanner() {
    if (!bannerEl) return;
    var bar = document.querySelector('.mab-bar'), lift = 0;
    if (bar) { var r = bar.getBoundingClientRect(); if (r.height > 0 && getComputedStyle(bar).display !== 'none') lift = Math.max(0, window.innerHeight - r.top); }
    bannerEl.style.bottom = (lift + 8) + 'px';
    var h = bannerEl.offsetHeight + lift + 16;
    document.documentElement.style.setProperty('--tn-consent-h', h + 'px');
    document.body.style.paddingBottom = h + 'px';      // content scrolls clear of the banner instead of sitting under it
  }

  function closeBanner() {
    if (bannerEl && bannerEl.parentNode) bannerEl.parentNode.removeChild(bannerEl);
    bannerEl = null;
    document.documentElement.classList.remove('tn-consent-open');
    document.documentElement.style.removeProperty('--tn-consent-h');
    if (document.body) document.body.style.paddingBottom = '';
    if (onResize) { window.removeEventListener('resize', onResize); onResize = null; }
  }

  function openBanner() {
    if (!active || bannerEl || !document.body) return;
    if (!styleEl) { styleEl = document.createElement('style'); styleEl.textContent = CSS; document.head.appendChild(styleEl); }
    var el = document.createElement('div');
    el.id = 'tn-consent'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Cookie notice');
    el.innerHTML =
      '<p>We use cookies to see how the site is used and to measure our ads. The site works without them. ' +
      '<a href="' + PRIVACY + '">Privacy policy</a></p>' +
      '<div class="tn-c-row"><button type="button" class="tn-c-no">Decline</button><button type="button" class="tn-c-yes">Accept</button></div>';
    el.querySelector('.tn-c-yes').addEventListener('click', accept);
    el.querySelector('.tn-c-no').addEventListener('click', decline);
    document.body.appendChild(el);
    bannerEl = el;
    document.documentElement.classList.add('tn-consent-open');
    placeBanner();
    onResize = placeBanner; window.addEventListener('resize', onResize);
    setTimeout(placeBanner, 400);                     // the action bar mounts after load
  }

  function save(c) { ls('set', KEY, JSON.stringify({ v: 1, c: c, t: Date.now() })); }

  function accept() {
    var was = state;
    save('accepted'); state = 'accepted';
    closeBanner();
    pushConsent('update', GRANTED, false);
    release(); flush();
    return was;
  }
  function decline() {
    var was = state;
    save('declined'); state = 'declined'; queue = [];
    closeBanner();
    pushConsent('update', DENIED, false);
    if (was === 'accepted') {                         // withdrawing: drop the cookies we can and start clean
      try {
        var names = document.cookie.split(';');
        for (var i = 0; i < names.length; i++) {
          var nm = names[i].split('=')[0].trim();
          if (/^(_ga|_gid|_gat|_gcl|_fb|__utm|fub|wt_)/i.test(nm)) {
            var host = location.hostname, parts = host.split('.');
            var doms = [host, '.' + host, '.' + parts.slice(-2).join('.')];
            for (var d2 = 0; d2 < doms.length; d2++) document.cookie = nm + '=; Max-Age=0; path=/; domain=' + doms[d2];
            document.cookie = nm + '=; Max-Age=0; path=/';
          }
        }
      } catch (e) { /* ignore */ }
      window.location.reload();
    }
    return was;
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target && ev.target.closest ? ev.target.closest('[data-consent-settings]') : null;
    if (!t) return;
    ev.preventDefault();
    openBanner();
  });

  window.TurnerCookieConsent = {
    when: when,
    state: function () { return state; },
    active: function () { return active; },
    open: openBanner,
    accept: accept,
    decline: decline,
    switchValue: SW
  };

  function start() {
    drainEarly();
    if (active) document.documentElement.classList.add('tn-consent-on');
    if (state === 'accepted') { release(); flush(); }
    else if (state === null) openBanner();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
