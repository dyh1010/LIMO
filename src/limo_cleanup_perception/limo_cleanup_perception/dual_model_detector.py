"""ROS 2 RGB-D detector for actionable bottles outside trash bins."""

import json
import threading
import uuid

import numpy as np
import rclpy
from limo_cleanup_interfaces.msg import CleanupTask, ObjectDetection
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
    classify_bottles,
    select_target_bottle,
)
from limo_cleanup_perception.task_actions import (
    accepts_perception_task,
)


class DualModelDetector(Node):
    """Publish only bottle targets that are not already inside a bin."""

    def __init__(self) -> None:
        super().__init__('cleanup_dual_model_detector')
        self.declare_parameters('', [
            ('bottle_model_path', ''),
            ('bin_model_path', ''),
            ('rgb_topic', '/camera/color/image_raw'),
            ('depth_topic', '/camera/depth/image_raw'),
            ('camera_info_topic', '/camera/color/camera_info'),
            ('confidence', 0.5),
            ('iou', 0.45),
            ('imgsz', 640),
            ('device', '0'),
            ('process_period', 0.20),
            ('publish_period', 0.50),
            ('depth_scale', 0.001),
            ('min_depth', 0.30),
            ('max_depth', 3.00),
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
        self.publish_period = self.parameter_double('publish_period')
        self.always_active = self.parameter_bool('always_active')

        self.get_logger().info('Loading bottle and trash-bin models')
        self.bottle_model = YOLO(bottle_model_path)
        self.bin_model = YOLO(bin_model_path)
        self.data_lock = threading.Lock()
        self.latest_rgb = None
        self.latest_depth = None
        self.latest_rgb_header = None
        self.camera_info = None
        self.active_task = (
            'read-only-perception' if self.always_active else None)
        self.last_processed_stamp = None
        self.last_publish_time = 0.0

        rgb_topic = self.parameter_string('rgb_topic')
        depth_topic = self.parameter_string('depth_topic')
        camera_info_topic = self.parameter_string('camera_info_topic')
        self.create_subscription(
            Image, rgb_topic, self.rgb_callback, qos_profile_sensor_data)
        self.create_subscription(
            Image, depth_topic, self.depth_callback, qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, camera_info_topic, self.camera_info_callback,
            qos_profile_sensor_data)
        self.create_subscription(
            CleanupTask, '/cleanup/task', self.task_callback, 10)
        self.detection_publisher = self.create_publisher(
            ObjectDetection, '/cleanup/detection/raw', 10)
        self.status_publisher = self.create_publisher(
            String, '/cleanup/perception_status', 10)
        self.create_timer(
            self.parameter_double('process_period'), self.process_latest_frame)
        self.get_logger().info(
            f'Dual-model detector ready; rgb={rgb_topic}; '
            f'depth={depth_topic}; '
            f'camera_info={camera_info_topic}; '
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
            self.latest_rgb = image
            self.latest_rgb_header = message.header

    def depth_callback(self, message):
        try:
            depth = image_message_to_numpy(message)
        except ValueError as error:
            self.get_logger().warning(str(error))
            return
        with self.data_lock:
            self.latest_depth = depth

    def camera_info_callback(self, message):
        with self.data_lock:
            self.camera_info = message

    def task_callback(self, message):
        if self.always_active:
            return
        if message.action == 'cancel':
            if self.active_task == message.task_id:
                self.active_task = None
            return
        if (
                accepts_perception_task(message.action)
                and message.object_class == 'plastic_bottle'
                and message.task_id):
            self.active_task = message.task_id
            self.get_logger().info(
                f'Activated perception for task {message.task_id}')

    def process_latest_frame(self):
        if self.active_task is None:
            return
        with self.data_lock:
            if (
                    self.latest_rgb is None
                    or self.latest_depth is None
                    or self.camera_info is None
                    or self.latest_rgb_header is None):
                self.publish_status('waiting_for_rgb_depth_camera_info')
                return
            stamp = (
                self.latest_rgb_header.stamp.sec,
                self.latest_rgb_header.stamp.nanosec,
            )
            if stamp == self.last_processed_stamp:
                return
            rgb = self.latest_rgb.copy()
            depth = self.latest_depth.copy()
            header = self.latest_rgb_header
            camera_info = self.camera_info
            self.last_processed_stamp = stamp

        bottle_result = self.bottle_model.predict(
            source=rgb, conf=self.confidence, iou=self.iou,
            imgsz=self.imgsz, device=self.device, verbose=False)[0]
        bin_result = self.bin_model.predict(
            source=rgb, conf=self.confidence, iou=self.iou,
            imgsz=self.imgsz, device=self.device, verbose=False)[0]
        bottles = self.to_detections(
            bottle_result, 'plastic_bottle', 'bottle_model')
        bins = self.to_detections(bin_result, 'trash_bin', 'bin_model')
        classified = classify_bottles(
            bottles, bins,
            overlap_threshold=self.in_bin_overlap,
            horizontal_margin_ratio=self.opening_margin_ratio,
            opening_height_ratio=self.opening_height_ratio,
        )
        target = select_target_bottle(classified.active)
        self.publish_status(
            'target_ready' if target is not None else 'searching_bottle',
            bottles_total=len(bottles),
            bottles_active=len(classified.active),
            bottles_already_in_bin=len(classified.already_in_bin),
            bins=len(bins),
        )
        if target is None:
            return
        now_seconds = self.get_clock().now().nanoseconds / 1e9
        if now_seconds - self.last_publish_time < self.publish_period:
            return
        point, size = self.project_detection(target, depth, camera_info)
        if point is None:
            self.publish_status('target_has_no_valid_depth')
            return
        self.publish_detection(target, point, size, header)
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

    def project_detection(self, detection, depth_image, camera_info):
        height, width = depth_image.shape[:2]
        x1 = max(0, min(width - 1, round(detection.x1)))
        x2 = max(x1 + 1, min(width, round(detection.x2)))
        y1 = max(0, min(height - 1, round(detection.y1)))
        y2 = max(y1 + 1, min(height, round(detection.y2)))
        crop_width = x2 - x1
        crop_height = y2 - y1
        roi_x1 = x1 + round(crop_width * 0.30)
        roi_x2 = x2 - round(crop_width * 0.30)
        roi_y1 = y1 + round(crop_height * 0.30)
        roi_y2 = y2 - round(crop_height * 0.30)
        roi = depth_image[roi_y1:roi_y2, roi_x1:roi_x2]
        if roi.size == 0:
            return None, None
        depth_values = roi.astype(np.float64)
        if np.issubdtype(roi.dtype, np.integer):
            depth_values *= self.depth_scale
        valid = depth_values[
            np.isfinite(depth_values)
            & (depth_values >= self.min_depth)
            & (depth_values <= self.max_depth)]
        if valid.size < 5:
            return None, None
        z = float(np.median(valid))
        center_x, center_y = detection.center
        fx, fy = float(camera_info.k[0]), float(camera_info.k[4])
        cx, cy = float(camera_info.k[2]), float(camera_info.k[5])
        if fx <= 0.0 or fy <= 0.0:
            return None, None
        point = (
            (center_x - cx) * z / fx,
            (center_y - cy) * z / fy,
            z,
        )
        size = (
            max(0.01, detection.width * z / fx),
            max(0.01, detection.height * z / fy),
            0.07,
        )
        return point, size

    def publish_detection(self, target, point, size, header):
        message = ObjectDetection()
        message.stamp = header.stamp
        message.detection_id = str(uuid.uuid4())
        message.task_id = self.active_task or ''
        message.object_class = 'plastic_bottle'
        message.confidence = target.confidence
        message.frame_id = (
            self.frame_id_override or header.frame_id
            or 'camera_depth_optical_frame')
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
