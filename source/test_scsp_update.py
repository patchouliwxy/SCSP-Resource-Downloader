import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import scsp_update as updater
from test_scsp_web import resource


class UpdateTests(unittest.TestCase):
    def test_console_version_extracts_only_version_and_uses_last_line(self):
        text = ('token=secret\nPlugin Loaded - Game Version: 2.17.0, Resource Version: 20006000@abcd=\n'
                'Plugin Loaded - Game Version: 2.18.0, Resource Version: 20006100@Fsfg1as9y1FopBx2GTxLj/s=')
        self.assertEqual(updater.console_version(text), ('2.18.0', '20006100@Fsfg1as9y1FopBx2GTxLj/s='))
        with self.assertRaises(ValueError):
            updater.console_version('Resource Version: 20006100')

    def test_validation_rejects_incomplete_names_and_conflicting_version(self):
        index = dict(game_version='test', resource_version='test', entries=[resource('002_yumeas_01.anim')])
        songs = dict(game_version='test', resource_version='test', songs={'002_yumeas': {'title': '夢咲きAfter school'}})
        chars = dict(game_version='test', resource_version='test', characters={'09': '小宮 果穂'},
                     formations={'002_yumeas': {'members': [{'name': '小宮 果穂'}]}})
        self.assertEqual(updater.validate(index, songs, chars), 1)
        songs['songs'].clear()
        with self.assertRaises(ValueError):
            updater.validate(index, songs, chars)
        songs['resource_version'] = 'older'
        with self.assertRaises(ValueError):
            updater.validate(index, songs, chars)

    def test_publication_failure_rolls_back_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / 'run/staging'
            stage.mkdir(parents=True)
            for name in ('first.json', 'second.json'):
                (root / name).write_text('old', encoding='utf-8')
                (stage / name).write_text('new', encoding='utf-8')
            copy = shutil.copy2

            def fail_second(source, target, *args, **kwargs):
                if Path(source) == stage / 'second.json':
                    raise OSError('Simulated disk write failure')
                return copy(source, target, *args, **kwargs)

            with patch.object(updater, 'PUBLISHED', ('first.json', 'second.json')), patch.object(updater.shutil, 'copy2', side_effect=fail_second):
                with self.assertRaises(OSError):
                    updater.publish(stage, root)
            self.assertEqual((root / 'first.json').read_text(), 'old')
            self.assertEqual((root / 'second.json').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
