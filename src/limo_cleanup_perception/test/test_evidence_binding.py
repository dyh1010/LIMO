"""Tests for canonical build/runtime evidence file binding."""

import hashlib
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from limo_cleanup_perception.evidence_binding import (
    canonical_file_manifest,
    valid_release_id,
)


class EvidenceBindingTest(unittest.TestCase):
    def test_canonical_manifest_reopens_every_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'source.py'
            path.write_text('value = 1\n', encoding='utf-8')
            entry = {
                'name': 'source.py', 'path': str(path),
                'size_bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            result = canonical_file_manifest([entry])
            self.assertEqual(1, result['file_count'])
            path.write_text('value = 2\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                canonical_file_manifest([entry])

    def test_release_id_is_explicit_and_machine_safe(self):
        self.assertTrue(valid_release_id('field-v2-release-001'))
        self.assertFalse(valid_release_id('short'))
        self.assertFalse(valid_release_id('release id with spaces'))

    def test_source_set_hash_does_not_depend_on_workspace_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first_root = root / 'first'
            second_root = root / 'second'
            first_root.mkdir()
            second_root.mkdir()
            first = first_root / 'source.py'
            first.write_text('value = 1\n', encoding='utf-8')
            second = second_root / 'source.py'
            shutil.copy2(first, second)
            entry = {
                'name': 'perception:source.py',
                'path': 'source.py',
                'size_bytes': first.stat().st_size,
                'sha256': hashlib.sha256(first.read_bytes()).hexdigest(),
            }
            self.assertEqual(
                canonical_file_manifest([entry], first_root)['sha256'],
                canonical_file_manifest([entry], second_root)['sha256'])


if __name__ == '__main__':
    unittest.main()
