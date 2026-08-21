#!/usr/bin/env python3
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool


TEST_PREFIX = '/test/legacy_ros2_offline/tracked_zero_launch'
TEST_REQUEST_TOPIC = TEST_PREFIX + '/request'
TEST_AUTHORIZATION_TOPIC = TEST_PREFIX + '/authorized'
TEST_SAFETY_TOPIC = TEST_PREFIX + '/safety'
TEST_OUTPUT_TOPIC = '/test/cleanup/tracked_zero_output'


class ZeroLaunchProbe(Node):
    def __init__(self):
        super().__init__('cleanup_tracked_zero_launch_probe')
        self.samples = []
        self.request_publisher = self.create_publisher(
            Twist, TEST_REQUEST_TOPIC, 10)
        self.authorization_publisher = self.create_publisher(
            Bool, TEST_AUTHORIZATION_TOPIC, 10)
        self.safety_publisher = self.create_publisher(
            Bool, TEST_SAFETY_TOPIC, 10)
        self.output_subscription = self.create_subscription(
            Twist, TEST_OUTPUT_TOPIC, self._on_output, 10)

    def _on_output(self, message):
        self.samples.append((
            float(message.linear.x),
            float(message.angular.z),
        ))

    def publish_nonzero_authorized_request(self):
        authorization = Bool()
        authorization.data = True
        self.authorization_publisher.publish(authorization)

        safety = Bool()
        safety.data = True
        self.safety_publisher.publish(safety)

        request = Twist()
        request.linear.x = 0.10
        request.angular.z = 0.20
        self.request_publisher.publish(request)


def main():
    rclpy.init()
    probe = ZeroLaunchProbe()
    try:
        discovery_deadline = time.monotonic() + 5.0
        while time.monotonic() < discovery_deadline:
            rclpy.spin_once(probe, timeout_sec=0.05)
            if probe.samples:
                break
        else:
            raise AssertionError(
                'zero-output launch sample was not received')

        sample_deadline = time.monotonic() + 3.0
        while time.monotonic() < sample_deadline:
            probe.publish_nonzero_authorized_request()
            rclpy.spin_once(probe, timeout_sec=0.04)

        assert len(probe.samples) >= 5, (
            'zero-output launch published only {} samples'.format(
                len(probe.samples)))
        assert all(
            abs(linear_x) < 1e-9 and abs(angular_z) < 1e-9
            for linear_x, angular_z in probe.samples
        ), 'hard-disabled launch emitted a nonzero command'
        assert not probe.get_publishers_info_by_topic('/cmd_vel'), (
            'isolated zero-output smoke created a real /cmd_vel publisher')
        print(
            'LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK: hard-disabled '
            'zero-output launch rejected test-only nonzero requests')
        print(
            'LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK: isolated launch created '
            'no public command publisher')
    finally:
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
