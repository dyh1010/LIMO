"""Decode and index one read-only rosbag2 RGB-D acceptance capture."""

import argparse
import hashlib
import json
import math
import os
import sqlite3
import struct
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


STREAM_NAMES = (
    'rgb',
    'aligned_depth',
    'rgb_camera_info',
    'depth_camera_info',
)
TF_TOPICS = ('/tf', '/tf_static')
SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
REQUIRED_TOPIC_COLUMNS = {
    'id', 'name', 'type', 'serialization_format', 'offered_qos_profiles'}
REQUIRED_MESSAGE_COLUMNS = {'id', 'topic_id', 'timestamp', 'data'}
EXPECTED_STREAM_TYPES = {
    'rgb': 'sensor_msgs/msg/Image',
    'aligned_depth': 'sensor_msgs/msg/Image',
    'rgb_camera_info': 'sensor_msgs/msg/CameraInfo',
    'depth_camera_info': 'sensor_msgs/msg/CameraInfo',
}
EXPECTED_TF_TYPE = 'tf2_msgs/msg/TFMessage'
MAX_SYNC_SPAN_SEC = 0.15
MAX_RECORD_HEADER_SKEW_SEC = 0.75
MAX_DYNAMIC_TF_AGE_SEC = 0.15
EXPECTED_TOPIC_MANIFEST_BASENAME = 'rgbd_expected_topics.json'
EXPECTED_TOPIC_MANIFEST_ID = 'limo-dabai-rgbd-six-topics-v1'
EXPECTED_TOPIC_MANIFEST_SHA256 = (
    '0e56197a7ca2bb01675d7894c79ff89fbcc2e45c5fad1c969ce97471c07dc8f4')
