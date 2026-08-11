"""Unit tests for read-only hardware readiness helpers."""

import math
from pathlib import Path

import numpy as np
from sensor_msgs.msg import Image

from limo_cleanup_bringup.hardware_readiness_check import (
    HardwareReadinessCheck,
    angle_distance,
    aligned_depth_frame_matches_rgb,
    depth_image_array,
    nearest_stamped_message,
    quaternion_to_rpy,
    summarize_depth,
)


PACKAGE_ROOT = Path(__file__).parents[1]
READINESS_SOURCE = (
    PACKAGE_ROOT / 'limo_cleanup_bringup' / 'hardware_readiness_check.py')


class FakeParameter:
    """Minimal parameter wrapper for actuator endpoint tests."""

    def __init__(self, value):
        self.value = value


class FakeEndpoint:
    """Minimal topic endpoint identity used by the read-only checker."""

    def __init__(self, node_namespace, node_name):
        self.node_namespace = node_namespace
        self.node_name = node_name


class FakeActuatorChecker:
    """Exercise endpoint checks without creating a ROS node."""

    append_check = staticmethod(HardwareReadinessCheck.append_check)
    add_actuator_safety_checks = (
        HardwareReadinessCheck.add_actuator_safety_checks)

    def get_parameter(self, name):
        assert name == 'forbidden_actuation_topics'
        return FakeParameter(['/cmd_vel'])

    @staticmethod
    def get_publishers_info_by_topic(topic):
        assert topic == '/cmd_vel'
        return []

    @staticmethod
    def get_subscriptions_info_by_topic(topic):
        assert topic == '/cmd_vel'
        return [FakeEndpoint('/', 'renamed_vendor_driver')]


def make_depth_image(values, encoding):
    """Create a compact sensor_msgs/Image for helper tests."""
    message = Image()
    message.height, message.width = values.shape
    message.encoding = encoding
    message.is_bigendian = False
    message.step = values.shape[1] * values.dtype.itemsize
    message.data = values.tobytes()
    return message


def make_stamped_image(seconds, nanoseconds=0):
    """Create an image with a controlled ROS header timestamp."""
    message = Image()
    message.header.stamp.sec = seconds
    message.header.stamp.nanosec = nanoseconds
    return message


def test_readonly_check_rejects_command_subscriber_without_publisher():
    """A renamed driver subscriber must fail read-only acceptance."""
    checks = []
    FakeActuatorChecker().add_actuator_safety_checks(checks)
    by_name = {item['name']: item for item in checks}

    assert by_name['no_actuation_publishers']['status'] == 'PASS'
    subscriber_check = by_name['no_actuation_subscribers']
    assert subscriber_check['status'] == 'FAIL'
    assert subscriber_check['measured']['active_subscribers'] == {
        '/cmd_vel': ['/renamed_vendor_driver'],
    }


def test_uint16_depth_uses_millimeter_scale():
    """16UC1 values should become meters through depth_scale."""
    values = np.full((16, 16), 1200, dtype=np.uint16)
    summary = summarize_depth(
        make_depth_image(values, '16UC1'), 0.001, 0.3, 3.0)
    assert summary['applied_scale'] == 0.001
    assert summary['median_m'] == 1.2


def test_float_depth_is_already_metric():
    """32FC1 values must not be multiplied by integer depth_scale."""
    values = np.full((16, 16), 1.5, dtype=np.float32)
    summary = summarize_depth(
        make_depth_image(values, '32FC1'), 0.001, 0.3, 3.0)
    assert summary['applied_scale'] == 1.0
    assert summary['median_m'] == 1.5


def test_depth_decoder_respects_row_padding():
    """The decoder should ignore padded values at the end of each row."""
    message = Image()
    message.height = 2
    message.width = 2
    message.encoding = '16UC1'
    message.is_bigendian = False
    message.step = 6
    padded = np.array([[1, 2, 999], [3, 4, 999]], dtype=np.uint16)
    message.data = padded.tobytes()
    decoded = depth_image_array(message)
    assert decoded.tolist() == [[1, 2], [3, 4]]


def test_quaternion_and_wrapped_angle_helpers():
    """Quaternion conversion and angle wrapping should be stable."""
    half = math.pi / 4.0
    roll, pitch, yaw = quaternion_to_rpy(
        0.0, 0.0, math.sin(half), math.cos(half))
    assert abs(roll) < 1e-12
    assert abs(pitch) < 1e-12
    assert abs(yaw - math.pi / 2.0) < 1e-12
    assert angle_distance(math.pi - 0.01, -math.pi + 0.01) < 0.021


def test_aligned_depth_frame_matches_rgb_frame():
    """Registered depth should pass when it uses the RGB optical frame."""
    frame = 'camera_color_optical_frame'
    assert aligned_depth_frame_matches_rgb(frame, frame)


def test_aligned_depth_frame_rejects_mismatch_and_empty_rgb():
    """Registered depth must reject a different frame or an empty RGB frame."""
    assert not aligned_depth_frame_matches_rgb(
        'camera_color_optical_frame',
        'camera_depth_optical_frame',
    )
    assert not aligned_depth_frame_matches_rgb('', '')


def test_nearest_stamped_message_ignores_startup_mismatch():
    """A later synchronized frame must replace an early stale sample."""
    rgb = make_stamped_image(10)
    stale_depth = make_stamped_image(9, 300_000_000)
    synchronized_depth = make_stamped_image(10, 20_000_000)
    nearest, delta = nearest_stamped_message(
        rgb, [stale_depth, synchronized_depth])
    assert nearest is synchronized_depth
    assert abs(delta - 0.02) < 1e-9


def test_nearest_stamped_message_handles_empty_candidates():
    """No candidate must return an explicit empty result."""
    nearest, delta = nearest_stamped_message(
        make_stamped_image(10), [])
    assert nearest is None
    assert delta is None


def test_readonly_acceptance_rejects_all_actuation_endpoints():
    """Read-only acceptance must reject publishers and subscribers."""
    source = READINESS_SOURCE.read_text(encoding='utf-8')
    assert "'/cleanup/base/safe_cmd_vel'" in source
    assert 'get_publishers_info_by_topic(topic)' in source
    assert 'get_subscriptions_info_by_topic(topic)' in source
    assert "'no_actuation_publishers'" in source
    assert "'no_actuation_subscribers'" in source
