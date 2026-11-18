"""Exercise the actual pyserial Windows completion logic without a COM device."""
import sys

import pytest
import serial

from radar_mic.protocol import Record
from radar_mic.transport import SerialTransport


@pytest.mark.skipif(sys.platform != "win32", reason="requires pyserial's Win32 backend")
def test_com_write_waits_for_completion_and_reports_short_write(monkeypatch):
    from serial import serialwin32 as backend

    record = Record("SCAN", "a" * 32, ("1",))
    data = record.encode()
    calls = []
    completed = len(data)

    def submit(handle, buffer, length, count, overlapped):
        calls.append("submit")
        assert length == len(data)
        return False  # Driver accepted the request asynchronously.

    def finish(handle, overlapped, count, wait):
        calls.append("finish")
        assert wait
        count._obj.value = completed
        return True

    monkeypatch.setattr(backend.win32, "WriteFile", submit)
    monkeypatch.setattr(backend.win32, "GetLastError", lambda: backend.win32.ERROR_IO_PENDING)
    monkeypatch.setattr(backend.win32, "GetOverlappedResult", finish)

    def make_port(name=None, baudrate=115200, *, timeout=0, write_timeout):
        port = backend.Serial(baudrate=baudrate, timeout=timeout, write_timeout=write_timeout)
        port.is_open = True
        port._port_handle = 1
        port._overlapped_write = backend.win32.OVERLAPPED()
        port.close = lambda: setattr(port, "is_open", False)
        return port

    legacy = make_port(write_timeout=0)
    assert legacy.write(data) == len(data)
    assert calls == ["submit"]  # Previous configuration reports success before completion.
    legacy.close()

    monkeypatch.setattr(serial, "Serial", make_port)
    transport = SerialTransport()
    transport.open("COM9")
    try:
        calls.clear()
        transport.send(record)
        assert calls == ["submit", "finish"]
        completed = len(data) - 1
        with pytest.raises(serial.SerialTimeoutException):
            transport.send(record)
    finally:
        transport.close()
