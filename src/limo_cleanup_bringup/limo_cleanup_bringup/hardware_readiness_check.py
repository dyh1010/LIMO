"""Read-only RGB-D, CameraInfo, TF, and actuator-safety checks."""

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener


INTEGER_DEPTH_ENCODINGS = {'16UC1', 'mono16'}
FLOAT_DEPTH_ENCODINGS = {'32FC1'}


def stamp_seconds(stamp):
    """Convert a ROS builtin time message to floating-point seconds."""
    return float(stamp.sec) + float(stamp.nanosec) / 1e9


def angle_distance(first, second):
    """Return the smallest absolute difference between two angles."""
    return abs(math.atan2(math.sin(first - second), math.cos(first - second)))


def quaternion_to_rpy(x, y, z, w):
    """Convert a quaternion to roll, pitch, and yaw."""
    sin_roll = 2.0 * (w * x + y * z)
    cos_roll = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sin_roll, cos_roll)

    sin_pitch = 2.0 * (w * y - z * x)
    sin_pitch = max(-1.0, min(1.0, sin_pitch))
    pitch = math.asin(sin_pitch)

    sin_yaw = 2.0 * (w * z + x * y)
    cos_yaw = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(sin_yaw, cos_yaw)
    return roll, pitch, yaw


def depth_image_array(message):
    """Decode supported depth image encodings without cv_bridge."""
    encoding = message.encoding
    if encoding in INTEGER_DEPTH_ENCODINGS:
        dtype = np.dtype(np.uint16)
    elif encoding in FLOAT_DEPTH_ENCODINGS:
        dtype = np.dtype(np.float32)
    else:
        raise ValueError(f'unsupported depth encoding: {encoding}')

    dtype = dtype.newbyteorder('>' if message.is_bigendian else '<')
    item_size = dtype.itemsize
    if message.step < message.width * item_size:
        raise ValueError('depth image step is smaller than row width')
    row_items = message.step // item_size
    expected_items = message.height * row_items
    values = np.frombuffer(message.data, dtype=dtype, count=expected_items)
    return values.reshape(message.height, row_items)[:, :message.width]


def summarize_depth(message, integer_scale, min_depth, max_depth):
    """Summarize valid metric depths and the unit conversion used."""
    image = depth_image_array(message)
    sampled = image[::8, ::8].astype(np.float64, copy=False)
    applied_scale = integer_scale if message.encoding in (
        INTEGER_DEPTH_ENCODINGS) else 1.0
    metric = sampled * applied_scale
    valid = metric[
        np.isfinite(metric)
        & (metric >= min_depth)
        & (metric <= max_depth)
    ]
    summary = {
        'encoding': message.encoding,
        'configured_integer_scale': integer_scale,
        'applied_scale': applied_scale,
        'sampled_pixels': int(metric.size),
        'valid_pixels': int(valid.size),
        'valid_ratio': (
            float(valid.size) / float(metric.size) if metric.size else 0.0),
    }
    if valid.size:
        summary.update({
            'min_m': float(np.min(valid)),
            'median_m': float(np.median(valid)),
            'max_m': float(np.max(valid)),
        })
    return summary


