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
