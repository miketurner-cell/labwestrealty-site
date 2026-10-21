/**
 * labwest-chat-test.mjs -- STRICT offline checks for netlify/functions/chat.ts and js/chat-widget.js on Lab West
 * (sites, D-1012-34, component 9).
 *
 * Pins: dark (no bundled listings data -> 404 for GET, POST, OPTIONS, any origin, nothing else runs); with data present a foreign
 * or missing Origin is refused (403) and only this site's hosts are allowed; no Anthropic/Supabase call is made by any of these
 * requests (fetch is stubbed to fail the test); the function and widget carry Lab West text only (Mike Turner as the one contact,
 * no Goose Bay agents or office, no street address, no Listing Email Alerts promise while the alerts backend is not ready); the
 * config (netlify.toml bundle, state-script rewrite) is in place and the committed _redirects does not route /api/chat while off.
 * Run from the repo root: node tools/tests/labwest-chat-test.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require_ = createRequire(import.meta.url);
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FAILURES = [];
function check(label, cond, detail = '') {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${label}` + (!cond && detail ? ` -- ${detail}` : ''));
  if (!cond) FAILURES.push(label);
}

let outbound = [];
globalThis.fetch = async (url) => { outbound.push(String(url)); return new Response('{}', { status: 500 }); };

const tmp = mkdtempSync(join(tmpdir(), 'lw-chat-'));
const out = join(tmp, 'chat.cjs');
execFileSync('npx', ['--yes', 'esbuild@0.23.1', join(ROOT, 'netlify', 'functions', 'chat.ts'), '--bundle',
  '--platform=node', '--target=node18', '--format=cjs', '--external:@netlify/functions', `--outfile=${out}`], { stdio: ['ignore', 'ignore', 'pipe'] });
const FN = require_(out);
const call = (method, origin, body) => FN.handler({ httpMethod: method, headers: origin ? { origin } : {}, body: body ? JSON.stringify(body) : '' });

// ---- dark: an empty working directory, as on the live site while the switch is off
const empty = join(tmp, 'empty'); mkdirSync(empty); process.chdir(empty);
for (const [m, o] of [['GET', 'https://labwestrealty.com'], ['POST', 'https://labwestrealty.com'], ['OPTIONS', 'https://labwestrealty.com'], ['POST', 'https://evil.example'], ['POST', null]]) {
  const r = await call(m, o, { messages: [{ role: 'user', content: 'hi' }] });
  check(`dark: ${m} from ${o || 'no origin'} -> 404 not_found`, r.statusCode === 404 && JSON.parse(r.body).error === 'not_found', String(r.statusCode));
}
check('dark: nothing was called out', outbound.length === 0, outbound.join(','));

// ---- with data bundled
const data = join(tmp, 'data'); mkdirSync(join(data, 'tools/idx-cache'), { recursive: true }); mkdirSync(join(data, 'listings/sold'), { recursive: true });
writeFileSync(join(data, 'tools/idx-cache/listings-projected.json'), JSON.stringify({ listings: [{ mls: '1', street: '1 Test St', city_raw: 'Labrador City', list_price: 100000, status: 'Active', url_path: '/listings/labrador-city/x.html' }] }));
writeFileSync(join(data, 'listings/sold/data.json'), JSON.stringify({ rows: [] }));
process.chdir(data);
let r = await call('GET', 'https://labwestrealty.com');
check('with data: GET answers ok', r.statusCode === 200 && JSON.parse(r.body).fn === 'chat');
check('CORS header names Lab West only', r.headers['Access-Control-Allow-Origin'] === 'https://labwestrealty.com');
for (const o of ['https://goosebayrealestate.ca', 'https://realestategander.com', 'https://evil.example', null]) {
  r = await call('POST', o, { messages: [{ role: 'user', content: 'hi' }] });
  check(`with data: POST from ${o || 'no origin'} -> 403`, r.statusCode === 403, String(r.statusCode));
}
for (const o of ['https://labwestrealty.com', 'https://www.labwestrealty.com', 'https://deploy-preview-12--labwestrealty.netlify.app']) {
  r = await call('POST', o, { messages: [] });
  check(`with data: POST from ${o} passes the origin check`, r.statusCode !== 403, String(r.statusCode));
}
check('no outbound call from the refused or empty requests', outbound.every((u) => !/anthropic|supabase/i.test(u)) , outbound.join(','));

// ---- text
process.chdir(ROOT);
const src = readFileSync('netlify/functions/chat.ts', 'utf8');
const widget = readFileSync('js/chat-widget.js', 'utf8');
check('SITE is labwestrealty.com', /const SITE = "https:\/\/labwestrealty\.com";/.test(src));
const agentsBlock = src.slice(src.indexOf('const AGENTS = ['), src.indexOf('// ── System prompt'));
check('exactly one contact: Mike Turner', /name: "Mike Turner"/.test(agentsBlock) && (agentsBlock.match(/name: "/g) || []).length === 1);
check('no Karen / Roberta / Dynamic Duo as a Lab West contact', !/karen pomeroy|roberta primmer|karenpomeroy|robertaprimmer|709-899-1778|709-896-7509/i.test(src + widget));
const prompt = src.slice(src.indexOf('const SYSTEM_PROMPT'), src.indexOf('// ── Tool definitions'));
check('prompt: no street address, no Hamilton River, no Goose Bay office', !/hamilton|loring|airport b|suite 102|371 /i.test(prompt));
check('prompt: no Listing Email Alerts promise while the alerts backend is not ready', !/listing email alerts/i.test(prompt));
check('prompt: Mike Turner, 709-256-7999, consent question names Mike', /Mike Turner/.test(prompt) && /709-256-7999/.test(prompt) && /Is it OK to have Mike Turner contact you/.test(prompt));
check('prompt: individual sold prices stay private', /NEVER a sold price of any kind/.test(prompt));
check('widget: Lab West contact only', /709-256-7999/.test(widget) && !/709-896|goosebay@|Goose Bay/i.test(widget));
check('origin allow-list is Lab West only', /ALLOWED_ORIGIN_HOSTS = \["labwestrealty\.com", "www\.labwestrealty\.com", "labwestrealty\.netlify\.app"\]/.test(src) && !/goosebay-turner-realty/.test(src));
const hIdx = src.indexOf('export const handler = async (event: any) => {');
const gIdx = src.indexOf('if (!(await readActiveBundle()))', hIdx);
check('the dark guard is the first statement of the handler', hIdx > 0 && gIdx > hIdx && !/\n\s*const headers = \{/.test(src.slice(hIdx, gIdx)) && !/event\.httpMethod/.test(src.slice(hIdx, gIdx)));
const toml = readFileSync('netlify.toml', 'utf8');
check('netlify.toml bundles listings and sold data into chat', /\[functions\.chat\][\s\S]*listings\/sold\/data\.json[\s\S]*listings-projected\.json/.test(toml));
const st = readFileSync('tools/labwest-listings-state.py', 'utf8');
check('state script routes /api/chat to the function', /\/api\/chat\s+\/\.netlify\/functions\/chat\s+200/.test(st));
check('the committed _redirects does not route /api/chat while off', !/api\/chat/.test(readFileSync('_redirects', 'utf8')));

if (FAILURES.length) { console.log(`\n${FAILURES.length} FAILED`); process.exit(1); }
console.log('\nlabwest-chat-test: all checks passed');
