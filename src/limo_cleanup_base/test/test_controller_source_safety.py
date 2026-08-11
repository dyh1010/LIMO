import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1]
CONTROLLER = (
    PACKAGE_ROOT / 'limo_cleanup_base' / 'tracked_base_controller.py')


def test_controller_uses_python38_syntax():
    ast.parse(
        CONTROLLER.read_text(encoding='utf-8'),
        filename=str(CONTROLLER),
        feature_version=(3, 8),
    )


def test_hardware_motion_default_is_false():
    source = CONTROLLER.read_text(encoding='utf-8')
    assert "declare_parameter('allow_base_motion', False)" in source
    assert "'output_topic', '/cleanup/base/safe_cmd_vel'" in source
    assert '/limo/vel_cmd' not in source


def test_controller_uses_monotonic_time_and_immediate_stop_callbacks():
    source = CONTROLLER.read_text(encoding='utf-8')
    assert 'return time.monotonic()' in source
    assert 'min(now - self.last_tick, self.control_period)' in source
    assert 'if not self.authorization:' in source
    assert 'if not self.safety_clear:' in source
    assert source.count('self._force_stop()') >= 3


def test_controller_shutdown_does_not_publish_on_invalid_context():
    source = CONTROLLER.read_text(encoding='utf-8')
    assert 'ExternalShutdownException' in source
    assert 'except (KeyboardInterrupt, ExternalShutdownException):' in source
    assert 'if rclpy.ok():\n            node.stop()' in source
    assert 'if rclpy.ok():\n            rclpy.shutdown()' in source


def test_controller_retains_all_subscription_handles():
    source = CONTROLLER.read_text(encoding='utf-8')
    assert 'self.request_subscription = self.create_subscription' in source
    assert (
        'self.authorization_subscription = self.create_subscription'
        in source)
    assert 'self.safety_subscription = self.create_subscription' in source
