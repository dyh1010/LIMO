"""Strictly inspect one ROS1 rosbag v2 without starting or joining a ROS graph."""

import argparse
import hashlib
import io
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


STREAM_ROLES = (
    'rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info')
TF_ROLES = ('tf', 'tf_static')
ALL_ROLES = STREAM_ROLES + TF_ROLES
EXPECTED_MANIFEST_BASENAME = 'dabai_ros1_raw_rgbd_six_topics_v1.json'
EXPECTED_MANIFEST_SHA256 = (
    '88771fcdac6770da49dc7ed75179c1b82243ca30e63f3e88d26a04ae70b59b2b')
EXPECTED_FORMAL_MANIFEST_BASENAME = (
    'dabai_ros1_formal_four_scene_six_topics_v1.json')
EXPECTED_FORMAL_MANIFEST_SHA256 = (
    '46b135e8aaacce4dc1d552078ff5236299a68efc90ada47420cb6e30ea7fb5f4')
IMAGE_TYPE = 'sensor_msgs/Image'
CAMERA_INFO_TYPE = 'sensor_msgs/CameraInfo'
TF_TYPE = 'tf2_msgs/TFMessage'
FORMAL_MODE = 'sensor_only_short_sample'
DIAGNOSTIC_MODE = 'diagnostic_shared_graph'
FORMAL_ACCEPTANCE_MODE = 'formal_scene_raw_capture'
FORMAL_CAMERA_ONLY_MODE = 'formal_camera_only'
FORMAL_READER_FACTORY_FORBIDDEN = (
    'formal_rosbag1_reader_factory_forbidden')
FORMAL_TEST_ONLY_READER_FORBIDDEN = (
    'formal_rosbag1_test_only_reader_not_admissible')
FORMAL_READER_ADMISSION_UNAVAILABLE = (
    'formal_rosbag1_fresh_reader_admission_unavailable')
FORMAL_SCENES = (
    'background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
_FRAME_SEGMENT = re.compile(r'^[A-Za-z0-9_-]+$')
ROSBAG1_V2_MAGIC = b'#ROSBAG V2.0\n'
ROSBAG1_MAX_FIRST_HEADER_BYTES = 1024 * 1024


class InspectionError(ValueError):
    """A deterministic fail-closed evidence validation error."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def sha256_file(path: Path) -> str:
    """Hash a file in bounded memory."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _path_component_is_linklike(path: Path) -> bool:
    """Reject symlinks and Windows reparse points without following them."""
    metadata = os.lstat(str(path))
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    return bool(
        reparse_flag
        and getattr(metadata, 'st_file_attributes', 0) & reparse_flag)


def _path_has_linklike_component(path: Path) -> bool:
    candidate = Path(path).absolute()
    chain = list(reversed(candidate.parents)) + [candidate]
    try:
        return any(_path_component_is_linklike(item) for item in chain)
    except (OSError, RuntimeError, ValueError):
        return True


def _formal_bag_identity(path: Path) -> Mapping:
    """Return a stable identity for one ordinary, non-linked `.bag` file."""
    candidate = Path(path)
    if candidate.suffix.lower() != '.bag':
        raise InspectionError('bag_extension_invalid')
    try:
        metadata_before = os.lstat(str(candidate.absolute()))
    except (OSError, RuntimeError, ValueError) as error:
        raise InspectionError('bag_missing', str(error)) from error
    if _path_has_linklike_component(candidate):
        raise InspectionError('bag_link_forbidden')
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise InspectionError('bag_missing', str(error)) from error
    if (not stat.S_ISREG(metadata_before.st_mode)
            or not resolved.is_file()
            or metadata_before.st_size <= 0):
        raise InspectionError('bag_not_regular_file')
    digest = sha256_file(resolved)
    try:
        metadata_after = os.lstat(str(candidate.absolute()))
    except OSError as error:
        raise InspectionError('bag_changed_during_hash', str(error)) from error
    if (not stat.S_ISREG(metadata_after.st_mode)
            or metadata_before.st_size != metadata_after.st_size
            or metadata_before.st_mtime_ns != metadata_after.st_mtime_ns
            or getattr(metadata_before, 'st_ino', None)
            != getattr(metadata_after, 'st_ino', None)):
        raise InspectionError('bag_changed_during_hash')
    return {
        'path': str(resolved),
        'size_bytes': metadata_after.st_size,
        'sha256': digest,
    }


def _rosbag1_header_fields(raw_header: bytes) -> Mapping[bytes, bytes]:
    """Parse one rosbag record header without importing the ROS stack."""
    fields = {}
    offset = 0
    while offset < len(raw_header):
        if len(raw_header) - offset < 4:
            raise InspectionError('rosbag1_v2_envelope_invalid')
        field_size = int.from_bytes(
            raw_header[offset:offset + 4], byteorder='little', signed=False)
        offset += 4
        if field_size <= 1 or field_size > len(raw_header) - offset:
            raise InspectionError('rosbag1_v2_envelope_invalid')
        field = raw_header[offset:offset + field_size]
        offset += field_size
        if b'=' not in field:
            raise InspectionError('rosbag1_v2_envelope_invalid')
        name, value = field.split(b'=', 1)
        if not name or name in fields:
            raise InspectionError('rosbag1_v2_envelope_invalid')
        fields[name] = value
    if offset != len(raw_header):
        raise InspectionError('rosbag1_v2_envelope_invalid')
    return fields


def _validate_rosbag1_v2_envelope(path: Path) -> None:
    """Reject renamed JSON/SQLite and truncated files before ROS imports.

    This small host-owned framing check is not a replacement for the Noetic
    decoder. It authenticates the exact v2 magic and first bag-header record
    before any ambient ``rosbag`` module or injected reader sees the file.
    """
    candidate = Path(path)
    try:
        file_size = candidate.stat().st_size
        with candidate.open('rb') as stream:
            magic = stream.read(len(ROSBAG1_V2_MAGIC))
            if magic != ROSBAG1_V2_MAGIC:
                raise InspectionError('rosbag1_v2_magic_invalid')
            header_size_raw = stream.read(4)
            if len(header_size_raw) != 4:
                raise InspectionError('rosbag1_v2_envelope_invalid')
            header_size = int.from_bytes(
                header_size_raw, byteorder='little', signed=False)
            remaining_after_length = (
                file_size - len(ROSBAG1_V2_MAGIC) - len(header_size_raw))
            if (header_size <= 0
                    or header_size > ROSBAG1_MAX_FIRST_HEADER_BYTES
                    or remaining_after_length < header_size + 4):
                raise InspectionError('rosbag1_v2_envelope_invalid')
            raw_header = stream.read(header_size)
            if len(raw_header) != header_size:
                raise InspectionError('rosbag1_v2_envelope_invalid')
            fields = _rosbag1_header_fields(raw_header)
            if fields.get(b'op') != b'\x03':
                raise InspectionError('rosbag1_v2_envelope_invalid')
            data_size_raw = stream.read(4)
            if len(data_size_raw) != 4:
                raise InspectionError('rosbag1_v2_envelope_invalid')
            data_size = int.from_bytes(
                data_size_raw, byteorder='little', signed=False)
            if data_size > file_size - stream.tell():
                raise InspectionError('rosbag1_v2_envelope_invalid')
    except InspectionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise InspectionError(
            'rosbag1_v2_envelope_invalid', str(error)) from error


def _canonical_mapping_sha256(value: Mapping) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def indexer_source_identity() -> Mapping:
    """Bind every report to the exact indexer source artifact in use."""
    try:
        path = Path(__file__).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise InspectionError('indexer_source_missing', str(error)) from error
    if not path.is_file():
        raise InspectionError(
            'indexer_source_not_regular_file', str(path))
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise InspectionError(
            'indexer_source_changed_during_hash', str(path))
    return {
        'path': str(path),
        'size_bytes': after.st_size,
        'sha256': digest,
    }


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _strict_json_loads(text: str):
    return json.loads(
        text, object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError('non-finite JSON constant: ' + value)))


def default_manifest_path() -> Path:
    """Find the frozen manifest in a source or catkin install layout."""
    module = Path(__file__).resolve()
    candidates = [
        module.parents[2] / 'config' / EXPECTED_MANIFEST_BASENAME]
    candidates.extend(
        parent / 'share' / 'limo_cleanup_ros1_perception' / 'config' /
        EXPECTED_MANIFEST_BASENAME
        for parent in module.parents)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise InspectionError(
        'manifest_not_found', 'frozen ROS1 RGB-D manifest is not installed')


def default_formal_manifest_path() -> Path:
    """Find the immutable formal four-scene manifest generation."""
    module = Path(__file__).resolve()
    candidates = [
        module.parents[2] / 'config' / EXPECTED_FORMAL_MANIFEST_BASENAME]
    candidates.extend(
        parent / 'share' / 'limo_cleanup_ros1_perception' / 'config' /
        EXPECTED_FORMAL_MANIFEST_BASENAME
        for parent in module.parents)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise InspectionError(
        'formal_manifest_not_found',
        'formal ROS1 RGB-D manifest is not installed')


def _validate_formal_manifest_payload(
        candidate: Path, resolved: Path, payload: Mapping,
        actual_sha: str) -> Mapping:
    if (_path_has_linklike_component(candidate)
            or resolved.name != EXPECTED_FORMAL_MANIFEST_BASENAME):
        raise InspectionError('formal_manifest_link_or_name_invalid')
    if actual_sha != EXPECTED_FORMAL_MANIFEST_SHA256:
        raise InspectionError(
            'formal_manifest_hash_mismatch',
            'formal manifest generation does not match its host anchor')
    expected_keys = {
        'schema_version', 'manifest_id', 'ros_major', 'ros_distro',
        'bag_format', 'inspection_scope', 'read_only', 'authorizes_motion',
        'publishes_ros_messages', 'starts_ros_graph', 'driver_callerid',
        'allowed_scenes', 'min_accepted_bundles', 'max_sync_span_sec',
        'max_record_header_skew_sec', 'max_unpaired_rate',
        'capture_window_policy', 'alignment_policy', 'tf_policy', 'topics'}
    if (not isinstance(payload, Mapping) or set(payload) != expected_keys
            or payload.get('schema_version') != 1
            or payload.get('manifest_id')
            != 'limo-dabai-ros1-formal-four-scene-six-topics-v1'
            or payload.get('ros_major') != 1
            or payload.get('ros_distro') != 'noetic'
            or payload.get('bag_format') != 'rosbag1-v2'
            or payload.get('inspection_scope') != FORMAL_ACCEPTANCE_MODE
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('publishes_ros_messages') is not False
            or payload.get('starts_ros_graph') is not False
            or payload.get('driver_callerid') != '/camera/camera'
            or payload.get('allowed_scenes') != list(FORMAL_SCENES)):
        raise InspectionError('formal_manifest_policy_invalid')
    for key, minimum, maximum in (
            ('min_accepted_bundles', 30, None),
            ('max_sync_span_sec', 0.0, 1.0),
            ('max_record_header_skew_sec', 0.0, 10.0),
            ('max_unpaired_rate', 0.0, 1.0)):
        value = payload.get(key)
        if key == 'min_accepted_bundles':
            valid = (isinstance(value, int) and not isinstance(value, bool)
                     and value >= minimum)
        else:
            valid = (_finite(value) and value >= minimum
                     and (maximum is None or value <= maximum))
        if not valid:
            raise InspectionError('formal_manifest_threshold_invalid', key)
    capture_policy = payload.get('capture_window_policy')
    if (not isinstance(capture_policy, Mapping)
            or set(capture_policy) != {
                'source', 'isolate_old_latched_camera_info',
                'require_isolation_ledger', 'allowed_isolated_roles',
                'max_isolated_messages_per_role'}
            or capture_policy.get('source')
            != 'decoded_rgb_depth_headers_and_record_times'
            or capture_policy.get(
                'isolate_old_latched_camera_info') is not True
            or capture_policy.get('require_isolation_ledger') is not True
            or capture_policy.get('allowed_isolated_roles')
            != ['rgb_camera_info', 'depth_camera_info']
            or not isinstance(
                capture_policy.get('max_isolated_messages_per_role'), int)
            or isinstance(
                capture_policy.get('max_isolated_messages_per_role'), bool)
            or capture_policy.get('max_isolated_messages_per_role') < 0):
        raise InspectionError('formal_manifest_capture_policy_invalid')
    alignment_policy = payload.get('alignment_policy')
    if (not isinstance(alignment_policy, Mapping)
            or set(alignment_policy) != {
                'require_all_stream_frames_equal',
                'require_all_stream_grids_equal',
                'require_stable_frame_per_stream',
                'require_stable_grid_per_stream'}
            or any(alignment_policy.get(key) is not True
                   for key in alignment_policy)):
        raise InspectionError('formal_manifest_alignment_policy_invalid')
    tf_policy = payload.get('tf_policy')
    tf_keys = {
        'allowed_frame_prefix', 'require_unique_parent_per_child',
        'require_unique_owner_per_child',
        'forbid_static_dynamic_child_overlap', 'forbidden_frame_ids'}
    if (not isinstance(tf_policy, Mapping) or set(tf_policy) != tf_keys
            or tf_policy.get('allowed_frame_prefix') != 'camera'
            or tf_policy.get('require_unique_parent_per_child') is not True
            or tf_policy.get('require_unique_owner_per_child') is not True
            or tf_policy.get('forbid_static_dynamic_child_overlap') is not True
            or not isinstance(tf_policy.get('forbidden_frame_ids'), list)
            or any(not isinstance(value, str) or not value
                   for value in tf_policy['forbidden_frame_ids'])):
        raise InspectionError('formal_manifest_tf_policy_invalid')
    entries = payload.get('topics')
    if not isinstance(entries, list) or len(entries) != len(ALL_ROLES):
        raise InspectionError('formal_manifest_topics_invalid')
    expected_types = {
        'rgb': IMAGE_TYPE,
        'raw_depth': IMAGE_TYPE,
        'rgb_camera_info': CAMERA_INFO_TYPE,
        'depth_camera_info': CAMERA_INFO_TYPE,
        'tf': TF_TYPE,
        'tf_static': TF_TYPE,
    }
    expected_latching = {
        'rgb_camera_info': True,
        'depth_camera_info': True,
        'tf_static': True,
    }
    expected_topic_keys = {
        'role', 'name', 'type', 'md5sum', 'callerid', 'latching'}
    by_role = {}
    by_name = {}
    for item in entries:
        if not isinstance(item, Mapping) or set(item) != expected_topic_keys:
            raise InspectionError('formal_manifest_topic_entry_invalid')
        role = item.get('role')
        name = item.get('name')
        if (role not in ALL_ROLES or role in by_role
                or not isinstance(name, str) or not name.startswith('/')
                or name in by_name or item.get('type') != expected_types[role]
                or not _lower_sha256(item.get('md5sum'))
                or item.get('callerid') != payload['driver_callerid']
                or item.get('latching')
                is not expected_latching.get(role, False)):
            raise InspectionError(
                'formal_manifest_topic_policy_invalid', str(role))
        by_role[role] = dict(item)
        by_name[name] = dict(item)
    if set(by_role) != set(ALL_ROLES):
        raise InspectionError('formal_manifest_roles_incomplete')
    return {
        **dict(payload),
        'path': str(resolved),
        'size_bytes': resolved.stat().st_size,
        'sha256': actual_sha,
        'topics_by_role': by_role,
        'topics_by_name': by_name,
    }


