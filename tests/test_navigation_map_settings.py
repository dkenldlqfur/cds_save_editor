import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / 'CDS_SaveEditor.pyw'),
    run_name='test_navigation_map_settings',
)
load_settings = MODULE['load_navigation_map_marker_settings']
save_settings = MODULE['save_navigation_map_marker_settings']


class NavigationMapSettingsTests(unittest.TestCase):
    def test_default_and_legacy_zoom_limit_are_300_percent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ui_settings.json'
            with patch.dict(load_settings.__globals__, {'_theme_settings_path': lambda: str(path)}):
                self.assertEqual(3.0, load_settings()[1])
                path.write_text('{"navigation_map_zoom_limit": 1.0}', encoding='utf-8')
                self.assertEqual(3.0, load_settings()[1])

    def test_zoom_limit_is_stored_as_percent_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ui_settings.json'
            with patch.dict(load_settings.__globals__, {'_theme_settings_path': lambda: str(path)}):
                save_settings(1.0, 3.0, {}, {}, {}, {})
                self.assertEqual(300, json.loads(path.read_text(encoding='utf-8'))[
                    'navigation_map_zoom_limit'])
                self.assertEqual(3.0, load_settings()[1])
                save_settings(1.0, 1.0, {}, {}, {}, {})
                self.assertEqual(100, json.loads(path.read_text(encoding='utf-8'))[
                    'navigation_map_zoom_limit'])
                self.assertEqual(1.0, load_settings()[1])


if __name__ == '__main__':
    unittest.main()
