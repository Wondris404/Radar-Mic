"""Cross-runtime regression: real ground serializer bytes into the desktop decoder."""
from pathlib import Path
import shutil
import subprocess
import unittest

from radar_mic.protocol import LineDecoder, parse

ROOT = Path(__file__).resolve().parents[1]
HAS_HOST = (
    shutil.which("node")
    and (ROOT / "tools/node_modules/pxt-microbit/built/target.json").is_file()
)


@unittest.skipUnless(HAS_HOST, "requires npm ci --prefix tools --ignore-scripts")
class FirmwareSerialTests(unittest.TestCase):
    def lines(self, *args):
        data = subprocess.check_output(["node", "tests/firmware-serial.cjs", *args], cwd=ROOT)
        decoder = LineDecoder()
        return [
            line
            for offset in range(0, len(data), 7)
            for line in decoder.feed(data[offset:offset + 7])
        ]

    def test_makecode_padding_reproduces_handshake_and_sensor_failure(self):
        lines = self.lines("--legacy-padding")
        for name in ("HELLO", "SONAR", "HEART", "LINK", "RTT"):
            line = next(line for line in lines if line.split("|")[1] == name)
            self.assertTrue(line.endswith(" "))
            with self.assertRaises(ValueError, msg=line):
                parse(line)

    def test_ground_records_parse_without_trimming_fields(self):
        lines = self.lines()
        self.assertTrue(all(line == line.rstrip(" ") for line in lines))
        records = {record.kind: record for record in map(parse, lines)}
        self.assertEqual(set(records), {"HELLO", "SONAR", "LINK", "EVENT", "HEART", "RTT"})
        self.assertEqual(records["HELLO"].fields, ("GROUND01", "47"))
        self.assertEqual(records["SONAR"].fields, ("VALID", "42"))
        self.assertEqual(records["LINK"].fields, ("AIR101", "UP", "-61"))
        self.assertEqual(records["EVENT"].fields, ("AIR101", "MAYDAY", "-61"))
        self.assertEqual(records["HEART"].fields[0], "GROUND01")
        self.assertEqual(records["RTT"].fields, ("OK", "0", "-61"))