def load_manifest(path=None) -> Mapping:
    """Load and fully validate the frozen ROS1 camera-only policy."""
    candidate = default_manifest_path() if path is None else Path(path)
    try:
        resolved = candidate.resolve(strict=True)
        raw_text = resolved.read_text(encoding='utf-8')
        payload = _strict_json_loads(raw_text)
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError,
            ValueError) as error:
        raise InspectionError('manifest_invalid', str(error)) from error
    actual_sha = sha256_file(resolved)
    if (resolved.name == EXPECTED_FORMAL_MANIFEST_BASENAME
            or (isinstance(payload, Mapping)
                and payload.get('manifest_id')
                == 'limo-dabai-ros1-formal-four-scene-six-topics-v1')):
        return _validate_formal_manifest_payload(
            candidate, resolved, payload, actual_sha)
    if actual_sha != EXPECTED_MANIFEST_SHA256:
        raise InspectionError(
            'manifest_hash_mismatch', 'manifest is not the frozen artifact')
    expected_keys = {
        'schema_version', 'manifest_id', 'ros_major', 'ros_distro',
        'bag_format', 'inspection_scope', 'read_only', 'authorizes_motion',
        'publishes_ros_messages', 'starts_ros_graph', 'driver_callerid',
        'min_accepted_bundles', 'max_sync_span_sec',
        'max_record_header_skew_sec', 'max_unpaired_rate', 'tf_policy',
        'topics'}
    if (not isinstance(payload, Mapping) or set(payload) != expected_keys
            or payload.get('schema_version') != 1
            or payload.get('manifest_id')
            != 'limo-dabai-ros1-raw-rgbd-six-topics-v1'
            or payload.get('ros_major') != 1
            or payload.get('ros_distro') != 'noetic'
            or payload.get('bag_format') != 'rosbag1-v2'
            or payload.get('inspection_scope')
            != 'sensor_only_short_sample'
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('publishes_ros_messages') is not False
            or payload.get('starts_ros_graph') is not False
            or payload.get('driver_callerid') != '/camera/camera'):
        raise InspectionError('manifest_policy_invalid')
    for key, minimum, maximum in (
            ('min_accepted_bundles', 1, None),
            ('max_sync_span_sec', 0.0, 1.0),
            ('max_record_header_skew_sec', 0.0, 10.0),
            ('max_unpaired_rate', 0.0, 1.0)):
        value = payload.get(key)
        if key == 'min_accepted_bundles':
            valid = (isinstance(value, int) and not isinstance(value, bool)
                     and value >= minimum)
        else:
            valid = (_finite(value) and value >= minimum
                     and (maximum is None or value <= maximum))
        if not valid:
            raise InspectionError('manifest_threshold_invalid', key)
    tf_policy = payload.get('tf_policy')
    tf_keys = {
        'allowed_frame_prefix', 'require_unique_parent_per_child',
        'require_unique_owner_per_child',
        'forbid_static_dynamic_child_overlap', 'forbidden_frame_ids'}
    if (not isinstance(tf_policy, Mapping) or set(tf_policy) != tf_keys
            or tf_policy.get('allowed_frame_prefix') != 'camera'
            or tf_policy.get('require_unique_parent_per_child') is not True
            or tf_policy.get('require_unique_owner_per_child') is not True
            or tf_policy.get('forbid_static_dynamic_child_overlap') is not True
            or not isinstance(tf_policy.get('forbidden_frame_ids'), list)
            or any(not isinstance(value, str) or not value
                   for value in tf_policy['forbidden_frame_ids'])):
        raise InspectionError('manifest_tf_policy_invalid')
    topic_entries = payload.get('topics')
    if not isinstance(topic_entries, list) or len(topic_entries) != 6:
        raise InspectionError('manifest_topics_invalid')
    by_role = {}
    by_name = {}
    expected_types = {
        'rgb': IMAGE_TYPE,
        'raw_depth': IMAGE_TYPE,
        'rgb_camera_info': CAMERA_INFO_TYPE,
        'depth_camera_info': CAMERA_INFO_TYPE,
        'tf': TF_TYPE,
        'tf_static': TF_TYPE,
    }
    expected_latching = {'tf_static': True}
    expected_topic_keys = {
        'role', 'name', 'type', 'md5sum', 'callerid', 'latching'}
    for item in topic_entries:
        if not isinstance(item, Mapping) or set(item) != expected_topic_keys:
            raise InspectionError('manifest_topic_entry_invalid')
        role = item.get('role')
        name = item.get('name')
        if (role not in ALL_ROLES or role in by_role
                or not isinstance(name, str) or not name.startswith('/')
                or name in by_name or item.get('type') != expected_types[role]
                or not _lower_sha256(item.get('md5sum'))
                or item.get('callerid') != payload['driver_callerid']
                or item.get('latching')
                is not expected_latching.get(role, False)):
            raise InspectionError('manifest_topic_policy_invalid', str(role))
        by_role[role] = dict(item)
        by_name[name] = dict(item)
    if set(by_role) != set(ALL_ROLES):
        raise InspectionError('manifest_roles_incomplete')
    return {
        **dict(payload),
        'path': str(resolved),
        'size_bytes': resolved.stat().st_size,
        'sha256': actual_sha,
        'topics_by_role': by_role,
        'topics_by_name': by_name,
    }


def load_formal_manifest(path=None) -> Mapping:
    """Load only the host-anchored formal four-scene manifest."""
    candidate = default_formal_manifest_path() if path is None else Path(path)
    manifest = load_manifest(candidate)
    if manifest.get('inspection_scope') != FORMAL_ACCEPTANCE_MODE:
        raise InspectionError('formal_manifest_scope_invalid')
    return manifest


def _finite(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _lower_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 32
            and value == value.lower()
            and all(character in '0123456789abcdef' for character in value))


def _lower_sha256_digest(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and value == value.lower()
            and all(character in '0123456789abcdef' for character in value))


def _valid_frame_id(value) -> bool:
    if (not isinstance(value, str) or not value or value != value.strip()
            or value.startswith('/')):
        return False
    return all(
        segment not in ('', '.', '..') and _FRAME_SEGMENT.fullmatch(segment)
        for segment in value.split('/'))


def _strict_keys(value, expected, code):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise InspectionError(code)


def _validate_header(value, allow_zero: bool = False) -> Mapping:
    _strict_keys(value, {'stamp_ns', 'frame_id'}, 'header_schema_invalid')
    stamp_ns = value.get('stamp_ns')
    frame_id = value.get('frame_id')
    if (not isinstance(stamp_ns, int) or isinstance(stamp_ns, bool)
            or stamp_ns < (0 if allow_zero else 1)):
        raise InspectionError('header_stamp_invalid')
    if not _valid_frame_id(frame_id):
        raise InspectionError('frame_id_invalid')
    return {'stamp_ns': stamp_ns, 'frame_id': frame_id}


def _validate_image(value, role: str) -> Mapping:
    expected = {
        'header', 'height', 'width', 'encoding', 'is_bigendian', 'step',
        'data_length'}
    _strict_keys(value, expected, 'image_schema_invalid')
    header = _validate_header(value.get('header'))
    height = value.get('height')
    width = value.get('width')
    encoding = value.get('encoding')
    is_bigendian = value.get('is_bigendian')
    step = value.get('step')
    data_length = value.get('data_length')
    allowed = ({'bgr8': 3, 'rgb8': 3, 'rgba8': 4, 'bgra8': 4,
                'mono8': 1} if role == 'rgb'
               else {'16UC1': 2, 'mono16': 2, '32FC1': 4})
    bytes_per_pixel = allowed.get(encoding)
    if (not isinstance(height, int) or isinstance(height, bool) or height <= 0
            or not isinstance(width, int) or isinstance(width, bool)
            or width <= 0 or bytes_per_pixel is None
            or is_bigendian not in (0, 1)
            or not isinstance(step, int) or isinstance(step, bool)
            or step < width * bytes_per_pixel
            or role == 'raw_depth' and step % bytes_per_pixel != 0
            or not isinstance(data_length, int) or isinstance(data_length, bool)
            or data_length != step * height):
        raise InspectionError('image_payload_invalid', role)
    return {
        'header': header,
        'height': height,
        'width': width,
        'encoding': encoding,
        'is_bigendian': is_bigendian,
        'step': step,
        'data_length': data_length,
    }


def _validate_numeric_array(value, length: Optional[int], code: str) -> List[float]:
    if (not isinstance(value, (list, tuple))
            or length is not None and len(value) != length
            or any(not _finite(item) for item in value)):
        raise InspectionError(code)
    return [float(item) for item in value]


def _validate_camera_info(value) -> Mapping:
    expected = {
        'header', 'height', 'width', 'distortion_model', 'D', 'K', 'R', 'P',
        'binning_x', 'binning_y', 'roi'}
    _strict_keys(value, expected, 'camera_info_schema_invalid')
    header = _validate_header(value.get('header'))
    height = value.get('height')
    width = value.get('width')
    distortion_model = value.get('distortion_model')
    distortion = _validate_numeric_array(
        value.get('D'), None, 'camera_info_D_invalid')
    camera_matrix = _validate_numeric_array(
        value.get('K'), 9, 'camera_info_K_invalid')
    rectification = _validate_numeric_array(
        value.get('R'), 9, 'camera_info_R_invalid')
    projection = _validate_numeric_array(
        value.get('P'), 12, 'camera_info_P_invalid')
    binning_x = value.get('binning_x')
    binning_y = value.get('binning_y')
    roi = value.get('roi')
    _strict_keys(
        roi, {'x_offset', 'y_offset', 'height', 'width', 'do_rectify'},
        'camera_info_roi_invalid')
    if (not isinstance(height, int) or isinstance(height, bool) or height <= 0
            or not isinstance(width, int) or isinstance(width, bool)
            or width <= 0 or not isinstance(distortion_model, str)
            or not distortion_model or len(distortion) > 128
            or camera_matrix[0] <= 0.0 or camera_matrix[4] <= 0.0
            or projection[0] <= 0.0 or projection[5] <= 0.0
            or not 0.0 <= camera_matrix[2] < width
            or not 0.0 <= camera_matrix[5] < height
            or not 0.0 <= projection[2] < width
            or not 0.0 <= projection[6] < height
            or not isinstance(binning_x, int) or isinstance(binning_x, bool)
            or not isinstance(binning_y, int) or isinstance(binning_y, bool)
            or binning_x < 0 or binning_y < 0
            or binning_x not in (0,) and binning_x > width
            or binning_y not in (0,) and binning_y > height):
        raise InspectionError('camera_info_intrinsics_invalid')
    for key in ('x_offset', 'y_offset', 'height', 'width'):
        item = roi.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise InspectionError('camera_info_roi_invalid')
    if (not isinstance(roi.get('do_rectify'), bool)
            or roi['x_offset'] + roi['width'] > width
            or roi['y_offset'] + roi['height'] > height):
        raise InspectionError('camera_info_roi_invalid')
    return {
        'header': header,
        'height': height,
        'width': width,
        'distortion_model': distortion_model,
        'D': distortion,
        'K': camera_matrix,
        'R': rectification,
        'P': projection,
        'binning_x': binning_x,
        'binning_y': binning_y,
        'roi': dict(roi),
        'intrinsics': {
            'fx': camera_matrix[0], 'fy': camera_matrix[4],
            'cx': camera_matrix[2], 'cy': camera_matrix[5],
        },
    }


