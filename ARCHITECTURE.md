# slither.io iOS mod — how it works

The docs for this project are [README.md](README.md) (start there) and this file. This file joins the four earlier docs — audit, mod menu, skins, and building/testing — into one (2026-09-27); their text is unchanged. When the code or pipeline changes, fix the matching part here.

- [Part 1 — Audit: why there is no game source](#part-1)
- [Part 2 — Mod menu](#part-2)
- [Part 3 — Skins and in-game art](#part-3)
- [Part 4 — Building and testing](#part-4)


<a id="part-1"></a>
# Part 1 — Audit: why there is no game source

## IPA audit: `TabemaruModV3-TsEdited-1.ipa`

Read-only teardown of the shipped IPA, recording what the package actually
contains and which parts can be edited. Everything below was observed from the
file itself, not assumed.

### Package identity

| Field | Value |
| --- | --- |
| Source file | `TabemaruModV3-TsEdited-1.ipa` (49,963,285 bytes) |
| Bundle | `Payload/slither.io.app` |
| `CFBundleIdentifier` | `com.hypah.io.TabemaruMod` |
| AIR descriptor `<id>` | `com.hypah.io.slither` |
| Version | 2.1.2 (`CFBundleVersion` 2.1.2) |
| Minimum iOS | 10.0 |
| Device family | iPhone + iPad |
| Built against | `iphoneos18.2` |
| Required capabilities | `arm64`, `opengles-2` |
| Signed by | esign (`SignedByEsign` marker, `esign.yyyue.xyz`) |

The bundle identifier and the AIR descriptor id disagree. The descriptor still
carries the original `com.hypah.io.slither`, while `Info.plist` was rewritten to
`com.hypah.io.TabemaruMod`. That is consistent with a repack-and-resign chain
rather than a rebuild from source, and it is harmless — iOS reads `Info.plist`.

### What the app is

An **Adobe AIR 51.1 (HARMAN) application**, not a native Swift/Objective-C app.

- `META-INF/AIR/application.xml` — AIR descriptor, `renderMode` `direct`,
  portrait, fullscreen, content `slither ios.swf`.
- Four ANEs: `com.distriqt.Core`, `com.distriqt.Application`,
  `com.distriqt.ApplicationRater`, `com.distriqt.InAppBilling`.
- `slither ios.swf` (35,535,345 bytes) — uncompressed `FWS` v51, 196 tags.
- `slither.io` (13,981,264 bytes) — Mach-O arm64 executable; the AIR runtime.

### The critical finding: there is no ActionScript bytecode in the SWF

The SWF's single `DoABC2` tag (tag index 192, tag id 82) is **29 bytes long**:

```
01 00 00 00  00                          flags + empty name
00 00 00 00 e7 34 87 22 1d e8 5a e5      24-byte stub, not ABC
e4 ca af d5 42 c4 b4 80 e5 9c 9f 5f
```

JPEXS FFDec 26.2.1 rejects it:

```
SEVERE: Error during tag reading. ID: 82 name: Unresolved (tcl: DoABC2, tid: 82)
com.jpexs.decompiler.flash.abc.ABCOpenException: Invalid ABC file.
Caused by: com.jpexs.decompiler.flash.EndOfStreamException: Premature end of the stream
```

`-export script` therefore produces **zero** `.as` files. This is not a tooling
problem and not encryption that a key would open.

It is how AIR packages for iOS. Apple forbids runtime bytecode execution, so
ADT **AOT-compiles the ActionScript to native ARM64 and strips the ABC out of
the SWF**, leaving a hash-sized stub. The compiled code lives in the Mach-O
executable — confirmed by scanning `slither.io` for strings:

- `slitherios_fla`, `slitherios_fla:MainTimeline` — the game's own class names
- `avmplus!http://adobe.com/AS3/2006/builtin`, 660 `flash.*` type names
- `com.harman.air.SwfCompress`, `https://api.airsdk.harman.com/adtlicensing`

**Consequence: the game logic of this IPA cannot be recovered as source.** It is
native ARM64. The only ways in are disassembly (Ghidra/IDA) or binary patching.

### What *is* editable, and how

#### 1. SWF assets — fully editable

The SWF keeps every asset. Exported to `assets/`:

| Kind | Count | Format |
| --- | --- | --- |
| Images (`DefineBitsLossless2`) | 160 | PNG |
| Fonts | 4 | TTF |
| Shapes | 1 | SVG |
| Sprites | 2 | PNG |
| Texts | 5 | TXT |
| Symbol→class map | 1 | `symbols.csv` (165 entries) |

`symbols.csv` names every asset the AOT code looks up — `bg_asanoha`,
`bgee_classic`, `a_3dglass`, `a_crown`, `argentina`, `arrowmode_png`, and so on.
Skins, backgrounds, accessories, flags and UI art all live here, and FFDec can
replace any of them in place (`-replace`) without touching code.

#### 2. `Info.plist` and the AIR descriptor — fully editable

App name, bundle id, version, device family, ATS exceptions, orientation,
SKAdNetwork entries. Plain plist/XML edits.

#### 3. Icons and launch images — fully editable

`Icon*.png`, `Default*.png`, `Assets.car`.

#### 4. The injected mod dylibs — native

`Mod1.dylib` and `Mod2.dylib` (3,406,784 bytes each, different SHA, Mach-O
arm64 dylibs) are the Tabemaru mod's own code, injected into the load commands.
Same story as the main binary: ARM64, no source.

#### 5. The Mach-O executable — native, patch-only

`slither.io` holds the AOT-compiled game. Changing behaviour means patching
instructions or hooking via a dylib, not editing source.

### Summary

| Layer | Editable as source | Notes |
| --- | --- | --- |
| Game logic | No | AOT ARM64 inside `slither.io` |
| Mod behaviour | No | AOT ARM64 inside `Mod*.dylib` |
| Skins / backgrounds / UI art | Yes | 160 PNGs in the SWF |
| Fonts | Yes | 4 TTFs in the SWF |
| App metadata | Yes | `Info.plist`, AIR descriptor |
| Icons / launch screens | Yes | Bundle PNGs, `Assets.car` |
| Repackaging | Yes | Plain ZIP, see `BUILDING-AND-TESTING.md` |

### Tooling used

- JPEXS Free Flash Decompiler 26.2.1 (`C:\Users\Om Rajput\Downloads\ffdec_26.2.1`)
- Java 21 (Temurin 21.0.12)
- Python 3.12 for plist, Mach-O and string inspection

<a id="part-2"></a>
# Part 2 — Mod menu

## The mod menu: how it works, what was broken, what changed

### How the mod is wired up

`slither.io` weak-links four dylibs from its own directory:

```
LC_LOAD_WEAK_DYLIB  @executable_path/H5GG.dylib      (not in the bundle)
LC_LOAD_WEAK_DYLIB  @executable_path/H5GGmenu.dylib  (not in the bundle)
LC_LOAD_WEAK_DYLIB  @executable_path/Mod2.dylib
LC_LOAD_WEAK_DYLIB  @executable_path/Mod1.dylib
```

The first two are leftovers from an earlier injection round. They are weak
references, so dyld skips them silently instead of failing the launch.

`Mod1.dylib` and `Mod2.dylib` are both **H5GG** builds — a memory-editing
framework whose UI is a WKWebView page talking to a native `h5gg` JS bridge
(`searchNumber`, `getResults`, `getValue`, `setValue`). Each dylib carries one
custom HTML page as a NUL-terminated UTF-8 string at file offset `0x000b86c0`,
inside a 2 MB zero-filled buffer. That page is the whole mod:

| Dylib | Panel | Controls |
| --- | --- | --- |
| `Mod1.dylib` | Toggles | Remove background, hide boost effect, hide menu icon, lightweight food, lightweight score |
| `Mod2.dylib` | Zoom | `+` and `-` |

Because the page is a plain string in a buffer with ~2 MB of headroom, it can be
rewritten in place without relocating anything in the Mach-O. `mod-ui/` holds
those pages as editable files; `Scripts/patch-mod-menu.py` writes them back.

### How the cheats find memory

Both panels start the same way:

```js
h5gg.searchNumber('31337', 'F64', '0x270000000', '0x7100000000');
```

`31337` is a sentinel the mod author found sitting at a fixed distance from the
fields it wants. Everything is addressed relative to it:

| Offset from anchor | Field | Panel |
| --- | --- | --- |
| `-0x260` | background | Mod1 cb1 |
| `-0x2d8` | boost effect | Mod1 cb2 |
| `-0x368` | food detail | Mod1 cb4 |
| `-0x378` | **zoom** | Mod2 `+` / `-` |
| `-0x400` | score detail | Mod1 cb5 |

Each toggle then holds its value in place with a `setInterval` that rewrites the
address every 1-250 ms, because the game recomputes these fields every frame.

### The bug behind the "index error" popup

#### What you saw

A popup reading roughly:

```
JSError in:<page> line:<n> column:<n>

TypeError: undefined is not an object (evaluating 'results[0].address')
```

or, on tapping a zoom button:

```
ReferenceError: Can't find variable: baseAddress
```

That dialog is H5GG's own global handler — it turns any uncaught JS error into
an `alert()`:

```js
window.onerror = h5gg_js_error_handler = function(message, url, line, column, error) {
    ...
    alert('JSError in:' + fname + ' line:' + line + ' column:' + column + "\n\n" + message);
};
```

So the popup is not an iOS crash and not a signing problem. It is a JavaScript
exception inside the mod's own menu page.

#### Root cause

The zoom panel's original script did this at page load, at top level, with no
guard:

```js
h5gg.clearResults();
h5gg.searchNumber('31337', 'F64', '0x270000000', '0x7100000000');
let results = h5gg.getResults(1, 0);
baseAddress = results[0].address;     // <- throws when the scan found nothing
```

The anchor value `31337` only exists in memory **while a match is running**. Open
the menu on the title screen, or after dying, and the scan returns zero results.
`results` is then an empty array, `results[0]` is `undefined`, and reading
`.address` off it throws `TypeError: undefined is not an object`.

Three things follow from that one unguarded line:

1. **The rest of the script never runs.** An uncaught throw at top level stops
   the script, so `let plusLocker = null;`, `let minusLocker = null;`,
   `setWindowRect(...)` and `setWindowDrag(...)` — all of which came *after* the
   throwing line — never execute.
2. **`plus()` and `minus()` still exist**, because function declarations are
   hoisted and created before the script body runs. The buttons stay tappable.
3. **So tapping `+` throws a second, different error.** `plus()` starts with
   `if (plusLocker)`, but `plusLocker` is a `let` that was never initialised, so
   it sits in the temporal dead zone and Safari raises
   `ReferenceError: Cannot access uninitialized variable.` And `baseAddress`,
   never declared at all in that page, raises
   `ReferenceError: Can't find variable: baseAddress`.

That is why the popup appears **on tap** rather than on open: the first error
fires while the panel is still loading and is easy to miss, and the one you
actually notice is the knock-on failure that every tap produces afterwards.

A second trigger for the same crash: the search range is hardcoded to
`0x270000000`-`0x7100000000`. If the heap lands outside that window on a given
iOS version or device, the scan finds nothing even mid-match, and you get the
identical popup.

#### The fix

`mod-ui/Mod1.html` and `mod-ui/Mod2.html` were rewritten so that:

- **Window placement happens first.** `setWindowRect` / `setWindowDrag` now run
  at the top of the script, so a failed scan can no longer leave the panel
  unpositioned as well as broken.
- **The scan is wrapped in `resolveBase()`**, which checks
  `h5gg.getResultsCount()` and the returned array before indexing it, and
  returns `null` instead of throwing. The whole body sits inside `try`/`catch`.
- **The address is resolved lazily and re-resolved on demand.** Instead of one
  lookup at load time, each tap uses the cached address and, if it is missing,
  drops the cache and scans again. That also fixes the stale-pointer case after
  you die and respawn, where the anchor moves but the old code kept writing to
  the address it found at startup.
- **Every handler catches its own errors**, so nothing reaches `window.onerror`
  and no `alert()` can fire.
- **Failure is reported inside the panel**, as a small `Join a game first` line
  under the controls, instead of a modal popup.
- **All state is declared.** `baseAddress`, `plusLocker`, `minusLocker` and the
  Mod1 lockers are declared up front; previously `TwoLocker`, `FourLocker` and
  `FiveLocker` were implicit globals created on first assignment, which is why
  unchecking a box before ever checking it could throw on its own.
- **Toggles refuse to stick when they cannot work.** Checking a box with no
  anchor resolved now unchecks itself and shows the status line, rather than
  installing an interval that writes to `NaN`.

The memory offsets, the values written, the freeze intervals and the two base64
button images are all unchanged, so the cheats behave exactly as before.

#### What still needs a match to be running

The fix removes the crash, not the requirement. The anchor genuinely does not
exist outside a match, so: **start a game, then use the panel.** The difference
is that doing it in the wrong order now shows `Join a game first` instead of a
JavaScript error, and the panel recovers by itself once you are in a game.

### Translation

Both pages shipped in Japanese (`<html lang="ja">`). They are now English:

| Japanese | English |
| --- | --- |
| チェックボックス (title) | slither.io Mod |
| ボタンリスト (title) | Zoom |
| 背景削除 | Remove background |
| ダッシュエフェクト非表示 | Hide boost effect |
| アイコン非表示 | Hide menu icon |
| エサ軽量化 | Lightweight food |
| スコア軽量化 | Lightweight score |

`アイコン非表示` turned out to mean the mod's own floating button, not anything
in the game: the toggle swaps that button's image between a 150x150 fully
transparent PNG and its original artwork. It is labelled "Hide menu icon"
accordingly.

The in-code comments were Japanese too and are now English. The contract test
fails the build if any kana reappears in either page.

H5GG's own search UI — the one behind the floating button — was never Japanese.
It ships Chinese and English copies and picks by `navigator.language`, so it
already reads English on an English device.

### Known cosmetic oddity, left alone

`Mod1.html` styles the body with `transform: rotate(45deg) translate(0,50px)`,
while `Mod2.html` uses `rotate(90deg)`. The 90-degree rotation matches the
rotated landscape presentation; 45 looks like a typo in the original. It was
left exactly as shipped, because it has nothing to do with the crash and
changing it would move the UI under you. Change `45deg` to `90deg` in
`mod-ui/Mod1.html` if you want the two panels to match.

### Editing the menu yourself

```bash
python Scripts/patch-mod-menu.py
```

```bash
python Tests/bundle_contract_test.py
```

```bash
powershell -ExecutionPolicy Bypass -File Scripts/repack-ipa.ps1 -Name my-edit
```

Edit `mod-ui/Mod1.html` or `mod-ui/Mod2.html`, then run those three in order.
`Scripts/extract-mod-ui.py --force` re-reads the pages out of the dylibs if you
ever need to start again from what is actually installed.

<a id="part-3"></a>
# Part 3 — Skins and in-game art

## Skins: beads, the atlas, and the skin-code tool

### Where the beads live

`slither ios.swf` character **35**, class `segmants`, is the bead atlas:
1160x1160, a 17-column grid of 64 px cells on a 68 px pitch, 265 occupied
slots. The UV rectangles that index it are baked into the AOT binary, so the
image can be replaced but the geometry cannot move.

`sheet0_a_png` ... `sheet3_d_png` are the UI/accessory atlases at four mip
sizes (2048, 1024, 512, 256). The snake preview art in the menus is baked into
`sheet1_a_png`; the beads themselves are not in there.

### What the shipped beads looked like

A flat radial gradient with no highlight and no rim contrast - the centre
washed out, the edge fading to about half brightness. Compared with the web
game the snake reads as plastic and dull.

### slither.io's actual bead recipe

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

### What `Scripts/rebuild-bead-atlas.py` does

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

### Verification that nothing else moved

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

### The 2x atlas experiment

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

### The skin-code tool

#### Why it is built this way

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

#### The alphabet

One character per bead. The character's position in this string is its
colour-group index, taken from Wyrm's `ntl_cg_map`, which is the table NTL 9.68
uses - it is just the keyboard, row by row:

```
zxcvbnm,asdfghjklqwertyuiop123456789*0*-**
```

`*` marks a disabled group. Maximum length is 256 beads (`MAX_SKIN_CODE_LEN`).

#### Using it

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

#### What still needs your phone

Whether the game wants anything poked alongside the bytes - a length field or a
dirty flag - before Play picks the skin up. Building a skin by hand first puts
the game in custom-skin mode, which is what that step is for. If a code writes
successfully and still does not show, Locate around a manual bead edit and look
for a second field moving next to the array.

### Testing

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

<a id="part-4"></a>
# Part 4 — Building and testing

## Building and testing

The shape of this pipeline is copied from `Wyrm iOS`: Windows is the editing
machine, GitHub Actions produces the artifact, and the IPA ships **unsigned** so
the signer on the phone applies its own identity.

The one real difference is that nothing compiles here. `Wyrm iOS` builds Swift
and C into a `.app` with `xcodebuild` on a macOS runner. This project's `.app`
already exists and its code is AOT-compiled ARM64 inside the bundle (see
[AUDIT.md](#part-1)), so packaging is a ZIP and runs on `ubuntu-latest` in
about a minute, with no macOS runner and no Xcode.

### Build inputs

| Input | Path |
| --- | --- |
| Editable bundle | `extracted/Payload/slither.io.app` |
| Contract test | `Tests/bundle_contract_test.py` |
| Local packager | `Scripts/repack-ipa.ps1` |
| CI workflow | `.github/workflows/pack-ipa.yml` |
| Exported SWF assets | `assets/` |
| Output | `dist/` |

`extracted/` is the source of truth. Edit files in place there; every build
reads from it.

### Local build (Windows)

```bash
powershell -ExecutionPolicy Bypass -File Scripts/repack-ipa.ps1
```

Optionally name the output:

```bash
powershell -ExecutionPolicy Bypass -File Scripts/repack-ipa.ps1 -Name slither-skinpack-v1
```

The script stages a copy so `extracted/` is never mutated, drops the stale
`_CodeSignature` and `embedded.mobileprovision`, writes
`dist/<name>.ipa` plus a `.sha256` file, and prints the hash.

It writes ZIP entries by hand rather than using
`ZipFile::CreateFromDirectory`, because Windows PowerShell emits backslash
separators there and iOS installers reject those paths.

Pass `-KeepSignature` to leave the original signature files in place; useful
only when you changed nothing that invalidates them.

### CI build

The workflow runs on pushes to `main` that touch `extracted/`, `Tests/` or the
workflow itself, and can be started by hand with an optional label:

```bash
gh workflow run pack-ipa.yml -f label=skinpack
gh run list --workflow pack-ipa.yml --limit 5
gh run watch <run-id> --exit-status
gh run download <run-id> -n slither-ios-ipa-<run-number> -D dist/<named-folder>
```

Steps:

1. Checkout with Git LFS.
2. Run the bundle contract test.
3. Read bundle id, version and build number out of `Info.plist`.
4. Stage the payload, drop the stale signature, ZIP it.
5. Write `SHA256SUMS` and a run summary table.
6. Upload `dist/*.ipa` and `SHA256SUMS` as a workflow artifact.

Artifacts are named `slither-ios-<version>-<label>-<run>-unsigned.ipa`. The
version is read from the bundle, so bumping `CFBundleShortVersionString` is
enough — there is no version string to keep in sync inside the workflow.

### The contract test

`Tests/bundle_contract_test.py` runs in CI before packaging and is worth
running locally after any edit:

```bash
python Tests/bundle_contract_test.py
```

It checks that `Payload/` holds exactly one `.app`; that `Info.plist` parses and
carries a sane bundle id, executable, name, version and minimum iOS; that
`CFBundleExecutable` exists and is Mach-O; that the AIR descriptor is present
with a `<content>` entry; and that exactly one top-level `.swf` is present with
a valid signature and a header length field matching its real size.

That last check matters. `slither ios.swf` is uncompressed (`FWS`), and bytes
5–8 of an uncompressed SWF are the total file length. Editing the SWF with a
hex editor without rewriting that field produces a bundle that installs and
then fails to start. FFDec's `-replace` rewrites it for you.

### Proving nothing else changed

The bundle is a shipped, working app; the safest edit is the smallest one. Two
checks keep it that way.

`Scripts/verify-against-source-ipa.py` diffs the working bundle against the IPA
it was unpacked from and prints every file that differs, how its size and hash
changed, and the exact byte range that moved:

```bash
python Scripts/verify-against-source-ipa.py
```

Anything it lists that you did not intend to change is a mistake to fix before
packaging. After the mod menu rewrite it reports exactly two modified files,
both `Mod*.dylib`, both the same size as before, with every changed byte inside
the HTML page buffer at `0x000b86c0` - no Mach-O header, load command or code
section touched, and `slither ios.swf` and the `slither.io` executable
byte-identical to the original.

`Scripts/check-mod-ui-js.py` parses the JavaScript in each `mod-ui/*.html` with
`node --check`:

```bash
python Scripts/check-mod-ui-js.py
```

A syntax error there would not fail the build or the install - it would fail
silently on the phone, as a dead panel or an error popup. Both the local build
and CI run this before packaging.

### Editing the assets

Assets were exported to `assets/` for browsing. To change one, replace it
inside the SWF rather than editing the export — the export is a copy, and
nothing reads it at runtime.

```bash
java -Xmx6g -jar "C:\Users\Om Rajput\Downloads\ffdec_26.2.1\ffdec-cli.jar" \
  -replace "extracted/Payload/slither.io.app/slither ios.swf" \
           "out.swf" \
  126 new-image.png lossless2
```

Write to a new file, check it, then move it over the bundle copy. Replacing in
place leaves you nothing to fall back on if the run goes wrong.

Character ids come from `assets/symbolClass/symbols.csv`, which maps each id to
the class name the game looks up (`bg_asanoha`, `a_crown`, `argentina`, …). The
exported filenames in `assets/images/` carry the same id as a prefix, so
`126_arrowmode_png.png` is character 126. The bundle's images are
`DefineBitsLossless2`, so pass `lossless2` as the format to keep them that way.

**Gotcha: FFDec exits with code 1 on this SWF even when the replace succeeds.**
It logs `ABCOpenException: Invalid ABC file` while walking the tags, because of
the AOT stub described in [AUDIT.md](#part-1). It still writes a correct SWF.
Do not treat the exit code as the result - check the output file instead. A
verified round-trip on this bundle preserved all 196 tags, left the `DoABC2`
stub and the `SymbolClass` table byte-identical, and rewrote the uncompressed
header length field to match the new size.

After replacing, re-run the contract test, then repack.

### Signing and installing

The IPA is unsigned by design, exactly as in `Wyrm iOS`. Use whichever signer
you already use:

- **esign** — matches how this IPA was signed before (it carries a
  `SignedByEsign` marker).
- **AltStore** — applies your Apple ID signature and provisioning profile at
  install time; AltServer must see the iPhone over USB or trusted Wi-Fi sync.
- **Sideloadly** — same idea from a desktop.

A successful install is not acceptance. Record install, launch, first frame,
touch/boost, live join, death/replay, background/resume, and whatever visual
change you made, before treating a build as good.

### Git and large files

`extracted/` contains a 35 MB SWF and a 14 MB Mach-O binary. Both sit well
under GitHub's 100 MB per-file limit, so they are committed normally - no Git
LFS, no quota to manage. `.gitattributes` marks them binary so git never tries
to diff or normalise their bytes.

`assets/` and the input `.ipa` are gitignored. The first is regenerated by
`Scripts/export-assets.ps1`, and the second is an input you keep locally.

### What this pipeline cannot do

It cannot change game logic. The ActionScript was AOT-compiled to ARM64 and
stripped from the SWF; there is no source to edit and no compile step to run.
Changing behaviour means patching the Mach-O or shipping a hook dylib, which is
outside this pipeline. See [AUDIT.md](#part-1) for the evidence.
