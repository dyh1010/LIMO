"""Quantitative read-only evaluation for four scenes and frozen RGB data."""

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')


@dataclass(frozen=True)
class EvaluationThresholds:
    """Machine gates for one independently arranged real scene."""

    min_frames: int = 30
    min_expected_class_recall: float = 0.90
    max_absent_class_false_positive_rate: float = 0.01
    min_expected_depth_valid_rate: float = 0.80
    min_actionable_recall: float = 0.90
    max_in_bin_actionable_leak_rate: float = 0.0
    max_outside_wrong_suppression_rate: float = 0.0
    max_rgbd_rejection_rate: float = 0.05
    max_sync_p95_sec: float = 0.15
    max_processing_latency_p95_sec: float = 0.50
    max_end_to_end_latency_p95_sec: float = 0.75


def _validate_thresholds(
        thresholds: EvaluationThresholds,
        enforce_production_minimum: bool) -> Tuple[str, ...]:
    """Reject unsafe evaluator settings even for direct Python callers."""
    reasons = []
    if (
            not isinstance(thresholds, EvaluationThresholds)
            or not isinstance(thresholds.min_frames, int)
            or isinstance(thresholds.min_frames, bool)
            or thresholds.min_frames <= 0):
        reasons.append('invalid_min_frames')
    elif enforce_production_minimum and thresholds.min_frames < 30:
        reasons.append('min_frames_below_production_minimum')
    return tuple(reasons)


def safe_rate(numerator: int, denominator: int) -> Optional[float]:
    """Return a finite rate or None when the denominator is zero."""
    if denominator <= 0:
        return None
    return float(numerator / denominator)


def percentile(values: Sequence[float], probability: float) -> Optional[float]:
    """Compute a linearly interpolated percentile without NumPy."""
    finite = sorted(
        float(value) for value in values
        if isinstance(value, (int, float)) and math.isfinite(value))
    if not finite:
        return None
    if len(finite) == 1:
        return finite[0]
    index = (len(finite) - 1) * probability
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return finite[lower]
    weight = index - lower
    return finite[lower] * (1.0 - weight) + finite[upper] * weight


def distribution(values: Sequence[float]) -> Mapping[str, Optional[float]]:
    """Summarize finite samples with count, p50, p95, and maximum."""
    finite = [
        float(value) for value in values
        if isinstance(value, (int, float)) and math.isfinite(value)]
    return {
        'samples': len(finite),
        'p50': median(finite) if finite else None,
        'p95': percentile(finite, 0.95),
        'max': max(finite) if finite else None,
    }


def wilson_interval(successes: int, total: int) -> Tuple[Optional[float], Optional[float]]:
    """Return the two-sided 95% Wilson score interval for a binomial rate."""
    if total <= 0:
        return None, None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    radius = (
        z * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total))
        / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


def expected_presence(scene: str) -> Mapping[str, bool]:
    """Return image-level class truth for one of the frozen four scenes."""
    if scene not in SCENES:
        raise ValueError('unsupported scene: ' + scene)
    return {
        'plastic_bottle': scene in ('bottle_in_bin', 'bottle_outside'),
        'trash_bin': scene in ('bin_only', 'bottle_in_bin', 'bottle_outside'),
    }


def _target_class(target: Mapping) -> str:
    return str(target.get('object_class', ''))


def _target_valid(target: Mapping) -> bool:
    return target.get('valid') is True


def _frame_rejected(frame: Mapping) -> bool:
    return (
        frame.get('valid') is not True
        or frame.get('status') in (
            'rgbd_contract_rejected', 'targets_invalid'))


