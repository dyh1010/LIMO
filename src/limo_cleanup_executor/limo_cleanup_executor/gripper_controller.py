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
            ('confirmed_gripper_model', 'UNRESOLVED_DO_NOT_CONNECT'),
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

        self.backend_error = (
            'legacy pymycobot AG hardware backend is forbidden: the final '
            'tool model, actuator, protocol, transport, limits, feedback and '
            'calibration are unresolved; use dry_run only')
        self.get_logger().error(self.backend_error)

    def goal_callback(self, goal_request):
        if self.backend is None:
            self.get_logger().warning(
                'Rejecting gripper goal because no released backend exists: '
                + self.backend_error)
            return GoalResponse.REJECT
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
        self.get_logger().info(
            'Accepting gripper command cancellation; STOP will be requested')
        return CancelResponse.ACCEPT

    def _stop_backend(self, reason: str) -> str:
        if self.backend is None:
            return 'STOP unavailable because no backend is configured'
        stopper = getattr(self.backend, 'stop', None)
        if stopper is None:
            return 'STOP unavailable because backend has no stop method'
        try:
            stopper()
            return f'STOP requested: {reason}'
        except Exception as error:  # noqa: BLE001
            detail = f'STOP failed after {reason}: {error}'
            self.get_logger().error(detail)
            return detail

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
                stop_detail = self._stop_backend(
                    'unverified completion is forbidden')
                goal_handle.abort()
                result.success = False
                result.final_state = 'verification_required'
                result.detail = (
                    'Command was sent but success cannot be declared without '
                    'fresh feedback; ' + stop_detail)
                return result

            deadline = time.monotonic() + self.command_timeout
            while time.monotonic() < deadline:
                if goal_handle.is_cancel_requested:
                    stop_detail = self._stop_backend('action cancellation')
                    goal_handle.canceled()
                    result.success = False
                    result.final_state = 'cancelled'
                    result.detail = (
                        'Cancelled; no automatic recovery motion was sent; '
                        + stop_detail)
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

            stop_detail = self._stop_backend('verification timeout')
            goal_handle.abort()
            result.success = False
            result.final_state = 'verification_timeout'
            result.detail = (
                'Position was not verified before timeout; '
                'no automatic retry was sent; ' + stop_detail)
            return result
        except (GripperCommandError, GripperBackendError) as error:
            stop_detail = self._stop_backend('command or feedback failure')
            goal_handle.abort()
            result.success = False
            result.final_state = 'failed'
            result.detail = f'{error}; {stop_detail}'
            self.get_logger().error(result.detail)
            return result
        except Exception as error:  # noqa: BLE001
            stop_detail = self._stop_backend('unexpected exception')
            goal_handle.abort()
            result.success = False
            result.final_state = 'failed'
            result.detail = (
                f'Unexpected gripper error: {error}; {stop_detail}')
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
        if self.backend is not None:
            close = getattr(self.backend, 'close', None)
            if close is not None:
                close()
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
