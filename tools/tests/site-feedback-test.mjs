#!/usr/bin/env node
// site-feedback-test.mjs (STRICT, redesign 2026-10-09, Mike's D-1009-72 (2)) -- byte-identical on all five public sites.
//
// The consumer feedback button: js/site-feedback.js is a Tier-1 fleet canonical (fleet/canonical/js/site-feedback.js), loaded by
// js/nav.js. This pins (1) the file is the canonical one (sha256 below; a drift on any one site fails that site's CI), (2) nav.js
// carries the loader with a stamp equal to the file's sha256[:8] (the cache-bust), (3) the button only draws after the function's
// probe says enabled, (4) the plain-words copy Mike asked for, (5) no tracking: no cookies, no localStorage, no analytics, no
// beacon, no fingerprinting, (6) a11y basics (44 px targets, 16 px inputs, Escape closes, aria labels), (7) the reserved slot for
// the lead session's card. Offline. Exits 1 on failure.
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const js = fs.readFileSync(path.join(root, 'js', 'site-feedback.js'), 'utf8');
const nav = fs.readFileSync(path.join(root, 'js', 'nav.js'), 'utf8');
const SHA = '677a36643b6c047d4eb3922ec7f29426569d59617df8559fb19ae769c1c98f7d';
let fails = 0;
const check = (c, m) => { if (c) console.log('ok   ' + m); else { fails++; console.error('FAIL ' + m); } };

const sha = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'js', 'site-feedback.js'))).digest('hex');
check(sha === SHA, 'js/site-feedback.js is the fleet canonical (sha256 ' + SHA.slice(0, 8) + '; this copy is ' + sha.slice(0, 8) + ')');
const m = /var SITE_FEEDBACK_STAMP = '([0-9a-f]{8})';/.exec(nav);
check(!!m && m[1] === sha.slice(0, 8), 'js/nav.js SITE_FEEDBACK_STAMP equals sha256[:8] of js/site-feedback.js' + (m ? ' (nav has ' + m[1] + ', want ' + sha.slice(0, 8) + ')' : ' (stamp missing)'));
check(/function loadSiteFeedback\(\)/.test(nav) && /loadSiteFeedback\(\);\n  }/.test(nav), 'js/nav.js calls loadSiteFeedback() at the end of injectNav()');
check(/SITE\.siteFeedback === 'off'/.test(nav), 'a site can opt out with SITE.siteFeedback = off');

// switch: probe first, draw only on enabled:true
check(/\?probe=1/.test(js) && /j\.enabled === true/.test(js), 'draws only after GET ?probe=1 answers enabled:true');
check(/function mount\(\)/.test(js) && !/^\s*mount\(\);/m.test(js), 'mount() is called only from the probe path');
check(/\.catch\(function \(\) \{ \/\* leave the page exactly as it was \*\/ \}\)/.test(js), 'probe error leaves the page untouched');
check(/sessionStorage/.test(js) && /CACHE_MS = 10 \* 60 \* 1000/.test(js), 'probe answer cached per session for 10 minutes');
check(/credentials: 'omit'/.test(js) && (js.match(/credentials: 'omit'/g) || []).length === 2, 'probe and send both omit cookies');

// the words
for (const t of ['Tell us what would make this site better', 'Email, only if you\\u2019d like a reply',
  'We keep your note and the page you were on. No account, no tracking. If you leave an email we only use it to reply.',
  'Thanks — we read every note.', '>Send<', 'Feedback']) check(js.includes(t) || js.includes(t.replace(/\\u2019/g, '’')), 'copy present: ' + t);
check(/placeholder="Tell us what would make this site better"/.test(js), 'textarea placeholder is the asked-for line');

// what it sends
check(/page_path: location\.pathname/.test(js) && !/location\.(search|href|hash)/.test(js), 'sends the page PATH only (no query, no hash, no full URL)');
const code = js.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
check(!/document\.cookie|localStorage|indexedDB|sendBeacon|gtag\(|dataLayer|fbq\(|_paq|fingerprint|canvas\.toDataURL|getContext\(|navigator\.(userAgent|plugins|languages)|screen\.(width|height)|document\.referrer/.test(code), 'no cookies, localStorage, analytics, beacon, fingerprinting, referrer or UA reads');
check(/class="tsf-hp"/.test(js) && /name="website"/.test(js) && /tabindex="-1"/.test(js), 'honeypot field present, off-screen, out of tab order');

// reserved slot for lead's card
check(/data-feedback-followup hidden/.test(js) && /turner:feedback-sent/.test(js) && /looks_like_lead === true/.test(js), 'thank-you state reserves <div data-feedback-followup hidden> and fires turner:feedback-sent on looks_like_lead');

// a11y / layout
check(/min-height:44px/.test(js) && /width:44px;height:44px/.test(js), '44 px targets (tab, send, close)');
check(/font:16px/.test(js), 'inputs are 16 px (no iOS zoom)');
check(/e\.key === 'Escape'/.test(js) && /aria-label="Close feedback"/.test(js) && /role: 'dialog'/.test(js) && /'aria-labelledby'/.test(js), 'Escape closes; dialog + labelled close button');
check(/left:12px;bottom:16px/.test(js) && /56px \+ 12px \+ env\(safe-area-inset-bottom/.test(js), 'bottom-left; on phones sits above the 56 px Call/Text bar');
check(/@media\(max-width:767px\)\{\.tsf-tab\{left:18px;bottom:calc\(56px \+ 15px/.test(js) && /width:44px;height:44px/.test(js) && js.includes("'aria-label': 'Feedback'") && js.includes('tsf-lbl'), 'phones (<768 px): icon-only round 44x44 tab, level with the chat bubble, label kept for screen readers');
check(/z-index:9300/.test(js), 'sits at z 9300, under the chat bubble (z 9500, bottom-right)');
check(js.includes('agent|agent-sales|office|broker|app|client|deal|deals|login|auth'), 'skips the signed-in tool routes');

if (fails) { console.error('\n' + fails + ' check(s) failed'); process.exit(1); }
console.log('\nsite-feedback: all checks passed');
