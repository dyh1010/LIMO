#!/usr/bin/env python3
"""Prove the zero-stage controller is the sole navigation gateway owner."""

import time

import rclpy
from rclpy.node import Node

from limo_cleanup_base.ros2_topology_policy import (
    EndpointMetadataContract,
    endpoint_names_with_unique_gids,
    validate_endpoint_metadata,
)


SAFE_TOPIC = '/cleanup/base/safe_cmd_vel'
EXPECTED_CONTROLLER = '/cleanup_tracked_base_zero_output'
EXPECTED_BRIDGE = '/dynamic_bridge'
EXPECTED_ZERO_MONITOR = '/verify_ros1_bridge_ros2_zero_output'
FORBIDDEN_TOPICS = (
    '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop', '/limo/vel_cmd',
    '/cleanup/base/driver_cmd_vel',
)


def _fqn(endpoint):
    namespace = str(endpoint.node_namespace or '/').rstrip('/') or '/'
    return ('/' if namespace == '/' else namespace + '/') + endpoint.node_name


def _policy_name(value):
    name = getattr(value, 'name', None)
    if name:
        return str(name).replace('RMW_QOS_POLICY_', '')
    text = str(value).upper()
    for prefix in (
            'RELIABILITYPOLICY.', 'DURABILITYPOLICY.', 'HISTORYPOLICY.',
            'QOSRELIABILITYPOLICY.', 'QOSDURABILITYPOLICY.',
            'QOSHISTORYPOLICY.'):
        text = text.replace(prefix, '')
    return text


def _names(endpoints, contracts):
    records = []
    for endpoint in endpoints:
        name = _fqn(endpoint)
        contract = contracts.get(name)
        if contract is None:
            raise RuntimeError('unexpected zero-stage endpoint {}'.format(name))
        qos = getattr(endpoint, 'qos_profile', None)
        gid = getattr(endpoint, 'endpoint_gid', None)
        if qos is None or gid is None:
            raise RuntimeError('ROS2 endpoint metadata API is unavailable')
        validate_endpoint_metadata(
            getattr(endpoint, 'topic_type', None),
            _policy_name(getattr(qos, 'reliability', None)),
            _policy_name(getattr(qos, 'durability', None)),
            _policy_name(getattr(qos, 'history', None)),
            getattr(qos, 'depth', None), contract)
        records.append((name, gid))
    return endpoint_names_with_unique_gids(records)


class ZeroStageHandoffVerifier(Node):
    """Read endpoint metadata without adding a second command subscriber."""

    def __init__(self):
        super().__init__('verify_ros2_zero_stage_handoff')

    def verify(self):
        twist_1 = EndpointMetadataContract('geometry_msgs/msg/Twist')
        twist_10 = EndpointMetadataContract(
            'geometry_msgs/msg/Twist', depth=10)
        publishers = _names(
            self.get_publishers_info_by_topic(SAFE_TOPIC),
            {EXPECTED_CONTROLLER: twist_1})
        subscribers = _names(
            self.get_subscriptions_info_by_topic(SAFE_TOPIC),
            {EXPECTED_BRIDGE: twist_10, EXPECTED_ZERO_MONITOR: twist_1})
        if publishers != [EXPECTED_CONTROLLER]:
            raise RuntimeError('zero-stage controller owner is not exact')
        if sorted(subscribers) != sorted(
                [EXPECTED_BRIDGE, EXPECTED_ZERO_MONITOR]):
            raise RuntimeError('zero-stage safety consumers are not exact')
        for topic in FORBIDDEN_TOPICS:
            if (
                    self.get_publishers_info_by_topic(topic)
                    or self.get_subscriptions_info_by_topic(topic)):
                raise RuntimeError('{} must have zero endpoints'.format(topic))


def main():
    rclpy.init()
    verifier = ZeroStageHandoffVerifier()
    deadline = time.monotonic() + 5.0
    last_error = None
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(verifier, timeout_sec=0.1)
            try:
                verifier.verify()
                print('ROS2_ZERO_STAGE_HANDOFF_PASS', flush=True)
                return 0
            except RuntimeError as error:
                last_error = error
        raise RuntimeError(last_error or 'zero-stage handoff timed out')
    except Exception as error:
        print('ROS2_ZERO_STAGE_HANDOFF_BLOCKED: {}'.format(error), flush=True)
        return 1
    finally:
        verifier.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