FORMAL_RAW_INSPECTION_POLICY = {
    'report_kind': 'formal_rgbd_raw_capture_index',
    'inspection_scope': 'formal_scene_raw_capture',
    'formal_acceptance': True,
    'shared_graph': False,
    'mixed_tf': False,
    'not_in_four_scene_denominator': False,
}
_ALLOWED_QOS_KEYS = {
    'history', 'depth', 'reliability', 'durability',
    'deadline', 'lifespan', 'liveliness', 'liveliness_lease_duration',
    'avoid_ros_namespace_conventions',
}
_REQUIRED_QOS_KEYS = {'history', 'depth', 'reliability', 'durability'}
MAX_UINT64 = (1 << 64) - 1
_FRAME_ID_SEGMENT_CHARS = frozenset(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-')
CONTROL_TOPIC_NAMES = {
    '/cmd_vel',
    '/cleanup/base/safe_cmd_vel',
    '/navigate_to_pose',
    '/move_base_simple/goal',
    '/arm_controller/joint_trajectory',
    '/gripper_controller/commands',
}
CONTROL_MESSAGE_TYPES = {
    'geometry_msgs/msg/Twist',
    'geometry_msgs/msg/TwistStamped',
    'geometry_msgs/msg/PoseStamped',
    'trajectory_msgs/msg/JointTrajectory',
    'control_msgs/action/FollowJointTrajectory',
    'control_msgs/action/GripperCommand',
    'nav2_msgs/action/NavigateToPose',
    'move_base_msgs/action/MoveBase',
    'limo_cleanup_interfaces/action/ExecuteArmMotion',
    'limo_cleanup_interfaces/action/ExecuteGripperMotion',
}


def sha256_file(path: Path) -> str:
    """Hash an evidence file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def default_topic_manifest_path() -> Path:
    """Locate the installed or source-tree frozen six-topic manifest."""
    candidates = []
    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(Path(get_package_share_directory(
            'limo_cleanup_perception')) / 'fixtures' /
            EXPECTED_TOPIC_MANIFEST_BASENAME)
    except (ImportError, LookupError, OSError):
        pass
    candidates.append(
        Path(__file__).resolve().parents[1] / 'fixtures' /
        EXPECTED_TOPIC_MANIFEST_BASENAME)
    executable = Path(sys.argv[0]).resolve()
    candidates.append(
        executable.parents[1] / 'share' / 'limo_cleanup_perception' /
        'fixtures' / EXPECTED_TOPIC_MANIFEST_BASENAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError('frozen expected-topic manifest is not installed')


def load_topic_manifest(path=None) -> Mapping:
    """Load and validate the immutable topic/type/QoS policy artifact."""
    candidate = default_topic_manifest_path() if path is None else Path(path)
    try:
        resolved = candidate.resolve(strict=True)
        payload = json.loads(resolved.read_text(encoding='utf-8'))
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('cannot load frozen expected-topic manifest') from error
    if not isinstance(payload, Mapping):
        raise ValueError('expected-topic manifest must be a JSON object')
    if sha256_file(resolved) != EXPECTED_TOPIC_MANIFEST_SHA256:
        raise ValueError('expected-topic manifest is not the frozen artifact')
    expected_top = {
        'schema_version', 'manifest_id', 'read_only', 'authorizes_motion',
        'publishes_ros_messages', 'topics'}
    if (set(payload) != expected_top or payload.get('schema_version') != 1
            or payload.get('manifest_id') != EXPECTED_TOPIC_MANIFEST_ID
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('publishes_ros_messages') is not False):
        raise ValueError('expected-topic manifest policy is invalid')
    topics = payload.get('topics')
    if not isinstance(topics, list) or len(topics) != 6:
        raise ValueError('expected-topic manifest must define exactly six topics')
    roles = set(STREAM_NAMES).union({'tf', 'tf_static'})
    result = {}
    for item in topics:
        if not isinstance(item, Mapping) or set(item) != {
                'role', 'name', 'type', 'serialization_format', 'qos'}:
            raise ValueError('expected-topic manifest topic entry is invalid')
        role = item.get('role')
        name = item.get('name')
        qos = item.get('qos')
        if (role not in roles or role in result
                or not isinstance(name, str) or not name
                or item.get('serialization_format') != 'cdr'
                or not isinstance(qos, Mapping)
                or set(qos) != {
                    'reliability', 'durability', 'liveliness'}):
            raise ValueError('expected-topic manifest topic policy is invalid')
        expected_type = (EXPECTED_STREAM_TYPES.get(role)
                         if role in STREAM_NAMES else EXPECTED_TF_TYPE)
        reliability = qos.get('reliability')
        durability = qos.get('durability')
        liveliness = qos.get('liveliness')
        if (item.get('type') != expected_type
                or not isinstance(reliability, list) or not reliability
                or len(reliability) != len(set(reliability))
                or any(value not in ('BEST_EFFORT', 'RELIABLE')
                       for value in reliability)
                or not isinstance(durability, list) or not durability
                or len(durability) != len(set(durability))
                or any(value not in ('VOLATILE', 'TRANSIENT_LOCAL')
                       for value in durability)
                or not isinstance(liveliness, list) or not liveliness
                or len(liveliness) != len(set(liveliness))
                or any(value not in (
                    'AUTOMATIC', 'MANUAL_BY_NODE', 'MANUAL_BY_TOPIC')
                       for value in liveliness)):
            raise ValueError('expected-topic manifest type or QoS is invalid')
        result[role] = dict(item)
    if set(result) != roles:
        raise ValueError('expected-topic manifest roles are incomplete')
    return {
        'path': str(resolved),
        'size_bytes': resolved.stat().st_size,
        'sha256': sha256_file(resolved),
        'manifest_id': payload['manifest_id'],
        'schema_version': payload['schema_version'],
        'topics': result,
    }


def _validate_inputs(
        path: Path, capture_id: str, scene: str,
        stream_topics: Mapping[str, str], topic_manifest: Mapping) -> Path:
    if path.suffix.lower() != '.db3':
        raise ValueError('rosbag input must use the .db3 extension')
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError('rosbag input does not exist') from error
    if not resolved.is_file():
        raise ValueError('rosbag input must be a regular file')
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise ValueError('capture_id must be a non-empty string')
    if scene not in SCENES:
        raise ValueError('scene must be one of: ' + ', '.join(SCENES))
    if not isinstance(stream_topics, Mapping):
        raise ValueError('stream_topics must be a mapping')
    if set(stream_topics) != set(STREAM_NAMES):
        raise ValueError(
            'stream_topics must contain exactly: ' + ', '.join(STREAM_NAMES))
    topic_names = [stream_topics[name] for name in STREAM_NAMES]
    if any(not isinstance(name, str) or not name.strip()
           for name in topic_names):
        raise ValueError('all stream topic names must be non-empty strings')
    if len(set(topic_names)) != len(topic_names):
        raise ValueError('stream topic mappings must be unique')
    if set(topic_names).intersection(TF_TOPICS):
        raise ValueError('RGB-D stream topics may not alias TF topics')
    expected_stream_topics = {
        role: topic_manifest['topics'][role]['name'] for role in STREAM_NAMES}
    if dict(stream_topics) != expected_stream_topics:
        raise ValueError(
            'stream_topics must exactly match frozen expected-topic manifest')
    return resolved


def _table_columns(connection: sqlite3.Connection, table: str) -> set:
    rows = connection.execute(
        'PRAGMA table_info("{}")'.format(table)).fetchall()
    return {row['name'] for row in rows}


def _validate_schema(connection: sqlite3.Connection) -> None:
    objects = {
        row['name']: row['type'] for row in connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE name IN ('topics', 'messages')")}
    if objects != {'topics': 'table', 'messages': 'table'}:
        raise ValueError(
            'invalid rosbag2 SQLite schema: topics/messages tables required')
    topic_columns = _table_columns(connection, 'topics')
    message_columns = _table_columns(connection, 'messages')
    if not REQUIRED_TOPIC_COLUMNS.issubset(topic_columns):
        raise ValueError(
            'invalid rosbag2 SQLite schema: topics columns missing')
    if not REQUIRED_MESSAGE_COLUMNS.issubset(message_columns):
        raise ValueError(
            'invalid rosbag2 SQLite schema: messages columns missing')


def is_control_topic(name: str, message_type: str) -> bool:
    """Return whether a recorded topic can address motion or actuation."""
    if not isinstance(name, str) or not isinstance(message_type, str):
        return True
    normalized = name.rstrip('/') or '/'
    lowered = normalized.lower()
    type_lower = message_type.lower()
    if (normalized in CONTROL_TOPIC_NAMES
            or message_type in CONTROL_MESSAGE_TYPES):
        return True
    leaf = lowered.rsplit('/', 1)[-1]
    if leaf in {'cmd_vel', 'safe_cmd_vel', 'navigate_to_pose'}:
        return True
    if ('navigate' in lowered or 'move_base' in lowered) and (
            leaf in {'goal', 'command'} or 'action' in type_lower):
        return True
    if 'joint_trajectory' in lowered:
        return True
    return any(
        actuator in lowered and command in leaf
        for actuator in ('arm', 'gripper')
        for command in ('command', 'commands', 'goal'))


def _qos_scalar(value: str):
    stripped = value.strip()
    if not stripped:
        raise ValueError('offered QoS field is empty')
    lowered = stripped.lower().replace('-', '_')
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    try:
        return int(lowered, 10)
    except ValueError:
        return lowered


def _parse_qos_profiles(value) -> Sequence[Mapping]:
    """Parse rosbag2's fixed YAML QoS subset without a YAML dependency."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('offered QoS metadata is missing')
    profiles = []
    current = None
    nested_key = None
    for raw_line in value.splitlines():
        if '\t' in raw_line:
            raise ValueError('offered QoS tabs are not supported')
        if not raw_line.strip() or raw_line.lstrip().startswith('#'):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(' '))
        text = raw_line.strip()
        is_profile = text.startswith('-')
        if is_profile:
            if indent != 0:
                raise ValueError('offered QoS list indentation is invalid')
            if current is not None:
                profiles.append(current)
            current = {}
            nested_key = None
            text = text[1:].strip()
            if not text:
                continue
        elif current is None:
            raise ValueError('offered QoS root must be a profile list')
        if ':' not in text:
            raise ValueError('offered QoS metadata is not parseable')
        key, raw_value = text.split(':', 1)
        key = key.strip().lower()
        raw_value = raw_value.strip()
        if indent >= 4:
            if (nested_key not in {'deadline', 'lifespan',
                                   'liveliness_lease_duration'}
                    or key not in {'sec', 'nsec'}):
                raise ValueError('offered QoS nested field is invalid')
            nested = current[nested_key]
            if key in nested:
                raise ValueError('offered QoS nested field is duplicated')
            nested[key] = _qos_scalar(raw_value)
            continue
        if indent not in (0, 2):
            raise ValueError('offered QoS indentation is invalid')
        if key not in _ALLOWED_QOS_KEYS or key in current:
            raise ValueError('offered QoS field is unknown or duplicated')
        if key in {'deadline', 'lifespan', 'liveliness_lease_duration'}:
            if raw_value not in ('', '{}'):
                raise ValueError('offered QoS duration field is invalid')
            current[key] = {}
            nested_key = key
        else:
            current[key] = _qos_scalar(raw_value)
            nested_key = None
    if current is not None:
        profiles.append(current)
    if not profiles:
        raise ValueError('offered QoS metadata is missing')
    return profiles


