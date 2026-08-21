"""Pure-software tests for the host-owned ROS1 final-readiness intake."""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
_IMPORT_PATH_BEFORE = list(sys.path)
try:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from limo_cleanup_perception import (  # noqa: E402
        ros1_noetic_field_readiness as GATE)
    from limo_cleanup_perception import (  # noqa: E402
        ros1_semantic_evidence_producer as PRODUCER)
finally:
    sys.path[:] = _IMPORT_PATH_BEFORE


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False) + '\n',
        encoding='utf-8')


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False) + '\n'
        for value in values), encoding='utf-8')


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _metadata_with(metadata, **changes):
    values = {
        name: getattr(metadata, name, None)
        for name in (
            'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_nlink',
            'st_mode', 'st_uid', 'st_gid', 'st_file_attributes')}
    values.update(changes)
    return SimpleNamespace(**values)


class _Fixture:

    def __init__(self, root):
        self.root = Path(root)
        self.prefix = self.root / 'noetic'
        self.python_root = self.prefix / 'lib/python3/dist-packages'
        self.python_root.mkdir(parents=True)
        self.rosbag_path = self.python_root / 'rosbag/__init__.py'
        self.rosbag_path.parent.mkdir()
        self.rosbag_path.write_text(
            '# trusted rosbag fixture\n', encoding='utf-8')
        self.rosbag_bag_path = self.rosbag_path.with_name('bag.py')
        self.rosbag_bag_path.write_text(
            '# trusted rosbag bag fixture\n', encoding='utf-8')
        self.probe_path = self.root / 'anchored/rosbag1_isolated_probe.py'
        self.indexer_path = self.root / 'anchored/rosbag1_rgbd_indexer.py'
        self.formal_manifest_path = self.root / 'anchored/formal_manifest.json'
        self.canonical_path = self.root / 'authority/canonical.json'
        self.install_path = self.root / 'authority/install.json'
        for path, content in (
                (self.probe_path, '# probe source\n'),
                (self.indexer_path, '# indexer source\n')):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        _write_json(self.formal_manifest_path, {'schema_version': 1})
        _write_json(self.canonical_path, {'test_only': True})
        _write_json(self.install_path, {'validated_pass': False})
        self.model_manifest_path = self.root / 'authority/model_manifest.json'
        self.model_paths = {
            'plastic_bottle': self.root / 'models/bottle.engine',
            'trash_bin': self.root / 'models/bin.engine',
        }
        for name, path in self.model_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('test-model:' + name).encode('utf-8'))
        self.model_artifacts = {
            name: GATE.regular_file_identity(path)
            for name, path in self.model_paths.items()}
        _write_json(self.model_manifest_path, {
            'schema_version': 1,
            'model_artifacts': self.model_artifacts,
        })
        self.model_manifest = GATE.regular_file_identity(
            self.model_manifest_path)
        self.model_hashes = {
            name: identity['sha256']
            for name, identity in self.model_artifacts.items()}
        self.model_set_sha = GATE._model_set_sha256(self.model_hashes)
        self.install_sha = GATE.regular_file_identity(
            self.install_path)['sha256']
        self.probe_calls = []
        self.extra_probe_bundles = 0
        self.semantic_producer_authorities = {}
        self.scenes = {}
        base_stamp = 1_700_000_000_000_000_000
        for index, scene_name in enumerate(GATE.SCENES):
            self.scenes[scene_name] = self._scene(
                scene_name, index, base_stamp + index * 10_000_000_000)
        self.request = {
            'schema_version': 1,
            'marker': GATE.REQUEST_MARKER,
            'request_id': 'test-only-readiness-request-v1',
            'mode': GATE.TEST_ONLY_MODE,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'runtime_family': 'ROS1',
            'ros_distro': 'noetic',
            'release_binding': {
                'release_id': 'test-release-v1',
                'source_manifest_artifact_sha256': '1' * 64,
                'source_set_sha256': '2' * 64,
                'manifest_generated_at_unix_sec': 1_700_000_000.0,
            },
            'model_artifact_sha256': dict(self.model_hashes),
            'model_set_sha256': self.model_set_sha,
            'canonical_source_admission': GATE.regular_file_identity(
                self.canonical_path),
            'field_install_evidence': GATE.regular_file_identity(
                self.install_path),
            'scenes': self.scenes,
        }
        self.request_path = self.root / 'request.json'
        self.authority_path = self.root / 'authority.json'
        self.authority = None
        self.authority_identity = None
        self.refresh()
        for scene_name in GATE.SCENES:
            self._prepare_semantic_producer_scene(scene_name)
        self.probe_calls.clear()
        self.refresh()

    @staticmethod
    def _targets(scene_name):
        targets = []
        if scene_name != 'background':
            targets.append({
                'observation_id': scene_name + '-bin',
                'object_class': 'trash_bin',
                'confidence': 0.99,
                'valid': True,
                'actionable': False,
                'status': 'observed',
                'error_code': '',
                'position': {'x': 1.0, 'y': 0.0, 'z': 1.0},
                'size': {'x': 0.5, 'y': 0.5, 'z': 0.8},
                'bbox': [100.0, 100.0, 300.0, 300.0],
                'depth_m': 1.0,
                'depth_valid_pixels': 100,
                'depth_total_pixels': 100,
                'depth_valid_ratio': 1.0,
                'source': 'test_fixture_detector',
                'position_semantics': 'base_link_from_independent_extrinsics',
            })
        if scene_name in ('bottle_in_bin', 'bottle_outside'):
            targets.append({
                'observation_id': scene_name + '-bottle',
                'object_class': 'plastic_bottle',
                'confidence': 0.98,
                'valid': True,
                'actionable': scene_name == 'bottle_outside',
                'status': ('already_in_bin' if scene_name == 'bottle_in_bin'
                           else 'active'),
                'error_code': '',
                'position': {'x': 0.5, 'y': 0.0, 'z': 1.0},
                'size': {'x': 0.1, 'y': 0.1, 'z': 0.25},
                'bbox': [20.0, 20.0, 80.0, 120.0],
                'depth_m': 1.0,
                'depth_valid_pixels': 100,
                'depth_total_pixels': 100,
                'depth_valid_ratio': 1.0,
                'source': 'test_fixture_detector',
                'position_semantics': 'base_link_from_independent_extrinsics',
            })
        return targets

    def _scene(self, scene_name, index, stamp_ns):
        group = self.root / 'scenes' / scene_name
        group.mkdir(parents=True)
        capture_id = 'capture-{}-{}'.format(index, scene_name)
        task_id = 'task-{}-{}'.format(index, scene_name)
        bundle_id = _sha('bundle:' + scene_name)
        raw_path = group / 'capture.bag'
        raw_path.write_bytes(b'#ROSBAG V2.0\nunit-test-record-chain')
        targets = self._targets(scene_name)
        frame = {
            'schema_version': 1,
            'read_only': True,
            'received_unix_sec': stamp_ns / 1e9 + 0.2,
            'transport_latency_sec': 0.2,
            'stamp': {
                'sec': stamp_ns // 1_000_000_000,
                'nanosec': stamp_ns % 1_000_000_000,
            },
            'frame_id': 'camera_color_optical_frame',
            'task_id': task_id,
            'capture_id': capture_id,
            'bundle_id': bundle_id,
            'model_binding_sha256': self.model_set_sha,
            'sequence': 1,
            'valid': True,
            'status': 'targets_valid' if targets else 'no_targets',
            'error_code': '',
            'sync_span_sec': 0.001,
            'processing_latency_sec': 0.1,
            'tf_target_frame': 'base_link',
            'tf_valid': True,
            'tf_transform_applied': True,
            'tf_status': 'applied',
            'tf_error_code': '',
            'targets': targets,
            'scene': scene_name,
        }
        frames_path = group / 'typed_frames.jsonl'
        _write_jsonl(frames_path, [frame])
        frames_identity = GATE.regular_file_identity(frames_path)
        collector_path = group / 'collector.json'
        _write_json(collector_path, {
            'schema_version': 1,
            'collector_kind': GATE.ARTIFACT_MARKERS['collector_manifest'],
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'scene': scene_name,
            'topic': GATE.EXPECTED_COLLECTOR_TOPIC,
            'message_type': GATE.EXPECTED_COLLECTOR_MESSAGE_TYPE,
            'task_id': task_id,
            'max_frames': 1,
            'duration_sec': 1.0,
            'received_frames': 1,
            'unique_frames': 1,
            'duplicate_sequences': 0,
            'duplicate_bundle_ids': 0,
            'serialization_errors': 0,
            'interrupted': False,
            'completed_minimum': True,
            'completed_requested_frames': True,
            'output': frames_identity,
        })
        stream_hashes = {
            role: _sha('{}:{}'.format(scene_name, role))
            for role in ('rgb', 'raw_depth', 'rgb_camera_info',
                         'depth_camera_info')}
        binding_path = group / 'typed_raw_binding.json'
        association = {
            'typed_row_index': 0,
            'sequence': 1,
            'stamp_ns': stamp_ns,
            'bundle_id': bundle_id,
            'typed_frame_sha256': GATE._canonical_sha256(frame),
            'raw_bundle_index': 1,
            'raw_stream_payload_sha256': stream_hashes,
        }
        _write_json(binding_path, {
            'schema_version': 2,
            'report_kind': GATE.ARTIFACT_MARKERS['typed_raw_binding'],
            'evidence_scope': 'test_only_rosbag1_typed_raw_binding',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'binding_sha256': '6' * 64,
            'capture_id': capture_id,
            'task_id': task_id,
            'scene': scene_name,
            'model_binding_sha256': self.model_set_sha,
            'artifacts': {},
            'provenance': {},
            'typed_frame_count': 1,
            'raw_bundle_count': 1,
            'association_count': 1,
            'minimum_scene_frames': 1,
            'unpaired_typed_count': 0,
            'unpaired_raw_bundle_count': 0,
            'associations': [association],
            'test_only': True,
            'validated_pass': True,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
            'delivery_ready': False,
            'failures': [],
        })
        common = {
            'schema_version': 1,
            'scene': scene_name,
            'capture_id': capture_id,
            'task_id': task_id,
            'ros1_field_install_sha256': self.install_sha,
            'model_binding_sha256': self.model_set_sha,
            'synthetic_test_only': True,
        }
        key = (1, stamp_ns, bundle_id)
        annotations = [{
            'instance_id': target['observation_id'],
            'object_class': target['object_class'],
            'bbox': target['bbox'],
            'relation': (
                'container' if target['object_class'] == 'trash_bin'
                else ('inside_bin' if scene_name == 'bottle_in_bin'
                      else 'outside_bin')),
        } for target in targets]
        ground_record = {
            'sequence': 1, 'stamp_ns': stamp_ns,
            'bundle_id': bundle_id,
            'typed_frame_sha256': GATE._canonical_sha256(frame),
            'rgb_payload_sha256': stream_hashes['rgb'],
            'annotations': annotations,
        }
        class_metrics = GATE._class_metrics(
            {key: ground_record}, {key: (0, frame)})
        ground_path = group / 'ground_truth.json'
        _write_json(ground_path, {
            **common,
            'report_kind': GATE.ARTIFACT_MARKERS['ground_truth'],
            'complete': True,
            'unique_frames': 1,
            'annotation_count': len(annotations),
            'class_metrics': class_metrics,
            'records': [ground_record],
        })
        extrinsics_payload = {
            'source_frame': 'camera_color_optical_frame',
            'target_frame': 'base_link',
            'translation_m': [0.0, 0.0, 0.0],
            'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
        }
        extrinsics_path = group / 'extrinsics.json'
        _write_json(extrinsics_path, {
            **common,
            'report_kind': GATE.ARTIFACT_MARKERS['extrinsics_reference'],
            **extrinsics_payload,
            'transform_sha256': GATE._canonical_sha256(extrinsics_payload),
            'measurement_method': 'independent_fixture_measurement',
            'operator_id': 'fixture-operator',
            'reviewer_id': 'fixture-reviewer',
            'measured_at_unix_sec': stamp_ns / 1e9 - 10.0,
            'reviewed_at_unix_sec': stamp_ns / 1e9 - 5.0,
        })
        transform_sha = GATE._canonical_sha256(extrinsics_payload)
        target_transforms = [{
            'observation_id': target['observation_id'],
            'input_position_m': [
                target['position']['x'], target['position']['y'],
                target['position']['z']],
            'output_position_m': [
                target['position']['x'], target['position']['y'],
                target['position']['z']],
            'extrinsics_transform_sha256': transform_sha,
        } for target in targets]
        tf_path = group / 'tf.json'
        _write_json(tf_path, {
            **common,
            'report_kind': GATE.ARTIFACT_MARKERS['tf_records'],
            'source_frame': 'camera_color_optical_frame',
            'target_frame': 'base_link',
            'transform_applied': True,
            'mixed_tf': False,
            'tf_valid_frames': 1,
            'xyz_valid_frames': 1,
            'records': [{
                'sequence': 1, 'stamp_ns': stamp_ns,
                'bundle_id': bundle_id,
                'topic': '/tf_static', 'message_id': 1,
                'connection_id': 1, 'transform_index': 0,
                'callerid': '/camera/camera',
                'transform_stamp_ns': 0,
                'parent_frame_id': 'camera_link',
                'child_frame_id': 'camera_color_optical_frame',
                'lookup_source_frame': 'camera_color_optical_frame',
                'lookup_target_frame': 'base_link',
                'translation_m': [0.0, 0.0, 0.0],
                'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
                'serialized_sha256': _sha('raw-tf:' + scene_name),
                'lookup_succeeded': True,
                'transform_applied': True,
                'output_frame': 'base_link',
                'extrinsics_transform_sha256': transform_sha,
                'target_transforms': target_transforms,
            }],
        })
        xyz_records = [{
            'sequence': 1, 'stamp_ns': stamp_ns, 'bundle_id': bundle_id,
            'observation_id': target['observation_id'],
            'reference_xyz_m': [
                target['position']['x'], target['position']['y'],
                target['position']['z']],
            'measured_xyz_m': [
                target['position']['x'], target['position']['y'],
                target['position']['z']],
            'error_m': 0.0,
        } for target in targets]
        xyz_path = group / 'xyz.json'
        _write_json(xyz_path, {
            **common,
            'report_kind': GATE.ARTIFACT_MARKERS['xyz_records'],
            'not_applicable': not bool(xyz_records),
            'sample_count': len(xyz_records),
            'max_error_m': 0.0 if xyz_records else None,
            'p95_error_m': 0.0 if xyz_records else None,
            'records': xyz_records,
        })
        depth_records = [{
            'sequence': 1, 'stamp_ns': stamp_ns, 'bundle_id': bundle_id,
            'observation_id': target['observation_id'],
            'reference_depth_m': target['depth_m'],
            'measured_depth_m': target['depth_m'],
            'valid_pixels': target['depth_valid_pixels'],
            'total_pixels': target['depth_total_pixels'],
            'valid_ratio': target['depth_valid_ratio'],
            'valid': True,
            'error_m': 0.0,
        } for target in targets]
        depth_path = group / 'depth.json'
        _write_json(depth_path, {
            **common,
            'report_kind': GATE.ARTIFACT_MARKERS['depth_records'],
            'not_applicable': not bool(depth_records),
            'sample_count': len(depth_records),
            'valid_rate': 1.0 if depth_records else None,
            'max_error_m': 0.0 if depth_records else None,
            'p95_error_m': 0.0 if depth_records else None,
            'records': depth_records,
        })
        latency_path = group / 'latency.json'
        _write_json(latency_path, {
            **common,
            'report_kind': GATE.ARTIFACT_MARKERS['latency_records'],
            'sample_count': 1,
            'max_latency_sec': 0.2,
            'p95_end_to_end_sec': 0.2,
            'p95_processing_sec': 0.1,
            'p95_sync_sec': 0.001,
            'records': [{
                'sequence': 1, 'stamp_ns': stamp_ns,
                'bundle_id': bundle_id,
                'sensor_stamp_sec': stamp_ns / 1e9,
                'inference_started_unix_sec': stamp_ns / 1e9 + 0.05,
                'inference_ended_unix_sec': stamp_ns / 1e9 + 0.15,
                'collector_received_unix_sec': stamp_ns / 1e9 + 0.2,
                'sync_span_sec': 0.001,
                'processing_latency_sec': 0.1,
                'transport_latency_sec': 0.2,
                'end_to_end_latency_sec': 0.2,
            }],
        })
        artifacts = {
            'raw_bag': GATE.regular_file_identity(raw_path),
            'collector_manifest': GATE.regular_file_identity(collector_path),
            'typed_frames': frames_identity,
            'typed_raw_binding': GATE.regular_file_identity(binding_path),
            'ground_truth': GATE.regular_file_identity(ground_path),
            'extrinsics_reference': GATE.regular_file_identity(
                extrinsics_path),
            'tf_records': GATE.regular_file_identity(tf_path),
            'xyz_records': GATE.regular_file_identity(xyz_path),
            'depth_records': GATE.regular_file_identity(depth_path),
            'latency_records': GATE.regular_file_identity(latency_path),
        }
        return {
            'scene': scene_name,
            'capture_id': capture_id,
            'task_id': task_id,
            'bundle_id': _sha('scene-envelope:' + scene_name),
            'capture_window': {
                'record_start_ns': stamp_ns - 1,
                'record_end_ns': stamp_ns + 1,
                'header_start_ns': stamp_ns,
                'header_end_ns': stamp_ns,
            },
            'collector_request': {
                'topic': GATE.EXPECTED_COLLECTOR_TOPIC,
                'message_type': GATE.EXPECTED_COLLECTOR_MESSAGE_TYPE,
                'max_frames': 1,
                'duration_sec': 1.0,
            },
            'probe_output_path': str(group / 'probe_output.json'),
            'artifacts': artifacts,
        }

    def _planned_probe_call(self, scene_name):
        scene = self.request['scenes'][scene_name]
        return {
            'bag_path': Path(scene['artifacts']['raw_bag']['path']),
            'expected_bag_identity': scene['artifacts']['raw_bag'],
            'noetic_prefix': self.prefix,
            'expected_rosbag_module_identity': self.authority['rosbag_module'],
            'expected_rosbag_decoder_closure': self.authority[
                'rosbag_decoder_closure'],
            'expected_indexer_module_identity': self.authority[
                'rosbag1_indexer_source'],
            'formal_manifest_path': self.formal_manifest_path,
            'expected_formal_manifest_identity': self.authority[
                'formal_manifest'],
            'expected_probe_source_identity': self.authority[
                'isolated_probe_source'],
            'expected_sys_executable_identity': self.authority[
                'python_executable_target'],
            'capture_id': scene['capture_id'],
            'scene': scene_name,
            'output_path': Path(scene['probe_output_path']),
            'admission_mode': 'test_only',
            'python_root_relative': self.authority['python_root_relative'],
            'trusted_system_python_roots': [],
        }

    def _prepare_semantic_producer_scene(self, scene_name):
        scene = self.request['scenes'][scene_name]
        probe_result = self.fake_probe(**self._planned_probe_call(scene_name))
        probe_identity = probe_result['output_identity']
        frame_path = Path(scene['artifacts']['typed_frames']['path'])
        frame = json.loads(frame_path.read_text(encoding='utf-8').strip())
        stamp_ns = (
            frame['stamp']['sec'] * 1_000_000_000
            + frame['stamp']['nanosec'])
        binding = json.loads(Path(
            scene['artifacts']['typed_raw_binding']['path']
        ).read_text(encoding='utf-8'))
        stream_hashes = binding['associations'][0][
            'raw_stream_payload_sha256']
        ground = json.loads(Path(
            scene['artifacts']['ground_truth']['path']
        ).read_text(encoding='utf-8'))
        metadata_root = self.root / 'producer_meta' / scene_name
        metadata_root.mkdir(parents=True)
        ledger_path = metadata_root / 'measurement_ledger.json'
        ledger = {
            'schema_version': 1,
            'marker': PRODUCER.LEDGER_MARKER,
            'scene': scene_name,
            'capture_id': scene['capture_id'],
            'task_id': scene['task_id'],
            'raw_bag': scene['artifacts']['raw_bag'],
            'probe_artifact': probe_identity,
            'typed_frames': scene['artifacts']['typed_frames'],
            'typed_raw_binding': scene['artifacts']['typed_raw_binding'],
            'canonical_source_admission': self.request[
                'canonical_source_admission'],
            'field_install_evidence': self.request['field_install_evidence'],
            'model_manifest': self.model_manifest,
            'model_artifacts': self.model_artifacts,
            'model_set_sha256': self.model_set_sha,
            'ground_truth_operator_id': 'test-truth-operator',
            'ground_truth_reviewer_id': 'test-truth-reviewer',
            'extrinsics': {
                'source_frame': 'camera_color_optical_frame',
                'target_frame': 'base_link',
                'translation_m': [0.0, 0.0, 0.0],
                'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
                'measurement_method': 'test-independent-measurement',
                'operator_id': 'test-extrinsics-operator',
                'reviewer_id': 'test-extrinsics-reviewer',
                'measured_at_unix_sec': stamp_ns / 1e9 - 10.0,
                'reviewed_at_unix_sec': stamp_ns / 1e9 - 5.0,
            },
            'records': [{
                'sequence': frame['sequence'],
                'stamp_ns': stamp_ns,
                'bundle_id': frame['bundle_id'],
                'typed_frame_sha256': GATE._canonical_sha256(frame),
                'rgb_payload_sha256': stream_hashes['rgb'],
                'annotations': ground['records'][0]['annotations'],
                'observations': [{
                    'observation_id': target['observation_id'],
                    'camera_xyz_m': [
                        target['position']['x'], target['position']['y'],
                        target['position']['z']],
                    'reference_xyz_m': [
                        target['position']['x'], target['position']['y'],
                        target['position']['z']],
                    'reference_depth_m': target['depth_m'],
                } for target in frame['targets']],
                'inference_started_unix_sec': stamp_ns / 1e9 + 0.05,
                'inference_ended_unix_sec': stamp_ns / 1e9 + 0.15,
            }],
        }
        review_authority_path = metadata_root / 'ground_truth_review.json'
        review_authority = {
            'schema_version': 1,
            'marker': 'LIMO_ROS1_GROUND_TRUTH_REVIEW_AUTHORITY_V1',
            'scope': 'independent_ground_truth_review',
            'scene': scene_name,
            'capture_id': scene['capture_id'],
            'task_id': scene['task_id'],
            'raw_bag': scene['artifacts']['raw_bag'],
            'typed_frames': scene['artifacts']['typed_frames'],
            'operator_id': ledger['ground_truth_operator_id'],
            'reviewer_id': ledger['ground_truth_reviewer_id'],
            'reviewed_at_unix_sec': stamp_ns / 1e9 - 1.0,
            'synthetic_test_only': True,
        }
        _write_json(review_authority_path, review_authority)
        review_authority_identity = GATE.regular_file_identity(
            review_authority_path)
        measurement_authority_path = (
            metadata_root / 'measurement_reference.json')
        observation_ids = sorted(
            target['observation_id'] for target in frame['targets'])
        measurement_authority = {
            'schema_version': 1,
            'marker': 'LIMO_ROS1_MEASUREMENT_REFERENCE_AUTHORITY_V1',
            'scope': 'independent_extrinsics_xyz_depth_reference',
            'scene': scene_name,
            'capture_id': scene['capture_id'],
            'task_id': scene['task_id'],
            'raw_bag': scene['artifacts']['raw_bag'],
            'probe_artifact': probe_identity,
            'typed_frames': scene['artifacts']['typed_frames'],
            'extrinsics_operator_id': ledger['extrinsics']['operator_id'],
            'extrinsics_reviewer_id': ledger['extrinsics']['reviewer_id'],
            'measurement_method': ledger['extrinsics']['measurement_method'],
            'observation_ids': observation_ids,
            'authorized_at_unix_sec': stamp_ns / 1e9 - 1.0,
            'synthetic_test_only': True,
        }
        _write_json(measurement_authority_path, measurement_authority)
        measurement_authority_identity = GATE.regular_file_identity(
            measurement_authority_path)
        ledger['ground_truth_review_authority'] = review_authority_identity
        ledger['measurement_reference_authority'] = (
            measurement_authority_identity)
        _write_json(ledger_path, ledger)
        output_root = self.root / 'producer_outputs'
        output_root.mkdir(exist_ok=True)
        output_directory = output_root / scene_name
        producer_request_path = metadata_root / 'request.json'
        producer_request = {
            'schema_version': 1,
            'marker': PRODUCER.REQUEST_MARKER,
            'request_id': 'test-producer-request-' + scene_name,
            'mode': PRODUCER.TEST_ONLY_MODE,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'scene': scene_name,
            'capture_id': scene['capture_id'],
            'task_id': scene['task_id'],
            'raw_bag': scene['artifacts']['raw_bag'],
            'probe_artifact': probe_identity,
            'typed_frames': scene['artifacts']['typed_frames'],
            'typed_raw_binding': scene['artifacts']['typed_raw_binding'],
            'measurement_ledger': GATE.regular_file_identity(ledger_path),
            'canonical_source_admission': self.request[
                'canonical_source_admission'],
            'field_install_evidence': self.request['field_install_evidence'],
            'model_manifest': self.model_manifest,
            'model_artifacts': self.model_artifacts,
            'model_set_sha256': self.model_set_sha,
            'ground_truth_review_authority': review_authority_identity,
            'measurement_reference_authority': (
                measurement_authority_identity),
            'output_directory': str(output_directory.absolute()),
        }
        _write_json(producer_request_path, producer_request)
        producer_authority_path = metadata_root / 'authority.json'
        producer_authority = {
            'schema_version': 1,
            'marker': PRODUCER.AUTHORITY_MARKER,
            'authority_id': 'test-producer-authority-' + scene_name,
            'scope': 'ros1_noetic_semantic_evidence_producer',
            'test_only': True,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'request_identity': GATE.regular_file_identity(
                producer_request_path),
            'producer_source': GATE.regular_file_identity(
                Path(PRODUCER.__file__)),
            'field_readiness_source': GATE.regular_file_identity(
                Path(GATE.__file__)),
            'canonical_source_admission': self.request[
                'canonical_source_admission'],
            'field_install_evidence': self.request['field_install_evidence'],
            'model_manifest': self.model_manifest,
            'model_artifacts': self.model_artifacts,
            'model_set_sha256': self.model_set_sha,
            'ground_truth_review_authority': review_authority_identity,
            'measurement_reference_authority': (
                measurement_authority_identity),
            'allowed_output_root': str(output_root.resolve()),
        }
        _write_json(producer_authority_path, producer_authority)
        producer_authority_identity = GATE.regular_file_identity(
            producer_authority_path)
        result = PRODUCER.produce_semantic_evidence(
            producer_request_path, producer_authority_path,
            producer_authority_identity, output_directory, test_only=True)
        for role, identity in result['outputs'].items():
            scene['artifacts'][role] = identity
        scene['artifacts']['semantic_producer_report'] = result[
            'report_identity']
        self.semantic_producer_authorities[scene_name] = (
            producer_authority_identity)
        Path(scene['probe_output_path']).unlink()

    def refresh(self):
        _write_json(self.request_path, self.request)
        self.authority = {
            'schema_version': 1,
            'marker': GATE.AUTHORITY_MARKER,
            'authority_id': 'test-only-authority-v1',
            'scope': 'ros1_noetic_field_readiness_intake',
            'test_only': self.request['mode'] == GATE.TEST_ONLY_MODE,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'request_identity': GATE.regular_file_identity(self.request_path),
            'canonical_source_admission': self.request[
                'canonical_source_admission'],
            'field_install_evidence': self.request['field_install_evidence'],
            'formal_manifest': GATE.regular_file_identity(
                self.formal_manifest_path),
            'isolated_probe_source': GATE.regular_file_identity(
                self.probe_path),
            'rosbag1_indexer_source': GATE.regular_file_identity(
                self.indexer_path),
            'rosbag_module': GATE.regular_file_identity(self.rosbag_path),
            'rosbag_decoder_closure': {
                'rosbag': GATE.regular_file_identity(self.rosbag_path),
                'rosbag.bag': GATE.regular_file_identity(
                    self.rosbag_bag_path),
            },
            'python_executable_target': GATE.regular_file_identity(
                Path(sys.executable).resolve(strict=True)),
            'trusted_system_python_roots': [],
            'noetic_prefix': str(self.prefix.resolve()),
            'python_root_relative': 'lib/python3/dist-packages',
            'scene_set': list(GATE.SCENES),
            'artifact_markers': dict(GATE.ARTIFACT_MARKERS),
            'semantic_producer_source': GATE.regular_file_identity(
                Path(PRODUCER.__file__)),
            'semantic_producer_authorities': dict(
                self.semantic_producer_authorities),
        }
        _write_json(self.authority_path, self.authority)
        self.authority_identity = GATE.regular_file_identity(
            self.authority_path)

    def update_artifact(self, scene_name, role, value, jsonl=False):
        declaration = self.request['scenes'][scene_name]['artifacts'][role]
        path = Path(declaration['path'])
        if jsonl:
            _write_jsonl(path, value)
        else:
            _write_json(path, value)
        self.request['scenes'][scene_name]['artifacts'][role] = (
            GATE.regular_file_identity(path))
        self.refresh()

    def fake_probe(self, **keywords):
        self.probe_calls.append(keywords)
        scene = keywords['scene']
        scene_value = self.request['scenes'][scene]
        frame_path = Path(scene_value['artifacts']['typed_frames']['path'])
        frame_text = frame_path.read_text(encoding='utf-8').strip()
        if frame_text:
            frame = json.loads(frame_text)
            stamp_ns = (
                frame['stamp']['sec'] * 1_000_000_000
                + frame['stamp']['nanosec'])
        else:
            stamp_ns = scene_value['capture_window']['header_start_ns']
        stream_hashes = json.loads(Path(
            scene_value['artifacts']['typed_raw_binding']['path']
        ).read_text(encoding='utf-8'))['associations'][0][
            'raw_stream_payload_sha256']
        output = Path(keywords['output_path'])
        executable_target = keywords['expected_sys_executable_identity']
        executable_admission = {
            'entry_path': executable_target['path'],
            'chain': [{
                'path': executable_target['path'],
                'kind': 'regular_target',
                'link_target': None,
                'mode': 0,
                'device': 0,
                'inode': 0,
            }],
            'target_identity': executable_target,
        }
        artifact = {
            'schema_version': 1,
            'marker': GATE.PROBE_ARTIFACT_MARKER,
            'report_kind': 'isolated_rosbag1_raw_records',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'delivery_ready': False,
            'request_id': _sha('probe-request:' + scene),
            'request_sha256': _sha('probe-request-bytes:' + scene),
            'bag_identity': keywords['expected_bag_identity'],
            'noetic_prefix': str(Path(keywords['noetic_prefix']).resolve()),
            'python_root': str((Path(keywords['noetic_prefix']) /
                                keywords['python_root_relative']).resolve()),
            'rosbag_module_identity': keywords[
                'expected_rosbag_module_identity'],
            'indexer_module_identity': keywords[
                'expected_indexer_module_identity'],
            'formal_manifest_identity': keywords[
                'expected_formal_manifest_identity'],
            'probe_source_identity': self.authority['isolated_probe_source'],
            'sys_executable_identity': executable_target,
            'parent_executable_admission': executable_admission,
            'child_executable_admission': executable_admission,
            'capture_id': keywords['capture_id'],
            'scene': scene,
            'connections': [{'connection_id': 1}],
            'messages': [{'message_id': 1}],
            'connection_count': 1,
            'message_count': 1,
            'total_payload_bytes': 1,
            'formal_report': {
                'storage_identifier': 'rosbag1-v2',
                'mode': 'formal_camera_only',
                'inspection_passed': True,
                'formal_acceptance': False,
                'shared_graph': False,
                'mixed_tf': False,
                'not_in_four_scene_denominator': True,
                'delivery_ready': False,
                'capture_id': keywords['capture_id'],
                'scene': scene,
                'capture_window': scene_value['capture_window'],
                'accepted_bundles': [{
                    'index': 1,
                    'header_stamps_ns': {'rgb': stamp_ns},
                    'stream_record_timestamps_ns': {'rgb': stamp_ns},
                    'stream_payload_sha256': stream_hashes,
                }],
                'tf_graph': {
                    'camera_only': True,
                    'base_chain_required': False,
                    'transforms': [{
                        'topic': '/tf_static',
                        'message_id': 1,
                        'connection_id': 1,
                        'transform_index': 0,
                        'callerid': '/camera/camera',
                        'stamp_ns': 0,
                        'parent_frame_id': 'camera_link',
                        'child_frame_id': 'camera_color_optical_frame',
                        'translation_m': [0.0, 0.0, 0.0],
                        'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
                        'serialized_sha256': _sha('raw-tf:' + scene),
                    }],
                },
            },
            'loaded_nonstdlib_module_provenance': [],
            'test_only': True,
            'algorithm_validated': True,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
        }
        for offset in range(self.extra_probe_bundles):
            artifact['formal_report']['accepted_bundles'].append({
                'index': 2 + offset,
                'header_stamps_ns': {'rgb': stamp_ns},
                'stream_record_timestamps_ns': {'rgb': stamp_ns},
                'stream_payload_sha256': dict(stream_hashes),
            })
        _write_json(output, artifact)
        identity = GATE.regular_file_identity(output)
        return {
            'validated_pass': False,
            'algorithm_validated': True,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'delivery_ready': False,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
            'argv': [executable_target['path']],
            'sys_executable_identity': executable_target,
            'parent_executable_admission': executable_admission,
            'child_executable_admission': executable_admission,
            'output_identity': identity,
            'failures': [],
        }

    def evaluate(self, runner=None, anchor=None):
        return GATE.evaluate_field_readiness(
            self.request_path, self.authority_path,
            self.authority_identity if anchor is None else anchor,
            probe_runner=self.fake_probe if runner is None else runner)


