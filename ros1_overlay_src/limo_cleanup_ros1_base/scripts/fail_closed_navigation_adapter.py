#!/usr/bin/env python3
"""Atomically bridge nonce-bound commands into the ROS1 move_base action."""

import queue
import threading
import time

import actionlib
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
import rospy
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
import tf2_ros

from limo_cleanup_ros1_base.navigation_policy import (
    AtomicNavigationProtocol,
    GoalGenerationGate,
    parse_bridge_command,
)
from limo_cleanup_ros1_base.map_binding import (
    load_runtime_preflight_lease,
    validate_map_binding,
    validate_release_files,
    validate_runtime_preflight_lease,
)
from limo_cleanup_ros1_base.navigation_health import (
    EXPECTED_AMCL_TRANSFORM_TOLERANCE,
    EXPECTED_SCAN_ANGLE_MAX,
    EXPECTED_SCAN_ANGLE_MIN,
    EXPECTED_SCAN_MIN_BEAMS,
    MAX_TF_FUTURE_TOLERANCE,
    navigation_health_ready,
    ScanWindow,
    transform_tolerance_contract_ready,
    TransformChainWindow,
)


RESULT_STATES = {
    GoalStatus.SUCCEEDED: 'succeeded',
    GoalStatus.ABORTED: 'aborted',
    GoalStatus.PREEMPTED: 'preempted',
    GoalStatus.RECALLED: 'preempted',
    GoalStatus.REJECTED: 'rejected',
    GoalStatus.LOST: 'aborted',
}


def _pose_message(pose):
    message = PoseStamped()
    message.header.stamp = rospy.Time.now()
    message.header.frame_id = pose.frame_id
    message.pose.position.x = pose.position_x
    message.pose.position.y = pose.position_y
    message.pose.position.z = pose.position_z
    message.pose.orientation.x = pose.orientation_x
    message.pose.orientation.y = pose.orientation_y
    message.pose.orientation.z = pose.orientation_z
    message.pose.orientation.w = pose.orientation_w
    return message


