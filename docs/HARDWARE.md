# Wiring and bench verification

Ground station: micro:bit **V2**, USB data cable to Windows 11. Sonar:bit Signal
→ **P2**, Voltage → **3V**, Ground → **GND**. Secure it to the LEGO mount facing
forward; there is no servo, angular encoder, or 360-degree scan. Disconnect power
before wiring; follow the sensor manufacturer's connector labels.

Aircraft: second micro:bit V2 fixed to the LEGO aircraft, USB power bank.
No external radio module is needed. Both programs use group 47 / band 7.
The power bank must stay on at the micro:bit's low load.

## Flash

Download **RADAR-MIC-Firmware** and **RADAR-MIC-Windows** from the same successful
[Actions run](https://github.com/Wondris404/Radar-Mic/actions/workflows/verify.yml).
Sign in to GitHub to download artifacts. Choose a run that includes USB protocol 2.
The v2 desktop app requires the v2 ground firmware.

1. Extract the firmware artifact. Connect the ground micro:bit V2 with a USB data
   cable. Copy `radar-mic-ground.hex` to its `MICROBIT` drive and wait for the
   board to finish flashing.
2. Connect the aircraft micro:bit V2 separately. Copy
   `radar-mic-aircraft.hex` to its `MICROBIT` drive. Wait for flashing to finish
   before moving the aircraft board to its USB power bank.
3. Open the Windows artifact, extract `RADAR-MIC-Windows.zip`, and keep
   `RADAR-MIC.exe` with its accompanying files. Launch the EXE from there.

For source builds, use the CLI commands in the README. You can also open each HEX
in [MakeCode](https://makecode.microbit.org/) or create separate JavaScript
projects using each role's `main.ts`, `radio.ts` and `pxt.json`.
The ground manifest pins the official ELECFREAKS Sonar:bit extension.

## First bench test

1. With the ground board disconnected, wire the sensor **Signal → P2, Voltage →
   3V, Ground → GND**. Connect ground to the PC over a USB data cable, power the
   aircraft, and close any MakeCode serial console or other COM-port software.
2. In RADAR-MIC, choose **HARDWARE**, click **Discover ports**, select the ground
   board's COM port, then click **Connect**. You can check the COM number in
   Windows Device Manager under **Ports (COM & LPT)**. Wait for **protocol 2 /
   GROUND01 compatible**, **Heartbeat: OK**, and **LINK ACTIVE**.
3. Type `AIR101 HOLD` and click **SEND**. Expect a TX log entry followed by
   **ACK RECEIVED** and verify that the aircraft scrolls the text.
4. Press aircraft **A** for POSITION, **B** for LANDING, then **A+B** for MAYDAY.
   Check that the PC displays the red timestamped MAYDAY banner. Unplug and
   reconnect ground USB. Confirm the alert stays visible, then click
   **Acknowledge MAYDAY** to clear it.
5. Place a flat obstacle 20–100 cm in front of the sensor. Compare the reading
   with a ruler, then move the obstacle away and check **NO ULTRASONIC TARGET**.
   Ground **A** toggles scanning and **B** scrolls link/sensor status.
6. Switch off aircraft power and send a test message. Check for
   **AIRCRAFT SIGNAL LOST** within 7 seconds and a radio timeout or expiry with
   unconfirmed reception. To cancel pending text, click **Cancel pending text**
   and check the log for the ground result.

Reconnection uses the selected port. Re-select it if Windows assigns a different
COM number. A disconnection resets telemetry and outstanding PC delivery state,
while the MAYDAY banner stays latched within the running app.

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
