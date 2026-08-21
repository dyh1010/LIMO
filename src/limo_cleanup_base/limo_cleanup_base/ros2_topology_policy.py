"""Pure ROS2 source-owner checks for the atomic navigation bridge."""

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ExpectedRos2Topology:
    """Expected ROS2 endpoints before commands cross ros1_bridge."""

    bridge_node: str = '/dynamic_bridge'
    consumer_node: str = '/cleanup_navigation_intent_consumer'
    controller_node: str = '/cleanup_tracked_base_zero_output'
    voice_node: str = '/voice_dialogue'
    verifier_node: str = '/verify_ros2_navigation_bridge_topology'
    zero_verifier_node: str = '/verify_ros1_bridge_ros2_zero_output'
    safety_source_node: str = '/cleanup_base_safety_monitor'
    intent_topic: str = '/cleanup/navigation_intent'
    command_topic: str = '/cleanup/navigation/bridge_command'
    status_topic: str = '/cleanup/navigation/bridge_status'
    request_topic: str = '/cleanup/base/cmd_vel_request'
    authorization_topic: str = '/cleanup/base/motion_authorized'
    topology_ready_topic: str = '/cleanup/navigation/topology_ready'
    topology_bootstrap_topic: str = '/cleanup/navigation/topology_bootstrap_ready'
    safety_topic: str = '/cleanup/base/safety_clear'
    safe_topic: str = '/cleanup/base/safe_cmd_vel'
    forbidden_topics: tuple = (
        '/cmd_vel',
        '/cleanup/base/driver_cmd_vel',
        '/cleanup/navigation/goal',
        '/cleanup/navigation/stop',
        '/cleanup/navigation/cancel',
        '/cleanup/navigation/rearm',
    )


@dataclass(frozen=True)
class EndpointMetadataContract:
    """Exact ROS2 type/QoS contract for one endpoint."""

    topic_type: str
    reliability: str = 'RELIABLE'
    durability: str = 'VOLATILE'
    history: str = 'KEEP_LAST'
    depth: int = 1


def _owners(
        mapping: Mapping[str, Sequence[str]],
        topic: str):
    return list(mapping.get(topic, ()))


def endpoint_names_with_unique_gids(records):
    """Preserve endpoint multiplicity and require a unique nonzero GID."""
    names = []
    gids = set()
    for name, gid in records:
        try:
            normalized_gid = bytes(gid)
        except (TypeError, ValueError) as error:
            raise RuntimeError('ROS2 endpoint GID is malformed') from error
        if not normalized_gid or not any(normalized_gid):
            raise RuntimeError('ROS2 endpoint GID is empty/all-zero')
        if normalized_gid in gids:
            raise RuntimeError('duplicate ROS2 endpoint GID detected')
        gids.add(normalized_gid)
        names.append(name)
    return names


def validate_endpoint_metadata(
        topic_type, reliability, durability, history, depth, contract):
    """Require the exact message type and QoS selected for one endpoint."""
    if not isinstance(contract, EndpointMetadataContract):
        raise RuntimeError('ROS2 endpoint metadata contract is missing')
    if topic_type != contract.topic_type:
        raise RuntimeError(
            'ROS2 endpoint type {} does not match {}'.format(
                topic_type, contract.topic_type))
    if reliability != contract.reliability:
        raise RuntimeError(
            'ROS2 endpoint reliability {} does not match {}'.format(
                reliability, contract.reliability))
    if durability != contract.durability:
        raise RuntimeError(
            'ROS2 endpoint durability {} does not match {}'.format(
                durability, contract.durability))
    if history != contract.history:
        raise RuntimeError(
            'ROS2 endpoint history {} does not match {}'.format(
                history, contract.history))
    if (
            not isinstance(depth, int)
            or isinstance(depth, bool)
            or depth != contract.depth):
        raise RuntimeError(
            'ROS2 endpoint depth {} does not match {}'.format(
                depth, contract.depth))


