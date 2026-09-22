# slither.io iOS — editable bundle and IPA pipeline

Working tree for editing the `TabemaruModV3-TsEdited-1.ipa` build of slither.io
for iOS and rebuilding it into an installable IPA, driven from Windows with
GitHub Actions doing the packaging — the same split `Wyrm iOS` uses.

## Read this first

The app is **Adobe AIR**, and AIR packages for iOS are AOT-compiled. The
ActionScript was turned into native ARM64 and stripped out of the SWF, so
**there is no game source to decompile** — a decompiler returns zero files, and
that is the format working as designed, not a broken tool.
[docs/AUDIT.md](docs/AUDIT.md) has the evidence.

What you *can* edit, and what this repo makes editable:

- **The mod menu.** Both injected dylibs store their whole UI as an HTML page
  with JavaScript. Those pages live in `mod-ui/` as ordinary files and get
  written back into the dylibs by a script. This is real, editable source.
- **In-game art.** 160 images inside the SWF — skins, backgrounds, accessories,
  flags, UI — plus 4 fonts.
- **App metadata, icons and launch screens.**

## Layout

| Path | What it is |
| --- | --- |
| `mod-ui/Mod1.html`, `mod-ui/Mod2.html` | The mod menu pages. **Edit these, not the dylibs.** |
| `extracted/Payload/slither.io.app/` | The unpacked bundle — the packaging source of truth |
| `Scripts/patch-mod-menu.py` | Writes `mod-ui/` back into the dylibs |
| `Scripts/extract-mod-ui.py` | Re-reads the pages out of the dylibs (`--force` to overwrite) |
| `Scripts/repack-ipa.ps1` | Local build: patch → test → unsigned IPA in `dist/` |
| `Scripts/rebuild-bead-atlas.py` | Rebuilds the bead atlas on slither's own ramp |
| `Scripts/apply-skin-atlas.py` | Injects `skin/` images into the SWF |
| `Scripts/preview-snake.py` | Renders overlapping beads, for judging an atlas |
| `Scripts/export-assets.ps1` | Regenerates `assets/` from the bundle's SWF |
| `Scripts/check-mod-ui-js.py` | Parses the menu JavaScript with `node --check` |
| `Scripts/verify-against-source-ipa.py` | Diffs the working bundle against the original IPA |
| `Tests/bundle_contract_test.py` | Pre-flight checks that catch a broken edit |
| `Tests/mod_ui_logic_test.js` | Runs both panels under Node against a fake H5GG |
| `skin/` | Bead atlas sources and the Mod1 page template |
| `.github/workflows/pack-ipa.yml` | CI build, uploads the IPA as an artifact |
| `docs/MOD-MENU.md` | How the mod works, the zoom crash, and the fix |
| `docs/SKINS.md` | Bead recipe, the atlas rebuild, and the skin-code tool |
| `docs/AUDIT.md` | Teardown: what is inside the IPA and what can change |
| `docs/BUILDING-AND-TESTING.md` | Build, test, sign and install |
| `assets/`, `dist/` | Generated; both gitignored |

## Quick start

Edit `mod-ui/Mod2.html`, then:

```bash
powershell -ExecutionPolicy Bypass -File Scripts/repack-ipa.ps1 -Name my-edit
```

That patches the dylibs from `mod-ui/`, runs the contract test, and writes
`dist/my-edit.ipa`, unsigned. Sign it with esign, AltStore or Sideloadly to
install — same as the `Wyrm iOS` artifacts.

To build in CI instead:

```bash
gh workflow run pack-ipa.yml -f label=my-edit
```

## What changed from the shipped IPA

- The zoom `+` / `-` buttons no longer raise a JavaScript error popup. The
  cause was an unguarded `results[0].address` after a memory scan that finds
  nothing outside a match; see [docs/MOD-MENU.md](docs/MOD-MENU.md).
- Both mod panels are in English instead of Japanese.
- Cheat offsets, values and freeze intervals are untouched.
- The bead atlas is rebuilt on slither.io's own gradient recipe, lifted from
  NTL 9.68's renderer. 140 plain beads rebuilt; flags, emblems and rim-lit
  beads left byte-identical. Only that one image changed in the SWF - the
  other 159 are pixel-identical.
- A **Skin code** tab: type a code, press ON, press Play. It locates the skin
  bytes itself and verifies the write by reading it back. Codes use the NTL
  alphabet, and the game's own Play sends them - the protocol is untouched.

Nothing else moved. `Scripts/verify-against-source-ipa.py` reports exactly two
modified files - `Mod1.dylib` and `Mod2.dylib` - both still 3,406,784 bytes,
with every changed byte inside the HTML page buffer. The SWF, the `slither.io`
executable, `Info.plist`, the AIR descriptor, the ANEs and every icon are
byte-identical to the shipped IPA.

## How this differs from `Wyrm iOS`

`Wyrm iOS` compiles Swift and C with `xcodebuild` on a macOS runner and zips the
resulting `.app` into an unsigned IPA. Here the `.app` already exists and its
game code is not compilable source, so the pipeline keeps the packaging half —
contract tests, unsigned IPA, SHA-256, workflow artifact, sign-on-install — and
drops the compile half. That makes the build a ZIP on `ubuntu-latest`: no macOS
runner, no Xcode, about a minute per run.
