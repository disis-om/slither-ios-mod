#!/usr/bin/env node
/*
 * Runs each mod menu page's script against a fake H5GG host and a minimal DOM.
 *
 * The panels cannot be exercised anywhere else before they are on a phone, and
 * the failure they are most likely to have - an uncaught exception that stops
 * the script and leaves half the page dead - is exactly what took the zoom
 * buttons down in the shipped build. These tests reproduce both states the
 * panel has to survive: a match running, and no match at all.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const MOD_UI = path.join(ROOT, 'mod-ui');
const BASE = 0x300000000;

let failures = 0;

function check(condition, message) {
    if (condition) {
        console.log(`  ok   ${message}`);
    } else {
        console.log(`  FAIL ${message}`);
        failures++;
    }
}

/* ---------------------------------------------------------------- */

function makeElement(id) {
    return {
        id,
        value: '',
        textContent: '',
        className: '',
        hidden: false,
        checked: false,
        _handlers: {},
        addEventListener(type, fn) {
            (this._handlers[type] = this._handlers[type] || []).push(fn);
        },
        fire(type) {
            (this._handlers[type] || []).forEach((fn) => fn.call(this));
        },
    };
}

function makeHost(options) {
    const inMatch = options.inMatch !== false;
    const memory = new Map();
    const writes = [];

    const readByte = (address) => memory.get(address) || 0;

    const host = {
        results: [],
        clearResults() { this.results = []; },
        searchNumber(value, type) {
            this.results = inMatch
                ? [{ address: BASE.toString(16), type, value }]
                : [];
        },
        getResultsCount() { return this.results.length; },
        getResults(count, skip) { return this.results.slice(skip, skip + count); },
        getValue(address, type) {
            const at = parseInt(address, 16);
            if (type === 'I8') return readByte(at);
            if (type === 'I32') {
                let word = 0;
                for (let i = 3; i >= 0; i--) word = word * 256 + readByte(at + i);
                return word;
            }
            return host.f64 === undefined ? 1 : host.f64;
        },
        setValue(address, value, type) {
            const at = parseInt(address, 16);
            writes.push({ address, value, type });
            if (type === 'I8') memory.set(at, Number(value) & 255);
            else host.f64 = Number(value);
        },
    };

    return { host, memory, writes };
}

function runPage(name, options) {
    const html = fs.readFileSync(path.join(MOD_UI, `${name}.html`), 'utf8');
    const script = /<script[^>]*>([\s\S]*?)<\/script>/i.exec(html);
    if (!script) throw new Error(`${name}.html has no <script>`);

    const ids = new Set();
    for (const match of html.matchAll(/id="([^"]+)"/g)) ids.add(match[1]);

    const elements = new Map();
    for (const id of ids) elements.set(id, makeElement(id));

    // Carry over each input's default value, the way a browser would.
    for (const tag of html.matchAll(/<input[^>]*>/g)) {
        const id = /id="([^"]+)"/.exec(tag[0]);
        const value = /value="([^"]*)"/.exec(tag[0]);
        if (id && value && elements.has(id[1])) elements.get(id[1]).value = value[1];
    }

    const { host, memory, writes } = makeHost(options);
    const calls = { rect: null, drag: null, icon: null };
    const timers = new Set();

    const sandbox = {
        h5gg: host,
        document: {
            getElementById: (id) => elements.get(id) || null,
        },
        setWindowRect: (...args) => { calls.rect = args; },
        setWindowDrag: (...args) => { calls.drag = args; },
        setButtonImage: (src) => { calls.icon = String(src).slice(0, 24); },
        setInterval: (fn) => { const handle = { fn }; timers.add(handle); return handle; },
        clearInterval: (handle) => { timers.delete(handle); },
        Math, Number, String, isFinite, parseInt, parseFloat, JSON,
        console: { log() {} },
    };
    sandbox.window = sandbox;

    // An uncaught throw here is the bug this whole exercise is about.
    vm.createContext(sandbox);
    vm.runInContext(script[1], sandbox, { filename: `${name}.html` });

    return { elements, host, memory, writes, calls, timers, sandbox };
}

/* ---------------------------------------------------------------- */

console.log('Mod2.html - zoom panel');
{
    const live = runPage('Mod2', { inMatch: true });
    check(live.calls.rect !== null, 'window is positioned even before any tap');

    live.sandbox.plus();
    check(live.timers.size === 1, 'plus() installs exactly one locker');
    live.timers.forEach((handle) => handle.fn());     // the locker's first tick
    check(live.writes.some((w) => w.type === 'F64'), 'plus() writes the zoom value');
    const afterPlus = live.elements.get('status').textContent;
    check(/^Zoom /.test(afterPlus), `plus() reports zoom, got "${afterPlus}"`);

    live.sandbox.minus();
    check(live.timers.size === 1, 'minus() replaces the locker rather than stacking');

    const dead = runPage('Mod2', { inMatch: false });
    check(dead.calls.rect !== null, 'window is positioned with no match running');
    check(dead.elements.get('status').textContent === 'Join a game first',
        'load with no match shows the status line, not an error');
    dead.sandbox.plus();
    check(dead.elements.get('status').textContent === 'Join a game first',
        'tapping + with no match stays on the status line');
    check(dead.timers.size === 0, 'no locker is installed when the anchor is missing');
}