def _finite_number(value, minimum=None, maximum=None) -> bool:
    if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)):
        return False
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def validate_target_record(target: Mapping) -> Tuple[str, ...]:
    """Validate one serialized typed target fail-closed."""
    reasons = []
    if target.get('object_class') not in ('plastic_bottle', 'trash_bin'):
        reasons.append('unsupported_object_class')
    if not isinstance(target.get('observation_id'), str) or not target.get(
            'observation_id'):
        reasons.append('missing_observation_id')
    if not _finite_number(target.get('confidence'), 0.0, 1.0):
        reasons.append('invalid_confidence')
    if not isinstance(target.get('valid'), bool):
        reasons.append('invalid_valid_flag')
    if not isinstance(target.get('actionable'), bool):
        reasons.append('invalid_actionable_flag')
    if not isinstance(target.get('status'), str) or not target.get('status'):
        reasons.append('invalid_status')
    label = target.get('object_class')
    status = target.get('status')
    valid = target.get('valid')
    actionable = target.get('actionable')
    error_code = target.get('error_code')
    if not isinstance(error_code, str):
        reasons.append('invalid_error_code')
    elif valid is True and error_code:
        reasons.append('valid_target_has_error')
    elif valid is False and not error_code:
        reasons.append('invalid_target_missing_error')
    if label == 'trash_bin' and (
            status != 'observed' or actionable is not False):
        reasons.append('trash_bin_semantics_invalid')
    if label == 'plastic_bottle':
        if status not in ('active', 'already_in_bin'):
            reasons.append('bottle_status_invalid')
        elif status == 'active' and valid is True and actionable is not True:
            reasons.append('active_bottle_not_actionable')
        elif status == 'already_in_bin' and actionable is not False:
            reasons.append('in_bin_bottle_actionable')
    if valid is False and actionable is not False:
        reasons.append('invalid_target_actionable')
    if not _finite_number(target.get('depth_valid_ratio'), 0.0, 1.0):
        reasons.append('invalid_depth_valid_ratio')
    position = target.get('position')
    size = target.get('size')
    if (not isinstance(position, Mapping)
            or not all(_finite_number(position.get(axis)) for axis in 'xyz')):
        reasons.append('invalid_position')
    if (not isinstance(size, Mapping)
            or not all(_finite_number(size.get(axis), 0.0) for axis in 'xyz')
            or (isinstance(size, Mapping) and not all(
                _finite_number(size.get(axis)) and size.get(axis) > 0.0
                for axis in 'xyz'))):
        reasons.append('invalid_size')
    bbox = target.get('bbox')
    if (not isinstance(bbox, list) or len(bbox) != 4
            or not all(_finite_number(value) for value in bbox)
            or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]):
        reasons.append('invalid_bbox')
    depth_m = target.get('depth_m')
    valid_pixels = target.get('depth_valid_pixels')
    total_pixels = target.get('depth_total_pixels')
    target_valid = target.get('valid') is True
    if (target_valid and (
            not _finite_number(depth_m, 0.0) or depth_m <= 0.0)):
        reasons.append('invalid_depth_m')
    elif not target_valid and not _finite_number(depth_m, 0.0):
        reasons.append('invalid_depth_m')
    if (not isinstance(valid_pixels, int) or isinstance(valid_pixels, bool)
            or valid_pixels < 0 or not isinstance(total_pixels, int)
            or isinstance(total_pixels, bool) or total_pixels <= 0
            or valid_pixels > total_pixels):
        reasons.append('invalid_depth_pixel_counts')
    elif (not _finite_number(target.get('depth_valid_ratio'), 0.0, 1.0)
          or abs(target['depth_valid_ratio']
                 - valid_pixels / total_pixels) > 1e-6):
        reasons.append('depth_ratio_count_mismatch')
    expected_source = {
        'plastic_bottle': 'plastic_bottle_model',
        'trash_bin': 'trash_bin_model',
    }.get(label)
    if target.get('source') != expected_source:
        reasons.append('missing_source')
    if target.get('position_semantics') != (
            'aligned_depth_roi_median_at_clipped_bbox_center'):
        reasons.append('missing_position_semantics')
    return tuple(reasons)


def validate_frame_record(frame: Mapping, expected_scene: str) -> Tuple[str, ...]:
    """Validate one collected frame before using it in metrics."""
    reasons = []
    if not isinstance(frame, Mapping):
        return ('frame_not_object',)
    if frame.get('schema_version') != 1:
        reasons.append('invalid_frame_schema_version')
    if frame.get('read_only') is not True:
        reasons.append('frame_not_read_only')
    if not isinstance(frame.get('task_id'), str) or not frame.get('task_id'):
        reasons.append('missing_task_id')
    if not isinstance(frame.get('valid'), bool):
        reasons.append('invalid_frame_valid_flag')
    if not isinstance(frame.get('status'), str) or not frame.get('status'):
        reasons.append('invalid_frame_status')
    if not isinstance(frame.get('frame_id'), str) or not frame.get('frame_id'):
        reasons.append('missing_frame_id')
    if frame.get('scene') not in (None, '', expected_scene):
        reasons.append('scene_label_mismatch')
    targets = frame.get('targets')
    if not isinstance(targets, list):
        reasons.append('targets_not_list')
    else:
        for target in targets:
            if not isinstance(target, Mapping):
                reasons.append('target_not_object')
                continue
            reasons.extend(validate_target_record(target))
        status = frame.get('status')
        valid_targets = sum(
            isinstance(target, Mapping) and target.get('valid') is True
            for target in targets)
        if status == 'targets_ready' and (not targets or not valid_targets):
            reasons.append('targets_ready_without_valid_target')
        elif status == 'no_targets' and targets:
            reasons.append('no_targets_contains_targets')
        elif status == 'targets_invalid' and (
                not targets or valid_targets or frame.get('valid') is not False
                or not frame.get('error_code')):
            reasons.append('targets_invalid_semantics')
        elif status == 'rgbd_contract_rejected' and (
                targets or frame.get('valid') is not False
                or not frame.get('error_code')):
            reasons.append('rgbd_rejected_semantics')
        elif status not in (
                'targets_ready', 'no_targets', 'targets_invalid',
                'rgbd_contract_rejected'):
            reasons.append('unsupported_frame_status')
        if frame.get('valid') is True:
            if status not in ('targets_ready', 'no_targets'):
                reasons.append('valid_frame_status_invalid')
            if frame.get('error_code') not in ('', None):
                reasons.append('valid_frame_has_error')
        elif frame.get('valid') is False and not frame.get('error_code'):
            reasons.append('invalid_frame_missing_error')
    for key in (
            'sync_span_sec', 'processing_latency_sec',
            'transport_latency_sec'):
        if not _finite_number(frame.get(key), 0.0):
            reasons.append('invalid_' + key)
    return tuple(reasons)


