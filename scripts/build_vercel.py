"""Publish ONLY the explicit static directory; never runtime data or secrets."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def build():
    destination = ROOT/'public/static'
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT/'static').iterdir():
        if source.is_file() and source.suffix in {'.css', '.js', '.svg', '.png', '.html', '.webmanifest'}:
            shutil.copy2(source, destination/source.name)
    shutil.copy2(ROOT/'static/sw.js', ROOT/'public/sw.js')


if __name__ == '__main__': build()
