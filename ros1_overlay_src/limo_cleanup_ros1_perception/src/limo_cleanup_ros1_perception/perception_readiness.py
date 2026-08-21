"""Fail-closed ROS1/Noetic four-scene perception admission.

This module only reopens and evaluates immutable artifacts.  It does not
import ROS client libraries, start a graph, access a camera, or publish any
message.  The historical count/boolean readiness shape is retained solely so
that old evidence receives explicit, machine-readable rejection reasons.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import stat
from pathlib import Path
from typing import Mapping, Optional

from limo_cleanup_ros1_perception.typed_raw_binding import create_binding


SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
MIN_SCENE_FRAMES = 30
MAX_SYNC_P95_SEC = 0.15
MAX_PROCESSING_P95_SEC = 0.50
MAX_END_TO_END_P95_SEC = 0.75
MAX_UNPAIRED_RATE = 0.05
MIN_DEPTH_VALID_RATE = 0.80
MAX_XYZ_ERROR_M = 0.02
MAX_DEPTH_ERROR_M = 0.02

REQUIRED_GATES = {
    'minimum_unique_frames_per_scene': 30,
    'rosbag1_connection_and_header_decode': True,
    'camera_info_intrinsics_bound': True,
    'old_latched_camera_info_rejected': True,
    'unique_four_stream_pairing': True,
    'camera_only_tf_chain': True,
    'typed_raw_binding': True,
    'ground_truth_and_measurement_reference': True,
    'depth_xyz_and_latency_metrics': True,
}
FORMAL_TOP_KEYS = {
    'schema_version', 'bundle_id', 'runtime_family', 'ros_distro',
    'evidence_scope', 'read_only', 'authorizes_motion',
    'publishes_ros_messages', 'delivery_ready', 'source_binding',
    'model_binding', 'output_contract', 'ros1_field_install_validation',
    'hardware_readiness', 'expected_topic_manifest', 'scenes',
    'required_gates',
}
FORMAL_SCENE_KEYS = {
    'capture_id', 'task_id', 'capture_window', 'raw_bag', 'raw_index',
    'collector_manifest', 'typed_frames', 'typed_raw_binding',
    'ground_truth_artifact', 'tf_artifact', 'xyz_artifact',
    'depth_artifact', 'latency_artifact',
}
LEGACY_TOP_KEYS = {
    'schema_version', 'read_only', 'authorizes_motion',
    'formal_acceptance', 'shared_graph', 'mixed_tf',
    'not_in_four_scene_denominator', 'ros1_field_install_pass',
    'runtime_model_binding_pass', 'scenes',
}
LEGACY_SCENE_KEYS = {
    'unique_frames', 'ground_truth_complete', 'tf_valid_frames',
    'xyz_valid_frames', 'depth_valid_frames', 'latency_samples',
    'bag_index_formal', 'typed_raw_binding_pass', 'capture_id', 'task_id',
    'ground_truth_artifact', 'tf_artifact', 'latency_artifact',
}
ARTIFACT_KEYS = {'path', 'size_bytes', 'sha256'}


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


def _strict_keys(value, expected) -> bool:
    return isinstance(value, Mapping) and set(value) == set(expected)


def _finite(value, minimum=None, maximum=None) -> bool:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        return False
    return ((minimum is None or value >= minimum)
            and (maximum is None or value <= maximum))


def _integer(value, minimum=None) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (minimum is None or value >= minimum))


def _lower_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and value == value.lower()
            and all(character in '0123456789abcdef' for character in value))


def _valid_text(value) -> bool:
    return (isinstance(value, str) and bool(value)
            and value == value.strip() and '\x00' not in value)


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


def _path_has_linklike_component(path: Path) -> bool:
    """Reject a linked/reparse artifact or any linked parent component."""
    candidate = Path(path).absolute()
    chain = list(reversed(candidate.parents)) + [candidate]
    return any(_path_is_linklike(item) for item in chain)


def _artifact_identity(path: Path) -> Mapping:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file() or _path_has_linklike_component(path):
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


def _resolve_artifact(
        declaration, artifact_root, label, failures, seen_paths):
    if not _strict_keys(declaration, ARTIFACT_KEYS):
        failures.append(label + ':artifact_declaration_invalid')
        return None
    relative = declaration.get('path')
    if (not _valid_text(relative) or Path(relative).is_absolute()
            or Path(relative).drive or '\\' in relative
            or '..' in Path(relative).parts
            or not _integer(declaration.get('size_bytes'), 0)
            or not _lower_sha256(declaration.get('sha256'))):
        failures.append(label + ':artifact_declaration_invalid')
        return None
    if artifact_root is None:
        failures.append(label + ':artifact_live_audit_missing')
        return None
    try:
        root = Path(artifact_root).resolve(strict=True)
        unresolved = root / Path(relative)
        candidate = unresolved.resolve(strict=True)
        candidate.relative_to(root)
        identity = _artifact_identity(unresolved)
    except (OSError, RuntimeError, ValueError):
        failures.append(label + ':artifact_path_invalid')
        return None
    rendered = str(candidate)
    if rendered in seen_paths:
        failures.append(label + ':artifact_reused')
        return None
    seen_paths.add(rendered)
    if (identity['size_bytes'] != declaration['size_bytes']
            or identity['sha256'] != declaration['sha256']):
        failures.append(label + ':artifact_identity_mismatch')
        return None
    return candidate


def _load_declared_json(
        declaration, artifact_root, label, failures, seen_paths):
    path = _resolve_artifact(
        declaration, artifact_root, label, failures, seen_paths)
    if path is None:
        return None, None
    try:
        value = _load_json(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        failures.append(label + ':artifact_json_invalid')
        return path, None
    if not isinstance(value, Mapping):
        failures.append(label + ':artifact_json_invalid')
        return path, None
    return path, value


def _record_content_fingerprint(
        path, scene, role, seen_fingerprints, failures, failure_code):
    """Record one reopened artifact by content, not merely by pathname."""
    if path is None:
        return None
    try:
        digest = _sha256_file(Path(path))
    except (OSError, RuntimeError, ValueError):
        failures.append('scene:{}:{}:artifact_identity_mismatch'.format(
            scene, role))
        return None
    previous = seen_fingerprints.get(digest)
    if previous is not None:
        failures.append(failure_code)
    else:
        seen_fingerprints[digest] = {'scene': scene, 'role': role}
    return digest


def _record_raw_bundle_fingerprints(
        scene, binding, seen_fingerprints, failures):
    """Reject the same raw RGB-D payload bundle reused by two scenes."""
    associations = binding.get('associations') if isinstance(
        binding, Mapping) else None
    if not isinstance(associations, list):
        return
    expected_roles = {
        'rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info'}
    for association in associations:
        hashes = association.get('raw_stream_payload_sha256') if isinstance(
            association, Mapping) else None
        bundle_id = association.get('bundle_id') if isinstance(
            association, Mapping) else None
        if (not _lower_sha256(bundle_id) or not isinstance(hashes, Mapping)
                or set(hashes) != expected_roles
                or any(not _lower_sha256(hashes.get(role))
                       for role in expected_roles)):
            continue
        fingerprint = _canonical_sha256({
            'bundle_id': bundle_id,
            'raw_stream_payload_sha256': {
                role: hashes[role] for role in sorted(expected_roles)},
        })
        previous = seen_fingerprints.get(fingerprint)
        if previous is not None and previous != scene:
            failures.append('four_scene_raw_bundle_fingerprint_reused')
        else:
            seen_fingerprints[fingerprint] = scene


def _capture_windows_overlap(first, second) -> bool:
    if not _capture_window(first) or not _capture_window(second):
        return False
    return any(
        max(first[prefix + '_start_ns'], second[prefix + '_start_ns'])
        <= min(first[prefix + '_end_ns'], second[prefix + '_end_ns'])
        for prefix in ('record', 'header'))


def _record_capture_window(scene, window, capture_windows, failures):
    if any(_capture_windows_overlap(window, previous['window'])
           for previous in capture_windows):
        failures.append('four_scene_capture_window_overlap')
    capture_windows.append({'scene': scene, 'window': dict(window)})


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[rank]


def _semantic_common(value, scene, capture_id, task_id, failures, label):
    if not isinstance(value, Mapping):
        failures.append(label + '_artifact_invalid')
        return None
    if (value.get('schema_version') != 1
            or value.get('scene') != scene
            or value.get('capture_id') != capture_id
            or value.get('task_id') != task_id
            or not _lower_sha256(value.get('ros1_field_install_sha256'))
            or not _lower_sha256(value.get('model_binding_sha256'))
            or value.get('synthetic_test_only') is not False):
        failures.append(label + '_binding_invalid')
    return (
        value.get('ros1_field_install_sha256'),
        value.get('model_binding_sha256'))


def _frame_stamp_ns(frame):
    stamp = frame.get('stamp') if isinstance(frame, Mapping) else None
    if not _strict_keys(stamp, {'sec', 'nanosec'}):
        return None
    sec = stamp.get('sec')
    nanosec = stamp.get('nanosec')
    if (not _integer(sec, 0) or not _integer(nanosec, 0)
            or nanosec >= 1_000_000_000):
        return None
    value = sec * 1_000_000_000 + nanosec
    return value if value > 0 else None


def _frame_key(frame):
    if not isinstance(frame, Mapping):
        return None
    sequence = frame.get('sequence')
    stamp_ns = _frame_stamp_ns(frame)
    bundle_id = frame.get('bundle_id')
    if (not _integer(sequence, 1) or stamp_ns is None
            or not _lower_sha256(bundle_id)):
        return None
    return sequence, stamp_ns, bundle_id


def _frame_maps(frames, binding):
    frame_by_key = {}
    frame_by_sequence = {}
    targets = {}
    for frame in frames or []:
        key = _frame_key(frame)
        if key is None or key in frame_by_key or key[0] in frame_by_sequence:
            continue
        frame_by_key[key] = frame
        frame_by_sequence[key[0]] = frame
        frame_targets = frame.get('targets', [])
        if not isinstance(frame_targets, list):
            frame_targets = []
        for target in frame_targets:
            if isinstance(target, Mapping):
                observation_id = target.get('observation_id')
                if _valid_text(observation_id) and observation_id not in targets:
                    targets[observation_id] = (frame, target)
    rgb_hash_by_bundle = {}
    if isinstance(binding, Mapping):
        for association in binding.get('associations', []):
            if not isinstance(association, Mapping):
                continue
            hashes = association.get('raw_stream_payload_sha256')
            bundle_id = association.get('bundle_id')
            if (_lower_sha256(bundle_id) and isinstance(hashes, Mapping)
                    and _lower_sha256(hashes.get('rgb'))):
                rgb_hash_by_bundle[bundle_id] = hashes['rgb']
    return frame_by_key, frame_by_sequence, targets, rgb_hash_by_bundle


def _bbox_valid(value):
    return (isinstance(value, list) and len(value) == 4
            and all(_finite(item) for item in value)
            and value[0] < value[2] and value[1] < value[3])


def _bbox_iou(first, second):
    if not _bbox_valid(first) or not _bbox_valid(second):
        return 0.0
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _ground_truth_metrics(records, frame_by_key, failures):
    classes = ('plastic_bottle', 'trash_bin')
    counts = {
        name: {'tp': 0, 'fp': 0, 'fn': 0} for name in classes}
    in_bin_leaks = 0
    outside_wrong_suppression = 0
    for record in records:
        key = (record['sequence'], record['stamp_ns'], record['bundle_id'])
        frame = frame_by_key[key]
        annotations = [
            item for item in record.get('annotations', [])
            if isinstance(item, Mapping)]
        frame_targets = frame.get('targets', [])
        if not isinstance(frame_targets, list):
            frame_targets = []
        for class_name in classes:
            truth = [item for item in annotations
                     if item.get('object_class') == class_name]
            detections = [item for item in frame_targets
                           if isinstance(item, Mapping)
                           and item.get('object_class') == class_name]
            used = set()
            for annotation in truth:
                ranked = sorted(
                    ((_bbox_iou(annotation['bbox'], detection.get('bbox')),
                      index, detection)
                     for index, detection in enumerate(detections)
                     if index not in used),
                    key=lambda item: (-item[0], item[1]))
                if ranked and ranked[0][0] >= 0.50:
                    used.add(ranked[0][1])
                    counts[class_name]['tp'] += 1
                else:
                    counts[class_name]['fn'] += 1
            counts[class_name]['fp'] += len(detections) - len(used)
        for target in frame_targets:
            if (not isinstance(target, Mapping)
                    or target.get('object_class') != 'plastic_bottle'):
                continue
            if (any(item.get('object_class') == 'plastic_bottle'
                    and item.get('relation') == 'inside_bin'
                    for item in annotations)
                    and (target.get('actionable') is True
                         or target.get('status') == 'active')):
                in_bin_leaks += 1
            if (any(item.get('object_class') == 'plastic_bottle'
                    and item.get('relation') == 'outside_bin'
                    for item in annotations)
                    and (target.get('actionable') is not True
                         or target.get('status') != 'active')):
                outside_wrong_suppression += 1
    frame_count = len(records)
    result = {}
    for class_name, value in counts.items():
        expected = value['tp'] + value['fn']
        recall = value['tp'] / expected if expected else 1.0
        false_positive_rate = value['fp'] / frame_count if frame_count else None
        result[class_name] = {
            **value,
            'recall': recall,
            'false_positive_rate': false_positive_rate,
        }
        if expected and recall < 0.90:
            failures.append('ground_truth_detection_recall_below_threshold')
        if not expected and (
                false_positive_rate is None or false_positive_rate > 0.01):
            failures.append('ground_truth_absent_class_false_positive')
    if in_bin_leaks:
        failures.append('ground_truth_in_bin_filter_leak')
    if outside_wrong_suppression:
        failures.append('ground_truth_outside_wrong_suppression')
    result['in_bin_leaks'] = in_bin_leaks
    result['outside_wrong_suppression'] = outside_wrong_suppression
    return result


def _check_ground_truth_summary(
        value, scene, capture_id, task_id, failures,
        frames=None, binding=None):
    provenance = _semantic_common(
        value, scene, capture_id, task_id, failures, 'ground_truth')
    expected_top = {
        'schema_version', 'report_kind', 'scene', 'capture_id', 'task_id',
        'ros1_field_install_sha256', 'model_binding_sha256',
        'synthetic_test_only', 'complete', 'unique_frames',
        'annotation_count', 'records'}
    if (not _strict_keys(value, expected_top)
            or value.get('report_kind') != 'ros1_ground_truth'
            or value.get('complete') is not True
            or not isinstance(value.get('records'), list)):
        failures.append('ground_truth_content_invalid')
        return {'provenance': provenance, 'records': {}, 'metrics': {}}
    frame_by_key, _, _, rgb_hash_by_bundle = _frame_maps(frames, binding)
    records_by_key = {}
    instance_ids = set()
    annotation_count = 0
    record_keys = {
        'sequence', 'stamp_ns', 'bundle_id', 'rgb_payload_sha256',
        'annotations'}
    annotation_keys = {
        'instance_id', 'object_class', 'bbox', 'relation'}
    for record in value['records']:
        if not _strict_keys(record, record_keys):
            failures.append('ground_truth_record_invalid')
            continue
        key = (record.get('sequence'), record.get('stamp_ns'),
               record.get('bundle_id'))
        annotations = record.get('annotations')
        if (key not in frame_by_key or key in records_by_key
                or record.get('rgb_payload_sha256')
                != rgb_hash_by_bundle.get(record.get('bundle_id'))
                or not isinstance(annotations, list)):
            failures.append('ground_truth_binding_invalid')
            continue
        valid_annotations = []
        for annotation in annotations:
            if (not _strict_keys(annotation, annotation_keys)
                    or not _valid_text(annotation.get('instance_id'))
                    or annotation['instance_id'] in instance_ids
                    or annotation.get('object_class')
                    not in ('plastic_bottle', 'trash_bin')
                    or not _bbox_valid(annotation.get('bbox'))
                    or annotation.get('relation')
                    not in ('none', 'inside_bin', 'outside_bin')):
                failures.append('ground_truth_annotation_invalid')
                continue
            if (annotation['object_class'] == 'trash_bin'
                    and annotation['relation'] != 'none'):
                failures.append('ground_truth_annotation_invalid')
            instance_ids.add(annotation['instance_id'])
            valid_annotations.append(annotation)
        classes = [item['object_class'] for item in valid_annotations]
        bottle_relations = [
            item['relation'] for item in valid_annotations
            if item['object_class'] == 'plastic_bottle']
        scene_valid = (
            (scene == 'background' and not valid_annotations)
            or (scene == 'bin_only' and 'trash_bin' in classes
                and 'plastic_bottle' not in classes)
            or (scene == 'bottle_in_bin' and 'trash_bin' in classes
                and bottle_relations and all(
                    item == 'inside_bin' for item in bottle_relations))
            or (scene == 'bottle_outside' and 'trash_bin' in classes
                and bottle_relations and all(
                    item == 'outside_bin' for item in bottle_relations)))
        if not scene_valid:
            failures.append('ground_truth_scene_semantics_invalid')
        annotation_count += len(valid_annotations)
        sanitized_record = dict(record)
        sanitized_record['annotations'] = valid_annotations
        records_by_key[key] = sanitized_record
    if (len(records_by_key) != len(frame_by_key)
            or len(records_by_key) < MIN_SCENE_FRAMES
            or value.get('unique_frames') != len(records_by_key)
            or value.get('annotation_count') != annotation_count):
        failures.append('ground_truth_denominator_mismatch')
    metrics = _ground_truth_metrics(
        list(records_by_key.values()), frame_by_key, failures
    ) if len(records_by_key) == len(frame_by_key) else {}
    return {
        'provenance': provenance,
        'records': records_by_key,
        'metrics': metrics,
    }


def _point(value):
    return (_strict_keys(value, {'x', 'y', 'z'})
            and all(_finite(value[key]) for key in ('x', 'y', 'z')))


def _transform_point(point, translation, rotation):
    x, y, z, w = rotation
    px, py, pz = point['x'], point['y'], point['z']
    # q * p * q^-1, expanded to avoid external numeric dependencies.
    tx = 2.0 * (y * pz - z * py)
    ty = 2.0 * (z * px - x * pz)
    tz = 2.0 * (x * py - y * px)
    return {
        'x': px + w * tx + (y * tz - z * ty) + translation[0],
        'y': py + w * ty + (z * tx - x * tz) + translation[1],
        'z': pz + w * tz + (x * ty - y * tx) + translation[2],
    }


def _points_close(first, second, tolerance=1e-6):
    return (_point(first) and _point(second)
            and all(abs(first[key] - second[key]) <= tolerance
                    for key in ('x', 'y', 'z')))


def _check_tf_summary(
        value, scene, capture_id, task_id, failures,
        frames=None, binding=None):
    provenance = _semantic_common(
        value, scene, capture_id, task_id, failures, 'tf_application')
    expected_top = {
        'schema_version', 'report_kind', 'scene', 'capture_id', 'task_id',
        'ros1_field_install_sha256', 'model_binding_sha256',
        'synthetic_test_only', 'source_frame', 'target_frame',
        'transform_applied', 'mixed_tf', 'tf_valid_frames',
        'xyz_valid_frames', 'records'}
    if (not _strict_keys(value, expected_top)
            or value.get('report_kind') != 'ros1_tf_application'
            or not _valid_text(value.get('source_frame'))
            or value.get('target_frame') != 'base_link'
            or value.get('transform_applied') is not True
            or value.get('mixed_tf') is not False
            or not isinstance(value.get('records'), list)):
        failures.append('tf_application_content_invalid')
        failures.append('xyz_content_invalid')
        return {'provenance': provenance, 'records': {}}
    frame_by_key, _, targets, _ = _frame_maps(frames, binding)
    records_by_key = {}
    record_keys = {
        'sequence', 'stamp_ns', 'bundle_id', 'topic', 'connection_id',
        'callerid', 'parent_frame_id', 'child_frame_id',
        'lookup_source_frame', 'lookup_target_frame', 'translation_m',
        'rotation_xyzw', 'transform_sha256', 'lookup_succeeded',
        'transform_applied', 'output_frame', 'target_observations'}
    observation_keys = {
        'observation_id', 'input_position', 'output_position'}
    xyz_valid_frames = 0
    for record in value['records']:
        if not _strict_keys(record, record_keys):
            failures.append('tf_application_record_invalid')
            continue
        key = (record.get('sequence'), record.get('stamp_ns'),
               record.get('bundle_id'))
        translation = record.get('translation_m')
        rotation = record.get('rotation_xyzw')
        identity_value = {key_name: record[key_name] for key_name in (
            'topic', 'connection_id', 'callerid', 'parent_frame_id',
            'child_frame_id', 'lookup_source_frame', 'lookup_target_frame',
            'stamp_ns', 'translation_m', 'rotation_xyzw')}
        if (key not in frame_by_key or key in records_by_key
                or record.get('topic') not in ('/tf', '/tf_static')
                or not _integer(record.get('connection_id'), 0)
                or not _valid_text(record.get('callerid'))
                or not _valid_text(record.get('parent_frame_id'))
                or not _valid_text(record.get('child_frame_id'))
                or record.get('lookup_source_frame')
                != value.get('source_frame')
                or record.get('lookup_target_frame') != 'base_link'
                or not isinstance(translation, list)
                or len(translation) != 3
                or not all(_finite(item) for item in translation)
                or not isinstance(rotation, list) or len(rotation) != 4
                or not all(_finite(item) for item in rotation)
                or abs(math.sqrt(sum(item * item for item in rotation))
                       - 1.0) > 1e-3
                or record.get('transform_sha256')
                != _canonical_sha256(identity_value)
                or record.get('lookup_succeeded') is not True
                or record.get('transform_applied') is not True
                or record.get('output_frame') != 'base_link'
                or not isinstance(record.get('target_observations'), list)):
            failures.append('tf_application_binding_invalid')
            continue
        frame = frame_by_key[key]
        if (frame.get('frame_id') != value.get('source_frame')
                or frame.get('tf_target_frame') != 'base_link'
                or frame.get('tf_valid') is not True
                or frame.get('tf_transform_applied') is not True):
            failures.append('tf_application_typed_join_invalid')
        seen_observations = set()
        observations_valid = True
        for observation in record['target_observations']:
            if (not _strict_keys(observation, observation_keys)
                    or observation.get('observation_id') in seen_observations
                    or observation.get('observation_id') not in targets
                    or targets[observation['observation_id']][0] is not frame
                    or not _point(observation.get('input_position'))
                    or not _point(observation.get('output_position'))):
                observations_valid = False
                continue
            target = targets[observation['observation_id']][1]
            if not _points_close(
                    observation['input_position'], target.get('position')):
                observations_valid = False
            calculated = _transform_point(
                observation['input_position'], translation, rotation)
            if not _points_close(calculated, observation['output_position']):
                observations_valid = False
            seen_observations.add(observation['observation_id'])
        frame_targets = frame.get('targets', [])
        if not isinstance(frame_targets, list):
            frame_targets = []
        expected_observations = {
            item.get('observation_id') for item in frame_targets
            if isinstance(item, Mapping) and item.get('valid') is True}
        if seen_observations != expected_observations or not observations_valid:
            failures.append('tf_application_observation_join_invalid')
        else:
            xyz_valid_frames += 1
        records_by_key[key] = record
    if (len(records_by_key) != len(frame_by_key)
            or len(records_by_key) < MIN_SCENE_FRAMES
            or value.get('tf_valid_frames') != len(records_by_key)
            or value.get('xyz_valid_frames') != xyz_valid_frames):
        failures.append('tf_application_denominator_mismatch')
        failures.append('xyz_denominator_mismatch')
    return {'provenance': provenance, 'records': records_by_key}


def _check_latency_summary(
        value, scene, capture_id, task_id, failures,
        frames=None, binding=None):
    provenance = _semantic_common(
        value, scene, capture_id, task_id, failures, 'latency')
    expected_top = {
        'schema_version', 'report_kind', 'scene', 'capture_id', 'task_id',
        'ros1_field_install_sha256', 'model_binding_sha256',
        'synthetic_test_only', 'sample_count', 'max_latency_sec',
        'p95_end_to_end_sec', 'p95_processing_sec', 'p95_sync_sec',
        'records'}
    if (not _strict_keys(value, expected_top)
            or value.get('report_kind') != 'ros1_latency_evidence'
            or not isinstance(value.get('records'), list)):
        failures.append('latency_content_invalid')
        return {'provenance': provenance, 'records': {}}
    frame_by_key, _, _, _ = _frame_maps(frames, binding)
    records_by_key = {}
    end_to_end = []
    processing = []
    sync = []
    record_keys = {
        'sequence', 'stamp_ns', 'bundle_id', 'sensor_stamp_sec',
        'inference_started_unix_sec', 'inference_ended_unix_sec',
        'collector_received_unix_sec', 'sync_span_sec',
        'processing_latency_sec', 'transport_latency_sec',
        'end_to_end_latency_sec'}
    for record in value['records']:
        if not _strict_keys(record, record_keys):
            failures.append('latency_record_invalid')
            continue
        key = (record.get('sequence'), record.get('stamp_ns'),
               record.get('bundle_id'))
        frame = frame_by_key.get(key)
        sensor = record.get('sensor_stamp_sec')
        started = record.get('inference_started_unix_sec')
        ended = record.get('inference_ended_unix_sec')
        received = record.get('collector_received_unix_sec')
        calculated_processing = (
            ended - started if _finite(ended) and _finite(started) else None)
        calculated_transport = (
            received - sensor if _finite(received) and _finite(sensor)
            else None)
        frame_sync = frame.get('sync_span_sec') if frame else None
        frame_processing = (
            frame.get('processing_latency_sec') if frame else None)
        frame_transport = (
            frame.get('transport_latency_sec') if frame else None)
        frame_received = frame.get('received_unix_sec') if frame else None
        if (frame is None or key in records_by_key
                or not _finite(sensor, 0.0)
                or abs(sensor - key[1] / 1e9) > 1e-9
                or not _finite(started, sensor)
                or not _finite(ended, started)
                or not _finite(received, ended)
                or not _finite(record.get('sync_span_sec'), 0.0)
                or not _finite(frame_sync, 0.0)
                or record.get('sync_span_sec') != frame_sync
                or not _finite(record.get('processing_latency_sec'), 0.0)
                or abs(record['processing_latency_sec']
                       - calculated_processing) > 1e-6
                or not _finite(frame_processing, 0.0)
                or abs(record['processing_latency_sec']
                       - frame_processing) > 1e-6
                or not _finite(record.get('transport_latency_sec'), 0.0)
                or abs(record['transport_latency_sec']
                       - calculated_transport) > 1e-6
                or not _finite(frame_transport, 0.0)
                or abs(record['transport_latency_sec']
                       - frame_transport) > 1e-6
                or not _finite(record.get('end_to_end_latency_sec'), 0.0)
                or abs(record['end_to_end_latency_sec']
                       - calculated_transport) > 1e-6
                or not _finite(frame_received, 0.0)
                or abs(received - frame_received) > 1e-6):
            failures.append('latency_binding_invalid')
            continue
        records_by_key[key] = record
        end_to_end.append(record['end_to_end_latency_sec'])
        processing.append(record['processing_latency_sec'])
        sync.append(record['sync_span_sec'])
    calculated = {
        'sample_count': len(records_by_key),
        'max_latency_sec': max(end_to_end) if end_to_end else None,
        'p95_end_to_end_sec': _percentile(end_to_end, 0.95),
        'p95_processing_sec': _percentile(processing, 0.95),
        'p95_sync_sec': _percentile(sync, 0.95),
    }
    if (len(records_by_key) != len(frame_by_key)
            or len(records_by_key) < MIN_SCENE_FRAMES
            or any(value.get(key) != expected
                   for key, expected in calculated.items())
            or calculated['p95_end_to_end_sec'] > MAX_END_TO_END_P95_SEC
            or calculated['p95_processing_sec'] > MAX_PROCESSING_P95_SEC
            or calculated['p95_sync_sec'] > MAX_SYNC_P95_SEC):
        failures.append('latency_content_invalid')
    return {'provenance': provenance, 'records': records_by_key}


def _legacy_scene(
        scene, record, artifact_root, failures, seen_paths,
        global_capture_ids, global_task_ids):
    prefix = 'scene:' + scene
    scene_failures = []
    if not _strict_keys(record, LEGACY_SCENE_KEYS):
        failures.append(prefix + ':schema_invalid')
        return {'passed': False, 'failures': [prefix + ':schema_invalid']}
    capture_id = record.get('capture_id')
    task_id = record.get('task_id')
    if (not _valid_text(capture_id) or capture_id in global_capture_ids):
        scene_failures.append(prefix + ':capture_id_invalid_or_duplicate')
    else:
        global_capture_ids.add(capture_id)
    if not _valid_text(task_id) or task_id in global_task_ids:
        scene_failures.append(prefix + ':task_id_invalid_or_duplicate')
    else:
        global_task_ids.add(task_id)
    if not _integer(record.get('unique_frames'), MIN_SCENE_FRAMES):
        scene_failures.append(prefix + ':unique_frames_below_minimum')
    if record.get('ground_truth_complete') is not True:
        scene_failures.append(prefix + ':ground_truth_incomplete')
    for field in (
            'tf_valid_frames', 'xyz_valid_frames', 'depth_valid_frames',
            'latency_samples'):
        value = record.get(field)
        if (not _integer(value, MIN_SCENE_FRAMES)
                or _integer(record.get('unique_frames'), 0)
                and value > record['unique_frames']):
            scene_failures.append(prefix + ':' + field + '_insufficient')
    if record.get('bag_index_formal') is not True:
        scene_failures.append(prefix + ':bag_index_not_formal')
    if record.get('typed_raw_binding_pass') is not True:
        scene_failures.append(prefix + ':typed_raw_binding_failed')

    truth_path, truth = _load_declared_json(
        record.get('ground_truth_artifact'), artifact_root,
        prefix + ':ground_truth', scene_failures, seen_paths)
    tf_path, tf_value = _load_declared_json(
        record.get('tf_artifact'), artifact_root,
        prefix + ':tf', scene_failures, seen_paths)
    latency_path, latency = _load_declared_json(
        record.get('latency_artifact'), artifact_root,
        prefix + ':latency', scene_failures, seen_paths)
    del truth_path, tf_path, latency_path
    provenances = [
        _check_ground_truth_summary(
            truth, scene, capture_id, task_id, scene_failures),
        _check_tf_summary(
            tf_value, scene, capture_id, task_id, scene_failures),
        _check_latency_summary(
            latency, scene, capture_id, task_id, scene_failures),
    ]
    comparable = [value for value in provenances if value is not None]
    if comparable and any(value != comparable[0] for value in comparable[1:]):
        scene_failures.append(prefix + ':semantic_provenance_mismatch')
    failures.extend(scene_failures)
    return {
        'capture_id': capture_id,
        'task_id': task_id,
        'declared_unique_frames': record.get('unique_frames'),
        'passed': False,
        'failures': sorted(set(scene_failures)),
    }


def _legacy_assessment(payload, artifact_root, failures):
    failures.append('legacy_self_reported_readiness_forbidden')
    if payload.get('schema_version') != 1:
        failures.append('readiness_schema_version_invalid')
    if (payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False):
        failures.append('readiness_safety_policy_invalid')
    if payload.get('formal_acceptance') is not True:
        failures.append('formal_acceptance_missing')
    if payload.get('shared_graph') is not False:
        failures.append('shared_graph_forbidden')
    if payload.get('mixed_tf') is not False:
        failures.append('mixed_tf_forbidden')
    if payload.get('not_in_four_scene_denominator') is not False:
        failures.append('four_scene_denominator_excluded')
    if payload.get('ros1_field_install_pass') is not True:
        failures.append('ros1_field_install_missing')
    if payload.get('runtime_model_binding_pass') is not True:
        failures.append('runtime_model_binding_missing')
    scenes = payload.get('scenes')
    if not isinstance(scenes, Mapping) or set(scenes) != set(SCENES):
        failures.append('four_scene_set_invalid')
        scenes = {}
    reports = {}
    seen_paths = set()
    capture_ids = set()
    task_ids = set()
    for scene in SCENES:
        if scene not in scenes:
            reports[scene] = {
                'passed': False,
                'failures': ['scene:' + scene + ':missing']}
            continue
        reports[scene] = _legacy_scene(
            scene, scenes[scene], artifact_root, failures, seen_paths,
            capture_ids, task_ids)
    return reports


def _global_artifact(
        payload, key, artifact_root, failures, seen_paths):
    path, value = _load_declared_json(
        payload.get(key), artifact_root, key, failures, seen_paths)
    return path, value


def _validate_capability_matrix(workspace_root, failures):
    blocker = 'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED'
    if workspace_root is None:
        failures.append('workspace_live_audit_missing')
        return [blocker]
    path = (Path(workspace_root)
            / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception'
            / 'config' / 'capability_matrix.json')
    try:
        value = _load_json(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        failures.append('capability_matrix_invalid')
        return [blocker]
    capabilities = value.get('capabilities') if isinstance(
        value, Mapping) else None
    if (not isinstance(capabilities, Mapping)
            or value.get('implementation_validated') is not True
            or any(item is not True for item in capabilities.values())
            or capabilities.get('formal_readiness_rosbag1_admission')
            is not True
            or capabilities.get('typed_raw_binding') is not True):
        failures.append('ros1_runtime_architecture_incomplete')
        return [blocker]
    return []


def _validate_source_binding(
        payload, artifact_root, workspace_root, failures, seen_paths):
    declaration = payload.get('source_binding')
    path = _resolve_artifact(
        declaration, artifact_root, 'source_binding', failures, seen_paths)
    result = None
    if path is None or workspace_root is None:
        failures.append('source_binding_invalid')
        return result, path
    try:
        root = Path(workspace_root).resolve(strict=True)
        validator_path = (
            root / 'src' / 'limo_cleanup_perception'
            / 'limo_cleanup_perception'
            / 'ros1_source_core_admission.py')
        if _path_is_linklike(validator_path):
            raise OSError('host source admission validator is linked')
        spec = importlib.util.spec_from_file_location(
            'limo_cleanup_host_source_admission', str(validator_path))
        if spec is None or spec.loader is None:
            raise ImportError('host source admission loader unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.validate_ros1_source_core_admission(root)
        evidence = _load_json(path)
        if (not isinstance(evidence, Mapping) or evidence != result
                or result.get('gate_id')
                != 'ROS1_SOURCE_CORE_ADMISSION_V2'
                or result.get('validated_pass') is not True
                or result.get('package_validator_executed') is not False
                or result.get('package_validator_return_value_trusted')
                is not False):
            failures.append('source_binding_invalid')
    except (ImportError, OSError, RuntimeError, ValueError,
            json.JSONDecodeError):
        failures.append('source_binding_invalid')
    if (not isinstance(result, Mapping)
            or result.get('validated_pass') is not True):
        failures.append('host_source_admission_not_validated')
    return result, path


def _validate_model_binding(
        payload, artifact_root, failures, seen_paths):
    # Direct weight reopening through the ROS1 package loader is necessary,
    # but a host-owned production model-admission validator is not yet bound.
    failures.append('host_model_admission_not_validated')
    declaration = payload.get('model_binding')
    if (not isinstance(declaration, Mapping)
            or set(declaration) != {'manifest', 'model_root', 'artifacts'}
            or not isinstance(declaration.get('artifacts'), Mapping)
            or set(declaration['artifacts'])
            != {'plastic_bottle', 'trash_bin'}
            or not _valid_text(declaration.get('model_root'))
            or Path(declaration['model_root']).is_absolute()
            or '..' in Path(declaration['model_root']).parts):
        failures.append('model_binding_invalid')
        return {}, None, None
    manifest_path = _resolve_artifact(
        declaration['manifest'], artifact_root, 'model_binding:manifest',
        failures, seen_paths)
    if artifact_root is None:
        failures.append('model_binding_invalid')
        return {}, manifest_path, None
    try:
        root = (Path(artifact_root).resolve(strict=True)
                / declaration['model_root']).resolve(strict=True)
        root.relative_to(Path(artifact_root).resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        failures.append('model_binding_invalid')
        return {}, manifest_path, None
    declared_paths = {}
    for class_name in ('plastic_bottle', 'trash_bin'):
        declared_paths[class_name] = _resolve_artifact(
            declaration['artifacts'][class_name], artifact_root,
            'model_binding:' + class_name, failures, seen_paths)
    if manifest_path is None or any(
            path is None for path in declared_paths.values()):
        failures.append('model_binding_invalid')
        return {}, manifest_path, root
    try:
        from limo_cleanup_ros1_perception.dual_model_detector import (
            load_model_bindings, model_set_sha256, resolve_model_artifacts)
        bindings, manifest_sha = load_model_bindings(manifest_path)
        resolved = resolve_model_artifacts(bindings, root)
        if any(Path(resolved[name]) != declared_paths[name]
               for name in resolved):
            failures.append('model_binding_invalid')
        return {
            'manifest_sha256': manifest_sha,
            'model_set_sha256': model_set_sha256(bindings),
            'artifacts': {
                name: _artifact_identity(path)
                for name, path in sorted(resolved.items())},
        }, manifest_path, root
    except (ImportError, OSError, RuntimeError, ValueError, KeyError):
        failures.append('model_binding_invalid')
        return {}, manifest_path, root


def _validate_output_contract(
        payload, artifact_root, workspace_root, failures, seen_paths):
    path, value = _global_artifact(
        payload, 'output_contract', artifact_root, failures, seen_paths)
    expected_path = None
    if workspace_root is not None:
        expected_path = (
            Path(workspace_root) / 'ros1_overlay_src'
            / 'limo_cleanup_ros1_perception' / 'config'
            / 'read_only_output_contract.json')
    try:
        expected = _load_json(expected_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            TypeError):
        expected = None
    if (path is None or not isinstance(value, Mapping)
            or value != expected
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('control_publishers_allowed') is not False
            or value.get('services_allowed') is not False
            or value.get('actions_allowed') is not False):
        failures.append('output_contract_invalid')
    return value


def _validate_install(value, source_result, failures):
    # A self-reported install PASS is never authoritative.  This blocker is
    # removed only after wiring the exact host production validator and
    # matching its fresh recomputation to this evidence artifact.
    failures.append('host_install_admission_not_validated')
    if (not isinstance(value, Mapping)
            or value.get('gate_id') != 'ROS1_NOETIC_FIELD_INSTALL'
            or value.get('validated_pass') is not True
            or value.get('architecture_blockers') != []
            or value.get('delivery_ready') is not False):
        failures.append('ros1_field_install_validation_invalid')
        return None
    source_contract = value.get('source_contract')
    if (not isinstance(source_result, Mapping)
            or not isinstance(source_contract, Mapping)
            or source_contract.get('source_set_sha256')
            != source_result.get('source_set_sha256')
            or source_contract.get('contract_sha256')
            != source_result.get('contract_sha256')):
        failures.append('ros1_field_install_source_binding_mismatch')
    return value.get('evidence_sha256')


def _validate_hardware(value, failures):
    if (not isinstance(value, Mapping)
            or value.get('runtime_family') != 'ROS1'
            or value.get('ros_distro') != 'noetic'
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('camera_only') is not True
            or value.get('shared_graph') is not False
            or value.get('mixed_tf') is not False
            or value.get('validated_pass') is not True
            or value.get('control_publishers_present') is not False):
        failures.append('hardware_readiness_invalid')


def _validate_expected_manifest(
        payload, artifact_root, failures, seen_paths):
    path, value = _global_artifact(
        payload, 'expected_topic_manifest', artifact_root,
        failures, seen_paths)
    try:
        from limo_cleanup_ros1_perception.rosbag1_rgbd_indexer import (
            load_formal_manifest)
        loaded = load_formal_manifest(path)
        if value.get('manifest_id') != loaded.get('manifest_id'):
            failures.append('expected_topic_manifest_invalid')
    except (ImportError, OSError, RuntimeError, ValueError, AttributeError):
        failures.append('expected_topic_manifest_invalid')
    return path


def _capture_window(value) -> bool:
    return (_strict_keys(value, {
        'record_start_ns', 'record_end_ns',
        'header_start_ns', 'header_end_ns'})
        and all(_integer(value[key], 1) for key in value)
        and value['record_end_ns'] > value['record_start_ns']
        and value['header_end_ns'] > value['header_start_ns'])


def _distance(first, second):
    if not _point(first) or not _point(second):
        return None
    return math.sqrt(sum(
        (first[key] - second[key]) ** 2 for key in ('x', 'y', 'z')))


def _check_xyz_records(
        value, scene, capture_id, task_id, failures,
        frames, binding):
    provenance = _semantic_common(
        value, scene, capture_id, task_id, failures, 'xyz')
    expected_top = {
        'schema_version', 'report_kind', 'scene', 'capture_id', 'task_id',
        'ros1_field_install_sha256', 'model_binding_sha256',
        'synthetic_test_only', 'not_applicable', 'sample_count',
        'max_error_m', 'p95_error_m', 'records'}
    if (not _strict_keys(value, expected_top)
            or value.get('report_kind') != 'ros1_xyz_reference'
            or not isinstance(value.get('not_applicable'), bool)
            or not isinstance(value.get('records'), list)):
        failures.append('xyz_reference_binding_invalid')
        return {'provenance': provenance, 'records': {}}
    _, _, targets, _ = _frame_maps(frames, binding)
    expected_observations = {
        observation_id for observation_id, pair in targets.items()
        if pair[1].get('valid') is True}
    records = {}
    errors = []
    record_keys = {
        'sequence', 'stamp_ns', 'bundle_id', 'observation_id',
        'object_class', 'reference_position', 'measured_position',
        'error_m', 'reference_artifact_sha256'}
    for record in value['records']:
        if not _strict_keys(record, record_keys):
            failures.append('xyz_record_invalid')
            continue
        observation_id = record.get('observation_id')
        pair = targets.get(observation_id)
        frame = pair[0] if pair else None
        target = pair[1] if pair else None
        key = (record.get('sequence'), record.get('stamp_ns'),
               record.get('bundle_id'))
        calculated = _distance(
            record.get('reference_position'),
            record.get('measured_position'))
        if (pair is None or observation_id in records
                or _frame_key(frame) != key
                or record.get('object_class') != target.get('object_class')
                or not _points_close(
                    record.get('measured_position'), target.get('position'))
                or calculated is None
                or not _finite(record.get('error_m'), 0.0)
                or abs(record['error_m'] - calculated) > 1e-6
                or not _lower_sha256(
                    record.get('reference_artifact_sha256'))):
            failures.append('xyz_reference_binding_invalid')
            continue
        records[observation_id] = record
        errors.append(calculated)
    no_observations = not expected_observations
    expected_summary = {
        'not_applicable': no_observations,
        'sample_count': len(records),
        'max_error_m': max(errors) if errors else None,
        'p95_error_m': _percentile(errors, 0.95),
    }
    if (set(records) != expected_observations
            or any(value.get(key) != expected
                   for key, expected in expected_summary.items())
            or errors and max(errors) > MAX_XYZ_ERROR_M):
        failures.append('xyz_reference_binding_invalid')
    return {'provenance': provenance, 'records': records}


def _check_depth_records(
        value, scene, capture_id, task_id, failures,
        frames, binding):
    provenance = _semantic_common(
        value, scene, capture_id, task_id, failures, 'depth')
    expected_top = {
        'schema_version', 'report_kind', 'scene', 'capture_id', 'task_id',
        'ros1_field_install_sha256', 'model_binding_sha256',
        'synthetic_test_only', 'not_applicable', 'sample_count',
        'valid_rate', 'max_error_m', 'p95_error_m', 'records'}
    if (not _strict_keys(value, expected_top)
            or value.get('report_kind') != 'ros1_depth_reference'
            or not isinstance(value.get('not_applicable'), bool)
            or not isinstance(value.get('records'), list)):
        failures.append('depth_reference_binding_invalid')
        return {'provenance': provenance, 'records': {}}
    _, _, targets, _ = _frame_maps(frames, binding)
    expected_observations = {
        observation_id for observation_id, pair in targets.items()
        if pair[1].get('valid') is True}
    records = {}
    errors = []
    valid_samples = 0
    record_keys = {
        'sequence', 'stamp_ns', 'bundle_id', 'observation_id',
        'object_class', 'reference_depth_m', 'measured_depth_m',
        'valid_pixels', 'total_pixels', 'valid_ratio', 'valid', 'error_m',
        'reference_artifact_sha256'}
    for record in value['records']:
        if not _strict_keys(record, record_keys):
            failures.append('depth_record_invalid')
            continue
        observation_id = record.get('observation_id')
        pair = targets.get(observation_id)
        frame = pair[0] if pair else None
        target = pair[1] if pair else None
        key = (record.get('sequence'), record.get('stamp_ns'),
               record.get('bundle_id'))
        measured = record.get('measured_depth_m')
        reference = record.get('reference_depth_m')
        calculated_error = (
            abs(measured - reference)
            if _finite(measured, 0.0) and _finite(reference, 0.0)
            else None)
        pixels = record.get('valid_pixels')
        total = record.get('total_pixels')
        ratio = record.get('valid_ratio')
        valid = record.get('valid')
        target_depth = target.get('depth_m') if target else None
        target_pixels = target.get('depth_valid_pixels') if target else None
        target_total = target.get('depth_total_pixels') if target else None
        target_ratio = target.get('depth_valid_ratio') if target else None
        target_valid = target.get('valid') if target else None
        if (pair is None or observation_id in records
                or _frame_key(frame) != key
                or record.get('object_class') != target.get('object_class')
                or calculated_error is None
                or not _finite(target_depth, 0.0)
                or abs(measured - target_depth) > 1e-6
                or pixels != target_pixels
                or total != target_total
                or ratio != target_ratio
                or not _integer(pixels, 0) or not _integer(total, 1)
                or pixels > total or not _finite(ratio, 0.0, 1.0)
                or abs(ratio - pixels / total) > 1e-6
                or not isinstance(valid, bool)
                or not isinstance(target_valid, bool)
                or valid is not (target_valid is True)
                or not _finite(record.get('error_m'), 0.0)
                or abs(record['error_m'] - calculated_error) > 1e-6
                or not _lower_sha256(
                    record.get('reference_artifact_sha256'))):
            failures.append('depth_reference_binding_invalid')
            continue
        records[observation_id] = record
        if valid:
            valid_samples += 1
            errors.append(calculated_error)
    no_observations = not expected_observations
    valid_rate = (
        valid_samples / len(records) if records else None)
    expected_summary = {
        'not_applicable': no_observations,
        'sample_count': len(records),
        'valid_rate': valid_rate,
        'max_error_m': max(errors) if errors else None,
        'p95_error_m': _percentile(errors, 0.95),
    }
    if (set(records) != expected_observations
            or any(value.get(key) != expected
                   for key, expected in expected_summary.items())
            or (records and (valid_rate is None
                             or valid_rate < MIN_DEPTH_VALID_RATE))
            or errors and max(errors) > MAX_DEPTH_ERROR_M):
        failures.append('depth_reference_binding_invalid')
    return {'provenance': provenance, 'records': records}


def _formal_scene(
        scene, record, payload, artifact_root, workspace_root,
        source_path, model_manifest_path, model_root, topic_manifest_path,
        install_sha, model_info, failures, seen_paths,
        capture_ids, task_ids, capture_windows,
        seen_scene_artifact_fingerprints, seen_raw_fingerprints,
        seen_raw_bundle_fingerprints):
    prefix = 'scene:' + scene
    scene_failures = []
    report = {'passed': False, 'failures': scene_failures}
    if not _strict_keys(record, FORMAL_SCENE_KEYS):
        scene_failures.append(prefix + ':schema_invalid')
        failures.extend(scene_failures)
        return report
    capture_id = record.get('capture_id')
    task_id = record.get('task_id')
    if not _valid_text(capture_id):
        scene_failures.append(prefix + ':capture_id_invalid_or_duplicate')
    if not _valid_text(task_id):
        scene_failures.append(prefix + ':task_id_invalid_or_duplicate')
    if not _capture_window(record.get('capture_window')):
        scene_failures.append(prefix + ':capture_window_invalid')

    raw_path = _resolve_artifact(
        record.get('raw_bag'), artifact_root, prefix + ':raw_bag',
        scene_failures, seen_paths)
    index_path, index_value = _load_declared_json(
        record.get('raw_index'), artifact_root, prefix + ':raw_index',
        scene_failures, seen_paths)
    collector_path, collector = _load_declared_json(
        record.get('collector_manifest'), artifact_root,
        prefix + ':collector_manifest', scene_failures, seen_paths)
    frames_path = _resolve_artifact(
        record.get('typed_frames'), artifact_root, prefix + ':typed_frames',
        scene_failures, seen_paths)
    stored_binding_path, stored_binding = _load_declared_json(
        record.get('typed_raw_binding'), artifact_root,
        prefix + ':typed_raw_binding', scene_failures, seen_paths)
    for role, path in (
            ('raw_bag', raw_path), ('raw_index', index_path),
            ('collector_manifest', collector_path),
            ('typed_frames', frames_path),
            ('typed_raw_binding', stored_binding_path)):
        _record_content_fingerprint(
            path, scene, role, seen_scene_artifact_fingerprints,
            scene_failures, 'four_scene_artifact_content_fingerprint_reused')
    _record_content_fingerprint(
        raw_path, scene, 'raw_bag', seen_raw_fingerprints,
        scene_failures, 'four_scene_raw_capture_fingerprint_reused')
    try:
        frames = _load_jsonl(frames_path) if frames_path is not None else []
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        frames = []
        scene_failures.append(prefix + ':typed_frames_invalid')
    context = {
        'index_path': index_path,
        'frames_path': frames_path,
        'collector_path': collector_path,
        'raw_bag_path': raw_path,
        'workspace_root': workspace_root,
        'source_admission_path': source_path,
        'topic_manifest_path': topic_manifest_path,
        'model_manifest_path': model_manifest_path,
        'model_root': model_root,
    }
    recomputed = create_binding(
        index_value if isinstance(index_value, Mapping) else {},
        frames, collector if isinstance(collector, Mapping) else {},
        artifact_context=context)
    stored_comparable = dict(stored_binding) if isinstance(
        stored_binding, Mapping) else None
    if isinstance(stored_comparable, Mapping):
        stored_comparable.pop('binding_source', None)
    if (recomputed.get('formal_acceptance') is not True
            or stored_comparable != recomputed):
        scene_failures.append(prefix + ':typed_raw_binding_invalid')

    index_capture_id = index_value.get('capture_id') if isinstance(
        index_value, Mapping) else None
    index_scene = index_value.get('scene') if isinstance(
        index_value, Mapping) else None
    index_window = index_value.get('capture_window') if isinstance(
        index_value, Mapping) else None
    collector_task_id = collector.get('task_id') if isinstance(
        collector, Mapping) else None
    collector_scene = collector.get('scene') if isinstance(
        collector, Mapping) else None
    if (not _valid_text(capture_id)
            or capture_id != index_capture_id
            or capture_id != recomputed.get('capture_id')):
        scene_failures.append(prefix + ':capture_identity_mismatch')
    elif capture_id in capture_ids:
        scene_failures.append(prefix + ':capture_id_invalid_or_duplicate')
    else:
        capture_ids.add(capture_id)
    if (not _valid_text(task_id)
            or task_id != collector_task_id
            or task_id != recomputed.get('task_id')):
        scene_failures.append(prefix + ':task_identity_mismatch')
    elif task_id in task_ids:
        scene_failures.append(prefix + ':task_id_invalid_or_duplicate')
    else:
        task_ids.add(task_id)
    if (scene != index_scene or scene != collector_scene
            or scene != recomputed.get('scene')):
        scene_failures.append(prefix + ':scene_identity_mismatch')
    declared_window = record.get('capture_window')
    if (not _capture_window(declared_window)
            or declared_window != index_window):
        scene_failures.append(prefix + ':capture_window_binding_mismatch')
    else:
        _record_capture_window(
            scene, index_window, capture_windows, scene_failures)
    _record_raw_bundle_fingerprints(
        scene, recomputed, seen_raw_bundle_fingerprints, scene_failures)

    truth_path, truth = _load_declared_json(
        record.get('ground_truth_artifact'), artifact_root,
        prefix + ':ground_truth', scene_failures, seen_paths)
    tf_path, tf_value = _load_declared_json(
        record.get('tf_artifact'), artifact_root, prefix + ':tf',
        scene_failures, seen_paths)
    xyz_path, xyz_value = _load_declared_json(
        record.get('xyz_artifact'), artifact_root, prefix + ':xyz',
        scene_failures, seen_paths)
    depth_path, depth_value = _load_declared_json(
        record.get('depth_artifact'), artifact_root, prefix + ':depth',
        scene_failures, seen_paths)
    latency_path, latency = _load_declared_json(
        record.get('latency_artifact'), artifact_root, prefix + ':latency',
        scene_failures, seen_paths)
    for role, path in (
            ('ground_truth', truth_path), ('tf', tf_path),
            ('xyz', xyz_path), ('depth', depth_path),
            ('latency', latency_path)):
        _record_content_fingerprint(
            path, scene, role, seen_scene_artifact_fingerprints,
            scene_failures, 'four_scene_artifact_content_fingerprint_reused')

    truth_report = _check_ground_truth_summary(
        truth, scene, capture_id, task_id, scene_failures,
        frames, recomputed)
    tf_report = _check_tf_summary(
        tf_value, scene, capture_id, task_id, scene_failures,
        frames, recomputed)
    xyz_report = _check_xyz_records(
        xyz_value, scene, capture_id, task_id, scene_failures,
        frames, recomputed)
    depth_report = _check_depth_records(
        depth_value, scene, capture_id, task_id, scene_failures,
        frames, recomputed)
    latency_report = _check_latency_summary(
        latency, scene, capture_id, task_id, scene_failures,
        frames, recomputed)
    expected_provenance = (
        install_sha, model_info.get('model_set_sha256'))
    for semantic_report in (
            truth_report, tf_report, xyz_report, depth_report,
            latency_report):
        if semantic_report.get('provenance') != expected_provenance:
            scene_failures.append(prefix + ':semantic_provenance_mismatch')

    frame_count = len(frames)
    sync_values = [
        frame.get('sync_span_sec') for frame in frames
        if isinstance(frame, Mapping)
        and _finite(frame.get('sync_span_sec'), 0.0)]
    processing_values = [
        frame.get('processing_latency_sec') for frame in frames
        if isinstance(frame, Mapping)
        and _finite(frame.get('processing_latency_sec'), 0.0)]
    transport_values = [
        frame.get('transport_latency_sec') for frame in frames
        if isinstance(frame, Mapping)
        and _finite(frame.get('transport_latency_sec'), 0.0)]
    if (frame_count < MIN_SCENE_FRAMES
            or len(sync_values) != frame_count
            or len(processing_values) != frame_count
            or len(transport_values) != frame_count
            or _percentile(sync_values, 0.95) > MAX_SYNC_P95_SEC
            or _percentile(processing_values, 0.95)
            > MAX_PROCESSING_P95_SEC
            or _percentile(transport_values, 0.95)
            > MAX_END_TO_END_P95_SEC):
        scene_failures.append(prefix + ':latency_binding_invalid')
    if recomputed.get('association_count', 0) < MIN_SCENE_FRAMES:
        scene_failures.append(prefix + ':unique_frames_below_minimum')
    raw_count = recomputed.get('raw_bundle_count', 0)
    paired_count = recomputed.get('association_count', 0)
    if (not _integer(raw_count, 1)
            or not _integer(paired_count, 0)
            or (raw_count - paired_count) / raw_count > MAX_UNPAIRED_RATE):
        scene_failures.append(prefix + ':typed_raw_rejection_rate_exceeded')

    scene_failures = sorted(set(scene_failures))
    failures.extend(scene_failures)
    report.update({
        'capture_id': capture_id,
        'task_id': task_id,
        'unique_bound_frames': recomputed.get('association_count', 0),
        'typed_raw_binding': recomputed,
        'ground_truth_metrics': truth_report.get('metrics', {}),
        'tf_record_count': len(tf_report.get('records', {})),
        'xyz_record_count': len(xyz_report.get('records', {})),
        'depth_record_count': len(depth_report.get('records', {})),
        'latency_record_count': len(latency_report.get('records', {})),
        'passed': not scene_failures,
        'failures': scene_failures,
    })
    return report


def _formal_assessment(
        payload, artifact_root, workspace_root, failures):
    architecture_blockers = _validate_capability_matrix(
        workspace_root, failures)
    if (payload.get('schema_version') != 1
            or payload.get('runtime_family') != 'ROS1'
            or payload.get('ros_distro') != 'noetic'
            or payload.get('evidence_scope')
            != 'formal_four_scene_rosbag1_rgbd_acceptance'
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('publishes_ros_messages') is not False
            or payload.get('delivery_ready') is not False
            or payload.get('required_gates') != REQUIRED_GATES):
        failures.append('readiness_policy_invalid')
    bundle_payload = dict(payload)
    declared_bundle_id = bundle_payload.pop('bundle_id', None)
    if (not _lower_sha256(declared_bundle_id)
            or declared_bundle_id != _canonical_sha256(bundle_payload)):
        failures.append('readiness_bundle_id_invalid')

    seen_paths = set()
    source_result, source_path = _validate_source_binding(
        payload, artifact_root, workspace_root, failures, seen_paths)
    model_info, model_manifest_path, model_root = _validate_model_binding(
        payload, artifact_root, failures, seen_paths)
    _validate_output_contract(
        payload, artifact_root, workspace_root, failures, seen_paths)
    install_path, install_value = _global_artifact(
        payload, 'ros1_field_install_validation', artifact_root,
        failures, seen_paths)
    _validate_install(install_value, source_result, failures)
    install_sha = (
        _sha256_file(install_path) if install_path is not None else None)
    hardware_path, hardware = _global_artifact(
        payload, 'hardware_readiness', artifact_root, failures, seen_paths)
    del hardware_path
    _validate_hardware(hardware, failures)
    topic_manifest_path = _validate_expected_manifest(
        payload, artifact_root, failures, seen_paths)

    scenes = payload.get('scenes')
    if not isinstance(scenes, Mapping) or set(scenes) != set(SCENES):
        failures.append('four_scene_set_invalid')
        scenes = {}
    reports = {}
    capture_ids = set()
    task_ids = set()
    capture_windows = []
    seen_scene_artifact_fingerprints = {}
    seen_raw_fingerprints = {}
    seen_raw_bundle_fingerprints = {}
    for scene in SCENES:
        record = scenes.get(scene)
        if not isinstance(record, Mapping):
            code = 'scene:' + scene + ':missing'
            failures.append(code)
            reports[scene] = {'passed': False, 'failures': [code]}
            continue
        reports[scene] = _formal_scene(
            scene, record, payload, artifact_root, workspace_root,
            source_path, model_manifest_path, model_root,
            topic_manifest_path, install_sha, model_info, failures,
            seen_paths, capture_ids, task_ids, capture_windows,
            seen_scene_artifact_fingerprints, seen_raw_fingerprints,
            seen_raw_bundle_fingerprints)
    return reports, architecture_blockers


def assess_field_readiness(
        payload: Mapping, artifact_root: Optional[Path] = None,
        workspace_root: Optional[Path] = None) -> Mapping:
    """Reopen and recompute every admissible ROS1 field-evidence gate."""
    failures = []
    architecture_blockers = []
    if not isinstance(payload, Mapping):
        payload = {}
        failures.append('readiness_schema_invalid')
    if set(payload) == LEGACY_TOP_KEYS:
        scene_reports = _legacy_assessment(
            payload, artifact_root, failures)
        architecture_blockers = [
            'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED']
    elif set(payload) == FORMAL_TOP_KEYS:
        scene_reports, architecture_blockers = _formal_assessment(
            payload, artifact_root, workspace_root, failures)
    else:
        failures.append('readiness_schema_invalid')
        scene_reports = {
            scene: {'passed': False, 'failures': ['scene:' + scene + ':missing']}
            for scene in SCENES}
        architecture_blockers = [
            'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED']

    failures = sorted(set(failures))
    architecture_blockers = sorted(set(architecture_blockers))
    four_scene = (
        not failures and set(scene_reports) == set(SCENES)
        and all(scene_reports[scene].get('passed') is True
                for scene in SCENES))
    tf_3d = four_scene and all(
        scene_reports[scene].get('typed_raw_binding', {}).get(
            'formal_acceptance') is True for scene in SCENES)
    validated = not failures and not architecture_blockers
    delivery = validated and four_scene and tf_3d
    return {
        'schema_version': 2,
        'gate_id': 'ROS1_NOETIC_PERCEPTION_FIELD_READINESS',
        'evidence_scope': 'formal_four_scene_rosbag1_rgbd_acceptance',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'install_authority_scope': (
            'overlay_non_authoritative_material_only'),
        'host_install_admission_required': True,
        'minimum_unique_frames_per_scene': MIN_SCENE_FRAMES,
        'thresholds': {
            'max_sync_p95_sec': MAX_SYNC_P95_SEC,
            'max_processing_p95_sec': MAX_PROCESSING_P95_SEC,
            'max_end_to_end_p95_sec': MAX_END_TO_END_P95_SEC,
            'max_typed_raw_unpaired_rate': MAX_UNPAIRED_RATE,
            'min_depth_valid_rate': MIN_DEPTH_VALID_RATE,
            'max_xyz_error_m': MAX_XYZ_ERROR_M,
            'max_depth_error_m': MAX_DEPTH_ERROR_M,
        },
        'scene_reports': scene_reports,
        'architecture_blockers': architecture_blockers,
        'validated_pass': validated,
        'formal_four_scene_pass': four_scene,
        'formal_tf_3d_pass': tf_3d,
        'delivery_ready': delivery,
        'failures': failures,
    }


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description='Fail-closed ROS1 four-scene readiness admission.')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--artifact-root', type=Path, required=True)
    parser.add_argument('--workspace-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args(args)


def main(args=None):
    """Write one exclusive report; never starts ROS, a camera, or motion."""
    parsed = parse_args(args)
    if parsed.output.exists():
        raise SystemExit('output path must not already exist')
    if parsed.output.resolve() == parsed.input.resolve():
        raise SystemExit('output path must differ from input')
    try:
        payload = _load_json(parsed.input)
        report = assess_field_readiness(
            payload, parsed.artifact_root, parsed.workspace_root)
    except (OSError, RuntimeError, UnicodeError, ValueError,
            json.JSONDecodeError) as error:
        report = {
            'schema_version': 2,
            'gate_id': 'ROS1_NOETIC_PERCEPTION_FIELD_READINESS',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'install_authority_scope': (
                'overlay_non_authoritative_material_only'),
            'host_install_admission_required': True,
            'validated_pass': False,
            'formal_four_scene_pass': False,
            'formal_tf_3d_pass': False,
            'delivery_ready': False,
            'architecture_blockers': [
                'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED'],
            'failures': ['readiness_input_invalid', type(error).__name__],
        }
    report['readiness_source'] = _artifact_identity(Path(__file__))
    report['input_bundle'] = _artifact_identity(parsed.input)
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    with parsed.output.open('x', encoding='utf-8') as stream:
        json.dump(
            report, stream, ensure_ascii=False, indent=2,
            sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return 0 if report.get('delivery_ready') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