def _validate_tf_message(value, is_static: bool) -> Mapping:
    _strict_keys(value, {'transforms'}, 'tf_message_schema_invalid')
    transforms = value.get('transforms')
    if not isinstance(transforms, list) or not transforms or len(transforms) > 1024:
        raise InspectionError('tf_message_empty_or_oversized')
    result = []
    expected = {
        'header', 'child_frame_id', 'translation_m', 'rotation_xyzw'}
    for item in transforms:
        _strict_keys(item, expected, 'tf_transform_schema_invalid')
        header = _validate_header(item.get('header'), allow_zero=is_static)
        child = item.get('child_frame_id')
        translation = _validate_numeric_array(
            item.get('translation_m'), 3, 'tf_translation_invalid')
        rotation = _validate_numeric_array(
            item.get('rotation_xyzw'), 4, 'tf_rotation_invalid')
        norm = math.sqrt(sum(component * component for component in rotation))
        if (not _valid_frame_id(child) or child == header['frame_id']
                or abs(norm - 1.0) > 1e-3):
            raise InspectionError('tf_transform_invalid')
        result.append({
            'header': header,
            'child_frame_id': child,
            'translation_m': translation,
            'rotation_xyzw': rotation,
        })
    return {'transforms': result}


def _calibration_identity(value: Mapping) -> str:
    canonical = {
        key: value[key] for key in (
            'height', 'width', 'distortion_model', 'D', 'K', 'R', 'P',
            'binning_x', 'binning_y', 'roi')}
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(',', ':'),
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _failure_report(
        source_capture: Mapping, manifest: Mapping, capture_id: str,
        scene: str, error: InspectionError,
        mode: str = FORMAL_MODE) -> Mapping:
    diagnostic = mode == DIAGNOSTIC_MODE
    formal = mode == FORMAL_CAMERA_ONLY_MODE
    if diagnostic:
        report_kind = 'ros1_shared_graph_diagnostic_manifest'
        inspection_scope = DIAGNOSTIC_MODE
    elif formal:
        report_kind = 'formal_rgbd_raw_capture_index'
        inspection_scope = FORMAL_ACCEPTANCE_MODE
    else:
        report_kind = 'ros1_sensor_only_short_sample_index'
        inspection_scope = FORMAL_MODE
    return {
        'schema_version': 1,
        'report_kind': report_kind,
        'inspection_scope': inspection_scope,
        'mode': mode,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'starts_ros_graph': False,
        'storage_identifier': 'rosbag1-v2',
        'indexer_source': indexer_source_identity(),
        'source_capture': dict(source_capture),
        'capture_id': capture_id,
        'scene': scene,
        'expected_topic_manifest': {
            key: manifest.get(key) for key in (
                'path', 'size_bytes', 'sha256', 'manifest_id',
                'schema_version')},
        'inspection_passed': False,
        'diagnostic_completed': False,
        'formal_acceptance': False,
        'shared_graph': diagnostic,
        'mixed_tf': False,
        'not_in_four_scene_denominator': diagnostic or formal,
        'delivery_ready': False,
        'failures': [error.code],
        'failure_details': [{'code': error.code, 'detail': error.detail}],
        'limitations': (
            ['formal_scene_rejected', 'not_in_four_scene_denominator']
            if formal else ['sensor_only_short_sample_not_formal_delivery']),
    }


def _connection_signature(
        topic: str, datatype: str, md5sum: str,
        callerid: str, latching: Optional[bool]) -> Tuple:
    return topic, datatype, md5sum, callerid, latching


def _validate_connections(
        connections: Sequence[Mapping], manifest: Mapping
        ) -> Tuple[List[Mapping], Mapping[int, Mapping]]:
    if not isinstance(connections, Sequence) or isinstance(connections, str):
        raise InspectionError('connections_invalid')
    expected_by_name = manifest['topics_by_name']
    seen_ids = set()
    seen_signatures = set()
    by_topic: Dict[str, List[Mapping]] = {}
    normalized = []
    for raw in connections:
        required = {
            'connection_id', 'topic', 'type', 'md5sum', 'callerid',
            'latching'}
        if not isinstance(raw, Mapping) or not required.issubset(raw):
            raise InspectionError('connection_schema_invalid')
        connection_id = raw.get('connection_id')
        topic = raw.get('topic')
        datatype = raw.get('type')
        md5sum = raw.get('md5sum')
        callerid = raw.get('callerid')
        latching = raw.get('latching')
        if (not isinstance(connection_id, int) or isinstance(connection_id, bool)
                or connection_id < 0 or connection_id in seen_ids):
            raise InspectionError('connection_id_invalid')
        if topic not in expected_by_name:
            raise InspectionError('unexpected_topic', str(topic))
        expected = expected_by_name[topic]
        if datatype != expected['type']:
            raise InspectionError('connection_type_mismatch', topic)
        if md5sum != expected['md5sum']:
            raise InspectionError('connection_md5_mismatch', topic)
        if callerid != expected['callerid']:
            raise InspectionError('connection_callerid_mismatch', topic)
        if not isinstance(latching, bool) or latching is not expected['latching']:
            raise InspectionError('connection_latching_mismatch', topic)
        signature = _connection_signature(
            topic, datatype, md5sum, callerid, latching)
        if signature in seen_signatures:
            raise InspectionError('duplicate_connection', topic)
        seen_ids.add(connection_id)
        seen_signatures.add(signature)
        item = {
            'connection_id': connection_id,
            'topic': topic,
            'role': expected['role'],
            'type': datatype,
            'md5sum': md5sum,
            'callerid': callerid,
            'latching': latching,
            'message_count': 0,
            'first_record_timestamp_ns': None,
            'last_record_timestamp_ns': None,
        }
        if 'connection_header' in raw:
            header = raw.get('connection_header')
            header_sha = raw.get('connection_header_sha256')
            if (not isinstance(header, Mapping)
                    or not _lower_sha256_digest(header_sha)
                    or _canonical_mapping_sha256(header) != header_sha):
                raise InspectionError(
                    'connection_header_evidence_invalid', topic)
            item['connection_header'] = dict(header)
            item['connection_header_sha256'] = header_sha
        if raw.get('connection_header_violations'):
            raise InspectionError('connection_header_policy_invalid', topic)
        normalized.append(item)
        by_topic.setdefault(topic, []).append(item)
    if set(by_topic) != set(expected_by_name):
        missing = sorted(set(expected_by_name).difference(by_topic))
        raise InspectionError('missing_topic_connection', ','.join(missing))
    for topic, values in by_topic.items():
        if len(values) != 1:
            raise InspectionError('cross_connection_topic', topic)
    by_id = {item['connection_id']: item for item in normalized}
    return sorted(normalized, key=lambda item: item['connection_id']), by_id


def _read_messages(
        raw_messages: Sequence[Mapping], connections: Sequence[Mapping],
        connection_by_id: Mapping[int, Mapping], manifest: Mapping
        ) -> Tuple[List[Mapping], Mapping[str, List[Mapping]]]:
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, str):
        raise InspectionError('messages_invalid')
    last_record_by_connection = {}
    stream_messages = {role: [] for role in STREAM_ROLES}
    result = []
    for message_id, raw in enumerate(raw_messages, start=1):
        required = {
            'connection_id', 'record_timestamp_ns', 'serialized_payload',
            'decoded'}
        if not isinstance(raw, Mapping) or not required.issubset(raw):
            raise InspectionError('message_schema_invalid')
        connection_id = raw.get('connection_id')
        if connection_id not in connection_by_id:
            raise InspectionError('message_unknown_connection')
        connection = connection_by_id[connection_id]
        record_stamp = raw.get('record_timestamp_ns')
        payload = raw.get('serialized_payload')
        if (not isinstance(record_stamp, int) or isinstance(record_stamp, bool)
                or record_stamp <= 0):
            raise InspectionError('record_timestamp_invalid')
        previous = last_record_by_connection.get(connection_id)
        if previous is not None and record_stamp <= previous:
            raise InspectionError('record_timestamp_not_increasing')
        if not isinstance(payload, bytes) or not payload:
            raise InspectionError('serialized_payload_invalid')
        role = connection['role']
        if role in ('rgb', 'raw_depth'):
            decoded = _validate_image(raw.get('decoded'), role)
            header_stamps = [decoded['header']['stamp_ns']]
        elif role in ('rgb_camera_info', 'depth_camera_info'):
            decoded = _validate_camera_info(raw.get('decoded'))
            header_stamps = [decoded['header']['stamp_ns']]
        else:
            decoded = _validate_tf_message(
                raw.get('decoded'), role == 'tf_static')
            header_stamps = [
                transform['header']['stamp_ns']
                for transform in decoded['transforms']]
        skews = [(record_stamp - stamp) / 1e9 for stamp in header_stamps]
        if role == 'tf_static':
            if any(skew < 0.0 for skew in skews):
                raise InspectionError('static_tf_from_future')
        elif any(skew < 0.0 or skew > manifest[
                'max_record_header_skew_sec'] for skew in skews):
            raise InspectionError('record_header_skew_invalid', role)
        last_record_by_connection[connection_id] = record_stamp
        connection['message_count'] += 1
        if connection['first_record_timestamp_ns'] is None:
            connection['first_record_timestamp_ns'] = record_stamp
        connection['last_record_timestamp_ns'] = record_stamp
        item = {
            'message_id': message_id,
            'connection_id': connection_id,
            'topic': connection['topic'],
            'role': role,
            'callerid': connection['callerid'],
            'record_timestamp_ns': record_stamp,
            'serialized_size_bytes': len(payload),
            'serialized_sha256': hashlib.sha256(payload).hexdigest(),
            'record_header_skew_sec': max(skews) if skews else None,
            'decoded': decoded,
        }
        if 'connection_header' in raw:
            item['connection_header'] = dict(raw['connection_header'])
            item['connection_header_sha256'] = raw.get(
                'connection_header_sha256')
        result.append(item)
        if role in STREAM_ROLES:
            stream_messages[role].append(item)
    if any(connection['message_count'] <= 0 for connection in connections):
        missing = [
            connection['topic'] for connection in connections
            if connection['message_count'] <= 0]
        raise InspectionError('connection_has_no_messages', ','.join(missing))
    return result, stream_messages


def _validate_streams(streams: Mapping[str, Sequence[Mapping]]) -> Mapping:
    summaries = {}
    for role in STREAM_ROLES:
        values = streams.get(role)
        if not isinstance(values, list) or not values:
            raise InspectionError('stream_missing', role)
        stamps = [item['decoded']['header']['stamp_ns'] for item in values]
        if any(current <= previous for previous, current in zip(
                stamps, stamps[1:])):
            raise InspectionError('stream_header_not_increasing', role)
        frames = {item['decoded']['header']['frame_id'] for item in values}
        grids = {(item['decoded']['width'], item['decoded']['height'])
                 for item in values}
        if len(frames) != 1:
            raise InspectionError('stream_frame_changed', role)
        if len(grids) != 1:
            raise InspectionError('stream_resolution_changed', role)
        summary = {
            'topic': values[0]['topic'],
            'message_type': (
                IMAGE_TYPE if role in ('rgb', 'raw_depth')
                else CAMERA_INFO_TYPE),
            'message_count': len(values),
            'frame_id': next(iter(frames)),
            'width': next(iter(grids))[0],
            'height': next(iter(grids))[1],
            'first_stamp_ns': stamps[0],
            'last_stamp_ns': stamps[-1],
        }
        if role in ('rgb', 'raw_depth'):
            encodings = {item['decoded']['encoding'] for item in values}
            if len(encodings) != 1:
                raise InspectionError('stream_encoding_changed', role)
            summary['encoding'] = next(iter(encodings))
        else:
            calibrations = {
                _calibration_identity(item['decoded']) for item in values}
            if len(calibrations) != 1:
                raise InspectionError('camera_info_changed', role)
            summary['calibration_sha256'] = next(iter(calibrations))
            summary['intrinsics'] = dict(values[0]['decoded']['intrinsics'])
        summaries[role] = summary
    for image_role, info_role in (
            ('rgb', 'rgb_camera_info'),
            ('raw_depth', 'depth_camera_info')):
        image = summaries[image_role]
        info = summaries[info_role]
        if image['frame_id'] != info['frame_id']:
            raise InspectionError(
                'image_camera_info_frame_mismatch', image_role)
        if (image['width'], image['height']) != (info['width'], info['height']):
            raise InspectionError(
                'image_camera_info_resolution_mismatch', image_role)
    # Raw depth is deliberately permitted to use a different frame and grid
    # from RGB in sensor_only_short_sample mode.
    return summaries