def _frame_sequence(frame: Mapping) -> Optional[int]:
    value = frame.get('sequence')
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _frame_stamp_ns(frame: Mapping) -> Optional[int]:
    stamp = frame.get('stamp')
    if not isinstance(stamp, Mapping):
        return None
    sec = stamp.get('sec')
    nanosec = stamp.get('nanosec')
    if (
            not isinstance(sec, int) or isinstance(sec, bool)
            or not isinstance(nanosec, int) or isinstance(nanosec, bool)
            or sec < 0 or not 0 <= nanosec < 1_000_000_000):
        return None
    value = sec * 1_000_000_000 + nanosec
    return value if value > 0 else None


def frame_identity_quality(frames: Sequence[Mapping]) -> Dict:
    """Check unique/monotonic sequence and usable sensor timestamps."""
    sequences = [
        _frame_sequence(frame) if isinstance(frame, Mapping) else None
        for frame in frames]
    stamps = [
        _frame_stamp_ns(frame) if isinstance(frame, Mapping) else None
        for frame in frames]
    valid_sequences = [value for value in sequences if value is not None]
    valid_stamps = [value for value in stamps if value is not None]
    sequence_unique = (
        len(valid_sequences) == len(frames)
        and len(set(valid_sequences)) == len(valid_sequences))
    sequence_strictly_increasing = (
        len(valid_sequences) == len(frames)
        and all(
            current > previous
            for previous, current in zip(
                valid_sequences, valid_sequences[1:])))
    stamp_strictly_increasing = (
        len(valid_stamps) == len(frames)
        and all(
            current > previous
            for previous, current in zip(valid_stamps, valid_stamps[1:])))
    frames_without_scene_label = sum(
        isinstance(frame, Mapping) and frame.get('scene') in (None, '')
        for frame in frames)
    return {
        'frames': len(frames),
        'valid_sequence_frames': len(valid_sequences),
        'unique_sequences': len(set(valid_sequences)),
        'sequence_unique': sequence_unique,
        'sequence_strictly_increasing': sequence_strictly_increasing,
        'valid_stamp_frames': len(valid_stamps),
        'stamp_strictly_increasing': stamp_strictly_increasing,
        'frames_without_scene_label': frames_without_scene_label,
    }


