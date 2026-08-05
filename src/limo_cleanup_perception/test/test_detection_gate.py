import math
import unittest

from limo_cleanup_interfaces.msg import ObjectDetection
from limo_cleanup_perception.detection_gate import (
    GateConfig,
    validate_detection,
)
from rclpy.clock import ClockType
from rclpy.time import Time


def make_valid_detection() -> ObjectDetection:
    message = ObjectDetection()
    message.detection_id = 'det-0001'
    message.task_id = 'task-0001'
    message.object_class = 'plastic_bottle'
    message.confidence = 0.9
    message.frame_id = 'camera_depth_optical_frame'
    message.position.x = 0.8
    message.position.y = 0.0
    message.position.z = 0.05
    message.size.x = 0.07
    message.size.y = 0.07
    message.size.z = 0.22
    return message


def make_config(**overrides) -> GateConfig:
    values = {'max_detection_age': 0.0}
    values.update(overrides)
    return GateConfig(**values)


class ValidateDetectionTest(unittest.TestCase):

    def test_valid_detection_is_accepted(self):
        accepted, reasons = validate_detection(
            make_valid_detection(), make_config())
        self.assertTrue(accepted)
        self.assertEqual([], reasons)

    def test_low_confidence_is_rejected(self):
        message = make_valid_detection()
        message.confidence = 0.2
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertTrue(
            any(r.startswith('low_confidence') for r in reasons))

    def test_confidence_above_one_is_rejected(self):
        message = make_valid_detection()
        message.confidence = 1.5
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('confidence_out_of_range', reasons)

    def test_unsupported_class_is_rejected(self):
        message = make_valid_detection()
        message.object_class = 'banana'
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('unsupported_class:banana', reasons)

    def test_unsupported_frame_is_rejected(self):
        message = make_valid_detection()
        message.frame_id = 'map'
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('unsupported_frame:map', reasons)

    def test_non_finite_position_is_rejected(self):
        message = make_valid_detection()
        message.position.x = math.nan
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('position_not_finite', reasons)

    def test_far_position_is_rejected(self):
        message = make_valid_detection()
        message.position.x = 10.0
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertTrue(
            any(r.startswith('distance_out_of_range') for r in reasons))

    def test_zero_size_is_rejected(self):
        message = make_valid_detection()
        message.size.x = 0.0
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('size_not_positive', reasons)

    def test_oversize_is_rejected(self):
        message = make_valid_detection()
        message.size.z = 5.0
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('size_out_of_bounds', reasons)

    def test_missing_detection_id_is_rejected(self):
        message = make_valid_detection()
        message.detection_id = ''
        accepted, reasons = validate_detection(message, make_config())
        self.assertFalse(accepted)
        self.assertIn('missing_detection_id', reasons)

    def test_stale_detection_is_rejected(self):
        message = make_valid_detection()
        now = Time(
            nanoseconds=10_000_000_000, clock_type=ClockType.ROS_TIME)
        message.stamp = Time(
            nanoseconds=8_000_000_000,
            clock_type=ClockType.ROS_TIME).to_msg()
        config = make_config(max_detection_age=1.0)
        accepted, reasons = validate_detection(message, config, now=now)
        self.assertFalse(accepted)
        self.assertTrue(
            any(r.startswith('stale_detection') for r in reasons))

    def test_fresh_detection_passes_age_check(self):
        message = make_valid_detection()
        now = Time(
            nanoseconds=10_000_000_000, clock_type=ClockType.ROS_TIME)
        message.stamp = Time(
            nanoseconds=9_500_000_000,
            clock_type=ClockType.ROS_TIME).to_msg()
        config = make_config(max_detection_age=1.0)
        accepted, reasons = validate_detection(message, config, now=now)
        self.assertTrue(accepted)
        self.assertEqual([], reasons)


if __name__ == '__main__':
    unittest.main()
