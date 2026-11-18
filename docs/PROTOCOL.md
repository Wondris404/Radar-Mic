# RADAR-MIC protocol v1

## USB serial

115200 baud, 8N1, USB CDC, ASCII, one record per LF; CRLF accepted.
`1|TYPE|hhhh|field[|field...]` with a four lowercase hexadecimal command ID.
Maximum line: 240 bytes excluding LF. Invalid lines are rejected; overlong lines
are discarded through LF. No escaping: user text must be 1–80 printable ASCII
characters (32–126), excluding `|`. No Unicode. There is no JSON on the micro:bit.

PC commands (exact field counts):

| Type | Fields | Meaning |
|---|---|---|
| TEXT | text | Deliver text to AIR101 |
| SCAN | 0 or 1 | Stop/start P2 sampling |
| THRESH | integer 2–400 | Obstacle threshold in cm |
| PING | AIR101 | Start one probe if none outstanding |

Ground records:

| Type | Fields | Meaning |
|---|---|---|
| HELLO | GROUND01,47 | Firmware protocol 1 and radio group compatibility |
| HEART | GROUND01,uptime_ms | Ground heartbeat every 2 s |
| SONAR | VALID/NO_TARGET/OFF/FAULT,cm | VALID is 2–400; others use 0 |
| LINK | AIR101,UP/LOST,rssi | Latest link state; RSSI -128 means unknown |
| EVENT | AIR101,POSITION/LANDING/MAYDAY,rssi | Aircraft button event; RSSI at ground reception |
| RTT | OK/LOST,milliseconds,rssi | Probe outcome; LOST has 0 ms (not a measurement) |
| ACK | APPLIED/DELIVERED | Command applied, or full radio text acknowledged |
| ERROR | reason | BAD_RECORD, BAD_COMMAND, ID_CONFLICT, BUSY, LINE_TOO_LONG, RADIO_TIMEOUT |

Examples:

```text
1|HELLO|0000|GROUND01|47
1|TEXT|0001|AIR101 HOLD
1|ACK|0001|DELIVERED
1|EVENT|03af|AIR101|LANDING|-63
1|EVENT|03b0|AIR101|MAYDAY|-70
1|SONAR|0000|VALID|42
1|RTT|1111|OK|28|-65
1|LINK|0000|AIR101|LOST|-65
```

IDs in ACK/ERROR echo the PC command. EVENT IDs identify a radio message;
RTT IDs identify probes. Periodic telemetry uses `0000`. PC logs use UTC receipt
time, not aircraft time; firmware timers are monotonic uptime.

PC allows eight outstanding commands, retries the same ID every 4 s, maximum
three attempts. Ground caches up to 32 command IDs/results for 30 s and rejects
new commands with BUSY if full. Identical retries replay final results without
reapplying; conflicting reuse returns ID_CONFLICT. TEXT gets its final ACK only
after radio reassembly is acknowledged. ACK means accepted by aircraft firmware,
not that a human read the text or that LED scrolling finished. Lost ACKs can leave
successful deliveries unconfirmed. No persistence or exactly-once guarantee across
reboot, reconnect, ID collision, or cache expiry. Reconnecting clears pending PC
commands; they are not automatically replayed into a restarted device.

## Built-in radio

Both devices: **group 47, frequency band 7, transmit power 6**. Change GROUP and
setFrequencyBand in `firmware/shared.ts`, copy it to both projects' `radio.ts`,
and update the HELLO/group compatibility check if changing the group.
Device roles identify themselves with `H|GROUND01` and `H|AIR101` every 2 s.
The group isolates normal classroom traffic; this is unencrypted, unauthenticated
radio and a classroom demonstration, not operational aviation equipment.

Logical bodies: `H|GROUND01`, `H|AIR101`, `T|<text>` (ground to aircraft),
`E|POSITION`, `E|LANDING`, `E|MAYDAY` (aircraft to ground). Receivers validate
role-specific types before acknowledgment. Aircraft is statically AIR101; radio
packets are not globally addressed. Do not run multiple aircraft on this group.

Every sendString is **≤19 ASCII characters**:

* Data: `Dhhhhit<payload>`: D, 4-hex ID, decimal index 0–7, count 1–8,
  then 1–12 characters. All non-final fragments have 12 characters.
* Full-message ACK: `Khhhh`.
* Independent RTT request: `Phhhh`; immediate aircraft reply: `Qhhhh`.

Example for `T|AIR101 HOLD`: `D012302T|AIR101 HOL`, `D012312D`, then `K0123`.
IDs increment modulo 65536, randomized at boot. They are not security nonces.
A sender queues at most eight messages, one active at a time; fragments are
spaced by 12 ms in a dedicated fiber. Retry after 650 ms, maximum three complete
transmissions. Receiver holds at most four partial messages, each ≤96 characters,
with a 3 s lifetime from first fragment. Out-of-order fragments are supported;
identical fragment duplicates are harmless; conflicting fragments/counts are
ignored. Completed IDs are retained for up to 30 s (maximum 32); duplicates are
ACKed without repeated events/scrolling. Reception callbacks do not scroll.
LED display has its own bounded eight-item queue; new text is not acknowledged
while that queue is full, allowing retry/explicit timeout rather than silent drop.

Ground probes run every 2 s with a 1 s timeout and are separate from delivery retries. Ground measures elapsed
`input.runningTime()` between sending P and receiving matching Q, includes
firmware scheduling and packet processing, and reports one OK or LOST per probe.
The desktop summarizes up to 120 outcomes, successful RTTs and RSSI samples.
Neither RTT nor RSSI is converted to meters, altitude, or coordinates.
After 7 s without valid radio traffic the link is LOST. Ground telemetry is stale
after 5 s; sonar stream after 2 s. Separate clocks need no synchronization.
