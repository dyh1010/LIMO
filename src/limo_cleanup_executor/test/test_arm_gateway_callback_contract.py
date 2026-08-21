"""ROS callback contract tests using source and a fake core only."""

import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
NODE = ROOT / 'limo_cleanup_executor' / 'arm_gateway_node.py'


class FakeLogger:
    """Collect callback log messages without constructing a ROS node."""

    def __init__(self):
        self.messages = []

    def warning(self, message):
        self.messages.append(('warning', message))


class FakeCore:
    """Minimal core contract used by STOP and ACK callback probes."""

    def __init__(self):
        self.session_id = 'session-1'
        self.state = SimpleNamespace(value='READY')
        self.snapshot = None
        self.active_command = None
        self.last_result = None
        self.fault_reason = ''
        self.motion_calls = []
        self.stop_calls = []
        self.ack_calls = []
        self.motion_safety_unresolved = False
        self.boundary_calls = []

    def command_named_joint_pose(
            self, name, speed_grade, authorization_id,
            expected_session_id):
        self.motion_calls.append((
            'named', name, speed_grade, authorization_id,
            expected_session_id,
        ))
        return self._complete_command('named-command')

    def command_tcp_move(
            self, target, speed_grade, mode, authorization_id,
            expected_session_id):
        self.motion_calls.append((
            'tcp', list(target), speed_grade, mode, authorization_id,
            expected_session_id,
        ))
        return self._complete_command('tcp-command')

    def _complete_command(self, command_id):
        self.last_result = SimpleNamespace(
            command_id=command_id,
            success=True,
            detail='fake target reached',
        )
        return SimpleNamespace(command_id=command_id)

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
            self.state = SimpleNamespace(value='FAULT_LATCHED')
            self.fault_reason = 'physical safety escalation'
            self.motion_safety_unresolved = True
            return True
        return False


def callback_namespace(ok=None):
    """Load only callback functions with tiny ROS enum stand-ins."""
    tree = ast.parse(NODE.read_text(encoding='utf-8'), filename=str(NODE))
    wanted = {
        'goal_callback',
        'cancel_callback',
        'execute_callback',
        '_fill_result',
        'stop_callback',
        'acknowledge_callback',
        '_session_matches',
    }
    methods = []
    for item in tree.body:
        if isinstance(item, ast.ClassDef) and item.name == 'ArmGatewayNode':
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
        'GatewayState': SimpleNamespace(
            READY=SimpleNamespace(value='READY'),
            FAULT_LATCHED=SimpleNamespace(value='FAULT_LATCHED'),
        ),
        'ExecuteArmMotion': SimpleNamespace(
            Result=SimpleNamespace,
            Goal=SimpleNamespace(
                KIND_NAMED_JOINT_POSE=1,
                KIND_BOUNDED_TCP_MOVE=2,
            ),
        ),
        'ArmGatewayError': RuntimeError,
        'MotionRejected': ValueError,
        'rclpy': SimpleNamespace(ok=ok or (lambda: True)),
        'time': __import__('time'),
    }
    exec(compile(module, str(NODE), 'exec'), namespace)
    return namespace


class FakeNode:
    """Object matching the fields used by extracted callbacks."""

    def __init__(self, ok=None):
        namespace = callback_namespace(ok=ok)
        for name in (
                '_session_matches', 'goal_callback', 'cancel_callback',
                'execute_callback', '_fill_result', 'stop_callback',
                'acknowledge_callback'):
            setattr(self, name, namespace[name].__get__(self, FakeNode))
        self._busy = False
        self._core = FakeCore()
        self._lifecycle_lock = __import__('threading').RLock()
        self._logger = FakeLogger()
        self.feedback_hz = 20.0
        self._publish_feedback = lambda unused_goal_handle: None

    def get_logger(self):
        return self._logger


def response():
    return SimpleNamespace(accepted=False, gateway_state='', detail='')