def _accepted_bundles(
        streams: Mapping[str, Sequence[Mapping]], max_sync_span_sec: float
        ) -> Tuple[List[Mapping], Mapping]:
    used = {role: set() for role in STREAM_ROLES if role != 'rgb'}
    last_selected_stamp = {
        role: None for role in STREAM_ROLES if role != 'rgb'}
    accepted = []
    rejected = {'missing_stream': 0, 'over_sync_span': 0}
    for anchor in streams['rgb']:
        selected = {'rgb': anchor}
        for role in STREAM_ROLES[1:]:
            candidates = [
                message for message in streams[role]
                if (message['message_id'] not in used[role]
                    and (last_selected_stamp[role] is None
                         or message['decoded']['header']['stamp_ns']
                         > last_selected_stamp[role]))]
            if not candidates:
                selected = {}
                rejected['missing_stream'] += 1
                break
            anchor_stamp = anchor['decoded']['header']['stamp_ns']
            ranked = sorted(candidates, key=lambda message: (
                abs(message['decoded']['header']['stamp_ns'] - anchor_stamp),
                message['decoded']['header']['stamp_ns'],
                message['message_id']))
            if (len(ranked) > 1
                    and abs(ranked[0]['decoded']['header']['stamp_ns']
                            - anchor_stamp)
                    == abs(ranked[1]['decoded']['header']['stamp_ns']
                           - anchor_stamp)):
                raise InspectionError('ambiguous_stream_pairing', role)
            selected[role] = ranked[0]
        if len(selected) != len(STREAM_ROLES):
            continue
        header_stamps = {
            role: selected[role]['decoded']['header']['stamp_ns']
            for role in STREAM_ROLES}
        span = (max(header_stamps.values()) - min(header_stamps.values())) / 1e9
        record_stamps = {
            role: selected[role]['record_timestamp_ns'] for role in STREAM_ROLES}
        record_span = (
            max(record_stamps.values()) - min(record_stamps.values())) / 1e9
        if span > max_sync_span_sec or record_span > max_sync_span_sec:
            rejected['over_sync_span'] += 1
            continue
        for role in STREAM_ROLES[1:]:
            used[role].add(selected[role]['message_id'])
            last_selected_stamp[role] = header_stamps[role]
        accepted.append({
            'index': len(accepted),
            **{role: selected[role]['message_id'] for role in STREAM_ROLES},
            'header_stamps_ns': header_stamps,
            'stream_payload_sha256': {
                role: selected[role]['serialized_sha256']
                for role in STREAM_ROLES},
            'stream_serialized_size_bytes': {
                role: selected[role]['serialized_size_bytes']
                for role in STREAM_ROLES},
            'stream_record_timestamps_ns': record_stamps,
            'record_timestamp_span_sec': record_span,
            'stamp_span_sec': span,
        })
    candidate_count = len(streams['rgb'])
    rejected_count = candidate_count - len(accepted)
    if sum(rejected.values()) != rejected_count:
        raise InspectionError('pairing_accounting_invalid')
    unmatched = {
        role: len(streams[role]) - len(accepted) for role in STREAM_ROLES}
    total = sum(len(streams[role]) for role in STREAM_ROLES)
    unpaired = total - len(accepted) * len(STREAM_ROLES)
    return accepted, {
        'rgb_candidate_count': candidate_count,
        'accepted_bundle_count': len(accepted),
        'rejected_rgb_count': rejected_count,
        'rejection_reasons': rejected,
        'unmatched_message_count_by_stream': unmatched,
        'total_stream_message_count': total,
        'total_unpaired_message_count': unpaired,
        'total_unpaired_rate': unpaired / total if total else None,
    }


def _camera_frame_allowed(frame_id: str, policy: Mapping) -> bool:
    if frame_id in set(policy['forbidden_frame_ids']):
        return False
    prefix = policy['allowed_frame_prefix']
    return all(
        segment == prefix or segment.startswith(prefix + '_')
        for segment in frame_id.split('/'))


def _has_cycle(adjacency: Mapping[str, set]) -> bool:
    seen = set()
    for root in adjacency:
        if root in seen:
            continue
        pending = [(root, None)]
        while pending:
            node, parent = pending.pop()
            if node in seen:
                return True
            seen.add(node)
            for neighbour in adjacency.get(node, set()):
                if neighbour != parent:
                    pending.append((neighbour, node))
    return False


def _path_count(adjacency: Mapping[str, set], start: str, goal: str) -> int:
    if start == goal:
        return 1
    count = 0
    pending = [(start, (start,))]
    while pending:
        node, path = pending.pop()
        for neighbour in adjacency.get(node, set()):
            if neighbour in path:
                continue
            if neighbour == goal:
                count += 1
            else:
                pending.append((neighbour, path + (neighbour,)))
            if count > 1:
                return count
    return count


def _validate_tf_graph(
        messages: Sequence[Mapping], stream_summaries: Mapping,
        manifest: Mapping) -> Mapping:
    policy = manifest['tf_policy']
    transforms = []
    child_policy = {}
    static_children = set()
    dynamic_children = set()
    dynamic_last_stamp = {}
    dynamic_baseline = {}
    adjacency: Dict[str, set] = {}
    topic_counts = {'/tf': 0, '/tf_static': 0}
    for message in messages:
        if message['role'] not in TF_ROLES:
            continue
        topic = message['topic']
        is_static = message['role'] == 'tf_static'
        for index, transform in enumerate(message['decoded']['transforms']):
            parent = transform['header']['frame_id']
            child = transform['child_frame_id']
            stamp = transform['header']['stamp_ns']
            if (not _camera_frame_allowed(parent, policy)
                    or not _camera_frame_allowed(child, policy)):
                raise InspectionError('non_camera_tf_frame', parent + '->' + child)
            owner_key = (parent, message['callerid'])
            previous_owner = child_policy.get(child)
            if previous_owner is not None and previous_owner != owner_key:
                if previous_owner[0] != parent:
                    raise InspectionError('tf_child_multiple_parents', child)
                raise InspectionError('tf_child_multiple_owners', child)
            child_policy[child] = owner_key
            if is_static:
                if child in dynamic_children:
                    raise InspectionError('tf_child_static_dynamic_overlap', child)
                if child in static_children:
                    raise InspectionError('duplicate_static_tf', child)
                static_children.add(child)
            else:
                if child in static_children:
                    raise InspectionError('tf_child_static_dynamic_overlap', child)
                dynamic_children.add(child)
                edge = (parent, child)
                previous_stamp = dynamic_last_stamp.get(edge)
                if previous_stamp is not None and stamp <= previous_stamp:
                    raise InspectionError('dynamic_tf_stamp_not_increasing', child)
                dynamic_last_stamp[edge] = stamp
                values = tuple(
                    transform['translation_m'] + transform['rotation_xyzw'])
                baseline = dynamic_baseline.get(edge)
                if baseline is not None and any(
                        abs(first - second) > 1e-9
                        for first, second in zip(baseline, values)):
                    raise InspectionError('dynamic_camera_tf_changed', child)
                dynamic_baseline[edge] = values
            adjacency.setdefault(parent, set()).add(child)
            adjacency.setdefault(child, set()).add(parent)
            topic_counts[topic] += 1
            transforms.append({
                'topic': topic,
                'message_id': message['message_id'],
                'connection_id': message['connection_id'],
                'transform_index': index,
                'callerid': message['callerid'],
                'stamp_ns': stamp,
                'parent_frame_id': parent,
                'child_frame_id': child,
                'translation_m': transform['translation_m'],
                'rotation_xyzw': transform['rotation_xyzw'],
                'serialized_sha256': message['serialized_sha256'],
            })
    if topic_counts['/tf'] <= 0 or topic_counts['/tf_static'] <= 0:
        raise InspectionError('tf_topic_payload_missing')
    if _has_cycle(adjacency):
        raise InspectionError('tf_graph_cycle')
    rgb_frame = stream_summaries['rgb']['frame_id']
    depth_frame = stream_summaries['raw_depth']['frame_id']
    if rgb_frame not in adjacency or depth_frame not in adjacency:
        raise InspectionError('stream_frame_missing_from_tf')
    if _path_count(adjacency, rgb_frame, depth_frame) != 1:
        raise InspectionError('rgb_depth_tf_path_not_unique')
    return {
        'camera_only': True,
        'base_chain_required': False,
        'rgb_frame': rgb_frame,
        'raw_depth_frame': depth_frame,
        'transform_count': len(transforms),
        'dynamic_child_frames': sorted(dynamic_children),
        'static_child_frames': sorted(static_children),
        'child_owners': {
            child: {'parent_frame_id': value[0], 'callerid': value[1]}
            for child, value in sorted(child_policy.items())},
        'transforms': transforms,
    }


def _inspect_records(
        connections: Sequence[Mapping], raw_messages: Sequence[Mapping],
        capture_id: str, scene: str, manifest: Mapping,
        source_capture: Mapping) -> Mapping:
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise InspectionError('capture_id_invalid')
    if not isinstance(scene, str) or not scene.strip():
        raise InspectionError('scene_invalid')
    topics, connection_by_id = _validate_connections(connections, manifest)
    messages, streams = _read_messages(
        raw_messages, topics, connection_by_id, manifest)
    stream_summaries = _validate_streams(streams)
    bundles, pairing = _accepted_bundles(
        streams, manifest['max_sync_span_sec'])
    if pairing['rejection_reasons']['missing_stream']:
        raise InspectionError('pairing_stream_missing')
    if pairing['rejection_reasons']['over_sync_span']:
        raise InspectionError('pairing_over_sync_window')
    if len(bundles) < manifest['min_accepted_bundles']:
        raise InspectionError('accepted_bundle_count_below_minimum')
    if (pairing['total_unpaired_rate'] is None
            or pairing['total_unpaired_rate'] > manifest['max_unpaired_rate']):
        raise InspectionError('stream_unpaired_rate_exceeded')
    tf_graph = _validate_tf_graph(messages, stream_summaries, manifest)
    return {
        'schema_version': 1,
        'report_kind': 'ros1_sensor_only_short_sample_index',
        'inspection_scope': manifest['inspection_scope'],
        'mode': FORMAL_MODE,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'starts_ros_graph': False,
        'storage_identifier': 'rosbag1-v2',
        'indexer_source': indexer_source_identity(),
        'timestamp_semantics': {
            'record_timestamp': 'rosbag1_recorder_receive_time',
            'pairing_and_sync': 'decoded_ros_header_stamp',
        },
        'source_capture': dict(source_capture),
        'capture_id': capture_id,
        'scene': scene,
        'expected_topic_manifest': {
            key: manifest[key] for key in (
                'path', 'size_bytes', 'sha256', 'manifest_id',
                'schema_version')},
        'stream_topics': {
            role: manifest['topics_by_role'][role]['name']
            for role in STREAM_ROLES},
        'topics': topics,
        'messages': messages,
        'streams': stream_summaries,
        **pairing,
        'unique_header_pair_count': len(bundles),
        'formal_contract_valid_pair_count': len(bundles),
        'accepted_bundles': bundles,
        'tf_graph': tf_graph,
        'inspection_passed': True,
        'diagnostic_completed': False,
        'formal_acceptance': False,
        'shared_graph': False,
        'mixed_tf': False,
        'not_in_four_scene_denominator': True,
        'delivery_ready': False,
        'failures': [],
        'limitations': [
            'sensor_only_short_sample_not_formal_delivery',
            'raw_depth_may_differ_from_rgb_frame_and_resolution',
            'base_to_camera_extrinsics_not_evaluated',
        ],
    }


