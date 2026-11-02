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
- Each generated tutorial starts with `fq.set_default_runtime("numpy")`.
  This selects NumPy for subsequent simulators in that notebook kernel;
  explicit runtime arguments remain unchanged. In a new notebook, run
  `import fatqat as fq; fq.set_default_runtime("numpy")` before creating simulators.
- Every build executes all tutorial code cells in fresh Chromium/WebAssembly
  kernels. Only complete, successful runs within five minutes are published.
  Shots and iteration counts are not reduced. Explicit Numba requirements,
  unsupported dependencies, errors, and slow tutorials are filtered by execution.
  The documentation retains the full collection. Timings depend on the device;
  this check is a publishing threshold, not a guarantee for every browser.

The FatQat release must provide `set_default_runtime`. The browser preflight
fails the build if it does not; publish the FatQat API change before enabling
this workflow against a release. A failed build leaves the deployed site intact.

## Staying in step with FatQat

`scripts/sync_fatqat.py` prepares each build from the latest FatQat release:
the newest final release on PyPI, or the newest pre-release while there is no
final release. Set `FATQAT_VERSION` to build another release.

- It pins `fatqat` to that release in `lite/try-fatqat-env.pinned.yaml`, the
  environment file `scripts/jl-build` uses.
- It renders the release's tutorials from its git tag into
  `lite/files/tutorials/<category>/`, following the category folders of the
  FatQat documentation, and writes an index grouped the same way. Notebooks and
  the installed package therefore always come from the same release.
- It fails if the release needs a dependency that `lite/try-fatqat-env.yaml`
  does not provide, so a new dependency is added deliberately.

The workflow runs daily, so a new release reaches the site within a day. A
failed build leaves the last deployed site in place.

## Build locally

Install Node.js 22 or newer in addition to the conda build environment.

```bash
conda env create -f environment.yml
conda activate try-fatqat-build
python scripts/sync_fatqat.py   # pin FatQat and render its tutorials
./scripts/jl-build              # build the site into _output
npm ci
npx playwright install chromium
npm run test:browser            # complete runs, at most five minutes each
python scripts/sync_fatqat.py --apply-report browser-report.json
JUPYTERLITE_OUTPUT_DIR=_validated ./scripts/jl-build
JUPYTERLITE_OUTPUT_DIR=_validated ./scripts/jl-serve
```

The second build uses a fresh output directory so rejected notebooks cannot
remain in the published files or contents index. `browser-report.json` records
the browser version, environment, notebook hashes, times, and failures; CI saves
it with the candidate manifest as an artifact. Kernel startup has a separate
two-minute deadline. Tutorial timing includes the NumPy setup cell, imports,
execution, and plot delivery, after kernel startup. Each timeout closes its
browser context and terminates the worker before continuing.

For an unpublished FatQat change, render with
`python scripts/sync_fatqat.py --source /path/to/fatqat`. Build a test environment
with that same local package (jupyterlite-xeus supports local pip paths), or set
`TUTORIAL_SITE_DIR` to an existing build and `FATQAT_SOURCE_ZIP` to a zip containing
the modified `fatqat/` package at its root. The latter overlays only FatQat in
each fresh test kernel; the report records the archive hash. These development
options do not change the normal release deployment.

Run `python -m unittest discover -s tests` for the manifest/filter checks.

## Deployment

`.github/workflows/build_github_pages.yaml` builds the site on every push and
pull request and once a day, and deploys `main` to GitHub Pages. In the repository settings,
set **Pages > Build and deployment > Source** to **GitHub Actions**.

GitHub pauses scheduled workflows after 60 days without repository activity.
If that happens, re-enable the workflow from the repository's **Actions** tab.
