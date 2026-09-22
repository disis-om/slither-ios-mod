# IPA audit: `TabemaruModV3-TsEdited-1.ipa`

Read-only teardown of the shipped IPA, recording what the package actually
contains and which parts can be edited. Everything below was observed from the
file itself, not assumed.

## Package identity

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

## What the app is

An **Adobe AIR 51.1 (HARMAN) application**, not a native Swift/Objective-C app.

- `META-INF/AIR/application.xml` — AIR descriptor, `renderMode` `direct`,
  portrait, fullscreen, content `slither ios.swf`.
- Four ANEs: `com.distriqt.Core`, `com.distriqt.Application`,
  `com.distriqt.ApplicationRater`, `com.distriqt.InAppBilling`.
- `slither ios.swf` (35,535,345 bytes) — uncompressed `FWS` v51, 196 tags.
- `slither.io` (13,981,264 bytes) — Mach-O arm64 executable; the AIR runtime.

## The critical finding: there is no ActionScript bytecode in the SWF

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

## What *is* editable, and how

### 1. SWF assets — fully editable

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

### 2. `Info.plist` and the AIR descriptor — fully editable

App name, bundle id, version, device family, ATS exceptions, orientation,
SKAdNetwork entries. Plain plist/XML edits.

### 3. Icons and launch images — fully editable

`Icon*.png`, `Default*.png`, `Assets.car`.

### 4. The injected mod dylibs — native

`Mod1.dylib` and `Mod2.dylib` (3,406,784 bytes each, different SHA, Mach-O
arm64 dylibs) are the Tabemaru mod's own code, injected into the load commands.
Same story as the main binary: ARM64, no source.

### 5. The Mach-O executable — native, patch-only

`slither.io` holds the AOT-compiled game. Changing behaviour means patching
instructions or hooking via a dylib, not editing source.

## Summary

| Layer | Editable as source | Notes |
| --- | --- | --- |
| Game logic | No | AOT ARM64 inside `slither.io` |
| Mod behaviour | No | AOT ARM64 inside `Mod*.dylib` |
| Skins / backgrounds / UI art | Yes | 160 PNGs in the SWF |
| Fonts | Yes | 4 TTFs in the SWF |
| App metadata | Yes | `Info.plist`, AIR descriptor |
| Icons / launch screens | Yes | Bundle PNGs, `Assets.car` |
| Repackaging | Yes | Plain ZIP, see `BUILDING-AND-TESTING.md` |

## Tooling used

- JPEXS Free Flash Decompiler 26.2.1 (`C:\Users\Om Rajput\Downloads\ffdec_26.2.1`)
- Java 21 (Temurin 21.0.12)
- Python 3.12 for plist, Mach-O and string inspection
