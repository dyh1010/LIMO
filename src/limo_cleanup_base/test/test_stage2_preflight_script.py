from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
PREFLIGHT = WORKSPACE_ROOT / 'scripts' / 'tracked_base_stage2_preflight.sh'


def _source():
    return PREFLIGHT.read_text(encoding='utf-8')


def _assert_retired_contract(source):
    for marker in (
            'FIELD_RUNTIME_AUTHORITY=ROS1_NOETIC',
            'LEGACY_ROS2_OFFLINE_ONLY',
            'LIMO_ALLOW_LEGACY_ROS2_OFFLINE',
            'NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE'):
        assert marker in source
    assert source.count('exit 64') >= 2
    assert 'LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS' not in source
    assert 'PASS:' not in source


def test_preflight_sources_ros_before_enabling_nounset():
    source = _source()
    _assert_retired_contract(source)
    assert 'source ' not in source
    assert '/opt/ros/' not in source
    assert 'install/setup.bash' not in source


def test_preflight_requires_all_physical_acknowledgements():
    source = _source()
    _assert_retired_contract(source)
    for legacy_override in (
            'TRACKED_BASE_PHYSICAL_CHECKLIST_CONFIRMED',
            'TRACKED_BASE_ESTOP_TESTED',
            'TRACKED_BASE_COMMAND_MODE_WRITE_ACK'):
        assert legacy_override not in source
    assert 'permanently retired' in source


def test_preflight_cannot_inspect_an_isolated_or_overridden_ros_graph():
    source = _source()
    _assert_retired_contract(source)
    for token in (
            'ROS_DOMAIN_ID', 'ROS_LOCALHOST_ONLY', 'ROS_DISCOVERY_SERVER',
            'CYCLONEDDS_URI', 'FASTRTPS_DEFAULT_PROFILES_FILE',
            'node list', 'topic info'):
        assert token not in source


def test_preflight_requires_exact_platform_uart_identity():
    source = _source()
    _assert_retired_contract(source)
    for token in (
            'TRACKED_BASE_PORT', 'EXPECTED_SYSFS_DEVICE', 'EXPECTED_DRIVER',
            '/dev/', 'ttyTHS', 'limo_base'):
        assert token not in source


def test_preflight_rejects_console_getty_and_missing_dialout_access():
    source = _source()
    _assert_retired_contract(source)
    for token in ('dialout', '/proc/cmdline', 'systemctl', 'getty', 'console='):
        assert token not in source


def test_preflight_fails_closed_when_inspection_tools_or_queries_fail():
    source = _source()
    _assert_retired_contract(source)
    for token in ('fuser', 'readlink', 'timeout ', 'ros2 ', 'python3 ', 'ps -'):
        assert token not in source


def test_preflight_blocks_when_ros_graph_query_fails():
    source = _source()
    _assert_retired_contract(source)
    assert 'ROS node query' not in source
    assert 'process ownership query' not in source
    assert 'STAGE2_PREFLIGHT_PASS' not in source


def test_preflight_checks_all_known_motion_topic_publishers():
    source = _source()
    _assert_retired_contract(source)
    for topic in (
            '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop',
            '/limo/vel_cmd', '/cleanup/base/safe_cmd_vel'):
        assert topic not in source


def test_preflight_is_read_only_and_foxy_compatible():
    source = _source()
    _assert_retired_contract(source)
    for token in ('ros2 ', 'launch ', 'run ', ' topic pub ', ' service call '):
        assert token not in source
