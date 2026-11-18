"""Pure sensor state; future physical ranging providers stay separate from radio."""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from .protocol import Record


class RangingProvider(Protocol):
    source: str
    def measured_distance_cm(self) -> float | None: ...


@dataclass
class Calibration:
    near: int = -55
    far: int = -80
    enabled: bool = False

    def classify(self, rssi):
        if not self.enabled or rssi is None:
            return "UNKNOWN (uncalibrated)"
        return ("NEAR" if rssi >= self.near else "FAR" if rssi < self.far else "MEDIUM") + " (low confidence)"


class State:
    def __init__(self):
        self.calibration = Calibration()
        self.reset()

    def reset(self):
        self.compatible = False
        self.connected = False
        self.last_ground = None
        self.last_radio = None
        self.last_sonar = None
        self.last_seen = "—"
        self.sensor = "UNAVAILABLE"
        self.distance = None
        self.rssi = None
        self.link = False
        self.last_message = "—"
        self.emergency = ""
        self.rtts = deque(maxlen=120)
        self.probes = deque(maxlen=120)
        self.distances = deque(maxlen=120)
        self.signals = deque(maxlen=120)
        self.threshold = 50
        self.latest_rtt = None

    def apply(self, record: Record, now: float):
        self.last_ground = now
        k, f = record.kind, record.fields
        if k == "HELLO": self.compatible = True
        if k == "SONAR":
            self.last_sonar = now
            self.sensor = f[0]
            self.distance = int(f[1]) if f[0] == "VALID" else None
            self.distances.append(self.distance)
        if k in {"LINK", "EVENT"}:
            self.link = k == "EVENT" or f[1] == "UP"
            self.rssi = int(f[2])
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
                self.rssi = int(f[2])

    def tick(self, now):
        if self.last_sonar is None or now - self.last_sonar > 2:
            self.sensor, self.distance = "UNAVAILABLE", None
        if self.last_radio is None or now - self.last_radio > 7:
            self.link = False
        if self.last_ground is None or now - self.last_ground > 5:
            self.compatible = False
            self.link = False

    @property
    def loss(self):
        return 100 * (1 - sum(self.probes) / len(self.probes)) if self.probes else None

    @property
    def obstacle(self):
        if self.sensor == "VALID": return f"{self.distance} cm"
        return {"NO_TARGET": "NO ULTRASONIC TARGET", "OFF": "SCANNING OFF"}.get(self.sensor, "UNAVAILABLE")