class FailClosedNavigationAdapter:
    """Single-topic atomic ROS1 adapter with result/status heartbeats."""

    def __init__(self):
        self._initialized = False
        self._lock = threading.RLock()
        self.goal_gate = GoalGenerationGate()
        if not bool(rospy.get_param('~enabled', False)):
            raise RuntimeError('navigation adapter is disabled by default')
        operating_mode = rospy.get_param('~operating_mode', 'disabled')
        if operating_mode != 'navigation':
            raise RuntimeError(
                'navigation adapter requires operating_mode=navigation')
        status_rate = float(rospy.get_param('~status_rate', 20.0))
        if status_rate <= 0.0:
            raise ValueError('status_rate must be positive')
        self.scan_timeout = float(rospy.get_param('~scan_timeout', 0.5))
        self.tf_timeout = float(rospy.get_param('~tf_timeout', 0.5))
        self.tf_future_tolerance = float(
            rospy.get_param('~tf_future_tolerance', 0.1))
        self.expected_amcl_tolerance = float(
            rospy.get_param('~expected_amcl_transform_tolerance', 0.05))
        if self.scan_timeout <= 0.0 or self.tf_timeout <= 0.0:
            raise ValueError('scan_timeout and tf_timeout must be positive')
        if not 0.0 <= self.tf_future_tolerance <= MAX_TF_FUTURE_TOLERANCE:
            raise ValueError(
                'tf_future_tolerance must be between 0.0 and 0.1 seconds')
        if abs(
                self.expected_amcl_tolerance
                - EXPECTED_AMCL_TRANSFORM_TOLERANCE) > 1e-9:
            raise ValueError(
                'expected_amcl_transform_tolerance must equal 0.05 seconds')
        if self.expected_amcl_tolerance > self.tf_future_tolerance:
            raise ValueError(
                'AMCL transform tolerance cannot exceed the TF future cap')
        self.scan_frame = rospy.get_param('~scan_frame', 'laser_link')
        self.scan_angle_min = float(rospy.get_param(
            '~scan_angle_min', EXPECTED_SCAN_ANGLE_MIN))
        self.scan_angle_max = float(rospy.get_param(
            '~scan_angle_max', EXPECTED_SCAN_ANGLE_MAX))
        self.scan_minimum_beams = int(rospy.get_param(
            '~scan_minimum_beams', EXPECTED_SCAN_MIN_BEAMS))
        self.global_frame = rospy.get_param('~global_frame', 'map')
        self.odom_frame = rospy.get_param('~odom_frame', 'odom')
        self.base_frame = rospy.get_param('~base_frame', 'base_link')
        binding = validate_map_binding(
            rospy.get_param('~binding_file', ''),
            rospy.get_param('~binding_sha256', ''),
            rospy.get_param('~binding_token', ''),
            rospy.get_param('~map_root', ''),
        )
        self.active_map_id = binding.active_map_id
        self.map_file = binding.map_file
        validate_release_files(rospy.get_param('~v1_release_root', ''))
        runtime_lease = load_runtime_preflight_lease(
            rospy.get_param('~runtime_lease_file', ''))
        validate_runtime_preflight_lease(
            runtime_lease,
            binding,
            rospy.get_param('~runtime_lease_sha256', ''),
            rospy.get_param('~runtime_token', ''),
            time.monotonic(),
        )
        self.amcl_tolerance_param = rospy.get_param(
            '~amcl_transform_tolerance_param',
            '/amcl/transform_tolerance',
        )
        self.protocol = AtomicNavigationProtocol()
        self._goal_queue = queue.Queue(maxsize=1)
        self._worker_stop = threading.Event()
        self.client = actionlib.SimpleActionClient(
            rospy.get_param('~move_base_action', '/move_base'),
            MoveBaseAction,
        )
        self.tf_buffer = tf2_ros.Buffer(
            cache_time=rospy.Duration.from_sec(5.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.status_publisher = rospy.Publisher(
            '/cleanup/navigation/bridge_status',
            String,
            queue_size=1,
            latch=False,
        )
        self.server_ready = False
        self.topology_ready = False
        self.topology_received_at = None
        self.topology_timeout = float(
            rospy.get_param('~topology_timeout', 0.25))
        if not 0.0 < self.topology_timeout <= 0.25:
            raise ValueError('topology_timeout must be in (0, 0.25]')
        self.scan_fresh = False
        self.tf_ready = False
        self.tf_contract_ready = False
        self.navigation_ready = False
        self.last_scan_monotonic = None
        self.last_scan_stamp = None
        self.scan_window = ScanWindow(
            expected_angle_min=self.scan_angle_min,
            expected_angle_max=self.scan_angle_max,
            minimum_beams=self.scan_minimum_beams)
        self.scan_content_ready = False
        self.tf_chain = TransformChainWindow()
        self._goal_worker = threading.Thread(
            target=self._dispatch_worker,
            name='cleanup_ros1_navigation_goal_dispatch',
            daemon=True,
        )
        self._goal_worker.start()
        self.goal_gate.invalidate(self.client.cancel_all_goals)
        self._publish_status()
        self._initialized = True
        # Register inbound callbacks only after every field they may touch is
        # initialized and the adapter is stop-latched.
        self.command_subscription = rospy.Subscriber(
            '/cleanup/navigation/bridge_command',
            String,
            self._on_command,
            queue_size=1,
            tcp_nodelay=True,
        )
        self.scan_subscription = rospy.Subscriber(
            rospy.get_param('~scan_topic', '/scan'),
            LaserScan,
            self._on_scan,
            queue_size=1,
            tcp_nodelay=True,
        )
        self.topology_subscription = rospy.Subscriber(
            rospy.get_param(
                '~topology_ready_topic',
                '/cleanup/navigation/ros1_topology_ready'),
            Bool,
            self._on_topology_ready,
            queue_size=1,
            tcp_nodelay=True,
        )
        self.status_timer = rospy.Timer(
            rospy.Duration.from_sec(1.0 / status_rate),
            self._on_status_timer,
        )
        rospy.on_shutdown(self._on_shutdown)
        rospy.logwarn(
            'ROS1 navigation adapter ready stop-latched; only atomic '
            'nonce-bound commands are accepted')

    def _server_available(self):
        return self.client.wait_for_server(rospy.Duration.from_sec(0.0))

    def _on_topology_ready(self, message):
        if not self._initialized:
            return
        with self._lock:
            self.topology_ready = bool(message.data)
            self.topology_received_at = time.monotonic()
            if not self.topology_ready:
                self.goal_gate.invalidate(self.client.cancel_all_goals)
                self.protocol.set_navigation_ready(False)
                self.navigation_ready = False
                self._publish_status()

    def _topology_available(self, monotonic_now):
        return (
            self.topology_ready
            and self.topology_received_at is not None
            and monotonic_now >= self.topology_received_at
            and monotonic_now - self.topology_received_at
            < self.topology_timeout
        )

    def _on_scan(self, message):
        if not self._initialized:
            return
        with self._lock:
            stamp = message.header.stamp.to_sec()
            receipt = time.monotonic()
            ros_now = rospy.Time.now().to_sec()
            self.scan_content_ready = self.scan_window.add(
                frame_id=message.header.frame_id,
                expected_frame=self.scan_frame,
                ranges=message.ranges,
                range_min=float(message.range_min),
                range_max=float(message.range_max),
                angle_min=float(message.angle_min),
                angle_max=float(message.angle_max),
                angle_increment=float(message.angle_increment),
                source_stamp=stamp,
                receipt_time=receipt,
                ros_now=ros_now,
                timeout=self.scan_timeout,
                future_tolerance=self.tf_future_tolerance,
            )
            if not self.scan_content_ready:
                self.last_scan_monotonic = None
                self.last_scan_stamp = None
                return
            self.last_scan_monotonic = receipt
            self.last_scan_stamp = stamp

    def _scan_available(self, monotonic_now, ros_now):
        if (
                self.last_scan_monotonic is None
                or self.last_scan_stamp is None
                or ros_now <= 0.0):
            return False
        return self.scan_window.ready(
            monotonic_now,
            ros_now,
            self.scan_timeout,
            self.tf_future_tolerance,
        )

    def _amcl_contract_available(self):
        configured = rospy.get_param(self.amcl_tolerance_param, None)
        if isinstance(configured, bool) or not isinstance(
                configured, (int, float)):
            return False
        return transform_tolerance_contract_ready(
            float(configured),
            self.expected_amcl_tolerance,
            self.tf_future_tolerance,
        )

    def _tf_available(self, monotonic_now, ros_now):
        if ros_now <= 0.0:
            return False
        self.tf_contract_ready = self._amcl_contract_available()
        if not self.tf_contract_ready:
            return False
        edges = (
            ('map_to_odom', self.global_frame, self.odom_frame),
            ('odom_to_base', self.odom_frame, self.base_frame),
            ('base_to_laser', self.base_frame, self.scan_frame),
        )
        try:
            transforms = [(segment, self.tf_buffer.lookup_transform(
                parent,
                child,
                rospy.Time(0),
                rospy.Duration.from_sec(0.0),
            )) for segment, parent, child in edges]
        except (
                tf2_ros.LookupException,
                tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            return False
        for segment, transform in transforms:
            translation = transform.transform.translation
            rotation = transform.transform.rotation
            if not self.tf_chain.update(
                    segment,
                    transform.header.stamp.to_sec(),
                    monotonic_now,
                    ros_now,
                    (translation.x, translation.y, translation.z),
                    (rotation.x, rotation.y, rotation.z, rotation.w),
                    self.tf_timeout,
                    self.tf_future_tolerance):
                return False
        return self.tf_chain.ready(
            monotonic_now,
            ros_now,
            self.tf_timeout,
            self.tf_future_tolerance,
        )

    def _publish_status(self):
        message = String()
        message.data = self.protocol.status_payload(
            self.server_ready,
            self.scan_fresh,
            self.tf_ready,
        )
        self.status_publisher.publish(message)

    def _on_status_timer(self, _event):
        if not self._initialized:
            return
        with self._lock:
            monotonic_now = time.monotonic()
            ros_now = rospy.Time.now().to_sec()
            self.server_ready = bool(self._server_available())
            self.scan_fresh = self._scan_available(monotonic_now, ros_now)
            self.tf_ready = self._tf_available(monotonic_now, ros_now)
            ready = navigation_health_ready(
                self.server_ready and self._topology_available(monotonic_now),
                self.scan_fresh,
                self.tf_ready,
            )
            changed = self.protocol.set_navigation_ready(ready)
            if changed and not ready:
                self.goal_gate.invalidate(self.client.cancel_all_goals)
                rospy.logerr(
                    'navigation health gate failed; active navigation cancelled '
                     '(move_base=%s scan_fresh=%s tf_ready=%s tf_contract=%s)',
                    self.server_ready,
                    self.scan_fresh,
                    self.tf_ready,
                    self.tf_contract_ready,
                )
            self.navigation_ready = ready
            self._publish_status()

    def _reject_and_stop(self, error, epoch=0):
        with self._lock:
            self.protocol.reject(epoch)
            self.goal_gate.invalidate(self.client.cancel_all_goals)
            self._publish_status()
            rospy.logerr('navigation bridge command rejected: %s', error)

    def _dispatch_worker(self):
        while not self._worker_stop.is_set():
            try:
                item = self._goal_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return
            goal, epoch, frame_id, generation = item
            try:
                committed = self.goal_gate.commit(
                    generation,
                    lambda: self.client.send_goal(
                        goal,
                        done_cb=lambda status, result: self._on_done(
                            epoch, generation, status, result),
                    ),
                )
            except Exception as error:
                self._reject_and_stop(error, epoch)
                continue
            with self._lock:
                if not committed:
                    rospy.logwarn(
                        'queued navigation epoch %d invalidated before send',
                        epoch)
                    continue
                self._publish_status()
                rospy.loginfo(
                    'atomic navigation epoch %d sent in frame %s',
                    epoch, frame_id)

    def _on_command(self, message):
        if not self._initialized:
            return
        try:
            command = parse_bridge_command(message.data)
        except ValueError as error:
            self._reject_and_stop(error)
            return
        with self._lock:
            try:
                decision = self.protocol.accept(
                    command,
                    self.navigation_ready,
                    self.active_map_id,
                )
            except RuntimeError as error:
                self.goal_gate.invalidate(self.client.cancel_all_goals)
                self._publish_status()
                rospy.logerr('navigation bridge command blocked: %s', error)
                return
            if decision == 'cancelled':
                self.goal_gate.invalidate(self.client.cancel_all_goals)
                self._publish_status()
                rospy.logwarn(
                    'atomic navigation cancel accepted; all goals cancelled')
                return
            if decision == 'duplicate':
                self._publish_status()
                rospy.logwarn(
                    'duplicate active navigation command ignored idempotently')
                return
            goal = MoveBaseGoal()
            goal.target_pose = _pose_message(command.pose)
            generation = self.goal_gate.reserve()
            try:
                self._goal_queue.put_nowait((
                    goal, command.epoch, command.pose.frame_id, generation))
            except queue.Full as error:
                self._reject_and_stop(error, command.epoch)
                return
            self._publish_status()
            rospy.loginfo(
                'atomic navigation epoch %d queued for generation %d',
                command.epoch, generation,
            )

    def _on_done(self, epoch, generation, status, _result):
        if not self._initialized:
            return
        with self._lock:
            if not self.goal_gate.is_current(generation):
                return
            state = RESULT_STATES.get(status, 'aborted')
            if self.protocol.complete(epoch, state):
                self.goal_gate.invalidate()
                self._publish_status()
                rospy.logwarn(
                    'navigation epoch %d completed with state %s',
                    epoch,
                    state,
                )

    def _on_shutdown(self):
        with self._lock:
            self.goal_gate.invalidate(self.client.cancel_all_goals)
            self.protocol.cancel(self.protocol.highest_epoch)
            self.server_ready = False
            self.topology_ready = False
            self.topology_received_at = None
            self.scan_fresh = False
            self.tf_ready = False
            self.tf_contract_ready = False
            self.tf_chain.invalidate()
            self.navigation_ready = False
            self._publish_status()
        self._worker_stop.set()
        try:
            self._goal_queue.put_nowait(None)
        except queue.Full:
            pass
        self._goal_worker.join(timeout=1.0)


def main():
    rospy.init_node('cleanup_ros1_navigation_adapter')
    FailClosedNavigationAdapter()
    rospy.spin()


if __name__ == '__main__':
    main()
