/* Execute complete notebooks in fresh WebAssembly kernels before publishing. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const site = path.resolve(process.env.TUTORIAL_SITE_DIR || path.join(root, '_output'));
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'tutorial-manifest.json'), 'utf8'));
const reportPath = path.join(root, 'browser-report.json');
const limit = 300;
const types = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json',
  '.wasm': 'application/wasm', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };

function serve(req, res) {
  let filename;
  try { filename = path.resolve(site, '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname)); }
  catch { res.writeHead(400).end(); return; }
  if (path.relative(site, filename).startsWith('..')) { res.writeHead(403).end(); return; }
  if (fs.existsSync(filename) && fs.statSync(filename).isDirectory()) filename = path.join(filename, 'index.html');
  if (!fs.existsSync(filename)) { res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', types[path.extname(filename)] || 'application/octet-stream');
  res.setHeader('Cache-Control', 'no-store');
  if (filename === path.join(site, 'jupyter-lite.json')) {
    const config = JSON.parse(fs.readFileSync(filename, 'utf8'));
    config['jupyter-config-data'].exposeAppInBrowser = 'true';
    res.end(JSON.stringify(config));
  } else fs.createReadStream(filename).pipe(res);
}

async function execute(page, code) {
  return page.evaluate(async (source) => {
    const messages = [];
    const future = window.auditKernel.requestExecute({ code: source, stop_on_error: true, store_history: false });
    future.onIOPub = (msg) => {
      if (msg.header.msg_type === 'error') messages.push({ type: 'error', ...msg.content });
      if (msg.header.msg_type === 'stream') messages.push({ type: 'stream', text: msg.content.text });
    };
    const reply = await future.done;
    return { status: reply.content.status, messages };
  }, code);
}

function withTimeout(promise, milliseconds) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('tutorial-timeout')), milliseconds);
  })]).finally(() => clearTimeout(timer));
}

async function prepare(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.jupyterapp, null, { timeout: 120000 });
  await page.evaluate(async () => {
    await window.jupyterapp.started;
    await window.jupyterapp.serviceManager.ready;
    window.auditKernel = await window.jupyterapp.serviceManager.kernels.startNew({ name: 'xpython' });
    await window.auditKernel.info;
  });
  // Development only: exercise this task's full source tree in the existing WASM environment.
  if (process.env.FATQAT_SOURCE_ZIP) {
    const data = fs.readFileSync(process.env.FATQAT_SOURCE_ZIP).toString('base64');
    const result = await execute(page, `import base64, io, sys, zipfile\nzipfile.ZipFile(io.BytesIO(base64.b64decode('${data}'))).extractall('/tmp/fatqat-audit')\nsys.path.insert(0, '/tmp/fatqat-audit')`);
    if (result.status !== 'ok') throw new Error(JSON.stringify(result));
  }
}

async function main() {
  const server = http.createServer(serve);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/lab/index.html`;
  let browser;
  const report = { version: manifest.version, timeout_seconds: limit,
    started_at: new Date().toISOString(), tutorials: [] };
  const save = () => fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
  try {
    browser = await chromium.launch({ headless: true,
      ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) });
    report.browser = browser.version();
    report.source_zip_sha256 = process.env.FATQAT_SOURCE_ZIP
      ? crypto.createHash('sha256').update(fs.readFileSync(process.env.FATQAT_SOURCE_ZIP)).digest('hex') : null;
    // Fail the build, rather than hiding all tutorials, if the release lacks the new API.
    const smokeContext = await browser.newContext();
    try {
      const page = await smokeContext.newPage();
      await withTimeout(prepare(page, url), 120000);
      const result = await withTimeout(execute(page,
        "import sys, fatqat as fq\nassert hasattr(fq.simulator, 'set_default_runtime'), 'Release FatQat with set_default_runtime before deploying this site'\nfq.simulator.set_default_runtime('numpy')\nassert fq.simulator.get_default_runtime() == 'numpy'\nprint(sys.version, fq.__version__)\nprint(fq.simulator.Simulator().run(fq.Program(1)).result().metadata['runtime'])"), 60000);
      if (result.status !== 'ok') throw new Error('Kernel preflight failed: ' + JSON.stringify(result));
      report.environment = result.messages;
      console.log('PREFLIGHT', JSON.stringify(result));
    } finally { await smokeContext.close(); }

    for (const item of manifest.tutorials) {
      const content = fs.readFileSync(path.join(root, item.path));
      if (crypto.createHash('sha256').update(content).digest('hex') !== item.sha256)
        throw new Error('Notebook changed after generation: ' + item.slug);
      const notebook = JSON.parse(content);
      const context = await browser.newContext();
      let started;
      let cell = 0;
      const result = { slug: item.slug, sha256: item.sha256, status: 'error', seconds: 0 };
      console.log('START', item.slug);
      try {
        const page = await context.newPage();
        await withTimeout(prepare(page, url), 120000);
        started = performance.now();
        const run = async () => {
          for (const entry of notebook.cells) {
            if (entry.cell_type !== 'code') continue;
            cell++;
            const reply = await execute(page, Array.isArray(entry.source) ? entry.source.join('') : entry.source);
            if (reply.status !== 'ok') throw new Error(JSON.stringify(reply));
            // Inline displays have already been delivered. Release figures between cells.
            const cleanup = await execute(page, "import matplotlib.pyplot as _plt\n_plt.close('all')");
            if (cleanup.status !== 'ok') throw new Error(JSON.stringify(cleanup));
          }
        };
        await withTimeout(run(), limit * 1000);
        result.status = 'pass';
      } catch (error) {
        if (started === undefined) throw error; // Infrastructure failure must not prune a tutorial.
        result.status = error.message === 'tutorial-timeout' ? 'timeout' : 'error';
        result.error = error.message;
      } finally {
        result.seconds = started === undefined ? 0 : (performance.now() - started) / 1000;
        result.cell = cell;
        await context.close(); // Terminates a timed-out Web Worker before the next tutorial.
      }
      report.tutorials.push(result);
      save();
      console.log('RESULT', item.slug, result.status, result.seconds.toFixed(1), result.error || '');
    }
  } finally {
    save();
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
