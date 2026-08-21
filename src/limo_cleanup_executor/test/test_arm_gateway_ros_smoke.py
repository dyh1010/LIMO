"""End-to-end ROS smoke test using only the in-memory arm backend."""

import threading
import time
import unittest

try:
    import rclpy
    from limo_cleanup_interfaces.action import ExecuteArmMotion
    from limo_cleanup_interfaces.msg import ArmState
    from limo_cleanup_interfaces.srv import AcknowledgeArmFault, StopArm
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter

    from limo_cleanup_executor.arm_gateway_node import ArmGatewayNode
except ImportError as import_error:  # pragma: no cover - non-ROS host
    _ROS_IMPORT_ERROR = import_error
    _ROS_SKIP_CODE = (
        'SKIPPED_NO_RCLPY'
        if getattr(import_error, 'name', '') == 'rclpy'
        else 'SKIPPED_ROS2_RUNTIME_INCOMPLETE')
else:
    _ROS_IMPORT_ERROR = None
    _ROS_SKIP_CODE = ''


def wait_future(future, timeout_s=5.0):
    """Wait for a future while a background executor services callbacks."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if future.done():
            return future.result()
        time.sleep(0.01)
    raise AssertionError('ROS future did not complete before timeout')


def validate_fake_authorization(authorization_id, purpose, session_id):
    """Accept only purpose- and session-bound tokens in this smoke suite."""
    if purpose not in ('motion', 'ack') or not session_id:
        return False
    prefix = '{}:{}:'.format(session_id, purpose)
    return bool(
        isinstance(authorization_id, str)
        and authorization_id.startswith(prefix)
        and len(authorization_id) > len(prefix)
    )


@unittest.skipIf(
    _ROS_IMPORT_ERROR is not None,
    '{}; ROS2_ONLY_ENVIRONMENT; {}'.format(
        _ROS_SKIP_CODE, _ROS_IMPORT_ERROR),
)
class ArmGatewayRosSmokeTest(unittest.TestCase):
    """Verify the public ROS contract without constructing hardware."""

    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        if rclpy.ok():
            rclpy.shutdown()

    def setUp(self):
        allow_motion = (
            self._testMethodName != 'test_default_policy_rejects_motion'
        )
        motion_duration = (
            1.0
            if self._testMethodName == 'test_command_timeout_stops_and_aborts'
            else 0.40
            if self._testMethodName in (
                'test_concurrent_goal_is_rejected',
                'test_cancel_waits_for_stationary_verification',
            )
            else 0.10
        )
        overrides = [
            Parameter('allow_simulated_motion', value=allow_motion),
            Parameter('poll_hz', value=20.0),
            Parameter(
                'feedback_hz',
                value=(
                    1.0
                    if self._testMethodName
                    == 'test_stop_ack_race_cannot_report_action_success'
                    else 20.0
                ),
            ),
            Parameter(
                'dry_run_motion_duration_s',
                value=motion_duration,
            ),
            Parameter('stable_samples_required', value=2),
            Parameter(
                'command_timeout_s',
                value=(
                    0.20
                    if self._testMethodName
                    == 'test_command_timeout_stops_and_aborts'
                    else 5.0
                ),
            ),
        ]
        self.gateway = ArmGatewayNode(
            parameter_overrides=overrides,
            authorization_validator=validate_fake_authorization,
        )
        self.client_node = Node('arm_gateway_smoke_client')
        self.executor = MultiThreadedExecutor(num_threads=4)
        self.executor.add_node(self.gateway)
        self.executor.add_node(self.client_node)
        self.spin_thread = threading.Thread(
            target=self.executor.spin,
            daemon=True,
        )
        self.spin_thread.start()
        self.states = []
        self.subscription = self.client_node.create_subscription(
            ArmState,
            '/cleanup/arm/state',
            self.states.append,
            10,
        )
        self.action_client = ActionClient(
            self.client_node,
            ExecuteArmMotion,
            '/cleanup/arm/execute',
        )
        self.stop_client = self.client_node.create_client(
            StopArm,
            '/cleanup/arm/stop',
        )
        self.ack_client = self.client_node.create_client(
            AcknowledgeArmFault,
            '/cleanup/arm/acknowledge_fault',
        )

    def tearDown(self):
        self.action_client.destroy()
        self.client_node.destroy_client(self.stop_client)
        self.client_node.destroy_client(self.ack_client)
        self.client_node.destroy_subscription(self.subscription)
        self.executor.shutdown()
        self.spin_thread.join(timeout=2.0)
        self.client_node.destroy_node()
        self.gateway.destroy_node()

    def wait_for_state(self, expected, timeout_s=5.0, after_sequence=None):
        """Return the newest requested state sample."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for state in reversed(self.states):
                is_new = (
                    after_sequence is None
                    or state.sample_sequence > after_sequence
                )
                if state.gateway_state == expected and is_new:
                    return state
            time.sleep(0.01)
        observed = [state.gateway_state for state in self.states]
        raise AssertionError(
            'state {} not observed; got {}'.format(expected, observed))

    @staticmethod
    def make_named_goal(session_id, authorization_id=None):
        """Create a valid named-pose request for this smoke suite."""
        goal = ExecuteArmMotion.Goal()
        goal.kind = goal.KIND_NAMED_JOINT_POSE
        goal.named_pose = 'inspection'
        goal.tcp_mode = goal.MODE_MOVE_J
        goal.speed_grade = 5
        goal.authorization_id = (
            authorization_id
            if authorization_id is not None
            else '{}:motion:simulated-action-1'.format(session_id)
        )
        goal.expected_session_id = session_id
        return goal

    @staticmethod
    def make_tcp_goal(session_id, target, authorization_id):
        """Create a bounded TCP request for this smoke suite."""
        goal = ExecuteArmMotion.Goal()
        goal.kind = goal.KIND_BOUNDED_TCP_MOVE
        goal.tcp_target = list(target)
        goal.tcp_mode = goal.MODE_MOVE_J
        goal.speed_grade = 5
        goal.authorization_id = authorization_id
        goal.expected_session_id = session_id
        return goal

    def test_action_stop_and_acknowledge_flow(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertEqual(ready.port, 'DRY_RUN_NO_DEVICE')
        self.assertTrue(ready.valid)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))

        goal = self.make_named_goal(ready.session_id)
        goal_handle = wait_future(self.action_client.send_goal_async(goal))
        self.assertTrue(goal_handle.accepted)
        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertTrue(wrapped_result.result.success)
        self.assertEqual(
            wrapped_result.result.final_state,
            ArmState.STATE_READY,
        )
        self.assertTrue(wrapped_result.result.command_id)
        self.assertIn(
            ArmState.STATE_EXECUTING,
            [state.gateway_state for state in self.states],
        )

        self.assertTrue(self.stop_client.wait_for_service(timeout_sec=2.0))
        stop_request = StopArm.Request()
        stop_request.reason = 'simulated stop verification'
        stop_request.expected_session_id = ready.session_id
        stop_response = wait_future(
            self.stop_client.call_async(stop_request))
        self.assertTrue(stop_response.accepted)
        fault = self.wait_for_state(ArmState.STATE_FAULT_LATCHED)

        self.assertTrue(self.ack_client.wait_for_service(timeout_sec=2.0))
        ack_request = AcknowledgeArmFault.Request()
        ack_request.authorization_id = (
            '{}:ack:simulated-review-1'.format(ready.session_id))
        ack_request.expected_session_id = ready.session_id
        ack_response = wait_future(self.ack_client.call_async(ack_request))
        self.assertTrue(ack_response.accepted)
        self.assertIn('was not modified', ack_response.detail)
        recovered = self.wait_for_state(
            ArmState.STATE_READY,
            after_sequence=fault.sample_sequence,
        )
        self.assertEqual(recovered.session_id, ready.session_id)

    def test_default_policy_rejects_motion(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        goal_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(ready.session_id)))
        self.assertTrue(goal_handle.accepted)
        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertFalse(wrapped_result.result.success)
        self.assertIn('disabled', wrapped_result.result.detail)
        self.assertEqual(
            wrapped_result.result.final_state,
            ArmState.STATE_READY,
        )

    def test_stale_session_and_missing_authorization_are_rejected(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))

        stale_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal('stale-session')))
        self.assertFalse(stale_handle.accepted)

        missing_auth_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(ready.session_id, '')))
        self.assertFalse(missing_auth_handle.accepted)

        self.assertTrue(self.stop_client.wait_for_service(timeout_sec=2.0))
        stop_request = StopArm.Request()
        stop_request.reason = 'must not be accepted'
        stop_request.expected_session_id = 'stale-session'
        stop_response = wait_future(
            self.stop_client.call_async(stop_request))
        self.assertFalse(stop_response.accepted)
        self.assertIn('stale', stop_response.detail)

    def test_concurrent_goal_is_rejected(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))

        first_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(
                    ready.session_id,
                    '{}:motion:simulated-concurrent-1'.format(
                        ready.session_id),
                )))
        self.assertTrue(first_handle.accepted)

        second_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(
                    ready.session_id,
                    '{}:motion:simulated-concurrent-2'.format(
                        ready.session_id),
                )))
        self.assertFalse(second_handle.accepted)

        wrapped_result = wait_future(first_handle.get_result_async())
        self.assertTrue(wrapped_result.result.success)

    def test_cancel_waits_for_stationary_verification(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        goal_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(
                    ready.session_id,
                    '{}:motion:simulated-cancel-1'.format(
                        ready.session_id),
                )))
        self.assertTrue(goal_handle.accepted)
        executing = self.wait_for_state(ArmState.STATE_EXECUTING)

        cancel_response = wait_future(goal_handle.cancel_goal_async())
        self.assertEqual(len(cancel_response.goals_canceling), 1)
        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertFalse(wrapped_result.result.success)
        self.assertEqual(
            wrapped_result.result.final_state,
            ArmState.STATE_FAULT_LATCHED,
        )
        self.assertIn(
            'stationary state verified',
            wrapped_result.result.detail,
        )
        fault = self.wait_for_state(
            ArmState.STATE_FAULT_LATCHED,
            after_sequence=executing.sample_sequence,
        )
        self.assertGreater(
            fault.sample_sequence,
            executing.sample_sequence,
        )

    def test_bounded_tcp_action_reaches_measured_target(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        target = [120.0, 10.0, 220.0, 0.0, 0.0, 5.0]
        goal_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_tcp_goal(
                    ready.session_id,
                    target,
                    '{}:motion:simulated-tcp-1'.format(ready.session_id),
                )))
        self.assertTrue(goal_handle.accepted)
        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertTrue(wrapped_result.result.success)
        self.assertEqual(
            list(wrapped_result.result.measured_tcp_pose),
            target,
        )

    def test_out_of_bounds_tcp_action_aborts_without_success(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        goal_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_tcp_goal(
                    ready.session_id,
                    [999.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                    '{}:motion:simulated-tcp-invalid-1'.format(
                        ready.session_id),
                )))
        self.assertTrue(goal_handle.accepted)
        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertFalse(wrapped_result.result.success)
        self.assertEqual(
            wrapped_result.result.final_state,
            ArmState.STATE_READY,
        )
        self.assertIn('outside', wrapped_result.result.detail)

    def test_stop_ack_race_cannot_report_action_success(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        goal_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(
                    ready.session_id,
                    '{}:motion:simulated-stop-race-1'.format(
                        ready.session_id),
                )))
        self.assertTrue(goal_handle.accepted)
        self.wait_for_state(ArmState.STATE_EXECUTING)

        self.assertTrue(self.stop_client.wait_for_service(timeout_sec=2.0))
        stop_request = StopArm.Request()
        stop_request.reason = 'external stop before action result'
        stop_request.expected_session_id = ready.session_id
        stop_response = wait_future(
            self.stop_client.call_async(stop_request))
        self.assertTrue(stop_response.accepted)
        fault = self.wait_for_state(ArmState.STATE_FAULT_LATCHED)

        self.assertTrue(self.ack_client.wait_for_service(timeout_sec=2.0))
        ack_request = AcknowledgeArmFault.Request()
        ack_request.authorization_id = (
            '{}:ack:simulated-race-review-1'.format(ready.session_id))
        ack_request.expected_session_id = ready.session_id
        ack_response = wait_future(self.ack_client.call_async(ack_request))
        self.assertTrue(ack_response.accepted)
        self.wait_for_state(
            ArmState.STATE_READY,
            after_sequence=fault.sample_sequence,
        )

        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertFalse(wrapped_result.result.success)
        self.assertEqual(
            wrapped_result.result.final_state,
            ArmState.STATE_READY,
        )
        self.assertIn('external stop', wrapped_result.result.detail)

    def test_command_timeout_stops_and_aborts(self):
        ready = self.wait_for_state(ArmState.STATE_READY)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        goal_handle = wait_future(
            self.action_client.send_goal_async(
                self.make_named_goal(
                    ready.session_id,
                    '{}:motion:simulated-timeout-1'.format(
                        ready.session_id),
                )))
        self.assertTrue(goal_handle.accepted)
        wrapped_result = wait_future(goal_handle.get_result_async())
        self.assertFalse(wrapped_result.result.success)
        self.assertEqual(
            wrapped_result.result.final_state,
            ArmState.STATE_FAULT_LATCHED,
        )
        self.assertIn('command timeout', wrapped_result.result.detail)
        self.assertIn(
            ArmState.STATE_STOPPING,
            [state.gateway_state for state in self.states],
        )


if __name__ == '__main__':
    unittest.main()
