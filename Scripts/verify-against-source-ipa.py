#!/usr/bin/env python3
"""Diff the working bundle against the IPA it was unpacked from.

Answers one question: exactly which bytes of the shipped app have changed?
Anything this reports that you did not intend is a bug in an edit, not a
surprise to discover on the phone.

Usage:
    python Scripts/verify-against-source-ipa.py [path/to/original.ipa]
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def first_last_diff(a: bytes, b: bytes) -> tuple[int, int, int]:
    """Return (first differing offset, last differing offset, changed byte count)."""
    n = min(len(a), len(b))
    first = next((i for i in range(n) if a[i] != b[i]), None)
    if first is None and len(a) == len(b):
        return (-1, -1, 0)
    if first is None:
        first = n
    last = first
    changed = 0
    for i in range(first, n):
        if a[i] != b[i]:
            last = i
            changed += 1
    changed += abs(len(a) - len(b))
    if len(a) != len(b):
        last = max(last, n)
    return (first, last, changed)


def main() -> int:
    if len(sys.argv) > 1:
        source = Path(sys.argv[1])
    else:
        candidates = sorted(ROOT.glob("*.ipa"))
        if len(candidates) != 1:
            print("Pass the original IPA path; found "
                  f"{len(candidates)} .ipa files beside this project.")
            return 2
        source = candidates[0]

    if not source.is_file():
        print(f"not found: {source}")
        return 2

    payload = ROOT / "extracted" / "Payload"
    print(f"source : {source.name}")
    print(f"working: {payload}\n")

    with zipfile.ZipFile(source) as zf:
        original = {
            name: zf.read(name)
            for name in zf.namelist()
            if name.startswith("Payload/") and not name.endswith("/")
        }

    current: dict[str, bytes] = {}
    for path in payload.rglob("*"):
        if path.is_file():
            rel = "Payload/" + path.relative_to(payload).as_posix()
            current[rel] = path.read_bytes()

    added = sorted(set(current) - set(original))
    removed = sorted(set(original) - set(current))
    shared = sorted(set(original) & set(current))

    modified = []
    for name in shared:
        if original[name] != current[name]:
            modified.append(name)

    print(f"{len(shared)} files compared, "
          f"{len(modified)} modified, {len(added)} added, {len(removed)} removed\n")

    if not (modified or added or removed):
        print("IDENTICAL - the working bundle matches the source IPA byte for byte.")
        return 0

    for name in modified:
        a, b = original[name], current[name]
        first, last, changed = first_last_diff(a, b)
        print(f"MODIFIED {name}")
        print(f"    size    {len(a)} -> {len(b)}"
              f"{'  (unchanged)' if len(a) == len(b) else ''}")
        print(f"    sha256  {sha(a)} -> {sha(b)}")
        print(f"    bytes   {changed} differ, "
              f"range 0x{first:08x}-0x{last:08x}")
    for name in added:
        print(f"ADDED    {name}  ({len(current[name])} bytes)")
    for name in removed:
        print(f"REMOVED  {name}  ({len(original[name])} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
