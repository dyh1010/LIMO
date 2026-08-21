#!/usr/bin/env python3
"""Dependency-free static audit of the isolated ROS1 Catkin overlay."""

import ast
from pathlib import Path
import re
import xml.etree.ElementTree as ET


WORKSPACE_ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = (
    WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_cleanup_ros1_base')
REQUIRED_DEPENDENCIES = {
    'actionlib',
    'actionlib_msgs',
    'geometry_msgs',
    'move_base_msgs',
    'rospy',
    'sensor_msgs',
    'std_msgs',
    'tf2_ros',
}
INSTALLED_SCRIPTS = {
    'cleanup_sequence_guard.py',
    'fail_closed_cmd_vel_watchdog.py',
    'fail_closed_navigation_adapter.py',
    'run_v2_bridged_navigation.py',
    'validate_v1_map_binding.py',
    'verify_v1_map_binding_runtime.py',
    'verify_ros1_base_bridge_topology.py',
}
REGISTERED_TESTS = {
    'test/test_watchdog_policy.py',
    'test/test_topology_policy.py',
    'test/test_navigation_policy.py',
    'test/test_map_binding.py',
    'test/test_runner_barrier.py',
    'test/test_cleanup_sequence.py',
}


def audit(package_root=PACKAGE_ROOT):
    """Raise on an incomplete or cross-version Catkin package contract."""
    package_root = Path(package_root)
    package_xml = ET.parse(package_root / 'package.xml').getroot()
    if package_xml.findtext('name') != 'limo_cleanup_ros1_base':
        raise RuntimeError('unexpected Catkin package name')
    if package_xml.attrib.get('format') != '2':
        raise RuntimeError('Catkin package format must be 2')
    if package_xml.findtext('buildtool_depend') != 'catkin':
        raise RuntimeError('Catkin buildtool dependency is missing')
    dependencies = {
        element.text for element in package_xml.findall('depend')}
    if not REQUIRED_DEPENDENCIES.issubset(dependencies):
        raise RuntimeError(
            'Catkin dependencies are incomplete: {}'.format(
                sorted(REQUIRED_DEPENDENCIES - dependencies)))
    if 'limo_base' in dependencies or 'rclpy' in dependencies:
        raise RuntimeError('vendor or ROS2 dependency leaked into overlay')

    cmake = (package_root / 'CMakeLists.txt').read_text(encoding='utf-8')
    for dependency in REQUIRED_DEPENDENCIES:
        if dependency not in cmake:
            raise RuntimeError(
                'CMakeLists is missing {}'.format(dependency))
    install_match = re.search(
        r'catkin_install_python\(PROGRAMS(?P<body>.*?)DESTINATION',
        cmake,
        flags=re.DOTALL,
    )
    if install_match is None:
        raise RuntimeError('catkin_install_python block is missing')
    installed = {
        Path(token).name
        for token in install_match.group('body').split()
        if token.endswith('.py')
    }
    if installed != INSTALLED_SCRIPTS:
        raise RuntimeError(
            'installed scripts are {}, expected {}'.format(
                sorted(installed), sorted(INSTALLED_SCRIPTS)))
    if 'install(DIRECTORY launch' not in cmake:
        raise RuntimeError('launch directory is not installed')
    for test_path in REGISTERED_TESTS:
        if 'catkin_add_nosetests({})'.format(test_path) not in cmake:
            raise RuntimeError(
                'Catkin test is not registered: {}'.format(test_path))

    for launch_path in (package_root / 'launch').glob('*.launch'):
        ET.parse(launch_path)
    if (package_root / 'launch' / 'move_base_private_request.launch').exists():
        raise RuntimeError('obsolete vendor navigation wrapper must be absent')
    internal_launch = (
        package_root / 'launch' / 'v2_bridged_navigation_internal.launch')
    if internal_launch.exists():
        raise RuntimeError(
            'directly launchable integrated wrapper must not be installed')
    runner_source = (
        package_root / 'scripts' / 'run_v2_bridged_navigation.py'
    ).read_text(encoding='utf-8')
    for required in (
            'map_pipe.wait_for(', '_build_private_core_launch(',
            "['roslaunch', str(core_path)]",
            'create_navigation_snapshot('):
        if required not in runner_source:
            raise RuntimeError('private runner barrier is incomplete')
    if (
            'v2_bridged_navigation_internal.launch' in runner_source
            or 'limo_navigation_diff.launch' in runner_source):
        raise RuntimeError('bypassable/vendor navigation entry remains')
    for path in (
            list((package_root / 'scripts').glob('*.py'))
            + list((package_root / 'src').rglob('*.py'))):
        source = path.read_text(encoding='utf-8')
        ast.parse(source, filename=str(path))
        if 'import rclpy' in source or 'from rclpy' in source:
            raise RuntimeError('ROS2 import leaked into {}'.format(path))
    adapter = (
        package_root / 'scripts' / 'fail_closed_navigation_adapter.py'
    ).read_text(encoding='utf-8')
    for topic in (
            '/cleanup/navigation/bridge_command',
            '/cleanup/navigation/bridge_status'):
        if topic not in adapter:
            raise RuntimeError('atomic interface missing {}'.format(topic))
    for legacy in ('/goal', '/rearm', '/stop', '/cancel'):
        if '/cleanup/navigation{}'.format(legacy) in adapter:
            raise RuntimeError('legacy navigation interface remains')


def main():
    try:
        audit()
    except Exception as error:
        print('ROS1_CATKIN_OVERLAY_AUDIT_BLOCKED: {}'.format(error))
        return 1
    print('ROS1_CATKIN_OVERLAY_AUDIT_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
