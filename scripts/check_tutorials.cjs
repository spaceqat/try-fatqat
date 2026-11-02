/* Execute complete notebooks in fresh WebAssembly kernels before publishing. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const site = path.resolve(process.env.TUTORIAL_SITE_DIR || path.join(root, '_output'));
const tutorials = path.join(site, 'files', 'tutorials');
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
  const rejected = new Set();
  const notebooks = fs.readdirSync(tutorials, { recursive: true })
    .filter(file => file.endsWith('.ipynb'));
  if (!notebooks.length) throw new Error('No tutorials found');
  const server = http.createServer(serve);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/lab/index.html`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true,
      ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}) });
    for (const file of notebooks) {
      const notebook = JSON.parse(fs.readFileSync(path.join(tutorials, file), 'utf8'));
      const context = await browser.newContext();
      let started;
      const result = { status: 'error', seconds: 0 };
      console.log('START', file);
      try {
        const page = await context.newPage();
        await withTimeout(prepare(page, url), 120000);
        started = performance.now();
        const run = async () => {
          for (const entry of notebook.cells) {
            if (entry.cell_type !== 'code') continue;
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
        await context.close(); // Terminates a timed-out Web Worker before the next tutorial.
      }
      if (result.status !== 'pass') rejected.add(file.replaceAll('\\', '/'));
      console.log('RESULT', file, result.status, result.seconds.toFixed(1), result.error || '');
    }
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
  if (rejected.size === notebooks.length) throw new Error('No tutorials passed');
  // Prune the built files and their JupyterLite directory listings in place.
  for (const file of rejected) fs.unlinkSync(path.join(tutorials, file));
  const readme = path.join(tutorials, 'README.md');
  const index = fs.readFileSync(readme, 'utf8').split('\n').filter(line => {
    const link = line.match(/^- \[.*?\]\(([^)]+)\)/);
    return !link || !rejected.has(link[1]);
  }).join('\n');
  fs.writeFileSync(readme, index);
  const contents = path.join(site, 'api', 'contents', 'tutorials');
  for (const file of fs.readdirSync(contents, { recursive: true })) {
    if (!file.endsWith('all.json')) continue;
    const filename = path.join(contents, file);
    const listing = JSON.parse(fs.readFileSync(filename, 'utf8'));
    listing.content = listing.content.filter(entry =>
      !rejected.has(entry.path.replaceAll('\\', '/').replace(/^tutorials\//, '')));
    for (const entry of listing.content) {
      if (entry.path === 'tutorials/README.md') entry.size = Buffer.byteLength(index);
    }
    fs.writeFileSync(filename, JSON.stringify(listing));
  }
  console.log(`Published ${notebooks.length - rejected.size}/${notebooks.length} tutorials`);

}

main().catch(error => { console.error(error); process.exitCode = 1; });
