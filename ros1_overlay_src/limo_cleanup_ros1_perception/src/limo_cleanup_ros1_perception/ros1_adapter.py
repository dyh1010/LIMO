"""ROS1 Noetic adapter for strictly read-only RGB-D perception output."""

import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Mapping, Sequence, Tuple

from limo_cleanup_ros1_perception.dual_model_detector import (
    DualModelInference,
    InferenceConfig,
)
from limo_cleanup_ros1_perception.image_conversion import (
    image_message_to_numpy,
)
from limo_cleanup_ros1_perception.perception_core import (
    classify_bottles_with_depth,
    select_target_bottle,
)
from limo_cleanup_ros1_perception.rgbd_contract import (
    StreamMetadata,
    validate_rgbd_contract,
)
from limo_cleanup_ros1_perception.target_contract import (
    ProjectionConfig,
    project_detection,
)


PERCEPTION_OUTPUT_TOPICS = (
    '/cleanup/perception/frames',
    '/cleanup/detection/raw',
    '/cleanup/perception_status',
)
TARGET_CLASSES = ('plastic_bottle', 'trash_bin')
_FRAME_ID = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_/-]*$')


def _finite(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _value(source, name, default=None):
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _valid_frame_id(frame_id) -> bool:
    return (
        isinstance(frame_id, str)
        and bool(frame_id)
        and frame_id == frame_id.strip()
        and not frame_id.startswith('/')
        and _FRAME_ID.fullmatch(frame_id) is not None
        and all(part not in ('', '.', '..') for part in frame_id.split('/'))
    )


def validate_observation_contract(
        frame_id, stamp_sec, object_class, confidence, projection,
        tf_metadata=None) -> Tuple[str, ...]:
    """Validate one camera-frame 3D observation without relabeling frames."""
    reasons = []
    if not _valid_frame_id(frame_id):
        reasons.append('frame_id_invalid')
    if not _finite(stamp_sec) or stamp_sec <= 0.0:
        reasons.append('stamp_invalid')
    if object_class not in TARGET_CLASSES:
        reasons.append('class_invalid')
    if not _finite(confidence) or not 0.0 <= confidence <= 1.0:
        reasons.append('confidence_invalid')

    valid = _value(projection, 'valid')
    point = _value(projection, 'point')
    size = _value(projection, 'size')
    depth_m = _value(projection, 'depth_m')
    valid_pixels = _value(projection, 'valid_pixels')
    total_pixels = _value(projection, 'total_pixels')
    valid_ratio = _value(projection, 'valid_ratio')
    if valid is not True:
        reasons.append('projection_invalid')
    if (
            not isinstance(point, (list, tuple))
            or len(point) != 3
            or not all(_finite(value) for value in point)
            or not isinstance(size, (list, tuple))
            or len(size) != 3
            or not all(_finite(value) and value >= 0.0 for value in size)):
        reasons.append('projection_invalid')
    if (
            not _finite(depth_m)
            or depth_m <= 0.0
            or not isinstance(valid_pixels, int)
            or isinstance(valid_pixels, bool)
            or not isinstance(total_pixels, int)
            or isinstance(total_pixels, bool)
            or not 0 < valid_pixels <= total_pixels
            or not _finite(valid_ratio)
            or not 0.0 < valid_ratio <= 1.0):
        reasons.append('depth_invalid')

    if not isinstance(tf_metadata, Mapping):
        reasons.append('tf_metadata_missing')
    else:
        expected_keys = {
            'source_frame', 'target_frame', 'stamp_sec',
            'transform_applied', 'chain_valid', 'mixed_tf'}
        if set(tf_metadata) != expected_keys:
            reasons.append('tf_metadata_missing')
        else:
            source_frame = tf_metadata.get('source_frame')
            target_frame = tf_metadata.get('target_frame')
            tf_stamp = tf_metadata.get('stamp_sec')
            transform_applied = tf_metadata.get('transform_applied')
            if tf_metadata.get('mixed_tf') is not False:
                reasons.append('mixed_tf_forbidden')
            if tf_metadata.get('chain_valid') is not True:
                reasons.append('tf_chain_invalid')
            if source_frame != frame_id or not _valid_frame_id(target_frame):
                reasons.append('tf_frame_mismatch')
            if (
                    not _finite(tf_stamp)
                    or not _finite(stamp_sec)
                    or abs(tf_stamp - stamp_sec) > 1e-6):
                reasons.append('tf_stamp_mismatch')
            if not isinstance(transform_applied, bool):
                reasons.append('tf_not_applied')
            elif target_frame != source_frame and not transform_applied:
                reasons.append('tf_not_applied')
    return tuple(sorted(set(reasons)))


def build_observation_id(
        stamp_sec, frame_id, object_class, bbox, status,
        model_binding_sha256) -> str:
    """Build a stable identifier bound to frame, box, status, and model set."""
    if (
            not _finite(stamp_sec)
            or not _valid_frame_id(frame_id)
            or object_class not in TARGET_CLASSES
            or not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or not all(_finite(value) for value in bbox)
            or not isinstance(status, str)
            or not status
            or not isinstance(model_binding_sha256, str)
            or len(model_binding_sha256) != 64):
        raise ValueError('observation identity inputs are invalid')
    identity = {
        'stamp_sec': round(float(stamp_sec), 9),
        'frame_id': frame_id,
        'object_class': object_class,
        'bbox': [round(float(value), 6) for value in bbox],
        'status': status,
        'model_binding_sha256': model_binding_sha256,
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL, hashlib.sha256(encoded).hexdigest()))


