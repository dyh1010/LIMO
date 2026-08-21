from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.topology_policy import (  # noqa: E402
    ExpectedTopology,
    validate_topology,
)


EXPECTED = ExpectedTopology()


def _valid_graph(driver_expected=True):
    publishers = {
        EXPECTED.bridge_topic: [EXPECTED.bridge_node],
        EXPECTED.driver_topic: [EXPECTED.watchdog_node],
    }
    driver_subscribers = [EXPECTED.verifier_node]
    if driver_expected:
        driver_subscribers.append(EXPECTED.driver_node)
    subscribers = {
        EXPECTED.bridge_topic: [EXPECTED.watchdog_node],
        EXPECTED.driver_topic: driver_subscribers,
    }
    return publishers, subscribers


def _assert_early_phase_rejects_private_navigation_chain():
    phase_cases = (
        {'navigation_expected': False},
        {'navigation_phase': 'base'},
        {'navigation_phase': 'pre_core'},
    )
    private_endpoints = {
        EXPECTED.request_topic: {
            'publishers': EXPECTED.move_base_node,
            'subscribers': EXPECTED.bridge_node,
        },
        EXPECTED.command_topic: {
            'publishers': EXPECTED.bridge_node,
            'subscribers': EXPECTED.navigation_adapter_node,
        },
        EXPECTED.status_topic: {
            'publishers': EXPECTED.navigation_adapter_node,
            'subscribers': EXPECTED.bridge_node,
        },
    }
    forbidden_nodes = (
        '/map_server', '/amcl', EXPECTED.move_base_node,
        EXPECTED.navigation_adapter_node, '/slam_gmapping',
        '/cartographer_node', '/robot_pose_ekf',
    )
    base_nodes = (
        EXPECTED.bridge_node, EXPECTED.watchdog_node, EXPECTED.driver_node,
        EXPECTED.verifier_node,
    )

    def early_phase_graph(phase_kwargs):
        publishers, subscribers = _valid_graph()
        active_nodes = base_nodes
        if phase_kwargs.get('navigation_phase') == 'pre_core':
            publishers.update({
                EXPECTED.scan_topic: [EXPECTED.scan_node],
                EXPECTED.odom_topic: [EXPECTED.odom_node],
                EXPECTED.tf_topic: [
                    node for node in EXPECTED.tf_nodes if node != '/amcl'],
                EXPECTED.tf_static_topic: list(EXPECTED.tf_static_nodes),
            })
            active_nodes += (EXPECTED.scan_node,)
        return publishers, subscribers, active_nodes

    for phase_kwargs in phase_cases:
        phase_label = (
            'PRE_CORE'
            if phase_kwargs.get('navigation_phase') == 'pre_core'
            else 'BASE')
        publishers, subscribers, active_nodes = early_phase_graph(
            phase_kwargs)
        validate_topology(
            publishers, subscribers, active_nodes=active_nodes,
            **phase_kwargs)
        assert not publishers.get(EXPECTED.public_topic)
        assert not subscribers.get(EXPECTED.public_topic)

        for node in forbidden_nodes:
            publishers, subscribers, active_nodes = early_phase_graph(
                phase_kwargs)
            with pytest.raises(
                    RuntimeError,
                    match='{} graph contains forbidden'.format(phase_label)):
                validate_topology(
                    publishers, subscribers,
                    active_nodes=active_nodes + (node,),
                    **phase_kwargs)

        for topic, endpoints in private_endpoints.items():
            for side, canonical_owner in endpoints.items():
                publishers, subscribers, active_nodes = early_phase_graph(
                    phase_kwargs)
                mapping = publishers if side == 'publishers' else subscribers
                mapping[topic] = [canonical_owner]
                with pytest.raises(
                        RuntimeError, match='must have zero endpoints'):
                    validate_topology(
                        publishers, subscribers, active_nodes=active_nodes,
                        **phase_kwargs)

                for owners in (
                        [canonical_owner, canonical_owner],
                        [canonical_owner, '/rogue_navigation_owner']):
                    publishers, subscribers, active_nodes = early_phase_graph(
                        phase_kwargs)
                    mapping = (
                        publishers if side == 'publishers' else subscribers)
                    mapping[topic] = owners
                    with pytest.raises(
                            RuntimeError, match='must have zero endpoints'):
                        validate_topology(
                            publishers, subscribers,
                            active_nodes=active_nodes, **phase_kwargs)

        for topic in EXPECTED.legacy_navigation_topics + (
                EXPECTED.intent_topic,):
            message = (
                'must remain ROS2-only'
                if topic == EXPECTED.intent_topic
                else 'forbidden legacy topic')
            for side in ('publishers', 'subscribers'):
                for owners in (
                        ['/forbidden_ros1_navigation_owner'],
                        ['/forbidden_ros1_navigation_owner',
                         '/forbidden_ros1_navigation_owner'],
                        ['/rogue_navigation_owner'],
                        ['/forbidden_ros1_navigation_owner',
                         '/rogue_navigation_owner']):
                    publishers, subscribers, active_nodes = early_phase_graph(
                        phase_kwargs)
                    mapping = (
                        publishers if side == 'publishers' else subscribers)
                    mapping[topic] = owners
                    with pytest.raises(RuntimeError, match=message):
                        validate_topology(
                            publishers, subscribers,
                            active_nodes=active_nodes, **phase_kwargs)

        publishers, subscribers, active_nodes = early_phase_graph(
            phase_kwargs)
        publishers.update({
            EXPECTED.request_topic: [EXPECTED.move_base_node],
            EXPECTED.command_topic: [EXPECTED.bridge_node],
            EXPECTED.status_topic: [EXPECTED.navigation_adapter_node],
        })
        subscribers.update({
            EXPECTED.request_topic: [EXPECTED.bridge_node],
            EXPECTED.command_topic: [EXPECTED.navigation_adapter_node],
            EXPECTED.status_topic: [EXPECTED.bridge_node],
        })
        with pytest.raises(
                RuntimeError,
                match='{} graph contains forbidden'.format(phase_label)):
            validate_topology(
                publishers, subscribers,
                active_nodes=active_nodes + forbidden_nodes,
                **phase_kwargs)


