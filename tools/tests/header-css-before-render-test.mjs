#!/usr/bin/env node
/**
 * header-css-before-render-test.mjs -- STRICT 2974 (sites, D-1112-08 Fix 1). Byte-identical on all five sites.
 * js/nav.js writes the header markup before css/header-v2.css arrives. Without a guard the header painted unstyled (~270px) on a
 * cold load and collapsed when the file landed, shifting the whole page (Playwright CLS 0.67 Goose Bay, 0.62 Gander). The guard:
 * while html.header-v2 lacks .h2-css, the two bars are hidden and held at their final height; .h2-css is added when the
 * stylesheet loads or fails, or after a timeout. Offline: reads js/nav.js and css/header-v2.css of THIS site.
 */
import { readFileSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => readFileSync(join(ROOT, rel), 'utf8');
let passes = 0; const FAIL = [];
function ok(c, label, d = '') { console.log(`[${c ? 'PASS' : 'FAIL'}] ${label}` + (!c && d ? ` - ${d}` : '')); if (c) passes++; else FAIL.push(label); }

const nav = read('js/nav.js');
const css = read('css/header-v2.css');
const fn = (nav.match(/function loadHeader2Css\(\) \{[\s\S]*?\n  \}\n/) || [''])[0];
ok(fn.length > 200, 'loadHeader2Css found');
ok(/var pre = 'html\.header-v2:not\(\.h2-css\) ';/.test(fn), 'the guard rules apply only while html.header-v2 lacks .h2-css');
ok(/\.nav-top-bar,' \+ pre \+ '\.nav-main-bar\{visibility:hidden;overflow:hidden/.test(fn), 'both bars are hidden until the stylesheet is in');
ok(/\.region-strip\{display:none\}/.test(fn), 'the region strip does not show unstyled');
const iCrit = fn.indexOf('document.head.appendChild(crit)'), iLink = fn.indexOf('document.head.appendChild(l)');
ok(iCrit > 0 && iLink > iCrit, 'the guard style is in the head before the stylesheet link');
ok(/l\.onload = l\.onerror = showHeader2;/.test(fn) && /classList\.add\('h2-css'\)/.test(fn), '.h2-css is added on the stylesheet load or error');
ok(/setTimeout\(showHeader2, \d{4}\)/.test(fn), 'a timeout shows the header even if neither event fires');
// held heights equal the real ones in header-v2.css
const topH = +(/--h2-top-h:\s*(\d+)px/.exec(css) || [])[1], mainH = +(/--h2-h:\s*(\d+)px/.exec(css) || [])[1];
const phoneMin = +(/max-width: 1023px\)[\s\S]*?\.nav-main-bar\.nav2 \{[^}]*min-height: (\d+)px/.exec(css) || [])[1];
ok(topH > 0 && new RegExp('\\.nav-top-bar\\{height:' + topH + 'px!important;min-height:0!important\\}').test(fn), 'held top-line height = --h2-top-h (' + topH + 'px), overriding any min-height');
ok(mainH > 0 && new RegExp('\\.nav-main-bar\\{height:' + mainH + 'px!important;min-height:0!important\\}').test(fn), 'held main-bar height = --h2-h (' + mainH + 'px), overriding any min-height');
ok(phoneMin > 0 && new RegExp('max-width:1023px\\)\\{.*\\.nav-main-bar\\{height:' + (phoneMin + 1) + 'px!important\\}').test(fn), 'held phone main-bar height = min-height + 1px border (' + (phoneMin + 1) + 'px)');
ok(/max-width:1023px\)\{' \+ pre \+ '\.nav-top-bar\{display:none\}/.test(fn), 'the top line is absent on phone, as in header-v2.css');
console.log(`\n${passes} passed, ${FAIL.length} failed`);
process.exit(FAIL.length ? 1 : 0);
