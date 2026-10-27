/*
 * consent-forms.js -- CASL consent line, optional "Also email me updates" box, 16px inputs, autocomplete.
 *
 * Mike, D-1027-02 (10-27, CASL gaps) + D-1027-03 (forms parts): every consumer lead form shows
 *   - one line under Submit: "By sending, you agree we may contact you about this request. Privacy policy."
 *   - an OPTIONAL, unticked "Also email me updates" box (express consent; whole row tappable, >= 44px)
 * and the Listing Email Alerts sign-up carries a REQUIRED express-consent checkbox (it is written into that form's own
 * template in js/boldtrail-forms.js, data-consent="alerts"; this file only styles it and keeps it required).
 * Inputs are 16px (iOS zooms the page on focus below that) and name / email / phone fields get autocomplete tokens.
 *
 * Consent record: when a form posts to lead-receive, the fetch wrapper below adds marketing_optin (true = express consent,
 * false = inquiry only, i.e. implied), consent_at (ISO timestamp of the tick/submit) and consent_page (the page URL). lead-receive
 * writes express_marketing / express_inquiry + the timestamp into Follow Up Boss's "Casl Consent" / "Casl Consent At" fields.
 * A flow this file does not recognise is left exactly as it was (no consent state recorded = the server default).
 *
 * Skipped on purpose: careers / join / recruiting forms (their own builder), sign-in and registration forms, search forms,
 * the site-feedback widget, and any form that already carries its own marketing_optin box or consent line.
 *
 * Byte-identical on every site (fleet canonical). Loaded by js/boldtrail-forms.js on the sites that carry lead forms.
 * Not legal advice: wording to be confirmed by a lawyer.
 */
