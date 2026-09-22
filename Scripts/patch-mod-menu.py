#!/usr/bin/env python3
"""Write mod-ui/*.html back into the injected mod dylibs.

Each Mod*.dylib carries its menu as one NUL-terminated UTF-8 HTML string that
sits at the front of a large zero-filled buffer. Replacing the page in place is
safe as long as the new bytes plus the terminator still fit inside that buffer,
so nothing in the Mach-O needs relocating.

mod-ui/ is the source of truth. Run this after editing it, before packaging.
"""
from __future__ import annotations

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


def slot_bounds(blob: bytes, start: int) -> tuple[int, int]:
    """Return (current page length, bytes available from `start`).

    The buffer runs from the page start up to the next non-zero byte after the
    page's NUL terminator; everything between is reserved padding.
    """
    end = blob.find(b"\x00", start)
    if end < 0:
        raise SystemExit("HTML page is not NUL-terminated")
    cursor = end
    while cursor < len(blob) and blob[cursor] == 0:
        cursor += 1
    return end - start, cursor - start


def main() -> int:
    if not MOD_UI.is_dir():
        raise SystemExit("mod-ui/ not found - run Scripts/extract-mod-ui.py first")

    app = app_dir()
    dylibs = sorted(app.glob("Mod*.dylib"))
    if not dylibs:
        raise SystemExit(f"no Mod*.dylib found in {app}")

    changed = 0
    for dylib in dylibs:
        page = MOD_UI / f"{dylib.stem}.html"
        if not page.is_file():
            print(f"skip   {dylib.name}: no {page.name} in mod-ui/")
            continue

        blob = bytearray(dylib.read_bytes())
        start = blob.find(MARKER)
        if start < 0:
            raise SystemExit(f"{dylib.name}: no HTML page to replace")

        old_len, capacity = slot_bounds(bytes(blob), start)
        new = page.read_bytes()
        if b"\x00" in new:
            raise SystemExit(f"{page.name}: contains a NUL byte, which would truncate the page")
        if len(new) + 1 > capacity:
            raise SystemExit(
                f"{page.name}: {len(new)} bytes + terminator exceeds the "
                f"{capacity}-byte buffer in {dylib.name}")

        if bytes(blob[start:start + old_len]) == new:
            print(f"ok     {dylib.name}: already up to date ({old_len} bytes)")
            continue

        # Overwrite the page, terminate it, and clear whatever the old, longer
        # page left behind so no stale markup trails the new one.
        span = max(old_len, len(new))
        blob[start:start + span] = new + b"\x00" * (span - len(new))
        dylib.write_bytes(bytes(blob))
        changed += 1
        headroom = capacity - len(new) - 1
        print(f"patch  {dylib.name}: {old_len} -> {len(new)} bytes "
              f"({headroom} bytes headroom)")

    print(f"{changed} dylib(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
