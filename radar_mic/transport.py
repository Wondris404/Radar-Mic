"""All serial work is bounded and nonblocking on the Qt event loop."""
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4
import serial
from serial.tools import list_ports
from .protocol import LineDecoder, Record


def ports():
    return [(p.device, f"{p.device} — {p.description}") for p in list_ports.comports()]


class SerialTransport:
    def __init__(self):
        self.port = None
        self.decoder = LineDecoder()

    def open(self, name):
        self.close()
        self.port = serial.Serial(name, 115200, timeout=0, write_timeout=0)
        self.decoder = LineDecoder()

    def close(self):
        if self.port:
            self.port.close()
        self.port = None

    def send(self, record):
        if not self.port: raise OSError("Serial disconnected")
        data = record.encode()
        if self.port.write(data) != len(data): raise OSError("Incomplete serial write")

    def poll(self):
        if not self.port: return []
        return self.decoder.feed(self.port.read(min(self.port.in_waiting, 4096)))


@dataclass
class Pending:
    record: Record
    started: float
    last_sent: float
    attempts: int = 1


class Delivery:
    """Track command results and retry the exact same record within a fixed deadline."""

    TIMEOUT = 12
    RETRY_INTERVAL = 4

    def __init__(self, send, report):
        self.send, self.report = send, report
        self.pending: dict[str, Pending] = {}

    def command(self, kind, *fields, now=None):
        now = monotonic() if now is None else now
        if len(self.pending) >= 8:
            raise ValueError("Command queue full")
        ident = uuid4().hex
        record = Record(kind, ident, tuple(fields))
        # Validate before placing the record on either transport.
        record.encode()
        self.send(record)
        self.pending[ident] = Pending(record, now, now)
        return ident

    def cancel_text(self, now=None):
        now = monotonic() if now is None else now
        cancellations = []
        for ident, item in self.pending.items():
            if item.record.kind != "TEXT":
                continue
            record = Record("CANCEL", ident, (item.record.fields[0],))
            self.pending[ident] = Pending(record, now, now)
            cancellations.append(record)
            self.report(f"CANCEL REQUESTED {ident} — waiting for ground acknowledgment")
        # Stop every local TEXT retry even if the first cancellation write fails.
        for record in cancellations:
            self.send(record)

    def abandon(self):
        for ident in self.pending:
            self.report(f"DISCONNECTED {ident} — command outcome unknown")
        self.pending.clear()

    def receive(self, record):
        if record.kind not in {"ACK", "ERROR"}:
            return
        result = record.fields[0]
        item = self.pending.pop(record.id, None)
        late = "LATE " if item is None and record.id != "0000" else ""
        if result == "RECEIVED":
            detail = "aircraft accepted the text for display"
        elif result == "APPLIED":
            detail = "ground applied the command"
        elif result == "CANCELLED":
            detail = "ground stopped further transmission; prior reception unknown"
        elif result in {"EXPIRED", "RADIO_TIMEOUT"}:
            detail = "transmission stopped; aircraft reception unconfirmed"
        else:
            detail = "ground rejected the command"
        self.report(f"{late}{record.kind} {result} {record.id} — {detail}")

    def tick(self, now):
        for ident, item in list(self.pending.items()):
            if now - item.started >= self.TIMEOUT:
                del self.pending[ident]
                operation = "CANCELLATION" if item.record.kind == "CANCEL" else "TRANSMISSION"
                self.report(f"{operation} TIMEOUT {ident} — outcome unconfirmed")
            elif item.attempts < 3 and now - item.last_sent >= self.RETRY_INTERVAL:
                self.send(item.record)
                item.last_sent = now
                item.attempts += 1
