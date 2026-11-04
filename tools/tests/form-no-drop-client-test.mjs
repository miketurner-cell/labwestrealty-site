// form-no-drop-client-test.mjs -- D-1104-30: the website form scripts never silently drop a real person.
// Only the hidden field blocks; reviewFlags names what's odd, and lead-receive tells the agent (tested in Gander's STRICT 2263).
// Offline. Run: node tools/tests/form-no-drop-client-test.mjs   Exit 0 = all pass.
import { existsSync, readFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
let failed = 0;
const check = (label, cond) => { console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}`); if (!cond) failed++; };
const bt = readFileSync(path.join(root, 'js/boldtrail-forms.js'), 'utf8');
const i = bt.indexOf('function botCheck(formId, data)'), j = bt.indexOf('// Honeypot HTML snippet', i);
const end = j > 0 ? j : bt.indexOf('\n    }\n', bt.indexOf('function reviewFlags', i)) + 7;
const load = (secs) => new Function('secondsSinceLoad', bt.slice(i, end) + ';return { botCheck, reviewFlags };')(() => secs);
const B = load(20), F = load(0.5);
const p = (first_name, last_name, email = 'a@example.ca') => ({ first_name, last_name, email });
for (const [a, b, e, w] of [['J', 'Smith', undefined, 'short-name'], ['Mike', 'Root', undefined, 'odd-name'], ['Li', 'Na', undefined, 'odd-name'], ['Pat', 'Lee', 'test@example.ca', 'odd-email']]) {
  check(`${a} ${b}: not blocked, flagged ${w}`, B.botCheck('x', p(a, b, e)) === null && B.reviewFlags('x', p(a, b, e)).includes(w));
}
check('a fast submit is not blocked', F.botCheck('x', p('Mary', 'Smith')) === null && F.reviewFlags('x', p('Mary', 'Smith')).includes('submitted-fast'));
check('an ordinary person has no flags', B.reviewFlags('x', p('Mary', 'Smith')).length === 0);
check('the hidden field still blocks', B.botCheck('x', { ...p('Mary', 'Smith'), _hp_company: 'x' }) === 'bot-honeypot');
const sp = bt.slice(bt.indexOf('function safePostLead'), bt.indexOf('function safePostLead') + 900);
check('safePostLead never fakes success without posting', !/callback\(null\)/.test(sp) && /postLead\(data, callback\)/.test(sp));
check('postLead forwards website and review_flags', /payload\.website = data\.website/.test(bt) && /payload\.review_flags = data\.review_flags/.test(bt));
const fp = path.join(root, 'js/forms-v2.js');
if (existsSync(fp)) check('forms-v2: no path fakes success', !/if \(bot\)/.test(readFileSync(fp, 'utf8')));
if (failed) process.exit(1);
console.log('form-no-drop-client-test: all checks passed');
