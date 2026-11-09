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
- FatQat simulators default to `runtime="numba"`, which is unavailable here,
  so the site offers only the tutorials that run without numba: every
  `Simulator`, `AtomArraySimulator`, and `SCQubitSimulator` they create passes
  `runtime="numpy"`, and none imports numba. The site is for trying FatQat;
  the documentation has every tutorial.

## Staying in step with FatQat

`scripts/sync_fatqat.py` prepares each build from the latest FatQat release:
the newest final release on PyPI, or the newest pre-release while there is no
final release. Set `FATQAT_VERSION` to build another release.

- It pins `fatqat` to that release in `lite/try-fatqat-env.pinned.yaml`, the
  environment file `scripts/jl-build` uses.
- It renders the release's numba-free tutorials from its git tag into
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
python scripts/sync_fatqat.py   # pin FatQat and render its tutorials
./scripts/jl-build              # build the site into _output
./scripts/jl-serve              # serve it at http://localhost:8000
```

## Notebook appearance

All notebooks share `lite/brand/fatqat.css`, with SpaceQat's navy/cyan palette
and its original black/lime logo (`spaceqat-logo.png`, copied unchanged from
[the SpaceQat site](https://github.com/spaceqat/spaceqat.github.io/tree/main/assets)).
Only prose has a reading-width limit; native cell spacing and controls remain.
`lite/overrides.json` supplies font sizes and Notebook's full-width setting.

The build ends with `scripts/style_site.py`, which copies the brand folder and
links the stylesheet from Jupyter's generated app pages. Refresh an existing
build with `python scripts/style_site.py --output-dir _output`. Navigation uses
JupyterLite's standard entry points; no custom redirect or runtime JavaScript.

## Deployment

`.github/workflows/build_github_pages.yaml` builds the site on every push and
pull request and once a day, and deploys `main` to GitHub Pages. In the repository settings,
set **Pages > Build and deployment > Source** to **GitHub Actions**.

GitHub pauses scheduled workflows after 60 days without repository activity.
If that happens, re-enable the workflow from the repository's **Actions** tab.
