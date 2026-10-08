#!/usr/bin/env node
/**
 * header-v2-test.mjs — One header, everywhere (redesign, Mike's D-1008-86). Same file on every site that carries it.
 * Offline, no browser: reads js/nav.js, js/nav-config.js and css/header-v2.css of THIS site and checks
 *   - the switch: off unless nav-config says header: 'v2' (or ?header=v2 previews; ?header=v1 forces the old header), and a
 *     site without header2.menu keeps the old header whatever the switch says;
 *   - the CSS is loaded only by nav.js while the header is on, and every rule is scoped to html.header-v2 (so with the switch
 *     off nothing on the page changes);
 *   - every link in the site's header2 (menu items, More) is a page that exists in this repo (no dead links in the header);
 *   - the menu breakpoint is per-site config, default 1023.
 * Run: node tools/tests/header-v2-test.mjs
 */
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => readFileSync(join(ROOT, rel), 'utf8');
let passes = 0; const FAIL = [];
function ok(c, label, d = '') { console.log(`[${c ? 'PASS' : 'FAIL'}] ${label}` + (!c && d ? ` — ${d}` : '')); if (c) passes++; else FAIL.push(label); }

const nav = read('js/nav.js');
ok(/var H2 = \(SITE\.header2 && typeof SITE\.header2 === 'object'\) \? SITE\.header2 : null;/.test(nav), 'nav.js reads header2 from the site config');
ok(/if \(!H2 \|\| !Array\.isArray\(H2\.menu\) \|\| !H2\.menu\.length\) return false;/.test(nav), 'no header2.menu: the old header, whatever the switch says');
ok(/return SITE\.header === 'v2' \|\| \/\[\?&\]header=v2\(&\|\$\)\/\.test\(q\);/.test(nav) && /\[\?&\]header=v1\(&\|\$\)/.test(nav), "on only at header: 'v2' or ?header=v2; ?header=v1 forces the old one");
ok(/if \(v2\) \{ loadHeader2Css\(\);/.test(nav) && (nav.match(/loadHeader2Css\(\)/g) || []).length === 2, 'the CSS is loaded by nav.js only when the header is on');
ok(/topBar\.innerHTML = v2 \? top2HTML\(\) : topBarHTML\(\);/.test(nav) && /mainBar\.innerHTML = v2 \? navMain2HTML\(sCfg\) : navMainHTML;/.test(nav), 'the old top bar and main bar render unchanged when off');
ok(/var NAV_BP = \(typeof SITE\.navBreakpoint === 'number' && SITE\.navBreakpoint > 0\) \? SITE\.navBreakpoint : 1023;/.test(nav) && !/innerWidth <= 102[34]\b/.test(nav), 'the menu breakpoint is per-site config, default 1023');
ok(/Get my home&rsquo;s value/.test(nav) && /nav2-cta/.test(nav) && !/Free Evaluation[^']*nav2/.test(nav), 'one CTA in the new header: "Get my home’s value"');

// every rule in header-v2.css is scoped (html.header-v2 …), apart from the verbatim search-sheet section, whose classes only
// exist on a page where nav.js built the sheet
const css = read('css/header-v2.css').replace(/\/\*[\s\S]*?\*\//g, '');
const scopedPart = read('css/header-v2.css').split('/* ---- the search sheet')[0].replace(/\/\*[\s\S]*?\*\//g, '');
const selectors = [];
scopedPart.replace(/([^{}]+)\{/g, (_, sel) => { sel = sel.trim(); if (sel && !sel.startsWith('@')) selectors.push(...sel.split(',').map((s) => s.trim())); return ''; });
const unscoped = selectors.filter((s) => !s.startsWith('html.header-v2'));
ok(selectors.length > 40 && !unscoped.length, 'every header rule is scoped to html.header-v2', unscoped.slice(0, 4).join(' | '));
ok(/--h2-bg:/.test(css) && /--h2-pad:/.test(css), 'colours and spacing are custom properties (a light theme is a second set, D-1008-88)');

// the site's own config: off, and every link real
const cfgSrc = read('js/nav-config.js');
const win = {};
vm.runInNewContext(cfgSrc, { window: win, document: { currentScript: null } });
const SITE = win.SITE || {};
ok(SITE.header !== 'v2', "this site's header switch is not on (Mike's GO flips it)", String(SITE.header));
const h2 = SITE.header2;
if (h2) {
  const hrefs = [];
  for (const m of h2.menu || []) { if (m.href) hrefs.push(m.href); for (const it of m.items || []) hrefs.push(it[1]); }
  for (const it of h2.more || []) hrefs.push(it[1]);
  const dead = hrefs.filter((h) => {
    if (/^(https?:|tel:|mailto:)/.test(h)) return false;
    const p = h.split('#')[0].split('?')[0];
    const f = p.endsWith('/') ? join(ROOT, p, 'index.html') : join(ROOT, p);
    return !existsSync(f);
  });
  ok(hrefs.length >= 8 && !dead.length, `every header link is a page on this site (${hrefs.length} links)`, dead.join(', '));
  ok((h2.menu || []).map((m) => m.label).join('|') === 'Buy|Sell|Sold prices|Communities', 'the four words, in the drawn order');
} else {
  ok(true, 'no header2 on this site yet: the old header stays (its words need Mike’s word first)');
}

console.log(`\n${passes} passed, ${FAIL.length} failed`);
if (FAIL.length) process.exit(1);