def evaluate_scene(
        scene: str, frames: Sequence[Mapping],
        thresholds: EvaluationThresholds = EvaluationThresholds(),
        enforce_production_minimum: bool = False) -> Dict:
    """Evaluate one scene using image-level class and 3D quality evidence."""
    truth = expected_presence(scene)
    class_counts = {
        label: {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0,
                'depth_valid_frames': 0, 'expected_frames': 0,
                'confidence': [], 'depth_valid_ratio': []}
        for label in truth
    }
    rejected_frames = 0
    sync_spans = []
    processing_latencies = []
    end_to_end_latencies = []
    actionable_true = 0
    actionable_expected = 0
    in_bin_actionable_leaks = 0
    outside_wrong_suppressions = 0
    seen_observation_ids = set()
    duplicate_observation_ids = 0
    scene_label_mismatches = 0
    schema_invalid_frames = 0
    schema_failures = []

    threshold_failures = list(_validate_thresholds(
        thresholds, enforce_production_minimum))

    for frame in frames:
        frame_errors = validate_frame_record(frame, scene)
        if frame_errors:
            schema_invalid_frames += 1
            schema_failures.extend(frame_errors)
        if not isinstance(frame, Mapping):
            rejected_frames += 1
            continue
        if frame.get('scene') not in (None, '', scene):
            scene_label_mismatches += 1
        rejected = _frame_rejected(frame)
        if rejected:
            rejected_frames += 1
        sync_spans.append(frame.get('sync_span_sec'))
        processing_latencies.append(frame.get('processing_latency_sec'))
        end_to_end_latencies.append(frame.get('transport_latency_sec'))
        raw_targets = frame.get('targets')
        targets = [
            item for item in raw_targets
            if isinstance(item, Mapping)
        ] if isinstance(raw_targets, list) else []
        for item in targets:
            observation_id = str(item.get('observation_id', ''))
            if not observation_id:
                continue
            if observation_id in seen_observation_ids:
                duplicate_observation_ids += 1
            seen_observation_ids.add(observation_id)
        by_class = {
            label: [item for item in targets if _target_class(item) == label]
            for label in truth
        }

        for label, expected in truth.items():
            observed = bool(by_class[label]) and not rejected
            counts = class_counts[label]
            if expected:
                counts['expected_frames'] += 1
                counts['tp' if observed else 'fn'] += 1
                if any(_target_valid(item) for item in by_class[label]):
                    counts['depth_valid_frames'] += 1
            else:
                counts['fp' if observed else 'tn'] += 1
            counts['confidence'].extend(
                item.get('confidence') for item in by_class[label])
            counts['depth_valid_ratio'].extend(
                item.get('depth_valid_ratio') for item in by_class[label]
                if _target_valid(item))

        bottles = by_class['plastic_bottle']
        if scene == 'bottle_outside':
            actionable_expected += 1
            if any(
                    item.get('actionable') is True and _target_valid(item)
                    for item in bottles):
                actionable_true += 1
            if any(
                    item.get('status') == 'already_in_bin'
                    for item in bottles):
                outside_wrong_suppressions += 1
        elif scene == 'bottle_in_bin' and any(
                item.get('actionable') is True for item in bottles):
            in_bin_actionable_leaks += 1

    class_metrics = {}
    failures = threshold_failures
    for label, expected in truth.items():
        counts = class_counts[label]
        recall = safe_rate(
            counts['tp'], counts['tp'] + counts['fn'])
        false_positive_rate = safe_rate(
            counts['fp'], counts['fp'] + counts['tn'])
        depth_valid_rate = safe_rate(
            counts['depth_valid_frames'], counts['expected_frames'])
        class_metrics[label] = {
            'tp': counts['tp'],
            'fp': counts['fp'],
            'fn': counts['fn'],
            'tn': counts['tn'],
            'image_recall': recall,
            'image_false_positive_rate': false_positive_rate,
            'expected_depth_valid_rate': depth_valid_rate,
            'confidence': distribution(counts['confidence']),
            'valid_target_roi_depth_ratio': distribution(
                counts['depth_valid_ratio']),
        }
        if expected:
            if recall is None or recall < thresholds.min_expected_class_recall:
                failures.append(label + '_recall_below_threshold')
            if (
                    depth_valid_rate is None
                    or depth_valid_rate
                    < thresholds.min_expected_depth_valid_rate):
                failures.append(label + '_depth_valid_rate_below_threshold')
        elif (
                false_positive_rate is None
                or false_positive_rate
                > thresholds.max_absent_class_false_positive_rate):
            failures.append(label + '_false_positive_rate_exceeded')

    frame_count = len(frames)
    identity = frame_identity_quality(frames)
    if frame_count < thresholds.min_frames:
        failures.append('insufficient_frame_count')
    if not identity['sequence_unique']:
        failures.append('sequence_not_unique')
    if not identity['sequence_strictly_increasing']:
        failures.append('sequence_not_strictly_increasing')
    if not identity['stamp_strictly_increasing']:
        failures.append('stamp_not_strictly_increasing')
    if scene_label_mismatches:
        failures.append('scene_label_mismatch')
    if schema_invalid_frames:
        failures.append('frame_schema_invalid')
    if duplicate_observation_ids:
        failures.append('duplicate_observation_id')
    rejection_rate = safe_rate(rejected_frames, frame_count)
    if (
            rejection_rate is None
            or rejection_rate > thresholds.max_rgbd_rejection_rate):
        failures.append('rgbd_rejection_rate_exceeded')

    sync = distribution(sync_spans)
    if sync['samples'] != frame_count:
        failures.append('sync_samples_incomplete')
    if sync['p95'] is None or sync['p95'] > thresholds.max_sync_p95_sec:
        failures.append('sync_p95_exceeded')
    latency = distribution(processing_latencies)
    if latency['samples'] != frame_count:
        failures.append('processing_latency_samples_incomplete')
    if (
            latency['p95'] is None
            or latency['p95']
            > thresholds.max_processing_latency_p95_sec):
        failures.append('processing_latency_p95_exceeded')
    end_to_end_latency = distribution(end_to_end_latencies)
    if end_to_end_latency['samples'] != frame_count:
        failures.append('end_to_end_latency_samples_incomplete')
    if (
            end_to_end_latency['p95'] is None
            or end_to_end_latency['p95'] < 0.0
            or end_to_end_latency['p95']
            > thresholds.max_end_to_end_latency_p95_sec):
        failures.append('end_to_end_latency_p95_exceeded')

    actionable_recall = safe_rate(actionable_true, actionable_expected)
    in_bin_leak_rate = safe_rate(in_bin_actionable_leaks, frame_count)
    outside_wrong_suppression_rate = safe_rate(
        outside_wrong_suppressions, frame_count)
    if scene == 'bottle_outside' and (
            actionable_recall is None
            or actionable_recall < thresholds.min_actionable_recall):
        failures.append('outside_bottle_actionable_recall_below_threshold')
    if scene == 'bottle_outside' and (
            outside_wrong_suppression_rate is None
            or outside_wrong_suppression_rate
            > thresholds.max_outside_wrong_suppression_rate):
        failures.append('outside_bottle_wrong_suppression_rate_exceeded')
    if scene == 'bottle_in_bin' and (
            in_bin_leak_rate is None
            or in_bin_leak_rate
            > thresholds.max_in_bin_actionable_leak_rate):
        failures.append('in_bin_actionable_leak_rate_exceeded')

    return {
        'schema_version': 1,
        'scene': scene,
        'read_only': True,
        'frame_count': frame_count,
        'frame_identity': identity,
        'scene_label_mismatches': scene_label_mismatches,
        'schema_invalid_frames': schema_invalid_frames,
        'schema_failures': sorted(set(schema_failures)),
        'duplicate_observation_ids': duplicate_observation_ids,
        'thresholds': asdict(thresholds),
        'class_metrics': class_metrics,
        'rgbd_rejected_frames': rejected_frames,
        'rgbd_rejection_rate': rejection_rate,
        'sync_span_sec': sync,
        'processing_latency_sec': latency,
        'end_to_end_latency_sec': end_to_end_latency,
        'outside_bottle_actionable_recall': actionable_recall,
        'outside_bottle_wrong_suppressed_frames': (
            outside_wrong_suppressions),
        'outside_bottle_wrong_suppression_rate': (
            outside_wrong_suppression_rate),
        'in_bin_actionable_leak_rate': in_bin_leak_rate,
        'passed': not failures,
        'failures': failures,
    }


