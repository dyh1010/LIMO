from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
PREFLIGHT = WORKSPACE_ROOT / 'scripts' / 'tracked_base_stage2_preflight.sh'


def test_preflight_sources_ros_before_enabling_nounset():
    source = PREFLIGHT.read_text(encoding='utf-8')
    nounset_index = source.index('set -u\n')
    assert nounset_index > source.index('source /opt/ros/foxy/setup.bash')
    assert nounset_index > source.index(
        'source /home/agilex/limo_ros2_ws/install/setup.bash')
    assert nounset_index > source.index(
        'source /home/agilex/limo_cleanup_ws/install/setup.bash')
    assert source.index(
        'source /home/agilex/limo_ros2_ws/install/setup.bash') < source.index(
            'source /home/agilex/limo_cleanup_ws/install/setup.bash')


def test_preflight_requires_all_physical_acknowledgements():
    source = PREFLIGHT.read_text(encoding='utf-8')
    required = (
        'TRACKED_BASE_PHYSICAL_CHECKLIST_CONFIRMED',
        'TRACKED_BASE_ESTOP_TESTED',
        'TRACKED_BASE_COMMAND_MODE_WRITE_ACK',
    )
    for name in required:
        assert name in source
    assert "port=\"${TRACKED_BASE_PORT:-/dev/ttyTHS0}\"" in source
    assert '"${port}" != \'/dev/ttyTHS0\'' in source


def test_preflight_cannot_inspect_an_isolated_or_overridden_ros_graph():
    source = PREFLIGHT.read_text(encoding='utf-8')
    assert 'export ROS_DOMAIN_ID=137' in source
    assert 'export ROS_LOCALHOST_ONLY=0' in source
    assert 'requested_ros_domain_id}' in source
    assert 'requested_ros_localhost_only}' in source
    for variable in (
            'ROS_DISCOVERY_SERVER', 'CYCLONEDDS_URI',
            'FASTRTPS_DEFAULT_PROFILES_FILE'):
        assert variable in source
    assert 'custom discovery can hide ROS participants' in source


def test_preflight_requires_exact_platform_uart_identity():
    source = PREFLIGHT.read_text(encoding='utf-8')
    assert 'TRACKED_BASE_EXPECTED_SYSFS_DEVICE' in source
    assert 'TRACKED_BASE_EXPECTED_DRIVER' in source
    assert 'sysfs identity mismatch' in source
    assert 'driver mismatch' in source
    assert "vendor_prefix}" in source
    assert "default_value='ttyTHS0'" in source


def test_preflight_rejects_console_getty_and_missing_dialout_access():
    source = PREFLIGHT.read_text(encoding='utf-8')
    assert "grep -qx 'dialout'" in source
    assert 'console=ttyTHS0' in source
    assert 'serial-getty@ttyTHS0.service' in source
    assert 'current user is not a member of dialout' in source


def test_preflight_fails_closed_when_inspection_tools_or_queries_fail():
    source = PREFLIGHT.read_text(encoding='utf-8')
    required = (
        'fuser', 'grep', 'id', 'ps', 'readlink', 'ros2', 'systemctl',
        'timeout', 'tr',
    )
    for command in required:
        assert command in source
    assert 'required command is missing' in source
    assert 'port_owners="$(fuser "${port}" 2>&1)"' in source
    assert 'fuser_status=$?' in source
    assert 'could not prove ${port} ownership' in source
    assert 'console_status=$?' in source
    assert 'could not inspect /proc/cmdline' in source
    assert 'getty_status=$?' in source
    assert 'could not prove serial-getty inactive' in source
    assert 'fuser "${port}" 2>/dev/null || true' not in source


def test_preflight_blocks_when_ros_graph_query_fails():
    source = PREFLIGHT.read_text(encoding='utf-8')
    assert 'if ! process_table="$(ps -eo pid,args 2>&1)"' in source
    assert 'process ownership query failed' in source
    assert 'if ! nodes="$(timeout -k 2 8' in source
    assert 'ROS node query failed' in source


def test_preflight_checks_all_known_motion_topic_publishers():
    source = PREFLIGHT.read_text(encoding='utf-8')
    for topic in (
            '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop',
            '/limo/vel_cmd', '/cleanup/base/safe_cmd_vel'):
        assert topic in source
    assert 'command_status=$?' in source
    assert 'could not inspect ${command_topic} publishers' in source
    assert 'Subscription count: 0' in source
    assert 'has an endpoint or could not be proven safe' in source
    assert 'topic info "${command_topic}" --verbose 2>&1)' in source
    assert 'topic info "${command_topic}" --verbose 2>&1 || true' not in source


def test_preflight_is_read_only_and_foxy_compatible():
    source = PREFLIGHT.read_text(encoding='utf-8')
    forbidden = (
        'ros2 topic pub',
        'ros2 action send_goal',
        'ros2 service call',
        'ros2 launch limo_base',
        'ros2 run limo_base',
    )
    for command in forbidden:
        assert command not in source
    assert 'ros2 topic info "${command_topic}" --verbose' in source
    assert 'ros2 topic info "${command_topic}" --verbose --no-daemon' not in source
    assert "grep -q 'enableCommandedMode();'" in source
    assert 'STAGE2_PREFLIGHT_BLOCKED' in source
