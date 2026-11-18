"""Deterministic, explicit simulation; never selected as hardware fallback."""
import math
from .protocol import Record


class Simulation:
    def __init__(self):
        self.step = 0
        self.scanning = True
        self.failed = False
        self.sensor_failed = False
        self.loss_percent = 10
        self.queue = [Record("HELLO", "0000", ("GROUND01", "47"))]

    def send(self, r):
        if r.kind == "TEXT": self.queue.append(Record("ACK", r.id, ("DELIVERED",)))
        elif r.kind == "SCAN":
            self.scanning = r.fields[0] == "1"
            self.queue.append(Record("ACK", r.id, ("APPLIED",)))
        elif r.kind in {"THRESH", "PING"}: self.queue.append(Record("ACK", r.id, ("APPLIED",)))

    def event(self, name):
        if not self.failed:
            self.queue.append(Record("EVENT", f"{self.step % 65536:04x}", ("AIR101", name, "-62")))

    def poll(self):
        self.step += 1
        r = self.queue
        self.queue = []
        r.append(Record("HELLO", "0000", ("GROUND01", "47")))
        r.append(Record("HEART", "0000", ("GROUND01", str(self.step * 500))))
        if not self.sensor_failed:
            distance = int(90 + 75 * math.sin(self.step / 8))
            state = "OFF" if not self.scanning else "NO_TARGET" if self.step % 30 > 24 else "VALID"
            r.append(Record("SONAR", "0000", (state, str(distance if state == "VALID" else 0))))
        lost = self.failed or (self.step * 37 % 100 < self.loss_percent)
        if not self.failed:
            r.append(Record("LINK", "0000", ("AIR101", "UP", str(-62 + self.step % 9))))
        else:
            r.append(Record("LINK", "0000", ("AIR101", "LOST", "-128")))
        r.append(Record("RTT", f"{self.step % 65536:04x}", ("LOST" if lost else "OK", "0" if lost else str(18 + self.step % 35), "-62")))
        return [x.encode().decode().strip() for x in r]