console.log('Mod1.html - cheats and skin code');
{
    const live = runPage('Mod1', { inMatch: true });
    check(live.calls.rect !== null, 'window is positioned');

    const cb1 = live.elements.get('cb1');
    cb1.checked = true;
    cb1.fire('change');
    check(live.timers.size === 1, 'cb1 installs a freeze locker');
    cb1.checked = false;
    cb1.fire('change');
    check(live.timers.size === 0, 'unchecking cb1 clears it');

    const cb3 = live.elements.get('cb3');
    cb3.checked = true;
    cb3.fire('change');
    check(live.calls.icon !== null, 'cb3 swaps the menu button image');

    live.sandbox.showTab('skin');
    check(live.elements.get('paneSkin').hidden === false, 'skin tab shows its pane');
    check(live.elements.get('paneCheats').hidden === true, 'skin tab hides the cheats pane');

    // Nothing that looks like a skin anywhere: refuse rather than scribble.
    live.elements.get('skinCode').value = 'zxcv';
    live.sandbox.skinOn();
    check(live.writes.filter((w) => w.type === 'I8').length === 0,
        'ON writes nothing when no skin array can be found');
    check(live.elements.get('skinAdvanced').hidden === false,
        'ON reveals the manual fallback when it cannot find the bytes');

    // Now lay a plausible skin array down: a run of colour-group indices
    // bounded by bytes too large to be one.
    const SKIN_AT = BASE - 0x1c0;
    live.memory.set(SKIN_AT - 1, 200);
    for (let i = 0; i < 64; i++) live.memory.set(SKIN_AT + i, (i % 9) + 1);
    live.memory.set(SKIN_AT + 64, 200);

    const code = 'zxcvbnm,asdfghjkl';
    live.elements.get('skinCode').value = code;
    live.sandbox.skinOn();
    const onStatus = live.elements.get('status').textContent;
    check(/^On - 17 beads/.test(onStatus), `ON reports success, got "${onStatus}"`);
    check(live.writes.filter((w) => w.type === 'I8').length === code.length,
        'ON writes one byte per bead');
    check(live.memory.get(SKIN_AT) === 0 && live.memory.get(SKIN_AT + 1) === 1,
        'ON writes the right indices at the located offset');

    live.memory.set(SKIN_AT + code.length, 200);
    live.elements.get('skinCode').value = '';
    live.sandbox.readSkin();
    check(live.elements.get('skinCode').value === code,
        `Read current round-trips the code, got "${live.elements.get('skinCode').value}"`);

    live.elements.get('skinCode').value = 'zx!!';
    live.sandbox.skinOn();
    check(/Not in the alphabet/.test(live.elements.get('status').textContent),
        'ON rejects characters outside the alphabet');

    live.elements.get('skinCode').value = '';
    live.sandbox.skinOn();
    check(/Type a skin code first/.test(live.elements.get('status').textContent),
        'ON asks for a code when the box is empty');

    // The manual fallback: two reads around a bead change.
    const manual = runPage('Mod1', { inMatch: true });
    manual.sandbox.showTab('skin');
    manual.sandbox.locate();
    check(/change one bead/i.test(manual.elements.get('status').textContent),
        'first Locate asks for a bead change');
    manual.memory.set(BASE - 0x40, 5);
    manual.sandbox.locate();
    check(/Found the skin bytes/.test(manual.elements.get('status').textContent),
        `second Locate finds it, got "${manual.elements.get('status').textContent}"`);
    check(manual.elements.get('skinOffset').value === '-0x40',
        `Locate fills the offset box, got "${manual.elements.get('skinOffset').value}"`);

    const dead = runPage('Mod1', { inMatch: false });
    check(dead.elements.get('status').textContent === 'Join a game first',
        'load with no match shows the status line');
    const deadBox = dead.elements.get('cb1');
    deadBox.checked = true;
    deadBox.fire('change');
    check(deadBox.checked === false, 'a toggle refuses to stick with no anchor');
    check(dead.timers.size === 0, 'and installs no locker');
    dead.sandbox.showTab('skin');
    dead.elements.get('skinCode').value = 'zxcv';
    dead.sandbox.skinOn();
    check(dead.elements.get('status').textContent === 'Join a game first',
        'ON with no match reports it instead of throwing');
    dead.sandbox.readSkin();
    check(dead.elements.get('status').textContent === 'Join a game first',
        'readSkin() with no match reports it instead of throwing');
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed');
process.exit(failures ? 1 : 0);
