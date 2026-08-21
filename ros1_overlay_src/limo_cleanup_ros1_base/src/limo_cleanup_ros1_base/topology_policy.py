"""Pure ROS1 graph checks for the bridged LIMO command path."""

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ExpectedTopology:
    """Expected ROS1 owners for the private command chain."""

    bridge_node: str = '/dynamic_bridge'
    watchdog_node: str = '/cleanup_ros1_safe_cmd_vel_watchdog'
    driver_node: str = '/limo_base_node'
    move_base_node: str = '/move_base'
    navigation_adapter_node: str = '/cleanup_ros1_navigation_adapter'
    verifier_node: str = '/verify_ros1_base_bridge_topology'
    production_verifier_node: str = '/verify_ros1_base_bridge_topology'
    zero_stage_verifier_node: str = '/verify_ros1_base_zero_stage_topology'
    request_topic: str = '/cleanup/base/cmd_vel_request'
    bridge_topic: str = '/cleanup/base/safe_cmd_vel'
    driver_topic: str = '/cleanup/base/driver_cmd_vel'
    public_topic: str = '/cmd_vel'
    command_topic: str = '/cleanup/navigation/bridge_command'
    status_topic: str = '/cleanup/navigation/bridge_status'
    intent_topic: str = '/cleanup/navigation_intent'
    scan_topic: str = '/scan'
    scan_node: str = '/ydlidar_lidar_publisher'
    odom_topic: str = '/odom'
    odom_node: str = '/limo_base_node'
    tf_topic: str = '/tf'
    tf_static_topic: str = '/tf_static'
    tf_nodes: tuple = (
        '/amcl',
        '/limo_base_node',
        '/base_link_to_camera_link',
        '/base_link_to_imu_link',
        '/base_link_to_laser_link',
    )
    tf_static_nodes: tuple = ()
    legacy_navigation_topics: tuple = (
        '/cleanup/navigation/goal',
        '/cleanup/navigation/stop',
        '/cleanup/navigation/cancel',
        '/cleanup/navigation/rearm',
    )


def _owners(
        mapping: Mapping[str, Sequence[str]],
        topic: str):
    return list(mapping.get(topic, ()))


def _exact(actual, expected):
    return Counter(actual) == Counter(expected)


def _reject_private_navigation_chain(
        publishers: Mapping[str, Sequence[str]],
        subscribers: Mapping[str, Sequence[str]],
        expected: ExpectedTopology,
        nodes,
        phase: str) -> None:
    """Reject every private navigation owner before its declared phase."""
    forbidden_nodes = {
        expected.move_base_node,
        expected.navigation_adapter_node,
        '/amcl',
        '/map_server',
        '/slam_gmapping',
        '/cartographer_node',
        '/robot_pose_ekf',
    }
    present = Counter(nodes) & Counter(forbidden_nodes)
    if present:
        raise RuntimeError(
            '{} graph contains forbidden core/adapter nodes: {}'.format(
                phase.upper(), sorted(present.elements())))
    for topic in (
            expected.request_topic, expected.command_topic,
            expected.status_topic):
        topic_publishers = _owners(publishers, topic)
        topic_subscribers = _owners(subscribers, topic)
        if topic_publishers or topic_subscribers:
            raise RuntimeError(
                '{} topic {} must have zero endpoints; '
                'publishers={} subscribers={}'.format(
                    phase.upper(), topic, sorted(topic_publishers),
                    sorted(topic_subscribers)))
    for topic in expected.legacy_navigation_topics:
        topic_publishers = _owners(publishers, topic)
        topic_subscribers = _owners(subscribers, topic)
        if topic_publishers or topic_subscribers:
            raise RuntimeError(
                '{} is a forbidden legacy topic; publishers={} '
                'subscribers={}'.format(
                    topic,
                    sorted(topic_publishers),
                    sorted(topic_subscribers)))
    intent_publishers = _owners(publishers, expected.intent_topic)
    intent_subscribers = _owners(subscribers, expected.intent_topic)
    if intent_publishers or intent_subscribers:
        raise RuntimeError(
            '{} must remain ROS2-only; ROS1 publishers={} subscribers={}'.format(
                expected.intent_topic,
                sorted(intent_publishers),
                sorted(intent_subscribers)))