(function () {
  'use strict';
  if (window.TurnerConsent) return;

  var PRIVACY_URL = '/pages/privacy-policy.html';
  var SENDER = 'Royal LePage Turner Realty, 204 Airport Blvd, Gander NL A1V 1L6';
  var LINE_TEXT = 'By sending, you agree we may contact you about this request. ';
  var OPTIN_TEXT = 'Also email me updates';
  var OPTIN_SUB = SENDER + '. Unsubscribe any time from the link in every email.';
  var ALERTS_TEXT = 'I agree to receive Listing Email Alerts from ' + SENDER + '. Unsubscribe any time from the link in every email.';
  var FRESH_MS = 10 * 60 * 1000;

  var state = null;   // last submitted lead form: {optin, at, page, t}

  function q(el, sel) { try { return el.querySelector(sel); } catch (e) { return null; } }
  function qa(el, sel) { try { return Array.prototype.slice.call(el.querySelectorAll(sel)); } catch (e) { return []; } }

  // ---------------------------------------------------------------- styles (16px inputs, consent block, tap targets)
  function injectStyles() {
    if (document.getElementById('tc-consent-css')) return;
    var s = document.createElement('style');
    s.id = 'tc-consent-css';
    s.textContent =
      'input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=range]):not([type=submit]):not([type=button]):not([type=image]):not([type=file]):not([type=color]),select,textarea{font-size:16px}' +
      '.tc-consent{margin:12px 0 0;text-align:left;font-family:inherit}' +
      'form label.tc-optin,form label.tc-alerts{display:flex;gap:12px;align-items:flex-start;box-sizing:border-box;min-height:44px;padding:10px 0;margin:0;' +
        'cursor:pointer;text-transform:none;letter-spacing:normal;font-weight:400;font-size:14px;line-height:1.45;color:inherit;width:100%}' +
      'form .tc-optin input[type=checkbox],form .tc-alerts input[type=checkbox]{flex:none;width:22px;height:22px;min-width:22px;margin:1px 0 0;padding:0;accent-color:#EA002A;cursor:pointer}' +
      'form .tc-optin>span,form .tc-alerts>span{display:block;min-width:0}' +
      'form .tc-optin .tc-sub{display:block;margin-top:2px;font-size:12px;line-height:1.4;opacity:.75}' +
      'form .tc-line{margin:8px 0 0;font-size:13px;line-height:1.45;opacity:.8;text-align:left;text-transform:none;letter-spacing:normal;font-weight:400}' +
      'form .tc-line a{color:inherit;text-decoration:underline;display:inline-block;padding:2px 0}';
    (document.head || document.documentElement).appendChild(s);
  }

  // ---------------------------------------------------------------- which forms
  var SKIP_FORM = /feedback|search|login|signin|sign-in|signup|register|recruit|career|newsletter-unsub|filter|vow/i;
  var SKIP_PATH = /^\/(agent|account|broker|office|admin|app|saved)\b|\/(join|careers|become-a-realtor|why-join|work-with-us)/i;

  function isLeadForm(f) {
    if (!f || f.nodeType !== 1 || f.tagName !== 'FORM') return false;
    if (f.hasAttribute('data-consent-skip') || (f.closest && f.closest('[data-consent-skip]'))) return false;
    if (f.getAttribute('role') === 'search') return false;
    if (q(f, 'input[type=password]')) return false;
    if (SKIP_FORM.test((f.id || '') + ' ' + (f.className || '') + ' ' + (f.getAttribute('action') || ''))) return false;
    if (f.closest && f.closest('#site-feedback,[id*=feedback],[class*=feedback],[id*=vow],[class*=vow-]')) return false;
    // already carries its own consent (the Listing Text Alerts form, VOW / homepage / account sign-ups, report sign-ups)
    if (q(f, '[name=years_licensed],[name=marketing_optin],.rf-consent,[data-consent-line],input[type=checkbox][id*=consent],input[type=checkbox][name*=consent],input[type=checkbox][class*=consent]')) return false;
    if (SKIP_PATH.test(location.pathname) && !/\/contact(\.html)?$/.test(location.pathname)) return false;
    return !!q(f, 'input[type=email],input[type=tel],input[name=email],input[name=phone]');
  }

  function submitButton(f) {
    var b = qa(f, 'button[type=submit],input[type=submit]').pop() || qa(f, 'button:not([type=button]):not([type=reset])').pop();
    return b || null;
  }

  // ---------------------------------------------------------------- autocomplete + labels
  function setAc(el, token) { if (!el.getAttribute('autocomplete')) el.setAttribute('autocomplete', token); }
  function enhanceFields(f) {
    qa(f, 'input,select,textarea').forEach(function (el) {
      if (el.type === 'hidden' || el.type === 'checkbox' || el.type === 'radio' || el.type === 'submit' || el.type === 'button') return;
      var n = (el.getAttribute('name') || el.id || '').toLowerCase().replace(/[^a-z]/g, '');
      if (/^(rfhpcheck|website|url)$/.test(n)) return;
      var h = [el.getAttribute('name'), el.id, el.getAttribute('aria-label'), el.getAttribute('placeholder')].join(' ').toLowerCase();
      var textual = el.tagName === 'INPUT' && (el.type === 'text' || el.type === '');
      if (el.type === 'email' || n === 'email') setAc(el, 'email');
      else if (el.type === 'tel' || /^(phone|phonenumber|tel|mobile)$/.test(n)) setAc(el, 'tel');
      else if (textual && /(^|[^a-z])(first|fname|given)([^a-z]|$)/.test(h)) setAc(el, 'given-name');
      else if (textual && /(^|[^a-z])(last|lname|surname|family)([^a-z]|$)/.test(h)) setAc(el, 'family-name');
      else if (textual && /^(name|fullname|yourname)$/.test(n)) setAc(el, 'name');
      // a select or field with no label of any kind gets its placeholder / first option as the accessible name
      if (!el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !(el.labels && el.labels.length) && !(el.closest && el.closest('label'))) {
        var nm = el.getAttribute('placeholder') || (el.tagName === 'SELECT' && el.options && el.options[0] ? el.options[0].text : '') || el.getAttribute('name') || '';
        if (nm) el.setAttribute('aria-label', nm.replace(/[_-]+/g, ' '));
      }
    });
  }

  // ---------------------------------------------------------------- the consent block
  // text colour from the real background behind the form (a light page must not get white text, a dark one must not get dark)
  function textColourFor(el) {
    try {
      for (var n = el; n && n.nodeType === 1; n = n.parentNode) {
        var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(getComputedStyle(n).backgroundColor || '');
        if (m && (m[4] === undefined || parseFloat(m[4]) > 0.5)) {
          var lum = 0.299 * m[1] + 0.587 * m[2] + 0.114 * m[3];
          return lum < 140 ? 'rgba(255,255,255,0.85)' : '#333333';
        }
      }
    } catch (e) { return ''; }
    return '#333333';   // no opaque background anywhere above the form: the browser's white canvas
  }
  var seq = 0;
  function enhanceForm(f) {
    if (f.getAttribute('data-consent-done')) return;
    f.setAttribute('data-consent-done', '1');
    enhanceFields(f);
    var btn = submitButton(f);
    var id = 'tc-' + (++seq);
    var txt = (btn && (btn.textContent || btn.value) || '').toLowerCase();
    var emailOnly = !q(f, 'textarea') && !q(f, 'input[type=tel],input[name=phone]') && /subscribe|newsletter|market report|send me the report/.test(txt);
    var line = document.createElement('p');
    line.className = 'tc-line';
    line.setAttribute('data-consent-line', '');
    if (emailOnly) {
      // sign-ups: the subscribe press is the express consent, so the line names the sender and the unsubscribe
      line.innerHTML = 'By subscribing, you agree to receive these emails from ' + SENDER + '. Unsubscribe any time from the link in every email. <a href="' + PRIVACY_URL + '">Privacy policy</a>.';
      f.setAttribute('data-consent-kind', 'express-signup');
    } else {
      // inquiry: the optional box reads before Submit, the one-line notice sits under it
      var label = document.createElement('label');
      label.className = 'tc-optin';
      label.setAttribute('for', id);
      label.innerHTML = '<input type="checkbox" id="' + id + '" name="marketing_optin" value="1" data-tc="optin"><span>' + OPTIN_TEXT +
        '<span class="tc-sub">' + OPTIN_SUB + '</span></span>';
      if (btn && btn.parentNode) btn.parentNode.insertBefore(label, btn); else f.appendChild(label);
      line.innerHTML = LINE_TEXT + '<a href="' + PRIVACY_URL + '">Privacy policy</a>.';
      f.setAttribute('data-consent-kind', 'inquiry');
    }
    if (btn && btn.parentNode) btn.parentNode.insertBefore(line, btn.nextSibling); else f.appendChild(line);
    var col = textColourFor(f);
    if (col) qa(f, '[data-consent-line],label.tc-optin').forEach(function (e) { e.style.color = col; });
  }

  function enhanceAlerts(f) {
    // the Listing Email Alerts form carries its own checkbox in the template; keep it required and recorded
    qa(f, 'input[data-tc=alerts]').forEach(function (c) { c.required = true; c.setAttribute('aria-required', 'true'); });
    enhanceFields(f);
    f.setAttribute('data-consent-done', '1');
  }

  function scan(root) {
    root = root || document;
    qa(root, 'form[data-consent="alerts"]').forEach(enhanceAlerts);
    var forms = root.tagName === 'FORM' ? [root] : qa(root, 'form');
    forms.forEach(function (f) {
      // field hygiene (autocomplete tokens, accessible names) for every contact form, even one that carries its own consent
      if (!f.getAttribute('data-fields-done') && q(f, 'input[type=email],input[type=tel]') && !q(f, 'input[type=password]')) { f.setAttribute('data-fields-done', '1'); enhanceFields(f); }
      if (isLeadForm(f)) enhanceForm(f);
    });
  }

  // ---------------------------------------------------------------- record the consent state at submit time
  function record(f) {
    if (!f || !f.querySelector) return;
    var tick = q(f, 'input[data-tc=optin],input[data-tc=alerts],input[name=marketing_optin]');
    var kind = f.getAttribute('data-consent-kind') || (f.getAttribute('data-consent') === 'alerts' ? 'alerts' : '');
    if (!tick && !kind) return;   // a form this file does not manage: leave the post alone
    state = {
      optin: kind === 'express-signup' || kind === 'alerts' ? true : !!(tick && tick.checked),
      at: new Date().toISOString(), page: String(location.href).split('#')[0], t: Date.now()
    };
  }
  document.addEventListener('submit', function (e) { record(e.target); }, true);
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button,input[type=submit]') : null;
    if (b && b.form && (b.type === 'submit' || !b.getAttribute('type'))) record(b.form);
  }, true);

  var origFetch = window.fetch;
  if (typeof origFetch === 'function') {
    window.fetch = function (input, init) {
      try {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (state && Date.now() - state.t < FRESH_MS && /lead-receive/.test(url) && method === 'POST' && init && typeof init.body === 'string') {
          var b = JSON.parse(init.body);
          if (b && typeof b === 'object' && !Array.isArray(b) && b.source === 'web' && !('marketing_optin' in b)) {
            b.marketing_optin = state.optin;
            b.consent_type = state.optin ? 'express' : 'implied';
            b.consent_at = state.at;
            b.consent_page = state.page;
            init = Object.assign({}, init, { body: JSON.stringify(b) });
          }
        }
      } catch (e) { /* never block a real submit over this */ }
      return origFetch.call(this, input, init);
    };
  }

  window.TurnerConsent = { scan: scan, isLeadForm: isLeadForm, text: { line: LINE_TEXT, optin: OPTIN_TEXT, alerts: ALERTS_TEXT, sender: SENDER }, last: function () { return state; } };

  function start() {
    injectStyles();
    scan(document);
    try {
      var pending = false;
      new MutationObserver(function (muts) {
        var seen = false;
        muts.forEach(function (m) { if (m.addedNodes && m.addedNodes.length) seen = true; });
        if (seen && !pending) { pending = true; (window.requestAnimationFrame || setTimeout)(function () { pending = false; scan(document); }); }
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) { /* no observer: forms present at load are still handled */ }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
