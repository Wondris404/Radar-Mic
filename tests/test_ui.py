import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from radar_mic.app import Window


def test_ui_simulation_controls_and_mode_isolation():
    app = QApplication.instance() or QApplication([])
    w = Window(demo=True)
    w.timer.stop()
    w.tick()
    assert 'SIMULATION' in w.banner.text()
    w.sim.event('MAYDAY')
    w.last_sim = 0
    w.tick()
    assert 'MAYDAY' in w.alert.text()
    w.transmit('HOLD')
    assert w.delivery.pending
    w.last_sim = 0; w.tick()
    assert not w.delivery.pending
    w.mode.setCurrentIndex(0)
    assert w.sim is None and w.state.distance is None and not w.state.link
    w.render_state()
    assert 'HARDWARE' in w.banner.text() and 'SIMULATION' not in w.banner.text()
    assert w.sonar_chart.values is w.state.distances
    w.close()


def test_hardware_mayday_survives_serial_failure_reconnect_and_mode_change(monkeypatch):
    from PySide6.QtWidgets import QPushButton

    app = QApplication.instance() or QApplication([])
    w = Window()
    w.timer.stop()
    monkeypatch.setattr(w.serial, "poll", lambda: [
        "2|HELLO|0000|GROUND01|47", "2|EVENT|0001|AIR101|MAYDAY|-63",
    ])
    w.tick()
    alert = w.alert.text()
    assert "MAYDAY" in alert

    def disconnected():
        raise OSError("USB cable disconnected")

    monkeypatch.setattr(w.serial, "poll", disconnected)
    w.tick()
    assert w.alert.text() == alert
    monkeypatch.setattr(w.serial, "open", lambda port: None)
    w.connect_port()
    w.disconnect_port()
    w.render_state()
    assert w.alert.text() == alert

    w.mode.setCurrentIndex(1)
    w.render_state()
    assert not w.alert.text()
    w.sim.event("MAYDAY")
    w.last_sim = 0
    w.tick()
    assert "MAYDAY" in w.alert.text()
    w.mode.setCurrentIndex(0)
    w.render_state()
    assert w.alert.text() == alert
    next(b for b in w.findChildren(QPushButton) if b.text() == "Acknowledge MAYDAY").click()
    w.render_state()
    assert not w.alert.text()
    w.close()


def test_ground_restart_clears_pending_without_replaying(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = Window()
    w.timer.stop()
    clock = [100.0]
    monkeypatch.setattr("radar_mic.app.monotonic", lambda: clock[0])
    lines = [
        "2|HELLO|0000|GROUND01|47",
        "2|HEART|0000|GROUND01|0000000000000001|1000",
        "2|EVENT|0001|AIR101|MAYDAY|-63",
    ]
    monkeypatch.setattr(w.serial, "poll", lambda: lines)
    sent = []
    monkeypatch.setattr(w.serial, "send", sent.append)
    try:
        w.tick()
        original_alert = w.alert.text()
        w.transmit("AIR101 HOLD")
        w.command("SCAN", "0")
        assert len(w.delivery.pending) == 2
        lines[:] = ["2|HELLO|0000|GROUND01|47", "2|HEART|0000|GROUND01|0000000000000002|1"]
        clock[0] = 104.0
        w.tick()
        assert [record.kind for record in sent] == ["TEXT", "SCAN"]
        assert not w.delivery.pending
        assert w.state.ground_boot == "0000000000000002"
        assert w.alert.text() == original_alert
        assert "GROUND RESTARTED" in w.history.toPlainText()
    finally:
        w.close()


def test_wrong_group_cannot_supply_telemetry_before_handshake(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = Window()
    w.timer.stop()
    lines = [
        "2|HELLO|0000|GROUND01|99",
        "2|HEART|0000|GROUND01|0000000000000001|1000",
        "2|SONAR|0000|VALID|42",
        "2|EVENT|0001|AIR101|MAYDAY|-63",
    ]
    monkeypatch.setattr(w.serial, "poll", lambda: lines)
    try:
        w.tick()
        assert not w.state.compatible and w.state.distance is None and not w.alert.text()
        lines[0] = "2|HELLO|0000|GROUND01|47"
        w.tick()
        assert w.state.compatible and w.state.distance == 42 and "MAYDAY" in w.alert.text()
    finally:
        w.close()


def test_automatic_reconnect_keeps_port_selected_at_connect(monkeypatch):
    app = QApplication.instance() or QApplication([])
    port_list = [("COM7", "COM7 — other"), ("COM9", "COM9 — micro:bit")]
    monkeypatch.setattr("radar_mic.app.ports", lambda: port_list)
    w = Window()
    w.timer.stop()
    opened = []
    monkeypatch.setattr(w.serial, "open", opened.append)
    try:
        w.port_box.setCurrentIndex(1)
        w.connect_port()
        port_list.reverse()
        w.refresh_ports()
        assert w.selected_port() == "COM9"
        w.port_box.setCurrentIndex(1)  # Other port is now at index 1.
        w.tick()
        assert w.selected_port() == "COM7"
        assert opened == ["COM9", "COM9"]
    finally:
        w.close()
