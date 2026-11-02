# try-fatqat

[FatQat](https://github.com/spaceqat/fatqat) running in the browser through
[JupyterLite](https://jupyterlite.readthedocs.io/) and the
[xeus-python](https://github.com/jupyter-xeus/xeus-python) kernel, with
packages from [emscripten-forge](https://emscripten-forge.org/). Modeled on
[qutip/try-qutip](https://github.com/qutip/try-qutip).

Visitors need no installation and no server: the site is static and every
computation runs in the visitor's browser. Performance is not a goal.

## How FatQat runs in the browser

- numba has no WebAssembly build, so `jupyterlite-xeus` installs FatQat with
  pip's `--no-deps`, and the remaining dependencies (NumPy, SciPy, Matplotlib,
  QuTiP) come from emscripten-forge. See `lite/try-fatqat-env.yaml`.
- Each generated tutorial starts with `fq.simulator.set_default_runtime("numpy")`.
  This selects NumPy for subsequent simulators in that notebook kernel;
  explicit runtime arguments remain unchanged. In a new notebook, run
  `import fatqat as fq; fq.simulator.set_default_runtime("numpy")` before creating simulators.
- The site includes tutorials that complete during a browser check at build time,
  with a five-minute limit per notebook. Runtime varies by device.

## Staying in step with FatQat

`scripts/sync_fatqat.py` prepares each build from the latest FatQat release:
the newest final release on PyPI, or the newest pre-release while there is no
final release. Set `FATQAT_VERSION` to build another release.

- It pins `fatqat` to that release in `lite/try-fatqat-env.pinned.yaml`, the
  environment file `scripts/jl-build` uses.
- It renders all tutorials from the release's git tag into
  `lite/files/tutorials/<category>/`, following the category folders of the
  FatQat documentation, and writes an index grouped the same way. Notebooks and
  the installed package therefore always come from the same release.
- It fails if the release needs a dependency that `lite/try-fatqat-env.yaml`
  does not provide, so a new dependency is added deliberately.

The workflow runs daily, so a new release reaches the site within a day. A
failed build leaves the last deployed site in place.

## Build locally

```bash
conda env create -f environment.yml
conda activate try-fatqat-build
python scripts/sync_fatqat.py
./scripts/jl-build
npm install --no-save --package-lock=false playwright@1.62.1
npx playwright install chromium
node scripts/check_tutorials.cjs
./scripts/jl-serve
```

To render tutorials from a local FatQat checkout, use
`python scripts/sync_fatqat.py --source /path/to/fatqat`.

## Select tutorials

Each build runs every tutorial in a fresh browser kernel. Only notebooks that
finish successfully within five minutes are published. New tutorials are
included automatically when they pass this check.

## Deployment

`.github/workflows/build_github_pages.yaml` builds the site on every push and
pull request and once a day, and deploys `main` to GitHub Pages. In the repository settings,
set **Pages > Build and deployment > Source** to **GitHub Actions**.

GitHub pauses scheduled workflows after 60 days without repository activity.
If that happens, re-enable the workflow from the repository's **Actions** tab.
