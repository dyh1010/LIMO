#!/usr/bin/env python3
"""Fail-closed, perception-only ROS1 field acceptance orchestrator.

The default mode only prints the plan.  ``--read-only-precheck`` inspects the
host without changing ROS or device state.  Hardware can start only after an
explicit action flag, a one-time authorization id, an exact CLI confirmation,
and a second exact confirmation entered on an interactive terminal.
"""

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
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

from limo_v1_navigation.topology_policy import (  # noqa: E402
    TfEdgeObservation,
    TfEdgeValidationError,
    load_verified_vendor_tf_rules,
    validate_tf_edge_evidence,
)


CONFIRMATION = 'START_PERCEPTION_ONLY'
VENDOR_BLOCKER_FILE = PACKAGE_ROOT / 'docs' / (
    'V1_ROS1_VENDOR_INCLUDE_BLOCKER.json')
SCAN_SAMPLES = 30
ODOM_SAMPLES = 10
SCAN_MIN_HZ = 4.8
SCAN_MAX_HZ = 7.2
SCAN_FRAME = 'laser_link'
ODOM_FRAME = 'odom'
BASE_FRAME = 'base_link'
ANGLE_MIN = math.radians(-100.0)
ANGLE_MAX = math.radians(100.0)
ANGLE_TOLERANCE = math.radians(0.5)
SOURCE_TIMEOUT = 0.5
SOURCE_FUTURE_TOLERANCE = 0.1

PROCESS_PATTERN = re.compile(
    r'(^|[/\s])('
    r'roscore|rosmaster|roslaunch|rosout|limo_base_node|limo_base|'
    r'ydlidar_lidar_publisher|teleop|teletop|joy_node|slam_gmapping|'
    r'cartographer|amcl|move_base|map_server|robot_pose_ekf|dynamic_bridge|'
    r'cleanup_ros1_navigation_adapter|v1_cmd_guard|nav2[^\s/]*)'
    r'([/\s]|$)',
    re.IGNORECASE,
)
FORBIDDEN_NODES = {
    '/slam_gmapping', '/cartographer_node', '/amcl', '/move_base',
    '/map_server', '/robot_pose_ekf', '/cleanup_ros1_navigation_adapter',
    '/v1_cmd_guard', '/dynamic_bridge',
}


def _run(command, timeout=6.0):
    return subprocess.run(
        command, capture_output=True, text=True, timeout=timeout,
        check=False)


def _matching_processes():
    completed = _run(
        ['ps', '-eo', 'pid=,ppid=,comm=,args=', '--width', '400'],
        timeout=5.0)
    if completed.returncode != 0:
        return ['PROCESS_AUDIT_FAILED: {}'.format(completed.stderr.strip())]
    matches = []
    for line in completed.stdout.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) != 4:
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if PROCESS_PATTERN.search(fields[3]):
            matches.append(line.strip())
    return matches


def _device_state(path):
    candidate = Path(path)
    if not candidate.exists():
        return {
            'path': path, 'exists': False, 'owners': [], 'free': False,
            'error': 'device path is missing'}
    completed = _run(['fuser', path], timeout=5.0)
    owners = [
        token for token in completed.stdout.replace(':', ' ').split()
        if token.isdigit()]
    # fuser returns 1 when no process owns the device.
    free = completed.returncode == 1 and not owners
    error = '' if completed.returncode in (0, 1) else (
        completed.stderr.strip() or 'fuser audit failed')
    return {
        'path': path, 'exists': True, 'owners': owners, 'free': free,
        'error': error}


def _master_online():
    completed = _run(['rosnode', 'list'], timeout=5.0)
    return completed.returncode == 0, completed.stdout.splitlines(), (
        completed.stderr.strip())


def _cmd_vel_publishers():
    online, _nodes, _error = _master_online()
    if not online:
        return {}
    topics = _run(['rostopic', 'list'], timeout=5.0)
    if topics.returncode != 0:
        return {'<topic-list-failed>': [topics.stderr.strip()]}
    result = {}
    for topic in sorted(
            item.strip() for item in topics.stdout.splitlines()
            if 'cmd_vel' in item):
        info = _run(['rostopic', 'info', topic], timeout=5.0)
        publishers = []
        in_publishers = False
        for raw in info.stdout.splitlines():
            line = raw.strip()
            if line == 'Publishers:':
                in_publishers = True
                continue
            if line == 'Subscribers:':
                in_publishers = False
            elif in_publishers and line.startswith('*'):
                publishers.append(line)
        if publishers:
            result[topic] = publishers
    return result


