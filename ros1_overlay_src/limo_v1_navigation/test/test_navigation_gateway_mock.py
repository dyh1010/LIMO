from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
import unittest
from unittest import mock


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

import v1_navigation_gateway as wrapper  # noqa: E402


class Message:
    def __init__(self):
        self.data = ''


class TriggerResponse:
    def __init__(self, success=False, message=''):
        self.success = success
        self.message = message


class MoveBaseGoal:
    def __init__(self):
        self.target_pose = None


class GoalStatus:
    SUCCEEDED = 3
    PREEMPTED = 2
    RECALLED = 8


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeClient:
    def __init__(self):
        self.sent = []
        self.cancel_count = 0

    def wait_for_server(self, _duration):
        return True

    def send_goal(self, goal, **callbacks):
        self.sent.append((goal, callbacks))

    def cancel_all_goals(self):
        self.cancel_count += 1


class FakeActionlib:
    def __init__(self, client):
        self.client = client

    def SimpleActionClient(self, _name, _action):
        return self.client


class FakeRospy:
    class Duration:
        def __init__(self, seconds):
            self.seconds = seconds

    def __init__(self, params=None):
        self.params = params or {}
        self.publishers = []
        self.subscribers = {}

    def get_param(self, name, default=None):
        return self.params.get(name, default)

    def Publisher(self, _name, _kind, **_kwargs):
        publisher = FakePublisher()
        self.publishers.append(publisher)
        return publisher

    def Subscriber(self, name, _kind, callback, **_kwargs):
        self.subscribers[name] = callback
        return callback

    def Service(self, _name, _kind, callback):
        return callback

    def Timer(self, _duration, callback):
        return callback


def pose_message():
    return SimpleNamespace(
        header=SimpleNamespace(seq=0, frame_id='map'),
        pose=SimpleNamespace(
            position=SimpleNamespace(x=1.0, y=2.0),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)))


class NavigationGatewayMockTest(unittest.TestCase):

    def _gateway(self, enabled=True):
        rospy = FakeRospy({
            '~enabled': enabled,
            '~allow_goal_forwarding': enabled,
            '~localization_timeout_s': 0.5,
            '~guard_timeout_s': 0.5,
        })
        client = FakeClient()
        gateway = wrapper.V1NavigationGateway(
            rospy, FakeActionlib(client), object, MoveBaseGoal, object, object,
            Message, object, TriggerResponse, GoalStatus)
        return gateway, client

    @staticmethod
    def _make_ready(gateway):
        now = time.monotonic()
        gateway.gate.update_localization(True, now)
        gateway.gate.update_action_server(True)
        gateway.guard_receive = now
        gateway.guard_latched = False
        decision = gateway.gate.arm(now, gateway.localization_timeout_s)
        if not decision.accepted:
            raise AssertionError(decision.reason)

    def _assert_invalidation_cannot_late_send(self, invalidator):
        gateway, client = self._gateway()
        self._make_ready(gateway)
        original_commit = gateway.goal_gate.commit
        accepted = threading.Event()
        continue_callback = threading.Event()

        def pause_before_commit(generation, send_callback):
            accepted.set()
            continue_callback.wait(timeout=2.0)
            return original_commit(generation, send_callback)

        gateway.goal_gate.commit = pause_before_commit
        callback = threading.Thread(target=gateway._goal_callback,
                                    args=(pose_message(),))
        callback.start()
        self.assertTrue(accepted.wait(timeout=2.0))
        stop = threading.Thread(target=invalidator, args=(gateway,))
        stop.start()
        continue_callback.set()
        callback.join(timeout=2.0)
        stop.join(timeout=2.0)
        self.assertFalse(callback.is_alive())
        self.assertFalse(stop.is_alive())
        self.assertEqual(len(client.sent), 0)
        self.assertGreaterEqual(client.cancel_count, 1)

    def test_cancel_between_policy_accept_and_send_never_late_sends(self):
        self._assert_invalidation_cannot_late_send(
            lambda gateway: gateway._cancel('mock_cancel'))

    def test_ready_loss_between_policy_accept_and_send_never_late_sends(self):
        self._assert_invalidation_cannot_late_send(
            lambda gateway: gateway._localization_callback(
                SimpleNamespace(data=False)))

    def test_stop_latch_between_policy_accept_and_send_never_late_sends(self):
        self._assert_invalidation_cannot_late_send(
            lambda gateway: gateway._stop_latched_callback(
                SimpleNamespace(data=True)))

    def test_disabled_gateway_never_forwards_but_cancel_and_status_work(self):
        gateway, client = self._gateway(enabled=False)
        gateway._goal_callback(pose_message())
        self.assertEqual(client.sent, [])
        response = gateway._cancel_service(None)
        self.assertTrue(response.success)
        self.assertGreaterEqual(client.cancel_count, 1)
        self.assertGreaterEqual(len(gateway.status_publisher.messages), 2)

    def test_stale_guard_heartbeat_cancels_an_active_goal(self):
        gateway, client = self._gateway()
        self._make_ready(gateway)
        gateway._goal_callback(pose_message())
        self.assertEqual(len(client.sent), 1)
        gateway.guard_receive = time.monotonic() - 1.0
        gateway._timer(None)
        self.assertGreaterEqual(client.cancel_count, 1)
        self.assertIsNone(gateway.gate.active_goal)
        self.assertFalse(gateway.gate.armed)

    def test_normal_ready_armed_path_sends_exactly_once(self):
        gateway, client = self._gateway()
        self._make_ready(gateway)
        gateway._goal_callback(pose_message())
        self.assertEqual(len(client.sent), 1)

    def test_old_done_callback_cannot_corrupt_a_new_generation(self):
        gateway, client = self._gateway()
        self._make_ready(gateway)
        gateway._goal_callback(pose_message())
        old_callbacks = client.sent[-1][1]
        gateway._cancel('mock_cancel')
        with mock.patch.object(gateway.gate, 'complete') as complete:
            old_callbacks['done_cb'](GoalStatus.SUCCEEDED, object())
        complete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
