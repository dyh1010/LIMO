import ast
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
VERIFIER = WORKSPACE_ROOT / 'scripts' / 'verify_tracked_zero_output.py'
SMOKE = WORKSPACE_ROOT / 'scripts' / 'smoke_test_tracked_zero_guard.sh'


def _source():
    return VERIFIER.read_text(encoding='utf-8')


def test_verifier_uses_python38_syntax_and_fixed_topics():
    source = _source()
    ast.parse(source, filename=str(VERIFIER), feature_version=(3, 8))
    assert "SAFE_COMMAND_TOPIC = '/cleanup/base/safe_cmd_vel'" in source
    assert "EXPECTED_PUBLISHER_NODE = 'cleanup_tracked_base_zero_output'" in source
    for topic in (
            '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop', '/limo/vel_cmd'):
        assert topic in source


def test_verifier_is_strictly_observational():
    source = _source()
    forbidden = (
        'create_publisher',
        '.publish(',
        'ros2 topic pub',
        'ros2 service call',
        'ros2 action send_goal',
        'subprocess',
    )
    for token in forbidden:
        assert token not in source
    assert 'create_subscription' in source
    assert 'self.command_subscription = self.create_subscription' in source


def test_verifier_checks_all_twist_axes_and_fails_closed():
    source = _source()
    for field in (
            'message.linear.x', 'message.linear.y', 'message.linear.z',
            'message.angular.x', 'message.angular.y', 'message.angular.z'):
        assert field in source
    assert 'math.isfinite' in source
    assert 'len(publishers) != 1' in source
    assert 'len(subscribers) != 1' in source
    assert 'get_subscriptions_info_by_topic' in source
    assert 'must have no endpoints' in source
    assert 'MINIMUM_SAMPLES = 10' in source
    assert 'ZERO_OUTPUT_GUARD_PASS' in source
    assert 'ZERO_OUTPUT_GUARD_BLOCKED' in source


def test_guard_smoke_is_local_only_and_never_starts_vendor_driver():
    source = SMOKE.read_text(encoding='utf-8')
    assert 'tracked_base_zero_output.launch.py' in source
    assert 'verify_tracked_zero_output.py' in source
    assert 'RMW_IMPLEMENTATION=rmw_cyclonedds_cpp' in source
    assert 'NetworkInterface name="lo"' in source
    assert 'TRACKED_ZERO_GUARD_SMOKE_PASS' in source
    assert 'setsid ros2 launch' in source
    assert 'timeout -k 2 15' in source
    assert 'kill -INT -- "-${launch_pid}"' in source
    assert 'kill -TERM -- "-${launch_pid}"' in source
    assert 'kill -KILL -- "-${launch_pid}"' in source
    assert 'launch_log="$(mktemp)"' in source
    assert '/opt/ros/foxy/setup.bash' in source
    assert 'tracked_base_vendor_stage2.launch.py' not in source
    assert 'ros2 run limo_base' not in source
    assert 'ros2 launch limo_base' not in source
