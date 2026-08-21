from pathlib import Path
import sys
import unittest
from unittest import mock


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))
sys.path.insert(0, str(PACKAGE_ROOT / 'scripts'))

import v1_cmd_guard as guard_wrapper  # noqa: E402


class _Vector:

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0


class _Twist:

    def __init__(self):
        self.linear = _Vector()
        self.angular = _Vector()


class _Bool:

    def __init__(self):
        self.data = False


class _TriggerResponse:

    def __init__(self, success=False, message=''):
        self.success = bool(success)
        self.message = str(message)


class _FakeTime:

    def __init__(self, seconds=0.0):
        self.seconds = float(seconds)

    @classmethod
    def now(cls):
        return cls(100.0)

    def to_sec(self):
        return self.seconds


class _FakePublisher:

    def __init__(self, topic):
        self.topic = topic
        self.messages = []

    def publish(self, message):
        if isinstance(message, _Twist):
            self.messages.append((
                message.linear.x,
                message.linear.y,
                message.linear.z,
                message.angular.x,
                message.angular.y,
                message.angular.z,
            ))
        else:
            self.messages.append(bool(message.data))


class _FakeRospy:

    Time = _FakeTime

    def __init__(self, profile_file):
        self.params = {'~profile_file': str(profile_file)}
        self.publishers = []
        self.subscribers = {}
        self.services = []
        self.timers = []
        self.shutdown_callback = None

    def get_param(self, name, default=None):
        return self.params.get(name, default)

    def Publisher(self, topic, _message_type, **_kwargs):
        publisher = _FakePublisher(topic)
        self.publishers.append(publisher)
        return publisher

    def Subscriber(self, topic, _message_type, callback, **_kwargs):
        self.subscribers[topic] = callback
        return callback

    def Service(self, name, _service_type, callback):
        self.services.append((name, callback))
        return callback

    def Timer(self, duration, callback):
        self.timers.append((duration, callback))
        return callback

    @staticmethod
    def Duration(seconds):
        return float(seconds)

    def on_shutdown(self, callback):
        self.shutdown_callback = callback

    @staticmethod
    def get_name():
        return '/pure_fake_v1_cmd_guard'


class _FakeRosgraph:

    class Master:

        def __init__(self, _name):
            pass

        @staticmethod
        def getSystemState():
            return [], [], []


class _FakeTf2:

    class Buffer:

        calls = 0

        @classmethod
        def lookup_transform(cls, *_args, **_kwargs):
            cls.calls += 1
            raise LookupError('pure fake has no TF evidence')

    class TransformListener:

        def __init__(self, _buffer):
            pass


class GuardLocalizationContractTest(unittest.TestCase):

    def test_guard_requires_fresh_localization_ready_for_rearm_and_output(self):
        source = (PACKAGE_ROOT / 'scripts' / 'v1_cmd_guard.py').read_text(
            encoding='utf-8')
        self.assertIn("'/v1/localization/ready'", source)
        self.assertIn('localization_ready_lost', source)
        self.assertIn('localization_ready_stale', source)
        self.assertIn("'/v1/cmd_guard/stop_latched'", source)
        self.assertIn('self._publish_stop_latched()', source)
        self.assertIn('self._stop_heartbeat_timer', source)
        self.assertIn('not self.localization_ready', source)
        self.assertLess(
            source.index('not self.localization_ready'),
            source.index('decision = evaluate_safety(',
                         source.index('def _health_ready')))
        self.assertNotIn('SimpleActionClient', source)
        self.assertNotIn('send_goal', source)

        fake_rospy = _FakeRospy(
            PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml')
        topology_validator = mock.Mock(
            side_effect=RuntimeError('pure fake has no topology evidence'))
        _FakeTf2.Buffer.calls = 0
        with mock.patch.object(
                guard_wrapper.time, 'monotonic', return_value=10.0), \
                mock.patch.object(
                    guard_wrapper, 'validate_topology',
                    topology_validator):
            guard = guard_wrapper.V1CommandGuard(
                fake_rospy, _FakeRosgraph, _FakeTf2, _Twist, object,
                object, _Bool, object, _TriggerResponse)
            self.assertEqual(guard.stop_latched_publisher.messages, [True])
            self.assertEqual(guard.publisher.messages, [])
            requested = _Twist()
            requested.linear.x = 0.18
            requested.angular.z = 0.45
            fake_rospy.subscribers['/v1/nav_cmd_vel'](requested)
            guard._timer(None)
            zero = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            self.assertEqual(guard.publisher.messages, [zero])
            self.assertEqual(_FakeTf2.Buffer.calls, 1)
            self.assertEqual(topology_validator.call_count, 1)
            self.assertIsNone(guard.last_tf)
            self.assertFalse(guard.tf_owner_ok)
            self.assertFalse(guard.localization_ready)
            self.assertTrue(guard.latch.latched)
            self.assertIsNotNone(fake_rospy.shutdown_callback)
            fake_rospy.shutdown_callback()
            self.assertEqual(guard.publisher.messages[1:], [zero] * 5)

        self.assertFalse(guard.allow_nonzero)
        self.assertFalse(guard.driver_timeout_verified)
        self.assertEqual(
            [publisher.topic for publisher in fake_rospy.publishers],
            ['/v1/driver_cmd_vel', '/v1/cmd_guard/stop_latched'])
        self.assertNotIn('/cmd_vel', fake_rospy.subscribers)
        self.assertNotIn('/cmd_vel', [
            publisher.topic for publisher in fake_rospy.publishers])
        self.assertEqual([name for name, _ in fake_rospy.services], ['~rearm'])
        self.assertEqual(len(guard.publisher.messages), 6)
        self.assertTrue(all(
            components == zero
            for components in guard.publisher.messages))
        self.assertGreaterEqual(
            len(guard.stop_latched_publisher.messages), 1)
        self.assertTrue(guard.stop_latched_publisher.messages[0])

    def test_navigation_gateway_launch_is_inert_by_default(self):
        source = (PACKAGE_ROOT / 'launch' / 'v1_navigation.launch').read_text(
            encoding='utf-8')
        self.assertIn(
            '<arg name="enable_goal_gateway" default="false"', source)
        self.assertIn(
            '<arg name="allow_goal_forwarding" default="false"', source)
        self.assertIn('type="v1_navigation_gateway.py"', source)
        core = (PACKAGE_ROOT / 'launch' / 'v1_navigation_core.launch').read_text(
            encoding='utf-8')
        self.assertIn('name="move_base"', core)
        self.assertIn(
            'from="move_base_simple/goal" '
            'to="/v1/private_move_base_simple/goal"', core)


if __name__ == '__main__':
    unittest.main()
