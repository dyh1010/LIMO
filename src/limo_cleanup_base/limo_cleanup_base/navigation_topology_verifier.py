"""Continuously verify ROS2 source owners before ros1_bridge."""

import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool

from limo_cleanup_base.ros2_topology_policy import (
    ExpectedRos2Topology,
    endpoint_metadata_contracts,
    endpoint_names_with_unique_gids,
    validate_endpoint_metadata,
    validate_ros2_navigation_topology,
)


def _fully_qualified_name(name, namespace):
    namespace = str(namespace or '/').rstrip('/') or '/'
    if namespace == '/':
        return '/{}'.format(name)
    return '{}/{}'.format(namespace, name)


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


def _endpoint_names(endpoints, contracts):
    records = []
    for endpoint in endpoints:
        endpoint_name = _fully_qualified_name(
            endpoint.node_name, endpoint.node_namespace)
        contract = contracts.get(endpoint_name)
        if contract is None:
            raise RuntimeError(
                'unexpected ROS2 endpoint owner {}'.format(endpoint_name))
        gid = getattr(endpoint, 'endpoint_gid', None)
        if gid is None:
            raise RuntimeError('ROS2 endpoint GID API is unavailable')
        qos = getattr(endpoint, 'qos_profile', None)
        if qos is None:
            raise RuntimeError('ROS2 endpoint QoS API is unavailable')
        validate_endpoint_metadata(
            getattr(endpoint, 'topic_type', None),
            _policy_name(getattr(qos, 'reliability', None)),
            _policy_name(getattr(qos, 'durability', None)),
            _policy_name(getattr(qos, 'history', None)),
            getattr(qos, 'depth', None),
            contract,
        )
        records.append((
            endpoint_name,
            gid,
        ))
    return endpoint_names_with_unique_gids(records)


class NavigationTopologyVerifier(Node):
    """Detect rogue ROS2 publishers that ROS1 can only see as bridge."""

    def __init__(self):
        super().__init__('verify_ros2_navigation_bridge_topology')
        self.declare_parameter('continuous', True)
        self.declare_parameter('voice_expected', True)
        self.declare_parameter('safety_source_expected', False)
        self.continuous = bool(self.get_parameter('continuous').value)
        self.voice_expected = bool(
            self.get_parameter('voice_expected').value)
        self.safety_source_expected = bool(
            self.get_parameter('safety_source_expected').value)
        self.expected = ExpectedRos2Topology()
        self.ready_publisher = self.create_publisher(
            Bool, self.expected.topology_ready_topic, 1)
        self.bootstrap_publisher = self.create_publisher(
            Bool, self.expected.topology_bootstrap_topic, 1)

    def publish_ready(self, ready):
        message = Bool()
        message.data = bool(ready)
        self.ready_publisher.publish(message)

    def publish_bootstrap(self, ready):
        message = Bool()
        message.data = bool(ready)
        self.bootstrap_publisher.publish(message)

    def _owners(self, getter, topic, contracts):
        return _endpoint_names(getter(topic), contracts)

    def verify(self, intent_subscriber_expected=True):
        topics = {
            self.expected.intent_topic,
            self.expected.command_topic,
            self.expected.status_topic,
            self.expected.request_topic,
            self.expected.authorization_topic,
            self.expected.topology_ready_topic,
            self.expected.topology_bootstrap_topic,
            self.expected.safety_topic,
            self.expected.safe_topic,
            *self.expected.forbidden_topics,
        }
        publisher_contracts, subscriber_contracts = (
            endpoint_metadata_contracts(
                self.expected,
                voice_expected=self.voice_expected,
                safety_source_expected=self.safety_source_expected,
                intent_subscriber_expected=intent_subscriber_expected,
            ))
        publishers = {
            topic: self._owners(
                self.get_publishers_info_by_topic,
                topic,
                publisher_contracts.get(topic, {}))
            for topic in topics
        }
        subscribers = {
            topic: self._owners(
                self.get_subscriptions_info_by_topic,
                topic,
                subscriber_contracts.get(topic, {}))
            for topic in topics
        }
        validate_ros2_navigation_topology(
            publishers,
            subscribers,
            expected=self.expected,
            voice_expected=self.voice_expected,
            safety_source_expected=self.safety_source_expected,
            intent_subscriber_expected=intent_subscriber_expected,
        )


def run_verification():
    verifier = NavigationTopologyVerifier()
    deadline = time.monotonic() + 10.0
    last_error = None
    try:
        verifier.publish_bootstrap(False)
        while rclpy.ok() and time.monotonic() < deadline:
            verifier.publish_ready(False)
            rclpy.spin_once(verifier, timeout_sec=0.1)
            try:
                verifier.verify(intent_subscriber_expected=False)
                verifier.publish_bootstrap(True)
                full_deadline = time.monotonic() + 10.0
                while rclpy.ok() and time.monotonic() < full_deadline:
                    rclpy.spin_once(verifier, timeout_sec=0.1)
                    try:
                        verifier.verify(intent_subscriber_expected=True)
                        break
                    except RuntimeError as error:
                        last_error = error
                else:
                    raise last_error or RuntimeError(
                        'full ROS2 navigation topology did not become ready')
                last_error = None
                verifier.publish_ready(True)
                print('ROS2_NAVIGATION_TOPOLOGY_PASS', flush=True)
                if not verifier.continuous:
                    return 0
                print('ROS2_NAVIGATION_TOPOLOGY_MONITORING', flush=True)
                while rclpy.ok():
                    rclpy.spin_once(verifier, timeout_sec=0.1)
                    verifier.verify()
                    verifier.publish_ready(True)
                return 0
            except RuntimeError as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise RuntimeError('navigation topology did not become ready')
    finally:
        verifier.publish_ready(False)
        verifier.publish_bootstrap(False)
        verifier.destroy_node()


def main(args=None):
    rclpy.init(args=args)
    try:
        return run_verification()
    except (KeyboardInterrupt, ExternalShutdownException):
        return 0
    except Exception as error:
        print(
            'ROS2_NAVIGATION_TOPOLOGY_BLOCKED: {}'.format(error),
            flush=True,
        )
        return 1
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
