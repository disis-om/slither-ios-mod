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
| `Scripts/export-assets.ps1` | Regenerates `assets/` from the bundle's SWF |
| `Tests/bundle_contract_test.py` | Pre-flight checks that catch a broken edit |
| `.github/workflows/pack-ipa.yml` | CI build, uploads the IPA as an artifact |
| `docs/MOD-MENU.md` | How the mod works, the zoom crash, and the fix |
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

## How this differs from `Wyrm iOS`

`Wyrm iOS` compiles Swift and C with `xcodebuild` on a macOS runner and zips the
resulting `.app` into an unsigned IPA. Here the `.app` already exists and its
game code is not compilable source, so the pipeline keeps the packaging half —
contract tests, unsigned IPA, SHA-256, workflow artifact, sign-on-install — and
drops the compile half. That makes the build a ZIP on `ubuntu-latest`: no macOS
runner, no Xcode, about a minute per run.
