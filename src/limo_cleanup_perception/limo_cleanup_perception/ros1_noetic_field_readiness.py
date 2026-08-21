"""Host-owned, fail-closed ROS1/Noetic field-readiness intake.

This module is deliberately outside the ROS1 overlay.  It does not join a
ROS graph, import a model backend, or publish anything.  It binds an intake
request to one externally anchored authority document, invokes the isolated
rosbag1 reader probe, and independently recomputes the minimum cross-artifact
record graph needed before the existing host source/install gates can matter.

An explicit test-only mode exists for pure algorithm fixtures.  That mode can
set ``algorithm_validated`` but can never admit field evidence, enter the
four-scene denominator, or set ``delivery_ready``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from typing import Sequence, Tuple

GATE_ID = 'ROS1_NOETIC_HOST_FIELD_READINESS_V1'
AUTHORITY_MARKER = 'LIMO_ROS1_NOETIC_FIELD_READINESS_AUTHORITY_V1'
REQUEST_MARKER = 'LIMO_ROS1_NOETIC_FIELD_READINESS_REQUEST_V1'
PROBE_ARTIFACT_MARKER = 'LIMO_ROS1_ISOLATED_BAG_RAW_ARTIFACT_V1'
PRODUCTION_MODE = 'production_field_intake'
TEST_ONLY_MODE = 'test_only_algorithm'
SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
MIN_PRODUCTION_SCENE_FRAMES = 30
MAX_DECLARED_RECORD_HEADER_SKEW_NS = 750_000_000
MAX_XYZ_ERROR_M = 0.02
MAX_DEPTH_ERROR_M = 0.02
MIN_DEPTH_VALID_RATE = 0.80
MAX_SYNC_P95_SEC = 0.15
MAX_PROCESSING_P95_SEC = 0.50
MAX_TRANSPORT_P95_SEC = 0.75
MODEL_CLASSES = ('plastic_bottle', 'trash_bin')
EXPECTED_COLLECTOR_TOPIC = '/cleanup/perception/frames'
EXPECTED_COLLECTOR_MESSAGE_TYPE = (
    'limo_cleanup_ros1_perception/PerceptionFrame')

IDENTITY_KEYS = {'path', 'size_bytes', 'sha256'}
RELEASE_BINDING_KEYS = {
    'release_id', 'source_manifest_artifact_sha256', 'source_set_sha256',
    'manifest_generated_at_unix_sec'}
AUTHORITY_KEYS = {
    'schema_version', 'marker', 'authority_id', 'scope', 'test_only',
    'read_only', 'authorizes_motion', 'publishes_ros_messages',
    'request_identity', 'canonical_source_admission',
    'field_install_evidence', 'formal_manifest', 'isolated_probe_source',
    'rosbag1_indexer_source', 'rosbag_module', 'noetic_prefix',
    'rosbag_decoder_closure', 'python_executable_target',
    'trusted_system_python_roots', 'python_root_relative', 'scene_set',
    'artifact_markers', 'semantic_producer_source',
    'semantic_producer_authorities'}
REQUEST_KEYS = {
    'schema_version', 'marker', 'request_id', 'mode', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'runtime_family',
    'ros_distro', 'release_binding', 'model_artifact_sha256',
    'model_set_sha256', 'canonical_source_admission',
    'field_install_evidence', 'scenes'}
SCENE_KEYS = {
    'scene', 'capture_id', 'task_id', 'bundle_id', 'capture_window',
    'collector_request', 'probe_output_path', 'artifacts'}
CAPTURE_WINDOW_KEYS = {
    'record_start_ns', 'record_end_ns', 'header_start_ns', 'header_end_ns'}
COLLECTOR_REQUEST_KEYS = {
    'topic', 'message_type', 'max_frames', 'duration_sec'}
ARTIFACT_ROLES = (
    'raw_bag', 'collector_manifest', 'typed_frames', 'typed_raw_binding',
    'ground_truth', 'extrinsics_reference', 'tf_records', 'xyz_records',
    'depth_records', 'latency_records', 'semantic_producer_report')
ARTIFACT_MARKERS = {
    'probe_output': PROBE_ARTIFACT_MARKER,
    'collector_manifest': 'ros1_typed_frame_readonly',
    'typed_raw_binding': 'ros1_typed_raw_binding',
    'ground_truth': 'ros1_ground_truth',
    'extrinsics_reference': 'ros1_independent_extrinsics_reference',
    'tf_records': 'ros1_tf_application',
    'xyz_records': 'ros1_xyz_reference',
    'depth_records': 'ros1_depth_reference',
    'latency_records': 'ros1_latency_evidence',
    'semantic_producer_report': (
        'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_REPORT_V1'),
}

SEMANTIC_PRODUCER_AUTHORITY_KEYS = {
    'schema_version', 'marker', 'authority_id', 'scope', 'test_only',
    'read_only', 'authorizes_motion', 'publishes_ros_messages',
    'request_identity', 'producer_source', 'field_readiness_source',
    'canonical_source_admission', 'field_install_evidence',
    'model_manifest', 'model_artifacts', 'model_set_sha256',
    'ground_truth_review_authority', 'measurement_reference_authority',
    'allowed_output_root'}
SEMANTIC_PRODUCER_REQUEST_KEYS = {
    'schema_version', 'marker', 'request_id', 'mode', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'scene', 'capture_id',
    'task_id', 'raw_bag', 'probe_artifact', 'typed_frames',
    'typed_raw_binding', 'measurement_ledger',
    'canonical_source_admission', 'field_install_evidence',
    'model_manifest', 'model_artifacts', 'model_set_sha256',
    'ground_truth_review_authority', 'measurement_reference_authority',
    'output_directory'}
SEMANTIC_PRODUCER_REPORT_KEYS = {
    'schema_version', 'marker', 'gate_id', 'mode', 'read_only',
    'authorizes_motion', 'publishes_ros_messages',
    'producer_material_validated', 'formal_acceptance',
    'not_in_four_scene_denominator', 'field_evidence_admitted',
    'delivery_ready', 'synthetic_test_only', 'authority_identity',
    'authority_index_identity',
    'producer_source_identity', 'field_readiness_source_identity',
    'request_identity', 'measurement_ledger_identity', 'raw_bag_identity',
    'probe_artifact_identity', 'typed_frames_identity',
    'typed_raw_binding_identity', 'canonical_source_admission',
    'field_install_evidence', 'model_manifest', 'model_artifacts',
    'model_set_sha256', 'ground_truth_review_authority',
    'measurement_reference_authority', 'scene', 'capture_id', 'task_id',
    'typed_frame_count', 'observation_count', 'outputs',
    'output_commit_state', 'failures'}
SEMANTIC_PRODUCER_OUTPUT_NAMES = {
    'ground_truth': 'ground_truth.json',
    'extrinsics_reference': 'extrinsics_reference.json',
    'tf_records': 'tf_records.json',
    'xyz_records': 'xyz_records.json',
    'depth_records': 'depth_records.json',
    'latency_records': 'latency_records.json',
}

COLLECTOR_KEYS = {
    'schema_version', 'collector_kind', 'read_only', 'authorizes_motion',
    'publishes_ros_messages', 'scene', 'topic', 'message_type', 'task_id',
    'max_frames', 'duration_sec', 'received_frames', 'unique_frames',
    'duplicate_sequences', 'duplicate_bundle_ids', 'serialization_errors',
    'interrupted', 'completed_minimum', 'completed_requested_frames',
    'output'}
FRAME_KEYS = {
    'schema_version', 'read_only', 'received_unix_sec',
    'transport_latency_sec', 'stamp', 'frame_id', 'task_id', 'capture_id',
    'bundle_id', 'model_binding_sha256', 'sequence', 'valid', 'status',
    'error_code', 'sync_span_sec', 'processing_latency_sec',
    'tf_target_frame', 'tf_valid', 'tf_transform_applied', 'tf_status',
    'tf_error_code', 'targets', 'scene'}
TYPED_TARGET_KEYS = {
    'observation_id', 'object_class', 'confidence', 'valid', 'actionable',
    'status', 'error_code', 'position', 'size', 'bbox', 'depth_m',
    'depth_valid_pixels', 'depth_total_pixels', 'depth_valid_ratio',
    'source', 'position_semantics'}
BINDING_KEYS = {
    'schema_version', 'report_kind', 'evidence_scope', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'binding_sha256',
    'capture_id', 'task_id', 'scene', 'model_binding_sha256', 'artifacts',
    'provenance', 'typed_frame_count', 'raw_bundle_count',
    'association_count', 'minimum_scene_frames', 'unpaired_typed_count',
    'unpaired_raw_bundle_count', 'associations', 'test_only',
    'validated_pass', 'formal_acceptance',
    'not_in_four_scene_denominator', 'delivery_ready', 'failures'}
COMMON_SEMANTIC_KEYS = {
    'schema_version', 'scene', 'capture_id', 'task_id',
    'ros1_field_install_sha256', 'model_binding_sha256',
    'synthetic_test_only', 'report_kind'}
GROUND_TRUTH_KEYS = COMMON_SEMANTIC_KEYS | {
    'complete', 'unique_frames', 'annotation_count', 'class_metrics',
    'records'}
EXTRINSICS_KEYS = COMMON_SEMANTIC_KEYS | {
    'source_frame', 'target_frame', 'translation_m', 'rotation_xyzw',
    'transform_sha256', 'measurement_method', 'operator_id', 'reviewer_id',
    'measured_at_unix_sec', 'reviewed_at_unix_sec'}
TF_KEYS = COMMON_SEMANTIC_KEYS | {
    'source_frame', 'target_frame', 'transform_applied', 'mixed_tf',
    'tf_valid_frames', 'xyz_valid_frames', 'records'}
XYZ_KEYS = COMMON_SEMANTIC_KEYS | {
    'not_applicable', 'sample_count', 'max_error_m', 'p95_error_m',
    'records'}
DEPTH_KEYS = COMMON_SEMANTIC_KEYS | {
    'not_applicable', 'sample_count', 'valid_rate', 'max_error_m',
    'p95_error_m', 'records'}
LATENCY_KEYS = COMMON_SEMANTIC_KEYS | {
    'sample_count', 'max_latency_sec', 'p95_end_to_end_sec',
    'p95_processing_sec', 'p95_sync_sec', 'records'}
POINT_KEYS = {'x', 'y', 'z'}
ANNOTATION_KEYS = {'instance_id', 'object_class', 'bbox', 'relation'}
CLASS_METRIC_KEYS = {'tp', 'fp', 'fn', 'precision', 'recall', 'f1'}
GROUND_RECORD_KEYS = {
    'sequence', 'stamp_ns', 'bundle_id', 'typed_frame_sha256',
    'rgb_payload_sha256', 'annotations'}
TARGET_TRANSFORM_KEYS = {
    'observation_id', 'input_position_m', 'output_position_m',
    'extrinsics_transform_sha256'}
TF_RECORD_KEYS = {
    'sequence', 'stamp_ns', 'bundle_id', 'topic', 'message_id',
    'connection_id', 'transform_index', 'callerid', 'transform_stamp_ns',
    'parent_frame_id', 'child_frame_id', 'translation_m', 'rotation_xyzw',
    'serialized_sha256', 'lookup_source_frame', 'lookup_target_frame',
    'lookup_succeeded', 'transform_applied', 'output_frame',
    'extrinsics_transform_sha256', 'target_transforms'}
XYZ_RECORD_KEYS = {
    'sequence', 'stamp_ns', 'bundle_id', 'observation_id',
    'reference_xyz_m', 'measured_xyz_m', 'error_m'}
DEPTH_RECORD_KEYS = {
    'sequence', 'stamp_ns', 'bundle_id', 'observation_id',
    'reference_depth_m', 'measured_depth_m', 'valid_pixels',
    'total_pixels', 'valid_ratio', 'valid', 'error_m'}
LATENCY_RECORD_KEYS = {
    'sequence', 'stamp_ns', 'bundle_id', 'sensor_stamp_sec',
    'inference_started_unix_sec', 'inference_ended_unix_sec',
    'collector_received_unix_sec', 'sync_span_sec',
    'processing_latency_sec', 'transport_latency_sec',
    'end_to_end_latency_sec'}
PROBE_ARTIFACT_KEYS = {
    'schema_version', 'marker', 'report_kind', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'delivery_ready',
    'request_id', 'request_sha256', 'bag_identity', 'noetic_prefix',
    'python_root', 'rosbag_module_identity', 'indexer_module_identity',
    'formal_manifest_identity', 'probe_source_identity',
    'sys_executable_identity', 'parent_executable_admission',
    'child_executable_admission', 'capture_id', 'scene', 'connections',
    'messages', 'connection_count', 'message_count',
    'total_payload_bytes', 'formal_report',
    'loaded_nonstdlib_module_provenance', 'test_only',
    'algorithm_validated', 'formal_acceptance',
    'not_in_four_scene_denominator'}


class IntakeError(ValueError):
    """Stable fail-closed intake error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise IntakeError('duplicate_json_key')
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise IntakeError('nonfinite_json_number:' + value)


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode('utf-8'), object_pairs_hook=_strict_object,
        parse_constant=_reject_nonfinite)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n')


def _path_component_is_linklike(path: Path) -> bool:
    metadata = os.lstat(str(path))
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    return bool(
        reparse
        and getattr(metadata, 'st_file_attributes', 0) & reparse)


