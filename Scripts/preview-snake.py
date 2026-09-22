#!/usr/bin/env python3
"""Render overlapping beads as a snake body, for comparing atlases.

A single bead tells you almost nothing about how the snake reads. The beads
overlap heavily in game, so what matters is whether consecutive beads separate
from each other - which is the job of the dark rim.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
COLUMNS, PITCH, CELL, ORIGIN = 17, 68, 64, 2


def bead(atlas: Image.Image, index: int) -> Image.Image:
    row, column = divmod(index, COLUMNS)
    x, y = ORIGIN + column * PITCH, ORIGIN + row * PITCH
    return atlas.crop((x, y, x + CELL, y + CELL))


def strip(atlas: Image.Image, indices: list[int], size: int, step: int,
          width: int, height: int) -> Image.Image:
    """Lay beads along a sine wave, back to front, the way the game does."""
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    count = (width - size) // step + 1
    for i in range(count):
        x = i * step
        y = height / 2 + np.sin(i / 7.0) * (height / 4.5) - size / 2
        piece = bead(atlas, indices[i % len(indices)]).resize((size, size), Image.LANCZOS)
        out.alpha_composite(piece, (int(x), int(y)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("atlases", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--beads", default="0,1,2,3",
                        help="comma separated bead indices to cycle through")
    parser.add_argument("--size", type=int, default=46)
    parser.add_argument("--step", type=int, default=11)
    parser.add_argument("--bg", default="20,26,20")
    args = parser.parse_args()

    indices = [int(v) for v in args.beads.split(",")]
    width, height = 900, 190
    background = tuple(int(v) for v in args.bg.split(",")) + (255,)

    panels = []
    for path in args.atlases:
        atlas = Image.open(path).convert("RGBA")
        panel = Image.new("RGBA", (width, height), background)
        panel.alpha_composite(strip(atlas, indices, args.size, args.step, width, height))
        panels.append((path.name, panel))

    canvas = Image.new("RGBA", (width, height * len(panels)), background)
    for i, (_, panel) in enumerate(panels):
        canvas.alpha_composite(panel, (0, i * height))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(args.out)
    print("rendered " + " | ".join(name for name, _ in panels) + f" -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
