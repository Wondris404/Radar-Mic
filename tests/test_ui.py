import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from radar_mic.app import Window
from radar_mic.protocol import parse


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
    monkeypatch.setattr(w.serial, "poll", lambda: ["2|EVENT|0001|AIR101|MAYDAY|-63"])
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