def _validate_qos(
        name: str, offered, expected_policy: Mapping) -> Mapping[str, str]:
    profiles = _parse_qos_profiles(offered)
    normalized_profiles = []
    semantic_profiles = []
    history_map = {
        0: 'SYSTEM_DEFAULT', 'system_default': 'SYSTEM_DEFAULT',
        1: 'KEEP_LAST', 'keep_last': 'KEEP_LAST',
        2: 'KEEP_ALL', 'keep_all': 'KEEP_ALL',
        3: 'UNKNOWN', 'unknown': 'UNKNOWN',
    }
    reliability_map = {
        1: 'RELIABLE', 'reliable': 'RELIABLE',
        2: 'BEST_EFFORT', 'best_effort': 'BEST_EFFORT',
    }
    durability_map = {
        1: 'TRANSIENT_LOCAL', 'transient_local': 'TRANSIENT_LOCAL',
        2: 'VOLATILE', 'volatile': 'VOLATILE',
    }
    liveliness_map = {
        1: 'AUTOMATIC', 'automatic': 'AUTOMATIC',
        2: 'MANUAL_BY_NODE', 'manual_by_node': 'MANUAL_BY_NODE',
        3: 'MANUAL_BY_TOPIC', 'manual_by_topic': 'MANUAL_BY_TOPIC',
    }
    allowed_reliability = expected_policy.get('reliability') if isinstance(
        expected_policy, Mapping) else None
    allowed_durability = expected_policy.get('durability') if isinstance(
        expected_policy, Mapping) else None
    allowed_liveliness = expected_policy.get('liveliness') if isinstance(
        expected_policy, Mapping) else None
    for fields in profiles:
        if set(fields) != _ALLOWED_QOS_KEYS:
            raise ValueError(
                'offered QoS fields are incomplete or unknown: ' + name)
        if not _REQUIRED_QOS_KEYS.issubset(fields):
            raise ValueError('offered QoS required fields are missing: ' + name)
        for duration_name in (
                'deadline', 'lifespan', 'liveliness_lease_duration'):
            duration = fields.get(duration_name)
            if (not isinstance(duration, Mapping)
                    or set(duration) != {'sec', 'nsec'}
                    or not isinstance(duration.get('sec'), int)
                    or isinstance(duration.get('sec'), bool)
                    or not isinstance(duration.get('nsec'), int)
                    or isinstance(duration.get('nsec'), bool)
                    or not 0 <= duration['sec'] <= MAX_UINT64
                    or not 0 <= duration['nsec'] < 1_000_000_000):
                raise ValueError('offered QoS duration is invalid: ' + name)
        if not isinstance(fields.get('avoid_ros_namespace_conventions'), bool):
            raise ValueError('offered QoS namespace flag is invalid: ' + name)
        if fields.get('avoid_ros_namespace_conventions') is not False:
            raise ValueError('offered QoS ROS namespace compatibility is required: ' + name)
        liveliness = liveliness_map.get(fields.get('liveliness'))
        if liveliness is None:
            raise ValueError('offered QoS liveliness is unknown: ' + name)
        history = history_map.get(fields['history'])
        depth = fields['depth'] if isinstance(
            fields['depth'], int) and not isinstance(fields['depth'], bool) else -1
        if (history not in ('KEEP_LAST', 'KEEP_ALL')
                or not 0 <= depth <= MAX_UINT64):
            raise ValueError('offered QoS history/depth is invalid: ' + name)
        if history == 'KEEP_LAST' and depth <= 0:
            raise ValueError('KEEP_LAST offered QoS depth must be positive: ' + name)
        reliability = fields.get('reliability')
        durability = fields.get('durability')
        if reliability not in reliability_map:
            raise ValueError('offered QoS reliability is unknown: ' + name)
        if durability not in durability_map:
            raise ValueError('offered QoS durability is unknown: ' + name)
        transient = durability_map[durability] == 'TRANSIENT_LOCAL'
        if name == '/tf_static' and not transient:
            raise ValueError('/tf_static must offer transient-local durability')
        if name != '/tf_static' and transient:
            raise ValueError('non-static capture topic may not be transient-local')
        result = {
            'history': history,
            'depth': depth,
            'reliability': reliability_map[reliability],
            'durability': 'TRANSIENT_LOCAL' if transient else 'VOLATILE',
            'liveliness': liveliness,
        }
        if (not isinstance(allowed_reliability, list)
                or result['reliability'] not in allowed_reliability
                or not isinstance(allowed_durability, list)
                or result['durability'] not in allowed_durability
                or not isinstance(allowed_liveliness, list)
                or result['liveliness'] not in allowed_liveliness):
            raise ValueError('offered QoS is incompatible with stream use: ' + name)
        normalized_profiles.append(result)
        semantic_profiles.append({
            **result,
            'depth': 0 if history == 'KEEP_ALL' else depth,
            'deadline': dict(fields['deadline']),
            'lifespan': dict(fields['lifespan']),
            'liveliness': liveliness,
            'liveliness_lease_duration': dict(
                fields['liveliness_lease_duration']),
            'avoid_ros_namespace_conventions': False,
        })
    canonical = {
        json.dumps(profile, sort_keys=True, separators=(',', ':'))
        for profile in semantic_profiles}
    if len(canonical) != 1:
        raise ValueError('offered QoS profiles are mutually incompatible: ' + name)
    return {
        **normalized_profiles[0],
        'profile_count': len(normalized_profiles),
    }


def _valid_frame_id(value: str) -> bool:
    """Accept a conservative, unambiguous tf2 frame-id subset."""
    if (not isinstance(value, str) or not value
            or value != value.strip() or value.startswith('/')):
        return False
    segments = value.split('/')
    return all(
        segment not in ('', '.', '..')
        and all(character in _FRAME_ID_SEGMENT_CHARS for character in segment)
        for segment in segments)


