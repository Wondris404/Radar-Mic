// Two PXT-compiled programs in Microsoft's micro:bit simulator runtime.
// Only the physical echo, USB boundary and delivery between boards are modeled.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const vm = require('node:vm');

const modules = path.resolve(__dirname, '../tools/node_modules');
const simulatorFiles = [
  'pxt-core/built/pxtsim.js',
  'pxt-microbit/built/common-sim.js',
  'pxt-microbit/built/sim.js',
];
const simulators = simulatorFiles.map(name =>
  new vm.Script(fs.readFileSync(path.join(modules, name), 'utf8'), {filename: name})
);
const programs = Object.fromEntries(['ground', 'aircraft'].map(role => [
  role, fs.readFileSync(path.join(__dirname, `../firmware/${role}/built/debug/binary.js`), 'utf8')
]));

const elapsed = ms => new Promise(resolve => setTimeout(resolve, ms));
const boards = {};
let radioOnline = true;
let pulse = 42 * 58;
let usb = [];
let display = [];
let observedPins = [];
let radio = [];

function startBoard(role) {
  const timers = new Set();
  function schedule(callback, ms, ...args) {
    const timer = setTimeout(() => {
      timers.delete(timer);
      callback(...args);
    }, ms);
    timers.add(timer);
    return timer;
  }
  const context = vm.createContext({
    console: {...console, log: console.error, warn: console.error},
    setTimeout: schedule, clearTimeout: timer => { timers.delete(timer); clearTimeout(timer); },
    performance, TextEncoder, TextDecoder, btoa, atob, navigator: {userAgent: ''},
    addEventListener() {}, removeEventListener() {}, location: {href: 'http://localhost', search: ''},
    parent: {postMessage() {}},
  });
  context.window = context;
  context.self = context;
  for (const simulator of simulators) simulator.runInContext(context);
  const sim = context.pxsim;
  const runtime = new sim.Runtime({id: role, type: 'run', code: programs[role]});
  runtime.errorHandler = error => { console.error(role, error.stack); process.exit(1); };
  const board = runtime.board;
  board.hardwareVersion = 2;
  sim.pins.pulseIn = (pin, polarity, timeout) => {
    if (role === 'ground') {
      assert.equal(pin, 102); // DAL identifier for P2, not MCU GPIO number.
      assert.equal(polarity, 4); // PulseValue.High.
      assert.equal(timeout, 25000);
      observedPins.push(pin);
    }
    return pulse;
  };

  const showString = sim.basic.showString;
  sim.basic.showString = (message, interval) => {
    display.push({role, message, interval});
    showString(message, interval);
  };

  sim.Runtime.messagePosted = msg => {
    if (role === 'ground' && msg.type === 'serial') usb.push(msg.data);
    if (role === 'ground' && msg.type === 'bulkserial') usb.push(...msg.data.map(item => item.data));
    if (msg.type !== 'radiopacket') return;
    const bytes = msg.payload.bufferData;
    assert.equal(bytes[0], 2); // MakeCode PACKET_TYPE_STRING.
    const packet = Buffer.from(bytes.subarray(10, 10 + bytes[9])).toString('ascii');
    assert.equal(packet.length, bytes[9]);
    assert.ok(packet.length <= 19);
    radio.push({role, packet});
    if (!radioOnline) return;
    const peer = boards[role === 'ground' ? 'aircraft' : 'ground'];
    if (peer && board.radioState.band === peer.board.radioState.band) {
      // Receive via MakeCode's bounded datagram queue and normal event bus.
      schedule(() => {
        if (radioOnline && !peer.runtime.dead) {
          peer.board.receiveMessage({...msg, rssi: -63});
        }
      }, 4);
    }
  };

  boards[role] = {
    board, runtime, stop() {
      runtime.dead = true;
      for (const timer of timers) clearTimeout(timer);
      timers.clear();
    },
  };
  runtime.run(() => {});
}

async function step(request) {
  if (request.restartGround) {
    boards.ground.stop();
    startBoard('ground');
  }
  if (request.radioOnline !== undefined) radioOnline = request.radioOnline;
  if (request.pulse !== undefined) pulse = request.pulse;
  if (request.button) {
    const {role, name} = request.button;
    boards[role].board.bus.queue({A: 1, B: 2, AB: 3}[name], 3); // DAL button click.
  }
  if (request.usb) {
    // PXT 9.1.2's SerialState.receiveData never adds its data argument to
    // serialIn. Feed the simulator's actual readString input queue directly.
    const chunks = request.usb.match(/[\s\S]{1,23}/g) || [];
    boards.ground.board.serialState.serialIn.push(...chunks);
  }
  await elapsed(request.ms ?? 75);
  const result = {
    usb: usb.join(''), display, observedPins, radio,
    led: {
      ground: boards.ground.board.ledMatrixState.image.get(0, 0),
    },
    config: Object.fromEntries(Object.entries(boards).map(([role, {board}]) =>
      [role, [board.radioState.groupId, board.radioState.band, board.radioState.power]]
    )),
  };
  usb = [];
  display = [];
  observedPins = [];
  radio = [];
  return result;
}

async function main() {
  startBoard('aircraft');
  startBoard('ground');
  const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
  for await (const line of input) {
    const response = await step(JSON.parse(line));
    process.stdout.write(JSON.stringify(response) + '\n');
  }
  for (const board of Object.values(boards)) board.stop();
}
main().catch(error => { console.error(error.stack); process.exit(1); });
