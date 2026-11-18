"""Responsive desktop console. Hardware mode never falls back to simulation."""
import argparse
import math
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from time import monotonic
from PySide6.QtCore import Qt, QSignalBlocker, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QSpinBox,
    QGroupBox, QSplitter, QCheckBox, QScrollArea)
from .protocol import SONAR_MIN_CM, SONAR_MAX_CM, VERSION, parse, valid_text
from .state import State, read_rssi
from .transport import SerialTransport, Delivery, ports
from .simulation import Simulation

GREEN = QColor("#54f5b1")


class Radar(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.phase = 0
        self.setMinimumSize(340, 340)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(self.width(), self.height()) * .40
        p.fillRect(self.rect(), QColor("#07151d"))
        p.setPen(QPen(QColor("#17483f"), 1))
        for fraction in (.25, .5, .75, 1):
            p.drawEllipse(QPointF(cx, cy), r * fraction, r * fraction)
            p.drawText(QPointF(cx + 6, cy - r * fraction + 15), f"{int(400 * fraction)} cm")
        p.drawLine(QPointF(cx-r, cy), QPointF(cx+r, cy))
        p.drawLine(QPointF(cx, cy-r), QPointF(cx, cy+r))
        p.setBrush(QColor(60, 230, 160, 22))
        p.drawPolygon(QPolygonF([QPointF(cx, cy), QPointF(cx-r*.16, cy-r), QPointF(cx+r*.16, cy-r)]))
        p.setPen(GREEN)
        p.drawText(14, 25, "FIXED FORWARD • ULTRASONIC")
        p.drawText(14, self.height()-32, "Sector is illustrative; beam width is not calibrated")
        p.drawText(14, self.height()-12, "Aircraft has no measured bearing or position")
        if self.state.distance is not None:
            y = cy - r * self.state.distance / 400
            p.setBrush(GREEN)
            p.drawEllipse(QPointF(cx, y), 6, 6)
            p.drawText(QPointF(cx+12, y), f"Obstacle {self.state.distance} cm")
        p.setBrush(QColor("#54f5b1") if self.state.link else QColor("#e56c75"))
        p.drawEllipse(QPointF(cx, cy), 6 + math.sin(self.phase) * 1.5, 6 + math.sin(self.phase) * 1.5)
        p.end()


class Chart(QWidget):
    def __init__(self, values, low, high, label):
        super().__init__()
        self.values, self.low, self.high, self.label = values, low, high, label
        self.setMinimumHeight(85)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#07151d"))
        p.setPen(QColor("#91afa9"))
        p.drawText(8, 16, self.label)
        p.setPen(QPen(GREEN, 1.5))
        prev = None
        values = list(self.values)
        for i, value in enumerate(values):
            if value is None:
                prev = None
                continue
            point = QPointF(8 + i / max(1, len(values)-1) * (self.width()-16),
                            self.height()-8 - (value-self.low)/(self.high-self.low)*(self.height()-34))
            if prev is not None: p.drawLine(prev, point)
            prev = point
        p.end()


def button(text, callback):
    b = QPushButton(text)
    b.clicked.connect(callback)
    return b


def panel(title):
    w = QGroupBox(title)
    layout = QVBoxLayout(w)
    return w, layout


class Window(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.setWindowTitle("RADAR-MIC / Ground control")
        self.resize(1280, 900)
        self.state = State()
        self.serial = SerialTransport()
        self.sim = None
        self.saved_hardware_emergency = ""
        self.delivery = Delivery(self.send_record, self.log)
        self.retry_at = 0
        self.want_connection = False
        self.reconnect_port = None
        self.last_sim = 0
        self.build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(30)
        self.refresh_ports()
        if demo: self.mode.setCurrentIndex(1)

    def build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root = QWidget()
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        outer = QVBoxLayout(root)
        title = QLabel("RADAR–MIC    /    GROUND CONTROL")
        title.setObjectName("title")
        outer.addWidget(title)
        top = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["HARDWARE", "DEMO / SIMULATION"])
        self.mode.currentIndexChanged.connect(self.change_mode)
        top.addWidget(self.mode)
        self.port_box = QComboBox(); self.port_box.setEditable(True)
        top.addWidget(self.port_box, 1)
        top.addWidget(button("Discover ports", self.refresh_ports))
        top.addWidget(button("Connect", self.connect_port))
        top.addWidget(button("Disconnect", self.disconnect_port))
        outer.addLayout(top)
        self.banner = QLabel("HARDWARE • disconnected")
        self.banner.setObjectName("banner")
        outer.addWidget(self.banner)
        self.alert = QLabel("")
        self.alert.setObjectName("alert")
        outer.addWidget(self.alert)
        grid = QGridLayout()
        outer.addLayout(grid)
        radar_panel, r = panel("01 / FIXED-DIRECTION RADAR")
        self.radar = Radar(self.state)
        r.addWidget(self.radar)
        self.obstacle = QLabel("UNAVAILABLE")
        self.obstacle.setObjectName("metric")
        r.addWidget(self.obstacle)
        r.addWidget(QLabel(
            f"Source: Sonar:bit / P2 • obstacle measurement • nominal {SONAR_MIN_CM}–{SONAR_MAX_CM} cm"
        ))
        grid.addWidget(radar_panel, 0, 0, 2, 1)
        info, il = panel("02 / AIRCRAFT • AIR101")
        self.info = QLabel()
        self.info.setWordWrap(True)
        il.addWidget(self.info)
        il.addWidget(QLabel("Position / bearing / altitude: NOT AVAILABLE"))
        il.addWidget(QLabel("Radio proximity requires local calibration; no radio-derived distance."))
        self.calibrate = QCheckBox("Use experimental RSSI calibration (low confidence)")
        self.calibrate.toggled.connect(lambda on: setattr(self.state.calibration, "enabled", on))
        il.addWidget(self.calibrate)
        row = QHBoxLayout()
        for name, attr, default in [("NEAR ≥", "near", -55), ("FAR <", "far", -80)]:
            row.addWidget(QLabel(name))
            spin = QSpinBox(); spin.setRange(-127, -1); spin.setValue(default)
            spin.valueChanged.connect(lambda value, a=attr: setattr(self.state.calibration, a, value))
            row.addWidget(spin)
        il.addLayout(row)
        grid.addWidget(info, 0, 1)
        sensor, sl = panel("03 / SENSOR & LINK MONITOR")
        self.sonar_chart = Chart(self.state.distances, 0, 400, "Ultrasonic / cm • last 120 samples • gaps = unavailable")
        self.rssi_chart = Chart(self.state.signals, -128, 0, "Radio RSSI / dBm • independent aircraft link")
        sl.addWidget(self.sonar_chart); sl.addWidget(self.rssi_chart)
        self.scan = QCheckBox("Ultrasonic scanning"); self.scan.setChecked(True)
        self.scan.toggled.connect(lambda on: self.command("SCAN", "1" if on else "0"))
        row = QHBoxLayout(); row.addWidget(self.scan)
        row.addWidget(QLabel("Obstacle alert ≤ cm"))
        self.threshold = QSpinBox(); self.threshold.setRange(2, 400); self.threshold.setValue(50)
        row.addWidget(self.threshold)
        row.addWidget(button("Apply", self.set_threshold))
        sl.addLayout(row)
        sl.addWidget(button("Probe AIR101 RTT", lambda: self.command("PING", "AIR101")))
        grid.addWidget(sensor, 1, 1)
        comm, cl = panel("04 / ATC COMMUNICATIONS")
        row = QHBoxLayout()
        self.message = QLineEdit(); self.message.setMaxLength(80)
        self.message.setPlaceholderText("ATC text • 1–80 printable ASCII characters • no |")
        self.message.returnPressed.connect(self.send_text)
        row.addWidget(self.message); row.addWidget(button("SEND", self.send_text)); cl.addLayout(row)
        presets = QHBoxLayout()
        for text in ["TAKEOFF", "LAND", "HOLD", "RETURN"]:
            presets.addWidget(button(text, lambda checked=False, t=text: self.transmit(t)))
        presets.addWidget(button("Cancel pending text", self.cancel_pending_text))
        presets.addWidget(button("Acknowledge MAYDAY", lambda: setattr(self.state, "emergency", "")))
        cl.addLayout(presets)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); self.history.setMaximumBlockCount(500)
        cl.addWidget(self.history)
        outer.addWidget(comm)
        self.demo_controls, dl = panel("SIMULATION CONTROLS • GENERATED DATA ONLY")
        row = QHBoxLayout()
        for event in ["POSITION", "LANDING", "MAYDAY"]:
            row.addWidget(button(event, lambda checked=False, e=event: self.sim and self.sim.event(e)))
        self.radio_fail = QCheckBox("Radio failure")
        self.radio_fail.toggled.connect(lambda on: self.sim and setattr(self.sim, "failed", on))
        row.addWidget(self.radio_fail)
        self.sensor_fail = QCheckBox("Stop sensor stream")
        self.sensor_fail.toggled.connect(lambda on: self.sim and setattr(self.sim, "sensor_failed", on))
        row.addWidget(self.sensor_fail)
        row.addWidget(QLabel("Packet loss %"))
        self.loss = QSpinBox(); self.loss.setRange(0, 100); self.loss.setValue(10)
        self.loss.valueChanged.connect(lambda value: self.sim and setattr(self.sim, "loss_percent", value))
        row.addWidget(self.loss); dl.addLayout(row)
        outer.addWidget(self.demo_controls); self.demo_controls.hide()
        self.status = QLabel(); outer.addWidget(self.status)

    def log(self, text):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.history.appendPlainText(f"{stamp} {'[SIM] ' if self.sim else ''}{text}")

    def selected_port(self):
        choice = self.port_box.currentIndex()
        text = self.port_box.currentText()
        if choice >= 0 and text == self.port_box.itemText(choice):
            return self.port_box.currentData()
        return text.strip()

    def refresh_ports(self):
        old = self.selected_port()
        self.port_box.clear()
        for device, label in ports():
            self.port_box.addItem(label, device)
        if old:
            match = self.port_box.findData(old)
            if match >= 0:
                self.port_box.setCurrentIndex(match)
            else:
                self.port_box.setEditText(old)
        elif self.port_box.count() == 0:
            self.port_box.setEditText("COM3")

    def change_mode(self, index):
        self.disconnect_port()
        if self.sim is None:
            self.saved_hardware_emergency = self.state.emergency
        self.state.reset()
        self.sim = Simulation() if index else None
        if self.sim is None:
            self.state.emergency = self.saved_hardware_emergency
        self.demo_controls.setVisible(bool(index))
        for widget in (self.port_box,): widget.setEnabled(not index)
        self.radio_fail.setChecked(False); self.sensor_fail.setChecked(False)
        self.loss.setValue(10)
        self.log("DEMO / SIMULATION enabled" if index else "Hardware mode selected")

    def connect_port(self):
        if self.sim: return
        name = self.selected_port()
        if not name:
            self.log("Select the ground station COM port")
            return
        self.reconnect_port = name
        self.want_connection = True
        self.open_requested_port()

    def open_requested_port(self):
        try:
            if self.serial.port:
                self.close_link(cancel=True)
            self.serial.open(self.reconnect_port)
            self.state.reset(preserve_emergency=True)
            self.log(f"Serial open: {self.reconnect_port} — waiting for protocol {VERSION} HELLO and heartbeat")
        except (OSError, ValueError) as e:
            self.log(str(e)); self.retry_at = monotonic() + 3

    def disconnect_port(self):
        self.want_connection = False
        self.close_link(cancel=True)

    def close_link(self, *, cancel=False):
        if cancel:
            self.cancel_pending_text()
        self.serial.close()
        self.delivery.abandon()
        self.state.reset(preserve_emergency=True)

    def cancel_pending_text(self):
        try:
            self.delivery.cancel_text()
        except OSError as error:
            self.log(f"Could not send cancellation: {error}")

    def send_record(self, record):
        if self.sim: self.sim.send(record)
        else: self.serial.send(record)

    def command(self, kind, *fields):
        now = monotonic()
        self.state.tick(now)
        if not self.state.compatible or not self.state.heartbeat_alive(now):
            self.log(f"Command unavailable — waiting for protocol {VERSION} and a fresh ground heartbeat")
            return
        try:
            command_fields = (*self.state.text_lease(), *fields) if kind == "TEXT" else fields
            ident = self.delivery.command(kind, *command_fields, now=now)
            self.log(f"TX {ident} {kind}: {' '.join(fields)}")
        except (OSError, ValueError) as e: self.log(str(e))

    def set_threshold(self):
        self.state.threshold = self.threshold.value()
        self.command("THRESH", str(self.state.threshold))

    def transmit(self, text):
        if not valid_text(text): self.log("Use 1–80 printable ASCII characters without |")
        else: self.command("TEXT", text)

    def send_text(self):
        self.transmit(self.message.text()); self.message.clear()

    def tick(self):
        now = monotonic()
        try:
            lines = []
            if self.sim:
                if now-self.last_sim >= .5:
                    lines = self.sim.poll(); self.last_sim = now
            else:
                if self.want_connection and not self.serial.port and now >= self.retry_at:
                    self.retry_at = now + 3
                    self.open_requested_port()
                lines = self.serial.poll()
            for line in lines:
                try:
                    record = parse(line)
                    self.apply_record(record, now)
                except ValueError as e: self.log(f"Rejected serial record: {e}")
            self.delivery.tick(now)
        except (OSError, ValueError) as e:
            self.log(f"Serial error: {e}; reconnect in 3s")
            self.close_link()
            self.retry_at = now + 3
        self.state.tick(now)
        self.render_state()

    def apply_record(self, record, now):
        if record.kind not in {"HELLO", "ERROR"} and self.state.last_hello is None:
            return
        if (record.kind == "HEART" and self.state.ground_boot is not None
                and record.fields[1] != self.state.ground_boot):
            self.delivery.abandon("GROUND RESTARTED")
            last_hello = self.state.last_hello
            self.state.reset(preserve_emergency=True)
            self.state.last_hello = last_hello
            self.log("Ground station restarted — cleared pending commands")
        self.state.apply(record, now)
        self.delivery.receive(record)
        if record.kind == "EVENT":
            rssi = read_rssi(record.fields[2])
            signal = "unavailable" if rssi is None else f"{rssi} dBm"
            self.log(f"RX AIR101 {record.fields[1]} • RSSI {signal}")

    def render_state(self):
        s = self.state
        heartbeat = s.heartbeat_alive(monotonic())
        if self.sim:
            self.banner.setText("DEMO / SIMULATION • ALL MEASUREMENTS GENERATED")
        elif s.compatible and heartbeat:
            self.banner.setText(f"HARDWARE • protocol {VERSION} / GROUND01 compatible")
        else:
            self.banner.setText(f"HARDWARE • waiting for protocol {VERSION} HELLO and heartbeat")
        self.alert.setText(s.emergency)
        if s.sensor != "UNAVAILABLE":
            with QSignalBlocker(self.scan):
                self.scan.setChecked(s.sensor != "OFF")
        self.scan.setEnabled(s.compatible and heartbeat and s.sensor != "UNAVAILABLE"
                             and not any(p.record.kind == "SCAN" for p in self.delivery.pending.values()))
        self.obstacle.setText(s.obstacle + (" • OBSTACLE WARNING" if s.distance is not None and s.distance <= s.threshold else ""))
        rtt = f"{s.latest_rtt} ms / avg {sum(s.rtts)/len(s.rtts):.1f} / min {min(s.rtts)} / max {max(s.rtts)}" if s.rtts else "—"
        loss = f"{s.loss:.1f}% ({len(s.probes)} probes)" if s.loss is not None else "—"
        proximity = s.calibration.classify(s.rssi) if s.link else "UNKNOWN (no current signal)"
        if s.calibration.near <= s.calibration.far: proximity = "UNKNOWN (invalid calibration thresholds)"
        signal = f"{s.rssi} dBm" if s.link and s.rssi is not None else "—"
        self.info.setText(
            f"{'LINK ACTIVE' if s.link else 'AIRCRAFT SIGNAL LOST'}\nLast event: {s.last_message}"
            f"\nRSSI: {signal} • {proximity}\nLast successful RTT: {rtt}\nRTT probe loss: {loss}"
            f"\nLast seen: {s.last_seen}\nSource: radio • link metrics only; RTT is not distance"
        )
        self.status.setText(f"Sensor: {s.sensor} • confidence: {'direct, beam/range limited' if s.distance is not None else 'no valid measurement'} • Heartbeat: {'OK' if heartbeat else 'MISSING'} • radio group 47 / band 7")
        self.sonar_chart.values = s.distances
        self.rssi_chart.values = s.signals
        self.radar.phase += .05
        self.radar.update(); self.sonar_chart.update(); self.rssi_chart.update()

    def closeEvent(self, event):
        self.timer.stop()
        self.close_link(cancel=True)
        event.accept()


