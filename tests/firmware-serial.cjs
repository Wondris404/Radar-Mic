// Emit raw bytes using the actual ground firmware. Python consumes stdout.
const {device} = require('./firmware-host.cjs');

const ground = device('ground', true);
if (process.argv.includes('--legacy-padding')) {
  // Replay the pre-fix serializer under the pinned MakeCode runtime.
  ground.run('emit = (kind, id, fields) => serial.writeLine("2|" + kind + "|" + id + "|" + fields)');
}
ground.forever[3](); // Sonar
ground.forever[4](); // HELLO and HEART
const aircraft = device('aircraft', true);
ground.wire = packet => aircraft.receive(packet);
aircraft.wire = packet => ground.receive(packet);
aircraft.buttons[2]();
aircraft.tick(0); // Radio triggers LINK and EVENT
ground.run('startProbe()'); // Packet round trip triggers RTT
process.stdout.write(Buffer.from(ground.serialWrites.join(''), 'ascii'));