def evaluate_suite(
        scenes: Mapping[str, Sequence[Mapping]],
        thresholds: EvaluationThresholds = EvaluationThresholds(),
        enforce_production_minimum: bool = False) -> Dict:
    """Require all four independently collected scenes before overall PASS."""
    threshold_failures = list(_validate_thresholds(
        thresholds, enforce_production_minimum))
    missing = [name for name in SCENES if name not in scenes]
    reports = {
        name: evaluate_scene(
            name, scenes[name], thresholds, enforce_production_minimum)
        for name in SCENES if name in scenes
    }
    failures = threshold_failures
    failures.extend('missing_scene:' + name for name in missing)
    failures.extend(
        'scene_failed:' + name
        for name, report in reports.items() if not report['passed'])
    return {
        'schema_version': 1,
        'read_only': True,
        'required_scenes': list(SCENES),
        'scene_reports': reports,
        'passed': not failures,
        'failures': failures,
    }


def _matrix_records(payload: Mapping, dataset: str) -> List[Mapping]:
    return list(payload.get('run', {}).get('records', {}).get(dataset, []))


def _record_by_name(records: Iterable[Mapping], name: str) -> Optional[Mapping]:
    return next((item for item in records if item.get('name') == name), None)


def recorded_artifact_binding(payload: Mapping) -> Dict:
    """Extract immutable input, model, and source hashes from a matrix."""
    models = []
    for name, item in payload.get('models', {}).items():
        if isinstance(item, Mapping):
            models.append({
                'name': name,
                'path': item.get('path'),
                'size': item.get('size'),
                'sha256': item.get('sha256'),
            })
    source_files = []
    for item in payload.get('source', {}).get('files', []):
        if isinstance(item, Mapping):
            source_files.append({
                'path': item.get('path'),
                'size': item.get('size'),
                'sha256': item.get('sha256'),
            })
    datasets = []
    for name, item in payload.get('datasets', {}).items():
        if isinstance(item, Mapping):
            datasets.append({
                'name': name,
                'path': item.get('path'),
                'images': item.get('images'),
                'manifest_sha256': item.get('manifest_sha256'),
                'files': [
                    {
                        'name': value.get('name'),
                        'path': value.get('path'),
                        'size': value.get('size'),
                        'sha256': value.get('sha256'),
                    }
                    for value in item.get('files', [])
                    if isinstance(value, Mapping)
                ],
            })
    return {
        'matrix_schema_version': payload.get('schema_version'),
        'matrix_generated_at': payload.get('generated_at'),
        'inference_parameters': payload.get('parameters', {}),
        'models': models,
        'source_files': source_files,
        'datasets': datasets,
    }


def _local_path(recorded_path: Optional[str]) -> Optional[Path]:
    """Map a recorded WSL /mnt/<drive> path to Windows when applicable."""
    if not recorded_path:
        return None
    match = re.match(r'^/mnt/([a-zA-Z])/(.*)$', str(recorded_path))
    if os.name == 'nt' and match:
        return Path(
            '{}:/{}'.format(match.group(1).upper(), match.group(2)))
    return Path(str(recorded_path))


def _verify_file(item: Mapping) -> Dict:
    """Verify one recorded size/hash entry against the local filesystem."""
    path = _local_path(item.get('path'))
    result = {
        'recorded_path': item.get('path'),
        'local_path': str(path) if path is not None else None,
        'expected_size': item.get('size'),
        'expected_sha256': item.get('sha256'),
        'exists': bool(path is not None and path.is_file()),
        'size_matches': False,
        'sha256_matches': False,
    }
    if not result['exists']:
        return result
    actual_size = path.stat().st_size
    actual_sha256 = sha256_file(path)
    result.update({
        'actual_size': actual_size,
        'actual_sha256': actual_sha256,
        'size_matches': actual_size == item.get('size'),
        'sha256_matches': actual_sha256.lower() == str(
            item.get('sha256', '')).lower(),
    })
    return result