STYLE = """
QWidget { background: #0b121d; color: #d0e4e5; font-family: 'Segoe UI'; font-size: 12px; }
QGroupBox { border: 1px solid #233947; border-radius: 7px; margin-top: 14px; padding: 16px 10px 8px; }
QGroupBox::title { color: #6bcba9; subcontrol-origin: margin; left: 12px; }
QPushButton { background: #163b36; border: 1px solid #2b7261; border-radius: 4px; padding: 8px 14px; }
QPushButton:hover { background: #24634e; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #07101a; border: 1px solid #2c4350; padding: 6px; }
QLabel#title { font-size: 24px; font-weight: 700; padding: 8px; }
QLabel#metric { color: #54f5b1; font-size: 20px; }
QLabel#banner { background: #18382d; color: #9bf3b5; padding: 8px; }
QLabel#alert { color: #ff8b8b; font-size: 18px; font-weight: bold; }
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--smoke-test", action="store_true", help="Render a simulated emergency, then exit")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setStyleSheet(STYLE)
    window = Window(args.demo or args.smoke_test); window.show()
    if args.smoke_test:
        QTimer.singleShot(600, lambda: window.sim.event("MAYDAY"))
        QTimer.singleShot(1300, lambda: window.grab().save(str(Path(tempfile.gettempdir()) / "radar-mic-smoke.png")))
        QTimer.singleShot(1500, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
