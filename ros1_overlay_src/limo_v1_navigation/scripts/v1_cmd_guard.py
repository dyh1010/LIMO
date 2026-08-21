#!/usr/bin/env python3
"""Sole fail-closed publisher from move_base request to the V1 driver topic."""

from collections import deque
import math
from pathlib import Path
import sys
import time


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.config_policy import load_profile  # noqa: E402
from limo_v1_navigation.freshness_policy import (  # noqa: E402
    CommandValues,
    FaultLatch,
    FreshnessLimits,
    FreshnessSnapshot,
    ZERO_COMMAND,
    evaluate_safety,
    slew_limit,
)
from limo_v1_navigation.topology_policy import validate_topology  # noqa: E402


class V1CommandGuard:
    """ROS wrapper around the dependency-free freshness policy."""

    def __init__(self, rospy, rosgraph, tf2_ros, Twist, LaserScan, Odometry,
                 Bool, Trigger, TriggerResponse):
        self.rospy = rospy
        self.rosgraph = rosgraph
        self.tf2_ros = tf2_ros
        self.Twist = Twist
        self.Bool = Bool
        self.TriggerResponse = TriggerResponse
        self.profile = load_profile(rospy.get_param('~profile_file'))
        self.allow_nonzero = bool(rospy.get_param('~allow_nonzero', False))
        self.driver_timeout_verified = bool(
            rospy.get_param('~driver_timeout_verified', False))
        if self.allow_nonzero and not self.driver_timeout_verified:
            raise RuntimeError('nonzero blocked: driver timeout is unverified')
        freshness = self.profile['freshness']
        motion = self.profile['motion']
        self.limits = FreshnessLimits(
            scan_timeout_s=freshness['scan_timeout_s'],
            odom_timeout_s=freshness['odom_timeout_s'],
            tf_timeout_s=freshness['tf_timeout_s'],
            command_timeout_s=freshness['command_timeout_s'],
            source_future_tolerance_s=(
                self.profile['tf_timing']['source_future_tolerance_s']),
            min_scan_hz=self.profile['scan']['min_hz'],
            max_scan_hz=self.profile['scan']['max_hz'],
            max_linear_x_mps=motion['max_linear_x_mps'],
            max_angular_z_rps=motion['max_angular_z_rps'],
        )
        self.latch = FaultLatch()
        self.last_scan = None
        self.scan_source_stamp = None
        self.last_odom = None
        self.last_tf = None
        self.tf_source_stamp = None
        self.last_command = None
        self.localization_ready = False
        self.last_localization_ready = None
        self.scan_frame_ok = False
        self.odom_frames_ok = False
        self.tf_owner_ok = False
        self.forbidden_tf_owner_present = False
        self.scan_times = deque(maxlen=12)
        self.command = ZERO_COMMAND
        self.output = ZERO_COMMAND
        self.last_output_time = time.monotonic()
        self.last_topology_check = 0.0
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.publisher = rospy.Publisher(
            self.profile['topics']['driver_cmd'], Twist, queue_size=1)
        self.stop_latched_publisher = rospy.Publisher(
            '/v1/cmd_guard/stop_latched', Bool, queue_size=1, latch=True)
        rospy.Subscriber(
            self.profile['topics']['nav_cmd'], Twist,
            self._command_callback, queue_size=1)
        rospy.Subscriber(
            self.profile['topics']['scan'], LaserScan,
            self._scan_callback, queue_size=10)
        rospy.Subscriber(
            self.profile['topics']['odom'], Odometry,
            self._odom_callback, queue_size=10)
        rospy.Subscriber(
            '/v1/localization/ready', Bool,
            self._localization_ready_callback, queue_size=10)
        rospy.Service('~rearm', Trigger, self._rearm)
        rospy.Timer(rospy.Duration(0.05), self._timer)
        rospy.Timer(rospy.Duration(0.10), self._stop_heartbeat_timer)
        rospy.on_shutdown(self._shutdown)
        self._publish_stop_latched()

    def _command_callback(self, message):
        self.command = CommandValues(
            linear_x=message.linear.x,
            linear_y=message.linear.y,
            linear_z=message.linear.z,
            angular_x=message.angular.x,
            angular_y=message.angular.y,
            angular_z=message.angular.z,
        )
        self.last_command = time.monotonic()

    def _scan_callback(self, message):
        now = time.monotonic()
        self.last_scan = now
        self.scan_source_stamp = message.header.stamp.to_sec()
        self.scan_times.append(now)
        self.scan_frame_ok = (
            message.header.frame_id == self.profile['frames']['laser'])

    def _odom_callback(self, message):
        self.last_odom = time.monotonic()
        self.odom_frames_ok = (
            message.header.frame_id == self.profile['frames']['odom']
            and message.child_frame_id == self.profile['frames']['base'])

    def _localization_ready_callback(self, message):
        now = time.monotonic()
        previous = self.localization_ready
        self.localization_ready = bool(message.data)
        self.last_localization_ready = now
        if previous and not self.localization_ready:
            self.latch.trip('localization_ready_lost')
            self._publish_stop_latched()

    def _scan_hz(self):
        if len(self.scan_times) < 3:
            return None
        duration = self.scan_times[-1] - self.scan_times[0]
        return ((len(self.scan_times) - 1) / duration
                if duration > 0.0 else None)

    def _update_tf(self, now):
        try:
            self.tf_buffer.lookup_transform(
                self.profile['frames']['odom'],
                self.profile['frames']['base'],
                self.rospy.Time(0), self.rospy.Duration(0.02))
            self.tf_buffer.lookup_transform(
                self.profile['frames']['base'],
                self.profile['frames']['laser'],
                self.rospy.Time(0), self.rospy.Duration(0.02))
            map_to_base = self.tf_buffer.lookup_transform(
                self.profile['frames']['map'],
                self.profile['frames']['base'],
                self.rospy.Time(0), self.rospy.Duration(0.02))
            self.last_tf = now
            self.tf_source_stamp = map_to_base.header.stamp.to_sec()
        except Exception:
            pass

    def _update_topology(self, now):
        if now - self.last_topology_check < 0.5:
            return
        self.last_topology_check = now
        try:
            publishers, subscribers, _ = self.rosgraph.Master(
                self.rospy.get_name()).getSystemState()
            publisher_map = dict(publishers)
            subscriber_map = dict(subscribers)
            tf_publishers = set(publisher_map.get('/tf', ())) | set(
                publisher_map.get('/tf_static', ()))
            self.forbidden_tf_owner_present = any(
                owner in tf_publishers
                for owner in self.profile['owners']['forbidden_odom_tf'])
            validate_topology(
                publisher_map, subscriber_map, tf_publishers,
                navigation=True)
            self.tf_owner_ok = True
        except Exception:
            self.tf_owner_ok = False

    def _snapshot(self, now):
        return FreshnessSnapshot(
            now=now,
            ros_now=self.rospy.Time.now().to_sec(),
            last_scan=self.last_scan,
            scan_source_stamp=self.scan_source_stamp,
            last_odom=self.last_odom,
            last_tf=self.last_tf,
            tf_source_stamp=self.tf_source_stamp,
            last_command=self.last_command,
            scan_hz=self._scan_hz(),
            scan_frame_ok=self.scan_frame_ok,
            odom_frames_ok=self.odom_frames_ok,
            tf_owner_ok=self.tf_owner_ok,
            forbidden_tf_owner_present=self.forbidden_tf_owner_present,
        )

    def _health_ready(self, now):
        if (
                not self.localization_ready
                or self.last_localization_ready is None
                or now - self.last_localization_ready
                >= self.limits.tf_timeout_s):
            return False
        decision = evaluate_safety(
            self._snapshot(now), ZERO_COMMAND, self.limits,
            allow_nonzero=True,
            driver_timeout_verified=self.driver_timeout_verified,
            fault_latched=False,
        )
        return decision.allowed

    def _rearm(self, _request):
        now = time.monotonic()
        zero_command = all(
            abs(value) <= 0.0 for value in self.command.components())
        accepted = self.latch.rearm(
            self._health_ready(now), zero_command, explicit_request=True)
        self._publish_stop_latched()
        return self.TriggerResponse(
            success=accepted,
            message='rearmed' if accepted else 'health/zero/timeout proof missing')

    def _publish(self, command):
        message = self.Twist()
        message.linear.x = command.linear_x
        message.angular.z = command.angular_z
        self.publisher.publish(message)

    def _publish_stop_latched(self):
        message = self.Bool()
        message.data = bool(self.latch.latched)
        self.stop_latched_publisher.publish(message)

    def _stop_heartbeat_timer(self, _event):
        self._publish_stop_latched()

    def _timer(self, _event):
        now = time.monotonic()
        self._update_tf(now)
        self._update_topology(now)
        if (
                self.localization_ready
                and (self.last_localization_ready is None
                     or now - self.last_localization_ready
                     >= self.limits.tf_timeout_s)):
            self.localization_ready = False
            self.latch.trip('localization_ready_stale')
            self._publish_stop_latched()
        decision = evaluate_safety(
            self._snapshot(now), self.command, self.limits,
            allow_nonzero=self.allow_nonzero,
            driver_timeout_verified=self.driver_timeout_verified,
            fault_latched=self.latch.latched,
        )
        if decision.allowed:
            elapsed = max(0.0, now - self.last_output_time)
            motion = self.profile['motion']
            self.output = slew_limit(
                self.output, decision.output, elapsed,
                motion['max_linear_accel_mps2'],
                motion['max_angular_accel_rps2'])
        else:
            self.output = ZERO_COMMAND
            if (self.allow_nonzero
                    and decision.reason not in ('fault_latched',)):
                self.latch.trip(decision.reason)
                self._publish_stop_latched()
        self.last_output_time = now
        self._publish(self.output)

    def _shutdown(self):
        for _ in range(5):
            self._publish(ZERO_COMMAND)


def main():
    try:
        import rosgraph
        import rospy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import LaserScan
        from std_msgs.msg import Bool
        from std_srvs.srv import Trigger, TriggerResponse
        import tf2_ros
        rospy.init_node('v1_cmd_guard', anonymous=False)
        V1CommandGuard(
            rospy, rosgraph, tf2_ros, Twist, LaserScan, Odometry, Bool,
            Trigger, TriggerResponse)
        rospy.spin()
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print('V1_CMD_GUARD_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
