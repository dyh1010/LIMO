from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

from v1_diagnostic_capture import (  # noqa: E402
    DiagnosticCapture,
    new_output_path,
    wait_wall_duration,
)


class FakeSubscriber:
    def __init__(self, fail_unregister=False):
        self.fail_unregister = fail_unregister

    def unregister(self):
        if self.fail_unregister:
            raise RuntimeError('mock unregister failure')


class FakeRospy:
    def __init__(self, fail_at=None, fail_unregister_at=None):
        self.fail_at = fail_at
        self.fail_unregister_at = fail_unregister_at
        self.calls = 0

    def Subscriber(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError('mock subscribe failure')
        return FakeSubscriber(self.calls == self.fail_unregister_at)


class DiagnosticCapturePolicyTest(unittest.TestCase):

    def test_output_is_timestamped_under_exact_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = new_output_path(
                root, 'v1_diagnostics',
                datetime(2026, 8, 13, 12, 34, 56, 123456,
                         tzinfo=timezone.utc))
            self.assertEqual(output.parent, root)
            self.assertEqual(output.parent, root.resolve(strict=True))
            self.assertEqual(
                output.name,
                'v1_diagnostics_20260813T123456_123456Z.jsonl')
            self.assertFalse(output.exists())

    def test_output_rejects_relative_missing_and_unsafe_labels(self):
        with self.assertRaises(ValueError):
            new_output_path('relative', 'capture')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with self.assertRaises((OSError, ValueError)):
                new_output_path(root / 'missing', 'capture')
            for label in ('../escape', 'nested/path', '', 'space label'):
                with self.subTest(label=label), self.assertRaises(ValueError):
                    new_output_path(root, label)

    def test_wait_uses_wall_monotonic_deadline_not_ros_time(self):
        rospy = mock.Mock()
        rospy.is_shutdown.return_value = False
        with mock.patch(
                'v1_diagnostic_capture.time.monotonic',
                side_effect=[10.0, 10.0, 10.05, 10.10]), mock.patch(
                    'v1_diagnostic_capture.time.sleep') as sleep:
            wait_wall_duration(0.10, rospy, poll_s=0.05)
        self.assertEqual(sleep.call_count, 2)

    def test_constructor_and_unregister_failures_still_close_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            failed_output = root / 'init_failure.jsonl'
            with self.assertRaises(RuntimeError):
                DiagnosticCapture(
                    FakeRospy(fail_at=2), object, object, object, object,
                    failed_output)
            with failed_output.open('a', encoding='utf-8') as stream:
                stream.write('')

            close_output = root / 'close_failure.jsonl'
            capture = DiagnosticCapture(
                FakeRospy(fail_unregister_at=1), object, object, object,
                object, close_output)
            capture.close()
            self.assertTrue(capture.closed)
            self.assertTrue(capture.stream.closed)
            payload = close_output.read_text(encoding='utf-8')
            self.assertIn('mock unregister failure', payload)


if __name__ == '__main__':
    unittest.main()
