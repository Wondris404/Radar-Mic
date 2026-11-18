"""Version 1 serial records. Text is bounded printable ASCII without '|'."""
from dataclasses import dataclass
import re

VERSION = "1"
MAX_LINE = 240
TYPES = {"HELLO", "TEXT", "SCAN", "THRESH", "PING", "ACK", "ERROR", "EVENT", "SONAR", "LINK", "RTT", "HEART"}


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
    if len(parts) < 4 or parts[0] != VERSION or parts[1] not in TYPES:
        raise ValueError("Unknown protocol/version/type")
    if not re.fullmatch(r"[0-9a-f]{4}", parts[2]):
        raise ValueError("Invalid ID")
    fields = parts[3:]
    kind = parts[1]
    counts = {"HELLO": 2, "TEXT": 1, "SCAN": 1, "THRESH": 1, "PING": 1,
              "ACK": 1, "ERROR": 1, "EVENT": 3, "SONAR": 2, "LINK": 3,
              "RTT": 3, "HEART": 2}
    if len(fields) != counts[kind]:
        raise ValueError("Wrong field count")
    def integer(value, low, high):
        if not re.fullmatch(r"-?\d{1,9}", value) or not low <= int(value) <= high:
            raise ValueError("Number out of range")
    if kind == "TEXT" and not valid_text(fields[0]):
        raise ValueError("Text must be 1–80 printable ASCII characters, excluding |")
    if kind == "HELLO" and fields != ["GROUND01", "47"]:
        raise ValueError("Incompatible ground firmware/group")
    if kind == "SCAN" and fields[0] not in {"0", "1"}:
        raise ValueError("Invalid scan state")
    if kind == "THRESH": integer(fields[0], 2, 400)
    if kind == "PING" and fields[0] != "AIR101": raise ValueError("Unknown aircraft")
    if kind == "SONAR":
        if fields[0] not in {"VALID", "NO_TARGET", "OFF", "FAULT"}: raise ValueError("Invalid sensor state")
        integer(fields[1], 0, 400)
        if fields[0] == "VALID" and int(fields[1]) < 2: raise ValueError("Invalid distance")
    if kind in {"EVENT", "LINK"}:
        if fields[0] != "AIR101": raise ValueError("Unknown aircraft")
        integer(fields[2], -128, 0)
        if kind == "EVENT" and fields[1] not in {"POSITION", "LANDING", "MAYDAY"}: raise ValueError("Invalid event")
        if kind == "LINK" and fields[1] not in {"UP", "LOST"}: raise ValueError("Invalid link")
    if kind == "RTT":
        if fields[0] not in {"OK", "LOST"}: raise ValueError("Invalid probe state")
        integer(fields[1], 0, 60000)
        integer(fields[2], -128, 0)
    if kind == "HEART":
        if fields[0] != "GROUND01": raise ValueError("Unknown ground")
        integer(fields[1], 0, 2147483647)
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
                    lines.append(self.buffer.rstrip(b"\r").decode("ascii", errors="replace"))
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE:
                    self.buffer.clear()
                    self.discard = True
        return lines
