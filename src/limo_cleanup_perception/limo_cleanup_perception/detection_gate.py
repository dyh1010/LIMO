"""Quality gate between detection producers and the cleanup executor."""

import json
import math
from dataclasses import dataclass

import rclpy
from limo_cleanup_interfaces.msg import ObjectDetection
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import String


DEFAULT_ALLOWED_CLASSES = (
    'plastic_bottle', 'can', 'paper_box', 'generic_waste')
DEFAULT_ALLOWED_FRAMES = (
    'camera_color_optical_frame', 'camera_depth_optical_frame',
    'base_link', 'arm_base_link')
CONFIDENCE_EPSILON = 1e-6


@dataclass(frozen=True)
class GateConfig:
    min_confidence: float = 0.35
    max_detection_age: float = 1.0
    min_range: float = 0.05
    max_range: float = 3.0
    min_size: float = 0.01
    max_size: float = 1.0
    allowed_classes: tuple = DEFAULT_ALLOWED_CLASSES
    allowed_frames: tuple = DEFAULT_ALLOWED_FRAMES


def validate_detection(message, config, now=None):
    """
    Check one ObjectDetection against the quality config.

    Returns (accepted, reasons); reasons lists every failed check.
    """
    reasons = []

    if not message.detection_id:
        reasons.append('missing_detection_id')

    if message.object_class not in config.allowed_classes:
        reasons.append(f'unsupported_class:{message.object_class}')

    if message.frame_id not in config.allowed_frames:
        reasons.append(f'unsupported_frame:{message.frame_id}')

    if not math.isfinite(message.confidence):
        reasons.append('confidence_not_finite')
    elif not 0.0 <= message.confidence <= 1.0:
        reasons.append('confidence_out_of_range')
    elif message.confidence < config.min_confidence - CONFIDENCE_EPSILON:
        reasons.append(f'low_confidence:{message.confidence:.2f}')

    position = (message.position.x, message.position.y, message.position.z)
    size = (message.size.x, message.size.y, message.size.z)

    if not all(math.isfinite(value) for value in position):
        reasons.append('position_not_finite')
    else:
        distance = math.sqrt(sum(value * value for value in position))
        if distance < config.min_range or distance > config.max_range:
            reasons.append(f'distance_out_of_range:{distance:.2f}')

    if not all(math.isfinite(value) for value in size):
        reasons.append('size_not_finite')
    elif any(value <= 0.0 for value in size):
        reasons.append('size_not_positive')
    elif any(
            value < config.min_size or value > config.max_size
            for value in size):
        reasons.append('size_out_of_bounds')

    if config.max_detection_age > 0.0 and now is not None:
        stamp = Time.from_msg(message.stamp, clock_type=now.clock_type)
        age = (now - stamp).nanoseconds / 1e9
        if age > config.max_detection_age:
            reasons.append(f'stale_detection:{age:.2f}s')
        elif age < -0.5:
            reasons.append(f'future_detection:{-age:.2f}s')

    return (not reasons, reasons)


class DetectionGate(Node):
    """Republish only the detections that pass every quality check."""

    def __init__(self) -> None:
        super().__init__('cleanup_detection_gate')

        self.declare_parameter('min_confidence', 0.35)
        self.declare_parameter('max_detection_age', 1.0)
        self.declare_parameter('min_range', 0.05)
        self.declare_parameter('max_range', 3.0)
        self.declare_parameter('min_size', 0.01)
        self.declare_parameter('max_size', 1.0)
        self.declare_parameter(
            'allowed_classes', list(DEFAULT_ALLOWED_CLASSES))
        self.declare_parameter(
            'allowed_frames', list(DEFAULT_ALLOWED_FRAMES))

        self.config = GateConfig(
            min_confidence=self.parameter_double('min_confidence'),
            max_detection_age=self.parameter_double('max_detection_age'),
            min_range=self.parameter_double('min_range'),
            max_range=self.parameter_double('max_range'),
            min_size=self.parameter_double('min_size'),
            max_size=self.parameter_double('max_size'),
            allowed_classes=tuple(
                self.get_parameter(
                    'allowed_classes').get_parameter_value(
                    ).string_array_value),
            allowed_frames=tuple(
                self.get_parameter(
                    'allowed_frames').get_parameter_value(
                    ).string_array_value),
        )

        status_qos = QoSProfile(depth=20)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.detection_publisher = self.create_publisher(
            ObjectDetection, '/cleanup/detection', 10)
        self.status_publisher = self.create_publisher(
            String, '/cleanup/detection_status', status_qos)
        self.create_subscription(
            ObjectDetection,
            '/cleanup/detection/raw',
            self.detection_callback,
            10,
        )

        self.received_count = 0
        self.accepted_count = 0
        self.rejected_count = 0

        self.get_logger().info(
            'Detection gate ready on /cleanup/detection/raw; '
            f'min_confidence={self.config.min_confidence:.2f}; '
            f'max_detection_age={self.config.max_detection_age:.2f}s; '
            f'range=[{self.config.min_range:.2f}, '
            f'{self.config.max_range:.2f}]m')

    def parameter_double(self, name: str) -> float:
        return float(
            self.get_parameter(name).get_parameter_value().double_value)

    def detection_callback(self, message: ObjectDetection) -> None:
        self.received_count += 1
        accepted, reasons = validate_detection(
            message, self.config, now=self.get_clock().now())

        if accepted:
            self.accepted_count += 1
            self.detection_publisher.publish(message)
            self.publish_status(
                'accepted', 'Passed all quality checks', message, reasons)
            self.get_logger().info(
                f'Accepted detection {message.detection_id}: '
                f'{message.object_class} ({message.confidence:.0%})')
        else:
            self.rejected_count += 1
            detail = '; '.join(reasons)
            self.publish_status('rejected', detail, message, reasons)
            self.get_logger().warning(
                f'Rejected detection {message.detection_id}: {detail}')

    def publish_status(
            self, state, detail, detection, reasons) -> None:
        payload = {
            'state': state,
            'detail': detail,
            'detection_id': detection.detection_id,
            'task_id': detection.task_id,
            'object_class': detection.object_class,
            'confidence': round(float(detection.confidence), 3),
            'frame_id': detection.frame_id,
            'counters': {
                'received': self.received_count,
                'accepted': self.accepted_count,
                'rejected': self.rejected_count,
            },
        }
        if reasons:
            payload['reasons'] = list(reasons)
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.status_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DetectionGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
