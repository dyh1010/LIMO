#!/usr/bin/env python3
"""Read-only ROS1 topology and zero-output verifier for the base bridge."""

import math
import os
import socket
import stat
import time

from geometry_msgs.msg import Twist
import rosgraph
import rospy
from std_msgs.msg import Bool

from limo_cleanup_ros1_base.topology_policy import (
    ExpectedTopology,
    validate_topology,
)


ZERO_EPSILON = 1e-9
MINIMUM_SAMPLES = 10
PRODUCTION_VERIFIER_NODE = '/verify_ros1_base_bridge_topology'
ZERO_STAGE_VERIFIER_NODE = '/verify_ros1_base_zero_stage_topology'
PRODUCTION_READY_TOPIC = '/cleanup/navigation/ros1_topology_ready'
ZERO_STAGE_READY_TOPIC = '/cleanup/base/zero_stage_topology_ready'


def _system_state(timeout):
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        master = rosgraph.Master(rospy.get_name())
        publishers, subscribers, services = master.getSystemState()
        active_nodes = []
        for _name, owners in publishers + subscribers + services:
            active_nodes.extend(owners)
        return dict(publishers), dict(subscribers), active_nodes
    finally:
        socket.setdefaulttimeout(previous_timeout)


def _twist_values(message):
    return (
        float(message.linear.x),
        float(message.linear.y),
        float(message.linear.z),
        float(message.angular.x),
        float(message.angular.y),
        float(message.angular.z),
    )


class Ros1BaseBridgeVerifier:
    """Collect zero samples while repeatedly checking exact graph owners."""

    def __init__(self):
        self.monitor_role = str(
            rospy.get_param('~monitor_role', 'standalone')).strip()
        if self.monitor_role not in {
                'standalone', 'zero_stage', 'production'}:
            raise ValueError('monitor_role must be standalone, zero_stage, or production')
        if (
                self.monitor_role == 'zero_stage'
                and rospy.get_name() != ZERO_STAGE_VERIFIER_NODE):
            raise RuntimeError(
                'zero-stage monitor must use {}'.format(
                    ZERO_STAGE_VERIFIER_NODE))
        if (
                self.monitor_role == 'production'
                and rospy.get_name() != PRODUCTION_VERIFIER_NODE):
            raise RuntimeError(
                'production monitor must use {}'.format(
                    PRODUCTION_VERIFIER_NODE))
        self.driver_expected = bool(rospy.get_param('~driver_expected', True))
        self.navigation_expected = bool(
            rospy.get_param('~navigation_expected', False))
        self.navigation_phase = rospy.get_param(
            '~navigation_phase',
            'full' if self.navigation_expected else 'base')
        self.bootstrap_then_full = bool(
            rospy.get_param('~bootstrap_then_full', False))
        self.continuous = bool(rospy.get_param('~continuous', False))
        self.graph_query_timeout = float(
            rospy.get_param('~graph_query_timeout', 1.0))
        if not 0.0 < self.graph_query_timeout <= 2.0:
            raise ValueError('graph_query_timeout must be in (0, 2] seconds')
        self.expected = ExpectedTopology(
            bridge_node=rospy.get_param('~bridge_node', '/dynamic_bridge'),
            watchdog_node=rospy.get_param(
                '~watchdog_node', '/cleanup_ros1_safe_cmd_vel_watchdog'),
            driver_node=rospy.get_param('~driver_node', '/limo_base_node'),
            verifier_node=rospy.get_name(),
        )
        self.samples = []
        self.invalid_sample = None
        default_ready_topic = (
            ZERO_STAGE_READY_TOPIC
            if self.monitor_role == 'zero_stage'
            else PRODUCTION_READY_TOPIC)
        ready_topic = rospy.get_param('~ready_topic', default_ready_topic)
        if (
                self.monitor_role == 'zero_stage'
                and ready_topic != ZERO_STAGE_READY_TOPIC):
            raise RuntimeError(
                'zero-stage monitor READY topic must remain isolated')
        if (
                self.monitor_role == 'production'
                and ready_topic != PRODUCTION_READY_TOPIC):
            raise RuntimeError(
                'production monitor must own the navigation READY topic')
        self.ready_publisher = rospy.Publisher(
            ready_topic,
            Bool,
            queue_size=1,
            latch=True,
        )
        self.ready_publisher.publish(Bool(data=False))
        self.ready_fd = rospy.get_param('~ready_fd', None)
        self.ready_digest = str(rospy.get_param('~ready_digest', '')).strip()
        self.heartbeat_sequence = 0
        if self.ready_fd is not None:
            if (
                    isinstance(self.ready_fd, bool)
                    or not isinstance(self.ready_fd, int)
                    or self.ready_fd < 3
                    or len(self.ready_digest) != 64
                    or not stat.S_ISFIFO(os.fstat(self.ready_fd).st_mode)):
                raise RuntimeError('private topology ready FD/digest is invalid')
        self.subscription = rospy.Subscriber(
            self.expected.driver_topic,
            Twist,
            self._on_command,
            queue_size=1,
            tcp_nodelay=True,
        )

    def _on_command(self, message):
        values = _twist_values(message)
        if not all(math.isfinite(value) for value in values):
            self.invalid_sample = values
            return
        if any(abs(value) > ZERO_EPSILON for value in values):
            self.invalid_sample = values
            return
        if len(self.samples) < MINIMUM_SAMPLES:
            self.samples.append(values)

    def verify_graph(self):
        publishers, subscribers, active_nodes = _system_state(
            self.graph_query_timeout)
        validate_topology(
            publishers,
            subscribers,
            expected=self.expected,
            driver_expected=self.driver_expected,
            navigation_expected=self.navigation_expected,
            navigation_phase=self.navigation_phase,
            monitor_role=self.monitor_role,
            active_nodes=active_nodes,
        )

    def signal(self, label):
        if self.ready_fd is None:
            return
        payload = '{}:{}:{}\n'.format(
            label, self.ready_digest, self.heartbeat_sequence).encode('ascii')
        self.heartbeat_sequence += 1
        os.write(self.ready_fd, payload)

    def publish_ready(self, value):
        self.ready_publisher.publish(Bool(data=bool(value)))


