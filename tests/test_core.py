import pytest

from radar_mic.protocol import CLOCK_MASK, LineDecoder, Record, parse
from radar_mic.simulation import Simulation
from radar_mic.state import State
from radar_mic.transport import Delivery, SerialTransport


ID = "1234567890abcdef1234567890abcdef"
BOOT = Simulation.BOOT_ID
TEXT_FIELDS = (BOOT, "10000", "HOLD")


@pytest.mark.parametrize("line", [
    f"1|TEXT|{ID}|{BOOT}|10000|ok",
    f"2|TEXT|abcd|{BOOT}|10000|ok",
    f"2|TEXT|{ID}|{BOOT}|10000|",
    f"2|TEXT|{ID}|{BOOT}|10000|a|b",
    f"2|TEXT|{ID}|{BOOT}|10000|é",
    f"2|TEXT|{ID}|{BOOT}|10000|" + "a" * 81,
    f"2|TEXT|{ID}|{BOOT}|{CLOCK_MASK + 1}|HOLD",
    f"2|CANCEL|{ID}|INVALID",
    f"2|SCAN|{ID}|2",
    f"2|THRESH|{ID}|401",
    f"2|ACK|{ID}|DELIVERED",
    "2|SONAR|0000|VALID|0",
    "2|SONAR|0000|VALID|3",
    "2|SONAR|0000|VALID|401",
    "2|SONAR|0000|OFF|42",
    "2|RTT|0000|OK|-1|-60",
    "2|EVENT|0000|BOGUS|MAYDAY|-60",
    "2|LINK|0000|AIR101|UP|-200",
    "2|HELLO|0000|GROUND01|48",
])
def test_reject(line):
    with pytest.raises(ValueError):
        parse(line)


def test_round_trip_and_resynchronization():
    r = Record("TEXT", ID, (*TEXT_FIELDS[:2], "HOLD "))
    wire = r.encode()
    assert parse(wire.decode().removesuffix("\n")) == r
    d = LineDecoder()
    assert d.feed(b"x" * 400) == []
    assert d.feed(b"\n" + wire[:5]) == []
    assert d.feed(wire[5:]) == [wire[:-1].decode()]
    assert d.feed(wire[:-1] + b"\r\n") == [wire[:-1].decode()]
    assert d.feed(b"a" * 240 + b"\r\n") == ["a" * 240]


def test_delivery_fixed_retry_deadline_and_late_reception():
    sent, logs = [], []
    d = Delivery(sent.append, logs.append)
    ident = d.command("TEXT", *TEXT_FIELDS, now=0)
    d.tick(4)
    d.tick(8)
    assert len(sent) == 3 and all(record == sent[0] for record in sent)
    d.receive(Record("ACK", ident, ("RECEIVED",)))
    assert "aircraft accepted the text" in logs[-1]
    assert not d.pending
    ident = d.command("TEXT", *TEXT_FIELDS, now=0)
    # Even if the UI loop stalled, never send another retry after the deadline.
    before = len(sent)
    d.tick(14)
    assert len(sent) == before
    assert not d.pending and "TRANSMISSION TIMEOUT" in logs[-1]
    d.receive(Record("ACK", ident, ("RECEIVED",)))
    assert logs[-1].startswith("LATE ACK") and "aircraft accepted" in logs[-1]


def test_cancellation_replaces_text_retries_and_reports_confirmation():
    sent, logs = [], []
    d = Delivery(sent.append, logs.append)
    ident = d.command("TEXT", *TEXT_FIELDS, now=0)
    d.cancel_text(now=1)
    assert "CANCEL REQUESTED" in logs[-1]
    assert sent[-1] == Record("CANCEL", ident, (BOOT,))
    d.tick(5)
    assert sent[1:] == [sent[1], sent[1]]
    d.receive(Record("ACK", ident, ("CANCELLED",)))
    assert "prior reception unknown" in logs[-1]
    d.tick(20)
    assert not d.pending and len(sent) == 3


def test_failed_cancellation_write_never_retries_original_text():
    sent = []
    d = Delivery(sent.append, lambda _: None)
    d.command("TEXT", *TEXT_FIELDS, now=0)
    d.command("TEXT", *TEXT_FIELDS, now=0)

    def unavailable(record):
        raise OSError("USB unavailable")

    d.send = unavailable
    with pytest.raises(OSError):
        d.cancel_text(now=1)
    d.send = sent.append
    d.tick(5)
    assert [r.kind for r in sent] == ["TEXT", "TEXT", "CANCEL", "CANCEL"]


def test_first_commands_from_new_desktop_instances_have_distinct_ids():
    sent = []
    first = Delivery(sent.append, lambda _: None)
    restarted = Delivery(sent.append, lambda _: None)
    first.command("TEXT", *TEXT_FIELDS, now=0)
    restarted.command("TEXT", *TEXT_FIELDS, now=0)
    assert sent[0].id != sent[1].id
    assert all(len(r.id) == 32 and parse(r.encode().decode().removesuffix("\n")) == r for r in sent)


