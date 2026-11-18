"""Check that both packaged Universal HEX images carry a valid V2 section."""
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("role", ["ground", "aircraft"])
def test_universal_hex_has_v2_data_and_valid_checksums(role):
    image = ROOT / "dist/firmware" / f"radar-mic-{role}.hex"
    if not image.is_file():
        pytest.skip("requires a native firmware build")
    board_id = None
    v2_bytes = 0
    eof = False
    for line in image.read_text(encoding="ascii").splitlines():
        if not line:
            # Preserve MakeCode's original padding around embedded source.
            continue
        assert line.startswith(":")
        contents = bytes.fromhex(line[1:])
        assert len(contents) == contents[0] + 5 and sum(contents) % 256 == 0
        kind = contents[3]
        if kind == 0x0A:  # Universal HEX block start
            assert contents[6:8] == bytes((0xC0, 0xDE))
            board_id = int.from_bytes(contents[4:6], "big")
        elif kind == 0x0B:
            board_id = None
        elif kind == 0x0D and board_id == 0x9903:  # V2 custom data
            v2_bytes += contents[0]
        elif kind == 0x01:
            eof = True
    assert v2_bytes > 0 and eof
