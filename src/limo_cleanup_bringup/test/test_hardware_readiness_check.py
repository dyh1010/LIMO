"""Unit tests for read-only hardware readiness helpers."""

import math

import numpy as np
from sensor_msgs.msg import Image

from limo_cleanup_bringup.hardware_readiness_check import (
    angle_distance,
    depth_image_array,
    quaternion_to_rpy,
    summarize_depth,
)


def make_depth_image(values, encoding):
    """Create a compact sensor_msgs/Image for helper tests."""
    message = Image()
    message.height, message.width = values.shape
    message.encoding = encoding
    message.is_bigendian = False
    message.step = values.shape[1] * values.dtype.itemsize
    message.data = values.tobytes()
    return message


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
