#!/usr/bin/env node
// feedback-tab-clearance-test.mjs (STRICT, provincial 2026-11-20, Mike's D-1120-53 (2)) -- same file in the hub and Avalon.
// On phones the round Feedback tab (.tsf-tab, fixed at bottom 56+15 px, 44 px high) used to sit on top of page content at the bottom
// of the page. js/site-feedback.js now adds class tsf-pad to <body> when the tab mounts and its own injected <style> reserves room
// (below 768 px only). This pins: the rule exists in the <768px block, it is scoped to body.tsf-pad (so nothing changes while the tab
// is not drawn), the class is added only inside mount() (probe-gated), it clears the tab (>= 56+15+44), and the file is the shared
// copy (md5 below; the hub and Avalon copies must stay byte-identical, always-on #27). Offline. Exits 1 on failure.
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const MD5 = 'f52ce2dab60b0273f9f6ddecd2f8881b';
let fails = 0;
const check = (c, m) => { if (c) console.log('ok   ' + m); else { fails++; console.error('FAIL ' + m); } };
const buf = fs.readFileSync(path.join(root, 'js', 'site-feedback.js'));
const js = buf.toString('utf8');
const md5 = crypto.createHash('md5').update(buf).digest('hex');
check(md5 === MD5, 'js/site-feedback.js is the shared copy (md5 ' + MD5.slice(0, 8) + '; this copy is ' + md5.slice(0, 8) + ')');
const media = /@media\(max-width:767px\)\{([\s\S]*?)\}\}' \+/.exec(js);
check(!!media, 'the <768px media block is present');
const rule = media && /'html body\.tsf-pad,html body\.tsf-pad\.mab-active\{padding-bottom:calc\((\d+)px \+ env\(safe-area-inset-bottom,0px\)\) !important;\}/.exec(media[0]);
check(!!rule, 'the clearance rule sits inside the <768px block and is scoped to body.tsf-pad (also over the action bar\'s body.mab-active padding)');
check(!!rule && Number(rule[1]) >= 56 + 15 + 44, 'it reserves at least tab bottom + height (56+15+44 px)' + (rule ? ' (' + rule[1] + ' px)' : ''));
check(!/^[^\n]*body\.tsf-pad[^\n]*\{[^}]*\}[^\n]*$/m.test(js.split("@media(max-width:767px)")[0]), 'no tsf-pad rule applies outside the <768px block (desktop unchanged)');
const mount = /function mount\(\) \{[\s\S]*?\n  \}\n/.exec(js);
check(!!mount && /matchMedia\('\(max-width:767px\)'\)\.matches && parseFloat\(getComputedStyle\(document\.body\)\.paddingBottom\) < 127\) document\.body\.classList\.add\('tsf-pad'\)/.test(mount[0]), 'tsf-pad is added inside mount(), on phones, only when the page pads less than 127 px (a page that pads more keeps its own)');
check((js.match(/classList\.add\('tsf-pad'\)/g) || []).length === 1, 'tsf-pad is added in exactly one place');
check(/\?probe=1/.test(js) && /j\.enabled === true/.test(js) && /if \(on\) mount\(\)/.test(js), 'mount() is still reached only after the probe says enabled');
check(/\.tsf-tab\{left:18px;bottom:calc\(56px \+ 15px \+ env\(safe-area-inset-bottom,0px\)\);width:44px;height:44px/.test(js), 'the tab itself did not move');
if (fails) { console.error('\n' + fails + ' check(s) failed'); process.exit(1); }
console.log('\nfeedback-tab-clearance: all checks passed');