class Ros1NoeticFieldReadinessTest(unittest.TestCase):

    @staticmethod
    def _seal_authority(fixture):
        _write_json(fixture.authority_path, fixture.authority)
        fixture.authority_identity = GATE.regular_file_identity(
            fixture.authority_path)

    def test_test_only_algorithm_pass_never_enters_field_denominator(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.evaluate()
        self.assertTrue(result['algorithm_validated'], result)
        self.assertTrue(result['validator_unit_test_pass'])
        self.assertFalse(result['validated_pass'])
        self.assertFalse(result['formal_acceptance'])
        self.assertTrue(result['not_in_four_scene_denominator'])
        self.assertFalse(result['field_evidence_admitted'])
        self.assertFalse(result['delivery_ready'])
        self.assertEqual(4, len(fixture.probe_calls))
        for call in fixture.probe_calls:
            self.assertEqual('test_only', call['admission_mode'])
            self.assertEqual(
                fixture.authority['rosbag_decoder_closure'],
                call['expected_rosbag_decoder_closure'])
            self.assertEqual(
                fixture.authority['isolated_probe_source'],
                call['expected_probe_source_identity'])
            self.assertEqual(
                fixture.authority['python_executable_target'],
                call['expected_sys_executable_identity'])

    def test_test_only_fake_probe_cannot_self_report_formal_denominator(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)

            def self_reporting_probe(**keywords):
                result = dict(fixture.fake_probe(**keywords))
                output = Path(result['output_identity']['path'])
                artifact = json.loads(output.read_text(encoding='utf-8'))
                artifact['formal_report']['formal_acceptance'] = True
                artifact['formal_report'][
                    'not_in_four_scene_denominator'] = False
                _write_json(output, artifact)
                result['output_identity'] = GATE.regular_file_identity(output)
                return result

            result = fixture.evaluate(runner=self_reporting_probe)
        self.assertIn(
            'isolated_probe_formal_report_invalid:background',
            result['failures'])
        self.assertFalse(result['formal_acceptance'])
        self.assertTrue(result['not_in_four_scene_denominator'])
        self.assertFalse(result['delivery_ready'])

    def test_external_authority_anchor_mismatch_fails_closed(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            bad = dict(fixture.authority_identity, sha256='0' * 64)
            result = fixture.evaluate(anchor=bad)
        self.assertIn('authority_external_anchor_mismatch', result['failures'])
        self.assertFalse(result['algorithm_validated'])

    def test_runtime_authority_drift_rejects_before_fake_runner(self):
        mutations = {
            'decoder_closure_hash': lambda fixture: fixture.authority[
                'rosbag_decoder_closure']['rosbag.bag'].__setitem__(
                    'sha256', '0' * 64),
            'probe_hash': lambda fixture: fixture.authority[
                'isolated_probe_source'].__setitem__('sha256', '0' * 64),
            'executable_target_hash': lambda fixture: fixture.authority[
                'python_executable_target'].__setitem__('sha256', '0' * 64),
            'missing_noetic_root': lambda fixture: fixture.authority.__setitem__(
                'noetic_prefix', str(fixture.root / 'missing-noetic')),
            'missing_trusted_root': lambda fixture: fixture.authority[
                'trusted_system_python_roots'].append(
                    str(fixture.root / 'missing-trusted-root')),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                mutate(fixture)
                self._seal_authority(fixture)
                result = fixture.evaluate()
                self.assertFalse(result['algorithm_validated'], result)
                self.assertEqual([], fixture.probe_calls)

    def test_linklike_authority_probe_rejects_before_fake_runner(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            link = fixture.root / 'anchored/probe-link.py'
            try:
                link.symlink_to(fixture.probe_path)
            except (NotImplementedError, OSError):
                self.skipTest('platform does not permit test symlinks')
            declaration = dict(fixture.authority['isolated_probe_source'])
            declaration['path'] = str(link.absolute())
            fixture.authority['isolated_probe_source'] = declaration
            self._seal_authority(fixture)
            result = fixture.evaluate()
        self.assertFalse(result['algorithm_validated'], result)
        self.assertEqual([], fixture.probe_calls)

    def test_request_self_reported_pass_field_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.request['validated_pass'] = True
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn('request_schema_invalid', result['failures'])

    def test_model_set_identity_is_recomputed_from_ordered_model_hashes(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.request['model_set_sha256'] = 'f' * 64
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn(
            'request_model_set_sha256_mismatch', result['failures'])
        self.assertEqual([], fixture.probe_calls)

    def test_collector_report_must_match_exact_authority_bound_request(self):
        mutations = {
            'topic': '/foreign/perception/frames',
            'message_type': 'foreign_msgs/PerceptionFrame',
            'max_frames': 2,
            'duration_sec': 2.0,
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                declaration = fixture.request['scenes']['background'][
                    'artifacts']['collector_manifest']
                payload = json.loads(Path(declaration['path']).read_text(
                    encoding='utf-8'))
                payload[field] = replacement
                fixture.update_artifact(
                    'background', 'collector_manifest', payload)
                result = fixture.evaluate()
                self.assertIn(
                    'collector_manifest_invalid:background',
                    result['failures'])

    def test_typed_raw_self_report_cannot_hide_unpaired_raw_bundle(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.extra_probe_bundles = 1
            declaration = fixture.request['scenes']['background'][
                'artifacts']['typed_raw_binding']
            payload = json.loads(Path(declaration['path']).read_text(
                encoding='utf-8'))
            payload['raw_bundle_count'] = 2
            payload['unpaired_raw_bundle_count'] = 0
            fixture.update_artifact(
                'background', 'typed_raw_binding', payload)
            result = fixture.evaluate()
        self.assertIn(
            'typed_raw_binding_policy_invalid:background',
            result['failures'])
        self.assertFalse(result['algorithm_validated'])

    def test_test_only_typed_raw_cannot_self_report_formal(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            declaration = fixture.request['scenes']['background'][
                'artifacts']['typed_raw_binding']
            payload = json.loads(Path(declaration['path']).read_text(
                encoding='utf-8'))
            payload['formal_acceptance'] = True
            payload['not_in_four_scene_denominator'] = False
            fixture.update_artifact(
                'background', 'typed_raw_binding', payload)
            result = fixture.evaluate()
        self.assertIn(
            'typed_raw_binding_policy_invalid:background', result['failures'])
        self.assertFalse(result['formal_acceptance'])
        self.assertTrue(result['not_in_four_scene_denominator'])
        self.assertFalse(result['delivery_ready'])

    def test_typed_target_requires_complete_geometry_and_quality_contract(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene = fixture.request['scenes']['bin_only']
            frames = GATE._load_jsonl_identity(
                scene['artifacts']['typed_frames'], 'typed_frames')
            del frames[0]['targets'][0]['bbox']
            fixture.update_artifact(
                'bin_only', 'typed_frames', frames, jsonl=True)
            result = fixture.evaluate()
        self.assertIn('typed_target_schema_invalid:bin_only', result['failures'])

    def test_ground_truth_requires_bbox_and_typed_raw_rgb_binding(self):
        mutations = {
            'missing_bbox': lambda value: value['records'][0][
                'annotations'][0].pop('bbox'),
            'raw_rgb_hash': lambda value: value['records'][0].__setitem__(
                'rgb_payload_sha256', '0' * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                declaration = fixture.request['scenes']['bin_only'][
                    'artifacts']['ground_truth']
                payload = json.loads(Path(declaration['path']).read_text(
                    encoding='utf-8'))
                mutate(payload)
                fixture.update_artifact('bin_only', 'ground_truth', payload)
                result = fixture.evaluate()
                self.assertFalse(result['algorithm_validated'], result)
                self.assertTrue(any(
                    code.startswith(('ground_truth_annotation_invalid:',
                                     'ground_truth_typed_raw_binding_invalid:'))
                    for code in result['failures']), result)

    def test_extrinsics_reference_is_required_and_independently_reviewed(self):
        mutations = {
            'missing_transform_sha': lambda value: value.pop(
                'transform_sha256'),
            'self_reviewed': lambda value: value.__setitem__(
                'reviewer_id', value['operator_id']),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                declaration = fixture.request['scenes']['bin_only'][
                    'artifacts']['extrinsics_reference']
                payload = json.loads(Path(declaration['path']).read_text(
                    encoding='utf-8'))
                mutate(payload)
                fixture.update_artifact(
                    'bin_only', 'extrinsics_reference', payload)
                result = fixture.evaluate()
                self.assertFalse(result['algorithm_validated'], result)
                self.assertTrue(any(
                    code.startswith('extrinsics_reference_')
                    for code in result['failures']), result)

    def test_tf_raw_identity_and_applied_transform_are_recomputed(self):
        mutations = {
            'raw_identity': lambda value: value['records'][0].__setitem__(
                'serialized_sha256', '0' * 64),
            'not_applied': lambda value: value['records'][0].__setitem__(
                'transform_applied', False),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                declaration = fixture.request['scenes']['bin_only'][
                    'artifacts']['tf_records']
                payload = json.loads(Path(declaration['path']).read_text(
                    encoding='utf-8'))
                mutate(payload)
                fixture.update_artifact('bin_only', 'tf_records', payload)
                result = fixture.evaluate()
                self.assertIn(
                    'tf_raw_identity_or_application_invalid:bin_only',
                    result['failures'])

    def test_xyz_and_depth_values_are_recomputed_not_self_reported(self):
        mutations = {
            'xyz_records': lambda value: value['records'][0].__setitem__(
                'reference_xyz_m', [2.0, 0.0, 1.0]),
            'depth_records': lambda value: value['records'][0].__setitem__(
                'reference_depth_m', 1.5),
        }
        for role, mutate in mutations.items():
            with self.subTest(role=role), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                declaration = fixture.request['scenes']['bin_only'][
                    'artifacts'][role]
                payload = json.loads(Path(declaration['path']).read_text(
                    encoding='utf-8'))
                mutate(payload)
                fixture.update_artifact('bin_only', role, payload)
                result = fixture.evaluate()
                self.assertFalse(result['algorithm_validated'], result)
                self.assertTrue(any(
                    code in ('xyz_observation_recompute_invalid',
                             'depth_observation_recompute_invalid')
                    for code in result['failures']), result)

    def test_semantic_summaries_cannot_survive_deleted_samples(self):
        for role in ('xyz_records', 'depth_records', 'latency_records'):
            with self.subTest(role=role), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                declaration = fixture.request['scenes']['bin_only'][
                    'artifacts'][role]
                payload = json.loads(Path(declaration['path']).read_text(
                    encoding='utf-8'))
                payload['records'] = []
                fixture.update_artifact('bin_only', role, payload)
                result = fixture.evaluate()
                self.assertFalse(result['algorithm_validated'], result)

    def test_high_latency_samples_fail_recomputed_p95_thresholds(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene_name = 'bin_only'
            scene = fixture.request['scenes'][scene_name]
            frames = GATE._load_jsonl_identity(
                scene['artifacts']['typed_frames'], 'typed_frames')
            frame = frames[0]
            stamp_sec = (
                frame['stamp']['sec'] + frame['stamp']['nanosec'] / 1e9)
            frame['received_unix_sec'] = stamp_sec + 0.8
            frame['transport_latency_sec'] = 0.8
            frame['processing_latency_sec'] = 0.6
            frame['sync_span_sec'] = 0.2
            fixture.update_artifact(
                scene_name, 'typed_frames', frames, jsonl=True)
            frame_identity = fixture.request['scenes'][scene_name][
                'artifacts']['typed_frames']

            collector_decl = fixture.request['scenes'][scene_name][
                'artifacts']['collector_manifest']
            collector = json.loads(Path(collector_decl['path']).read_text(
                encoding='utf-8'))
            collector['output'] = frame_identity
            fixture.update_artifact(
                scene_name, 'collector_manifest', collector)

            binding_decl = fixture.request['scenes'][scene_name][
                'artifacts']['typed_raw_binding']
            binding = json.loads(Path(binding_decl['path']).read_text(
                encoding='utf-8'))
            binding['associations'][0]['typed_frame_sha256'] = (
                GATE._canonical_sha256(frame))
            fixture.update_artifact(
                scene_name, 'typed_raw_binding', binding)

            truth_decl = fixture.request['scenes'][scene_name][
                'artifacts']['ground_truth']
            truth = json.loads(Path(truth_decl['path']).read_text(
                encoding='utf-8'))
            truth['records'][0]['typed_frame_sha256'] = (
                GATE._canonical_sha256(frame))
            fixture.update_artifact(scene_name, 'ground_truth', truth)

            latency_decl = fixture.request['scenes'][scene_name][
                'artifacts']['latency_records']
            latency = json.loads(Path(latency_decl['path']).read_text(
                encoding='utf-8'))
            sample = latency['records'][0]
            sample.update({
                'inference_started_unix_sec': stamp_sec + 0.05,
                'inference_ended_unix_sec': stamp_sec + 0.65,
                'collector_received_unix_sec': stamp_sec + 0.8,
                'sync_span_sec': 0.2,
                'processing_latency_sec': 0.6,
                'transport_latency_sec': 0.8,
                'end_to_end_latency_sec': 0.8,
            })
            latency.update({
                'max_latency_sec': 0.8,
                'p95_end_to_end_sec': 0.8,
                'p95_processing_sec': 0.6,
                'p95_sync_sec': 0.2,
            })
            fixture.update_artifact(scene_name, 'latency_records', latency)
            result = fixture.evaluate()
        self.assertIn('latency_summary_recompute_mismatch', result['failures'])

    def test_duplicate_json_key_in_anchored_request_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            raw = fixture.request_path.read_text(encoding='utf-8')
            raw = raw.replace(
                '"mode":"test_only_algorithm",',
                '"mode":"test_only_algorithm",'
                '"mode":"test_only_algorithm",', 1)
            fixture.request_path.write_text(raw, encoding='utf-8')
            fixture.authority['request_identity'] = (
                GATE.regular_file_identity(fixture.request_path))
            _write_json(fixture.authority_path, fixture.authority)
            fixture.authority_identity = GATE.regular_file_identity(
                fixture.authority_path)
            result = fixture.evaluate()
        self.assertIn('duplicate_json_key', result['failures'])

    def test_ros2_db3_cannot_be_renamed_as_raw_rosbag1(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene = fixture.request['scenes']['background']
            old = Path(scene['artifacts']['raw_bag']['path'])
            db3 = old.with_suffix('.db3')
            db3.write_bytes(b'SQLite format 3\x00not-a-rosbag1')
            scene['artifacts']['raw_bag'] = GATE.regular_file_identity(db3)
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn('raw_capture_not_rosbag1_suffix', result['failures'])

    def test_json_renamed_dot_bag_is_rejected_before_probe(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene = fixture.request['scenes']['background']
            raw = Path(scene['artifacts']['raw_bag']['path'])
            raw.write_bytes(b'{"formal_acceptance":true}\n')
            scene['artifacts']['raw_bag'] = GATE.regular_file_identity(raw)
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn('raw_capture_not_rosbag1', result['failures'])
        self.assertEqual([], fixture.probe_calls)

    def test_artifact_identity_drift_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            path = Path(fixture.request['scenes']['background'][
                'artifacts']['ground_truth']['path'])
            path.write_text('{}\n', encoding='utf-8')
            fixture.refresh()
            result = fixture.evaluate()
        self.assertTrue(any(
            'ground_truth_identity_mismatch' in code
            for code in result['failures']), result)

    def test_artifact_path_reuse_across_roles_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene = fixture.request['scenes']['background']
            scene['artifacts']['tf_records'] = scene['artifacts'][
                'ground_truth']
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn('scene_artifact_path_reused', result['failures'])

    def test_zero_typed_frame_denominator_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.update_artifact(
                'background', 'typed_frames', [], jsonl=True)
            result = fixture.evaluate()
        self.assertIn('background:typed_frames_zero_denominator',
                      result['failures'])

    def test_summary_without_ground_truth_records_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            declaration = fixture.request['scenes']['background'][
                'artifacts']['ground_truth']
            payload = json.loads(Path(declaration['path']).read_text(
                encoding='utf-8'))
            payload['records'] = []
            fixture.update_artifact('background', 'ground_truth', payload)
            result = fixture.evaluate()
        self.assertIn(
            'ground_truth_frame_coverage_invalid', result['failures'])

    def test_production_scene_cannot_use_empty_truth_and_observations(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene_name = 'bin_only'
            scene = fixture.request['scenes'][scene_name]
            frames = GATE._load_jsonl_identity(
                scene['artifacts']['typed_frames'], 'typed_frames')
            frames[0] = dict(frames[0], targets=[], status='no_targets')
            frame_report = GATE._validate_frames(
                frames, scene_name, scene, fixture.request, 1)
            loaded = {}
            for role in (
                    'ground_truth', 'extrinsics_reference', 'tf_records',
                    'xyz_records', 'depth_records', 'latency_records'):
                value = GATE._load_identity_json(
                    scene['artifacts'][role], role)
                value['synthetic_test_only'] = False
                loaded[role] = value
            ground_record = dict(loaded['ground_truth']['records'][0])
            ground_record['annotations'] = []
            ground_record['typed_frame_sha256'] = GATE._canonical_sha256(
                frames[0])
            loaded['ground_truth']['records'] = [ground_record]
            key = next(iter(frame_report['frames']))
            frame_report['raw_by_frame'] = {key: {
                'stream_payload_sha256': {
                    'rgb': ground_record['rgb_payload_sha256']}}}
            frame_report['tf_graph'] = {}
            with self.assertRaises(GATE.IntakeError) as raised:
                GATE._validate_semantic_records(
                    scene_name, scene, fixture.request, frame_report,
                    loaded, False)
        self.assertEqual(
            'four_scene_ground_truth_semantics_invalid:bin_only',
            raised.exception.code)

    def test_cross_frame_ground_truth_reuse_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            declaration = fixture.request['scenes']['background'][
                'artifacts']['ground_truth']
            payload = json.loads(Path(declaration['path']).read_text(
                encoding='utf-8'))
            payload['records'][0]['stamp_ns'] += 1
            fixture.update_artifact('background', 'ground_truth', payload)
            result = fixture.evaluate()
        self.assertIn('ground_truth_frame_join_invalid', result['failures'])

    def test_duplicate_capture_identity_across_scenes_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.request['scenes']['bin_only']['capture_id'] = (
                fixture.request['scenes']['background']['capture_id'])
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn(
            'scene_identity_duplicate_or_invalid:capture_id',
            result['failures'])

    def test_missing_four_scene_member_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.request['scenes'].pop('background')
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn('request_scene_set_invalid', result['failures'])

    def test_capture_window_allows_10ms_record_receive_offset(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            window = fixture.request['scenes']['background'][
                'capture_window']
            window['record_start_ns'] = window['header_start_ns'] + 10_000_000
            window['record_end_ns'] = window['header_end_ns'] + 10_000_000
            scenes = GATE._validate_scene_declarations(fixture.request)
        self.assertEqual(set(GATE.SCENES), set(scenes))

    def test_capture_window_allows_exact_750ms_endpoint_skew(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            window = fixture.request['scenes']['background'][
                'capture_window']
            window['record_start_ns'] = (
                window['header_start_ns']
                + GATE.MAX_DECLARED_RECORD_HEADER_SKEW_NS)
            window['record_end_ns'] = (
                window['header_end_ns']
                + GATE.MAX_DECLARED_RECORD_HEADER_SKEW_NS)
            scenes = GATE._validate_scene_declarations(fixture.request)
        self.assertEqual(set(GATE.SCENES), set(scenes))

    def test_capture_window_rejects_endpoint_skew_over_750ms(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            window = fixture.request['scenes']['background'][
                'capture_window']
            window['record_start_ns'] = (
                window['header_start_ns']
                + GATE.MAX_DECLARED_RECORD_HEADER_SKEW_NS + 1)
            window['record_end_ns'] = (
                window['header_end_ns']
                + GATE.MAX_DECLARED_RECORD_HEADER_SKEW_NS + 1)
            with self.assertRaises(GATE.IntakeError) as raised:
                GATE._validate_scene_declarations(fixture.request)
        self.assertEqual(
            'scene_capture_window_invalid:background', raised.exception.code)

    def test_capture_window_rejects_reversed_header_or_record_axis(self):
        for axis in ('header', 'record'):
            with self.subTest(axis=axis), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                window = fixture.request['scenes']['background'][
                    'capture_window']
                window[axis + '_start_ns'] = window[axis + '_end_ns'] + 1
                with self.assertRaises(GATE.IntakeError) as raised:
                    GATE._validate_scene_declarations(fixture.request)
                self.assertEqual(
                    'scene_capture_window_invalid:background',
                    raised.exception.code)

    def test_production_probe_injection_is_rejected_without_execution(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.request['mode'] = GATE.PRODUCTION_MODE
            for scene in fixture.request['scenes'].values():
                scene['collector_request']['max_frames'] = (
                    GATE.MIN_PRODUCTION_SCENE_FRAMES)
            fixture.refresh()
            calls = []

            def injected(**keywords):
                calls.append(keywords)
                raise AssertionError('production injection executed')

            result = fixture.evaluate(runner=injected)
        self.assertIn(
            'production_probe_injection_forbidden', result['failures'])
        self.assertEqual([], calls)
        self.assertFalse(result['delivery_ready'])

    def test_linklike_artifact_is_rejected_when_platform_supports_links(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            scene = fixture.request['scenes']['background']
            target = Path(scene['artifacts']['ground_truth']['path'])
            link = target.with_name('ground_truth_link.json')
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest('platform does not permit test symlinks')
            scene['artifacts']['ground_truth'] = {
                'path': str(link.absolute()),
                'size_bytes': target.stat().st_size,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            }
            fixture.refresh()
            result = fixture.evaluate()
        self.assertIn('artifact_path_linklike', result['failures'])

    def test_path_read_bytes_injection_cannot_replace_identity_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'identity.json'
            _write_json(path, {'source': 'A', 'value': 11})
            identity = GATE.regular_file_identity(path)
            original_open = Path.open
            opened = []

            def tracked_open(candidate, *args, **kwargs):
                if Path(candidate) == path:
                    opened.append(str(candidate))
                return original_open(candidate, *args, **kwargs)

            injected = b'{"source":"B","value":99}\n'
            with (mock.patch.object(Path, 'open', new=tracked_open),
                  mock.patch.object(
                      Path, 'read_bytes', return_value=injected) as second_read):
                parsed = GATE._load_identity_json(identity, 'read_once_json')
        self.assertEqual({'source': 'A', 'value': 11}, parsed)
        self.assertEqual([str(path)], opened)
        second_read.assert_not_called()

    def test_path_read_bytes_injection_cannot_replace_identity_jsonl(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'identity.jsonl'
            _write_jsonl(path, [
                {'sequence': 1, 'source': 'A'},
                {'sequence': 2, 'source': 'A'},
            ])
            identity = GATE.regular_file_identity(path)
            original_open = Path.open
            opened = []

            def tracked_open(candidate, *args, **kwargs):
                if Path(candidate) == path:
                    opened.append(str(candidate))
                return original_open(candidate, *args, **kwargs)

            injected = b'{"sequence":99,"source":"B"}\n'
            with (mock.patch.object(Path, 'open', new=tracked_open),
                  mock.patch.object(
                      Path, 'read_bytes', return_value=injected) as second_read):
                parsed = GATE._load_jsonl_identity(
                    identity, 'read_once_jsonl')
        self.assertEqual([1, 2], [item['sequence'] for item in parsed])
        self.assertEqual([str(path)], opened)
        second_read.assert_not_called()

    def test_authority_request_canonical_and_report_each_open_once(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            report_identity = fixture.request['scenes']['background'][
                'artifacts']['semantic_producer_report']
            cases = (
                ('authority', fixture.authority_path,
                 lambda: GATE._load_anchored_authority(
                     fixture.authority_path, fixture.authority_identity)),
                ('request', fixture.request_path,
                 lambda: GATE._load_request(
                     fixture.request_path, fixture.authority)),
                ('canonical', fixture.canonical_path,
                 lambda: GATE._load_identity_json(
                     fixture.request['canonical_source_admission'],
                     'canonical_read_once')),
                ('report', Path(report_identity['path']),
                 lambda: GATE._load_identity_json_with_path(
                     report_identity, 'report_read_once')),
            )
            for name, target, loader in cases:
                with self.subTest(name=name):
                    original_open = Path.open
                    opened = []

                    def tracked_open(candidate, *args, **kwargs):
                        if Path(candidate) == target:
                            opened.append(str(candidate))
                        return original_open(candidate, *args, **kwargs)

                    with (mock.patch.object(Path, 'open', new=tracked_open),
                          mock.patch.object(
                              Path, 'read_bytes', return_value=b'{}\n'
                              ) as second_read):
                        loader()
                    self.assertEqual([str(target)], opened)
                    second_read.assert_not_called()

    def test_identity_reader_rejects_path_replacement_hook(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'selected.json'
            replacement = root / 'replacement.json'
            _write_json(path, {'source': 'A', 'value': 1})
            _write_json(replacement, {'source': 'B', 'value': 2})
            identity = GATE.regular_file_identity(path)
            original_open = Path.open
            replaced = []

            def replacing_open(candidate, *args, **kwargs):
                if Path(candidate) == path and not replaced:
                    os.replace(replacement, path)
                    replaced.append(True)
                return original_open(candidate, *args, **kwargs)

            with (mock.patch.object(Path, 'open', new=replacing_open),
                  self.assertRaises(GATE.IntakeError) as raised):
                GATE._load_identity_json(identity, 'replacement_case')
        self.assertEqual('artifact_changed_during_audit', raised.exception.code)

        metadata_mutations = {
            'mode': lambda value: {
                'st_mode': value.st_mode ^ stat.S_IWUSR},
            'file_type': lambda value: {
                'st_mode': stat.S_IFDIR | stat.S_IMODE(value.st_mode)},
            'inode': lambda value: {'st_ino': value.st_ino + 1},
            'size': lambda value: {'st_size': value.st_size + 1},
            'mtime': lambda value: {
                'st_mtime_ns': value.st_mtime_ns + 1},
            'nlink': lambda value: {'st_nlink': value.st_nlink + 1},
        }
        for name, mutate in metadata_mutations.items():
            with self.subTest(metadata=name), TemporaryDirectory() as directory:
                path = Path(directory) / 'stable.json'
                _write_json(path, {'source': 'A'})
                identity = GATE.regular_file_identity(path)
                original_fstat = GATE.os.fstat
                calls = []

                def drifting_fstat(descriptor):
                    metadata = original_fstat(descriptor)
                    calls.append(True)
                    if len(calls) == 2:
                        return _metadata_with(metadata, **mutate(metadata))
                    return metadata

                with (mock.patch.object(
                          GATE.os, 'fstat', new=drifting_fstat),
                      self.assertRaises(GATE.IntakeError) as drifted):
                    GATE._load_identity_json(identity, 'metadata_drift')
                self.assertEqual(
                    'artifact_changed_during_audit', drifted.exception.code)

        for name, mutate in metadata_mutations.items():
            with (self.subTest(metadata='path_' + name),
                  TemporaryDirectory() as directory):
                path = Path(directory) / 'stable.json'
                _write_json(path, {'source': 'A'})
                identity = GATE.regular_file_identity(path)
                original_lstat = GATE.os.lstat
                original_open = Path.open
                target = os.path.normcase(os.path.abspath(str(path)))
                state = {'opened': False, 'mutated': False}

                def tracked_open(candidate, *args, **kwargs):
                    stream = original_open(candidate, *args, **kwargs)
                    selected = os.path.normcase(os.path.abspath(
                        os.fspath(candidate)))
                    if selected == target:
                        state['opened'] = True
                    return stream

                def drifting_lstat(candidate):
                    metadata = original_lstat(candidate)
                    selected = os.path.normcase(os.path.abspath(
                        os.fspath(candidate)))
                    if (selected == target and state['opened']
                            and not state['mutated']):
                        state['mutated'] = True
                        return _metadata_with(metadata, **mutate(metadata))
                    return metadata

                with (mock.patch.object(Path, 'open', new=tracked_open),
                      mock.patch.object(
                          GATE.os, 'lstat', new=drifting_lstat),
                      self.assertRaises(GATE.IntakeError) as drifted):
                    GATE._load_identity_json(identity, 'path_metadata_drift')
                self.assertTrue(state['mutated'])
                self.assertEqual(
                    'artifact_changed_during_audit', drifted.exception.code)

    def test_identity_reader_rejects_linklike_and_hardlink_paths(self):
        cases = (
            ('linklike', os.symlink, 'artifact_path_linklike'),
            ('hardlink', os.link, 'artifact_hardlink_forbidden'),
        )
        supported = 0
        for name, create_link, expected_code in cases:
            with self.subTest(kind=name), TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / 'target.json'
                candidate = root / (name + '.json')
                raw = b'{"source":"A"}\n'
                target.write_bytes(raw)
                try:
                    create_link(target, candidate)
                except (OSError, NotImplementedError):
                    continue
                supported += 1
                declaration = {
                    'path': str(candidate.absolute()),
                    'size_bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(),
                }
                with self.assertRaises(GATE.IntakeError) as raised:
                    GATE._load_identity_json(declaration, name + '_case')
                self.assertEqual(expected_code, raised.exception.code)
        if not supported:
            self.skipTest('platform permits neither symlinks nor hardlinks')

    def test_raw_bag_magic_uses_declared_identity_fd_without_read_bytes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.bag'
            magic = b'#ROSBAG V2.0\n'
            target_size = 81 * 1024 * 1024
            chunk = b'x' * (1024 * 1024)
            remaining = target_size - len(magic)
            with path.open('wb') as stream:
                stream.write(magic)
                while remaining:
                    material = chunk[:min(len(chunk), remaining)]
                    stream.write(material)
                    remaining -= len(material)
            identity = GATE.regular_file_identity(path)
            original_reader = GATE._read_identity_material
            retained = []

            def capturing_reader(*args, **kwargs):
                selected, prefix = original_reader(*args, **kwargs)
                retained.append(len(prefix) if prefix is not None else None)
                return selected, prefix

            with (mock.patch.object(
                      GATE, '_read_identity_material', new=capturing_reader),
                  mock.patch.object(
                      Path, 'read_bytes', return_value=b'{"fake":true}\n'
                      ) as second_read):
                selected = GATE._check_raw_bag(identity, 'raw_bag_case')
        self.assertEqual(path.resolve(strict=False), selected)
        self.assertEqual(target_size, identity['size_bytes'])
        self.assertEqual([32], retained)
        second_read.assert_not_called()

    def test_identity_parsers_have_no_path_read_bytes_fallback(self):
        source = Path(GATE.__file__).read_text(encoding='utf-8')
        self.assertNotIn('.read_bytes(', source)
        self.assertNotIn('def _sha256_file(', source)
        executable = Path(sys.executable).resolve(strict=True)
        identity = GATE.regular_file_identity(executable)
        self.assertEqual(str(executable), identity['path'])
        self.assertGreater(identity['size_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
