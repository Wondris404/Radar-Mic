// Execute the shipped TypeScript, not a separately implemented protocol model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../tools/node_modules/typescript');
const shared = fs.readFileSync('firmware/shared.ts', 'utf8');
for (const role of ['ground', 'aircraft']) assert.equal(fs.readFileSync(`firmware/${role}/radio.ts`, 'utf8'), shared);
function device(role, actual=false) {
  let handler;
  const d = {now:0, sent:[], received:[], results:[], forever:[], rssi:-61, serial:[], buttons:{}};
  const context = vm.createContext({
    radio: {setGroup(){}, setFrequencyBand(){}, setTransmitPower(){},
      onReceivedString(fn){handler=fn}, receivedPacket(){return d.rssi},
      sendString(p){assert.ok(p.length<=19); d.sent.push(p); if(d.wire) d.wire(p)}},
    serial:{redirectToUSB(){},setBaudRate(){},setRxBufferSize(){},setTxBufferSize(){},readString(){return ''},writeLine:s=>d.serial.push(s)},
    BaudRate:{BaudRate115200:115200}, Button:{A:0,B:1,AB:2},
    sonarbit:{sonarbit_distance:()=>42},Distance_Unit:{Distance_Unit_cm:1},DigitalPin:{P2:2},led:{plot(){},unplot(){}},
    randint:()=> role==='a'?100:1000,
    input: {runningTime:()=>d.now, onButtonPressed:(b,fn)=>d.buttons[b]=fn}, RadioPacketProperty:{SignalStrength:0},
    basic: {forever:fn=>d.forever.push(fn), pause(){}, showString(){}},
    acceptBody:body=>body.length>0, received:(...args)=>d.received.push(args),
    delivered:(...args)=>d.results.push(args), onProbe(){}, onProbeReply(){},
  });
  vm.runInContext('Array.prototype.removeAt = function(i) { return this.splice(i,1)[0]; }',context);
  vm.runInContext(ts.transpile(shared + (actual ? fs.readFileSync(`firmware/${role}/main.ts`, 'utf8') : '')), context);
  d.receive = p=>handler(p);
  d.run = code=>vm.runInContext(code,context);
  d.tick = ms=>{d.now+=ms; d.forever[0]()};
  return d;
}
let a=device('a'), b=device('b');
a.wire=p=>b.receive(p); b.wire=p=>a.receive(p);
a.run(`enqueue('T|' + 'x'.repeat(80), 'pc01')`); a.tick(0);
assert.equal(b.received.length,1); assert.equal(b.received[0][0], 'T|'+'x'.repeat(80));
assert.deepEqual(a.results,[['pc01',true]]);
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
assert.equal(b.received.length,1); assert.deepEqual(a.results,[['event',true]]);
// Lost fragment => retry completes the existing assembly.
a=device('a'); b=device('b'); let drop=true;
a.wire=p=>{if(drop && p[5]==='1')return; b.receive(p)}; b.wire=p=>a.receive(p);
a.run(`enqueue('T|'+'z'.repeat(80), 'fragment')`); a.tick(0); assert.equal(b.received.length,0);
drop=false; a.tick(650); assert.equal(b.received.length,1); assert.deepEqual(a.results,[['fragment',true]]);
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
assert.deepEqual(a.results,[['emergency',false]]);
for(let n=0;n<20;n++)a.run(`enqueue('H|AIR101','HEART')`);
assert.equal(a.run('txIds.length'),8);
console.log('Radio transport: 8 scenarios passed (actual shared MakeCode TypeScript)');

// Interoperate both shipped firmwares: PC command -> fragmented radio -> ACK.
const ground=device('ground',true), aircraft=device('aircraft',true);
ground.wire=p=>aircraft.receive(p); aircraft.wire=p=>ground.receive(p);
ground.run(`command('1|TEXT|abcd|AIR101 HOLD')`); ground.tick(0);
assert.ok(ground.serial.includes('1|ACK|abcd|DELIVERED'));
assert.ok(aircraft.run('displayQueue.indexOf("AIR101 HOLD") >= 0'));
const n=ground.sent.length;
ground.run(`command('1|TEXT|abcd|AIR101 HOLD')`); ground.tick(20);
assert.equal(ground.sent.length,n); // serial retry replays cached ACK
ground.run(`command('1|TEXT|abcd|DIFFERENT')`);
assert.ok(ground.serial.includes('1|ERROR|abcd|ID_CONFLICT'));
aircraft.buttons[2](); aircraft.tick(0);
assert.ok(ground.serial.some(s=>s.includes('|AIR101|MAYDAY|-61')));
ground.run('startProbe()');
assert.ok(ground.serial.some(s=>s.includes('|OK|0|-61')));
ground.wire=()=>{}; ground.run('startProbe()'); ground.now+=1001;
ground.forever[ground.forever.length-1]();
assert.ok(ground.serial.some(s=>s.includes('|LOST|0|')));
assert.equal(ground.run('acceptBody("T|bad")'),false);
assert.equal(aircraft.run('acceptBody("E|MAYDAY")'),false);
console.log('Firmware integration: PC delivery, duplicate/conflicting commands, emergency, RTT success/loss, role validation passed');