def read_only_precheck():
    online, nodes, master_error = _master_online()
    report = {
        'phase': 'READ_ONLY_PRECHECK',
        'process_matches': _matching_processes(),
        'ros_master_online': online,
        'ros_nodes': nodes,
        'ros_master_error': master_error,
        'ttyTHS0': _device_state('/dev/ttyTHS0'),
        'ydlidar': _device_state('/dev/ydlidar'),
        'cmd_vel_publishers': _cmd_vel_publishers(),
    }
    blockers = []
    if report['process_matches']:
        blockers.append('existing ROS/base/lidar/navigation process')
    if online:
        blockers.append('ROS master already online; this run must own its master')
    if not report['ttyTHS0']['exists'] or not report['ttyTHS0']['free']:
        blockers.append('/dev/ttyTHS0 missing or owned')
    if not report['ydlidar']['exists'] or not report['ydlidar']['free']:
        blockers.append('/dev/ydlidar missing or owned')
    if report['cmd_vel_publishers']:
        blockers.append('unknown cmd_vel publisher exists')
    report['blockers'] = blockers
    report['status'] = 'PASS' if not blockers else 'BLOCK'
    return report


def _canonical(value):
    value = str(value or '').strip()
    return '/' + value.strip('/') if value.strip('/') else '/'


def _load_vendor_tf_rules(
        rules_file, source_manifest_file, publisher_pin_file):
    """Verify independent artifacts and their actual referenced bytes."""
    return load_verified_vendor_tf_rules(
        rules_file, source_manifest_file, publisher_pin_file,
        VENDOR_BLOCKER_FILE)


def _require_runtime_launch_binding(_vendor_tf_rules):
    """Block until roslaunch consumes the exact verified immutable bytes."""
    raise TfEdgeValidationError(
        'TF_VENDOR_CONTRACT_UNVERIFIED',
        'TF_VENDOR_RUNTIME_BINDING_UNVERIFIED: verified paths are not '
        'atomically bound to roslaunch consumption')


def _tf_observation(message, transform, topic, message_id, receipt_monotonic):
    header = getattr(message, '_connection_header', None) or {}
    translation = transform.transform.translation
    rotation = transform.transform.rotation
    latching = str(header.get('latching', '0')).strip().lower() in (
        '1', 'true')
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
        latching=latching,
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


class PerceptionEvidence:
    def __init__(self, rospy, LaserScan, Odometry, TFMessage):
        self.rospy = rospy
        self.lock = threading.RLock()
        self.scan = []
        self.odom = []
        self.tf_observations = []
        self.tf_message_id = 0
        self.subscriptions = [
            rospy.Subscriber('/scan', LaserScan, self._scan, queue_size=50),
            rospy.Subscriber('/odom', Odometry, self._odom, queue_size=50),
            rospy.Subscriber(
                '/tf', TFMessage, self._tf,
                callback_args='/tf', queue_size=100),
            rospy.Subscriber(
                '/tf_static', TFMessage, self._tf,
                callback_args='/tf_static', queue_size=20),
        ]

    def _caller(self, message):
        header = getattr(message, '_connection_header', None) or {}
        return _canonical(header.get('callerid', ''))

    def _scan(self, message):
        with self.lock:
            stamp = message.header.stamp.to_sec()
            ros_now = self.rospy.Time.now().to_sec()
            self.scan.append({
                'receipt_monotonic': time.monotonic(),
                'stamp': stamp,
                'source_age': ros_now - stamp,
                'frame_id': message.header.frame_id,
                'angle_min': float(message.angle_min),
                'angle_max': float(message.angle_max),
                'range_min': float(message.range_min),
                'range_max': float(message.range_max),
                'callerid': self._caller(message),
            })
            self.scan = self.scan[-SCAN_SAMPLES:]

    def _odom(self, message):
        with self.lock:
            self.odom.append({
                'receipt_monotonic': time.monotonic(),
                'stamp': message.header.stamp.to_sec(),
                'frame_id': message.header.frame_id,
                'child_frame_id': message.child_frame_id,
                'callerid': self._caller(message),
            })
            self.odom = self.odom[-ODOM_SAMPLES:]

    def _tf(self, message, topic):
        receipt = time.monotonic()
        with self.lock:
            self.tf_message_id += 1
            for transform in message.transforms:
                self.tf_observations.append(_tf_observation(
                    message, transform, topic,
                    self.tf_message_id, receipt))

    def ready(self):
        with self.lock:
            edges = {
                (
                    item.parent_frame.strip().strip('/'),
                    item.child_frame.strip().strip('/'))
                for item in self.tf_observations}
            return (
                len(self.scan) >= SCAN_SAMPLES
                and len(self.odom) >= ODOM_SAMPLES
                and ('odom', 'base_link') in edges
                and ('base_link', 'laser_link') in edges)

    def close(self):
        for subscription in self.subscriptions:
            subscription.unregister()


