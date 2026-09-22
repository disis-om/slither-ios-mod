#!/usr/bin/env python3
"""Write the rebuilt bead atlas into the bundle's SWF.

skin/ holds the source images; this puts them into the SWF's character tags
with JPEXS FFDec. The replacement is by character id, and the image keeps the
source's dimensions, so nothing the renderer depends on moves.

FFDec exits non-zero on this SWF whatever happens, because it cannot parse the
AOT DoABC2 stub while walking the tags (see docs/AUDIT.md). The exit code is
therefore not the result: the output file is checked instead.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIN = ROOT / "skin"

# character id -> (source image, what it is)
REPLACEMENTS = {
    35: (SKIN / "segmants-hq.png", "snake bead atlas"),
}

DEFAULT_FFDEC = Path(
    os.environ.get("FFDEC_JAR")
    or Path.home() / "Downloads" / "ffdec_26.2.1" / "ffdec-cli.jar"
)


def find_swf() -> Path:
    apps = sorted((ROOT / "extracted" / "Payload").glob("*.app"))
    if len(apps) != 1:
        raise SystemExit(f"expected one .app under extracted/Payload, found {len(apps)}")
    swfs = sorted(apps[0].glob("*.swf"))
    if len(swfs) != 1:
        raise SystemExit(f"expected one top-level .swf, found {len(swfs)}")
    return swfs[0]


def swf_length_field(path: Path) -> tuple[bytes, int]:
    head = path.read_bytes()[:8]
    return head[:3], int.from_bytes(head[4:8], "little")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atlas", type=Path, default=None,
                        help="bead atlas to inject instead of skin/segmants-hq.png")
    args = parser.parse_args()
    if args.atlas is not None:
        REPLACEMENTS[35] = (args.atlas, "snake bead atlas")

    ffdec = DEFAULT_FFDEC
    if not ffdec.is_file():
        raise SystemExit(f"FFDec not found at {ffdec}; set FFDEC_JAR to its path")

    missing = [str(src) for src, _ in REPLACEMENTS.values() if not src.is_file()]
    if missing:
        raise SystemExit("missing source image(s): " + ", ".join(missing))

    swf = find_swf()
    before = swf.stat().st_size

    args: list[str] = []
    for character, (source, label) in sorted(REPLACEMENTS.items()):
        print(f"replace character {character}  <- {source.name}  ({label})")
        # lossless2 keeps the tag as DefineBitsLossless2, which is what it is.
        args += [str(character), str(source), "lossless2"]

    with tempfile.TemporaryDirectory() as workdir:
        out = Path(workdir) / "patched.swf"
        subprocess.run(
            ["java", "-Xmx8g", "-jar", str(ffdec), "-replace", str(swf), str(out), *args],
            capture_output=True, text=True,
        )

        if not out.is_file() or out.stat().st_size < before // 2:
            raise SystemExit("FFDec did not produce a usable SWF")

        signature, declared = swf_length_field(out)
        actual = out.stat().st_size
        if signature != b"FWS":
            raise SystemExit(f"output SWF has signature {signature!r}, expected FWS")
        if declared != actual:
            raise SystemExit(
                f"output SWF header says {declared} bytes but the file is {actual}")

        shutil.move(str(out), str(swf))

    after = swf.stat().st_size
    print(f"wrote   {swf.name}  {before} -> {after} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
