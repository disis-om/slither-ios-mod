# Building and testing

The shape of this pipeline is copied from `Wyrm iOS`: Windows is the editing
machine, GitHub Actions produces the artifact, and the IPA ships **unsigned** so
the signer on the phone applies its own identity.

The one real difference is that nothing compiles here. `Wyrm iOS` builds Swift
and C into a `.app` with `xcodebuild` on a macOS runner. This project's `.app`
already exists and its code is AOT-compiled ARM64 inside the bundle (see
[AUDIT.md](AUDIT.md)), so packaging is a ZIP and runs on `ubuntu-latest` in
about a minute, with no macOS runner and no Xcode.

## Build inputs

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

## Local build (Windows)

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

## CI build

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

## The contract test

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

## Editing the assets

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
the AOT stub described in [AUDIT.md](AUDIT.md). It still writes a correct SWF.
Do not treat the exit code as the result - check the output file instead. A
verified round-trip on this bundle preserved all 196 tags, left the `DoABC2`
stub and the `SymbolClass` table byte-identical, and rewrote the uncompressed
header length field to match the new size.

After replacing, re-run the contract test, then repack.

## Signing and installing

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

## Git and large files

`extracted/` contains a 35 MB SWF and a 14 MB Mach-O binary. Both sit well
under GitHub's 100 MB per-file limit, so they are committed normally - no Git
LFS, no quota to manage. `.gitattributes` marks them binary so git never tries
to diff or normalise their bytes.

`assets/` and the input `.ipa` are gitignored. The first is regenerated by
`Scripts/export-assets.ps1`, and the second is an input you keep locally.

## What this pipeline cannot do

It cannot change game logic. The ActionScript was AOT-compiled to ARM64 and
stripped from the SWF; there is no source to edit and no compile step to run.
Changing behaviour means patching the Mach-O or shipping a hook dylib, which is
outside this pipeline. See [AUDIT.md](AUDIT.md) for the evidence.
