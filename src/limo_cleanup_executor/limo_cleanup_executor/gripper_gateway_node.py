"""ROS 2 dry-run gateway for the reviewed gripper contract.

The released node is deliberately simulation-only.  It constructs an
in-memory backend locally and has no vendor, serial, USB or device path.
"""

import math
import threading
import time

import rclpy
from limo_cleanup_interfaces.action import ExecuteGripperMotion
from limo_cleanup_interfaces.msg import GripperState
from limo_cleanup_interfaces.srv import (
    AcknowledgeGripperFault,
    StopGripper,
)
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .gripper_gateway_core import (
    GripperGatewayCore,
    GripperGatewayError,
    GripperGatewayPolicy,
    GripperGatewayState,
    GripperMotionRejected,
)


class DryRunGatewayGripperBackend:
    """Deterministic in-memory backend with reviewed fake identity."""

    def __init__(
            self,
            tool_model,
            tool_revision,
            controller_identity,
            transport_identity,
            protocol_identity,
            motion_duration_s=0.20,
            clock=None):
        self._clock = clock or time.monotonic
        self._duration = float(motion_duration_s)
        if not math.isfinite(self._duration) or self._duration < 0.0:
            raise ValueError(
                'dry_run_motion_duration_s must be finite and non-negative')
        self._identity = {
            'tool_model': tool_model,
            'tool_revision': tool_revision,
            'controller_identity': controller_identity,
            'transport_identity': transport_identity,
            'protocol_identity': protocol_identity,
        }
        if any(
                type(value) is not str
                or not value
                or value != value.strip()
                for value in self._identity.values()):
            raise ValueError('dry-run gripper identities must be exact strings')
        self._boot_id = 'DRY_RUN_BOOT_1'
        self._position = 1.0
        self._target = None
        self._active_command_id = ''
        self._moving = False
        self._complete_at = None
        self._sequence = 0
        self._closed = False

    # Static data, not a capability method: construction must not execute an
    # adapter merely to discover whether it is safe to use.
    SAFETY_CAPABILITIES = {
            'execution_mode': 'PURE_FAKE',
            'bounded_calls_enforced': True,
            'native_deadline_enforced': True,
            'method_deadlines_s': {
                'read_state': 1.0,
                'command_position': 1.0,
                'stop': 1.0,
                'close': 1.0,
            },
            'independent_stop_channel': True,
            'native_cancel_enforced': True,
            'independent_stop_lock_domain': True,
            'stop_not_queued_behind_commands': True,
            'release_binding': None,
            'persistent_latch_binding': None,
    }

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('dry-run gripper backend is closed')

    def _update(self):
        self._ensure_open()
        now = self._clock()
        if (
                self._moving
                and self._complete_at is not None
                and now >= self._complete_at):
            self._position = self._target
            self._target = None
            self._moving = False
            self._complete_at = None
        return now

    def read_state(self):
        now = self._update()
        self._sequence += 1
        return {
            **self._identity,
            'controller_boot_id': self._boot_id,
            'sample_timestamp': now,
            'sequence': self._sequence,
            'command_id': self._active_command_id,
            'connected': True,
            'valid': True,
            'enabled': True,
            'moving': self._moving,
            'position': self._position,
            'fault_code': 0,
        }

    def command_position(self, position, speed, command_id):
        self._ensure_open()
        if not (
                isinstance(position, (int, float))
                and not isinstance(position, bool)
                and math.isfinite(float(position))
                and 0.0 <= float(position) <= 1.0):
            raise ValueError('position must be finite and normalized')
        if not (
                isinstance(speed, (int, float))
                and not isinstance(speed, bool)
                and math.isfinite(float(speed))
                and 0.0 < float(speed) <= 1.0):
            raise ValueError('speed must be finite in (0, 1]')
        if type(command_id) is not str or not command_id.strip():
            raise ValueError('command_id must be a non-empty exact string')
        self._active_command_id = command_id
        self._target = float(position)
        self._moving = True
        self._complete_at = self._clock() + self._duration

    def stop(self):
        self._ensure_open()
        self._target = None
        self._moving = False
        self._complete_at = None

    def close(self):
        self._closed = True
        self._target = None
        self._moving = False
        self._complete_at = None


def validate_fake_authorization(authorization_id, purpose, session_id):
    """Accept a purpose/session-bound token only in the dry-run node."""
    if type(authorization_id) is not str or purpose not in ('motion', 'ack'):
        return False
    prefix = '{}:{}:'.format(session_id, purpose)
    return (
        authorization_id.startswith(prefix)
        and len(authorization_id) > len(prefix)
    )


