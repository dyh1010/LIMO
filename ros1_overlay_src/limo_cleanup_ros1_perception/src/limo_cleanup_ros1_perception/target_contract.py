"""Pure helpers for read-only 2D-to-3D perception target contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional, Sequence, Tuple

if TYPE_CHECKING:
    import numpy as np

from limo_cleanup_ros1_perception.perception_core import Detection2D


EXPECTED_MODEL_SHA256 = {
    'plastic_bottle': (
        'abe7eaf409e3d24d255a627823f4b107'
        'a8884008ab659901c6c50479b2153512'),
    'trash_bin': (
        '24beb4a7941ba5d783f1937128b5f0f4307b03513'
        '7889c78be1993cad76b8bc5'),
}


@dataclass(frozen=True)
class ProjectionConfig:
    """Configuration for robust median-depth projection of one 2D box."""

    depth_scale: float = 0.001
    min_depth: float = 0.30
    max_depth: float = 3.00
    min_valid_pixels: int = 5
    min_valid_ratio: float = 0.01
    roi_left: float = 0.30
    roi_top: float = 0.30
    roi_right: float = 0.70
    roi_bottom: float = 0.70


@dataclass(frozen=True)
class ProjectionResult:
    """Metric projection result, including quality when projection fails."""

    valid: bool
    error_code: str
    point: Optional[Tuple[float, float, float]]
    size: Optional[Tuple[float, float, float]]
    depth_m: Optional[float]
    valid_pixels: int
    total_pixels: int
    valid_ratio: float


def _invalid_projection(
        error_code: str, valid_pixels: int = 0, total_pixels: int = 0,
        valid_ratio: float = 0.0) -> ProjectionResult:
    return ProjectionResult(
        valid=False,
        error_code=error_code,
        point=None,
        size=None,
        depth_m=None,
        valid_pixels=valid_pixels,
        total_pixels=total_pixels,
        valid_ratio=valid_ratio,
    )


def _config_error(config: ProjectionConfig) -> Optional[str]:
    numeric = (
        config.depth_scale, config.min_depth, config.max_depth,
        config.min_valid_ratio, config.roi_left, config.roi_top,
        config.roi_right, config.roi_bottom,
    )
    if not all(math.isfinite(value) for value in numeric):
        return 'projection_config_not_finite'
    if config.depth_scale <= 0.0:
        return 'invalid_depth_scale'
    if config.min_depth < 0.0 or config.max_depth <= config.min_depth:
        return 'invalid_depth_range'
    if config.min_valid_pixels <= 0:
        return 'invalid_min_valid_pixels'
    if not 0.0 <= config.min_valid_ratio <= 1.0:
        return 'invalid_min_valid_ratio'
    if not (
            0.0 <= config.roi_left < config.roi_right <= 1.0
            and 0.0 <= config.roi_top < config.roi_bottom <= 1.0):
        return 'invalid_roi_fractions'
    return None


def project_detection(
        detection: Detection2D, depth_image: np.ndarray,
        camera_matrix: Sequence[float],
        config: ProjectionConfig,
        depth_encoding: str = '16UC1') -> ProjectionResult:
    """Project a clipped detection through aligned depth and RGB intrinsics."""
    import numpy as np

    config_error = _config_error(config)
    if config_error:
        return _invalid_projection(config_error)
    if not isinstance(depth_image, np.ndarray) or depth_image.ndim != 2:
        return _invalid_projection('invalid_depth_image')
    if depth_image.size == 0 or not np.issubdtype(
            depth_image.dtype, np.number):
        return _invalid_projection('invalid_depth_image')
    if len(camera_matrix) < 9:
        return _invalid_projection('invalid_camera_matrix')

    coordinates = (detection.x1, detection.y1, detection.x2, detection.y2)
    if not all(math.isfinite(value) for value in coordinates):
        return _invalid_projection('bbox_not_finite')
    if detection.width <= 0.0 or detection.height <= 0.0:
        return _invalid_projection('bbox_not_positive')

    height, width = depth_image.shape
    if detection.x2 <= 0.0 or detection.y2 <= 0.0:
        return _invalid_projection('bbox_outside_image')
    if detection.x1 >= width or detection.y1 >= height:
        return _invalid_projection('bbox_outside_image')

    x1 = max(0, min(width, int(math.floor(detection.x1))))
    y1 = max(0, min(height, int(math.floor(detection.y1))))
    x2 = max(0, min(width, int(math.ceil(detection.x2))))
    y2 = max(0, min(height, int(math.ceil(detection.y2))))
    if x2 <= x1 or y2 <= y1:
        return _invalid_projection('bbox_outside_image')

    box_width = x2 - x1
    box_height = y2 - y1
    roi_x1 = x1 + int(math.floor(box_width * config.roi_left))
    roi_y1 = y1 + int(math.floor(box_height * config.roi_top))
    roi_x2 = x1 + int(math.ceil(box_width * config.roi_right))
    roi_y2 = y1 + int(math.ceil(box_height * config.roi_bottom))
    roi_x1 = max(x1, min(x2 - 1, roi_x1))
    roi_y1 = max(y1, min(y2 - 1, roi_y1))
    roi_x2 = max(roi_x1 + 1, min(x2, roi_x2))
    roi_y2 = max(roi_y1 + 1, min(y2, roi_y2))
    roi = depth_image[roi_y1:roi_y2, roi_x1:roi_x2]
    total_pixels = int(roi.size)
    if total_pixels == 0:
        return _invalid_projection('empty_depth_roi')

    depth_values = roi.astype(np.float64)
    if depth_encoding in ('16UC1', 'mono16'):
        if not np.issubdtype(roi.dtype, np.integer):
            return _invalid_projection('depth_encoding_dtype_mismatch')
        depth_values *= config.depth_scale
    elif depth_encoding == '32FC1':
        if not np.issubdtype(roi.dtype, np.floating):
            return _invalid_projection('depth_encoding_dtype_mismatch')
    else:
        return _invalid_projection('unsupported_depth_encoding')
    valid_mask = (
        np.isfinite(depth_values)
        & (depth_values >= config.min_depth)
        & (depth_values <= config.max_depth)
    )
    valid = depth_values[valid_mask]
    valid_pixels = int(valid.size)
    valid_ratio = float(valid_pixels / total_pixels)
    if valid_pixels < config.min_valid_pixels:
        return _invalid_projection(
            'insufficient_depth_pixels', valid_pixels, total_pixels,
            valid_ratio)
    if valid_ratio < config.min_valid_ratio:
        return _invalid_projection(
            'insufficient_depth_ratio', valid_pixels, total_pixels,
            valid_ratio)

    fx, fy = float(camera_matrix[0]), float(camera_matrix[4])
    cx, cy = float(camera_matrix[2]), float(camera_matrix[5])
    if not all(math.isfinite(value) for value in (fx, fy, cx, cy)):
        return _invalid_projection(
            'camera_intrinsics_not_finite', valid_pixels, total_pixels,
            valid_ratio)
    if fx <= 0.0 or fy <= 0.0:
        return _invalid_projection(
            'camera_intrinsics_not_positive', valid_pixels, total_pixels,
            valid_ratio)

    z = float(np.median(valid))
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    depth_span = float(np.percentile(valid, 90) - np.percentile(valid, 10))
    point = (
        (center_x - cx) * z / fx,
        (center_y - cy) * z / fy,
        z,
    )
    size = (
        max(0.01, box_width * z / fx),
        max(0.01, box_height * z / fy),
        max(0.01, depth_span),
    )
    return ProjectionResult(
        valid=True,
        error_code='',
        point=point,
        size=size,
        depth_m=z,
        valid_pixels=valid_pixels,
        total_pixels=total_pixels,
        valid_ratio=valid_ratio,
    )


def normalized_model_labels(names) -> Tuple[str, ...]:
    """Normalize Ultralytics dict/list class names for fail-closed checks."""
    if isinstance(names, Mapping):
        values = names.values()
    elif isinstance(names, (list, tuple)):
        values = names
    else:
        raise ValueError('model class names must be a mapping or sequence')
    labels = tuple(str(value).strip() for value in values)
    if not labels or any(not value for value in labels):
        raise ValueError('model class names must be non-empty')
    return labels


def require_single_class_model(names, expected_label: str) -> None:
    """Reject a missing, wrong, or multi-class model before inference."""
    labels = normalized_model_labels(names)
    if labels != (expected_label,):
        raise ValueError(
            'expected single class {!r}; model classes are {!r}'.format(
                expected_label, labels))


def bundle_signature(*metadata) -> Tuple:
    """Create a deterministic signature so unchanged bad bundles deduplicate."""
    return tuple(
        (item.name, item.stamp_sec, item.frame_id, item.width, item.height)
        for item in metadata
    )
