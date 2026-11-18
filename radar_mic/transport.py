"""All serial work is bounded and nonblocking on the Qt event loop."""
from time import monotonic
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


class Delivery:
    """PC retries reuse command IDs; ground deduplicates for 30 seconds."""
    def __init__(self, send, report):
        self.send, self.report = send, report
        self.pending = {}
        self.counter = 0

    def command(self, kind, *fields, now=None):
        now = monotonic() if now is None else now
        if len(self.pending) >= 8: raise ValueError("Command queue full")
        self.counter = (self.counter + 1) % 65536
        ident = f"{self.counter:04x}"
        record = Record(kind, ident, tuple(fields))
        self.send(record)
        self.pending[ident] = [record, now, 1]
        return ident

    def receive(self, record):
        if record.kind in {"ACK", "ERROR"}:
            self.pending.pop(record.id, None)
            self.report(f"{record.kind} {record.id}: {' '.join(record.fields)}")

    def tick(self, now):
        for ident, item in list(self.pending.items()):
            if now - item[1] >= 4:
                if item[2] >= 3:
                    del self.pending[ident]
                    self.report(f"TIMEOUT {ident} — delivery unconfirmed")
                else:
                    self.send(item[0])
                    item[1], item[2] = now, item[2] + 1
