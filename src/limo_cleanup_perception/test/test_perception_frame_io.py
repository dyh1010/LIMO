"""Tests for complete typed-frame JSON serialization."""

import math
import unittest

from limo_cleanup_perception.perception_frame_io import frame_to_dict


class Value:
    """Tiny mutable message stand-in."""


def message_fixture():
    """Build one ROS-like typed frame without importing ROS."""
    target = Value()
    target.observation_id = 'obs-1'
    target.object_class = 'trash_bin'
    target.confidence = 0.92
    target.valid = True
    target.actionable = False
    target.status = 'observed'
    target.error_code = ''
    target.position = Value()
    target.position.x, target.position.y, target.position.z = 0.1, 0.2, 1.0
    target.size = Value()
    target.size.x, target.size.y, target.size.z = 0.5, 0.6, 0.1
    target.bbox_x1, target.bbox_y1 = 10.0, 20.0
    target.bbox_x2, target.bbox_y2 = 100.0, 200.0
    target.depth_m = 1.0
    target.depth_valid_pixels = 100
    target.depth_total_pixels = 120
    target.depth_valid_ratio = 100 / 120
    target.source = 'bin_model'
    target.position_semantics = 'aligned_depth_roi_median'

    frame = Value()
    frame.stamp = Value()
    frame.stamp.sec, frame.stamp.nanosec = 10, 500000000
    frame.frame_id = 'camera_color_optical_frame'
    frame.task_id = 'read-only-perception'
    frame.sequence = 4
    frame.valid = True
    frame.status = 'targets_ready'
    frame.error_code = ''
    frame.sync_span_sec = 0.02
    frame.processing_latency_sec = 0.1
    frame.targets = [target]
    return frame


class PerceptionFrameIoTest(unittest.TestCase):
    """Verify complete schema and fail-closed numeric handling."""

    def test_complete_target_contract_is_serialized(self):
        payload = frame_to_dict(message_fixture(), 11.0)
        self.assertTrue(payload['read_only'])
        self.assertEqual(0.5, payload['transport_latency_sec'])
        self.assertEqual('trash_bin', payload['targets'][0]['object_class'])
        self.assertEqual(
            [10.0, 20.0, 100.0, 200.0],
            payload['targets'][0]['bbox'])
        self.assertEqual(
            100, payload['targets'][0]['depth_valid_pixels'])

    def test_non_finite_target_is_rejected(self):
        frame = message_fixture()
        frame.targets[0].confidence = math.nan
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            frame_to_dict(frame, 11.0)


if __name__ == '__main__':
    unittest.main()