def test_stale_heartbeat_is_independent_of_hello_and_other_traffic():
    s = State()
    s.apply(parse("2|HELLO|0000|GROUND01|47"), 0)
    s.apply(parse(f"2|HEART|0000|GROUND01|{BOOT}|{CLOCK_MASK - 2}"), 0)
    assert s.text_lease() == (BOOT, "9997")
    s.apply(parse("2|HELLO|0000|GROUND01|47"), 6)
    s.apply(parse("2|SONAR|0000|VALID|42"), 6)
    s.apply(parse("2|LINK|0000|AIR101|UP|-63"), 6)
    s.tick(6)
    assert s.compatible and s.distance == 42
    assert not s.heartbeat_alive(6) and not s.link
    s.apply(parse(f"2|HEART|0000|GROUND01|{BOOT}|6001"), 6.5)
    s.tick(6.5)
    assert s.heartbeat_alive(6.5)


def test_independent_sensor_failures_and_emergency():
    s = State()
    s.apply(parse("2|HELLO|0000|GROUND01|47"), 0)
    s.apply(parse(f"2|HEART|0000|GROUND01|{BOOT}|0"), 0)
    s.apply(parse("2|SONAR|0000|VALID|40"), 0)
    s.apply(parse("2|EVENT|abcd|AIR101|MAYDAY|-62"), 1)
    assert "MAYDAY" in s.emergency and s.distance == 40
    s.tick(3)
    assert s.distance is None and s.sensor == "UNAVAILABLE" and s.link
    s.apply(parse("2|SONAR|0000|VALID|30"), 9)
    s.tick(9)
    assert s.distance == 30 and not s.link
    s.apply(parse("2|SONAR|0000|NO_TARGET|0"), 10)
    assert s.obstacle == "NO VALID ULTRASONIC DISTANCE" and s.distance is None
    assert "UNKNOWN" in s.calibration.classify(-60)


@pytest.mark.parametrize("fail_after_send", [False, True])
def test_simulation_radio_failure_cannot_confirm_delivery(fail_after_send):
    sim = Simulation()
    sim.failed = not fail_after_send
    sim.send(Record("TEXT", ID, TEXT_FIELDS))
    sim.failed = True
    records = list(map(parse, sim.poll()))
    assert [r for r in records if r.id == ID] == [Record("ERROR", ID, ("RADIO_TIMEOUT",))]
    assert any(r.kind == "LINK" and r.fields[1] == "LOST" for r in records)


def test_simulation_and_reset():
    sim, s = Simulation(), State()
    sim.event("LANDING")
    sim.send(Record("TEXT", ID, TEXT_FIELDS))
    records = [parse(x) for x in sim.poll()]
    assert Record("ACK", ID, ("RECEIVED",)) in records
    for r in records:
        s.apply(r, 0)
    assert s.last_message == "LANDING" and s.link and s.compatible
    sim.failed = True
    for r in map(parse, sim.poll()):
        s.apply(r, 1)
    assert not s.link and s.distance is not None
    sim.sensor_failed = True
    for r in map(parse, sim.poll()):
        s.apply(r, 4)
    s.tick(4)
    assert s.distance is None
    s.reset()
    assert s.rssi is None and not s.rtts and not s.emergency


def test_real_serial_loopback():
    import serial

    t = SerialTransport()
    t.port = serial.serial_for_url("loop://", timeout=0, write_timeout=1)
    record = Record("TEXT", ID, TEXT_FIELDS)
    t.send(record)
    assert list(map(parse, t.poll())) == [record]
    t.close()
    with pytest.raises(OSError):
        t.send(record)


def test_local_control_is_not_replayed_without_a_boot_id():
    sent, logs = [], []
    d = Delivery(sent.append, logs.append)
    for kind, value in (("SCAN", "0"), ("THRESH", "100"), ("PING", "AIR101")):
        d.command(kind, value, now=0)
    d.tick(4)
    d.tick(8)
    assert [item.kind for item in sent] == ["SCAN", "THRESH", "PING"]
    d.tick(12)
    assert not d.pending
    assert all("TIMEOUT" in line for line in logs)


def test_unavailable_rssi_is_not_interpreted_as_far():
    state = State()
    state.calibration.enabled = True
    state.apply(parse("2|LINK|0000|AIR101|UP|-128"), 1)
    assert state.link
    assert state.rssi is None
    assert state.signals[-1] is None
    assert state.calibration.classify(state.rssi) == "UNKNOWN (RSSI unavailable)"
    state.apply(parse("2|LINK|0000|AIR101|UP|-63"), 2)
    assert state.rssi == -63
