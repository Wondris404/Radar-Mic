// Execute the shipped TypeScript with MakeCode device I/O supplied by the host.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../tools/node_modules/typescript');
const target = require('../tools/node_modules/pxt-microbit/built/target.json');

const shared = fs.readFileSync('firmware/shared.ts', 'utf8');
for (const role of ['ground', 'aircraft']) {
  assert.equal(fs.readFileSync(`firmware/${role}/radio.ts`, 'utf8'), shared);
}

// Keep MakeCode's real writeLine implementation in the harness. Stub only the
// native writeString shim so captured bytes include any padding and framing.
const serialSource = target.bundledpkgs.core['serial.ts'];
const start = serialSource.indexOf('namespace serial {');
const end = serialSource.indexOf('    /**\n     * Print a numeric value', start);
assert.ok(start >= 0 && end > start);
const serialRuntime = ts.transpile(serialSource.slice(start, end) + '\n}');

function device(role, actual = false, seed = role === 'a' ? 100 : 1000) {
  let handler;
  let random = seed;
  const d = {
    now: 0, sent: [], received: [], results: [], forever: [], rssi: -61,
    serialInput: '', serialWrites: [], buttons: {},
    get records() { return this.serialWrites.join('').split('\r\n').filter(Boolean); },
  };
  const context = vm.createContext({
    radio: {
      setGroup() {}, setFrequencyBand() {}, setTransmitPower() {},
      onReceivedString(fn) { handler = fn; },
      receivedPacket() { return d.rssi; },
      sendString(packet) {
        assert.ok(packet.length <= 19);
        d.sent.push(packet);
        if (d.wire) d.wire(packet);
      },
    },
    serial: {
      redirectToUSB() {}, setBaudRate() {}, setRxBufferSize() {}, setTxBufferSize() {},
      readString() {
        const data = d.serialInput;
        d.serialInput = '';
        return data;
      },
      writeString(text) {
        d.serialWrites.push(text);
        if (d.onSerialWrite) d.onSerialWrite(text);
      },
    },
    Delimiters: {NewLine: 0},
    BaudRate: {BaudRate115200: 115200},
    Button: {A: 0, B: 1, AB: 2},
    sonarbit: {sonarbit_distance: () => 42},
    Distance_Unit: {Distance_Unit_cm: 1},
    DigitalPin: {P2: 2},
    led: {plot() {}, unplot() {}},
    randint: () => random++,
    input: {runningTime: () => d.now, onButtonPressed: (button, fn) => d.buttons[button] = fn},
    RadioPacketProperty: {SignalStrength: 0},
    basic: {
      forever: fn => d.forever.push(fn),
      pause(ms) { if (d.onPause) d.onPause(ms); },
      showString() {},
    },
    acceptBody: body => body.length > 0,
    received: (...args) => d.received.push(args),
    delivered: (...args) => d.results.push(args),
    onProbe() {}, onProbeReply() {},
  });
  vm.runInContext('Array.prototype.removeAt = function(i) { return this.splice(i,1)[0]; }', context);
  vm.runInContext(serialRuntime, context);
  const main = actual ? fs.readFileSync(`firmware/${role}/main.ts`, 'utf8') : '';
  vm.runInContext(ts.transpile(shared + main), context);
  d.receive = packet => handler(packet);
  d.run = code => vm.runInContext(code, context);
  d.tick = ms => { d.now += ms; d.forever[0](); };
  d.usb = text => { d.serialInput += text; d.forever[2](); };
  d.command = line => d.usb(line + '\n');
  return d;
}

module.exports = {device};