def _bundle_id(metadata: Sequence[StreamMetadata], model_hash: str) -> str:
    payload = {
        'streams': [
            {
                'name': item.name,
                'stamp_sec': round(item.stamp_sec, 9),
                'frame_id': item.frame_id,
                'width': item.width,
                'height': item.height,
                'encoding': item.encoding,
            }
            for item in metadata],
        'model_set_sha256': model_hash,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def stream_metadata(message, name: str) -> StreamMetadata:
    """Extract ROS1 header/grid metadata without importing message classes."""
    stamp = message.header.stamp
    if hasattr(stamp, 'to_sec'):
        stamp_sec = float(stamp.to_sec())
    else:
        stamp_sec = float(stamp.secs) + float(stamp.nsecs) / 1e9
    return StreamMetadata(
        name=name,
        stamp_sec=stamp_sec,
        frame_id=str(message.header.frame_id),
        width=int(message.width),
        height=int(message.height),
        encoding=str(getattr(message, 'encoding', '')),
    )


def _target_payload(
        detection, projection, stamp_sec, frame_id, status, actionable,
        model_set_hash):
    bbox = [detection.x1, detection.y1, detection.x2, detection.y2]
    camera_tf = {
        'source_frame': frame_id,
        'target_frame': frame_id,
        'stamp_sec': stamp_sec,
        'transform_applied': False,
        'chain_valid': True,
        'mixed_tf': False,
    }
    reasons = validate_observation_contract(
        frame_id, stamp_sec, detection.label, detection.confidence,
        projection, camera_tf)
    valid = not reasons
    point = projection.point if projection.point is not None else (0.0, 0.0, 0.0)
    size = projection.size if projection.size is not None else (0.0, 0.0, 0.0)
    return {
        'observation_id': build_observation_id(
            stamp_sec, frame_id, detection.label, bbox, status,
            model_set_hash),
        'object_class': detection.label,
        'confidence': detection.confidence,
        'valid': valid,
        'actionable': bool(actionable and valid),
        'status': status,
        'error_code': ';'.join(reasons) if reasons else projection.error_code,
        'position': tuple(float(value) for value in point),
        'size': tuple(float(value) for value in size),
        'bbox': tuple(float(value) for value in bbox),
        'depth_m': float(projection.depth_m or 0.0),
        'depth_valid_pixels': int(projection.valid_pixels),
        'depth_total_pixels': int(projection.total_pixels),
        'depth_valid_ratio': float(projection.valid_ratio),
        'source': detection.source,
        'position_semantics': (
            'camera_frame_aligned_depth_roi_median_at_clipped_bbox_center'),
    }


class PerceptionPipeline:
    """Pure synchronized-frame processor used by the ROS1 adapter and mocks."""

    def __init__(
            self, detector, projection_config=ProjectionConfig(),
            max_sync_delta_sec=0.15, in_bin_overlap=0.30,
            opening_margin_ratio=0.0, opening_height_ratio=0.62,
            max_bin_depth_difference_m=0.20, capture_id=''):
        self.detector = detector
        self.projection_config = projection_config
        self.max_sync_delta_sec = float(max_sync_delta_sec)
        self.in_bin_overlap = float(in_bin_overlap)
        self.opening_margin_ratio = float(opening_margin_ratio)
        self.opening_height_ratio = float(opening_height_ratio)
        self.max_bin_depth_difference_m = float(max_bin_depth_difference_m)
        self.capture_id = str(capture_id)
        self.sequence = 0

    def process(
            self, rgb_image, depth_image, camera_matrix,
            metadata: Sequence[StreamMetadata], task_id='',
            tf_status=None) -> Mapping:
        """Create one typed camera-frame result and optional legacy bottle."""
        started = time.perf_counter()
        if len(metadata) != 4:
            raise ValueError('exactly four RGB-D metadata records are required')
        rgb, depth, rgb_info, depth_info = metadata
        contract = validate_rgbd_contract(
            rgb, depth, rgb_info, depth_info, self.max_sync_delta_sec)
        self.sequence += 1
        bundle_id = _bundle_id(metadata, self.detector.model_set_sha256)
        base = {
            'stamp_sec': rgb.stamp_sec,
            'frame_id': rgb.frame_id,
            'task_id': str(task_id),
            'capture_id': self.capture_id,
            'bundle_id': bundle_id,
            'model_binding_sha256': self.detector.model_set_sha256,
            'sequence': self.sequence,
            'sync_span_sec': (
                contract.timestamp_span_sec
                if contract.timestamp_span_sec is not None else -1.0),
            'tf_target_frame': str((tf_status or {}).get(
                'target_frame', rgb.frame_id)),
            'tf_valid': (tf_status or {}).get('valid') is True,
            'tf_transform_applied': (
                (tf_status or {}).get('transform_applied') is True),
            'tf_status': str((tf_status or {}).get(
                'status', 'camera_frame_only')),
            'tf_error_code': str((tf_status or {}).get('error_code', '')),
        }
        if not contract.accepted:
            return {
                **base,
                'valid': False,
                'status': 'rgbd_contract_rejected',
                'error_code': ';'.join(contract.reasons),
                'processing_latency_sec': time.perf_counter() - started,
                'targets': [],
                'legacy_bottle': None,
            }

        bottles, bins = self.detector.infer(rgb_image)
        bottle_projections = {
            item: project_detection(
                item, depth_image, camera_matrix, self.projection_config,
                depth.encoding)
            for item in bottles}
        bin_projections = {
            item: project_detection(
                item, depth_image, camera_matrix, self.projection_config,
                depth.encoding)
            for item in bins}
        classified = classify_bottles_with_depth(
            bottles,
            bins,
            {item: result.depth_m if result.valid else None
             for item, result in bottle_projections.items()},
            {item: result.depth_m if result.valid else None
             for item, result in bin_projections.items()},
            overlap_threshold=self.in_bin_overlap,
            horizontal_margin_ratio=self.opening_margin_ratio,
            opening_height_ratio=self.opening_height_ratio,
            max_depth_difference_m=self.max_bin_depth_difference_m,
        )
        targets = []
        payload_by_detection = {}
        for item in classified.active:
            payload = _target_payload(
                item, bottle_projections[item], rgb.stamp_sec, rgb.frame_id,
                'active', True, self.detector.model_set_sha256)
            targets.append(payload)
            payload_by_detection[item] = payload
        for item in classified.already_in_bin:
            targets.append(_target_payload(
                item, bottle_projections[item], rgb.stamp_sec, rgb.frame_id,
                'already_in_bin', False, self.detector.model_set_sha256))
        for item in bins:
            targets.append(_target_payload(
                item, bin_projections[item], rgb.stamp_sec, rgb.frame_id,
                'observed', False, self.detector.model_set_sha256))
        valid_count = sum(item['valid'] for item in targets)
        if targets and valid_count == 0:
            status = 'targets_invalid'
            error_code = 'all_target_projections_invalid'
            frame_valid = False
        else:
            status = 'targets_ready' if targets else 'no_targets'
            error_code = ''
            frame_valid = True
        selected = select_target_bottle(classified.active)
        legacy = payload_by_detection.get(selected)
        if legacy is not None and not legacy['valid']:
            legacy = None
        return {
            **base,
            'valid': frame_valid,
            'status': status,
            'error_code': error_code,
            'processing_latency_sec': time.perf_counter() - started,
            'targets': targets,
            'legacy_bottle': legacy,
        }


def _find_installed_config(filename: str) -> Path:
    module = Path(__file__).resolve()
    candidates = [module.parents[2] / 'config' / filename]
    candidates.extend(
        parent / 'share' / 'limo_cleanup_ros1_perception' / 'config' /
        filename for parent in module.parents)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError('installed config is unavailable: ' + filename)


class Ros1PerceptionAdapter:
    """Own the ROS1 sensor subscriptions and perception-only publishers."""

    def __init__(self):
        import message_filters
        import rospy
        import tf2_ros
        from limo_cleanup_ros1_perception.msg import (
            ObjectDetection,
            PerceptionFrame,
            PerceptionTarget,
        )
        from sensor_msgs.msg import CameraInfo, Image
        from std_msgs.msg import String

        formal_capture_mode = rospy.get_param('~formal_capture_mode', False)
        if not isinstance(formal_capture_mode, bool):
            raise RuntimeError('formal_capture_mode_invalid')
        task_id = str(rospy.get_param('~task_id', '')).strip()
        capture_id = str(rospy.get_param(
            '~capture_id', 'runtime-readonly')).strip()
        if formal_capture_mode and not task_id:
            raise RuntimeError('formal_capture_task_id_invalid')
        if formal_capture_mode and not capture_id:
            raise RuntimeError('formal_capture_capture_id_invalid')

        self.rospy = rospy
        self.PerceptionFrame = PerceptionFrame
        self.PerceptionTarget = PerceptionTarget
        self.ObjectDetection = ObjectDetection
        self.String = String
        self.formal_capture_mode = formal_capture_mode
        self.task_id = task_id
        manifest = Path(rospy.get_param(
            '~model_manifest', str(_find_installed_config(
                'model_bindings.json'))))
        model_root_value = str(rospy.get_param('~model_root', '')).strip()
        detector = DualModelInference(
            manifest,
            model_root=Path(model_root_value) if model_root_value else None,
            config=InferenceConfig(
                confidence=float(rospy.get_param('~confidence', 0.35)),
                iou=float(rospy.get_param('~iou', 0.45)),
                image_size=int(rospy.get_param('~image_size', 640)),
                device=str(rospy.get_param('~device', '')),
            ),
        )
        self.base_frame = str(rospy.get_param('~tf_target_frame', 'base_link'))
        self.pipeline = PerceptionPipeline(
            detector,
            projection_config=ProjectionConfig(
                depth_scale=float(rospy.get_param('~depth_scale', 0.001)),
                min_depth=float(rospy.get_param('~min_depth', 0.30)),
                max_depth=float(rospy.get_param('~max_depth', 3.00)),
                min_valid_pixels=int(rospy.get_param(
                    '~min_valid_depth_pixels', 5)),
                min_valid_ratio=float(rospy.get_param(
                    '~min_valid_depth_ratio', 0.01)),
            ),
            max_sync_delta_sec=float(rospy.get_param(
                '~max_sync_delta_sec', 0.15)),
            in_bin_overlap=float(rospy.get_param('~in_bin_overlap', 0.30)),
            opening_margin_ratio=float(rospy.get_param(
                '~opening_margin_ratio', 0.0)),
            opening_height_ratio=float(rospy.get_param(
                '~opening_height_ratio', 0.62)),
            max_bin_depth_difference_m=float(rospy.get_param(
                '~max_bin_depth_difference_m', 0.20)),
            capture_id=capture_id,
        )
        self.frame_publisher = rospy.Publisher(
            PERCEPTION_OUTPUT_TOPICS[0], PerceptionFrame,
            queue_size=10, latch=False)
        self.legacy_publisher = rospy.Publisher(
            PERCEPTION_OUTPUT_TOPICS[1], ObjectDetection,
            queue_size=10, latch=False)
        self.status_publisher = rospy.Publisher(
            PERCEPTION_OUTPUT_TOPICS[2], String,
            queue_size=10, latch=False)
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        queue_size = int(rospy.get_param('~sync_queue_size', 10))
        slop = float(rospy.get_param('~max_sync_delta_sec', 0.15))
        subscribers = [
            message_filters.Subscriber(str(rospy.get_param(
                '~rgb_topic', '/camera/color/image_raw')), Image),
            message_filters.Subscriber(str(rospy.get_param(
                '~depth_topic', '/camera/depth/image_raw')), Image),
            message_filters.Subscriber(str(rospy.get_param(
                '~rgb_camera_info_topic',
                '/camera/color/camera_info')), CameraInfo),
            message_filters.Subscriber(str(rospy.get_param(
                '~depth_camera_info_topic',
                '/camera/depth/camera_info')), CameraInfo),
        ]
        self.synchronizer = message_filters.ApproximateTimeSynchronizer(
            subscribers, queue_size=queue_size, slop=slop,
            allow_headerless=False)
        self.synchronizer.registerCallback(self._callback)

    def _tf_status(self, frame_id, stamp):
        if not self.base_frame or self.base_frame == frame_id:
            return {
                'target_frame': frame_id,
                'valid': True,
                'transform_applied': False,
                'status': 'camera_frame_output',
                'error_code': '',
            }
        try:
            self.tf_buffer.lookup_transform(
                self.base_frame, frame_id, stamp,
                self.rospy.Duration(0.0))
        except Exception as error:
            return {
                'target_frame': self.base_frame,
                'valid': False,
                'transform_applied': False,
                'status': 'tf_unavailable_camera_frame_retained',
                'error_code': type(error).__name__,
            }
        return {
            'target_frame': self.base_frame,
            'valid': False,
            'transform_applied': False,
            'status': 'tf_chain_available_not_applied_camera_frame_output',
            'error_code': 'transform_not_applied',
        }

    def _callback(self, rgb_message, depth_message, rgb_info, depth_info):
        try:
            metadata = (
                stream_metadata(rgb_message, 'rgb'),
                stream_metadata(depth_message, 'depth'),
                stream_metadata(rgb_info, 'rgb_info'),
                stream_metadata(depth_info, 'depth_info'),
            )
            result = self.pipeline.process(
                image_message_to_numpy(rgb_message, color=True),
                image_message_to_numpy(depth_message, color=False),
                tuple(float(value) for value in rgb_info.K),
                metadata,
                task_id=self.task_id,
                tf_status=self._tf_status(
                    rgb_message.header.frame_id, rgb_message.header.stamp),
            )
            self._publish(result, rgb_message.header.stamp)
        except Exception as error:
            payload = {
                'state': 'processing_error',
                'error_code': type(error).__name__,
                'read_only': True,
            }
            self.status_publisher.publish(self.String(
                data=json.dumps(payload, sort_keys=True)))

    def _target_message(self, payload):
        message = self.PerceptionTarget()
        message.observation_id = payload['observation_id']
        message.object_class = payload['object_class']
        message.confidence = payload['confidence']
        message.valid = payload['valid']
        message.actionable = payload['actionable']
        message.status = payload['status']
        message.error_code = payload['error_code']
        message.position.x, message.position.y, message.position.z = (
            payload['position'])
        message.size.x, message.size.y, message.size.z = payload['size']
        (message.bbox_x1, message.bbox_y1,
         message.bbox_x2, message.bbox_y2) = payload['bbox']
        message.depth_m = payload['depth_m']
        message.depth_valid_pixels = payload['depth_valid_pixels']
        message.depth_total_pixels = payload['depth_total_pixels']
        message.depth_valid_ratio = payload['depth_valid_ratio']
        message.source = payload['source']
        message.position_semantics = payload['position_semantics']
        return message

    def _publish(self, payload, stamp):
        frame = self.PerceptionFrame()
        frame.stamp = stamp
        frame.frame_id = payload['frame_id']
        frame.task_id = payload['task_id']
        frame.capture_id = payload['capture_id']
        frame.bundle_id = payload['bundle_id']
        frame.model_binding_sha256 = payload['model_binding_sha256']
        frame.sequence = payload['sequence']
        frame.valid = payload['valid']
        frame.status = payload['status']
        frame.error_code = payload['error_code']
        frame.sync_span_sec = payload['sync_span_sec']
        frame.processing_latency_sec = payload['processing_latency_sec']
        frame.tf_target_frame = payload['tf_target_frame']
        frame.tf_valid = payload['tf_valid']
        frame.tf_transform_applied = payload['tf_transform_applied']
        frame.tf_status = payload['tf_status']
        frame.tf_error_code = payload['tf_error_code']
        frame.targets = [
            self._target_message(item) for item in payload['targets']]
        self.frame_publisher.publish(frame)
        legacy = payload['legacy_bottle']
        if legacy is not None:
            message = self.ObjectDetection()
            message.stamp = stamp
            message.detection_id = legacy['observation_id']
            message.task_id = payload['task_id']
            message.object_class = legacy['object_class']
            message.confidence = legacy['confidence']
            message.frame_id = payload['frame_id']
            message.position.x, message.position.y, message.position.z = (
                legacy['position'])
            message.size.x, message.size.y, message.size.z = legacy['size']
            self.legacy_publisher.publish(message)
        self.status_publisher.publish(self.String(data=json.dumps({
            'state': payload['status'],
            'sequence': payload['sequence'],
            'bundle_id': payload['bundle_id'],
            'target_count': len(payload['targets']),
            'read_only': True,
        }, sort_keys=True)))


def main(args=None):
    """Run only the ROS1 sensor adapter; it never starts a camera driver."""
    del args
    import rospy
    rospy.init_node('limo_cleanup_readonly_perception', anonymous=False)
    Ros1PerceptionAdapter()
    rospy.spin()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