def _verification_summary(items: Sequence[Mapping]) -> Dict:
    """Summarize local verification without hiding any mismatch."""
    verified = [_verify_file(item) for item in items]
    return {
        'expected': len(verified),
        'existing': sum(bool(item['exists']) for item in verified),
        'size_matches': sum(
            bool(item['size_matches']) for item in verified),
        'sha256_matches': sum(
            bool(item['sha256_matches']) for item in verified),
        'all_match': bool(verified) and all(
            item['size_matches'] and item['sha256_matches']
            for item in verified),
        'files': verified,
    }


def verify_recorded_artifacts(binding: Mapping) -> Dict:
    """Verify recorded model, source, and input image files locally."""
    datasets = binding.get('datasets', [])
    input_files = [
        item
        for dataset in datasets if isinstance(dataset, Mapping)
        for item in dataset.get('files', []) if isinstance(item, Mapping)
    ]
    models = _verification_summary(binding.get('models', []))
    source_files = _verification_summary(binding.get('source_files', []))
    inputs = _verification_summary(input_files)
    return {
        'models': models,
        'source_files': source_files,
        'input_images': inputs,
        'all_recorded_files_match': (
            models['all_match']
            and source_files['all_match']
            and inputs['all_match']),
        'current_source_matches_recorded_inference': source_files['all_match'],
    }