def _path_has_linklike_component(path: Path) -> bool:
    candidate = Path(path).absolute()
    chain = list(reversed(candidate.parents)) + [candidate]
    try:
        return any(_path_component_is_linklike(item) for item in chain)
    except (OSError, RuntimeError, ValueError):
        return True


def _stat_common_snapshot(metadata: os.stat_result) -> Tuple[Any, ...]:
    """Return metadata represented consistently by path and descriptor APIs."""
    return (
        getattr(metadata, 'st_dev', None),
        getattr(metadata, 'st_ino', None),
        int(metadata.st_size),
        getattr(metadata, 'st_mtime_ns', None),
        int(getattr(metadata, 'st_nlink', 1)),
        getattr(metadata, 'st_uid', None),
        getattr(metadata, 'st_gid', None),
        getattr(metadata, 'st_file_attributes', None),
    )


def _same_side_stat_snapshot(metadata: os.stat_result) -> Tuple[Any, ...]:
    """Compare two path stats or two descriptor stats, including full mode."""
    return _stat_common_snapshot(metadata) + (int(metadata.st_mode),)


def _path_fd_stat_snapshot(metadata: os.stat_result) -> Tuple[Any, ...]:
    """Compare path and FD state without Windows permission-bit false drift."""
    return _stat_common_snapshot(metadata) + (
        stat.S_IFMT(int(metadata.st_mode)),)


def _read_regular_file_once(
        path: Path, *, collect_raw: bool = False,
        prefix_size: int = 0) -> Tuple[Mapping[str, Any], Optional[bytes]]:
    """Hash and optionally retain content from one stable regular-file FD.

    JSON/JSONL callers request ``collect_raw``.  Large rosbag callers request
    only a small prefix, so validating a declared bag identity never retains
    the complete bag in memory.  All bytes, the digest, and the returned
    prefix/raw material come from the same descriptor.
    """
    if type(prefix_size) is not int or prefix_size < 0:
        raise IntakeError('artifact_read_contract_invalid')
    candidate = Path(path)
    try:
        os.lstat(str(candidate))
    except FileNotFoundError as error:
        raise IntakeError('artifact_missing') from error
    except (OSError, RuntimeError, ValueError) as error:
        raise IntakeError('artifact_path_linklike') from error
    if _path_has_linklike_component(candidate):
        raise IntakeError('artifact_path_linklike')
    try:
        resolved = candidate.resolve(strict=True)
        path_before = os.lstat(str(resolved))
    except (OSError, RuntimeError, ValueError) as error:
        raise IntakeError('artifact_missing') from error
    if not stat.S_ISREG(path_before.st_mode):
        raise IntakeError('artifact_not_regular_file')
    if int(getattr(path_before, 'st_nlink', 1)) != 1:
        raise IntakeError('artifact_hardlink_forbidden')
    digest = hashlib.sha256()
    chunks = [] if collect_raw else None
    prefix = bytearray()
    total_size = 0
    try:
        with resolved.open('rb') as stream:
            descriptor_before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(descriptor_before.st_mode)
                    or int(getattr(descriptor_before, 'st_nlink', 1)) != 1
                    or _path_fd_stat_snapshot(path_before)
                    != _path_fd_stat_snapshot(descriptor_before)):
                raise IntakeError('artifact_changed_during_audit')
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                total_size += len(chunk)
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
                elif prefix_size and len(prefix) < prefix_size:
                    prefix.extend(chunk[:prefix_size - len(prefix)])
            descriptor_after = os.fstat(stream.fileno())
        path_after = os.lstat(str(resolved))
    except IntakeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise IntakeError('artifact_changed_during_audit') from error
    if (_path_has_linklike_component(resolved)
            or not stat.S_ISREG(descriptor_after.st_mode)
            or not stat.S_ISREG(path_after.st_mode)
            or int(getattr(descriptor_after, 'st_nlink', 1)) != 1
            or int(getattr(path_after, 'st_nlink', 1)) != 1
            or _same_side_stat_snapshot(path_before)
            != _same_side_stat_snapshot(path_after)
            or _same_side_stat_snapshot(descriptor_before)
            != _same_side_stat_snapshot(descriptor_after)
            or _path_fd_stat_snapshot(path_before)
            != _path_fd_stat_snapshot(descriptor_before)
            or _path_fd_stat_snapshot(path_after)
            != _path_fd_stat_snapshot(descriptor_after)
            or total_size != int(descriptor_after.st_size)):
        raise IntakeError('artifact_changed_during_audit')
    identity = {
        'path': str(resolved),
        'size_bytes': total_size,
        'sha256': digest.hexdigest(),
    }
    if chunks is not None:
        material = b''.join(chunks)
    elif prefix_size:
        material = bytes(prefix)
    else:
        material = None
    return identity, material


def regular_file_identity(path: Path) -> Mapping[str, Any]:
    """Return one stable identity after rejecting link/reparse ancestors."""
    identity, _ = _read_regular_file_once(path)
    return identity


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and value == value.lower()
        and all(character in '0123456789abcdef' for character in value))


def _valid_identity(value: Any) -> bool:
    return (
        isinstance(value, Mapping) and set(value) == IDENTITY_KEYS
        and isinstance(value.get('path'), str) and bool(value.get('path'))
        and Path(value['path']).is_absolute()
        and type(value.get('size_bytes')) is int
        and value['size_bytes'] >= 0 and _valid_sha256(value.get('sha256')))


def _identity_path(value: Mapping[str, Any], kind: str) -> Path:
    path, _ = _read_identity_material(value, kind)
    return path


def _read_identity_material(
        value: Mapping[str, Any], kind: str, *, collect_raw: bool = False,
        prefix_size: int = 0) -> Tuple[Path, Optional[bytes]]:
    """Read a declared identity once and return material from that same FD."""
    if not _valid_identity(value):
        raise IntakeError(kind + '_identity_schema_invalid')
    actual, material = _read_regular_file_once(
        Path(value['path']), collect_raw=collect_raw,
        prefix_size=prefix_size)
    if dict(value) != actual:
        raise IntakeError(kind + '_identity_mismatch')
    return Path(actual['path']), material


def _is_under(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve(strict=True).relative_to(Path(root).resolve(strict=True))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _load_identity_json_with_path(
        value: Mapping[str, Any], kind: str) -> Tuple[Path, Any]:
    path, raw = _read_identity_material(value, kind, collect_raw=True)
    try:
        return path, _strict_json_bytes(raw if raw is not None else b'')
    except (OSError, UnicodeError, json.JSONDecodeError, IntakeError) as error:
        if isinstance(error, IntakeError):
            raise
        raise IntakeError(kind + '_json_invalid') from error


def _load_identity_json(value: Mapping[str, Any], kind: str) -> Any:
    _, parsed = _load_identity_json_with_path(value, kind)
    return parsed


def _load_jsonl_identity(value: Mapping[str, Any], kind: str) -> List[Any]:
    _, raw = _read_identity_material(value, kind, collect_raw=True)
    records = []
    try:
        lines = (raw if raw is not None else b'').splitlines()
        if not lines:
            raise IntakeError(kind + '_zero_denominator')
        for line in lines:
            if not line.strip():
                raise IntakeError(kind + '_jsonl_blank_record')
            records.append(_strict_json_bytes(line))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntakeError(kind + '_jsonl_invalid') from error
    return records


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value).rstrip(b'\n')).hexdigest()


def _model_set_sha256(model_hashes: Mapping[str, str]) -> str:
    """Recompute the ROS1 model contract's ordered class/hash identity."""
    value = [
        {'class_name': name, 'sha256': model_hashes[name]}
        for name in MODEL_CLASSES]
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any, minimum: float = None) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value))
        and (minimum is None or float(value) >= minimum))


def _integer(value: Any, minimum: int = None) -> bool:
    return (
        type(value) is int and (minimum is None or value >= minimum))


def _text(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value)
        and value == value.strip() and '\x00' not in value)


