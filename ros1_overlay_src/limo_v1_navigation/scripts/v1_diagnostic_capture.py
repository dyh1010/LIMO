#!/usr/bin/env python3
"""Read-only ROS1 V1 status capture; creates no publisher, goal, or service."""

import argparse
import json
import math
from pathlib import Path
import sys
import threading
import time
from datetime import datetime, timezone


TOPICS = (
    '/v1/localization/status',
    '/v1/navigation/status',
    '/v1/navigation/error',
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='v1_diagnostics')
    parser.add_argument('--duration-s', type=float, default=60.0)
    return parser.parse_args()


def new_output_path(directory, label, now=None):
    requested_root = Path(directory)
    if not requested_root.is_absolute():
        raise ValueError('output directory must be absolute')
    root = requested_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('output directory must already exist')
    if (not isinstance(label, str) or not label
            or any(character not in (
                'abcdefghijklmnopqrstuvwxyz'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_') for character in label)):
        raise ValueError('label must contain only letters, digits, dash, underscore')
    timestamp = (now or datetime.now(timezone.utc)).strftime(
        '%Y%m%dT%H%M%S_%fZ')
    target = root / '{}_{}.jsonl'.format(label, timestamp)
    if target.parent != root:
        raise ValueError('output path escaped the requested directory')
    if target.exists():
        raise ValueError('timestamped output file already exists')
    return target


class DiagnosticCapture:
    """Collect JSON status samples and raw scan/odom timing as JSON Lines."""

    def __init__(
            self, rospy, String, PoseWithCovarianceStamped,
            LaserScan, Odometry, output):
        self.rospy = rospy
        self.output = output
        self.lock = threading.RLock()
        self.closed = False
        self.subscribers = []
        self.counts = {}
        self.start_monotonic = time.monotonic()
        self.stream = None
        try:
            self.stream = output.open('x', encoding='utf-8')
            self._write({
                'schema': 'limo_v1_diagnostic_capture/v1',
                'event': 'capture_started',
                'monotonic': self.start_monotonic,
                'motion_commanded': False,
            })
            for topic in TOPICS:
                self.subscribers.append(rospy.Subscriber(
                    topic, String,
                    lambda message, name=topic: self._json_callback(
                        name, message),
                    queue_size=100))
            self.subscribers.append(rospy.Subscriber(
                '/amcl_pose', PoseWithCovarianceStamped,
                self._amcl_callback, queue_size=100))
            self.subscribers.append(rospy.Subscriber(
                '/scan', LaserScan, self._scan_callback, queue_size=100))
            self.subscribers.append(rospy.Subscriber(
                '/odom', Odometry, self._odom_callback, queue_size=100))
        except Exception:
            self.close(event='capture_initialization_failed')
            raise

    def _write(self, payload):
        with self.lock:
            if self.closed:
                return
            self.stream.write(json.dumps(
                payload, sort_keys=True, separators=(',', ':')) + '\n')
            self.stream.flush()

    def _count(self, topic):
        with self.lock:
            if self.closed:
                return False
            self.counts[topic] = self.counts.get(topic, 0) + 1
            return True

    def _json_callback(self, topic, message):
        if not self._count(topic):
            return
        try:
            payload = json.loads(message.data)
            error = None
        except (TypeError, ValueError) as exc:
            payload = None
            error = str(exc)
        self._write({
            'event': 'status',
            'topic': topic,
            'receive_monotonic': time.monotonic(),
            'payload': payload,
            'parse_error': error,
        })

    def _amcl_callback(self, message):
        topic = '/amcl_pose'
        if not self._count(topic):
            return
        covariance = message.pose.covariance
        self._write({
            'event': 'amcl_pose',
            'topic': topic,
            'receive_monotonic': time.monotonic(),
            'source_stamp': message.header.stamp.to_sec(),
            'frame_id': message.header.frame_id,
            'x': message.pose.pose.position.x,
            'y': message.pose.pose.position.y,
            'quaternion': {
                'x': message.pose.pose.orientation.x,
                'y': message.pose.pose.orientation.y,
                'z': message.pose.pose.orientation.z,
                'w': message.pose.pose.orientation.w,
            },
            'covariance_x': covariance[0],
            'covariance_y': covariance[7],
            'covariance_yaw': covariance[35],
            'stddev_x_m': math.sqrt(covariance[0])
            if covariance[0] >= 0.0 else None,
            'stddev_y_m': math.sqrt(covariance[7])
            if covariance[7] >= 0.0 else None,
            'stddev_yaw_rad': math.sqrt(covariance[35])
            if covariance[35] >= 0.0 else None,
        })

    def _scan_callback(self, message):
        topic = '/scan'
        if not self._count(topic):
            return
        self._write({
            'event': 'timing',
            'topic': topic,
            'receive_monotonic': time.monotonic(),
            'source_stamp': message.header.stamp.to_sec(),
            'frame_id': message.header.frame_id,
            'sample_count': len(message.ranges),
        })

    def _odom_callback(self, message):
        topic = '/odom'
        if not self._count(topic):
            return
        self._write({
            'event': 'timing',
            'topic': topic,
            'receive_monotonic': time.monotonic(),
            'source_stamp': message.header.stamp.to_sec(),
            'frame_id': message.header.frame_id,
            'child_frame_id': message.child_frame_id,
        })

    def close(self, event='capture_finished'):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            unregister_errors = []
            for subscriber in self.subscribers:
                try:
                    subscriber.unregister()
                except Exception as exc:
                    unregister_errors.append(str(exc))
            if self.stream is not None and not self.stream.closed:
                try:
                    self.stream.write(json.dumps({
                        'event': event,
                        'monotonic': time.monotonic(),
                        'counts': self.counts,
                        'motion_commanded': False,
                        'unregister_errors': unregister_errors,
                    }, sort_keys=True, separators=(',', ':')) + '\n')
                    self.stream.flush()
                finally:
                    self.stream.close()


def wait_wall_duration(duration_s, rospy, poll_s=0.05):
    """Use a monotonic wall deadline so stopped simulated time cannot hang."""
    deadline = time.monotonic() + duration_s
    while not rospy.is_shutdown():
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        time.sleep(min(poll_s, remaining))


def main():
    args = parse_args()
    try:
        if (not math.isfinite(args.duration_s)
                or not 0.0 < args.duration_s <= 3600.0):
            raise ValueError('duration-s must be in (0, 3600]')
        output = new_output_path(args.output_dir, args.label)
        import rospy
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import LaserScan
        from std_msgs.msg import String
        rospy.init_node('v1_diagnostic_capture', anonymous=False)
        capture = None
        try:
            capture = DiagnosticCapture(
                rospy, String, PoseWithCovarianceStamped,
                LaserScan, Odometry, output)
            wait_wall_duration(args.duration_s, rospy)
        finally:
            if capture is not None:
                capture.close()
    except Exception as exc:
        print('V1_DIAGNOSTIC_CAPTURE_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1
    print('V1_DIAGNOSTIC_CAPTURE_PASS: {}'.format(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
