from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
AUDIT_SCRIPT = WORKSPACE_ROOT / 'scripts' / 'robot_tracked_readonly_audit.sh'


def _source():
    return AUDIT_SCRIPT.read_text(encoding='utf-8')


def _assert_retired_contract(source):
    for marker in (
            'FIELD_RUNTIME_AUTHORITY=ROS1_NOETIC',
            'LEGACY_ROS2_OFFLINE_ONLY',
            'LIMO_ALLOW_LEGACY_ROS2_OFFLINE',
            'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'):
        assert marker in source
    assert source.count('exit 64') >= 2
    assert 'LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS' not in source


def test_audit_sources_foxy_and_colcon_before_enabling_nounset():
    source = _source()
    _assert_retired_contract(source)
    assert 'source ' not in source
    assert '/opt/ros/' not in source
    assert 'install/setup.bash' not in source


def test_audit_uses_foxy_compatible_topic_info_cli():
    source = _source()
    _assert_retired_contract(source)
    assert 'ros2 ' not in source
    assert 'topic info' not in source
    assert 'node list' not in source


def test_audit_contains_no_ros_publish_or_hardware_launch_commands():
    source = _source()
    _assert_retired_contract(source)
    for token in (
            'ros2 ', 'python3 ', 'setsid ', 'launch ', ' topic pub ',
            ' action send_goal ', ' service call ', '/cmd_vel'):
        assert token not in source


def test_audit_collects_platform_uart_identity_without_opening_ports():
    source = _source()
    _assert_retired_contract(source)
    for token in (
            '/dev/', '/sys/class/tty', '/proc/device-tree', 'udevadm',
            'fuser', 'ttyTHS', 'READ_ONLY_AUDIT_COMPLETE',
            'EVIDENCE_CAPTURED_NOT_ACCEPTANCE_PASS'):
        assert token not in source
    assert 'permanently retired' in source
