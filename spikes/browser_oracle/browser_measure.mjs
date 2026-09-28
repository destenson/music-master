// Runs the same readout in a real browser and reports latency.
//
// Headless Chromium in this sandbox has no visible GPU, so the default device is `wasm` --
// which is also the honest fallback path for the ~15% of browsers without WebGPU. Pass
// --device=webgpu under a GPU-visible sandbox to measure the accelerated path.

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = new Map(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, '').split('=');
    return [k, v.join('=') || 'true'];
  }),
);

const device = args.get('device') ?? 'wasm';
const dtype = args.get('dtype') ?? 'q4f16';
const model = args.get('model') ?? 'onnx-community/Qwen3-0.6B-ONNX';
const headless = args.get('headed') !== 'true';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
};

// `/vendor/` is the installed transformers.js dist directory: the import map points at its
// self-contained ESM bundle, and ONNX Runtime fetches its .wasm and .mjs assets from the same
// directory, so the page needs no CDN.
const VENDOR = join(HERE, 'node_modules', '@huggingface', 'transformers', 'dist');

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  let rel = normalize(url.pathname === '/' ? '/page.html' : url.pathname).replace(/^(\.\.[/\\])+/, '');
  let file = join(HERE, rel);
  if (rel.startsWith('/vendor/')) file = join(VENDOR, rel.slice('/vendor/'.length));
  if (!file.startsWith(HERE)) {
    res.writeHead(403).end('forbidden');
    return;
  }
  if (!existsSync(file)) {
    res.writeHead(404).end('not found');
    return;
  }
  const body = await readFile(file);
  res.writeHead(200, { 'content-type': MIME[extname(file)] ?? 'application/octet-stream' });
  res.end(body);
});

await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const url =
  `http://127.0.0.1:${port}/page.html` +
  `?model=${encodeURIComponent(model)}&dtype=${dtype}&device=${device}`;
console.log(`serving ${url}`);

const browser = await chromium.launch({
  headless,
  // Chromium's own sandbox needs privileges this environment does not grant it; the page is
  // local and reads only model files, so the Playwright-level sandbox is off.
  chromiumSandbox: false,
  args:
    device === 'webgpu'
      ? ['--enable-unsafe-webgpu', '--enable-features=Vulkan', '--use-angle=vulkan']
      : [],
});
const page = await browser.newPage();
page.on('console', (m) => console.log(`  [page] ${m.text()}`));
page.on('pageerror', (e) => console.error(`  [pageerror] ${e.message}`));

await page.goto(url, { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => window.__RESULTS__ || window.__ERROR__, null, { timeout: 30 * 60 * 1000 });
const results = await page.evaluate(() => window.__RESULTS__ ?? { error: window.__ERROR__ });
await browser.close();
server.close();

if (results.error) {
  console.error(`\nFAILED: ${results.error}`);
  process.exitCode = 1;
} else {
  const c = results.calibration;
  console.log(
    `\n${results.modelId} dtype=${results.dtype} device=${results.device} ` +
      `(webgpu available: ${results.hasWebGpu})`,
  );
  console.log(`load ${(results.loadMs / 1000).toFixed(1)}s`);
  console.log(
    `agreement ${results.correct}/${results.total} | ` +
      `latency p50=${results.latency.p50.toFixed(0)}ms p95=${results.latency.p95.toFixed(0)}ms | ` +
      `uncertain ${c.uncertainNouls}/${c.totalNouls} saturated ${c.saturatedNouls}/${c.totalNouls} | ` +
      `mean option-mass=${c.meanOptionMass.toFixed(3)}`,
  );
  const { mkdirSync, writeFileSync } = await import('node:fs');
  mkdirSync(join(HERE, 'results'), { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const out = join(HERE, 'results', `browser-${device}-${stamp}.json`);
  writeFileSync(out, JSON.stringify(results, null, 2));
  console.log(`wrote ${out}`);
}
