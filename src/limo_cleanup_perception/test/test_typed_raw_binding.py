"""Tests for the ROS-independent typed-to-raw evidence binder."""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from limo_cleanup_perception.rgbd_bag_indexer import inspect_sqlite_bag
from limo_cleanup_perception.typed_raw_binding import create_binding, main
from src.limo_cleanup_perception.test.test_rgbd_bag_indexer import (
    STREAM_TOPICS, create_bag,
)


WORKSPACE = Path(__file__).resolve().parents[3]
ROS1_DIAGNOSTIC_MANIFEST_V3 = (
    WORKSPACE / 'evidence' / 'perception_v2_field_20260814' /
    'diagnostic_shared_graph' /
    'v2_ros1_shared_graph_diagnostic_20260814T052442Z.'
    'diagnostic-manifest-v3.json')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, frame_count=30):
    raw = root / 'capture.db3'
    create_bag(
        raw, frame_count=frame_count, base_time_ns=1_000_000_000,
        frame_period_ns=10_000_000)
    inspection_value = inspect_sqlite_bag(
        raw, 'capture-background', 'background', STREAM_TOPICS)
    inspection = root / 'inspection.json'
    inspection.write_text(
        json.dumps(inspection_value, sort_keys=True) + '\n', encoding='utf-8')
    frames = []
    for sequence, bundle in enumerate(
            inspection_value['accepted_bundles'], 1):
        stamp_ns = bundle['header_stamps_ns']['rgb']
        frames.append({
            'schema_version': 1,
            'read_only': True,
            'received_unix_sec': stamp_ns / 1e9 + 0.2,
            'transport_latency_sec': 0.2,
            'stamp': {
                'sec': stamp_ns // 1_000_000_000,
                'nanosec': stamp_ns % 1_000_000_000,
            },
            'frame_id': 'camera_color_optical_frame',
            'task_id': 'readonly-background',
            'sequence': sequence,
            'scene': 'background',
            'valid': True,
            'status': 'no_targets',
            'error_code': '',
            'sync_span_sec': bundle['stamp_span_sec'],
            'processing_latency_sec': 0.1,
            'targets': [],
        })
    typed = root / 'frames.jsonl'
    typed.write_text(''.join(
        json.dumps(frame, sort_keys=True) + '\n' for frame in frames),
        encoding='utf-8')
    collector = root / 'collector.json'
    collector.write_text(json.dumps({
        'schema_version': 1,
        'read_only': True,
        'authorizes_motion': False,
        'scene': 'background',
        'topic': '/cleanup/perception/frames',
        'message_type': 'limo_cleanup_interfaces/msg/PerceptionFrame',
        'task_id': 'readonly-background',
        'max_frames': frame_count,
        'duration_sec': 60.0,
        'received_frames': frame_count,
        'unique_sequence_frames': frame_count,
        'duplicate_sequences': 0,
        'serialization_errors': 0,
        'interrupted': False,
        'completed_max_frames': True,
        'output': {
            'path': typed.name,
            'size_bytes': typed.stat().st_size,
            'sha256': _sha(typed),
        },
        'publishes_ros_messages': False,
        'forbidden_control_topics': [
            '/cmd_vel', '/cleanup/base/safe_cmd_vel', '/navigate_to_pose',
            '/arm_controller/joint_trajectory',
            '/gripper_controller/commands',
        ],
    }, sort_keys=True), encoding='utf-8')
    return typed, collector, raw, inspection


def _write_frames(typed: Path, collector: Path, frames):
    typed.write_text(''.join(
        json.dumps(frame, sort_keys=True) + '\n' for frame in frames),
        encoding='utf-8')
    manifest = json.loads(collector.read_text(encoding='utf-8'))
    manifest['received_frames'] = len(frames)
    manifest['unique_sequence_frames'] = len(frames)
    manifest['output']['size_bytes'] = typed.stat().st_size
    manifest['output']['sha256'] = _sha(typed)
    collector.write_text(
        json.dumps(manifest, sort_keys=True), encoding='utf-8')


def _shift_last_stamps(typed: Path, collector: Path, count: int):
    frames = [json.loads(line) for line in typed.read_text(
        encoding='utf-8').splitlines()]
    for frame in frames[len(frames) - count:] if count else ():
        stamp_ns = (frame['stamp']['sec'] * 1_000_000_000
                    + frame['stamp']['nanosec'] + 1)
        frame['stamp'] = {
            'sec': stamp_ns // 1_000_000_000,
            'nanosec': stamp_ns % 1_000_000_000,
        }
    _write_frames(typed, collector, frames)


