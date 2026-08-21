#!/usr/bin/env python3
"""Safe ROS1 AMCL convergence manager; it never publishes velocity."""

import json
import math
from pathlib import Path
import threading
import sys
import time


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.config_policy import (  # noqa: E402
    load_profile,
    validate_amcl_transform_tolerance,
    validate_map_file,
)
from limo_v1_navigation.localization_policy import (  # noqa: E402
    BLOCKED,
    ChainEvidence,
    ConvergenceConfig,
    InitialPoseEvidence,
    LocalizationConvergence,
    PoseEstimate,
    planar_yaw,
)


def _configuration(rospy):
    names = (
        'chain_timeout_s', 'initial_pose_timeout_s',
        'convergence_timeout_s', 'message_timeout_s',
        'future_tolerance_s', 'stable_window_s', 'stable_min_samples',
        'max_covariance_x', 'max_covariance_y', 'max_covariance_yaw',
        'max_stable_position_span_m', 'max_stable_yaw_span_rad',
        'max_ready_position_jump_m', 'max_ready_yaw_jump_rad',
        'nomotion_update_period_s', 'min_nomotion_updates',
        'max_consecutive_nomotion_failures', 'max_initial_covariance_xy',
        'max_initial_covariance_yaw')
    return ConvergenceConfig(**{
        name: rospy.get_param('~' + name) for name in names})