def _p95(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _vector(value: Any, length: int) -> bool:
    return (
        isinstance(value, list) and len(value) == length
        and all(_finite(item) for item in value))


def _point(value: Any) -> bool:
    return (
        isinstance(value, Mapping) and set(value) == POINT_KEYS
        and all(_finite(value.get(axis)) for axis in ('x', 'y', 'z')))


def _point_vector(value: Mapping[str, Any]) -> List[float]:
    return [float(value[axis]) for axis in ('x', 'y', 'z')]


def _same_vector(first: Sequence[float], second: Sequence[float],
                 tolerance: float = 1e-9) -> bool:
    return (
        len(first) == len(second)
        and all(abs(float(a) - float(b)) <= tolerance
                for a, b in zip(first, second)))


def _transform_point(
        point: Sequence[float], translation: Sequence[float],
        rotation: Sequence[float]) -> List[float]:
    x, y, z, w = (float(item) for item in rotation)
    px, py, pz = (float(item) for item in point)
    tx = 2.0 * (y * pz - z * py)
    ty = 2.0 * (z * px - x * pz)
    tz = 2.0 * (x * py - y * px)
    rotated = [
        px + w * tx + (y * tz - z * ty),
        py + w * ty + (z * tx - x * tz),
        pz + w * tz + (x * ty - y * tx),
    ]
    return [
        rotated[index] + float(translation[index]) for index in range(3)]


def _bbox_iou(first: Any, second: Any) -> float:
    if (not _vector(first, 4) or not _vector(second, 4)
            or first[2] <= first[0] or first[3] <= first[1]
            or second[2] <= second[0] or second[3] <= second[1]):
        return 0.0
    x1 = max(float(first[0]), float(second[0]))
    y1 = max(float(first[1]), float(second[1]))
    x2 = min(float(first[2]), float(second[2]))
    y2 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = (float(first[2]) - float(first[0])) * (
        float(first[3]) - float(first[1]))
    second_area = (float(second[2]) - float(second[0])) * (
        float(second[3]) - float(second[1]))
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _class_metrics(
        ground_map: Mapping, frames: Mapping) -> Mapping[str, Mapping]:
    counts = {
        label: {'tp': 0, 'fp': 0, 'fn': 0} for label in MODEL_CLASSES}
    for key, pair in frames.items():
        annotations = ground_map[key]['annotations']
        targets = pair[1]['targets']
        for label in MODEL_CLASSES:
            truths = [
                item for item in annotations if item['object_class'] == label]
            predictions = [
                item for item in targets if item['object_class'] == label]
            unmatched = set(range(len(truths)))
            for prediction in sorted(
                    predictions, key=lambda item: item['confidence'],
                    reverse=True):
                best = None
                best_iou = 0.0
                for index in unmatched:
                    value = _bbox_iou(prediction['bbox'], truths[index]['bbox'])
                    if value > best_iou:
                        best = index
                        best_iou = value
                if best is not None and best_iou >= 0.50:
                    counts[label]['tp'] += 1
                    unmatched.remove(best)
                else:
                    counts[label]['fp'] += 1
            counts[label]['fn'] += len(unmatched)
    result = {}
    for label, values in counts.items():
        tp, fp, fn = values['tp'], values['fp'], values['fn']
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = (2.0 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        result[label] = {
            'tp': tp, 'fp': fp, 'fn': fn,
            'precision': precision, 'recall': recall, 'f1': f1,
        }
    return result


def _stamp_ns(frame: Mapping[str, Any]) -> Optional[int]:
    stamp_value = frame.get('stamp') if isinstance(frame, Mapping) else None
    if not isinstance(stamp_value, Mapping) or set(stamp_value) != {
            'sec', 'nanosec'}:
        return None
    sec = stamp_value.get('sec')
    nanosec = stamp_value.get('nanosec')
    if (not _integer(sec, 0) or not _integer(nanosec, 0)
            or nanosec >= 1_000_000_000):
        return None
    result = sec * 1_000_000_000 + nanosec
    return result if result > 0 else None


def _load_anchored_authority(
        path: Path, expected_identity: Mapping[str, Any]) -> Mapping[str, Any]:
    actual, raw = _read_regular_file_once(path, collect_raw=True)
    if not _valid_identity(expected_identity) or actual != expected_identity:
        raise IntakeError('authority_external_anchor_mismatch')
    try:
        value = _strict_json_bytes(raw if raw is not None else b'')
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntakeError('authority_json_invalid') from error
    if not isinstance(value, Mapping) or set(value) != AUTHORITY_KEYS:
        raise IntakeError('authority_schema_invalid')
    if (value.get('schema_version') != 1
            or value.get('marker') != AUTHORITY_MARKER
            or not _text(value.get('authority_id'))
            or value.get('scope') != 'ros1_noetic_field_readiness_intake'
            or type(value.get('test_only')) is not bool
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('publishes_ros_messages') is not False
            or value.get('scene_set') != list(SCENES)
            or value.get('artifact_markers') != ARTIFACT_MARKERS):
        raise IntakeError('authority_policy_invalid')
    for key in (
            'request_identity', 'canonical_source_admission',
            'field_install_evidence', 'formal_manifest',
            'isolated_probe_source', 'rosbag1_indexer_source',
            'rosbag_module', 'python_executable_target',
            'semantic_producer_source'):
        if not _valid_identity(value.get(key)):
            raise IntakeError('authority_identity_invalid:' + key)
    producer_authorities = value.get('semantic_producer_authorities')
    if (not isinstance(producer_authorities, Mapping)
            or list(producer_authorities) != list(SCENES)
            or any(not _valid_identity(identity)
                   for identity in producer_authorities.values())
            or len({identity['path']
                    for identity in producer_authorities.values()})
            != len(SCENES)):
        raise IntakeError('authority_semantic_producer_authorities_invalid')
    decoder_closure = value.get('rosbag_decoder_closure')
    if (not isinstance(decoder_closure, Mapping) or not decoder_closure
            or 'rosbag' not in decoder_closure
            or any(not _text(name) or not _valid_identity(identity)
                   for name, identity in decoder_closure.items())
            or decoder_closure.get('rosbag') != value.get('rosbag_module')):
        raise IntakeError('authority_rosbag_decoder_closure_invalid')
    trusted_roots = value.get('trusted_system_python_roots')
    if (not isinstance(trusted_roots, list)
            or any(not _text(root) or not Path(root).is_absolute()
                   for root in trusted_roots)
            or len(set(trusted_roots)) != len(trusted_roots)):
        raise IntakeError('authority_trusted_python_roots_invalid')
    if (not isinstance(value.get('noetic_prefix'), str)
            or not Path(value['noetic_prefix']).is_absolute()
            or not _text(value.get('python_root_relative'))
            or Path(value['python_root_relative']).is_absolute()
            or '..' in Path(value['python_root_relative']).parts):
        raise IntakeError('authority_noetic_prefix_invalid')
    return dict(value)


def _load_exact_semantic_producer(authority: Mapping[str, Any]) -> Any:
    source_path = _identity_path(
        authority['semantic_producer_source'], 'semantic_producer_source')
    name = '_limo_host_anchored_semantic_evidence_producer'
    spec = importlib.util.spec_from_file_location(name, source_path)
    if spec is None or spec.loader is None:
        raise IntakeError('semantic_producer_loader_unavailable')
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise IntakeError('semantic_producer_loader_failed') from error
    if not callable(getattr(module, 'load_production_authority_index', None)):
        raise IntakeError('semantic_producer_index_api_invalid')
    return module


def _validate_runtime_authority_artifacts(
        authority: Mapping[str, Any]) -> Mapping[str, Any]:
    prefix_candidate = Path(authority['noetic_prefix'])
    if _path_has_linklike_component(prefix_candidate):
        raise IntakeError('authority_noetic_prefix_linklike')
    try:
        prefix = prefix_candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise IntakeError('authority_noetic_prefix_missing') from error
    if not prefix.is_dir():
        raise IntakeError('authority_noetic_prefix_not_directory')
    python_root = (prefix / authority['python_root_relative'])
    if _path_has_linklike_component(python_root):
        raise IntakeError('authority_python_root_linklike')
    try:
        python_root = python_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise IntakeError('authority_python_root_missing') from error
    if not python_root.is_dir() or not _is_under(python_root, prefix):
        raise IntakeError('authority_python_root_invalid')

    identities = {}
    for key in (
            'formal_manifest', 'isolated_probe_source',
            'rosbag1_indexer_source', 'rosbag_module',
            'python_executable_target', 'semantic_producer_source'):
        identities[key] = _identity_path(authority[key], 'authority_' + key)
    if identities['isolated_probe_source'].with_name(
            'rosbag1_rgbd_indexer.py') != identities['rosbag1_indexer_source']:
        raise IntakeError('authority_probe_indexer_sibling_mismatch')
    if not _is_under(identities['rosbag_module'], python_root):
        raise IntakeError('authority_rosbag_module_outside_python_root')
    executable_metadata = os.lstat(str(identities['python_executable_target']))
    if os.name != 'nt' and not (
            executable_metadata.st_mode
            & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        raise IntakeError('authority_python_target_not_executable')

    closure = {}
    for name, declaration in sorted(
            authority['rosbag_decoder_closure'].items()):
        path = _identity_path(
            declaration, 'authority_rosbag_decoder_closure:' + name)
        if not _is_under(path, python_root):
            raise IntakeError(
                'authority_rosbag_decoder_outside_python_root:' + name)
        closure[name] = dict(declaration)
    if closure.get('rosbag') != authority['rosbag_module']:
        raise IntakeError('authority_rosbag_decoder_root_mismatch')

    expected_producer_path = Path(__file__).with_name(
        'ros1_semantic_evidence_producer.py').resolve(strict=True)
    if (identities['semantic_producer_source'] != expected_producer_path
            or authority['semantic_producer_source']
            != regular_file_identity(expected_producer_path)):
        raise IntakeError('authority_semantic_producer_source_mismatch')
    semantic_authorities = {}
    for scene_name in SCENES:
        semantic_authorities[scene_name] = dict(authority[
            'semantic_producer_authorities'][scene_name])
        _identity_path(
            semantic_authorities[scene_name],
            'authority_semantic_producer_authority:' + scene_name)
    semantic_index_identity = None
    if authority['test_only'] is False:
        producer_module = _load_exact_semantic_producer(authority)
        try:
            semantic_index = producer_module.load_production_authority_index()
        except Exception as error:
            code = getattr(error, 'code', None)
            if code == 'semantic_producer_production_authority_not_anchored':
                raise IntakeError(code) from error
            raise IntakeError(
                'semantic_producer_production_authority_index_invalid') from error
        if (not isinstance(semantic_index, Mapping)
                or semantic_index.get('payload', {}).get('authorities')
                != authority['semantic_producer_authorities']
                or not _valid_identity(semantic_index.get('identity'))):
            raise IntakeError(
                'semantic_producer_production_authority_index_mismatch')
        semantic_index_identity = dict(semantic_index['identity'])

    trusted_roots = []
    for value in authority['trusted_system_python_roots']:
        candidate = Path(value)
        if _path_has_linklike_component(candidate):
            raise IntakeError('authority_trusted_python_root_linklike')
        try:
            candidate = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            raise IntakeError('authority_trusted_python_root_missing') from error
        if (not candidate.is_dir()
                or any(part.lower() in {'src', 'devel', 'build'}
                       for part in candidate.parts)):
            raise IntakeError('authority_trusted_python_root_invalid')
        trusted_roots.append(str(candidate))
    return {
        'noetic_prefix': str(prefix),
        'python_root': str(python_root),
        'rosbag_decoder_closure': closure,
        'trusted_system_python_roots': trusted_roots,
        'python_executable_target': authority['python_executable_target'],
        'semantic_producer_source': authority['semantic_producer_source'],
        'semantic_producer_authorities': semantic_authorities,
        'semantic_producer_authority_index': semantic_index_identity,
    }


def _validate_canonical_probe_binding(
        authority: Mapping[str, Any], workspace: Path) -> Mapping[str, Any]:
    if workspace is None:
        raise IntakeError('production_workspace_required')
    workspace_root = Path(workspace).resolve(strict=True)
    canonical = _load_identity_json(
        authority['canonical_source_admission'],
        'canonical_source_admission')
    from limo_cleanup_perception import perception_readiness
    live_source_audit = (
        perception_readiness.audit_ros1_noetic_field_source_contract(
            workspace_root))
    if (live_source_audit.get('pass') is not True
            or live_source_audit.get('complete_runtime') is not True
            or live_source_audit.get('failures') != []
            or live_source_audit.get('architecture_blockers') != []):
        raise IntakeError('canonical_probe_live_source_audit_failed')
    expected_canonical = (
        perception_readiness.make_ros1_canonical_source_binding(
            workspace_root, source_audit=live_source_audit,
            test_only=False))
    if canonical != expected_canonical:
        raise IntakeError('canonical_probe_external_binding_mismatch')
    expected_keys = {
        'architecture_blockers', 'binding_kind', 'binding_sha256',
        'canonical_source_root', 'contract_sha256', 'entries', 'file_count',
        'indexer_only_detected', 'schema_version', 'source_contract_pass',
        'source_set_sha256', 'test_only'}
    if (not isinstance(canonical, Mapping)
            or set(canonical) != expected_keys
            or canonical.get('schema_version') != 1
            or canonical.get('binding_kind') != 'canonical_project_overlay'
            or canonical.get('source_contract_pass') is not True
            or canonical.get('indexer_only_detected') is not False
            or canonical.get('architecture_blockers') != []
            or canonical.get('test_only') is not False):
        raise IntakeError('canonical_probe_binding_manifest_invalid')
    relative_root = canonical.get('canonical_source_root')
    if (not _text(relative_root) or Path(relative_root).is_absolute()
            or '..' in Path(relative_root).parts):
        raise IntakeError('canonical_probe_binding_root_invalid')
    source_root = (workspace_root / relative_root).resolve(strict=True)
    if not _is_under(source_root, workspace_root) or not source_root.is_dir():
        raise IntakeError('canonical_probe_binding_root_invalid')
    entries = canonical.get('entries')
    if (not isinstance(entries, list)
            or canonical.get('file_count') != len(entries)):
        raise IntakeError('canonical_probe_binding_entries_invalid')
    by_path = {}
    for entry in entries:
        if (not isinstance(entry, Mapping)
                or set(entry) != {'path', 'size_bytes', 'sha256'}
                or not _text(entry.get('path'))
                or Path(entry['path']).is_absolute()
                or '..' in Path(entry['path']).parts
                or type(entry.get('size_bytes')) is not int
                or entry['size_bytes'] < 0
                or not _valid_sha256(entry.get('sha256'))
                or entry['path'] in by_path):
            raise IntakeError('canonical_probe_binding_entries_invalid')
        by_path[entry['path']] = dict(entry)
    required = {
        'isolated_probe_source':
            'src/limo_cleanup_ros1_perception/rosbag1_isolated_probe.py',
        'rosbag1_indexer_source':
            'src/limo_cleanup_ros1_perception/rosbag1_rgbd_indexer.py',
    }
    admitted = {}
    for role, relative in required.items():
        entry = by_path.get(relative)
        path = (source_root / relative).resolve(strict=True)
        identity = regular_file_identity(path)
        if (entry is None
                or entry['size_bytes'] != identity['size_bytes']
                or entry['sha256'] != identity['sha256']
                or authority[role] != identity):
            raise IntakeError('canonical_probe_binding_mismatch:' + role)
        admitted[role] = identity
    return {
        'canonical_source_admission':
            authority['canonical_source_admission'],
        'canonical_source_root': str(source_root),
        'bound_artifacts': admitted,
    }


def _load_request(
        path: Path, authority: Mapping[str, Any]) -> Mapping[str, Any]:
    actual, raw = _read_regular_file_once(path, collect_raw=True)
    if actual != authority.get('request_identity'):
        raise IntakeError('request_authority_identity_mismatch')
    try:
        value = _strict_json_bytes(raw if raw is not None else b'')
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntakeError('request_json_invalid') from error
    if not isinstance(value, Mapping) or set(value) != REQUEST_KEYS:
        raise IntakeError('request_schema_invalid')
    mode = TEST_ONLY_MODE if authority['test_only'] else PRODUCTION_MODE
    if (value.get('schema_version') != 1
            or value.get('marker') != REQUEST_MARKER
            or not _text(value.get('request_id'))
            or value.get('mode') != mode
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('publishes_ros_messages') is not False
            or value.get('runtime_family') != 'ROS1'
            or value.get('ros_distro') != 'noetic'
            or value.get('canonical_source_admission')
            != authority.get('canonical_source_admission')
            or value.get('field_install_evidence')
            != authority.get('field_install_evidence')):
        raise IntakeError('request_policy_invalid')
    release = value.get('release_binding')
    if (not isinstance(release, Mapping)
            or set(release) != RELEASE_BINDING_KEYS
            or not _text(release.get('release_id'))
            or not _valid_sha256(
                release.get('source_manifest_artifact_sha256'))
            or not _valid_sha256(release.get('source_set_sha256'))
            or not _finite(
                release.get('manifest_generated_at_unix_sec'), 0.0)):
        raise IntakeError('request_release_binding_invalid')
    model_hashes = value.get('model_artifact_sha256')
    if (not isinstance(model_hashes, Mapping)
            or set(model_hashes) != set(MODEL_CLASSES)
            or any(not _valid_sha256(item) for item in model_hashes.values())
            or not _valid_sha256(value.get('model_set_sha256'))):
        raise IntakeError('request_model_binding_invalid')
    if value['model_set_sha256'] != _model_set_sha256(model_hashes):
        raise IntakeError('request_model_set_sha256_mismatch')
    scenes = value.get('scenes')
    if not isinstance(scenes, Mapping) or list(scenes) != list(SCENES):
        raise IntakeError('request_scene_set_invalid')
    return dict(value)


def _validate_scene_declarations(
        request: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    scenes: Dict[str, Mapping[str, Any]] = {}
    seen_capture_ids = set()
    seen_task_ids = set()
    seen_bundle_ids = set()
    seen_paths = {
        str(_identity_path(
            request['canonical_source_admission'],
            'canonical_source_admission')),
        str(_identity_path(
            request['field_install_evidence'],
            'field_install_evidence')),
    }
    windows = []
    for expected_scene in SCENES:
        scene = request['scenes'][expected_scene]
        if not isinstance(scene, Mapping) or set(scene) != SCENE_KEYS:
            raise IntakeError('scene_schema_invalid:' + expected_scene)
        if scene.get('scene') != expected_scene:
            raise IntakeError('scene_name_mismatch:' + expected_scene)
        collector_request = scene.get('collector_request')
        minimum_frames = (
            1 if request.get('mode') == TEST_ONLY_MODE
            else MIN_PRODUCTION_SCENE_FRAMES)
        if (not isinstance(collector_request, Mapping)
                or set(collector_request) != COLLECTOR_REQUEST_KEYS
                or collector_request.get('topic')
                != EXPECTED_COLLECTOR_TOPIC
                or collector_request.get('message_type')
                != EXPECTED_COLLECTOR_MESSAGE_TYPE
                or not _integer(
                    collector_request.get('max_frames'), minimum_frames)
                or not _finite(
                    collector_request.get('duration_sec'), 0.0)
                or float(collector_request['duration_sec']) <= 0.0):
            raise IntakeError(
                'scene_collector_request_invalid:' + expected_scene)
        for key, seen in (
                ('capture_id', seen_capture_ids), ('task_id', seen_task_ids),
                ('bundle_id', seen_bundle_ids)):
            value = scene.get(key)
            if not _text(value) or value in seen:
                raise IntakeError('scene_identity_duplicate_or_invalid:' + key)
            seen.add(value)
        window = scene.get('capture_window')
        if (not isinstance(window, Mapping)
                or set(window) != CAPTURE_WINDOW_KEYS
                or not all(_integer(window.get(key), 1)
                           for key in CAPTURE_WINDOW_KEYS)
                or window['header_start_ns'] > window['header_end_ns']
                or window['record_start_ns'] > window['record_end_ns']
                or abs(
                    window['record_start_ns'] - window['header_start_ns'])
                > MAX_DECLARED_RECORD_HEADER_SKEW_NS
                or abs(window['record_end_ns'] - window['header_end_ns'])
                > MAX_DECLARED_RECORD_HEADER_SKEW_NS):
            raise IntakeError('scene_capture_window_invalid:' + expected_scene)
        for prior_start, prior_end in windows:
            if not (
                    window['record_end_ns'] < prior_start
                    or window['record_start_ns'] > prior_end):
                raise IntakeError('scene_capture_window_overlap')
        windows.append((window['record_start_ns'], window['record_end_ns']))
        output_path = scene.get('probe_output_path')
        if (not isinstance(output_path, str)
                or not Path(output_path).is_absolute()
                or str(Path(output_path)).lower().endswith('.db3')):
            raise IntakeError('scene_probe_output_path_invalid')
        normalized_output = str(Path(output_path).absolute())
        if normalized_output in seen_paths:
            raise IntakeError('scene_artifact_path_reused')
        seen_paths.add(normalized_output)
        artifacts = scene.get('artifacts')
        if (not isinstance(artifacts, Mapping)
                or set(artifacts) != set(ARTIFACT_ROLES)):
            raise IntakeError('scene_artifact_set_invalid:' + expected_scene)
        for role in ARTIFACT_ROLES:
            path = _identity_path(
                artifacts[role], '{}:{}'.format(expected_scene, role))
            normalized = str(path)
            if normalized in seen_paths:
                raise IntakeError('scene_artifact_path_reused')
            seen_paths.add(normalized)
        scenes[expected_scene] = dict(scene)
    return scenes


def _check_raw_bag(
        identity: Mapping[str, Any], kind: str) -> Path:
    path, prefix = _read_identity_material(
        identity, kind, prefix_size=32)
    if path.suffix.lower() != '.bag':
        raise IntakeError('raw_capture_not_rosbag1_suffix')
    material = prefix if prefix is not None else b''
    if (not material.startswith(b'#ROSBAG V2.0\n')
            or material.startswith(b'SQLite format 3\x00')
            or material.lstrip().startswith((b'{', b'['))):
        raise IntakeError('raw_capture_not_rosbag1')
    return path


def _load_exact_probe(authority: Mapping[str, Any]) -> Any:
    source_path = _identity_path(
        authority['isolated_probe_source'], 'isolated_probe_source')
    expected_indexer = source_path.with_name('rosbag1_rgbd_indexer.py')
    if regular_file_identity(expected_indexer) != authority[
            'rosbag1_indexer_source']:
        raise IntakeError('isolated_probe_indexer_sibling_mismatch')
    name = '_limo_host_anchored_rosbag1_probe'
    spec = importlib.util.spec_from_file_location(name, str(source_path))
    if spec is None or spec.loader is None:
        raise IntakeError('isolated_probe_loader_unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runner = getattr(module, 'run_isolated_rosbag_probe', None)
    reconstruct = getattr(module, 'reconstruct_probe_records', None)
    if not callable(runner) or not callable(reconstruct):
        raise IntakeError('isolated_probe_api_missing')
    return module


def _load_exact_indexer(authority: Mapping[str, Any]) -> Any:
    source_path = _identity_path(
        authority['rosbag1_indexer_source'], 'rosbag1_indexer_source')
    name = '_limo_host_anchored_rosbag1_indexer'
    spec = importlib.util.spec_from_file_location(name, str(source_path))
    if spec is None or spec.loader is None:
        raise IntakeError('rosbag1_indexer_loader_unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (not callable(getattr(module, 'load_formal_manifest', None))
            or not callable(getattr(module, 'inspect_records', None))
            or getattr(module, 'FORMAL_CAMERA_ONLY_MODE', None)
            != 'formal_camera_only'):
        raise IntakeError('rosbag1_indexer_api_invalid')
    return module


def _validate_probe_artifact(
        scene_name: str, scene: Mapping[str, Any],
        authority: Mapping[str, Any], result: Mapping[str, Any],
        probe_module: Any, test_only: bool) -> Mapping:
    if (not isinstance(result, Mapping)
            or result.get('algorithm_validated') is not True
            or (not test_only and result.get('validated_pass') is not True)
            or (test_only and result.get('validated_pass') is not False)
            or result.get('read_only') is not True
            or result.get('authorizes_motion') is not False
            or result.get('publishes_ros_messages') is not False
            or result.get('delivery_ready') is not False
            or result.get('formal_acceptance') is not False
            or result.get('not_in_four_scene_denominator') is not True
            or result.get('failures') != []):
        raise IntakeError('isolated_probe_result_not_valid:' + scene_name)
    executable_target = authority['python_executable_target']
    parent_admission = result.get('parent_executable_admission')
    child_admission = result.get('child_executable_admission')
    if (not isinstance(parent_admission, Mapping)
            or parent_admission.get('target_identity') != executable_target
            or not isinstance(child_admission, Mapping)
            or child_admission.get('target_identity') != executable_target
            or result.get('sys_executable_identity') != executable_target
            or (not test_only and (
                not isinstance(result.get('argv'), list)
                or not result['argv']
                or result['argv'][0] != executable_target['path']))):
        raise IntakeError('isolated_probe_executable_admission_invalid:' + scene_name)
    output_identity = result.get('output_identity')
    output_path, artifact = _load_identity_json_with_path(
        output_identity, 'probe_output:' + scene_name)
    if output_path != Path(scene['probe_output_path']).resolve(strict=True):
        raise IntakeError('isolated_probe_output_path_mismatch:' + scene_name)
    if (not isinstance(artifact, Mapping)
            or set(artifact) != PROBE_ARTIFACT_KEYS
            or artifact.get('schema_version') != 1
            or artifact.get('marker') != authority['artifact_markers'][
                'probe_output']
            or artifact.get('read_only') is not True
            or artifact.get('authorizes_motion') is not False
            or artifact.get('publishes_ros_messages') is not False
            or artifact.get('delivery_ready') is not False
            or artifact.get('capture_id') != scene['capture_id']
            or artifact.get('scene') != scene_name
            or artifact.get('bag_identity') != scene['artifacts']['raw_bag']
            or artifact.get('rosbag_module_identity')
            != authority['rosbag_module']
            or artifact.get('indexer_module_identity')
            != authority['rosbag1_indexer_source']
            or artifact.get('formal_manifest_identity')
            != authority['formal_manifest']
            or artifact.get('probe_source_identity')
            != authority['isolated_probe_source']
            or artifact.get('sys_executable_identity') != executable_target
            or artifact.get('parent_executable_admission') != parent_admission
            or artifact.get('child_executable_admission') != child_admission
            or artifact.get('test_only') is not test_only
            or artifact.get('algorithm_validated') is not True
            or artifact.get('formal_acceptance') is not False
            or artifact.get('not_in_four_scene_denominator') is not True):
        raise IntakeError(
            'isolated_probe_artifact_schema_invalid:' + scene_name)
    connections = artifact.get('connections')
    messages = artifact.get('messages')
    if (not isinstance(connections, list) or not connections
            or not isinstance(messages, list) or not messages
            or artifact.get('connection_count') != len(connections)
            or artifact.get('message_count') != len(messages)
            or not _integer(artifact.get('total_payload_bytes'), 1)):
        raise IntakeError(
            'isolated_probe_record_denominator_invalid:' + scene_name)
    embedded_report = artifact.get('formal_report')
    if probe_module is None:
        if not test_only:
            raise IntakeError('production_probe_module_missing')
        report = embedded_report
    else:
        try:
            connections, messages, reconstructed = (
                probe_module.reconstruct_probe_records(output_path))
        except Exception as error:
            raise IntakeError(
                'isolated_probe_record_reconstruction_failed:' + scene_name
            ) from error
        if reconstructed != embedded_report:
            raise IntakeError(
                'isolated_probe_embedded_report_mismatch:' + scene_name)
        indexer = _load_exact_indexer(authority)
        try:
            manifest = indexer.load_formal_manifest(
                Path(authority['formal_manifest']['path']))
            report = indexer.inspect_records(
                connections, messages, scene['capture_id'], scene_name,
                manifest, scene['artifacts']['raw_bag'],
                indexer.FORMAL_CAMERA_ONLY_MODE)
        except Exception as error:
            raise IntakeError(
                'host_formal_rosbag1_recompute_failed:' + scene_name
            ) from error
    injected_test_only_report = probe_module is None and test_only
    expected_report_formal = not injected_test_only_report
    expected_report_not_in_denominator = injected_test_only_report
    bundles = report.get('accepted_bundles') if isinstance(
        report, Mapping) else None
    if (not isinstance(report, Mapping)
            or report.get('storage_identifier') != 'rosbag1-v2'
            or report.get('mode') != 'formal_camera_only'
            or report.get('inspection_passed') is not True
            or report.get('formal_acceptance') is not expected_report_formal
            or report.get('shared_graph') is not False
            or report.get('mixed_tf') is not False
            or report.get('not_in_four_scene_denominator')
            is not expected_report_not_in_denominator
            or report.get('delivery_ready') is not False
            or report.get('capture_id') != scene['capture_id']
            or report.get('scene') != scene_name
            or report.get('capture_window') != scene['capture_window']
            or not isinstance(bundles, list) or not bundles):
        raise IntakeError('isolated_probe_formal_report_invalid:' + scene_name)
    window = scene['capture_window']
    for bundle in bundles:
        header_stamps = bundle.get('header_stamps_ns') if isinstance(
            bundle, Mapping) else None
        record_stamps = bundle.get('stream_record_timestamps_ns') if isinstance(
            bundle, Mapping) else None
        if (not isinstance(header_stamps, Mapping) or not header_stamps
                or not isinstance(record_stamps, Mapping) or not record_stamps
                or any(not _integer(stamp, window['header_start_ns'])
                       or stamp > window['header_end_ns']
                       for stamp in header_stamps.values())
                or any(not _integer(stamp, 1)
                       for stamp in record_stamps.values())):
            raise IntakeError(
                'isolated_probe_bundle_window_mismatch:' + scene_name)
        if not test_only:
            required_streams = {
                'rgb', 'raw_depth',
                'rgb_camera_info', 'depth_camera_info'}
            if (set(header_stamps) != required_streams
                    or set(record_stamps) != required_streams
                    or any(
                        not _integer(
                            record_stamps[role], window['record_start_ns'])
                        or record_stamps[role] > window['record_end_ns']
                        for role in ('rgb', 'raw_depth'))
                    or any(
                        abs(record_stamps[role] - header_stamps[role])
                        > MAX_DECLARED_RECORD_HEADER_SKEW_NS
                        for role in required_streams)):
                raise IntakeError(
                    'isolated_probe_bundle_window_mismatch:' + scene_name)
        elif any(
                role in header_stamps
                and abs(stamp - header_stamps[role])
                > MAX_DECLARED_RECORD_HEADER_SKEW_NS
                for role, stamp in record_stamps.items()):
            raise IntakeError(
                'isolated_probe_bundle_window_mismatch:' + scene_name)
    admitted = dict(artifact)
    admitted['formal_report'] = dict(report)
    return admitted


def _validate_collector(
        value: Any, scene_name: str, scene: Mapping[str, Any],
        frames: Sequence[Mapping[str, Any]]) -> None:
    expected_output = scene['artifacts']['typed_frames']
    expected_request = scene['collector_request']
    if (not isinstance(value, Mapping) or set(value) != COLLECTOR_KEYS
            or value.get('schema_version') != 1
            or value.get('collector_kind')
            != ARTIFACT_MARKERS['collector_manifest']
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('publishes_ros_messages') is not False
            or value.get('scene') != scene_name
            or value.get('topic') != EXPECTED_COLLECTOR_TOPIC
            or value.get('message_type')
            != EXPECTED_COLLECTOR_MESSAGE_TYPE
            or value.get('task_id') != scene['task_id']
            or value.get('topic') != expected_request['topic']
            or value.get('message_type') != expected_request['message_type']
            or not _integer(value.get('max_frames'), 1)
            or value.get('max_frames') != expected_request['max_frames']
            or not _finite(value.get('duration_sec'), 0.0)
            or float(value['duration_sec']) <= 0.0
            or value.get('duration_sec') != expected_request['duration_sec']
            or value.get('max_frames') != len(frames)
            or value.get('output') != expected_output
            or value.get('received_frames') != len(frames)
            or value.get('unique_frames') != len(frames)
            or value.get('duplicate_sequences') != 0
            or value.get('duplicate_bundle_ids') != 0
            or value.get('serialization_errors') != 0
            or value.get('interrupted') is not False
            or value.get('completed_minimum') is not True
            or value.get('completed_requested_frames') is not True):
        raise IntakeError('collector_manifest_invalid:' + scene_name)


def _validate_typed_target(
        target: Any, frame: Mapping[str, Any], scene_name: str,
        observations: Mapping[str, Any]) -> str:
    if not isinstance(target, Mapping) or set(target) != TYPED_TARGET_KEYS:
        raise IntakeError('typed_target_schema_invalid:' + scene_name)
    observation_id = target.get('observation_id')
    object_class = target.get('object_class')
    bbox = target.get('bbox')
    pixels = target.get('depth_valid_pixels')
    total = target.get('depth_total_pixels')
    ratio = target.get('depth_valid_ratio')
    expected_status = (
        'observed' if object_class == 'trash_bin'
        else ('already_in_bin' if scene_name == 'bottle_in_bin' else 'active'))
    expected_actionable = (
        object_class == 'plastic_bottle'
        and scene_name == 'bottle_outside')
    if (not _text(observation_id) or observation_id in observations
            or object_class not in MODEL_CLASSES
            or not _finite(target.get('confidence'), 0.0)
            or float(target['confidence']) > 1.0
            or target.get('valid') is not True
            or target.get('actionable') is not expected_actionable
            or target.get('status') != expected_status
            or target.get('error_code') != ''
            or not _point(target.get('position'))
            or not _point(target.get('size'))
            or any(float(target['size'][axis]) <= 0.0
                   for axis in ('x', 'y', 'z'))
            or not _vector(bbox, 4)
            or bbox[0] < 0.0 or bbox[1] < 0.0
            or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]
            or not _finite(target.get('depth_m'), 0.0)
            or float(target['depth_m']) <= 0.0
            or not _integer(pixels, 1) or not _integer(total, 1)
            or pixels > total
            or not _finite(ratio, 0.0) or float(ratio) > 1.0
            or abs(float(ratio) - pixels / total) > 1e-9
            or float(ratio) < MIN_DEPTH_VALID_RATE
            or not _text(target.get('source'))
            or target.get('position_semantics')
            != 'base_link_from_independent_extrinsics'
            or frame.get('tf_target_frame') != 'base_link'
            or frame.get('tf_valid') is not True
            or frame.get('tf_transform_applied') is not True):
        raise IntakeError('typed_target_contract_invalid:' + scene_name)
    return observation_id


def _validate_frames(
        frames: Sequence[Any], scene_name: str, scene: Mapping[str, Any],
        request: Mapping[str, Any], minimum: int) -> Mapping:
    if len(frames) < minimum:
        raise IntakeError('typed_frame_zero_or_below_minimum:' + scene_name)
    by_key = {}
    observations = {}
    previous_sequence = 0
    previous_stamp = 0
    for row_index, frame in enumerate(frames):
        if not isinstance(frame, Mapping) or set(frame) != FRAME_KEYS:
            raise IntakeError('typed_frame_schema_invalid:' + scene_name)
        stamp_ns = _stamp_ns(frame)
        sequence = frame.get('sequence')
        key = (sequence, stamp_ns, frame.get('bundle_id'))
        received = frame.get('received_unix_sec')
        transport = frame.get('transport_latency_sec')
        if (frame.get('schema_version') != 1
                or frame.get('read_only') is not True
                or not _integer(sequence, 1) or sequence <= previous_sequence
                or stamp_ns is None or stamp_ns <= previous_stamp
                or not _valid_sha256(frame.get('bundle_id'))
                or frame.get('capture_id') != scene['capture_id']
                or frame.get('task_id') != scene['task_id']
                or frame.get('scene') != scene_name
                or frame.get('model_binding_sha256')
                != request['model_set_sha256']
                or key in by_key or not isinstance(frame.get('targets'), list)
                or frame.get('valid') is not True
                or frame.get('status') not in ('no_targets', 'targets_valid')
                or frame.get('error_code') != ''
                or frame.get('tf_target_frame') != 'base_link'
                or frame.get('tf_valid') is not True
                or frame.get('tf_transform_applied') is not True
                or frame.get('tf_status') != 'applied'
                or frame.get('tf_error_code') != ''
                or not _finite(received, 0.0)
                or not _finite(frame.get('processing_latency_sec'), 0.0)
                or not _finite(transport, 0.0)
                or abs(float(transport) - (float(received) - stamp_ns / 1e9))
                > 1e-6
                or not _finite(frame.get('sync_span_sec'), 0.0)
                or frame.get('status')
                != ('targets_valid' if frame['targets'] else 'no_targets')):
            raise IntakeError('typed_frame_identity_invalid:' + scene_name)
        previous_sequence = sequence
        previous_stamp = stamp_ns
        by_key[key] = (row_index, frame)
        for target in frame['targets']:
            observation_id = _validate_typed_target(
                target, frame, scene_name, observations)
            observations[observation_id] = (key, target)
    return {'frames': by_key, 'observations': observations}


def _bundle_map(probe_artifact: Mapping[str, Any], scene_name: str) -> Mapping:
    result = {}
    bundles = probe_artifact['formal_report']['accepted_bundles']
    for bundle in bundles:
        index = bundle.get('index') if isinstance(bundle, Mapping) else None
        stamps = bundle.get('header_stamps_ns') if isinstance(
            bundle, Mapping) else None
        payloads = bundle.get('stream_payload_sha256') if isinstance(
            bundle, Mapping) else None
        if (not _integer(index, 0) or index in result
                or not isinstance(stamps, Mapping)
                or not _integer(stamps.get('rgb'), 1)
                or not isinstance(payloads, Mapping)):
            raise IntakeError('probe_bundle_schema_invalid:' + scene_name)
        result[index] = bundle
    return result


def _validate_typed_raw(
        value: Any, scene_name: str, scene: Mapping[str, Any],
        request: Mapping[str, Any], frame_report: Mapping,
        probe_artifact: Mapping[str, Any], test_only: bool) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != BINDING_KEYS:
        raise IntakeError('typed_raw_binding_schema_invalid:' + scene_name)
    associations = value.get('associations')
    frames = frame_report['frames']
    bundles = _bundle_map(probe_artifact, scene_name)
    expected_scope = (
        'test_only_rosbag1_typed_raw_binding' if test_only
        else 'production_rosbag1_typed_raw_binding')
    if (value.get('schema_version') != 2
            or value.get('report_kind')
            != ARTIFACT_MARKERS['typed_raw_binding']
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('publishes_ros_messages') is not False
            or value.get('capture_id') != scene['capture_id']
            or value.get('task_id') != scene['task_id']
            or value.get('scene') != scene_name
            or value.get('model_binding_sha256')
            != request['model_set_sha256']
            or value.get('evidence_scope') != expected_scope
            or not _valid_sha256(value.get('binding_sha256'))
            or value.get('test_only') is not test_only
            or value.get('validated_pass') is not True
            or value.get('formal_acceptance') is not (not test_only)
            or value.get('not_in_four_scene_denominator') is not test_only
            or value.get('delivery_ready') is not False
            or value.get('failures') != []
            or not isinstance(associations, list)
            or len(associations) != len(frames)
            or len(associations) != len(bundles)
            or value.get('typed_frame_count') != len(frames)
            or value.get('raw_bundle_count') != len(bundles)
            or value.get('association_count') != len(associations)
            or value.get('minimum_scene_frames')
            != (1 if test_only else MIN_PRODUCTION_SCENE_FRAMES)
            or value.get('unpaired_typed_count') != 0
            or value.get('unpaired_raw_bundle_count') != 0):
        raise IntakeError('typed_raw_binding_policy_invalid:' + scene_name)
    seen_rows = set()
    seen_bundles = set()
    raw_by_frame = {}
    for association in associations:
        if not isinstance(association, Mapping):
            raise IntakeError('typed_raw_association_invalid:' + scene_name)
        row = association.get('typed_row_index')
        sequence = association.get('sequence')
        stamp_ns = association.get('stamp_ns')
        bundle_id = association.get('bundle_id')
        key = (sequence, stamp_ns, bundle_id)
        pair = frames.get(key)
        raw_index = association.get('raw_bundle_index')
        raw = bundles.get(raw_index)
        if (not _integer(row, 0) or row in seen_rows
                or pair is None or pair[0] != row
                or association.get('typed_frame_sha256')
                != _canonical_sha256(pair[1])
                or raw is None or raw_index in seen_bundles
                or raw.get('header_stamps_ns', {}).get('rgb') != stamp_ns
                or association.get('raw_stream_payload_sha256')
                != raw.get('stream_payload_sha256')):
            raise IntakeError('typed_raw_association_invalid:' + scene_name)
        seen_rows.add(row)
        seen_bundles.add(raw_index)
        raw_by_frame[key] = raw
    if seen_bundles != set(bundles):
        raise IntakeError('typed_raw_bundle_coverage_invalid:' + scene_name)
    if set(raw_by_frame) != set(frames):
        raise IntakeError('typed_raw_frame_coverage_invalid:' + scene_name)
    tf_graph = probe_artifact.get('formal_report', {}).get('tf_graph')
    if (not isinstance(tf_graph, Mapping)
            or tf_graph.get('camera_only') is not True
            or not isinstance(tf_graph.get('transforms'), list)
            or not tf_graph['transforms']):
        raise IntakeError('formal_tf_graph_invalid:' + scene_name)
    return {'raw_by_frame': raw_by_frame, 'tf_graph': tf_graph}


def _common_semantic(
        value: Any, expected_keys: set, expected_kind: str,
        scene_name: str, scene: Mapping[str, Any], request: Mapping[str, Any],
        test_only: bool) -> List[Mapping[str, Any]]:
    if (not isinstance(value, Mapping) or set(value) != expected_keys
            or value.get('schema_version') != 1
            or value.get('report_kind') != expected_kind
            or value.get('scene') != scene_name
            or value.get('capture_id') != scene['capture_id']
            or value.get('task_id') != scene['task_id']
            or value.get('ros1_field_install_sha256')
            != request['field_install_evidence']['sha256']
            or value.get('model_binding_sha256')
            != request['model_set_sha256']
            or value.get('synthetic_test_only') is not test_only
            or not isinstance(value.get('records'), list)):
        raise IntakeError('semantic_artifact_schema_invalid:' + expected_kind)
    return value['records']


def _record_key(value: Mapping[str, Any]) -> Optional[Tuple[Any, Any, Any]]:
    if not isinstance(value, Mapping):
        return None
    key = (
        value.get('sequence'), value.get('stamp_ns'), value.get('bundle_id'))
    if (not _integer(key[0], 1) or not _integer(key[1], 1)
            or not _valid_sha256(key[2])):
        return None
    return key


def _exact_frame_record_map(
        records: Sequence[Mapping[str, Any]], frame_keys: set,
        kind: str) -> Mapping:
    result = {}
    for record in records:
        key = _record_key(record)
        if key is None or key in result or key not in frame_keys:
            raise IntakeError(kind + '_frame_join_invalid')
        result[key] = record
    if set(result) != frame_keys:
        raise IntakeError(kind + '_frame_coverage_invalid')
    return result


def _validate_extrinsics_reference(
        value: Any, scene_name: str, scene: Mapping[str, Any],
        request: Mapping[str, Any], test_only: bool,
        source_frame: str) -> Mapping[str, Any]:
    if (not isinstance(value, Mapping) or set(value) != EXTRINSICS_KEYS
            or value.get('schema_version') != 1
            or value.get('report_kind')
            != ARTIFACT_MARKERS['extrinsics_reference']
            or value.get('scene') != scene_name
            or value.get('capture_id') != scene['capture_id']
            or value.get('task_id') != scene['task_id']
            or value.get('ros1_field_install_sha256')
            != request['field_install_evidence']['sha256']
            or value.get('model_binding_sha256')
            != request['model_set_sha256']
            or value.get('synthetic_test_only') is not test_only):
        raise IntakeError('extrinsics_reference_schema_invalid:' + scene_name)
    translation = value.get('translation_m')
    rotation = value.get('rotation_xyzw')
    transform_payload = {
        'source_frame': value.get('source_frame'),
        'target_frame': value.get('target_frame'),
        'translation_m': translation,
        'rotation_xyzw': rotation,
    }
    measured = value.get('measured_at_unix_sec')
    reviewed = value.get('reviewed_at_unix_sec')
    if (value.get('source_frame') != source_frame
            or value.get('target_frame') != 'base_link'
            or not _vector(translation, 3) or not _vector(rotation, 4)
            or abs(math.sqrt(sum(float(item) ** 2 for item in rotation)) - 1.0)
            > 1e-6
            or value.get('transform_sha256')
            != _canonical_sha256(transform_payload)
            or not _text(value.get('measurement_method'))
            or not _text(value.get('operator_id'))
            or not _text(value.get('reviewer_id'))
            or value.get('operator_id') == value.get('reviewer_id')
            or not _finite(measured, 0.0) or not _finite(reviewed, measured)):
        raise IntakeError('extrinsics_reference_policy_invalid:' + scene_name)
    return dict(value)


def _raw_camera_transform(
        tf_graph: Mapping[str, Any], frame_id: str,
        scene_name: str) -> Mapping[str, Any]:
    transforms = tf_graph.get('transforms') if isinstance(
        tf_graph, Mapping) else None
    matches = [
        item for item in transforms if isinstance(item, Mapping)
        and item.get('child_frame_id') == frame_id
    ] if isinstance(transforms, list) else []
    if (tf_graph.get('camera_only') is not True
            or tf_graph.get('base_chain_required') is not False
            or len(matches) != 1):
        raise IntakeError('tf_raw_camera_transform_missing:' + scene_name)
    value = matches[0]
    if (value.get('topic') not in ('/tf', '/tf_static')
            or not _integer(value.get('message_id'), 1)
            or not _integer(value.get('connection_id'), 1)
            or not _integer(value.get('transform_index'), 0)
            or not _text(value.get('callerid'))
            or not _integer(value.get('stamp_ns'), 0)
            or not _text(value.get('parent_frame_id'))
            or value.get('parent_frame_id') == 'base_link'
            or value.get('child_frame_id') == 'base_link'
            or not _vector(value.get('translation_m'), 3)
            or not _vector(value.get('rotation_xyzw'), 4)
            or not _valid_sha256(value.get('serialized_sha256'))):
        raise IntakeError('tf_raw_camera_transform_invalid:' + scene_name)
    return value


def _validate_semantic_records(
        scene_name: str, scene: Mapping[str, Any],
        request: Mapping[str, Any], frame_report: Mapping,
        loaded: Mapping[str, Any], test_only: bool) -> Mapping:
    frames = frame_report['frames']
    frame_keys = set(frames)
    raw_by_frame = frame_report.get('raw_by_frame')
    tf_graph = frame_report.get('tf_graph')
    if (not isinstance(raw_by_frame, Mapping)
            or set(raw_by_frame) != frame_keys
            or not isinstance(tf_graph, Mapping)):
        raise IntakeError('semantic_binding_context_missing:' + scene_name)
    source_frames = {pair[1].get('frame_id') for pair in frames.values()}
    if source_frames != {'camera_color_optical_frame'}:
        raise IntakeError('typed_frame_source_frame_invalid:' + scene_name)
    extrinsics = _validate_extrinsics_reference(
        loaded['extrinsics_reference'], scene_name, scene, request,
        test_only, 'camera_color_optical_frame')

    ground = loaded['ground_truth']
    ground_records = _common_semantic(
        ground, GROUND_TRUTH_KEYS, ARTIFACT_MARKERS['ground_truth'],
        scene_name, scene, request, test_only)
    ground_map = _exact_frame_record_map(
        ground_records, frame_keys, 'ground_truth')
    annotation_count = 0
    expected_classes = {
        'background': set(),
        'bin_only': {'trash_bin'},
        'bottle_in_bin': {'plastic_bottle', 'trash_bin'},
        'bottle_outside': {'plastic_bottle', 'trash_bin'},
    }[scene_name]
    for key, record in ground_map.items():
        frame = frames[key][1]
        raw = raw_by_frame[key]
        annotations = record.get('annotations')
        if (set(record) != GROUND_RECORD_KEYS
                or record.get('typed_frame_sha256')
                != _canonical_sha256(frame)
                or record.get('rgb_payload_sha256')
                != raw.get('stream_payload_sha256', {}).get('rgb')
                or not isinstance(annotations, list)):
            raise IntakeError('ground_truth_typed_raw_binding_invalid:' + scene_name)
        annotation_count += len(annotations)
        instance_ids = set()
        for annotation in annotations:
            if (not isinstance(annotation, Mapping)
                    or set(annotation) != ANNOTATION_KEYS
                    or not _text(annotation.get('instance_id'))
                    or annotation['instance_id'] in instance_ids
                    or annotation.get('object_class') not in MODEL_CLASSES
                    or not _vector(annotation.get('bbox'), 4)
                    or annotation['bbox'][0] < 0.0
                    or annotation['bbox'][1] < 0.0
                    or annotation['bbox'][2] <= annotation['bbox'][0]
                    or annotation['bbox'][3] <= annotation['bbox'][1]
                    or annotation.get('relation') != (
                        'container' if annotation.get('object_class') == 'trash_bin'
                        else ('inside_bin' if scene_name == 'bottle_in_bin'
                              else 'outside_bin'))):
                raise IntakeError('ground_truth_annotation_invalid:' + scene_name)
            instance_ids.add(annotation['instance_id'])
        observed_classes = {item['object_class'] for item in annotations}
        typed_classes = {item['object_class'] for item in frame['targets']}
        if observed_classes != expected_classes or typed_classes != expected_classes:
            raise IntakeError(
                'four_scene_ground_truth_semantics_invalid:' + scene_name)
    metrics = _class_metrics(ground_map, frames)
    declared_metrics = ground.get('class_metrics')
    if (not isinstance(declared_metrics, Mapping)
            or set(declared_metrics) != set(MODEL_CLASSES)
            or any(not isinstance(declared_metrics.get(label), Mapping)
                   or set(declared_metrics[label]) != CLASS_METRIC_KEYS
                   for label in MODEL_CLASSES)
            or declared_metrics != metrics
            or any(metrics[label]['precision'] < 0.90
                   or metrics[label]['recall'] < 0.90
                   or metrics[label]['f1'] < 0.90
                   for label in MODEL_CLASSES)
            or ground.get('complete') is not True
            or ground.get('unique_frames') != len(ground_map)
            or ground.get('annotation_count') != annotation_count):
        raise IntakeError('ground_truth_summary_recompute_mismatch')

    tf_value = loaded['tf_records']
    tf_records = _common_semantic(
        tf_value, TF_KEYS, ARTIFACT_MARKERS['tf_records'],
        scene_name, scene, request, test_only)
    tf_map = _exact_frame_record_map(tf_records, frame_keys, 'tf')
    raw_transform = _raw_camera_transform(
        tf_graph, 'camera_color_optical_frame', scene_name)
    expected_raw_identity = {
        'topic': raw_transform['topic'],
        'message_id': raw_transform['message_id'],
        'connection_id': raw_transform['connection_id'],
        'transform_index': raw_transform['transform_index'],
        'callerid': raw_transform['callerid'],
        'transform_stamp_ns': raw_transform['stamp_ns'],
        'parent_frame_id': raw_transform['parent_frame_id'],
        'child_frame_id': raw_transform['child_frame_id'],
        'translation_m': raw_transform['translation_m'],
        'rotation_xyzw': raw_transform['rotation_xyzw'],
        'serialized_sha256': raw_transform['serialized_sha256'],
    }
    for key, record in tf_map.items():
        frame = frames[key][1]
        if (set(record) != TF_RECORD_KEYS
                or any(record.get(name) != expected
                       for name, expected in expected_raw_identity.items())
                or record.get('lookup_source_frame') != frame.get('frame_id')
                or record.get('lookup_target_frame') != 'base_link'
                or record.get('lookup_succeeded') is not True
                or record.get('transform_applied') is not True
                or record.get('output_frame') != 'base_link'
                or record.get('extrinsics_transform_sha256')
                != extrinsics['transform_sha256']
                or not isinstance(record.get('target_transforms'), list)):
            raise IntakeError('tf_raw_identity_or_application_invalid:' + scene_name)
        transformed = {}
        targets = {item['observation_id']: item for item in frame['targets']}
        for item in record['target_transforms']:
            observation_id = item.get('observation_id') if isinstance(
                item, Mapping) else None
            target = targets.get(observation_id)
            input_position = item.get('input_position_m') if isinstance(
                item, Mapping) else None
            output_position = item.get('output_position_m') if isinstance(
                item, Mapping) else None
            if (not isinstance(item, Mapping)
                    or set(item) != TARGET_TRANSFORM_KEYS
                    or observation_id in transformed or target is None
                    or not _vector(input_position, 3)
                    or not _vector(output_position, 3)
                    or item.get('extrinsics_transform_sha256')
                    != extrinsics['transform_sha256']
                    or abs(float(input_position[2]) - target['depth_m']) > 1e-6
                    or not _same_vector(
                        _transform_point(
                            input_position, extrinsics['translation_m'],
                            extrinsics['rotation_xyzw']), output_position, 1e-6)
                    or not _same_vector(
                        output_position, _point_vector(target['position']), 1e-6)):
                raise IntakeError('tf_target_transform_recompute_mismatch:' + scene_name)
            transformed[observation_id] = item
        if set(transformed) != set(targets):
            raise IntakeError('tf_target_transform_coverage_invalid:' + scene_name)
    if (tf_value.get('source_frame') != 'camera_color_optical_frame'
            or tf_value.get('target_frame') != 'base_link'
            or tf_value.get('transform_applied') is not True
            or tf_value.get('mixed_tf') is not False
            or tf_value.get('tf_valid_frames') != len(tf_map)
            or tf_value.get('xyz_valid_frames') != len(tf_map)):
        raise IntakeError('tf_summary_recompute_mismatch')

    observations = frame_report['observations']
    xyz_value = loaded['xyz_records']
    xyz_records = _common_semantic(
        xyz_value, XYZ_KEYS, ARTIFACT_MARKERS['xyz_records'],
        scene_name, scene, request, test_only)
    xyz_by_id = {}
    xyz_errors = []
    for record in xyz_records:
        observation_id = record.get('observation_id') if isinstance(
            record, Mapping) else None
        target = observations.get(observation_id)
        reference = record.get('reference_xyz_m') if isinstance(
            record, Mapping) else None
        measured = record.get('measured_xyz_m') if isinstance(
            record, Mapping) else None
        derived_error = (math.sqrt(sum(
            (float(a) - float(b)) ** 2 for a, b in zip(reference, measured)))
            if _vector(reference, 3) and _vector(measured, 3) else None)
        if (not isinstance(record, Mapping) or set(record) != XYZ_RECORD_KEYS
                or target is None or observation_id in xyz_by_id
                or _record_key(record) != target[0]
                or derived_error is None
                or not _finite(record.get('error_m'), 0.0)
                or abs(float(record['error_m']) - derived_error) > 1e-9
                or not _same_vector(
                    measured, _point_vector(target[1]['position']), 1e-6)):
            raise IntakeError('xyz_observation_recompute_invalid')
        xyz_by_id[observation_id] = record
        xyz_errors.append(derived_error)
    if set(xyz_by_id) != set(observations):
        raise IntakeError('xyz_observation_coverage_invalid')
    expected_xyz_max = max(xyz_errors) if xyz_errors else None
    if (xyz_value.get('not_applicable') is not (not bool(xyz_errors))
            or xyz_value.get('sample_count') != len(xyz_errors)
            or xyz_value.get('max_error_m') != expected_xyz_max
            or xyz_value.get('p95_error_m') != _p95(xyz_errors)
            or (xyz_errors and (
                expected_xyz_max > MAX_XYZ_ERROR_M
                or _p95(xyz_errors) > MAX_XYZ_ERROR_M))):
        raise IntakeError('xyz_summary_recompute_mismatch')

    depth_value = loaded['depth_records']
    depth_records = _common_semantic(
        depth_value, DEPTH_KEYS, ARTIFACT_MARKERS['depth_records'],
        scene_name, scene, request, test_only)
    depth_by_id = {}
    depth_errors = []
    valid_depth = 0
    for record in depth_records:
        observation_id = record.get('observation_id') if isinstance(
            record, Mapping) else None
        target = observations.get(observation_id)
        reference = record.get('reference_depth_m') if isinstance(
            record, Mapping) else None
        measured = record.get('measured_depth_m') if isinstance(
            record, Mapping) else None
        pixels = record.get('valid_pixels') if isinstance(record, Mapping) else None
        total = record.get('total_pixels') if isinstance(record, Mapping) else None
        ratio = record.get('valid_ratio') if isinstance(record, Mapping) else None
        derived_valid = (
            _finite(measured, 0.0) and float(measured) > 0.0
            and _integer(pixels, 1) and _integer(total, 1) and pixels <= total
            and pixels / total >= MIN_DEPTH_VALID_RATE)
        derived_error = (abs(float(measured) - float(reference))
                         if _finite(measured, 0.0)
                         and _finite(reference, 0.0) else None)
        if (not isinstance(record, Mapping) or set(record) != DEPTH_RECORD_KEYS
                or target is None or observation_id in depth_by_id
                or _record_key(record) != target[0]
                or derived_error is None
                or not _integer(pixels, 1) or not _integer(total, 1)
                or pixels > total
                or not _finite(ratio, 0.0) or float(ratio) > 1.0
                or abs(float(ratio) - pixels / total) > 1e-9
                or record.get('valid') is not derived_valid
                or not _finite(record.get('error_m'), 0.0)
                or abs(float(record['error_m']) - derived_error) > 1e-9
                or abs(float(measured) - target[1]['depth_m']) > 1e-6
                or pixels != target[1]['depth_valid_pixels']
                or total != target[1]['depth_total_pixels']
                or abs(float(ratio) - target[1]['depth_valid_ratio']) > 1e-9):
            raise IntakeError('depth_observation_recompute_invalid')
        depth_by_id[observation_id] = record
        depth_errors.append(derived_error)
        valid_depth += int(derived_valid)
    if set(depth_by_id) != set(observations):
        raise IntakeError('depth_observation_coverage_invalid')
    expected_rate = valid_depth / len(depth_errors) if depth_errors else None
    expected_depth_max = max(depth_errors) if depth_errors else None
    if (depth_value.get('not_applicable') is not (not bool(depth_errors))
            or depth_value.get('sample_count') != len(depth_errors)
            or depth_value.get('valid_rate') != expected_rate
            or depth_value.get('max_error_m') != expected_depth_max
            or depth_value.get('p95_error_m') != _p95(depth_errors)
            or (depth_errors and (
                expected_rate < MIN_DEPTH_VALID_RATE
                or expected_depth_max > MAX_DEPTH_ERROR_M
                or _p95(depth_errors) > MAX_DEPTH_ERROR_M))):
        raise IntakeError('depth_summary_recompute_mismatch')

    latency_value = loaded['latency_records']
    latency_records = _common_semantic(
        latency_value, LATENCY_KEYS, ARTIFACT_MARKERS['latency_records'],
        scene_name, scene, request, test_only)
    latency_map = _exact_frame_record_map(
        latency_records, frame_keys, 'latency')
    end_to_end = []
    processing = []
    sync = []
    for key, record in latency_map.items():
        frame = frames[key][1]
        sensor = record.get('sensor_stamp_sec') if isinstance(
            record, Mapping) else None
        started = record.get('inference_started_unix_sec') if isinstance(
            record, Mapping) else None
        ended = record.get('inference_ended_unix_sec') if isinstance(
            record, Mapping) else None
        collected = record.get('collector_received_unix_sec') if isinstance(
            record, Mapping) else None
        if (not isinstance(record, Mapping) or set(record) != LATENCY_RECORD_KEYS
                or not _finite(sensor, 0.0) or not _finite(started, sensor)
                or not _finite(ended, started)
                or not _finite(collected, ended)
                or not _finite(record.get('sync_span_sec'), 0.0)
                or not _finite(record.get('processing_latency_sec'), 0.0)
                or not _finite(record.get('transport_latency_sec'), 0.0)
                or not _finite(record.get('end_to_end_latency_sec'), 0.0)
                or abs(float(sensor) - key[1] / 1e9) > 1e-9
                or abs(float(collected) - frame['received_unix_sec']) > 1e-6
                or abs(record.get('sync_span_sec')
                       - frame['sync_span_sec']) > 1e-9
                or abs(record.get('processing_latency_sec')
                       - (ended - started)) > 1e-6
                or abs(record.get('processing_latency_sec')
                       - frame['processing_latency_sec']) > 1e-6
                or abs(record.get('transport_latency_sec')
                       - (collected - sensor)) > 1e-6
                or abs(record.get('transport_latency_sec')
                       - frame['transport_latency_sec']) > 1e-6
                or abs(record.get('end_to_end_latency_sec')
                       - (collected - sensor)) > 1e-6):
            raise IntakeError('latency_sample_recompute_mismatch')
        end_to_end.append(float(record['end_to_end_latency_sec']))
        processing.append(float(record['processing_latency_sec']))
        sync.append(float(record['sync_span_sec']))
    p95_end = _p95(end_to_end)
    p95_processing = _p95(processing)
    p95_sync = _p95(sync)
    if (latency_value.get('sample_count') != len(latency_map)
            or latency_value.get('max_latency_sec') != max(end_to_end)
            or latency_value.get('p95_end_to_end_sec') != p95_end
            or latency_value.get('p95_processing_sec') != p95_processing
            or latency_value.get('p95_sync_sec') != p95_sync
            or p95_sync > MAX_SYNC_P95_SEC
            or p95_processing > MAX_PROCESSING_P95_SEC
            or p95_end > MAX_TRANSPORT_P95_SEC):
        raise IntakeError('latency_summary_recompute_mismatch')
    return {
        'typed_frame_count': len(frame_keys),
        'ground_truth_frame_count': len(ground_map),
        'ground_truth_class_metrics': metrics,
        'extrinsics_transform_sha256': extrinsics['transform_sha256'],
        'tf_record_count': len(tf_map),
        'xyz_record_count': len(xyz_by_id),
        'depth_record_count': len(depth_by_id),
        'latency_record_count': len(latency_map),
    }


def _validate_semantic_producer_report(
        scene_name: str, scene: Mapping[str, Any],
        request: Mapping[str, Any], authority: Mapping[str, Any],
        probe_output_identity: Mapping[str, Any],
        frame_report: Mapping[str, Any], semantic: Mapping[str, Any],
        test_only: bool) -> Mapping[str, Any]:
    """Bind the six semantic files to one anchored host producer run."""
    report_path, report = _load_identity_json_with_path(
        scene['artifacts']['semantic_producer_report'],
        scene_name + ':semantic_producer_report')
    producer_authority_identity = authority[
        'semantic_producer_authorities'][scene_name]
    producer_source_identity = authority['semantic_producer_source']
    expected_index_identity = None
    if not test_only:
        producer_module = _load_exact_semantic_producer(authority)
        try:
            semantic_index = producer_module.load_production_authority_index()
        except Exception as error:
            code = getattr(error, 'code', None)
            raise IntakeError(
                code if code == (
                    'semantic_producer_production_authority_not_anchored')
                else 'semantic_producer_production_authority_index_invalid'
            ) from error
        if semantic_index.get('payload', {}).get('authorities') != authority[
                'semantic_producer_authorities']:
            raise IntakeError(
                'semantic_producer_production_authority_index_mismatch')
        expected_index_identity = semantic_index.get('identity')
    expected_outputs = {
        role: scene['artifacts'][role] for role in (
            'ground_truth', 'extrinsics_reference', 'tf_records',
            'xyz_records', 'depth_records', 'latency_records')}
    expected_failures = (
        ['synthetic_test_only_not_formal_evidence'] if test_only else [])
    if (not isinstance(report, Mapping)
            or set(report) != SEMANTIC_PRODUCER_REPORT_KEYS
            or report.get('schema_version') != 1
            or report.get('marker')
            != ARTIFACT_MARKERS['semantic_producer_report']
            or report.get('gate_id')
            != 'ROS1_NOETIC_SEMANTIC_EVIDENCE_PRODUCER_V1'
            or report.get('mode') != (
                'test_only_semantic_algorithm' if test_only
                else 'production_semantic_material')
            or report.get('read_only') is not True
            or report.get('authorizes_motion') is not False
            or report.get('publishes_ros_messages') is not False
            or report.get('producer_material_validated') is not True
            or report.get('formal_acceptance') is not False
            or report.get('not_in_four_scene_denominator') is not True
            or report.get('field_evidence_admitted') is not False
            or report.get('delivery_ready') is not False
            or report.get('synthetic_test_only') is not test_only
            or report.get('authority_identity')
            != producer_authority_identity
            or report.get('authority_index_identity')
            != expected_index_identity
            or report.get('producer_source_identity')
            != producer_source_identity
            or report.get('field_readiness_source_identity')
            != regular_file_identity(Path(__file__))
            or report.get('raw_bag_identity')
            != scene['artifacts']['raw_bag']
            or report.get('probe_artifact_identity')
            != probe_output_identity
            or report.get('typed_frames_identity')
            != scene['artifacts']['typed_frames']
            or report.get('typed_raw_binding_identity')
            != scene['artifacts']['typed_raw_binding']
            or report.get('canonical_source_admission')
            != request['canonical_source_admission']
            or report.get('field_install_evidence')
            != request['field_install_evidence']
            or report.get('model_set_sha256') != request['model_set_sha256']
            or report.get('scene') != scene_name
            or report.get('capture_id') != scene['capture_id']
            or report.get('task_id') != scene['task_id']
            or report.get('typed_frame_count') != len(frame_report['frames'])
            or report.get('observation_count')
            != len(frame_report['observations'])
            or report.get('outputs') != expected_outputs
            or report.get('output_commit_state')
            != 'COMPLETE_EXCLUSIVE_SET'
            or report.get('failures') != expected_failures):
        raise IntakeError(
            'semantic_producer_report_policy_invalid:' + scene_name)

    producer_authority = _load_identity_json(
        producer_authority_identity,
        'semantic_producer_authority:' + scene_name)
    if (not isinstance(producer_authority, Mapping)
            or set(producer_authority) != SEMANTIC_PRODUCER_AUTHORITY_KEYS
            or producer_authority.get('schema_version') != 1
            or producer_authority.get('marker')
            != 'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_AUTHORITY_V1'
            or producer_authority.get('scope')
            != 'ros1_noetic_semantic_evidence_producer'
            or producer_authority.get('test_only') is not test_only
            or producer_authority.get('read_only') is not True
            or producer_authority.get('authorizes_motion') is not False
            or producer_authority.get('publishes_ros_messages') is not False
            or producer_authority.get('producer_source')
            != producer_source_identity
            or producer_authority.get('field_readiness_source')
            != regular_file_identity(Path(__file__))
            or producer_authority.get('canonical_source_admission')
            != request['canonical_source_admission']
            or producer_authority.get('field_install_evidence')
            != request['field_install_evidence']
            or producer_authority.get('model_set_sha256')
            != request['model_set_sha256']
            or producer_authority.get('ground_truth_review_authority')
            != report.get('ground_truth_review_authority')
            or producer_authority.get('measurement_reference_authority')
            != report.get('measurement_reference_authority')
            or producer_authority.get('request_identity')
            != report.get('request_identity')):
        raise IntakeError(
            'semantic_producer_authority_policy_invalid:' + scene_name)

    producer_request = _load_identity_json(
        report['request_identity'],
        'semantic_producer_request:' + scene_name)
    if (not isinstance(producer_request, Mapping)
            or set(producer_request) != SEMANTIC_PRODUCER_REQUEST_KEYS
            or producer_request.get('schema_version') != 1
            or producer_request.get('marker')
            != 'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_REQUEST_V1'
            or producer_request.get('mode') != report['mode']
            or producer_request.get('read_only') is not True
            or producer_request.get('authorizes_motion') is not False
            or producer_request.get('publishes_ros_messages') is not False
            or producer_request.get('scene') != scene_name
            or producer_request.get('capture_id') != scene['capture_id']
            or producer_request.get('task_id') != scene['task_id']
            or producer_request.get('raw_bag')
            != scene['artifacts']['raw_bag']
            or producer_request.get('probe_artifact')
            != probe_output_identity
            or producer_request.get('typed_frames')
            != scene['artifacts']['typed_frames']
            or producer_request.get('typed_raw_binding')
            != scene['artifacts']['typed_raw_binding']
            or producer_request.get('measurement_ledger')
            != report['measurement_ledger_identity']
            or producer_request.get('canonical_source_admission')
            != request['canonical_source_admission']
            or producer_request.get('field_install_evidence')
            != request['field_install_evidence']
            or producer_request.get('model_manifest')
            != report['model_manifest']
            or producer_request.get('model_artifacts')
            != report['model_artifacts']
            or producer_request.get('model_set_sha256')
            != request['model_set_sha256']
            or producer_request.get('ground_truth_review_authority')
            != report['ground_truth_review_authority']
            or producer_request.get('measurement_reference_authority')
            != report['measurement_reference_authority']):
        raise IntakeError(
            'semantic_producer_request_policy_invalid:' + scene_name)

    allowed_output_root = producer_authority.get('allowed_output_root')
    try:
        output_root = Path(allowed_output_root).resolve(strict=True)
        report_directory = report_path.parent.resolve(strict=True)
        report_directory.relative_to(output_root)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise IntakeError(
            'semantic_producer_output_root_invalid:' + scene_name) from error
    expected_paths = {
        role: report_directory / filename
        for role, filename in SEMANTIC_PRODUCER_OUTPUT_NAMES.items()}
    expected_names = set(SEMANTIC_PRODUCER_OUTPUT_NAMES.values()) | {
        'semantic_producer_report.json'}
    try:
        actual_names = {item.name for item in report_directory.iterdir()}
    except OSError as error:
        raise IntakeError(
            'semantic_producer_output_set_invalid:' + scene_name) from error
    if (not isinstance(allowed_output_root, str)
            or not Path(allowed_output_root).is_absolute()
            or not output_root.is_dir()
            or _path_has_linklike_component(output_root)
            or producer_request.get('output_directory')
            != str(report_directory)
            or report_path != report_directory / 'semantic_producer_report.json'
            or actual_names != expected_names
            or any(
                Path(expected_outputs[role]['path']) != expected_paths[role]
                for role in SEMANTIC_PRODUCER_OUTPUT_NAMES)):
        raise IntakeError(
            'semantic_producer_output_set_invalid:' + scene_name)

    _identity_path(
        report['measurement_ledger_identity'],
        'semantic_producer_measurement_ledger:' + scene_name)
    review_authority = _load_identity_json(
        report['ground_truth_review_authority'],
        'semantic_producer_ground_truth_review_authority:' + scene_name)
    measurement_authority = _load_identity_json(
        report['measurement_reference_authority'],
        'semantic_producer_measurement_reference_authority:' + scene_name)
    if (not isinstance(review_authority, Mapping)
            or review_authority.get('schema_version') != 1
            or review_authority.get('marker')
            != 'LIMO_ROS1_GROUND_TRUTH_REVIEW_AUTHORITY_V1'
            or review_authority.get('scope')
            != 'independent_ground_truth_review'
            or review_authority.get('scene') != scene_name
            or review_authority.get('capture_id') != scene['capture_id']
            or review_authority.get('task_id') != scene['task_id']
            or review_authority.get('raw_bag')
            != scene['artifacts']['raw_bag']
            or review_authority.get('typed_frames')
            != scene['artifacts']['typed_frames']
            or review_authority.get('synthetic_test_only') is not test_only
            or not _text(review_authority.get('operator_id'))
            or not _text(review_authority.get('reviewer_id'))
            or review_authority.get('operator_id')
            == review_authority.get('reviewer_id')
            or not _finite(
                review_authority.get('reviewed_at_unix_sec'), 0.0)):
        raise IntakeError(
            'semantic_producer_ground_truth_review_invalid:' + scene_name)
    if (not isinstance(measurement_authority, Mapping)
            or measurement_authority.get('schema_version') != 1
            or measurement_authority.get('marker')
            != 'LIMO_ROS1_MEASUREMENT_REFERENCE_AUTHORITY_V1'
            or measurement_authority.get('scope')
            != 'independent_extrinsics_xyz_depth_reference'
            or measurement_authority.get('scene') != scene_name
            or measurement_authority.get('capture_id') != scene['capture_id']
            or measurement_authority.get('task_id') != scene['task_id']
            or measurement_authority.get('raw_bag')
            != scene['artifacts']['raw_bag']
            or measurement_authority.get('probe_artifact')
            != probe_output_identity
            or measurement_authority.get('typed_frames')
            != scene['artifacts']['typed_frames']
            or measurement_authority.get('synthetic_test_only')
            is not test_only
            or not _text(measurement_authority.get('extrinsics_operator_id'))
            or not _text(measurement_authority.get('extrinsics_reviewer_id'))
            or measurement_authority.get('extrinsics_operator_id')
            == measurement_authority.get('extrinsics_reviewer_id')
            or not _text(measurement_authority.get('measurement_method'))
            or not isinstance(
                measurement_authority.get('observation_ids'), list)
            or len(measurement_authority['observation_ids'])
            != len(set(measurement_authority['observation_ids']))
            or not _finite(
                measurement_authority.get('authorized_at_unix_sec'), 0.0)):
        raise IntakeError(
            'semantic_producer_measurement_reference_invalid:' + scene_name)
    _identity_path(
        report['model_manifest'],
        'semantic_producer_model_manifest:' + scene_name)
    model_artifacts = report.get('model_artifacts')
    if (not isinstance(model_artifacts, Mapping)
            or set(model_artifacts) != set(MODEL_CLASSES)
            or producer_authority.get('model_manifest')
            != report['model_manifest']
            or producer_authority.get('model_artifacts') != model_artifacts
            or {name: model_artifacts[name].get('sha256')
                for name in MODEL_CLASSES}
            != request['model_artifact_sha256']):
        raise IntakeError(
            'semantic_producer_model_provenance_invalid:' + scene_name)
    for name in MODEL_CLASSES:
        _identity_path(
            model_artifacts[name],
            'semantic_producer_model_artifact:{}:{}'.format(
                scene_name, name))
    if semantic.get('typed_frame_count') != report['typed_frame_count']:
        raise IntakeError(
            'semantic_producer_report_count_mismatch:' + scene_name)
    return {
        'report_identity': scene['artifacts']['semantic_producer_report'],
        'authority_identity': producer_authority_identity,
        'producer_source_identity': producer_source_identity,
        'synthetic_test_only': test_only,
        'outputs': expected_outputs,
    }


def _validate_scene(
        scene_name: str, scene: Mapping[str, Any],
        request: Mapping[str, Any], authority: Mapping[str, Any],
        runner: Callable[..., Mapping[str, Any]], probe_module: Any,
        test_only: bool) -> Mapping:
    raw_path = _check_raw_bag(
        scene['artifacts']['raw_bag'], scene_name + ':raw_bag')
    output_path = Path(scene['probe_output_path'])
    if output_path.exists():
        raise IntakeError('isolated_probe_output_not_exclusive:' + scene_name)
    result = runner(
        bag_path=raw_path,
        expected_bag_identity=scene['artifacts']['raw_bag'],
        noetic_prefix=Path(authority['noetic_prefix']),
        expected_rosbag_module_identity=authority['rosbag_module'],
        expected_rosbag_decoder_closure=authority[
            'rosbag_decoder_closure'],
        expected_indexer_module_identity=authority['rosbag1_indexer_source'],
        formal_manifest_path=Path(authority['formal_manifest']['path']),
        expected_formal_manifest_identity=authority['formal_manifest'],
        expected_probe_source_identity=authority['isolated_probe_source'],
        expected_sys_executable_identity=authority[
            'python_executable_target'],
        capture_id=scene['capture_id'], scene=scene_name,
        output_path=output_path,
        admission_mode='test_only' if test_only else 'production',
        python_root_relative=authority['python_root_relative'],
        trusted_system_python_roots=[
            Path(value) for value in authority[
                'trusted_system_python_roots']])
    probe_artifact = _validate_probe_artifact(
        scene_name, scene, authority, result, probe_module, test_only)
    frames = _load_jsonl_identity(
        scene['artifacts']['typed_frames'], scene_name + ':typed_frames')
    frame_report = _validate_frames(
        frames, scene_name, scene, request,
        1 if test_only else MIN_PRODUCTION_SCENE_FRAMES)
    collector = _load_identity_json(
        scene['artifacts']['collector_manifest'],
        scene_name + ':collector_manifest')
    _validate_collector(collector, scene_name, scene, frames)
    binding = _load_identity_json(
        scene['artifacts']['typed_raw_binding'],
        scene_name + ':typed_raw_binding')
    binding_report = _validate_typed_raw(
        binding, scene_name, scene, request, frame_report,
        probe_artifact, test_only)
    frame_report = dict(frame_report)
    frame_report.update(binding_report)
    loaded = {
        role: _load_identity_json(
            scene['artifacts'][role], '{}:{}'.format(scene_name, role))
        for role in (
            'ground_truth', 'extrinsics_reference', 'tf_records',
            'xyz_records', 'depth_records', 'latency_records')}
    semantic = _validate_semantic_records(
        scene_name, scene, request, frame_report, loaded, test_only)
    semantic_producer = _validate_semantic_producer_report(
        scene_name, scene, request, authority, result['output_identity'],
        frame_report, semantic, test_only)
    return {
        'scene': scene_name,
        'capture_id': scene['capture_id'],
        'task_id': scene['task_id'],
        'probe_output_identity': result['output_identity'],
        'semantic_recompute': semantic,
        'semantic_producer': semantic_producer,
        'algorithm_validated': True,
        'failures': [],
    }


def _production_source_and_install(
        request: Mapping[str, Any], workspace: Optional[Path]) -> Mapping:
    # Keep algorithm/test-only intake independent of NumPy, ROS, and model
    # imports.  The authoritative host source/install module is loaded only
    # after all four production scenes have passed the record graph gate.
    from limo_cleanup_perception import perception_readiness

    failures = []
    source_audit = (
        perception_readiness.audit_ros1_noetic_field_source_contract(
            workspace))
    try:
        expected_binding = (
            perception_readiness.make_ros1_canonical_source_binding(
                workspace, test_only=False))
        declared_binding = _load_identity_json(
            request['canonical_source_admission'],
            'canonical_source_admission')
    except (OSError, RuntimeError, TypeError, ValueError, IntakeError):
        expected_binding = None
        declared_binding = None
        failures.append('canonical_source_admission_recompute_failed')
    source_pass = (
        isinstance(source_audit, Mapping)
        and source_audit.get('pass') is True
        and isinstance(expected_binding, Mapping)
        and declared_binding == expected_binding)
    if not source_pass:
        failures.append('canonical_source_admission_not_validated')
    install_path = _identity_path(
        request['field_install_evidence'], 'field_install_evidence')
    install = perception_readiness.validate_ros1_noetic_field_install_evidence(
        install_path,
        release_binding=request['release_binding'],
        expected_model_hashes=request['model_artifact_sha256'],
        workspace=workspace, source_audit=source_audit,
        canonical_source_binding=expected_binding,
        allow_test_synthetic_binding=False)
    install_pass = (
        isinstance(install, Mapping)
        and install.get('validated_pass') is True)
    if not install_pass:
        failures.append('ros1_noetic_field_install_not_validated')
    return {
        'source_audit': source_audit,
        'canonical_source_binding': expected_binding,
        'field_install_validation': install,
        'source_pass': source_pass,
        'install_pass': install_pass,
        'failures': sorted(set(failures)),
    }


def evaluate_field_readiness(
        request_path: Path, authority_path: Path,
        authority_expected_identity: Mapping[str, Any], *,
        workspace: Path = None,
        probe_runner: Callable[..., Mapping[str, Any]] = None) -> Mapping:
    """Evaluate one anchored intake without ROS, inference, or hardware I/O."""
    algorithm_failures: List[str] = []
    scene_reports: Dict[str, Mapping[str, Any]] = {}
    authority = None
    request = None
    runtime_authority_admission = None
    canonical_probe_binding = None
    test_only = False
    try:
        authority = _load_anchored_authority(
            authority_path, authority_expected_identity)
        test_only = authority['test_only']
        if probe_runner is not None and not test_only:
            raise IntakeError('production_probe_injection_forbidden')
        runtime_authority_admission = _validate_runtime_authority_artifacts(
            authority)
        request = _load_request(request_path, authority)
        scenes = _validate_scene_declarations(request)
        if not test_only:
            canonical_probe_binding = _validate_canonical_probe_binding(
                authority, workspace)
        probe_module = None
        if probe_runner is not None:
            runner = probe_runner
        else:
            probe_module = _load_exact_probe(authority)
            runner = probe_module.run_isolated_rosbag_probe
        for scene_name in SCENES:
            scene_reports[scene_name] = _validate_scene(
                scene_name, scenes[scene_name], request, authority,
                runner, probe_module, test_only)
    except IntakeError as error:
        algorithm_failures.append(error.code)
    except (
            ImportError, OSError, RuntimeError, TypeError,
            ValueError) as error:
        algorithm_failures.append(
            'host_field_readiness_unexpected:' + type(error).__name__)

    algorithm_validated = (
        not algorithm_failures and set(scene_reports) == set(SCENES)
        and all(report.get('algorithm_validated') is True
                for report in scene_reports.values()))
    production_gate = {
        'source_pass': False,
        'install_pass': False,
        'source_audit': None,
        'canonical_source_binding': None,
        'field_install_validation': None,
        'failures': [],
    }
    if algorithm_validated and not test_only and request is not None:
        try:
            production_gate = _production_source_and_install(
                request, workspace)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            production_gate['failures'] = [
                'production_gate_recompute_failed:' + type(error).__name__]
    production_failures = list(production_gate.get('failures', []))
    production_complete = (
        algorithm_validated and not test_only
        and production_gate.get('source_pass') is True
        and production_gate.get('install_pass') is True
        and not production_failures)
    failures = sorted(set(algorithm_failures + production_failures))
    if test_only:
        failures = sorted(set(failures + [
            'synthetic_test_only_not_formal_evidence']))
    return {
        'schema_version': 1,
        'gate_id': GATE_ID,
        'mode': TEST_ONLY_MODE if test_only else PRODUCTION_MODE,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'algorithm_validated': algorithm_validated,
        'validator_unit_test_pass': algorithm_validated and test_only,
        'validated_pass': production_complete,
        'source_gate_pass': production_gate.get('source_pass') is True,
        'ros1_noetic_field_install_pass': (
            production_gate.get('install_pass') is True),
        'formal_four_scene_pass': production_complete,
        'formal_tf_3d_pass': production_complete,
        'field_evidence_admitted': production_complete,
        'formal_acceptance': production_complete,
        'not_in_four_scene_denominator': not production_complete,
        'delivery_ready': production_complete,
        'accepted_by_formal_evidence_consumer': production_complete,
        'authority_identity': (
            dict(authority_expected_identity)
            if _valid_identity(authority_expected_identity) else None),
        'request_identity': (
            authority.get('request_identity')
            if isinstance(authority, Mapping) else None),
        'runtime_authority_admission': runtime_authority_admission,
        'canonical_probe_binding': canonical_probe_binding,
        'scene_reports': scene_reports,
        'production_gate': production_gate,
        'failures': failures,
    }


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Host-owned ROS1/Noetic formal field-readiness intake.')
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--authority', type=Path, required=True)
    parser.add_argument('--authority-size-bytes', type=int, required=True)
    parser.add_argument('--authority-sha256', required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--output', type=Path)
    return parser.parse_args(args)


def main(args: Optional[Sequence[str]] = None) -> int:
    """Run the host intake and optionally write one exclusive JSON report."""
    parsed = parse_args(args)
    try:
        authority_path = parsed.authority.resolve(strict=True)
        result = evaluate_field_readiness(
            parsed.request, authority_path, {
                'path': str(authority_path),
                'size_bytes': parsed.authority_size_bytes,
                'sha256': parsed.authority_sha256,
            }, workspace=parsed.workspace)
        encoded = _json_bytes(result)
        if parsed.output is None:
            sys.stdout.buffer.write(encoded)
        else:
            output = parsed.output
            if output.exists() or not output.parent.is_dir():
                raise IntakeError('output_not_exclusive')
            with output.open('xb') as stream:
                stream.write(encoded)
        return 0 if result.get('delivery_ready') is True else 1
    except (
            IntakeError, OSError, RuntimeError, TypeError,
            ValueError) as error:
        failure = error.code if isinstance(error, IntakeError) else (
            'cli_failure:' + type(error).__name__)
        sys.stdout.buffer.write(_json_bytes({
            'schema_version': 1,
            'gate_id': GATE_ID,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'validated_pass': False,
            'field_evidence_admitted': False,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
            'delivery_ready': False,
            'failures': [failure],
        }))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
