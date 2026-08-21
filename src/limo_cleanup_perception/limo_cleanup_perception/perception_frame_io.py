"""Pure JSON serialization helpers for typed read-only perception frames."""

import math
from typing import Mapping


def stamp_to_dict(stamp) -> Mapping[str, int]:
    """Serialize ROS1 ``time`` or ROS2 builtin time without ROS imports."""
    nanosec = getattr(stamp, 'nanosec', None)
    if nanosec is None:
        nanosec = getattr(stamp, 'nsecs', None)
    sec = getattr(stamp, 'sec', None)
    if sec is None:
        sec = getattr(stamp, 'secs', None)
    if sec is None or nanosec is None:
        raise ValueError('stamp does not expose ROS1 or ROS2 time fields')
    return {
        'sec': int(sec),
        'nanosec': int(nanosec),
    }


def point_to_dict(point) -> Mapping[str, float]:
    """Serialize a ROS-like point/vector to finite JSON numbers."""
    values = (float(point.x), float(point.y), float(point.z))
    if not all(math.isfinite(value) for value in values):
        raise ValueError('target geometry contains non-finite values')
    return dict(zip(('x', 'y', 'z'), values))


def target_to_dict(target) -> Mapping:
    """Serialize the complete PerceptionTarget navigation contract."""
    confidence = float(target.confidence)
    depth_m = float(target.depth_m)
    depth_valid_ratio = float(target.depth_valid_ratio)
    bbox = [
        float(target.bbox_x1), float(target.bbox_y1),
        float(target.bbox_x2), float(target.bbox_y2),
    ]
    numeric = [confidence, depth_m, depth_valid_ratio] + bbox
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError('target quality contains non-finite values')
    return {
        'observation_id': str(target.observation_id),
        'object_class': str(target.object_class),
        'confidence': confidence,
        'valid': bool(target.valid),
        'actionable': bool(target.actionable),
        'status': str(target.status),
        'error_code': str(target.error_code),
        'position': point_to_dict(target.position),
        'size': point_to_dict(target.size),
        'bbox': bbox,
        'depth_m': depth_m,
        'depth_valid_pixels': int(target.depth_valid_pixels),
        'depth_total_pixels': int(target.depth_total_pixels),
        'depth_valid_ratio': depth_valid_ratio,
        'source': str(target.source),
        'position_semantics': str(target.position_semantics),
    }


def frame_to_dict(message, received_unix_sec: float) -> Mapping:
    """Serialize a complete PerceptionFrame plus subscriber receipt time."""
    received = float(received_unix_sec)
    sync_span = float(message.sync_span_sec)
    processing_latency = float(message.processing_latency_sec)
    if not all(math.isfinite(value) for value in (
            received, sync_span, processing_latency)):
        raise ValueError('frame timing contains non-finite values')
    stamp = stamp_to_dict(message.stamp)
    sensor_stamp_sec = stamp['sec'] + stamp['nanosec'] / 1e9
    transport_latency = (
        received - sensor_stamp_sec if sensor_stamp_sec > 0.0 else None)
    return {
        'schema_version': 1,
        'read_only': True,
        'received_unix_sec': received,
        'transport_latency_sec': transport_latency,
        'stamp': stamp,
        'frame_id': str(message.frame_id),
        'task_id': str(message.task_id),
        'capture_id': str(getattr(message, 'capture_id', '')),
        'bundle_id': str(getattr(message, 'bundle_id', '')),
        'model_binding_sha256': str(getattr(
            message, 'model_binding_sha256', '')),
        'sequence': int(message.sequence),
        'valid': bool(message.valid),
        'status': str(message.status),
        'error_code': str(message.error_code),
        'sync_span_sec': sync_span,
        'processing_latency_sec': processing_latency,
        'tf_target_frame': str(getattr(message, 'tf_target_frame', '')),
        'tf_valid': bool(getattr(message, 'tf_valid', False)),
        'tf_transform_applied': bool(getattr(
            message, 'tf_transform_applied', False)),
        'tf_status': str(getattr(message, 'tf_status', '')),
        'tf_error_code': str(getattr(message, 'tf_error_code', '')),
        'targets': [target_to_dict(target) for target in message.targets],
    }
