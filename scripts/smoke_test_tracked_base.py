#!/usr/bin/env python3
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool

from limo_cleanup_base.tracked_base_controller import TrackedBaseController


TEST_OUTPUT_TOPIC = '/test/cleanup/tracked_cmd_vel'


class TrackedBaseProbe(Node):
    def __init__(self):
        super().__init__('cleanup_tracked_base_smoke_probe')
        self.request_publisher = self.create_publisher(
            Twist, '/cleanup/base/cmd_vel_request', 10)
        self.authorization_publisher = self.create_publisher(
            Bool, '/cleanup/base/motion_authorized', 10)
        self.safety_publisher = self.create_publisher(
            Bool, '/cleanup/base/safety_clear', 10)
        self.samples = []
        self.create_subscription(
            Twist, TEST_OUTPUT_TOPIC, self._on_output, 10)

    def _on_output(self, message):
        self.samples.append((
            time.monotonic(),
            float(message.linear.x),
            float(message.angular.z),
        ))

    def publish_inputs(
            self,
            authorized,
            safety_clear,
            linear_x,
            angular_z,
            linear_y=0.0):
        authorization = Bool()
        authorization.data = authorized
        self.authorization_publisher.publish(authorization)

        safety = Bool()
        safety.data = safety_clear
        self.safety_publisher.publish(safety)

        request = Twist()
        request.linear.x = linear_x
        request.linear.y = linear_y
        request.angular.z = angular_z
        self.request_publisher.publish(request)


def _publish_for(probe, duration, authorized, safety_clear, linear_x, angular_z):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        probe.publish_inputs(
            authorized, safety_clear, linear_x, angular_z)
        time.sleep(0.04)


def _latest(probe):
    if not probe.samples:
        raise RuntimeError('tracked controller published no test samples')
    return probe.samples[-1]


def _assert_latest_zero(probe, message):
    time.sleep(0.08)
    _, linear_x, angular_z = _latest(probe)
    assert abs(linear_x) < 1e-9, message
    assert abs(angular_z) < 1e-9, message


def main():
    rclpy.init(args=[
        '--ros-args',
        '-p', 'allow_base_motion:=true',
        '-p', 'output_topic:={}'.format(TEST_OUTPUT_TOPIC),
        '-p', 'publish_rate:=50.0',
        '-p', 'command_timeout:=0.20',
        '-p', 'heartbeat_timeout:=0.30',
    ])
    controller = TrackedBaseController()
    probe = TrackedBaseProbe()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(controller)
    executor.add_node(probe)

    import threading
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        time.sleep(0.20)
        assert not probe.get_publishers_info_by_topic('/cmd_vel'), (
            'smoke test must never create a real /cmd_vel publisher')

        start = len(probe.samples)
        _publish_for(probe, 0.35, False, False, 0.10, 0.20)
        blocked = probe.samples[start:]
        assert blocked
        assert all(abs(x) < 1e-9 and abs(z) < 1e-9 for _, x, z in blocked)
        print('PASS: missing authorization and safety kept output at zero')

        start = len(probe.samples)
        _publish_for(probe, 0.70, True, True, 0.50, 1.00)
        allowed = probe.samples[start:]
        moving = [(x, z) for _, x, z in allowed if abs(x) > 1e-4]
        assert moving
        assert max(abs(x) for x, _ in moving) <= 0.120001
        assert max(abs(z) for _, z in moving) <= 0.350001
        print('PASS: authorized tracked command was axis and speed limited')

        probe.publish_inputs(False, True, 0.10, 0.20)
        _assert_latest_zero(
            probe, 'authorization false must immediately stop output')
        print('PASS: authorization withdrawal cleared output and request')

        _publish_for(probe, 0.30, True, True, 0.10, 0.20)
        assert abs(_latest(probe)[1]) > 1e-4
        probe.publish_inputs(True, False, 0.10, 0.20)
        _assert_latest_zero(
            probe, 'safety false must immediately stop output')
        print('PASS: safety withdrawal cleared output and request')

        _publish_for(probe, 0.30, True, True, 0.10, 0.20)
        assert abs(_latest(probe)[1]) > 1e-4
        probe.publish_inputs(True, True, 0.10, 0.20, linear_y=0.01)
        _assert_latest_zero(
            probe, 'unsupported lateral axis must stop output')
        print('PASS: unsupported tracked axis failed closed')

        time.sleep(0.55)
        _, linear_x, angular_z = _latest(probe)
        assert abs(linear_x) < 1e-9
        assert abs(angular_z) < 1e-9
        print('PASS: stale command and heartbeats forced an immediate stop')
        assert not probe.get_publishers_info_by_topic('/cmd_vel'), (
            'smoke test created a real /cmd_vel publisher')
    finally:
        executor.shutdown()
        spin_thread.join(timeout=1.0)
        controller.stop()
        executor.remove_node(controller)
        executor.remove_node(probe)
        controller.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
