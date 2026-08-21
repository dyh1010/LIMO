"""Static fail-closed contract for the pinned camera-only launch package."""

import ast
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / 'launch' / 'dabai_cc1wc520183_sensor_only.launch.py'
SOURCE = LAUNCH.read_text(encoding='utf-8')
TREE = ast.parse(SOURCE, filename=str(LAUNCH), feature_version=(3, 8))
EXPECTED_ARGUMENTS = {
    'camera_name': 'camera',
    'serial_number': 'CC1WC520183',
    'enable_color': 'true',
    'color_width': '640',
    'color_height': '480',
    'color_fps': '30',
    'color_format': 'MJPG',
    'enable_depth': 'true',
    'depth_width': '640',
    'depth_height': '400',
    'depth_fps': '30',
    'depth_format': 'Y11',
    'enable_ir': 'false',
    'enable_point_cloud': 'false',
    'enable_colored_point_cloud': 'false',
    'depth_registration': 'true',
    'enable_depth_scale': 'true',
    'enable_ldp': 'false',
    'enable_frame_sync': 'true',
    'publish_tf': 'true',
    'tf_publish_rate': '10.0',
}


def _assignment(name):
    for node in TREE.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == name
                        for target in node.targets)):
            return ast.literal_eval(node.value)
    raise AssertionError('missing assignment: ' + name)


def _contract_failures(source):
    failures = []
    if "'serial_number': 'CC1WC520183'" not in source:
        failures.append('serial')
    for token in (
            "'enable_ir': 'false'",
            "'enable_point_cloud': 'false'",
            "'enable_colored_point_cloud': 'false'",
            "'depth_registration': 'true'",
            "'enable_depth_scale': 'true'",
            "'enable_ldp': 'false'",
            "'enable_frame_sync': 'true'",
            "'tf_publish_rate': '10.0'"):
        if token not in source:
            failures.append(token)
    return failures


def test_python38_ast_and_exact_vendor_hash_gate():
    compile(SOURCE, str(LAUNCH), 'exec')
    assert _assignment('EXPECTED_VENDOR_LAUNCH_SHA256') == (
        '955c98ac653182241a26ae3b4cc4eba3937d1529cd60c0361b23d05f2e4e7aaf')
    assert "actual_sha256 != EXPECTED_VENDOR_LAUNCH_SHA256" in SOURCE
    assert SOURCE.index('actual_sha256 =') < SOURCE.index(
        'IncludeLaunchDescription(')


def test_driver_arguments_are_complete_fixed_and_not_overridable():
    assert _assignment('FIXED_DRIVER_ARGUMENTS') == EXPECTED_ARGUMENTS
    assert 'DeclareLaunchArgument' not in SOURCE
    assert 'LaunchConfiguration' not in SOURCE
    assert 'Substitution' not in SOURCE
    assert "FindPackageShare" not in SOURCE


def test_only_vendor_include_is_returned_and_outer_config_is_not_forwarded():
    assert SOURCE.count('IncludeLaunchDescription(') == 1
    assert SOURCE.count('OpaqueFunction(') == 1
    assert SOURCE.count('GroupAction(') == 1
    assert 'forwarding=False' in SOURCE
    for token in (
            'launch_ros.actions', 'Node(', 'ExecuteProcess(',
            'ComposableNode(', 'create_publisher(', 'create_service(',
            'ActionClient(', 'ActionServer('):
        assert token not in SOURCE


def test_environment_is_fixed_to_local_domain_137():
    assert "SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1')" in SOURCE
    assert "SetEnvironmentVariable('ROS_DOMAIN_ID', '137')" in SOURCE
    assert "SetEnvironmentVariable('ROS2CLI_NO_DAEMON', '1')" in SOURCE


def test_package_runtime_dependency_set_is_exact_and_camera_only():
    package = ET.parse(str(ROOT / 'package.xml')).getroot()
    buildtool = {node.text for node in package.findall('buildtool_depend')}
    runtime = {node.text for node in package.findall('exec_depend')}
    tests = {node.text for node in package.findall('test_depend')}
    assert buildtool == {'ament_cmake'}
    assert runtime == {'ament_index_python', 'launch', 'orbbec_camera'}
    assert tests == {'ament_cmake_pytest'}


def test_package_has_one_launch_and_no_executable_surface():
    assert [path.name for path in (ROOT / 'launch').glob('*.launch.py')] == [
        'dabai_cc1wc520183_sensor_only.launch.py']
    assert not (ROOT / 'scripts').exists()
    cmake = (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
    for token in ('add_executable(', 'install(PROGRAMS', 'ament_python'):
        assert token not in cmake


def test_no_control_uart_or_unmeasured_base_tf_surface():
    lowered = SOURCE.lower()
    for token in (
            'base_link', 'static_transform_publisher', 'frame_id_override',
            '/cmd_vel', 'twist', 'navigate', 'move_base', 'controller',
            'trajectory', 'arm', 'gripper', '/dev/tty', 'serial_port'):
        assert token not in lowered


def test_negative_mutations_all_fail_the_source_contract():
    mutations = (
        SOURCE.replace("'CC1WC520183'", "'WRONG'", 1),
        SOURCE.replace("'enable_ir': 'false'", "'enable_ir': 'true'"),
        SOURCE.replace(
            "'enable_point_cloud': 'false'",
            "'enable_point_cloud': 'true'"),
        SOURCE.replace(
            "'depth_registration': 'true'",
            "'depth_registration': 'false'"),
        SOURCE.replace(
            "'enable_frame_sync': 'true'",
            "'enable_frame_sync': 'false'"),
        SOURCE.replace("'tf_publish_rate': '10.0'", "'tf_publish_rate': '0.0'"),
    )
    assert _contract_failures(SOURCE) == []
    assert all(_contract_failures(value) for value in mutations)
