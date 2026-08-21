"""Fail-closed binding of ROS1 typed observations to rosbag1 evidence.

The module is deliberately ROS-independent.  It never joins a ROS graph and
never publishes.  A binding is admitted only when the supplied index can be
recomputed from its decoded connection/message evidence and every typed frame
has the bundle identifier that the ROS1 adapter would have produced from that
exact four-stream bundle and immutable model set.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import stat
from pathlib import Path
from typing import Mapping, Optional, Sequence


SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
STREAM_ROLES = ('rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info')
TF_ROLES = ('tf', 'tf_static')
ALL_ROLES = STREAM_ROLES + TF_ROLES
ADAPTER_STREAM_NAMES = {
    'rgb': 'rgb',
    'raw_depth': 'depth',
    'rgb_camera_info': 'rgb_info',
    'depth_camera_info': 'depth_info',
}
MIN_SCENE_FRAMES = 30
MAX_SYNC_SPAN_SEC = 0.15
MAX_UNPAIRED_RATE = 0.05
EXPECTED_FRAME_TOPIC = '/cleanup/perception/frames'
EXPECTED_FRAME_TYPE = 'limo_cleanup_ros1_perception/PerceptionFrame'
TARGET_CLASSES = ('plastic_bottle', 'trash_bin')

COLLECTOR_KEYS = {
    'schema_version', 'collector_kind', 'read_only', 'authorizes_motion',
    'publishes_ros_messages', 'scene', 'topic', 'message_type', 'task_id',
    'max_frames', 'duration_sec', 'received_frames', 'unique_frames',
    'duplicate_sequences', 'duplicate_bundle_ids', 'serialization_errors',
    'interrupted', 'completed_minimum', 'completed_requested_frames',
    'output',
}
FRAME_KEYS = {
    'schema_version', 'read_only', 'received_unix_sec',
    'transport_latency_sec', 'stamp', 'frame_id', 'task_id', 'capture_id',
    'bundle_id', 'model_binding_sha256', 'sequence', 'valid', 'status',
    'error_code', 'sync_span_sec', 'processing_latency_sec',
    'tf_target_frame', 'tf_valid', 'tf_transform_applied', 'tf_status',
    'tf_error_code', 'targets', 'scene',
}
TARGET_KEYS = {
    'observation_id', 'object_class', 'confidence', 'valid', 'actionable',
    'status', 'error_code', 'position', 'size', 'bbox', 'depth_m',
    'depth_valid_pixels', 'depth_total_pixels', 'depth_valid_ratio',
    'source', 'position_semantics',
}
LEGACY_INDEX_SUCCESS_KEYS = {
    'schema_version', 'report_kind', 'inspection_scope', 'mode', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'starts_ros_graph',
    'storage_identifier', 'indexer_source', 'timestamp_semantics',
    'source_capture', 'capture_id', 'scene', 'expected_topic_manifest',
    'stream_topics', 'topics', 'messages', 'streams', 'rgb_candidate_count',
    'accepted_bundle_count', 'rejected_rgb_count', 'rejection_reasons',
    'unmatched_message_count_by_stream', 'total_stream_message_count',
    'total_unpaired_message_count', 'total_unpaired_rate',
    'unique_header_pair_count', 'formal_contract_valid_pair_count',
    'accepted_bundles', 'tf_graph', 'inspection_passed',
    'diagnostic_completed', 'formal_acceptance', 'shared_graph', 'mixed_tf',
    'not_in_four_scene_denominator', 'delivery_ready', 'failures',
    'limitations',
}
FORMAL_INDEX_SUCCESS_KEYS = LEGACY_INDEX_SUCCESS_KEYS | {
    'capture_window', 'message_accounting',
    'isolated_old_latched_camera_info_count',
    'isolated_old_latched_camera_info', 'aligned_stream_contract',
    'failure_details',
}
FORMAL_TOPIC_KEYS = {
    'connection_id', 'topic', 'role', 'type', 'md5sum', 'callerid',
    'latching', 'connection_header', 'connection_header_sha256',
    'message_count', 'first_record_timestamp_ns',
    'last_record_timestamp_ns', 'formal_valid', 'validation_failures',
}
FORMAL_MESSAGE_KEYS = {
    'message_id', 'connection_id', 'topic', 'role', 'callerid',
    'record_timestamp_ns', 'serialized_size_bytes', 'serialized_sha256',
    'record_header_skew_sec', 'connection_header',
    'connection_header_sha256', 'decoded', 'isolated',
    'isolation_reason', 'formal_valid', 'validation_failures',
}
CAPTURE_WINDOW_KEYS = {
    'header_start_ns', 'header_end_ns',
    'record_start_ns', 'record_end_ns',
}
MESSAGE_ACCOUNTING_KEYS = {
    'source_message_count', 'admitted_message_count',
    'isolated_message_count', 'source_message_count_by_role',
    'admitted_message_count_by_role', 'isolated_message_count_by_role',
    'closure_valid',
}
ISOLATED_LEDGER_KEYS = {
    'message_id', 'connection_id', 'topic', 'role', 'callerid',
    'record_timestamp_ns', 'header_stamp_ns', 'frame_id',
    'serialized_size_bytes', 'serialized_sha256',
    'connection_header_sha256', 'reason',
}
ALIGNED_STREAM_CONTRACT_KEYS = {
    'required', 'frame_id', 'width', 'height', 'validated_bundle_count',
}
FORMAL_INDEX_POLICY = {
    'report_kind': 'formal_rgbd_raw_capture_index',
    'inspection_scope': 'formal_scene_raw_capture',
    'mode': 'formal_camera_only',
    'inspection_passed': True,
    'diagnostic_completed': False,
    'formal_acceptance': True,
    'shared_graph': False,
    'mixed_tf': False,
    'not_in_four_scene_denominator': False,
    'delivery_ready': False,
}


def _reject_duplicate_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key: ' + key)
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError('non-finite JSON constant: ' + value)


def _load_json(path: Path):
    return json.loads(
        Path(path).read_text(encoding='utf-8'),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_invalid_constant)


def _load_jsonl(path: Path):
    records = []
    with Path(path).open('r', encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(
                    'blank JSONL record at line {}'.format(line_number))
            value = json.loads(
                line, object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_invalid_constant)
            if not isinstance(value, Mapping):
                raise ValueError(
                    'JSONL record is not an object at line {}'.format(
                        line_number))
            records.append(value)
    return records


def _finite(value, minimum=None, maximum=None) -> bool:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        return False
    return ((minimum is None or value >= minimum)
            and (maximum is None or value <= maximum))


def _integer(value, minimum=None) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (minimum is None or value >= minimum))


def _lower_hex(value, length) -> bool:
    return (isinstance(value, str) and len(value) == length
            and value == value.lower()
            and all(character in '0123456789abcdef' for character in value))


def _lower_sha256(value) -> bool:
    return _lower_hex(value, 64)


def _valid_text(value) -> bool:
    return (isinstance(value, str) and bool(value)
            and value == value.strip() and '\x00' not in value)


def _valid_frame_id(value) -> bool:
    if (not _valid_text(value) or value.startswith('/')
            or len(value) > 255):
        return False
    allowed = set(
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')
    return all(
        part not in ('', '.', '..') and all(character in allowed
                                             for character in part)
        for part in value.split('/'))


def _strict_keys(value, expected) -> bool:
    return isinstance(value, Mapping) and set(value) == set(expected)


def _canonical_sha256(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _path_is_linklike(path: Path) -> bool:
    try:
        candidate = Path(path)
        info = candidate.lstat()
        if candidate.is_symlink() or stat.S_ISLNK(info.st_mode):
            return True
        attributes = getattr(info, 'st_file_attributes', 0)
        reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        return bool(reparse and attributes & reparse)
    except (OSError, RuntimeError):
        return True


def _artifact_identity(path: Path) -> Mapping:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file() or _path_is_linklike(path):
        raise ValueError('artifact is not a regular non-link file')
    before = resolved.stat()
    digest = _sha256_file(resolved)
    after = resolved.stat()
    if (before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError('artifact changed during identity audit')
    return {
        'path': str(resolved),
        'size_bytes': after.st_size,
        'sha256': digest,
    }


def _identity_matches(declaration, identity) -> bool:
    return (isinstance(declaration, Mapping)
            and set(declaration) == {'path', 'size_bytes', 'sha256'}
            and _valid_text(declaration.get('path'))
            and declaration.get('size_bytes') == identity.get('size_bytes')
            and declaration.get('sha256') == identity.get('sha256'))


def _stamp_ns(stamp) -> Optional[int]:
    if not _strict_keys(stamp, {'sec', 'nanosec'}):
        return None
    sec = stamp.get('sec')
    nanosec = stamp.get('nanosec')
    if (not _integer(sec, 0) or not _integer(nanosec, 0)
            or nanosec >= 1_000_000_000):
        return None
    value = sec * 1_000_000_000 + nanosec
    return value if value > 0 else None


def _decoded_header(decoded) -> Optional[Mapping]:
    header = decoded.get('header') if isinstance(decoded, Mapping) else None
    if (not _strict_keys(header, {'stamp_ns', 'frame_id'})
            or not _integer(header.get('stamp_ns'), 1)
            or not _valid_frame_id(header.get('frame_id'))):
        return None
    return header


def _validate_image(decoded, role, failures) -> bool:
    expected = {
        'header', 'height', 'width', 'encoding', 'is_bigendian', 'step',
        'data_length'}
    if not _strict_keys(decoded, expected) or _decoded_header(decoded) is None:
        failures.append('raw_index_connection_or_message_invalid')
        return False
    bytes_per_pixel = ({
        'rgb8': 3, 'bgr8': 3, 'rgba8': 4, 'bgra8': 4, 'mono8': 1,
    } if role == 'rgb' else {
        '16UC1': 2, 'mono16': 2, '32FC1': 4,
    }).get(decoded.get('encoding'))
    valid = (
        _integer(decoded.get('height'), 1)
        and _integer(decoded.get('width'), 1)
        and bytes_per_pixel is not None
        and decoded.get('is_bigendian') in (0, 1)
        and _integer(decoded.get('step'), 1)
        and decoded['step'] >= decoded['width'] * bytes_per_pixel
        and _integer(decoded.get('data_length'), 1)
        and decoded['data_length'] == decoded['step'] * decoded['height'])
    if not valid:
        failures.append('raw_index_connection_or_message_invalid')
    return valid


def _finite_array(value, length=None) -> bool:
    return (isinstance(value, list)
            and (length is None or len(value) == length)
            and all(_finite(item) for item in value))


def _validate_camera_info(decoded, failures) -> bool:
    expected = {
        'header', 'height', 'width', 'distortion_model', 'D', 'K', 'R',
        'P', 'binning_x', 'binning_y', 'roi', 'intrinsics'}
    roi_keys = {'x_offset', 'y_offset', 'height', 'width', 'do_rectify'}
    intrinsics_keys = {'fx', 'fy', 'cx', 'cy'}
    if (not _strict_keys(decoded, expected)
            or _decoded_header(decoded) is None
            or not _integer(decoded.get('height'), 1)
            or not _integer(decoded.get('width'), 1)
            or not _valid_text(decoded.get('distortion_model'))
            or not _finite_array(decoded.get('D'))
            or not _finite_array(decoded.get('K'), 9)
            or not _finite_array(decoded.get('R'), 9)
            or not _finite_array(decoded.get('P'), 12)
            or not _integer(decoded.get('binning_x'), 0)
            or not _integer(decoded.get('binning_y'), 0)
            or not _strict_keys(decoded.get('roi'), roi_keys)
            or not _strict_keys(decoded.get('intrinsics'), intrinsics_keys)
            or not all(_finite(decoded['intrinsics'][key])
                       for key in intrinsics_keys)):
        failures.append('raw_index_connection_or_message_invalid')
        return False
    width = decoded['width']
    height = decoded['height']
    matrix = decoded['K']
    projection = decoded['P']
    valid = (
        matrix[0] > 0.0 and matrix[4] > 0.0
        and projection[0] > 0.0 and projection[5] > 0.0
        and 0.0 <= matrix[2] < width and 0.0 <= matrix[5] < height
        and 0.0 <= projection[2] < width
        and 0.0 <= projection[6] < height
        and decoded['intrinsics'] == {
            'fx': matrix[0], 'fy': matrix[4],
            'cx': matrix[2], 'cy': matrix[5]})
    roi = decoded['roi']
    valid = valid and (
        all(_integer(roi.get(key), 0)
            for key in ('x_offset', 'y_offset', 'height', 'width'))
        and isinstance(roi.get('do_rectify'), bool)
        and roi['x_offset'] + roi['width'] <= width
        and roi['y_offset'] + roi['height'] <= height)
    if not valid:
        failures.append('raw_index_connection_or_message_invalid')
    return valid


def _validate_tf(decoded, allow_zero, failures) -> bool:
    if (not _strict_keys(decoded, {'transforms'})
            or not isinstance(decoded.get('transforms'), list)
            or not decoded['transforms']):
        failures.append('raw_index_connection_or_message_invalid')
        return False
    expected = {
        'header', 'child_frame_id', 'translation_m', 'rotation_xyzw'}
    valid = True
    for transform in decoded['transforms']:
        header = transform.get('header') if isinstance(
            transform, Mapping) else None
        if (not _strict_keys(transform, expected)
                or not _strict_keys(header, {'stamp_ns', 'frame_id'})
                or not _integer(header.get('stamp_ns'), 0 if allow_zero else 1)
                or not _valid_frame_id(header.get('frame_id'))
                or not _valid_frame_id(transform.get('child_frame_id'))
                or transform.get('child_frame_id') == header.get('frame_id')
                or not _finite_array(transform.get('translation_m'), 3)
                or not _finite_array(transform.get('rotation_xyzw'), 4)):
            valid = False
            continue
        norm = math.sqrt(sum(
            item * item for item in transform['rotation_xyzw']))
        if abs(norm - 1.0) > 1e-3:
            valid = False
    if not valid:
        failures.append('raw_index_connection_or_message_invalid')
    return valid


def _calibration_sha256(decoded) -> str:
    value = {key: decoded[key] for key in (
        'height', 'width', 'distortion_model', 'D', 'K', 'R', 'P',
        'binning_x', 'binning_y', 'roi')}
    return _canonical_sha256(value)


def _formal_policy_failures(index_report) -> Sequence[str]:
    failures = []
    if not isinstance(index_report, Mapping):
        return ['raw_index_schema_invalid']
    if index_report.get('read_only') is not True:
        failures.append('raw_index_safety_policy_invalid')
    if index_report.get('authorizes_motion') is not False:
        failures.append('raw_index_safety_policy_invalid')
    if index_report.get('publishes_ros_messages') is not False:
        failures.append('raw_index_safety_policy_invalid')
    if index_report.get('starts_ros_graph') is not False:
        failures.append('raw_index_safety_policy_invalid')
    if any(index_report.get(key) != value
           for key, value in FORMAL_INDEX_POLICY.items()):
        failures.append('raw_index_not_formal')
    if (index_report.get('shared_graph') is not False
            or index_report.get('mixed_tf') is not False):
        failures.append('raw_index_shared_or_mixed')
    return failures


def _validate_index_artifacts(index_report, context, failures):
    identities = {}
    if not isinstance(context, Mapping):
        failures.append('raw_index_artifact_identity_mismatch')
        return identities
    for key in ('index_path', 'raw_bag_path', 'frames_path', 'collector_path'):
        path = context.get(key)
        if path is None:
            failures.append('raw_index_artifact_identity_mismatch')
            continue
        try:
            identities[key] = _artifact_identity(Path(path))
        except (OSError, RuntimeError, ValueError):
            failures.append('raw_index_artifact_identity_mismatch')
    raw_identity = identities.get('raw_bag_path')
    if (raw_identity is None
            or not _identity_matches(
                index_report.get('source_capture'), raw_identity)):
        failures.append('raw_index_source_capture_mismatch')

    try:
        from limo_cleanup_ros1_perception import rosbag1_rgbd_indexer
        source_identity = _artifact_identity(Path(
            rosbag1_rgbd_indexer.__file__))
        declaration = index_report.get('indexer_source')
        if (not _identity_matches(declaration, source_identity)
                or Path(declaration['path']).resolve(strict=True)
                != Path(source_identity['path'])):
            failures.append('raw_index_artifact_identity_mismatch')
        # The currently deployed indexer intentionally produces diagnostic
        # short-sample reports only.  Edited report booleans must never turn
        # that source into a formal producer.  A future implementation must
        # expose both of these explicit, source-bound admission hooks.
        if (getattr(rosbag1_rgbd_indexer, 'FORMAL_ACCEPTANCE_MODE', None)
                != 'formal_scene_raw_capture'
                or not callable(getattr(
                    rosbag1_rgbd_indexer, 'inspect_formal_scene', None))):
            failures.append('raw_index_formal_producer_not_implemented')
    except (ImportError, OSError, RuntimeError, ValueError, KeyError):
        failures.append('raw_index_artifact_identity_mismatch')

    manifest_path = context.get('topic_manifest_path')
    try:
        from limo_cleanup_ros1_perception.rosbag1_rgbd_indexer import (
            load_manifest)
        manifest = load_manifest(manifest_path)
        identity = {
            'path': manifest['path'],
            'size_bytes': manifest['size_bytes'],
            'sha256': manifest['sha256'],
            'manifest_id': manifest['manifest_id'],
            'schema_version': manifest['schema_version'],
        }
        declaration = index_report.get('expected_topic_manifest')
        if not isinstance(declaration, Mapping) or any(
                declaration.get(key) != identity[key]
                for key in ('size_bytes', 'sha256', 'manifest_id',
                            'schema_version')):
            failures.append('raw_index_manifest_mismatch')
        identities['topic_manifest'] = identity
    except (ImportError, OSError, RuntimeError, ValueError, KeyError):
        failures.append('raw_index_manifest_mismatch')
    return identities


def _validate_topics(index_report, manifest, failures):
    topics = index_report.get('topics')
    expected_roles = manifest.get('topics_by_role', {}) if isinstance(
        manifest, Mapping) else {}
    if (not isinstance(topics, list) or len(topics) != len(ALL_ROLES)
            or set(expected_roles) != set(ALL_ROLES)):
        failures.append('raw_index_manifest_mismatch')
        return {}, {}
    by_id = {}
    by_role = {}
    core_keys = {
        'connection_id', 'topic', 'role', 'type', 'md5sum', 'callerid',
        'latching', 'message_count', 'first_record_timestamp_ns',
        'last_record_timestamp_ns', 'connection_header',
        'connection_header_sha256'}
    for topic in topics:
        if not _strict_keys(topic, core_keys):
            failures.append('raw_index_connection_or_message_invalid')
            continue
        role = topic.get('role')
        expected = expected_roles.get(role)
        connection_id = topic.get('connection_id')
        header = topic.get('connection_header')
        header_hash = topic.get('connection_header_sha256')
        if (expected is None or role in by_role
                or not _integer(connection_id, 0) or connection_id in by_id
                or topic.get('topic') != expected.get('name')
                or topic.get('type') != expected.get('type')
                or topic.get('md5sum') != expected.get('md5sum')
                or topic.get('callerid') != expected.get('callerid')
                or topic.get('latching') is not expected.get('latching')
                or not _integer(topic.get('message_count'), 1)
                or not _integer(topic.get('first_record_timestamp_ns'), 1)
                or not _integer(topic.get('last_record_timestamp_ns'), 1)
                or topic['last_record_timestamp_ns']
                < topic['first_record_timestamp_ns']
                or not isinstance(header, Mapping)
                or not _lower_sha256(header_hash)
                or _canonical_sha256(header) != header_hash
                or header.get('topic') != expected.get('name')
                or header.get('type') != expected.get('type')
                or header.get('md5sum') != expected.get('md5sum')
                or header.get('callerid') != expected.get('callerid')
                or header.get('latching')
                != ('1' if expected.get('latching') else '0')):
            failures.append('raw_index_connection_or_message_invalid')
            continue
        by_id[connection_id] = topic
        by_role[role] = topic
    if set(by_role) != set(ALL_ROLES):
        failures.append('raw_index_manifest_mismatch')
    return by_id, by_role


def _validate_messages(index_report, by_connection, manifest, failures):
    messages = index_report.get('messages')
    if not isinstance(messages, list) or not messages:
        failures.append('raw_index_connection_or_message_invalid')
        return {}, {role: [] for role in ALL_ROLES}
    by_id = {}
    by_role = {role: [] for role in ALL_ROLES}
    counts = {connection_id: 0 for connection_id in by_connection}
    first = {}
    last = {}
    previous_record = {}
    expected_keys = {
        'message_id', 'connection_id', 'topic', 'role', 'callerid',
        'record_timestamp_ns', 'serialized_size_bytes', 'serialized_sha256',
        'record_header_skew_sec', 'decoded', 'connection_header',
        'connection_header_sha256'}
    max_skew = manifest.get('max_record_header_skew_sec') if isinstance(
        manifest, Mapping) else None
    for ordinal, message in enumerate(messages, 1):
        if not _strict_keys(message, expected_keys):
            failures.append('raw_index_connection_or_message_invalid')
            continue
        connection = by_connection.get(message.get('connection_id'))
        message_id = message.get('message_id')
        record_stamp = message.get('record_timestamp_ns')
        role = message.get('role')
        if (connection is None or message_id != ordinal or message_id in by_id
                or message.get('topic') != connection.get('topic')
                or role != connection.get('role')
                or message.get('callerid') != connection.get('callerid')
                or not _integer(record_stamp, 1)
                or (message.get('connection_id') in previous_record
                    and record_stamp <= previous_record[
                        message.get('connection_id')])
                or not _integer(message.get('serialized_size_bytes'), 1)
                or not _lower_sha256(message.get('serialized_sha256'))
                or message.get('connection_header')
                != connection.get('connection_header')
                or message.get('connection_header_sha256')
                != connection.get('connection_header_sha256')):
            failures.append('raw_index_connection_or_message_invalid')
            continue
        decoded = message.get('decoded')
        if role in ('rgb', 'raw_depth'):
            valid_payload = _validate_image(decoded, role, failures)
        elif role in ('rgb_camera_info', 'depth_camera_info'):
            valid_payload = _validate_camera_info(decoded, failures)
        else:
            valid_payload = _validate_tf(
                decoded, role == 'tf_static', failures)
        skew = message.get('record_header_skew_sec')
        if (not _finite(skew, 0.0)
                or role != 'tf_static'
                and (not _finite(max_skew, 0.0) or skew > max_skew)):
            valid_payload = False
            failures.append('raw_index_connection_or_message_invalid')
        if not valid_payload:
            continue
        connection_id = message['connection_id']
        previous_record[connection_id] = record_stamp
        counts[connection_id] += 1
        first.setdefault(connection_id, record_stamp)
        last[connection_id] = record_stamp
        by_id[message_id] = message
        by_role[role].append(message)
    for connection_id, connection in by_connection.items():
        if (counts.get(connection_id) != connection.get('message_count')
                or first.get(connection_id)
                != connection.get('first_record_timestamp_ns')
                or last.get(connection_id)
                != connection.get('last_record_timestamp_ns')):
            failures.append('raw_index_connection_or_message_invalid')
    return by_id, by_role


def _expected_stream_summary(role, messages):
    first_decoded = messages[0]['decoded']
    stamps = [item['decoded']['header']['stamp_ns'] for item in messages]
    result = {
        'topic': messages[0]['topic'],
        'message_type': (
            'sensor_msgs/Image' if role in ('rgb', 'raw_depth')
            else 'sensor_msgs/CameraInfo'),
        'message_count': len(messages),
        'frame_id': first_decoded['header']['frame_id'],
        'width': first_decoded['width'],
        'height': first_decoded['height'],
        'first_stamp_ns': stamps[0],
        'last_stamp_ns': stamps[-1],
    }
    if role in ('rgb', 'raw_depth'):
        result['encoding'] = first_decoded['encoding']
    else:
        result['calibration_sha256'] = _calibration_sha256(first_decoded)
        result['intrinsics'] = dict(first_decoded['intrinsics'])
    return result


def _validate_streams(index_report, by_role, failures):
    streams = index_report.get('streams')
    if not isinstance(streams, Mapping) or set(streams) != set(STREAM_ROLES):
        failures.append('raw_index_connection_or_message_invalid')
        return {}
    expected = {}
    for role in STREAM_ROLES:
        values = by_role.get(role, [])
        if not values:
            failures.append('raw_index_connection_or_message_invalid')
            continue
        stamps = [item['decoded']['header']['stamp_ns'] for item in values]
        if any(current <= previous for previous, current in zip(
                stamps, stamps[1:])):
            failures.append('raw_index_connection_or_message_invalid')
        frames = {item['decoded']['header']['frame_id'] for item in values}
        grids = {(item['decoded']['width'], item['decoded']['height'])
                 for item in values}
        if len(frames) != 1 or len(grids) != 1:
            failures.append('raw_index_connection_or_message_invalid')
        if role in ('rgb', 'raw_depth'):
            if len({item['decoded']['encoding'] for item in values}) != 1:
                failures.append('raw_index_connection_or_message_invalid')
        else:
            if len({_calibration_sha256(item['decoded'])
                    for item in values}) != 1:
                failures.append('raw_index_connection_or_message_invalid')
        expected[role] = _expected_stream_summary(role, values)
        if streams.get(role) != expected[role]:
            failures.append('raw_index_connection_or_message_invalid')
    for image_role, info_role in (
            ('rgb', 'rgb_camera_info'),
            ('raw_depth', 'depth_camera_info')):
        image = expected.get(image_role, {})
        info = expected.get(info_role, {})
        if (image.get('frame_id') != info.get('frame_id')
                or (image.get('width'), image.get('height'))
                != (info.get('width'), info.get('height'))):
            failures.append('raw_index_connection_or_message_invalid')
    return expected


def _bundle_from_messages(bundle, by_message, failures):
    expected_keys = {
        'index', *STREAM_ROLES, 'header_stamps_ns',
        'stream_payload_sha256', 'stream_serialized_size_bytes',
        'stream_record_timestamps_ns', 'record_timestamp_span_sec',
        'stamp_span_sec'}
    if not _strict_keys(bundle, expected_keys):
        failures.append('raw_index_bundle_invalid')
        return None
    selected = {}
    for role in STREAM_ROLES:
        message = by_message.get(bundle.get(role))
        if message is None or message.get('role') != role:
            failures.append('raw_index_bundle_invalid')
            return None
        selected[role] = message
    header_stamps = {
        role: selected[role]['decoded']['header']['stamp_ns']
        for role in STREAM_ROLES}
    payload_hashes = {
        role: selected[role]['serialized_sha256'] for role in STREAM_ROLES}
    sizes = {
        role: selected[role]['serialized_size_bytes'] for role in STREAM_ROLES}
    record_stamps = {
        role: selected[role]['record_timestamp_ns'] for role in STREAM_ROLES}
    stamp_span = (
        max(header_stamps.values()) - min(header_stamps.values())) / 1e9
    record_span = (
        max(record_stamps.values()) - min(record_stamps.values())) / 1e9
    if (bundle.get('header_stamps_ns') != header_stamps
            or bundle.get('stream_payload_sha256') != payload_hashes
            or bundle.get('stream_serialized_size_bytes') != sizes
            or bundle.get('stream_record_timestamps_ns') != record_stamps
            or not _finite(bundle.get('stamp_span_sec'), 0.0)
            or abs(bundle['stamp_span_sec'] - stamp_span) > 1e-9
            or not _finite(bundle.get('record_timestamp_span_sec'), 0.0)
            or abs(bundle['record_timestamp_span_sec'] - record_span) > 1e-9
            or stamp_span > MAX_SYNC_SPAN_SEC
            or record_span > MAX_SYNC_SPAN_SEC):
        failures.append('raw_index_bundle_invalid')
        return None
    return {
        'bundle': bundle,
        'messages': selected,
        'header_stamps_ns': header_stamps,
        'stream_payload_sha256': payload_hashes,
    }


def _validate_bundles(index_report, by_message, by_role, failures):
    bundles = index_report.get('accepted_bundles')
    if not isinstance(bundles, list) or not bundles:
        failures.append('raw_index_bundle_invalid')
        return []
    validated = []
    used = {role: set() for role in STREAM_ROLES}
    rgb_stamps = set()
    for ordinal, bundle in enumerate(bundles):
        value = _bundle_from_messages(bundle, by_message, failures)
        if value is None:
            continue
        if bundle.get('index') != ordinal:
            failures.append('raw_index_bundle_invalid')
            continue
        stamp = value['header_stamps_ns']['rgb']
        if stamp in rgb_stamps:
            failures.append('raw_index_bundle_invalid')
            continue
        duplicate = False
        for role in STREAM_ROLES:
            message_id = bundle[role]
            if message_id in used[role]:
                duplicate = True
            used[role].add(message_id)
        if duplicate:
            failures.append('raw_index_bundle_invalid')
            continue
        rgb_stamps.add(stamp)
        validated.append(value)

    accepted = len(validated)
    total = sum(len(by_role.get(role, [])) for role in STREAM_ROLES)
    unmatched = {
        role: len(by_role.get(role, [])) - accepted for role in STREAM_ROLES}
    unpaired = total - accepted * len(STREAM_ROLES)
    unpaired_rate = unpaired / total if total else None
    expected = {
        'rgb_candidate_count': len(by_role.get('rgb', [])),
        'accepted_bundle_count': accepted,
        'rejected_rgb_count': len(by_role.get('rgb', [])) - accepted,
        'unmatched_message_count_by_stream': unmatched,
        'total_stream_message_count': total,
        'total_unpaired_message_count': unpaired,
        'total_unpaired_rate': unpaired_rate,
        'unique_header_pair_count': accepted,
        'formal_contract_valid_pair_count': accepted,
    }
    for key, value in expected.items():
        actual = index_report.get(key)
        if isinstance(value, float):
            equal = _finite(actual) and abs(actual - value) <= 1e-12
        else:
            equal = actual == value
        if not equal:
            failures.append('raw_index_bundle_invalid')
    rejection = index_report.get('rejection_reasons')
    if (not _strict_keys(rejection, {'missing_stream', 'over_sync_span'})
            or not all(_integer(rejection[key], 0) for key in rejection)
            or sum(rejection.values()) != expected['rejected_rgb_count']):
        failures.append('raw_index_bundle_invalid')
    if (accepted < MIN_SCENE_FRAMES or unpaired_rate is None
            or unpaired_rate > MAX_UNPAIRED_RATE):
        failures.append('raw_index_bundle_invalid')
    return validated


def _validate_tf_graph(index_report, by_message, streams, failures):
    graph = index_report.get('tf_graph')
    expected_keys = {
        'camera_only', 'base_chain_required', 'rgb_frame',
        'raw_depth_frame', 'transform_count', 'dynamic_child_frames',
        'static_child_frames', 'child_owners', 'transforms'}
    if not _strict_keys(graph, expected_keys):
        failures.append('raw_index_connection_or_message_invalid')
        return
    transforms = []
    owners = {}
    dynamic = set()
    static = set()
    for message_id in sorted(by_message):
        message = by_message[message_id]
        role = message['role']
        if role not in TF_ROLES:
            continue
        for index, transform in enumerate(message['decoded']['transforms']):
            parent = transform['header']['frame_id']
            child = transform['child_frame_id']
            owner = {'parent_frame_id': parent, 'callerid': message['callerid']}
            if child in owners and owners[child] != owner:
                failures.append('raw_index_shared_or_mixed')
            owners[child] = owner
            (static if role == 'tf_static' else dynamic).add(child)
            transforms.append({
                'topic': message['topic'],
                'message_id': message_id,
                'connection_id': message['connection_id'],
                'transform_index': index,
                'callerid': message['callerid'],
                'stamp_ns': transform['header']['stamp_ns'],
                'parent_frame_id': parent,
                'child_frame_id': child,
                'translation_m': transform['translation_m'],
                'rotation_xyzw': transform['rotation_xyzw'],
                'serialized_sha256': message['serialized_sha256'],
            })
    expected = {
        'camera_only': True,
        'base_chain_required': False,
        'rgb_frame': streams.get('rgb', {}).get('frame_id'),
        'raw_depth_frame': streams.get('raw_depth', {}).get('frame_id'),
        'transform_count': len(transforms),
        'dynamic_child_frames': sorted(dynamic),
        'static_child_frames': sorted(static),
        'child_owners': {key: owners[key] for key in sorted(owners)},
        'transforms': transforms,
    }
    if graph != expected or dynamic.intersection(static):
        failures.append('raw_index_connection_or_message_invalid')
    if not transforms:
        failures.append('raw_index_connection_or_message_invalid')


def _identity_path_matches(declaration, identity) -> bool:
    if not _identity_matches(declaration, identity):
        return False
    try:
        return (Path(declaration['path']).resolve(strict=True)
                == Path(identity['path']).resolve(strict=True))
    except (OSError, RuntimeError, KeyError, TypeError):
        return False


def _validate_formal_artifacts_and_redecode(
        index_report, context, failures):
    """Bind the stored index to a second decode of the exact raw bag."""
    identities = {}
    if not isinstance(context, Mapping):
        failures.append('raw_index_artifact_identity_mismatch')
        return identities, {}
    for key in ('index_path', 'raw_bag_path', 'frames_path', 'collector_path'):
        path = context.get(key)
        if path is None:
            failures.append('raw_index_artifact_identity_mismatch')
            continue
        try:
            identities[key] = _artifact_identity(Path(path))
        except (OSError, RuntimeError, ValueError):
            failures.append('raw_index_artifact_identity_mismatch')
    index_path = context.get('index_path')
    if index_path is not None:
        try:
            if _load_json(Path(index_path)) != index_report:
                failures.append('raw_index_stored_content_mismatch')
        except (OSError, RuntimeError, UnicodeError, ValueError,
                json.JSONDecodeError):
            failures.append('raw_index_stored_content_mismatch')
    raw_identity = identities.get('raw_bag_path')
    if (raw_identity is None
            or not _identity_path_matches(
                index_report.get('source_capture'), raw_identity)):
        failures.append('raw_index_source_capture_mismatch')

    manifest = {}
    try:
        from limo_cleanup_ros1_perception import rosbag1_rgbd_indexer
        source_identity = _artifact_identity(Path(
            rosbag1_rgbd_indexer.__file__))
        if not _identity_path_matches(
                index_report.get('indexer_source'), source_identity):
            failures.append('raw_index_artifact_identity_mismatch')
        if (getattr(rosbag1_rgbd_indexer, 'FORMAL_ACCEPTANCE_MODE', None)
                != 'formal_scene_raw_capture'
                or getattr(
                    rosbag1_rgbd_indexer, 'FORMAL_CAMERA_ONLY_MODE', None)
                != 'formal_camera_only'
                or not callable(getattr(
                    rosbag1_rgbd_indexer, 'load_formal_manifest', None))
                or not callable(getattr(
                    rosbag1_rgbd_indexer, 'inspect_bag', None))):
            failures.append('raw_index_formal_redecode_api_unavailable')
            return identities, manifest
        manifest = rosbag1_rgbd_indexer.load_formal_manifest(
            context.get('topic_manifest_path'))
        manifest_identity = {
            key: manifest[key] for key in (
                'path', 'size_bytes', 'sha256', 'manifest_id',
                'schema_version')}
        declaration = index_report.get('expected_topic_manifest')
        if (not isinstance(declaration, Mapping)
                or set(declaration) != set(manifest_identity)
                or any(declaration.get(key) != value
                       for key, value in manifest_identity.items())
                or Path(declaration['path']).resolve(strict=True)
                != Path(manifest_identity['path']).resolve(strict=True)):
            failures.append('raw_index_manifest_mismatch')
        identities['topic_manifest'] = manifest_identity
        if raw_identity is None:
            failures.append('raw_index_formal_redecode_failed')
            return identities, manifest
        redecoded = rosbag1_rgbd_indexer.inspect_bag(
            raw_identity['path'],
            capture_id=index_report.get('capture_id'),
            scene=index_report.get('scene'),
            manifest_path=manifest_identity['path'],
            mode=rosbag1_rgbd_indexer.FORMAL_CAMERA_ONLY_MODE)
        if (not isinstance(redecoded, Mapping)
                or redecoded.get('inspection_passed') is not True
                or redecoded.get('formal_acceptance') is not True
                or redecoded.get('failures') != []):
            failures.append('raw_index_formal_redecode_failed')
        if redecoded != index_report:
            failures.append('raw_index_redecode_mismatch')
    except (ImportError, OSError, RuntimeError, ValueError, KeyError,
            TypeError):
        failures.append('raw_index_formal_redecode_api_unavailable')
    return identities, manifest


def _validate_formal_topics(index_report, manifest, failures):
    topics = index_report.get('topics')
    expected_roles = manifest.get('topics_by_role', {}) if isinstance(
        manifest, Mapping) else {}
    if (not isinstance(topics, list) or len(topics) != len(ALL_ROLES)
            or set(expected_roles) != set(ALL_ROLES)):
        failures.append('raw_index_manifest_mismatch')
        return {}, {}
    by_id = {}
    by_role = {}
    for topic in topics:
        if not _strict_keys(topic, FORMAL_TOPIC_KEYS):
            failures.append('raw_index_connection_or_message_invalid')
            continue
        role = topic.get('role')
        expected = expected_roles.get(role)
        connection_id = topic.get('connection_id')
        header = topic.get('connection_header')
        header_hash = topic.get('connection_header_sha256')
        valid = (
            expected is not None and role not in by_role
            and _integer(connection_id, 0) and connection_id not in by_id
            and topic.get('topic') == expected.get('name')
            and topic.get('type') == expected.get('type')
            and topic.get('md5sum') == expected.get('md5sum')
            and topic.get('callerid') == expected.get('callerid')
            and topic.get('latching') is expected.get('latching')
            and _integer(topic.get('message_count'), 1)
            and _integer(topic.get('first_record_timestamp_ns'), 1)
            and _integer(topic.get('last_record_timestamp_ns'), 1)
            and topic['last_record_timestamp_ns']
            >= topic['first_record_timestamp_ns']
            and isinstance(header, Mapping) and _lower_sha256(header_hash)
            and _canonical_sha256(header) == header_hash
            and header.get('topic') == expected.get('name')
            and header.get('type') == expected.get('type')
            and header.get('md5sum') == expected.get('md5sum')
            and header.get('callerid') == expected.get('callerid')
            and header.get('latching')
            == ('1' if expected.get('latching') else '0')
            and topic.get('formal_valid') is True
            and topic.get('validation_failures') == [])
        if not valid:
            failures.append('raw_index_connection_or_message_invalid')
            continue
        by_id[connection_id] = topic
        by_role[role] = topic
    if set(by_role) != set(ALL_ROLES):
        failures.append('raw_index_manifest_mismatch')
    return by_id, by_role


def _validate_isolated_camera_info(decoded) -> bool:
    base_keys = {
        'header', 'height', 'width', 'distortion_model', 'D', 'K', 'R',
        'P', 'binning_x', 'binning_y', 'roi'}
    header = decoded.get('header') if isinstance(decoded, Mapping) else None
    roi_keys = {'x_offset', 'y_offset', 'height', 'width', 'do_rectify'}
    intrinsics_keys = {'fx', 'fy', 'cx', 'cy'}
    if (not isinstance(decoded, Mapping)
            or set(decoded) not in (base_keys, base_keys | {'intrinsics'})
            or not _strict_keys(header, {'stamp_ns', 'frame_id'})
            or not _integer(header.get('stamp_ns'), 1)
            or not isinstance(header.get('frame_id'), str)
            or '\x00' in header.get('frame_id')
            or not _integer(decoded.get('height'), 1)
            or not _integer(decoded.get('width'), 1)
            or not _valid_text(decoded.get('distortion_model'))
            or not _finite_array(decoded.get('D'))
            or not _finite_array(decoded.get('K'), 9)
            or not _finite_array(decoded.get('R'), 9)
            or not _finite_array(decoded.get('P'), 12)
            or not _integer(decoded.get('binning_x'), 0)
            or not _integer(decoded.get('binning_y'), 0)
            or not _strict_keys(decoded.get('roi'), roi_keys)):
        return False
    width = decoded['width']
    height = decoded['height']
    matrix = decoded['K']
    projection = decoded['P']
    roi = decoded['roi']
    intrinsics = decoded.get('intrinsics', {
        'fx': matrix[0], 'fy': matrix[4],
        'cx': matrix[2], 'cy': matrix[5]})
    return (
        _strict_keys(intrinsics, intrinsics_keys)
        and all(_finite(intrinsics[key]) for key in intrinsics_keys)
        and intrinsics == {
            'fx': matrix[0], 'fy': matrix[4],
            'cx': matrix[2], 'cy': matrix[5]}
        and matrix[0] > 0.0 and matrix[4] > 0.0
        and projection[0] > 0.0 and projection[5] > 0.0
        and 0.0 <= matrix[2] < width and 0.0 <= matrix[5] < height
        and 0.0 <= projection[2] < width
        and 0.0 <= projection[6] < height
        and all(_integer(roi.get(key), 0)
                for key in ('x_offset', 'y_offset', 'height', 'width'))
        and isinstance(roi.get('do_rectify'), bool)
        and roi['x_offset'] + roi['width'] <= width
        and roi['y_offset'] + roi['height'] <= height)


def _validate_formal_messages(
        index_report, by_connection, manifest, failures):
    messages = index_report.get('messages')
    if not isinstance(messages, list) or not messages:
        failures.append('raw_index_connection_or_message_invalid')
        return {}, {role: [] for role in ALL_ROLES}, {}
    by_id = {}
    admitted_by_role = {role: [] for role in ALL_ROLES}
    isolated_by_id = {}
    counts = {connection_id: 0 for connection_id in by_connection}
    first = {}
    last = {}
    previous_record = {}
    allowed_isolated = set(manifest.get(
        'capture_window_policy', {}).get('allowed_isolated_roles', []))
    max_skew = manifest.get('max_record_header_skew_sec')
    for ordinal, message in enumerate(messages, 1):
        if not _strict_keys(message, FORMAL_MESSAGE_KEYS):
            failures.append('raw_index_connection_or_message_invalid')
            continue
        connection_id = message.get('connection_id')
        connection = by_connection.get(connection_id)
        message_id = message.get('message_id')
        role = message.get('role')
        record_stamp = message.get('record_timestamp_ns')
        isolated = message.get('isolated')
        basic_valid = (
            connection is not None and message_id == ordinal
            and message_id not in by_id
            and message.get('topic') == connection.get('topic')
            and role == connection.get('role')
            and message.get('callerid') == connection.get('callerid')
            and _integer(record_stamp, 1)
            and (connection_id not in previous_record
                 or record_stamp > previous_record[connection_id])
            and _integer(message.get('serialized_size_bytes'), 1)
            and _lower_sha256(message.get('serialized_sha256'))
            and message.get('connection_header')
            == connection.get('connection_header')
            and message.get('connection_header_sha256')
            == connection.get('connection_header_sha256')
            and isinstance(isolated, bool)
            and isinstance(message.get('formal_valid'), bool)
            and message.get('validation_failures') == [])
        if not basic_valid:
            failures.append('raw_index_connection_or_message_invalid')
            continue
        decoded = message.get('decoded')
        if isolated:
            payload_valid = (
                role in allowed_isolated
                and message.get('isolation_reason')
                == 'old_latched_camera_info_before_capture_window'
                and message.get('formal_valid') is False
                and message.get('record_header_skew_sec') is None
                and _validate_isolated_camera_info(decoded))
        else:
            if role in ('rgb', 'raw_depth'):
                payload_valid = _validate_image(decoded, role, failures)
            elif role in ('rgb_camera_info', 'depth_camera_info'):
                payload_valid = _validate_camera_info(decoded, failures)
            else:
                payload_valid = _validate_tf(
                    decoded, role == 'tf_static', failures)
            skew = message.get('record_header_skew_sec')
            skew_valid = (
                _finite(skew, 0.0)
                and (role == 'tf_static'
                     or (_finite(max_skew, 0.0) and skew <= max_skew)))
            payload_valid = (
                payload_valid and skew_valid
                and message.get('isolation_reason') is None
                and message.get('formal_valid') is True)
        if not payload_valid:
            failures.append('raw_index_connection_or_message_invalid')
            continue
        previous_record[connection_id] = record_stamp
        counts[connection_id] += 1
        first.setdefault(connection_id, record_stamp)
        last[connection_id] = record_stamp
        by_id[message_id] = message
        if isolated:
            isolated_by_id[message_id] = message
        else:
            admitted_by_role[role].append(message)
    for connection_id, connection in by_connection.items():
        if (counts.get(connection_id) != connection.get('message_count')
                or first.get(connection_id)
                != connection.get('first_record_timestamp_ns')
                or last.get(connection_id)
                != connection.get('last_record_timestamp_ns')):
            failures.append('raw_index_connection_or_message_invalid')
    return by_id, admitted_by_role, isolated_by_id


def _validate_formal_capture_window(
        index_report, admitted_by_role, failures):
    window = index_report.get('capture_window')
    header_stamps = []
    record_stamps = []
    for role in ('rgb', 'raw_depth'):
        for message in admitted_by_role.get(role, []):
            header_stamps.append(message['decoded']['header']['stamp_ns'])
            record_stamps.append(message['record_timestamp_ns'])
    expected = ({
        'header_start_ns': min(header_stamps),
        'header_end_ns': max(header_stamps),
        'record_start_ns': min(record_stamps),
        'record_end_ns': max(record_stamps),
    } if header_stamps and record_stamps else None)
    if (expected is None or not _strict_keys(window, CAPTURE_WINDOW_KEYS)
            or window != expected):
        failures.append('raw_index_capture_window_invalid')
        return expected or {}
    return expected


def _validate_formal_accounting_and_isolation(
        index_report, by_message, isolated_by_id, capture_window,
        manifest, failures):
    source_by_role = {role: 0 for role in ALL_ROLES}
    admitted_by_role = {role: 0 for role in ALL_ROLES}
    isolated_by_role = {role: 0 for role in ALL_ROLES}
    for message in by_message.values():
        role = message.get('role')
        if role not in source_by_role:
            failures.append('raw_index_message_accounting_invalid')
            continue
        source_by_role[role] += 1
        if message.get('isolated') is True:
            isolated_by_role[role] += 1
        else:
            admitted_by_role[role] += 1
    expected_accounting = {
        'source_message_count': len(by_message),
        'admitted_message_count': len(by_message) - len(isolated_by_id),
        'isolated_message_count': len(isolated_by_id),
        'source_message_count_by_role': source_by_role,
        'admitted_message_count_by_role': admitted_by_role,
        'isolated_message_count_by_role': isolated_by_role,
        'closure_valid': True,
    }
    accounting = index_report.get('message_accounting')
    if (not _strict_keys(accounting, MESSAGE_ACCOUNTING_KEYS)
            or accounting != expected_accounting
            or any(source_by_role[role]
                   != admitted_by_role[role] + isolated_by_role[role]
                   for role in ALL_ROLES)):
        failures.append('raw_index_message_accounting_invalid')

    ledger = index_report.get('isolated_old_latched_camera_info')
    if (not isinstance(ledger, list)
            or index_report.get('isolated_old_latched_camera_info_count')
            != len(ledger)):
        failures.append('raw_index_isolation_ledger_invalid')
        ledger = []
    ledger_by_id = {}
    allowed_roles = set(manifest.get(
        'capture_window_policy', {}).get('allowed_isolated_roles', []))
    maximum = manifest.get(
        'capture_window_policy', {}).get(
            'max_isolated_messages_per_role')
    for entry in ledger:
        if (not _strict_keys(entry, ISOLATED_LEDGER_KEYS)
                or entry.get('message_id') in ledger_by_id):
            failures.append('raw_index_isolation_ledger_invalid')
            continue
        message = isolated_by_id.get(entry.get('message_id'))
        decoded = message.get('decoded') if isinstance(message, Mapping) else {}
        header = decoded.get('header') if isinstance(decoded, Mapping) else {}
        expected = ({
            'message_id': message['message_id'],
            'connection_id': message['connection_id'],
            'topic': message['topic'],
            'role': message['role'],
            'callerid': message['callerid'],
            'record_timestamp_ns': message['record_timestamp_ns'],
            'header_stamp_ns': header.get('stamp_ns'),
            'frame_id': header.get('frame_id'),
            'serialized_size_bytes': message['serialized_size_bytes'],
            'serialized_sha256': message['serialized_sha256'],
            'connection_header_sha256': message[
                'connection_header_sha256'],
            'reason': message['isolation_reason'],
        } if isinstance(message, Mapping) else None)
        if (expected is None or entry != expected
                or entry.get('role') not in allowed_roles
                or entry.get('reason')
                != 'old_latched_camera_info_before_capture_window'
                or not _integer(entry.get('header_stamp_ns'), 1)
                or not isinstance(entry.get('frame_id'), str)
                or not _lower_sha256(entry.get('serialized_sha256'))
                or not _lower_sha256(
                    entry.get('connection_header_sha256'))
                or not capture_window
                or entry['header_stamp_ns'] >= capture_window[
                    'header_start_ns'] - int(
                        manifest.get('max_sync_span_sec', 0.0) * 1e9)):
            failures.append('raw_index_isolation_ledger_invalid')
            continue
        ledger_by_id[entry['message_id']] = entry
    if set(ledger_by_id) != set(isolated_by_id):
        failures.append('raw_index_isolation_ledger_invalid')
    if (_integer(maximum, 0)
            and any(isolated_by_role[role] > maximum
                    for role in allowed_roles)):
        failures.append('raw_index_isolation_ledger_invalid')
    if index_report.get('failure_details') != []:
        failures.append('raw_index_isolation_ledger_invalid')


def _validate_formal_alignment(
        index_report, streams, bundle_count, failures):
    frames = {streams.get(role, {}).get('frame_id')
              for role in STREAM_ROLES}
    grids = {(streams.get(role, {}).get('width'),
              streams.get(role, {}).get('height'))
             for role in STREAM_ROLES}
    if len(frames) != 1 or len(grids) != 1 or None in frames:
        failures.append('raw_index_stream_alignment_invalid')
        return
    frame_id = next(iter(frames))
    width, height = next(iter(grids))
    expected = {
        'required': True,
        'frame_id': frame_id,
        'width': width,
        'height': height,
        'validated_bundle_count': bundle_count,
    }
    if (not _strict_keys(
            index_report.get('aligned_stream_contract'),
            ALIGNED_STREAM_CONTRACT_KEYS)
            or index_report.get('aligned_stream_contract') != expected):
        failures.append('raw_index_stream_alignment_invalid')


def _validate_formal_index(index_report, artifact_context, failures):
    if (not isinstance(index_report, Mapping)
            or set(index_report) != FORMAL_INDEX_SUCCESS_KEYS):
        failures.append('raw_index_schema_invalid')
    failures.extend(_formal_policy_failures(index_report))
    if (not isinstance(index_report, Mapping)
            or index_report.get('schema_version') != 1
            or index_report.get('storage_identifier') != 'rosbag1-v2'
            or index_report.get('timestamp_semantics') != {
                'record_timestamp': 'rosbag1_recorder_receive_time',
                'pairing_and_sync': 'decoded_ros_header_stamp'}
            or not _valid_text(index_report.get('capture_id'))
            or index_report.get('scene') not in SCENES
            or index_report.get('failures') != []
            or not isinstance(index_report.get('failure_details'), list)
            or index_report.get('limitations') != [
                'formal_raw_capture_only_not_delivery',
                'base_to_camera_extrinsics_not_evaluated',
                'does_not_authorize_motion']):
        failures.append('raw_index_schema_invalid')
    identities, manifest = _validate_formal_artifacts_and_redecode(
        index_report, artifact_context, failures)
    expected_topics = {
        role: manifest.get('topics_by_role', {}).get(role, {}).get('name')
        for role in STREAM_ROLES}
    if index_report.get('stream_topics') != expected_topics:
        failures.append('raw_index_manifest_mismatch')
    by_connection, _ = _validate_formal_topics(
        index_report, manifest, failures)
    by_message, admitted_by_role, isolated_by_id = (
        _validate_formal_messages(
            index_report, by_connection, manifest, failures))
    stored_bundle_message_ids = {
        bundle.get(role)
        for bundle in index_report.get('accepted_bundles', [])
        if isinstance(bundle, Mapping)
        for role in STREAM_ROLES}
    if set(isolated_by_id).intersection(stored_bundle_message_ids):
        failures.append('raw_index_isolated_message_in_bundle')
    capture_window = _validate_formal_capture_window(
        index_report, admitted_by_role, failures)
    _validate_formal_accounting_and_isolation(
        index_report, by_message, isolated_by_id, capture_window,
        manifest, failures)
    streams = _validate_streams(
        index_report, admitted_by_role, failures)
    admitted_by_message = {
        message['message_id']: message
        for role in ALL_ROLES
        for message in admitted_by_role.get(role, [])}
    bundles = _validate_bundles(
        index_report, admitted_by_message, admitted_by_role, failures)
    isolated_ids = set(isolated_by_id)
    bundle_ids = [
        bundle['bundle'][role]
        for bundle in bundles for role in STREAM_ROLES]
    header_tuples = [tuple(
        bundle['header_stamps_ns'][role] for role in STREAM_ROLES)
        for bundle in bundles]
    minimum = manifest.get('min_accepted_bundles')
    if (not _integer(minimum, MIN_SCENE_FRAMES)
            or len(bundles) < minimum
            or len(header_tuples) != len(set(header_tuples))
            or isolated_ids.intersection(bundle_ids)
            or len(bundle_ids) != len(set(bundle_ids))):
        failures.append('raw_index_bundle_freshness_invalid')
    if capture_window:
        for bundle in bundles:
            if any(
                    stamp < capture_window['header_start_ns']
                    or stamp > capture_window['header_end_ns']
                    for stamp in bundle['header_stamps_ns'].values()):
                failures.append('raw_index_bundle_freshness_invalid')
                break
    _validate_formal_alignment(
        index_report, streams, len(bundles), failures)
    _validate_tf_graph(
        index_report, admitted_by_message, streams, failures)
    return bundles, identities, manifest


def _validate_index(index_report, artifact_context, failures):
    """Admit only the exact formal schema; retain legacy rows for diagnosis."""
    formal_candidate = (
        isinstance(index_report, Mapping)
        and (index_report.get('mode') == 'formal_camera_only'
             or index_report.get('report_kind')
             == 'formal_rgbd_raw_capture_index'
             or index_report.get('inspection_scope')
             == 'formal_scene_raw_capture'))
    if formal_candidate:
        formal_bundles, identities, manifest = _validate_formal_index(
            index_report, artifact_context, failures)
        if formal_bundles:
            return formal_bundles, identities, manifest
        # Historical tests and diagnostic tooling may still need association
        # counts from the short-sample schema.  That derivation is explicitly
        # non-admissible and can never clear the formal-schema failure above.
        legacy_failures = []
        legacy_bundles, legacy_identities, legacy_manifest = (
            _validate_legacy_index(
                index_report, artifact_context, legacy_failures))
        if legacy_bundles:
            failures.append('raw_index_formal_schema_required')
            return legacy_bundles, legacy_identities, legacy_manifest
        return formal_bundles, identities, manifest
    failures.append('raw_index_formal_schema_required')
    return _validate_legacy_index(index_report, artifact_context, failures)


def _validate_legacy_index(index_report, artifact_context, failures):
    failures.extend(_formal_policy_failures(index_report))
    if (not isinstance(index_report, Mapping)
            or set(index_report) != LEGACY_INDEX_SUCCESS_KEYS
            or index_report.get('schema_version') != 1
            or index_report.get('storage_identifier') != 'rosbag1-v2'
            or index_report.get('timestamp_semantics') != {
                'record_timestamp': 'rosbag1_recorder_receive_time',
                'pairing_and_sync': 'decoded_ros_header_stamp'}
            or not _valid_text(index_report.get('capture_id'))
            or index_report.get('scene') not in SCENES
            or index_report.get('failures') != []
            or not isinstance(index_report.get('limitations'), list)):
        failures.append('raw_index_schema_invalid')
        return [], {}, {}
    identities = _validate_index_artifacts(
        index_report, artifact_context, failures)
    manifest = None
    try:
        from limo_cleanup_ros1_perception.rosbag1_rgbd_indexer import (
            load_manifest)
        manifest = load_manifest(
            artifact_context.get('topic_manifest_path')
            if isinstance(artifact_context, Mapping) else None)
    except (ImportError, OSError, RuntimeError, ValueError):
        failures.append('raw_index_manifest_mismatch')
        manifest = {}
    expected_topics = {
        role: manifest.get('topics_by_role', {}).get(role, {}).get('name')
        for role in STREAM_ROLES}
    if index_report.get('stream_topics') != expected_topics:
        failures.append('raw_index_manifest_mismatch')
    by_connection, _ = _validate_topics(index_report, manifest, failures)
    by_message, by_role = _validate_messages(
        index_report, by_connection, manifest, failures)
    streams = _validate_streams(index_report, by_role, failures)
    bundles = _validate_bundles(
        index_report, by_message, by_role, failures)
    _validate_tf_graph(index_report, by_message, streams, failures)
    return bundles, identities, manifest


def _validate_collector(collector, frames, context, failures):
    if (not _strict_keys(collector, COLLECTOR_KEYS)
            or collector.get('schema_version') != 1
            or collector.get('collector_kind')
            != 'ros1_typed_frame_readonly'
            or collector.get('read_only') is not True
            or collector.get('authorizes_motion') is not False
            or collector.get('publishes_ros_messages') is not False
            or collector.get('scene') not in SCENES
            or collector.get('topic') != EXPECTED_FRAME_TOPIC
            or collector.get('message_type') != EXPECTED_FRAME_TYPE
            or not _valid_text(collector.get('task_id'))
            or not _integer(collector.get('max_frames'), MIN_SCENE_FRAMES)
            or not _finite(collector.get('duration_sec'), 0.0)
            or collector.get('duration_sec') <= 0.0
            or collector.get('received_frames') != len(frames)
            or collector.get('unique_frames') != len(frames)
            or collector.get('duplicate_sequences') != 0
            or collector.get('duplicate_bundle_ids') != 0
            or collector.get('serialization_errors') != 0
            or collector.get('interrupted') is not False
            or collector.get('completed_minimum') is not True
            or not isinstance(
                collector.get('completed_requested_frames'), bool)):
        failures.append('collector_manifest_invalid')
        return
    frames_identity = None
    if isinstance(context, Mapping) and context.get('frames_path') is not None:
        try:
            frames_identity = _artifact_identity(Path(context['frames_path']))
        except (OSError, RuntimeError, ValueError):
            pass
    declaration = collector.get('output')
    if (frames_identity is None
            or not _identity_matches(declaration, frames_identity)):
        failures.append('collector_output_identity_mismatch')
    else:
        try:
            if (Path(declaration['path']).resolve(strict=True)
                    != Path(frames_identity['path'])):
                failures.append('collector_output_identity_mismatch')
        except (OSError, RuntimeError):
            failures.append('collector_output_identity_mismatch')


def _point(value) -> bool:
    return (_strict_keys(value, {'x', 'y', 'z'})
            and all(_finite(value[key]) for key in ('x', 'y', 'z')))


def _validate_target(target, frame, rgb, seen_observations, failures):
    if not _strict_keys(target, TARGET_KEYS):
        failures.append('typed_frame_schema_invalid')
        return
    observation = target.get('observation_id')
    object_class = target.get('object_class')
    bbox = target.get('bbox')
    pixels = target.get('depth_valid_pixels')
    total = target.get('depth_total_pixels')
    ratio = target.get('depth_valid_ratio')
    valid = target.get('valid')
    actionable = target.get('actionable')
    schema_valid = (
        _valid_text(observation) and observation not in seen_observations
        and object_class in TARGET_CLASSES
        and _finite(target.get('confidence'), 0.0, 1.0)
        and isinstance(valid, bool) and isinstance(actionable, bool)
        and _valid_text(target.get('status'))
        and isinstance(target.get('error_code'), str)
        and _point(target.get('position')) and _point(target.get('size'))
        and isinstance(bbox, list) and len(bbox) == 4
        and all(_finite(item) for item in bbox)
        and 0.0 <= bbox[0] < bbox[2] <= rgb['width']
        and 0.0 <= bbox[1] < bbox[3] <= rgb['height']
        and _finite(target.get('depth_m'), 0.0)
        and _integer(pixels, 0) and _integer(total, 1) and pixels <= total
        and _finite(ratio, 0.0, 1.0)
        and abs(ratio - pixels / total) <= 1e-6
        and _valid_text(target.get('source'))
        and _valid_text(target.get('position_semantics')))
    if not schema_valid:
        failures.append('typed_frame_schema_invalid')
        return
    seen_observations.add(observation)
    if valid:
        position = target['position']
        if (target['depth_m'] <= 0.0 or pixels <= 0 or ratio <= 0.0
                or position['z'] <= 0.0 or target['error_code']):
            failures.append('typed_frame_schema_invalid')
    elif actionable:
        failures.append('typed_frame_schema_invalid')
    if actionable and (
            object_class != 'plastic_bottle'
            or target.get('status') != 'active'):
        failures.append('typed_frame_schema_invalid')
    if object_class == 'trash_bin' and actionable:
        failures.append('typed_frame_schema_invalid')
    if (frame.get('tf_target_frame') != frame.get('frame_id')
            and not frame.get('tf_transform_applied')
            and valid):
        failures.append('tf_transform_not_applied')
    try:
        from limo_cleanup_ros1_perception.ros1_adapter import (
            build_observation_id)
        expected = build_observation_id(
            _stamp_ns(frame['stamp']) / 1e9, frame['frame_id'], object_class,
            bbox, target['status'], frame['model_binding_sha256'])
        if observation != expected:
            failures.append('typed_frame_schema_invalid')
    except (ImportError, TypeError, ValueError, ZeroDivisionError):
        failures.append('typed_frame_schema_invalid')


def _bundle_identifier(raw_bundle, model_set_sha256):
    streams = []
    for role in STREAM_ROLES:
        decoded = raw_bundle['messages'][role]['decoded']
        streams.append({
            'name': ADAPTER_STREAM_NAMES[role],
            'stamp_sec': round(decoded['header']['stamp_ns'] / 1e9, 9),
            'frame_id': decoded['header']['frame_id'],
            'width': decoded['width'],
            'height': decoded['height'],
            'encoding': decoded.get('encoding', ''),
        })
    return _canonical_sha256({
        'streams': streams,
        'model_set_sha256': model_set_sha256,
    })


def _validate_frames(frames, bundles, collector, model_hash, failures):
    if (not isinstance(frames, Sequence)
            or isinstance(frames, (str, bytes)) or not frames):
        failures.append('typed_frame_schema_invalid')
        return []
    raw_by_stamp = {}
    for bundle in bundles:
        stamp = bundle['header_stamps_ns']['rgb']
        expected_bundle_id = _bundle_identifier(bundle, model_hash)
        raw_by_stamp[stamp] = (bundle, expected_bundle_id)
    seen_sequences = set()
    seen_bundle_ids = set()
    seen_observations = set()
    used_raw_stamps = set()
    associations = []
    previous_sequence = None
    previous_stamp = None
    for row_index, frame in enumerate(frames):
        if not _strict_keys(frame, FRAME_KEYS):
            failures.append('typed_frame_schema_invalid')
            continue
        stamp = _stamp_ns(frame.get('stamp'))
        sequence = frame.get('sequence')
        bundle_id = frame.get('bundle_id')
        received = frame.get('received_unix_sec')
        transport = frame.get('transport_latency_sec')
        schema_valid = (
            frame.get('schema_version') == 1
            and frame.get('read_only') is True
            and stamp is not None
            and _valid_frame_id(frame.get('frame_id'))
            and frame.get('task_id') == collector.get('task_id')
            and _valid_text(frame.get('capture_id'))
            and frame.get('scene') == collector.get('scene')
            and _lower_sha256(bundle_id)
            and frame.get('model_binding_sha256') == model_hash
            and _integer(sequence, 1) and sequence not in seen_sequences
            and (previous_sequence is None or sequence > previous_sequence)
            and (previous_stamp is None or stamp > previous_stamp)
            and bundle_id not in seen_bundle_ids
            and isinstance(frame.get('valid'), bool)
            and _valid_text(frame.get('status'))
            and isinstance(frame.get('error_code'), str)
            and _finite(frame.get('sync_span_sec'), 0.0, MAX_SYNC_SPAN_SEC)
            and _finite(frame.get('processing_latency_sec'), 0.0)
            and _finite(received, stamp / 1e9)
            and _finite(transport, 0.0)
            and abs(transport - (received - stamp / 1e9)) <= 1e-6
            and _valid_frame_id(frame.get('tf_target_frame'))
            and isinstance(frame.get('tf_valid'), bool)
            and isinstance(frame.get('tf_transform_applied'), bool)
            and _valid_text(frame.get('tf_status'))
            and isinstance(frame.get('tf_error_code'), str)
            and isinstance(frame.get('targets'), list))
        if not schema_valid:
            failures.append('typed_frame_schema_invalid')
            continue
        seen_sequences.add(sequence)
        seen_bundle_ids.add(bundle_id)
        previous_sequence = sequence
        previous_stamp = stamp
        raw = raw_by_stamp.get(stamp)
        if raw is None or stamp in used_raw_stamps:
            failures.append('typed_raw_not_one_to_one')
            continue
        raw_bundle, expected_bundle_id = raw
        if bundle_id != expected_bundle_id:
            failures.append('typed_bundle_id_mismatch')
            continue
        if abs(frame['sync_span_sec'] - raw_bundle[
                'bundle']['stamp_span_sec']) > 1e-6:
            failures.append('typed_raw_not_one_to_one')
            continue
        rgb = raw_bundle['messages']['rgb']['decoded']
        if frame['frame_id'] != rgb['header']['frame_id']:
            failures.append('typed_frame_schema_invalid')
            continue
        for target in frame['targets']:
            _validate_target(
                target, frame, rgb, seen_observations, failures)
        if (frame['tf_target_frame'] != frame['frame_id']
                and frame['tf_valid'] is True
                and frame['tf_transform_applied'] is not True):
            failures.append('tf_transform_not_applied')
        used_raw_stamps.add(stamp)
        associations.append({
            'typed_row_index': row_index,
            'sequence': sequence,
            'stamp_ns': stamp,
            'bundle_id': bundle_id,
            'typed_frame_sha256': _canonical_sha256(frame),
            'raw_bundle_index': raw_bundle['bundle']['index'],
            'raw_stream_payload_sha256': dict(
                raw_bundle['stream_payload_sha256']),
        })
    if len(associations) != len(frames) or len(associations) != len(bundles):
        failures.append('typed_raw_not_one_to_one')
    if len(associations) < MIN_SCENE_FRAMES:
        failures.append('typed_raw_frame_count_below_minimum')
    return associations


def _validate_source_and_models(context, failures, test_only):
    report = {
        'host_source_admission': None,
        'host_source_admission_validator': None,
        'model_manifest': None,
        'model_artifacts': {},
        'model_set_sha256': None,
    }
    if test_only:
        failures.append('synthetic_test_only_forbidden')
    if not isinstance(context, Mapping):
        failures.extend([
            'source_binding_missing', 'model_binding_missing'])
        return report
    workspace_root = context.get('workspace_root')
    source_admission_path = context.get('source_admission_path')
    if workspace_root is None or source_admission_path is None:
        failures.append('source_binding_missing')
    else:
        try:
            root = Path(workspace_root).resolve(strict=True)
            validator_path = (
                root / 'src' / 'limo_cleanup_perception'
                / 'limo_cleanup_perception'
                / 'ros1_source_core_admission.py')
            report['host_source_admission_validator'] = (
                _artifact_identity(validator_path))
            report['host_source_admission_evidence'] = (
                _artifact_identity(Path(source_admission_path)))
            evidence = _load_json(Path(source_admission_path))
            spec = importlib.util.spec_from_file_location(
                'limo_cleanup_host_source_admission',
                str(validator_path))
            if spec is None or spec.loader is None:
                raise ImportError('host source admission loader unavailable')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            source = module.validate_ros1_source_core_admission(root)
            report['host_source_admission'] = source
            if (not isinstance(evidence, Mapping) or evidence != source
                    or source.get('gate_id')
                    != 'ROS1_SOURCE_CORE_ADMISSION_V2'
                    or source.get('validated_pass') is not True
                    or source.get('package_validator_executed') is not False
                    or source.get('package_validator_return_value_trusted')
                    is not False):
                failures.append('source_binding_invalid')
        except (ImportError, OSError, RuntimeError, ValueError,
                json.JSONDecodeError):
            failures.append('source_binding_invalid')
    if (not isinstance(report.get('host_source_admission'), Mapping)
            or report['host_source_admission'].get(
                'validated_pass') is not True):
        failures.append('host_source_admission_not_validated')
    model_manifest = context.get('model_manifest_path')
    model_root = context.get('model_root')
    if model_manifest is None or model_root is None:
        failures.append('model_binding_missing')
        return report
    try:
        from limo_cleanup_ros1_perception.dual_model_detector import (
            load_model_bindings, model_set_sha256, resolve_model_artifacts)
        bindings, manifest_sha = load_model_bindings(Path(model_manifest))
        artifacts = resolve_model_artifacts(bindings, Path(model_root))
        report['model_manifest'] = {
            **_artifact_identity(Path(model_manifest)),
            'manifest_sha256': manifest_sha,
        }
        report['model_artifacts'] = {
            name: _artifact_identity(path)
            for name, path in sorted(artifacts.items())}
        report['model_set_sha256'] = model_set_sha256(bindings)
    except (ImportError, OSError, RuntimeError, ValueError, KeyError):
        failures.append('model_binding_invalid')
    failures.append('host_model_admission_not_validated')
    return report


def _empty_report(failures):
    return {
        'schema_version': 2,
        'report_kind': 'ros1_typed_raw_binding',
        'evidence_scope': 'formal_scene_rosbag1_typed_raw_binding',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'validated_pass': False,
        'formal_acceptance': False,
        'not_in_four_scene_denominator': True,
        'delivery_ready': False,
        'failures': sorted(set(failures)),
    }


def create_binding(
        index_report: Mapping, frame_records: Sequence[Mapping],
        collector_manifest: Mapping, max_stamp_delta_ns: int = 0,
        test_only: bool = False, artifact_context: Optional[Mapping] = None
        ) -> Mapping:
    """Recompute a deterministic typed/raw association report.

    ``test_only`` exists solely for pure algorithm fixtures.  It can never
    produce formal or delivery evidence.  Production admission additionally
    requires reopened raw/index/collector/frame artifacts, the canonical
    source-core binding, the frozen model manifest, and both model weights.
    """
    failures = []
    if (not _integer(max_stamp_delta_ns, 0)
            or max_stamp_delta_ns != 0):
        failures.append('stamp_tolerance_invalid')
    if not isinstance(test_only, bool):
        failures.append('synthetic_test_only_forbidden')
        test_only = True
    frames = (list(frame_records) if isinstance(frame_records, Sequence)
              and not isinstance(frame_records, (str, bytes)) else [])
    if not frames:
        failures.append('typed_frame_schema_invalid')
    if not isinstance(collector_manifest, Mapping):
        collector_manifest = {}
        failures.append('collector_manifest_invalid')
    provenance = _validate_source_and_models(
        artifact_context, failures, test_only)
    model_hash = provenance.get('model_set_sha256')
    if model_hash is None:
        hashes = {
            frame.get('model_binding_sha256') for frame in frames
            if isinstance(frame, Mapping)
            and _lower_sha256(frame.get('model_binding_sha256'))}
        model_hash = next(iter(hashes)) if len(hashes) == 1 else '0' * 64
    bundles, artifacts, _ = _validate_index(
        index_report, artifact_context, failures)
    _validate_collector(
        collector_manifest, frames, artifact_context, failures)
    associations = _validate_frames(
        frames, bundles, collector_manifest, model_hash, failures)

    capture_id = index_report.get('capture_id') if isinstance(
        index_report, Mapping) else None
    scene = index_report.get('scene') if isinstance(
        index_report, Mapping) else None
    task_id = collector_manifest.get('task_id')
    if any(
            isinstance(frame, Mapping)
            and (frame.get('capture_id') != capture_id
                 or frame.get('scene') != scene
                 or frame.get('task_id') != task_id)
            for frame in frames):
        failures.append('raw_index_source_capture_mismatch')
    failures = sorted(set(failures))
    formal = not failures
    envelope = {
        'capture_id': capture_id,
        'task_id': task_id,
        'scene': scene,
        'model_binding_sha256': model_hash,
        'artifacts': artifacts,
        'provenance': provenance,
        'typed_frame_count': len(frames),
        'raw_bundle_count': len(bundles),
        'association_count': len(associations),
        'minimum_scene_frames': MIN_SCENE_FRAMES,
        'unpaired_typed_count': len(frames) - len(associations),
        'unpaired_raw_bundle_count': len(bundles) - len(associations),
        'associations': associations,
        'test_only': test_only,
    }
    return {
        'schema_version': 2,
        'report_kind': 'ros1_typed_raw_binding',
        'evidence_scope': 'formal_scene_rosbag1_typed_raw_binding',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'binding_sha256': _canonical_sha256(envelope),
        **envelope,
        'validated_pass': formal,
        'formal_acceptance': formal,
        'not_in_four_scene_denominator': not formal,
        'delivery_ready': False,
        'failures': failures,
    }


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description=(
            'Bind ROS1 typed observations to immutable rosbag1 evidence.'))
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--frames', type=Path, required=True)
    parser.add_argument('--collector-manifest', type=Path, required=True)
    parser.add_argument('--raw-bag', type=Path, required=True)
    parser.add_argument('--workspace-root', type=Path, required=True)
    parser.add_argument('--source-admission', type=Path, required=True)
    parser.add_argument('--topic-manifest', type=Path)
    parser.add_argument('--model-manifest', type=Path, required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--test-only', action='store_true')
    return parser.parse_args(args)


def main(args=None):
    """Create one exclusive offline report; never starts ROS or hardware."""
    parsed = parse_args(args)
    input_paths = (
        parsed.index, parsed.frames, parsed.collector_manifest,
        parsed.raw_bag, parsed.source_admission,
        parsed.model_manifest)
    if parsed.output.exists():
        raise SystemExit('output path must not already exist')
    try:
        output_resolved = parsed.output.resolve()
        if any(output_resolved == path.resolve() for path in input_paths):
            raise SystemExit('output path must differ from every input')
        index_report = _load_json(parsed.index)
        frames = _load_jsonl(parsed.frames)
        collector = _load_json(parsed.collector_manifest)
        report = create_binding(
            index_report, frames, collector, test_only=parsed.test_only,
            artifact_context={
                'index_path': parsed.index,
                'frames_path': parsed.frames,
                'collector_path': parsed.collector_manifest,
                'raw_bag_path': parsed.raw_bag,
                'workspace_root': parsed.workspace_root,
                'source_admission_path': parsed.source_admission,
                'topic_manifest_path': parsed.topic_manifest,
                'model_manifest_path': parsed.model_manifest,
                'model_root': parsed.model_root,
            })
    except (OSError, RuntimeError, UnicodeError, ValueError,
            json.JSONDecodeError) as error:
        report = _empty_report([
            'binding_input_invalid', type(error).__name__])
    report['binding_source'] = _artifact_identity(Path(__file__))
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    with parsed.output.open('x', encoding='utf-8') as stream:
        json.dump(
            report, stream, ensure_ascii=False, indent=2,
            sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return 0 if report.get('formal_acceptance') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
