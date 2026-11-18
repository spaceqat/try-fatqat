"""Apply the local FatQat stylesheet to generated JupyterLite entry points."""

import argparse
from pathlib import Path
import shutil


def style_site(output: Path) -> None:
    """Copy branding assets and add one relative CSS link per app entry point."""
    source = Path(__file__).resolve().parents[1] / "lite" / "brand"
    shutil.copytree(source, output / "brand", dirs_exist_ok=True)
    for app in ("lab", "notebooks", "tree", "edit", "consoles", "repl"):
        entry = output / app / "index.html"
        if not entry.is_file():
            continue
        html = entry.read_text(encoding="utf-8")
        if 'id="fatqat-style"' not in html:
            if "</head>" not in html:
                raise ValueError(f"Missing closing head element in {entry}")
            html = html.replace(
                "</head>",
                '<link id="fatqat-style" rel="stylesheet" '
                'href="../brand/fatqat.css">\n</head>',
                1,
            )
            entry.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", "--LiteBuildConfig.output_dir", type=Path, required=True
    )
    options, _ = parser.parse_known_args()
    style_site(options.output_dir)