def validate_topology(
        publishers: Mapping[str, Sequence[str]],
        subscribers: Mapping[str, Sequence[str]],
        expected: ExpectedTopology = ExpectedTopology(),
        driver_expected: bool = True,
        navigation_expected: bool = False,
        navigation_phase: str = None,
        monitor_role: str = 'standalone',
        active_nodes=()) -> None:
    """Require exact ROS1 endpoint ownership or raise RuntimeError."""
    bridge_publishers = _owners(publishers, expected.bridge_topic)
    if not _exact(bridge_publishers, [expected.bridge_node]):
        raise RuntimeError(
            '{} publishers are {}, expected only {}'.format(
                expected.bridge_topic,
                sorted(bridge_publishers),
                expected.bridge_node))

    bridge_subscribers = _owners(subscribers, expected.bridge_topic)
    if not _exact(bridge_subscribers, [expected.watchdog_node]):
        raise RuntimeError(
            '{} subscribers are {}, expected only {}'.format(
                expected.bridge_topic,
                sorted(bridge_subscribers),
                expected.watchdog_node))

    driver_publishers = _owners(publishers, expected.driver_topic)
    if not _exact(driver_publishers, [expected.watchdog_node]):
        raise RuntimeError(
            '{} publishers are {}, expected only {}'.format(
                expected.driver_topic,
                sorted(driver_publishers),
                expected.watchdog_node))

    if monitor_role not in {'standalone', 'zero_stage', 'production'}:
        raise RuntimeError('unknown ROS1 topology monitor role')
    if (
            monitor_role == 'zero_stage'
            and expected.verifier_node != expected.zero_stage_verifier_node):
        raise RuntimeError(
            'zero-stage topology monitor must use its canonical node name')
    if (
            monitor_role == 'production'
            and expected.verifier_node != expected.production_verifier_node):
        raise RuntimeError(
            'production topology monitor must use its canonical node name')

    expected_driver_subscribers = [expected.verifier_node]
    if driver_expected:
        expected_driver_subscribers.append(expected.driver_node)
    driver_subscribers = _owners(subscribers, expected.driver_topic)
    valid_driver_subscribers = [expected_driver_subscribers]
    if monitor_role == 'zero_stage':
        # The zero-stage monitor starts first and remains the PID-supervised
        # base/zero proof while the production monitor joins.  It therefore
        # accepts either transition state, but never an unnamed third peer.
        valid_driver_subscribers.append(
            expected_driver_subscribers + [expected.production_verifier_node])
    elif monitor_role == 'production':
        # Production is only valid as a child of the zero-stage safety chain.
        # Requiring that peer also prevents a standalone production runner
        # from silently replacing the independently supervised zero proof.
        valid_driver_subscribers = [
            expected_driver_subscribers + [expected.zero_stage_verifier_node]]
    if not any(
            _exact(driver_subscribers, allowed)
            for allowed in valid_driver_subscribers):
        raise RuntimeError(
            '{} subscribers are {}, expected one of {}'.format(
                expected.driver_topic,
                sorted(driver_subscribers),
                [sorted(allowed) for allowed in valid_driver_subscribers]))

    public_publishers = _owners(publishers, expected.public_topic)
    public_subscribers = _owners(subscribers, expected.public_topic)
    if public_publishers or public_subscribers:
        raise RuntimeError(
            '{} must have zero endpoints, got publishers={} subscribers={}'.format(
                expected.public_topic,
                sorted(public_publishers),
                sorted(public_subscribers)))

    if navigation_phase is None:
        navigation_phase = 'full' if navigation_expected else 'base'
    if navigation_phase not in {'base', 'pre_core', 'post_core', 'full'}:
        raise RuntimeError('unknown ROS1 navigation topology phase')
    nodes = list(active_nodes)
    if navigation_phase == 'base':
        _reject_private_navigation_chain(
            publishers, subscribers, expected, nodes, navigation_phase)
        return
    if navigation_phase == 'pre_core':
        _reject_private_navigation_chain(
            publishers, subscribers, expected, nodes, navigation_phase)
        if not _exact(
                _owners(publishers, expected.scan_topic),
                [expected.scan_node]):
            raise RuntimeError('PRE_CORE /scan owner is not unique YDLidar')
        if not _exact(
                _owners(publishers, expected.odom_topic),
                [expected.odom_node]):
            raise RuntimeError('PRE_CORE /odom owner is not unique limo_base_node')
        pre_core_tf = tuple(
            node for node in expected.tf_nodes if node != '/amcl')
        if not _exact(_owners(publishers, expected.tf_topic), pre_core_tf):
            raise RuntimeError('PRE_CORE /tf owners do not match external chain')
        if not _exact(
                _owners(publishers, expected.tf_static_topic),
                expected.tf_static_nodes):
            raise RuntimeError('PRE_CORE /tf_static must have zero publishers')
        return
    request_publishers = _owners(publishers, expected.request_topic)
    request_subscribers = _owners(subscribers, expected.request_topic)
    if not _exact(request_publishers, [expected.move_base_node]):
        raise RuntimeError(
            '{} publishers are {}, expected only {}'.format(
                expected.request_topic,
                sorted(request_publishers),
                expected.move_base_node))
    if not _exact(request_subscribers, [expected.bridge_node]):
        raise RuntimeError(
            '{} subscribers are {}, expected only {}'.format(
                expected.request_topic,
                sorted(request_subscribers),
                expected.bridge_node))
    if navigation_phase in {'post_core', 'full'}:
        required_nodes = {'/map_server', '/amcl', expected.move_base_node}
        if Counter(nodes) & Counter(required_nodes) != Counter(required_nodes):
            raise RuntimeError(
                'POST_CORE graph is missing map_server/AMCL/move_base')
        if (
                navigation_phase == 'post_core'
                and expected.navigation_adapter_node in nodes):
            raise RuntimeError('POST_CORE adapter must still be absent')
        if navigation_phase == 'post_core':
            for topic in (expected.command_topic, expected.status_topic):
                if _owners(publishers, topic) or _owners(subscribers, topic):
                    raise RuntimeError(
                        'POST_CORE topic {} must have zero endpoints'.format(topic))
        # Sensor and TF ownership is checked below for both post-core and full.

    command_publishers = _owners(publishers, expected.command_topic)
    command_subscribers = _owners(subscribers, expected.command_topic)
    if navigation_phase == 'full' and not _exact(
            command_publishers, [expected.bridge_node]):
        raise RuntimeError(
            '{} publishers are {}, expected bridge only'.format(
                expected.command_topic, sorted(command_publishers)))
    if navigation_phase == 'full' and not _exact(
            command_subscribers, [expected.navigation_adapter_node]):
        raise RuntimeError(
            '{} subscribers are {}, expected adapter only'.format(
                expected.command_topic, sorted(command_subscribers)))
    status_publishers = _owners(publishers, expected.status_topic)
    status_subscribers = _owners(subscribers, expected.status_topic)
    if navigation_phase == 'full' and not _exact(
            status_publishers, [expected.navigation_adapter_node]):
        raise RuntimeError(
            '{} publishers are {}, expected adapter only'.format(
                expected.status_topic, sorted(status_publishers)))
    if navigation_phase == 'full' and not _exact(
            status_subscribers, [expected.bridge_node]):
        raise RuntimeError(
            '{} subscribers are {}, expected bridge only'.format(
                expected.status_topic, sorted(status_subscribers)))
    for topic in expected.legacy_navigation_topics:
        topic_publishers = _owners(publishers, topic)
        topic_subscribers = _owners(subscribers, topic)
        if topic_publishers or topic_subscribers:
            raise RuntimeError(
                '{} is a forbidden legacy topic; publishers={} '
                'subscribers={}'.format(
                    topic,
                    sorted(topic_publishers),
                    sorted(topic_subscribers)))
    intent_publishers = _owners(publishers, expected.intent_topic)
    intent_subscribers = _owners(subscribers, expected.intent_topic)
    if intent_publishers or intent_subscribers:
        raise RuntimeError(
            '{} must remain ROS2-only; ROS1 publishers={} subscribers={}'.format(
                expected.intent_topic,
                sorted(intent_publishers),
                sorted(intent_subscribers)))
    if not _exact(
            _owners(publishers, expected.scan_topic), [expected.scan_node]):
        raise RuntimeError('/scan must have exactly one accepted YDLidar owner')
    if not _exact(
            _owners(publishers, expected.odom_topic), [expected.odom_node]):
        raise RuntimeError('/odom must have exactly one limo_base_node owner')
    if not _exact(
            _owners(publishers, expected.tf_topic), expected.tf_nodes):
        raise RuntimeError('/tf owners do not match AMCL+limo_base contract')
    if not _exact(
            _owners(publishers, expected.tf_static_topic),
            expected.tf_static_nodes):
        raise RuntimeError('/tf_static must have zero publishers in vendor TF mode')
