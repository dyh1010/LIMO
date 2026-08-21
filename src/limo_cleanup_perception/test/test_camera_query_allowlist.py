"""Fail-closed source contract for camera-only remote metadata queries."""

import json
from pathlib import Path


FIXTURE = (
    Path(__file__).parents[1] / 'fixtures'
    / 'dabai_camera_query_allowlist.json'
)
EXPECTED_COMMANDS = [
    ['readlink', '-f', '--', '/dev/dabai'],
    ['stat', '--dereference', '--format=%F,%a,%U,%G,%n', '--',
     '/dev/dabai'],
    ['udevadm', 'info', '--query=property', '--name=/dev/dabai'],
    ['readlink', '-f', '--', '/dev/dc1_rgb'],
    ['stat', '--dereference', '--format=%F,%a,%U,%G,%n', '--',
     '/dev/dc1_rgb'],
    ['udevadm', 'info', '--query=property', '--name=/dev/dc1_rgb'],
    ['readlink', '-f', '--', '/dev/dabai_dc1_'],
    ['stat', '--dereference', '--format=%F,%a,%U,%G,%n', '--',
     '/dev/dabai_dc1_'],
    ['udevadm', 'info', '--query=property', '--name=/dev/dabai_dc1_'],
]


def _load():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def test_allowlist_is_camera_only_and_does_not_authorize_execution():
    value = _load()
    assert value['read_only'] is True
    assert value['authorizes_motion'] is False
    assert value['authorizes_ros_start'] is False
    assert value['remote_query_state'] == (
        'frozen_not_executed_after_scope_correction')
    assert value['camera'] == {
        'model': 'Dabai DC1',
        'serial_number': 'CC1WC520183',
        'rgb_usb_identity': '2bc5:0557',
        'depth_usb_identity': '2bc5:0657',
    }


def test_allowlist_has_exact_three_persistent_camera_links():
    value = _load()
    links = value['allowed_device_links']
    assert [item['path'] for item in links] == [
        '/dev/dabai', '/dev/dc1_rgb', '/dev/dabai_dc1_']
    assert [item['expected_usb_identity'] for item in links] == [
        '2bc5:0557', '2bc5:0557', '2bc5:0657']
    assert all(item['path'].startswith('/dev/d') for item in links)
    assert links[0]['required_udev_properties'] == {
        'ID_VENDOR_ID': '2bc5', 'ID_MODEL_ID': '0557',
        'ID_MODEL': 'Dabai_DC1', 'ID_SERIAL_SHORT': 'CC1WC520183'}
    assert links[1]['required_udev_properties'] == (
        links[0]['required_udev_properties'])
    assert links[2]['required_udev_properties'] == {
        'ID_VENDOR_ID': '2bc5', 'ID_MODEL_ID': '0657',
        'ID_MODEL': 'ORBBEC_Depth_Sensor'}


def test_commands_are_exact_argv_without_shell_or_tree_enumeration():
    value = _load()
    allowed_paths = {
        item['path'] for item in value['allowed_device_links']}
    commands = value['allowed_commands']
    assert commands == EXPECTED_COMMANDS
    assert len(commands) == 3 * len(allowed_paths)
    assert {argv[0] for argv in commands} == {
        'readlink', 'stat', 'udevadm'}
    for argv in commands:
        assert isinstance(argv, list)
        assert all(isinstance(token, str) and token for token in argv)
        joined = ' '.join(argv)
        assert sum(path in argv or any(
            token.endswith('=' + path) for token in argv)
                   for path in allowed_paths) == 1
        assert not any(token in joined for token in (
            '$(', '`', ';', '&&', '||', '|', '<', '>', '*', '?',
            '/sys', '/dev/tty'))
        assert argv[0] not in {'find', 'lsusb', 'pgrep', 'ps'}
    mutations = [list(argv) + ['/dev/extra'] for argv in commands]
    mutations.extend((
        ['udevadm', 'info', '--attribute-walk', '--name=/dev/dabai'],
        ['readlink', '-f', '--', '/dev/dabai', '/dev/dc1_rgb'],
        ['stat', '--dereference', '--format=%n', '--', '/dev/dabai'],
        ['find', '-L', '/dev/dabai'],
    ))
    assert all(mutation not in commands for mutation in mutations)


def test_every_link_has_one_readlink_stat_and_udevadm_command():
    value = _load()
    commands = value['allowed_commands']
    for link in value['allowed_device_links']:
        path = link['path']
        matching = [
            argv for argv in commands
            if path in argv or any(
                token.endswith('=' + path) for token in argv)]
        assert [argv[0] for argv in matching] == [
            'readlink', 'stat', 'udevadm']


def test_forbidden_tokens_cover_known_scope_expansion_paths():
    forbidden = set(_load()['forbidden_tokens'])
    assert {
        'find', '-L', '--recursive', '/sys', 'lsusb', 'pgrep', 'ps',
        'rosnode', 'rostopic', 'roscore', 'roslaunch', 'rosrun',
        'rosbag', 'rosparam', 'rosservice', 'ros2', '/dev/tty', '/cmd_vel',
        'move_base', 'navigate', 'arm', 'gripper',
    }.issubset(forbidden)
    policy = _load()['output_policy']
    assert policy == {
        'readlink_line_count': 1,
        'readlink_target_regex': '^/dev/bus/usb/[0-9]{3}/[0-9]{3}$',
        'stat_line_count': 1,
        'stat_field_count': 5,
        'udevadm_record_count': 1,
        'udevadm_requires_link_identity_properties': True,
        'unexpected_device_path_is_failure': True,
        'unexpected_property_record_is_failure': True,
        'empty_output_is_failure': True,
    }
