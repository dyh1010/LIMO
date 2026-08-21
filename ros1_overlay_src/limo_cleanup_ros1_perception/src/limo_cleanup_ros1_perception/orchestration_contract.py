"""Pure read-only target selection contract for task orchestration."""

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


ALLOWED_TARGET_CLASSES = ('plastic_bottle', 'trash_bin')


@dataclass(frozen=True)
class OrchestrationSelection:
    """Fail-closed result of consuming one typed perception frame."""

    accepted: bool
    reason: str
    target: Optional[Mapping]
    sequence: Optional[int]


def _rejected(reason, sequence=None):
    return OrchestrationSelection(False, reason, None, sequence)


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _stamp_seconds(frame):
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
    value = sec + nanosec / 1e9
    return value if value > 0.0 else None


def _valid_position(target):
    position = target.get('position')
    return (
        isinstance(position, Mapping)
        and all(_finite_number(position.get(axis)) for axis in ('x', 'y', 'z'))
    )


def _valid_size(target):
    size = target.get('size')
    return (
        isinstance(size, Mapping)
        and all(_finite_number(size.get(axis)) for axis in ('x', 'y', 'z'))
        and all(float(size[axis]) >= 0.0 for axis in ('x', 'y', 'z'))
    )


def _valid_bbox(target):
    bbox = target.get('bbox')
    return (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(_finite_number(value) for value in bbox)
        and float(bbox[2]) > float(bbox[0])
        and float(bbox[3]) > float(bbox[1])
    )


def _valid_depth_quality(target):
    depth_m = target.get('depth_m')
    valid_pixels = target.get('depth_valid_pixels')
    total_pixels = target.get('depth_total_pixels')
    ratio = target.get('depth_valid_ratio')
    return (
        _finite_number(depth_m) and float(depth_m) > 0.0
        and isinstance(valid_pixels, int) and not isinstance(valid_pixels, bool)
        and isinstance(total_pixels, int) and not isinstance(total_pixels, bool)
        and 0 < valid_pixels <= total_pixels
        and _finite_number(ratio) and 0.0 < float(ratio) <= 1.0
    )


def select_typed_target(
        frame: Mapping, requested_class: str, consumer_now_sec: float,
        max_frame_age_sec: float = 1.0, last_sequence: Optional[int] = None,
        seen_observation_ids: Sequence[str] = ()) -> OrchestrationSelection:
    """Select one fresh valid target without authorizing any robot motion."""
    if requested_class not in ALLOWED_TARGET_CLASSES:
        return _rejected('unsupported_requested_class')
    if (
            not _finite_number(consumer_now_sec)
            or not _finite_number(max_frame_age_sec)
            or max_frame_age_sec <= 0.0):
        return _rejected('invalid_consumer_time_config')
    if not isinstance(frame, Mapping):
        return _rejected('invalid_frame_schema')
    sequence = frame.get('sequence')
    if (
            not isinstance(sequence, int) or isinstance(sequence, bool)
            or sequence <= 0):
        return _rejected('invalid_sequence')
    if last_sequence is not None and sequence <= last_sequence:
        return _rejected('duplicate_or_stale_sequence', sequence)
    if frame.get('valid') is not True:
        return _rejected('frame_invalid', sequence)
    if frame.get('status') not in ('targets_ready', 'no_targets'):
        return _rejected('frame_status_invalid', sequence)
    if frame.get('error_code') not in ('', None):
        return _rejected('frame_error', sequence)
    if not isinstance(frame.get('frame_id'), str) or not frame.get('frame_id'):
        return _rejected('missing_frame_id', sequence)
    stamp_sec = _stamp_seconds(frame)
    if stamp_sec is None:
        return _rejected('invalid_stamp', sequence)
    age_sec = consumer_now_sec - stamp_sec
    if age_sec > max_frame_age_sec:
        return _rejected('frame_stale', sequence)
    if age_sec < -0.5:
        return _rejected('frame_from_future', sequence)
    targets = frame.get('targets')
    if not isinstance(targets, list):
        return _rejected('invalid_targets_schema', sequence)

    seen = set(str(value) for value in seen_observation_ids)
    duplicate_match = False
    current_observation_ids = set()
    candidates = []
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        observation_id = target.get('observation_id')
        if not isinstance(observation_id, str) or not observation_id:
            continue
        if observation_id in seen or observation_id in current_observation_ids:
            duplicate_match = True
            continue
        current_observation_ids.add(observation_id)
        if target.get('object_class') != requested_class:
            continue
        if target.get('valid') is not True:
            continue
        if target.get('error_code') not in ('', None):
            continue
        if requested_class == 'plastic_bottle':
            if (
                    target.get('actionable') is not True
                    or target.get('status') != 'active'):
                continue
        elif (
                target.get('actionable') is not False
                or target.get('status') != 'observed'):
            continue
        confidence = target.get('confidence')
        if not _finite_number(confidence) or not 0.0 <= confidence <= 1.0:
            continue
        if (
                not _valid_position(target)
                or not _valid_size(target)
                or not _valid_bbox(target)
                or not _valid_depth_quality(target)):
            continue
        candidates.append(target)

    if duplicate_match:
        return _rejected('duplicate_observation', sequence)
    if not candidates:
        return _rejected(
            'no_valid_target', sequence)
    selected = max(
        candidates,
        key=lambda target: (
            float(target['confidence']), str(target['observation_id'])),
    )
    return OrchestrationSelection(True, 'selected', selected, sequence)