class GripperGatewayNode(Node):
    """Expose Action/STOP/ACK around the pure in-memory gateway core."""

    def __init__(
            self,
            authorization_validator=None,
            parameter_overrides=None):
        super().__init__(
            'cleanup_gripper_gateway',
            parameter_overrides=parameter_overrides,
        )
        self._declare_parameters()
        if self.backend_name != 'dry_run':
            raise RuntimeError(
                'only backend=dry_run is released; gripper hardware is blocked')
        identity = (
            self.reviewed_tool_model,
            self.reviewed_tool_revision,
            self.reviewed_controller_identity,
            self.reviewed_transport_identity,
            self.reviewed_protocol_identity,
        )
        if any(not value.startswith('DRY_RUN_') for value in identity):
            raise RuntimeError(
                'dry-run identity fields must use explicit DRY_RUN_ sentinels')
        self._backend = DryRunGatewayGripperBackend(
            *identity,
            motion_duration_s=self.dry_run_motion_duration_s,
        )
        policy = GripperGatewayPolicy(
            permit_motion=self.allow_simulated_motion,
            reviewed_tool_model=identity[0],
            reviewed_tool_revision=identity[1],
            reviewed_controller_identity=identity[2],
            reviewed_transport_identity=identity[3],
            reviewed_protocol_identity=identity[4],
            state_max_age_s=self.state_max_age_s,
            command_timeout_s=self.command_timeout_s,
            stop_timeout_s=self.stop_timeout_s,
            stable_samples_required=self.stable_samples_required,
            position_tolerance=self.position_tolerance,
            stationary_position_tolerance=(
                self.stationary_position_tolerance),
            stationary_dwell_s=self.stationary_dwell_s,
        )
        self._core = GripperGatewayCore(
            self._backend,
            policy,
            authorization_validator=(
                authorization_validator or validate_fake_authorization),
        )
        self._lock = threading.RLock()
        self._busy = False
        self._sample_sequence = 0
        self._callback_group = ReentrantCallbackGroup()
        self._state_publisher = self.create_publisher(
            GripperState, '/cleanup/gripper/state', 10)
        self._action_server = ActionServer(
            self,
            ExecuteGripperMotion,
            '/cleanup/gripper/execute',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self._callback_group,
        )
        self._stop_service = self.create_service(
            StopGripper,
            '/cleanup/gripper/stop',
            self.stop_callback,
            callback_group=self._callback_group,
        )
        self._ack_service = self.create_service(
            AcknowledgeGripperFault,
            '/cleanup/gripper/acknowledge_fault',
            self.acknowledge_callback,
            callback_group=self._callback_group,
        )
        self._poll_timer = self.create_timer(
            1.0 / self.poll_hz,
            self.poll_once,
            callback_group=self._callback_group,
        )
        self.poll_once()

    def _declare_parameters(self):
        defaults = (
            ('backend', 'dry_run'),
            ('allow_simulated_motion', False),
            ('poll_hz', 20.0),
            ('feedback_hz', 20.0),
            ('dry_run_motion_duration_s', 0.20),
            ('state_max_age_s', 0.25),
            ('command_timeout_s', 5.0),
            ('stop_timeout_s', 2.0),
            ('stable_samples_required', 3),
            ('position_tolerance', 0.02),
            ('stationary_position_tolerance', 0.005),
            ('stationary_dwell_s', 0.20),
            ('reviewed_tool_model', 'DRY_RUN_TOOL'),
            ('reviewed_tool_revision', 'DRY_RUN_REVISION'),
            ('reviewed_controller_identity', 'DRY_RUN_CONTROLLER'),
            ('reviewed_transport_identity', 'DRY_RUN_TRANSPORT'),
            ('reviewed_protocol_identity', 'DRY_RUN_PROTOCOL'),
        )
        for name, value in defaults:
            self.declare_parameter(name, value)
        self.backend_name = str(self.get_parameter('backend').value)
        self.allow_simulated_motion = bool(
            self.get_parameter('allow_simulated_motion').value)
        self.poll_hz = float(self.get_parameter('poll_hz').value)
        self.feedback_hz = float(self.get_parameter('feedback_hz').value)
        self.dry_run_motion_duration_s = float(
            self.get_parameter('dry_run_motion_duration_s').value)
        self.state_max_age_s = float(
            self.get_parameter('state_max_age_s').value)
        self.command_timeout_s = float(
            self.get_parameter('command_timeout_s').value)
        self.stop_timeout_s = float(
            self.get_parameter('stop_timeout_s').value)
        self.stable_samples_required = int(
            self.get_parameter('stable_samples_required').value)
        self.position_tolerance = float(
            self.get_parameter('position_tolerance').value)
        self.stationary_position_tolerance = float(
            self.get_parameter('stationary_position_tolerance').value)
        self.stationary_dwell_s = float(
            self.get_parameter('stationary_dwell_s').value)
        self.reviewed_tool_model = str(
            self.get_parameter('reviewed_tool_model').value)
        self.reviewed_tool_revision = str(
            self.get_parameter('reviewed_tool_revision').value)
        self.reviewed_controller_identity = str(
            self.get_parameter('reviewed_controller_identity').value)
        self.reviewed_transport_identity = str(
            self.get_parameter('reviewed_transport_identity').value)
        self.reviewed_protocol_identity = str(
            self.get_parameter('reviewed_protocol_identity').value)
        if not 1.0 <= self.poll_hz <= 50.0:
            raise RuntimeError('poll_hz must be in 1..50')
        if not 1.0 <= self.feedback_hz <= 50.0:
            raise RuntimeError('feedback_hz must be in 1..50')

    def poll_once(self):
        try:
            self._core.refresh()
        except GripperGatewayError as error:
            self.get_logger().error(str(error))
        with self._lock:
            self._sample_sequence += 1
        self._publish_state()

    def _publish_state(self):
        message = GripperState()
        message.stamp = self.get_clock().now().to_msg()
        message.gateway_state = (
            GripperState.STATE_PHYSICAL_ESTOP_REQUIRED
            if self._core.physical_stop_required
            else self._core.state.value
        )
        message.session_id = self._core.session_id
        message.sample_sequence = self._sample_sequence
        message.sample_stamp = message.stamp
        snapshot = self._core.snapshot
        message.valid = self._core.snapshot_is_valid()
        message.tool_model = self.reviewed_tool_model
        message.tool_revision = self.reviewed_tool_revision
        message.controller_identity = self.reviewed_controller_identity
        message.transport_identity = self.reviewed_transport_identity
        message.protocol_identity = self.reviewed_protocol_identity
        message.controller_boot_id = (
            snapshot.controller_boot_id if snapshot is not None else '')
        message.connected = int(snapshot.connected) if snapshot else -1
        message.enabled = int(snapshot.enabled) if snapshot else -1
        message.moving = int(snapshot.moving) if snapshot else -1
        message.opened_limit = -1
        message.closed_limit = -1
        message.normalized_position_valid = message.valid
        message.normalized_position = (
            snapshot.position if snapshot is not None else math.nan)
        message.jaw_opening_valid = False
        message.jaw_opening_m = math.nan
        message.supply_voltage_valid = False
        message.supply_voltage_v = math.nan
        message.motor_current_valid = False
        message.motor_current_a = math.nan
        message.grip_force_valid = False
        message.grip_force_n = math.nan
        message.temperature_valid = False
        message.temperature_c = math.nan
        message.active_command_id = (
            self._core.active_command.command_id
            if self._core.active_command is not None else '')
        message.fault_code = snapshot.fault_code if snapshot else -1
        message.fault_reason = self._core.fault_reason
        self._state_publisher.publish(message)

    def _session_matches(self, expected_session_id):
        return (
            type(expected_session_id) is str
            and expected_session_id == self._core.session_id
        )

    def _public_gateway_state(self):
        return (
            GripperState.STATE_PHYSICAL_ESTOP_REQUIRED
            if self._core.physical_stop_required
            else self._core.state.value
        )

    def goal_callback(self, goal_request):
        with self._lock:
            if self._busy:
                return GoalResponse.REJECT
            if not self._session_matches(goal_request.expected_session_id):
                return GoalResponse.REJECT
            if not goal_request.authorization_id:
                return GoalResponse.REJECT
            if goal_request.expected_tool_revision != (
                    self.reviewed_tool_revision):
                return GoalResponse.REJECT
            if goal_request.target_kind != (
                    ExecuteGripperMotion.Goal.TARGET_NORMALIZED_POSITION):
                return GoalResponse.REJECT
            self._busy = True
            return GoalResponse.ACCEPT

    def cancel_callback(self, unused_goal_handle):
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        request = goal_handle.request
        result = ExecuteGripperMotion.Result()
        command = None
        try:
            command = self._core.command_position(
                float(request.normalized_position),
                float(request.speed_normalized),
                request.authorization_id,
                request.expected_session_id,
                request.expected_tool_revision,
            )
            period = 1.0 / self.feedback_hz
            cancellation_pending = False
            while rclpy.ok():
                if (
                        goal_handle.is_cancel_requested
                        and not cancellation_pending):
                    self._core.request_stop(
                        'action cancellation', self._core.session_id)
                    cancellation_pending = True
                self._core.refresh()
                self._publish_feedback(goal_handle, command.command_id)
                command_result = self._core.last_result
                result_matches = (
                    command_result is not None
                    and command_result.command_id == command.command_id
                )
                unsafe_terminal = (
                    self._core.physical_stop_required
                    or self._core.state == GripperGatewayState.CLOSED
                    or (
                        self._core.state == GripperGatewayState.FAULT_LATCHED
                        and (
                            not result_matches
                            or command_result.success
                        )
                    )
                )
                if unsafe_terminal:
                    goal_handle.abort()
                    result.success = False
                    result.command_id = command.command_id
                    result.final_state = self._public_gateway_state()
                    result.detail = (
                        self._core.fault_reason
                        or '{} invalidated the command result'.format(
                            self._core.state.value))
                    result.measured_normalized_position_valid = False
                    result.measured_normalized_position = math.nan
                    result.measured_jaw_opening_valid = False
                    result.measured_jaw_opening_m = math.nan
                    return result
                if result_matches:
                    result.success = command_result.success
                    result.command_id = command.command_id
                    result.final_state = self._public_gateway_state()
                    result.detail = command_result.detail
                    snapshot = self._core.snapshot
                    result.measured_normalized_position_valid = (
                        snapshot is not None)
                    result.measured_normalized_position = (
                        snapshot.position if snapshot else math.nan)
                    result.measured_jaw_opening_valid = False
                    result.measured_jaw_opening_m = math.nan
                    if cancellation_pending:
                        goal_handle.canceled()
                    elif result.success:
                        goal_handle.succeed()
                    else:
                        goal_handle.abort()
                    return result
                if self._core.state in (
                        GripperGatewayState.FAULT_LATCHED,
                        GripperGatewayState.READY):
                    goal_handle.abort()
                    result.success = False
                    result.command_id = command.command_id
                    result.final_state = self._public_gateway_state()
                    result.detail = (
                        self._core.fault_reason
                        or '{} without a matching command result'.format(
                            self._core.state.value))
                    result.measured_normalized_position_valid = False
                    result.measured_normalized_position = math.nan
                    result.measured_jaw_opening_valid = False
                    result.measured_jaw_opening_m = math.nan
                    return result
                time.sleep(period)
            self._core.fail_closed_action_boundary(
                'ROS shutdown during active gripper action')
            goal_handle.abort()
            result.success = False
            result.command_id = command.command_id
            result.final_state = self._public_gateway_state()
            result.detail = (
                self._core.fault_reason
                or 'ROS shutdown before command completion')
            result.measured_normalized_position_valid = False
            result.measured_normalized_position = math.nan
            result.measured_jaw_opening_valid = False
            result.measured_jaw_opening_m = math.nan
            return result
        except GripperGatewayError as error:
            if self._core.motion_safety_unresolved:
                self._core.fail_closed_action_boundary(
                    'gripper action failed before safe resolution')
            goal_handle.abort()
            result.success = False
            result.command_id = command.command_id if command else ''
            result.final_state = self._public_gateway_state()
            result.detail = self._core.fault_reason or str(error)
            result.measured_normalized_position_valid = False
            result.measured_normalized_position = math.nan
            result.measured_jaw_opening_valid = False
            result.measured_jaw_opening_m = math.nan
            return result
        finally:
            with self._lock:
                self._busy = False

    def _publish_feedback(self, goal_handle, command_id):
        feedback = ExecuteGripperMotion.Feedback()
        feedback.command_id = command_id
        feedback.state = self._public_gateway_state()
        feedback.progress = 0.0
        feedback.detail = self._core.fault_reason
        snapshot = self._core.snapshot
        feedback.measured_normalized_position_valid = snapshot is not None
        feedback.measured_normalized_position = (
            snapshot.position if snapshot else math.nan)
        feedback.measured_jaw_opening_valid = False
        feedback.measured_jaw_opening_m = math.nan
        goal_handle.publish_feedback(feedback)

    def stop_callback(self, request, response):
        if not self._session_matches(request.expected_session_id):
            response.accepted = False
            response.gateway_state = self._public_gateway_state()
            response.detail = 'stale or empty session id'
            return response
        try:
            response.accepted = self._core.request_stop(
                request.reason, request.expected_session_id)
            response.detail = (
                'STOP requested; stationary verification pending')
        except GripperGatewayError as error:
            response.accepted = False
            response.detail = str(error)
        response.gateway_state = self._public_gateway_state()
        return response

    def acknowledge_callback(self, request, response):
        if not self._session_matches(request.expected_session_id):
            response.accepted = False
            response.gateway_state = self._public_gateway_state()
            response.detail = 'stale or empty session id'
            return response
        try:
            response.accepted = self._core.acknowledge_local_fault(
                request.authorization_id,
                request.expected_session_id,
            )
            response.detail = (
                'local fault latch cleared; controller was not modified')
        except GripperGatewayError as error:
            response.accepted = False
            response.detail = str(error)
        response.gateway_state = self._public_gateway_state()
        return response

    def destroy_node(self):
        self._action_server.destroy()
        try:
            self._core.close()
        except GripperGatewayError as error:
            self.get_logger().error(str(error))
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GripperGatewayNode()
    executor = MultiThreadedExecutor(num_threads=4)
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
