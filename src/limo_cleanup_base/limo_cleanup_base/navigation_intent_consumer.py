"""Consume exact voice intents through an atomic internal bridge protocol."""

import math
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String

from limo_cleanup_base.bridge_protocol import (
    CancelRetryPolicy,
    EpochStore,
    NavigationAuthorizationPolicy,
    build_cancel_command,
    build_dispatch_command,
    parse_bridge_status,
)
from limo_cleanup_base.navigation_intent_policy import (
    load_map_waypoint,
    parse_navigation_intent,
)


class NavigationIntentConsumer(Node):
    """Fail closed unless ROS1 acknowledges the exact active epoch."""

    def __init__(self):
        super().__init__('cleanup_navigation_intent_consumer')
        self.declare_parameter('enabled', False)
        self.declare_parameter(
            'intent_topic', '/cleanup/navigation_intent')
        self.declare_parameter(
            'command_topic', '/cleanup/navigation/bridge_command')
        self.declare_parameter(
            'status_topic', '/cleanup/navigation/bridge_status')
        self.declare_parameter(
            'motion_authorized_topic', '/cleanup/base/motion_authorized')
        self.declare_parameter(
            'topology_ready_topic', '/cleanup/navigation/topology_ready')
        self.declare_parameter(
            'topology_bootstrap_topic',
            '/cleanup/navigation/topology_bootstrap_ready')
        self.declare_parameter('waypoint_file', '')
        self.declare_parameter('active_v1_map_id', '')
        self.declare_parameter('epoch_state_file', '')
        self.declare_parameter('status_timeout', 0.25)
        self.declare_parameter('topology_timeout', 0.25)
        self.declare_parameter('cancel_retry_interval', 0.05)
        self.declare_parameter('cancel_retry_timeout', 0.50)
        self.declare_parameter('goal_timeout', 0.0)
        self.declare_parameter('publish_rate', 20.0)
        if not bool(self.get_parameter('enabled').value):
            raise RuntimeError(
                'navigation intent consumer is disabled by default')

        self.waypoint_file = str(
            self.get_parameter('waypoint_file').value).strip()
        self.active_v1_map_id = str(
            self.get_parameter('active_v1_map_id').value).strip()
        self.status_timeout = float(
            self.get_parameter('status_timeout').value)
        self.topology_timeout = float(
            self.get_parameter('topology_timeout').value)
        self.goal_timeout = float(
            self.get_parameter('goal_timeout').value)
        publish_rate = float(self.get_parameter('publish_rate').value)
        if (
                not math.isfinite(self.status_timeout)
                or self.status_timeout <= 0.0
                or not math.isfinite(self.topology_timeout)
                or self.topology_timeout <= 0.0
                or not math.isfinite(self.goal_timeout)
                or self.goal_timeout <= 0.0
                or not math.isfinite(publish_rate)
                or publish_rate <= 0.0):
            raise ValueError('timeouts and rates must be finite and positive')
        epoch_path = str(
            self.get_parameter('epoch_state_file').value).strip()
        self.epoch_store = EpochStore(epoch_path)
        self.policy = NavigationAuthorizationPolicy()
        self._state_lock = threading.RLock()
        self.cancel_retry = CancelRetryPolicy(
            float(self.get_parameter('cancel_retry_interval').value),
            float(self.get_parameter('cancel_retry_timeout').value),
        )

        self.command_publisher = self.create_publisher(
            String, self.get_parameter('command_topic').value, 1)
        self.authorization_publisher = self.create_publisher(
            Bool,
            self.get_parameter('motion_authorized_topic').value,
            1,
        )
        # The intent endpoint does not exist until the first fresh exact
        # topology PASS.  Any earlier voice message is therefore dropped and
        # must be sent again after activation.
        self.intent_subscription = None
        self.status_subscription = self.create_subscription(
            String,
            self.get_parameter('status_topic').value,
            self._on_status,
            1,
        )
        self.topology_subscription = self.create_subscription(
            Bool,
            self.get_parameter('topology_ready_topic').value,
            self._on_topology_ready,
            1,
        )
        self.topology_bootstrap_subscription = self.create_subscription(
            Bool,
            self.get_parameter('topology_bootstrap_topic').value,
            self._on_topology_bootstrap,
            1,
        )
        self.timer = self.create_timer(
            1.0 / publish_rate, self._on_timer)
        self.topology_ready = False
        self.topology_time = -1.0
        self._latch_safe_stop('navigation consumer started stop-latched')

    def _now(self):
        return time.monotonic()

    def _publish_authorization(self, value):
        message = Bool()
        message.data = bool(value)
        self.authorization_publisher.publish(message)

    def _publish_command(self, payload):
        message = String()
        message.data = payload
        self.command_publisher.publish(message)

    def _topology_is_ready(self, now):
        return (
            self.topology_ready
            and self.topology_time >= 0.0
            and now >= self.topology_time
            and now - self.topology_time < self.topology_timeout
        )

    def _on_topology_ready(self, message):
        with self._state_lock:
            self.topology_ready = bool(message.data)
            self.topology_time = self._now()
            if not self.topology_ready:
                if self.intent_subscription is not None:
                    self.destroy_subscription(self.intent_subscription)
                    self.intent_subscription = None
                self._latch_safe_stop('navigation topology is not ready')
                return

    def _on_topology_bootstrap(self, message):
        with self._state_lock:
            if not bool(message.data):
                if self.intent_subscription is not None:
                    self.destroy_subscription(self.intent_subscription)
                    self.intent_subscription = None
                self._latch_safe_stop(
                    'navigation topology bootstrap is unavailable')
                return
            if self.intent_subscription is None:
                self.intent_subscription = self.create_subscription(
                    String,
                    self.get_parameter('intent_topic').value,
                    self._on_intent,
                    1,
                )

    def _allocate_epoch(self):
        return self.epoch_store.allocate()

    def _send_cancel_once(self):
        if self.cancel_retry.active:
            return
        try:
            epoch = self._allocate_epoch()
            payload = build_cancel_command(epoch)
            now = self._now()
            self.cancel_retry.start(epoch, payload, now)
            self._publish_command(payload)
        except (OSError, ValueError) as error:
            self.get_logger().error(
                'could not persist navigation cancel epoch: {}'.format(error))

    def _latch_safe_stop(self, reason):
        self.policy.latch_fault()
        self._publish_authorization(False)
        self._send_cancel_once()
        self.get_logger().warning(reason)

    def _on_status(self, message):
        with self._state_lock:
            try:
                status = parse_bridge_status(message.data)
            except ValueError as error:
                self._latch_safe_stop(
                    'invalid ROS1 navigation status: {}'.format(error))
                return
            self.cancel_retry.acknowledge(status)
            if not self.policy.update(status, self._now()):
                self._latch_safe_stop(
                    'ROS1 navigation status fault/epoch anomaly latched')
                return
            if status.state != 'active':
                self._publish_authorization(False)

    def _on_intent(self, message):
        with self._state_lock:
            try:
                intent = parse_navigation_intent(message.data)
            except ValueError as error:
                self._latch_safe_stop(
                    'navigation intent rejected: {}'.format(error))
                return
            if intent.action == 'cancel_navigation':
                self._latch_safe_stop(
                    'cancel_navigation requested safe stop')
                return
            if self.cancel_retry.active:
                self._publish_authorization(False)
                self.get_logger().warning(
                    'navigation intent rejected while cancel ACK is pending')
                return
            if not self._topology_is_ready(self._now()):
                self._latch_safe_stop(
                    'navigation intent rejected before topology PASS')
                return
            try:
                waypoint = load_map_waypoint(
                    self.waypoint_file,
                    intent.target_id,
                    self.active_v1_map_id,
                )
            except ValueError as error:
                self._latch_safe_stop(
                    'navigation waypoint rejected: {}'.format(error))
                return
            context = self.policy.dispatch_context(
                self._now(), self.status_timeout)
            if context is None:
                self._latch_safe_stop(
                    'navigation waypoint rejected: ROS1 status is not ready')
                return
            try:
                def allocate_dispatch():
                    epoch = self._allocate_epoch()
                    command = build_dispatch_command(
                        epoch, context.nonce, waypoint)
                    self.policy.dispatch(epoch, context.nonce, self._now())
                    return command

                allowed, command = self.cancel_retry.run_if_clear(
                    allocate_dispatch)
                if not allowed:
                    self._publish_authorization(False)
                    return
            except (OSError, RuntimeError, ValueError) as error:
                self._latch_safe_stop(
                    'navigation dispatch could not be persisted: {}'.format(
                        error))
                return
            self._publish_authorization(False)
            self._publish_command(command)

    def _on_timer(self):
        with self._state_lock:
            now = self._now()
            retry_payload = self.cancel_retry.next_payload(now)
            if retry_payload is not None:
                self._publish_command(retry_payload)
            if self.cancel_retry.active:
                self._publish_authorization(False)
            if not self._topology_is_ready(now):
                if self.intent_subscription is not None:
                    self.destroy_subscription(self.intent_subscription)
                    self.intent_subscription = None
                if (
                        self.policy.pending_epoch is not None
                        or not self.policy.fault_latched):
                    self._latch_safe_stop(
                        'navigation topology heartbeat stale or unavailable')
                else:
                    self._publish_authorization(False)
                return
            if self.policy.pending_expired(
                    now, self.status_timeout):
                self._latch_safe_stop(
                    'navigation status stale or no active epoch acknowledgement')
                return
            if self.policy.goal_expired(now, self.goal_timeout):
                self._latch_safe_stop('navigation goal exceeded total deadline')
                return
            pending_before_authorization = self.policy.pending_epoch
            authorized = self.policy.authorization(
                now, self.status_timeout)
            if (
                    pending_before_authorization is not None
                    and self.policy.fault_latched
                    and self.policy.pending_epoch is None):
                self._latch_safe_stop(
                    'navigation authorization timing anomaly latched')
                return
            self._publish_authorization(
                authorized and not self.cancel_retry.active)


def main(args=None):
    rclpy.init(args=args)
    node = NavigationIntentConsumer()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node._latch_safe_stop(
                'navigation intent consumer shutting down')
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
