# The mod menu: how it works, what was broken, what changed

## How the mod is wired up

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

## How the cheats find memory

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

## The bug behind the "index error" popup

### What you saw

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

### Root cause

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

### The fix

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

### What still needs a match to be running

The fix removes the crash, not the requirement. The anchor genuinely does not
exist outside a match, so: **start a game, then use the panel.** The difference
is that doing it in the wrong order now shows `Join a game first` instead of a
JavaScript error, and the panel recovers by itself once you are in a game.

## Translation

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

## Known cosmetic oddity, left alone

`Mod1.html` styles the body with `transform: rotate(45deg) translate(0,50px)`,
while `Mod2.html` uses `rotate(90deg)`. The 90-degree rotation matches the
rotated landscape presentation; 45 looks like a typo in the original. It was
left exactly as shipped, because it has nothing to do with the crash and
changing it would move the UI under you. Change `45deg` to `90deg` in
`mod-ui/Mod1.html` if you want the two panels to match.

## Editing the menu yourself

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
