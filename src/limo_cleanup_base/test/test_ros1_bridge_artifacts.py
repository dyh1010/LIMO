from pathlib import Path
import xml.etree.ElementTree as ET


WORKSPACE_ROOT = Path(__file__).parents[3]
ROS1_PACKAGE = (
    WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_cleanup_ros1_base')
SCRIPTS_ROOT = WORKSPACE_ROOT / 'scripts'


def test_ros1_package_is_catkin_and_has_no_vendor_dependency():
    package_source = (ROS1_PACKAGE / 'package.xml').read_text(encoding='utf-8')
    cmake_source = (ROS1_PACKAGE / 'CMakeLists.txt').read_text(encoding='utf-8')
    assert '<buildtool_depend>catkin</buildtool_depend>' in package_source
    assert '<depend>geometry_msgs</depend>' in package_source
    assert '<depend>sensor_msgs</depend>' in package_source
    assert '<depend>tf2_ros</depend>' in package_source
    assert '<depend>rospy</depend>' in package_source
    assert '<depend>limo_base</depend>' not in package_source
    assert 'catkin_install_python' in cmake_source


def test_zero_watchdog_launch_cannot_enable_nonzero_motion():
    path = ROS1_PACKAGE / 'launch' / 'safe_cmd_vel_watchdog_zero.launch'
    root = ET.parse(path).getroot()
    params = {
        item.attrib['name']: item.attrib['value']
        for item in root.findall('.//param')
    }
    assert params['input_topic'] == '/cleanup/base/safe_cmd_vel'
    assert params['output_topic'] == '/cleanup/base/driver_cmd_vel'
    assert params['allow_nonzero'] == 'false'
    assert 'allow_nonzero' not in {
        item.attrib.get('name') for item in root.findall('./arg')}


def test_vendor_wrapper_is_disabled_and_hard_remaps_cmd_vel():
    path = ROS1_PACKAGE / 'launch' / 'limo_start_private_cmd.launch'
    root = ET.parse(path).getroot()
    arguments = {
        item.attrib['name']: item.attrib['default']
        for item in root.findall('./arg')
    }
    assert arguments == {'hardware_write_authorized': 'false'}
    group = root.find('./group')
    assert group is not None
    assert group.attrib['if'] == '$(arg hardware_write_authorized)'
    remap = group.find('./remap')
    assert remap.attrib == {
        'from': '/cmd_vel',
        'to': '/cleanup/base/driver_cmd_vel',
    }
    include = group.find('./include')
    assert include.attrib['file'] == (
        '$(find limo_bringup)/launch/limo_start.launch')
    assert group.find(".//include[@file='$(find limo_bringup)/launch/"
                      "limo_teletop_keyboard.launch']") is None


def test_navigation_bridge_is_disabled_atomic_and_has_result_status():
    launch_path = ROS1_PACKAGE / 'launch' / 'navigation_bridge_adapter.launch'
    root = ET.parse(launch_path).getroot()
    argument = root.find("./arg[@name='enable_navigation_bridge']")
    assert argument is not None
    assert argument.attrib['default'] == 'false'
    source = (
        ROS1_PACKAGE / 'scripts' / 'fail_closed_navigation_adapter.py'
    ).read_text(encoding='utf-8')
    for topic in (
            '/cleanup/navigation/bridge_command',
            '/cleanup/navigation/bridge_status'):
        assert topic in source
    for legacy in ('/goal', '/rearm', '/stop', '/cancel'):
        assert '/cleanup/navigation{}'.format(legacy) not in source
    assert 'latch=False' in source
    assert 'latch=True' not in source
    assert '_on_done' in source
    assert 'done_cb=' in source
    assert 'cancel_all_goals' in source
    assert 'AtomicNavigationProtocol()' in source
    assert 'threading.RLock()' in source
    assert 'GoalGenerationGate()' in source
    assert 'queue.Queue(maxsize=1)' in source
    assert 'target=self._dispatch_worker' in source
    assert 'put_nowait' in source
    assert 'validate_map_binding(' in source
    assert 'validate_runtime_preflight_lease(' in source
    assert 'validate_release_files(' in source
    assert "rospy.get_param('~scan_topic', '/scan')" in source
    assert "rospy.get_param('~scan_frame', 'laser_link')" in source
    assert source.index('self._initialized = True') < source.index(
        'self.command_subscription = rospy.Subscriber(')
    assert source.index('self.status_publisher = rospy.Publisher(') < (
        source.index('self.command_subscription = rospy.Subscriber('))


def test_navigation_ros2_launch_reuses_zero_stage_controller_owner():
    launch_source = (
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'launch' /
        'navigation_intent_bridge.launch.py').read_text(encoding='utf-8')
    assert "executable='tracked_base_controller'" not in launch_source
    topology = (
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'ros2_topology_policy.py').read_text(
            encoding='utf-8')
    assert (
        "controller_node: str = '/cleanup_tracked_base_zero_output'"
        in topology)
    source = (
        ROS1_PACKAGE / 'scripts' / 'fail_closed_navigation_adapter.py'
    ).read_text(encoding='utf-8')
    assert "rospy.get_param('~global_frame', 'map')" in source
    assert "rospy.get_param('~base_frame', 'base_link')" in source
    assert 'scan_fresh' in source
    assert 'tf_ready' in source
    assert 'speaker' not in source.lower()
    watchdog_source = (
        ROS1_PACKAGE / 'scripts' / 'fail_closed_cmd_vel_watchdog.py'
    ).read_text(encoding='utf-8')
    assert 'GenerationPublishGate' in watchdog_source
    assert 'observe_generation()' in watchdog_source
    assert 'gate.shutdown()' in watchdog_source


def test_integrated_runner_generates_private_sealed_core_and_no_vendor_navigation():
    assert not (
        ROS1_PACKAGE / 'launch' / 'move_base_private_request.launch').exists()
    internal_launch = (
        ROS1_PACKAGE / 'launch' / 'v2_bridged_navigation_internal.launch')
    assert not internal_launch.exists()
    runner = (
        ROS1_PACKAGE / 'scripts' / 'run_v2_bridged_navigation.py'
    ).read_text(encoding='utf-8')
    for required in (
            '--binding-file', '--binding-sha256', '--binding-token',
            '--map-root'):
        assert required in runner
    assert '--map-file' not in runner
    assert '--active-map-id' not in runner
    assert 'v2_bridged_navigation_internal.launch' not in runner
    assert 'limo_navigation_diff.launch' not in runner
    assert 'v1_navigation_core.launch' not in runner
    assert "'stage:=navigation_precore'" in runner
    assert "'map_server'" in runner
    assert "'amcl'" in runner
    assert "'move_base'" in runner
    assert 'create_navigation_snapshot(' in runner
    preflight_call = runner.index('\n    _preflight(initial_binding)\n')
    final_revalidate = runner.index(
        'final_binding = validate_map_binding(*binding_args)')
    monitor_ready = runner.index('map_pipe.wait_for(', final_revalidate)
    spawn = runner.index("['roslaunch', str(core_path)]")
    assert runner.index('initial_binding = validate_map_binding(') < preflight_call
    assert preflight_call < final_revalidate < monitor_ready < spawn


def test_preflight_is_read_only_and_audits_exact_bridge_pair():
    source = (SCRIPTS_ROOT / 'ros1_base_bridge_preflight.sh').read_text(
        encoding='utf-8')
    assert 'dynamic_bridge --print-pairs' in source
    for message_pattern in (
            'geometry_msgs.*/Twist',
            'geometry_msgs.*/PoseStamped',
            'std_msgs.*/Bool',
            'std_msgs.*/String'):
        assert message_pattern in source
    assert 'roslaunch --nodes limo_bringup limo_start.launch' in source
    assert "grep -qx '/limo_base_node'" in source
    assert 'ROS1_BASE_BRIDGE_PREFLIGHT_PASS' in source
    assert '--bridge-all-topics' not in source
    assert 'rostopic pub' not in source
    assert 'ros2 topic pub' not in source
    assert 'roslaunch limo_bringup limo_start.launch' not in source


def test_zero_stage_proves_zero_before_vendor_and_has_bounded_cleanup():
    source = (SCRIPTS_ROOT / 'run_ros1_base_bridge_zero_stage.sh').read_text(
        encoding='utf-8')
    assert "--execute-zero-stage" in source
    assert "execute_mode='NO'" in source
    assert '--bridge-all-topics' not in source
    preflight = source.index('ros1_base_bridge_preflight.sh')
    watchdog = source.index('safe_cmd_vel_watchdog_zero.launch')
    gateway = source.index('tracked_base_zero_output.launch.py')
    bridge = source.index('ros1_bridge dynamic_bridge')
    ros2_proof = source.index('ROS1_BRIDGE_ROS2_ZERO_MONITORING')
    ros1_proof = source.index('ros1_pre_driver_verifier.log')
    vendor = source.index('limo_start_private_cmd.launch')
    assert preflight < watchdog < gateway < bridge
    assert bridge < ros2_proof < ros1_proof < vendor
    assert 'hardware_write_authorized:=true' in source
    assert 'ROS1_BASE_BRIDGE_ZERO_STAGE_READY' in source
    assert 'kill -TERM' in source
    assert 'kill -KILL' in source
    assert 'kill -0 -- "-${process_pid}"' in source
    assert 'wait "${process_pid}"' in source
    assert 'verify_cleanup' in source
    assert 'verify_uart_idle' in source
    assert 'could not prove ROS2 driver exclusion' in source
    assert 'roscore|rosmaster|limo_base_node' in source
    assert 'ROS1_BASE_ZERO_STAGE_AUTHORIZATION_FILE' in source
    assert 'authorization file must be owner-only mode 600' in source
    assert 'cleanup_sequence_guard.py' in source
    assert '--phase pre-master' in source
    assert '--phase post-master' in source
    assert 'verify_consumed_authorization_fresh' in source
    assert 'continuous zero monitor heartbeat became stale' in source
    cleanup = source[source.index('cleanup() {'):source.index('trap cleanup')]
    assert cleanup.index('prove_zero_immediately_before_driver_stop') < (
        cleanup.index('stop_group "${driver_pid}"'))
    assert cleanup.index('stop_group "${driver_pid}"') < cleanup.index(
        'stop_group "${bridge_pid}"')
    assert cleanup.index('verify_driver_stopped') < cleanup.index(
        'cleanup_event stop_safety')
    assert 'driver survived; zero safety chain retained' in cleanup
    assert 'ROS1_BRIDGE_ROS2_CONTINUOUS_ZERO_WINDOW_PASS' in source
    assert 'ROS1_BASE_BRIDGE_CONTINUOUS_ZERO_WINDOW_PASS' in source


def test_ros2_verifier_requires_gateway_bridge_and_no_public_endpoints():
    source = (
        SCRIPTS_ROOT / 'verify_ros1_bridge_ros2_zero_output.py'
    ).read_text(encoding='utf-8')
    assert "SAFE_TOPIC = '/cleanup/base/safe_cmd_vel'" in source
    assert "EXPECTED_GATEWAY = '/cleanup_tracked_base_zero_output'" in source
    assert "EXPECTED_BRIDGE = '/dynamic_bridge'" in source
    assert 'ROS1_BRIDGE_ROS2_ZERO_PASS' in source
    for topic in (
            '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop', '/limo/vel_cmd',
            '/cleanup/base/driver_cmd_vel'):
        assert "'{}'".format(topic) in source
