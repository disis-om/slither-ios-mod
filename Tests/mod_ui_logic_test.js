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

    // Write a code, read it back: the alphabet must round-trip.
    const code = 'zxcvbnm,asdfghjkl';
    live.elements.get('skinCode').value = code;
    live.sandbox.useOffset();
    const offsetStatus = live.elements.get('status').textContent;
    check(/Skin offset set to/.test(offsetStatus),
        `useOffset() accepts the default, got "${offsetStatus}"`);
    live.sandbox.writeSkin();
    check(live.writes.filter((w) => w.type === 'I8').length === code.length,
        `writeSkin() wrote ${code.length} bytes, status "${live.elements.get('status').textContent}"`);
    check(/press OK in Build a Slither/.test(live.elements.get('status').textContent),
        'writeSkin() points at the game\'s own OK');

    // Terminate the array the way a shorter skin would.
    const offset = parseInt('1c0', 16);
    live.memory.set(BASE - offset + code.length, 255);
    live.elements.get('skinCode').value = '';
    live.sandbox.readSkin();
    check(live.elements.get('skinCode').value === code,
        `readSkin() round-trips the code, got "${live.elements.get('skinCode').value}"`);

    live.elements.get('skinCode').value = 'zx!!';
    live.sandbox.writeSkin();
    check(/Not in the alphabet/.test(live.elements.get('status').textContent),
        'writeSkin() rejects characters outside the alphabet');

    live.sandbox.snap('A');
    live.memory.set(BASE - offset, 7);
    live.sandbox.snap('B');
    live.sandbox.diffSnaps();
    check(/Changed at:/.test(live.elements.get('status').textContent),
        `diff finds the byte that moved, got "${live.elements.get('status').textContent}"`);

    const dead = runPage('Mod1', { inMatch: false });
    check(dead.elements.get('status').textContent === 'Join a game first',
        'load with no match shows the status line');
    const deadBox = dead.elements.get('cb1');
    deadBox.checked = true;
    deadBox.fire('change');
    check(deadBox.checked === false, 'a toggle refuses to stick with no anchor');
    check(dead.timers.size === 0, 'and installs no locker');
    dead.sandbox.showTab('skin');
    dead.sandbox.readSkin();
    check(dead.elements.get('status').textContent === 'Join a game first',
        'readSkin() with no match reports it instead of throwing');
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed');
process.exit(failures ? 1 : 0);