def _append_diagnostic_issue(
        issues: List[Mapping], code: str, detail: str = '',
        context: Mapping = None) -> None:
    item = {'code': code, 'detail': detail or code}
    if context:
        item['context'] = dict(context)
    canonical = json.dumps(
        item, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if all(json.dumps(
            existing, sort_keys=True, separators=(',', ':'),
            allow_nan=False) != canonical for existing in issues):
        issues.append(item)


def _diagnostic_connections(
        connections: Sequence[Mapping], manifest: Mapping,
        issues: List[Mapping]
        ) -> Tuple[List[Mapping], Mapping[int, Mapping]]:
    normalized = []
    by_id = {}
    by_topic: Dict[str, List[Mapping]] = {}
    expected_by_name = manifest['topics_by_name']
    if not isinstance(connections, Sequence) or isinstance(connections, str):
        _append_diagnostic_issue(issues, 'connections_invalid')
        return normalized, by_id
    for ordinal, raw in enumerate(connections):
        if not isinstance(raw, Mapping):
            _append_diagnostic_issue(
                issues, 'connection_schema_invalid', str(ordinal))
            continue
        connection_id = raw.get('connection_id')
        topic = raw.get('topic')
        datatype = raw.get('type')
        md5sum = raw.get('md5sum')
        callerid = raw.get('callerid')
        latching = raw.get('latching')
        local_failures = []

        def fail(code, detail=''):
            local_failures.append(code)
            _append_diagnostic_issue(
                issues, code, detail or str(topic), {
                    'connection_id': connection_id,
                    'topic': topic})

        if (not isinstance(connection_id, int) or isinstance(connection_id, bool)
                or connection_id < 0 or connection_id in by_id):
            fail('connection_id_invalid', str(connection_id))
        expected = expected_by_name.get(topic)
        if expected is None:
            fail('unexpected_topic', str(topic))
            role = None
        else:
            role = expected['role']
            if datatype != expected['type']:
                fail('connection_type_mismatch')
            if md5sum != expected['md5sum']:
                fail('connection_md5_mismatch')
            if callerid != expected['callerid']:
                fail('connection_callerid_mismatch')
            if (not isinstance(latching, bool)
                    or latching is not expected['latching']):
                fail('connection_latching_mismatch')
        header = raw.get('connection_header')
        header_sha = raw.get('connection_header_sha256')
        if not isinstance(header, Mapping):
            fail('connection_header_evidence_missing')
            header = None
            header_sha = None
        elif (not _lower_sha256_digest(header_sha)
                or _canonical_mapping_sha256(header) != header_sha):
            fail('connection_header_evidence_invalid')
        for violation in raw.get('connection_header_violations', []):
            if isinstance(violation, Mapping):
                fail(
                    str(violation.get('code', 'connection_header_policy_invalid')),
                    str(violation.get('detail', topic)))
            else:
                fail('connection_header_policy_invalid', str(violation))
        item = {
            'connection_id': connection_id,
            'topic': topic,
            'role': role,
            'type': datatype,
            'md5sum': md5sum,
            'callerid': callerid,
            'latching': latching,
            'connection_header': dict(header) if header is not None else None,
            'connection_header_sha256': header_sha,
            'message_count': 0,
            'first_record_timestamp_ns': None,
            'last_record_timestamp_ns': None,
            'formal_valid': not local_failures,
            'validation_failures': sorted(set(local_failures)),
        }
        normalized.append(item)
        if isinstance(connection_id, int) and connection_id not in by_id:
            by_id[connection_id] = item
        if isinstance(topic, str):
            by_topic.setdefault(topic, []).append(item)
    for topic in sorted(set(expected_by_name).difference(by_topic)):
        _append_diagnostic_issue(
            issues, 'missing_topic_connection', topic, {'topic': topic})
    for topic, values in sorted(by_topic.items()):
        if topic in expected_by_name and len(values) != 1:
            _append_diagnostic_issue(
                issues, 'cross_connection_topic', topic, {
                    'topic': topic, 'connection_count': len(values)})
            for item in values:
                item['formal_valid'] = False
                if 'cross_connection_topic' not in item['validation_failures']:
                    item['validation_failures'].append('cross_connection_topic')
    return sorted(
        normalized,
        key=lambda item: (
            item['connection_id'] if isinstance(item['connection_id'], int)
            else -1, str(item['topic']))), by_id


def _permissive_header(decoded) -> Tuple[Optional[int], str]:
    if not isinstance(decoded, Mapping):
        return None, ''
    header = decoded.get('header')
    if not isinstance(header, Mapping):
        return None, ''
    stamp = header.get('stamp_ns')
    if not isinstance(stamp, int) or isinstance(stamp, bool) or stamp <= 0:
        stamp = None
    frame_id = header.get('frame_id')
    if not isinstance(frame_id, str):
        frame_id = ''
    return stamp, frame_id


def _diagnostic_capture_window(
        raw_messages: Sequence[Mapping], connection_by_id: Mapping[int, Mapping]
        ) -> Mapping:
    header_stamps = []
    record_stamps = []
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, str):
        return {
            'header_start_ns': None, 'header_end_ns': None,
            'record_start_ns': None, 'record_end_ns': None}
    for raw in raw_messages:
        if not isinstance(raw, Mapping):
            continue
        connection = connection_by_id.get(raw.get('connection_id'))
        if not connection or connection.get('role') not in ('rgb', 'raw_depth'):
            continue
        header_stamp, _frame = _permissive_header(raw.get('decoded'))
        record_stamp = raw.get('record_timestamp_ns')
        if header_stamp is not None:
            header_stamps.append(header_stamp)
        if (isinstance(record_stamp, int) and not isinstance(record_stamp, bool)
                and record_stamp > 0):
            record_stamps.append(record_stamp)
    return {
        'header_start_ns': min(header_stamps) if header_stamps else None,
        'header_end_ns': max(header_stamps) if header_stamps else None,
        'record_start_ns': min(record_stamps) if record_stamps else None,
        'record_end_ns': max(record_stamps) if record_stamps else None,
    }


def _diagnostic_messages(
        raw_messages: Sequence[Mapping], connections: Sequence[Mapping],
        connection_by_id: Mapping[int, Mapping], manifest: Mapping,
        capture_window: Mapping, issues: List[Mapping]
        ) -> Tuple[List[Mapping], Mapping[str, List[Mapping]], List[Mapping]]:
    results = []
    streams = {role: [] for role in STREAM_ROLES}
    isolated = []
    last_record_by_connection = {}
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, str):
        _append_diagnostic_issue(issues, 'messages_invalid')
        return results, streams, isolated
    for message_id, raw in enumerate(raw_messages, start=1):
        if not isinstance(raw, Mapping):
            _append_diagnostic_issue(
                issues, 'message_schema_invalid', str(message_id))
            continue
        connection_id = raw.get('connection_id')
        connection = connection_by_id.get(connection_id)
        topic = connection.get('topic') if connection else None
        role = connection.get('role') if connection else None
        callerid = connection.get('callerid') if connection else None
        record_stamp = raw.get('record_timestamp_ns')
        payload = raw.get('serialized_payload')
        decoded = raw.get('decoded')
        local_failures = []

        def fail(code, detail=''):
            local_failures.append(code)
            _append_diagnostic_issue(
                issues, code, detail or str(role or topic or message_id), {
                    'message_id': message_id,
                    'connection_id': connection_id,
                    'topic': topic})

        if connection is None:
            fail('message_unknown_connection', str(connection_id))
        if (not isinstance(record_stamp, int) or isinstance(record_stamp, bool)
                or record_stamp <= 0):
            fail('record_timestamp_invalid')
        elif connection is not None:
            previous = last_record_by_connection.get(connection_id)
            if previous is not None and record_stamp <= previous:
                fail('record_timestamp_not_increasing')
            last_record_by_connection[connection_id] = record_stamp
            connection['message_count'] += 1
            if connection['first_record_timestamp_ns'] is None:
                connection['first_record_timestamp_ns'] = record_stamp
            connection['last_record_timestamp_ns'] = record_stamp
        if not isinstance(payload, bytes) or not payload:
            fail('serialized_payload_invalid')
            payload_sha = None
            payload_size = 0
        else:
            payload_sha = hashlib.sha256(payload).hexdigest()
            payload_size = len(payload)
        for violation in raw.get('connection_header_violations', []):
            if isinstance(violation, Mapping):
                fail(
                    str(violation.get('code', 'connection_header_policy_invalid')),
                    str(violation.get('detail', topic)))
        message_header = raw.get('connection_header')
        message_header_sha = raw.get('connection_header_sha256')
        if message_header is not None:
            if (not isinstance(message_header, Mapping)
                    or not _lower_sha256_digest(message_header_sha)
                    or _canonical_mapping_sha256(message_header)
                    != message_header_sha):
                fail('message_connection_header_evidence_invalid')
            elif (connection is not None
                  and connection.get('connection_header_sha256') is not None
                  and message_header_sha
                  != connection.get('connection_header_sha256')):
                fail('message_connection_header_mismatch')
        decode_error = raw.get('decode_error')
        if isinstance(decode_error, Mapping):
            fail(
                str(decode_error.get('code', 'ros_message_deserialize_failed')),
                str(decode_error.get('detail', topic)))

        header_stamp, frame_id = _permissive_header(decoded)
        isolated_reason = None
        if (role in ('rgb_camera_info', 'depth_camera_info')
                and connection is not None
                and connection.get('latching') is True
                and header_stamp is not None
                and isinstance(record_stamp, int)):
            skew_ns = record_stamp - header_stamp
            capture_start = capture_window.get('header_start_ns')
            before_window = (
                isinstance(capture_start, int)
                and header_stamp < capture_start
                - int(manifest['max_sync_span_sec'] * 1e9))
            if (skew_ns > int(
                    manifest['max_record_header_skew_sec'] * 1e9)
                    or before_window):
                isolated_reason = 'old_latched_camera_info_before_capture_window'
        validated = None
        if isolated_reason is None and decode_error is None:
            try:
                if role in ('rgb', 'raw_depth'):
                    validated = _validate_image(decoded, role)
                elif role in ('rgb_camera_info', 'depth_camera_info'):
                    validated = _validate_camera_info(decoded)
                elif role in TF_ROLES:
                    validated = _validate_tf_message(
                        decoded, role == 'tf_static')
                elif role is None:
                    fail('unsupported_diagnostic_topic', str(topic))
            except InspectionError as error:
                fail(error.code, error.detail)
        header_stamps = []
        if header_stamp is not None:
            header_stamps.append(header_stamp)
        elif role in TF_ROLES and isinstance(decoded, Mapping):
            for transform in decoded.get('transforms', []):
                if isinstance(transform, Mapping):
                    transform_header = transform.get('header')
                    if isinstance(transform_header, Mapping):
                        transform_stamp = transform_header.get('stamp_ns')
                        if (isinstance(transform_stamp, int)
                                and not isinstance(transform_stamp, bool)):
                            header_stamps.append(transform_stamp)
        skew_values = []
        if (isolated_reason is None and isinstance(record_stamp, int)
                and role is not None):
            skew_values = [
                (record_stamp - stamp) / 1e9 for stamp in header_stamps]
            if role == 'tf_static':
                if any(skew < 0.0 for skew in skew_values):
                    fail('static_tf_from_future')
            elif any(
                    skew < 0.0
                    or skew > manifest['max_record_header_skew_sec']
                    for skew in skew_values):
                fail('record_header_skew_invalid', role)
        item = {
            'message_id': message_id,
            'connection_id': connection_id,
            'topic': topic,
            'role': role,
            'callerid': callerid,
            'record_timestamp_ns': record_stamp,
            'serialized_size_bytes': payload_size,
            'serialized_sha256': payload_sha,
            'record_header_skew_sec': (
                max(skew_values) if skew_values else None),
            'connection_header': (
                dict(message_header) if isinstance(message_header, Mapping)
                else None),
            'connection_header_sha256': message_header_sha,
            'decoded': (
                validated if validated is not None else decoded),
            'isolated': isolated_reason is not None,
            'isolation_reason': isolated_reason,
            'formal_valid': (
                isolated_reason is None and not local_failures
                and connection is not None
                and connection.get('formal_valid') is True),
            'validation_failures': sorted(set(local_failures)),
        }
        results.append(item)
        if isolated_reason is not None:
            isolation = {
                'message_id': message_id,
                'connection_id': connection_id,
                'topic': topic,
                'role': role,
                'callerid': callerid,
                'record_timestamp_ns': record_stamp,
                'header_stamp_ns': header_stamp,
                'frame_id': frame_id,
                'serialized_size_bytes': payload_size,
                'serialized_sha256': payload_sha,
                'connection_header_sha256': message_header_sha,
                'reason': isolated_reason,
            }
            isolated.append(isolation)
            _append_diagnostic_issue(
                issues, isolated_reason, role, {
                    'message_id': message_id,
                    'connection_id': connection_id})
        elif (role in STREAM_ROLES and header_stamp is not None
              and isinstance(record_stamp, int) and payload_sha is not None):
            streams[role].append(item)
    for connection in connections:
        if connection.get('message_count', 0) <= 0:
            _append_diagnostic_issue(
                issues, 'connection_has_no_messages',
                str(connection.get('topic')), {
                    'connection_id': connection.get('connection_id'),
                    'topic': connection.get('topic')})
            connection['formal_valid'] = False
            if 'connection_has_no_messages' not in connection[
                    'validation_failures']:
                connection['validation_failures'].append(
                    'connection_has_no_messages')
    return results, streams, isolated


def _deduplicate_diagnostic_streams(
        streams: Mapping[str, List[Mapping]], issues: List[Mapping]
        ) -> Mapping[str, List[Mapping]]:
    result = {role: [] for role in STREAM_ROLES}
    for role in STREAM_ROLES:
        seen = set()
        previous_stamp = None
        for item in streams.get(role, []):
            stamp = item['decoded']['header']['stamp_ns']
            key = (
                item['connection_id'], stamp, item['serialized_sha256'])
            if key in seen:
                item['formal_valid'] = False
                item['validation_failures'] = sorted(set(
                    item['validation_failures'] + ['duplicate_stream_message']))
                _append_diagnostic_issue(
                    issues, 'duplicate_stream_message', role, {
                        'message_id': item['message_id'], 'role': role})
                continue
            seen.add(key)
            if previous_stamp is not None and stamp <= previous_stamp:
                item['formal_valid'] = False
                item['validation_failures'] = sorted(set(
                    item['validation_failures']
                    + ['stream_header_not_increasing']))
                _append_diagnostic_issue(
                    issues, 'stream_header_not_increasing', role, {
                        'message_id': item['message_id'], 'role': role})
            previous_stamp = stamp
            result[role].append(item)
    return result


