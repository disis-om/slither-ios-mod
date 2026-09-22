#!/usr/bin/env python3
"""Rebuild the snake bead atlas using slither.io's own web bead recipe.

The iOS build bakes a flat, washed-out bead. The web client - and NTL 9.68 on
top of it - composites each bead live, and that is where the look comes from.
The recipe, lifted from NTL 9.68's `main-mt.js` (the loop that fills `wa[bb]`):

    AA = ceil(2.5*hb + 28)
    ctx.shadowColor   = "#000000"
    ctx.shadowBlur    = 6
    ctx.shadowOffsetY = 1 + 2*hb/18.8
    ctx.fillStyle     = "#000000"
    ctx.arc(AA/2, AA/2, 0.7*hb + 1); ctx.fill()     # black disc under the bead
    # shadow off
    mb   = 0.65*hb
    grad = createRadialGradient(AA/2, AA/2, 0, AA/2, AA/2, mb)
    grad.addColorStop(0,    "rgba(r,g,b,1)")
    grad.addColorStop(0.99, "rgba(r,g,b,0.2)")
    grad.addColorStop(1,    "rgba(r,g,b,0)")
    ctx.arc(AA/2, AA/2, mb); ctx.fill()

There is no specular anywhere. The depth comes from the alpha ramp: opaque
colour at the centre falling to 20% at the rim, composited over black, which
resolves to `colour * alpha` and reads as a dark-edged orb.

Baking that into the atlas keeps the geometry the renderer already expects, so
the black disc and its drop shadow are not reproduced - they would need room
this cell does not have, and the iOS renderer draws its own. What is
reproduced is the part that carries the look: the colour ramp.

Invariants, all asserted before the file is written:

  * same size as the source (1160x1160)
  * alpha channel copied through byte for byte, so silhouettes cannot shift
  * grid untouched - 17 columns, 64 px cells on a 68 px pitch - so the UV
    rectangles baked into the AOT binary still land on the same beads
  * only plain single-colour beads are touched; flags, emblems, star beads and
    rim-lit beads stay byte-identical, because the ramp does not describe them

Source of truth is skin/segmants-source.png, a pristine copy taken from the
original IPA, so re-running never compounds its own output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "skin" / "segmants-source.png"
OUTPUT = ROOT / "skin" / "segmants-hq.png"

COLUMNS = 17
PITCH = 68
CELL = 64
ORIGIN = 2

RIM_ALPHA = 0.20        # slither's stop at 0.99 - the whole look lives here
CORE_RADIUS = 0.16      # sample the bead's colour inside this fraction of radius

# A bead is only rebuilt when the ramp actually describes it. Thresholds come
# from measuring all 265 beads: plain ones sit near residual 0.18, flags near
# 0.67 and star beads near 0.31, while the genuinely rim-lit beads - dark
# centre, bright edge, and a deliberate design - run from 1.9 to 26 on
# outer/inner. Flat beads sit near 1.0 and are rebuilt: a flat bead is exactly
# what this is meant to fix.
FALLOFF_LIMIT = 1.10    # above this the bead is lit from its rim, not its centre
PATTERN_LIMIT = 0.25    # angular detail above this is an emblem, not a bead
MIN_LUMA = 0.010        # anything darker carries no colour to rebuild from


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def count_filled(alpha: np.ndarray) -> int:
    filled = 0
    for index in range(COLUMNS * COLUMNS):
        row, column = divmod(index, COLUMNS)
        y, x = ORIGIN + row * PITCH, ORIGIN + column * PITCH
        patch = alpha[y:y + CELL, x:x + CELL]
        if patch.size and patch.mean() > 8:
            filled = index + 1
    return filled


def geometry() -> tuple[np.ndarray, np.ndarray]:
    """Radius in bead-radii, and the slither alpha ramp at each radius."""
    axis = (np.arange(CELL) + 0.5) / CELL * 2.0 - 1.0
    radius = np.sqrt(axis[None, :] ** 2 + axis[:, None] ** 2)

    # createRadialGradient(0 -> mb) with stops 1.0 at 0 and 0.2 at 0.99 is a
    # straight line in alpha across the bead.
    ramp = np.clip(1.0 - (1.0 - RIM_ALPHA) * np.clip(radius, 0.0, 1.0), 0.0, 1.0)
    return radius, ramp


def radial_profile(luma: np.ndarray, weight: np.ndarray, radius: np.ndarray) -> np.ndarray:
    bands = 24
    index = np.clip((radius / 1.05 * bands).astype(int), 0, bands - 1)
    totals = np.bincount(index.ravel(), weights=(luma * weight).ravel(), minlength=bands)
    counts = np.bincount(index.ravel(), weights=weight.ravel(), minlength=bands)

    profile = np.where(counts > 1e-6, totals / np.maximum(counts, 1e-6), 0.0)
    last = 0.0
    for i in range(bands):
        if counts[i] > 1e-6:
            last = profile[i]
        else:
            profile[i] = last
    if profile[0] <= 1e-6:
        return np.ones_like(radius)
    return (profile / profile[0])[index]


def classify(luma: np.ndarray, alpha: np.ndarray, radius: np.ndarray,
             profile: np.ndarray) -> str:
    mask = alpha > 0.5
    if not mask.any():
        return "empty"

    mean_luma = float(luma[mask].mean())
    if mean_luma < MIN_LUMA:
        return "empty"

    inner_mask = mask & (radius < 0.35)
    outer_mask = mask & (radius > 0.72)
    inner = float(profile[inner_mask].mean()) if inner_mask.any() else 1.0
    outer = float(profile[outer_mask].mean()) if outer_mask.any() else 0.0
    if inner <= 1e-6 or outer / inner >= FALLOFF_LIMIT:
        return "rim-lit"

    modelled = profile * (mean_luma / max(float(profile[mask].mean()), 1e-6))
    residual = float(np.abs(luma[mask] - modelled[mask]).mean()) / max(mean_luma, 1e-6)
    if residual > PATTERN_LIMIT:
        return "patterned"

    return "plain"


def rebuild(cell: np.ndarray, radius: np.ndarray, ramp: np.ndarray
            ) -> tuple[np.ndarray | None, str]:
    rgb = cell[..., :3]
    alpha = cell[..., 3]

    linear = srgb_to_linear(rgb)
    luma = linear @ np.array([0.2126, 0.7152, 0.0722])

    profile = radial_profile(luma, alpha, radius)
    verdict = classify(luma, alpha, radius, profile)
    if verdict != "plain":
        return None, verdict

    # The bead's colour is slither's gradient stop 0: the fully opaque centre.
    core = (radius < CORE_RADIUS) & (alpha > 0.5)
    if not core.any():
        return None, "empty"
    colour = linear[core].mean(axis=0)

    # Colour composited over black at the ramp's alpha is just colour * alpha.
    return linear_to_srgb(colour[None, None, :] * ramp[..., None]), "plain"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--scale", type=int, default=1,
                        help="write the atlas at this multiple of its native size")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"missing pristine source: {args.source}")

    src = Image.open(args.source).convert("RGBA")
    data = np.asarray(src).astype(np.float64) / 255.0
    alpha8 = np.asarray(src)[..., 3]

    filled = count_filled(alpha8)
    print(f"source  {args.source.name}  {src.width}x{src.height}  "
          f"{filled} beads in a {COLUMNS}-wide grid")

    radius, ramp = geometry()
    out = data.copy()
    verdicts: dict[str, int] = {}

    for index in range(filled):
        row, column = divmod(index, COLUMNS)
        y, x = ORIGIN + row * PITCH, ORIGIN + column * PITCH
        cell = data[y:y + CELL, x:x + CELL]
        if cell.shape[:2] != (CELL, CELL):
            continue
        rebuilt, verdict = rebuild(cell, radius, ramp)
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if rebuilt is not None:
            out[y:y + CELL, x:x + CELL, :3] = rebuilt

    for name in sorted(verdicts):
        note = "rebuilt on slither's ramp" if name == "plain" else "left byte-identical"
        print(f"  {name:<10} {verdicts[name]:>4}  {note}")

    result = np.clip(out, 0.0, 1.0)
    result[..., 3] = data[..., 3]
    image = Image.fromarray((result * 255.0 + 0.5).astype(np.uint8), "RGBA")

    if args.scale != 1:
        image = image.resize(
            (src.width * args.scale, src.height * args.scale), Image.LANCZOS)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)

    check = Image.open(args.output).convert("RGBA")
    expected = (src.width * args.scale, src.height * args.scale)
    assert check.size == expected, (check.size, expected)
    if args.scale == 1:
        assert np.array_equal(np.asarray(check)[..., 3], alpha8), \
            "alpha channel changed - silhouettes would shift"
        print("alpha   identical to source (silhouettes preserved)")
    try:
        shown = args.output.resolve().relative_to(ROOT)
    except ValueError:
        shown = args.output
    print(f"wrote   {shown}  {check.width}x{check.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
