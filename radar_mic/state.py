"""Pure sensor state; future physical ranging providers stay separate from radio."""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from .protocol import CLOCK_MASK, RSSI_UNKNOWN, TEXT_LEASE_MS, Record


class RangingProvider(Protocol):
    source: str
    def measured_distance_cm(self) -> float | None: ...


@dataclass
class Calibration:
    near: int = -55
    far: int = -80
    enabled: bool = False

    def classify(self, rssi):
        if rssi is None:
            return "UNKNOWN (RSSI unavailable)"
        if not self.enabled:
            return "UNKNOWN (uncalibrated)"
        return ("NEAR" if rssi >= self.near else "FAR" if rssi < self.far else "MEDIUM") + " (low confidence)"


class State:
    def __init__(self):
        self.calibration = Calibration()
        self.reset()

    def reset(self, *, preserve_emergency=False):
        self.compatible = False
        self.last_hello = None
        self.last_heartbeat = None
        self.ground_boot = None
        self.ground_clock = None
        self.last_radio = None
        self.last_sonar = None
        self.last_seen = "—"
        self.sensor = "UNAVAILABLE"
        self.distance = None
        self.rssi = None
        self.link = False
        self.last_message = "—"
        if not preserve_emergency:
            self.emergency = ""
        self.rtts = deque(maxlen=120)
        self.probes = deque(maxlen=120)
        self.distances = deque(maxlen=120)
        self.signals = deque(maxlen=120)
        self.threshold = 50
        self.latest_rtt = None

    def apply(self, record: Record, now: float):
        k, f = record.kind, record.fields
        if k == "HELLO":
            self.last_hello = now
            self.compatible = True
        if k == "HEART":
            self.last_heartbeat = now
            self.ground_boot, self.ground_clock = f[1], int(f[2])
        if k == "SONAR":
            self.last_sonar = now
            self.sensor = f[0]
            self.distance = int(f[1]) if f[0] == "VALID" else None
            self.distances.append(self.distance)
        if k in {"LINK", "EVENT"}:
            self.link = k == "EVENT" or f[1] == "UP"
            self.rssi = read_rssi(f[2]) if self.link else None
            if self.link:
                self.last_radio = now
                self.last_seen = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                self.signals.append(self.rssi)
        if k == "EVENT":
            self.last_message = f[1]
            if f[1] == "MAYDAY": self.emergency = f"MAYDAY • AIR101 • {self.last_seen}"
        if k == "RTT":
            ok = f[0] == "OK"
            self.probes.append(ok)
            if ok:
                self.latest_rtt = int(f[1])
                self.rtts.append(self.latest_rtt)
                self.rssi = read_rssi(f[2])

    def tick(self, now):
        if self.last_sonar is None or now - self.last_sonar > 2:
            self.sensor, self.distance = "UNAVAILABLE", None
        if self.last_radio is None or now - self.last_radio > 7:
            self.link = False
        self.compatible = self.last_hello is not None and now - self.last_hello <= 5
        if not self.heartbeat_alive(now):
            self.link = False

    def heartbeat_alive(self, now):
        return self.last_heartbeat is not None and now - self.last_heartbeat <= 5

    def text_lease(self):
        return self.ground_boot, str((self.ground_clock + TEXT_LEASE_MS) & CLOCK_MASK)

    @property
    def loss(self):
        return 100 * (1 - sum(self.probes) / len(self.probes)) if self.probes else None

    @property
    def obstacle(self):
        if self.sensor == "VALID": return f"{self.distance} cm"
        return {
            "NO_TARGET": "NO VALID ULTRASONIC DISTANCE", "OFF": "SCANNING OFF",
        }.get(self.sensor, "UNAVAILABLE")


def read_rssi(value: str) -> int | None:
    rssi = int(value)
    return rssi if rssi != RSSI_UNKNOWN else None
