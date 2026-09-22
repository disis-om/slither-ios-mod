# Skins: beads, the atlas, and the skin-code tool

## Where the beads live

`slither ios.swf` character **35**, class `segmants`, is the bead atlas:
1160x1160, a 17-column grid of 64 px cells on a 68 px pitch, 265 occupied
slots. The UV rectangles that index it are baked into the AOT binary, so the
image can be replaced but the geometry cannot move.

`sheet0_a_png` ... `sheet3_d_png` are the UI/accessory atlases at four mip
sizes (2048, 1024, 512, 256). The snake preview art in the menus is baked into
`sheet1_a_png`; the beads themselves are not in there.

## What the shipped beads looked like

A flat radial gradient with no highlight and no rim contrast - the centre
washed out, the edge fading to about half brightness. Compared with the web
game the snake reads as plastic and dull.

## slither.io's actual bead recipe

The iOS build bakes one static bead. The web client - and NTL 9.68 on top of
it - composites each bead live, every frame, and that is where the look comes
from. From NTL 9.68's `main-mt.js`, the loop that fills `wa[bb]`:

```js
AA = Math.ceil(2.5*hb + 28)
ctx.shadowColor   = "#000000"
ctx.shadowBlur    = 6
ctx.shadowOffsetY = 1 + 2*hb/18.8
ctx.fillStyle     = "#000000"
ctx.arc(AA/2, AA/2, 0.7*hb + 1); ctx.fill()      // black disc under the bead
// shadow off
mb   = 0.65*hb
grad = ctx.createRadialGradient(AA/2, AA/2, 0, AA/2, AA/2, mb)
grad.addColorStop(0,    "rgba(r,g,b,1)")
grad.addColorStop(0.99, "rgba(r,g,b,0.2)")
grad.addColorStop(1,    "rgba(r,g,b,0)")
ctx.arc(AA/2, AA/2, mb); ctx.fill()
```

There is no specular highlight anywhere, which is the thing most people get
wrong when they try to "improve" these. The depth is entirely the alpha ramp:
opaque colour at the centre falling to 20% at the rim, over black. Composited,
that is just `colour * alpha`, and it reads as a dark-edged orb.

NTL ships no bead images of its own - `ntl 9.68/s/` is accessories, flags and
tags, and `highquality.webp` is the 180x174 icon for the quality setting, not
an atlas. So there was nothing to copy across; the recipe had to be lifted from
the code and baked.

## What `Scripts/rebuild-bead-atlas.py` does

Reads `skin/segmants-source.png` - a pristine copy taken from the original IPA,
so re-running never compounds its own output - and writes
`skin/segmants-hq.png`.

For each bead it measures the shipped shading's radial luminance profile,
divides it out to recover a flat albedo, takes the fully opaque centre as
slither's gradient stop 0, and re-lays the ramp over it.

It refuses to touch a bead the ramp does not describe. Classification is
measured, not guessed:

| Verdict | Count | Rule | Action |
| --- | --- | --- | --- |
| plain | 140 | normal centre-out falloff, low angular detail | rebuilt on the ramp |
| patterned | 74 | angular residual > 0.25 - flags, emblems, star beads | artwork kept, black rim added |
| rim-lit | 41 | outer/inner brightness >= 1.10 - dark centre by design | byte-identical |
| empty | 10 | no colour to rebuild from | byte-identical |

Asserted before the file is written:

* output is the same size as the source
* the alpha channel is copied through byte for byte, so no silhouette shifts
* the grid is untouched, so the baked UVs still land on the same beads

## Verification that nothing else moved

Injecting the atlas makes FFDec rewrite the whole SWF, so a byte diff of the
file is meaningless. What matters is the rendered content, and that was checked
directly: all 160 images were exported from the patched SWF and compared
against the pristine exports.

```
pristine images: 160   in patched swf: 160
names identical: True
images whose rendered pixels changed: 1
    35_segmants.png
```

One image changed. The other 159 are pixel-identical after premultiplication
(max difference 1.8/255, which is the premultiplied-alpha round trip, invisible).

