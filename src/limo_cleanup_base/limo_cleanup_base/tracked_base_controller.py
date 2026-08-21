import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool

from limo_cleanup_base.motion_policy import (
    MotionLimits,
    PermissionInputs,
    PlanarCommand,
    limited_command,
    permission_reason,
    reject_unsupported_axes,
    validate_planar_command,
    validate_limits,
)


class TrackedBaseController(Node):
    def __init__(self):
        super().__init__('cleanup_tracked_base_controller')
        self.declare_parameter('input_topic', '/cleanup/base/cmd_vel_request')
        self.declare_parameter(
            'output_topic', '/cleanup/base/safe_cmd_vel')
        self.declare_parameter(
            'authorization_topic', '/cleanup/base/motion_authorized')
        self.declare_parameter('safety_topic', '/cleanup/base/safety_clear')
        self.declare_parameter(
            'topology_ready_topic', '/cleanup/navigation/topology_ready')
        self.declare_parameter('allow_base_motion', False)
        self.declare_parameter('require_topology_ready', False)
        self.declare_parameter('publish_rate', 20.0)
        self.declare_parameter('command_timeout', 0.25)
        self.declare_parameter('heartbeat_timeout', 0.50)
        self.declare_parameter('topology_timeout', 0.25)
        self.declare_parameter('max_linear_speed', 0.12)
        self.declare_parameter('max_angular_speed', 0.35)
        self.declare_parameter('max_linear_acceleration', 0.20)
        self.declare_parameter('max_angular_acceleration', 0.60)

        self.allow_base_motion = bool(
            self.get_parameter('allow_base_motion').value)
        self.command_timeout = float(
            self.get_parameter('command_timeout').value)
        self.heartbeat_timeout = float(
            self.get_parameter('heartbeat_timeout').value)
        self.topology_timeout = float(
            self.get_parameter('topology_timeout').value)
        self.require_topology_ready = bool(
            self.get_parameter('require_topology_ready').value)
        publish_rate = float(self.get_parameter('publish_rate').value)
        if not math.isfinite(publish_rate) or publish_rate <= 0.0:
            raise ValueError('publish_rate must be finite and positive')
        for name, timeout in (
                ('command_timeout', self.command_timeout),
                ('heartbeat_timeout', self.heartbeat_timeout),
                ('topology_timeout', self.topology_timeout)):
            if not math.isfinite(timeout) or timeout <= 0.0:
                raise ValueError('{} must be finite and positive'.format(
                    name))
        self.control_period = 1.0 / publish_rate

        self.limits = MotionLimits(
            max_linear_speed=float(
                self.get_parameter('max_linear_speed').value),
            max_angular_speed=float(
                self.get_parameter('max_angular_speed').value),
            max_linear_acceleration=float(
                self.get_parameter('max_linear_acceleration').value),
            max_angular_acceleration=float(
                self.get_parameter('max_angular_acceleration').value),
        )
        validate_limits(self.limits)

        self.request = PlanarCommand()
        self.output = PlanarCommand()
        self.request_time = -1.0
        self.authorization = False
        self.authorization_time = -1.0
        self.safety_clear = False
        self.safety_time = -1.0
        self.topology_ready = False
        self.topology_time = -1.0
        self.last_tick = self._now()
        self.last_reason = None

        input_topic = str(self.get_parameter('input_topic').value)
        output_topic = str(self.get_parameter('output_topic').value)
        authorization_topic = str(
            self.get_parameter('authorization_topic').value)
        safety_topic = str(self.get_parameter('safety_topic').value)
        topology_ready_topic = str(
            self.get_parameter('topology_ready_topic').value)
        self.publisher = self.create_publisher(Twist, output_topic, 1)
        self.request_subscription = self.create_subscription(
            Twist, input_topic, self._on_request, 1)
        self.authorization_subscription = self.create_subscription(
            Bool, authorization_topic, self._on_authorization, 1)
        self.safety_subscription = self.create_subscription(
            Bool, safety_topic, self._on_safety, 1)
        self.topology_subscription = self.create_subscription(
            Bool, topology_ready_topic, self._on_topology_ready, 1)
        self.timer = self.create_timer(self.control_period, self._on_timer)

        self.get_logger().info(
            'tracked skid-steer gateway ready; allow_base_motion={}; '
            'input={}; output={}'.format(
                self.allow_base_motion, input_topic, output_topic))

    def _now(self) -> float:
        return time.monotonic()

    def _force_stop(self, clear_request=True) -> None:
        if clear_request:
            self.request = PlanarCommand()
            self.request_time = -1.0
        self.output = PlanarCommand()
        self.last_tick = self._now()
        self._publish(self.output)

    def _on_request(self, message: Twist) -> None:
        try:
            reject_unsupported_axes(
                message.linear.y,
                message.linear.z,
                message.angular.x,
                message.angular.y,
                self.limits.unsupported_axis_epsilon,
            )
            requested = PlanarCommand(
                linear_x=float(message.linear.x),
                angular_z=float(message.angular.z),
            )
            validate_planar_command(requested)
        except ValueError as error:
            self._force_stop()
            self.get_logger().error(str(error))
            return
        self.request = requested
        self.request_time = self._now()

    def _on_authorization(self, message: Bool) -> None:
        self.authorization = bool(message.data)
        self.authorization_time = self._now()
        if not self.authorization:
            self._force_stop()

    def _on_safety(self, message: Bool) -> None:
        self.safety_clear = bool(message.data)
        self.safety_time = self._now()
        if not self.safety_clear:
            self._force_stop()

    def _on_topology_ready(self, message: Bool) -> None:
        self.topology_ready = bool(message.data)
        self.topology_time = self._now()
        if self.require_topology_ready and not self.topology_ready:
            self._force_stop()

    def _publish(self, command: PlanarCommand) -> None:
        message = Twist()
        message.linear.x = command.linear_x
        message.angular.z = command.angular_z
        self.publisher.publish(message)

    def _on_timer(self) -> None:
        now = self._now()
        reason = permission_reason(PermissionInputs(
            allow_base_motion=self.allow_base_motion,
            now=now,
            request_time=self.request_time,
            authorization=self.authorization,
            authorization_time=self.authorization_time,
            safety_clear=self.safety_clear,
            safety_time=self.safety_time,
            require_topology_ready=self.require_topology_ready,
            topology_ready=self.topology_ready,
            topology_time=self.topology_time,
            command_timeout=self.command_timeout,
            heartbeat_timeout=self.heartbeat_timeout,
            topology_timeout=self.topology_timeout,
        ))
        if reason == 'allowed':
            dt = max(
                1e-6,
                min(now - self.last_tick, self.control_period),
            )
            self.output = limited_command(
                self.request, self.output, dt, self.limits)
        else:
            self.output = PlanarCommand()
        self.last_tick = now
        self._publish(self.output)

        if reason != self.last_reason:
            if reason == 'allowed':
                self.get_logger().info('base motion gate allowed')
            else:
                self.get_logger().warning(
                    'base motion gate stopped: {}'.format(reason))
            self.last_reason = reason

    def stop(self) -> None:
        self._force_stop()


def main(args=None):
    rclpy.init(args=args)
    node = TrackedBaseController()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
