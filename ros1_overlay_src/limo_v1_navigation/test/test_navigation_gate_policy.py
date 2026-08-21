from pathlib import Path
import sys
import threading
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.navigation_gate_policy import (  # noqa: E402
    ACTIVE,
    BLOCKED,
    GoalGenerationGate,
    GoalRequest,
    NavigationGate,
    SUCCEEDED,
)


class NavigationGatePolicyTest(unittest.TestCase):

    def setUp(self):
        self.gate = NavigationGate()
        self.goal = GoalRequest('request-1', 'map', 1.0, 2.0, 0.1)

    def _ready(self, now=1.0):
        self.gate.update_localization(True, now)
        self.gate.update_action_server(True)

    def test_goal_is_blocked_until_fresh_ready_and_explicit_arm(self):
        self.assertFalse(self.gate.submit(self.goal, 1.0, 0.5).accepted)
        self._ready()
        self.assertFalse(self.gate.submit(self.goal, 1.1, 0.5).accepted)
        self.assertTrue(self.gate.arm(1.1, 0.5).accepted)
        self.assertTrue(self.gate.submit(self.goal, 1.1, 0.5).accepted)
        self.assertEqual(self.gate.state, ACTIVE)

    def test_ready_loss_cancels_and_disarms(self):
        self._ready()
        self.gate.arm(1.1, 0.5)
        self.gate.submit(self.goal, 1.1, 0.5)
        self.gate.update_localization(False, 1.2)
        self.assertEqual(self.gate.state, BLOCKED)
        self.assertTrue(self.gate.cancel_required)
        self.assertFalse(self.gate.armed)
        self.assertIsNone(self.gate.active_goal)

    def test_stale_ready_and_action_server_loss_fail_closed(self):
        self._ready()
        self.assertFalse(self.gate.arm(1.5, 0.5).accepted)
        self._ready(2.0)
        self.gate.arm(2.1, 0.5)
        self.gate.submit(self.goal, 2.1, 0.5)
        self.gate.update_action_server(False)
        self.assertEqual(self.gate.state, BLOCKED)
        self.assertTrue(self.gate.cancel_required)

    def test_active_goal_is_canceled_when_ready_heartbeat_goes_stale(self):
        self._ready()
        self.gate.arm(1.1, 0.5)
        self.gate.submit(self.goal, 1.1, 0.5)
        self.gate.tick(1.5, 0.5)
        self.assertEqual(self.gate.state, BLOCKED)
        self.assertTrue(self.gate.cancel_required)

    def test_cancel_has_priority_and_old_goal_never_resumes(self):
        self._ready()
        self.gate.arm(1.1, 0.5)
        self.gate.submit(self.goal, 1.1, 0.5)
        self.gate.cancel('priority_stop')
        self.assertFalse(self.gate.armed)
        self.assertIsNone(self.gate.active_goal)
        self.assertFalse(self.gate.submit(self.goal, 1.2, 0.5).accepted)

    def test_terminal_result_disarms_and_duplicate_request_is_rejected(self):
        self._ready()
        self.gate.arm(1.1, 0.5)
        self.gate.submit(self.goal, 1.1, 0.5)
        self.gate.complete(SUCCEEDED, 'arrived')
        self.assertFalse(self.gate.armed)
        self._ready(1.2)
        self.gate.arm(1.2, 0.5)
        self.assertFalse(self.gate.submit(self.goal, 1.2, 0.5).accepted)

    def test_invalid_goal_values_are_rejected(self):
        cases = (
            GoalRequest('', 'map', 1.0, 2.0, 0.0),
            GoalRequest('x', 'odom', 1.0, 2.0, 0.0),
            GoalRequest('x', 'map', float('nan'), 2.0, 0.0),
        )
        for goal in cases:
            with self.subTest(goal=goal):
                with self.assertRaises(ValueError):
                    self.gate.submit(goal, 1.0, 0.5)

    def test_cancel_invalidates_accepted_goal_before_send(self):
        gate = GoalGenerationGate()
        reserved = gate.reserve()
        ready_to_invalidate = threading.Barrier(2)
        invalidated = threading.Event()
        events = []
        committed = []

        def delayed_send():
            ready_to_invalidate.wait()
            invalidated.wait(timeout=2.0)
            committed.append(gate.commit(
                reserved, lambda: events.append('goal_sent')))

        thread = threading.Thread(target=delayed_send)
        thread.start()
        ready_to_invalidate.wait()
        gate.invalidate(lambda: events.append('cancel_sent'))
        invalidated.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(committed, [False])
        self.assertEqual(events, ['cancel_sent'])

    def test_ready_loss_or_stop_invalidation_rejects_old_callbacks(self):
        for reason in ('ready_loss', 'stop_latched'):
            with self.subTest(reason=reason):
                gate = GoalGenerationGate()
                generation = gate.reserve()
                self.assertTrue(gate.is_current(generation))
                gate.invalidate()
                self.assertFalse(gate.is_current(generation))


if __name__ == '__main__':
    unittest.main()
