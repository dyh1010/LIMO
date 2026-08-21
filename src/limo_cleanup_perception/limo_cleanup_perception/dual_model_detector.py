"""ROS 2 RGB-D detector for actionable bottles outside trash bins."""

import hashlib
import json
import threading
import time
import uuid
from collections import deque

import rclpy
from limo_cleanup_interfaces.msg import (
    CleanupTask,
    ObjectDetection,
    PerceptionFrame,
    PerceptionTarget,
)
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from ultralytics import YOLO

from limo_cleanup_perception.image_conversion import (
    image_message_to_numpy,
)
from limo_cleanup_perception.perception_core import (
    Detection2D,
    classify_bottles_with_depth,
    select_target_bin,
    select_target_bottle,
)
from limo_cleanup_perception.rgbd_contract import (
    StreamMetadata,
    nearest_by_stamp,
    validate_rgbd_contract,
)
from limo_cleanup_perception.task_actions import (
    accepts_perception_task,
)
from limo_cleanup_perception.target_contract import (
    EXPECTED_MODEL_SHA256,
    ProjectionConfig,
    bundle_signature,
    project_detection,
    require_single_class_model,
)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class DualModelDetector(Node):
    """Publish read-only bottle/bin frames and legacy actionable bottles."""

    def __init__(self) -> None:
        super().__init__('cleanup_dual_model_detector')
        self.declare_parameters('', [
            ('bottle_model_path', ''),
            ('bin_model_path', ''),
            ('rgb_topic', '/camera/color/image_raw'),
            ('depth_topic', '/camera/depth/image_raw'),
            ('camera_info_topic', '/camera/color/camera_info'),
            ('depth_camera_info_topic', '/camera/depth/camera_info'),
            ('confidence', 0.5),
            ('iou', 0.45),
            ('imgsz', 640),
            ('device', '0'),
            ('process_period', 0.20),
            ('publish_period', 0.50),
            ('max_sync_delta_sec', 0.15),
            ('sync_queue_size', 30),
            ('depth_scale', 0.001),
            ('min_depth', 0.30),
            ('max_depth', 3.00),
            ('min_target_depth_pixels', 5),
            ('min_target_depth_ratio', 0.02),
            ('in_bin_overlap', 0.30),
            ('opening_height_ratio', 0.62),
            ('opening_margin_ratio', 0.0),
            ('frame_id_override', ''),
            ('always_active', False),
        ])
        bottle_model_path = self.parameter_string('bottle_model_path')
        bin_model_path = self.parameter_string('bin_model_path')
        if not bottle_model_path or not bin_model_path:
            raise RuntimeError(
                'bottle_model_path and bin_model_path are required')
        for label, path in (
                ('plastic_bottle', bottle_model_path),
                ('trash_bin', bin_model_path)):
            if _sha256_file(path) != EXPECTED_MODEL_SHA256[label]:
                raise RuntimeError(label + ' model SHA-256 mismatch')

        self.confidence = self.parameter_double('confidence')
        self.iou = self.parameter_double('iou')
        self.imgsz = self.parameter_integer('imgsz')
        self.device = self.parameter_string('device')
        self.depth_scale = self.parameter_double('depth_scale')
        self.min_depth = self.parameter_double('min_depth')
        self.max_depth = self.parameter_double('max_depth')
        self.in_bin_overlap = self.parameter_double('in_bin_overlap')
        self.opening_height_ratio = self.parameter_double(
            'opening_height_ratio')
        self.opening_margin_ratio = self.parameter_double(
            'opening_margin_ratio')
        self.frame_id_override = self.parameter_string('frame_id_override')
        if self.frame_id_override:
            raise RuntimeError(
                'frame_id_override cannot relabel untransformed coordinates; '
                'leave it empty and transform downstream with TF')
        self.publish_period = self.parameter_double('publish_period')
        self.max_sync_delta_sec = self.parameter_double(
            'max_sync_delta_sec')
        self.always_active = self.parameter_bool('always_active')

        self.get_logger().info('Loading bottle and trash-bin models')
        self.bottle_model = YOLO(bottle_model_path)
        self.bin_model = YOLO(bin_model_path)
        try:
            require_single_class_model(
                self.bottle_model.names, 'plastic_bottle')
            require_single_class_model(self.bin_model.names, 'trash_bin')
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        self.projection_config = ProjectionConfig(
            depth_scale=self.depth_scale,
            min_depth=self.min_depth,
            max_depth=self.max_depth,
            min_valid_pixels=self.parameter_integer(
                'min_target_depth_pixels'),
            min_valid_ratio=self.parameter_double(
                'min_target_depth_ratio'),
        )
        self.data_lock = threading.Lock()
        queue_size = self.parameter_integer('sync_queue_size')
        if queue_size <= 0:
            raise RuntimeError('sync_queue_size must be positive')
        self.rgb_candidates = deque(maxlen=queue_size)
        self.depth_candidates = deque(maxlen=queue_size)
        self.camera_info_candidates = deque(maxlen=queue_size)
        self.depth_camera_info_candidates = deque(maxlen=queue_size)
        self.active_task = (
            'read-only-perception' if self.always_active else None)
        self.last_bundle_signature = None
        self.last_publish_time = 0.0
        self.frame_sequence = 0

        rgb_topic = self.parameter_string('rgb_topic')
        depth_topic = self.parameter_string('depth_topic')
        camera_info_topic = self.parameter_string('camera_info_topic')
        depth_camera_info_topic = self.parameter_string(
            'depth_camera_info_topic')
        self.create_subscription(
            Image, rgb_topic, self.rgb_callback, qos_profile_sensor_data)
        self.create_subscription(
            Image, depth_topic, self.depth_callback, qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, camera_info_topic, self.camera_info_callback,
            qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, depth_camera_info_topic,
            self.depth_camera_info_callback, qos_profile_sensor_data)
        self.create_subscription(
            CleanupTask, '/cleanup/task', self.task_callback, 10)
        self.detection_publisher = self.create_publisher(
            ObjectDetection, '/cleanup/detection/raw', 10)
        self.frame_publisher = self.create_publisher(
            PerceptionFrame, '/cleanup/perception/frames', 10)
        self.status_publisher = self.create_publisher(
            String, '/cleanup/perception_status', 10)
        self.create_timer(
            self.parameter_double('process_period'), self.process_latest_frame)
        self.get_logger().info(
            f'Dual-model detector ready; rgb={rgb_topic}; '
            f'depth={depth_topic}; '
            f'camera_info={camera_info_topic}; '
            f'depth_camera_info={depth_camera_info_topic}; '
            f'always_active={self.always_active}')

    def parameter_string(self, name):
        return self.get_parameter(name).get_parameter_value().string_value

    def parameter_double(self, name):
        return float(
            self.get_parameter(name).get_parameter_value().double_value)

    def parameter_integer(self, name):
        return int(
            self.get_parameter(name).get_parameter_value().integer_value)

    def parameter_bool(self, name):
        return self.get_parameter(name).get_parameter_value().bool_value

    def rgb_callback(self, message):
        try:
            image = image_message_to_numpy(message, color=True)
        except ValueError as error:
            self.get_logger().warning(str(error))
            return
        with self.data_lock:
            self.rgb_candidates.append((
                self.stream_metadata('rgb', message), image, message.header))

    def depth_callback(self, message):
        try:
            depth = image_message_to_numpy(message)
        except ValueError as error:
            self.get_logger().warning(str(error))
            return
        with self.data_lock:
            self.depth_candidates.append((
                self.stream_metadata('depth', message), depth,
                str(message.encoding)))

    def camera_info_callback(self, message):
        with self.data_lock:
            self.camera_info_candidates.append((
                self.stream_metadata('rgb_info', message), message))

    def depth_camera_info_callback(self, message):
        with self.data_lock:
            self.depth_camera_info_candidates.append((
                self.stream_metadata('depth_info', message), message))

    @staticmethod
    def stamp_seconds(stamp):
        """Convert a ROS time message to floating-point seconds."""
        return float(stamp.sec) + float(stamp.nanosec) / 1e9

    @classmethod
    def stream_metadata(cls, name, message):
        """Extract contract metadata from Image or CameraInfo."""
        return StreamMetadata(
            name=name,
            stamp_sec=cls.stamp_seconds(message.header.stamp),
            frame_id=message.header.frame_id,
            width=int(message.width),
            height=int(message.height),
            encoding=str(getattr(message, 'encoding', '')),
        )

    def task_callback(self, message):
        if self.always_active:
            return
        if message.action == 'cancel':
            if self.active_task == message.task_id:
                self.active_task = None
            return
        if (
                accepts_perception_task(message.action)
                and message.object_class in ('plastic_bottle', 'trash_bin')
                and message.task_id):
            self.active_task = message.task_id
            self.get_logger().info(
                f'Activated perception for task {message.task_id}')

    def process_latest_frame(self):
        if self.active_task is None:
            return
        processing_started = time.perf_counter()
        with self.data_lock:
            queues = (
                self.rgb_candidates,
                self.depth_candidates,
                self.camera_info_candidates,
                self.depth_camera_info_candidates,
            )
            if not all(queues):
                self.publish_status(
                    'waiting_for_rgb_depth_camera_info_bundle')
                return
            rgb_metadata, rgb_source, header = self.rgb_candidates[-1]
            reference_stamp = rgb_metadata.stamp_sec
            depth_item = nearest_by_stamp(
                reference_stamp, self.depth_candidates)
            rgb_info_item = nearest_by_stamp(
                reference_stamp, self.camera_info_candidates)
            depth_info_item = nearest_by_stamp(
                reference_stamp, self.depth_camera_info_candidates)
            signature = bundle_signature(
                rgb_metadata, depth_item[0], rgb_info_item[0],
                depth_info_item[0])
            if signature == self.last_bundle_signature:
                return
            self.last_bundle_signature = signature
            contract = validate_rgbd_contract(
                rgb_metadata, depth_item[0], rgb_info_item[0],
                depth_info_item[0], self.max_sync_delta_sec)
            if not contract.accepted:
                self.publish_status(
                    'rgbd_contract_rejected',
                    reasons=list(contract.reasons),
                    timestamp_span_sec=contract.timestamp_span_sec,
                    max_sync_delta_sec=self.max_sync_delta_sec,
                )
                self.publish_perception_frame(
                    header=header,
                    frame_id=rgb_metadata.frame_id,
                    status='rgbd_contract_rejected',
                    error_code=';'.join(contract.reasons),
                    sync_span_sec=contract.timestamp_span_sec,
                    targets=[],
                    processing_latency_sec=(
                        time.perf_counter() - processing_started),
                )
                return
            rgb = rgb_source.copy()
            depth = depth_item[1].copy()
            depth_encoding = depth_item[2]
            camera_info = rgb_info_item[1]

        bottle_result = self.bottle_model.predict(
            source=rgb, conf=self.confidence, iou=self.iou,
            imgsz=self.imgsz, device=self.device, verbose=False)[0]
        bin_result = self.bin_model.predict(
            source=rgb, conf=self.confidence, iou=self.iou,
            imgsz=self.imgsz, device=self.device, verbose=False)[0]
        bottles = self.to_detections(
            bottle_result, 'plastic_bottle', 'bottle_model')
        bins = self.to_detections(bin_result, 'trash_bin', 'bin_model')
        bottle_projections = {
            bottle: project_detection(
                bottle, depth, camera_info.k, self.projection_config,
                depth_encoding)
            for bottle in bottles}
        bin_projections = {
            trash_bin: project_detection(
                trash_bin, depth, camera_info.k, self.projection_config,
                depth_encoding)
            for trash_bin in bins}
        classified = classify_bottles_with_depth(
            bottles, bins,
            {item: value.depth_m if value.valid else None
             for item, value in bottle_projections.items()},
            {item: value.depth_m if value.valid else None
             for item, value in bin_projections.items()},
            overlap_threshold=self.in_bin_overlap,
            horizontal_margin_ratio=self.opening_margin_ratio,
            opening_height_ratio=self.opening_height_ratio,
        )
        target_bottle = select_target_bottle(classified.active)
        target_bin = select_target_bin(bins)
        frame_targets = []
        for bottle in classified.active:
            projection = bottle_projections[bottle]
            frame_targets.append(self.build_target(
                bottle, projection, header,
                actionable=True, status='active'))
        for bottle in classified.already_in_bin:
            projection = bottle_projections[bottle]
            frame_targets.append(self.build_target(
                bottle, projection, header,
                actionable=False, status='already_in_bin'))
        for trash_bin in bins:
            projection = bin_projections[trash_bin]
            frame_targets.append(self.build_target(
                trash_bin, projection, header,
                actionable=False, status='observed'))

        valid_targets = sum(item.valid for item in frame_targets)
        invalid_targets = len(frame_targets) - valid_targets
        if frame_targets and valid_targets == 0:
            frame_status = 'targets_invalid'
            frame_error_code = 'all_target_projections_invalid'
        else:
            frame_status = 'targets_ready' if frame_targets else 'no_targets'
            frame_error_code = ''
        processing_latency = time.perf_counter() - processing_started
        self.publish_perception_frame(
            header=header,
            frame_id=rgb_metadata.frame_id,
            status=frame_status,
            error_code=frame_error_code,
            sync_span_sec=contract.timestamp_span_sec,
            targets=frame_targets,
            processing_latency_sec=processing_latency,
        )
        self.publish_status(
            'target_ready' if target_bottle is not None else 'searching_bottle',
            bottles_total=len(bottles),
            bottles_active=len(classified.active),
            bottles_already_in_bin=len(classified.already_in_bin),
            bins=len(bins),
            target_bin_ready=target_bin is not None,
            targets_valid=valid_targets,
            targets_invalid=invalid_targets,
            sync_span_sec=contract.timestamp_span_sec,
            processing_latency_sec=processing_latency,
        )
        if target_bottle is None:
            return
        now_seconds = self.get_clock().now().nanoseconds / 1e9
        if now_seconds - self.last_publish_time < self.publish_period:
            return
        projection = bottle_projections[target_bottle]
        if not projection.valid:
            self.publish_status(
                'target_has_no_valid_depth',
                error_code=projection.error_code,
                depth_valid_pixels=projection.valid_pixels,
                depth_total_pixels=projection.total_pixels,
                depth_valid_ratio=projection.valid_ratio,
            )
            return
        observation_id = self.observation_id(
            header, target_bottle, 'active')
        self.publish_detection(
            target_bottle, projection.point, projection.size,
            header, observation_id)
        self.last_publish_time = now_seconds

    @staticmethod
    def to_detections(result, label, source):
        if result.boxes is None:
            return []
        coordinates = result.boxes.xyxy.detach().cpu().tolist()
        confidences = result.boxes.conf.detach().cpu().tolist()
        return [
            Detection2D(
                label, float(confidence),
                float(box[0]), float(box[1]), float(box[2]), float(box[3]),
                source,
            )
            for box, confidence in zip(coordinates, confidences)
        ]

    @staticmethod
    def observation_id(header, detection, suffix):
        """Build a stable ID for one detection within one sensor frame."""
        key = (
            f'{header.stamp.sec}:{header.stamp.nanosec}:'
            f'{detection.label}:{detection.x1:.3f}:{detection.y1:.3f}:'
            f'{detection.x2:.3f}:{detection.y2:.3f}:{suffix}')
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

    def build_target(
            self, detection, projection, header, actionable, status):
        """Convert one 2D detection and projection into a typed target."""
        message = PerceptionTarget()
        message.observation_id = self.observation_id(
            header, detection, status)
        message.object_class = detection.label
        message.confidence = detection.confidence
        message.valid = projection.valid
        message.actionable = bool(actionable and projection.valid)
        message.status = status
        message.error_code = projection.error_code
        if projection.point is not None:
            (message.position.x, message.position.y,
             message.position.z) = projection.point
        if projection.size is not None:
            message.size.x, message.size.y, message.size.z = projection.size
        message.bbox_x1 = detection.x1
        message.bbox_y1 = detection.y1
        message.bbox_x2 = detection.x2
        message.bbox_y2 = detection.y2
        message.depth_m = (
            projection.depth_m if projection.depth_m is not None else 0.0)
        message.depth_valid_pixels = projection.valid_pixels
        message.depth_total_pixels = projection.total_pixels
        message.depth_valid_ratio = projection.valid_ratio
        message.source = detection.source
        message.position_semantics = (
            'aligned_depth_roi_median_at_clipped_bbox_center')
        return message

    def publish_perception_frame(
            self, header, frame_id, status, error_code, sync_span_sec,
            targets, processing_latency_sec):
        """Publish one navigation-consumable but strictly read-only frame."""
        self.frame_sequence += 1
        message = PerceptionFrame()
        message.stamp = header.stamp
        message.frame_id = frame_id
        message.task_id = self.active_task or ''
        message.sequence = self.frame_sequence
        message.valid = status in ('targets_ready', 'no_targets')
        message.status = status
        message.error_code = error_code
        message.sync_span_sec = (
            sync_span_sec if sync_span_sec is not None else -1.0)
        message.processing_latency_sec = processing_latency_sec
        message.targets = targets
        self.frame_publisher.publish(message)

    def publish_detection(
            self, target, point, size, header, observation_id):
        """Publish only the legacy actionable bottle contract."""
        message = ObjectDetection()
        message.stamp = header.stamp
        message.detection_id = observation_id
        message.task_id = self.active_task or ''
        message.object_class = 'plastic_bottle'
        message.confidence = target.confidence
        message.frame_id = header.frame_id
        message.position.x, message.position.y, message.position.z = point
        message.size.x, message.size.y, message.size.z = size
        self.detection_publisher.publish(message)

    def publish_status(self, state, **details):
        payload = {'state': state, 'task_id': self.active_task or ''}
        payload.update(details)
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.status_publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = DualModelDetector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
