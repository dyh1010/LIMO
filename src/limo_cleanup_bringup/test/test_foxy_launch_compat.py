import ast
import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext, LaunchDescription
from launch.substitutions import LaunchConfiguration


LAUNCH_DIR = Path(__file__).parents[1] / 'launch'
PROJECT_ROOT = LAUNCH_DIR.parents[2]
FOXY_LAUNCH_FILES = (
    'cleanup_system.launch.py',
    'camera_extrinsics.launch.py',
    'dabai_camera.launch.py',
    'gripper_control.launch.py',
    'hardware_readonly_acceptance.launch.py',
    'real_perception_only.launch.py',
    'tracked_base_vendor_stage2.launch.py',
    'tracked_base_zero_output.launch.py',
)
UNSUPPORTED_FOXY_IMPORTS = {
    'AndSubstitution',
    'NotSubstitution',
    'ParameterFile',
}


def _source(filename):
    return (LAUNCH_DIR / filename).read_text(encoding='utf-8')


def _load(filename):
    path = LAUNCH_DIR / filename
    spec = importlib.util.spec_from_file_location(
        filename.replace('.', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_launch_argument_defaults(filename):
    defaults = {}
    for node in ast.walk(ast.parse(_source(filename))):
        if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'DeclareLaunchArgument'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        for keyword in node.keywords:
            if (
                    keyword.arg == 'default_value'
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)):
                defaults[node.args[0].value] = keyword.value.value
    return defaults


def _included_launch_argument_names(filename):
    names = set()
    for node in ast.walk(ast.parse(_source(filename))):
        if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'IncludeLaunchDescription'):
            continue
        for keyword in node.keywords:
            if keyword.arg != 'launch_arguments':
                continue
            for descendant in ast.walk(keyword.value):
                if not isinstance(descendant, ast.Dict):
                    continue
                names.update(
                    key.value
                    for key in descendant.keys
                    if isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                )
    return names


@pytest.mark.parametrize('filename', FOXY_LAUNCH_FILES)
def test_launch_file_uses_python38_syntax(filename):
    ast.parse(
        _source(filename),
        filename=str(LAUNCH_DIR / filename),
        feature_version=(3, 8),
    )


@pytest.mark.parametrize('filename', FOXY_LAUNCH_FILES)
def test_launch_file_avoids_unsupported_foxy_imports(filename):
    tree = ast.parse(_source(filename))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not imported_names.intersection(UNSUPPORTED_FOXY_IMPORTS)


@pytest.mark.parametrize('filename', FOXY_LAUNCH_FILES)
def test_launch_description_generates(filename):
    module = _load(filename)
    assert isinstance(module.generate_launch_description(), LaunchDescription)


@pytest.mark.parametrize('filename', FOXY_LAUNCH_FILES)
def test_launch_defaults_do_not_reference_wsl_mounts(filename):
    assert '/mnt/c/' not in _source(filename)


@pytest.mark.parametrize(
    'mock,real,gate,expected_raw,expected_direct',
    (
        ('true', 'false', 'true', True, False),
        ('true', 'false', 'false', False, True),
        ('true', 'true', 'true', False, False),
        ('false', 'true', 'true', False, False),
    ),
)
def test_real_perception_suppresses_mock_nodes(
        mock, real, gate, expected_raw, expected_direct):
    module = _load('cleanup_system.launch.py')
    context = LaunchContext()
    context.launch_configurations.update({
        'mock': mock,
        'real': real,
        'gate': gate,
    })
    raw_condition = module._boolean_condition(
        required_true=(
            LaunchConfiguration('mock'),
            LaunchConfiguration('gate'),
        ),
        required_false=(LaunchConfiguration('real'),),
    )
    direct_condition = module._boolean_condition(
        required_true=(LaunchConfiguration('mock'),),
        required_false=(
            LaunchConfiguration('real'),
            LaunchConfiguration('gate'),
        ),
    )
    assert raw_condition.evaluate(context) is expected_raw
    assert direct_condition.evaluate(context) is expected_direct


def test_real_hardware_defaults_match_verified_robot_interfaces():
    bringup_root = LAUNCH_DIR.parent
    checked_paths = (
        LAUNCH_DIR / 'cleanup_system.launch.py',
        LAUNCH_DIR / 'hardware_readonly_acceptance.launch.py',
        LAUNCH_DIR / 'real_perception_only.launch.py',
        bringup_root / 'config' / 'dabai_real.yaml',
        bringup_root / 'limo_cleanup_bringup' / 'hardware_readiness_check.py',
    )
    for path in checked_paths:
        source = path.read_text(encoding='utf-8')
        assert '/camera/depth_registered/image_raw' not in source
        assert '/camera/depth/image_raw' in source


