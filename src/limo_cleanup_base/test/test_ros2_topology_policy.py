import pytest

from limo_cleanup_base.ros2_topology_policy import (
    EndpointMetadataContract,
    ExpectedRos2Topology,
    endpoint_metadata_contracts,
    endpoint_names_with_unique_gids,
    validate_endpoint_metadata,
    validate_ros2_navigation_topology,
)


def _valid_topology():
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
            expected.consumer_node, expected.controller_node],
        expected.topology_bootstrap_topic: [expected.consumer_node],
        expected.safety_topic: [expected.controller_node],
        expected.safe_topic: [
            expected.bridge_node, expected.zero_verifier_node],
    }
    return expected, publishers, subscribers


def test_exact_ros2_source_owners_pass():
    _, publishers, subscribers = _valid_topology()
    validate_ros2_navigation_topology(publishers, subscribers)


def test_bootstrap_topology_requires_intent_endpoint_absent_until_activation():
    expected, publishers, subscribers = _valid_topology()
    subscribers[expected.intent_topic] = []
    validate_ros2_navigation_topology(
        publishers, subscribers, intent_subscriber_expected=False)
    with pytest.raises(RuntimeError):
        validate_ros2_navigation_topology(publishers, subscribers)


@pytest.mark.parametrize('topic', [
    '/cleanup/navigation/goal',
    '/cleanup/navigation/rearm',
    '/cleanup/base/cmd_vel_request',
])
def test_rogue_source_publishers_are_rejected(topic):
    _, publishers, subscribers = _valid_topology()
    publishers.setdefault(topic, []).append('/rogue_source')
    with pytest.raises(RuntimeError):
        validate_ros2_navigation_topology(publishers, subscribers)


def test_safety_source_is_forbidden_until_implemented():
    expected, publishers, subscribers = _valid_topology()
    publishers[expected.safety_topic] = ['/manual_safety_pub']
    with pytest.raises(RuntimeError):
        validate_ros2_navigation_topology(publishers, subscribers)


def test_duplicate_same_fqn_endpoint_is_not_hidden_by_set_deduplication():
    expected, publishers, subscribers = _valid_topology()
    publishers[expected.command_topic].append(expected.consumer_node)
    with pytest.raises(RuntimeError):
        validate_ros2_navigation_topology(publishers, subscribers)


def test_endpoint_gid_must_be_present_nonzero_and_unique():
    assert endpoint_names_with_unique_gids([
        ('/same', bytes([1])), ('/same', bytes([2]))]) == ['/same', '/same']
    for records in (
            [('/node', b'')],
            [('/node', bytes([0, 0]))],
            [('/a', bytes([1])), ('/b', bytes([1]))]):
        with pytest.raises(RuntimeError):
            endpoint_names_with_unique_gids(records)


def test_endpoint_type_and_qos_contract_is_fail_closed():
    contract = EndpointMetadataContract('std_msgs/msg/String')
    validate_endpoint_metadata(
        'std_msgs/msg/String', 'RELIABLE', 'VOLATILE', 'KEEP_LAST', 1,
        contract)
    for mutation in (
        ('geometry_msgs/msg/Twist', 'RELIABLE', 'VOLATILE', 'KEEP_LAST', 1),
        ('std_msgs/msg/String', 'BEST_EFFORT', 'VOLATILE', 'KEEP_LAST', 1),
        ('std_msgs/msg/String', 'RELIABLE', 'TRANSIENT_LOCAL', 'KEEP_LAST', 1),
        ('std_msgs/msg/String', 'RELIABLE', 'VOLATILE', 'KEEP_ALL', 1),
        ('std_msgs/msg/String', 'RELIABLE', 'VOLATILE', 'KEEP_LAST', 10)):
        with pytest.raises(RuntimeError):
            validate_endpoint_metadata(*mutation, contract)


def test_all_control_and_safety_topics_require_exact_volatile_durability():
    expected = ExpectedRos2Topology()
    publishers, subscribers = endpoint_metadata_contracts(expected)
    required_topics = {
        expected.intent_topic,
        expected.command_topic,
        expected.status_topic,
        expected.request_topic,
        expected.authorization_topic,
        expected.topology_ready_topic,
        expected.topology_bootstrap_topic,
        expected.safety_topic,
        expected.safe_topic,
    }
    assert set(publishers) == required_topics
    assert set(subscribers) == required_topics
    contracts = [
        contract
        for mapping in (publishers, subscribers)
        for owners in mapping.values()
        for contract in owners.values()
    ]
    assert contracts
    assert {contract.durability for contract in contracts} == {'VOLATILE'}


def test_dynamic_bridge_depth_is_explicit_not_a_positive_lower_bound():
    expected = ExpectedRos2Topology()
    publishers, subscribers = endpoint_metadata_contracts(expected)
    bridge_contracts = (
        publishers[expected.status_topic][expected.bridge_node],
        publishers[expected.request_topic][expected.bridge_node],
        subscribers[expected.command_topic][expected.bridge_node],
        subscribers[expected.safe_topic][expected.bridge_node],
    )
    assert {contract.depth for contract in bridge_contracts} == {10}
    for contract in bridge_contracts:
        with pytest.raises(RuntimeError):
            validate_endpoint_metadata(
                contract.topic_type,
                contract.reliability,
                contract.durability,
                contract.history,
                1,
                contract,
            )