def evaluate_frozen_matrix(payload: Mapping) -> Dict:
    """Evaluate the current 148-image evidence without inventing 3D metrics."""
    positives = _matrix_records(payload, 'bottle_val')
    backgrounds = _matrix_records(payload, 'invalid_background')
    mixes = _matrix_records(payload, 'mix')
    selected_correct = sum(
        item.get('manual_label', {}).get('selected_target_correct') is True
        and item.get('target_bottle') is not None
        for item in positives)
    false_targets = sum(
        item.get('target_bottle') is not None for item in backgrounds)
    tp = selected_correct
    fn = len(positives) - tp
    fp = false_targets
    tn = len(backgrounds) - fp
    precision = safe_rate(tp, tp + fp)
    recall = safe_rate(tp, tp + fn)
    accuracy = safe_rate(tp + tn, tp + tn + fp + fn)
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision is not None and recall is not None
        and precision + recall > 0.0 else None)
    recall_interval = wilson_interval(tp, tp + fn)
    background_fp_interval = wilson_interval(fp, fp + tn)

    representative_names = {
        'background': ('invalid_background', 'IMG_9048.JPG'),
        'bin_only': ('mix', 'IMG_8976.JPG'),
        'bottle_in_bin': ('mix', 'IMG_9030.JPG'),
        'bottle_outside': ('mix', 'IMG_9017.JPG'),
    }
    datasets = {
        'invalid_background': backgrounds,
        'mix': mixes,
    }
    representatives = {}
    for scene, (dataset, name) in representative_names.items():
        record = _record_by_name(datasets[dataset], name)
        passed = False
        if record is not None and scene == 'background':
            passed = (
                record.get('target_bottle') is None
                and record.get('target_bin') is None)
        elif record is not None and scene == 'bin_only':
            passed = (
                record.get('target_bottle') is None
                and record.get('target_bin') is not None)
        elif record is not None and scene == 'bottle_in_bin':
            passed = (
                int(record.get('bottles_already_in_bin', 0)) >= 1
                and int(record.get('bottles_active', 0)) == 0
                and record.get('target_bin') is not None)
        elif record is not None and scene == 'bottle_outside':
            passed = (
                record.get('target_bottle') is not None
                and record.get('target_bin') is not None
                and int(record.get('bottles_active', 0)) >= 1)
        representatives[scene] = {
            'dataset': dataset,
            'image': name,
            'image_sha256': (
                record.get('image_sha256') if record is not None else None),
            'image_size_bytes': (
                record.get('image_size_bytes')
                if record is not None else None),
            'manual_label': (
                record.get('manual_label') if record is not None else None),
            'present': record is not None,
            'passed': passed,
        }

    mix_labeled = sum(
        item.get('manual_label', {}).get('status')
        == 'frozen_manual_representative'
        for item in mixes)
    mix_unknown = sum(
        item.get('manual_label', {}).get('status')
        == 'not_exhaustively_labeled'
        for item in mixes)
    scored_images = len(positives) + len(backgrounds)
    excluded_images = len(mixes)
    total_images = scored_images + excluded_images
    accounting = {
        'total_images': total_images,
        'confusion_matrix_scored_images': scored_images,
        'confusion_matrix_denominator': {
            'positive_ground_truth': len(positives),
            'negative_ground_truth': len(backgrounds),
            'tp_plus_fn': tp + fn,
            'fp_plus_tn': fp + tn,
            'tp_plus_fn_plus_fp_plus_tn': tp + fn + fp + tn,
        },
        'excluded_from_confusion_matrix_images': excluded_images,
        'unknown_or_not_exhaustively_labeled_images': mix_unknown,
        'manually_labeled_representative_images': mix_labeled,
        'skipped_due_to_file_or_inference_error': 0,
        'closure_equation': (
            '148 total = 78 confusion-matrix-scored + 70 mix '
            'inventory/representative-only'),
        'strictly_closed': (
            total_images == 148
            and scored_images == tp + fn + fp + tn
            and excluded_images == mix_unknown + mix_labeled),
        'datasets': {
            'bottle_val': {
                'images': len(positives),
                'ground_truth_label': (
                    'actionable_plastic_bottle_present'),
                'metric_role': 'positive_ground_truth_denominator',
                'purpose': (
                    'Frozen positive image-level bottle recall regression'),
                'scored_in_confusion_matrix': len(positives),
                'excluded': 0,
                'unknown': 0,
                'skipped': 0,
                'exclusion_reason': None,
            },
            'invalid_background': {
                'images': len(backgrounds),
                'ground_truth_label': 'no_plastic_bottle',
                'metric_role': 'negative_ground_truth_denominator',
                'purpose': (
                    'Frozen background image-level false-target regression'),
                'scored_in_confusion_matrix': len(backgrounds),
                'excluded': 0,
                'unknown': 0,
                'skipped': 0,
                'exclusion_reason': None,
            },
            'mix': {
                'images': len(mixes),
                'ground_truth_label': (
                    'mixed_three_representatives_plus_unknown_truth'),
                'metric_role': (
                    'inventory_statistics_and_four_scene_representatives'),
                'purpose': (
                    'Frozen detector inventory and three manually reviewed '
                    'bin-relation representative checks'),
                'scored_in_confusion_matrix': 0,
                'excluded': len(mixes),
                'unknown': mix_unknown,
                'skipped': 0,
                'manually_labeled_representatives': mix_labeled,
                'exclusion_reason': (
                    'The mix set is not exhaustively labeled. Its three '
                    'manually reviewed images are only representative '
                    'regressions and are not added to the TP/FP/FN/TN '
                    'denominator; the other 67 have unknown full truth.'),
            },
        },
    }

    regression_failures = []
    if not accounting['strictly_closed']:
        regression_failures.append('sample_accounting_not_strictly_closed')
    invalid_positive_labels = sum(
        item.get('manual_label', {}).get('selected_target_correct')
        not in (True, False)
        for item in positives)
    if invalid_positive_labels:
        regression_failures.append('invalid_selected_target_correct_label')
    if recall is None or recall < 0.90:
        regression_failures.append('bottle_recall_below_0.90')
    if false_targets != 0:
        regression_failures.append('background_false_targets_nonzero')
    regression_failures.extend(
        'representative_failed:' + scene
        for scene, value in representatives.items() if not value['passed'])

    return {
        'schema_version': 1,
        'read_only': True,
        'evidence_scope': 'frozen_2d_regression_only',
        'dataset_images': {
            'bottle_val': len(positives),
            'invalid_background': len(backgrounds),
            'mix': len(mixes),
            'total': len(positives) + len(backgrounds) + len(mixes),
        },
        'bottle_background_confusion': {
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'image_precision': precision,
            'image_recall': recall,
            'image_f1': f1,
            'image_accuracy': accuracy,
            'recall_wilson95': list(recall_interval),
            'background_false_positive_rate': safe_rate(fp, fp + tn),
            'background_fp_rate_wilson95': list(background_fp_interval),
        },
        'sample_accounting': accounting,
        'mix_summary': payload.get('run', {}).get(
            'summaries', {}).get('mix', {}),
        'four_scene_representatives': representatives,
        'recorded_artifact_binding': recorded_artifact_binding(payload),
        'regression_passed': not regression_failures,
        'regression_failures': regression_failures,
        'delivery_ready': False,
        'unavailable_evidence': [
            'trash_bin_independent_precision_recall',
            'target_roi_depth_valid_rate',
            'metric_xyz_error',
            'sync_span_distribution',
            'processing_and_end_to_end_latency',
            'statistically_sized_bin_only_in_bin_outside_scenes',
        ],
        'limitations': [
            'The data are a frozen same-domain regression set, not a proven '
            'instance-independent blind test.',
            'Most mix images are explicitly not exhaustively labeled.',
            'The 70 mix images are excluded from the 78-image bottle versus '
            'background confusion matrix; three are representative checks '
            'and 67 have unknown exhaustive truth.',
            'The matrix does not exercise live RGB-D, typed target frames, TF, '
            'or 3D projection.',
        ],
    }


def load_json_records(path: Path) -> List[Mapping]:
    """Load a JSON list/object-with-frames or one-JSON-value-per-line file."""
    text = path.read_text(encoding='utf-8')
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping) and isinstance(value.get('frames'), list):
        return value['frames']
    raise ValueError('expected a JSON list, JSONL, or object with frames')


