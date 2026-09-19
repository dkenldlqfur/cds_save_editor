import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / 'CDS_SaveEditor.pyw'),
    run_name='test_navigation_map_markers',
)
App = MODULE['CDS3SaveEditorApp']


class NavigationMapMarkerTests(unittest.TestCase):
    def make_app(self, region=None):
        app = App.__new__(App)
        app._navigation_map_marker_size = 1
        app.discovery_db = [{'index': 230}]
        app.discovery_state = [2]
        app.MAP_CITY_POINTS = ()
        app.MAP_DISCOVERY_REGIONS = (
            App.MAP_DISCOVERY_REGIONS[230] if region is None else region,)
        return app

    def collect(self, app):
        image = SimpleNamespace(width=app.NAVIGATION_MAP_WIDTH * 2)
        _, discovery_count = app._collect_navigation_map_markers(image)
        self.assertEqual(1, discovery_count)
        self.assertEqual(1, len(app._navigation_map_marker_records))
        return app._navigation_map_marker_records[0]

    def test_bundled_bulguksa_uses_its_real_exe_coordinates(self):
        self.assertEqual({
            'id': 230, 'min_x': 2144, 'min_y': 375,
            'max_x': 2145, 'max_y': 375,
        }, App.MAP_DISCOVERY_REGIONS[230])
        marker = self.collect(self.make_app())
        self.assertEqual('불국사', marker['name'])
        self.assertEqual('discovered', marker['state_key'])
        self.assertEqual((2144, 375, 2145, 375), marker['world_bounds'])
        self.assertEqual((1072.5, 187.75), (marker['x'], marker['y']))
        self.assertIn('bounds', marker)
        self.assertGreaterEqual(marker['bounds'][2] - marker['bounds'][0], 2)
        self.assertGreaterEqual(marker['bounds'][3] - marker['bounds'][1], 2)
        self.assertEqual(2, len(marker['coordinate'].splitlines()))
        self.assertTrue(marker['coordinate'].splitlines()[0].startswith('위도:'))
        self.assertTrue(marker['coordinate'].splitlines()[1].startswith('경도:'))
        self.assertNotIn('추정', marker['coordinate'])

    def test_every_located_discovery_is_a_rectangle(self):
        app = self.make_app()
        app.MAP_DISCOVERY_REGIONS = App.MAP_DISCOVERY_REGIONS
        image = SimpleNamespace(width=app.NAVIGATION_MAP_WIDTH * 2)
        _, discovery_count = app._collect_navigation_map_markers(image)
        self.assertEqual(146, discovery_count)
        self.assertTrue(all('bounds' in marker and '\n경도:' in marker['coordinate']
                            for marker in app._navigation_map_marker_records))

    def test_large_range_uses_exact_inclusive_exe_bounds(self):
        app = self.make_app(App.MAP_DISCOVERY_REGIONS[1])
        marker = self.collect(app)
        self.assertEqual((400, 100, 880, 850), marker['world_bounds'])
        self.assertEqual((200.0, 50.0, 440.5, 425.5), marker['bounds'])
        self.assertEqual(
            '위도: 북위 75.60°~남위 32.40°\n경도: 서경 53.28°~서경 122.40°',
            marker['coordinate'])

    def test_range_tooltip_orders_same_hemisphere_by_magnitude(self):
        self.assertEqual(
            '위도: 북위 10.80°~북위 18.00°\n경도: 서경 93.60°~서경 108.00°',
            App._navigation_map_range_text(500, 500, 600, 550))
        self.assertEqual(
            '위도: 남위 10.80°~남위 25.20°\n경도: 동경 36.00°~동경 50.40°',
            App._navigation_map_range_text(1500, 700, 1600, 800))

    def test_range_tooltip_orders_north_before_south_and_west_before_east(self):
        self.assertEqual(
            '위도: 북위 3.60°~남위 3.60°\n경도: 서경 7.20°~동경 7.20°',
            App._navigation_map_range_text(1200, 600, 1300, 650))

    def test_marker_size_changes_small_display_box_not_exe_range(self):
        small_app = self.make_app()
        small_app._navigation_map_marker_size = 0.5
        large_app = self.make_app()
        large_app._navigation_map_marker_size = 3
        small, large = self.collect(small_app), self.collect(large_app)
        self.assertEqual(small['world_bounds'], large['world_bounds'])
        self.assertEqual(1, small['bounds'][2] - small['bounds'][0])
        self.assertEqual(6, large['bounds'][2] - large['bounds'][0])

    def test_missing_exe_coordinates_do_not_make_off_map_marker(self):
        app = self.make_app({
            'id': 230, 'min_x': -1, 'min_y': -1,
            'max_x': -1, 'max_y': -1,
        })
        image = SimpleNamespace(width=app.NAVIGATION_MAP_WIDTH * 2)
        _, discovery_count = app._collect_navigation_map_markers(image)
        self.assertEqual(0, discovery_count)
        self.assertEqual([], app._navigation_map_marker_records)

    def test_bulguksa_uses_its_separate_save_record_for_marker_state(self):
        discovery = MODULE['load_discovery_database']()[-1]
        self.assertEqual(230, discovery['index'])
        self.assertEqual(527, discovery['disc_id'])
        self.assertEqual(0x2597B, discovery['save_offset'])
        save_buffer = bytearray(discovery['save_offset'] + 1)
        save_buffer[discovery['save_offset'] - 1] = 0xCC
        app = self.make_app()
        app.discovery_db = [discovery]
        app.discovery_state = [MODULE['state_from_marker'](
            save_buffer[discovery['save_offset'] - 1])]
        self.assertEqual('reported', self.collect(app)['state_key'])


if __name__ == '__main__':
    unittest.main()