def run_verification():
    verifier = Ros1BaseBridgeVerifier()
    deadline = time.monotonic() + float(rospy.get_param('~timeout', 8.0))
    rate = rospy.Rate(20.0)
    last_graph_error = None
    full_deadline = None
    while not rospy.is_shutdown() and time.monotonic() < deadline:
        if verifier.invalid_sample is not None:
            raise RuntimeError(
                'invalid or nonzero ROS1 driver command: {}'.format(
                    verifier.invalid_sample))
        try:
            verifier.verify_graph()
            last_graph_error = None
        except RuntimeError as error:
            last_graph_error = error
            verifier.samples.clear()
        if last_graph_error is None and len(verifier.samples) >= MINIMUM_SAMPLES:
            if verifier.bootstrap_then_full and verifier.navigation_phase == 'post_core':
                verifier.signal('ROS1_NAV_TOPOLOGY_POST_CORE_READY')
                print('ROS1_NAV_TOPOLOGY_POST_CORE_READY', flush=True)
                verifier.navigation_phase = 'full'
                verifier.samples.clear()
                verifier.publish_ready(False)
                full_deadline = time.monotonic() + float(
                    rospy.get_param('~full_topology_timeout', 10.0))
                deadline = full_deadline
                continue
            print(
                'ROS1_BASE_BRIDGE_TOPOLOGY_PASS: samples={} driver_expected={} phase={}'.format(
                    len(verifier.samples), verifier.driver_expected,
                    verifier.navigation_phase),
                flush=True)
            if verifier.navigation_phase == 'full':
                verifier.signal('ROS1_NAV_TOPOLOGY_FULL_READY')
                verifier.publish_ready(True)
            if not verifier.continuous:
                if verifier.ready_fd is not None:
                    os.close(verifier.ready_fd)
                return 0
            print('ROS1_BASE_BRIDGE_TOPOLOGY_MONITORING', flush=True)
            verifier.samples.clear()
            while not rospy.is_shutdown():
                if verifier.invalid_sample is not None:
                    raise RuntimeError(
                        'invalid or nonzero ROS1 driver command: {}'.format(
                            verifier.invalid_sample))
                try:
                    verifier.verify_graph()
                except Exception:
                    verifier.publish_ready(False)
                    raise
                if verifier.navigation_phase == 'full':
                    verifier.publish_ready(True)
                    verifier.signal('ROS1_NAV_TOPOLOGY_HEARTBEAT')
                if len(verifier.samples) >= MINIMUM_SAMPLES:
                    print(
                        'ROS1_BASE_BRIDGE_CONTINUOUS_ZERO_WINDOW_PASS',
                        flush=True)
                    verifier.samples.clear()
                rate.sleep()
            return 0
        rate.sleep()
    if last_graph_error is not None:
        verifier.publish_ready(False)
        raise last_graph_error
    raise RuntimeError(
        'received {} zero samples, expected at least {}'.format(
            len(verifier.samples), MINIMUM_SAMPLES))


def main():
    rospy.init_node('verify_ros1_base_bridge_topology')
    try:
        return run_verification()
    except Exception as error:
        print(
            'ROS1_BASE_BRIDGE_TOPOLOGY_BLOCKED: {}'.format(error),
            flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
