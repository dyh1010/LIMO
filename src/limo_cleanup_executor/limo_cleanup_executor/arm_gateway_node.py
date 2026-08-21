"""ROS 2 wrapper for the fail-closed myCobot arm gateway core."""

import math
import threading
import time

import rclpy
from limo_cleanup_interfaces.action import ExecuteArmMotion
from limo_cleanup_interfaces.msg import ArmState
from limo_cleanup_interfaces.srv import AcknowledgeArmFault, StopArm
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .arm_backends import ArmBackendError, DryRunArmBackend
from .arm_gateway_core import (
    ArmGatewayCore,
    ArmGatewayError,
    ArmGatewayPolicy,
    GatewayState,
    MotionRejected,
)


class ArmGatewayNode(Node):
    """Expose state and bounded dry-run arm commands through ROS 2."""

    def __init__(
            self,
            parameter_overrides=None,
            authorization_validator=None):
        super().__init__(
            'cleanup_arm_gateway',
            parameter_overrides=parameter_overrides,
        )
        self._declare_parameters()
        self._callback_group = ReentrantCallbackGroup()
        self._lifecycle_lock = threading.RLock()
        self._busy = False
        self._sample_sequence = 0
        self._backend = None
        self._core = None

        if self.backend_name != 'dry_run':
            raise RuntimeError(
                'only backend=dry_run is released; robot hardware is blocked')
        self._backend = DryRunArmBackend(
            initial_angles=self.initial_angles_deg,
            initial_tcp_pose=self.initial_tcp_pose,
            motion_duration_s=self.dry_run_motion_duration_s,
        )
        self._core = ArmGatewayCore(
            self._backend,
            self._make_policy(),
            authorization_validator=authorization_validator,
        )

        self._state_publisher = self.create_publisher(
            ArmState, '/cleanup/arm/state', 10)
        self._action_server = ActionServer(
            self,
            ExecuteArmMotion,
            '/cleanup/arm/execute',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self._callback_group,
        )
        self._stop_service = self.create_service(
            StopArm,
            '/cleanup/arm/stop',
            self.stop_callback,
            callback_group=self._callback_group,
        )
        self._ack_service = self.create_service(
            AcknowledgeArmFault,
            '/cleanup/arm/acknowledge_fault',
            self.acknowledge_callback,
            callback_group=self._callback_group,
        )
        self._timer = self.create_timer(
            1.0 / self.poll_hz,
            self.poll_once,
            callback_group=self._callback_group,
        )
        self.poll_once()
        self.get_logger().info(
            'Arm gateway ready in dry-run only; session_id={}'.format(
                self._core.session_id))

    def _declare_parameters(self):
        parameters = (
            ('backend', 'dry_run'),
            ('allow_simulated_motion', False),
            ('poll_hz', 10.0),
            ('feedback_hz', 10.0),
            ('dry_run_motion_duration_s', 0.20),
            ('max_speed_grade', 10),
            ('approved_speed_grades', [10]),
            ('state_max_age_s', 0.25),
            ('command_timeout_s', 5.0),
            ('stop_timeout_s', 2.0),
            ('max_stop_attempts', 3),
            ('stop_retry_interval_s', 0.50),
            ('stop_retry_backoff_factor', 2.0),
            ('stable_samples_required', 3),
            ('stationary_dwell_s', 0.20),
            ('stationary_joint_tolerance_deg', 0.01),
            ('joint_tolerance_deg', 0.5),
            ('tcp_translation_tolerance_mm', 1.0),
            ('tcp_rotation_tolerance_deg', 1.0),
            ('acceleration_profile_id', 'DRY_RUN_ONLY'),
            ('runtime_release_id', 'DRY_RUN_RELEASE_V1'),
            ('release_manifest_sha256',
             '0db63372cc24980532f650205fbb3537d02609ac62d52d76704e6dc7eaff9f83'),
            ('acceleration_profile_manifest_sha256',
             'cfd2f55631a9406ac5191bb09c38c3f3f678b8788ace2920d4966b3b3d56260e'),
            ('acceleration_profile_runtime_release_id',
             'DRY_RUN_RELEASE_V1'),
            ('joint_min_deg', [-160.0] * 6),
            ('joint_max_deg', [160.0] * 6),
            ('tcp_min', [-250.0, -250.0, 0.0, -180.0, -180.0, -180.0]),
            ('tcp_max', [250.0, 250.0, 400.0, 180.0, 180.0, 180.0]),
            ('allowed_tcp_modes', [0]),
            ('required_reference_frame', 0),
            ('required_end_type', 0),
            ('required_fresh_mode', 0),
            ('named_pose_names', ['inspection']),
            ('named_pose_values', [0.0] * 6),
            ('initial_angles_deg', [0.0] * 6),
            ('initial_tcp_pose', [100.0, 0.0, 200.0, 0.0, 0.0, 0.0]),
        )
        for name, default in parameters:
            self.declare_parameter(name, default)

        self.backend_name = str(self.get_parameter('backend').value)
        self.allow_simulated_motion = bool(
            self.get_parameter('allow_simulated_motion').value)
        self.poll_hz = float(self.get_parameter('poll_hz').value)
        self.feedback_hz = float(self.get_parameter('feedback_hz').value)
        self.dry_run_motion_duration_s = float(
            self.get_parameter('dry_run_motion_duration_s').value)
        self.max_speed_grade = int(
            self.get_parameter('max_speed_grade').value)
        self.approved_speed_grades = tuple(
            int(value)
            for value in self.get_parameter('approved_speed_grades').value)
        self.state_max_age_s = float(
            self.get_parameter('state_max_age_s').value)
        self.command_timeout_s = float(
            self.get_parameter('command_timeout_s').value)
        self.stop_timeout_s = float(
            self.get_parameter('stop_timeout_s').value)
        self.max_stop_attempts = int(
            self.get_parameter('max_stop_attempts').value)
        self.stop_retry_interval_s = float(
            self.get_parameter('stop_retry_interval_s').value)
        self.stop_retry_backoff_factor = float(
            self.get_parameter('stop_retry_backoff_factor').value)
        self.stable_samples_required = int(
            self.get_parameter('stable_samples_required').value)
        self.stationary_dwell_s = float(
            self.get_parameter('stationary_dwell_s').value)
        self.stationary_joint_tolerance_deg = float(
            self.get_parameter('stationary_joint_tolerance_deg').value)
        self.joint_tolerance_deg = float(
            self.get_parameter('joint_tolerance_deg').value)
        self.tcp_translation_tolerance_mm = float(
            self.get_parameter('tcp_translation_tolerance_mm').value)
        self.tcp_rotation_tolerance_deg = float(
            self.get_parameter('tcp_rotation_tolerance_deg').value)
        self.acceleration_profile_id = str(
            self.get_parameter('acceleration_profile_id').value)
        self.runtime_release_id = str(
            self.get_parameter('runtime_release_id').value)
        self.release_manifest_sha256 = str(
            self.get_parameter('release_manifest_sha256').value)
        self.acceleration_profile_manifest_sha256 = str(
            self.get_parameter(
                'acceleration_profile_manifest_sha256').value)
        self.acceleration_profile_runtime_release_id = str(
            self.get_parameter(
                'acceleration_profile_runtime_release_id').value)
        self.joint_min_deg = list(
            self.get_parameter('joint_min_deg').value)
        self.joint_max_deg = list(
            self.get_parameter('joint_max_deg').value)
        self.tcp_min = list(self.get_parameter('tcp_min').value)
        self.tcp_max = list(self.get_parameter('tcp_max').value)
        self.allowed_tcp_modes = tuple(
            int(value)
            for value in self.get_parameter('allowed_tcp_modes').value)
        self.required_reference_frame = int(
            self.get_parameter('required_reference_frame').value)
        self.required_end_type = int(
            self.get_parameter('required_end_type').value)
        self.required_fresh_mode = int(
            self.get_parameter('required_fresh_mode').value)
        self.named_pose_names = list(
            self.get_parameter('named_pose_names').value)
        self.named_pose_values = list(
            self.get_parameter('named_pose_values').value)
        self.initial_angles_deg = list(
            self.get_parameter('initial_angles_deg').value)
        self.initial_tcp_pose = list(
            self.get_parameter('initial_tcp_pose').value)

        if not 1.0 <= self.poll_hz <= 50.0:
            raise RuntimeError('poll_hz must be in 1..50')
        if not 1.0 <= self.feedback_hz <= 50.0:
            raise RuntimeError('feedback_hz must be in 1..50')

    def _make_policy(self):
        if len(self.joint_min_deg) != 6 or len(self.joint_max_deg) != 6:
            raise RuntimeError('joint min/max parameters must have six values')
        if len(self.tcp_min) != 6 or len(self.tcp_max) != 6:
            raise RuntimeError('TCP min/max parameters must have six values')
        if len(self.named_pose_values) != 6 * len(self.named_pose_names):
            raise RuntimeError(
                'named_pose_values must contain six values per pose name')
        if len(set(self.named_pose_names)) != len(self.named_pose_names):
            raise RuntimeError('named_pose_names must not contain duplicates')
        if any(not str(name).strip() for name in self.named_pose_names):
            raise RuntimeError('named_pose_names must not contain empty names')
        named_poses = {}
        for index, name in enumerate(self.named_pose_names):
            start = index * 6
            named_poses[str(name)] = tuple(
                float(value)
                for value in self.named_pose_values[start:start + 6])
        return ArmGatewayPolicy(
            permit_motion=(
                self.backend_name == 'dry_run'
                and self.allow_simulated_motion
            ),
            max_speed_grade=self.max_speed_grade,
            approved_speed_grades=self.approved_speed_grades,
            state_max_age_s=self.state_max_age_s,
            command_timeout_s=self.command_timeout_s,
            stop_timeout_s=self.stop_timeout_s,
            max_stop_attempts=self.max_stop_attempts,
            stop_retry_interval_s=self.stop_retry_interval_s,
            stop_retry_backoff_factor=self.stop_retry_backoff_factor,
            stable_samples_required=self.stable_samples_required,
            stationary_dwell_s=self.stationary_dwell_s,
            stationary_joint_tolerance_deg=(
                self.stationary_joint_tolerance_deg),
            joint_tolerance_deg=self.joint_tolerance_deg,
            tcp_translation_tolerance_mm=(
                self.tcp_translation_tolerance_mm),
            tcp_rotation_tolerance_deg=self.tcp_rotation_tolerance_deg,
            joint_limits_deg=tuple(zip(
                self.joint_min_deg, self.joint_max_deg)),
            tcp_bounds=tuple(zip(self.tcp_min, self.tcp_max)),
            named_joint_poses=named_poses,
            acceleration_profile_id=self.acceleration_profile_id,
            runtime_release_id=self.runtime_release_id,
            release_manifest_sha256=self.release_manifest_sha256,
            acceleration_profile_manifest_sha256=(
                self.acceleration_profile_manifest_sha256),
            acceleration_profile_runtime_release_id=(
                self.acceleration_profile_runtime_release_id),
            allowed_tcp_modes=self.allowed_tcp_modes,
            required_reference_frame=self.required_reference_frame,
            required_end_type=self.required_end_type,
            required_fresh_mode=self.required_fresh_mode,
        )

    def poll_once(self):
        try:
            self._core.refresh()
        except ArmGatewayError as error:
            self.get_logger().error(str(error))
        self._sample_sequence += 1
        self._publish_state()

    def _publish_state(self):
        message = ArmState()
        message.stamp = self.get_clock().now().to_msg()
        message.gateway_state = self._core.state.value
        snapshot = self._core.snapshot
        message.valid = self._core.snapshot_is_valid()
        message.physical_stop_required = self._core.physical_stop_required
        message.session_id = self._core.session_id
        message.sample_sequence = self._sample_sequence
        message.port = 'DRY_RUN_NO_DEVICE'
        message.usb_vid_pid = ''
        message.usb_serial = ''
        if snapshot is not None:
            message.controller_connected = snapshot.connected
            message.power_on = snapshot.power_on
            message.moving = snapshot.moving
            message.paused = snapshot.paused
            message.error_code = snapshot.error_code
            message.fresh_mode = snapshot.fresh_mode
            message.all_servos_enabled = snapshot.servo_enabled
            message.joint_angles_deg = list(snapshot.angles_deg)
            message.tcp_pose = list(snapshot.tcp_pose)
        else:
            message.controller_connected = -1
            message.power_on = -1
            message.moving = -1
            message.paused = -1
            message.error_code = -1
            message.fresh_mode = -1
            message.all_servos_enabled = -1
            message.joint_angles_deg = [math.nan] * 6
            message.tcp_pose = [math.nan] * 6
        message.active_command_id = (
            self._core.active_command.command_id
            if self._core.active_command is not None else '')
        message.fault_reason = self._core.fault_reason
        self._state_publisher.publish(message)

    def _session_matches(self, expected):
        return bool(expected) and expected == self._core.session_id

    def goal_callback(self, request):
        with self._lifecycle_lock:
            if not self._session_matches(request.expected_session_id):
                self.get_logger().warning(
                    'Rejecting arm goal with stale or empty session id')
                return GoalResponse.REJECT
            if not request.authorization_id:
                return GoalResponse.REJECT
            if request.kind not in (
                    ExecuteArmMotion.Goal.KIND_NAMED_JOINT_POSE,
                    ExecuteArmMotion.Goal.KIND_BOUNDED_TCP_MOVE):
                return GoalResponse.REJECT
            if self._busy or self._core.state != GatewayState.READY:
                return GoalResponse.REJECT
            self._busy = True
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        result = ExecuteArmMotion.Result()
        try:
            request = goal_handle.request
            if request.kind == request.KIND_NAMED_JOINT_POSE:
                command = self._core.command_named_joint_pose(
                    request.named_pose,
                    int(request.speed_grade),
                    request.authorization_id,
                    request.expected_session_id,
                )
            else:
                command = self._core.command_tcp_move(
                    list(request.tcp_target),
                    int(request.speed_grade),
                    int(request.tcp_mode),
                    request.authorization_id,
                    request.expected_session_id,
                )
            result.command_id = command.command_id

            period = 1.0 / self.feedback_hz
            cancellation_pending = False
            while rclpy.ok():
                if (
                        goal_handle.is_cancel_requested
                        and not cancellation_pending):
                    self._core.request_stop(
                        'action cancelled', self._core.session_id)
                    cancellation_pending = True

                state = self._core.state
                self._publish_feedback(goal_handle)
                command_result = self._core.last_result
                if state == GatewayState.READY:
                    result_matches = (
                        command_result is not None
                        and command_result.command_id
                        == result.command_id
                    )
                    if not result_matches:
                        goal_handle.abort()
                        return self._fill_result(
                            result, False, state.value,
                            'READY without a matching command result')
                    if command_result.success:
                        goal_handle.succeed()
                        return self._fill_result(
                            result, True, state.value,
                            command_result.detail)
                    if cancellation_pending:
                        goal_handle.canceled()
                    else:
                        goal_handle.abort()
                    return self._fill_result(
                        result, False, state.value,
                        command_result.detail)
                if state == GatewayState.FAULT_LATCHED:
                    if not self._core.motion_safety_unresolved:
                        result_matches = (
                            command_result is not None
                            and command_result.command_id
                            == result.command_id
                            and command_result.success is False
                        )
                        if not result_matches:
                            goal_handle.abort()
                            return self._fill_result(
                                result, False, state.value,
                                'resolved fault without a matching '
                                'failed command result')
                        if cancellation_pending:
                            goal_handle.canceled()
                        else:
                            goal_handle.abort()
                        return self._fill_result(
                            result, False, state.value,
                            command_result.detail)
                time.sleep(period)
            self._core.fail_closed_action_boundary(
                'ROS shutdown during active arm action')
            goal_handle.abort()
            return self._fill_result(
                result, False, self._core.state.value,
                self._core.fault_reason
                or 'ROS shutdown before command completion')
        except (MotionRejected, ArmGatewayError) as error:
            if self._core.motion_safety_unresolved:
                self._core.fail_closed_action_boundary(
                    'arm action failed before safe resolution')
            goal_handle.abort()
            return self._fill_result(
                result, False, self._core.state.value,
                self._core.fault_reason or str(error))
        except Exception as error:  # noqa: BLE001
            try:
                self._core.request_stop(
                    'unexpected action exception',
                    self._core.session_id,
                )
            except ArmGatewayError:
                pass
            self._core.fail_closed_action_boundary(
                'unexpected arm action exception')
            goal_handle.abort()
            return self._fill_result(
                result, False, self._core.state.value,
                'Unexpected arm gateway error: {}'.format(
                    type(error).__name__))
        finally:
            with self._lifecycle_lock:
                self._busy = False

    def _publish_feedback(self, goal_handle):
        feedback = ExecuteArmMotion.Feedback()
        feedback.command_id = (
            self._core.active_command.command_id
            if self._core.active_command is not None else '')
        feedback.state = self._core.state.value
        feedback.progress = (
            1.0 if self._core.state == GatewayState.READY else 0.5)
        feedback.detail = self._core.fault_reason
        if self._core.snapshot is not None:
            feedback.measured_joint_angles_deg = list(
                self._core.snapshot.angles_deg)
            feedback.measured_tcp_pose = list(
                self._core.snapshot.tcp_pose)
        goal_handle.publish_feedback(feedback)

    def _fill_result(self, result, success, final_state, detail):
        result.success = success
        result.final_state = final_state
        result.detail = detail
        if self._core.snapshot is not None:
            result.measured_joint_angles_deg = list(
                self._core.snapshot.angles_deg)
            result.measured_tcp_pose = list(self._core.snapshot.tcp_pose)
        return result

    def stop_callback(self, request, response):
        if not self._session_matches(request.expected_session_id):
            response.accepted = False
            response.gateway_state = self._core.state.value
            response.detail = 'stale or empty session id'
            return response
        try:
            response.accepted = self._core.request_stop(
                request.reason, request.expected_session_id)
            response.detail = (
                'STOP sent; stationary verification pending'
                if response.accepted else 'STOP was not sent')
        except ArmGatewayError as error:
            response.accepted = False
            response.detail = str(error)
        response.gateway_state = self._core.state.value
        return response

    def acknowledge_callback(self, request, response):
        if not self._session_matches(request.expected_session_id):
            response.accepted = False
            response.gateway_state = self._core.state.value
            response.detail = 'stale or empty session id'
            return response
        try:
            response.accepted = self._core.acknowledge_local_fault(
                request.authorization_id,
                request.expected_session_id,
            )
            response.detail = (
                'Local fault latch acknowledged; controller state '
                'was not modified')
        except MotionRejected as error:
            response.accepted = False
            response.detail = str(error)
        response.gateway_state = self._core.state.value
        return response

    def destroy_node(self):
        if self._action_server is not None:
            self._action_server.destroy()
        if self._core is not None:
            self._core.close()
        return super().destroy_node()


def main(args=None):
    """Run the dry-run-only ROS arm gateway."""
    rclpy.init(args=args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        node = ArmGatewayNode()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ArmBackendError) as error:
        print('arm gateway failed: {}'.format(error))
        raise
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
