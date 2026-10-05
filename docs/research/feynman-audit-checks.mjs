// Offline characterization of the reviewed Feynman snapshot, not model-quality tests.
// Run: node docs/research/feynman-audit-checks.mjs [path/to/feynman]
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const root = resolve(process.argv[2] ?? 'feynman');
const source = fs.readFileSync(join(root, 'evals/run.mjs'), 'utf8');
function between(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert(first >= 0 && last > first, `Reviewed scorer layout changed: ${start}`);
  return source.slice(first, last);
}
// Load the actual scorer definitions only; do not run main(), providers, or subprocesses.
const context = vm.createContext({
  ...fs, join, setTimeout, URL,
  fetch: async () => { throw new Error('Unexpected network request'); },
});
vm.runInContext(
  between('const UA =', '// ---------- run ----------') +
  between('function findFinal(', '// Sum usage over'), context,
);
context.resolveArxiv = async () => new Map([
  ['1234.56789', { title: 'A Study of Integer Addition', author: 'Example' }],
]);
const bibliography = '\nExample. A Study of Integer Addition. arXiv:1234.56789';
const supported = await context.scoreCitations('Two plus two is four.' + bibliography);
const unsupported = await context.scoreCitations('Two plus two is five.' + bibliography);
assert.equal(unsupported.citation_validity, 1);
assert.equal(unsupported.title_match, 1);
assert.equal(JSON.stringify(supported), JSON.stringify(unsupported));
console.log('CONFIRMED: changing the claim leaves perfect identifier/title scores unchanged (mock metadata).');

const wrongTitle = await context.scoreCitations('Example. An Unrelated Paper. arXiv:1234.56789');
assert.equal(wrongTitle.title_match, 1);
console.log('CONFIRMED: matching surname can pass title_match despite an unrelated title (mock metadata).');

const workspace = fs.mkdtempSync(join(tmpdir(), 'feynman-audit-'));
try {
  fs.mkdirSync(join(workspace, 'outputs'));
  fs.writeFileSync(join(workspace, 'outputs/empty.md'), '');
  fs.writeFileSync(join(workspace, 'outputs/empty.provenance.md'), '');
  assert(context.findFinal(workspace));
  console.log('CONFIRMED: an empty final and empty sidecar satisfy findFinal.');
} finally {
  fs.rmSync(workspace, { recursive: true, force: true });
}

context.fetch = async () => ({ ok: false, status: 503, json: async () => ({}) });
const outage = await context.resolveDoi('10.1234/synthetic-audit-fixture');
assert.equal(outage.resolves, false);
console.log('CONFIRMED: mocked Crossref/DOI HTTP 503 responses become unresolved rather than unknown.');

const { extractPaperSections } = await import(pathToFileURL(join(root, 'extensions/research-tools/alpha-sections.ts')));
const extracted = extractPaperSections('# Results\nAccuracy improved\nMeasured on the held-out set.', 'results');
assert.deepEqual(extracted.missing, ['results']);
console.log('CONFIRMED: an unpunctuated prose line is treated as a heading and loses the requested section.');
