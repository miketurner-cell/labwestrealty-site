/* recruit-form.js -- the confidential broker form behind the recruiting buttons (Mike's D-1008-106, 2026-10-08).
 *
 * Byte-identical on realestategander.com, avalonrealestate.ca, labwestrealty.com and royallepageturner.com (always-on #27);
 * the copy in realestategander-site is the canonical one.
 *
 * Every <a data-recruit-cta> ships as a mailto: to the broker (works with no JavaScript and while the gate is off). On load this
 * asks realestategander.com's recruit-inquiry function whether the form is open (gate RECRUIT_FORM). Only on {enabled:true}
 * do the buttons open the form; anything else (off, error, offline) leaves the mailto exactly as it was.
 * The form posts to that function, which emails Mike Turner only: no copy to anyone, no CRM, no database.
 */
(function () {
  'use strict';
  if (window.__turnerRecruitForm) return;
  window.__turnerRecruitForm = true;

  var BROKER_NAME = 'Mike Turner';
  var BROKER_EMAIL = 'miketurner@royallepage.ca'; // tools/agent_roster.json slug mike-turner (checked by tools/tests/recruit-form-test.py)
  var BROKER_PHONE = '709-424-6517';
  var host = location.hostname;
  var local = host === 'localhost' || host === '127.0.0.1';
  var ENDPOINT = (local || /(^|\.)realestategander\.com$/.test(host) ? '' : 'https://realestategander.com') + '/.netlify/functions/recruit-inquiry';
  var YEARS = ['Not licensed yet', 'Licence in progress', 'Under 2 years', '2 to 5 years', '5 to 10 years', 'Over 10 years'];

  function siteId() {
    var s = (window.TURNER_SITE || '').toLowerCase();
    if (s) return s;
    if (/avalonrealestate/.test(host)) return 'avalon';
    if (/labwest/.test(host)) return 'labwest';
    if (/royallepageturner/.test(host)) return 'hub';
    if (/goosebay/.test(host)) return 'goosebay';
    return 'gander';
  }

  function css() {
    if (document.getElementById('rcf-style')) return;
    var st = document.createElement('style');
    st.id = 'rcf-style';
    st.textContent =
      '.rcf-back{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:10000;display:flex;align-items:flex-start;justify-content:center;overflow-y:auto;padding:24px 16px;}' +
      '.rcf{background:#fff;color:#1a1a1a;max-width:560px;width:100%;border-radius:10px;padding:28px 26px 24px;position:relative;font-family:Roboto,Arial,sans-serif;box-shadow:0 20px 60px rgba(0,0,0,.4);margin:auto 0;}' +
      '.rcf h2{font-family:Raleway,Arial,sans-serif;font-weight:900;font-size:24px;line-height:1.2;margin:0 0 6px;color:#0a0a0a;}' +
      '.rcf-conf{display:inline-block;background:#fdecef;color:#a0001c;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;border-radius:3px;padding:3px 8px;margin:0 0 10px;}' +
      '.rcf p.rcf-sub{font-size:14px;color:#444;line-height:1.6;margin:0 0 18px;}' +
      '.rcf label{display:block;font-size:13px;font-weight:600;color:#222;margin:0 0 5px;}' +
      '.rcf label span{font-weight:400;color:#777;}' +
      '.rcf input[type=text],.rcf input[type=email],.rcf input[type=tel],.rcf select,.rcf textarea{width:100%;box-sizing:border-box;border:1px solid #c9c9c9;border-radius:5px;padding:10px 12px;font-size:15px;font-family:inherit;color:#111;background:#fff;}' +
      '.rcf textarea{min-height:96px;resize:vertical;}' +
      '.rcf input:focus,.rcf select:focus,.rcf textarea:focus{outline:2px solid #EA002A;outline-offset:1px;border-color:#EA002A;}' +
      '.rcf-f{margin:0 0 14px;}' +
      '.rcf-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}' +
      '@media(max-width:520px){.rcf-row{grid-template-columns:1fr;}.rcf{padding:24px 18px 20px;}}' +
      '.rcf-consent{display:flex;gap:10px;align-items:flex-start;font-size:13px;color:#333;line-height:1.5;margin:4px 0 16px;}' +
      '.rcf-consent input{margin-top:3px;width:18px;height:18px;flex:none;accent-color:#EA002A;}' +
      '.rcf-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;}' +
      '.rcf-go{display:block;width:100%;background:#EA002A;color:#fff;border:0;border-radius:5px;padding:14px;font-size:15px;font-weight:700;letter-spacing:.03em;cursor:pointer;font-family:Raleway,Arial,sans-serif;}' +
      '.rcf-go[disabled]{opacity:.6;cursor:wait;}' +
      '.rcf-x{position:absolute;top:10px;right:12px;background:none;border:0;font-size:28px;line-height:1;color:#666;cursor:pointer;padding:4px 8px;}' +
      '.rcf-err{color:#b00020;font-size:14px;margin:10px 0 0;display:none;}' +
      '.rcf-alt{font-size:13px;color:#555;margin:14px 0 0;line-height:1.5;}' +
      '.rcf-alt a{color:#c8001f;}';
    document.head.appendChild(st);
  }

  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
    if (html != null) e.innerHTML = html;
    return e;
  }

  var lastFocus = null;
  function close(back) {
    if (back && back.parentNode) back.parentNode.removeChild(back);
    document.removeEventListener('keydown', onKey, true);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  var openBack = null;
  function onKey(e) {
    if (!openBack) return;
    if (e.key === 'Escape') { close(openBack); openBack = null; return; }
    if (e.key === 'Tab') {
      var f = openBack.querySelectorAll('input:not(.rcf-hp-in),select,textarea,button,a[href]');
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
      else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
    }
  }

  function alt() {
    return 'Prefer to reach Mike directly? <a href="mailto:' + BROKER_EMAIL + '">' + BROKER_EMAIL + '</a> or <a href="tel:+1' +
      BROKER_PHONE.replace(/\D/g, '') + '">' + BROKER_PHONE + '</a>.';
  }

  function open(evt) {
    if (evt) evt.preventDefault();
    css();
    lastFocus = document.activeElement;
    var opts = YEARS.map(function (y) { return '<option value="' + y + '">' + y + '</option>'; }).join('');
    var back = el('div', { 'class': 'rcf-back' });
    var box = el('div', { 'class': 'rcf', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'rcf-title' },
      '<button type="button" class="rcf-x" aria-label="Close">&times;</button>' +
      '<p class="rcf-conf">Confidential</p>' +
      '<h2 id="rcf-title">Talk to the broker</h2>' +
      '<p class="rcf-sub">This goes only to ' + BROKER_NAME + ', Broker/Owner. It is not copied to anyone else at the brokerage and is not added to our client database. He will contact you personally.</p>' +
      '<form novalidate>' +
      '<div class="rcf-row"><div class="rcf-f"><label for="rcf-name">Name</label><input type="text" id="rcf-name" name="name" autocomplete="name" required></div>' +
      '<div class="rcf-f"><label for="rcf-phone">Phone</label><input type="tel" id="rcf-phone" name="phone" autocomplete="tel" required></div></div>' +
      '<div class="rcf-f"><label for="rcf-email">Email</label><input type="email" id="rcf-email" name="email" autocomplete="email" required></div>' +
      '<div class="rcf-row"><div class="rcf-f"><label for="rcf-brok">Current brokerage <span>(optional)</span></label><input type="text" id="rcf-brok" name="brokerage" autocomplete="organization"></div>' +
      '<div class="rcf-f"><label for="rcf-years">Years licensed</label><select id="rcf-years" name="years_licensed" required><option value="">Choose one</option>' + opts + '</select></div></div>' +
      '<div class="rcf-f"><label for="rcf-msg">Message</label><textarea id="rcf-msg" name="message" required placeholder="Where you are now and what you would like to talk about"></textarea></div>' +
      '<div class="rcf-hp" aria-hidden="true"><label for="rcf-hp">Company website</label><input type="text" id="rcf-hp" class="rcf-hp-in" name="company_website" tabindex="-1" autocomplete="off"></div>' +
      '<label class="rcf-consent"><input type="checkbox" name="consent" required><span>I agree that ' + BROKER_NAME + ' may contact me by email or phone about this inquiry.</span></label>' +
      '<button type="submit" class="rcf-go">Send to ' + BROKER_NAME + '</button>' +
      '<p class="rcf-err" role="alert"></p>' +
      '<p class="rcf-alt">' + alt() + '</p>' +
      '</form>');
    back.appendChild(box);
    document.body.appendChild(back);
    openBack = back;
    document.addEventListener('keydown', onKey, true);
    back.addEventListener('click', function (e) { if (e.target === back) { close(back); openBack = null; } });
    box.querySelector('.rcf-x').addEventListener('click', function () { close(back); openBack = null; });
    var form = box.querySelector('form');
    box.querySelector('#rcf-name').focus();
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var err = form.querySelector('.rcf-err');
      var btn = form.querySelector('.rcf-go');
      err.style.display = 'none';
      var v = function (n) { var f = form.elements[n]; return f ? String(f.value || '').trim() : ''; };
      var problem = !v('name') ? 'Please add your name.' :
        !/^[^\s@<>]+@[^\s@<>]+\.[a-z]{2,}$/i.test(v('email')) ? 'Please check your email address.' :
        (v('phone').match(/\d/g) || []).length < 7 ? 'Please add a phone number.' :
        !v('years_licensed') ? 'Please choose how long you have been licensed.' :
        !v('message') ? 'Please add a short message.' :
        !form.elements.consent.checked ? 'Please tick the consent box.' : '';
      if (problem) { err.textContent = problem; err.style.display = 'block'; return; }
      btn.disabled = true; btn.textContent = 'Sending...';
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: v('name'), email: v('email'), phone: v('phone'), brokerage: v('brokerage'),
          years_licensed: v('years_licensed'), message: v('message'), consent: true,
          company_website: v('company_website'), site: siteId(), page: location.pathname
        })
      }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j && j.ok, j: j || {} }; }); })
        .then(function (res) {
          if (res.ok) {
            box.querySelector('form').innerHTML = '<p class="rcf-sub" style="font-size:16px;color:#111;"><strong>Sent.</strong> Only ' + BROKER_NAME +
              ' receives this. He will contact you personally.</p><button type="button" class="rcf-go">Close</button>';
            var c = box.querySelector('.rcf-go');
            c.addEventListener('click', function () { close(back); openBack = null; });
            c.focus();
            try { if (typeof window.gtag === 'function') window.gtag('event', 'recruiting_inquiry', { form_name: 'confidential_broker_form', site: siteId() }); } catch (x) { /* no-op */ }
          } else {
            err.innerHTML = (res.j.message ? res.j.message + ' ' : 'It did not send. ') + alt();
            err.style.display = 'block';
            btn.disabled = false; btn.textContent = 'Send to ' + BROKER_NAME;
          }
        })
        .catch(function () {
          err.innerHTML = 'It did not send. ' + alt();
          err.style.display = 'block';
          btn.disabled = false; btn.textContent = 'Send to ' + BROKER_NAME;
        });
    });
  }

  function wire() {
    var links = document.querySelectorAll('a[data-recruit-cta]');
    if (!links.length || typeof fetch !== 'function') return;
    fetch(ENDPOINT, { method: 'GET', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || j.enabled !== true) return; // gate off or unknown: the mailto stays
        for (var i = 0; i < links.length; i++) {
          links[i].setAttribute('href', '#confidential-inquiry');
          links[i].removeAttribute('target');
          links[i].setAttribute('aria-haspopup', 'dialog');
          links[i].addEventListener('click', open);
        }
        if (location.hash === '#confidential-inquiry') open();
      })
      .catch(function () { /* leave the mailto */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
  else wire();
})();