The tag stream was checked too, and `Tests/bundle_contract_test.py` now
enforces it on every build: 196 tags, one `DoABC2` of exactly 29 bytes still
carrying the AOT stub, and the `SymbolClass` table byte-identical.

## The 2x atlas experiment

`Scripts/rebuild-bead-atlas.py --scale 2` writes a 2320x2320 atlas with 128 px
cells, shipped as a separate IPA labelled `atlas2x`.

**It will probably render wrong, and that is the point of shipping it
separately.** Starling addresses a sub-texture by a pixel rectangle, and those
rectangles are compiled into the ARM64 binary. On a 2320 px atlas a rectangle
of `(2, 2, 64, 64)` still reads the first 64 px, so every snake would wear the
top-left bead. It only works if the code derives its UVs from the texture's
dimensions, which is not how this is usually written.

Worth knowing before spending time on it: for the rebuilt beads the extra
resolution buys very little anyway. They are now a mathematically smooth linear
ramp, so 64 px already resolves them without stepping or aliasing. Only the
flags and emblems would gain. Install it, look at one snake, and if the beads
are wrong just go back to the normal build.

## The skin-code tool

### Why it is built this way

slither.io's iOS build already has a skin builder - the "Build a Slither"
button - and slither's protocol already carries custom skins: Wyrm's
`network/callback.c` shows the login packet taking a run-length encoded
`(count, colour-group id)` list, which the server relays so every client draws
the exact beads.

So there is nothing to add to the protocol, and nothing to add to the renderer.
The only missing piece is a way to type a code instead of tapping beads. The
tool therefore does the smallest possible thing: **it writes the same bytes the
builder writes, and then you press the game's own OK.** Everything after that
is the game's own code path, unchanged.

### The alphabet

One character per bead. The character's position in this string is its
colour-group index, taken from Wyrm's `ntl_cg_map`, which is the table NTL 9.68
uses - it is just the keyboard, row by row:

```
zxcvbnm,asdfghjklqwertyuiop123456789*0*-**
```

`*` marks a disabled group. Maximum length is 256 beads (`MAX_SKIN_CODE_LEN`).

### Using it

Build any skin once in Build a Slither, so the game is in custom-skin mode.
After that, in the **Skin code** tab: type a code, press **ON**, press Play.
That is the whole flow.

**ON** finds the skin array itself. Every byte of a skin is a colour-group
index, so the array shows up as a long run of small numbers inside a struct
that is otherwise doubles and pointers - long runs of bytes below 42, carrying
at least one non-zero value and at least 24 entries. Candidates are tried
longest first; each one is written and then **read back**, and a region that
will not hold the bytes is not the skin, so the next candidate gets a turn
rather than the write failing silently.

**Read current** pulls the skin the game is holding back out as a code.

If the scan cannot pick the array out, the panel reveals a **Locate** fallback:
press it, change one bead in Build a Slither, press it again, and it keeps
whatever byte moved. That path only appears when it is needed.

### What still needs your phone

Whether the game wants anything poked alongside the bytes - a length field or a
dirty flag - before Play picks the skin up. Building a skin by hand first puts
the game in custom-skin mode, which is what that step is for. If a code writes
successfully and still does not show, Locate around a manual bead edit and look
for a second field moving next to the array.

## Testing

`Tests/mod_ui_logic_test.js` runs both panels' scripts under Node against a
fake H5GG host and a minimal DOM, in two states: a match running, and no match
at all. It covers the freeze toggles, the icon swap, tab switching, the skin
code round trip, rejection of characters outside the alphabet, the
snapshot/compare diff, and - the reason it exists - that nothing throws when
the memory scan comes back empty.

```bash
node Tests/mod_ui_logic_test.js
```

It runs in CI and in `Scripts/repack-ipa.ps1` before anything is packaged.

`Scripts/preview-snake.py` renders overlapping beads from one or more atlases
so a change can be judged the way it will actually be seen:

```bash
python Scripts/preview-snake.py skin/segmants-source.png skin/segmants-hq.png --out out.png
```
