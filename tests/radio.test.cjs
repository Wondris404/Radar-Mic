// Execute the shipped TypeScript, including its actual USB framing.
const assert = require('node:assert/strict');
const {device} = require('./firmware-host.cjs');

let a=device('a'), b=device('b');
a.wire=p=>b.receive(p); b.wire=p=>a.receive(p);
a.run(`enqueue('T|' + 'x'.repeat(80), 'pc01')`); a.tick(0);
assert.equal(b.received.length,1); assert.equal(b.received[0][0], 'T|'+'x'.repeat(80));
assert.deepEqual(a.results,[['pc01','RECEIVED']]);
assert.equal(a.sent.filter(p=>p[0]==='D').length,11);
// Reverse order, duplicate fragments, reassembly, duplicate completed message.
a=device('a'); b=device('b');
a.run(`enqueue('T|' + 'y'.repeat(80), 'pc02')`); a.tick(0);
for(const p of [...a.sent].reverse()) { b.receive(p); b.receive(p); }
assert.equal(b.received.length,1);
for(const p of a.sent) b.receive(p);
assert.equal(b.received.length,1);
// Lost ACK => retransmit all fragments; receiver ACKs but never redelivers.
a=device('a'); b=device('b'); a.wire=p=>b.receive(p);
a.run(`enqueue('E|LANDING', 'event')`); a.tick(0);
b.wire=p=>a.receive(p); a.tick(650);
assert.equal(b.received.length,1); assert.deepEqual(a.results,[['event','RECEIVED']]);
// Lost fragment => retry completes the existing assembly.
a=device('a'); b=device('b'); let drop=true;
a.wire=p=>{if(drop && p[9]==='1')return; b.receive(p)}; b.wire=p=>a.receive(p);
a.run(`enqueue('T|'+'z'.repeat(80), 'fragment')`); a.tick(0); assert.equal(b.received.length,0);
drop=false; a.tick(650); assert.equal(b.received.length,1); assert.deepEqual(a.results,[['fragment','RECEIVED']]);
// Incomplete assemblies expire; malformed fragments and bounded slots cannot allocate unbounded memory.
b=device('b'); b.receive('DAAAAAAAB0c' + 'a'.repeat(8));
assert.equal(b.run('rxIds.length'),1); b.tick(3001); assert.equal(b.run('rxIds.length'),0);
for(let n=0;n<20;n++) b.receive('D'+n.toString(16).padStart(8,'0') + '0c' + 'a'.repeat(8));
assert.equal(b.run('rxIds.length'),4);
for(const p of ['Dzzzz11a', 'DAAA!AAAA01x', 'DAAAAAAAAaa1', 'DAAAAAAAA02short', 'KAAAAAAAAX']) b.receive(p);
assert.equal(b.received.length,0);
// Three attempts then explicit failure; queue remains bounded.
a=device('a');
a.run(`enqueue('E|MAYDAY','emergency')`); for(const ms of [0,650,650,650])a.tick(ms);
assert.deepEqual(a.results,[['emergency','RADIO_TIMEOUT']]);
for(let n=0;n<20;n++)a.run(`enqueue('H|AIR101','HEART')`);
assert.equal(a.run('outgoing.length'),8);
console.log('Radio transport: 8 scenarios passed (actual shared MakeCode TypeScript)');

// PC sends a real USB record through the ground reader, then the aircraft ACKs.
const id = n => n.toString(16).padStart(12, '0') + '0'.repeat(20);
const boot = ground => ground.run('bootId');
const text = (ground, n, message, deadline = 10000) =>
  `2|TEXT|${id(n)}|${boot(ground)}|${deadline}|${message}`;
const cancel = (ground, n) => `2|CANCEL|${id(n)}|${boot(ground)}`;
const reply = (n, result, kind = 'ACK') => `2|${kind}|${id(n)}|${result}`;
const connect = (ground, aircraft) => {
  ground.wire = packet => aircraft.receive(packet);
  aircraft.wire = packet => ground.receive(packet);
};