def _diagnostic_pairs(
        streams: Mapping[str, List[Mapping]], manifest: Mapping,
        issues: List[Mapping]) -> Tuple[List[Mapping], Mapping]:
    try:
        bundles, pairing = _accepted_bundles(
            streams, manifest['max_sync_span_sec'])
    except InspectionError as error:
        _append_diagnostic_issue(issues, error.code, error.detail)
        total = sum(len(streams.get(role, [])) for role in STREAM_ROLES)
        return [], {
            'rgb_candidate_count': len(streams.get('rgb', [])),
            'accepted_bundle_count': 0,
            'rejected_rgb_count': len(streams.get('rgb', [])),
            'rejection_reasons': {'missing_stream': 0, 'over_sync_span': 0},
            'unmatched_message_count_by_stream': {
                role: len(streams.get(role, [])) for role in STREAM_ROLES},
            'total_stream_message_count': total,
            'total_unpaired_message_count': total,
            'total_unpaired_rate': 1.0 if total else None,
        }
    if not all(streams.get(role) for role in STREAM_ROLES):
        _append_diagnostic_issue(issues, 'pairing_stream_missing')
    if len(bundles) < manifest['min_accepted_bundles']:
        _append_diagnostic_issue(
            issues, 'accepted_bundle_count_below_minimum', str(len(bundles)))
    if (pairing['total_unpaired_rate'] is None
            or pairing['total_unpaired_rate'] > manifest['max_unpaired_rate']):
        _append_diagnostic_issue(
            issues, 'stream_unpaired_rate_exceeded',
            str(pairing['total_unpaired_rate']))
    by_message_id = {
        item['message_id']: item
        for role in STREAM_ROLES for item in streams.get(role, [])}
    calibration_sets = {}
    for role in ('rgb_camera_info', 'depth_camera_info'):
        identities = set()
        for item in streams.get(role, []):
            try:
                identities.add(_calibration_identity(item['decoded']))
            except (InspectionError, KeyError, TypeError, ValueError):
                continue
        calibration_sets[role] = identities
        if len(identities) > 1:
            _append_diagnostic_issue(issues, 'camera_info_changed', role)
    enhanced = []
    for bundle in bundles:
        reasons = set()
        bindings = {}
        selected = {}
        for role in STREAM_ROLES:
            message = by_message_id[bundle[role]]
            selected[role] = message
            reasons.update(message.get('validation_failures', []))
            if not message.get('formal_valid'):
                reasons.add('stream_message_not_formal_valid')
            header = message['decoded'].get('header', {})
            bindings[role] = {
                'message_id': message['message_id'],
                'connection_id': message['connection_id'],
                'topic': message['topic'],
                'callerid': message['callerid'],
                'header_stamp_ns': header.get('stamp_ns'),
                'frame_id': header.get('frame_id'),
                'record_timestamp_ns': message['record_timestamp_ns'],
                'serialized_sha256': message['serialized_sha256'],
            }
        for image_role, info_role in (
                ('rgb', 'rgb_camera_info'),
                ('raw_depth', 'depth_camera_info')):
            image = selected[image_role]['decoded']
            info = selected[info_role]['decoded']
            if (image.get('header', {}).get('frame_id')
                    != info.get('header', {}).get('frame_id')):
                reasons.add('image_camera_info_frame_mismatch')
            if ((image.get('width'), image.get('height'))
                    != (info.get('width'), info.get('height'))):
                reasons.add('image_camera_info_resolution_mismatch')
        for role, identities in calibration_sets.items():
            if len(identities) > 1:
                reasons.add('camera_info_changed:' + role)
        canonical_binding = {
            role: bindings[role] for role in STREAM_ROLES}
        enhanced.append({
            **bundle,
            'stream_bindings': bindings,
            'pair_sha256': _canonical_mapping_sha256(canonical_binding),
            'formal_valid': not reasons,
            'formal_invalid_reasons': sorted(reasons),
        })
    return enhanced, pairing


def _diagnostic_tf(
        messages: Sequence[Mapping], manifest: Mapping,
        issues: List[Mapping]) -> Mapping:
    policy = manifest['tf_policy']
    transforms = []
    edge_counts = {}
    topic_message_counts = {'/tf': 0, '/tf_static': 0}
    mixed_tf = False
    for message in messages:
        if message.get('role') not in TF_ROLES:
            continue
        topic = message.get('topic')
        if topic in topic_message_counts:
            topic_message_counts[topic] += 1
        decoded = message.get('decoded')
        values = decoded.get('transforms') if isinstance(decoded, Mapping) else None
        if not isinstance(values, list):
            continue
        for index, transform in enumerate(values):
            if not isinstance(transform, Mapping):
                _append_diagnostic_issue(
                    issues, 'tf_transform_schema_invalid', str(index), {
                        'message_id': message.get('message_id')})
                continue
            header = transform.get('header')
            if not isinstance(header, Mapping):
                header = {}
            parent = header.get('frame_id')
            stamp = header.get('stamp_ns')
            child = transform.get('child_frame_id')
            edge_failures = []
            if (message.get('callerid') != manifest['driver_callerid']
                    or not _valid_frame_id(parent)
                    or not _valid_frame_id(child)
                    or not _camera_frame_allowed(parent, policy)
                    or not _camera_frame_allowed(child, policy)):
                edge_failures.append('non_camera_tf_edge')
                mixed_tf = True
            key = (
                topic, message.get('connection_id'), message.get('callerid'),
                parent, child)
            edge_counts[key] = edge_counts.get(key, 0) + 1
            transforms.append({
                'topic': topic,
                'connection_id': message.get('connection_id'),
                'callerid': message.get('callerid'),
                'message_id': message.get('message_id'),
                'transform_index': index,
                'stamp_ns': stamp,
                'parent_frame_id': parent,
                'child_frame_id': child,
                'translation_m': transform.get('translation_m'),
                'rotation_xyzw': transform.get('rotation_xyzw'),
                'serialized_sha256': message.get('serialized_sha256'),
                'policy_violations': edge_failures,
            })
    edge_summary = []
    for key, count in sorted(
            edge_counts.items(), key=lambda item: tuple(
                '' if value is None else str(value) for value in item[0])):
        topic, connection_id, callerid, parent, child = key
        edge_summary.append({
            'topic': topic,
            'connection_id': connection_id,
            'callerid': callerid,
            'parent_frame_id': parent,
            'child_frame_id': child,
            'transform_count': count,
        })
        if (callerid != manifest['driver_callerid']
                or not _valid_frame_id(parent) or not _valid_frame_id(child)
                or not _camera_frame_allowed(parent, policy)
                or not _camera_frame_allowed(child, policy)):
            _append_diagnostic_issue(
                issues, 'non_camera_tf_frame',
                '{}->{}'.format(parent, child), {
                    'topic': topic, 'connection_id': connection_id,
                    'callerid': callerid})
    for topic, count in topic_message_counts.items():
        if count <= 0:
            _append_diagnostic_issue(
                issues, 'tf_topic_payload_missing', topic, {'topic': topic})
    return {
        'camera_only': not mixed_tf,
        'mixed_tf': mixed_tf,
        'base_chain_required': False,
        'topic_message_counts': topic_message_counts,
        'transform_count': len(transforms),
        'edge_summary': edge_summary,
        'transforms': transforms,
    }


def _inspect_records_diagnostic(
        connections: Sequence[Mapping], raw_messages: Sequence[Mapping],
        capture_id: str, scene: str, manifest: Mapping,
        source_capture: Mapping) -> Mapping:
    issues: List[Mapping] = []
    if not isinstance(capture_id, str) or not capture_id.strip():
        _append_diagnostic_issue(issues, 'capture_id_invalid')
    if not isinstance(scene, str) or not scene.strip():
        _append_diagnostic_issue(issues, 'scene_invalid')
    topics, connection_by_id = _diagnostic_connections(
        connections, manifest, issues)
    capture_window = _diagnostic_capture_window(
        raw_messages, connection_by_id)
    messages, streams, isolated = _diagnostic_messages(
        raw_messages, topics, connection_by_id, manifest,
        capture_window, issues)
    streams = _deduplicate_diagnostic_streams(streams, issues)
    bundles, pairing = _diagnostic_pairs(streams, manifest, issues)
    tf_graph = _diagnostic_tf(messages, manifest, issues)
    failures = []
    for issue in issues:
        if issue['code'] not in failures:
            failures.append(issue['code'])
    if 'diagnostic_shared_graph_non_formal' not in failures:
        failures.append('diagnostic_shared_graph_non_formal')
    formal_valid_count = sum(
        1 for bundle in bundles if bundle['formal_valid'])
    return {
        'schema_version': 1,
        'report_kind': 'ros1_shared_graph_diagnostic_manifest',
        'inspection_scope': DIAGNOSTIC_MODE,
        'mode': DIAGNOSTIC_MODE,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'starts_ros_graph': False,
        'storage_identifier': 'rosbag1-v2',
        'indexer_source': indexer_source_identity(),
        'timestamp_semantics': {
            'record_timestamp': 'rosbag1_recorder_receive_time',
            'pairing_and_sync': 'decoded_ros_header_stamp',
        },
        'source_capture': dict(source_capture),
        'capture_id': capture_id,
        'scene': scene,
        'capture_window': capture_window,
        'expected_topic_manifest': {
            key: manifest[key] for key in (
                'path', 'size_bytes', 'sha256', 'manifest_id',
                'schema_version')},
        'topics': topics,
        'messages': messages,
        'isolated_old_latched_camera_info_count': len(isolated),
        'isolated_old_latched_camera_info': isolated,
        **pairing,
        'unique_header_pair_count': len(bundles),
        'formal_contract_valid_pair_count': formal_valid_count,
        'unique_header_pairs': bundles,
        'tf_graph': tf_graph,
        'inspection_passed': False,
        'diagnostic_completed': True,
        'formal_acceptance': False,
        'shared_graph': True,
        'mixed_tf': tf_graph['mixed_tf'],
        'not_in_four_scene_denominator': True,
        'delivery_ready': False,
        'failures': failures,
        'failure_details': issues,
        'limitations': [
            'diagnostic_shared_graph_non_formal',
            'not_in_four_scene_denominator',
            'does_not_authorize_motion',
        ],
    }


def _validated_formal_source_capture(source_capture: Mapping) -> Mapping:
    expected_keys = {'path', 'size_bytes', 'sha256'}
    if (not isinstance(source_capture, Mapping)
            or set(source_capture) != expected_keys
            or not isinstance(source_capture.get('path'), str)
            or not isinstance(source_capture.get('size_bytes'), int)
            or isinstance(source_capture.get('size_bytes'), bool)
            or source_capture.get('size_bytes') <= 0
            or not _lower_sha256_digest(source_capture.get('sha256'))):
        raise InspectionError('formal_source_capture_identity_invalid')
    actual = _formal_bag_identity(Path(source_capture['path']))
    if dict(source_capture) != actual:
        raise InspectionError('formal_source_capture_identity_mismatch')
    return actual


def _canonical_formal_manifest(manifest: Mapping) -> Mapping:
    if not isinstance(manifest, Mapping):
        raise InspectionError('formal_manifest_missing')
    path = manifest.get('path')
    if not isinstance(path, str):
        raise InspectionError('formal_manifest_identity_invalid')
    canonical = load_formal_manifest(path)
    if dict(manifest) != dict(canonical):
        raise InspectionError('formal_manifest_identity_mismatch')
    return canonical


def _validate_formal_capture_window(capture_window: Mapping) -> Mapping:
    expected_keys = {
        'header_start_ns', 'header_end_ns',
        'record_start_ns', 'record_end_ns'}
    if (not isinstance(capture_window, Mapping)
            or set(capture_window) != expected_keys
            or any(not isinstance(capture_window.get(key), int)
                   or isinstance(capture_window.get(key), bool)
                   or capture_window.get(key) <= 0
                   for key in expected_keys)
            or capture_window['header_start_ns']
            > capture_window['header_end_ns']
            or capture_window['record_start_ns']
            > capture_window['record_end_ns']):
        raise InspectionError('formal_capture_window_invalid')
    return dict(capture_window)


