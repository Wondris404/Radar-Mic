// Execute the shipped TypeScript, including its actual USB framing.
const assert = require('node:assert/strict');
const {device} = require('./firmware-host.cjs');

let a=device('a'), b=device('b');
a.wire=p=>b.receive(p); b.wire=p=>a.receive(p);
a.run(`enqueue('T|' + 'x'.repeat(80), 'pc01')`); a.tick(0);
assert.equal(b.received.length,1); assert.equal(b.received[0][0], 'T|'+'x'.repeat(80));
assert.deepEqual(a.results,[['pc01','RECEIVED']]);
assert.equal(a.sent.filter(p=>p[0]==='D').length,7);
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
a.wire=p=>{if(drop && p[5]==='1')return; b.receive(p)}; b.wire=p=>a.receive(p);
a.run(`enqueue('T|'+'z'.repeat(80), 'fragment')`); a.tick(0); assert.equal(b.received.length,0);
drop=false; a.tick(650); assert.equal(b.received.length,1); assert.deepEqual(a.results,[['fragment','RECEIVED']]);
// Incomplete assemblies expire; malformed fragments and bounded slots cannot allocate unbounded memory.
b=device('b'); b.receive('D000108'+ 'a'.repeat(12));
assert.equal(b.run('rxIds.length'),1); b.tick(3001); assert.equal(b.run('rxIds.length'),0);
for(let n=0;n<20;n++) b.receive('D'+n.toString(16).padStart(4,'0')+'08'+'a'.repeat(12));
assert.equal(b.run('rxIds.length'),4);
for(const p of ['Dzzzz11a','D111199bad','D111101bad','D111108short','K1111extra']) b.receive(p);
assert.equal(b.received.length,0);
// Three attempts then explicit failure; queue remains bounded.
a=device('a');
a.run(`enqueue('E|MAYDAY','emergency')`); for(const ms of [0,650,650,650])a.tick(ms);
assert.deepEqual(a.results,[['emergency','RADIO_TIMEOUT']]);
for(let n=0;n<20;n++)a.run(`enqueue('H|AIR101','HEART')`);
assert.equal(a.run('outgoing.length'),8);
console.log('Radio transport: 8 scenarios passed (actual shared MakeCode TypeScript)');

// PC sends a real USB record through the ground reader, then the aircraft ACKs.
const id = n => n.toString(16).padStart(32, '0');
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
assert.equal(busy.sent.at(-1).slice(7), 'E|MAYDAY');
busy.receive('K' + maydayId);
assert.equal(busy.run('displayPriority'), 'ACK MAYDAY');
assert.equal(busy.run('outgoing.length'), 8);
busy.buttons[2]();
for (const ms of [0, 650, 650, 650]) busy.tick(ms);
assert.equal(busy.run('displayPriority'), 'FAIL MAYDAY');

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

console.log('Firmware integration passed: USB commands, reception, retries, boot IDs, cancellation, expiry, MAYDAY priority, and RTT');
