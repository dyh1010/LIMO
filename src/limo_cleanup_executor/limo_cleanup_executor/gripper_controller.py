import math
import threading
import time

import rclpy
from limo_cleanup_interfaces.action import ControlGripper
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .gripper_backends import (
    DryRunGripperBackend,
    GripperBackendError,
    PymycobotGripperBackend,
)
from .gripper_core import (
    GripperCommandError,
    position_reached,
    resolve_gripper_command,
)


class GripperController(Node):
    def __init__(self) -> None:
        super().__init__('cleanup_gripper_controller')
        self._declare_parameters()
        self.callback_group = ReentrantCallbackGroup()
        self.busy_lock = threading.Lock()
        self.busy = False
        self.backend = None
        self.backend_error = ''
        self._configure_backend()

        self.action_server = ActionServer(
            self,
            ControlGripper,
            '/cleanup/gripper',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )
        self.get_logger().info(
            f'Gripper controller ready; backend={self.backend_name}; '
            f'allow_hardware_motion={self.allow_hardware_motion}; '
            f'model={self.confirmed_gripper_model}')

    def _declare_parameters(self) -> None:
        parameters = (
            ('backend', 'dry_run'),
            ('allow_hardware_motion', False),
            ('confirmed_gripper_model', 'mycobot_gripper_ag'),
            ('serial_port', '/dev/ttyACM0'),
            ('baud', 115200),
            ('gripper_type', 1),
            ('closed_value', 0),
            ('open_value', 100),
            ('default_speed', 0.25),
            ('position_tolerance', 0.08),
            ('command_timeout', 3.0),
            ('poll_period', 0.10),
            ('dry_run_initial_position', 1.0),
        )
        for name, value in parameters:
            self.declare_parameter(name, value)

        self.backend_name = self._string_parameter('backend')
        self.allow_hardware_motion = self._bool_parameter(
            'allow_hardware_motion')
        self.confirmed_gripper_model = self._string_parameter(
            'confirmed_gripper_model')
        self.serial_port = self._string_parameter('serial_port')
        self.baud = self._integer_parameter('baud')
        self.gripper_type = self._integer_parameter('gripper_type')
        self.closed_value = self._integer_parameter('closed_value')
        self.open_value = self._integer_parameter('open_value')
        self.default_speed = self._double_parameter('default_speed')
        self.position_tolerance = self._double_parameter(
            'position_tolerance')
        self.command_timeout = self._double_parameter('command_timeout')
        self.poll_period = self._double_parameter('poll_period')
        self.dry_run_initial_position = self._double_parameter(
            'dry_run_initial_position')

    def _string_parameter(self, name: str) -> str:
        return self.get_parameter(name).value

    def _bool_parameter(self, name: str) -> bool:
        return bool(self.get_parameter(name).value)

    def _integer_parameter(self, name: str) -> int:
        return int(self.get_parameter(name).value)

    def _double_parameter(self, name: str) -> float:
        return float(self.get_parameter(name).value)

    def _configure_backend(self) -> None:
        if self.backend_name == 'dry_run':
            self.backend = DryRunGripperBackend(
                self.dry_run_initial_position)
            return

        if self.backend_name != 'pymycobot':
            self.backend_error = (
                f'unsupported backend: {self.backend_name}')
            self.get_logger().error(self.backend_error)
            return

        if not self.allow_hardware_motion:
            self.backend_error = (
                'hardware motion is disabled; set '
                'allow_hardware_motion:=true only after physical acceptance')
            self.get_logger().warning(self.backend_error)
            return

        if self.confirmed_gripper_model != 'mycobot_gripper_ag':
            self.backend_error = (
                'confirmed_gripper_model must be mycobot_gripper_ag')
            self.get_logger().error(self.backend_error)
            return

        try:
            self.backend = PymycobotGripperBackend(
                port=self.serial_port,
                baud=self.baud,
                gripper_type=self.gripper_type,
                closed_value=self.closed_value,
                open_value=self.open_value,
            )
        except GripperBackendError as error:
            self.backend_error = str(error)
            self.get_logger().error(self.backend_error)

    def goal_callback(self, goal_request):
        try:
            resolve_gripper_command(
                goal_request.command,
                goal_request.position,
                goal_request.speed,
                goal_request.verify,
                self.default_speed,
            )
        except GripperCommandError as error:
            self.get_logger().warning(f'Rejecting invalid goal: {error}')
            return GoalResponse.REJECT

        with self.busy_lock:
            if self.busy:
                self.get_logger().warning(
                    'Rejecting goal because the gripper is busy')
                return GoalResponse.REJECT
            self.busy = True
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info('Accepting gripper command cancellation')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        result = ControlGripper.Result()
        result.measured_position = math.nan
        try:
            command = resolve_gripper_command(
                goal_handle.request.command,
                goal_handle.request.position,
                goal_handle.request.speed,
                goal_handle.request.verify,
                self.default_speed,
            )
            result.commanded_position = command.position

            if self.backend is None:
                goal_handle.abort()
                result.success = False
                result.final_state = (
                    'motion_not_authorized'
                    if (
                        self.backend_name == 'pymycobot'
                        and not self.allow_hardware_motion)
                    else 'backend_unavailable')
                result.detail = self.backend_error
                return result

            self._publish_feedback(
                goal_handle,
                'commanding',
                command.position,
                math.nan,
                'Sending one bounded gripper position command',
            )
            self.backend.command_position(
                command.position, command.speed)

            if not command.verify:
                goal_handle.succeed()
                result.success = True
                result.final_state = 'commanded'
                result.detail = (
                    'Command accepted without position verification')
                return result

            deadline = time.monotonic() + self.command_timeout
            while time.monotonic() < deadline:
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.final_state = 'cancelled'
                    result.detail = (
                        'Cancelled; no automatic recovery motion was sent')
                    return result

                measured = self.backend.read_position()
                result.measured_position = measured
                self._publish_feedback(
                    goal_handle,
                    'verifying',
                    command.position,
                    measured,
                    'Waiting for the measured gripper position',
                )
                if position_reached(
                        measured,
                        command.position,
                        self.position_tolerance):
                    goal_handle.succeed()
                    result.success = True
                    result.final_state = 'succeeded'
                    result.detail = 'Commanded position was verified'
                    return result
                time.sleep(self.poll_period)

            goal_handle.abort()
            result.success = False
            result.final_state = 'verification_timeout'
            result.detail = (
                'Position was not verified before timeout; '
                'no automatic retry was sent')
            return result
        except (GripperCommandError, GripperBackendError) as error:
            goal_handle.abort()
            result.success = False
            result.final_state = 'failed'
            result.detail = str(error)
            self.get_logger().error(result.detail)
            return result
        except Exception as error:  # noqa: BLE001
            goal_handle.abort()
            result.success = False
            result.final_state = 'failed'
            result.detail = f'Unexpected gripper error: {error}'
            self.get_logger().error(result.detail)
            return result
        finally:
            with self.busy_lock:
                self.busy = False

    def _publish_feedback(
            self,
            goal_handle,
            state: str,
            commanded: float,
            measured: float,
            detail: str) -> None:
        feedback = ControlGripper.Feedback()
        feedback.state = state
        feedback.commanded_position = commanded
        feedback.measured_position = measured
        feedback.detail = detail
        goal_handle.publish_feedback(feedback)

    def destroy_node(self):
        self.action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GripperController()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
