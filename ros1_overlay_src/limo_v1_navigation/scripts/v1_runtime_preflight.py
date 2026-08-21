#!/usr/bin/env python3
"""Read-only ROS1 topic, owner, scan-rate, and TF preflight."""

from collections import deque
import json
import math
from pathlib import Path
import sys
import threading
import time


def _resolve_package_root(script_file):
    script_path = Path(script_file).resolve()
    candidates = [script_path.parents[1]]
    if len(script_path.parents) > 2:
        candidates.append(
            script_path.parents[2] / 'share' / 'limo_v1_navigation')
    for candidate in candidates:
        if (
                (candidate / 'package.xml').is_file()
                and (candidate / 'config').is_dir()
                and (candidate / 'docs').is_dir()):
            return candidate
    raise RuntimeError(
        'limo_v1_navigation package share cannot be resolved safely')


PACKAGE_ROOT = _resolve_package_root(__file__)
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.config_policy import (  # noqa: E402
    load_profile,
    validate_amcl_transform_tolerance,
    validate_runtime_request,
)
from limo_v1_navigation.topology_policy import (  # noqa: E402
    TfEdgeObservation,
    TfEdgeValidationError,
    load_verified_vendor_tf_rules,
    validate_tf_edge_evidence,
    validate_topology,
)


VENDOR_BLOCKER_FILE = PACKAGE_ROOT / 'docs' / (
    'V1_ROS1_VENDOR_INCLUDE_BLOCKER.json')


def _system_state(master):
    publishers, subscribers, _ = master.getSystemState()
    return dict(publishers), dict(subscribers)


def _load_vendor_tf_rules(
        rules_file, source_manifest_file, publisher_pin_file):
    """Verify independent artifacts and their actual referenced bytes."""
    return load_verified_vendor_tf_rules(
        rules_file, source_manifest_file, publisher_pin_file,
        VENDOR_BLOCKER_FILE)


def _tf_observation(message, transform, topic, message_id, receipt_monotonic):
    """Preserve one TransformStamped with its TFMessage connection metadata."""
    header = getattr(message, '_connection_header', None) or {}
    translation = transform.transform.translation
    rotation = transform.transform.rotation
    return TfEdgeObservation(
        message_id=message_id,
        parent_frame=transform.header.frame_id,
        child_frame=transform.child_frame_id,
        authority=header.get('callerid', ''),
        topic=topic,
        source_stamp=transform.header.stamp.to_sec(),
        receipt_monotonic=receipt_monotonic,
        translation=(
            float(translation.x), float(translation.y), float(translation.z)),
        rotation=(
            float(rotation.x), float(rotation.y),
            float(rotation.z), float(rotation.w)),
        latching=str(header.get('latching', '0')).strip().lower() in (
            '1', 'true'),
    )


def _tf_observation_dict(observation):
    return {
        'message_id': observation.message_id,
        'parent_frame': observation.parent_frame,
        'child_frame': observation.child_frame,
        'callerid': observation.authority,
        'topic': observation.topic,
        'source_stamp': observation.source_stamp,
        'receipt_monotonic': observation.receipt_monotonic,
        'translation': list(observation.translation),
        'quaternion': list(observation.rotation),
        'latching': observation.latching,
    }


