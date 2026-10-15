#!/usr/bin/env node
// feedback-followup-test.mjs (STRICT, lead 2026-10-15, Mike's D-1009-72 (3) / D-1015-21) -- byte-identical on all five public sites.
//
// The "Talk to a local agent" card shown after consumer feedback that reads like a lead. js/feedback-followup.js is a Tier-1
// fleet canonical (fleet/canonical/js/feedback-followup.js), loaded by js/site-feedback.js only on looks_like_lead:true. This pins
// (1) the file is the canonical one (sha256 below) and site-feedback.js loads it with ?v= equal to its sha256[:8] (the cache-bust),
// inside the looks_like_lead branch only, (2) each site's contact page + phone (the CLAUDE.md per-site table), an unknown host gets
// no card, (3) feedback never becomes a lead: the card sends nothing (no fetch, XHR, beacon, form, storage, cookie, function call),
// (4) it renders into the slot already flagged before it loaded AND on later events, (5) 44 px targets and the plain copy.
// Offline. Exits 1 on failure.
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import vm from 'vm';
import { fileURLToPath } from 'url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const file = path.join(root, 'js', 'feedback-followup.js');
const js = fs.readFileSync(file, 'utf8');
const sf = fs.readFileSync(path.join(root, 'js', 'site-feedback.js'), 'utf8');
const SHA = '06d6fbfce2f17470c2ec011916dc1e1e808548a838d86448abf47c5e2407871c';
let fails = 0;
const check = (c, m) => { if (c) console.log('ok   ' + m); else { fails++; console.error('FAIL ' + m); } };

// (1) canonical + loader + stamp
const sha = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
check(sha === SHA, 'js/feedback-followup.js is the fleet canonical (sha256 ' + SHA.slice(0, 8) + '; this copy is ' + sha.slice(0, 8) + ')');
const hook = /\/js\/feedback-followup\.js\?v=([0-9a-f]{8})/.exec(sf);
check(!!hook && hook[1] === sha.slice(0, 8), 'site-feedback.js loads /js/feedback-followup.js?v=sha256[:8]' + (hook ? ' (has ' + hook[1] + ', want ' + sha.slice(0, 8) + ')' : ' (loader missing)'));
const branch = sf.slice(sf.indexOf('if (res.j.looks_like_lead === true) {'), sf.indexOf('card.querySelector(\'#tsf-thanks-h\').focus();'));
check(/feedback-followup\.js/.test(branch) && (sf.match(/feedback-followup\.js/g) || []).length === 2, 'the loader sits only inside the looks_like_lead === true branch (one script, loaded once)');

// (2) per-site contact page + phone
const want = {
  'realestategander.com': ['/pages/contact.html', '709-256-7999'],
  'goosebayrealestate.ca': ['/pages/contact.html', '709-896-5001'],
  'avalonrealestate.ca': ['/pages/contact.html', '709-725-6520'],
  'labwestrealty.com': ['/contact.html', '709-256-7999'],
  'royallepageturner.com': ['/contact.html', '709-256-7999'],
};

// A tiny DOM: enough for the card to render into a flagged slot.
function makeDom(hostname) {
  const listeners = {};
  const head = { children: [], appendChild(n) { this.children.push(n); } };
  const sent = [];
  function node(tag) {
    return {
      tagName: tag, attrs: {}, children: [], hidden: true, className: '', innerHTML: '', textContent: '', id: '',
      setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      appendChild(n) { this.children.push(n); }, querySelector(sel) { return sel === '.tff' ? (this.children.find((c) => c.className === 'tff') || null) : null; },
    };
  }
  const slot = node('div'); slot.setAttribute('data-feedback-followup', ''); slot.setAttribute('data-looks-like-lead', '1'); slot.hidden = false;
  const slots = [slot];
  const document = {
    head, createElement: node,
    getElementById: (id) => head.children.find((c) => c.id === id) || null,
    querySelectorAll: (sel) => (sel === '[data-feedback-followup][data-looks-like-lead="1"]' ? slots.filter((s) => s.getAttribute('data-looks-like-lead') === '1') : []),
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    dispatch: (t, detail) => (listeners[t] || []).forEach((f) => f({ detail })),
  };
  const trap = (name) => () => { sent.push(name); throw new Error(name + ' called'); };
  const window = {};
  const ctx = { window, document, location: { hostname }, fetch: trap('fetch'), XMLHttpRequest: trap('XMLHttpRequest'),
    navigator: { sendBeacon: trap('sendBeacon') } };
  return { ctx, slot, slots, node, sent, head };
}

for (const [host, [contact, phone]] of Object.entries(want)) {
  for (const h of [host, 'www.' + host]) {
    const d = makeDom(h);
    vm.runInNewContext(js, d.ctx);
    const box = d.slot.children.find((c) => c.className === 'tff');
    const html = box ? box.innerHTML : '';
    check(!!box && html.includes('href="' + contact + '"') && html.includes('href="tel:+1' + phone.replace(/\D/g, '') + '"') && html.includes('Call ' + phone),
      h + ': card links ' + contact + ' and tel ' + phone);
    if (h === host) {
      // (4) a slot flagged after load, via the event, also gets the card; an unflagged one does not.
      const late = d.node('div'); late.setAttribute('data-feedback-followup', ''); late.setAttribute('data-looks-like-lead', '1');
      d.ctx.document.dispatch('turner:feedback-sent', { looks_like_lead: true, slot: late });
      check(late.children.some((c) => c.className === 'tff') && late.hidden === false, h + ': renders on a later turner:feedback-sent event');
      const plain = d.node('div'); plain.setAttribute('data-feedback-followup', '');
      d.ctx.document.dispatch('turner:feedback-sent', { looks_like_lead: true, slot: plain });
      check(!plain.children.length, h + ': a slot not flagged looks-like-lead stays empty');
      d.ctx.document.dispatch('turner:feedback-sent', { looks_like_lead: true, slot: d.slot });
      check(d.slot.children.filter((c) => c.className === 'tff').length === 1, h + ': never renders the card twice');
      check(d.sent.length === 0, h + ': nothing sent (no fetch / XHR / beacon)');
    }
  }
}
for (const h of ['localhost', 'deploy-preview-1--chipper-kulfi-d3b59b.netlify.app', 'example.com']) {
  const d = makeDom(h);
  vm.runInNewContext(js, d.ctx);
  check(!d.slot.children.length, h + ': unknown host gets no card (never another site\'s phone)');
}

// (3) never a lead: static scan for any sending or storing path
check(!/\bfetch\s*\(|XMLHttpRequest|sendBeacon|\.submit\s*\(|<form|localStorage|sessionStorage|document\.cookie|\.netlify\/functions|lead-receive|phone_leads|followupboss/i.test(js.replace(/^\s*(\/\/|\*|\/\*).*$/gm, '')),
  'the card sends and stores nothing (no fetch, XHR, beacon, form, storage, cookie, function call)');
check(!/\bgtag\s*\(|dataLayer|fbq\s*\(/.test(js), 'no analytics events');

// (5) copy and targets
check(js.includes('Looking to buy or sell?') && js.includes('Talk to a local agent.') && js.includes('Send us a message'), 'copy: "Looking to buy or sell?" / "Talk to a local agent." / "Send us a message"');
check(/\.tff a\{[^}]*min-height:44px/.test(js), '44 px tap targets');

console.log(fails ? '\nfeedback-followup: ' + fails + ' FAILED' : '\nfeedback-followup: all checks passed');
process.exit(fails ? 1 : 0);
