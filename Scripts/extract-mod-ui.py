#!/usr/bin/env python3
"""Extract the mod menu web UI out of the injected dylibs into mod-ui/.

Each mod dylib stores its menu as one NUL-terminated UTF-8 HTML string in a
fixed ~2 MB buffer. This pulls those pages out so they can be edited as
ordinary files; Scripts/patch-mod-menu.py writes them back.

Run once to seed mod-ui/, or with --force to discard local edits and re-read
the pages currently inside the dylibs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD_UI = ROOT / "mod-ui"
MARKER = b"<!DOCTYPE html>"


def app_dir() -> Path:
    apps = sorted((ROOT / "extracted" / "Payload").glob("*.app"))
    if len(apps) != 1:
        raise SystemExit(f"expected one .app under extracted/Payload, found {len(apps)}")
    return apps[0]


def find_page(blob: bytes) -> tuple[int, int]:
    """Return (start, length) of the NUL-terminated HTML page."""
    start = blob.find(MARKER)
    if start < 0:
        raise SystemExit("no HTML page found in dylib")
    end = blob.find(b"\x00", start)
    if end < 0:
        raise SystemExit("HTML page is not NUL-terminated")
    return start, end - start


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files in mod-ui/")
    args = parser.parse_args()

    MOD_UI.mkdir(exist_ok=True)
    app = app_dir()

    for dylib in sorted(app.glob("Mod*.dylib")):
        out = MOD_UI / f"{dylib.stem}.html"
        if out.exists() and not args.force:
            print(f"skip   {out.relative_to(ROOT)} (exists; pass --force to overwrite)")
            continue
        blob = dylib.read_bytes()
        start, length = find_page(blob)
        out.write_bytes(blob[start:start + length])
        print(f"wrote  {out.relative_to(ROOT)}  "
              f"({length} bytes from {dylib.name} @ 0x{start:08x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