class _CdrReader:
    """Small strict CDR reader for the fixed ROS 2 evidence message types."""

    def __init__(self, payload: bytes):
        if not isinstance(payload, bytes) or len(payload) < 4:
            raise ValueError('CDR payload is truncated')
        encapsulation = payload[:2]
        if encapsulation == b'\x00\x01':
            self.endian = '<'
        elif encapsulation == b'\x00\x00':
            self.endian = '>'
        else:
            raise ValueError('unsupported CDR encapsulation')
        if payload[2:4] != b'\x00\x00':
            raise ValueError('unsupported CDR encapsulation options')
        self.payload = payload
        self.offset = 4
        self.origin = 4

    def _align(self, alignment: int) -> None:
        relative = self.offset - self.origin
        self.offset += (-relative) % alignment
        if self.offset > len(self.payload):
            raise ValueError('CDR payload is truncated')

    def _unpack(self, code: str, alignment: int):
        self._align(alignment)
        size = struct.calcsize(code)
        if self.offset + size > len(self.payload):
            raise ValueError('CDR payload is truncated')
        value = struct.unpack_from(self.endian + code, self.payload, self.offset)[0]
        self.offset += size
        return value

    def uint8(self) -> int:
        return self._unpack('B', 1)

    def uint32(self) -> int:
        return self._unpack('I', 4)

    def int32(self) -> int:
        return self._unpack('i', 4)

    def float64(self) -> float:
        return self._unpack('d', 8)

    def string(self) -> str:
        length = self.uint32()
        if length <= 0 or self.offset + length > len(self.payload):
            raise ValueError('invalid CDR string')
        raw = self.payload[self.offset:self.offset + length]
        self.offset += length
        if raw[-1:] != b'\x00':
            raise ValueError('CDR string lacks terminator')
        try:
            value = raw[:-1].decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('CDR string is not UTF-8') from error
        if '\x00' in value:
            raise ValueError('CDR string contains an embedded NUL')
        return value

    def bytes(self, count: int) -> bytes:
        if count < 0 or self.offset + count > len(self.payload):
            raise ValueError('CDR payload is truncated')
        value = self.payload[self.offset:self.offset + count]
        self.offset += count
        return value

    def finish(self) -> None:
        if self.offset != len(self.payload):
            raise ValueError('CDR payload has trailing bytes')


def _header(reader: _CdrReader) -> Mapping:
    sec = reader.int32()
    nanosec = reader.uint32()
    frame_id = reader.string()
    if sec < 0 or nanosec >= 1_000_000_000 or not _valid_frame_id(frame_id):
        raise ValueError('invalid ROS Header')
    stamp_ns = sec * 1_000_000_000 + nanosec
    if stamp_ns <= 0:
        raise ValueError('ROS Header stamp must be positive')
    return {'stamp_ns': stamp_ns, 'frame_id': frame_id}


def _decode_image(payload: bytes) -> Mapping:
    reader = _CdrReader(payload)
    header = _header(reader)
    height = reader.uint32()
    width = reader.uint32()
    encoding = reader.string()
    is_bigendian = reader.uint8()
    step = reader.uint32()
    data_length = reader.uint32()
    reader.bytes(data_length)
    reader.finish()
    if (height <= 0 or width <= 0 or not encoding or is_bigendian not in (0, 1)
            or step <= 0 or data_length != step * height):
        raise ValueError('invalid sensor_msgs/Image payload')
    return {
        **header, 'height': height, 'width': width, 'encoding': encoding,
        'is_bigendian': is_bigendian, 'step': step,
        'data_length': data_length,
    }


def decode_image_pixels(payload: bytes) -> Mapping:
    """Strictly decode one Image including bytes for offline remeasurement."""
    reader = _CdrReader(payload)
    header = _header(reader)
    height = reader.uint32()
    width = reader.uint32()
    encoding = reader.string()
    is_bigendian = reader.uint8()
    step = reader.uint32()
    data_length = reader.uint32()
    data = reader.bytes(data_length)
    reader.finish()
    bytes_per_pixel = {
        'bgr8': 3, 'rgb8': 3, 'rgba8': 4, 'bgra8': 4, 'mono8': 1,
        '16UC1': 2, 'mono16': 2, '32FC1': 4,
    }.get(encoding)
    if (height <= 0 or width <= 0 or bytes_per_pixel is None
            or is_bigendian not in (0, 1)
            or step < width * bytes_per_pixel
            or data_length != step * height):
        raise ValueError('invalid sensor_msgs/Image payload')
    if encoding in ('16UC1', 'mono16', '32FC1') and (
            step % bytes_per_pixel != 0):
        raise ValueError('depth Image encoding is incompatible')
    return {
        **header, 'height': height, 'width': width, 'encoding': encoding,
        'is_bigendian': is_bigendian, 'step': step,
        'data_length': data_length, 'data': data,
    }


def _decode_camera_info(payload: bytes) -> Mapping:
    reader = _CdrReader(payload)
    header = _header(reader)
    height = reader.uint32()
    width = reader.uint32()
    distortion_model = reader.string()
    distortion_count = reader.uint32()
    distortion = [reader.float64() for _ in range(distortion_count)]
    camera_matrix = [reader.float64() for _ in range(9)]
    rectification = [reader.float64() for _ in range(9)]
    projection = [reader.float64() for _ in range(12)]
    binning_x = reader.uint32()
    binning_y = reader.uint32()
    roi = {
        'x_offset': reader.uint32(),
        'y_offset': reader.uint32(),
        'height': reader.uint32(),
        'width': reader.uint32(),
    }
    do_rectify = reader.uint8()
    reader.finish()
    numeric = distortion + camera_matrix + rectification + projection
    if (height <= 0 or width <= 0 or not distortion_model
            or distortion_count > 128 or not all(math.isfinite(v) for v in numeric)
            or camera_matrix[0] <= 0.0 or camera_matrix[4] <= 0.0
            or not 0.0 <= camera_matrix[2] < float(width)
            or not 0.0 <= camera_matrix[5] < float(height)
            or (binning_x != 0 and not 1 <= binning_x <= width)
            or (binning_y != 0 and not 1 <= binning_y <= height)
            or do_rectify not in (0, 1)
            or roi['x_offset'] + roi['width'] > width
            or roi['y_offset'] + roi['height'] > height):
        raise ValueError('invalid sensor_msgs/CameraInfo payload')
    return {
        **header, 'height': height, 'width': width,
        'distortion_model': distortion_model,
        'intrinsics': {
            'fx': camera_matrix[0], 'fy': camera_matrix[4],
            'cx': camera_matrix[2], 'cy': camera_matrix[5],
        },
        'k': camera_matrix,
        'binning_x': binning_x,
        'binning_y': binning_y,
        'roi': {**roi, 'do_rectify': bool(do_rectify)},
    }


