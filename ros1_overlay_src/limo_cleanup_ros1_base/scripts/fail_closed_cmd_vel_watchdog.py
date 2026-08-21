#!/usr/bin/env python3
"""Relay bridged Twist commands to a private ROS1 driver topic safely."""

import time

from geometry_msgs.msg import Twist
import rospy

from limo_cleanup_ros1_base.watchdog_policy import (
    GenerationPublishGate,
    TwistValues,
    WatchdogLimits,
)


def _values_from_message(message):
    return TwistValues(
        linear_x=float(message.linear.x),
        linear_y=float(message.linear.y),
        linear_z=float(message.linear.z),
        angular_x=float(message.angular.x),
        angular_y=float(message.angular.y),
        angular_z=float(message.angular.z),
    )


def _message_from_values(values):
    message = Twist()
    message.linear.x = values.linear_x
    message.linear.y = values.linear_y
    message.linear.z = values.linear_z
    message.angular.x = values.angular_x
    message.angular.y = values.angular_y
    message.angular.z = values.angular_z
    return message


class FailClosedCmdVelWatchdog:
    """ROS1 node wrapper around the monotonic watchdog policy."""

    def __init__(self):
        input_topic = rospy.get_param(
            '~input_topic', '/cleanup/base/safe_cmd_vel')
        output_topic = rospy.get_param(
            '~output_topic', '/cleanup/base/driver_cmd_vel')
        publish_rate = float(rospy.get_param('~publish_rate', 20.0))
        if publish_rate <= 0.0:
            raise ValueError('publish_rate must be positive')
        limits = WatchdogLimits(
            lease_timeout=float(rospy.get_param('~lease_timeout', 0.25)),
            max_linear_speed=float(
                rospy.get_param('~max_linear_speed', 0.12)),
            max_angular_speed=float(
                rospy.get_param('~max_angular_speed', 0.35)),
            unsupported_axis_epsilon=float(
                rospy.get_param('~unsupported_axis_epsilon', 1e-6)),
        )
        allow_nonzero = bool(rospy.get_param('~allow_nonzero', False))
        self.gate = GenerationPublishGate(
            self._publish,
            allow_nonzero=allow_nonzero,
            limits=limits,
        )
        self.publisher = rospy.Publisher(
            output_topic, Twist, queue_size=1, latch=False)
        self.subscription = rospy.Subscriber(
            input_topic,
            Twist,
            self._on_command,
            queue_size=1,
            tcp_nodelay=True,
        )
        self.timer = rospy.Timer(
            rospy.Duration.from_sec(1.0 / publish_rate),
            self._on_timer,
        )
        rospy.on_shutdown(self._on_shutdown)
        self.gate.publish_initial_zero()
        rospy.loginfo(
            'ROS1 fail-closed cmd_vel watchdog ready; input=%s output=%s '
            'allow_nonzero=%s lease_timeout=%.3f',
            input_topic,
            output_topic,
            allow_nonzero,
            limits.lease_timeout,
        )

    def _publish(self, values):
        self.publisher.publish(_message_from_values(values))

    def _on_command(self, message):
        generation = self.gate.observe_generation()
        try:
            self.gate.handle_command(
                _values_from_message(message), time.monotonic(), generation)
        except ValueError as error:
            rospy.logerr_throttle(
                1.0, 'bridge command rejected and watchdog disabled: %s',
                error)

    def _on_timer(self, _event):
        generation = self.gate.observe_generation()
        self.gate.handle_timer(time.monotonic(), generation)

    def _on_shutdown(self):
        self.gate.shutdown()


def main():
    rospy.init_node('cleanup_ros1_safe_cmd_vel_watchdog')
    FailClosedCmdVelWatchdog()
    rospy.spin()


if __name__ == '__main__':
    main()