class ArmGatewayCallbackContractTest(unittest.TestCase):
    """Drive goal/STOP/ACK gates without importing rclpy."""

    def test_goal_requires_current_session_authorization_kind_and_ready(self):
        node = FakeNode()
        request = SimpleNamespace(
            expected_session_id='session-1',
            authorization_id='auth-1',
            kind=1,
        )
        self.assertEqual(node.goal_callback(request), 'ACCEPT')
        self.assertTrue(node._busy)

        cases = (
            {'expected_session_id': 'stale'},
            {'authorization_id': ''},
            {'kind': 99},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                probe = FakeNode()
                candidate = SimpleNamespace(**request.__dict__)
                for name, value in updates.items():
                    setattr(candidate, name, value)
                self.assertEqual(probe.goal_callback(candidate), 'REJECT')
                self.assertFalse(probe._busy)

        busy = FakeNode()
        busy._busy = True
        self.assertEqual(busy.goal_callback(request), 'REJECT')

    def test_cancel_acceptance_is_only_a_request_not_stationary_ack(self):
        node = FakeNode()
        self.assertEqual(node.cancel_callback(object()), 'ACCEPT')
        self.assertEqual(node._core.stop_calls, [])

    def test_action_execute_forwards_request_session_for_both_motion_kinds(self):
        cases = (
            (
                SimpleNamespace(
                    kind=1,
                    KIND_NAMED_JOINT_POSE=1,
                    named_pose='inspection',
                    speed_grade=5,
                    authorization_id='motion-auth-1',
                    expected_session_id='session-1',
                ),
                ('named', 'inspection', 5, 'motion-auth-1', 'session-1'),
                'named-command',
            ),
            (
                SimpleNamespace(
                    kind=2,
                    KIND_NAMED_JOINT_POSE=1,
                    tcp_target=[120.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                    speed_grade=5,
                    tcp_mode=0,
                    authorization_id='motion-auth-2',
                    expected_session_id='session-1',
                ),
                (
                    'tcp', [120.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                    5, 0, 'motion-auth-2', 'session-1',
                ),
                'tcp-command',
            ),
        )
        for request, expected_call, expected_command_id in cases:
            with self.subTest(kind=request.kind):
                node = FakeNode()
                goal_handle = SimpleNamespace(
                    request=request,
                    is_cancel_requested=False,
                    succeed=lambda: None,
                    abort=lambda: None,
                    canceled=lambda: None,
                )
                result = node.execute_callback(goal_handle)
                self.assertTrue(result.success)
                self.assertEqual(result.command_id, expected_command_id)
                self.assertEqual(node._core.motion_calls, [expected_call])
                self.assertFalse(node._busy)

    def test_action_waits_through_retry_pending_fault_until_resolved_result(self):
        calls = []
        node = FakeNode(ok=lambda: len(calls) < 5)
        command = SimpleNamespace(command_id='named-command')

        def command_named(*unused):
            node._core.motion_safety_unresolved = True
            node._core.state = SimpleNamespace(value='FAULT_LATCHED')
            return command

        node._core.command_named_joint_pose = command_named

        def feedback(unused_goal_handle):
            calls.append(node._core.state.value)
            if len(calls) == 2:
                node._core.motion_safety_unresolved = False
                node._core.last_result = SimpleNamespace(
                    command_id='named-command',
                    success=False,
                    detail='stationary STOP verified',
                )

        node._publish_feedback = feedback
        outcomes = []
        request = SimpleNamespace(
            kind=1,
            KIND_NAMED_JOINT_POSE=1,
            named_pose='inspection',
            speed_grade=5,
            authorization_id='motion-auth',
            expected_session_id='session-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=False,
            succeed=lambda: outcomes.append('succeed'),
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
        )
        result = node.execute_callback(goal_handle)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(outcomes, ['abort'])
        self.assertFalse(result.success)
        self.assertEqual(result.detail, 'stationary STOP verified')
        self.assertEqual(node._core.boundary_calls, [])
        self.assertFalse(node._busy)

    def test_ros_shutdown_escalates_active_action_and_returns_result(self):
        node = FakeNode(ok=lambda: False)
        node._core.motion_safety_unresolved = True
        outcomes = []
        request = SimpleNamespace(
            kind=1,
            KIND_NAMED_JOINT_POSE=1,
            named_pose='inspection',
            speed_grade=5,
            authorization_id='motion-auth',
            expected_session_id='session-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=False,
            succeed=lambda: outcomes.append('succeed'),
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
        )
        result = node.execute_callback(goal_handle)
        self.assertEqual(outcomes, ['abort'])
        self.assertFalse(result.success)
        self.assertEqual(
            node._core.boundary_calls,
            ['ROS shutdown during active arm action'],
        )
        self.assertIn('physical safety escalation', result.detail)
        self.assertFalse(node._busy)

    def test_stop_error_escalates_before_action_returns(self):
        node = FakeNode(ok=lambda: True)
        node._core.motion_safety_unresolved = True

        def fail_motion(*unused):
            raise RuntimeError('sanitized core error')

        node._core.command_named_joint_pose = fail_motion
        outcomes = []
        request = SimpleNamespace(
            kind=1,
            KIND_NAMED_JOINT_POSE=1,
            named_pose='inspection',
            speed_grade=5,
            authorization_id='motion-auth',
            expected_session_id='session-1',
        )
        goal_handle = SimpleNamespace(
            request=request,
            is_cancel_requested=False,
            succeed=lambda: outcomes.append('succeed'),
            abort=lambda: outcomes.append('abort'),
            canceled=lambda: outcomes.append('canceled'),
        )
        result = node.execute_callback(goal_handle)
        self.assertEqual(outcomes, ['abort'])
        self.assertFalse(result.success)
        self.assertEqual(
            node._core.boundary_calls,
            ['arm action failed before safe resolution'],
        )
        self.assertIn('physical safety escalation', result.detail)
        self.assertFalse(node._busy)

    def test_stop_rejects_stale_session_without_calling_core(self):
        node = FakeNode()
        request = SimpleNamespace(
            expected_session_id='stale', reason='operator STOP')
        result = node.stop_callback(request, response())
        self.assertFalse(result.accepted)
        self.assertIn('stale', result.detail)
        self.assertEqual(node._core.stop_calls, [])

    def test_stop_calls_core_and_reports_verification_pending(self):
        node = FakeNode()
        request = SimpleNamespace(
            expected_session_id='session-1', reason='operator STOP')
        result = node.stop_callback(request, response())
        self.assertTrue(result.accepted)
        self.assertEqual(
            node._core.stop_calls,
            [('operator STOP', 'session-1')],
        )
        self.assertEqual(result.gateway_state, 'STOPPING')
        self.assertIn('verification pending', result.detail)

    def test_stop_callback_is_not_blocked_by_busy_lifecycle_lock(self):
        node = FakeNode()
        node._busy = True
        request = SimpleNamespace(
            expected_session_id='session-1', reason='concurrent STOP')
        entered = threading.Event()
        returned = threading.Event()
        outcome = []

        def worker():
            entered.set()
            outcome.append(node.stop_callback(request, response()))
            returned.set()

        with node._lifecycle_lock:
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(entered.wait(timeout=1.0))
            self.assertTrue(returned.wait(timeout=1.0))
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertTrue(outcome[0].accepted)
        self.assertEqual(
            node._core.stop_calls,
            [('concurrent STOP', 'session-1')],
        )

    def test_ack_rejects_stale_session_and_forwards_authorization(self):
        node = FakeNode()
        stale = SimpleNamespace(
            expected_session_id='stale', authorization_id='review-1')
        stale_result = node.acknowledge_callback(stale, response())
        self.assertFalse(stale_result.accepted)
        self.assertEqual(node._core.ack_calls, [])

        valid = SimpleNamespace(
            expected_session_id='session-1', authorization_id='review-1')
        valid_result = node.acknowledge_callback(valid, response())
        self.assertTrue(valid_result.accepted)
        self.assertEqual(
            node._core.ack_calls,
            [('review-1', 'session-1')],
        )
        self.assertIn('was not modified', valid_result.detail)

    def test_ack_core_call_does_not_run_under_lifecycle_lock(self):
        node = FakeNode()
        lock_available = []

        def acknowledge(authorization_id, expected_session_id):
            def probe_lock():
                acquired = node._lifecycle_lock.acquire(timeout=0.5)
                lock_available.append(acquired)
                if acquired:
                    node._lifecycle_lock.release()

            thread = threading.Thread(target=probe_lock)
            thread.start()
            thread.join(timeout=1.0)
            self.assertFalse(thread.is_alive())
            node._core.ack_calls.append(
                (authorization_id, expected_session_id))
            return True

        node._core.acknowledge_local_fault = acknowledge
        valid = SimpleNamespace(
            expected_session_id='session-1', authorization_id='review-1')
        result = node.acknowledge_callback(valid, response())

        self.assertTrue(result.accepted)
        self.assertEqual(lock_available, [True])
        self.assertEqual(
            node._core.ack_calls,
            [('review-1', 'session-1')],
        )

    def test_core_session_is_the_only_node_session_authority(self):
        node = FakeNode()
        self.assertTrue(node._session_matches(node._core.session_id))
        self.assertFalse(hasattr(node, '_session_id'))


if __name__ == '__main__':
    unittest.main()
