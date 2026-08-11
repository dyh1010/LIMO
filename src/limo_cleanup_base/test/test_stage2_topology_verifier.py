import ast
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
VERIFIER = WORKSPACE_ROOT / 'scripts' / 'verify_tracked_stage2_topology.py'


def test_stage2_verifier_uses_python38_syntax():
    source = VERIFIER.read_text(encoding='utf-8')
    ast.parse(
        source,
        filename=str(VERIFIER),
        feature_version=(3, 8),
    )


def test_stage2_verifier_is_strictly_read_only():
    source = VERIFIER.read_text(encoding='utf-8')
    forbidden = (
        'create_publisher',
        'create_client',
        'ActionClient',
        'subprocess',
        'os.system',
        'send_goal',
        '/cleanup/base/cmd_vel_request',
        '/cleanup/base/motion_authorized',
        '/cleanup/base/safety_clear',
    )
    for token in forbidden:
        assert token not in source
    assert source.count('create_subscription(') == 1
    assert 'self.command_subscription = self.create_subscription' in source


def test_stage2_verifier_enforces_private_topology_and_public_isolation():
    source = VERIFIER.read_text(encoding='utf-8')
    assert "SAFE_COMMAND_TOPIC = '/cleanup/base/safe_cmd_vel'" in source
    assert "EXPECTED_GATEWAY = '/cleanup_tracked_base_zero_output'" in source
    assert "EXPECTED_DRIVER = '/limo_base_stage2'" in source
    for topic in (
            '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop',
            '/limo/vel_cmd', '/odom', '/imu', '/limo_status'):
        assert topic in source
    assert 'get_subscriptions_info_by_topic' in source
    assert 'len(publishers) != 1' in source
    assert 'len(subscribers) != 2' in source
    assert 'len(state_publisher_endpoints) != 1' in source
    assert 'STAGE2_TOPOLOGY_BLOCKED' in source
    assert 'STAGE2_TOPOLOGY_PASS' in source


def test_stage2_verifier_requires_finite_all_axis_zero_samples():
    source = VERIFIER.read_text(encoding='utf-8')
    assert 'math.isfinite' in source
    assert 'message.linear.y' in source
    assert 'message.linear.z' in source
    assert 'message.angular.x' in source
    assert 'message.angular.y' in source
    assert 'MINIMUM_SAMPLES = 10' in source