def test_exact_full_topology_passes():
    publishers, subscribers = _valid_graph()
    validate_topology(publishers, subscribers)
    # Keep the frozen bridge test denominator stable while exhaustively
    # exercising every supported early phase without adding pytest node IDs.
    _assert_early_phase_rejects_private_navigation_chain()

    # The zero-stage monitor survives the production peer joining; production
    # is invalid unless that independently supervised peer is present.
    zero_stage = ExpectedTopology(
        verifier_node=EXPECTED.zero_stage_verifier_node)
    zero_publishers = {
        zero_stage.bridge_topic: [zero_stage.bridge_node],
        zero_stage.driver_topic: [zero_stage.watchdog_node],
    }
    zero_subscribers = {
        zero_stage.bridge_topic: [zero_stage.watchdog_node],
        zero_stage.driver_topic: [
            zero_stage.zero_stage_verifier_node,
            zero_stage.driver_node,
        ],
    }
    validate_topology(
        zero_publishers, zero_subscribers, expected=zero_stage,
        monitor_role='zero_stage')
    zero_subscribers[zero_stage.driver_topic].append(
        zero_stage.production_verifier_node)
    validate_topology(
        zero_publishers, zero_subscribers, expected=zero_stage,
        monitor_role='zero_stage')
    validate_topology(
        zero_publishers, zero_subscribers, expected=EXPECTED,
        monitor_role='production')

    for invalid_subscribers in (
            [EXPECTED.production_verifier_node, EXPECTED.driver_node],
            [EXPECTED.production_verifier_node,
             EXPECTED.zero_stage_verifier_node,
             EXPECTED.driver_node, '/rogue_monitor']):
        bad = dict(zero_subscribers)
        bad[EXPECTED.driver_topic] = invalid_subscribers
        with pytest.raises(RuntimeError):
            validate_topology(
                zero_publishers, bad, expected=EXPECTED,
                monitor_role='production')

    with pytest.raises(RuntimeError):
        validate_topology(
            zero_publishers, zero_subscribers, expected=EXPECTED,
            monitor_role='zero_stage')


def test_pre_driver_topology_passes_only_when_explicit():
    publishers, subscribers = _valid_graph(driver_expected=False)
    validate_topology(publishers, subscribers, driver_expected=False)
    with pytest.raises(RuntimeError):
        validate_topology(publishers, subscribers, driver_expected=True)


def test_navigation_bridge_requires_exact_direction_and_private_request():
    publishers, subscribers = _valid_graph()
    publishers[EXPECTED.request_topic] = [EXPECTED.move_base_node]
    subscribers[EXPECTED.request_topic] = [EXPECTED.bridge_node]
    publishers[EXPECTED.command_topic] = [EXPECTED.bridge_node]
    subscribers[EXPECTED.command_topic] = [
        EXPECTED.navigation_adapter_node]
    publishers[EXPECTED.status_topic] = [
        EXPECTED.navigation_adapter_node]
    subscribers[EXPECTED.status_topic] = [EXPECTED.bridge_node]
    publishers[EXPECTED.scan_topic] = [EXPECTED.scan_node]
    publishers[EXPECTED.odom_topic] = [EXPECTED.odom_node]
    publishers[EXPECTED.tf_topic] = list(EXPECTED.tf_nodes)
    publishers[EXPECTED.tf_static_topic] = list(EXPECTED.tf_static_nodes)
    validate_topology(
        publishers, subscribers, navigation_expected=True,
        active_nodes=['/map_server', '/amcl', '/move_base'])

    subscribers[EXPECTED.request_topic].append('/rogue_request_consumer')
    with pytest.raises(RuntimeError):
        validate_topology(
            publishers, subscribers, navigation_expected=True,
            active_nodes=['/map_server', '/amcl', '/move_base'])


