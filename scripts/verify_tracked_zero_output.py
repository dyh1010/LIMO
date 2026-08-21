#!/usr/bin/env python3
import math
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


SAFE_COMMAND_TOPIC = '/test/cleanup/tracked_zero_output'
EXPECTED_PUBLISHER_NODE = 'cleanup_tracked_base_zero_output'
PUBLIC_COMMAND_TOPICS = (
    '/cmd_vel',
    '/cmd_vel_nav',
    '/cmd_vel_teleop',
    '/limo/vel_cmd',
)
ZERO_EPSILON = 1e-9
MINIMUM_SAMPLES = 10


def _fully_qualified_node_name(node_name, node_namespace):
    namespace = str(node_namespace or '/').rstrip('/')
    if not namespace:
        namespace = '/'
    if namespace == '/':
        return '/{}'.format(node_name)
    return '{}/{}'.format(namespace, node_name)


def _endpoint_name(endpoint):
    return _fully_qualified_node_name(
        endpoint.node_name, endpoint.node_namespace)


def _rmw_identifier():
    public_getter = getattr(
        rclpy, 'get_rmw_implementation_identifier', None)
    if public_getter is not None:
        return str(public_getter())
    try:
        from rclpy.impl.implementation_singleton import rclpy_implementation
    except ImportError:
        return 'unknown'
    private_getter = getattr(
        rclpy_implementation, 'rmw_get_implementation_identifier', None)
    if private_getter is None:
        return 'unknown'
    return str(private_getter())


def _twist_values(message):
    return (
        float(message.linear.x),
        float(message.linear.y),
        float(message.linear.z),
        float(message.angular.x),
        float(message.angular.y),
        float(message.angular.z),
    )


class ZeroOutputVerifier(Node):
    def __init__(self):
        super().__init__('cleanup_tracked_zero_output_verifier')
        self.sample_count = 0
        self.invalid_sample = None
        self.command_subscription = self.create_subscription(
            Twist, SAFE_COMMAND_TOPIC, self._on_command, 1)

    def _on_command(self, message):
        values = _twist_values(message)
        self.sample_count += 1
        if not all(math.isfinite(value) for value in values):
            self.invalid_sample = ('non-finite', values)
        elif any(abs(value) > ZERO_EPSILON for value in values):
            self.invalid_sample = ('non-zero', values)

    def verify_topology(self):
        publishers = self.get_publishers_info_by_topic(SAFE_COMMAND_TOPIC)
        subscribers = self.get_subscriptions_info_by_topic(
            SAFE_COMMAND_TOPIC)
        if len(publishers) != 1:
            raise RuntimeError(
                '{} must have exactly one publisher; found {}'.format(
                    SAFE_COMMAND_TOPIC, len(publishers)))
        publisher_name = _endpoint_name(publishers[0])
        expected_name = '/{}'.format(EXPECTED_PUBLISHER_NODE)
        if publisher_name != expected_name:
            raise RuntimeError(
                '{} publisher is {}, expected {}'.format(
                    SAFE_COMMAND_TOPIC, publisher_name, expected_name))
        subscriber_names = {
            _endpoint_name(endpoint) for endpoint in subscribers}
        expected_subscriber = _fully_qualified_node_name(
            self.get_name(), self.get_namespace())
        if (len(subscribers) != 1
                or subscriber_names != {expected_subscriber}):
            raise RuntimeError(
                '{} must have only the verifier subscriber; found {}'.format(
                    SAFE_COMMAND_TOPIC, sorted(subscriber_names)))

        for topic in PUBLIC_COMMAND_TOPICS:
            topic_publishers = self.get_publishers_info_by_topic(topic)
            topic_subscribers = self.get_subscriptions_info_by_topic(topic)
            if topic_publishers or topic_subscribers:
                raise RuntimeError(
                    '{} must have no endpoints; publishers={}, '
                    'subscribers={}'.format(
                        topic,
                        sorted(_endpoint_name(endpoint)
                               for endpoint in topic_publishers),
                        sorted(_endpoint_name(endpoint)
                               for endpoint in topic_subscribers)))


def _spin_until(node, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if predicate():
            return True
    return False


def run_verification():
    verifier = ZeroOutputVerifier()
    try:
        expected_publisher = '/{}'.format(EXPECTED_PUBLISHER_NODE)
        expected_subscriber = _fully_qualified_node_name(
            verifier.get_name(), verifier.get_namespace())
        discovered = _spin_until(
            verifier,
            lambda: (
                len(verifier.get_publishers_info_by_topic(
                    SAFE_COMMAND_TOPIC)) == 1
                and {
                    _endpoint_name(endpoint)
                    for endpoint in verifier.get_publishers_info_by_topic(
                        SAFE_COMMAND_TOPIC)
                } == {expected_publisher}
                and len(verifier.get_subscriptions_info_by_topic(
                    SAFE_COMMAND_TOPIC)) == 1
                and {
                    _endpoint_name(endpoint)
                    for endpoint in verifier.get_subscriptions_info_by_topic(
                        SAFE_COMMAND_TOPIC)
                } == {expected_subscriber}
            ),
            5.0,
        )
        if not discovered:
            raise RuntimeError(
                '{} endpoint metadata did not resolve to the exact '
                'zero-output topology'.format(
                    SAFE_COMMAND_TOPIC))
        verifier.verify_topology()

        enough_samples = _spin_until(
            verifier,
            lambda: (
                verifier.sample_count >= MINIMUM_SAMPLES
                or verifier.invalid_sample is not None),
            3.0,
        )
        if verifier.invalid_sample is not None:
            kind, values = verifier.invalid_sample
            raise RuntimeError(
                '{} Twist sample received: {}'.format(kind, values))
        if not enough_samples:
            raise RuntimeError(
                'received only {} zero samples; need at least {}'.format(
                    verifier.sample_count, MINIMUM_SAMPLES))

        verifier.verify_topology()
        print('ZERO_OUTPUT_GUARD_PASS')
        print(
            '{} published {} finite all-axis zero samples'.format(
                SAFE_COMMAND_TOPIC, verifier.sample_count))
        print('Public /cmd_vel command topics have no endpoints.')
        return 0
    except RuntimeError as error:
        print('ZERO_OUTPUT_GUARD_BLOCKED: {}'.format(error), file=sys.stderr)
        return 1
    finally:
        verifier.destroy_node()


def main():
    rclpy.init()
    try:
        print('RMW_IMPLEMENTATION={}'.format(_rmw_identifier()))
        return run_verification()
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
