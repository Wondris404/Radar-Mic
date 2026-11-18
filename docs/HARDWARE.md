# Wiring and bench verification

Ground station: micro:bit **V2**, USB data cable to Windows 11. Sonar:bit Signal
→ **P2**, Voltage → **3V**, Ground → **GND**. Secure it to the LEGO mount facing
forward; there is no servo, angular encoder, or 360-degree scan. Disconnect power
before wiring; follow the sensor manufacturer's connector labels.

Aircraft: second micro:bit V2 fixed to the LEGO aircraft, USB power bank.
No external radio module is needed. Both programs use group 47 / band 7.
The power bank must stay on at the micro:bit's low load.

## Flash

Open https://makecode.microbit.org/ and create two projects in JavaScript mode.
For each project paste its `firmware/<role>/main.ts`; use Explorer → + to create
`radio.ts` and paste `firmware/<role>/radio.ts`. Open `pxt.json` and replace it
with the corresponding committed file, preserving the two TypeScript files.
The ground project pins the official ELECFREAKS Sonar:bit extension; allow its
installation. Alternatively import the repository HEX artifacts after downloading
the Actions firmware artifact (when available). Download and copy each compiled
HEX to the correct device's MICROBIT drive. Label the boards GROUND01 and AIR101.
Do not flash both boards with the same program.

CLI build is described in the README. Build products are universal micro:bit HEX
files from MakeCode; these projects are intended and tested at compile time for V2.

## First bench test

1. Power aircraft, connect ground over a USB **data** cable. Close MakeCode serial
   console/other COM-port software before opening RADAR-MIC.
2. Select Hardware, Discover ports, select the micro:bit COM port, Connect.
   Wait for compatible protocol/ground heartbeat and LINK ACTIVE.
3. Type `AIR101 HOLD`, SEND. Expect TX then ACK DELIVERED and aircraft scrolling.
4. Aircraft A → POSITION with RSSI on PC and ACK POSITION on aircraft. B → LANDING
   notification; A+B → timestamped red MAYDAY; clear the PC latch after checking.
5. Place a flat obstacle 20–100 cm in front of ground sensor. Compare the displayed
   centimeters with a ruler. Move it away/out of view: NO ULTRASONIC TARGET.
6. Ground A toggles scanning. B scrolls link/sensor status without blocking radio.
7. Unplug aircraft power: within 7 seconds AIRCRAFT SIGNAL LOST; sonar continues.
   Unplug ground USB: stale sonar becomes UNAVAILABLE; reconnect is attempted every
   3 seconds. Re-select port if Windows assigns a different COM number.

## Limits and calibration

Sonar is nominally 2–400 cm and depends strongly on object material, angle, beam
coverage and ambient conditions. The extension returns zero on pulse timeout:
**no echo cannot distinguish an unplugged/dead sensor from no target**. Thus zero
is NO ULTRASONIC TARGET, not a diagnosed fault. Missing telemetry is UNAVAILABLE;
a future diagnostic provider can emit FAULT. No radio-derived substitute exists.

Ultrasonic detections may be a wall or a LEGO object, not AIR101. Its forward
marker has measured range but no measured angle. The displayed narrow sector is
illustrative, not a calibrated beam pattern. Aircraft radio status has no plot
position. No altitude or coordinates are generated.

RSSI classification defaults to UNKNOWN. To experiment, collect RSSI observations
at locally chosen near/middle/far placements, with the same mounting/orientation,
and set NEAR and FAR thresholds in the UI (NEAR must exceed FAR). Enable calibration
only after this; it is low confidence, changes with interference, body shielding,
reflections, battery, and orientation, and is not a physical range measurement.
RTT is application latency only. It cannot measure radio propagation distance.

No hardware was attached in development. USB enumeration on Windows, actual
sensor readings, radio range/packet-loss characteristics, button/LED operation,
and power-bank behavior require the above physical acceptance test.