class V1LocalizationManager:
    """ROS wrapper around the dependency-free convergence state machine."""

    def __init__(
            self, rospy, rosgraph, tf2_ros, PoseWithCovarianceStamped,
            LaserScan, Odometry, MapMetaData, Bool, String, Empty, Trigger,
            TriggerResponse, GoalStatusArray):
        self.rospy = rospy
        self.rosgraph = rosgraph
        self.Bool = Bool
        self.String = String
        self.TriggerResponse = TriggerResponse
        self.profile = load_profile(rospy.get_param('~profile_file'))
        validate_amcl_transform_tolerance(
            self.profile, PACKAGE_ROOT / 'config' / 'amcl.yaml')
        self.map_file = rospy.get_param('~map_file')
        self.active_map_id = rospy.get_param('~active_map_id')
        validate_map_file(
            self.profile, self.map_file, self.active_map_id)
        self.config = _configuration(rospy)
        self.initial_pose_authorization_timeout_s = float(rospy.get_param(
            '~initial_pose_authorization_timeout_s'))
        self.nomotion_service_timeout_s = float(rospy.get_param(
            '~nomotion_service_timeout_s'))
        if (
                not math.isfinite(self.initial_pose_authorization_timeout_s)
                or not 0.0 < self.initial_pose_authorization_timeout_s <= 300.0
                or not math.isfinite(self.nomotion_service_timeout_s)
                or not 0.0 < self.nomotion_service_timeout_s <= 10.0):
            raise ValueError('manager authorization/service timeouts are invalid')
        self.manager = LocalizationConvergence(
            time.monotonic(), self.config)
        self.scan_receive = None
        self.scan_stamp = None
        self.scan_frame_ok = False
        self.odom_receive = None
        self.odom_stamp = None
        self.odom_frames_ok = False
        self.map_receive = None
        self.map_contract_ok = False
        self.last_topology_check = None
        self.cached_topology_reason = 'topology_not_checked'
        self.initial_pose_authorized_until = None
        self.navigation_active = False
        self.state_lock = threading.RLock()
        self.nomotion_lock = threading.Lock()
        self.nomotion_call_active = False
        self.nomotion_call_started = None
        self.nomotion_result = None
        self.nomotion_generation = 0
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.nomotion_service = rospy.ServiceProxy(
            '/request_nomotion_update', Empty, persistent=False)
        self.ready_publisher = rospy.Publisher(
            '/v1/localization/ready', Bool, queue_size=1, latch=True)
        self.status_publisher = rospy.Publisher(
            '/v1/localization/status', String, queue_size=1, latch=True)
        self.diagnostic_publisher = rospy.Publisher(
            '/v1/localization/diagnostics', String, queue_size=1, latch=True)
        self.validated_initial_pose_publisher = rospy.Publisher(
            '/v1/validated_initialpose', PoseWithCovarianceStamped,
            queue_size=1, latch=False)
        rospy.Subscriber(
            '/initialpose', PoseWithCovarianceStamped,
            self._initial_pose_callback, queue_size=1)
        rospy.Subscriber(
            '/amcl_pose', PoseWithCovarianceStamped,
            self._amcl_pose_callback, queue_size=10)
        rospy.Subscriber(
            self.profile['topics']['scan'], LaserScan,
            self._scan_callback, queue_size=10)
        rospy.Subscriber(
            self.profile['topics']['odom'], Odometry,
            self._odom_callback, queue_size=10)
        rospy.Subscriber(
            '/map_metadata', MapMetaData,
            self._map_callback, queue_size=1)
        rospy.Subscriber(
            '/v1/private_move_base/status', GoalStatusArray,
            self._move_base_status_callback, queue_size=5)
        rospy.Service('~authorize_initial_pose', Trigger,
                      self._authorize_initial_pose)
        rospy.Service('~reset', Trigger, self._reset)
        rospy.Timer(rospy.Duration(0.10), self._timer)
        self._publish_status(time.monotonic(), 'startup')

    def _scan_callback(self, message):
        with self.state_lock:
            self.scan_receive = time.monotonic()
            self.scan_stamp = message.header.stamp.to_sec()
            self.scan_frame_ok = (
                message.header.frame_id == self.profile['frames']['laser'])

    def _odom_callback(self, message):
        with self.state_lock:
            self.odom_receive = time.monotonic()
            self.odom_stamp = message.header.stamp.to_sec()
            self.odom_frames_ok = (
                message.header.frame_id == self.profile['frames']['odom']
                and message.child_frame_id == self.profile['frames']['base'])

    def _map_callback(self, message):
        with self.state_lock:
            self.map_receive = time.monotonic()
            self.map_contract_ok = (
                message.width > 0 and message.height > 0
                and math.isfinite(message.resolution)
                and message.resolution > 0.0)

    def _move_base_status_callback(self, message):
        with self.state_lock:
            now = time.monotonic()
            active = any(item.status in (0, 1, 6, 7)
                         for item in message.status_list)
            if active != self.navigation_active:
                self.navigation_active = active
                self.manager.set_navigation_active(active, now)
                if active:
                    self._invalidate_nomotion_call()

    def _pose_evidence(self, message, now, initial=False):
        covariance = message.pose.covariance
        arguments = dict(
            received_monotonic=now,
            source_stamp=message.header.stamp.to_sec(),
            ros_now=self.rospy.Time.now().to_sec(),
            frame_id=message.header.frame_id.lstrip('/'),
            x=message.pose.pose.position.x,
            y=message.pose.pose.position.y,
            yaw=planar_yaw(
                message.pose.pose.orientation.x,
                message.pose.pose.orientation.y,
                message.pose.pose.orientation.z,
                message.pose.pose.orientation.w),
            covariance_x=covariance[0],
            covariance_y=covariance[7],
            covariance_yaw=covariance[35],
        )
        if initial:
            arguments['source'] = 'topic'
            return InitialPoseEvidence(**arguments)
        return PoseEstimate(**arguments)

    def _initial_pose_callback(self, message):
        with self.state_lock:
            now = time.monotonic()
            try:
                if (
                        self.initial_pose_authorized_until is None
                        or now >= self.initial_pose_authorized_until):
                    raise ValueError(
                        'initial pose authorization window is not open')
                if self.navigation_active:
                    raise ValueError(
                        'initial pose is forbidden while navigation is active')
                self.manager.accept_initial_pose(
                    self._pose_evidence(message, now, initial=True), now)
                self._invalidate_nomotion_call()
                self.validated_initial_pose_publisher.publish(message)
                self.initial_pose_authorized_until = None
                self.rospy.loginfo(
                    'V1 localization accepted explicit /initialpose; '
                    'starting no-motion convergence')
            except (ValueError, RuntimeError) as exc:
                self.rospy.logerr(
                    'V1 localization rejected /initialpose: %s', exc)
            self._publish_status(now, 'initialpose')

    def _authorize_initial_pose(self, _request):
        with self.state_lock:
            if self.navigation_active:
                return self.TriggerResponse(
                    success=False,
                    message=(
                        'navigation is active; cancel it before authorizing pose'))
            now = time.monotonic()
            self.initial_pose_authorized_until = (
                now + self.initial_pose_authorization_timeout_s)
            return self.TriggerResponse(
                success=True,
                message='one validated /initialpose accepted for {:.1f}s'.format(
                    self.initial_pose_authorization_timeout_s))

    def _amcl_pose_callback(self, message):
        with self.state_lock:
            now = time.monotonic()
            try:
                self.manager.observe_estimate(
                    self._pose_evidence(message, now), now,
                    navigation_active=self.navigation_active)
            except ValueError as exc:
                if self.manager.state != BLOCKED:
                    self.manager.block('invalid_amcl_pose:{}'.format(exc))
            self._publish_status(now, 'amcl_pose')

    @staticmethod
    def _age_reason(now, received, stamp, ros_now, timeout, future, label):
        if received is None or stamp is None:
            return '{}_missing'.format(label)
        values = (now, received, stamp, ros_now)
        if not all(math.isfinite(value) for value in values):
            return '{}_time_invalid'.format(label)
        receive_age = now - received
        source_age = ros_now - stamp
        if not 0.0 <= receive_age < timeout:
            return '{}_receive_stale'.format(label)
        if not -future <= source_age < timeout:
            return '{}_source_stale'.format(label)
        return None

    def _topology_reason(self, now):
        if (
                self.last_topology_check is not None
                and now - self.last_topology_check < 0.5):
            return self.cached_topology_reason
        self.last_topology_check = now
        try:
            publishers, subscribers, _ = self.rosgraph.Master(
                self.rospy.get_name()).getSystemState()
            publishers = dict(publishers)
            subscribers = dict(subscribers)
        except Exception as exc:
            self.cached_topology_reason = (
                'ros_graph_unavailable:{}'.format(exc))
            return self.cached_topology_reason
        if set(publishers.get('/scan', ())) != {
                self.profile['owners']['scan']}:
            self.cached_topology_reason = 'scan_owner_mismatch'
            return self.cached_topology_reason
        if set(publishers.get('/odom', ())) != {
                self.profile['owners']['odom_tf']}:
            self.cached_topology_reason = 'odom_owner_mismatch'
            return self.cached_topology_reason
        if set(publishers.get('/map', ())) != {'/map_server'}:
            self.cached_topology_reason = 'map_owner_mismatch'
            return self.cached_topology_reason
        if set(publishers.get('/amcl_pose', ())) != {'/amcl'}:
            self.cached_topology_reason = 'amcl_pose_owner_mismatch'
            return self.cached_topology_reason
        if set(subscribers.get('/initialpose', ())) != {self.rospy.get_name()}:
            self.cached_topology_reason = 'initialpose_consumers_mismatch'
            return self.cached_topology_reason
        if set(publishers.get('/v1/validated_initialpose', ())) != {
                self.rospy.get_name()}:
            self.cached_topology_reason = 'validated_initialpose_owner_mismatch'
            return self.cached_topology_reason
        if set(subscribers.get('/v1/validated_initialpose', ())) != {'/amcl'}:
            self.cached_topology_reason = 'amcl_validated_initialpose_consumer_mismatch'
            return self.cached_topology_reason
        active_nodes = set()
        for mapping in (publishers, subscribers):
            for owners in mapping.values():
                active_nodes.update(owners)
        for canonical in ('/map_server', '/amcl'):
            aliases = {
                node for node in active_nodes
                if node == canonical or node.startswith(canonical + '_')}
            if aliases != {canonical}:
                self.cached_topology_reason = (
                    '{}_canonical_instance_mismatch'.format(
                        canonical.lstrip('/')))
                return self.cached_topology_reason
        forbidden_localization_nodes = (
            '/slam_gmapping', '/cartographer_node', '/robot_pose_ekf')
        for forbidden in forbidden_localization_nodes:
            aliases = {
                node for node in active_nodes
                if node == forbidden or node.startswith(forbidden + '_')}
            if aliases:
                self.cached_topology_reason = (
                    'forbidden_localization_owner_present:{}'.format(
                        forbidden))
                return self.cached_topology_reason
        tf_publishers = set(publishers.get('/tf', ())) | set(
            publishers.get('/tf_static', ()))
        if self.profile['owners']['odom_tf'] not in tf_publishers:
            self.cached_topology_reason = 'odom_tf_owner_missing'
            return self.cached_topology_reason
        if any(owner in tf_publishers
               for owner in self.profile['owners']['forbidden_odom_tf']):
            self.cached_topology_reason = 'forbidden_odom_tf_owner_present'
            return self.cached_topology_reason
        self.cached_topology_reason = None
        return None

    def _chain_evidence(self, now):
        ros_now = self.rospy.Time.now().to_sec()
        timeout = self.config.message_timeout_s
        future = self.config.future_tolerance_s
        for reason in (
                self._age_reason(
                    now, self.scan_receive, self.scan_stamp, ros_now,
                    timeout, future, 'scan'),
                self._age_reason(
                    now, self.odom_receive, self.odom_stamp, ros_now,
                    timeout, future, 'odom')):
            if reason:
                return ChainEvidence(False, reason, now)
        if not self.scan_frame_ok:
            return ChainEvidence(False, 'scan_frame_invalid', now)
        if not self.odom_frames_ok:
            return ChainEvidence(False, 'odom_frames_invalid', now)
        if (
                self.map_receive is None or not self.map_contract_ok):
            return ChainEvidence(False, 'map_metadata_missing_or_invalid', now)
        topology_reason = self._topology_reason(now)
        if topology_reason:
            return ChainEvidence(False, topology_reason, now)
        try:
            self.tf_buffer.lookup_transform(
                'odom', 'base_link', self.rospy.Time(0),
                self.rospy.Duration(0.02))
            self.tf_buffer.lookup_transform(
                'base_link', 'laser_link', self.rospy.Time(0),
                self.rospy.Duration(0.02))
            map_to_base = None
            if self.manager.initial_pose is not None:
                map_to_base = self.tf_buffer.lookup_transform(
                    'map', 'base_link', self.rospy.Time(0),
                    self.rospy.Duration(0.02))
        except Exception as exc:
            return ChainEvidence(False, 'tf_missing:{}'.format(exc), now)
        if map_to_base is None:
            return ChainEvidence(True, 'pre_initialpose_chain_ok', now)
        stamp = map_to_base.header.stamp.to_sec()
        if not math.isfinite(stamp):
            return ChainEvidence(False, 'map_tf_stamp_invalid', now)
        age = ros_now - stamp
        if not -future <= age < timeout:
            return ChainEvidence(False, 'map_tf_stale', now)
        return ChainEvidence(True, 'ok', now)

    def _request_nomotion_update(self, now):
        self.manager.mark_nomotion_requested(now)
        with self.nomotion_lock:
            self.nomotion_generation += 1
            generation = self.nomotion_generation
            self.nomotion_call_active = True
            self.nomotion_call_started = now
            self.nomotion_result = None

        def invoke():
            try:
                self.nomotion_service()
                result = (True, '')
            except Exception as exc:
                result = (False, str(exc))
            self._store_nomotion_result(generation, *result)

        thread = threading.Thread(target=invoke, daemon=True)
        thread.start()

    def _store_nomotion_result(self, generation, success, error):
        """Accept only the response belonging to the current in-flight call."""
        with self.nomotion_lock:
            if (
                    not self.nomotion_call_active
                    or generation != self.nomotion_generation):
                return False
            self.nomotion_result = (generation, bool(success), str(error))
            return True

    def _invalidate_nomotion_call(self):
        """Make any in-flight service response stale for the next pose epoch."""
        with self.nomotion_lock:
            self.nomotion_generation += 1
            self.nomotion_call_active = False
            self.nomotion_call_started = None
            self.nomotion_result = None

    def _poll_nomotion_result(self, now):
        completed = None
        with self.nomotion_lock:
            if not self.nomotion_call_active:
                return
            if self.nomotion_result is not None:
                generation, success, error = self.nomotion_result
                if generation != self.nomotion_generation:
                    self.nomotion_result = None
                    return
                self.nomotion_call_active = False
                self.nomotion_call_started = None
                self.nomotion_result = None
                completed = (success, error)
            elif now - self.nomotion_call_started >= self.nomotion_service_timeout_s:
                self.nomotion_call_active = False
                self.nomotion_call_started = None
                self.nomotion_generation += 1
                self.nomotion_result = None
                completed = (False, 'service_call_timeout')
        if completed is not None:
            self.manager.record_nomotion_result(*completed)

    def _timer(self, _event):
        with self.state_lock:
            now = time.monotonic()
            evidence = self._chain_evidence(now)
            was_chain_ok = self.manager.chain.ok
            self.manager.update_chain(evidence, now)
            if was_chain_ok and not evidence.ok:
                self._invalidate_nomotion_call()
            self._poll_nomotion_result(now)
            if (
                    not self.nomotion_call_active
                    and self.manager.nomotion_due(
                        now, navigation_active=self.navigation_active)):
                self._request_nomotion_update(now)
            self.manager.tick(now)
            self._publish_status(now, 'timer')

    def _reset(self, _request):
        with self.state_lock:
            now = time.monotonic()
            self.manager.reset(now)
            self._invalidate_nomotion_call()
            self.initial_pose_authorized_until = None
            self._publish_status(now, 'reset')
            return self.TriggerResponse(
                success=True,
                message='reset; a new explicit /initialpose is required')

    def _publish_status(self, now, event):
        report = self.manager.status(now)
        report.update({
            'schema': 'limo_v1_localization_status/v1',
            'event': event,
            'active_map_id': self.active_map_id,
            'map_file': self.map_file,
            'motion_commanded': False,
            'initial_pose_authorized': bool(
                self.initial_pose_authorized_until is not None
                and now < self.initial_pose_authorized_until),
            'nomotion_call_active': self.nomotion_call_active,
        })
        payload = json.dumps(report, sort_keys=True, separators=(',', ':'))
        ready = self.Bool()
        ready.data = bool(report['ready'])
        self.ready_publisher.publish(ready)
        status = self.String()
        status.data = payload
        self.status_publisher.publish(status)
        diagnostics = self.String()
        diagnostics.data = payload
        self.diagnostic_publisher.publish(diagnostics)


def main():
    try:
        import rosgraph
        import rospy
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from actionlib_msgs.msg import GoalStatusArray
        from nav_msgs.msg import MapMetaData, Odometry
        from sensor_msgs.msg import LaserScan
        from std_msgs.msg import Bool, String
        from std_srvs.srv import Empty, Trigger, TriggerResponse
        import tf2_ros
        rospy.init_node('v1_localization_manager', anonymous=False)
        V1LocalizationManager(
            rospy, rosgraph, tf2_ros, PoseWithCovarianceStamped,
            LaserScan, Odometry, MapMetaData, Bool, String, Empty, Trigger,
            TriggerResponse, GoalStatusArray)
        rospy.spin()
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print('V1_LOCALIZATION_MANAGER_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