def _bind(paths):
    typed, collector, raw, inspection = paths
    return create_binding(
        typed, collector, raw, inspection, 'background',
        'capture-background', 'readonly-background', 1.0, 10.0,
        'release-v2-0001', 'a' * 64, {
            'plastic_bottle': 'b' * 64,
            'trash_bin': 'c' * 64,
        })


class TypedRawBindingTest(unittest.TestCase):
    def test_collector_native_frames_bind_without_inline_raw_bundle(self):
        with TemporaryDirectory() as directory:
            paths = _fixture(Path(directory))
            report = _bind(paths)
            self.assertEqual(30, report['typed_frame_count'])
            self.assertEqual(30, report['raw_bundle_count'])
            self.assertEqual(0.0, report['unpaired_rate'])
            self.assertTrue(report['read_only'])
            self.assertFalse(report['authorizes_motion'])
            self.assertFalse(report['publishes_ros_messages'])
            self.assertNotIn('raw_bundle', json.loads(
                paths[0].read_text(encoding='utf-8').splitlines()[0]))

    def test_unpaired_boundaries_are_measured_not_decided(self):
        cases = (
            ('zero_percent', 40, 0, 0.0),
            ('five_percent', 40, 2, 0.05),
            ('five_percent_plus_epsilon', 99, 5, 5 / 99),
            ('seventy_percent', 40, 28, 0.70),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, frame_count, unpaired, expected_rate in cases:
                with self.subTest(case=name):
                    case_root = root / name
                    case_root.mkdir()
                    paths = _fixture(case_root, frame_count=frame_count)
                    _shift_last_stamps(paths[0], paths[1], unpaired)
                    report = _bind(paths)
                    self.assertEqual(
                        frame_count, report['typed_frame_count'])
                    self.assertEqual(
                        frame_count, report['raw_bundle_count'])
                    self.assertEqual(
                        frame_count - unpaired,
                        len(report['frame_bindings']))
                    self.assertEqual(
                        unpaired, report['unpaired_typed_count'])
                    self.assertEqual(
                        unpaired, report['unpaired_raw_bundle_count'])
                    self.assertAlmostEqual(
                        expected_rate, report['unpaired_rate'])
                    self.assertNotIn('delivery_ready', report)

    def test_unpaired_rate_uses_larger_side_rate(self):
        with TemporaryDirectory() as directory:
            typed, collector, raw, inspection = _fixture(
                Path(directory), frame_count=40)
            frames = [json.loads(line) for line in typed.read_text(
                encoding='utf-8').splitlines()]
            del frames[-2:]
            _write_frames(typed, collector, frames)
            manifest = json.loads(collector.read_text(encoding='utf-8'))
            manifest['max_frames'] = len(frames)
            collector.write_text(
                json.dumps(manifest, sort_keys=True), encoding='utf-8')
            report = _bind((typed, collector, raw, inspection))
            self.assertEqual(38, report['typed_frame_count'])
            self.assertEqual(40, report['raw_bundle_count'])
            self.assertEqual(38, len(report['frame_bindings']))
            self.assertEqual(0, report['unpaired_typed_count'])
            self.assertEqual(2, report['unpaired_raw_bundle_count'])
            self.assertEqual(0.05, report['unpaired_rate'])

    def test_zero_denominators_duplicates_and_fake_counts_fail_closed(self):
        cases = (
            'zero_typed', 'zero_raw', 'duplicate_typed_stamp',
            'duplicate_raw_stamp', 'fake_collector_count',
            'fake_inspection_count', 'fake_topic_manifest_binding',
            'diagnostic_exclusion_flags', 'typed_diagnostic_envelope')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for case in cases:
                with self.subTest(case=case):
                    case_root = root / case
                    case_root.mkdir()
                    typed, collector, raw, inspection = _fixture(case_root)
                    if case in (
                            'zero_typed', 'duplicate_typed_stamp',
                            'typed_diagnostic_envelope'):
                        frames = [json.loads(line) for line in typed.read_text(
                            encoding='utf-8').splitlines()]
                        if case == 'zero_typed':
                            frames = []
                        elif case == 'duplicate_typed_stamp':
                            frames[1]['stamp'] = dict(frames[0]['stamp'])
                        if case == 'typed_diagnostic_envelope':
                            typed.write_text(json.dumps({
                                'formal_acceptance': False,
                                'shared_graph': True,
                                'mixed_tf': True,
                                'not_in_four_scene_denominator': True,
                                'frames': frames,
                            }, sort_keys=True) + '\n', encoding='utf-8')
                            manifest = json.loads(collector.read_text(
                                encoding='utf-8'))
                            manifest['output']['size_bytes'] = typed.stat().st_size
                            manifest['output']['sha256'] = _sha(typed)
                            collector.write_text(
                                json.dumps(manifest, sort_keys=True),
                                encoding='utf-8')
                        else:
                            _write_frames(typed, collector, frames)
                    elif case == 'fake_collector_count':
                        value = json.loads(collector.read_text(
                            encoding='utf-8'))
                        value['received_frames'] += 1
                        collector.write_text(
                            json.dumps(value, sort_keys=True),
                            encoding='utf-8')
                    else:
                        value = json.loads(inspection.read_text(
                            encoding='utf-8'))
                        if case == 'zero_raw':
                            value['accepted_bundles'] = []
                            value['accepted_bundle_count'] = 0
                            value['tf_graph']['bundle_transforms'] = []
                        elif case == 'duplicate_raw_stamp':
                            duplicate = value['accepted_bundles'][0][
                                'header_stamps_ns']['rgb']
                            value['accepted_bundles'][1][
                                'header_stamps_ns']['rgb'] = duplicate
                            value['tf_graph']['bundle_transforms'][1][
                                'rgb_header_stamp_ns'] = duplicate
                        elif case == 'fake_topic_manifest_binding':
                            value['expected_topic_manifest']['sha256'] = (
                                '0' * 64)
                        elif case == 'diagnostic_exclusion_flags':
                            value.update({
                                'report_kind': (
                                    'ros1_shared_graph_diagnostic_manifest'),
                                'inspection_scope': 'diagnostic_shared_graph',
                                'formal_acceptance': False,
                                'shared_graph': True,
                                'mixed_tf': True,
                                'not_in_four_scene_denominator': True,
                            })
                        else:
                            value['accepted_bundle_count'] += 1
                        inspection.write_text(
                            json.dumps(value, sort_keys=True),
                            encoding='utf-8')
                    with self.assertRaises(ValueError):
                        _bind((typed, collector, raw, inspection))

            formal_policy = {
                'report_kind': 'formal_rgbd_raw_capture_index',
                'inspection_scope': 'formal_scene_raw_capture',
                'formal_acceptance': True,
                'shared_graph': False,
                'mixed_tf': False,
                'not_in_four_scene_denominator': False,
            }
            mutations = {
                'report_kind': (
                    'ros1_shared_graph_diagnostic_manifest', 1),
                'inspection_scope': ('diagnostic_shared_graph', 1),
                'formal_acceptance': (False, 'true'),
                'shared_graph': (True, 'false'),
                'mixed_tf': (True, 'false'),
                'not_in_four_scene_denominator': (True, 'false'),
            }
            for field, (wrong_value, wrong_type) in mutations.items():
                for mutation_name in ('missing', 'null', 'wrong',
                                      'wrong_type'):
                    with self.subTest(
                            binding_field=field,
                            binding_case=mutation_name):
                        case_root = root / (
                            'policy_{}_{}'.format(field, mutation_name))
                        case_root.mkdir()
                        typed, collector, raw, inspection = _fixture(case_root)
                        value = json.loads(inspection.read_text(
                            encoding='utf-8'))
                        for policy_field, expected in formal_policy.items():
                            self.assertEqual(value[policy_field], expected)
                        if mutation_name == 'missing':
                            value.pop(field)
                        elif mutation_name == 'null':
                            value[field] = None
                        elif mutation_name == 'wrong':
                            value[field] = wrong_value
                        else:
                            value[field] = wrong_type
                        inspection.write_text(
                            json.dumps(value, sort_keys=True) + '\n',
                            encoding='utf-8')
                        with self.assertRaisesRegex(
                                ValueError,
                                'diagnostic raw inspection cannot enter a '
                                'formal scene binding'):
                            _bind((typed, collector, raw, inspection))

            actual_root = root / 'actual_ros1_diagnostic_manifest_v3'
            actual_root.mkdir()
            typed, collector, raw, _ = _fixture(actual_root)
            with self.assertRaisesRegex(
                    ValueError,
                    'diagnostic raw inspection cannot enter a formal scene '
                    'binding'):
                _bind((
                    typed, collector, raw, ROS1_DIAGNOSTIC_MANIFEST_V3))

    def test_stamp_sync_artifact_and_count_splices_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                'stamp', 'sync', 'typed_hash', 'raw_hash', 'missing_row',
                'frame_override', 'motion_claim', 'collector_motion',
                'collector_extra', 'collector_publisher',
                'collector_topic', 'collector_control_topics')
            for case in cases:
                with self.subTest(case=case):
                    case_root = root / case
                    case_root.mkdir()
                    typed, collector, raw, inspection = _fixture(case_root)
                    if case in (
                            'stamp', 'sync', 'missing_row', 'frame_override',
                            'motion_claim'):
                        rows = typed.read_text(encoding='utf-8').splitlines()
                        if case == 'stamp':
                            value = json.loads(rows[0])
                            value['stamp']['nanosec'] += 1
                            rows[0] = json.dumps(value, sort_keys=True)
                        elif case == 'sync':
                            value = json.loads(rows[0])
                            value['sync_span_sec'] += 0.001
                            rows[0] = json.dumps(value, sort_keys=True)
                        elif case == 'missing_row':
                            rows.pop()
                        elif case == 'frame_override':
                            value = json.loads(rows[0])
                            value['frame_id_override'] = 'base_link'
                            rows[0] = json.dumps(value, sort_keys=True)
                        else:
                            value = json.loads(rows[0])
                            value['authorizes_motion'] = True
                            rows[0] = json.dumps(value, sort_keys=True)
                        typed.write_text('\n'.join(rows) + '\n', encoding='utf-8')
                        manifest = json.loads(collector.read_text(encoding='utf-8'))
                        manifest['received_frames'] = len(rows)
                        manifest['unique_sequence_frames'] = len(rows)
                        manifest['output']['size_bytes'] = typed.stat().st_size
                        manifest['output']['sha256'] = _sha(typed)
                        collector.write_text(
                            json.dumps(manifest, sort_keys=True), encoding='utf-8')
                    elif case == 'typed_hash':
                        manifest = json.loads(collector.read_text(encoding='utf-8'))
                        manifest['output']['sha256'] = '0' * 64
                        collector.write_text(
                            json.dumps(manifest, sort_keys=True), encoding='utf-8')
                    elif case == 'raw_hash':
                        value = json.loads(inspection.read_text(encoding='utf-8'))
                        value['source_capture']['sha256'] = '0' * 64
                        inspection.write_text(
                            json.dumps(value, sort_keys=True), encoding='utf-8')
                    else:
                        manifest = json.loads(collector.read_text(encoding='utf-8'))
                        if case == 'collector_motion':
                            manifest['authorizes_motion'] = True
                        elif case == 'collector_extra':
                            manifest['publisher'] = '/cmd_vel'
                        elif case == 'collector_publisher':
                            manifest['publishes_ros_messages'] = True
                        elif case == 'collector_topic':
                            manifest['topic'] = '/cmd_vel'
                        else:
                            manifest['forbidden_control_topics'] = ['/cmd_vel']
                        collector.write_text(
                            json.dumps(manifest, sort_keys=True), encoding='utf-8')
                    if case == 'stamp':
                        report = _bind(
                            (typed, collector, raw, inspection))
                        self.assertEqual(30, report['typed_frame_count'])
                        self.assertEqual(30, report['raw_bundle_count'])
                        self.assertEqual(1, report['unpaired_typed_count'])
                        self.assertEqual(
                            1, report['unpaired_raw_bundle_count'])
                        self.assertAlmostEqual(
                            1 / 30, report['unpaired_rate'])
                    else:
                        with self.assertRaises(ValueError):
                            _bind((typed, collector, raw, inspection))

    def test_cli_writes_exclusively_and_source_is_read_only(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            typed, collector, raw, inspection = _fixture(root)
            output = root / 'binding.json'
            args = [
                '--typed-frames', str(typed),
                '--collector-manifest', str(collector),
                '--raw-bag', str(raw), '--raw-inspection', str(inspection),
                '--scene', 'background', '--capture-id', 'capture-background',
                '--task-id', 'readonly-background',
                '--started-unix-sec', '1', '--ended-unix-sec', '2',
                '--release-id', 'release-v2-0001',
                '--source-set-sha256', 'a' * 64,
                '--bottle-model-sha256', 'b' * 64,
                '--trash-bin-model-sha256', 'c' * 64,
                '--output', str(output),
            ]
            self.assertEqual(0, main(args))
            with self.assertRaisesRegex(SystemExit, 'must not already exist'):
                main(args)
            source = Path(create_binding.__code__.co_filename).read_text(
                encoding='utf-8')
            for token in (
                    'rclpy', 'rospy', 'create_publisher(', '.publish(',
                    'create_subscription(', 'Twist(', 'NavigateToPose('):
                self.assertNotIn(token, source)


if __name__ == '__main__':
    unittest.main()