def endpoint_metadata_contracts(
        expected=ExpectedRos2Topology(),
        voice_expected=True,
        safety_source_expected=False,
        intent_subscriber_expected=True):
    """Return exact per-topic/per-owner metadata for publishers/subscribers."""
    string_1 = EndpointMetadataContract('std_msgs/msg/String')
    string_10 = EndpointMetadataContract('std_msgs/msg/String', depth=10)
    bool_1 = EndpointMetadataContract('std_msgs/msg/Bool')
    twist_1 = EndpointMetadataContract('geometry_msgs/msg/Twist')
    twist_10 = EndpointMetadataContract('geometry_msgs/msg/Twist', depth=10)
    publishers = {
        expected.intent_topic: (
            {expected.voice_node: string_10} if voice_expected else {}),
        expected.command_topic: {expected.consumer_node: string_1},
        expected.status_topic: {expected.bridge_node: string_10},
        expected.request_topic: {expected.bridge_node: twist_10},
        expected.authorization_topic: {expected.consumer_node: bool_1},
        expected.topology_ready_topic: {expected.verifier_node: bool_1},
        expected.topology_bootstrap_topic: {expected.verifier_node: bool_1},
        expected.safety_topic: (
            {expected.safety_source_node: bool_1}
            if safety_source_expected else {}),
        expected.safe_topic: {expected.controller_node: twist_1},
    }
    subscribers = {
        expected.intent_topic: (
            {expected.consumer_node: string_1}
            if intent_subscriber_expected else {}),
        expected.command_topic: {expected.bridge_node: string_10},
        expected.status_topic: {expected.consumer_node: string_1},
        expected.request_topic: {expected.controller_node: twist_1},
        expected.authorization_topic: {expected.controller_node: bool_1},
        expected.topology_ready_topic: {
            expected.consumer_node: bool_1,
            expected.controller_node: bool_1,
        },
        expected.topology_bootstrap_topic: {expected.consumer_node: bool_1},
        expected.safety_topic: {expected.controller_node: bool_1},
        expected.safe_topic: {
            expected.bridge_node: twist_10,
            expected.zero_verifier_node: twist_1,
        },
    }
    return publishers, subscribers


def _require_exact(mapping, topic, expected, endpoint_kind):
    actual = _owners(mapping, topic)
    expected_values = list(expected)
    if Counter(actual) != Counter(expected_values):
        raise RuntimeError(
            '{} {} are {}, expected {}'.format(
                topic, endpoint_kind, sorted(actual), sorted(expected_values)))


def validate_ros2_navigation_topology(
        publishers: Mapping[str, Sequence[str]],
        subscribers: Mapping[str, Sequence[str]],
        expected: ExpectedRos2Topology = ExpectedRos2Topology(),
        voice_expected: bool = True,
        safety_source_expected: bool = False,
        intent_subscriber_expected: bool = True) -> None:
    """Reject rogue source publishers hidden behind dynamic_bridge."""
    _require_exact(
        publishers,
        expected.command_topic,
        {expected.consumer_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.command_topic,
        {expected.bridge_node},
        'subscribers',
    )
    _require_exact(
        publishers,
        expected.topology_bootstrap_topic,
        {expected.verifier_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.topology_bootstrap_topic,
        {expected.consumer_node},
        'subscribers',
    )
    _require_exact(
        publishers,
        expected.status_topic,
        {expected.bridge_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.status_topic,
        {expected.consumer_node},
        'subscribers',
    )
    _require_exact(
        publishers,
        expected.request_topic,
        {expected.bridge_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.request_topic,
        {expected.controller_node},
        'subscribers',
    )
    _require_exact(
        publishers,
        expected.authorization_topic,
        {expected.consumer_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.authorization_topic,
        {expected.controller_node},
        'subscribers',
    )
    _require_exact(
        publishers,
        expected.topology_ready_topic,
        {expected.verifier_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.topology_ready_topic,
        {expected.consumer_node, expected.controller_node},
        'subscribers',
    )
    expected_safety_publishers = (
        {expected.safety_source_node} if safety_source_expected else set())
    _require_exact(
        publishers,
        expected.safety_topic,
        expected_safety_publishers,
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.safety_topic,
        {expected.controller_node},
        'subscribers',
    )
    _require_exact(
        publishers,
        expected.safe_topic,
        {expected.controller_node},
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.safe_topic,
        {expected.bridge_node, expected.zero_verifier_node},
        'subscribers',
    )
    expected_voice_publishers = {expected.voice_node} if voice_expected else set()
    _require_exact(
        publishers,
        expected.intent_topic,
        expected_voice_publishers,
        'publishers',
    )
    _require_exact(
        subscribers,
        expected.intent_topic,
        {expected.consumer_node} if intent_subscriber_expected else set(),
        'subscribers',
    )
    for topic in expected.forbidden_topics:
        topic_publishers = _owners(publishers, topic)
        topic_subscribers = _owners(subscribers, topic)
        if topic_publishers or topic_subscribers:
            raise RuntimeError(
                '{} must have zero ROS2 endpoints; publishers={} '
                'subscribers={}'.format(
                    topic,
                    sorted(topic_publishers),
                    sorted(topic_subscribers)))