const ground = device('ground', true), aircraft = device('aircraft', true);
connect(ground, aircraft);
const record = text(ground, 1, 'AIR101 HOLD ');
ground.usb(record.slice(0, 25));
ground.tick(0);
assert.equal(ground.sent.length, 0);
ground.usb(record.slice(25) + '\r\n');
ground.tick(0);
assert.ok(ground.records.includes(reply(1, 'RECEIVED')));
assert.ok(aircraft.run('displayQueue.indexOf("AIR101 HOLD ") >= 0'));
const n = ground.sent.length;
ground.command(record);
ground.tick(20);
assert.equal(ground.sent.length, n);
ground.command(text(ground, 1, 'DIFFERENT'));
assert.ok(ground.records.includes(reply(1, 'ID_CONFLICT', 'ERROR')));
ground.command(cancel(ground, 1)); // Once accepted, cancellation must report reception.
assert.equal(ground.records.at(-1), reply(1, 'RECEIVED'));
aircraft.buttons[2]();
aircraft.tick(0);
assert.ok(ground.records.some(s => s.includes('|AIR101|MAYDAY|-61')));
ground.run('startProbe()');
assert.ok(ground.records.some(s => s.includes('|OK|0|-61')));
ground.wire = () => {};
ground.run('startProbe()');
ground.now += 1001;
ground.forever[ground.forever.length - 1]();
assert.ok(ground.records.some(s => s.includes('|LOST|0|')));
assert.equal(ground.run('acceptBody("T|bad")'), false);
assert.equal(aircraft.run('acceptBody("E|MAYDAY")'), false);

// A full routine queue and an unacknowledged routine transmission cannot block MAYDAY.
const busy = device('aircraft', true);
busy.buttons[1]();
busy.tick(0);
for (let i = 0; i < 8; i++) busy.buttons[0]();
assert.equal(busy.run('outgoing.length'), 8);
busy.run('while (displayQueue.length < 8) displayText("QUEUED")');
busy.buttons[2]();
const maydayId = busy.run('emergency.id');
busy.buttons[2]();
assert.equal(busy.run('emergency.id'), maydayId);
busy.tick(20);
assert.equal(busy.sent.at(-1).slice(11), 'E|MAYDAY');
busy.receive('K' + maydayId);
assert.equal(busy.run('displayPriority'), 'ACK MAYDAY');
assert.equal(busy.run('outgoing.length'), 8);
busy.buttons[2]();
for (const ms of [0, 650, 650, 650]) busy.tick(ms);
assert.equal(busy.run('displayPriority'), 'FAIL MAYDAY');

// The one-frame emergency also bypasses a full receiver partial queue.
const congested = device('ground', true);
const emergencySender = device('aircraft', true);
for (let i = 0; i < 4; i++) congested.receive('D' + i.toString().padStart(8, '0') + '02H|AIR101');
assert.equal(congested.run('rxIds.length'), 4);
connect(congested, emergencySender);
emergencySender.buttons[2]();
emergencySender.tick(0);
assert.ok(congested.records.some(line => line.includes('|AIR101|MAYDAY|-61')));
assert.equal(emergencySender.run('displayPriority'), 'ACK MAYDAY');

// On reconnection after the application deadline, queued text has already expired.
const offline = device('ground', true), returning = device('aircraft', true);
for (let i = 1; i <= 8; i++) offline.command(text(offline, i, i === 8 ? 'LAND' : 'HOLD'));
offline.tick(0);
const retry = text(offline, 8, 'LAND');
offline.now = 8000;
offline.command(retry);
connect(offline, returning);
const first = offline.sent.length;
offline.tick(6000);
assert.equal(offline.sent.length, first);
assert.equal(returning.run('displayQueue.length'), 1); // Startup label only.
assert.ok(offline.records.includes(reply(8, 'EXPIRED', 'ERROR')));
offline.command(retry);
offline.tick(20);
assert.equal(offline.sent.length, first);

// Cancellation removes queued work, remains sticky across retries and stops an
// active fragmented transmission at the next yield.
const cancelled = device('ground', true);
cancelled.command(text(cancelled, 1, 'x'.repeat(80)));
cancelled.command(text(cancelled, 2, 'HOLD'));
cancelled.command(cancel(cancelled, 2));
cancelled.command(text(cancelled, 2, 'HOLD'));
assert.equal(cancelled.records.at(-1), reply(2, 'CANCELLED'));
cancelled.command(cancel(cancelled, 3));
cancelled.command(text(cancelled, 3, 'RETURN'));
assert.equal(cancelled.records.at(-1), reply(3, 'CANCELLED'));
cancelled.onPause = ms => {
  if (ms !== 12) return;
  cancelled.onPause = undefined;
  cancelled.command(cancel(cancelled, 1));
};
cancelled.tick(0);
assert.equal(cancelled.sent.length, 1);
assert.equal(cancelled.records.at(-1), reply(1, 'CANCELLED'));
cancelled.tick(8000);
assert.equal(cancelled.sent.length, 1);

