"""Offline tests for the fail-closed formal evidence readiness gate."""

import copy
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from limo_cleanup_perception import perception_readiness
from limo_cleanup_perception.typed_raw_binding import create_binding
from limo_cleanup_perception.perception_readiness import (
    evaluate_readiness as _evaluate_readiness,
)
from src.limo_cleanup_perception.test.test_rgbd_bag_indexer import (
    STREAM_TOPICS as RAW_STREAM_TOPICS,
    _image,
    _tf,
    create_bag,
)
from src.limo_cleanup_perception.test.test_ros1_field_install_gate import (
    build_valid_ros1_field_install_fixture,
)


SCENES = ('background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
TEST_MODEL_HASHES = {
    'plastic_bottle': hashlib.sha256(b'bottle-model').hexdigest(),
    'trash_bin': hashlib.sha256(b'bin-model').hexdigest(),
}
WORKSPACE = Path(__file__).resolve().parents[3]
ROS1_DIAGNOSTIC_ROOT = (
    WORKSPACE / 'evidence' / 'perception_v2_field_20260814' /
    'diagnostic_shared_graph')
ROS1_DIAGNOSTIC_BAG = (
    ROS1_DIAGNOSTIC_ROOT /
    'v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag')
ROS1_DIAGNOSTIC_MANIFEST_V3 = (
    ROS1_DIAGNOSTIC_ROOT /
    'v2_ros1_shared_graph_diagnostic_20260814T052442Z.'
    'diagnostic-manifest-v3.json')


def _evaluate(bundle, payload, now_unix_sec=2000.0, **_unused):
    canonical_binding = None
    canonical_audit = None
    try:
        declaration = payload['ros1_field_install_validation']
        evidence_path = Path(declaration['path'])
        if not evidence_path.is_absolute():
            evidence_path = Path(bundle).parent / evidence_path
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        workspace = Path(evidence['workspace_root'])
        canonical_audit = (
            perception_readiness.audit_ros1_noetic_field_source_contract(
                workspace=workspace))
        canonical_binding = (
            perception_readiness.make_ros1_canonical_source_binding(
                workspace=workspace, source_audit=canonical_audit,
                test_only=True))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        canonical_binding = None
        canonical_audit = None
    return _evaluate_readiness(
        bundle, payload, now_unix_sec=now_unix_sec,
        expected_model_hashes=TEST_MODEL_HASHES,
        canonical_source_binding=canonical_binding,
        canonical_source_audit=canonical_audit,
        allow_test_synthetic_binding=True)


evaluate_readiness = _evaluate


def _write_json(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
    return {
        'path': path.name,
        'size_bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _artifact_identity(root, entry):
    path = root / entry['path']
    return {
        'path': str(path.resolve()),
        'size_bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_raw_capture(root, scene, base_time, capture_id, stream_topics):
    path = root / (scene + '.db3')
    if path.exists():
        path.unlink()
    self_topics = dict(RAW_STREAM_TOPICS)
    if stream_topics != self_topics:
        raise AssertionError('readiness test topics drifted from raw fixture')
    create_bag(
        path, frame_count=30, base_time_ns=int(base_time * 1e9),
        frame_period_ns=10_000_000)
    source = {
        'path': path.name,
        'size_bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    inspection = perception_readiness.inspect_sqlite_bag(
        path, capture_id, scene, stream_topics)
    inspection_entry = _write_json(
        root / (scene + '-bag-inspection.json'), inspection)
    return {
        'capture_id': capture_id,
        'scene_label': scene,
        'storage_identifier': 'sqlite3',
        'storage_file': source,
        'inspection': inspection_entry,
    }


def _target(scene, index, label):
    actionable = label == 'plastic_bottle' and scene == 'bottle_outside'
    return {
        'observation_id': '{}-{}-{}'.format(scene, index, label),
        'object_class': label,
        'confidence': 0.95,
        'valid': True,
        'actionable': actionable,
        'status': ('active' if actionable else
                   'already_in_bin' if label == 'plastic_bottle' else
                   'observed'),
        'error_code': '',
        'position': {'x': 0.1, 'y': 0.2, 'z': 1.0},
        'size': {'x': 0.1, 'y': 0.2, 'z': 0.3},
        'bbox': [0.0, 0.0, 4.0, 3.0],
        'depth_m': 1.0,
        'depth_valid_pixels': 4,
        'depth_total_pixels': 4,
        'depth_valid_ratio': 1.0,
        'source': label + '_model',
        'position_semantics': (
            'aligned_depth_roi_median_at_clipped_bbox_center'),
    }


def _frames(scene):
    records = []
    base_time = 1000 + SCENES.index(scene) * 10
    for index in range(30):
        labels = []
        if scene != 'background':
            labels.append('trash_bin')
        if scene in ('bottle_in_bin', 'bottle_outside'):
            labels.append('plastic_bottle')
        stamp = {
            'sec': base_time + index // 100,
            'nanosec': (index % 100) * 10_000_000,
        }
        records.append({
            'schema_version': 1,
            'read_only': True,
            'received_unix_sec': base_time + index / 100.0 + 0.2,
            'transport_latency_sec': 0.2,
            'stamp': stamp,
            'frame_id': 'camera_color_optical_frame',
            'task_id': 'read-only-acceptance',
            'sequence': index + 1,
            'scene': scene,
            'valid': True,
            'status': 'targets_ready' if labels else 'no_targets',
            'error_code': '',
            'sync_span_sec': 0.02,
            'processing_latency_sec': 0.1,
            'targets': [_target(scene, index, label) for label in labels],
        })
    return records


def _hardware_report():
    checks = []
    for name in perception_readiness.REQUIRED_HARDWARE_CHECKS:
        measured = {}
        if name == 'base_to_camera_tf':
            measured = {
                'parent': 'base_link',
                'child': 'camera_color_optical_frame',
                'translation_m': [0.1, 0.0, 0.2],
                'rpy_rad': [0.0, 0.0, 0.0],
            }
        elif name == 'camera_extrinsics_match_measurement':
            measured = {
                'translation_error_m': 0.001,
                'rotation_error_rad': 0.001,
                'translation_tolerance_m': 0.01,
                'rotation_tolerance_rad': 0.02,
                'measurement_reference_sha256': 'FILL_REFERENCE_SHA',
            }
        elif name == 'no_actuation_publishers':
            measured = {'active_publishers': {}}
        elif name == 'no_actuation_subscribers':
            measured = {'active_subscribers': {}}
        checks.append({'name': name, 'status': 'PASS', 'measured': measured})
    return {'schema_version': 1, 'result': 'PASS', 'read_only': True,
            'generated_at_unix_sec': 1050.0,
            'checks': checks}


def _rgbd(base_time):
    streams = {}
    for name in perception_readiness.REQUIRED_STREAMS:
        stream = {
            'topic': RAW_STREAM_TOPICS[name],
            'message_type': perception_readiness.EXPECTED_STREAM_TYPES[name],
            'frame_id': 'camera_color_optical_frame',
            'width': 4,
            'height': 3,
            'message_count': 30,
            'first_stamp_unix_sec': base_time,
            'last_stamp_unix_sec': base_time + 0.29,
        }
        if name == 'aligned_depth':
            stream['first_stamp_unix_sec'] = base_time + 0.02
            stream['last_stamp_unix_sec'] = base_time + 0.31
        elif name in ('rgb_camera_info', 'depth_camera_info'):
            stream['first_stamp_unix_sec'] = base_time + 0.01
            stream['last_stamp_unix_sec'] = base_time + 0.30
        if name in ('rgb', 'aligned_depth'):
            stream['encoding'] = 'bgr8' if name == 'rgb' else '16UC1'
        if name == 'aligned_depth':
            stream['depth_scale_m'] = 0.001
        if 'camera_info' in name:
            stream['intrinsics'] = {
                'fx': 500.0, 'fy': 500.0, 'cx': 2.0, 'cy': 1.5}
        streams[name] = stream
    return {'schema_version': 1, 'streams': streams,
            'accepted_bundle_count': 30,
            'sync_span_sec': [0.02] * 30}


def _truth(scene, frames, binding):
    raw_by_row = {
        item['typed_row_index']: item['raw_bundle']
        for item in binding['frame_bindings']}
    annotations = []
    for row_index, frame in enumerate(frames):
        raw = raw_by_row[row_index]
        instances = []
        for target_index, target in enumerate(frame['targets']):
            instance = {
                'instance_id': '{}-{}-gt-{}'.format(
                    scene, frame['sequence'], target_index),
                'object_class': target['object_class'],
                'bbox': target['bbox'],
            }
            if target['object_class'] == 'plastic_bottle':
                instance['inside_trash_bin'] = scene == 'bottle_in_bin'
            instances.append(instance)
        annotations.append({
            'sequence': frame['sequence'],
            'stamp': frame['stamp'],
            'raw_rgb': {
                'bundle_index': raw['bundle_index'],
                'message_id': raw['stream_message_ids']['rgb'],
                'header_stamp_ns': raw['header_stamps_ns']['rgb'],
                'payload_sha256': raw['stream_payload_sha256']['rgb'],
                'serialized_size_bytes': raw[
                    'stream_serialized_size_bytes']['rgb'],
            },
            'presence': {
                'plastic_bottle': scene in (
                    'bottle_in_bin', 'bottle_outside'),
                'trash_bin': scene != 'background',
            },
            'instances': instances,
        })
    return {
        'schema_version': 2,
        'scene': scene,
        'exhaustive': True,
        'classes': ['plastic_bottle', 'trash_bin'],
        'annotator': 'annotator-a',
        'reviewer': 'reviewer-b',
        'reviewed_at_unix_sec': 1100.0,
        'frames': annotations,
    }


def _build_bundle(root):
    bottle = root / 'nongfu_yolov8n_best.pt'
    bottle.write_bytes(b'bottle-model')
    trash_bin = root / 'trash_bin_yolov8n_best.pt'
    trash_bin.write_bytes(b'bin-model')
    source_files = []
    for name in perception_readiness.REQUIRED_SOURCE_BASENAMES:
        path = root / name
        path.write_bytes((
            Path(perception_readiness.__file__).resolve().parent / name
        ).read_bytes())
        source_files.append(path)

    def binary_entry(path):
        return {
            'path': path.name,
            'size_bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    reference = root / 'camera-extrinsics-reference.txt'
    reference.write_text('independent mount survey\n', encoding='utf-8')

    reference_entry = binary_entry(reference)
    release_id = 'test-v2-release-0001'
    manifest_generated_at = 800.0
    project_root = Path(perception_readiness.__file__).resolve().parents[3]
    build_manifest_entries = []
    for name in perception_readiness._required_build_source_names():
        package, relative = name.split(':', 1)
        package_root = project_root / (
            'src/limo_cleanup_interfaces' if package == 'interfaces'
            else 'src/limo_cleanup_perception')
        source = package_root / relative
        build_manifest_entries.append({
            'name': name,
            'path': str(source.relative_to(project_root).as_posix()),
            'size_bytes': source.stat().st_size,
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        })
    manifest_result = perception_readiness.canonical_file_manifest(
        build_manifest_entries, project_root)
    source_manifest_path = root / 'source-manifest.json'
    source_manifest_value = {
        'schema_version': 1,
        'release_id': release_id,
        'generated_at_unix_sec': manifest_generated_at,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'scope': 'complete_interfaces_and_perception_package_inputs',
        'package_roots': [
            'src/limo_cleanup_interfaces', 'src/limo_cleanup_perception'],
        'required_source_names': list(
            perception_readiness._required_build_source_names()),
        'entries': build_manifest_entries,
        'source_set_sha256': manifest_result['sha256'],
    }
    source_manifest_path.write_text(
        json.dumps(source_manifest_value, sort_keys=True) + '\n',
        encoding='utf-8')
    source_manifest_artifact_sha = hashlib.sha256(
        source_manifest_path.read_bytes()).hexdigest()
    build_logs = {}
    for name in ('build', 'test', 'test_result'):
        path = root / ('colcon-' + name + '.log')
        path.write_text('synthetic isolated ' + name + ' log\n', encoding='utf-8')
        build_logs[name] = binary_entry(path)
    hardware_value = _hardware_report()
    next(item for item in hardware_value['checks'] if item['name'] ==
         'camera_extrinsics_match_measurement')['measured'][
             'measurement_reference_sha256'] = reference_entry['sha256']
    hardware = _write_json(root / 'hardware.json', hardware_value)
    runtime_checks = [
        {'name': name, 'status': 'PASS'}
        for name in (
            'python_module_numpy', 'python_module_cv2',
            'python_module_torch', 'python_module_ultralytics',
            'ultralytics_exact_version', 'source_hashes_match')]
    runtime_checks.extend([
        {'name': 'model_nongfu_yolov8n_best.pt', 'status': 'PASS',
         'measured': binary_entry(bottle)['sha256']},
        {'name': 'model_trash_bin_yolov8n_best.pt', 'status': 'PASS',
         'measured': binary_entry(trash_bin)['sha256']},
        {'name': 'models_load_and_labels_match', 'status': 'PASS'},
    ])
    runtime = _write_json(root / 'runtime.json', {
        'schema_version': 1,
        'passed': True,
        'mode': 'filesystem_only_no_ros_graph_no_hardware',
        'platform': {
            'python': '3.8.10', 'machine': 'aarch64',
            'ros_distro': 'foxy'},
        'release_id': release_id,
        'source_manifest_artifact_sha256': source_manifest_artifact_sha,
        'source_set_sha256': manifest_result['sha256'],
        'model_sha256': {
            'plastic_bottle': binary_entry(bottle)['sha256'],
            'trash_bin': binary_entry(trash_bin)['sha256'],
        },
        'generated_at_unix_sec': 900.0,
        'checks': runtime_checks,
    })
    isolation_root = '/tmp/limo_v2_colcon_test-v2-release-0001'
    ros_build = _write_json(root / 'ros-build.json', {
        'schema_version': 2,
        'result': 'PASS',
        'packages': [
            'limo_cleanup_interfaces', 'limo_cleanup_perception'],
        'exit_codes': {'build': 0, 'test': 0, 'test_result': 0},
        'test_failures': 0,
        'nodes_started': False,
        'generated_at_unix_sec': 900.0,
        'workspace_root': str(project_root.resolve()),
        'isolation_root': isolation_root,
        'cwd': str(project_root.resolve()),
        'platform': {
            'python': '3.8.10', 'machine': 'aarch64',
            'ros_distro': 'foxy'},
        'commands': perception_readiness._isolated_colcon_argv(
            str(project_root.resolve()), isolation_root),
        'release_id': release_id,
        'logs': build_logs,
        'source_manifest_artifact': binary_entry(source_manifest_path),
        'source_manifest': {
            'required_source_names': list(
                perception_readiness._required_build_source_names()),
            'entries': build_manifest_entries,
            'source_set_sha256': manifest_result['sha256'],
        },
    })
    ros1_field = build_valid_ros1_field_install_fixture(
        root / 'ros1-field-fixture',
        release_binding={
            'release_id': release_id,
            'source_set_sha256': manifest_result['sha256'],
        },
        model_paths={
            'plastic_bottle': bottle,
            'trash_bin': trash_bin,
        },
        now=900.0)
    payload = {
        'schema_version': 1,
        'evidence_scope': 'formal_four_scene_rgbd_acceptance',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'release_binding': {
            'release_id': release_id,
            'source_manifest_artifact_sha256': source_manifest_artifact_sha,
            'source_set_sha256': manifest_result['sha256'],
            'manifest_generated_at_unix_sec': manifest_generated_at,
        },
        'software_binding': {
            'models': {
                'plastic_bottle': binary_entry(bottle),
                'trash_bin': binary_entry(trash_bin),
            },
            'sources': [binary_entry(path) for path in source_files],
            'runtime_preflight': runtime,
        },
        'hardware_readiness': hardware,
        'extrinsics_measurement_reference': reference_entry,
        'ros_build_validation': ros_build,
        'ros1_field_install_validation': ros1_field['declaration'],
        'scenes': {},
    }
    for scene_index, scene in enumerate(SCENES):
        frames = _frames(scene)
        stream_topics = dict(RAW_STREAM_TOPICS)
        raw_capture = _write_raw_capture(
            root, scene, 1000.0 + scene_index * 10,
            'capture-' + scene, stream_topics)
        frames_path = root / (scene + '.jsonl')
        frames_path.write_text(''.join(
            json.dumps(item, sort_keys=True) + '\n' for item in frames),
            encoding='utf-8')
        frames_entry = binary_entry(frames_path)
        manifest = {
            'schema_version': 1,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'scene': scene,
            'topic': '/cleanup/perception/frames',
            'message_type': 'limo_cleanup_interfaces/msg/PerceptionFrame',
            'task_id': 'read-only-acceptance',
            'max_frames': 30,
            'duration_sec': 60.0,
            'received_frames': 30,
            'unique_sequence_frames': 30,
            'duplicate_sequences': 0,
            'serialization_errors': 0,
            'interrupted': False,
            'completed_max_frames': True,
            'output': dict(frames_entry),
            'forbidden_control_topics': [
                '/cmd_vel', '/cleanup/base/safe_cmd_vel',
                '/navigate_to_pose', '/arm_controller/joint_trajectory',
                '/gripper_controller/commands',
            ],
        }
        manifest_path = root / (scene + '-manifest.json')
        manifest_entry = _write_json(manifest_path, manifest)
        binding_value = create_binding(
            frames_path, manifest_path,
            root / raw_capture['storage_file']['path'],
            root / raw_capture['inspection']['path'], scene,
            'capture-' + scene, 'read-only-acceptance',
            1000.0 + scene_index * 10, 1001.0 + scene_index * 10,
            release_id, manifest_result['sha256'], {
                'plastic_bottle': binary_entry(bottle)['sha256'],
                'trash_bin': binary_entry(trash_bin)['sha256'],
            })
        binding_entry = _write_json(
            root / (scene + '-typed-raw-binding.json'), binding_value)
        capture_provenance = perception_readiness._capture_provenance(
            binding_value)
        tf = {
            'schema_version': 1,
            'capture_provenance': capture_provenance,
            'parent': 'base_link',
            'child': 'camera_color_optical_frame',
            'translation_m': [0.1, 0.0, 0.2],
            'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
            'independent_extrinsics_validated': True,
            'measurement_owner': 'surveyor-a',
            'measurement_source': 'independent_mount_survey',
            'measurement_reference_sha256': reference_entry['sha256'],
            'measured_at_unix_sec': 900.0,
            'translation_error_m': 0.001,
            'rotation_error_rad': 0.001,
            'translation_tolerance_m': 0.01,
            'rotation_tolerance_rad': 0.02,
        }
        truth_value = _truth(scene, frames, binding_value)
        truth_value['capture_provenance'] = capture_provenance
        truth_instances = [
            (annotation, instance)
            for annotation in truth_value['frames']
            for instance in annotation['instances']]
        xyz = {
            'schema_version': 1,
            'capture_provenance': capture_provenance,
            'frame_id': 'base_link',
            'units': 'm',
            'measurement_method': 'survey_fixture',
            'samples': [
                {'sequence': annotation['sequence'],
                 'stamp': annotation['stamp'],
                 'instance_id': instance['instance_id'],
                 'object_class': instance['object_class'],
                 'observation_id': '{}-{}-{}'.format(
                     scene, annotation['sequence'] - 1,
                     instance['object_class']),
                 'predicted_camera_frame': 'camera_color_optical_frame',
                 'predicted_camera_xyz_m': [0.1, 0.2, 1.0],
                 'predicted_base_xyz_m': [0.2, 0.2, 1.2],
                 'truth_xyz_m': [0.2, 0.2, 1.2]}
                for annotation, instance in truth_instances],
        }
        expected_targets = sum(len(item['targets']) for item in frames)
        raw_by_row = {
            item['typed_row_index']: item['raw_bundle']
            for item in binding_value['frame_bindings']}
        depth_reference = {
            'schema_version': 1,
            'capture_provenance': capture_provenance,
            'scene': scene,
            'capture_id': 'capture-' + scene,
            'capture_window': capture_provenance['capture_window'],
            'units': 'm',
            'independent_measurement': True,
            'measurement_owner': 'surveyor-c',
            'reviewer': 'reviewer-d',
            'reviewed_at_unix_sec': 1100.0,
            'samples': [
                {
                    'sequence': frame['sequence'],
                    'stamp': frame['stamp'],
                    'reference_id': '{}-depth-reference-{}'.format(
                        scene, frame['sequence']),
                    'measurement_method': 'calibrated_flat_target',
                    'expected_depth_m': 0.995,
                }
                for frame in frames],
        }
        depth_reference_entry = _write_json(
            root / (scene + '-depth-reference.json'), depth_reference)
        depth = {
            'schema_version': 2,
            'capture_provenance': capture_provenance,
            'projection_min_valid_ratio': 0.02,
            'target_roi_samples': [
                {
                    'sequence': annotation['sequence'],
                    'stamp': annotation['stamp'],
                    'instance_id': instance['instance_id'],
                    'object_class': instance['object_class'],
                    'observation_id': '{}-{}-{}'.format(
                        scene, annotation['sequence'] - 1,
                        instance['object_class']),
                    'depth_m': 1.0,
                    'depth_valid_ratio': 1.0,
                }
                for annotation, instance in truth_instances],
            'known_distance_samples': [
                {
                    'sequence': frame['sequence'],
                    'stamp': frame['stamp'],
                    'reference_id': '{}-depth-reference-{}'.format(
                        scene, frame['sequence']),
                    'roi_xyxy': [0, 0, 4, 3],
                    'measurement_method': 'calibrated_flat_target',
                    'measurement_reference_sha256':
                    depth_reference_entry['sha256'],
                    'estimator': 'median_valid_depth_in_roi',
                    'raw_depth': {
                        'bundle_index': raw_by_row[index]['bundle_index'],
                        'message_id': raw_by_row[index][
                            'stream_message_ids']['aligned_depth'],
                        'header_stamp_ns': raw_by_row[index][
                            'header_stamps_ns']['aligned_depth'],
                        'payload_sha256': raw_by_row[index][
                            'stream_payload_sha256']['aligned_depth'],
                        'serialized_size_bytes': raw_by_row[index][
                            'stream_serialized_size_bytes']['aligned_depth'],
                    },
                    'depth_encoding': '16UC1',
                    'depth_scale_m': 0.001,
                    'valid_pixel_count': 12,
                    'total_pixel_count': 12,
                    'valid_ratio': 1.0,
                    'expected_depth_m': 0.995,
                    'measured_depth_m': 1.0,
                    'absolute_error_m': 0.005,
                }
                for index, frame in enumerate(frames)],
            'expected_target_samples': expected_targets,
            'valid_target_samples': expected_targets,
        }
        scene_declaration = {
            'arrangement': {
                'capture_id': 'capture-' + scene,
                'scene_label': scene,
                'independently_arranged': True,
                'operator': 'operator-a',
                'reviewer': 'reviewer-b',
                'started_unix_sec': 1000.0 + scene_index * 10,
                'ended_unix_sec': 1001.0 + scene_index * 10,
            },
            'frames': frames_entry,
            'collector_manifest': manifest_entry,
            'typed_raw_binding': binding_entry,
            'rgbd_artifact': _write_json(
                root / (scene + '-rgbd.json'), {
                    **_rgbd(1000.0 + scene_index * 10),
                    'capture_provenance': capture_provenance,
                }),
            'raw_capture': raw_capture,
            'ground_truth': _write_json(
                root / (scene + '-truth.json'), truth_value),
            'tf_artifact': _write_json(
                root / (scene + '-tf.json'), tf),
            'xyz_ground_truth': _write_json(
                root / (scene + '-xyz.json'), xyz),
            'depth_measurement_reference': depth_reference_entry,
            'depth_quality': _write_json(
                root / (scene + '-depth.json'), depth),
            'latency': {
                'capture_provenance': capture_provenance,
                'clock_domain': 'system_time_unix',
                'use_sim_time': False,
                'sensor_stamp_clock': 'CLOCK_REALTIME',
                'receipt_clock': 'CLOCK_REALTIME',
                'synchronization_source': 'chrony',
                'synchronization_status': 'synchronized',
                'verified_at_unix_sec': 999.0 + scene_index * 10,
            },
        }
        scene_declaration['evidence_binding'] = {
            'schema_version': 1,
            'scene': scene,
            'capture_id': 'capture-' + scene,
            'capture_binding_id': capture_provenance['capture_binding_id'],
            'capture_window': capture_provenance['capture_window'],
            'release_id': capture_provenance['release_id'],
            'source_set_sha256': capture_provenance['source_set_sha256'],
            'model_sha256': capture_provenance['model_sha256'],
            'raw_capture_sha256': capture_provenance[
                'raw_capture_sha256'],
            'raw_inspection_sha256': capture_provenance[
                'raw_inspection_sha256'],
            'expected_topic_manifest': capture_provenance[
                'expected_topic_manifest'],
            'artifacts': {
                name: _artifact_identity(root, scene_declaration[field])
                for name, field in (
                    ('frames', 'frames'),
                    ('collector_manifest', 'collector_manifest'),
                    ('typed_raw_binding', 'typed_raw_binding'),
                    ('rgbd_artifact', 'rgbd_artifact'),
                    ('ground_truth', 'ground_truth'),
                    ('tf_artifact', 'tf_artifact'),
                    ('xyz_ground_truth', 'xyz_ground_truth'),
                    ('depth_measurement_reference',
                     'depth_measurement_reference'),
                    ('depth_quality', 'depth_quality'))},
        }
        payload['scenes'][scene] = scene_declaration
    bundle = root / 'bundle.json'
    bundle.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8')
    return bundle, payload


class PerceptionReadinessTest(unittest.TestCase):
    """Verify a complete bundle and representative fail-closed mutations."""

    @staticmethod
    def _mutate_json_artifact(root, payload, scene, field, mutation):
        entry = payload['scenes'][scene][field]
        path = root / entry['path']
        value = json.loads(path.read_text(encoding='utf-8'))
        mutation(value)
        path.write_text(
            json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
        entry['size_bytes'] = path.stat().st_size
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        binding = payload['scenes'][scene].get('evidence_binding')
        if isinstance(binding, dict):
            name_by_field = {
                'frames': 'frames',
                'collector_manifest': 'collector_manifest',
                'typed_raw_binding': 'typed_raw_binding',
                'rgbd_artifact': 'rgbd_artifact',
                'ground_truth': 'ground_truth',
                'tf_artifact': 'tf_artifact',
                'xyz_ground_truth': 'xyz_ground_truth',
                'depth_measurement_reference':
                'depth_measurement_reference',
                'depth_quality': 'depth_quality',
            }
            name = name_by_field.get(field)
            if name is not None:
                binding['artifacts'][name] = _artifact_identity(root, entry)

    def test_truth_raw_rgb_and_known_depth_payload_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ('truth_rgb_hash', 'ground_truth', lambda value:
                 value['frames'][0]['raw_rgb'].__setitem__(
                     'payload_sha256', '0' * 64),
                 'ground_truth_raw_rgb_binding_mismatch:background'),
                ('truth_bundle_reuse', 'ground_truth', lambda value:
                 value['frames'][1].__setitem__(
                     'raw_rgb', copy.deepcopy(value['frames'][0]['raw_rgb'])),
                 'ground_truth_raw_rgb_binding_mismatch:background'),
                ('truth_extra_key', 'ground_truth', lambda value:
                 value['frames'][0].__setitem__('raw_alias', {}),
                 'ground_truth_raw_rgb_binding_mismatch:background'),
                ('old_depth_float_list', 'depth_quality', lambda value:
                 value.update(known_distance_errors_m=[0.0] * 30),
                 'depth_artifact_schema_invalid:background'),
                ('depth_hash', 'depth_quality', lambda value:
                 value['known_distance_samples'][0]['raw_depth'].__setitem__(
                     'payload_sha256', '0' * 64),
                 'known_depth_sample_binding_mismatch:background'),
                ('depth_measured_forged', 'depth_quality', lambda value:
                 value['known_distance_samples'][0].update({
                     'measured_depth_m': 0.995,
                     'absolute_error_m': 0.0}),
                 'known_depth_sample_binding_mismatch:background'),
                ('depth_error_not_recomputed', 'depth_quality', lambda value:
                 value['known_distance_samples'][0].__setitem__(
                     'absolute_error_m', 0.0),
                 'known_depth_sample_binding_mismatch:background'),
                ('depth_roi_wrong', 'depth_quality', lambda value:
                 value['known_distance_samples'][0].__setitem__(
                     'roi_xyxy', [0, 0, 5, 3]),
                 'known_depth_sample_binding_mismatch:background'),
                ('depth_duplicate_reference', 'depth_quality', lambda value:
                 value['known_distance_samples'][1].__setitem__(
                     'reference_id', value[
                         'known_distance_samples'][0]['reference_id']),
                 'known_depth_sample_binding_mismatch:background'),
                ('depth_missing_sample', 'depth_quality', lambda value:
                 value['known_distance_samples'].pop(),
                 'known_depth_sample_coverage_mismatch:background'),
            )
            for name, field, mutation, failure in cases:
                with self.subTest(name=name):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    self._mutate_json_artifact(
                        root, payload, 'background', field, mutation)
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(failure, report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            self._mutate_json_artifact(
                root, payload, 'bin_only', 'depth_quality',
                lambda value: value['target_roi_samples'][0].update({
                    'depth_m': 0.9,
                    'depth_valid_ratio': 1.0}))
            frames_entry = payload['scenes']['bin_only']['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            frames[0]['targets'][0]['depth_m'] = 0.9
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            frames_entry['size_bytes'] = frames_path.stat().st_size
            frames_entry['sha256'] = hashlib.sha256(
                frames_path.read_bytes()).hexdigest()
            manifest_entry = payload['scenes']['bin_only'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            manifest_entry['size_bytes'] = manifest_path.stat().st_size
            manifest_entry['sha256'] = hashlib.sha256(
                manifest_path.read_bytes()).hexdigest()
            binding = payload['scenes']['bin_only']['evidence_binding']
            binding['artifacts']['frames'] = _artifact_identity(
                root, frames_entry)
            binding['artifacts']['collector_manifest'] = _artifact_identity(
                root, manifest_entry)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'depth_prediction_binding_mismatch:bin_only',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            self._mutate_json_artifact(
                root, payload, 'background', 'depth_quality',
                lambda value: value['known_distance_samples'][0].update({
                    'expected_depth_m': 0.98,
                    'absolute_error_m': 0.02}))
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'known_depth_sample_binding_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            self._mutate_json_artifact(
                root, payload, 'background',
                'depth_measurement_reference',
                lambda value: value['samples'][0].__setitem__(
                    'expected_depth_m', 0.98))
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'known_depth_sample_binding_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            self._mutate_json_artifact(
                root, payload, 'background',
                'depth_measurement_reference',
                lambda value: value['samples'].pop())
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'depth_measurement_reference_coverage_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            self._mutate_json_artifact(
                root, payload, 'background',
                'depth_measurement_reference',
                lambda value: value.__setitem__(
                    'measurement_owner', 'operator-a'))
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'depth_measurement_independence_not_proven:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            other = payload['scenes']['bin_only'][
                'depth_measurement_reference']
            payload['scenes']['background'][
                'depth_measurement_reference'] = copy.deepcopy(other)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'capture_artifact_binding_mismatch:background:'
                'depth_measurement_reference', report['failures'])
            self.assertIn(
                'scene_evidence_binding_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            self._mutate_json_artifact(
                root, payload, 'background', 'depth_quality',
                lambda value: value['known_distance_samples'][0].update({
                    'expected_depth_m': 0.979999,
                    'absolute_error_m': 0.020001}))
            self._mutate_json_artifact(
                root, payload, 'background',
                'depth_measurement_reference',
                lambda value: value['samples'][0].__setitem__(
                    'expected_depth_m', 0.979999))
            reference_entry = payload['scenes']['background'][
                'depth_measurement_reference']
            reference_sha = reference_entry['sha256']
            self._mutate_json_artifact(
                root, payload, 'background', 'depth_quality',
                lambda value: value['known_distance_samples'][0].__setitem__(
                    'measurement_reference_sha256', reference_sha))
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'known_depth_error_exceeded:background', report['failures'])

    def test_scene_evidence_binding_rejects_cross_artifact_splices(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ('missing', lambda binding: binding.pop('artifacts'),
                 'scene_evidence_binding_invalid:background'),
                ('wrong_truth_hash', lambda binding: binding['artifacts'][
                    'ground_truth'].__setitem__('sha256', '0' * 64),
                 'scene_evidence_binding_mismatch:background'),
                ('wrong_capture_window', lambda binding: binding[
                    'capture_window'].__setitem__(
                        'ended_unix_sec', 1000.5),
                 'scene_evidence_binding_mismatch:background'),
                ('wrong_model', lambda binding: binding['model_sha256'].
                 __setitem__('trash_bin', '0' * 64),
                 'scene_evidence_binding_mismatch:background'),
            )
            for name, mutation, failure in cases:
                with self.subTest(name=name):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    mutation(payload['scenes']['background'][
                        'evidence_binding'])
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(failure, report['failures'])

    def test_template_like_null_raw_artifacts_fail_without_exception(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            payload['scenes']['background']['raw_capture'][
                'storage_file'] = None
            payload['scenes']['background']['raw_capture'][
                'inspection'] = None
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('missing_raw_capture:background', report['failures'])

    def test_unpaired_rate_boundaries_are_fail_closed(self):
        stream_topics = [
            {'role': stream, 'message_count': count}
            for stream, count in zip(
                perception_readiness.REQUIRED_STREAMS, (20, 20, 20, 20))]
        cases = (
            ('zero', stream_topics, dict.fromkeys(
                perception_readiness.REQUIRED_STREAMS, 0), 80, 0, 0.0,
             True, False),
            ('exact_five', stream_topics, dict.fromkeys(
                perception_readiness.REQUIRED_STREAMS, 1), 80, 4, 0.05,
             True, False),
            ('epsilon', [
                {'role': stream, 'message_count': 19 if stream == 'rgb' else 20}
                for stream in perception_readiness.REQUIRED_STREAMS], {
                    'rgb': 1, 'aligned_depth': 0,
                    'rgb_camera_info': 0, 'depth_camera_info': 0},
             79, 1, 1 / 79, True, True),
            ('seventy', [
                {'role': stream, 'message_count': 10}
                for stream in perception_readiness.REQUIRED_STREAMS],
             dict.fromkeys(perception_readiness.REQUIRED_STREAMS, 7),
             40, 28, 0.7, True, True),
            ('zero_denominator', [
                {'role': stream, 'message_count': 0 if stream == 'rgb' else 20}
                for stream in perception_readiness.REQUIRED_STREAMS],
             dict.fromkeys(perception_readiness.REQUIRED_STREAMS, 0),
             60, 0, 0.0, False, False),
        )
        for (name, topics, unmatched, total, unpaired, rate,
             expected_valid, expected_exceeded) in cases:
            with self.subTest(raw_stream=name):
                report, valid, exceeded = (
                    perception_readiness._raw_stream_unpaired_report(
                        topics, unmatched, total, unpaired, rate))
                self.assertEqual(expected_valid, valid)
                self.assertEqual(expected_exceeded, exceeded)
                if valid:
                    self.assertEqual(
                        set(perception_readiness.REQUIRED_STREAMS),
                        set(report['unpaired_rate_by_stream']))

        binding_cases = (
            ('zero', 20, 20, 0, 0, 20, 0.0, True, False),
            ('exact_five', 20, 20, 1, 1, 19, 0.05, True, False),
            ('epsilon', 19, 18, 1, 0, 18, 1 / 19, True, True),
            ('seventy', 10, 10, 7, 7, 3, 0.7, True, True),
            ('zero_typed', 0, 20, 0, 20, 0, 1.0, False, False),
            ('zero_raw', 20, 0, 20, 0, 0, 1.0, False, False),
        )
        for (name, typed, raw, unpaired_typed, unpaired_raw, paired,
             rate, expected_valid, expected_exceeded) in binding_cases:
            with self.subTest(typed_raw=name):
                report, valid, exceeded = (
                    perception_readiness._typed_raw_unpaired_report(
                        typed, raw, unpaired_typed, unpaired_raw,
                        [{}] * paired, rate))
                self.assertEqual(expected_valid, valid)
                self.assertEqual(expected_exceeded, exceeded)
                if valid:
                    self.assertEqual(rate, report['unpaired_rate'])

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            frames_path = root / scene['frames']['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            binding_path = root / scene['typed_raw_binding']['path']
            binding = json.loads(binding_path.read_text(encoding='utf-8'))
            inspection_path = root / scene['raw_capture']['inspection']['path']
            inspection = json.loads(inspection_path.read_text(encoding='utf-8'))
            partial_binding = copy.deepcopy(binding)
            partial_binding['frame_bindings'] = binding['frame_bindings'][:19]
            partial_binding['typed_frame_count'] = 19
            partial_binding['raw_bundle_count'] = 20
            partial_binding['unpaired_typed_count'] = 0
            partial_binding['unpaired_raw_bundle_count'] = 1
            partial_binding['unpaired_rate'] = 0.05
            raw_report = {
                'bundles': inspection['accepted_bundles'][:20],
                'tf_graph': {
                    'bundle_transforms': inspection['tf_graph'][
                        'bundle_transforms'][:20]},
            }
            failures = []
            perception_readiness._check_typed_raw_sync_binding(
                'background', frames[:19], raw_report,
                partial_binding, failures)
            self.assertEqual([], failures)

    def test_control_claim_scanner_and_collector_fail_closed(self):
        dangerous_keys = (
            'control_topic', 'control_topics', 'publisher', 'publishers',
            'command_topic', 'command_topics',
            'publishes_topic', 'publishes_topics')
        for key in dangerous_keys:
            with self.subTest(scanner=key):
                self.assertTrue(
                    perception_readiness._contains_forbidden_control_claim({
                        'outer': {'inner': {key: '/cmd_vel'}}}))
        self.assertFalse(
            perception_readiness._contains_forbidden_control_claim({
                'forbidden_control_topics': ['/cmd_vel']}))
        self.assertFalse(
            perception_readiness._contains_forbidden_control_claim({
                'active_publishers': {}}))

        with TemporaryDirectory() as directory:
            root = Path(directory)

            def mutate_manifest(payload, mutation):
                entry = payload['scenes']['background'][
                    'collector_manifest']
                path = root / entry['path']
                manifest = json.loads(path.read_text(encoding='utf-8'))
                mutation(manifest)
                path.write_text(
                    json.dumps(manifest, sort_keys=True) + '\n',
                    encoding='utf-8')
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            cases = (
                ('motion', lambda item: item.__setitem__(
                    'authorizes_motion', True),
                 'collector_motion_contract_violation:background'),
                ('publisher', lambda item: item.__setitem__(
                    'publishes_ros_messages', True),
                 'collector_publisher_contract_violation:background'),
                ('nested_command', lambda item: item['output'].__setitem__(
                    'command_topic', '/cmd_vel'),
                 'collector_control_contract_violation:background'),
                ('wrong_forbidden', lambda item: item.__setitem__(
                    'forbidden_control_topics', ['/cmd_vel']),
                 'manifest_control_policy_mismatch:background'),
                ('missing_field', lambda item: item.pop('duration_sec'),
                 'invalid_collector_manifest:background'),
                ('short', lambda item: item.__setitem__('max_frames', 29),
                 'collector_target_below_minimum:background'),
                ('zero_duration', lambda item: item.__setitem__(
                    'duration_sec', 0.0),
                 'collector_duration_invalid:background'),
            )
            for name, mutation, failure in cases:
                with self.subTest(collector=name):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    mutate_manifest(payload, mutation)
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(failure, report['failures'])

    def test_capture_provenance_and_frozen_manifest_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            truth_entry = payload['scenes']['background']['ground_truth']
            truth_path = root / truth_entry['path']
            truth = json.loads(truth_path.read_text(encoding='utf-8'))
            truth['capture_provenance']['raw_capture_sha256'] = '0' * 64
            truth_path.write_text(
                json.dumps(truth, sort_keys=True) + '\n', encoding='utf-8')
            truth_entry['size_bytes'] = truth_path.stat().st_size
            truth_entry['sha256'] = hashlib.sha256(
                truth_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'capture_artifact_binding_mismatch:background:ground_truth',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            truth_entry = payload['scenes']['background']['ground_truth']
            truth_path = root / truth_entry['path']
            truth = json.loads(truth_path.read_text(encoding='utf-8'))
            truth['raw_capture_sha256'] = '0' * 64
            truth_path.write_text(
                json.dumps(truth, sort_keys=True) + '\n', encoding='utf-8')
            truth_entry['size_bytes'] = truth_path.stat().st_size
            truth_entry['sha256'] = hashlib.sha256(
                truth_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'ground_truth_schema_invalid:background', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            binding_entry = payload['scenes']['background'][
                'typed_raw_binding']
            binding_path = root / binding_entry['path']
            binding = json.loads(binding_path.read_text(encoding='utf-8'))
            binding['expected_topic_manifest']['sha256'] = '0' * 64
            envelope = {
                key: binding[key] for key in (
                    'capture_id', 'scene', 'task_id', 'capture_window',
                    'release_id', 'source_set_sha256', 'model_sha256',
                    'typed_frames', 'collector_manifest', 'raw_capture',
                    'raw_inspection', 'expected_topic_manifest')}
            binding['capture_binding_id'] = hashlib.sha256(json.dumps(
                envelope, ensure_ascii=False, sort_keys=True,
                separators=(',', ':')).encode('utf-8')).hexdigest()
            binding_path.write_text(
                json.dumps(binding, sort_keys=True) + '\n', encoding='utf-8')
            binding_entry['size_bytes'] = binding_path.stat().st_size
            binding_entry['sha256'] = hashlib.sha256(
                binding_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'typed_raw_topic_manifest_mismatch:background',
                report['failures'])

    def test_complete_synthetic_evidence_bundle_is_validator_only(self):
        with TemporaryDirectory() as directory:
            bundle, payload = _build_bundle(Path(directory))
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['passed'])
            self.assertFalse(report['delivery_ready'])
            self.assertTrue(report['offline_migration_passed'])
            self.assertEqual([], report['non_delivery_failures'])
            self.assertFalse(report['delivery_gate_summary'][
                'ros1_field_install_pass'])
            self.assertTrue(report['delivery_gate_summary'][
                'formal_four_scene_pass'])
            self.assertTrue(report['delivery_gate_summary'][
                'formal_tf_3d_pass'])
            self.assertIn(
                perception_readiness.ROS1_TEST_ONLY_SOURCE_BINDING,
                report['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                report['failures'])
            self.assertTrue(report['read_only'])
            self.assertFalse(report['authorizes_motion'])
            self.assertFalse(report['publishes_ros_messages'])
            self.assertTrue(report['typed_frame_evaluator']['passed'])
            json.dumps(report, sort_keys=True)
            self.assertEqual(4, len(report['scene_reports']))
            self.assertEqual(
                0.05, report['thresholds'][
                    'max_raw_stream_unpaired_rate'])
            for scene in SCENES:
                scene_report = report['scene_reports'][scene]
                self.assertEqual(
                    0.0, scene_report['typed_raw_binding'][
                        'unpaired_rate'])
                self.assertEqual(
                    dict.fromkeys(
                        perception_readiness.REQUIRED_STREAMS, 0.0),
                    scene_report['raw_capture']['unpaired'][
                        'unpaired_rate_by_stream'])

    def test_raw_source_tf_frame_and_future_provenance_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            del payload['scenes']['background']['raw_capture']
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('missing_raw_capture:background', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            source_entry = next(
                item for item in payload['software_binding']['sources']
                if Path(item['path']).name == 'dual_model_detector.py')
            source_path = root / source_entry['path']
            source_path.write_bytes(b'not the current detector source')
            refresh(source_entry, source_path)
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'source_hash_mismatch:dual_model_detector.py',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            xyz_entry = payload['scenes']['bottle_outside'][
                'xyz_ground_truth']
            xyz_path = root / xyz_entry['path']
            xyz = json.loads(xyz_path.read_text(encoding='utf-8'))
            for sample in xyz['samples']:
                sample['predicted_camera_frame'] = 'wrong_camera_frame'
            xyz_path.write_text(
                json.dumps(xyz, sort_keys=True) + '\n', encoding='utf-8')
            refresh(xyz_entry, xyz_path)
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'xyz_camera_frame_mismatch:bottle_outside',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            tf_entry = payload['scenes']['bin_only']['tf_artifact']
            tf_path = root / tf_entry['path']
            tf_value = json.loads(tf_path.read_text(encoding='utf-8'))
            tf_value['measurement_reference_sha256'] = 'b' * 64
            tf_path.write_text(
                json.dumps(tf_value, sort_keys=True) + '\n', encoding='utf-8')
            refresh(tf_entry, tf_path)
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'extrinsics_reference_hash_mismatch:bin_only',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            for scene in SCENES:
                arrangement = payload['scenes'][scene]['arrangement']
                arrangement['started_unix_sec'] += 10_000_000_000
                arrangement['ended_unix_sec'] += 10_000_000_000
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('capture_time_future:background', report['failures'])

            bundle, baseline = _build_bundle(root)
            report = evaluate_readiness(
                bundle, baseline, now_unix_sec=2_000_000_000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'capture_evidence_stale:background', report['failures'])
            self.assertIn('hardware_readiness_stale', report['failures'])
            self.assertIn('runtime_preflight_stale', report['failures'])
            self.assertIn(
                'ros_build_validation_stale',
                report['non_delivery_failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            inspection_entry = payload['scenes']['background'][
                'raw_capture']['inspection']
            inspection_path = root / inspection_entry['path']
            inspection = json.loads(inspection_path.read_text(encoding='utf-8'))
            inspection['messages'][0]['serialized_sha256'] = '0' * 64
            inspection_path.write_text(
                json.dumps(inspection, sort_keys=True) + '\n',
                encoding='utf-8')
            refresh(inspection_entry, inspection_path)
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'raw_capture_sqlite_index_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            frames_entry = payload['scenes']['background']['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            for frame in frames:
                frame['transport_latency_sec'] = 0.0
                frame['sync_span_sec'] = 0.14
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            refresh(frames_entry, frames_path)
            manifest_entry = payload['scenes']['background'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            refresh(manifest_entry, manifest_path)
            report = evaluate_readiness(bundle, payload, now_unix_sec=2000.0)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'transport_latency_binding_mismatch:background',
                report['failures'])
            self.assertIn(
                'typed_raw_sync_binding_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            frames_entry = payload['scenes']['background']['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            frames[0]['stamp']['nanosec'] += 1
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            refresh(frames_entry, frames_path)
            manifest_entry = payload['scenes']['background'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            refresh(manifest_entry, manifest_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'typed_raw_frame_identity_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            binding_entry = payload['scenes']['background'][
                'typed_raw_binding']
            binding_path = root / binding_entry['path']
            binding = json.loads(binding_path.read_text(encoding='utf-8'))
            binding['frame_bindings'][0]['raw_bundle'][
                'stream_payload_sha256']['rgb'] = '0' * 64
            binding_path.write_text(
                json.dumps(binding, sort_keys=True) + '\n', encoding='utf-8')
            refresh(binding_entry, binding_path)
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'typed_raw_payload_binding_mismatch:background',
                report['failures'])

    def test_single_over_limit_sync_sample_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, payload = _build_bundle(root)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            scene = payload['scenes']['background']
            inspection_entry = scene['raw_capture']['inspection']
            inspection_path = root / inspection_entry['path']
            bag_path = root / scene['raw_capture']['storage_file']['path']
            connection = sqlite3.connect(str(bag_path))
            try:
                topic_id = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        RAW_STREAM_TOPICS['aligned_depth'],)).fetchone()[0]
                message_id, payload_blob = connection.execute(
                    'SELECT id, data FROM messages WHERE topic_id=? '
                    'ORDER BY id DESC LIMIT 1', (topic_id,)).fetchone()
                decoded_stamp = perception_readiness.inspect_sqlite_bag(
                    bag_path, 'capture-background', 'background',
                    RAW_STREAM_TOPICS)['messages'][message_id - 1][
                        'decoded']['stamp_ns']
                connection.execute(
                    'UPDATE messages SET data=?, timestamp=? WHERE id=?', (
                        _image(
                            decoded_stamp + 160_000_000,
                            'camera_color_optical_frame', '16UC1'),
                        decoded_stamp + 180_000_000,
                        message_id))
                connection.commit()
            finally:
                connection.close()
            refresh(scene['raw_capture']['storage_file'], bag_path)
            inspection = perception_readiness.inspect_sqlite_bag(
                bag_path, 'capture-background', 'background',
                RAW_STREAM_TOPICS)
            inspection_path.write_text(
                json.dumps(inspection, sort_keys=True) + '\n',
                encoding='utf-8')
            refresh(inspection_entry, inspection_path)
            rgbd_entry = scene['rgbd_artifact']
            rgbd_path = root / rgbd_entry['path']
            rgbd = json.loads(rgbd_path.read_text(encoding='utf-8'))
            rgbd['sync_span_sec'][0] = 0.163
            rgbd_path.write_text(
                json.dumps(rgbd, sort_keys=True) + '\n', encoding='utf-8')
            refresh(rgbd_entry, rgbd_path)
            frames_entry = scene['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            frames[0]['sync_span_sec'] = 0.163
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            refresh(frames_entry, frames_path)
            manifest_entry = scene['collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            refresh(manifest_entry, manifest_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'raw_capture_bundle_count_invalid:background',
                report['failures'])

    def test_raw_manifest_cdr_qos_tf_and_rejection_false_passes_fail(self):
        """Every reproduced raw-evidence bypass is rejected by re-indexing."""
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            def mutate_bag(mutator):
                bundle, payload = _build_bundle(root)
                scene = payload['scenes']['background']
                storage = scene['raw_capture']['storage_file']
                bag_path = root / storage['path']
                connection = sqlite3.connect(str(bag_path))
                try:
                    mutator(connection)
                    connection.commit()
                finally:
                    connection.close()
                refresh(storage, bag_path)
                return bundle, payload

            cases = {
                'missing_tf_static': lambda connection: connection.execute(
                    "DELETE FROM messages WHERE topic_id=(SELECT id FROM "
                    "topics WHERE name='/tf_static')"),
                'extra_topic': lambda connection: connection.execute(
                    "INSERT INTO topics VALUES (99, '/diagnostics', "
                    "'diagnostic_msgs/msg/DiagnosticArray', 'cdr', "
                    "'reliability: 1 durability: 2')"),
                'empty_qos': lambda connection: connection.execute(
                    "UPDATE topics SET offered_qos_profiles='' WHERE name=?", (
                        RAW_STREAM_TOPICS['rgb'],)),
                'bad_cdr': lambda connection: connection.execute(
                    "UPDATE messages SET data=x'00' WHERE id=(SELECT id FROM "
                    "messages ORDER BY id LIMIT 1)"),
                'broken_tf': lambda connection: connection.execute(
                    "UPDATE messages SET data=? WHERE topic_id=(SELECT id "
                    "FROM topics WHERE name='/tf')", (
                        _tf(1000_000_000_000,
                            'other_parent', 'other_child'),)),
            }
            for name, mutator in cases.items():
                with self.subTest(name=name):
                    bundle, payload = mutate_bag(mutator)
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(
                        'raw_capture_decode_failed:background',
                        report['failures'])

            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            storage = scene['raw_capture']['storage_file']
            bag_path = root / storage['path']
            connection = sqlite3.connect(str(bag_path))
            try:
                for topic in (
                        RAW_STREAM_TOPICS['aligned_depth'],
                        RAW_STREAM_TOPICS['rgb_camera_info'],
                        RAW_STREAM_TOPICS['depth_camera_info']):
                    topic_id = connection.execute(
                        'SELECT id FROM topics WHERE name=?', (
                            topic,)).fetchone()[0]
                    connection.execute(
                        'DELETE FROM messages WHERE topic_id=? AND id NOT IN '
                        '(SELECT id FROM messages WHERE topic_id=? ORDER BY id '
                        'LIMIT 3)', (topic_id, topic_id))
                connection.commit()
            finally:
                connection.close()
            refresh(storage, bag_path)
            inspection_path = root / scene['raw_capture']['inspection']['path']
            inspection = perception_readiness.inspect_sqlite_bag(
                bag_path, 'capture-background', 'background',
                RAW_STREAM_TOPICS)
            inspection_path.write_text(
                json.dumps(inspection, sort_keys=True) + '\n',
                encoding='utf-8')
            refresh(scene['raw_capture']['inspection'], inspection_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'raw_capture_rejection_rate_exceeded:background',
                report['failures'])

            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            storage = scene['raw_capture']['storage_file']
            bag_path = root / storage['path']
            connection = sqlite3.connect(str(bag_path))
            try:
                topic_id = connection.execute(
                    'SELECT id FROM topics WHERE name=?', (
                        RAW_STREAM_TOPICS['aligned_depth'],)).fetchone()[0]
                next_id = connection.execute(
                    'SELECT MAX(id)+1 FROM messages').fetchone()[0]
                next_stamp = connection.execute(
                    'SELECT MAX(timestamp)+10000000 FROM messages WHERE '
                    'topic_id=?', (topic_id,)).fetchone()[0]
                for offset in range(2):
                    connection.execute(
                        'INSERT INTO messages VALUES (?, ?, ?, ?)', (
                            next_id + offset, topic_id,
                            next_stamp + offset * 10_000_000,
                            _image(next_stamp + offset * 10_000_000
                                   - 50_000_000,
                                   'camera_color_optical_frame', '16UC1')))
                connection.commit()
            finally:
                connection.close()
            refresh(storage, bag_path)
            inspection_path = root / scene['raw_capture']['inspection']['path']
            inspection = perception_readiness.inspect_sqlite_bag(
                bag_path, 'capture-background', 'background',
                RAW_STREAM_TOPICS)
            inspection_path.write_text(
                json.dumps(inspection, sort_keys=True) + '\n',
                encoding='utf-8')
            refresh(scene['raw_capture']['inspection'], inspection_path)
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'raw_capture_unpaired_rate_exceeded:background',
                report['failures'])

            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            inspection_entry = scene['raw_capture']['inspection']
            inspection_path = root / inspection_entry['path']
            inspection = json.loads(
                inspection_path.read_text(encoding='utf-8'))
            inspection.update({
                'report_kind': 'ros1_shared_graph_diagnostic_manifest',
                'inspection_scope': 'diagnostic_shared_graph',
                'formal_acceptance': False,
                'shared_graph': True,
                'mixed_tf': True,
                'not_in_four_scene_denominator': True,
                'delivery_ready': False,
            })
            inspection_path.write_text(
                json.dumps(inspection, sort_keys=True) + '\n',
                encoding='utf-8')
            refresh(inspection_entry, inspection_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'raw_capture_formal_policy_invalid:background',
                report['failures'])
            self.assertIn(
                'raw_capture_non_formal:background', report['failures'])
            self.assertIn(
                'raw_capture_shared_graph:background', report['failures'])
            self.assertIn(
                'raw_capture_mixed_tf:background', report['failures'])
            self.assertIn(
                'raw_capture_excluded_from_scene_denominator:background',
                report['failures'])
            self.assertIn(
                'raw_capture_diagnostic_scope:background', report['failures'])
            raw_report = report['scene_reports']['background']['raw_capture']
            self.assertGreater(raw_report['diagnostic_observed_topics'], 0)
            self.assertGreater(raw_report['diagnostic_observed_messages'], 0)
            self.assertGreater(
                raw_report['diagnostic_observed_accepted_bundles'], 0)
            self.assertEqual(0, raw_report['topics'])
            self.assertEqual(0, raw_report['messages'])
            self.assertEqual(0, raw_report['accepted_bundles'])
            self.assertEqual([], raw_report['bundles'])
            self.assertIsNone(raw_report['tf_graph'])
            self.assertNotIn(
                'background',
                report['typed_frame_evaluator']['scene_reports'])
            self.assertIn(
                'missing_scene:background',
                report['typed_frame_evaluator']['failures'])
            self.assertEqual(
                set(SCENES) - {'background'},
                set(report['typed_frame_evaluator']['scene_reports']))
            self.assertEqual(
                {
                    'report_kind', 'inspection_scope', 'formal_acceptance',
                    'shared_graph', 'mixed_tf',
                    'not_in_four_scene_denominator',
                },
                set(raw_report['formal_scene_admission'][
                    'exclusion_reasons']))

            bundle, payload = _build_bundle(root)
            raw_declaration = payload['scenes']['background']['raw_capture']
            raw_declaration.update({
                'formal_acceptance': False,
                'shared_graph': True,
                'mixed_tf': True,
                'not_in_four_scene_denominator': True,
            })
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'raw_capture_declaration_schema_invalid:background',
                report['failures'])
            raw_report = report['scene_reports']['background']['raw_capture']
            self.assertFalse(raw_report['formal_scene_admission'][
                'admitted_to_formal_scene'])
            self.assertEqual(0, raw_report['topics'])
            self.assertEqual(0, raw_report['messages'])
            self.assertEqual(0, raw_report['accepted_bundles'])
            self.assertIsNone(raw_report['tf_graph'])
            self.assertNotIn(
                'background',
                report['typed_frame_evaluator']['scene_reports'])

            admitted_policy = {
                'report_kind': 'formal_rgbd_raw_capture_index',
                'inspection_scope': 'formal_scene_raw_capture',
                'formal_acceptance': True,
                'shared_graph': False,
                'mixed_tf': False,
                'not_in_four_scene_denominator': False,
            }
            admission_failures = []
            admission = perception_readiness._formal_raw_inspection_admission(
                'background', admitted_policy, admission_failures)
            self.assertTrue(admission['admitted_to_formal_scene'])
            self.assertEqual([], admission['exclusion_reasons'])
            self.assertEqual([], admission_failures)
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
                            admission_field=field,
                            admission_case=mutation_name):
                        candidate = dict(admitted_policy)
                        if mutation_name == 'missing':
                            candidate.pop(field)
                        elif mutation_name == 'null':
                            candidate[field] = None
                        elif mutation_name == 'wrong':
                            candidate[field] = wrong_value
                        else:
                            candidate[field] = wrong_type
                        admission_failures = []
                        admission = (
                            perception_readiness.
                            _formal_raw_inspection_admission(
                                'background', candidate,
                                admission_failures))
                        self.assertFalse(
                            admission['admitted_to_formal_scene'])
                        self.assertEqual(
                            [field], admission['exclusion_reasons'])
                        self.assertIn(
                            'raw_capture_formal_policy_invalid:background',
                            admission_failures)

            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            scene['raw_capture']['storage_identifier'] = 'rosbag1-v2'
            scene['raw_capture']['storage_file'] = {
                'path': str(ROS1_DIAGNOSTIC_BAG),
                'size_bytes': 81634393,
                'sha256': (
                    '31a9c280aaa8d1ce6f1836bb9a445eafd87fbc5b096967932484c2f4c6982168'),
            }
            scene['raw_capture']['inspection'] = {
                'path': str(ROS1_DIAGNOSTIC_MANIFEST_V3),
                'size_bytes': 6989444,
                'sha256': (
                    '4683b682b908a2325232aa604a3b7e6367dd0404a84baf0013d159ab8da7e08f'),
            }
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            for failure in (
                    'raw_capture_binding_mismatch:background',
                    'unsupported_raw_capture_storage:background',
                    'raw_capture_formal_policy_invalid:background',
                    'raw_capture_non_formal:background',
                    'raw_capture_shared_graph:background',
                    'raw_capture_mixed_tf:background',
                    'raw_capture_excluded_from_scene_denominator:background',
                    'raw_capture_diagnostic_scope:background',
                    'raw_capture_inspection_invalid:background',
                    'raw_capture_inspection_incomplete:background'):
                self.assertIn(failure, report['failures'])
            raw_report = report['scene_reports']['background']['raw_capture']
            self.assertEqual(0, raw_report['accepted_bundles'])
            self.assertEqual([], raw_report['bundles'])
            self.assertIsNone(raw_report['tf_graph'])
            self.assertEqual(
                set(admitted_policy),
                set(raw_report['formal_scene_admission'][
                    'exclusion_reasons']))
            self.assertNotIn(
                'background',
                report['typed_frame_evaluator']['scene_reports'])
            self.assertEqual(
                set(SCENES) - {'background'},
                set(report['typed_frame_evaluator']['scene_reports']))
            self.assertIn(
                'missing_scene:background',
                report['typed_frame_evaluator']['failures'])

            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            frames_entry = scene['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines()]
            frames_path.write_text(json.dumps({
                'formal_acceptance': False,
                'shared_graph': True,
                'mixed_tf': True,
                'not_in_four_scene_denominator': True,
                'frames': frames,
            }, sort_keys=True) + '\n', encoding='utf-8')
            refresh(frames_entry, frames_path)
            manifest_entry = scene['collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            refresh(manifest_entry, manifest_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'invalid_frames_artifact:background', report['failures'])
            self.assertNotIn(
                'background',
                report['typed_frame_evaluator']['scene_reports'])

    def test_raw_record_receive_time_attacks_fail_full_readiness(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            for name, mutate in (
                    ('constant', lambda rows: [
                        (1_000_900_000_000, row[0]) for row in rows]),
                    ('reverse', lambda rows: [
                        (1_000_900_000_000 - index * 1_000_000, row[0])
                        for index, row in enumerate(rows)])):
                with self.subTest(name=name):
                    bundle, payload = _build_bundle(root)
                    scene = payload['scenes']['background']
                    bag_path = root / scene['raw_capture'][
                        'storage_file']['path']
                    connection = sqlite3.connect(str(bag_path))
                    try:
                        rows = connection.execute(
                            'SELECT id FROM messages ORDER BY id').fetchall()
                        connection.executemany(
                            'UPDATE messages SET timestamp=? WHERE id=?',
                            mutate(rows))
                        connection.commit()
                    finally:
                        connection.close()
                    refresh(scene['raw_capture']['storage_file'], bag_path)
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(
                        'raw_capture_decode_failed:background',
                        report['failures'])

    def test_typed_frame_task_status_and_target_semantics_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            cases = {
                'missing_schema': lambda frames: [
                    frame.pop('schema_version', None) for frame in frames],
                'empty_task': lambda frames: [
                    frame.update(task_id='') for frame in frames],
                'mixed_task': lambda frames: [
                    frame.update(task_id='other-task')
                    for frame in frames[15:]],
                'valid_frame_error': lambda frames: [
                    frame.update(error_code='unexpected') for frame in frames],
                'targets_ready_empty': lambda frames: [
                    frame.update(status='targets_ready') for frame in frames],
            }
            for name, mutate in cases.items():
                with self.subTest(name=name):
                    bundle, payload = _build_bundle(root)
                    scene = payload['scenes']['background']
                    frames_entry = scene['frames']
                    frames_path = root / frames_entry['path']
                    frames = [json.loads(line) for line in frames_path.read_text(
                        encoding='utf-8').splitlines() if line]
                    mutate(frames)
                    frames_path.write_text(''.join(
                        json.dumps(item, sort_keys=True) + '\n'
                        for item in frames), encoding='utf-8')
                    refresh(frames_entry, frames_path)
                    manifest_entry = scene['collector_manifest']
                    manifest_path = root / manifest_entry['path']
                    manifest = json.loads(manifest_path.read_text(
                        encoding='utf-8'))
                    manifest['output'].update(frames_entry)
                    manifest_path.write_text(
                        json.dumps(manifest, sort_keys=True) + '\n',
                        encoding='utf-8')
                    refresh(manifest_entry, manifest_path)
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])

            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['bin_only']
            frames_entry = scene['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            for frame in frames:
                frame['targets'][0].update(actionable=True, status='active')
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            refresh(frames_entry, frames_path)
            manifest_entry = scene['collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n',
                encoding='utf-8')
            refresh(manifest_entry, manifest_path)
            self.assertFalse(evaluate_readiness(
                bundle, payload)['delivery_ready'])

    def test_typed_raw_task_id_and_malformed_cli_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, payload = _build_bundle(root)
            scene = payload['scenes']['background']
            entry = scene['typed_raw_binding']
            path = root / entry['path']
            binding = json.loads(path.read_text(encoding='utf-8'))
            binding['task_id'] = 'other-read-only-task'
            envelope = {
                key: binding[key] for key in (
                    'capture_id', 'scene', 'task_id', 'capture_window',
                    'release_id', 'source_set_sha256', 'model_sha256',
                    'typed_frames', 'collector_manifest', 'raw_capture',
                    'raw_inspection', 'expected_topic_manifest')}
            binding['capture_binding_id'] = hashlib.sha256(json.dumps(
                envelope, ensure_ascii=False, sort_keys=True,
                separators=(',', ':')).encode('utf-8')).hexdigest()
            path.write_text(
                json.dumps(binding, sort_keys=True) + '\n', encoding='utf-8')
            entry['size_bytes'] = path.stat().st_size
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'typed_raw_task_id_mismatch:background', report['failures'])

            malformed = root / 'malformed.json'
            malformed.write_text('{"schema_version": NaN}\n', encoding='utf-8')
            report_path = root / 'malformed-report.json'
            with patch('sys.argv', [
                    'perception_readiness', '--bundle', str(malformed),
                    '--report', str(report_path)]):
                self.assertEqual(1, perception_readiness.main())
            cli_report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertFalse(cli_report['delivery_ready'])
            self.assertEqual(
                ['readiness_evaluation_error'], cli_report['failures'])
            self.assertIsInstance(cli_report['evaluation_error']['message'], str)

            malformed = root / 'bad-number.json'
            malformed.write_text(json.dumps({
                'schema_version': 1,
                'evidence_scope': 'formal_four_scene_rgbd_acceptance',
                'read_only': True,
                'authorizes_motion': False,
                'publishes_ros_messages': False,
                'scenes': {'background': {
                    'arrangement': {
                        'started_unix_sec': {'not': 'numeric'},
                        'ended_unix_sec': 1.0}}},
            }), encoding='utf-8')
            report_path = root / 'bad-number-report.json'
            with patch('sys.argv', [
                    'perception_readiness', '--bundle', str(malformed),
                    '--report', str(report_path)]):
                self.assertEqual(1, perception_readiness.main())
            cli_report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertFalse(cli_report['delivery_ready'])

    def test_bundle_and_scene_sets_are_exact(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            payload['unexpected_evidence'] = {'claim': 'pass'}
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('bundle_schema_invalid', report['failures'])

            payload = copy.deepcopy(baseline)
            payload['scenes']['background_alias'] = copy.deepcopy(
                payload['scenes']['background'])
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('scene_set_mismatch', report['failures'])

            payload = copy.deepcopy(baseline)
            payload['scenes']['background']['legacy_alias'] = None
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn(
                'scene_declaration_schema_invalid:background',
                report['failures'])

    def test_top_level_safety_flags_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)
            cases = (
                ('read_only', False, 'read_only_contract_violation'),
                ('authorizes_motion', True, 'motion_authorization_present'),
                ('publishes_ros_messages', True,
                 'publisher_contract_violation'),
            )
            for key, value, failure in cases:
                with self.subTest(key=key):
                    payload = copy.deepcopy(baseline)
                    payload[key] = value
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(failure, report['failures'])

            for name, field, value, failure in (
                    ('release_id', 'release_id', 'forged-release-0001',
                     'runtime_release_binding_mismatch'),
                    ('manifest_hash', 'source_set_sha256', '0' * 64,
                     'runtime_release_binding_mismatch'),
                    ('manifest_time', 'manifest_generated_at_unix_sec', 999.0,
                     'runtime_release_binding_mismatch')):
                with self.subTest(name='top_' + name):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    payload['release_binding'][field] = value
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(failure, report['failures'])

    def test_hash_missing_scene_and_manifest_count_fail_closed(self):
        with TemporaryDirectory() as directory:
            bundle, baseline = _build_bundle(Path(directory))

            payload = copy.deepcopy(baseline)
            payload['scenes']['background']['frames']['sha256'] = '0' * 64
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'artifact_sha256_mismatch:background:frames',
                report['failures'])

            payload = copy.deepcopy(baseline)
            del payload['scenes']['bin_only']
            report = evaluate_readiness(bundle, payload)
            self.assertIn('missing_scene:bin_only', report['failures'])

            payload = copy.deepcopy(baseline)
            manifest_entry = payload['scenes']['background'][
                'collector_manifest']
            manifest_path = Path(directory) / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['received_frames'] = 29
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            manifest_entry.update({
                'size_bytes': manifest_path.stat().st_size,
                'sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            })
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'manifest_count_mismatch:background', report['failures'])

    def test_rgbd_truth_tf_xyz_depth_latency_and_hardware_gates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)

            def mutate_artifact(payload, scene, key, mutator):
                entry = payload['scenes'][scene][key]
                path = root / entry['path']
                value = json.loads(path.read_text(encoding='utf-8'))
                mutator(value)
                path.write_text(
                    json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            payload = copy.deepcopy(baseline)
            mutate_artifact(payload, 'background', 'rgbd_artifact',
                            lambda value: value['streams'].pop('aligned_depth'))
            self.assertIn(
                'missing_stream:background:aligned_depth',
                evaluate_readiness(bundle, payload)['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            mutate_artifact(payload, 'bin_only', 'ground_truth',
                            lambda value: value.update(classes=['plastic_bottle']))
            self.assertIn(
                'missing_trash_bin_annotation:bin_only',
                evaluate_readiness(bundle, payload)['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            mutate_artifact(payload, 'bottle_outside', 'tf_artifact',
                            lambda value: value.update(
                                independent_extrinsics_validated=False))
            self.assertIn(
                'extrinsics_unvalidated:bottle_outside',
                evaluate_readiness(bundle, payload)['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            mutate_artifact(payload, 'bottle_outside', 'xyz_ground_truth',
                            lambda value: value['samples'][0].update(
                                predicted_base_xyz_m=[0.3, 0.2, 1.2]))
            self.assertIn(
                'xyz_error_exceeded:bottle_outside',
                evaluate_readiness(bundle, payload)['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            mutate_artifact(payload, 'bin_only', 'depth_quality',
                            lambda value: value.update(valid_target_samples=1))
            self.assertIn(
                'depth_valid_count_mismatch:bin_only',
                evaluate_readiness(bundle, payload)['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            payload['scenes']['background']['latency']['clock_domain'] = 'unknown'
            self.assertIn(
                'latency_clock_domain_unproven:background',
                evaluate_readiness(bundle, payload)['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            hardware_entry = payload['hardware_readiness']
            hardware_path = root / hardware_entry['path']
            hardware = json.loads(hardware_path.read_text(encoding='utf-8'))
            hardware['checks'] = [
                item for item in hardware['checks']
                if item['name'] != 'no_actuation_publishers']
            hardware_path.write_text(
                json.dumps(hardware, sort_keys=True) + '\n', encoding='utf-8')
            hardware_entry['size_bytes'] = hardware_path.stat().st_size
            hardware_entry['sha256'] = hashlib.sha256(
                hardware_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn('actuation_safety_not_proven', report['failures'])

    def test_reproduced_false_passes_are_now_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            frames_entry = payload['scenes']['bottle_outside']['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            for frame in frames:
                for item in frame['targets']:
                    if item['object_class'] == 'plastic_bottle':
                        item['position'] = {'x': 99.0, 'y': 99.0, 'z': 99.0}
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            refresh(frames_entry, frames_path)
            manifest_entry = payload['scenes']['bottle_outside'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            refresh(manifest_entry, manifest_path)
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'xyz_prediction_binding_mismatch:bottle_outside',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            for scene in SCENES:
                entry = payload['scenes'][scene]['tf_artifact']
                path = root / entry['path']
                value = json.loads(path.read_text(encoding='utf-8'))
                value['translation_m'] = [9.0, 8.0, 7.0]
                path.write_text(
                    json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
                refresh(entry, path)
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'hardware_tf_numeric_mismatch:background', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            payload['scenes']['bin_only']['arrangement']['operator'] = 'same'
            payload['scenes']['bin_only']['arrangement']['reviewer'] = 'same'
            truth_entry = payload['scenes']['bin_only']['ground_truth']
            truth_path = root / truth_entry['path']
            truth = json.loads(truth_path.read_text(encoding='utf-8'))
            truth['annotator'] = truth['reviewer'] = 'same'
            truth_path.write_text(
                json.dumps(truth, sort_keys=True) + '\n', encoding='utf-8')
            refresh(truth_entry, truth_path)
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'independent_review_not_proven:bin_only', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            depth_entry = payload['scenes']['bin_only']['depth_quality']
            depth_path = root / depth_entry['path']
            depth = json.loads(depth_path.read_text(encoding='utf-8'))
            for sample in depth['target_roi_samples']:
                sample['depth_valid_ratio'] = 0.01
            depth_path.write_text(
                json.dumps(depth, sort_keys=True) + '\n', encoding='utf-8')
            refresh(depth_entry, depth_path)
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'depth_valid_count_mismatch:bin_only', report['failures'])
            self.assertIn(
                'depth_valid_rate_below_threshold:bin_only', report['failures'])

    def test_runtime_model_checks_bind_exact_names_and_hashes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)

            def mutate_runtime(payload, mutation):
                entry = payload['software_binding']['runtime_preflight']
                path = root / entry['path']
                value = json.loads(path.read_text(encoding='utf-8'))
                mutation(value)
                path.write_text(
                    json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            payload = copy.deepcopy(baseline)
            mutate_runtime(
                payload,
                lambda value: value['checks'].__setitem__(
                    -2, {'name': 'model_arbitrary.pt', 'status': 'PASS',
                         'measured': '0' * 64}))
            report = evaluate_readiness(bundle, payload)
            self.assertIn('runtime_preflight_not_passed', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            for label, content in (
                    ('plastic_bottle', b'forged-bottle-model'),
                    ('trash_bin', b'forged-bin-model')):
                entry = payload['software_binding']['models'][label]
                path = root / entry['path']
                path.write_bytes(content)
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(content).hexdigest()
            runtime_entry = payload['software_binding']['runtime_preflight']
            runtime_path = root / runtime_entry['path']
            runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
            model_hashes = {
                label: payload['software_binding']['models'][label]['sha256']
                for label in ('plastic_bottle', 'trash_bin')}
            for item in runtime['checks']:
                if item['name'] == 'model_nongfu_yolov8n_best.pt':
                    item['measured'] = model_hashes['plastic_bottle']
                elif item['name'] == 'model_trash_bin_yolov8n_best.pt':
                    item['measured'] = model_hashes['trash_bin']
            runtime_path.write_text(
                json.dumps(runtime, sort_keys=True) + '\n', encoding='utf-8')
            runtime_entry['size_bytes'] = runtime_path.stat().st_size
            runtime_entry['sha256'] = hashlib.sha256(
                runtime_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'model_hash_mismatch:plastic_bottle', report['failures'])
            self.assertIn('model_hash_mismatch:trash_bin', report['failures'])

    def test_runtime_platform_and_build_provenance_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def refresh(entry, path):
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            runtime_entry = payload['software_binding']['runtime_preflight']
            runtime_path = root / runtime_entry['path']
            runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
            runtime['platform']['machine'] = 'x86_64'
            runtime_path.write_text(
                json.dumps(runtime, sort_keys=True) + '\n', encoding='utf-8')
            refresh(runtime_entry, runtime_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('runtime_preflight_not_passed', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            build_entry = payload['ros_build_validation']
            build_path = root / build_entry['path']
            build = json.loads(build_path.read_text(encoding='utf-8'))
            for key in ('platform', 'commands', 'logs', 'source_manifest'):
                build.pop(key)
            build_path.write_text(
                json.dumps(build, sort_keys=True) + '\n', encoding='utf-8')
            refresh(build_entry, build_path)
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertFalse(report['offline_migration_passed'])
            self.assertIn(
                'ros_build_provenance_incomplete',
                report['non_delivery_failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            payload.pop('ros_build_validation')
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertFalse(report['offline_migration_passed'])
            self.assertNotIn('bundle_schema_invalid', report['failures'])
            self.assertIn(
                'ros_build_validation_not_passed',
                report['non_delivery_failures'])

    def test_build_runtime_release_evidence_cannot_be_self_reported_or_spliced(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def mutate_artifact(payload, entry, mutator):
                path = root / entry['path']
                value = json.loads(path.read_text(encoding='utf-8'))
                mutator(value)
                path.write_text(
                    json.dumps(value, sort_keys=True) + '\n',
                    encoding='utf-8')
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            cases = [
                ('fake_manifest_hash', 'ros_build_validation',
                 lambda value: value['source_manifest'].__setitem__(
                     'source_set_sha256', '0' * 64),
                 'ros_build_source_manifest_invalid'),
                ('missing_log', 'ros_build_validation',
                 lambda value: value['logs']['build'].__setitem__(
                     'path', 'definitely-missing.log'),
                 'artifact_missing:ros_build_log:build'),
                ('fake_command', 'ros_build_validation',
                 lambda value: value['commands'].__setitem__(
                     'build_argv', ['echo', 'pass']),
                 'ros_build_command_mismatch'),
                ('manifest_wrapper_splice', 'ros_build_validation',
                 lambda value: value['source_manifest_artifact'].__setitem__(
                     'sha256', '0' * 64),
                 'artifact_sha256_mismatch:'
                 'ros_build_source_manifest_artifact'),
                ('build_release_splice', 'ros_build_validation',
                 lambda value: value.__setitem__(
                     'release_id', 'other-release-0001'),
                 'ros_build_release_binding_mismatch'),
                ('runtime_release_splice', 'runtime_preflight',
                 lambda value: value.__setitem__(
                     'release_id', 'other-release-0001'),
                 'runtime_release_binding_mismatch'),
                ('runtime_model_splice', 'runtime_preflight',
                 lambda value: value['model_sha256'].__setitem__(
                     'plastic_bottle', '0' * 64),
                 'runtime_release_binding_mismatch'),
            ]
            for name, kind, mutator, failure in cases:
                with self.subTest(name=name):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    entry = (payload['ros_build_validation'] if kind ==
                             'ros_build_validation' else payload[
                                 'software_binding']['runtime_preflight'])
                    mutate_artifact(payload, entry, mutator)
                    report = evaluate_readiness(bundle, payload)
                    if kind == 'ros_build_validation':
                        self.assertFalse(report['delivery_ready'])
                        self.assertFalse(report['offline_migration_passed'])
                        self.assertIn(
                            failure, report['non_delivery_failures'])
                    else:
                        self.assertFalse(report['delivery_ready'])
                        self.assertIn(failure, report['failures'])

    def test_all_evidence_artifact_schema_versions_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ('rgbd_artifact', 'invalid_rgbd_schema:background'),
                ('tf_artifact', 'invalid_tf_schema:background'),
                ('xyz_ground_truth', 'invalid_xyz_schema:background'),
                ('depth_quality', 'invalid_depth_schema:background'),
            )
            for field, failure in cases:
                with self.subTest(field=field):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    entry = payload['scenes']['background'][field]
                    path = root / entry['path']
                    value = json.loads(path.read_text(encoding='utf-8'))
                    value['schema_version'] = 99
                    path.write_text(
                        json.dumps(value, sort_keys=True) + '\n',
                        encoding='utf-8')
                    entry['size_bytes'] = path.stat().st_size
                    entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertIn(failure, report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            entry = payload['hardware_readiness']
            path = root / entry['path']
            value = json.loads(path.read_text(encoding='utf-8'))
            value['schema_version'] = 99
            path.write_text(
                json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
            entry['size_bytes'] = path.stat().st_size
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertFalse(report['delivery_ready'])
            self.assertIn('invalid_hardware_schema', report['failures'])

    def test_source_scope_duplicate_hardware_and_relation_status_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)

            payload = copy.deepcopy(baseline)
            payload['software_binding']['sources'] = payload[
                'software_binding']['sources'][:-1]
            report = evaluate_readiness(bundle, payload)
            self.assertIn('source_binding_scope_mismatch', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            entry = payload['hardware_readiness']
            path = root / entry['path']
            value = json.loads(path.read_text(encoding='utf-8'))
            value['checks'].append(copy.deepcopy(value['checks'][0]))
            path.write_text(
                json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
            entry['size_bytes'] = path.stat().st_size
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'required_readiness_check_failed:rgb_received',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            entry = payload['scenes']['bottle_in_bin']['frames']
            path = root / entry['path']
            frames = [json.loads(line) for line in path.read_text(
                encoding='utf-8').splitlines() if line]
            for frame in frames:
                for item in frame['targets']:
                    if item['object_class'] == 'plastic_bottle':
                        item['status'] = 'active'
                        item['actionable'] = True
            path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            entry['size_bytes'] = path.stat().st_size
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_entry = payload['scenes']['bottle_in_bin'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            manifest_entry['size_bytes'] = manifest_path.stat().st_size
            manifest_entry['sha256'] = hashlib.sha256(
                manifest_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'bottle_relation_status_contract_failed:bottle_in_bin',
                report['failures'])

    def test_clock_proof_and_tf_rotation_are_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def mutate_runtime(payload, mutation):
                entry = payload['software_binding']['runtime_preflight']
                path = root / entry['path']
                value = json.loads(path.read_text(encoding='utf-8'))
                mutation(value)
                path.write_text(
                    json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            payload['scenes']['background']['latency'][
                'use_sim_time'] = True
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'latency_clock_proof_missing:background', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            entry = payload['scenes']['background']['tf_artifact']
            path = root / entry['path']
            value = json.loads(path.read_text(encoding='utf-8'))
            value['rotation_xyzw'] = [0.0, 0.0, 0.70710678, 0.70710678]
            path.write_text(
                json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
            entry['size_bytes'] = path.stat().st_size
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'hardware_tf_rotation_mismatch:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            mutate_runtime(
                payload,
                lambda value: next(
                    item for item in value['checks']
                    if item['name'] == 'models_load_and_labels_match').update(
                        status='FAIL'))
            report = evaluate_readiness(bundle, payload)
            self.assertIn('runtime_preflight_not_passed', report['failures'])

    def test_time_frame_and_scene_independence_bindings_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, baseline = _build_bundle(root)

            payload = copy.deepcopy(baseline)
            payload['scenes']['bin_only']['arrangement'][
                'capture_id'] = 'capture-background'
            report = evaluate_readiness(bundle, payload)
            self.assertIn('duplicate_capture_id', report['failures'])

            payload = copy.deepcopy(baseline)
            payload['scenes']['bin_only']['arrangement'][
                'started_unix_sec'] = 1000.5
            payload['scenes']['bin_only']['arrangement'][
                'ended_unix_sec'] = 1001.5
            report = evaluate_readiness(bundle, payload)
            self.assertIn('scene_capture_time_overlap', report['failures'])

            payload = copy.deepcopy(baseline)
            tf_entry = payload['scenes']['background']['tf_artifact']
            tf_path = root / tf_entry['path']
            tf_value = json.loads(tf_path.read_text(encoding='utf-8'))
            tf_value['child'] = 'other_camera_frame'
            tf_path.write_text(
                json.dumps(tf_value, sort_keys=True) + '\n', encoding='utf-8')
            tf_entry['size_bytes'] = tf_path.stat().st_size
            tf_entry['sha256'] = hashlib.sha256(tf_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'tf_frame_binding_mismatch:background', report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            frames_entry = payload['scenes']['background']['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            frames[0]['received_unix_sec'] = 999.0
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            frames_entry['size_bytes'] = frames_path.stat().st_size
            frames_entry['sha256'] = hashlib.sha256(
                frames_path.read_bytes()).hexdigest()
            manifest_entry = payload['scenes']['background'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output']['size_bytes'] = frames_path.stat().st_size
            manifest['output']['sha256'] = frames_entry['sha256']
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            manifest_entry['size_bytes'] = manifest_path.stat().st_size
            manifest_entry['sha256'] = hashlib.sha256(
                manifest_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'frame_outside_capture_window:background', report['failures'])

    def test_nested_control_claim_latency_spike_and_truth_id_reuse_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            entry = payload['scenes']['background']['typed_raw_binding']
            path = root / entry['path']
            value = json.loads(path.read_text(encoding='utf-8'))
            value['frame_bindings'][0]['authorizes_motion'] = True
            path.write_text(
                json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
            entry['size_bytes'] = path.stat().st_size
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'typed_raw_binding_control_claim:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            frames_entry = payload['scenes']['background']['frames']
            frames_path = root / frames_entry['path']
            frames = [json.loads(line) for line in frames_path.read_text(
                encoding='utf-8').splitlines() if line]
            frames[0]['processing_latency_sec'] = 10.0
            frames_path.write_text(''.join(
                json.dumps(item, sort_keys=True) + '\n' for item in frames),
                encoding='utf-8')
            frames_entry['size_bytes'] = frames_path.stat().st_size
            frames_entry['sha256'] = hashlib.sha256(
                frames_path.read_bytes()).hexdigest()
            manifest_entry = payload['scenes']['background'][
                'collector_manifest']
            manifest_path = root / manifest_entry['path']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output'].update(frames_entry)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            manifest_entry['size_bytes'] = manifest_path.stat().st_size
            manifest_entry['sha256'] = hashlib.sha256(
                manifest_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'processing_latency_sample_exceeded:background',
                report['failures'])

            bundle, baseline = _build_bundle(root)
            payload = copy.deepcopy(baseline)
            first_entry = payload['scenes']['bin_only']['ground_truth']
            first_path = root / first_entry['path']
            first = json.loads(first_path.read_text(encoding='utf-8'))
            reused = first['frames'][0]['instances'][0]['instance_id']
            second_entry = payload['scenes']['bottle_outside']['ground_truth']
            second_path = root / second_entry['path']
            second = json.loads(second_path.read_text(encoding='utf-8'))
            second['frames'][0]['instances'][0]['instance_id'] = reused
            second_path.write_text(
                json.dumps(second, sort_keys=True) + '\n', encoding='utf-8')
            second_entry['size_bytes'] = second_path.stat().st_size
            second_entry['sha256'] = hashlib.sha256(
                second_path.read_bytes()).hexdigest()
            report = evaluate_readiness(bundle, payload)
            self.assertIn(
                'duplicate_ground_truth_instance_id_across_bundle',
                report['failures'])

    def test_typed_frame_unknown_override_and_control_target_fields_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            def mutate_frame(payload, mutation):
                entry = payload['scenes']['bin_only']['frames']
                path = root / entry['path']
                rows = [json.loads(line) for line in path.read_text(
                    encoding='utf-8').splitlines() if line]
                mutation(rows[0])
                path.write_text(''.join(
                    json.dumps(row, sort_keys=True) + '\n' for row in rows),
                    encoding='utf-8')
                entry['size_bytes'] = path.stat().st_size
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest_entry = payload['scenes']['bin_only'][
                    'collector_manifest']
                manifest_path = root / manifest_entry['path']
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                manifest['output'].update(entry)
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True) + '\n',
                    encoding='utf-8')
                manifest_entry['size_bytes'] = manifest_path.stat().st_size
                manifest_entry['sha256'] = hashlib.sha256(
                    manifest_path.read_bytes()).hexdigest()

            cases = (
                ('frame_id_override', lambda frame: frame.__setitem__(
                    'frame_id_override', 'base_link')),
                ('motion', lambda frame: frame.__setitem__(
                    'authorizes_motion', True)),
                ('publisher', lambda frame: frame.__setitem__(
                    'publishes_ros_messages', True)),
                ('target_topic', lambda frame: frame['targets'][0].update({
                    'topic': '/cmd_vel',
                    'message_type': 'geometry_msgs/msg/Twist'})),
                ('target_frame', lambda frame: frame['targets'][0].update({
                    'frame_id': 'base_link'})),
            )
            for name, mutation in cases:
                with self.subTest(name=name):
                    bundle, baseline = _build_bundle(root)
                    payload = copy.deepcopy(baseline)
                    mutate_frame(payload, mutation)
                    report = evaluate_readiness(bundle, payload)
                    self.assertFalse(report['delivery_ready'])
                    self.assertTrue(any(code in report['failures'] for code in (
                        'typed_frame_schema_invalid:bin_only',
                        'typed_target_schema_invalid:bin_only',
                        'nested_control_contract_violation')))

    def test_cli_writes_exclusively_and_returns_one_when_not_ready(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'missing.json'
            bundle.write_text(json.dumps({
                'schema_version': 1,
                'evidence_scope': 'formal_four_scene_rgbd_acceptance',
                'read_only': True,
                'authorizes_motion': False,
                'publishes_ros_messages': False,
            }), encoding='utf-8')
            report_path = root / 'report.json'
            with patch('sys.argv', [
                    'perception_readiness', '--bundle', str(bundle),
                    '--report', str(report_path)]):
                self.assertEqual(1, perception_readiness.main())
            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertFalse(report['delivery_ready'])
            with patch('sys.argv', [
                    'perception_readiness', '--bundle', str(bundle),
                    '--report', str(report_path)]):
                with self.assertRaisesRegex(
                        SystemExit, 'must not already exist'):
                    perception_readiness.main()


if __name__ == '__main__':
    unittest.main()
