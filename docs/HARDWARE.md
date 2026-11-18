# Wiring and bench verification

Use two BBC micro:bit **V2** boards. Identify the ground board and the aircraft
board before flashing. Use USB cables that carry both data and power.

The ELECFREAKS EF04089 Sonar:bit supports DC 3–5 V and the manufacturer's
3.3 V microcontroller example uses P2. On the ground board connect Sonar:bit
**S → P2, V → 3V, G → GND** through the expansion board. Disconnect all power
first. Check the header labels and board orientation against the expansion
board's documentation. Some breakout boards provide a separate 5 V rail or
selectable logic levels. Use the 3 V rail and 3.3 V logic for this connection.
The micro:bit pins cannot take a 5 V signal. Keep the sensor facing forward on
the LEGO tower. [ELECFREAKS Sonar:bit](https://shop.elecfreaks.com/products/elecfreaks-octopus-sonar-bit) ·
[micro:bit pinout](https://tech.microbit.org/hardware/edge-connector/)

Power the aircraft from a computer USB port for the first bench test. For
standalone use the micro:bit's battery connector with the Foundation's
recommended 2 × AAA holder. The Foundation advises against generic USB power
banks, which can shut off or produce out-of-range voltage at low load. The
user's exact power bank and expansion board have not been verified.
[Foundation power guidance](https://tech.microbit.org/hardware/power-supply/#usb-powering) ·
[Battery holder instructions](https://support.microbit.org/support/solutions/articles/19000013982-how-do-i-power-my-micro-bit-)

## Flash both boards and start Windows

1. Sign in to GitHub. Download **RADAR-MIC-Firmware** and **RADAR-MIC-Windows**
   from the [same successful Actions run](https://github.com/Wondris404/Radar-Mic/actions/workflows/verify.yml)
   containing the hardware audit. Flash both boards because the audit changes
   the radio format.
2. Extract the firmware bundle. Connect the ground micro:bit with a USB data
   cable. Copy `radar-mic-ground.hex` to its `MICROBIT` drive and wait for
   flashing to finish. Connect the aircraft board separately and do the same
   with `radar-mic-aircraft.hex`.
3. Extract the Windows artifact, then unpack `RADAR-MIC-Windows.zip`.
   Run `RADAR-MIC.exe` while keeping its accompanying files in the same folder.

The CLI commands in the README build the same Universal HEX format. The
ground manifest pins the official Sonar:bit extension.

## First bench test

1. Wire the unpowered ground board as above. Connect it to the Windows laptop
   and power the aircraft from another computer USB port or the recommended
   battery holder. Close other serial-monitor programs.
2. Open Windows **Device Manager → Ports (COM & LPT)**. Note the ground board's
   COM number by watching the list when plugging in that board. In RADAR-MIC
   select **HARDWARE**, click **Discover ports**, select that COM port and click
   **Connect**. Look for **protocol 2 / GROUND01 compatible**, **Heartbeat: OK**
   and **LINK ACTIVE**. If Windows changes the COM number, select it again and
   click **Connect**. [Official Windows USB guidance](https://support.microbit.org/support/solutions/articles/19000089574-micro-bit-does-not-connect-in-windows)
3. Send `AIR101 HOLD`. Verify **ACK RECEIVED** and watch the aircraft LEDs
   scroll the whole text. Confirmation means the aircraft accepted the text
   for display. A person reading the text is outside the ACK.
4. Press and release aircraft **A** (POSITION) and then **B** (LANDING).
   Press **A+B** together and release to test MAYDAY. Verify that the timestamped
   red banner stays visible after unplugging ground USB and reconnecting it.
   Click **Acknowledge MAYDAY** to clear the banner.
5. Place a flat rigid obstacle perpendicular to the beam at 20, 50 and 100 cm.
   Measure from the sensor face. Compare the displayed values with a ruler
   and record deviations. Move the obstacle away and check **NO VALID
   ULTRASONIC DISTANCE**. Ground **A** toggles scanning. The desktop checkbox
   follows the reported state. Ground **B** scrolls radio and sensor status.
6. Remove aircraft power. Check **AIRCRAFT SIGNAL LOST** after the link timeout.
   Send a text test and verify **RADIO_TIMEOUT** or **EXPIRED** and no **ACK
   RECEIVED** for that command. Wait for the result before powering the aircraft
   again. When the link returns, send a different text and verify that only the
   new text is received. For a separate cancellation test, click **Cancel
   pending text** before timeout and check for **ACK CANCELLED**.
7. Leave the setup running and record whether the USB port, P2 measurement
   and radio stay stable. Range, interference, the actual LED scroll, and
   power-source behavior require the physical boards.

## Interpreting measurements

Sonar:bit reports a nominal 4–400 cm obstacle distance. Temperature, angles and
absorbing surfaces change the echo. No echo, a disconnected sensor and an echo
outside the accepted range can all produce no valid distance. A silent telemetry
stream is shown as UNAVAILABLE. The fixed sector is illustrative. The module
does not measure angle, identify the aircraft, or map coordinates.

RSSI is received signal power in dBm when available. Orientation, the mounting,
obstructions and multipath make thresholds installation specific. The desktop
defaults to UNKNOWN and offers optional empirical proximity labels. The RTT
probe measures software turnaround and radio time together. Its losses are
shown separately from text delivery acknowledgments. The application does not
convert RF latency or RSSI to meters, coordinates or altitude.