def main():
    try:
        import rosgraph
        import rospy
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import LaserScan
        from tf2_msgs.msg import TFMessage
        import tf2_ros
    except ImportError as exc:
        print('V1_RUNTIME_PREFLIGHT_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1

    rospy.init_node('v1_runtime_preflight', anonymous=False)
    profile_file = rospy.get_param('~profile_file')
    stage = rospy.get_param('~stage', 'scan')
    map_file = rospy.get_param('~map_file', '') or None
    active_map_id = rospy.get_param('~active_map_id', '') or None
    mode = rospy.get_param('~mode', 'native')
    cmd_vel_output_topic = rospy.get_param(
        '~cmd_vel_output_topic', '') or None
    samples = int(rospy.get_param('~samples', 30))
    vendor_tf_rules_file = rospy.get_param(
        '~vendor_tf_rules_file', '') or ''
    vendor_source_manifest_file = rospy.get_param(
        '~vendor_source_manifest_file', '') or ''
    vendor_publisher_pin_file = rospy.get_param(
        '~vendor_publisher_pin_file', '') or ''
    if samples < 10:
        rospy.logfatal('samples must be at least 10')
        return 1
    try:
        profile = load_profile(profile_file)
        validate_amcl_transform_tolerance(
            profile, PACKAGE_ROOT / 'config' / 'amcl.yaml')
        validate_runtime_request(
            profile, stage, map_file=map_file, active_map_id=active_map_id,
            mode=mode, cmd_vel_output_topic=cmd_vel_output_topic)
        vendor_tf_rules = _load_vendor_tf_rules(
            vendor_tf_rules_file,
            vendor_source_manifest_file,
            vendor_publisher_pin_file)
    except (
            OSError, ValueError, json.JSONDecodeError,
            TfEdgeValidationError) as exc:
        rospy.logfatal('V1_RUNTIME_PREFLIGHT_BLOCKED: %s', exc)
        return 1

    scan_times = deque(maxlen=samples)
    scan_valid = {'frame': False, 'range': False, 'source_stamp': None}
    odom_valid = {'seen': False, 'frames': False}
    tf_lock = threading.RLock()
    tf_observations = []
    tf_message_id = {'value': 0}
    master = rosgraph.Master(rospy.get_name())
    publishers_before, _subscribers_before = _system_state(master)
    tf_publishers_before = {
        topic: set(publishers_before.get(topic, ()))
        for topic in ('/tf', '/tf_static')}

    def scan_callback(message):
        scan_times.append(time.monotonic())
        scan_valid['source_stamp'] = message.header.stamp.to_sec()
        scan_valid['frame'] = message.header.frame_id == profile['frames']['laser']
        scan_valid['range'] = (
            abs(message.range_min - profile['scan']['range_min_m']) <= 1e-6
            and abs(message.range_max - profile['scan']['range_max_m']) <= 1e-6)

    def odom_callback(message):
        odom_valid['seen'] = True
        odom_valid['frames'] = (
            message.header.frame_id == profile['frames']['odom']
            and message.child_frame_id == profile['frames']['base'])

    def tf_callback(message, topic):
        receipt = time.monotonic()
        with tf_lock:
            tf_message_id['value'] += 1
            message_id = tf_message_id['value']
            for transform in message.transforms:
                tf_observations.append(_tf_observation(
                    message, transform, topic, message_id, receipt))

    rospy.Subscriber(profile['topics']['scan'], LaserScan, scan_callback, queue_size=10)
    rospy.Subscriber(profile['topics']['odom'], Odometry, odom_callback, queue_size=10)
    rospy.Subscriber(
        '/tf', TFMessage, tf_callback, callback_args='/tf', queue_size=100)
    rospy.Subscriber(
        '/tf_static', TFMessage, tf_callback,
        callback_args='/tf_static', queue_size=20)
    deadline = time.monotonic() + max(
        10.0, samples / profile['scan']['min_hz'] + 3.0)
    rate = rospy.Rate(20)
    while not rospy.is_shutdown() and time.monotonic() < deadline:
        if len(scan_times) >= samples and odom_valid['seen']:
            break
        rate.sleep()
    if len(scan_times) < samples or not odom_valid['seen']:
        rospy.logfatal('V1_RUNTIME_PREFLIGHT_BLOCKED: scan/odom samples missing')
        return 1
    duration = scan_times[-1] - scan_times[0]
    scan_hz = (len(scan_times) - 1) / duration if duration > 0.0 else 0.0
    if not profile['scan']['min_hz'] <= scan_hz <= profile['scan']['max_hz']:
        rospy.logfatal('V1_RUNTIME_PREFLIGHT_BLOCKED: scan rate %.3f', scan_hz)
        return 1
    scan_source_stamp = scan_valid['source_stamp']
    if scan_source_stamp is None or not math.isfinite(scan_source_stamp):
        rospy.logfatal(
            'V1_RUNTIME_PREFLIGHT_BLOCKED: scan source stamp missing/invalid')
        return 1
    scan_source_age = rospy.Time.now().to_sec() - scan_source_stamp
    scan_receive_age = time.monotonic() - scan_times[-1]
    scan_timeout = profile['freshness']['scan_timeout_s']
    future_tolerance = profile['tf_timing']['source_future_tolerance_s']
    if not (-future_tolerance <= scan_source_age < scan_timeout):
        rospy.logfatal(
            'V1_RUNTIME_PREFLIGHT_BLOCKED: scan source age %.3f',
            scan_source_age)
        return 1
    if not 0.0 <= scan_receive_age < scan_timeout:
        rospy.logfatal(
            'V1_RUNTIME_PREFLIGHT_BLOCKED: scan receive age %.3f',
            scan_receive_age)
        return 1
    if not scan_valid['frame'] or not scan_valid['range'] or not odom_valid['frames']:
        rospy.logfatal('V1_RUNTIME_PREFLIGHT_BLOCKED: frame/range contract failed')
        return 1

    buffer = tf2_ros.Buffer()
    listener = tf2_ros.TransformListener(buffer)
    rospy.sleep(0.5)
    try:
        odom_to_base = buffer.lookup_transform(
            profile['frames']['odom'], profile['frames']['base'],
            rospy.Time(0), rospy.Duration(0.5))
        buffer.lookup_transform(
            profile['frames']['base'], profile['frames']['laser'],
            rospy.Time(0), rospy.Duration(0.5))
        if stage in ('localization', 'navigation'):
            map_to_base = buffer.lookup_transform(
                profile['frames']['map'], profile['frames']['base'],
                rospy.Time(0), rospy.Duration(0.5))
            tf_source_stamp = map_to_base.header.stamp.to_sec()
        else:
            tf_source_stamp = odom_to_base.header.stamp.to_sec()
    except Exception as exc:  # tf2 exception classes vary across Noetic builds
        rospy.logfatal('V1_RUNTIME_PREFLIGHT_BLOCKED: TF missing: %s', exc)
        return 1
    if not math.isfinite(tf_source_stamp):
        rospy.logfatal(
            'V1_RUNTIME_PREFLIGHT_BLOCKED: TF source stamp invalid')
        return 1
    tf_source_age = rospy.Time.now().to_sec() - tf_source_stamp
    if not (-future_tolerance
            <= tf_source_age < profile['freshness']['tf_timeout_s']):
        rospy.logfatal(
            'V1_RUNTIME_PREFLIGHT_BLOCKED: TF source age %.3f',
            tf_source_age)
        return 1

    publishers, subscribers = _system_state(master)
    tf_publishers_after = {
        topic: set(publishers.get(topic, ()))
        for topic in ('/tf', '/tf_static')}
    if tf_publishers_before != tf_publishers_after:
        rospy.logfatal(
            'V1_RUNTIME_PREFLIGHT_BLOCKED: TF publisher graph changed '
            'during evidence capture')
        return 1
    tf_publishers = set(publishers.get('/tf', ())) | set(
        publishers.get('/tf_static', ()))
    active_nodes = set(tf_publishers)
    for mapping in (publishers, subscribers):
        for owners in mapping.values():
            active_nodes.update(owners)
    try:
        validate_topology(
            publishers, subscribers, tf_publishers,
            navigation=(stage == 'navigation'), mode=mode,
            active_nodes=active_nodes,
            phase=('precore' if stage == 'navigation_precore' else 'runtime'))
        with tf_lock:
            captured_tf = tuple(tf_observations)
        tf_edge_report = validate_tf_edge_evidence(
            captured_tf,
            stage=stage,
            vendor_rules=vendor_tf_rules,
            current_tf_publishers_by_topic=tf_publishers_after,
            now_monotonic=time.monotonic(),
            dynamic_timeout_s=profile['freshness']['tf_timeout_s'],
            now_source_time=rospy.Time.now().to_sec(),
            source_timeout_s=profile['freshness']['tf_timeout_s'],
            source_future_tolerance_s=future_tolerance,
        )
    except (RuntimeError, TfEdgeValidationError) as exc:
        rospy.logfatal('V1_RUNTIME_PREFLIGHT_BLOCKED: %s', exc)
        return 1
    report = {
        'status': 'V1_SCAN_ODOM_TF_PREFLIGHT_PASS',
        'stage': stage,
        'mode': mode,
        'cmd_vel_output_topic': cmd_vel_output_topic,
        'scan_hz': scan_hz,
        'scan_source_age_s': scan_source_age,
        'scan_receive_age_s': scan_receive_age,
        'tf_source_age_s': tf_source_age,
        'scan_samples': len(scan_times),
        'odom_tf_owner': profile['owners']['odom_tf'],
        'vendor_tf_rules_file': vendor_tf_rules_file or None,
        'vendor_source_manifest_file': vendor_source_manifest_file or None,
        'vendor_publisher_pin_file': vendor_publisher_pin_file or None,
        'vendor_contract': vendor_tf_rules.evidence_summary(),
        'tf_publishers_by_topic': {
            topic: sorted(owners)
            for topic, owners in tf_publishers_after.items()},
        'tf_edge_report': tf_edge_report,
        'tf_observation_count': len(captured_tf),
        'tf_observations': [
            _tf_observation_dict(item) for item in captured_tf],
        'map_id': active_map_id,
    }
    del listener
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
