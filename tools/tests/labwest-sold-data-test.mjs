/**
 * labwest-sold-data-test.mjs -- STRICT offline checks for netlify/functions/sold-data.ts on Lab West
 * (sites, D-1012-34, component 5). Adapted from Goose Bay's sold-data harness, which reads committed data files;
 * Lab West has none while the switch is off, so this builds a temp tree with fixture files.
 *
 * Pins: dark guard (no sold data bundled -> 404 for everyone, even signed in); then, with data: no / bad token -> 401
 * sign_in_required with rows: [] and none of the data; valid token -> the exact file, private + no-store; only the three
 * allowed shapes resolve (no path traversal); a signed-out ?mls= request returns one row with no price key; the per-user
 * rate limit answers 429; netlify.toml bundles the files; the state script carries the three forced rewrites.
 * Run from the repo root: node tools/tests/labwest-sold-data-test.mjs
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

globalThis.fetch = async (url, opts = {}) => {
  const tok = String(opts.headers?.Authorization || '').replace(/^Bearer /, '');
  if (String(url).endsWith('/auth/v1/user')) {
    return tok === 'good' ? new Response(JSON.stringify({ id: 'u-1', email: 'r@x.test' }), { status: 200 }) : new Response('{}', { status: 401 });
  }
  return new Response('unexpected', { status: 599 });
};
process.env.SOLD_DATA_RATE_MAX = '5';
process.env.SOLD_DATA_ANON_MAX = '4';

const tmp = mkdtempSync(join(tmpdir(), 'lw-sold-data-'));
const out = join(tmp, 'sold-data.cjs');
execFileSync('npx', ['--yes', 'esbuild@0.23.1', join(ROOT, 'netlify', 'functions', 'sold-data.ts'), '--bundle',
  '--platform=node', '--target=node18', '--format=cjs', '--external:@netlify/functions', `--outfile=${out}`], { stdio: ['ignore', 'ignore', 'pipe'] });
const FN = require_(out);
const call = (q, token, path = '/.netlify/functions/sold-data') => FN.handler({ httpMethod: 'GET', queryStringParameters: q,
  path, rawUrl: `https://example.test${path}`, headers: token ? { authorization: `Bearer ${token}` } : {} });

// ---- dark: an empty working directory, as on the live site while the switch is off
const empty = join(tmp, 'empty'); mkdirSync(empty);
process.chdir(empty);
for (const [label, tok] of [['signed out', null], ['signed in', 'good']]) {
  const r = await call({ f: 'data.json' }, tok, '/listings/sold/data.json');
  check(`dark (no sold data): ${label} -> 404 not_found`, r.statusCode === 404 && JSON.parse(r.body).error === 'not_found', String(r.statusCode));
}

// ---- with data
const data = join(tmp, 'data'); mkdirSync(join(data, 'listings/sold/labrador-city'), { recursive: true }); mkdirSync(join(data, 'listings/sold/detail'), { recursive: true });
const hub = JSON.stringify({ rows: [{ mls: '1290001', city_slug: 'labrador-city', street: '1 Test St', list_price: 100000 }] });
const shard = JSON.stringify({ rows: [{ mls: '1290001', street: '1 Test St', close_price: 99999, sa_ratio: 0.99 }] });
writeFileSync(join(data, 'listings/sold/data.json'), hub);
writeFileSync(join(data, 'listings/sold/labrador-city/data.json'), hub);
writeFileSync(join(data, 'listings/sold/detail/1290.json'), shard);
process.chdir(data);

let r = await call({}, null, '/listings/sold/data.json');
check('signed out -> 401 sign_in_required with rows: []', r.statusCode === 401 && JSON.parse(r.body).error === 'sign_in_required' && JSON.parse(r.body).rows.length === 0);
check('signed out -> none of the data', !r.body.includes('"mls"'));
r = await call({}, 'forged', '/listings/sold/data.json');
check('bad token -> 401', r.statusCode === 401);
r = await call({}, 'good', '/listings/sold/data.json');
check('signed in -> the exact file, private, no-store, noindex', r.statusCode === 200 && r.body === hub && r.headers['Cache-Control'] === 'private, no-store' && r.headers['X-Robots-Tag'] === 'noindex');
r = await call({}, 'good', '/listings/sold/labrador-city/data.json');
check('town file served when signed in', r.statusCode === 200 && r.body === hub);
for (const q of [{ town: '../../netlify' }, { shard: '../../_redirects' }, { f: 'secrets.json' }, {}]) {
  const x = await call(q, 'good');
  check(`rejects ${JSON.stringify(q)}`, x.statusCode === 404 && !x.body.includes('netlify'));
}
check('resolvePath allows the three shapes only', FN.resolvePath('/listings/sold/labrador-city/data.json') === 'listings/sold/labrador-city/data.json'
  && FN.resolvePath('/listings/sold/detail/1290.json') === 'listings/sold/detail/1290.json' && FN.resolvePath('/listings/sold/data.json') === 'listings/sold/data.json'
  && FN.resolvePath('/listings/sold/../x') === null && FN.resolvePath('/etc/passwd') === null);

// signed-out single row: one row, never a price-like key; the bulk stays sign-in only
const anon = (path, ip) => FN.handler({ httpMethod: 'GET', queryStringParameters: {}, path: path.split('?')[0],
  rawUrl: `https://example.test${path}`, headers: { 'x-nf-client-connection-ip': ip } });
let a = await anon('/listings/sold/detail/1290.json?mls=1290001', '10.0.0.1');
const ab = JSON.parse(a.body);
check('signed out + ?mls= on its shard -> exactly that row', a.statusCode === 200 && ab.rows.length === 1 && ab.rows[0].mls === '1290001');
check('the single row carries no price-like key', !Object.keys(ab.rows[0]).some((k) => /close|sold_price|sale_price|sa_ratio|sale_to_list|sp_lp/i.test(k)) && !a.body.includes('99999'));
a = await anon('/listings/sold/detail/1290.json', '10.0.0.1');
check('signed out shard without ?mls= -> 401 (bulk stays sign-in only)', a.statusCode === 401 && !a.body.includes('"mls"'));
a = await anon('/listings/sold/labrador-city/data.json?mls=1290001', '10.0.0.1');
check('signed out town file + ?mls= -> 401', a.statusCode === 401);
process.env.VOW_SOLD_GATE = 'on';
a = await anon('/listings/sold/detail/1290.json?mls=1290001', '10.0.0.3');
check('VOW_SOLD_GATE=on closes the signed-out path -> 401', a.statusCode === 401);
delete process.env.VOW_SOLD_GATE;
let last;
for (let i = 0; i < 6; i++) last = await anon('/listings/sold/detail/1290.json?mls=1290001', '10.0.0.9');
check('signed-out single reads -> 429 after the per-IP cap', last.statusCode === 429);
for (let i = 0; i < 8; i++) last = await call({}, 'good', '/listings/sold/data.json');
check('rate limit -> 429 after the per-user cap', last.statusCode === 429);

// ---- config
process.chdir(ROOT);
const toml = readFileSync('netlify.toml', 'utf8');
check('netlify.toml bundles the sold files into sold-data', /\[functions\."sold-data"\][\s\S]*listings\/sold\/data\.json[\s\S]*listings\/sold\/\*\/data\.json[\s\S]*listings\/sold\/detail\/\*\.json/.test(toml));
const st = readFileSync('tools/labwest-listings-state.py', 'utf8');
check('state script forces the hub file', /\/listings\/sold\/data\.json\s+\/\.netlify\/functions\/sold-data\?f=data\.json\s+200!/.test(st));
check('state script forces town files', /\/listings\/sold\/:town\/data\.json\s+\/\.netlify\/functions\/sold-data\?town=:town\s+200!/.test(st));
check('state script forces detail shards', /\/listings\/sold\/detail\/:shard\s+\/\.netlify\/functions\/sold-data\?shard=:shard\s+200!/.test(st));
check('the committed _redirects does not route sold data while off', !/sold-data/.test(readFileSync('_redirects', 'utf8')));

if (FAILURES.length) { console.log(`\n${FAILURES.length} FAILED`); process.exit(1); }
console.log('\nlabwest-sold-data-test: all checks passed');
