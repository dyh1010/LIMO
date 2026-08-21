#!/usr/bin/env python3
"""Dependency-free offline regression for the ROS1 base bridge."""

import ast
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
import importlib.util


WORKSPACE_ROOT = Path(__file__).parents[1]
ROS1_PACKAGE = (
    WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_cleanup_ros1_base')
TEST_ACTIVE_MAP_ID = 'v1_frozen_map'
sys.path.insert(0, str(ROS1_PACKAGE / 'src'))
sys.path.insert(0, str(WORKSPACE_ROOT / 'src' / 'limo_cleanup_base'))
try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    yaml_stub = types.ModuleType('yaml')
    yaml_stub.safe_load = json.loads
    sys.modules['yaml'] = yaml_stub

from limo_cleanup_ros1_base.navigation_policy import (  # noqa: E402
    AtomicNavigationProtocol,
    parse_bridge_command,
)
from limo_cleanup_ros1_base.navigation_health import (  # noqa: E402
    navigation_health_ready,
    received_sample_is_fresh,
    timestamp_is_fresh,
)
from limo_cleanup_ros1_base.topology_policy import (  # noqa: E402
    ExpectedTopology,
    validate_topology,
)
from limo_cleanup_ros1_base.watchdog_policy import (  # noqa: E402
    FailClosedWatchdog,
    TwistValues,
    WatchdogLimits,
    ZERO_TWIST,
)
from limo_cleanup_base.bridge_protocol import (  # noqa: E402
    BridgeStatus,
    EpochStore,
    NavigationAuthorizationPolicy,
    build_cancel_command,
    build_dispatch_command,
    parse_bridge_status,
)
from limo_cleanup_base.motion_policy import (  # noqa: E402
    PermissionInputs,
    permission_reason,
)
from limo_cleanup_base.navigation_intent_policy import (  # noqa: E402
    MapWaypoint,
    load_map_waypoint,
    parse_navigation_intent,
)
from limo_cleanup_base.ros2_topology_policy import (  # noqa: E402
    ExpectedRos2Topology,
    validate_ros2_navigation_topology,
)


def _expect_raises(callable_object):
    try:
        callable_object()
    except (OSError, RuntimeError, ValueError):
        return
    raise AssertionError('expected a fail-closed exception')


def _waypoint():
    return MapWaypoint(
        map_id=TEST_ACTIVE_MAP_ID,
        target_id='trash_bin_staging',
        frame_id='map',
        x=1.0,
        y=-2.0,
        yaw=0.5,
    )


def test_watchdog_policy():
    watchdog = FailClosedWatchdog()
    assert watchdog.output(0.0) == ZERO_TWIST
    assert watchdog.accept(TwistValues(linear_x=0.01), 1.0) == ZERO_TWIST
    watchdog = FailClosedWatchdog(
        allow_nonzero=True,
        limits=WatchdogLimits(lease_timeout=0.25),
    )
    accepted = watchdog.accept(
        TwistValues(linear_x=1.0, angular_z=-1.0), 2.0)
    assert accepted == TwistValues(linear_x=0.12, angular_z=-0.35)
    assert watchdog.output(2.249999) == accepted
    assert watchdog.output(2.25) == ZERO_TWIST
    assert watchdog.output(3.0) == ZERO_TWIST
    for invalid in (
            TwistValues(linear_y=0.01),
            TwistValues(angular_x=0.01),
            TwistValues(linear_x=math.nan),
            TwistValues(angular_z=math.inf)):
        watchdog.accept(TwistValues(linear_x=0.01), 4.0)
        _expect_raises(
            lambda value=invalid: watchdog.accept(value, 4.1))
        assert watchdog.output(4.11) == ZERO_TWIST


def test_ros1_topology_policy():
    expected = ExpectedTopology()
    publishers = {
        expected.bridge_topic: [expected.bridge_node],
        expected.driver_topic: [expected.watchdog_node],
    }
    subscribers = {
        expected.bridge_topic: [expected.watchdog_node],
        expected.driver_topic: [
            expected.driver_node,
            expected.verifier_node,
        ],
    }
    validate_topology(publishers, subscribers)
    pre_driver = dict(subscribers)
    pre_driver[expected.driver_topic] = [expected.verifier_node]
    validate_topology(publishers, pre_driver, driver_expected=False)

    zero_stage = ExpectedTopology(
        verifier_node=expected.zero_stage_verifier_node)
    combined_subscribers = dict(subscribers)
    combined_subscribers[expected.driver_topic] = [
        expected.zero_stage_verifier_node,
        expected.driver_node,
    ]
    validate_topology(
        publishers, combined_subscribers, expected=zero_stage,
        monitor_role='zero_stage')
    combined_subscribers[expected.driver_topic].append(
        expected.production_verifier_node)
    validate_topology(
        publishers, combined_subscribers, expected=zero_stage,
        monitor_role='zero_stage')
    validate_topology(
        publishers, combined_subscribers, expected=expected,
        monitor_role='production')
    missing_peer = dict(combined_subscribers)
    missing_peer[expected.driver_topic] = [
        expected.production_verifier_node, expected.driver_node]
    _expect_raises(lambda: validate_topology(
        publishers, missing_peer, expected=expected,
        monitor_role='production'))
    rogue_peer = dict(combined_subscribers)
    rogue_peer[expected.driver_topic] = (
        combined_subscribers[expected.driver_topic] + ['/rogue_monitor'])
    _expect_raises(lambda: validate_topology(
        publishers, rogue_peer, expected=expected,
        monitor_role='production'))

    navigation_publishers = dict(publishers)
    navigation_subscribers = dict(subscribers)
    navigation_publishers[expected.request_topic] = [
        expected.move_base_node]
    navigation_subscribers[expected.request_topic] = [
        expected.bridge_node]
    navigation_publishers[expected.command_topic] = [expected.bridge_node]
    navigation_subscribers[expected.command_topic] = [
        expected.navigation_adapter_node]
    navigation_publishers[expected.status_topic] = [
        expected.navigation_adapter_node]
    navigation_subscribers[expected.status_topic] = [expected.bridge_node]
    navigation_publishers[expected.scan_topic] = [expected.scan_node]
    navigation_publishers[expected.odom_topic] = [expected.odom_node]
    navigation_publishers[expected.tf_topic] = list(expected.tf_nodes)
    navigation_publishers[expected.tf_static_topic] = list(
        expected.tf_static_nodes)
    navigation_nodes = [
        '/map_server', '/amcl', expected.move_base_node,
        expected.navigation_adapter_node,
    ]
    validate_topology(
        navigation_publishers,
        navigation_subscribers,
        navigation_expected=True,
        active_nodes=navigation_nodes,
    )
    rogue_legacy = dict(navigation_publishers)
    rogue_legacy['/cleanup/navigation/rearm'] = [expected.bridge_node]
    _expect_raises(lambda: validate_topology(
        rogue_legacy,
        navigation_subscribers,
        navigation_expected=True,
        active_nodes=navigation_nodes,
    ))
    rogue_intent = dict(navigation_subscribers)
    rogue_intent[expected.intent_topic] = [expected.bridge_node]
    _expect_raises(lambda: validate_topology(
        navigation_publishers,
        rogue_intent,
        navigation_expected=True,
        active_nodes=navigation_nodes,
    ))


def test_atomic_navigation_protocol():
    nonces = iter([
        'nonce000000000001',
        'nonce000000000002',
        'nonce000000000003',
        'nonce000000000004',
        'nonce000000000005',
        'nonce000000000006',
        'nonce000000000007',
        'nonce000000000008',
        'nonce000000000009',
        'nonce000000000010',
        'nonce000000000011',
        'nonce000000000012',
        'nonce000000000013',
        'nonce000000000014',
        'nonce000000000015',
    ])
    protocol = AtomicNavigationProtocol(nonce_factory=lambda: next(nonces))
    first = build_dispatch_command(1, protocol.nonce, _waypoint())
    command = parse_bridge_command(first)
    assert protocol.accept(command, True, TEST_ACTIVE_MAP_ID) == 'accepted'
    assert protocol.state == 'active'
    assert protocol.accept(command, True, TEST_ACTIVE_MAP_ID) == 'duplicate'

    conflict_protocol = AtomicNavigationProtocol()
    accepted = parse_bridge_command(build_dispatch_command(
        1, conflict_protocol.nonce, _waypoint()))
    assert conflict_protocol.accept(
        accepted, True, TEST_ACTIVE_MAP_ID) == 'accepted'
    conflicting_waypoint = MapWaypoint(
        **{**_waypoint().__dict__, 'x': 9.0})
    conflicting = parse_bridge_command(build_dispatch_command(
        1, accepted.nonce, conflicting_waypoint))
    _expect_raises(
        lambda: conflict_protocol.accept(
            conflicting, True, TEST_ACTIVE_MAP_ID))
    assert conflict_protocol.state == 'rejected'

    cancel = parse_bridge_command(build_cancel_command(2))
    assert protocol.accept(cancel, True) == 'cancelled'
    assert protocol.state == 'stopped'
    _expect_raises(
        lambda: protocol.accept(command, True, TEST_ACTIVE_MAP_ID))
    assert protocol.state == 'rejected'

    current_nonce = protocol.nonce
    new_command = parse_bridge_command(
        build_dispatch_command(3, current_nonce, _waypoint()))
    assert protocol.accept(
        new_command, True, TEST_ACTIVE_MAP_ID) == 'accepted'
    assert protocol.complete(3, 'succeeded')
    assert protocol.state == 'succeeded'
    _expect_raises(
        lambda: protocol.accept(new_command, True, TEST_ACTIVE_MAP_ID))

    current_nonce = protocol.nonce
    unavailable = parse_bridge_command(
        build_dispatch_command(4, current_nonce, _waypoint()))
    _expect_raises(
        lambda: protocol.accept(unavailable, False, TEST_ACTIVE_MAP_ID))
    assert protocol.state == 'rejected'
    protocol.set_navigation_ready(False)
    assert protocol.state == 'unavailable'
    protocol.set_navigation_ready(True)
    assert protocol.state == 'ready'

    for terminal_state in (
            'succeeded', 'aborted', 'preempted', 'rejected'):
        terminal_protocol = AtomicNavigationProtocol()
        terminal_command = parse_bridge_command(build_dispatch_command(
            1, terminal_protocol.nonce, _waypoint()))
        terminal_protocol.accept(
            terminal_command, True, TEST_ACTIVE_MAP_ID)
        assert terminal_protocol.complete(1, terminal_state)
        assert terminal_protocol.state == terminal_state


def test_status_authorization_and_epoch_store():
    with tempfile.TemporaryDirectory() as directory:
        store = EpochStore(str(Path(directory) / 'navigation_epoch'))
        assert store.allocate() == 1
        assert store.allocate() == 2
        assert EpochStore(str(Path(directory) / 'navigation_epoch')).allocate() == 3

    ready = BridgeStatus(
        state='stopped',
        epoch=3,
        nonce='nonce000000000100',
        server_ready=True,
        scan_fresh=True,
        tf_ready=True,
    )
    policy = NavigationAuthorizationPolicy()
    policy.update(ready, 10.0)
    assert policy.dispatch_context(10.1, 0.25) == ready
    policy.dispatch(4, ready.nonce, 10.11)
    assert not policy.authorization(10.11, 0.25)
    assert not policy.pending_expired(10.359999, 0.25)
    active = BridgeStatus(
        state='active',
        epoch=4,
        nonce='nonce000000000101',
        server_ready=True,
        scan_fresh=True,
        tf_ready=True,
    )
    policy.update(active, 10.12)
    assert policy.authorization(10.369999, 0.25)
    assert not policy.pending_expired(10.369999, 0.25)
    assert policy.pending_expired(10.37, 0.25)
    assert policy.fault_latched
    assert not policy.update(active, 10.38)
    assert not policy.authorization(10.39, 0.25)
    recovery = BridgeStatus(
        state='ready',
        epoch=4,
        nonce='nonce000000000102',
        server_ready=True,
        scan_fresh=True,
        tf_ready=True,
    )
    assert policy.update(recovery, 10.40)
    policy.dispatch(5, recovery.nonce, 10.41)
    policy.update(BridgeStatus(
        state='aborted',
        epoch=5,
        nonce='nonce000000000103',
        server_ready=True,
        scan_fresh=True,
        tf_ready=True,
    ), 10.42)
    assert not policy.authorization(10.43, 0.25)
    assert policy.pending_epoch is None

    payload = json.dumps({
        'protocol': 'cleanup_navigation_bridge/v3',
        'state': 'preempted',
        'epoch': 5,
        'nonce': 'nonce000000000103',
        'server_ready': True,
        'scan_fresh': True,
        'tf_ready': True,
    })
    assert parse_bridge_status(payload).state == 'preempted'
    _expect_raises(lambda: parse_bridge_status(json.dumps({
        'protocol': 'cleanup_navigation_bridge/v3',
        'state': 'active',
        'epoch': 5,
        'nonce': 'nonce000000000103',
        'server_ready': True,
        'scan_fresh': True,
        'tf_ready': True,
        'extra': 'rejected',
    })))

    for scan_fresh, tf_ready in ((False, True), (True, False)):
        health_policy = NavigationAuthorizationPolicy()
        health_ready = BridgeStatus(
            state='ready',
            epoch=5,
            nonce='nonce000000000105',
            server_ready=True,
            scan_fresh=True,
            tf_ready=True,
        )
        health_policy.update(health_ready, 11.0)
        health_policy.dispatch(6, health_ready.nonce, 11.001)
        health_policy.update(BridgeStatus(
            state='active',
            epoch=6,
            nonce='nonce000000000106',
            server_ready=True,
            scan_fresh=scan_fresh,
            tf_ready=tf_ready,
        ), 11.01)
        assert not health_policy.authorization(11.02, 0.25)

    assert timestamp_is_fresh(20.0, 20.499999, 0.5)
    assert not timestamp_is_fresh(20.0, 20.5, 0.5)
    assert not timestamp_is_fresh(20.2, 20.0, 0.5)
    assert received_sample_is_fresh(30.0, 40.0, 30.499999, 40.4, 0.5)
    assert not received_sample_is_fresh(30.0, 40.0, 30.5, 40.4, 0.5)
    assert not received_sample_is_fresh(30.1, 40.0, 30.0, 40.1, 0.5)
    assert navigation_health_ready(True, True, True)
    assert not navigation_health_ready(True, False, True)
    assert not navigation_health_ready(True, True, False)

    watchdog = FailClosedWatchdog(
        allow_nonzero=True,
        limits=WatchdogLimits(lease_timeout=0.25),
    )
    watchdog.accept(TwistValues(linear_x=0.1), 20.0)
    reason = permission_reason(PermissionInputs(
        allow_base_motion=True,
        now=20.01,
        request_time=20.01,
        authorization=False,
        authorization_time=20.01,
        safety_clear=True,
        safety_time=20.01,
    ))
    assert reason == 'motion_not_authorized'
    assert watchdog.accept(ZERO_TWIST, 20.01) == ZERO_TWIST
    assert watchdog.output(20.26) == ZERO_TWIST


def test_exact_voice_and_waypoint_policy():
    cancel = parse_navigation_intent(
        '{"action":"cancel_navigation","request_safe_stop":true}')
    assert cancel.request_safe_stop
    waypoint_intent = parse_navigation_intent(
        '{"action":"navigate_to_waypoint",'
        '"target_id":"trash_bin_staging",'
        '"target_source":"fixed_map_waypoint"}')
    assert waypoint_intent.target_id == 'trash_bin_staging'
    for payload in (
            'not-json',
            '{"action":"cancel_navigation","request_safe_stop":false}',
            '{"action":"cancel_navigation","request_safe_stop":true,'
            '"raw_text":"stop"}',
            '{"action":"navigate_to_speaker"}'):
        _expect_raises(
            lambda candidate=payload: parse_navigation_intent(candidate))

    locked_template = (
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'config' /
        'v1_navigation_waypoints.example.yaml')
    locked_source = locked_template.read_text(encoding='utf-8')
    assert 'map_id: NOT_AVAILABLE_MAP_NOT_FROZEN' in locked_source
    assert 'waypoints: {}' in locked_source
    _expect_raises(lambda: load_map_waypoint(
        str(locked_template),
        'trash_bin_staging',
        'NOT_AVAILABLE_MAP_NOT_FROZEN',
    ))


def test_ros2_source_topology_policy():
    expected = ExpectedRos2Topology()
    publishers = {
        expected.intent_topic: [expected.voice_node],
        expected.command_topic: [expected.consumer_node],
        expected.status_topic: [expected.bridge_node],
        expected.request_topic: [expected.bridge_node],
        expected.authorization_topic: [expected.consumer_node],
        expected.topology_ready_topic: [expected.verifier_node],
        expected.topology_bootstrap_topic: [expected.verifier_node],
        expected.safe_topic: [expected.controller_node],
    }
    subscribers = {
        expected.intent_topic: [expected.consumer_node],
        expected.command_topic: [expected.bridge_node],
        expected.status_topic: [expected.consumer_node],
        expected.request_topic: [expected.controller_node],
        expected.authorization_topic: [expected.controller_node],
        expected.topology_ready_topic: [
            expected.consumer_node,
            expected.controller_node,
        ],
        expected.topology_bootstrap_topic: [expected.consumer_node],
        expected.safety_topic: [expected.controller_node],
        expected.safe_topic: [
            expected.bridge_node, expected.zero_verifier_node],
    }
    validate_ros2_navigation_topology(publishers, subscribers)
    for topic in (
            '/cleanup/navigation/goal',
            '/cleanup/navigation/rearm',
            expected.request_topic):
        rogue = {key: list(value) for key, value in publishers.items()}
        rogue.setdefault(topic, []).append('/rogue_source')
        _expect_raises(lambda mapping=rogue: validate_ros2_navigation_topology(
            mapping, subscribers))
    rogue_safety = {key: list(value) for key, value in publishers.items()}
    rogue_safety[expected.safety_topic] = ['/manual_safety_pub']
    _expect_raises(lambda: validate_ros2_navigation_topology(
        rogue_safety, subscribers))


def test_launch_manifest_and_runner_contracts():
    package_source = (ROS1_PACKAGE / 'package.xml').read_text(
        encoding='utf-8')
    cmake_source = (ROS1_PACKAGE / 'CMakeLists.txt').read_text(
        encoding='utf-8')
    assert '<depend>actionlib_msgs</depend>' in package_source
    assert '<depend>sensor_msgs</depend>' in package_source
    assert '<depend>tf2_ros</depend>' in package_source
    assert 'actionlib_msgs' in cmake_source
    assert 'sensor_msgs' in cmake_source
    assert 'tf2_ros' in cmake_source
    assert '<depend>limo_base</depend>' not in package_source

    navigation_launch = ET.parse(
        ROS1_PACKAGE / 'launch' / 'navigation_bridge_adapter.launch'
    ).getroot()
    enable = navigation_launch.find(
        "./arg[@name='enable_navigation_bridge']")
    assert enable.attrib['default'] == 'false'
    adapter_source = (
        ROS1_PACKAGE / 'scripts' / 'fail_closed_navigation_adapter.py'
    ).read_text(encoding='utf-8')
    assert '/cleanup/navigation/bridge_command' in adapter_source
    assert '/cleanup/navigation/bridge_status' in adapter_source
    assert 'done_cb=' in adapter_source
    for legacy in ('/goal', '/rearm', '/stop', '/cancel'):
        assert '/cleanup/navigation{}'.format(legacy) not in adapter_source

    runner = (
        WORKSPACE_ROOT / 'scripts' / 'run_ros1_base_bridge_zero_stage.sh'
    ).read_text(encoding='utf-8')
    watchdog = runner.index('safe_cmd_vel_watchdog_zero.launch')
    gateway = runner.index('tracked_base_zero_output.launch.py')
    bridge = runner.index('ros1_bridge dynamic_bridge')
    ros2_proof = runner.index('ROS1_BRIDGE_ROS2_ZERO_MONITORING')
    ros1_proof = runner.index('ros1_pre_driver_verifier.log')
    vendor = runner.index('limo_start_private_cmd.launch')
    assert watchdog < gateway < bridge < ros2_proof < ros1_proof < vendor
    assert 'kill -TERM' in runner
    assert 'kill -KILL' in runner
    assert 'kill -0 -- "-${process_pid}"' in runner
    assert 'wait "${process_pid}"' in runner
    assert 'verify_cleanup' in runner
    assert 'verify_uart_idle' in runner
    assert 'verify_driver_exclusion' in runner
    assert 'could not prove ROS2 driver exclusion' in runner
    assert 'roscore|rosmaster|limo_base_node' in runner
    assert '--bridge-all-topics' not in runner
    assert runner.count(
        '__name:=/verify_ros1_base_zero_stage_topology') == 2
    assert runner.count(
        '_ready_topic:=/cleanup/base/zero_stage_topology_ready') == 2
    assert '__name:=/verify_ros1_base_bridge_topology' not in runner

    production_runner = (
        ROS1_PACKAGE / 'scripts' / 'run_v2_bridged_navigation.py'
    ).read_text(encoding='utf-8')
    assert production_runner.count(
        "'__name:=/verify_ros1_base_bridge_topology'") == 2
    assert '/verify_ros1_base_zero_stage_topology' not in production_runner

    verifier_source = (
        ROS1_PACKAGE / 'scripts' / 'verify_ros1_base_bridge_topology.py'
    ).read_text(encoding='utf-8')
    assert "ZERO_STAGE_READY_TOPIC = '/cleanup/base/zero_stage_topology_ready'" \
        in verifier_source
    assert "PRODUCTION_READY_TOPIC = '/cleanup/navigation/ros1_topology_ready'" \
        in verifier_source

    all_production = '\n'.join(
        path.read_text(encoding='utf-8')
        for path in (
            WORKSPACE_ROOT / 'scripts').glob('*')
        if path.is_file() and path.name != 'test_ros1_base_bridge_offline.py'
    )
    assert '--bridge-all-topics' not in all_production


def test_catkin_overlay_audit():
    path = WORKSPACE_ROOT / 'scripts' / 'audit_ros1_catkin_overlay.py'
    spec = importlib.util.spec_from_file_location('catkin_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.audit()


def test_python_syntax():
    paths = (
        ROS1_PACKAGE / 'src' / 'limo_cleanup_ros1_base' /
        'watchdog_policy.py',
        ROS1_PACKAGE / 'src' / 'limo_cleanup_ros1_base' /
        'topology_policy.py',
        ROS1_PACKAGE / 'src' / 'limo_cleanup_ros1_base' /
        'navigation_health.py',
        ROS1_PACKAGE / 'src' / 'limo_cleanup_ros1_base' /
        'navigation_policy.py',
        ROS1_PACKAGE / 'scripts' / 'fail_closed_cmd_vel_watchdog.py',
        ROS1_PACKAGE / 'scripts' / 'fail_closed_navigation_adapter.py',
        ROS1_PACKAGE / 'scripts' / 'verify_ros1_base_bridge_topology.py',
        WORKSPACE_ROOT / 'scripts' /
        'verify_ros1_bridge_ros2_zero_output.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'bridge_protocol.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'navigation_intent_policy.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'navigation_intent_consumer.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'ros2_topology_policy.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'navigation_topology_verifier.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' /
        'limo_cleanup_base' / 'zero_stage_handoff_verifier.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'setup.py',
        WORKSPACE_ROOT / 'src' / 'limo_cleanup_base' / 'launch' /
        'navigation_intent_bridge.launch.py',
    )
    for path in paths:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def main():
    tests = (
        test_watchdog_policy,
        test_ros1_topology_policy,
        test_atomic_navigation_protocol,
        test_status_authorization_and_epoch_store,
        test_exact_voice_and_waypoint_policy,
        test_ros2_source_topology_policy,
        test_launch_manifest_and_runner_contracts,
        test_catkin_overlay_audit,
        test_python_syntax,
    )
    for test in tests:
        test()
        print('PASS: {}'.format(test.__name__))
    print('ROS1_BASE_BRIDGE_OFFLINE_TEST_PASS: {} groups'.format(len(tests)))


if __name__ == '__main__':
    main()