def _decode_tf_message(payload: bytes) -> Mapping:
    reader = _CdrReader(payload)
    count = reader.uint32()
    if count <= 0 or count > 1024:
        raise ValueError('invalid TFMessage transform count')
    transforms = []
    for _unused in range(count):
        header = _header(reader)
        child = reader.string()
        translation = [reader.float64() for _axis in range(3)]
        rotation = [reader.float64() for _axis in range(4)]
        if (not _valid_frame_id(child) or child == header['frame_id']
                or not all(math.isfinite(value)
                           for value in translation + rotation)
                or abs(math.sqrt(sum(value * value for value in rotation))
                       - 1.0) > 1e-3):
            raise ValueError('invalid geometry_msgs/TransformStamped payload')
        transforms.append({
            'stamp_ns': header['stamp_ns'],
            'parent_frame_id': header['frame_id'],
            'child_frame_id': child,
            'translation_m': translation,
            'rotation_xyzw': rotation,
        })
    reader.finish()
    return {'transforms': transforms}


def decode_cdr_payload(message_type: str, payload: bytes) -> Mapping:
    """Strictly decode the accepted fixed ROS 2 message types."""
    if message_type == 'sensor_msgs/msg/Image':
        return _decode_image(payload)
    if message_type == 'sensor_msgs/msg/CameraInfo':
        return _decode_camera_info(payload)
    if message_type == EXPECTED_TF_TYPE:
        return _decode_tf_message(payload)
    raise ValueError('unsupported message type for CDR validation')


def _read_topics(
        connection: sqlite3.Connection,
        stream_topics: Mapping[str, str],
        topic_manifest: Mapping) -> List[Mapping]:
    manifest_topics = topic_manifest['topics']
    expected_by_name = {
        item['name']: item for item in manifest_topics.values()}
    result = []
    seen_ids = set()
    seen_names = set()
    query = (
        'SELECT id, name, type, serialization_format, offered_qos_profiles '
        'FROM topics ORDER BY id')
    rows = list(connection.execute(query))
    names = [row['name'] for row in rows]
    if len(names) != len(set(names)):
        raise ValueError('duplicate rosbag2 topic name')
    if (set(names) != set(expected_by_name)
            or len(names) != len(expected_by_name)):
        raise ValueError('rosbag topic set must equal frozen six-topic manifest')
    for row in rows:
        topic_id = row['id']
        name = row['name']
        message_type = row['type']
        serialization = row['serialization_format']
        if (not isinstance(topic_id, int) or isinstance(topic_id, bool)
                or topic_id <= 0 or topic_id in seen_ids):
            raise ValueError('invalid rosbag2 topic identity')
        if (not isinstance(name, str) or not name or name in seen_names):
            raise ValueError('invalid or duplicate rosbag2 topic name')
        expected = expected_by_name[name]
        if (message_type != expected['type']
                or serialization != expected['serialization_format']):
            raise ValueError('topic type or CDR serialization mismatch: ' + name)
        qos = _validate_qos(
            name, row['offered_qos_profiles'], expected['qos'])
        seen_ids.add(topic_id)
        seen_names.add(name)
        result.append({
            'topic_id': topic_id,
            'name': name,
            'role': expected['role'],
            'type': message_type,
            'serialization_format': serialization,
            'offered_qos_profiles': row['offered_qos_profiles'],
            'qos': qos,
            'message_count': 0,
            'first_record_timestamp_ns': None,
            'last_record_timestamp_ns': None,
        })
    return result


def _read_messages(
        connection: sqlite3.Connection,
        topics: Sequence[Mapping]) -> List[Mapping]:
    topic_by_id = {item['topic_id']: item for item in topics}
    seen_ids = set()
    last_record_by_topic = {}
    result = []
    query = (
        'SELECT id, topic_id, timestamp, data FROM messages '
        'ORDER BY id')
    for row in connection.execute(query):
        message_id = row['id']
        topic_id = row['topic_id']
        timestamp_ns = row['timestamp']
        if (not isinstance(message_id, int) or isinstance(message_id, bool)
                or message_id <= 0 or message_id in seen_ids):
            raise ValueError('invalid or duplicate rosbag2 message identity')
        if topic_id not in topic_by_id:
            raise ValueError('rosbag2 message references an unknown topic')
        if (not isinstance(timestamp_ns, int) or isinstance(timestamp_ns, bool)
                or timestamp_ns < 0):
            raise ValueError('invalid rosbag2 message timestamp')
        payload = row['data']
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        if not isinstance(payload, bytes):
            raise ValueError('rosbag2 message data must be a BLOB')
        topic = topic_by_id[topic_id]
        try:
            decoded = decode_cdr_payload(topic['type'], payload)
        except ValueError as error:
            raise ValueError(
                'CDR payload decode failed for {} message {}'.format(
                    topic['name'], message_id)) from error
        if topic['name'] == '/camera/color/image_raw':
            encoding = decoded.get('encoding')
            bytes_per_pixel = {
                'bgr8': 3, 'rgb8': 3, 'rgba8': 4,
                'bgra8': 4, 'mono8': 1}.get(encoding)
            if (bytes_per_pixel is None
                    or decoded.get('step', 0)
                    < decoded.get('width', 0) * bytes_per_pixel):
                raise ValueError('RGB Image encoding is incompatible')
        if topic['name'] == '/camera/depth/image_raw':
            encoding = decoded.get('encoding')
            bytes_per_pixel = {
                '16UC1': 2, 'mono16': 2, '32FC1': 4}.get(encoding)
            if (bytes_per_pixel is None
                    or decoded.get('step', 0)
                    < decoded.get('width', 0) * bytes_per_pixel
                    or decoded.get('step', 0) % bytes_per_pixel != 0):
                raise ValueError('depth Image encoding is incompatible')
        previous_record = last_record_by_topic.get(topic_id)
        if (previous_record is not None
                and timestamp_ns <= previous_record):
            raise ValueError(
                'rosbag2 record timestamps must be strictly increasing per topic')
        last_record_by_topic[topic_id] = timestamp_ns
        header_stamps = []
        if topic['type'] in EXPECTED_STREAM_TYPES.values():
            header_stamps = [decoded['stamp_ns']]
        elif topic['name'] in TF_TOPICS:
            header_stamps = [
                item['stamp_ns'] for item in decoded['transforms']]
        if header_stamps:
            skews = [
                (timestamp_ns - stamp_ns) / 1e9
                for stamp_ns in header_stamps]
            # A transient-local static transform may legitimately have been
            # stamped long before this recorder joined.  It may never be
            # stamped in the future relative to receipt, while live sensor
            # and dynamic-TF samples must also meet the receive-latency bound.
            invalid_skew = (
                any(skew < 0.0 for skew in skews)
                if topic['name'] == '/tf_static'
                else any(
                    skew < 0.0 or skew > MAX_RECORD_HEADER_SKEW_SEC
                    for skew in skews))
            if invalid_skew:
                raise ValueError(
                    'rosbag2 record/Header timestamp skew is invalid')
        topic['message_count'] += 1
        first = topic['first_record_timestamp_ns']
        last = topic['last_record_timestamp_ns']
        topic['first_record_timestamp_ns'] = (
            timestamp_ns if first is None else min(first, timestamp_ns))
        topic['last_record_timestamp_ns'] = (
            timestamp_ns if last is None else max(last, timestamp_ns))
        seen_ids.add(message_id)
        result.append({
            'message_id': message_id,
            'topic': topic['name'],
            'record_timestamp_ns': timestamp_ns,
            'serialized_size_bytes': len(payload),
            'serialized_sha256': hashlib.sha256(payload).hexdigest(),
            'payload_decode_ok': True,
            'record_header_skew_sec': (
                max(skews) if header_stamps else None),
            'decoded': decoded,
        })
    if any(topic['message_count'] <= 0 for topic in topics):
        raise ValueError('all frozen six topics must contain at least one message')
    return result


