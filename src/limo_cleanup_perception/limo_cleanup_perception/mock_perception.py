import time
import uuid

import rclpy
from limo_cleanup_interfaces.msg import CleanupTask, ObjectDetection
from rclpy.node import Node


class MockPerceptionNode(Node):
    def __init__(self) -> None:
        super().__init__('cleanup_mock_perception')

        self.declare_parameter('detection_delay', 1.0)
        self.declare_parameter('confidence', 0.92)
        self.declare_parameter(
            'frame_id', 'camera_depth_optical_frame')
        self.declare_parameter('position_x', 0.80)
        self.declare_parameter('position_y', 0.00)
        self.declare_parameter('position_z', 0.05)
        self.declare_parameter('size_x', 0.07)
        self.declare_parameter('size_y', 0.07)
        self.declare_parameter('size_z', 0.22)
        self.declare_parameter('publish_detections', True)

        self.detection_delay = float(
            self.get_parameter(
                'detection_delay').get_parameter_value().double_value)
        self.confidence = float(
            self.get_parameter(
                'confidence').get_parameter_value().double_value)
        self.frame_id = self.get_parameter(
            'frame_id').get_parameter_value().string_value
        self.position = (
            self.parameter_double('position_x'),
            self.parameter_double('position_y'),
            self.parameter_double('position_z'),
        )
        self.size = (
            self.parameter_double('size_x'),
            self.parameter_double('size_y'),
            self.parameter_double('size_z'),
        )
        self.publish_detections = self.get_parameter(
            'publish_detections').get_parameter_value().bool_value

        self.pending_tasks = {}
        self.detection_publisher = self.create_publisher(
            ObjectDetection, '/cleanup/detection', 10)
        self.create_subscription(
            CleanupTask, '/cleanup/task', self.task_callback, 10)
        self.create_timer(0.05, self.publish_due_detections)

        mode = 'enabled' if self.publish_detections else 'disabled'
        self.get_logger().info(
            f'Mock perception ready; mode={mode}; '
            f'detection_delay={self.detection_delay:.2f}s')

    def parameter_double(self, name: str) -> float:
        return float(
            self.get_parameter(name).get_parameter_value().double_value)

    def task_callback(self, message: CleanupTask) -> None:
        if message.action == 'cancel':
            self.pending_tasks.pop(message.task_id, None)
            return

        if (
                not self.publish_detections
                or message.action != 'pick_and_dispose'
                or not message.task_id
                or not message.object_class):
            return

        self.pending_tasks[message.task_id] = {
            'due_at': time.monotonic() + self.detection_delay,
            'object_class': message.object_class,
        }
        self.get_logger().info(
            f'Scheduled mock detection for {message.task_id}: '
            f'{message.object_class}')

    def publish_due_detections(self) -> None:
        now = time.monotonic()
        due_task_ids = [
            task_id
            for task_id, task in self.pending_tasks.items()
            if task['due_at'] <= now
        ]

        for task_id in due_task_ids:
            task = self.pending_tasks.pop(task_id, None)
            if task is None:
                continue
            self.publish_detection(
                task_id, task['object_class'])

    def publish_detection(
            self, task_id: str, object_class: str) -> None:
        message = ObjectDetection()
        message.stamp = self.get_clock().now().to_msg()
        message.detection_id = str(uuid.uuid4())
        message.task_id = task_id
        message.object_class = object_class
        message.confidence = self.confidence
        message.frame_id = self.frame_id
        message.position.x = self.position[0]
        message.position.y = self.position[1]
        message.position.z = self.position[2]
        message.size.x = self.size[0]
        message.size.y = self.size[1]
        message.size.z = self.size[2]
        self.detection_publisher.publish(message)
        self.get_logger().info(
            f'Published detection {message.detection_id} for '
            f'{task_id}: {object_class} at '
            f'({message.position.x:.2f}, '
            f'{message.position.y:.2f}, '
            f'{message.position.z:.2f})')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MockPerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