def _validate_formal_isolation_ledger(
        raw_messages: Sequence[Mapping], messages: Sequence[Mapping],
        isolated: Sequence[Mapping], issues: Sequence[Mapping],
        manifest: Mapping) -> Mapping:
    if (not isinstance(raw_messages, Sequence)
            or isinstance(raw_messages, (str, bytes))
            or len(messages) != len(raw_messages)):
        raise InspectionError('formal_message_accounting_not_closed')
    allowed_roles = set(
        manifest['capture_window_policy']['allowed_isolated_roles'])
    maximum = manifest['capture_window_policy'][
        'max_isolated_messages_per_role']
    isolated_messages = {
        item['message_id']: item for item in messages
        if item.get('isolated') is True}
    if len(isolated_messages) != sum(
            1 for item in messages if item.get('isolated') is True):
        raise InspectionError('formal_isolation_ledger_not_closed')
    ledger_by_id = {}
    expected_ledger_keys = {
        'message_id', 'connection_id', 'topic', 'role', 'callerid',
        'record_timestamp_ns', 'header_stamp_ns', 'frame_id',
        'serialized_size_bytes', 'serialized_sha256',
        'connection_header_sha256', 'reason'}
    for entry in isolated:
        if (not isinstance(entry, Mapping)
                or set(entry) != expected_ledger_keys
                or entry.get('message_id') in ledger_by_id
                or entry.get('role') not in allowed_roles
                or entry.get('reason')
                != 'old_latched_camera_info_before_capture_window'
                or not isinstance(entry.get('serialized_size_bytes'), int)
                or isinstance(entry.get('serialized_size_bytes'), bool)
                or entry.get('serialized_size_bytes') <= 0
                or not _lower_sha256_digest(
                    entry.get('serialized_sha256'))
                or not _lower_sha256_digest(
                    entry.get('connection_header_sha256'))):
            raise InspectionError('formal_isolation_ledger_invalid')
        ledger_by_id[entry['message_id']] = dict(entry)
    if set(ledger_by_id) != set(isolated_messages):
        raise InspectionError('formal_isolation_ledger_not_closed')
    isolated_by_role = {role: 0 for role in ALL_ROLES}
    for message_id, message in isolated_messages.items():
        decoded = message.get('decoded')
        header = decoded.get('header') if isinstance(decoded, Mapping) else None
        expected = {
            'message_id': message_id,
            'connection_id': message.get('connection_id'),
            'topic': message.get('topic'),
            'role': message.get('role'),
            'callerid': message.get('callerid'),
            'record_timestamp_ns': message.get('record_timestamp_ns'),
            'header_stamp_ns': (
                header.get('stamp_ns') if isinstance(header, Mapping)
                else None),
            'frame_id': (
                header.get('frame_id') if isinstance(header, Mapping)
                else ''),
            'serialized_size_bytes': message.get('serialized_size_bytes'),
            'serialized_sha256': message.get('serialized_sha256'),
            'connection_header_sha256': message.get(
                'connection_header_sha256'),
            'reason': message.get('isolation_reason'),
        }
        role = message.get('role')
        if (ledger_by_id.get(message_id) != expected
                or message.get('formal_valid') is not False
                or role not in allowed_roles):
            raise InspectionError('formal_isolation_ledger_mismatch')
        isolated_by_role[role] += 1
    if any(isolated_by_role[role] > maximum for role in allowed_roles):
        raise InspectionError('formal_isolated_message_limit_exceeded')
    isolation_issues = [
        item for item in issues if isinstance(item, Mapping)
        and item.get('code')
        == 'old_latched_camera_info_before_capture_window']
    issue_ids = {
        item.get('context', {}).get('message_id')
        for item in isolation_issues
        if isinstance(item.get('context'), Mapping)}
    if (len(isolation_issues) != len(isolated)
            or issue_ids != set(ledger_by_id)):
        raise InspectionError('formal_isolation_issue_ledger_mismatch')
    source_by_role = {role: 0 for role in ALL_ROLES}
    admitted_by_role = {role: 0 for role in ALL_ROLES}
    for message in messages:
        role = message.get('role')
        if role not in source_by_role:
            raise InspectionError('formal_message_role_invalid')
        source_by_role[role] += 1
        if message.get('isolated') is not True:
            admitted_by_role[role] += 1
    source_count = len(messages)
    isolated_count = len(isolated_messages)
    admitted_count = source_count - isolated_count
    if (source_count != admitted_count + isolated_count
            or any(source_by_role[role]
                   != admitted_by_role[role] + isolated_by_role[role]
                   for role in ALL_ROLES)):
        raise InspectionError('formal_message_accounting_not_closed')
    return {
        'source_message_count': source_count,
        'admitted_message_count': admitted_count,
        'isolated_message_count': isolated_count,
        'source_message_count_by_role': source_by_role,
        'admitted_message_count_by_role': admitted_by_role,
        'isolated_message_count_by_role': isolated_by_role,
        'closure_valid': True,
    }


def _validate_formal_alignment(
        stream_summaries: Mapping, accepted_bundle_count: int) -> Mapping:
    frames = {
        stream_summaries[role]['frame_id'] for role in STREAM_ROLES}
    grids = {
        (stream_summaries[role]['width'], stream_summaries[role]['height'])
        for role in STREAM_ROLES}
    if len(frames) != 1:
        raise InspectionError('formal_rgbd_frame_not_aligned')
    if len(grids) != 1:
        raise InspectionError('formal_rgbd_grid_not_aligned')
    frame_id = next(iter(frames))
    width, height = next(iter(grids))
    return {
        'required': True,
        'frame_id': frame_id,
        'width': width,
        'height': height,
        'validated_bundle_count': accepted_bundle_count,
    }


def _inspect_records_formal(
        connections: Sequence[Mapping], raw_messages: Sequence[Mapping],
        capture_id: str, scene: str, manifest: Mapping,
        source_capture: Mapping) -> Mapping:
    canonical_manifest = _canonical_formal_manifest(manifest)
    source = _validated_formal_source_capture(source_capture)
    if (not isinstance(capture_id, str) or not capture_id.strip()
            or capture_id != capture_id.strip()):
        raise InspectionError('capture_id_invalid')
    if scene not in FORMAL_SCENES:
        raise InspectionError('formal_scene_invalid', str(scene))
    issues: List[Mapping] = []
    topics, connection_by_id = _diagnostic_connections(
        connections, canonical_manifest, issues)
    capture_window = _validate_formal_capture_window(
        _diagnostic_capture_window(raw_messages, connection_by_id))
    messages, streams, isolated = _diagnostic_messages(
        raw_messages, topics, connection_by_id, canonical_manifest,
        capture_window, issues)
    streams = _deduplicate_diagnostic_streams(streams, issues)
    disallowed_issues = [
        item for item in issues
        if item.get('code')
        != 'old_latched_camera_info_before_capture_window']
    if disallowed_issues:
        first = disallowed_issues[0]
        raise InspectionError(
            str(first.get('code', 'formal_message_validation_failed')),
            str(first.get('detail', 'formal message validation failed')))
    accounting = _validate_formal_isolation_ledger(
        raw_messages, messages, isolated, issues, canonical_manifest)
    stream_summaries = _validate_streams(streams)
    bundles, pairing = _accepted_bundles(
        streams, canonical_manifest['max_sync_span_sec'])
    if len(bundles) < canonical_manifest['min_accepted_bundles']:
        raise InspectionError('accepted_bundle_count_below_minimum')
    if (pairing['total_unpaired_rate'] is None
            or pairing['total_unpaired_rate']
            > canonical_manifest['max_unpaired_rate']):
        raise InspectionError('stream_unpaired_rate_exceeded')
    alignment = _validate_formal_alignment(
        stream_summaries, len(bundles))
    tf_graph = _validate_tf_graph(
        messages, stream_summaries, canonical_manifest)
    if tf_graph.get('camera_only') is not True:
        raise InspectionError('formal_tf_not_camera_only')
    return {
        'schema_version': 1,
        'report_kind': 'formal_rgbd_raw_capture_index',
        'inspection_scope': FORMAL_ACCEPTANCE_MODE,
        'mode': FORMAL_CAMERA_ONLY_MODE,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'starts_ros_graph': False,
        'storage_identifier': 'rosbag1-v2',
        'indexer_source': indexer_source_identity(),
        'timestamp_semantics': {
            'record_timestamp': 'rosbag1_recorder_receive_time',
            'pairing_and_sync': 'decoded_ros_header_stamp',
        },
        'source_capture': source,
        'capture_id': capture_id,
        'scene': scene,
        'capture_window': capture_window,
        'expected_topic_manifest': {
            key: canonical_manifest[key] for key in (
                'path', 'size_bytes', 'sha256', 'manifest_id',
                'schema_version')},
        'stream_topics': {
            role: canonical_manifest['topics_by_role'][role]['name']
            for role in STREAM_ROLES},
        'topics': topics,
        'messages': messages,
        'message_accounting': accounting,
        'isolated_old_latched_camera_info_count': len(isolated),
        'isolated_old_latched_camera_info': isolated,
        'streams': stream_summaries,
        'aligned_stream_contract': alignment,
        **pairing,
        'unique_header_pair_count': len(bundles),
        'formal_contract_valid_pair_count': len(bundles),
        'accepted_bundles': bundles,
        'tf_graph': tf_graph,
        'inspection_passed': True,
        'diagnostic_completed': False,
        'formal_acceptance': True,
        'shared_graph': False,
        'mixed_tf': False,
        'not_in_four_scene_denominator': False,
        'delivery_ready': False,
        'failures': [],
        'failure_details': [],
        'limitations': [
            'formal_raw_capture_only_not_delivery',
            'base_to_camera_extrinsics_not_evaluated',
            'does_not_authorize_motion',
        ],
    }


def inspect_formal_scene(
        connections: Sequence[Mapping], raw_messages: Sequence[Mapping],
        capture_id: str, scene: str, manifest: Mapping = None,
        source_capture: Mapping = None) -> Mapping:
    """Validate one immutable camera-only formal rosbag1 scene capture."""
    selected_manifest = manifest
    try:
        if selected_manifest is None:
            selected_manifest = load_formal_manifest()
        return _inspect_records_formal(
            connections, raw_messages, capture_id, scene,
            selected_manifest, source_capture)
    except InspectionError as error:
        return _failure_report(
            dict(source_capture) if isinstance(source_capture, Mapping) else {},
            selected_manifest if isinstance(selected_manifest, Mapping) else {},
            capture_id, scene, error, FORMAL_CAMERA_ONLY_MODE)
    except Exception as error:
        return _failure_report(
            dict(source_capture) if isinstance(source_capture, Mapping) else {},
            selected_manifest if isinstance(selected_manifest, Mapping) else {},
            capture_id, scene,
            InspectionError('unexpected_formal_error', str(error)),
            FORMAL_CAMERA_ONLY_MODE)


def inspect_records(
        connections: Sequence[Mapping], raw_messages: Sequence[Mapping],
        capture_id: str, scene: str, manifest: Mapping,
        source_capture: Mapping = None,
        mode: str = FORMAL_MODE) -> Mapping:
    """Inspect already-decoded records; intended for tests and offline adapters."""
    source = dict(source_capture or {
        'path': '<in-memory-fake-bag>', 'size_bytes': 0,
        'sha256': hashlib.sha256(b'').hexdigest()})
    if mode == FORMAL_CAMERA_ONLY_MODE:
        return inspect_formal_scene(
            connections, raw_messages, capture_id, scene,
            manifest, source_capture)
    if mode == DIAGNOSTIC_MODE:
        try:
            return _inspect_records_diagnostic(
                connections, raw_messages, capture_id, scene,
                manifest, source)
        except InspectionError as error:
            return _failure_report(
                source, manifest, capture_id, scene, error, mode)
        except Exception as error:
            return _failure_report(
                source, manifest, capture_id, scene,
                InspectionError(
                    'unexpected_diagnostic_error', str(error)), mode)
    if mode != FORMAL_MODE:
        return _failure_report(
            source, manifest, capture_id, scene,
            InspectionError('inspection_mode_invalid', str(mode)), mode)
    if manifest.get('inspection_scope') != FORMAL_MODE:
        return _failure_report(
            source, manifest, capture_id, scene,
            InspectionError('short_sample_manifest_scope_invalid'), mode)
    try:
        return _inspect_records(
            connections, raw_messages, capture_id, scene, manifest, source)
    except InspectionError as error:
        return _failure_report(
            source, manifest, capture_id, scene, error, mode)


def _header_from_ros(value) -> Mapping:
    stamp = getattr(value, 'stamp', None)
    if stamp is None:
        raise InspectionError('ros_message_header_missing')
    if hasattr(stamp, 'to_nsec'):
        stamp_ns = int(stamp.to_nsec())
    else:
        sec = getattr(stamp, 'secs', getattr(stamp, 'sec', None))
        nsec = getattr(stamp, 'nsecs', getattr(stamp, 'nsec', None))
        if not isinstance(sec, int) or not isinstance(nsec, int):
            raise InspectionError('ros_message_stamp_invalid')
        stamp_ns = sec * 1_000_000_000 + nsec
    return {'stamp_ns': stamp_ns, 'frame_id': str(getattr(value, 'frame_id', ''))}


