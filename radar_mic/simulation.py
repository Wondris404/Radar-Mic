"""Deterministic, explicit simulation; never selected as hardware fallback."""
import math
from .protocol import CLOCK_MASK, Record


class Simulation:
    BOOT_ID = "0000000000000001"

    def __init__(self):
        self.step = 0
        self.scanning = True
        self.failed = False
        self.sensor_failed = False
        self.loss_percent = 10
        self.queue = []
        self.pending_text = {}
        self.text_results = {}

    def send(self, r):
        if r.kind in {"TEXT", "CANCEL"}:
            if r.id in self.text_results:
                self.queue.append(self.text_results[r.id])
            elif r.kind == "CANCEL":
                self.pending_text.pop(r.id, None)
                self.queue.append(self.text_result(r.id, "CANCELLED"))
            else:
                self.pending_text.setdefault(r.id, self.failed or self.loss_percent == 100)
        elif r.kind == "SCAN":
            self.scanning = r.fields[0] == "1"
            self.queue.append(Record("ACK", r.id, ("APPLIED",)))
        elif r.kind in {"THRESH", "PING"}: self.queue.append(Record("ACK", r.id, ("APPLIED",)))

    def text_result(self, ident, result):
        record = Record("ERROR" if result == "RADIO_TIMEOUT" else "ACK", ident, (result,))
        if len(self.text_results) >= 32:
            del self.text_results[next(iter(self.text_results))]
        self.text_results[ident] = record
        return record

    def event(self, name):
        if not self.failed:
            self.queue.append(Record("EVENT", f"{self.step % 65536:04x}", ("AIR101", name, "-62")))

    def poll(self):
        self.step += 1
        r = [
            Record("HELLO", "0000", ("GROUND01", "47")),
            Record("HEART", "0000", ("GROUND01", self.BOOT_ID, str((self.step * 500) & CLOCK_MASK))),
            *self.queue,
        ]
        self.queue = []
        for ident, failed_at_send in self.pending_text.items():
            failed = failed_at_send or self.failed or self.loss_percent == 100
            r.append(self.text_result(ident, "RADIO_TIMEOUT" if failed else "RECEIVED"))
        self.pending_text.clear()
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
        return [x.encode().decode().removesuffix("\n") for x in r]