def test_gripper_defaults_use_stable_udev_alias():
    bringup_root = LAUNCH_DIR.parent
    executor_root = bringup_root.parent / 'limo_cleanup_executor'
    checked_paths = (
        LAUNCH_DIR / 'cleanup_system.launch.py',
        LAUNCH_DIR / 'gripper_control.launch.py',
        bringup_root / 'config' / 'gripper_safe.yaml',
        executor_root / 'limo_cleanup_executor' / 'gripper_controller.py',
    )
    for path in checked_paths:
        source = path.read_text(encoding='utf-8')
        assert '/dev/ttyACM0' not in source
        assert '/dev/elephant' in source


def test_smoke_scripts_have_portable_defaults():
    for relative_path in (
            'scripts/smoke_test_mock_system.sh',
            'scripts/smoke_test_real_perception_startup.sh'):
        source = (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')
        assert '/home/dyh/' not in source
        assert '/mnt/c/' not in source
        assert 'ROS_LOCALHOST_ONLY=1' in source


def test_yaml_does_not_override_launch_owned_always_active():
    config_source = (
        LAUNCH_DIR.parent / 'config' / 'dabai_real.yaml'
    ).read_text(encoding='utf-8')
    assert 'always_active:' not in config_source
    assert "'always_active':" in _source('real_perception_only.launch.py')


def test_yaml_does_not_override_launch_owned_readiness_parameters():
    config_source = (
        LAUNCH_DIR.parent / 'config' / 'dabai_real.yaml'
    ).read_text(encoding='utf-8')
    readiness_source = config_source.split(
        'cleanup_hardware_readiness:', 1)[1]
    launch_source = _source('hardware_readonly_acceptance.launch.py')
    for parameter in (
            'rgb_topic', 'depth_topic', 'camera_info_topic', 'base_frame',
            'camera_frame_override', 'require_tf', 'report_path'):
        assert '\n    {}:'.format(parameter) not in readiness_source
        assert "'{}'".format(parameter) in launch_source


def test_dabai_wrapper_propagates_safe_depth_parameters():
    expected_defaults = {
        'depth_registration': 'true',
        'enable_depth_scale': 'true',
        'enable_ldp': 'false',
    }
    filenames = (
        'dabai_camera.launch.py',
        'real_perception_only.launch.py',
        'hardware_readonly_acceptance.launch.py',
    )

    for filename in filenames:
        defaults = _literal_launch_argument_defaults(filename)
        forwarded = _included_launch_argument_names(filename)
        for parameter, expected in expected_defaults.items():
            assert defaults.get(parameter) == expected
            assert parameter in forwarded


def test_candidate_confidence_is_shared_by_detector_and_gate():
    launch_source = _source('cleanup_system.launch.py')
    config_source = (
        LAUNCH_DIR.parent / 'config' / 'dabai_real.yaml'
    ).read_text(encoding='utf-8')
    assert "'min_detection_confidence'" in launch_source
    assert "default_value='0.35'" in launch_source
    assert 'confidence: 0.35' in config_source


def test_camera_extrinsics_uses_foxy_positional_cli():
    source = _source('camera_extrinsics.launch.py')
    for unsupported_option in (
            "'--x'", "'--y'", "'--z'", "'--roll'", "'--pitch'",
            "'--yaw'", "'--frame-id'", "'--child-frame-id'"):
        assert unsupported_option not in source


def test_cleanup_executor_defaults_are_touch_safe():
    defaults = _literal_launch_argument_defaults('cleanup_system.launch.py')
    source = _source('cleanup_system.launch.py')

    assert defaults['executor_dry_run'] == 'true'
    assert defaults['allow_arm_motion'] == 'false'
    assert defaults['use_gripper_controller'] == 'false'
    assert "'dry_run':" in source
    assert "'allow_arm_motion':" in source


def test_tracked_base_gateway_defaults_are_fail_closed():
    defaults = _literal_launch_argument_defaults('cleanup_system.launch.py')
    source = _source('cleanup_system.launch.py')

    assert defaults['use_tracked_base_controller'] == 'false'
    assert defaults['allow_base_motion'] == 'false'
    assert defaults['base_output_topic'] == '/cleanup/base/safe_cmd_vel'
    assert defaults['base_max_linear_speed'] == '0.12'
    assert defaults['base_max_angular_speed'] == '0.35'
    assert "package='limo_cleanup_base'" in source
    assert "'allow_base_motion':" in source

    config_source = (
        LAUNCH_DIR.parent / 'config' / 'dabai_real.yaml'
    ).read_text(encoding='utf-8')
    readiness_source = (
        LAUNCH_DIR.parent / 'limo_cleanup_bringup'
        / 'hardware_readiness_check.py'
    ).read_text(encoding='utf-8')
    assert '- /cleanup/base/safe_cmd_vel' in config_source
    assert "'/cleanup/base/safe_cmd_vel'" in readiness_source
    assert 'get_subscriptions_info_by_topic' in readiness_source
    assert "'no_actuation_subscribers'" in readiness_source


def test_tracked_base_zero_output_launch_cannot_enable_motion():
    filename = 'tracked_base_zero_output.launch.py'
    defaults = _literal_launch_argument_defaults(filename)
    source = _source(filename)

    assert defaults['output_topic'] == '/cleanup/base/safe_cmd_vel'
    assert defaults['publish_rate'] == '20.0'
    assert 'allow_base_motion' not in defaults
    assert "'allow_base_motion': False" in source
    assert "package='limo_cleanup_base'" in source
    assert "package='limo_base'" not in source
    assert 'ExecuteProcess' not in source

    probe = (
        PROJECT_ROOT / 'scripts' / 'smoke_test_tracked_zero_launch.py'
    ).read_text(encoding='utf-8')
    ast.parse(
        probe,
        filename='smoke_test_tracked_zero_launch.py',
        feature_version=(3, 8),
    )
    assert "TEST_OUTPUT_TOPIC = '/test/cleanup/tracked_zero_output'" in probe
    assert "get_publishers_info_by_topic('/cmd_vel')" in probe

    wrapper = (
        PROJECT_ROOT / 'scripts' / 'smoke_test_tracked_zero_launch.sh'
    ).read_text(encoding='utf-8')
    assert 'RMW_IMPLEMENTATION=rmw_cyclonedds_cpp' in wrapper
    assert 'NetworkInterface name="lo"' in wrapper
    assert 'output_topic:=/test/cleanup/tracked_zero_output' in wrapper
    assert 'smoke_test_tracked_zero_launch.py' in wrapper
    assert 'setsid ros2 launch' in wrapper
    assert 'kill -TERM -- "-${zero_launch_pid}"' in wrapper
    assert 'kill -KILL -- "-${zero_launch_pid}"' in wrapper
    assert 'tracked_base_vendor_stage2.launch.py' not in wrapper
    assert 'allow_base_motion:=true' not in wrapper


def test_tracked_base_vendor_stage2_is_disabled_and_remapped():
    filename = 'tracked_base_vendor_stage2.launch.py'
    defaults = _literal_launch_argument_defaults(filename)
    source = _source(filename)

    assert defaults['stage2_hardware_write_authorized'] == 'false'
    assert 'port_name' not in defaults
    assert 'safe_command_topic' not in defaults
    assert 'publish_odom_tf' not in defaults
    assert "package='limo_base'" in source
    assert "condition=IfCondition(authorized)" in source
    assert "'port_name': 'ttyTHS0'" in source
    assert "'pub_odom_tf': False" in source
    assert "('/cmd_vel', '/cleanup/base/safe_cmd_vel')" in source
    assert "'use_mcnamu': False" in source


def test_tracked_readonly_audit_sources_foxy_before_nounset():
    source = (
        PROJECT_ROOT / 'scripts' / 'robot_tracked_readonly_audit.sh'
    ).read_text(encoding='utf-8')

    foxy_source = 'source /opt/ros/foxy/setup.bash'
    overlay_source = (
        'source /home/agilex/limo_cleanup_ws/install/setup.bash')
    nounset = 'set -u'
    assert foxy_source in source
    assert overlay_source in source
    assert source.index(nounset) > source.index(foxy_source)
    assert source.index(nounset) > source.index(overlay_source)
    assert 'ROS2CLI_NO_DAEMON=1 timeout -k 2 8' in source
    assert 'udevadm info --query=property' in source


def test_cleanup_bringup_never_starts_mycobot_follow():
    for filename in FOXY_LAUNCH_FILES:
        assert 'mycobot_follow' not in _source(filename)
