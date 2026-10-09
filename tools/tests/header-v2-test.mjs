#!/usr/bin/env node
/**
 * header-v2-test.mjs — One header, everywhere (redesign, Mike's D-1008-86). Same file on every site that carries it.
 * Offline, no browser: reads js/nav.js, js/nav-config.js and css/header-v2.css of THIS site and checks
 *   - the switch: off unless nav-config says header: 'v2' (or ?header=v2 previews; ?header=v1 forces the old header), and a
 *     site without header2.menu keeps the old header whatever the switch says;
 *   - the CSS is loaded only by nav.js while the header is on, and every rule is scoped to html.header-v2 (so with the switch
 *     off nothing on the page changes);
 *   - every link in the site's header2 (menu items, More) is a page that exists in this repo (no dead links in the header);
 *   - the menu breakpoint is per-site config, default 1023;
 *   - the desktop More menu (button, aria-expanded/-controls, Escape, arrows), the official Royal LePage lockup in the header, and
 *     header-v2.css's content-hash stamp in nav-config (D-1009-55/-56).
 * Run: node tools/tests/header-v2-test.mjs
 */
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { createHash } from 'node:crypto';

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
// the switch: 'off' (or unset), or 'v2' only with a full header2 (Mike switched Gander, Avalon and Goose Bay on, D-1008-103)
ok(SITE.header === undefined || SITE.header === 'off' || (SITE.header === 'v2' && SITE.header2 && Array.isArray(SITE.header2.menu) && SITE.header2.menu.length === 4),
  "the header switch is 'off', or 'v2' with the four words configured", String(SITE.header));
const h2 = SITE.header2;
if (h2) {
  const hrefs = [];
  for (const m of h2.menu || []) { if (m.href) hrefs.push(m.href); for (const it of m.items || []) hrefs.push(it[1]); }
  for (const it of h2.more || []) hrefs.push(it[1]);
  if (h2.ctaHref) hrefs.push(h2.ctaHref);   // the one button's target (a #fragment is stripped below)
  const dead = hrefs.filter((h) => {
    if (/^(https?:|tel:|mailto:)/.test(h)) return false;
    const p = h.split('#')[0].split('?')[0];
    const f = p.endsWith('/') ? join(ROOT, p, 'index.html') : join(ROOT, p);
    return !existsSync(f);
  });
  ok(hrefs.length >= 6 && !dead.length, `every header link is a page on this site (${hrefs.length} links)`, dead.join(', '));
  // the drawn words: the three listing sites share one set; Lab West and the hub (D-1009-10) have their own
  const DRAWN = ['Buy|Sell|Sold prices|Communities', 'Why join|Get licensed|The market|About Turner', 'Offices|Our team|Awards|Careers'];
  ok(DRAWN.includes((h2.menu || []).map((m) => m.label).join('|')), 'the four words, in the drawn order');
} else {
  ok(true, 'no header2 on this site yet: the old header stays (its words need Mike’s word first)');
}

// ---- the desktop "More" menu, the Royal LePage logo and the CSS stamp (redesign, D-1009-55 / D-1009-56) ----
// More: one button (aria-expanded, aria-controls -> the panel), the panel's links are the config's header2.more plus the other regions
ok(/<button class="nav2-more-btn" type="button" aria-expanded="false" aria-controls="nav2-more-panel">More<\/button>/.test(nav)
  && /<div class="nav2-more-panel" id="nav2-more-panel">/.test(nav), 'a "More" button with aria-expanded and aria-controls over its panel of links');
ok(/Array\.isArray\(H2\.more\) \? H2\.more\.slice\(\)/.test(nav) && /liveRegions\(\)\.forEach/.test(nav), 'the More links are header2.more plus the other regions and partner brokerages, no words added in nav.js');
ok(/k === 'Escape'/.test(nav) && /setOpen\(false\); btn\.focus\(\);/.test(nav) && /k === 'ArrowDown'/.test(nav) && /k === 'ArrowUp'/.test(nav) && /'focusout'/.test(nav),
  'More: Escape closes and returns focus to the button, arrows move, focus leaving closes it');
ok(/setAttribute\('aria-expanded', o \? 'true' : 'false'\)/.test(nav), 'More: aria-expanded follows the open state');
const navLinksOrder = /'<ul class="nav-main-links nav2-links">' \+ H2\.menu\.map\(menuItem\)\.join\(''\) \+ more2HTML\(\)/.test(nav);
ok(navLinksOrder, 'More comes last, after the four words');
ok(/\.nav2-more-btn \{[^}]*\}/.test(css) && /\.nav2-more\.open > \.nav2-more-panel \{ display: block; \}/.test(css) && /\.nav2-more-panel \{ display: none; position: absolute; top: 100%;/.test(css)
  && /@media \(max-width: 1023px\)[\s\S]*\.nav2-more-btn \{ display: none; \}/.test(css), 'More: styled like the dropdowns on desktop; on the phone sheet the button is hidden and the links show');
const moreCfg = (SITE.header2 && SITE.header2.more) || [];
ok(!SITE.header2 || moreCfg.length >= 2, `header2.more holds the links the desktop More shows (${moreCfg.length})`);
// logo: the official lockup, whole, alt "Royal LePage", 44px tall in the header; the file is the one Mike added 2026-06-24 (sha256 below)
ok(/class="nav2-logo" src="' \+ escAttrNav\(logoSrc\) \+ '" alt="Royal LePage" width="87" height="44"/.test(nav) && /r \+ 'images\/rlp-turner-lockup\.png'/.test(nav), 'the header carries the official lockup image, alt "Royal LePage", 87x44');
ok(/\.nav2-logo \{[^}]*height: 44px;/.test(css), 'the logo is 44px tall (its mark is 25px: not under 24px)');
const lock = join(ROOT, 'images', 'rlp-turner-lockup.png');
if (existsSync(lock)) {
  const buf = readFileSync(lock);
  const isPng = buf.slice(0, 8).toString('hex') === '89504e470d0a1a0a', w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  const sha = createHash('sha256').update(buf).digest('hex');
  ok(isPng && w === 1280 && h === 647 && w >= 2 * 87 && h >= 2 * 44, `the logo file is a ${w}x${h} PNG, at least 2x its 87x44 box`);
  ok(sha === '8e87ca19f481159663d5d2f85152f7a6d3561d20262a6d71c486b1eef960e3ee', 'the logo file is the official lockup, byte for byte (never edited or cropped)', sha);
} else ok(false, 'images/rlp-turner-lockup.png exists');
// the CSS stamp: the content hash, kept in nav-config (nav.js reads it), never a fixed date
const cssHash = createHash('sha256').update(readFileSync(join(ROOT, 'css', 'header-v2.css'))).digest('hex').slice(0, 8);
ok(SITE.header2Stamp === cssHash, `nav-config's header2Stamp is the sha256[:8] of css/header-v2.css (${cssHash})`, `it reads ${SITE.header2Stamp}; set header2Stamp: '${cssHash}'`);
ok(/function header2Stamp\(\)/.test(nav) && /\+ \(header2Stamp\(\) \? '\?v=' \+ header2Stamp\(\) : ''\)/.test(nav) && !/20261008-header-v2/.test(nav), 'nav.js loads header-v2.css with that stamp, not a fixed date');

console.log(`\n${passes} passed, ${FAIL.length} failed`);
if (FAIL.length) process.exit(1);
