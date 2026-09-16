import unittest

from editor_core.treeview import EDITABLE_ROW_TAG, READONLY_ROW_TAG, mixed_editability_tags


class TreeviewEditabilityTagTests(unittest.TestCase):
    def test_mixed_rows_mark_only_read_only_rows(self):
        self.assertEqual(
            ((READONLY_ROW_TAG,), (EDITABLE_ROW_TAG,), (READONLY_ROW_TAG,)),
            mixed_editability_tags((False, True, False)),
        )

    def test_fully_read_only_list_marks_every_row(self):
        self.assertEqual(
            ((READONLY_ROW_TAG,), (READONLY_ROW_TAG,)),
            mixed_editability_tags((False, False)),
        )

    def test_fully_editable_list_marks_every_row_editable(self):
        self.assertEqual(
            ((EDITABLE_ROW_TAG,), (EDITABLE_ROW_TAG,)),
            mixed_editability_tags((True, True)),
        )


if __name__ == '__main__':
    unittest.main()