def _accepted_bundles(
        messages: Sequence[Mapping],
        stream_topics: Mapping[str, str],
        max_sync_span_sec: float = MAX_SYNC_SPAN_SEC
        ) -> Tuple[List[Mapping], Mapping]:
    if (not isinstance(max_sync_span_sec, (int, float))
            or isinstance(max_sync_span_sec, bool)
            or not math.isfinite(max_sync_span_sec)
            or max_sync_span_sec < 0.0):
        raise ValueError('max_sync_span_sec must be finite and non-negative')
    by_stream = {
        stream: [message for message in messages
                 if message['topic'] == stream_topics[stream]]
        for stream in STREAM_NAMES
    }
    for stream, values in by_stream.items():
        stamps = [item['decoded']['stamp_ns'] for item in values]
        if any(current <= previous for previous, current in zip(
                stamps, stamps[1:])):
            raise ValueError(
                'decoded Header stamps must be strictly increasing: ' + stream)
    used = {stream: set() for stream in STREAM_NAMES if stream != 'rgb'}
    last_selected_stamp = {
        stream: None for stream in STREAM_NAMES if stream != 'rgb'}
    accepted = []
    rejected = {'missing_stream': 0, 'over_sync_span': 0}
    for anchor in by_stream['rgb']:
        selected = {'rgb': anchor}
        for stream in STREAM_NAMES[1:]:
            candidates = [
                message for message in by_stream[stream]
                if (message['message_id'] not in used[stream]
                    and (last_selected_stamp[stream] is None
                         or message['decoded']['stamp_ns']
                         > last_selected_stamp[stream]))]
            if not candidates:
                selected = {}
                rejected['missing_stream'] += 1
                break
            selected[stream] = min(
                candidates,
                key=lambda message: (
                    abs(message['decoded']['stamp_ns']
                        - anchor['decoded']['stamp_ns']),
                    message['decoded']['stamp_ns'], message['message_id']))
        if len(selected) != len(STREAM_NAMES):
            continue
        header_stamps = {
            stream: selected[stream]['decoded']['stamp_ns']
            for stream in STREAM_NAMES}
        span_sec = (
            max(header_stamps.values()) - min(header_stamps.values())) / 1e9
        if span_sec > max_sync_span_sec:
            rejected['over_sync_span'] += 1
            continue
        record_span_sec = (
            max(selected[stream]['record_timestamp_ns']
                for stream in STREAM_NAMES)
            - min(selected[stream]['record_timestamp_ns']
                  for stream in STREAM_NAMES)) / 1e9
        if record_span_sec > max_sync_span_sec:
            rejected['over_sync_span'] += 1
            continue
        for stream in STREAM_NAMES[1:]:
            used[stream].add(selected[stream]['message_id'])
            last_selected_stamp[stream] = selected[stream][
                'decoded']['stamp_ns']
        accepted.append({
            'index': len(accepted),
            **{
                stream: selected[stream]['message_id']
                for stream in STREAM_NAMES},
            'header_stamps_ns': header_stamps,
            'stream_payload_sha256': {
                stream: selected[stream]['serialized_sha256']
                for stream in STREAM_NAMES},
            'stream_serialized_size_bytes': {
                stream: selected[stream]['serialized_size_bytes']
                for stream in STREAM_NAMES},
            'stream_record_timestamps_ns': {
                stream: selected[stream]['record_timestamp_ns']
                for stream in STREAM_NAMES},
            'stream_record_header_skew_sec': {
                stream: selected[stream]['record_header_skew_sec']
                for stream in STREAM_NAMES},
            'record_timestamp_span_sec': (
                record_span_sec),
            'stamp_span_sec': span_sec,
        })
    candidates = len(by_stream['rgb'])
    rejected_count = candidates - len(accepted)
    if sum(rejected.values()) != rejected_count:
        raise ValueError('RGB rejection accounting is not closed')
    unmatched_by_stream = {
        stream: len(by_stream[stream]) - len(accepted)
        for stream in STREAM_NAMES}
    total_stream_messages = sum(len(values) for values in by_stream.values())
    total_paired_messages = len(accepted) * len(STREAM_NAMES)
    total_unpaired_messages = total_stream_messages - total_paired_messages
    return accepted, {
        'rgb_candidate_count': candidates,
        'accepted_bundle_count': len(accepted),
        'rejected_rgb_count': rejected_count,
        'rejection_rate': (
            rejected_count / candidates if candidates else None),
        'rejection_reasons': rejected,
        'unmatched_message_count_by_stream': unmatched_by_stream,
        'total_stream_message_count': total_stream_messages,
        'total_unpaired_message_count': total_unpaired_messages,
        'total_unpaired_rate': (
            total_unpaired_messages / total_stream_messages
            if total_stream_messages else None),
    }


