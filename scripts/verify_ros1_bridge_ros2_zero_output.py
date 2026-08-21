#!/usr/bin/env python3
"""Read-only ROS2-side verifier for the ROS1 base bridge zero stage."""

import math
import time

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node


SAFE_TOPIC = '/cleanup/base/safe_cmd_vel'
FORBIDDEN_ROS2_TOPICS = (
    '/cmd_vel',
    '/cmd_vel_nav',
    '/cmd_vel_teleop',
    '/limo/vel_cmd',
    '/cleanup/base/driver_cmd_vel',
)
EXPECTED_GATEWAY = '/cleanup_tracked_base_zero_output'
EXPECTED_BRIDGE = '/dynamic_bridge'
ZERO_EPSILON = 1e-9
MINIMUM_SAMPLES = 10


def _fully_qualified_name(name, namespace):
    namespace = str(namespace or '/').rstrip('/') or '/'
    if namespace == '/':
        return '/{}'.format(name)
    return '{}/{}'.format(namespace, name)


def _endpoint_names(endpoints):
    names = []
    gids = set()
    for endpoint in endpoints:
        gid = getattr(endpoint, 'endpoint_gid', None)
        if gid is None:
            raise RuntimeError('ROS2 endpoint GID API is unavailable')
        normalized_gid = bytes(gid)
        if not normalized_gid or not any(normalized_gid):
            raise RuntimeError('ROS2 endpoint GID is empty/all-zero')
        if normalized_gid in gids:
            raise RuntimeError('duplicate ROS2 endpoint GID detected')
        gids.add(normalized_gid)
        names.append(_fully_qualified_name(
            endpoint.node_name, endpoint.node_namespace))
    return names


def _twist_values(message):
    return (
        float(message.linear.x),
        float(message.linear.y),
        float(message.linear.z),
        float(message.angular.x),
        float(message.angular.y),
        float(message.angular.z),
    )


class Ros2BridgeZeroVerifier(Node):
    """Check exact gateway/bridge endpoints and continuous zero samples."""

    def __init__(self):
        super().__init__('verify_ros1_bridge_ros2_zero_output')
        self.declare_parameter('continuous', False)
        self.continuous = bool(self.get_parameter('continuous').value)
        self.samples = []
        self.invalid_sample = None
        self.subscription = self.create_subscription(
            Twist, SAFE_TOPIC, self._on_command, 1)

    def _on_command(self, message):
        values = _twist_values(message)
        if (
                not all(math.isfinite(value) for value in values)
                or any(abs(value) > ZERO_EPSILON for value in values)):
            self.invalid_sample = values
            return
        if len(self.samples) < MINIMUM_SAMPLES:
            self.samples.append(values)

    def verify_topology(self):
        publishers = self.get_publishers_info_by_topic(SAFE_TOPIC)
        subscribers = self.get_subscriptions_info_by_topic(SAFE_TOPIC)
        if len(publishers) != 1 or _endpoint_names(publishers) != [
                EXPECTED_GATEWAY]:
            raise RuntimeError(
                '{} publishers are {}, expected only {}'.format(
                    SAFE_TOPIC, sorted(_endpoint_names(publishers)),
                    EXPECTED_GATEWAY))
        expected_verifier = _fully_qualified_name(
            self.get_name(), self.get_namespace())
        expected_subscribers = sorted([EXPECTED_BRIDGE, expected_verifier])
        if (
                len(subscribers) != 2
                or sorted(_endpoint_names(subscribers)) != expected_subscribers):
            raise RuntimeError(
                '{} subscribers are {}, expected {}'.format(
                    SAFE_TOPIC, sorted(_endpoint_names(subscribers)),
                    sorted(expected_subscribers)))
        for topic in FORBIDDEN_ROS2_TOPICS:
            if (
                    self.get_publishers_info_by_topic(topic)
                    or self.get_subscriptions_info_by_topic(topic)):
                raise RuntimeError(
                    '{} must have zero ROS2 endpoints'.format(topic))


def run_verification():
    verifier = Ros2BridgeZeroVerifier()
    deadline = time.monotonic() + 8.0
    last_error = None
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(verifier, timeout_sec=0.05)
            if verifier.invalid_sample is not None:
                raise RuntimeError(
                    'invalid or nonzero ROS2 bridge sample: {}'.format(
                        verifier.invalid_sample))
            try:
                verifier.verify_topology()
                last_error = None
            except RuntimeError as error:
                last_error = error
                verifier.samples.clear()
            if last_error is None and len(verifier.samples) >= MINIMUM_SAMPLES:
                print(
                    'ROS1_BRIDGE_ROS2_ZERO_PASS: samples={}'.format(
                        len(verifier.samples)),
                    flush=True)
                if not verifier.continuous:
                    return 0
                print('ROS1_BRIDGE_ROS2_ZERO_MONITORING', flush=True)
                verifier.samples.clear()
                while rclpy.ok():
                    rclpy.spin_once(verifier, timeout_sec=0.05)
                    if verifier.invalid_sample is not None:
                        raise RuntimeError(
                            'invalid or nonzero ROS2 bridge sample: {}'.format(
                                verifier.invalid_sample))
                    verifier.verify_topology()
                    if len(verifier.samples) >= MINIMUM_SAMPLES:
                        print(
                            'ROS1_BRIDGE_ROS2_CONTINUOUS_ZERO_WINDOW_PASS',
                            flush=True)
                        verifier.samples.clear()
                return 0
        if last_error is not None:
            raise last_error
        raise RuntimeError(
            'received {} zero samples, expected at least {}'.format(
                len(verifier.samples), MINIMUM_SAMPLES))
    finally:
        verifier.destroy_node()


def main():
    rclpy.init()
    try:
        return run_verification()
    except Exception as error:
        print(
            'ROS1_BRIDGE_ROS2_ZERO_BLOCKED: {}'.format(error),
            flush=True)
        return 1
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
