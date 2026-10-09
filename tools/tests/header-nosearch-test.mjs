#!/usr/bin/env node
/**
 * header-nosearch-test.mjs — the new header on the two sites with no listings (D-1009-10). Same file on Lab West and the hub.
 * Offline: reads js/nav-config.js of THIS site and checks
 *   - the switch is 'off' (Mike's GO flips it);
 *   - the header has no search bar and no search config (header2.bar === false; no header2.search; no SITE.search);
 *   - the four words and the one button are this site's own, every link (menu, items, More, the button) is a page that exists
 *     here (external links are other sites' pages and are skipped), and the button's target exists;
 *   - the phone is the brokerage line and the breakpoint stays 1024.
 * Run: node tools/tests/header-nosearch-test.mjs
 */
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
let passes = 0; const FAIL = [];
function ok(c, label, d = '') { console.log(`[${c ? 'PASS' : 'FAIL'}] ${label}` + (!c && d ? ` — ${d}` : '')); if (c) passes++; else FAIL.push(label); }

const fleet = JSON.parse(readFileSync(join(ROOT, 'tools', '_fleet_config.json'), 'utf8'));
const key = fleet.site_key;
const WANT = {
  labwest: { words: 'Why join|Get licensed|The market|About Turner', cta: 'Book a confidential call', ctaHref: 'become-a-realtor.html#confidential-inquiry', region: 'Labrador West &middot; recruiting' },
  hub: { words: 'Offices|Our team|Awards|Careers', cta: undefined, ctaHref: 'home-value.html', region: 'The brokerage' },
}[key];
ok(!!WANT, 'this test knows the site', String(key));

const win = {};
vm.runInNewContext(readFileSync(join(ROOT, 'js', 'nav-config.js'), 'utf8'), { window: win, document: { currentScript: null } });
const SITE = win.SITE || {};
const h2 = SITE.header2 || {};

ok(SITE.header === 'off', "the switch is 'off' (Mike's GO flips it)", String(SITE.header));
ok(h2.bar === false && h2.search === undefined && SITE.search === undefined, 'no search bar and no search config in the header');
ok((h2.menu || []).map((m) => m.label).join('|') === WANT.words, 'this site’s four words, in the drawn order', (h2.menu || []).map((m) => m.label).join('|'));
ok(h2.ctaHref === WANT.ctaHref, 'the one button goes to the drawn target', String(h2.ctaHref));
ok(h2.ctaLabel === WANT.cta, 'the one button’s words', String(h2.ctaLabel));
ok(h2.region === WANT.region, 'the top-line tag', String(h2.region));
ok(h2.signIn === false, 'no Sign in link (this site has no accounts)');
ok(SITE.phone === '709-256-7999' && SITE.phoneTel === '7092567999', 'the phone is the brokerage line');
ok(SITE.navBreakpoint === 1024, 'the breakpoint stays 1024');

const hrefs = [];
for (const m of h2.menu || []) { if (m.href) hrefs.push(m.href); for (const it of m.items || []) hrefs.push(it[1]); }
for (const it of h2.more || []) hrefs.push(it[1]);
hrefs.push(h2.ctaHref);
const local = hrefs.filter((h) => h && !/^(https?:|tel:|mailto:)/.test(h));
const dead = local.filter((h) => !existsSync(join(ROOT, h.split('#')[0].split('?')[0])));
ok(local.length >= 6 && !dead.length, `every local header link is a page on this site (${local.length} links)`, dead.join(', '));
ok(existsSync(join(ROOT, WANT.ctaHref.split('#')[0])), 'the button’s target page exists');
if (key === 'hub') {
  const hv = readFileSync(join(ROOT, 'home-value.html'), 'utf8');
  const targets = [...hv.matchAll(/class="ol-card"/g)].length;
  ok(targets === 3 && ['realestategander.com', 'avalonrealestate.ca', 'goosebayrealestate.ca'].every((d) => hv.includes(`https://${d}/pages/home-value.html`)),
    'home-value.html hands over to the three listing sites’ home-value pages');
}

console.log(`\n${passes} passed, ${FAIL.length} failed`);
if (FAIL.length) process.exit(1);
