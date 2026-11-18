import pytest
from radar_mic.protocol import parse, Record, LineDecoder
from radar_mic.transport import Delivery, SerialTransport
from radar_mic.state import State
from radar_mic.simulation import Simulation


@pytest.mark.parametrize('line', ['2|TEXT|abcd|ok', '1|TEXT|xyz|ok', '1|TEXT|abcd|',
 '1|TEXT|abcd|a|b', '1|SCAN|abcd|2', '1|THRESH|abcd|401', '1|SONAR|0000|VALID|0',
 '1|RTT|0000|OK|-1|-60', '1|EVENT|0000|BOGUS|MAYDAY|-60', '1|LINK|0000|AIR101|UP|-200',
 '1|TEXT|0000|é', '1|TEXT|0000|'+'a'*81, '1|HELLO|0000|GROUND01|48'])
def test_reject(line):
    with pytest.raises(ValueError): parse(line)


def test_round_trip_and_resynchronization():
    r = Record('TEXT', 'abcd', ('HOLD',))
    assert parse(r.encode().decode().strip()) == r
    d = LineDecoder()
    assert d.feed(b'x'*400) == []
    assert d.feed(b'\n'+r.encode()[:5]) == []
    assert d.feed(r.encode()[5:]) == ['1|TEXT|abcd|HOLD']
    assert d.feed(b'1|TEXT|abcd|HOLD\r\n') == ['1|TEXT|abcd|HOLD']


def test_delivery_retry_ack_and_timeout():
    sent, logs = [], []
    d = Delivery(sent.append, logs.append)
    ident = d.command('TEXT', 'LAND', now=0)
    d.tick(4); d.tick(8)
    assert len(sent) == 3 and len({r.id for r in sent}) == 1
    d.receive(Record('ACK', ident, ('DELIVERED',)))
    d.tick(12)
    assert not d.pending and len(sent) == 3
    d.command('TEXT', 'HOLD', now=0)
    d.tick(4); d.tick(8); d.tick(12)
    assert not d.pending and 'TIMEOUT' in logs[-1]


def test_independent_sensor_failures_and_emergency():
    s = State()
    s.apply(parse('1|HELLO|0000|GROUND01|47'), 0)
    s.apply(parse('1|SONAR|0000|VALID|40'), 0)
    s.apply(parse('1|EVENT|abcd|AIR101|MAYDAY|-62'), 1)
    assert 'MAYDAY' in s.emergency and s.distance == 40
    s.tick(3)
    assert s.distance is None and s.sensor == 'UNAVAILABLE' and s.link
    s.apply(parse('1|SONAR|0000|VALID|30'), 9)
    s.tick(9)
    assert s.distance == 30 and not s.link
    s.apply(parse('1|SONAR|0000|NO_TARGET|0'), 10)
    assert s.obstacle == 'NO ULTRASONIC TARGET' and s.distance is None
    assert 'UNKNOWN' in s.calibration.classify(-60)


def test_simulation_and_reset():
    sim, s = Simulation(), State()
    sim.event('LANDING')
    sim.send(Record('TEXT', '1234', ('TAKEOFF',)))
    records = [parse(x) for x in sim.poll()]
    assert any(r.kind == 'ACK' and r.id == '1234' for r in records)
    for r in records: s.apply(r, 0)
    assert s.last_message == 'LANDING' and s.link and s.compatible
    sim.failed = True
    for r in map(parse, sim.poll()): s.apply(r, 1)
    assert not s.link and s.distance is not None
    sim.sensor_failed = True
    for r in map(parse, sim.poll()): s.apply(r, 4)
    s.tick(4)
    assert s.distance is None
    s.reset()
    assert s.rssi is None and not s.rtts and not s.emergency


def test_real_serial_loopback():
    import serial
    t = SerialTransport()
    t.port = serial.serial_for_url('loop://', timeout=0, write_timeout=1)
    t.send(Record('TEXT', '1234', ('HOLD',)))
    assert t.poll() == ['1|TEXT|1234|HOLD']
    t.close()
    with pytest.raises(OSError): t.send(Record('TEXT', '1234', ('HOLD',)))