class HardwareReadinessCheck(Node):
    """Subscribe and inspect only; never publish commands or call actions."""

    def __init__(self):
        super().__init__('cleanup_hardware_readiness')
        self.declare_parameters('', [
            ('rgb_topic', '/camera/color/image_raw'),
            ('depth_topic', '/camera/depth_registered/image_raw'),
            ('camera_info_topic', '/camera/color/camera_info'),
            ('base_frame', 'base_link'),
            ('camera_frame_override', ''),
            ('timeout_sec', 20.0),
            ('settle_sec', 2.0),
            ('max_sync_delta_sec', 0.15),
            ('depth_scale', 0.001),
            ('min_depth', 0.30),
            ('max_depth', 3.00),
            ('min_valid_depth_ratio', 0.001),
            ('require_tf', True),
            ('check_expected_extrinsics', False),
            ('expected_x', 0.0),
            ('expected_y', 0.0),
            ('expected_z', 0.0),
            ('expected_roll', 0.0),
            ('expected_pitch', 0.0),
            ('expected_yaw', 0.0),
            ('translation_tolerance_m', 0.02),
            ('rotation_tolerance_rad', 0.05),
            ('forbidden_actuation_topics', [
                '/cmd_vel',
                '/cmd_vel_nav',
                '/cmd_vel_teleop',
                '/limo/vel_cmd',
                '/arm_controller/joint_trajectory',
                '/joint_trajectory_controller/joint_trajectory',
                '/gripper_controller/commands',
            ]),
            ('report_path', '/tmp/limo_hardware_readiness.json'),
        ])
        self.rgb_topic = self.string_parameter('rgb_topic')
        self.depth_topic = self.string_parameter('depth_topic')
        self.camera_info_topic = self.string_parameter('camera_info_topic')
        self.base_frame = self.string_parameter('base_frame')
        self.start_monotonic = time.monotonic()
        self.rgb_message = None
        self.depth_message = None
        self.camera_info_message = None
        self.done = False
        self.exit_code = 1
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.create_subscription(
            Image, self.rgb_topic, self.rgb_callback,
            qos_profile_sensor_data)
        self.create_subscription(
            Image, self.depth_topic, self.depth_callback,
            qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, self.camera_info_topic, self.camera_info_callback,
            qos_profile_sensor_data)
        self.create_timer(0.25, self.check_if_ready)
        self.get_logger().info(
            'Read-only check started; no command publisher, action client, '
            'base driver, or arm driver is created by this node')

    def string_parameter(self, name):
        """Read a string parameter."""
        return self.get_parameter(name).value

    def float_parameter(self, name):
        """Read a floating-point parameter."""
        return float(self.get_parameter(name).value)

    def bool_parameter(self, name):
        """Read a Boolean parameter."""
        return bool(self.get_parameter(name).value)

    def rgb_callback(self, message):
        """Keep the newest RGB image."""
        self.rgb_message = message

    def depth_callback(self, message):
        """Keep the newest aligned depth image."""
        self.depth_message = message

    def camera_info_callback(self, message):
        """Keep the newest color CameraInfo message."""
        self.camera_info_message = message

    def check_if_ready(self):
        """Finish when samples settle or when the timeout expires."""
        if self.done:
            return
        elapsed = time.monotonic() - self.start_monotonic
        have_messages = all((
            self.rgb_message is not None,
            self.depth_message is not None,
            self.camera_info_message is not None,
        ))
        if have_messages and elapsed >= self.float_parameter('settle_sec'):
            self.finish(timed_out=False)
            return
        if elapsed >= self.float_parameter('timeout_sec'):
            self.finish(timed_out=True)

    def finish(self, timed_out):
        """Evaluate all checks, write the report, and stop spinning."""
        report = self.build_report(timed_out)
        report_path = Path(self.string_parameter('report_path')).expanduser()
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8')
        except OSError as error:
            report['checks'].append({
                'name': 'write_report',
                'status': 'FAIL',
                'detail': str(error),
            })
            report['result'] = 'FAIL'

        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if report['result'] == 'PASS':
            self.get_logger().info(rendered)
            self.exit_code = 0
        else:
            self.get_logger().error(rendered)
            self.exit_code = 1
        self.done = True

    def build_report(self, timed_out):
        """Build a machine-readable report from the latest graph state."""
        checks = []
        self.add_topic_presence_checks(checks, timed_out)
        if all((self.rgb_message, self.depth_message,
                self.camera_info_message)):
            self.add_image_geometry_checks(checks)
            self.add_depth_checks(checks)
            self.add_tf_checks(checks)
        self.add_actuator_safety_checks(checks)
        result = 'PASS' if all(
            item['status'] == 'PASS' for item in checks) else 'FAIL'
        return {
            'schema_version': 1,
            'result': result,
            'read_only': True,
            'generated_at_unix': time.time(),
            'pid': os.getpid(),
            'topics': {
                'rgb': self.rgb_topic,
                'aligned_depth': self.depth_topic,
                'camera_info': self.camera_info_topic,
            },
            'checks': checks,
        }

    @staticmethod
    def append_check(checks, name, passed, detail, measured=None):
        """Append a normalized PASS or FAIL item."""
        item = {
            'name': name,
            'status': 'PASS' if passed else 'FAIL',
            'detail': detail,
        }
        if measured is not None:
            item['measured'] = measured
        checks.append(item)

    def add_topic_presence_checks(self, checks, timed_out):
        """Check that all three required sensor streams were observed."""
        for name, topic, message in (
                ('rgb_received', self.rgb_topic, self.rgb_message),
                ('aligned_depth_received', self.depth_topic,
                 self.depth_message),
                ('camera_info_received', self.camera_info_topic,
                 self.camera_info_message)):
            received = message is not None
            detail = f'received from {topic}' if received else (
                f'no message from {topic}' +
                (' before timeout' if timed_out else ''))
            self.append_check(checks, name, received, detail)

    def add_image_geometry_checks(self, checks):
        """Check resolution, intrinsics, frames, and timestamp alignment."""
        rgb = self.rgb_message
        depth = self.depth_message
        info = self.camera_info_message
        same_resolution = (
            rgb.width == depth.width and rgb.height == depth.height)
        self.append_check(
            checks, 'rgb_depth_same_resolution', same_resolution,
            'aligned depth must have the same pixel grid as RGB',
            measured={
                'rgb': [rgb.width, rgb.height],
                'depth': [depth.width, depth.height],
            })

        info_matches = info.width == rgb.width and info.height == rgb.height
        self.append_check(
            checks, 'camera_info_matches_rgb', info_matches,
            'CameraInfo dimensions must match RGB',
            measured={
                'rgb': [rgb.width, rgb.height],
                'camera_info': [info.width, info.height],
            })

        intrinsics_valid = (
            len(info.k) == 9 and info.k[0] > 0.0 and info.k[4] > 0.0)
        self.append_check(
            checks, 'camera_intrinsics_valid', intrinsics_valid,
            'fx and fy must be positive',
            measured={
                'fx': float(info.k[0]),
                'fy': float(info.k[4]),
                'cx': float(info.k[2]),
                'cy': float(info.k[5]),
            })

        delta = abs(
            stamp_seconds(rgb.header.stamp)
            - stamp_seconds(depth.header.stamp))
        max_delta = self.float_parameter('max_sync_delta_sec')
        self.append_check(
            checks, 'rgb_depth_timestamp_alignment', delta <= max_delta,
            f'RGB/depth timestamp delta must be <= {max_delta:.3f} s',
            measured={'delta_sec': delta})

        frame_consistent = bool(rgb.header.frame_id) and (
            not info.header.frame_id
            or info.header.frame_id == rgb.header.frame_id)
        self.append_check(
            checks, 'rgb_camera_info_frame_consistency', frame_consistent,
            'RGB and CameraInfo should use the same optical frame',
            measured={
                'rgb_frame': rgb.header.frame_id,
                'depth_frame': depth.header.frame_id,
                'camera_info_frame': info.header.frame_id,
            })

    def add_depth_checks(self, checks):
        """Check depth encoding, scale, and plausible metric samples."""
        try:
            summary = summarize_depth(
                self.depth_message,
                self.float_parameter('depth_scale'),
                self.float_parameter('min_depth'),
                self.float_parameter('max_depth'))
        except (ValueError, TypeError) as error:
            self.append_check(
                checks, 'depth_encoding_and_units', False, str(error))
            return
        minimum_ratio = self.float_parameter('min_valid_depth_ratio')
        valid = summary['valid_ratio'] >= minimum_ratio
        self.append_check(
            checks, 'depth_encoding_and_units', valid,
            'integer depth uses depth_scale; 32FC1 is already meters',
            measured=summary)

    def selected_camera_frame(self):
        """Choose the optical frame used for TF checks."""
        override = self.string_parameter('camera_frame_override')
        if override:
            return override
        if self.rgb_message and self.rgb_message.header.frame_id:
            return self.rgb_message.header.frame_id
        return ''

    def add_tf_checks(self, checks):
        """Check base-to-camera connectivity and optional measured values."""
        if not self.bool_parameter('require_tf'):
            self.append_check(
                checks, 'base_to_camera_tf', True,
                'TF requirement explicitly disabled')
            return
        camera_frame = self.selected_camera_frame()
        if not camera_frame:
            self.append_check(
                checks, 'base_to_camera_tf', False,
                'camera frame is empty')
            return
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                camera_frame,
                Time(),
                timeout=Duration(seconds=0.25))
        except TransformException as error:
            self.append_check(
                checks, 'base_to_camera_tf', False,
                f'{self.base_frame} -> {camera_frame} unavailable: {error}')
            return

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        roll, pitch, yaw = quaternion_to_rpy(
            rotation.x, rotation.y, rotation.z, rotation.w)
        measured = {
            'parent': self.base_frame,
            'child': camera_frame,
            'translation_m': [translation.x, translation.y, translation.z],
            'rpy_rad': [roll, pitch, yaw],
        }
        finite = all(math.isfinite(value) for value in (
            translation.x, translation.y, translation.z,
            roll, pitch, yaw))
        self.append_check(
            checks, 'base_to_camera_tf', finite,
            'TF exists and contains finite values', measured=measured)

        if not self.bool_parameter('check_expected_extrinsics'):
            return
        expected_translation = np.array([
            self.float_parameter('expected_x'),
            self.float_parameter('expected_y'),
            self.float_parameter('expected_z'),
        ])
        measured_translation = np.array([
            translation.x, translation.y, translation.z])
        translation_error = float(np.linalg.norm(
            measured_translation - expected_translation))
        expected_rpy = (
            self.float_parameter('expected_roll'),
            self.float_parameter('expected_pitch'),
            self.float_parameter('expected_yaw'),
        )
        rotation_error = max(
            angle_distance(roll, expected_rpy[0]),
            angle_distance(pitch, expected_rpy[1]),
            angle_distance(yaw, expected_rpy[2]),
        )
        translation_limit = self.float_parameter(
            'translation_tolerance_m')
        rotation_limit = self.float_parameter('rotation_tolerance_rad')
        extrinsics_valid = (
            translation_error <= translation_limit
            and rotation_error <= rotation_limit)
        self.append_check(
            checks, 'camera_extrinsics_match_measurement', extrinsics_valid,
            'TF must match the independently measured camera mount',
            measured={
                'translation_error_m': translation_error,
                'rotation_error_rad': rotation_error,
                'translation_tolerance_m': translation_limit,
                'rotation_tolerance_rad': rotation_limit,
            })

    def add_actuator_safety_checks(self, checks):
        """Fail when any configured actuation topic has a live publisher."""
        active = {}
        topics = self.get_parameter('forbidden_actuation_topics').value
        for topic in topics:
            publishers = self.get_publishers_info_by_topic(topic)
            if publishers:
                active[topic] = sorted({
                    f'{item.node_namespace}/{item.node_name}'.replace(
                        '//', '/')
                    for item in publishers
                })
        self.append_check(
            checks, 'no_actuation_publishers', not active,
            'no publisher may be connected to configured base/arm/gripper '
            'command topics during read-only acceptance',
            measured={'active_publishers': active})


def main(args=None):
    """Run the read-only check and return a process exit code."""
    rclpy.init(args=args)
    node = HardwareReadinessCheck()
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.25)
        return node.exit_code
    except KeyboardInterrupt:
        return 130
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
