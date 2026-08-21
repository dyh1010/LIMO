"""Fail-closed runtime contract for aligned RGB-D sensor bundles."""

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class StreamMetadata:
    """Timestamp, frame, and pixel-grid metadata for one sensor stream."""

    name: str
    stamp_sec: float
    frame_id: str
    width: int
    height: int
    encoding: str = ''


@dataclass(frozen=True)
class RgbdContractResult:
    """Normalized result of validating one aligned RGB-D bundle."""

    accepted: bool
    reasons: Tuple[str, ...]
    timestamp_span_sec: Optional[float]


def nearest_by_stamp(reference_stamp: float, candidates: Sequence):
    """Return the candidate with metadata stamp nearest to a reference."""
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: abs(item[0].stamp_sec - reference_stamp),
    )

def validate_rgbd_contract(
        rgb: StreamMetadata, depth: StreamMetadata,
        rgb_info: StreamMetadata, depth_info: StreamMetadata,
        max_sync_delta_sec: float) -> RgbdContractResult:
    """Validate timestamp, frame, and resolution for four aligned streams."""
    streams = (rgb, depth, rgb_info, depth_info)
    reasons = []

    if not math.isfinite(max_sync_delta_sec) or max_sync_delta_sec < 0.0:
        reasons.append('invalid_max_sync_delta')

    invalid_stamps = [
        item.name for item in streams
        if not math.isfinite(item.stamp_sec) or item.stamp_sec <= 0.0]
    if invalid_stamps:
        reasons.append('invalid_stamp:' + ','.join(invalid_stamps))
        timestamp_span = None
    else:
        stamps = [item.stamp_sec for item in streams]
        timestamp_span = max(stamps) - min(stamps)
        if (
                math.isfinite(max_sync_delta_sec)
                and max_sync_delta_sec >= 0.0
                and timestamp_span > max_sync_delta_sec):
            reasons.append('timestamp_span_exceeded')

    invalid_frames = [item.name for item in streams if not item.frame_id]
    if invalid_frames:
        reasons.append('empty_frame:' + ','.join(invalid_frames))
    elif any(item.frame_id != rgb.frame_id for item in streams[1:]):
        reasons.append('frame_mismatch')

    invalid_sizes = [
        item.name for item in streams
        if item.width <= 0 or item.height <= 0]
    if invalid_sizes:
        reasons.append('invalid_resolution:' + ','.join(invalid_sizes))
    elif any(
            (item.width, item.height) != (rgb.width, rgb.height)
            for item in streams[1:]):
        reasons.append('resolution_mismatch')

    if depth.encoding not in ('16UC1', 'mono16', '32FC1'):
        reasons.append('invalid_depth_encoding')

    return RgbdContractResult(
        accepted=not reasons,
        reasons=tuple(reasons),
        timestamp_span_sec=timestamp_span,
    )
