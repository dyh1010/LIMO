"""Exercise the ROS1 adapter with fake generated messages and publishers."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = str(PACKAGE_ROOT / 'src')
if PACKAGE_SOURCE not in sys.path:
    sys.path.insert(0, PACKAGE_SOURCE)

from limo_cleanup_ros1_perception import ros1_adapter  # noqa: E402


class _Point:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0


class _Target:
    def __init__(self):
        self.position = _Point()
        self.size = _Point()


class _Frame:
    pass


class _Detection:
    def __init__(self):
        self.position = _Point()
        self.size = _Point()


class _String:
    def __init__(self, data=''):
        self.data = data


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


def _target_payload():
    return {
        'observation_id': 'observation-1',
        'object_class': 'plastic_bottle',
        'confidence': 0.9,
        'valid': True,
        'actionable': True,
        'status': 'active',
        'error_code': '',
        'position': (0.1, 0.2, 1.0),
        'size': (0.05, 0.05, 0.2),
        'bbox': (1.0, 2.0, 3.0, 4.0),
        'depth_m': 1.0,
        'depth_valid_pixels': 20,
        'depth_total_pixels': 25,
        'depth_valid_ratio': 0.8,
        'source': 'bottle.pt',
        'position_semantics': 'camera_frame_depth_roi',
    }


class Ros1AdapterPureFakeTest(unittest.TestCase):

    def _adapter(self):
        adapter = ros1_adapter.Ros1PerceptionAdapter.__new__(
            ros1_adapter.Ros1PerceptionAdapter)
        adapter.PerceptionFrame = _Frame
        adapter.PerceptionTarget = _Target
        adapter.ObjectDetection = _Detection
        adapter.String = _String
        adapter.frame_publisher = _Publisher()
        adapter.legacy_publisher = _Publisher()
        adapter.status_publisher = _Publisher()
        return adapter

    def test_target_message_maps_all_typed_fields(self):
        message = self._adapter()._target_message(_target_payload())
        self.assertEqual('plastic_bottle', message.object_class)
        self.assertEqual((0.1, 0.2, 1.0), (
            message.position.x, message.position.y, message.position.z))
        self.assertEqual(20, message.depth_valid_pixels)
        self.assertTrue(message.actionable)

    def test_publish_uses_only_three_read_only_observation_publishers(self):
        adapter = self._adapter()
        target = _target_payload()
        payload = {
            'stamp_sec': 10.0,
            'frame_id': 'camera_color_optical_frame',
            'task_id': 'task-1',
            'capture_id': 'capture-1',
            'bundle_id': 'a' * 64,
            'model_binding_sha256': 'b' * 64,
            'sequence': 1,
            'valid': True,
            'status': 'targets_ready',
            'error_code': '',
            'sync_span_sec': 0.01,
            'processing_latency_sec': 0.02,
            'tf_target_frame': 'camera_color_optical_frame',
            'tf_valid': True,
            'tf_transform_applied': False,
            'tf_status': 'camera_frame_output',
            'tf_error_code': '',
            'targets': [target],
            'legacy_bottle': target,
        }
        adapter._publish(payload, SimpleNamespace(secs=10, nsecs=0))
        self.assertEqual(1, len(adapter.frame_publisher.messages))
        self.assertEqual(1, len(adapter.legacy_publisher.messages))
        self.assertEqual(1, len(adapter.status_publisher.messages))
        self.assertEqual(
            ('/cleanup/perception/frames', '/cleanup/detection/raw',
             '/cleanup/perception_status'),
            ros1_adapter.PERCEPTION_OUTPUT_TOPICS)
        self.assertFalse(any(
            token in '\n'.join(ros1_adapter.PERCEPTION_OUTPUT_TOPICS)
            for token in ('cmd_vel', 'move_base', 'goal', 'action', 'service')))


if __name__ == '__main__':
    unittest.main()
