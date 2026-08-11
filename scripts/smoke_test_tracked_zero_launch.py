#!/usr/bin/env python3
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool


TEST_OUTPUT_TOPIC = '/test/cleanup/tracked_zero_output'


class ZeroLaunchProbe(Node):
    def __init__(self):
        super().__init__('cleanup_tracked_zero_launch_probe')
        self.samples = []
        self.request_publisher = self.create_publisher(
            Twist, '/cleanup/base/cmd_vel_request', 10)
        self.authorization_publisher = self.create_publisher(
            Bool, '/cleanup/base/motion_authorized', 10)
        self.safety_publisher = self.create_publisher(
            Bool, '/cleanup/base/safety_clear', 10)
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
            'PASS: hard-disabled zero-output launch rejected authorized '
            'nonzero requests')
        print('PASS: isolated launch created no real /cmd_vel publisher')
    finally:
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
