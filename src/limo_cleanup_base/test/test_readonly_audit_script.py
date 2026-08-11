from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
AUDIT_SCRIPT = WORKSPACE_ROOT / 'scripts' / 'robot_tracked_readonly_audit.sh'


def test_audit_sources_foxy_and_colcon_before_enabling_nounset():
    source = AUDIT_SCRIPT.read_text(encoding='utf-8')
    nounset_index = source.index('set -u\n')
    assert nounset_index > source.index('source /opt/ros/foxy/setup.bash')
    assert nounset_index > source.index(
        'source /home/agilex/limo_ros2_ws/install/setup.bash')
    assert nounset_index > source.index(
        'source /home/agilex/limo_cleanup_ws/install/setup.bash')
    assert source.index(
        'source /home/agilex/limo_ros2_ws/install/setup.bash') < source.index(
            'source /home/agilex/limo_cleanup_ws/install/setup.bash')


def test_audit_uses_foxy_compatible_topic_info_cli():
    source = AUDIT_SCRIPT.read_text(encoding='utf-8')
    topic_info_lines = [
        line.strip() for line in source.splitlines()
        if line.strip().startswith('ros2 topic info ')
    ]
    assert topic_info_lines
    for line in topic_info_lines:
        assert '--no-daemon' not in line
        assert '--spin-time' not in line


def test_audit_contains_no_ros_publish_or_hardware_launch_commands():
    source = AUDIT_SCRIPT.read_text(encoding='utf-8')
    forbidden = (
        'ros2 topic pub',
        'ros2 action send_goal',
        'ros2 service call',
        'ros2 launch limo_base',
        'ros2 run limo_base',
        '/cmd_vel geometry_msgs',
        'cat /dev/ttyTHS',
        'stty ',
        ' minicom',
        ' screen ',
        'socat ',
        '> /dev/ttyTHS',
    )
    for command in forbidden:
        assert command not in source


def test_audit_collects_platform_uart_identity_without_opening_ports():
    source = AUDIT_SCRIPT.read_text(encoding='utf-8')
    for device in ('ttyTHS0', 'ttyTHS1', 'ttyTHS3', 'ttyTHS4'):
        assert '/dev/{}'.format(device) in source
    assert '/sys/class/tty/${device##*/}/device' in source
    assert '/proc/device-tree/aliases/serial*' in source
    assert 'fuser -v "${device}"' in source
    assert 'AUDIT_STATUS=EVIDENCE_CAPTURED_NOT_ACCEPTANCE_PASS' in source
