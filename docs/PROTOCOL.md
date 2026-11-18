# RADAR-MIC protocol

## USB serial v2

Use the matching v2 desktop app and ground firmware. The radio format is still v1.
The link uses 115200 baud, 8N1 and ASCII. The desktop sends LF and the ground sends
CRLF. One record is `2|TYPE|id|field[|field...]`. The ground emits the record and
its terminator in a single `serial.writeString` call because MakeCode
`serial.writeLine` inserts spaces before CRLF by default.

The line limit is 240 bytes before the terminator. Overlong lines are discarded
through LF. Text is 1–80 printable ASCII characters (32–126), excluding `|`.
Leading and trailing spaces in TEXT are preserved. Numeric and enum fields cannot
contain padding.

| PC command | Fields | Meaning |
|---|---|---|
| TEXT | boot_id,deadline_ms,text | Send expiring text to AIR101 |
| CANCEL | boot_id | Stop further attempts for this TEXT ID |
| SCAN | 0 or 1 | Stop/start P2 sampling |
| THRESH | integer 2–400 | Obstacle threshold in cm |
| PING | AIR101 | Start a probe if none is outstanding |

| Ground record | Fields | Meaning |
|---|---|---|
| HELLO | GROUND01,47 | USB compatibility and radio group |
| HEART | GROUND01,boot_id,uptime_ms | Ground heartbeat every 2 seconds |
| SONAR | VALID/NO_TARGET/OFF/FAULT,cm | VALID is 2–400; other states use 0 |
| LINK | AIR101,UP/LOST,rssi | Latest link state; RSSI -128 means unknown |
| EVENT | AIR101,POSITION/LANDING/MAYDAY,rssi | Aircraft button event and ground RSSI |
| RTT | OK/LOST,milliseconds,rssi | Probe outcome; LOST uses a 0 ms placeholder |
| ACK | APPLIED/RECEIVED/CANCELLED | Ground action applied, aircraft receipt confirmed, or ground stopped sending |
| ERROR | reason | BAD_RECORD, BAD_COMMAND, ID_CONFLICT, BUSY, LINE_TOO_LONG, RADIO_TIMEOUT, EXPIRED, STALE_BOOT |

PC command IDs are 32 lowercase hex digits generated from fresh UUIDv4 values.
ACK and ERROR echo the ID. Unattributed errors and periodic telemetry use
`0000`. EVENT, RTT and LINK can carry a four-digit radio packet ID. Logs use
UTC receipt time.

```text
2|HELLO|0000|GROUND01|47
2|HEART|0000|GROUND01|0123456789abcdef|2000
2|TEXT|d7aad368090c4bbf8254d5a5595af957|0123456789abcdef|12000|AIR101 HOLD
2|ACK|d7aad368090c4bbf8254d5a5595af957|RECEIVED
2|CANCEL|6b46fa77b0414e68a6ce813190a3c703|0123456789abcdef
2|ACK|6b46fa77b0414e68a6ce813190a3c703|CANCELLED
2|EVENT|03af|AIR101|LANDING|-63
2|EVENT|03b0|AIR101|MAYDAY|-70
2|SONAR|0000|VALID|42
2|RTT|1111|OK|28|-65
2|LINK|0000|AIR101|LOST|-65
```

A fresh HELLO and HEART are required to send PC commands. HEART goes stale after
five seconds even if other telemetry is still flowing. Its 16-digit `boot_id`
changes on ground restart, and its uptime wraps modulo 2³⁰ milliseconds.

TEXT carries an absolute deadline of the latest observed ground uptime plus
10 seconds, on that same wrapping clock. The board rejects another boot's
messages and expires queued or active text before sending another fragment.
Retries keep the original deadline. The desktop stops retrying and reports an
unconfirmed outcome after 12 seconds from its original send, even if the UI
timer was delayed. This leaves headroom for board processing and does not
require synchronizing wall clocks.

The PC tracks up to eight commands with up to three USB attempts spaced four
seconds apart. The board caches up to 32 commands and results for 30 seconds.
Identical retries replay cached results without applying commands again.
Conflicting reuse returns ID_CONFLICT. Cancellation reuses the TEXT ID and boot
ID. The board removes queued work or stops remaining fragments, remembers the
cancellation, and acknowledges it. If receipt was already confirmed, the board
replays RECEIVED. Once the PC requests cancellation it only retries CANCEL.
A USB interruption can prevent cancellation confirmation, while the board's
deadline still applies. New connections do not replay outstanding commands.

RECEIVED confirms that the aircraft firmware reassembled the text and accepted
it for LED display. A person reading the text or the end of LED scrolling is
outside this acknowledgment. RADIO_TIMEOUT and desktop TRANSMISSION TIMEOUT
mean receipt is unconfirmed. CANCELLED confirms no further attempts on the
ground; an already transmitted packet can still have been received. A late
reply is logged with its actual outcome.

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
A sender queues at most eight routine messages. Aircraft MAYDAY has its own
reserved slot and takes precedence over routine messages, including retries.
A repeated A+B press while an emergency is active refers to the same outstanding
message. Its pending, acknowledged, or failed status has a reserved LED display
slot. Fragments are spaced by 12 ms in a dedicated fiber. The sender retries
after 650 ms, with up to three attempts. Receiver holds at most four partial messages, each ≤96 characters,
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
After 7 seconds without valid radio traffic the link is LOST. The desktop tracks
USB heartbeat freshness separately from the sonar stream, which goes stale
after 2 seconds without a sample.
