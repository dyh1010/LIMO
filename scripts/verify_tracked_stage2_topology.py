#!/usr/bin/env python3
import math
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


SAFE_COMMAND_TOPIC = '/cleanup/base/safe_cmd_vel'
EXPECTED_GATEWAY = '/cleanup_tracked_base_zero_output'
EXPECTED_DRIVER = '/limo_base_stage2'
PUBLIC_COMMAND_TOPICS = (
    '/cmd_vel',
    '/cmd_vel_nav',
    '/cmd_vel_teleop',
    '/limo/vel_cmd',
)
STATE_TOPICS = ('/odom', '/imu', '/limo_status')
ZERO_EPSILON = 1e-9
MINIMUM_SAMPLES = 10


def _endpoint_name(endpoint):
    namespace = str(endpoint.node_namespace or '/').rstrip('/')
    if not namespace:
        namespace = '/'
    if namespace == '/':
        return '/{}'.format(endpoint.node_name)
    return '{}/{}'.format(namespace, endpoint.node_name)


def _endpoint_names(endpoints):
    return {_endpoint_name(endpoint) for endpoint in endpoints}


def _twist_values(message):
    return (
        float(message.linear.x),
        float(message.linear.y),
        float(message.linear.z),
        float(message.angular.x),
        float(message.angular.y),
        float(message.angular.z),
    )


class Stage2TopologyVerifier(Node):
    def __init__(self):
        super().__init__('cleanup_tracked_stage2_topology_verifier')
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
        publisher_names = _endpoint_names(publishers)
        subscriber_names = _endpoint_names(subscribers)
        if len(publishers) != 1 or publisher_names != {EXPECTED_GATEWAY}:
            raise RuntimeError(
                '{} has {} publisher endpoints from {}, expected exactly '
                'one from {}'.format(
                    SAFE_COMMAND_TOPIC,
                    len(publishers),
                    sorted(publisher_names),
                    EXPECTED_GATEWAY))
        if (len(subscribers) != 2 or subscriber_names != {
                EXPECTED_DRIVER, self.get_fully_qualified_name()}):
            raise RuntimeError(
                '{} has {} subscriber endpoints from {}, expected exactly '
                'driver plus verifier'.format(
                    SAFE_COMMAND_TOPIC,
                    len(subscribers),
                    sorted(subscriber_names)))

        for topic in PUBLIC_COMMAND_TOPICS:
            topic_publishers = self.get_publishers_info_by_topic(topic)
            topic_subscribers = self.get_subscriptions_info_by_topic(topic)
            if topic_publishers or topic_subscribers:
                raise RuntimeError(
                    '{} must have no endpoints; publishers={}, '
                    'subscribers={}'.format(
                        topic,
                        sorted(_endpoint_names(topic_publishers)),
                        sorted(_endpoint_names(topic_subscribers))))

        for topic in STATE_TOPICS:
            state_publisher_endpoints = self.get_publishers_info_by_topic(topic)
            state_publishers = _endpoint_names(state_publisher_endpoints)
            if (len(state_publisher_endpoints) != 1
                    or state_publishers != {EXPECTED_DRIVER}):
                raise RuntimeError(
                    '{} has {} publisher endpoints from {}, expected exactly '
                    'one from {}'.format(
                        topic,
                        len(state_publisher_endpoints),
                        sorted(state_publishers),
                        EXPECTED_DRIVER))


def _spin_until(node, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if predicate():
            return True
    return False


def run_verification():
    verifier = Stage2TopologyVerifier()
    try:
        ready = _spin_until(
            verifier,
            lambda: (
                bool(verifier.get_publishers_info_by_topic(
                    SAFE_COMMAND_TOPIC))
                and bool(verifier.get_subscriptions_info_by_topic(
                    SAFE_COMMAND_TOPIC))),
            8.0,
        )
        if not ready:
            raise RuntimeError('stage-2 safe command endpoints not discovered')
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
                '{} safe command received: {}'.format(kind, values))
        if not enough_samples:
            raise RuntimeError(
                'received only {} zero samples; need at least {}'.format(
                    verifier.sample_count, MINIMUM_SAMPLES))

        verifier.verify_topology()
        print('STAGE2_TOPOLOGY_PASS')
        print(
            '{} has one gateway publisher, one driver subscriber, and '
            '{} finite all-axis zero samples.'.format(
                SAFE_COMMAND_TOPIC, verifier.sample_count))
        print('Public command topics have no publishers or subscribers.')
        print('Vendor state topics are owned only by {}.'.format(
            EXPECTED_DRIVER))
        return 0
    except RuntimeError as error:
        print('STAGE2_TOPOLOGY_BLOCKED: {}'.format(error), file=sys.stderr)
        return 1
    finally:
        verifier.destroy_node()


def main():
    rclpy.init()
    try:
        return run_verification()
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
