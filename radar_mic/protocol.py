"""Version 2 serial records. Text is bounded printable ASCII without '|'."""
from dataclasses import dataclass
import re

VERSION = "2"
MAX_LINE = 240
CLOCK_MASK = 0x3FFFFFFF
TEXT_LEASE_MS = 10000
SONAR_MIN_CM = 4
SONAR_MAX_CM = 400
RSSI_UNKNOWN = -128
COMMAND_TYPES = {"TEXT", "CANCEL", "SCAN", "THRESH", "PING"}
FIELD_COUNTS = {
    "HELLO": 2, "TEXT": 3, "CANCEL": 1, "SCAN": 1, "THRESH": 1, "PING": 1,
    "ACK": 1, "ERROR": 1, "EVENT": 3, "SONAR": 2, "LINK": 3, "RTT": 3, "HEART": 3,
}
ACK_RESULTS = {"APPLIED", "RECEIVED", "CANCELLED"}
ERROR_RESULTS = {
    "BAD_RECORD", "BAD_COMMAND", "ID_CONFLICT", "BUSY", "LINE_TOO_LONG",
    "RADIO_TIMEOUT", "EXPIRED", "STALE_BOOT",
}


def valid_text(text: str) -> bool:
    return 1 <= len(text) <= 80 and all(32 <= ord(c) <= 126 and c != "|" for c in text)


@dataclass(frozen=True)
class Record:
    kind: str
    id: str
    fields: tuple[str, ...]

    def encode(self) -> bytes:
        line = "|".join((VERSION, self.kind, self.id, *self.fields))
        parse(line)
        return (line + "\n").encode("ascii")


def parse(line: str) -> Record:
    if len(line) > MAX_LINE or any(ord(c) < 32 or ord(c) > 126 for c in line):
        raise ValueError("Invalid record length or characters")
    parts = line.split("|")
    if len(parts) < 4 or parts[0] != VERSION or parts[1] not in FIELD_COUNTS:
        raise ValueError("Unknown protocol/version/type")
    kind, ident = parts[1:3]
    id_pattern = r"[0-9a-f]{32}" if kind in COMMAND_TYPES | {"ACK", "ERROR"} else r"[0-9a-f]{4}"
    if not re.fullmatch(id_pattern, ident) and not (kind == "ERROR" and ident == "0000"):
        raise ValueError("Invalid ID")
    fields = parts[3:]
    if len(fields) != FIELD_COUNTS[kind]:
        raise ValueError("Wrong field count")

    def integer(value, low, high):
        if not re.fullmatch(r"-?[0-9]{1,10}", value) or not low <= int(value) <= high:
            raise ValueError("Number out of range")

    if kind in {"TEXT", "CANCEL", "HEART"}:
        boot = fields[1] if kind == "HEART" else fields[0]
        if not re.fullmatch(r"[0-9a-f]{16}", boot):
            raise ValueError("Invalid ground boot ID")
    if kind == "TEXT":
        integer(fields[1], 0, CLOCK_MASK)
        if not valid_text(fields[2]):
            raise ValueError("Text must be 1–80 printable ASCII characters, excluding |")
    if kind == "ACK" and fields[0] not in ACK_RESULTS:
        raise ValueError("Invalid acknowledgment")
    if kind == "ERROR" and fields[0] not in ERROR_RESULTS:
        raise ValueError("Invalid error")
    if kind == "HELLO" and fields != ["GROUND01", "47"]:
        raise ValueError("Incompatible ground firmware/group")
    if kind == "SCAN" and fields[0] not in {"0", "1"}:
        raise ValueError("Invalid scan state")
    if kind == "THRESH": integer(fields[0], 2, 400)
    if kind == "PING" and fields[0] != "AIR101": raise ValueError("Unknown aircraft")
    if kind == "SONAR":
        if fields[0] not in {"VALID", "NO_TARGET", "OFF", "FAULT"}: raise ValueError("Invalid sensor state")
        if fields[0] == "VALID":
            integer(fields[1], SONAR_MIN_CM, SONAR_MAX_CM)
        elif fields[1] != "0":
            raise ValueError("Invalid distance for sonar state")
    if kind in {"EVENT", "LINK"}:
        if fields[0] != "AIR101": raise ValueError("Unknown aircraft")
        integer(fields[2], RSSI_UNKNOWN, 0)
        if kind == "EVENT" and fields[1] not in {"POSITION", "LANDING", "MAYDAY"}: raise ValueError("Invalid event")
        if kind == "LINK" and fields[1] not in {"UP", "LOST"}: raise ValueError("Invalid link")
    if kind == "RTT":
        if fields[0] not in {"OK", "LOST"}: raise ValueError("Invalid probe state")
        integer(fields[1], 0, 60000)
        integer(fields[2], RSSI_UNKNOWN, 0)
    if kind == "HEART":
        if fields[0] != "GROUND01": raise ValueError("Unknown ground")
        integer(fields[2], 0, CLOCK_MASK)
    return Record(kind, parts[2], tuple(fields))


class LineDecoder:
    """Bounded incremental decoder; discard an oversized line through its newline."""
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False

    def feed(self, data: bytes):
        lines = []
        for byte in data:
            if byte == 10:
                if not self.discard:
                    line = self.buffer.removesuffix(b"\r")
                    if len(line) <= MAX_LINE:
                        lines.append(line.decode("ascii", errors="replace"))
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE + 1:
                    self.buffer.clear()
                    self.discard = True
        return lines
