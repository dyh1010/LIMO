"""Pure-software tests for the host semantic evidence producer."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
_IMPORT_PATH_BEFORE = list(sys.path)
try:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from limo_cleanup_perception import (  # noqa: E402
        ros1_noetic_field_readiness as INTAKE)
    from limo_cleanup_perception import (  # noqa: E402
        ros1_semantic_evidence_producer as PRODUCER)
finally:
    sys.path[:] = _IMPORT_PATH_BEFORE


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PRODUCER._json_bytes(value))


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b''.join(PRODUCER._json_bytes(value) for value in values))


def _sha_text(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _authority_index_fixture(root, mutation=None):
    root = Path(root)
    authorities = {}
    for scene in INTAKE.SCENES:
        path = root / ('authority-' + scene + '.json')
        _write_json(path, {'scene': scene})
        authorities[scene] = INTAKE.regular_file_identity(path)
    payload = {
        'schema_version': 1,
        'marker': PRODUCER.AUTHORITY_INDEX_MARKER,
        'index_id': 'semantic-authority-index-test-v1',
        'scope': 'ros1_noetic_semantic_producer_authority_index',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'scene_set': list(INTAKE.SCENES),
        'authorities': authorities,
    }
    if mutation is not None:
        mutation(payload)
    index_path = root / 'semantic-authority-index.json'
    _write_json(index_path, payload)
    return index_path, INTAKE.regular_file_identity(index_path), payload


def _index_anchor_patch(identity):
    return mock.patch.multiple(
        PRODUCER,
        PRODUCTION_AUTHORITY_INDEX_PATH=identity['path'],
        PRODUCTION_AUTHORITY_INDEX_SIZE_BYTES=identity['size_bytes'],
        PRODUCTION_AUTHORITY_INDEX_SHA256=identity['sha256'])


class _Fixture:

    def __init__(self, root):
        self.root = Path(root)
        self.allowed_root = self.root / 'outputs'
        self.allowed_root.mkdir()
        self.destination = self.allowed_root / 'scene-material'
        self.scene = 'bottle_outside'
        self.capture_id = 'capture-bottle-outside-1'
        self.task_id = 'task-bottle-outside-1'
        self.stamp_ns = 1_700_000_000_000_000_000
        self.bundle_id = _sha_text('bundle:bottle-outside:1')

        self.canonical_path = self.root / 'canonical.json'
        self.install_path = self.root / 'install.json'
        self.model_manifest_path = self.root / 'model-manifest.json'
        self.model_paths = {
            'plastic_bottle': self.root / 'models/bottle.engine',
            'trash_bin': self.root / 'models/bin.engine',
        }
        _write_json(self.canonical_path, {'canonical': True})
        _write_json(self.install_path, {'validated_pass': False})
        for name, path in self.model_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('model:' + name).encode('utf-8'))
        self.model_artifacts = {
            name: INTAKE.regular_file_identity(path)
            for name, path in self.model_paths.items()}
        _write_json(self.model_manifest_path, {
            'schema_version': 1,
            'model_artifacts': self.model_artifacts,
        })
        self.model_manifest = INTAKE.regular_file_identity(
            self.model_manifest_path)
        self.model_hashes = {
            name: identity['sha256']
            for name, identity in self.model_artifacts.items()}
        self.model_set_sha = INTAKE._model_set_sha256(self.model_hashes)
        self.canonical = INTAKE.regular_file_identity(self.canonical_path)
        self.install = INTAKE.regular_file_identity(self.install_path)

        self.raw_path = self.root / 'capture.bag'
        self.raw_path.write_bytes(b'#ROSBAG V2.0\ncomplete-test-record-chain')
        self.raw = INTAKE.regular_file_identity(self.raw_path)
        self.stream_hashes = {
            role: _sha_text('stream:' + role)
            for role in ('rgb', 'raw_depth', 'rgb_camera_info',
                         'depth_camera_info')}
        self.targets = [
            self._target('outside-bin', 'trash_bin', 1.0, 'observed', False),
            self._target('outside-bottle', 'plastic_bottle', 1.0, 'active', True),
        ]
        self.frame = {
            'schema_version': 1,
            'read_only': True,
            'received_unix_sec': self.stamp_ns / 1e9 + 0.2,
            'transport_latency_sec': 0.2,
            'stamp': {
                'sec': self.stamp_ns // 1_000_000_000,
                'nanosec': self.stamp_ns % 1_000_000_000,
            },
            'frame_id': 'camera_color_optical_frame',
            'task_id': self.task_id,
            'capture_id': self.capture_id,
            'bundle_id': self.bundle_id,
            'model_binding_sha256': self.model_set_sha,
            'sequence': 1,
            'valid': True,
            'status': 'targets_valid',
            'error_code': '',
            'sync_span_sec': 0.001,
            'processing_latency_sec': 0.1,
            'tf_target_frame': 'base_link',
            'tf_valid': True,
            'tf_transform_applied': True,
            'tf_status': 'applied',
            'tf_error_code': '',
            'targets': self.targets,
            'scene': self.scene,
        }
        self.frames_path = self.root / 'typed-frames.jsonl'
        _write_jsonl(self.frames_path, [self.frame])
        self.frames = INTAKE.regular_file_identity(self.frames_path)
        self.binding_path = self.root / 'typed-raw-binding.json'
        self.binding = self._binding_payload()
        _write_json(self.binding_path, self.binding)
        self.binding_identity = INTAKE.regular_file_identity(
            self.binding_path)
        self.probe_path = self.root / 'probe-artifact.json'
        self.probe = self._probe_payload()
        _write_json(self.probe_path, self.probe)
        self.probe_identity = INTAKE.regular_file_identity(self.probe_path)

        self.ledger_path = self.root / 'semantic-ledger.json'
        self.ledger = self._ledger_payload()
        self.review_authority_path = self.root / 'ground-truth-review.json'
        self.measurement_authority_path = (
            self.root / 'measurement-reference.json')
        self.request_path = self.root / 'producer-request.json'
        self.authority_path = self.root / 'producer-authority.json'
        self.refresh()

    def _target(self, observation_id, object_class, depth, status, actionable):
        return {
            'observation_id': observation_id,
            'object_class': object_class,
            'confidence': 0.99,
            'valid': True,
            'actionable': actionable,
            'status': status,
            'error_code': '',
            'position': {'x': depth, 'y': 0.0, 'z': depth},
            'size': {'x': 0.2, 'y': 0.2, 'z': 0.2},
            'bbox': [10.0, 10.0, 40.0, 60.0],
            'depth_m': depth,
            'depth_valid_pixels': 100,
            'depth_total_pixels': 100,
            'depth_valid_ratio': 1.0,
            'source': 'fixture-detector',
            'position_semantics': 'base_link_from_independent_extrinsics',
        }

    def _binding_payload(self):
        return {
            'schema_version': 2,
            'report_kind': INTAKE.ARTIFACT_MARKERS['typed_raw_binding'],
            'evidence_scope': 'test_only_rosbag1_typed_raw_binding',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'binding_sha256': '6' * 64,
            'capture_id': self.capture_id,
            'task_id': self.task_id,
            'scene': self.scene,
            'model_binding_sha256': self.model_set_sha,
            'artifacts': {},
            'provenance': {},
            'typed_frame_count': 1,
            'raw_bundle_count': 1,
            'association_count': 1,
            'minimum_scene_frames': 1,
            'unpaired_typed_count': 0,
            'unpaired_raw_bundle_count': 0,
            'associations': [{
                'typed_row_index': 0,
                'sequence': 1,
                'stamp_ns': self.stamp_ns,
                'bundle_id': self.bundle_id,
                'typed_frame_sha256': INTAKE._canonical_sha256(self.frame),
                'raw_bundle_index': 1,
                'raw_stream_payload_sha256': self.stream_hashes,
            }],
            'test_only': True,
            'validated_pass': True,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
            'delivery_ready': False,
            'failures': [],
        }

    def _probe_payload(self):
        return {
            'schema_version': 1,
            'marker': INTAKE.PROBE_ARTIFACT_MARKER,
            'report_kind': 'isolated_rosbag1_raw_records',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'delivery_ready': False,
            'request_id': _sha_text('probe-request'),
            'request_sha256': _sha_text('probe-request-bytes'),
            'bag_identity': self.raw,
            'noetic_prefix': str(self.root / 'noetic'),
            'python_root': str(self.root / 'noetic/python'),
            'rosbag_module_identity': self.canonical,
            'indexer_module_identity': self.canonical,
            'formal_manifest_identity': self.canonical,
            'probe_source_identity': self.canonical,
            'sys_executable_identity': self.canonical,
            'parent_executable_admission': {},
            'child_executable_admission': {},
            'capture_id': self.capture_id,
            'scene': self.scene,
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
                'not_in_four_scene_denominator': False,
                'delivery_ready': False,
                'capture_id': self.capture_id,
                'scene': self.scene,
                'accepted_bundles': [{
                    'index': 1,
                    'header_stamps_ns': {'rgb': self.stamp_ns},
                    'stream_record_timestamps_ns': {'rgb': self.stamp_ns},
                    'stream_payload_sha256': self.stream_hashes,
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
                        'serialized_sha256': _sha_text('raw-tf'),
                    }],
                },
            },
            'loaded_nonstdlib_module_provenance': [],
            'test_only': True,
            'algorithm_validated': True,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
        }

    def _ledger_payload(self):
        annotations = [
            {
                'instance_id': target['observation_id'],
                'object_class': target['object_class'],
                'bbox': target['bbox'],
                'relation': (
                    'container' if target['object_class'] == 'trash_bin'
                    else 'outside_bin'),
            }
            for target in self.targets]
        observations = [{
            'observation_id': target['observation_id'],
            'camera_xyz_m': [
                target['position']['x'], target['position']['y'],
                target['position']['z']],
            'reference_xyz_m': [
                target['position']['x'], target['position']['y'],
                target['position']['z']],
            'reference_depth_m': target['depth_m'],
        } for target in self.targets]
        return {
            'schema_version': 1,
            'marker': PRODUCER.LEDGER_MARKER,
            'scene': self.scene,
            'capture_id': self.capture_id,
            'task_id': self.task_id,
            'raw_bag': self.raw,
            'probe_artifact': self.probe_identity,
            'typed_frames': self.frames,
            'typed_raw_binding': self.binding_identity,
            'canonical_source_admission': self.canonical,
            'field_install_evidence': self.install,
            'model_manifest': self.model_manifest,
            'model_artifacts': self.model_artifacts,
            'model_set_sha256': self.model_set_sha,
            'ground_truth_operator_id': 'fixture-truth-operator',
            'ground_truth_reviewer_id': 'fixture-truth-reviewer',
            'extrinsics': {
                'source_frame': 'camera_color_optical_frame',
                'target_frame': 'base_link',
                'translation_m': [0.0, 0.0, 0.0],
                'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
                'measurement_method': 'fixture-independent-measurement',
                'operator_id': 'fixture-extrinsics-operator',
                'reviewer_id': 'fixture-extrinsics-reviewer',
                'measured_at_unix_sec': self.stamp_ns / 1e9 - 10.0,
                'reviewed_at_unix_sec': self.stamp_ns / 1e9 - 5.0,
            },
            'records': [{
                'sequence': 1,
                'stamp_ns': self.stamp_ns,
                'bundle_id': self.bundle_id,
                'typed_frame_sha256': INTAKE._canonical_sha256(self.frame),
                'rgb_payload_sha256': self.stream_hashes['rgb'],
                'annotations': annotations,
                'observations': observations,
                'inference_started_unix_sec': self.stamp_ns / 1e9 + 0.05,
                'inference_ended_unix_sec': self.stamp_ns / 1e9 + 0.15,
            }],
        }

    def refresh(self):
        observation_ids = sorted({
            item['observation_id']
            for record in self.ledger['records']
            for item in record['observations']})
        _write_json(self.review_authority_path, {
            'schema_version': 1,
            'marker': 'LIMO_ROS1_GROUND_TRUTH_REVIEW_AUTHORITY_V1',
            'scope': 'independent_ground_truth_review',
            'scene': self.scene,
            'capture_id': self.capture_id,
            'task_id': self.task_id,
            'raw_bag': self.raw,
            'typed_frames': self.frames,
            'operator_id': self.ledger['ground_truth_operator_id'],
            'reviewer_id': self.ledger['ground_truth_reviewer_id'],
            'reviewed_at_unix_sec': self.stamp_ns / 1e9 - 1.0,
            'synthetic_test_only': True,
        })
        _write_json(self.measurement_authority_path, {
            'schema_version': 1,
            'marker': 'LIMO_ROS1_MEASUREMENT_REFERENCE_AUTHORITY_V1',
            'scope': 'independent_extrinsics_xyz_depth_reference',
            'scene': self.scene,
            'capture_id': self.capture_id,
            'task_id': self.task_id,
            'raw_bag': self.raw,
            'probe_artifact': self.probe_identity,
            'typed_frames': self.frames,
            'extrinsics_operator_id': self.ledger['extrinsics']['operator_id'],
            'extrinsics_reviewer_id': self.ledger['extrinsics']['reviewer_id'],
            'measurement_method': self.ledger['extrinsics'][
                'measurement_method'],
            'observation_ids': observation_ids,
            'authorized_at_unix_sec': self.stamp_ns / 1e9 - 1.0,
            'synthetic_test_only': True,
        })
        self.review_authority = INTAKE.regular_file_identity(
            self.review_authority_path)
        self.measurement_authority = INTAKE.regular_file_identity(
            self.measurement_authority_path)
        self.ledger['ground_truth_review_authority'] = self.review_authority
        self.ledger['measurement_reference_authority'] = (
            self.measurement_authority)
        _write_json(self.ledger_path, self.ledger)
        ledger_identity = INTAKE.regular_file_identity(self.ledger_path)
        self.request = {
            'schema_version': 1,
            'marker': PRODUCER.REQUEST_MARKER,
            'request_id': 'test-only-producer-request-v1',
            'mode': PRODUCER.TEST_ONLY_MODE,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'scene': self.scene,
            'capture_id': self.capture_id,
            'task_id': self.task_id,
            'raw_bag': self.raw,
            'probe_artifact': self.probe_identity,
            'typed_frames': self.frames,
            'typed_raw_binding': self.binding_identity,
            'measurement_ledger': ledger_identity,
            'canonical_source_admission': self.canonical,
            'field_install_evidence': self.install,
            'model_manifest': self.model_manifest,
            'model_artifacts': self.model_artifacts,
            'model_set_sha256': self.model_set_sha,
            'ground_truth_review_authority': self.review_authority,
            'measurement_reference_authority': self.measurement_authority,
            'output_directory': str(self.destination.absolute()),
        }
        _write_json(self.request_path, self.request)
        self.authority = {
            'schema_version': 1,
            'marker': PRODUCER.AUTHORITY_MARKER,
            'authority_id': 'test-only-semantic-producer-authority-v1',
            'scope': 'ros1_noetic_semantic_evidence_producer',
            'test_only': True,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'request_identity': INTAKE.regular_file_identity(
                self.request_path),
            'producer_source': INTAKE.regular_file_identity(
                Path(PRODUCER.__file__)),
            'field_readiness_source': INTAKE.regular_file_identity(
                Path(INTAKE.__file__)),
            'canonical_source_admission': self.canonical,
            'field_install_evidence': self.install,
            'model_manifest': self.model_manifest,
            'model_artifacts': self.model_artifacts,
            'model_set_sha256': self.model_set_sha,
            'ground_truth_review_authority': self.review_authority,
            'measurement_reference_authority': self.measurement_authority,
            'allowed_output_root': str(self.allowed_root.resolve()),
        }
        _write_json(self.authority_path, self.authority)
        self.authority_identity = INTAKE.regular_file_identity(
            self.authority_path)

    def run(self):
        return PRODUCER.produce_semantic_evidence(
            self.request_path, self.authority_path, self.authority_identity,
            self.destination, test_only=True)

    def mutate_ledger(self, mutation):
        mutation(self.ledger)
        self.refresh()

    def mutate_probe(self, mutation):
        mutation(self.probe)
        _write_json(self.probe_path, self.probe)
        self.probe_identity = INTAKE.regular_file_identity(self.probe_path)
        self.ledger['probe_artifact'] = self.probe_identity
        self.refresh()

    def consumer_context(self, result):
        loaded = {
            role: json.loads(Path(identity['path']).read_text(
                encoding='utf-8'))
            for role, identity in result['outputs'].items()}
        frame_report = PRODUCER._frame_context(
            self.request, self.probe, True)
        semantic = INTAKE._validate_semantic_records(
            self.scene, {
                'capture_id': self.capture_id, 'task_id': self.task_id}, {
                'field_install_evidence': self.install,
                'model_set_sha256': self.model_set_sha},
            frame_report, loaded, True)
        artifacts = {
            'raw_bag': self.raw,
            'typed_frames': self.frames,
            'typed_raw_binding': self.binding_identity,
            'semantic_producer_report': result['report_identity'],
            **result['outputs'],
        }
        return {
            'scene': {
                'capture_id': self.capture_id,
                'task_id': self.task_id,
                'artifacts': artifacts,
            },
            'request': {
                'canonical_source_admission': self.canonical,
                'field_install_evidence': self.install,
                'model_artifact_sha256': self.model_hashes,
                'model_set_sha256': self.model_set_sha,
            },
            'authority': {
                'semantic_producer_source': INTAKE.regular_file_identity(
                    Path(PRODUCER.__file__)),
                'semantic_producer_authorities': {
                    self.scene: self.authority_identity},
            },
            'frame_report': frame_report,
            'semantic': semantic,
        }


class Ros1SemanticEvidenceProducerTest(unittest.TestCase):

    def test_probe_embedded_formal_state_is_exact_for_admission_mode(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_probe(lambda value: value[
                'formal_report'].__setitem__('formal_acceptance', True))
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_probe_artifact_invalid'):
                fixture.run()
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_probe(
                lambda value: value.__setitem__('test_only', False))
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_probe_artifact_invalid'):
                PRODUCER._validate_probe(fixture.request, False)

    def test_production_authority_index_selects_four_distinct_scenes(self):
        with TemporaryDirectory() as directory:
            _, identity, payload = _authority_index_fixture(directory)
            with _index_anchor_patch(identity):
                loaded = PRODUCER.load_production_authority_index()
                selected, index_identity, scene = (
                    PRODUCER._expected_authority_selection(
                        Path(payload['authorities']['bin_only']['path']),
                        payload['authorities']['bin_only']['size_bytes'],
                        payload['authorities']['bin_only']['sha256'], False))
            self.assertEqual(identity, loaded['identity'])
            self.assertEqual(payload, loaded['payload'])
            self.assertEqual(payload['authorities']['bin_only'], selected)
            self.assertEqual(identity, index_identity)
            self.assertEqual('bin_only', scene)

    def test_single_authority_cannot_cover_all_four_scenes(self):
        def reuse_one(payload):
            first = payload['authorities']['background']
            payload['authorities'] = {
                scene: first for scene in INTAKE.SCENES}

        with TemporaryDirectory() as directory:
            _, identity, _ = _authority_index_fixture(directory, reuse_one)
            with _index_anchor_patch(identity), self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_production_authority_index_invalid'):
                PRODUCER.load_production_authority_index()

    def test_authority_index_missing_or_wrong_scene_fails_closed(self):
        mutations = {
            'missing': lambda value: value['authorities'].pop('background'),
            'wrong': lambda value: value['authorities'].__setitem__(
                'wrong_scene', value['authorities'].pop('background')),
            'scene_set': lambda value: value.__setitem__(
                'scene_set', list(INTAKE.SCENES[:-1])),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                _, identity, _ = _authority_index_fixture(directory, mutation)
                with _index_anchor_patch(identity), self.assertRaisesRegex(
                        PRODUCER.ProducerError,
                        'semantic_producer_production_authority_index_invalid'):
                    PRODUCER.load_production_authority_index()

    def test_authority_index_duplicate_scene_json_is_rejected(self):
        with TemporaryDirectory() as directory:
            index_path, _, payload = _authority_index_fixture(directory)
            entries = [
                json.dumps(scene) + ':' + json.dumps(
                    identity, sort_keys=True, separators=(',', ':'))
                for scene, identity in payload['authorities'].items()]
            entries.append(
                json.dumps('background') + ':' + json.dumps(
                    payload['authorities']['background'], sort_keys=True,
                    separators=(',', ':')))
            encoded = (
                '{"schema_version":1,"marker":'
                + json.dumps(PRODUCER.AUTHORITY_INDEX_MARKER)
                + ',"index_id":"semantic-authority-index-test-v1",'
                '"scope":"ros1_noetic_semantic_producer_authority_index",'
                '"read_only":true,"authorizes_motion":false,'
                '"publishes_ros_messages":false,"scene_set":'
                + json.dumps(list(INTAKE.SCENES), separators=(',', ':'))
                + ',"authorities":{' + ','.join(entries) + '}}\n')
            index_path.write_bytes(encoded.encode('utf-8'))
            identity = INTAKE.regular_file_identity(index_path)
            with _index_anchor_patch(identity), self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_duplicate_json_key'):
                PRODUCER.load_production_authority_index()

    def test_caller_authority_identity_cannot_substitute_for_index(self):
        with TemporaryDirectory() as directory:
            index_path, index_identity, _ = _authority_index_fixture(directory)
            outside = Path(directory) / 'caller-self-reported.json'
            _write_json(outside, {'caller': 'not indexed'})
            outside_identity = INTAKE.regular_file_identity(outside)
            with _index_anchor_patch(index_identity), self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_authority_identity_mismatch'):
                PRODUCER._expected_authority_selection(
                    outside, outside_identity['size_bytes'],
                    outside_identity['sha256'], False)
            with _index_anchor_patch(index_identity), self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_authority_identity_mismatch'):
                PRODUCER._expected_authority_selection(
                    index_path, index_identity['size_bytes'],
                    index_identity['sha256'], False)

    def test_request_scene_must_match_index_selected_authority(self):
        PRODUCER._validate_authority_scene(
            {'scene': 'background'}, 'background', False)
        with self.assertRaisesRegex(
                PRODUCER.ProducerError,
                'semantic_producer_authority_scene_mismatch'):
            PRODUCER._validate_authority_scene(
                {'scene': 'bin_only'}, 'background', False)

    def test_field_consumer_rejects_authority_map_different_from_index(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.run()
            context = fixture.consumer_context(result)
            _, index_identity, payload = _authority_index_fixture(
                Path(directory) / 'index')
            wrong_map = dict(payload['authorities'])
            wrong_map['background'] = wrong_map['bin_only']
            context['authority']['semantic_producer_authorities'] = wrong_map
            with (_index_anchor_patch(index_identity),
                  mock.patch.object(
                      INTAKE, '_load_exact_semantic_producer',
                      return_value=PRODUCER),
                  self.assertRaisesRegex(
                      INTAKE.IntakeError,
                      'semantic_producer_production_authority_index_mismatch')):
                INTAKE._validate_semantic_producer_report(
                    fixture.scene, context['scene'], context['request'],
                    context['authority'], fixture.probe_identity,
                    context['frame_report'], context['semantic'], False)

    def test_test_only_producer_builds_consumer_compatible_six_artifacts(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.run()
            self.assertTrue(result['producer_material_validated'], result)
            self.assertFalse(result['formal_acceptance'])
            self.assertTrue(result['not_in_four_scene_denominator'])
            self.assertFalse(result['field_evidence_admitted'])
            self.assertFalse(result['delivery_ready'])
            self.assertIsNone(result['authority_index_identity'])
            self.assertEqual(
                ['synthetic_test_only_not_formal_evidence'],
                result['failures'])
            self.assertEqual(set(PRODUCER.OUTPUT_NAMES), set(result['outputs']))
            loaded = {
                role: json.loads(Path(identity['path']).read_text(
                    encoding='utf-8'))
                for role, identity in result['outputs'].items()}
            frame_report = PRODUCER._frame_context(
                fixture.request, fixture.probe, True)
            recompute = INTAKE._validate_semantic_records(
                fixture.scene, {
                    'capture_id': fixture.capture_id,
                    'task_id': fixture.task_id}, {
                    'field_install_evidence': fixture.install,
                    'model_set_sha256': fixture.model_set_sha},
                frame_report, loaded, True)
            self.assertEqual(1, recompute['typed_frame_count'])
            self.assertEqual(2, recompute['xyz_record_count'])
            self.assertEqual(2, recompute['depth_record_count'])

    def test_host_consumer_reopens_exact_producer_lineage(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.run()
            context = fixture.consumer_context(result)
            admitted = INTAKE._validate_semantic_producer_report(
                fixture.scene, context['scene'], context['request'],
                context['authority'], fixture.probe_identity,
                context['frame_report'], context['semantic'], True)
            self.assertEqual(result['report_identity'], admitted[
                'report_identity'])
            report = json.loads(Path(result['report_identity']['path']).read_text(
                encoding='utf-8'))
            self.assertEqual(INTAKE.SEMANTIC_PRODUCER_REPORT_KEYS, set(report))

    def test_host_consumer_rejects_report_source_or_authority_substitution(self):
        mutations = {
            'source': lambda report: report.__setitem__(
                'producer_source_identity', report['model_manifest']),
            'authority': lambda report: report.__setitem__(
                'authority_identity', report['model_manifest']),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                result = fixture.run()
                report_path = Path(result['report_identity']['path'])
                report = json.loads(report_path.read_text(encoding='utf-8'))
                mutation(report)
                _write_json(report_path, report)
                result['report_identity'] = INTAKE.regular_file_identity(
                    report_path)
                context = fixture.consumer_context(result)
                with self.assertRaisesRegex(
                        INTAKE.IntakeError,
                        'semantic_producer_report_policy_invalid'):
                    INTAKE._validate_semantic_producer_report(
                        fixture.scene, context['scene'], context['request'],
                        context['authority'], fixture.probe_identity,
                        context['frame_report'], context['semantic'], True)

    def test_host_consumer_rejects_output_replacement_and_test_report_as_prod(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.run()
            context = fixture.consumer_context(result)
            ground_path = Path(result['outputs']['ground_truth']['path'])
            ground = json.loads(ground_path.read_text(encoding='utf-8'))
            ground['annotation_count'] += 1
            _write_json(ground_path, ground)
            context['scene']['artifacts']['ground_truth'] = (
                INTAKE.regular_file_identity(
                ground_path)
            )
            with self.assertRaisesRegex(
                    INTAKE.IntakeError,
                    'semantic_producer_report_policy_invalid'):
                INTAKE._validate_semantic_producer_report(
                    fixture.scene, context['scene'], context['request'],
                    context['authority'], fixture.probe_identity,
                    context['frame_report'], context['semantic'], True)
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.run()
            context = fixture.consumer_context(result)
            with self.assertRaisesRegex(
                    INTAKE.IntakeError,
                    'semantic_producer_production_authority_not_anchored'):
                INTAKE._validate_semantic_producer_report(
                    fixture.scene, context['scene'], context['request'],
                    context['authority'], fixture.probe_identity,
                    context['frame_report'], context['semantic'], False)

    def test_production_unbound_rejects_before_any_input_read_or_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'must-not-exist'
            environment = dict(os.environ)
            environment['PYTHONPATH'] = str(ROOT)
            environment['PYTHONDONTWRITEBYTECODE'] = '1'
            completed = subprocess.run([
                sys.executable, '-B', '-m',
                'limo_cleanup_perception.ros1_semantic_evidence_producer',
                '--request', str(root / 'missing-request.json'),
                '--authority', str(root / 'missing-authority.json'),
                '--authority-size-bytes', '1',
                '--authority-sha256', '0' * 64,
                '--output-directory', str(output),
            ], cwd=str(ROOT), env=environment, capture_output=True,
                text=True, encoding='utf-8', errors='strict', check=False)
            report = json.loads(completed.stdout)
            self.assertEqual(1, completed.returncode, completed)
            self.assertEqual([
                'semantic_producer_production_authority_not_anchored'],
                report['failures'])
            self.assertFalse(output.exists())

    def test_raw_bag_ledger_identity_mismatch_fails_closed(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_ledger(lambda value: value.__setitem__(
                'raw_bag', fixture.canonical))
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_raw_bag_identity_mismatch'):
                fixture.run()
            self.assertFalse(fixture.destination.exists())

    def test_typed_frame_join_hash_mismatch_fails_closed(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_ledger(lambda value: value['records'][0].__setitem__(
                'typed_frame_sha256', '0' * 64))
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_typed_frame_join_invalid'):
                fixture.run()

    def test_missing_measurement_frame_fails_closed(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_ledger(lambda value: value.__setitem__('records', []))
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_measurement_coverage_invalid'):
                fixture.run()

    def test_observation_coverage_must_be_exact(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_ledger(
                lambda value: value['records'][0]['observations'].pop())
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_observation_coverage_invalid'):
                fixture.run()

    def test_ground_truth_operator_and_reviewer_must_differ(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.mutate_ledger(lambda value: value.__setitem__(
                'ground_truth_reviewer_id',
                value['ground_truth_operator_id']))
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_ground_truth_review_invalid'):
                fixture.run()

    def test_source_install_and_model_provenance_are_exact(self):
        mutations = {
            'source': (
                lambda value, fixture: value.__setitem__(
                    'canonical_source_admission', fixture.install),
                'semantic_producer_source_provenance_invalid'),
            'install': (
                lambda value, fixture: value.__setitem__(
                    'field_install_evidence', fixture.canonical),
                'semantic_producer_install_provenance_invalid'),
            'model': (
                lambda value, fixture: value.__setitem__(
                    'model_set_sha256', '0' * 64),
                'semantic_producer_model_provenance_invalid'),
        }
        for name, (mutation, code) in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                fixture.mutate_ledger(
                    lambda value, f=fixture, m=mutation: m(value, f))
                with self.assertRaisesRegex(PRODUCER.ProducerError, code):
                    fixture.run()

    def test_existing_output_directory_is_rejected_without_overwrite(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.destination.mkdir()
            sentinel = fixture.destination / 'keep.txt'
            sentinel.write_text('keep', encoding='utf-8')
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_output_not_exclusive'):
                fixture.run()
            self.assertEqual('keep', sentinel.read_text(encoding='utf-8'))

    def test_host_consumer_rejects_extra_file_and_incomplete_marker(self):
        for filename in ('unexpected.txt', 'INCOMPLETE_DO_NOT_USE'):
            with self.subTest(filename=filename), TemporaryDirectory() as directory:
                fixture = _Fixture(directory)
                result = fixture.run()
                context = fixture.consumer_context(result)
                (fixture.destination / filename).write_text(
                    'not admitted', encoding='utf-8')
                with self.assertRaisesRegex(
                        INTAKE.IntakeError,
                        'semantic_producer_output_set_invalid'):
                    INTAKE._validate_semantic_producer_report(
                        fixture.scene, context['scene'], context['request'],
                        context['authority'], fixture.probe_identity,
                        context['frame_report'], context['semantic'], True)

    def test_output_root_escape_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.destination = fixture.root / 'outside-root'
            fixture.refresh()
            with self.assertRaisesRegex(
                    PRODUCER.ProducerError,
                    'semantic_producer_output_root_escape'):
                fixture.run()
            self.assertFalse(fixture.destination.exists())

    def test_wrong_output_filename_is_rejected_by_consumer(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            result = fixture.run()
            context = fixture.consumer_context(result)
            original = Path(result['outputs']['ground_truth']['path'])
            wrong = original.with_name('renamed-ground-truth.json')
            original.rename(wrong)
            wrong_identity = INTAKE.regular_file_identity(wrong)
            report_path = Path(result['report_identity']['path'])
            report = json.loads(report_path.read_text(encoding='utf-8'))
            report['outputs']['ground_truth'] = wrong_identity
            _write_json(report_path, report)
            context['scene']['artifacts']['ground_truth'] = wrong_identity
            context['scene']['artifacts']['semantic_producer_report'] = (
                INTAKE.regular_file_identity(report_path))
            with self.assertRaisesRegex(
                    INTAKE.IntakeError,
                    'semantic_producer_output_set_invalid'):
                INTAKE._validate_semantic_producer_report(
                    fixture.scene, context['scene'], context['request'],
                    context['authority'], fixture.probe_identity,
                    context['frame_report'], context['semantic'], True)

    def test_partial_write_leaves_machine_rejected_incomplete_marker(self):
        with TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            original_open = Path.open

            def failing_open(path, mode='r', *args, **kwargs):
                if path.name == 'tf_records.json' and mode == 'xb':
                    raise OSError('injected test-only write failure')
                return original_open(path, mode, *args, **kwargs)

            with mock.patch.object(Path, 'open', new=failing_open):
                with self.assertRaisesRegex(
                        PRODUCER.ProducerError,
                        'semantic_producer_output_write_failed'):
                    fixture.run()
            self.assertTrue((
                fixture.destination / 'INCOMPLETE_DO_NOT_USE').is_file())
            self.assertFalse((
                fixture.destination / PRODUCER.REPORT_NAME).exists())

    def test_parser_rejects_missing_unknown_and_duplicate_options(self):
        base = [
            '--request', 'r', '--authority', 'a',
            '--authority-size-bytes', '1', '--authority-sha256', '0' * 64,
            '--output-directory', 'o', '--test-only']
        cases = [
            base[:-2],
            base + ['--unknown'],
            base + ['--request', 'again'],
        ]
        for argv in cases:
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as ctx:
                PRODUCER.parse_args(argv)
            self.assertEqual(2, ctx.exception.code)


if __name__ == '__main__':
    unittest.main()