def _strictly_increasing(values):
    return all(
        math.isfinite(previous) and math.isfinite(current)
        and current > previous
        for previous, current in zip(values, values[1:]))


def _graph_state(rosgraph, node_name):
    publishers, subscribers, services = rosgraph.Master(node_name).getSystemState()
    return dict(publishers), dict(subscribers), {
        owner for _name, owners in publishers + subscribers + services
        for owner in owners}


def _validate_runtime(
        evidence, rosgraph, rospy, tf_buffer, vendor_tf_rules,
        tf_publishers_before):
    blockers = []
    with evidence.lock:
        scans = list(evidence.scan)
        odom = list(evidence.odom)
        tf_observations = tuple(evidence.tf_observations)
    tf_owners = defaultdict(set)
    for item in tf_observations:
        edge = '{}->{}'.format(
            _canonical(item.parent_frame), _canonical(item.child_frame))
        tf_owners[edge].add(_canonical(item.authority))
    tf_owners = {
        key: sorted(value) for key, value in tf_owners.items()}
    duration = scans[-1]['receipt_monotonic'] - scans[0]['receipt_monotonic']
    scan_hz = (len(scans) - 1) / duration if duration > 0.0 else 0.0
    scan_stamps = [item['stamp'] for item in scans]
    odom_stamps = [item['stamp'] for item in odom]
    if not SCAN_MIN_HZ <= scan_hz <= SCAN_MAX_HZ:
        blockers.append('scan rate is outside 4.8-7.2 Hz')
    if {item['callerid'] for item in scans} != {'/ydlidar_lidar_publisher'}:
        blockers.append('/scan publisher is not uniquely YDLidar')
    if any(item['frame_id'] != SCAN_FRAME for item in scans):
        blockers.append('/scan frame is not laser_link')
    if any(abs(item['angle_min'] - ANGLE_MIN) > ANGLE_TOLERANCE
           or abs(item['angle_max'] - ANGLE_MAX) > ANGLE_TOLERANCE
           for item in scans):
        blockers.append('/scan angle limits are not -100/+100 degrees')
    if not _strictly_increasing(scan_stamps):
        blockers.append('/scan stamps are not finite and strictly increasing')
    if any(not -SOURCE_FUTURE_TOLERANCE <= item['source_age'] < SOURCE_TIMEOUT
           for item in scans):
        blockers.append('/scan source age violates [-0.1, 0.5) seconds')
    if {item['callerid'] for item in odom} != {'/limo_base_node'}:
        blockers.append('/odom publisher is not uniquely limo_base_node')
    if any(item['frame_id'] != ODOM_FRAME
           or item['child_frame_id'] != BASE_FRAME for item in odom):
        blockers.append('/odom frames are not odom/base_link')
    if not _strictly_increasing(odom_stamps):
        blockers.append('/odom stamps are not finite and strictly increasing')
    try:
        tf_buffer.lookup_transform(
            ODOM_FRAME, BASE_FRAME, rospy.Time(0), rospy.Duration(0.5))
        tf_buffer.lookup_transform(
            BASE_FRAME, SCAN_FRAME, rospy.Time(0), rospy.Duration(0.5))
    except Exception as error:
        blockers.append('segment TF lookup failed: {}'.format(error))

    publishers, subscribers, active_nodes = _graph_state(
        rosgraph, rospy.get_name())
    tf_publishers_after = {
        topic: set(publishers.get(topic, ()))
        for topic in ('/tf', '/tf_static')}
    if tf_publishers_before != tf_publishers_after:
        blockers.append('TF publisher graph changed during evidence capture')
    tf_edge_report = None
    try:
        tf_edge_report = validate_tf_edge_evidence(
            tf_observations,
            stage='scan',
            vendor_rules=vendor_tf_rules,
            current_tf_publishers_by_topic=tf_publishers_after,
            now_monotonic=time.monotonic(),
            dynamic_timeout_s=SOURCE_TIMEOUT,
            now_source_time=rospy.Time.now().to_sec(),
            source_timeout_s=SOURCE_TIMEOUT,
            source_future_tolerance_s=SOURCE_FUTURE_TOLERANCE,
        )
    except TfEdgeValidationError as error:
        blockers.append(str(error))
    if set(publishers.get('/scan', ())) != {'/ydlidar_lidar_publisher'}:
        blockers.append('/scan ROS master owner mismatch')
    if set(publishers.get('/odom', ())) != {'/limo_base_node'}:
        blockers.append('/odom ROS master owner mismatch')
    if publishers.get('/cmd_vel') or subscribers.get('/cmd_vel'):
        blockers.append('public /cmd_vel must have zero endpoints')
    if publishers.get('/v1/driver_cmd_vel'):
        blockers.append('/v1/driver_cmd_vel must have zero publishers')
    if set(subscribers.get('/v1/driver_cmd_vel', ())) != {'/limo_base_node'}:
        blockers.append('/v1/driver_cmd_vel consumer is not uniquely limo_base_node')
    cmd_vel_publishers = {
        topic: sorted(owners) for topic, owners in publishers.items()
        if 'cmd_vel' in topic and owners}
    if cmd_vel_publishers:
        blockers.append('a cmd_vel-like publisher exists')
    forbidden = sorted(
        node for node in active_nodes
        if node in FORBIDDEN_NODES
        or any(node.startswith(item + '_') for item in FORBIDDEN_NODES))
    if forbidden:
        blockers.append('forbidden node present: {}'.format(', '.join(forbidden)))

    return {
        'scan_samples': len(scans),
        'scan_hz': scan_hz,
        'scan_frame': sorted({item['frame_id'] for item in scans}),
        'scan_angle_min_deg': math.degrees(scans[-1]['angle_min']),
        'scan_angle_max_deg': math.degrees(scans[-1]['angle_max']),
        'scan_stamp_first': scan_stamps[0],
        'scan_stamp_last': scan_stamps[-1],
        'scan_source_age_max_s': max(item['source_age'] for item in scans),
        'odom_samples': len(odom),
        'odom_frames': sorted({
            '{}/{}'.format(item['frame_id'], item['child_frame_id'])
            for item in odom}),
        'tf_owners': tf_owners,
        'tf_publishers_by_topic': {
            topic: sorted(owners)
            for topic, owners in tf_publishers_after.items()},
        'tf_edge_report': tf_edge_report,
        'tf_observation_count': len(tf_observations),
        'tf_observations': [
            _tf_observation_dict(item) for item in tf_observations],
        'cmd_vel_publishers': cmd_vel_publishers,
        'active_nodes': sorted(active_nodes),
        'blockers': blockers,
        'status': 'PASS' if not blockers else 'BLOCK',
    }


