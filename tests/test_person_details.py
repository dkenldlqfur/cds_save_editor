import runpy
import struct
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from editor_core.save_records import read_character_stat_values


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / 'CDS_SaveEditor.pyw'),
    run_name='test_person_details',
)
App = MODULE['CDS3SaveEditorApp']
CHARACTER_LAYOUT = MODULE['CHARACTER_LAYOUT']


class PersonDetailBufferTests(unittest.TestCase):
    def make_app(self, kind):
        app = App.__new__(App)
        app._person_active_type = kind
        app._crew_profiles = {'officer': {}, 'navigator': {},
                              'surveyor': {}, 'interpreter': {}}
        app.file_buffer = bytearray(CHARACTER_LAYOUT.end_offset)
        app.file_buffer[CHARACTER_LAYOUT.offset(0)] = 42
        app.person_display_buffer = bytes(CHARACTER_LAYOUT.end_offset)
        app._character_age_for_current_game_year = lambda *_args: 30
        app._character_hire_state = lambda *_args, **_kwargs: 3
        app._active_role_character_ids = lambda *_args: frozenset()
        app._person_current_city_state = lambda *_args: ('-', False)
        app._person_detail_trees = [MagicMock() for _ in range(5)]
        app.cbo_person_current_city = MagicMock()
        app._schedule_treeview_autofit = lambda *_args: None
        return app

    def test_role_details_use_unsaved_ability_edits(self):
        for role in ('officer', 'navigator', 'surveyor', 'interpreter'):
            with self.subTest(role=role):
                app = self.make_app(role)
                app._populate_person_details(0)
                app.file_buffer[CHARACTER_LAYOUT.offset(0)] = 91
                app._person_detail_trees[1].reset_mock()
                app._populate_person_details(0)
                first_stat = app._person_detail_trees[1].insert.call_args_list[0]
                self.assertEqual(91, first_stat.kwargs['values'][2])

    def test_unhireable_details_keep_snapshot(self):
        app = self.make_app('unhireable')
        app._populate_person_details(0)
        first_stat = app._person_detail_trees[1].insert.call_args_list[0]
        self.assertEqual(0, first_stat.kwargs['values'][2])

    def test_vitality_and_hire_coefficient_have_distinct_offsets_and_limits(self):
        app = self.make_app('officer')
        offset = CHARACTER_LAYOUT.offset(0)
        struct.pack_into('<I', app.file_buffer, offset + 0x06, 128)
        app.file_buffer[offset + 0x66] = 177

        app._populate_person_details(0)

        rows = [call.kwargs['values'] for call in app._person_detail_trees[1].insert.call_args_list]
        self.assertEqual(('생명력', 128, 2000), rows[6][1:])
        self.assertEqual(('고용비 계수', 177, 255), rows[7][1:])
        self.assertEqual((128, 177), read_character_stat_values(app.file_buffer, offset, 0x06)[6:])

    def test_edit_vitality_and_hire_coefficient_writes_separate_fields(self):
        app = self.make_app('officer')
        offset = CHARACTER_LAYOUT.offset(0)
        struct.pack_into('<I', app.file_buffer, offset + 0x06, 128)
        app.file_buffer[offset + 0x66] = 177
        app.tree_person_list = MagicMock()
        app.tree_person_list.selection.return_value = ('0',)
        app._set_person_assignment_buttons_visible = lambda: None
        tree = app._person_detail_trees[1]
        tree.selection.return_value = ('selected-row',)

        tree.item.return_value = (6, '생명력', 128, 2000)
        app.ask_bounded_integer = MagicMock(return_value=500)
        app._edit_person_detail_value(1)
        self.assertEqual((0, 2000), app.ask_bounded_integer.call_args.args[-2:])
        self.assertEqual(500, struct.unpack_from('<I', app.file_buffer, offset + 0x06)[0])
        self.assertEqual(177, app.file_buffer[offset + 0x66])

        tree.item.return_value = (7, '고용비 계수', 177, 255)
        app.ask_bounded_integer = MagicMock(return_value=222)
        app._edit_person_detail_value(1)
        self.assertEqual((0, 255), app.ask_bounded_integer.call_args.args[-2:])
        self.assertEqual(500, struct.unpack_from('<I', app.file_buffer, offset + 0x06)[0])
        self.assertEqual(222, app.file_buffer[offset + 0x66])


if __name__ == '__main__':
    unittest.main()
