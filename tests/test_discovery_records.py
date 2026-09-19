import unittest

from editor_core.discovery_records import set_hint_acquired


class HintStateTests(unittest.TestCase):
    def test_completed_hint_can_be_set_to_unacquired(self):
        self.assertEqual(0x08, set_hint_acquired(0x0B, False))
        self.assertEqual(0x08, set_hint_acquired(0x0F, False))

    def test_completed_hint_can_be_set_to_acquired(self):
        self.assertEqual(0x0D, set_hint_acquired(0x0B, True))
        self.assertEqual(0x0D, set_hint_acquired(0x0F, True))

    def test_unrelated_bits_are_preserved(self):
        self.assertEqual(0x8D, set_hint_acquired(0x8F, True))
        self.assertEqual(0x88, set_hint_acquired(0x8F, False))


if __name__ == '__main__':
    unittest.main()