def _stop_owned_launch(process):
    if process is None or process.poll() is not None:
        return
    group = os.getpgid(process.pid)
    os.killpg(group, signal.SIGINT)
    try:
        process.wait(timeout=12.0)
        return
    except subprocess.TimeoutExpired:
        os.killpg(group, signal.SIGTERM)
    try:
        process.wait(timeout=5.0)
        return
    except subprocess.TimeoutExpired:
        os.killpg(group, signal.SIGKILL)
        process.wait(timeout=5.0)


def _wait_for_cleanup(timeout=12.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        online, nodes, error = _master_online()
        last = {
            'process_matches': _matching_processes(),
            'ros_master_online': online,
            'ros_nodes': nodes,
            'ros_master_error': error,
            'ttyTHS0': _device_state('/dev/ttyTHS0'),
            'ydlidar': _device_state('/dev/ydlidar'),
        }
        if (
                not last['process_matches']
                and not online
                and last['ttyTHS0']['free']
                and last['ydlidar']['free']):
            last['status'] = 'PASS'
            last['blockers'] = []
            return last
        time.sleep(0.25)
    blockers = []
    if last['process_matches']:
        blockers.append('owned bringup process did not fully disappear')
    if last['ros_master_online']:
        blockers.append('owned ROS master did not stop')
    if not last['ttyTHS0']['free']:
        blockers.append('/dev/ttyTHS0 was not released')
    if not last['ydlidar']['free']:
        blockers.append('/dev/ydlidar was not released')
    last['status'] = 'BLOCK'
    last['blockers'] = blockers
    return last


def _write_result(path, report):
    if not path:
        return
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.parent.is_dir():
        raise ValueError('result-file must be an absolute path in an existing directory')
    descriptor = os.open(
        str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        payload = json.dumps(report, indent=2, sort_keys=True).encode('utf-8')
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_result_target(path):
    candidate = Path(path)
    if (
            not path or not candidate.is_absolute()
            or not candidate.parent.is_dir() or candidate.exists()):
        raise ValueError(
            'hardware action requires a new absolute result-file in an '
            'existing directory')


def authorize_hardware_action(arguments, stdin=None):
    """Require all three independent operator authorization factors."""
    if os.name != 'posix':
        raise RuntimeError('perception-only hardware execution requires Linux')
    if arguments.confirm_exact != CONFIRMATION:
        raise RuntimeError('exact CLI confirmation is missing')
    if (
            not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', arguments.authorization_id)
            or arguments.authorization_id == 'NOT_AUTHORIZED'):
        raise RuntimeError('a valid one-time authorization id is required')
    stream = stdin or sys.stdin
    if not stream.isatty():
        raise RuntimeError('interactive on-site terminal confirmation is required')
    sys.stdout.write(
        'Type {} to start sensors without motion: '.format(CONFIRMATION))
    sys.stdout.flush()
    typed = stream.readline().rstrip('\r\n')
    if typed != CONFIRMATION:
        raise RuntimeError('interactive confirmation did not match')


def execute_hardware(arguments):
    _validate_result_target(arguments.result_file)
    vendor_tf_rules = _load_vendor_tf_rules(
        arguments.vendor_tf_rules_file,
        arguments.vendor_source_manifest_file,
        arguments.vendor_publisher_pin_file)
    vendor_contract = vendor_tf_rules.evidence_summary()
    _require_runtime_launch_binding(vendor_tf_rules)
    authorize_hardware_action(arguments)

    precheck = read_only_precheck()
    if precheck['status'] != 'PASS':
        return {
            'status': 'BLOCK',
            'precheck': precheck,
            'vendor_contract': vendor_contract,
        }

    launch = None
    evidence = None
    runtime = {'status': 'BLOCK', 'blockers': ['runtime did not complete']}
    cleanup = {'status': 'BLOCK', 'blockers': ['cleanup did not run']}
    launch_tail = ''
    with tempfile.TemporaryDirectory(prefix='v1_perception_only.') as temporary:
        log_path = Path(temporary) / 'bringup.log'
        log_stream = log_path.open('w+', encoding='utf-8')
        try:
            command = [
                'roslaunch', 'limo_v1_navigation', 'v1_base_sensors.launch',
                'enable_hardware:=true',
                'hardware_authorization_id:={}'.format(
                    arguments.authorization_id),
                'odom_tf_owner:=/limo_base_node',
            ]
            launch = subprocess.Popen(
                command, stdout=log_stream, stderr=subprocess.STDOUT,
                start_new_session=True)
            deadline = time.monotonic() + 30.0
            required = {'/limo_base_node', '/ydlidar_lidar_publisher'}
            while time.monotonic() < deadline:
                if launch.poll() is not None:
                    raise RuntimeError('bringup exited before sensors became ready')
                online, nodes, _error = _master_online()
                if online and required.issubset(nodes):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError('bringup did not expose required nodes in 30 s')

            import rosgraph
            import rospy
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import LaserScan
            from tf2_msgs.msg import TFMessage
            import tf2_ros

            rospy.init_node(
                'v1_perception_only_acceptance', anonymous=False,
                disable_signals=True)
            tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
            tf_listener = tf2_ros.TransformListener(tf_buffer)
            publishers_before, _subscribers_before, _active_before = (
                _graph_state(rosgraph, rospy.get_name()))
            tf_publishers_before = {
                topic: set(publishers_before.get(topic, ()))
                for topic in ('/tf', '/tf_static')}
            evidence = PerceptionEvidence(rospy, LaserScan, Odometry, TFMessage)
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline and not evidence.ready():
                if launch.poll() is not None:
                    raise RuntimeError('bringup exited during evidence collection')
                time.sleep(0.05)
            if not evidence.ready():
                raise RuntimeError('scan/odom/TF evidence was incomplete after 15 s')
            runtime = _validate_runtime(
                evidence, rosgraph, rospy, tf_buffer, vendor_tf_rules,
                tf_publishers_before)
            del tf_listener
        except Exception as error:
            runtime = {'status': 'BLOCK', 'blockers': [str(error)]}
        finally:
            if evidence is not None:
                evidence.close()
            try:
                import rospy
                if not rospy.is_shutdown():
                    rospy.signal_shutdown('perception-only evidence complete')
            except ImportError:
                pass
            _stop_owned_launch(launch)
            log_stream.flush()
            log_stream.seek(0)
            launch_tail = log_stream.read()[-8000:]
            log_stream.close()
            cleanup = _wait_for_cleanup()

    status = (
        'PASS' if runtime.get('status') == 'PASS'
        and cleanup.get('status') == 'PASS' else 'BLOCK')
    return {
        'status': status,
        'authorization_id': arguments.authorization_id,
        'precheck': precheck,
        'vendor_contract': vendor_contract,
        'runtime': runtime,
        'cleanup': cleanup,
        'bringup_log_tail': launch_tail,
        'not_run': ['teleop', 'Gmapping', 'AMCL', 'move_base', 'map_server'],
    }


def print_plan():
    print('V1_PERCEPTION_ONLY_DRY_RUN')
    print('No ROS node or hardware process was started.')
    print('1. Source Noetic, vendor workspace, then the V1 overlay workspace.')
    print('2. Read-only check:')
    print('   rosrun limo_v1_navigation v1_perception_only_field.py '
          '--read-only-precheck')
    print('3. After a fresh main-task authorization and on-site confirmation:')
    print('   rosrun limo_v1_navigation v1_perception_only_field.py '
          '--execute-hardware --authorization-id <ONE_TIME_ID> '
          '--vendor-tf-rules-file /absolute/verified/vendor_tf_rules.json '
          '--vendor-source-manifest-file /absolute/verified/source.json '
          '--vendor-publisher-pin-file /absolute/verified/pin.json '
          '--confirm-exact {} --result-file /absolute/new/result.json'.format(
              CONFIRMATION))
    print('4. The action still requires typing {} on a TTY.'.format(
        CONFIRMATION))
    print('5. Never start teleop, Gmapping, AMCL, move_base, or map_server.')


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--read-only-precheck', action='store_true')
    mode.add_argument('--execute-hardware', action='store_true')
    parser.add_argument('--authorization-id', default='')
    parser.add_argument('--confirm-exact', default='')
    parser.add_argument('--result-file', default='')
    parser.add_argument('--vendor-tf-rules-file', default='')
    parser.add_argument('--vendor-source-manifest-file', default='')
    parser.add_argument('--vendor-publisher-pin-file', default='')
    arguments = parser.parse_args()
    try:
        if arguments.read_only_precheck:
            report = read_only_precheck()
        elif arguments.execute_hardware:
            report = execute_hardware(arguments)
        else:
            print_plan()
            return 0
        print(json.dumps(report, indent=2, sort_keys=True))
        _write_result(arguments.result_file, report)
        marker = 'PASS' if report.get('status') == 'PASS' else 'BLOCKED'
        print('V1_PERCEPTION_ONLY_{}'.format(marker))
        return 0 if report.get('status') == 'PASS' else 1
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('V1_PERCEPTION_ONLY_BLOCKED: {}'.format(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
