"""Offline binding between collector-native typed frames and raw RGB-D evidence."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Mapping, Sequence

from limo_cleanup_perception.evidence_binding import artifact_identity
from limo_cleanup_perception.perception_evaluator import SCENES
from limo_cleanup_perception.rgbd_bag_indexer import (
    EXPECTED_TOPIC_MANIFEST_ID,
    FORMAL_RAW_INSPECTION_POLICY,
    load_topic_manifest,
)


STREAM_NAMES = (
    'rgb', 'aligned_depth', 'rgb_camera_info', 'depth_camera_info')
COLLECTOR_KEYS = {
    'schema_version', 'read_only', 'authorizes_motion',
    'publishes_ros_messages', 'scene', 'topic', 'message_type', 'task_id',
    'max_frames', 'duration_sec', 'received_frames',
    'unique_sequence_frames', 'duplicate_sequences',
    'serialization_errors', 'interrupted', 'completed_max_frames', 'output',
    'forbidden_control_topics'}
EXPECTED_FRAME_TOPIC = '/cleanup/perception/frames'
EXPECTED_FRAME_TYPE = 'limo_cleanup_interfaces/msg/PerceptionFrame'
EXPECTED_FORBIDDEN_CONTROL_TOPICS = {
    '/cmd_vel', '/cleanup/base/safe_cmd_vel', '/navigate_to_pose',
    '/arm_controller/joint_trajectory', '/gripper_controller/commands'}


def load_formal_typed_records(path: Path):
    """Load collector-native JSONL/list frames without stripping envelopes."""
    text = Path(path).read_text(encoding='utf-8')
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(value, list):
        return value
    raise ValueError(
        'formal typed frames must be a JSON list or JSONL, not an envelope')


def _stamp_ns(stamp):
    if not isinstance(stamp, Mapping):
        return None
    sec = stamp.get('sec')
    nanosec = stamp.get('nanosec')
    if (not isinstance(sec, int) or isinstance(sec, bool) or sec < 0
            or not isinstance(nanosec, int) or isinstance(nanosec, bool)
            or nanosec < 0 or nanosec >= 1_000_000_000):
        return None
    value = sec * 1_000_000_000 + nanosec
    return value if value > 0 else None


def _sha256_json(value) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def _identity_from_declaration(
        path: Path, declaration, kind: str, base_path: Path = None) -> Mapping:
    if (not isinstance(declaration, Mapping)
            or set(declaration) != {'path', 'size_bytes', 'sha256'}):
        raise ValueError(kind + ' artifact declaration is invalid')
    declared_path = Path(declaration['path'])
    if not declared_path.is_absolute():
        declared_path = (base_path or path.parent) / declared_path
    try:
        declared_path = declared_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(kind + ' artifact path is invalid') from error
    if declared_path != path:
        raise ValueError(kind + ' artifact path mismatch')
    actual = artifact_identity(path)
    if (declaration.get('size_bytes') != actual['size_bytes']
            or declaration.get('sha256') != actual['sha256']):
        raise ValueError(kind + ' artifact identity mismatch')
    return actual


def _strict_keys(value, expected, kind):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(kind + ' schema is invalid')


def _validate_collector(
        collector: Mapping, collector_path: Path, typed_path: Path,
        frames: Sequence[Mapping], scene: str, task_id: str) -> Mapping:
    if (not isinstance(collector, Mapping)
            or set(collector) != COLLECTOR_KEYS
            or collector.get('schema_version') != 1
            or collector.get('read_only') is not True
            or collector.get('authorizes_motion') is not False
            or collector.get('publishes_ros_messages') is not False
            or collector.get('scene') != scene
            or collector.get('topic') != EXPECTED_FRAME_TOPIC
            or collector.get('message_type') != EXPECTED_FRAME_TYPE
            or collector.get('task_id') != task_id
            or not isinstance(collector.get('max_frames'), int)
            or isinstance(collector.get('max_frames'), bool)
            or collector.get('max_frames') < 30
            or collector.get('received_frames') != collector.get('max_frames')
            or collector.get('received_frames') != len(frames)
            or collector.get('unique_sequence_frames') != len(frames)
            or collector.get('duplicate_sequences') != 0
            or collector.get('serialization_errors') != 0
            or collector.get('interrupted') is not False
            or collector.get('completed_max_frames') is not True
            or not isinstance(collector.get('duration_sec'), (int, float))
            or isinstance(collector.get('duration_sec'), bool)
            or not math.isfinite(collector.get('duration_sec'))
            or collector.get('duration_sec') <= 0.0
            or not isinstance(collector.get('forbidden_control_topics'), list)
            or len(collector.get('forbidden_control_topics'))
            != len(EXPECTED_FORBIDDEN_CONTROL_TOPICS)
            or set(collector.get('forbidden_control_topics'))
            != EXPECTED_FORBIDDEN_CONTROL_TOPICS):
        raise ValueError('collector manifest does not prove a complete capture')
    output = collector.get('output')
    return _identity_from_declaration(
        typed_path, output, 'collector typed frames', collector_path.parent)


def _raw_bundle_record(bundle: Mapping, tf_record: Mapping) -> Mapping:
    expected_keys = {
        'index', *STREAM_NAMES, 'header_stamps_ns',
        'stream_payload_sha256', 'stream_serialized_size_bytes',
        'stream_record_timestamps_ns', 'stream_record_header_skew_sec',
        'record_timestamp_span_sec', 'stamp_span_sec'}
    if not isinstance(bundle, Mapping) or set(bundle) != expected_keys:
        raise ValueError('raw accepted bundle schema is invalid')
    header_stamps = bundle.get('header_stamps_ns')
    if (not isinstance(header_stamps, Mapping)
            or set(header_stamps) != set(STREAM_NAMES)):
        raise ValueError('raw accepted bundle Header stamps are invalid')
    for key in (
            'stream_payload_sha256', 'stream_serialized_size_bytes',
            'stream_record_timestamps_ns', 'stream_record_header_skew_sec'):
        if not isinstance(bundle.get(key), Mapping) or set(
                bundle[key]) != set(STREAM_NAMES):
            raise ValueError('raw accepted bundle stream metadata is invalid')
    if (not isinstance(tf_record, Mapping)
            or tf_record.get('bundle_index') != bundle.get('index')
            or tf_record.get('rgb_header_stamp_ns')
            != header_stamps.get('rgb')
            or not isinstance(tf_record.get('sample_set_sha256'), str)
            or len(tf_record.get('sample_set_sha256')) != 64):
        raise ValueError('raw bundle TF binding is invalid')
    return {
        'bundle_index': bundle['index'],
        'rgb_header_stamp_ns': header_stamps['rgb'],
        'header_stamps_ns': dict(header_stamps),
        'stream_message_ids': {
            name: bundle[name] for name in STREAM_NAMES},
        'stream_payload_sha256': dict(bundle['stream_payload_sha256']),
        'stream_serialized_size_bytes': dict(
            bundle['stream_serialized_size_bytes']),
        'stream_record_timestamps_ns': dict(
            bundle['stream_record_timestamps_ns']),
        'stream_record_header_skew_sec': dict(
            bundle['stream_record_header_skew_sec']),
        'record_timestamp_span_sec': bundle['record_timestamp_span_sec'],
        'sync_span_sec': bundle['stamp_span_sec'],
        'tf_sample_set_sha256': tf_record['sample_set_sha256'],
        'tf_chain_base_to_camera': tf_record.get('chain_base_to_camera'),
        'tf_max_dynamic_age_sec': tf_record.get('max_dynamic_age_sec'),
    }


def create_binding(
        typed_path: Path, collector_path: Path, raw_path: Path,
        inspection_path: Path, scene: str, capture_id: str, task_id: str,
        started_unix_sec: float, ended_unix_sec: float,
        release_id: str, source_set_sha256: str,
        model_sha256: Mapping) -> Mapping:
    """Create one deterministic scene binding without importing ROS."""
    paths = [Path(value).resolve(strict=True) for value in (
        typed_path, collector_path, raw_path, inspection_path)]
    if any(not path.is_file() for path in paths) or len(set(paths)) != 4:
        raise ValueError('binding inputs must be four distinct regular files')
    typed_path, collector_path, raw_path, inspection_path = paths
    if scene not in SCENES:
        raise ValueError('scene is invalid')
    if not all(isinstance(value, str) and value.strip() for value in (
            capture_id, task_id, release_id)):
        raise ValueError('capture/task/release identity is invalid')
    if (not isinstance(source_set_sha256, str)
            or len(source_set_sha256) != 64):
        raise ValueError('canonical source-set SHA-256 is invalid')
    if (not isinstance(model_sha256, Mapping)
            or set(model_sha256) != {'plastic_bottle', 'trash_bin'}
            or any(not isinstance(value, str) or len(value) != 64
                   for value in model_sha256.values())):
        raise ValueError('model SHA-256 binding is invalid')
    if (not isinstance(started_unix_sec, (int, float))
            or not isinstance(ended_unix_sec, (int, float))
            or isinstance(started_unix_sec, bool)
            or isinstance(ended_unix_sec, bool)
            or not math.isfinite(started_unix_sec)
            or not math.isfinite(ended_unix_sec)
            or started_unix_sec < 0.0 or ended_unix_sec <= started_unix_sec):
        raise ValueError('capture time window is invalid')
    frames = load_formal_typed_records(typed_path)
    if not frames:
        raise ValueError('typed/raw pairing denominator must be non-zero')
    collector = json.loads(collector_path.read_text(encoding='utf-8'))
    inspection = json.loads(inspection_path.read_text(encoding='utf-8'))
    if not isinstance(collector, Mapping) or not isinstance(inspection, Mapping):
        raise ValueError('binding JSON inputs must be objects')
    if any(
            (inspection.get(field) is not expected
             if isinstance(expected, bool)
             else inspection.get(field) != expected)
            for field, expected in FORMAL_RAW_INSPECTION_POLICY.items()):
        raise ValueError(
            'diagnostic raw inspection cannot enter a formal scene binding')
    frame_keys = {
        'schema_version', 'read_only', 'received_unix_sec',
        'transport_latency_sec', 'stamp', 'frame_id', 'task_id', 'sequence',
        'scene', 'valid', 'status', 'error_code', 'sync_span_sec',
        'processing_latency_sec', 'targets'}
    target_keys = {
        'observation_id', 'object_class', 'confidence', 'valid', 'actionable',
        'status', 'error_code', 'position', 'size', 'bbox', 'depth_m',
        'depth_valid_pixels', 'depth_total_pixels', 'depth_valid_ratio',
        'source', 'position_semantics'}
    typed_identity = _validate_collector(
        collector, collector_path, typed_path, frames, scene, task_id)
    raw_identity = artifact_identity(raw_path)
    inspection_identity = artifact_identity(inspection_path)
    if (inspection.get('schema_version') != 3
            or inspection.get('read_only') is not True
            or inspection.get('capture_id') != capture_id
            or inspection.get('scene') != scene
            or inspection.get('source_capture', {}).get('sha256')
            != raw_identity['sha256']
            or inspection.get('source_capture', {}).get('size_bytes')
            != raw_identity['size_bytes']):
        raise ValueError('raw inspection capture identity is invalid')
    bundles = inspection.get('accepted_bundles')
    if not isinstance(bundles, list):
        raise ValueError('raw inspection accepted bundles are missing')
    if not bundles:
        raise ValueError('typed/raw pairing denominator must be non-zero')
    if (not isinstance(inspection.get('accepted_bundle_count'), int)
            or isinstance(inspection.get('accepted_bundle_count'), bool)
            or inspection.get('accepted_bundle_count') != len(bundles)):
        raise ValueError('raw inspection accepted bundle count is invalid')
    tf_bundles = inspection.get('tf_graph', {}).get('bundle_transforms')
    if not isinstance(tf_bundles, list) or len(tf_bundles) != len(bundles):
        raise ValueError('raw inspection per-bundle TF evidence is missing')
    raw_by_stamp = {}
    for bundle, tf_record in zip(bundles, tf_bundles):
        record = _raw_bundle_record(bundle, tf_record)
        stamp = record['rgb_header_stamp_ns']
        if (not isinstance(stamp, int) or isinstance(stamp, bool)
                or stamp <= 0 or stamp in raw_by_stamp):
            raise ValueError('raw RGB Header identity is ambiguous')
        raw_by_stamp[stamp] = record
    frame_bindings = []
    seen_sequences = set()
    seen_stamps = set()
    previous_sequence = None
    previous_stamp = None
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise ValueError('typed frame row is not an object')
        _strict_keys(frame, frame_keys, 'typed frame')
        if not isinstance(frame.get('targets'), list):
            raise ValueError('typed targets schema is invalid')
        for target in frame['targets']:
            _strict_keys(target, target_keys, 'typed target')
        sequence = frame.get('sequence')
        stamp = _stamp_ns(frame.get('stamp'))
        received = frame.get('received_unix_sec')
        sync_span = frame.get('sync_span_sec')
        if (frame.get('schema_version') != 1
                or frame.get('read_only') is not True
                or frame.get('scene') != scene
                or frame.get('task_id') != task_id
                or not isinstance(frame.get('frame_id'), str)
                or not frame.get('frame_id')
                or not isinstance(sequence, int) or isinstance(sequence, bool)
                or sequence in seen_sequences or stamp is None
                or stamp in seen_stamps
                or previous_sequence is not None
                and sequence <= previous_sequence
                or previous_stamp is not None and stamp <= previous_stamp
                or not isinstance(received, (int, float))
                or isinstance(received, bool) or not math.isfinite(received)
                or not isinstance(sync_span, (int, float))
                or isinstance(sync_span, bool) or not math.isfinite(sync_span)
                or sync_span < 0.0
                or not started_unix_sec <= stamp / 1e9 <= ended_unix_sec
                or not started_unix_sec <= float(received) <= ended_unix_sec):
            raise ValueError('typed frame identity or capture window is invalid')
        seen_sequences.add(sequence)
        seen_stamps.add(stamp)
        previous_sequence = sequence
        previous_stamp = stamp
        raw = raw_by_stamp.get(stamp)
        if raw is None:
            continue
        if abs(float(sync_span) - raw['sync_span_sec']) > 1e-6:
            raise ValueError('typed/raw synchronization span mismatch')
        frame_bindings.append({
            'typed_row_index': index,
            'sequence': sequence,
            'stamp_ns': stamp,
            'frame_id': frame['frame_id'],
            'typed_frame_sha256': _sha256_json(frame),
            'raw_bundle': raw,
        })
    typed_frame_count = len(frames)
    raw_bundle_count = len(bundles)
    if typed_frame_count == 0 or raw_bundle_count == 0:
        raise ValueError('typed/raw pairing denominator must be non-zero')
    paired_count = len(frame_bindings)
    unpaired_typed_count = typed_frame_count - paired_count
    unpaired_raw_bundle_count = raw_bundle_count - paired_count
    unpaired_rate = max(
        unpaired_typed_count / typed_frame_count,
        unpaired_raw_bundle_count / raw_bundle_count)
    manifest_binding = inspection.get('expected_topic_manifest')
    frozen_manifest = load_topic_manifest()
    expected_manifest_binding = {
        key: frozen_manifest[key] for key in (
            'manifest_id', 'schema_version', 'size_bytes', 'sha256')}
    declared_manifest_binding = {
        key: manifest_binding.get(key) for key in (
            'manifest_id', 'schema_version', 'size_bytes', 'sha256')
    } if isinstance(manifest_binding, Mapping) else None
    if (not isinstance(manifest_binding, Mapping)
            or declared_manifest_binding != expected_manifest_binding
            or manifest_binding.get('manifest_id')
            != EXPECTED_TOPIC_MANIFEST_ID):
        raise ValueError('raw topic-manifest binding is missing')
    envelope = {
        'capture_id': capture_id,
        'scene': scene,
        'task_id': task_id,
        'capture_window': {
            'started_unix_sec': float(started_unix_sec),
            'ended_unix_sec': float(ended_unix_sec),
        },
        'release_id': release_id,
        'source_set_sha256': source_set_sha256,
        'model_sha256': dict(model_sha256),
        'typed_frames': typed_identity,
        'collector_manifest': artifact_identity(collector_path),
        'raw_capture': raw_identity,
        'raw_inspection': inspection_identity,
        'expected_topic_manifest': expected_manifest_binding,
    }
    return {
        'schema_version': 1,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'capture_binding_id': _sha256_json(envelope),
        **envelope,
        'frame_bindings': frame_bindings,
        'typed_frame_count': typed_frame_count,
        'raw_bundle_count': raw_bundle_count,
        'unpaired_typed_count': unpaired_typed_count,
        'unpaired_raw_bundle_count': unpaired_raw_bundle_count,
        'unpaired_rate': unpaired_rate,
    }


def parse_args(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--typed-frames', type=Path, required=True)
    parser.add_argument('--collector-manifest', type=Path, required=True)
    parser.add_argument('--raw-bag', type=Path, required=True)
    parser.add_argument('--raw-inspection', type=Path, required=True)
    parser.add_argument('--scene', choices=SCENES, required=True)
    parser.add_argument('--capture-id', required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--started-unix-sec', type=float, required=True)
    parser.add_argument('--ended-unix-sec', type=float, required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--source-set-sha256', required=True)
    parser.add_argument('--bottle-model-sha256', required=True)
    parser.add_argument('--trash-bin-model-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args(args)


def main(args=None):
    parsed = parse_args(args)
    if parsed.output.exists():
        raise SystemExit('output path must not already exist')
    report = create_binding(
        parsed.typed_frames, parsed.collector_manifest, parsed.raw_bag,
        parsed.raw_inspection, parsed.scene, parsed.capture_id,
        parsed.task_id, parsed.started_unix_sec, parsed.ended_unix_sec,
        parsed.release_id, parsed.source_set_sha256, {
            'plastic_bottle': parsed.bottle_model_sha256,
            'trash_bin': parsed.trash_bin_model_sha256,
        })
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    with parsed.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
