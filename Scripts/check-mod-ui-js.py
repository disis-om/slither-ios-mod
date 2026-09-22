#!/usr/bin/env python3
"""Parse the JavaScript inside mod-ui/*.html with Node.

A syntax error in a menu page does not fail the build or the install - it
fails silently on the phone, as a dead panel or an error popup. This catches
it on the desk instead.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD_UI = ROOT / "mod-ui"
SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def main() -> int:
    pages = sorted(MOD_UI.glob("*.html"))
    if not pages:
        print("no pages in mod-ui/")
        return 1

    failed = False
    for page in pages:
        html = page.read_text(encoding="utf-8")
        blocks = SCRIPT_RE.findall(html)
        if not blocks:
            print(f"{page.name}: no <script> block found")
            failed = True
            continue

        for index, body in enumerate(blocks):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".js", delete=False, encoding="utf-8"
            ) as handle:
                handle.write(body)
                temp = Path(handle.name)
            try:
                result = subprocess.run(
                    ["node", "--check", str(temp)],
                    capture_output=True, text=True,
                )
            finally:
                temp.unlink(missing_ok=True)

            label = f"{page.name} script #{index + 1}"
            if result.returncode == 0:
                print(f"ok   {label} ({len(body)} chars)")
            else:
                print(f"FAIL {label}")
                print(result.stderr.strip())
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
