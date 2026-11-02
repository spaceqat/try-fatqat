"""Prepare the latest FatQat release for the browser build.

- Pin fatqat in the in-browser environment to the release, writing
  lite/try-fatqat-env.pinned.yaml for scripts/jl-build.
- Check that the environment provides every dependency of the release.
- Render the release's tutorials with a NumPy startup cell into
  lite/files/tutorials/<category>/.

The latest release is the newest final release on PyPI, or the newest
pre-release while there is no final release. Set FATQAT_VERSION to use another
release.

Usage: python scripts/sync_fatqat.py
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import nbformat
import yaml

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "lite" / "try-fatqat-env.yaml"
PINNED_ENV_FILE = ROOT / "lite" / "try-fatqat-env.pinned.yaml"
TUTORIALS = ROOT / "lite" / "files" / "tutorials"

# FatQat dependencies with no WebAssembly build. FatQat runs without them when
# every simulator uses runtime="numpy" and execution stays in one process.
BROWSER_EXCLUDED = {"numba", "loky"}

MANIFEST = ROOT / "tutorial-manifest.json"
NUMPY_STARTUP = """import fatqat as fq
if not hasattr(fq, "set_default_runtime"):
    raise RuntimeError("This site requires a FatQat release with set_default_runtime support.")
fq.set_default_runtime("numpy")"""


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def _project_name(requirement: str) -> str:
    name = re.split(r"[\s<>=!~;\[@(]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def latest_release() -> str:
    # PyPI reports the newest final release, or the newest pre-release while
    # the project has no final release.
    return _get_json("https://pypi.org/pypi/fatqat/json")["info"]["version"]


def check_dependencies(version: str) -> None:
    release = _get_json(f"https://pypi.org/pypi/fatqat/{version}/json")
    required = {
        _project_name(requirement)
        for requirement in release["info"]["requires_dist"] or []
        if not re.search(r"\bextra\s*==", requirement)
    }
    provided = set()
    for dependency in yaml.safe_load(ENV_FILE.read_text())["dependencies"]:
        specs = dependency["pip"] if isinstance(dependency, dict) else [dependency]
        provided.update(_project_name(spec) for spec in specs)
    if missing := sorted(required - provided - BROWSER_EXCLUDED):
        raise SystemExit(
            f"fatqat {version} requires packages missing from {ENV_FILE.name}: "
            f"{', '.join(missing)}. Add them from emscripten-forge, or under pip "
            "if they are pure Python."
        )


def pin_environment(version: str) -> None:
    pinned, count = re.subn(
        r"^(\s*- fatqat)\s*$", rf"\g<1>=={version}", ENV_FILE.read_text(), flags=re.M
    )
    if count != 1:
        raise SystemExit(f"expected one unpinned '- fatqat' line in {ENV_FILE}")
    PINNED_ENV_FILE.write_text(pinned)


def download_source(version: str, directory: str) -> Path:
    url = f"https://github.com/spaceqat/fatqat/archive/refs/tags/v{version}.tar.gz"
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = io.BytesIO(response.read())
    with tarfile.open(fileobj=archive, mode="r:gz") as tar:
        tar.extractall(directory, filter="data")
    (source,) = Path(directory).iterdir()
    return source


def render_tutorials(source: Path, version: str) -> None:
    # Render the same unexecuted notebooks the FatQat docs offer for download.
    # The tool's own entry point also renders the docs pages, which need cached
    # execution results that release tags do not ship.
    sys.path.insert(0, str(source / "docs" / "mkdocs" / "tools"))
    import build_tutorials

    tutorials = build_tutorials.discover_tutorials()
    order = list(build_tutorials.GALLERY.get("category_order", []))
    categories = sorted(
        {tutorial.category for tutorial in tutorials},
        key=lambda category: (
            order.index(category) if category in order else len(order),
            category,
        ),
    )

    shutil.rmtree(TUTORIALS, ignore_errors=True)
    manifest = {"version": version, "categories": [], "tutorials": []}
    for category in categories:
        title, description = build_tutorials._category_label(category)
        manifest["categories"].append(
            {"name": category, "title": title, "description": description}
        )
        for tutorial in (item for item in tutorials if item.category == category):
            path = TUTORIALS / category / f"{tutorial.slug}.ipynb"
            path.parent.mkdir(parents=True, exist_ok=True)
            notebook = nbformat.reads(
                build_tutorials._render_notebook(tutorial), as_version=4
            )
            notebook.cells.insert(
                0, nbformat.v4.new_code_cell(NUMPY_STARTUP, id="browser-runtime")
            )
            nbformat.write(notebook, path)
            manifest["tutorials"].append(
                {
                    "slug": tutorial.slug,
                    "category": category,
                    "title": tutorial.source.title,
                    "description": tutorial.source.description,
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
            print(f"Added {path.relative_to(ROOT)}")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_index(manifest, manifest["tutorials"])


def write_index(manifest: dict, tutorials: list[dict]) -> None:
    index = [
        "# FatQat tutorials",
        "",
        f"From FatQat {manifest['version']}. The first cell selects NumPy for this kernel.",
        "These notebooks are checked in a browser with a five-minute execution limit "
        "per tutorial. Your device may take longer. Find the full collection in the "
        "[FatQat documentation](https://fatqat.readthedocs.io/en/stable/tutorials/).",
        "",
    ]
    for category in manifest["categories"]:
        members = [t for t in tutorials if t["category"] == category["name"]]
        if not members:
            continue
        index += [f"## {category['title']}", "", category["description"], ""]
        for item in members:
            index.append(
                f"- [{item['title']}]({item['category']}/{item['slug']}.ipynb): {item['description']}"
            )
        index.append("")
    (TUTORIALS / "README.md").write_text("\n".join(index), encoding="utf-8")


def apply_report(report_path: Path) -> None:
    """Keep only successful, unchanged notebooks from a complete browser run."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("version") != manifest["version"]
        or report.get("timeout_seconds") != 300
    ):
        raise ValueError(
            "browser report does not match this build or its five-minute limit"
        )
    results = report["tutorials"]
    if len(results) != len(manifest["tutorials"]) or len(
        {r["slug"] for r in results}
    ) != len(results):
        raise ValueError("browser report is incomplete or has duplicate tutorials")
    by_slug = {r["slug"]: r for r in results}
    accepted, rejected = [], []
    for item in manifest["tutorials"]:
        result = by_slug.get(item["slug"], {})
        path = ROOT / item["path"]
        if (
            result.get("sha256") != item["sha256"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError(f"stale browser report for {item['slug']}")
        if (
            result.get("status") == "pass"
            and 0 <= result.get("seconds", float("inf")) <= 300
        ):
            accepted.append(item)
        else:
            rejected.append(item)
    if not accepted:
        raise ValueError("no tutorials passed; refusing to deploy an empty gallery")
    # Rebuild into a fresh directory even when running the workflow locally twice.
    validated = ROOT / "_validated"
    if validated.is_symlink() or validated.resolve() != ROOT.resolve() / "_validated":
        raise ValueError("validated output must stay inside this checkout")
    if validated.exists():
        shutil.rmtree(validated)
    for item in rejected:
        (ROOT / item["path"]).unlink()
        print(f"Excluded {item['slug']}: {by_slug[item['slug']]['status']}")
    write_index(manifest, accepted)
    print(f"Included {len(accepted)} of {len(results)} tutorials")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, help="Render a local FatQat checkout for development"
    )
    parser.add_argument(
        "--apply-report",
        type=Path,
        help="Filter generated notebooks using browser results",
    )
    args = parser.parse_args()
    if args.apply_report:
        apply_report(args.apply_report)
        return 0
    if args.source:
        render_tutorials(args.source.resolve(), "local-development")
        return 0
    version = os.environ.get("FATQAT_VERSION") or latest_release()
    print(f"Preparing FatQat {version}")
    check_dependencies(version)
    pin_environment(version)
    with tempfile.TemporaryDirectory() as directory:
        render_tutorials(download_source(version, directory), version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
