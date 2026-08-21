"""Bounded ROS1 typed-frame collector with no ROS publisher."""

import argparse
import hashlib
import json
import os
import signal
import time
from pathlib import Path

from limo_cleanup_ros1_perception.perception_frame_io import frame_to_dict


SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
TYPED_FRAME_TOPIC = '/cleanup/perception/frames'


def sha256_file(path: Path) -> str:
    """Hash one completed evidence artifact."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class FrameWriter:
    """Validate and exclusively append typed frames as JSONL."""

    def __init__(self, path, scene, task_id, max_frames):
        self.path = Path(path)
        self.scene = scene
        self.task_id = task_id
        self.max_frames = max_frames
        self.received = 0
        self.unique_frames = 0
        self.duplicate_sequences = 0
        self.duplicate_bundle_ids = 0
        self.serialization_errors = 0
        self.sequences = set()
        self.bundle_ids = set()
        self.done = False
        self.stream = self.path.open('x', encoding='utf-8')

    def accept(self, message, received_unix_sec=None) -> bool:
        """Append one task-bound frame and reject duplicates fail-closed."""
        if self.done:
            return False
        try:
            record = dict(frame_to_dict(
                message,
                time.time() if received_unix_sec is None
                else received_unix_sec))
        except (TypeError, ValueError):
            self.serialization_errors += 1
            return False
        if record.get('task_id') != self.task_id:
            self.serialization_errors += 1
            return False
        sequence = record.get('sequence')
        bundle_id = record.get('bundle_id')
        if sequence in self.sequences:
            self.duplicate_sequences += 1
            return False
        if not isinstance(bundle_id, str) or len(bundle_id) != 64:
            self.serialization_errors += 1
            return False
        if bundle_id in self.bundle_ids:
            self.duplicate_bundle_ids += 1
            return False
        record['scene'] = self.scene
        encoded = json.dumps(
            record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        self.stream.write(encoded + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.sequences.add(sequence)
        self.bundle_ids.add(bundle_id)
        self.received += 1
        self.unique_frames += 1
        if self.unique_frames >= self.max_frames:
            self.done = True
        return True

    def close(self) -> None:
        """Flush and close the exclusive frame stream."""
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()


def parse_args(args=None):
    """Build the finite-duration ROS1 subscriber CLI."""
    parser = argparse.ArgumentParser(
        description='Collect read-only ROS1 typed perception frames.')
    parser.add_argument('--scene', choices=SCENES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--max-frames', type=int, default=120)
    parser.add_argument('--duration-sec', type=float, default=60.0)
    return parser.parse_args(args)


def _validate_cli(parsed) -> None:
    if parsed.max_frames < 30:
        raise SystemExit('max-frames cannot be lower than 30')
    if not isinstance(parsed.duration_sec, float):
        parsed.duration_sec = float(parsed.duration_sec)
    if not parsed.duration_sec > 0.0:
        raise SystemExit('duration-sec must be positive')
    if not parsed.task_id.strip():
        raise SystemExit('task-id must be non-empty')
    if parsed.output.resolve() == parsed.manifest.resolve():
        raise SystemExit('output and manifest paths must differ')
    if parsed.output.exists() or parsed.manifest.exists():
        raise SystemExit('output and manifest paths must not already exist')


def main(args=None):
    """Subscribe for a bounded interval and create exclusive evidence files."""
    parsed = parse_args(args)
    _validate_cli(parsed)
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    parsed.manifest.parent.mkdir(parents=True, exist_ok=True)
    writer = FrameWriter(
        parsed.output, parsed.scene, parsed.task_id, parsed.max_frames)
    import rospy
    from limo_cleanup_ros1_perception.msg import PerceptionFrame

    rospy.init_node(
        'limo_cleanup_readonly_frame_collector', anonymous=True,
        disable_signals=True)
    deadline = time.monotonic() + parsed.duration_sec
    interrupted = False

    def callback(message):
        writer.accept(message)

    def request_stop(*_unused):
        nonlocal interrupted
        interrupted = True
        writer.done = True

    subscriber = rospy.Subscriber(
        TYPED_FRAME_TOPIC, PerceptionFrame, callback,
        queue_size=100)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        rate = rospy.Rate(20)
        while (
                not rospy.is_shutdown()
                and not writer.done
                and time.monotonic() < deadline):
            rate.sleep()
    finally:
        subscriber.unregister()
        writer.close()
        manifest = {
            'schema_version': 1,
            'collector_kind': 'ros1_typed_frame_readonly',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'scene': parsed.scene,
            'topic': TYPED_FRAME_TOPIC,
            'message_type': (
                'limo_cleanup_ros1_perception/PerceptionFrame'),
            'task_id': parsed.task_id,
            'max_frames': parsed.max_frames,
            'duration_sec': parsed.duration_sec,
            'received_frames': writer.received,
            'unique_frames': writer.unique_frames,
            'duplicate_sequences': writer.duplicate_sequences,
            'duplicate_bundle_ids': writer.duplicate_bundle_ids,
            'serialization_errors': writer.serialization_errors,
            'interrupted': interrupted,
            'completed_minimum': writer.unique_frames >= 30,
            'completed_requested_frames': (
                writer.unique_frames >= parsed.max_frames),
            'output': {
                'path': str(parsed.output.resolve()),
                'size_bytes': parsed.output.stat().st_size,
                'sha256': sha256_file(parsed.output),
            },
        }
        with parsed.manifest.open('x', encoding='utf-8') as stream:
            json.dump(
                manifest, stream, ensure_ascii=False, indent=2,
                sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    return 0 if (
        writer.unique_frames >= parsed.max_frames
        and writer.duplicate_sequences == 0
        and writer.duplicate_bundle_ids == 0
        and writer.serialization_errors == 0
        and not interrupted
    ) else 1


if __name__ == '__main__':
    raise SystemExit(main())