// A serial reply can yield while USB cancellation updates the same queue.
const concurrent = device('ground', true);
for (let i = 1; i <= 4; i++) concurrent.command(text(concurrent, i, 'HOLD'));
concurrent.onSerialWrite = () => {
  concurrent.onSerialWrite = undefined;
  concurrent.command(cancel(concurrent, 1));
  concurrent.command(cancel(concurrent, 2));
};
concurrent.tick(10001);
assert.equal(concurrent.sent.length, 0);
assert.ok(concurrent.records.includes(reply(1, 'CANCELLED')));
assert.ok(concurrent.records.includes(reply(2, 'CANCELLED')));
assert.ok(!concurrent.records.includes(reply(1, 'EXPIRED', 'ERROR')));
assert.ok(!concurrent.records.includes(reply(2, 'EXPIRED', 'ERROR')));

// Absolute lease expires between fragments and is tied to a single board boot.
const expiring = device('ground', true);
expiring.now = 0x3ffffffe;
expiring.command(text(expiring, 1, 'x'.repeat(80), 3));
expiring.onPause = ms => { expiring.now += ms; };
expiring.tick(0);
assert.equal(expiring.sent.length, 1);
expiring.tick(0);
assert.equal(expiring.records.at(-1), reply(1, 'EXPIRED', 'ERROR'));
const rebooted = device('ground', true, 2000);
rebooted.command(text(expiring, 1, 'HOLD'));
assert.equal(rebooted.records.at(-1), reply(1, 'STALE_BOOT', 'ERROR'));

// Turning sonar off clears both the scanning and obstacle LEDs.
const scanner = device('ground', true);
scanner.forever[3]();
assert.deepEqual([...scanner.leds], ['2,2', '0,0']);
scanner.buttons[0]();
scanner.forever[3]();
assert.equal(scanner.leds.size, 0);
assert.equal(scanner.records.at(-1), '2|SONAR|0000|OFF|0');

// Reboot the sender with the same deterministic PRNG sequence while the
// aircraft still holds the old radio ACK cache. Separate PC UUIDs must not alias.
const peer = device('aircraft', true);
const oldGround = device('ground', true, 3000);
connect(oldGround, peer);
oldGround.command(text(oldGround, 1, 'AIR101 HOLD'));
oldGround.tick(0);
assert.ok(oldGround.records.includes(reply(1, 'RECEIVED')));
const newGround = device('ground', true, 3000);
connect(newGround, peer);
newGround.command(text(newGround, 2, 'AIR101 RETURN'));
newGround.tick(0);
assert.ok(newGround.records.includes(reply(2, 'RECEIVED')));
assert.ok(peer.run('displayQueue.indexOf("AIR101 RETURN") >= 0'));
const expectedRadioId = Buffer.from(id(2).slice(0, 12), 'hex').toString('base64url');
assert.equal(newGround.sent[0].slice(1, 9), expectedRadioId);

// Receive a Q while a serial reply can yield across the timeout boundary.
const race = device('ground', true);
race.run('startProbe()');
const probe = race.sent[0].slice(2);
race.now = 990;
race.onSerialWrite = () => {
  race.onSerialWrite = undefined;
  race.now = 1005;
  race.forever.at(-1)();
};
race.receive('Q2' + probe);
assert.deepEqual(race.records.filter(line => line.startsWith('2|RTT|' + probe)),
  ['2|RTT|' + probe + '|OK|990|-61']);

// A reply arriving after the deadline must not beat the periodic timeout.
// A legacy radio reply with the old format must not activate the link.
const late = device('ground', true);
late.run('startProbe()');
const lateProbe = late.sent[0].slice(2);
late.receive('Q' + lateProbe);
assert.equal(late.records.length, 0);
late.now = 1020;
late.receive('Q2' + lateProbe);
late.forever.at(-1)();
assert.deepEqual(late.records.filter(line => line.startsWith('2|RTT|' + lateProbe)),
  ['2|RTT|' + lateProbe + '|LOST|0|-128']);

console.log('Firmware integration passed: USB, ACK isolation after reboot, retries, cancellation, expiry, MAYDAY priority, and single-outcome RTT');
