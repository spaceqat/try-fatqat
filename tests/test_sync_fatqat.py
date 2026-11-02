"""A browser report must describe the exact notebooks being published."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import nbformat

SPEC = importlib.util.spec_from_file_location(
    "sync_fatqat", Path(__file__).resolve().parents[1] / "scripts" / "sync_fatqat.py"
)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class BrowserReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tutorials = self.root / "lite" / "files" / "tutorials"
        self.tutorials.mkdir(parents=True)
        self.manifest_path = self.root / "tutorial-manifest.json"
        self.report_path = self.root / "browser-report.json"
        self.manifest = {
            "version": "1.0",
            "categories": [
                {"name": "fast", "title": "Fast", "description": "Fast examples"},
                {"name": "slow", "title": "Slow", "description": "Slow examples"},
            ],
            "tutorials": [],
        }
        self.report = {"version": "1.0", "timeout_seconds": 300, "tutorials": []}
        for slug, category, status, seconds in (
            ("success", "fast", "pass", 2),
            ("too-slow", "slow", "timeout", 300),
            ("failure", "slow", "error", 1),
        ):
            path = self.tutorials / category / f"{slug}.ipynb"
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.manifest["tutorials"].append(
                {
                    "slug": slug,
                    "category": category,
                    "title": slug,
                    "description": slug,
                    "path": path.relative_to(self.root).as_posix(),
                    "sha256": digest,
                }
            )
            self.report["tutorials"].append(
                {
                    "slug": slug,
                    "sha256": digest,
                    "status": status,
                    "seconds": seconds,
                }
            )
        patches = patch.multiple(
            sync, ROOT=self.root, TUTORIALS=self.tutorials, MANIFEST=self.manifest_path
        )
        patches.start()
        self.addCleanup(patches.stop)

    def apply(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")
        sync.apply_report(self.report_path)

    def test_only_complete_fast_runs_are_published(self):
        self.apply()
        self.assertEqual([p.stem for p in self.tutorials.rglob("*.ipynb")], ["success"])
        index = (self.tutorials / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Fast", index)
        self.assertNotIn("## Slow", index)
        self.assertNotIn("too-slow", index)

    def test_missing_result_is_rejected_without_removing_files(self):
        self.report["tutorials"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.apply()
        self.assertEqual(len(list(self.tutorials.rglob("*.ipynb"))), 3)

    def test_duplicate_result_is_rejected(self):
        self.report["tutorials"][2] = self.report["tutorials"][1]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.apply()

    def test_changed_notebook_is_rejected_before_pruning(self):
        (self.tutorials / "slow" / "failure.ipynb").write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "stale"):
            self.apply()
        self.assertEqual(len(list(self.tutorials.rglob("*.ipynb"))), 3)

    def test_wrong_release_or_limit_is_rejected(self):
        for key, value in (("version", "old"), ("timeout_seconds", 600)):
            with self.subTest(key=key):
                previous = self.report[key]
                self.report[key] = value
                with self.assertRaisesRegex(ValueError, "does not match"):
                    self.apply()
                self.report[key] = previous

    def test_empty_gallery_does_not_replace_deployment(self):
        self.report["tutorials"][0]["seconds"] = 301
        with self.assertRaisesRegex(ValueError, "empty gallery"):
            self.apply()
        self.assertEqual(len(list(self.tutorials.rglob("*.ipynb"))), 3)

    def test_previous_output_is_removed_before_rebuild(self):
        output = self.root / "_validated"
        output.mkdir()
        (output / "rejected.ipynb").write_text("{}")
        self.apply()
        self.assertFalse(output.exists())

    def test_render_adds_setup_without_rewriting_tutorial_code(self):
        code = 'fq.simulator.Simulator(runtime="numba")'
        tutorial = types.SimpleNamespace(
            slug="explicit",
            category="fast",
            source=types.SimpleNamespace(
                title="Explicit runtime", description="Example"
            ),
        )
        builder = types.SimpleNamespace(
            discover_tutorials=lambda: [tutorial],
            GALLERY={"category_order": ["fast"]},
            _category_label=lambda category: ("Fast", "Examples"),
            _render_notebook=lambda item: nbformat.writes(
                nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(code)])
            ),
        )
        with patch.dict("sys.modules", {"build_tutorials": builder}), patch(
            "sys.path", []
        ):
            sync.render_tutorials(self.root, "1.0")
        notebook = nbformat.read(
            self.tutorials / "fast" / "explicit.ipynb", as_version=4
        )
        self.assertEqual(notebook.cells[0].source, sync.NUMPY_STARTUP)
        self.assertEqual(notebook.cells[1].source, code)


if __name__ == "__main__":
    unittest.main()
