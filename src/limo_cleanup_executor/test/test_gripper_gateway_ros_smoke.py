"""End-to-end ROS smoke for the simulation-only gripper gateway."""

import threading
import time
import unittest

try:
    import rclpy
    from limo_cleanup_interfaces.action import ExecuteGripperMotion
    from limo_cleanup_interfaces.msg import GripperState
    from limo_cleanup_interfaces.srv import (
        AcknowledgeGripperFault,
        StopGripper,
    )
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter

    from limo_cleanup_executor.gripper_gateway_node import GripperGatewayNode
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
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if future.done():
            return future.result()
        time.sleep(0.01)
    raise AssertionError('ROS future did not complete before timeout')


@unittest.skipIf(
    _ROS_IMPORT_ERROR is not None,
    '{}; ROS2_ONLY_ENVIRONMENT; {}'.format(
        _ROS_SKIP_CODE, _ROS_IMPORT_ERROR),
)
class GripperGatewayRosSmokeRuntimeTest(unittest.TestCase):
    """Drive Action/STOP/ACK without constructing hardware."""

    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        if rclpy.ok():
            rclpy.shutdown()

    def setUp(self):
        self.gateway = GripperGatewayNode(parameter_overrides=[
            Parameter('allow_simulated_motion', value=True),
            Parameter('dry_run_motion_duration_s', value=0.05),
            Parameter('stable_samples_required', value=2),
            Parameter('stationary_dwell_s', value=0.05),
        ])
        self.client_node = Node('gripper_gateway_smoke_client')
        self.executor = MultiThreadedExecutor(num_threads=4)
        self.executor.add_node(self.gateway)
        self.executor.add_node(self.client_node)
        self.spin_thread = threading.Thread(
            target=self.executor.spin, daemon=True)
        self.spin_thread.start()
        self.states = []
        self.subscription = self.client_node.create_subscription(
            GripperState,
            '/cleanup/gripper/state',
            self.states.append,
            10,
        )
        self.action_client = ActionClient(
            self.client_node,
            ExecuteGripperMotion,
            '/cleanup/gripper/execute',
        )
        self.stop_client = self.client_node.create_client(
            StopGripper, '/cleanup/gripper/stop')
        self.ack_client = self.client_node.create_client(
            AcknowledgeGripperFault,
            '/cleanup/gripper/acknowledge_fault',
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

    def wait_for_state(self, expected, timeout_s=5.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for state in reversed(self.states):
                if state.gateway_state == expected:
                    return state
            time.sleep(0.01)
        raise AssertionError('state {} not observed'.format(expected))

    def test_action_stop_and_acknowledge_flow(self):
        ready = self.wait_for_state(GripperState.STATE_READY)
        self.assertTrue(ready.valid)
        self.assertEqual(ready.tool_model, 'DRY_RUN_TOOL')
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=2.0))
        goal = ExecuteGripperMotion.Goal()
        goal.target_kind = goal.TARGET_NORMALIZED_POSITION
        goal.normalized_position = 0.5
        goal.speed_normalized = 0.2
        goal.expected_tool_revision = ready.tool_revision
        goal.authorization_id = '{}:motion:smoke-1'.format(ready.session_id)
        goal.expected_session_id = ready.session_id
        goal_handle = wait_future(self.action_client.send_goal_async(goal))
        self.assertTrue(goal_handle.accepted)
        result = wait_future(goal_handle.get_result_async()).result
        self.assertTrue(result.success)
        self.assertTrue(result.command_id)

        self.assertTrue(self.stop_client.wait_for_service(timeout_sec=2.0))
        stop = StopGripper.Request()
        stop.reason = 'simulated operator STOP'
        stop.expected_session_id = ready.session_id
        stop_result = wait_future(self.stop_client.call_async(stop))
        self.assertTrue(stop_result.accepted)
        self.wait_for_state(GripperState.STATE_FAULT_LATCHED)

        self.assertTrue(self.ack_client.wait_for_service(timeout_sec=2.0))
        ack = AcknowledgeGripperFault.Request()
        ack.authorization_id = '{}:ack:smoke-1'.format(ready.session_id)
        ack.expected_session_id = ready.session_id
        ack_result = wait_future(self.ack_client.call_async(ack))
        self.assertTrue(ack_result.accepted)
        self.wait_for_state(GripperState.STATE_READY)


if __name__ == '__main__':
    unittest.main()
