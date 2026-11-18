"""A–H using two compiled PXT simulator boards, a Linux PTY and the Qt app."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from radar_mic.app import Window

ROOT = Path(__file__).resolve().parents[1]
PXT_READY = (
    sys.platform.startswith("linux")
    and shutil.which("node")
    and all((ROOT / f"firmware/{role}/built/debug/binary.js").is_file() for role in ("ground", "aircraft"))
    and (ROOT / "tools/node_modules/pxt-microbit/built/sim.js").is_file()
)
pytestmark = pytest.mark.skipif(
    not PXT_READY, reason="requires a Linux PTY and node scripts/build-firmware.cjs --sim",
)


class Bench:
    def __init__(self, window, port):
        self.window = window
        self.port = port
        self.master = self.slave = None
        self.air_display = []
        self.radio = []
        self.pins = []
        self.worker = subprocess.Popen(
            ["node", "tests/pxt-bench.cjs"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )

    def plug(self):
        self.master, self.slave = os.openpty()
        os.set_blocking(self.master, False)
        self.port.unlink(missing_ok=True)
        self.port.symlink_to(os.ttyname(self.slave))

    def unplug(self):
        for fd in (self.master, self.slave):
            if fd is not None:
                os.close(fd)
        self.master = self.slave = None
        self.port.unlink(missing_ok=True)

    def step(self, **request):
        if self.master is not None:
            try:
                data = os.read(self.master, 4096)
            except BlockingIOError:
                data = b""
            request["usb"] = data.decode("ascii")
        self.worker.stdin.write(json.dumps(request) + "\n")
        self.worker.stdin.flush()
        response = self.worker.stdout.readline()
        assert response, f"PXT simulator exited early ({self.worker.poll()})"
        result = json.loads(response)
        self.air_display.extend(item["message"] for item in result["display"] if item["role"] == "aircraft")
        self.radio.extend(result["radio"])
        self.pins.extend(result["observedPins"])
        if self.master is not None and result["usb"]:
            data = result["usb"].encode("ascii")
            # Split across reads to cover real incremental framing.
            for start in range(0, len(data), 17):
                chunk = data[start:start + 17]
                assert os.write(self.master, chunk) == len(chunk)
                self.window.tick()
        self.window.tick()
        return result

    def until(self, condition, *, wait=5):
        deadline = monotonic() + wait
        while not condition():
            assert monotonic() < deadline, self.history
            self.step()

    @property
    def history(self):
        return self.window.history.toPlainText()

    def send(self, text):
        self.window.message.setText(text)
        self.window.send_text()
        return next(reversed(self.window.delivery.pending))

    def click_air(self, button):
        return self.step(button={"role": "aircraft", "name": button})

    def close(self):
        self.worker.stdin.close()
        try:
            self.worker.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.worker.kill()
            self.worker.wait(timeout=2)
        self.worker.stdout.close()
        self.unplug()


def test_a_through_h_with_compiled_firmware_virtual_usb_and_qt(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    port = tmp_path / "ground-usb"
    monkeypatch.setattr("radar_mic.app.ports", lambda: [(str(port), "Ground micro:bit — virtual COM")])
    window = Window()
    window.timer.stop()  # Pump the same GUI polling handler at explicit I/O boundaries.
    bench = Bench(window, port)
    try:
        # A — simulated port discovery, real pyserial open and both-sided handshake.
        bench.plug()
        assert window.port_box.currentText() == "Ground micro:bit — virtual COM"
        window.connect_port()
        assert window.serial.port.is_open and window.serial.port.baudrate == 115200
        os.write(bench.master, b"1|HELLO|0000|GROUND01|47\n" + b"x" * 260 + b"\n")
        window.tick()
        assert not window.state.compatible
        response = bench.step()
        assert response["config"] == {"ground": [47, 7, 6], "aircraft": [47, 7, 6]}
        bench.until(lambda: window.state.link and "protocol 2" in window.banner.text())
        assert "Heartbeat: OK" in window.status.text()
        assert bench.pins and set(bench.pins) == {102}

        # B — actual Qt send slot, two firmware state machines, LED scroll and ACK.
        hold = bench.send("AIR101 HOLD")
        bench.until(lambda: f"ACK RECEIVED {hold}" in bench.history)
        bench.until(lambda: "AIR101 HOLD" in bench.air_display, wait=8)
        long_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 2 + "12345678"
        long_id = bench.send(long_text)
        bench.until(lambda: f"ACK RECEIVED {long_id}" in bench.history)

        # C and D — the actual registered MakeCode click handlers, telemetry and UI.
        bench.click_air("A")
        bench.until(lambda: "Last event: POSITION" in window.info.text())
        assert "RX AIR101 POSITION • RSSI -63 dBm" in bench.history
        bench.click_air("B")
        bench.until(lambda: "Last event: LANDING" in window.info.text())

        # E — interrupt unsettled routine traffic and latch the alert.
        bench.step(radioOnline=False, button={"role": "aircraft", "name": "B"}, ms=120)
        bench.click_air("A")
        start = len(bench.radio)
        bench.step(radioOnline=True, button={"role": "aircraft", "name": "AB"})
        bench.until(lambda: "MAYDAY" in window.alert.text())
        sent = [item["packet"][11:] for item in bench.radio[start:]
                if item["role"] == "aircraft" and item["packet"].startswith("D")]
        assert sent[0] == "E|MAYDAY"
        alert = window.alert.text()

        # F — run the pinned Sonar:bit extension with simulated echo pulse widths.
        bench.until(lambda: window.obstacle.text().startswith("42 cm"))
        for invalid_pulse in (58 * 3, 0, 58 * 401):
            bench.step(pulse=invalid_pulse)
            bench.until(lambda: window.obstacle.text() == "NO VALID ULTRASONIC DISTANCE")
            bench.step(pulse=58 * 42)
            bench.until(lambda: window.state.distance == 42)
        bench.step(button={"role": "ground", "name": "A"})
        bench.until(lambda: window.state.sensor == "OFF")
        assert not window.scan.isChecked()
        bench.step(button={"role": "ground", "name": "A"})
        bench.until(lambda: window.state.distance == 42)
        assert window.scan.isChecked()

        # G — drop radio packets while USB and sonar continue.
        bench.step(radioOnline=False)
        loss = bench.send("AIR101 RADIO OFF")
        bench.until(lambda: f"ERROR RADIO_TIMEOUT {loss}" in bench.history)
        assert f"ACK RECEIVED {loss}" not in bench.history
        bench.until(lambda: "AIRCRAFT SIGNAL LOST" in window.info.text(), wait=9)
        assert window.state.distance == 42 and window.state.heartbeat_alive(monotonic())
        cancelled = bench.send("AIR101 CANCEL TEST")
        bench.step()
        window.cancel_pending_text()
        bench.until(lambda: f"ACK CANCELLED {cancelled}" in bench.history)
        assert f"ACK RECEIVED {cancelled}" not in bench.history

        # H — unplug the actual PTY master, retain MAYDAY, reconnect with a new boot.
        stale = bench.send("AIR101 STALE")
        stale_radio_id = base64.urlsafe_b64encode(bytes.fromhex(stale[:12])).decode()
        bench.step()
        bench.unplug()
        window.tick()
        assert window.serial.port is None and not window.delivery.pending
        assert window.alert.text() == alert
        start = len(bench.radio)
        bench.step(restartGround=True, radioOnline=True)
        bench.plug()
        bench.until(lambda: window.state.link and "protocol 2" in window.banner.text(), wait=8)
        again = bench.send("AIR101 BACK")
        bench.until(lambda: f"ACK RECEIVED {again}" in bench.history)
        assert not any(item["packet"].startswith("D" + stale_radio_id) for item in bench.radio[start:])
        assert window.alert.text() == alert
        next(button for button in window.findChildren(QPushButton)
             if button.text() == "Acknowledge MAYDAY").click()
        window.render_state()
        assert not window.alert.text()
        # Actual MakeCode scroll routine starts for the complete 80-byte text.
        bench.until(lambda: long_text in bench.air_display, wait=12)
    finally:
        window.close()
        bench.close()
