# Try FatQat

[FatQat](https://github.com/spaceqat/fatqat) runs here entirely in your
browser, compiled to WebAssembly. Nothing is installed on your computer and
nothing runs on a server. The first start downloads the Python environment,
so it can take a minute; later visits reuse the browser cache.

- Start with [quickstart.ipynb](quickstart.ipynb): build, draw, and run a
  Bell-state Program.
- Then open the [tutorials](tutorials/README.md): the case studies from the
  [FatQat documentation](https://fatqat.readthedocs.io/en/stable/tutorials/)
  that run in the browser.

## Differences from a local installation

- The first tutorial cell sets `fq.simulator.set_default_runtime("numpy")` for that
  notebook kernel. For a new notebook, run `import fatqat as fq` and then
  `fq.simulator.set_default_runtime("numpy")` before creating simulators. Existing
  instances and explicit runtime arguments are unchanged.
- The selected tutorials typically finish within a few minutes. Your device
  may be slower. NumPy and Numba results can differ in rounding and sampling.
- Everything runs in a single thread; leave the parallel execution options
  at their defaults.
- Files you create or edit are kept only in this browser. Use **Download** in
  the notebook toolbar to keep a copy.