def _ros_message_to_mapping(datatype: str, message) -> Mapping:
    if datatype == IMAGE_TYPE:
        return {
            'header': _header_from_ros(message.header),
            'height': int(message.height),
            'width': int(message.width),
            'encoding': str(message.encoding),
            'is_bigendian': int(message.is_bigendian),
            'step': int(message.step),
            'data_length': len(message.data),
        }
    if datatype == CAMERA_INFO_TYPE:
        roi = message.roi
        return {
            'header': _header_from_ros(message.header),
            'height': int(message.height),
            'width': int(message.width),
            'distortion_model': str(message.distortion_model),
            'D': list(message.D),
            'K': list(message.K),
            'R': list(message.R),
            'P': list(message.P),
            'binning_x': int(message.binning_x),
            'binning_y': int(message.binning_y),
            'roi': {
                'x_offset': int(roi.x_offset),
                'y_offset': int(roi.y_offset),
                'height': int(roi.height),
                'width': int(roi.width),
                'do_rectify': bool(roi.do_rectify),
            },
        }
    if datatype == TF_TYPE:
        transforms = []
        for item in message.transforms:
            translation = item.transform.translation
            rotation = item.transform.rotation
            transforms.append({
                'header': _header_from_ros(item.header),
                'child_frame_id': str(item.child_frame_id),
                'translation_m': [
                    float(translation.x), float(translation.y),
                    float(translation.z)],
                'rotation_xyzw': [
                    float(rotation.x), float(rotation.y),
                    float(rotation.z), float(rotation.w)],
            })
        return {'transforms': transforms}
    raise InspectionError('unsupported_ros_message_type', datatype)


def _normalize_header_value(value) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return str(value)


def _normalize_connection_header(header) -> Mapping[str, str]:
    if not isinstance(header, Mapping):
        raise InspectionError('rosbag_connection_header_invalid')
    return {
        _normalize_header_value(key): _normalize_header_value(value)
        for key, value in header.items()}


def _connection_header_fields(
        header: Mapping[str, str], topic: str, datatype: str,
        md5sum: str) -> Tuple[str, bool]:
    for key, expected in (
            ('topic', topic), ('type', datatype), ('md5sum', md5sum)):
        if header.get(key) != expected:
            raise InspectionError(
                'rosbag_connection_header_{}_mismatch'.format(key), topic)
    callerid = header.get('callerid')
    if not isinstance(callerid, str) or not callerid:
        raise InspectionError('rosbag_connection_header_callerid_missing', topic)
    if 'latching' not in header:
        raise InspectionError('rosbag_latching_header_missing', topic)
    latching_value = header.get('latching')
    if latching_value not in ('0', '1'):
        raise InspectionError('rosbag_latching_header_invalid', topic)
    return callerid, latching_value == '1'


def _diagnostic_connection_header_fields(
        header: Mapping[str, str], topic: str, datatype: str,
        md5sum: str) -> Tuple[str, Optional[bool], List[Mapping]]:
    violations = []
    for key, expected in (
            ('topic', topic), ('type', datatype), ('md5sum', md5sum)):
        if header.get(key) != expected:
            violations.append({
                'code': 'rosbag_connection_header_{}_mismatch'.format(key),
                'detail': topic})
    callerid = header.get('callerid')
    if not isinstance(callerid, str) or not callerid:
        violations.append({
            'code': 'rosbag_connection_header_callerid_missing',
            'detail': topic})
        callerid = ''
    if 'latching' not in header:
        violations.append({
            'code': 'rosbag_latching_header_missing', 'detail': topic})
        latching = None
    elif header.get('latching') not in ('0', '1'):
        violations.append({
            'code': 'rosbag_latching_header_invalid', 'detail': topic})
        latching = None
    else:
        latching = header['latching'] == '1'
    return callerid, latching, violations


def _raw_message_parts(value):
    if isinstance(value, tuple) and len(value) == 5:
        return value[0], value[1], value[2], value[3], value[4]
    if (isinstance(value, tuple) and len(value) == 3
            and isinstance(value[1], tuple) and len(value[1]) == 3):
        data, md5sum, position = value[1]
        return value[0], data, md5sum, position, value[2]
    for names in (
            ('datatype', 'data', 'md5sum', 'position', 'pytype'),
            ('type', 'data', 'md5sum', 'position', 'pytype')):
        if all(hasattr(value, name) for name in names):
            return tuple(getattr(value, name) for name in names)
    raise InspectionError('rosbag_raw_message_shape_invalid')


class Rosbag1Reader:
    """Read a rosbag1 v2 file through the Noetic API without ROS init."""

    def __init__(self, path: Path, diagnostic: bool = False):
        self.path = Path(path)
        self.diagnostic = bool(diagnostic)

    def read(self) -> Tuple[List[Mapping], List[Mapping]]:
        try:
            import rosbag
        except ImportError as error:
            raise InspectionError(
                'rosbag_python_api_unavailable', str(error)) from error
        try:
            bag = rosbag.Bag(str(self.path), mode='r', allow_unindexed=False)
        except Exception as error:
            raise InspectionError('rosbag_open_failed', str(error)) from error
        try:
            if not hasattr(bag, '_get_connections'):
                raise InspectionError('rosbag_connection_api_unavailable')
            if getattr(bag, 'version', None) != 200:
                raise InspectionError('rosbag_version_invalid')
            connection_infos = list(bag._get_connections())
            connections = []
            signature_to_id = {}
            for info in connection_infos:
                header = _normalize_connection_header(info.header)
                if self.diagnostic:
                    callerid, latching, header_violations = (
                        _diagnostic_connection_header_fields(
                            header, str(info.topic), str(info.datatype),
                            str(info.md5sum)))
                else:
                    callerid, latching = _connection_header_fields(
                        header, str(info.topic), str(info.datatype),
                        str(info.md5sum))
                    header_violations = []
                connection = {
                    'connection_id': int(info.id),
                    'topic': str(info.topic),
                    'type': str(info.datatype),
                    'md5sum': str(info.md5sum),
                    'callerid': callerid,
                    'latching': latching,
                    'connection_header': dict(header),
                    'connection_header_sha256': _canonical_mapping_sha256(
                        header),
                    'connection_header_violations': header_violations,
                }
                signature = _connection_signature(
                    connection['topic'], connection['type'],
                    connection['md5sum'], connection['callerid'],
                    connection['latching'])
                if signature in signature_to_id:
                    if not self.diagnostic:
                        raise InspectionError(
                            'duplicate_connection', connection['topic'])
                    connection['connection_header_violations'].append({
                        'code': 'duplicate_connection',
                        'detail': connection['topic']})
                else:
                    signature_to_id[signature] = connection['connection_id']
                connections.append(connection)
            messages = []
            iterator = bag.read_messages(
                raw=True, return_connection_header=True)
            for item in iterator:
                if not isinstance(item, tuple) or len(item) != 4:
                    raise InspectionError('rosbag_message_tuple_invalid')
                topic, raw_message, stamp, connection_header = item
                datatype, data, md5sum, _position, pytype = (
                    _raw_message_parts(raw_message))
                if isinstance(data, memoryview):
                    data = data.tobytes()
                if not isinstance(data, bytes):
                    data = bytes(data)
                header = _normalize_connection_header(connection_header)
                if self.diagnostic:
                    callerid, latching, header_violations = (
                        _diagnostic_connection_header_fields(
                            header, str(topic), str(datatype), str(md5sum)))
                else:
                    callerid, latching = _connection_header_fields(
                        header, str(topic), str(datatype), str(md5sum))
                    header_violations = []
                signature = _connection_signature(
                    str(topic), str(datatype), str(md5sum),
                    callerid, latching)
                connection_id = signature_to_id.get(signature)
                if connection_id is None and not self.diagnostic:
                    raise InspectionError('message_connection_header_mismatch')
                if connection_id is None:
                    header_violations.append({
                        'code': 'message_connection_header_mismatch',
                        'detail': str(topic)})
                decoded = None
                decode_error = None
                try:
                    decoded_message = pytype()
                    decoded_message.deserialize(data)
                    roundtrip = io.BytesIO()
                    decoded_message.serialize(roundtrip)
                except Exception as error:
                    if not self.diagnostic:
                        raise InspectionError(
                            'ros_message_deserialize_failed', str(error)) from error
                    decode_error = {
                        'code': 'ros_message_deserialize_failed',
                        'detail': str(error)}
                if decode_error is None and roundtrip.getvalue() != data:
                    if not self.diagnostic:
                        raise InspectionError('ros_message_roundtrip_mismatch')
                    decode_error = {
                        'code': 'ros_message_roundtrip_mismatch',
                        'detail': str(topic)}
                if decode_error is None:
                    try:
                        decoded = _ros_message_to_mapping(
                            str(datatype), decoded_message)
                    except InspectionError as error:
                        if not self.diagnostic:
                            raise
                        decode_error = {
                            'code': error.code, 'detail': error.detail}
                record_stamp = (
                    int(stamp.to_nsec()) if hasattr(stamp, 'to_nsec')
                    else int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs))
                messages.append({
                    'connection_id': connection_id,
                    'record_timestamp_ns': record_stamp,
                    'serialized_payload': data,
                    'decoded': decoded,
                    'connection_header': dict(header),
                    'connection_header_sha256': _canonical_mapping_sha256(
                        header),
                    'connection_header_violations': header_violations,
                    'decode_error': decode_error,
                })
            return connections, messages
        finally:
            bag.close()


def inspect_bag(
        path, capture_id: str, scene: str, manifest_path=None,
        reader_factory=None, mode: str = FORMAL_MODE,
        test_only: bool = False) -> Mapping:
    """Read and inspect one immutable `.bag`; never repair or reindex it."""
    manifest = (
        load_formal_manifest(manifest_path)
        if mode == FORMAL_CAMERA_ONLY_MODE
        else load_manifest(manifest_path))
    candidate = Path(path)
    if mode == FORMAL_CAMERA_ONLY_MODE:
        source_capture = _formal_bag_identity(candidate)
        resolved = Path(source_capture['path'])
    else:
        if candidate.suffix.lower() != '.bag':
            raise InspectionError('bag_extension_invalid')
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise InspectionError('bag_missing', str(error)) from error
        if not resolved.is_file():
            raise InspectionError('bag_not_regular_file')
        source_capture = {
            'path': str(resolved),
            'size_bytes': resolved.stat().st_size,
            'sha256': sha256_file(resolved),
        }
    try:
        _validate_rosbag1_v2_envelope(resolved)
        if mode == FORMAL_CAMERA_ONLY_MODE:
            # Formal evidence must never be decoded by an ambient, patched, or
            # caller-supplied reader.  The production path remains deliberately
            # fail-closed until a host-owned isolated Noetic subprocess binds
            # its executable, rosbag module closure, output marker, and exact
            # source-capture identity.  Algorithm tests use ``inspect_records``
            # and cannot turn this `.bag` gate into formal field evidence.
            if test_only is not False:
                raise InspectionError(FORMAL_TEST_ONLY_READER_FORBIDDEN)
            if reader_factory is not None:
                raise InspectionError(FORMAL_READER_FACTORY_FORBIDDEN)
            raise InspectionError(FORMAL_READER_ADMISSION_UNAVAILABLE)
        if reader_factory is None:
            reader = Rosbag1Reader(
                resolved, diagnostic=(
                    mode in (DIAGNOSTIC_MODE, FORMAL_CAMERA_ONLY_MODE)))
        else:
            reader = reader_factory(resolved)
        connections, messages = reader.read()
        return inspect_records(
            connections, messages, capture_id, scene, manifest,
            source_capture, mode)
    except InspectionError as error:
        return _failure_report(
            source_capture, manifest, capture_id, scene, error, mode)
    except Exception as error:
        return _failure_report(
            source_capture, manifest, capture_id, scene,
            InspectionError('unexpected_reader_error', str(error)), mode)


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description='Strictly index one ROS1 Noetic DaBai sensor-only bag.')
    parser.add_argument('--bag', type=Path, required=True)
    parser.add_argument('--capture-id', required=True)
    parser.add_argument('--scene', required=True)
    parser.add_argument(
        '--mode', choices=(
            FORMAL_MODE, DIAGNOSTIC_MODE, FORMAL_CAMERA_ONLY_MODE),
        default=FORMAL_MODE)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args(args)


def main(args=None, reader_factory=None):
    """Write one exclusive JSON report and return zero only for a valid sample."""
    parsed = parse_args(args)
    if parsed.output.exists():
        raise SystemExit('output path must not already exist')
    if parsed.output.resolve() == parsed.bag.resolve():
        raise SystemExit('output path must differ from bag path')
    report = inspect_bag(
        parsed.bag, parsed.capture_id, parsed.scene,
        parsed.manifest, reader_factory, parsed.mode)
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    with parsed.output.open('x', encoding='utf-8') as stream:
        json.dump(
            report, stream, ensure_ascii=False, indent=2, sort_keys=True,
            allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    if parsed.mode == DIAGNOSTIC_MODE:
        return 0 if report.get('diagnostic_completed') is True else 1
    if parsed.mode == FORMAL_CAMERA_ONLY_MODE:
        return 0 if (
            report.get('inspection_passed') is True
            and report.get('formal_acceptance') is True) else 1
    return 0 if report.get('inspection_passed') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
