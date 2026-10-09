/* site-feedback.js -- the consumer feedback button on the public sites (Mike's D-1009-72 (2), 2026-10-09).
 *
 * Tier-1, byte-identical on realestategander.com, avalonrealestate.ca, goosebay realestate, labwestrealty.com and
 * royallepageturner.com (fleet/canonical/js/site-feedback.js, always-on #27). Loaded by js/nav.js on public pages.
 *
 * Switch: NOTHING shows until Gander's site-feedback function answers GET ?probe=1 with {enabled:true} (gate SITE_FEEDBACK,
 * read by lib/gate.ts: table first, env override, default off). Off, error, offline or a non-public page = no button, no markup.
 * The probe result is kept in sessionStorage for 10 minutes so a visit makes at most one probe, not one per page.
 *
 * What it sends, only on Send: the note, the optional email, the page PATH (no query, no hash). No cookies, no account,
 * no analytics event, no fingerprint. The server derives the site from the Origin header and keeps a salted hash of the
 * address for the rate limit, never the address. If the response says looks_like_lead:true, the thank-you state fires a
 * "turner:feedback-sent" event and leaves the reserved slot [data-feedback-followup] for the lead session's card.
 */
(function () {
  'use strict';
  if (window.__turnerSiteFeedback) return;
  window.__turnerSiteFeedback = true;
  if (window.top !== window.self) return; // never inside a frame

  // Public pages only: the signed-in tools have their own feedback button.
  var path = location.pathname || '/';
  if (/^\/(agent|agent-sales|office|broker|app|client|deal|deals|login|auth)(\/|$)/i.test(path)) return;

  var host = location.hostname;
  var local = host === 'localhost' || host === '127.0.0.1';
  var ENDPOINT = (local || /(^|\.)realestategander\.com$/.test(host) ? '' : 'https://realestategander.com') + '/.netlify/functions/site-feedback';
  var CACHE_KEY = 'tsf_probe', CACHE_MS = 10 * 60 * 1000;
  var MAX_NOTE = 2000;

  function cached() {
    try {
      var v = (sessionStorage.getItem(CACHE_KEY) || '').split('|');
      if (v.length === 2 && Date.now() - Number(v[1]) < CACHE_MS) return v[0] === '1' ? 'on' : 'off';
    } catch (e) { /* storage blocked: probe every page */ }
    return '';
  }
  function remember(on) { try { sessionStorage.setItem(CACHE_KEY, (on ? '1' : '0') + '|' + Date.now()); } catch (e) { /* ignore */ } }

  function probe() {
    var c = cached();
    if (c) { if (c === 'on') mount(); return; }
    if (!window.fetch) return;
    fetch(ENDPOINT + '?probe=1', { method: 'GET', credentials: 'omit', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : { enabled: false }; })
      .then(function (j) { var on = !!(j && j.enabled === true); remember(on); if (on) mount(); })
      .catch(function () { /* leave the page exactly as it was */ });
  }

  function css() {
    if (document.getElementById('tsf-style')) return;
    var st = document.createElement('style');
    st.id = 'tsf-style';
    st.textContent =
      '.tsf-tab{position:fixed;left:12px;bottom:16px;z-index:9300;min-height:44px;padding:0 16px;display:inline-flex;align-items:center;gap:8px;' +
        'background:#fff;color:#1a1a1a;border:1px solid #c9c9c9;border-radius:22px;box-shadow:0 2px 10px rgba(0,0,0,.18);font:600 14px/1 Roboto,Arial,sans-serif;cursor:pointer;}' +
      '.tsf-tab:hover{border-color:#EA002A;color:#a0001c;}' +
      '.tsf-tab:focus-visible,.tsf-x:focus-visible,.tsf-go:focus-visible{outline:3px solid #EA002A;outline-offset:2px;}' +
      '.tsf-tab svg{width:16px;height:16px;flex:none;}' +
      '.tsf-card{position:fixed;left:12px;bottom:68px;z-index:9301;width:340px;max-width:calc(100vw - 24px);max-height:calc(100vh - 90px);overflow-y:auto;background:#fff;color:#1a1a1a;' +
        'border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.35);padding:20px 18px 18px;font-family:Roboto,Arial,sans-serif;box-sizing:border-box;}' +
      '.tsf-card[hidden],.tsf-tab[hidden],.tsf-followup[hidden],.tsf-form[hidden],.tsf-thanks[hidden]{display:none;}' +
      '.tsf-card h2{font:800 17px/1.25 Raleway,Arial,sans-serif;margin:0 40px 12px 0;color:#0a0a0a;}' +
      '.tsf-x{position:absolute;top:4px;right:4px;width:44px;height:44px;background:none;border:0;font-size:28px;line-height:1;color:#555;cursor:pointer;}' +
      '.tsf-card label{display:block;font-size:13px;font-weight:600;margin:12px 0 5px;color:#222;}' +
      '.tsf-card textarea,.tsf-card input[type=email]{width:100%;box-sizing:border-box;border:1px solid #c9c9c9;border-radius:6px;padding:10px 12px;font:16px/1.4 inherit;font-family:inherit;color:#111;background:#fff;}' +
      '.tsf-card textarea{min-height:104px;resize:vertical;}' +
      '.tsf-card textarea:focus,.tsf-card input:focus{outline:2px solid #EA002A;outline-offset:1px;border-color:#EA002A;}' +
      '.tsf-consent{font-size:12.5px;line-height:1.5;color:#444;margin:12px 0 12px;}' +
      '.tsf-go{display:block;width:100%;min-height:44px;background:#EA002A;color:#fff;border:0;border-radius:6px;font:700 15px/1 Raleway,Arial,sans-serif;letter-spacing:.03em;cursor:pointer;}' +
      '.tsf-go[disabled]{opacity:.6;cursor:wait;}' +
      '.tsf-err{color:#b00020;font-size:14px;margin:10px 0 0;}' +
      '.tsf-err:empty{display:none;}' +
      '.tsf-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;}' +
      '.tsf-thanks p{font-size:16px;line-height:1.5;margin:4px 40px 12px 0;font-weight:600;}' +
      '@media(max-width:1023px){.tsf-tab{bottom:calc(56px + 12px + env(safe-area-inset-bottom,0px));}' +
        '.tsf-card{left:8px;right:8px;width:auto;max-width:none;bottom:calc(131px + env(safe-area-inset-bottom,0px));max-height:calc(100vh - 180px);}}' +
      '@media(max-width:767px){.tsf-tab{left:18px;bottom:calc(56px + 15px + env(safe-area-inset-bottom,0px));width:44px;height:44px;min-height:44px;padding:0;justify-content:center;border-radius:50%;gap:0;}' +
        '.tsf-tab .tsf-lbl{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}.tsf-tab svg{width:20px;height:20px;}}' +
      '@media print{.tsf-tab,.tsf-card{display:none;}}';
    document.head.appendChild(st);
  }

  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
    if (html != null) e.innerHTML = html;
    return e;
  }

  function mount() {
    if (document.querySelector('.tsf-tab')) return;
    css();
    var tab = el('button', { type: 'button', class: 'tsf-tab', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'aria-label': 'Feedback' },
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span class="tsf-lbl">Feedback</span>');
    var card = el('div', { class: 'tsf-card', role: 'dialog', 'aria-labelledby': 'tsf-title', hidden: '' },
      '<button type="button" class="tsf-x" aria-label="Close feedback">&times;</button>' +
      '<form class="tsf-form" novalidate>' +
        '<h2 id="tsf-title">Tell us what would make this site better</h2>' +
        '<label for="tsf-note">Your note</label>' +
        '<textarea id="tsf-note" name="note" maxlength="' + MAX_NOTE + '" required placeholder="Tell us what would make this site better"></textarea>' +
        '<label for="tsf-email">Email, only if you’d like a reply</label>' +
        '<input id="tsf-email" name="email" type="email" autocomplete="email" maxlength="200" inputmode="email">' +
        '<div class="tsf-hp" aria-hidden="true"><label>Leave this empty<input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>' +
        '<p class="tsf-consent">We keep your note and the page you were on. No account, no tracking. If you leave an email we only use it to reply.</p>' +
        '<button type="submit" class="tsf-go">Send</button>' +
        '<p class="tsf-err" role="alert"></p>' +
      '</form>' +
      '<div class="tsf-thanks" hidden><h2 id="tsf-thanks-h" tabindex="-1">Feedback sent</h2><p>Thanks — we read every note.</p>' +
        '<div class="tsf-followup" data-feedback-followup hidden></div></div>');
    document.body.appendChild(tab);
    document.body.appendChild(card);

    var form = card.querySelector('.tsf-form'), thanks = card.querySelector('.tsf-thanks');
    var note = card.querySelector('#tsf-note'), email = card.querySelector('#tsf-email');
    var err = card.querySelector('.tsf-err'), go = card.querySelector('.tsf-go'), x = card.querySelector('.tsf-x');
    var follow = card.querySelector('[data-feedback-followup]');
    var isOpen = false;

    function open() {
      isOpen = true; card.hidden = false; tab.setAttribute('aria-expanded', 'true');
      (thanks.hidden ? note : card.querySelector('#tsf-thanks-h')).focus();
      document.addEventListener('keydown', onKey, true);
    }
    function close() {
      isOpen = false; card.hidden = true; tab.setAttribute('aria-expanded', 'false');
      document.removeEventListener('keydown', onKey, true);
      tab.focus();
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key !== 'Tab') return;
      var f = Array.prototype.filter.call(card.querySelectorAll('button,textarea,input'), function (n) {
        return !n.disabled && n.offsetParent !== null && n.tabIndex !== -1;
      });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    tab.addEventListener('click', function () { if (isOpen) close(); else open(); });
    x.addEventListener('click', close);

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      err.textContent = '';
      var n = note.value.replace(/^\s+|\s+$/g, ''), m = email.value.replace(/^\s+|\s+$/g, '');
      if (n.length < 3) { err.textContent = 'Please write a short note first.'; note.focus(); return; }
      if (m && !/^[^\s@<>]+@[^\s@<>]+\.[a-z]{2,}$/i.test(m)) { err.textContent = 'That email address looks off. You can leave it blank.'; email.focus(); return; }
      go.disabled = true; go.textContent = 'Sending…';
      var body = { note: n.slice(0, MAX_NOTE), page_path: location.pathname.slice(0, 200), website: form.elements.website.value };
      if (m) body.email = m;
      fetch(ENDPOINT, { method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j && j.ok, j: j || {} }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error(res.j.message || 'fail');
          form.hidden = true; thanks.hidden = false;
          if (res.j.looks_like_lead === true) {
            follow.hidden = false; follow.setAttribute('data-looks-like-lead', '1'); // shown only from the server's flag; the lead session's card renders into it
            try { document.dispatchEvent(new CustomEvent('turner:feedback-sent', { detail: { looks_like_lead: true, slot: follow } })); } catch (e2) { /* old browser */ }
          }
          card.querySelector('#tsf-thanks-h').focus();
          note.value = ''; email.value = '';
        })
        .catch(function (e3) {
          err.textContent = (e3 && e3.message && e3.message !== 'fail' && e3.message !== 'Failed to fetch') ? e3.message : 'Sorry, that did not send. Please try again in a moment.';
          go.disabled = false; go.textContent = 'Send';
        });
    });
    // Re-opening after a send starts a fresh note.
    tab.addEventListener('click', function () {
      if (isOpen && !thanks.hidden) { thanks.hidden = true; form.hidden = false; go.disabled = false; go.textContent = 'Send'; note.focus(); }
    });
  }

  function start() { if ('requestIdleCallback' in window) requestIdleCallback(probe, { timeout: 4000 }); else setTimeout(probe, 1500); }
  if (document.readyState === 'complete') start(); else window.addEventListener('load', start);
})();