def test_navigation_bridge_rejects_legacy_topic_or_ros1_intent_endpoint():
    publishers, subscribers = _valid_graph()
    publishers[EXPECTED.request_topic] = [EXPECTED.move_base_node]
    subscribers[EXPECTED.request_topic] = [EXPECTED.bridge_node]
    publishers[EXPECTED.command_topic] = [EXPECTED.bridge_node]
    subscribers[EXPECTED.command_topic] = [
        EXPECTED.navigation_adapter_node]
    publishers[EXPECTED.status_topic] = [
        EXPECTED.navigation_adapter_node]
    subscribers[EXPECTED.status_topic] = [EXPECTED.bridge_node]
    publishers[EXPECTED.scan_topic] = [EXPECTED.scan_node]
    publishers[EXPECTED.odom_topic] = [EXPECTED.odom_node]
    publishers[EXPECTED.tf_topic] = list(EXPECTED.tf_nodes)
    publishers[EXPECTED.tf_static_topic] = list(EXPECTED.tf_static_nodes)

    full_nodes = [
        '/map_server', '/amcl', EXPECTED.move_base_node,
        EXPECTED.navigation_adapter_node,
    ]
    validate_topology(
        publishers, subscribers, navigation_phase='full',
        active_nodes=full_nodes)

    post_publishers = {
        topic: list(owners) for topic, owners in publishers.items()
        if topic not in (EXPECTED.command_topic, EXPECTED.status_topic)}
    post_subscribers = {
        topic: list(owners) for topic, owners in subscribers.items()
        if topic not in (EXPECTED.command_topic, EXPECTED.status_topic)}
    validate_topology(
        post_publishers, post_subscribers, navigation_phase='post_core',
        active_nodes=['/map_server', '/amcl', EXPECTED.move_base_node])

    for phase, baseline_publishers, baseline_subscribers, nodes in (
            ('post_core', post_publishers, post_subscribers,
             ['/map_server', '/amcl', EXPECTED.move_base_node]),
            ('full', publishers, subscribers, full_nodes)):
        for topic in EXPECTED.legacy_navigation_topics + (
                EXPECTED.intent_topic,):
            for side in ('publishers', 'subscribers'):
                candidate_publishers = {
                    key: list(value)
                    for key, value in baseline_publishers.items()}
                candidate_subscribers = {
                    key: list(value)
                    for key, value in baseline_subscribers.items()}
                mapping = (
                    candidate_publishers
                    if side == 'publishers' else candidate_subscribers)
                mapping[topic] = ['/rogue_ros1_navigation_owner']
                with pytest.raises(RuntimeError):
                    validate_topology(
                        candidate_publishers, candidate_subscribers,
                        navigation_phase=phase, active_nodes=nodes)


@pytest.mark.parametrize('topic,owners', [
    (EXPECTED.scan_topic, ['/rogue_lidar']),
    (EXPECTED.tf_topic, ['/amcl', '/rogue_tf']),
    (EXPECTED.tf_static_topic, ['/rogue_static_tf']),
])
def test_navigation_sensor_and_tf_owner_spoofing_blocks(topic, owners):
    publishers, subscribers = _valid_graph()
    publishers.update({
        EXPECTED.request_topic: [EXPECTED.move_base_node],
        EXPECTED.command_topic: [EXPECTED.bridge_node],
        EXPECTED.status_topic: [EXPECTED.navigation_adapter_node],
        EXPECTED.scan_topic: [EXPECTED.scan_node],
        EXPECTED.odom_topic: [EXPECTED.odom_node],
        EXPECTED.tf_topic: list(EXPECTED.tf_nodes),
        EXPECTED.tf_static_topic: list(EXPECTED.tf_static_nodes),
    })
    subscribers.update({
        EXPECTED.request_topic: [EXPECTED.bridge_node],
        EXPECTED.command_topic: [EXPECTED.navigation_adapter_node],
        EXPECTED.status_topic: [EXPECTED.bridge_node],
    })
    publishers[topic] = owners
    with pytest.raises(RuntimeError):
        validate_topology(
            publishers, subscribers, navigation_expected=True,
            active_nodes=['/map_server', '/amcl', '/move_base'])


@pytest.mark.parametrize(
    'side,topic,extra_owner',
    [
        ('publishers', EXPECTED.bridge_topic, '/rogue_bridge'),
        ('subscribers', EXPECTED.bridge_topic, '/rogue_consumer'),
        ('publishers', EXPECTED.driver_topic, '/teleop'),
        ('subscribers', EXPECTED.driver_topic, '/rogue_driver'),
        ('publishers', EXPECTED.public_topic, '/teleop'),
        ('subscribers', EXPECTED.public_topic, '/rogue_driver'),
    ],
)
def test_any_extra_command_endpoint_blocks(side, topic, extra_owner):
    publishers, subscribers = _valid_graph()
    mapping = publishers if side == 'publishers' else subscribers
    mapping.setdefault(topic, []).append(extra_owner)
    with pytest.raises(RuntimeError):
        validate_topology(publishers, subscribers)
