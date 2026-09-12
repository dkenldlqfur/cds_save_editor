import struct
import unittest
from editor_core.save_records import RecordTableLayout
from editor_core.sponsor_records import intimacy, power_grade, write_intimacy

class SponsorRecordTests(unittest.TestCase):

    def test_power_grade_uses_game_boundaries(self):
        expected = {0: 'E', 1: 'E', 20: 'E', 21: 'D', 40: 'D', 41: 'C', 60: 'C', 61: 'B', 80: 'B', 81: 'A', 99: 'A'}
        for power, grade in expected.items():
            with self.subTest(power=power):
                self.assertEqual(grade, power_grade(power))

    def test_intimacy_reads_and_writes_first_record_dword(self):
        layout = RecordTableLayout(8, 28, 2)
        buffer = bytearray(layout.end_offset)
        struct.pack_into('<I', buffer, layout.offset(1), 50)
        self.assertEqual(50, intimacy(buffer, layout, 1))
        write_intimacy(buffer, layout, 1, 73)
        self.assertEqual(73, intimacy(buffer, layout, 1))

    def test_intimacy_is_clamped_to_game_range(self):
        layout = RecordTableLayout(0, 28, 1)
        buffer = bytearray(layout.end_offset)
        write_intimacy(buffer, layout, 0, 999)
        self.assertEqual(100, intimacy(buffer, layout, 0))
        write_intimacy(buffer, layout, 0, -1)
        self.assertEqual(0, intimacy(buffer, layout, 0))
if __name__ == '__main__':
    unittest.main()