def write_report(path: Path, report: Mapping) -> None:
    """Write stable, human-readable JSON evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8')


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest for evidence binding."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args():
    """Build the offline evaluator command line."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    matrix = subparsers.add_parser('matrix')
    matrix.add_argument('--matrix', type=Path, required=True)
    matrix.add_argument('--report', type=Path, required=True)
    matrix.add_argument(
        '--verify-recorded-files', action='store_true',
        help='Re-hash recorded models, source files, and all input images',
    )
    scene = subparsers.add_parser('scene')
    scene.add_argument('--scene', choices=SCENES, required=True)
    scene.add_argument('--frames', type=Path, required=True)
    scene.add_argument('--report', type=Path, required=True)
    scene.add_argument('--min-frames', type=int, default=30)
    suite = subparsers.add_parser('suite')
    for name in SCENES:
        suite.add_argument(
            '--' + name.replace('_', '-'), type=Path, required=True)
    suite.add_argument('--report', type=Path, required=True)
    suite.add_argument('--min-frames', type=int, default=30)
    gaps = subparsers.add_parser('gaps')
    for name in SCENES:
        gaps.add_argument('--' + name.replace('_', '-'), type=Path)
    gaps.add_argument('--report', type=Path, required=True)
    gaps.add_argument('--min-frames', type=int, default=30)
    return parser.parse_args()


def main():
    """Evaluate one matrix, one scene, or a complete four-scene suite."""
    args = parse_args()
    if args.command == 'matrix':
        payload = json.loads(args.matrix.read_text(encoding='utf-8'))
        report = evaluate_frozen_matrix(payload)
        report['source'] = {
            'path': str(args.matrix),
            'sha256': sha256_file(args.matrix),
            'size_bytes': args.matrix.stat().st_size,
        }
        evaluator_path = Path(__file__)
        report['evaluator'] = {
            'path': str(evaluator_path),
            'sha256': sha256_file(evaluator_path),
            'size_bytes': evaluator_path.stat().st_size,
        }
        current_sources = [
            evaluator_path,
            evaluator_path.with_name('perception_core.py'),
            evaluator_path.with_name('offline_dual_detector.py'),
        ]
        report['current_evaluation_sources'] = [
            {
                'path': str(path),
                'size_bytes': path.stat().st_size,
                'sha256': sha256_file(path),
            }
            for path in current_sources
        ]
        if args.verify_recorded_files:
            verification = verify_recorded_artifacts(
                report['recorded_artifact_binding'])
            report['artifact_verification'] = verification
            if not verification[
                    'current_source_matches_recorded_inference']:
                report['limitations'].append(
                    'Current source hashes differ from the source that '
                    'generated this frozen inference matrix; this command '
                    'evaluated recorded predictions and did not rerun YOLO.')
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['regression_passed'] else 1

    if args.min_frames < EvaluationThresholds().min_frames:
        raise SystemExit('min-frames cannot be lower than 30')
    thresholds = EvaluationThresholds(min_frames=args.min_frames)
    if args.command == 'scene':
        report = evaluate_scene(
            args.scene, load_json_records(args.frames), thresholds, True)
    elif args.command == 'suite':
        scene_paths = {
            name: getattr(args, name) for name in SCENES}
        report = evaluate_suite({
            name: load_json_records(path)
            for name, path in scene_paths.items()
        }, thresholds, True)
    else:
        scene_paths = {
            name: getattr(args, name) for name in SCENES
            if getattr(args, name) is not None
        }
        report = evaluate_suite({
            name: load_json_records(path)
            for name, path in scene_paths.items()
        }, thresholds, True)
        report['evidence_scope'] = 'formal_four_scene_rgbd_acceptance'
        report['delivery_ready'] = False
        report['provided_sources'] = {
            name: {
                'path': str(path),
                'sha256': sha256_file(path),
                'size_bytes': path.stat().st_size,
            }
            for name, path in scene_paths.items()
        }
        report['required_missing_evidence'] = [
            'independently_arranged_four_scene_rgbd_frames',
            'trash_bin_independent_precision_recall',
            'target_roi_depth_quality',
            'metric_xyz_ground_truth_error',
            'base_to_camera_tf_validation',
            'processing_and_transport_latency',
        ]
    if args.command in ('scene', 'suite'):
        if args.command == 'scene':
            scene_paths = {args.scene: args.frames}
        report['evidence_scope'] = 'four_scene_typed_rgbd_frame_metrics'
        report['provided_sources'] = {
            name: {
                'path': str(path),
                'sha256': sha256_file(path),
                'size_bytes': path.stat().st_size,
            }
            for name, path in scene_paths.items()
        }
        report['delivery_ready'] = False
        report['unavailable_delivery_evidence'] = [
            'metric_xyz_ground_truth_error_within_0.02_m',
            'validated_base_link_to_camera_tf',
            'independent_trash_bin_precision_recall',
            'independent_scene_arrangement_metadata',
        ]
    evaluator_path = Path(__file__)
    report['evaluator'] = {
        'path': str(evaluator_path),
        'sha256': sha256_file(evaluator_path),
        'size_bytes': evaluator_path.stat().st_size,
    }
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