def _quaternion_multiply(first, second):
    ax, ay, az, aw = first
    bx, by, bz, bw = second
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def _rotate(rotation, vector):
    conjugate = [-rotation[0], -rotation[1], -rotation[2], rotation[3]]
    value = _quaternion_multiply(
        _quaternion_multiply(rotation, [*vector, 0.0]), conjugate)
    return value[:3]


def _inverse_transform(transform: Mapping) -> Mapping:
    rotation = transform['rotation_xyzw']
    inverse_rotation = [-rotation[0], -rotation[1], -rotation[2], rotation[3]]
    return {
        **transform,
        'parent_frame_id': transform['child_frame_id'],
        'child_frame_id': transform['parent_frame_id'],
        'translation_m': [
            -value for value in _rotate(
                inverse_rotation, transform['translation_m'])],
        'rotation_xyzw': inverse_rotation,
    }


def _compose_chain(chain: Sequence[str], selected_edges: Mapping) -> Mapping:
    translation = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0, 1.0]
    sample_ids = []
    ages = []
    for parent, child in zip(chain, chain[1:]):
        edge = selected_edges[(parent, child)]
        rotated = _rotate(rotation, edge['translation_m'])
        translation = [
            first + second for first, second in zip(translation, rotated)]
        rotation = _quaternion_multiply(rotation, edge['rotation_xyzw'])
        sample_ids.append({
            'topic': edge['topic'],
            'message_id': edge['message_id'],
            'transform_index': edge['transform_index'],
            'serialized_sha256': edge['serialized_sha256'],
            'stamp_ns': edge['stamp_ns'],
            'age_sec': edge.get('age_sec'),
            'parent_frame_id': edge['parent_frame_id'],
            'child_frame_id': edge['child_frame_id'],
        })
        if edge.get('age_sec') is not None:
            ages.append(edge['age_sec'])
    canonical = json.dumps(
        sample_ids, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    return {
        'translation_m': translation,
        'rotation_xyzw': rotation,
        'samples': sample_ids,
        'sample_set_sha256': hashlib.sha256(canonical).hexdigest(),
        'max_dynamic_age_sec': max(ages) if ages else 0.0,
    }


def _tf_graph(
        messages: Sequence[Mapping], camera_frame: str,
        bundles: Sequence[Mapping], max_dynamic_tf_age_sec: float
        ) -> Mapping:
    transforms = []
    for message in messages:
        if message['topic'] in TF_TOPICS:
            for transform_index, transform in enumerate(
                    message['decoded']['transforms']):
                transforms.append({
                    **transform,
                    'topic': message['topic'],
                    'message_id': message['message_id'],
                    'transform_index': transform_index,
                    'serialized_sha256': message['serialized_sha256'],
                })
    if not transforms:
        raise ValueError('decoded TF payloads are empty')
    static_by_edge = {}
    dynamic_by_edge = {}
    child_parents = {}
    for transform in transforms:
        parent = transform['parent_frame_id']
        child = transform['child_frame_id']
        child_parents.setdefault(child, set()).add(parent)
        key = (parent, child)
        if transform['topic'] == '/tf_static':
            previous = static_by_edge.get(key)
            if previous is not None and any(
                    abs(first - second) > 1e-9 for first, second in zip(
                        previous['translation_m'] + previous['rotation_xyzw'],
                        transform['translation_m'] + transform[
                            'rotation_xyzw'])):
                raise ValueError('conflicting static TF samples')
            static_by_edge[key] = transform
        else:
            dynamic_by_edge.setdefault(key, []).append(transform)
    if any(len(parents) != 1 for parents in child_parents.values()):
        raise ValueError('TF child has multiple parents')
    if set(static_by_edge).intersection(dynamic_by_edge):
        raise ValueError('TF edge is declared both static and dynamic')
    for values in dynamic_by_edge.values():
        source_order = sorted(values, key=lambda item: (
            item['message_id'], item['transform_index']))
        if any(second['stamp_ns'] <= first['stamp_ns']
               for first, second in zip(source_order, source_order[1:])):
            raise ValueError(
                'dynamic TF Header stamps must be strictly increasing per edge')
        values.sort(key=lambda item: (
            item['stamp_ns'], item['message_id'], item['transform_index']))

    def select_edges(stamp_ns):
        selected = {key: dict(value) for key, value in static_by_edge.items()}
        for key, values in dynamic_by_edge.items():
            candidates = [value for value in values if value['stamp_ns'] <= stamp_ns]
            if not candidates:
                continue
            value = dict(candidates[-1])
            age_sec = (stamp_ns - value['stamp_ns']) / 1e9
            if age_sec <= max_dynamic_tf_age_sec:
                value['age_sec'] = age_sec
                selected[key] = value
        return selected

    bundle_transforms = []
    canonical_chain = None
    for bundle in bundles:
        stamp_ns = bundle['header_stamps_ns']['rgb']
        selected = select_edges(stamp_ns)
        adjacency: Dict[str, set] = {}
        directed = {}
        for (parent, child), transform in selected.items():
            adjacency.setdefault(parent, set()).add(child)
            adjacency.setdefault(child, set()).add(parent)
            directed[(parent, child)] = transform
            directed[(child, parent)] = _inverse_transform(transform)
        paths = []
        pending = [('base_link', ['base_link'])]
        while pending:
            frame, path = pending.pop(0)
            if frame == camera_frame:
                paths.append(path)
                continue
            for neighbour in sorted(adjacency.get(frame, ())):
                if neighbour not in path:
                    pending.append((neighbour, path + [neighbour]))
        if len(paths) != 1:
            raise ValueError(
                'TF must provide one unambiguous base-to-camera path per bundle')
        chain = paths[0]
        chain_topics = {
            directed[(first_frame, second_frame)].get('topic')
            for first_frame, second_frame in zip(chain, chain[1:])}
        if chain_topics != {'/tf', '/tf_static'}:
            raise ValueError(
                'base-to-camera chain must use both /tf and /tf_static')
        if canonical_chain is None:
            canonical_chain = chain
        elif chain != canonical_chain:
            raise ValueError('TF base-to-camera chain changes across bundles')
        composed = _compose_chain(chain, directed)
        bundle_transforms.append({
            'bundle_index': bundle['index'],
            'rgb_header_stamp_ns': stamp_ns,
            'chain_base_to_camera': chain,
            'translation_m': composed['translation_m'],
            'rotation_xyzw': composed['rotation_xyzw'],
            'samples': composed['samples'],
            'sample_set_sha256': composed['sample_set_sha256'],
            'max_dynamic_age_sec': composed['max_dynamic_age_sec'],
        })
    if not bundle_transforms:
        raise ValueError('no accepted RGB-D bundle has TF coverage')
    first = bundle_transforms[0]
    for item in bundle_transforms[1:]:
        if (any(abs(a - b) > 1e-6 for a, b in zip(
                    first['translation_m'], item['translation_m']))
                or any(abs(a - b) > 1e-6 for a, b in zip(
                    first['rotation_xyzw'], item['rotation_xyzw']))):
            raise ValueError('base-to-camera TF is not stable across capture')
    return {
        'camera_frame': camera_frame,
        'base_frame': 'base_link',
        'chain_base_to_camera': canonical_chain,
        'base_to_camera_transform': {
            'translation_m': first['translation_m'],
            'rotation_xyzw': first['rotation_xyzw'],
        },
        'max_dynamic_tf_age_sec': max_dynamic_tf_age_sec,
        'bundle_tf_coverage_count': len(bundle_transforms),
        'bundle_transforms': bundle_transforms,
        'transforms': transforms,
        'transform_count': len(transforms),
    }


def inspect_sqlite_bag(
        path, capture_id: str, scene: str,
        stream_topics: Mapping[str, str], topic_manifest_path=None,
        max_dynamic_tf_age_sec: float = MAX_DYNAMIC_TF_AGE_SEC) -> Mapping:
    """Return a deterministic, decoded, read-only index of one bag."""
    if (not isinstance(max_dynamic_tf_age_sec, (int, float))
            or isinstance(max_dynamic_tf_age_sec, bool)
            or not math.isfinite(max_dynamic_tf_age_sec)
            or max_dynamic_tf_age_sec < 0.0):
        raise ValueError('max_dynamic_tf_age_sec must be finite and non-negative')
    topic_manifest = load_topic_manifest(topic_manifest_path)
    resolved = _validate_inputs(
        Path(path), capture_id, scene, stream_topics, topic_manifest)
    source_size = resolved.stat().st_size
    source_sha256 = sha256_file(resolved)
    uri = resolved.as_uri() + '?mode=ro&immutable=1'
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only = ON')
            quick_check = connection.execute('PRAGMA quick_check').fetchone()
            if quick_check is None or quick_check[0] != 'ok':
                raise ValueError('invalid rosbag2 SQLite integrity')
            _validate_schema(connection)
            topics = _read_topics(connection, stream_topics, topic_manifest)
            messages = _read_messages(connection, topics)
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise ValueError('invalid rosbag2 SQLite database') from error
    bundles, pairing = _accepted_bundles(messages, stream_topics)
    camera_frames = {
        message['decoded']['frame_id'] for message in messages
        if message['topic'] in set(stream_topics.values())}
    if len(camera_frames) != 1:
        raise ValueError('decoded RGB-D Header frame IDs are inconsistent')
    tf_graph = _tf_graph(
        messages, next(iter(camera_frames)), bundles,
        max_dynamic_tf_age_sec)
    control_topics = sorted(
        topic['name'] for topic in topics
        if is_control_topic(topic['name'], topic['type']))
    return {
        'schema_version': 3,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        **FORMAL_RAW_INSPECTION_POLICY,
        'storage_identifier': 'sqlite3',
        'timestamp_semantics': {
            'record_timestamp': 'rosbag2_receive_time_not_sensor_header',
            'pairing_and_sync': 'decoded_ros_header_stamp',
        },
        'source_capture': {
            'path': str(resolved),
            'size_bytes': source_size,
            'sha256': source_sha256,
        },
        'capture_id': capture_id,
        'scene': scene,
        'expected_topic_manifest': {
            'path': topic_manifest['path'],
            'size_bytes': topic_manifest['size_bytes'],
            'sha256': topic_manifest['sha256'],
            'manifest_id': topic_manifest['manifest_id'],
            'schema_version': topic_manifest['schema_version'],
        },
        'frozen_expected_topics': {
            item['name']: item['type']
            for item in topic_manifest['topics'].values()},
        'stream_topics': {
            name: stream_topics[name] for name in STREAM_NAMES},
        'topics': topics,
        'messages': messages,
        **pairing,
        'accepted_bundles': bundles,
        'tf_graph': tf_graph,
        'control_topics': control_topics,
    }


def parse_args(args=None):
    """Parse the filesystem-only rosbag indexer command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--bag', type=Path, required=True)
    parser.add_argument('--capture-id', required=True)
    parser.add_argument('--scene', choices=SCENES, required=True)
    parser.add_argument('--rgb-topic', required=True)
    parser.add_argument('--aligned-depth-topic', required=True)
    parser.add_argument('--rgb-camera-info-topic', required=True)
    parser.add_argument('--depth-camera-info-topic', required=True)
    parser.add_argument('--expected-topic-manifest', type=Path)
    parser.add_argument(
        '--max-dynamic-tf-age-sec', type=float,
        default=MAX_DYNAMIC_TF_AGE_SEC)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args(args)


def main(args=None):
    """Write one exclusive JSON index; never start ROS or publish controls."""
    parsed = parse_args(args)
    if parsed.output.exists():
        raise SystemExit('output path must not already exist')
    if parsed.output.resolve() == parsed.bag.resolve():
        raise SystemExit('output path must be different from the bag')
    report = inspect_sqlite_bag(
        parsed.bag, parsed.capture_id, parsed.scene, {
            'rgb': parsed.rgb_topic,
            'aligned_depth': parsed.aligned_depth_topic,
            'rgb_camera_info': parsed.rgb_camera_info_topic,
            'depth_camera_info': parsed.depth_camera_info_topic,
        }, parsed.expected_topic_manifest, parsed.max_dynamic_tf_age_sec)
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    with parsed.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
