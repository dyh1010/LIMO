"""Drive gripper Action/STOP/ACK callbacks without importing ROS 2."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
NODE = ROOT / 'limo_cleanup_executor' / 'gripper_gateway_node.py'


class FakeCore:
    def __init__(self):
        self.session_id = 'session-1'
        self.state = SimpleNamespace(value='READY')
        self.snapshot = None
        self.last_result = None
        self.fault_reason = ''
        self.stop_calls = []
        self.ack_calls = []
        self.motion_safety_unresolved = False
        self.boundary_calls = []

    def request_stop(self, reason, expected_session_id):
        self.stop_calls.append((reason, expected_session_id))
        self.state = SimpleNamespace(value='STOPPING')
        return True

    def acknowledge_local_fault(
            self, authorization_id, expected_session_id):
        self.ack_calls.append((authorization_id, expected_session_id))
        self.state = SimpleNamespace(value='READY')
        return True

    def fail_closed_action_boundary(self, reason):
        self.boundary_calls.append(reason)
        if self.motion_safety_unresolved:
            self.physical_stop_required = True
            self.state = SimpleNamespace(value='FAULT_LATCHED')
            self.fault_reason = 'physical isolation required'
            return True
        return False


def callback_namespace(ok=None):
    tree = ast.parse(NODE.read_text(encoding='utf-8'), filename=str(NODE))
    wanted = {
        '_session_matches', 'goal_callback', 'cancel_callback',
        '_public_gateway_state', 'execute_callback', 'stop_callback',
        'acknowledge_callback',
    }
    methods = []
    for item in tree.body:
        if isinstance(item, ast.ClassDef) and item.name == 'GripperGatewayNode':
            methods = [
                child for child in item.body
                if isinstance(child, ast.FunctionDef)
                and child.name in wanted
            ]
            break
    module = ast.Module(body=methods, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        'GoalResponse': SimpleNamespace(ACCEPT='ACCEPT', REJECT='REJECT'),
        'CancelResponse': SimpleNamespace(ACCEPT='ACCEPT'),
        'ExecuteGripperMotion': SimpleNamespace(
            Goal=SimpleNamespace(TARGET_NORMALIZED_POSITION=1),
            Result=SimpleNamespace),
        'GripperGatewayError': RuntimeError,
        'GripperGatewayState': SimpleNamespace(
            FAULT_LATCHED=SimpleNamespace(value='FAULT_LATCHED'),
            CLOSED=SimpleNamespace(value='CLOSED'),
            READY=SimpleNamespace(value='READY')),
        'GripperState': SimpleNamespace(
            STATE_PHYSICAL_ESTOP_REQUIRED='PHYSICAL_ESTOP_REQUIRED'),
        'math': __import__('math'),
        'rclpy': SimpleNamespace(ok=ok or (lambda: True)),
        'time': __import__('time'),
    }
    exec(compile(module, str(NODE), 'exec'), namespace)
    return namespace


class FakeNode:
    def __init__(self, ok=None):
        namespace = callback_namespace(ok=ok)
        for name in (
                '_session_matches', 'goal_callback', 'cancel_callback',
                '_public_gateway_state', 'execute_callback', 'stop_callback',
                'acknowledge_callback'):
            setattr(self, name, namespace[name].__get__(self, FakeNode))
        self._lock = __import__('threading').RLock()
        self._busy = False
        self._core = FakeCore()
        self._core.physical_stop_required = False
        self.reviewed_tool_revision = 'revision-1'
        self.feedback_hz = 20.0
        self._publish_feedback = lambda unused_handle, unused_id: None


def response():
    return SimpleNamespace(accepted=False, gateway_state='', detail='')


class GripperGatewayCallbackContractTest(unittest.TestCase):
    def valid_goal(self):
        return SimpleNamespace(
            expected_session_id='session-1',
            authorization_id='auth-1',
            expected_tool_revision='revision-1',
            target_kind=1,
        )

    def test_goal_requires_session_authorization_revision_kind_and_idle(self):
        node = FakeNode()
        self.assertEqual(node.goal_callback(self.valid_goal()), 'ACCEPT')
        self.assertTrue(node._busy)
        cases = (
            {'expected_session_id': 'stale'},
            {'authorization_id': ''},
            {'expected_tool_revision': 'other'},
            {'target_kind': 2},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                probe = FakeNode()
                goal = self.valid_goal()
                for name, value in updates.items():
                    setattr(goal, name, value)
                self.assertEqual(probe.goal_callback(goal), 'REJECT')
                self.assertFalse(probe._busy)
        busy = FakeNode()
        busy._busy = True
        self.assertEqual(busy.goal_callback(self.valid_goal()), 'REJECT')

    def test_cancel_is_only_a_request(self):
        node = FakeNode()
        self.assertEqual(node.cancel_callback(object()), 'ACCEPT')
        self.assertEqual(node._core.stop_calls, [])

    def test_stop_rejects_stale_and_forwards_current_session(self):
        node = FakeNode()
        stale = SimpleNamespace(
            expected_session_id='stale', reason='operator STOP')
        stale_result = node.stop_callback(stale, response())
        self.assertFalse(stale_result.accepted)
        self.assertEqual(node._core.stop_calls, [])
        current = SimpleNamespace(
            expected_session_id='session-1', reason='operator STOP')
        result = node.stop_callback(current, response())
        self.assertTrue(result.accepted)
        self.assertEqual(
            node._core.stop_calls,
            [('operator STOP', 'session-1')],
        )
        self.assertIn('verification pending', result.detail)

    def test_ack_rejects_stale_and_forwards_authorization(self):
        node = FakeNode()
        stale = SimpleNamespace(
            expected_session_id='stale', authorization_id='review')
        stale_result = node.acknowledge_callback(stale, response())
        self.assertFalse(stale_result.accepted)
        self.assertEqual(node._core.ack_calls, [])
        current = SimpleNamespace(
            expected_session_id='session-1', authorization_id='review')
        result = node.acknowledge_callback(current, response())
        self.assertTrue(result.accepted)
        self.assertEqual(
            node._core.ack_calls,
            [('review', 'session-1')],
        )
        self.assertIn('was not modified', result.detail)

    def test_stop_and_ack_core_calls_do_not_run_under_node_lock(self):
        node = FakeNode()

        def assert_node_lock_available():
            outcome = []

            def worker():
                acquired = node._lock.acquire(timeout=0.5)
                outcome.append(acquired)
                if acquired:
                    node._lock.release()

            thread = __import__('threading').Thread(target=worker)
            thread.start()
            thread.join(timeout=1.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, [True])

        def request_stop(reason, expected_session_id):
            assert_node_lock_available()
            node._core.stop_calls.append((reason, expected_session_id))
            return True

        def acknowledge(authorization_id, expected_session_id):
            assert_node_lock_available()
            node._core.ack_calls.append(
                (authorization_id, expected_session_id))
            return True

        node._core.request_stop = request_stop
        node._core.acknowledge_local_fault = acknowledge
        stop_request = SimpleNamespace(
            expected_session_id='session-1', reason='operator STOP')
        ack_request = SimpleNamespace(
            expected_session_id='session-1', authorization_id='review')
        self.assertTrue(node.stop_callback(stop_request, response()).accepted)
        self.assertTrue(
            node.acknowledge_callback(ack_request, response()).accepted)

    def test_core_session_is_only_authority(self):
        node = FakeNode()
        self.assertTrue(node._session_matches(node._core.session_id))
        self.assertFalse(hasattr(node, '_session_id'))

    def test_public_state_exposes_physical_escalation(self):
        node = FakeNode()
        node._core.physical_stop_required = True
        self.assertEqual(
            node._public_gateway_state(),
            'PHYSICAL_ESTOP_REQUIRED',
        )

    def test_execute_aborts_fault_without_matching_old_result(self):
        node = FakeNode()
        command = SimpleNamespace(command_id='command-1')
        node._core.command_position = lambda *unused: command
        node._core.last_result = None
        node._core.fault_reason = 'external STOP fault'
        node._core.state = callback_namespace()[
            'GripperGatewayState'].FAULT_LATCHED
        node._core.refresh = lambda: None
        outcomes = []
        request = SimpleNamespace(
            normalized_position=0.2,
            speed_normalized=0.2,
            authorization_id='auth-1',
            expected_session_id='session-1',
            expected_tool_revision='revision-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=False,
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
            succeed=lambda: outcomes.append('succeed'),
        )
        result = node.execute_callback(goal_handle)
        self.assertEqual(outcomes, ['abort'])
        self.assertFalse(result.success)
        self.assertEqual(result.command_id, 'command-1')
        self.assertIn('external STOP fault', result.detail)
        self.assertFalse(node._busy)

    def test_execute_sends_cancel_stop_once_while_verification_is_pending(self):
        node = FakeNode()
        command = SimpleNamespace(command_id='command-1')
        node._core.command_position = lambda *unused: command
        refresh_count = []

        def refresh():
            refresh_count.append(True)
            if len(refresh_count) == 1:
                node._core.state = SimpleNamespace(value='STOPPING')
                return
            node._core.last_result = SimpleNamespace(
                command_id='command-1', success=False,
                detail='stationary STOP verified')
            node._core.state = SimpleNamespace(value='FAULT_LATCHED')

        node._core.refresh = refresh
        outcomes = []
        request = SimpleNamespace(
            normalized_position=0.2,
            speed_normalized=0.2,
            authorization_id='auth-1',
            expected_session_id='session-1',
            expected_tool_revision='revision-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=True,
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
            succeed=lambda: outcomes.append('succeed'),
        )
        result = node.execute_callback(goal_handle)
        self.assertEqual(
            node._core.stop_calls,
            [('action cancellation', 'session-1')],
        )
        self.assertEqual(outcomes, ['canceled'])
        self.assertFalse(result.success)
        self.assertFalse(node._busy)

    def test_physical_escalation_invalidates_matching_success_result(self):
        node = FakeNode()
        command = SimpleNamespace(command_id='command-1')
        node._core.command_position = lambda *unused: command
        node._core.last_result = SimpleNamespace(
            command_id='command-1', success=True,
            detail='stale success')
        node._core.physical_stop_required = True
        node._core.fault_reason = 'physical isolation required'
        node._core.state = callback_namespace()[
            'GripperGatewayState'].FAULT_LATCHED
        node._core.refresh = lambda: None
        outcomes = []
        request = SimpleNamespace(
            normalized_position=0.2,
            speed_normalized=0.2,
            authorization_id='auth-1',
            expected_session_id='session-1',
            expected_tool_revision='revision-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=False,
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
            succeed=lambda: outcomes.append('succeed'),
        )
        result = node.execute_callback(goal_handle)
        self.assertEqual(outcomes, ['abort'])
        self.assertFalse(result.success)
        self.assertEqual(result.final_state, 'PHYSICAL_ESTOP_REQUIRED')
        self.assertNotIn('stale success', result.detail)
        self.assertFalse(node._busy)

    def test_ros_shutdown_escalates_active_gripper_action(self):
        node = FakeNode(ok=lambda: False)
        command = SimpleNamespace(command_id='command-1')
        node._core.command_position = lambda *unused: command
        node._core.motion_safety_unresolved = True
        outcomes = []
        request = SimpleNamespace(
            normalized_position=0.2,
            speed_normalized=0.2,
            authorization_id='auth-1',
            expected_session_id='session-1',
            expected_tool_revision='revision-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=False,
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
            succeed=lambda: outcomes.append('succeed'),
        )
        result = node.execute_callback(goal_handle)
        self.assertEqual(outcomes, ['abort'])
        self.assertFalse(result.success)
        self.assertEqual(
            node._core.boundary_calls,
            ['ROS shutdown during active gripper action'],
        )
        self.assertEqual(result.final_state, 'PHYSICAL_ESTOP_REQUIRED')
        self.assertIn('physical isolation', result.detail)
        self.assertFalse(node._busy)


if __name__ == '__main__':
    unittest.main()
