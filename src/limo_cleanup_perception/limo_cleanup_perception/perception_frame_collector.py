"""Subscribe to typed perception frames and write read-only JSONL evidence."""

import argparse
import hashlib
import json
import os
import signal
import time
from pathlib import Path

import rclpy
from limo_cleanup_interfaces.msg import PerceptionFrame
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from limo_cleanup_perception.perception_evaluator import SCENES
from limo_cleanup_perception.perception_frame_io import frame_to_dict


class PerceptionFrameCollector(Node):
    """Collect a bounded scene without publishing any ROS message."""

    def __init__(
            self, output_path, scene, task_id, max_frames, duration_sec):
        super().__init__('cleanup_perception_frame_collector')
        self.output_path = output_path
        self.scene = scene
        self.task_id = task_id
        self.max_frames = max_frames
        self.deadline = time.monotonic() + duration_sec
        self.received = 0
        self.unique_frames = 0
        self.duplicate_sequences = 0
        self.seen_sequences = set()
        self.serialization_errors = 0
        self.done = False
        self.stream = output_path.open('x', encoding='utf-8')
        self.create_subscription(
            PerceptionFrame, '/cleanup/perception/frames',
            self.frame_callback, qos_profile_sensor_data)
        self.create_timer(0.1, self.check_deadline)

    def frame_callback(self, message):
        """Append one complete typed frame with receipt metadata."""
        if self.done:
            return
        try:
            record = dict(frame_to_dict(message, time.time()))
        except ValueError as error:
            self.serialization_errors += 1
            self.get_logger().error(str(error))
            return
        record['scene'] = self.scene
        if record.get('task_id') != self.task_id:
            self.serialization_errors += 1
            self.get_logger().error('typed frame task_id mismatch')
            return
        self.stream.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.received += 1
        sequence = int(message.sequence)
        if sequence in self.seen_sequences:
            self.duplicate_sequences += 1
        else:
            self.seen_sequences.add(sequence)
            self.unique_frames += 1
        if self.unique_frames >= self.max_frames:
            self.done = True

    def check_deadline(self):
        """Stop after the configured wall-clock duration."""
        if time.monotonic() >= self.deadline:
            self.done = True

    def close(self):
        """Flush and close the evidence stream."""
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()


def sha256_file(path):
    """Hash a completed evidence file."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args():
    """Build the bounded read-only collector CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene', choices=SCENES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--max-frames', type=int, default=120)
    parser.add_argument('--duration-sec', type=float, default=60.0)
    return parser.parse_args()


def main(args=None):
    """Collect typed frames only; never publish controls or other messages."""
    parsed = parse_args()
    if parsed.max_frames < 30:
        raise SystemExit('max-frames cannot be lower than 30')
    if parsed.duration_sec <= 0.0:
        raise SystemExit('duration-sec must be positive')
    if not parsed.task_id.strip():
        raise SystemExit('task-id must be non-empty')
    if parsed.output.resolve() == parsed.manifest.resolve():
        raise SystemExit('output and manifest paths must be different')
    if parsed.output.exists() or parsed.manifest.exists():
        raise SystemExit('output and manifest paths must not already exist')
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    parsed.manifest.parent.mkdir(parents=True, exist_ok=True)
    rclpy.init(args=args)
    node = PerceptionFrameCollector(
        parsed.output, parsed.scene, parsed.task_id, parsed.max_frames,
        parsed.duration_sec)
    interrupted = False

    def request_stop(*_unused):
        nonlocal interrupted
        interrupted = True
        node.done = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.close()
        manifest = {
            'schema_version': 1,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'scene': parsed.scene,
            'topic': '/cleanup/perception/frames',
            'message_type': 'limo_cleanup_interfaces/msg/PerceptionFrame',
            'task_id': parsed.task_id,
            'max_frames': parsed.max_frames,
            'duration_sec': parsed.duration_sec,
            'received_frames': node.received,
            'unique_sequence_frames': node.unique_frames,
            'duplicate_sequences': node.duplicate_sequences,
            'serialization_errors': node.serialization_errors,
            'interrupted': interrupted,
            'completed_max_frames': node.unique_frames >= parsed.max_frames,
            'output': {
                'path': str(parsed.output),
                'size_bytes': parsed.output.stat().st_size,
                'sha256': sha256_file(parsed.output),
            },
            'forbidden_control_topics': [
                '/cmd_vel', '/cleanup/base/safe_cmd_vel',
                '/navigate_to_pose', '/arm_controller/joint_trajectory',
                '/gripper_controller/commands',
            ],
        }
        with parsed.manifest.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(
                manifest, ensure_ascii=False, indent=2, sort_keys=True))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        node.destroy_node()
        rclpy.shutdown()
    return 0 if (
        node.unique_frames >= parsed.max_frames
        and node.duplicate_sequences == 0
        and node.serialization_errors == 0
        and not interrupted
    ) else 1


if __name__ == '__main__':
    raise SystemExit(main())
