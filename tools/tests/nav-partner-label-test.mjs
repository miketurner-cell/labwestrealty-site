#!/usr/bin/env node
// nav-partner-label-test.mjs (STRICT, D-1009-17, 2026-10-09)
// Grand Falls and Corner Brook are independent Royal LePage brokerages
// (tools/regions.json operator:"peer"). Every header region strip and the
// phone "More" menu label them "Partner Brokerage", the hub region grid's
// own badge wording. Reads js/nav.js (Tier-1, byte-identical on all five
// sites) and runs its real label helpers. Offline. Exits 1 on failure.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(root, 'js', 'nav.js'), 'utf8');
let fails = 0;
const check = (c, m) => { if (c) { console.log('ok   ' + m); } else { fails++; console.error('FAIL ' + m); } };

const a = src.indexOf("  var PEER_BADGE = 'Partner Brokerage';");
const b = src.indexOf('  function regionLinkTitle(r)', a);
const c = src.indexOf('\n  }\n', b) + 4;
check(a > 0 && b > a && c > b, 'PEER_BADGE + regionLinkText/regionLinkTitle present in js/nav.js');
const h = new Function(src.slice(a, c) + '\nreturn { text: regionLinkText, title: regionLinkTitle };')();
check(h.text({ label: 'Grand Falls', peer: true }) === 'Grand Falls &middot; Partner Brokerage', 'peer link reads "Grand Falls · Partner Brokerage"');
check(h.text({ label: 'Corner Brook', peer: true }) === 'Corner Brook &middot; Partner Brokerage', 'peer link reads "Corner Brook · Partner Brokerage"');
check(h.text({ label: 'Avalon', peer: false }) === 'Avalon', 'Turner regions are unlabelled');
check(/independent Royal LePage brokerage/.test(h.title({ peer: true })), 'peer link title says independent Royal LePage brokerage');

// Both surfaces use the helper, and both region sources carry the flag.
check(/'>' \+ regionLinkText\(r\) \+ '<\/a>'/.test(src), 'region strip (header) uses regionLinkText');
check(/items\.push\(\[regionLinkText\(rg\), rg\.url\]\)/.test(src), 'phone/More menu (header v2) uses regionLinkText');
check(/peer: reg\[k\]\.operator === 'peer'/.test(src), 'liveRegions() carries operator "peer" from regions-data.js');
check((src.match(/url: 'https:\/\/(generationrealty|royallepagenlrealty)\.ca\/', peer: true \}/g) || []).length === 2, 'fallback region list marks both partner brokerages');

// The registry agrees: the two are the only "peer" regions.
const reg = fs.readFileSync(path.join(root, 'js', 'regions-data.js'), 'utf8');
const peers = (reg.match(/"operator":\s*"peer"/g) || []).length;
check(peers === 2, 'js/regions-data.js has exactly 2 operator "peer" regions (found ' + peers + ')');

if (fails) { console.error(fails + ' failure(s)'); process.exit(1); }
console.log('nav-partner-label: all checks passed');
