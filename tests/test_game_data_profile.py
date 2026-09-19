import unittest

from editor_core.game_data_profile import GAME_RESOURCE_FILES, GameDataProfile


class GameDataProfileTests(unittest.TestCase):
    def test_builtin_profile_contains_all_static_resources(self):
        profile = GameDataProfile.from_builtin()

        self.assertEqual(set(GAME_RESOURCE_FILES), set(profile.resources))
        self.assertEqual(205, len(profile.characters['records']))
        self.assertEqual(226, len(profile.cities['records']))
        self.assertEqual(81, len(profile.sponsors['records']))
        self.assertEqual(70, len(profile.trade_goods['records']))
        self.assertEqual(205, len(profile.character_by_id))
        self.assertEqual(127, len(profile.barmaid_by_id))
        self.assertEqual(226, len(profile.city_name_by_id))
        self.assertEqual(70, len(profile.trade_good_name_by_id))
        self.assertEqual(99_999_999, profile.limits['player']['cash'])
        self.assertEqual(99_999_999, profile.limits['player']['fame'])
        self.assertEqual(4_294_967_295, profile.limits['player']['contract'])
        self.assertEqual(2_000, profile.limits['player']['vitality'])
        self.assertEqual(65_535, profile.limits['person']['reputation'])

    def test_executable_record_overlay_preserves_builtin_fallback_fields(self):
        profile = GameDataProfile.from_builtin()
        original = profile.characters['records'][0]
        executable_profile = profile.fork('executable', r'C:\Game\CDS_95.EXE')

        executable_profile.overlay_records(
            'characters',
            [{'id': original['id'], 'name': '수정된 이름'}],
            source='CDS_95.EXE:character_master',
        )

        updated = executable_profile.characters['records'][0]
        self.assertEqual('수정된 이름', updated['name'])
        self.assertEqual(original['face_code'], updated['face_code'])
        self.assertNotEqual('수정된 이름', profile.characters['records'][0]['name'])
        self.assertEqual(
            'CDS_95.EXE:character_master',
            executable_profile.provenance['characters.records[0].name'],
        )

    def test_mapping_overlay_changes_only_verified_fields(self):
        profile = GameDataProfile.from_builtin().fork('executable')
        original_blood_names = list(profile.master_data['blood_names'])

        profile.overlay_mapping(
            'master_data',
            {'personality_names': ['A', 'B']},
            source='CDS_95.EXE:personality_names',
        )

        self.assertEqual(['A', 'B'], profile.master_data['personality_names'])
        self.assertEqual(original_blood_names, profile.master_data['blood_names'])

    def test_apply_from_keeps_existing_nested_aliases_alive(self):
        active = GameDataProfile.from_builtin()
        barmaid_records = active.barmaids
        first_barmaid = barmaid_records[0]
        executable = active.fork('executable', r'C:\Game\CDS_95.EXE')
        executable.overlay_records(
            'master_data',
            [{'id': 0, 'name': '변경된 여급'}],
            source='CDS_95.EXE:barmaids',
            collection_name='barmaid_database',
        )

        active.apply_from(executable)

        self.assertIs(barmaid_records, active.barmaids)
        self.assertIs(first_barmaid, active.barmaids[0])
        self.assertEqual('변경된 여급', first_barmaid['name'])
        self.assertEqual('executable', active.source_kind)

    def test_limit_overlay_keeps_unverified_limits(self):
        builtin = GameDataProfile.from_builtin()
        executable = builtin.fork('executable', r'C:\Game\CDS_95.EXE')
        executable.overlay_mapping('limits', {
            'player': {**executable.limits['player'], 'cash': 1_000_000, 'fame': 99_999},
        }, source='CDS_95.EXE:limits')

        self.assertEqual(1_000_000, executable.limits['player']['cash'])
        self.assertEqual(99_999, executable.limits['player']['fame'])
        self.assertEqual(4_294_967_295, executable.limits['player']['contract'])
        self.assertEqual(2_000, executable.limits['person']['vitality'])


if __name__ == '__main__':
    unittest.main()
