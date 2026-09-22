#!/usr/bin/env python3
"""Contract test for the editable slither.io iOS app bundle.

Runs before packaging, in CI and locally, so a broken edit is caught before an
IPA is produced instead of on the phone. Checks only things an edit can
plausibly break; it does not try to validate game behaviour.
"""
from __future__ import annotations

import plistlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = ROOT / "extracted" / "Payload"
MACHO_MAGIC = (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")

failures: list[str] = []


AOT_STUB = bytes.fromhex(
    "010000000000000000e73487221de85ae5e4caafd542c4b480e59c9f5f")


def walk_swf_tags(blob: bytes) -> list[tuple[int, int]]:
    """Return (tag id, body length) for every tag in an uncompressed SWF."""
    # Skip the header: signature, version, length, then the frame-size RECT,
    # frame rate and frame count.
    nbits = blob[8] >> 3
    cursor = 8 + (5 + 4 * nbits + 7) // 8 + 4
    tags = []
    while cursor + 2 <= len(blob):
        code = int.from_bytes(blob[cursor:cursor + 2], "little")
        cursor += 2
        tag_id, length = code >> 6, code & 0x3F
        if length == 0x3F:
            length = int.from_bytes(blob[cursor:cursor + 4], "little")
            cursor += 4
        tags.append((tag_id, length))
        cursor += length
        if tag_id == 0:
            break
    return tags


def check(condition: bool, message: str) -> bool:
    if not condition:
        failures.append(message)
    return condition


def main() -> int:
    if not check(PAYLOAD.is_dir(), f"missing payload directory: {PAYLOAD}"):
        return report()

    apps = sorted(PAYLOAD.glob("*.app"))
    if not check(len(apps) == 1, f"expected exactly one .app in Payload, found {len(apps)}"):
        return report()
    app = apps[0]

    # --- Info.plist -------------------------------------------------------
    info_path = app / "Info.plist"
    info: dict = {}
    if check(info_path.is_file(), "Info.plist is missing"):
        try:
            info = plistlib.loads(info_path.read_bytes())
        except Exception as exc:  # noqa: BLE001 - surface any plist corruption
            failures.append(f"Info.plist does not parse: {exc}")

    if info:
        for key in (
            "CFBundleIdentifier",
            "CFBundleExecutable",
            "CFBundleName",
            "CFBundleShortVersionString",
            "CFBundleVersion",
            "MinimumOSVersion",
        ):
            check(bool(info.get(key)), f"Info.plist is missing {key}")

        bundle_id = info.get("CFBundleIdentifier", "")
        check(
            bundle_id.count(".") >= 2 and " " not in bundle_id,
            f"CFBundleIdentifier looks malformed: {bundle_id!r}",
        )

        name = info.get("CFBundleExecutable")
        if name:
            check(
                (app / name).is_file(),
                f"CFBundleExecutable {name!r} does not exist in the bundle",
            )

    # --- Mach-O executable ------------------------------------------------
    exe_name = info.get("CFBundleExecutable") or "slither.io"
    exe_path = app / exe_name
    if exe_path.is_file():
        magic = exe_path.read_bytes()[:4]
        check(magic in MACHO_MAGIC, f"{exe_name} is not a Mach-O binary (magic {magic.hex()})")

    # --- AIR descriptor ---------------------------------------------------
    descriptor = app / "META-INF" / "AIR" / "application.xml"
    if check(descriptor.is_file(), "META-INF/AIR/application.xml is missing"):
        text = descriptor.read_text(encoding="utf-8", errors="replace")
        check("<content>" in text, "AIR descriptor has no <content> entry")

    # --- SWF --------------------------------------------------------------
    swfs = sorted(app.glob("*.swf"))
    if check(len(swfs) == 1, f"expected exactly one top-level .swf, found {len(swfs)}"):
        swf = swfs[0]
        head = swf.read_bytes()[:8]
        check(head[:3] in (b"FWS", b"CWS", b"ZWS"), f"{swf.name} has no SWF signature")
        declared = struct.unpack("<I", head[4:8])[0]
        actual = swf.stat().st_size
        if head[:3] == b"FWS":
            check(
                declared == actual,
                f"{swf.name} header says {declared} bytes but file is {actual} "
                "- rewrite the length field after editing an uncompressed SWF",
            )

            # Editing images with FFDec rewrites the whole file, so the tag
            # stream is worth re-checking: the AOT stub and the symbol table
            # are what the app actually needs to still be there.
            blob = swf.read_bytes()
            tags = walk_swf_tags(blob)
            check(len(tags) == 196, f"{swf.name} has {len(tags)} tags, expected 196")
            check(
                any(tag == 76 for tag, _ in tags),
                f"{swf.name} lost its SymbolClass tag",
            )
            abc = [length for tag, length in tags if tag == 82]
            check(
                abc == [29],
                f"{swf.name} DoABC2 tags are {abc}, expected exactly one of 29 bytes",
            )
            check(
                AOT_STUB in blob,
                f"{swf.name} no longer carries the AOT DoABC2 stub",
            )

    # --- Mod menu pages ---------------------------------------------------
    mod_ui = ROOT / "mod-ui"
    dylibs = sorted(app.glob("Mod*.dylib"))
    check(bool(dylibs), "no Mod*.dylib found in the bundle")

    for dylib in dylibs:
        blob = dylib.read_bytes()
        check(blob[:4] in MACHO_MAGIC, f"{dylib.name} is not a Mach-O binary")

        start = blob.find(b"<!DOCTYPE html>")
        if not check(start >= 0, f"{dylib.name} has no embedded menu page"):
            continue
        end = blob.find(b"\x00", start)
        if not check(end > start, f"{dylib.name} menu page is not NUL-terminated"):
            continue
        page = blob[start:end]

        source = mod_ui / f"{dylib.stem}.html"
        if check(source.is_file(), f"mod-ui/{source.name} is missing"):
            check(
                page == source.read_bytes(),
                f"{dylib.name} menu page differs from mod-ui/{source.name} "
                "- run Scripts/patch-mod-menu.py",
            )

        text = page.decode("utf-8", errors="replace")
        kana = [c for c in text if "぀" <= c <= "ヿ"]
        check(not kana, f"{dylib.name} menu page still contains Japanese kana")
        check(
            "resolveBase" in text,
            f"{dylib.name} menu page is missing the guarded address lookup",
        )

    # --- Injected dylibs are still referenced -----------------------------
    if exe_path.is_file():
        exe = exe_path.read_bytes()
        for dylib in dylibs:
            check(
                f"@executable_path/{dylib.name}".encode() in exe,
                f"{exe_name} no longer loads {dylib.name}",
            )

    return report()


def report() -> int:
    if failures:
        print("bundle contract FAILED")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("bundle contract OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
