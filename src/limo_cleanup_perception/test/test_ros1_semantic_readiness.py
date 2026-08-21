"""Semantic fail-closed tests for ROS1 field-readiness evidence.

These tests freeze previously reproduced false-positive shapes.  They use
only the public pure functions ``assess_field_readiness`` and
``create_binding``; no ROS graph, model backend, camera, or hardware is used.
"""

import hashlib
import importlib
import inspect
import json
import copy
import runpy
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


WORKSPACE = Path(__file__).resolve().parents[3]
OVERLAY_ROOT = (
    WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception')
OVERLAY_PYTHON = (
    OVERLAY_ROOT / 'src')
if str(OVERLAY_PYTHON) not in sys.path:
    sys.path.insert(0, str(OVERLAY_PYTHON))

READINESS = importlib.import_module(
    'limo_cleanup_ros1_perception.perception_readiness')
BINDING = importlib.import_module(
    'limo_cleanup_ros1_perception.typed_raw_binding')

SCENES = (
    'background', 'bin_only', 'bottle_in_bin', 'bottle_outside')


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _placeholder_artifact(root, scene, role):
    path = Path(root) / scene / (role + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{}\n', encoding='utf-8')
    return {
        'path': path.relative_to(root).as_posix(),
        'size_bytes': path.stat().st_size,
        'sha256': _sha256(path),
    }


def _shallow_self_reported_readiness(root):
    scenes = {}
    for index, scene in enumerate(SCENES):
        scenes[scene] = {
            'unique_frames': 30,
            'ground_truth_complete': True,
            'tf_valid_frames': 30,
            'xyz_valid_frames': 30,
            'depth_valid_frames': 30,
            'latency_samples': 30,
            'bag_index_formal': True,
            'typed_raw_binding_pass': True,
            'capture_id': 'self-reported-capture-{}'.format(index),
            'task_id': 'self-reported-task-{}'.format(index),
            'ground_truth_artifact': _placeholder_artifact(
                root, scene, 'ground-truth'),
            'tf_artifact': _placeholder_artifact(root, scene, 'tf'),
            'latency_artifact': _placeholder_artifact(
                root, scene, 'latency'),
        }
    return {
        'schema_version': 1,
        'read_only': True,
        'authorizes_motion': False,
        'ros1_field_install_pass': True,
        'runtime_model_binding_pass': True,
        'formal_acceptance': True,
        'shared_graph': False,
        'mixed_tf': False,
        'not_in_four_scene_denominator': False,
        'scenes': scenes,
    }


def _write_artifact(root, scene, role, payload):
    path = Path(root) / scene / (role + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, allow_nan=False) + '\n',
        encoding='utf-8')
    return {
        'path': path.relative_to(root).as_posix(),
        'size_bytes': path.stat().st_size,
        'sha256': _sha256(path),
    }


def _semantic_self_reported_readiness(root):
    payload = _shallow_self_reported_readiness(root)
    install_sha = '2' * 64
    model_sha = '3' * 64
    for scene in SCENES:
        record = payload['scenes'][scene]
        common = {
            'schema_version': 1,
            'scene': scene,
            'capture_id': record['capture_id'],
            'task_id': record['task_id'],
            'ros1_field_install_sha256': install_sha,
            'model_binding_sha256': model_sha,
            'synthetic_test_only': False,
        }
        record['ground_truth_artifact'] = _write_artifact(
            root, scene, 'ground-truth', dict(common, **{
                'report_kind': 'ros1_ground_truth',
                'complete': True,
                'unique_frames': 30,
                'annotation_count': 30,
            }))
        record['tf_artifact'] = _write_artifact(
            root, scene, 'tf', dict(common, **{
                'report_kind': 'ros1_tf_application',
                'source_frame': 'camera_color_optical_frame',
                'target_frame': 'base_link',
                'transform_applied': True,
                'mixed_tf': False,
                'tf_valid_frames': 30,
                'xyz_valid_frames': 30,
            }))
        record['latency_artifact'] = _write_artifact(
            root, scene, 'latency', dict(common, **{
                'report_kind': 'ros1_latency_evidence',
                'sample_count': 30,
                'max_latency_sec': 0.1,
            }))
    return payload


def _rewrite_declared_artifact(root, declaration, payload):
    path = Path(root) / declaration['path']
    path.write_text(
        json.dumps(payload, sort_keys=True, allow_nan=False) + '\n',
        encoding='utf-8')
    declaration['size_bytes'] = path.stat().st_size
    declaration['sha256'] = _sha256(path)


_INDEXER_TEST_SUPPORT = None


def _indexer_test_support():
    global _INDEXER_TEST_SUPPORT
    if _INDEXER_TEST_SUPPORT is None:
        before = list(sys.path)
        try:
            _INDEXER_TEST_SUPPORT = runpy.run_path(str(
                OVERLAY_ROOT / 'test' / 'test_rosbag1_rgbd_indexer.py'))
        finally:
            sys.path[:] = before
    return _INDEXER_TEST_SUPPORT


def _canonical_sha256(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _absolute_identity(path):
    path = Path(path).resolve()
    return {
        'path': str(path),
        'size_bytes': path.stat().st_size,
        'sha256': _sha256(path),
    }


def _declaration(root, path):
    path = Path(path)
    return {
        'path': path.relative_to(root).as_posix(),
        'size_bytes': path.stat().st_size,
        'sha256': _sha256(path),
    }


def _write_bytes_artifact(root, group, role, value, suffix='.bin'):
    path = Path(root) / group / (role + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return _declaration(root, path), path


def _write_jsonl_artifact(root, group, role, records):
    path = Path(root) / group / (role + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(
        json.dumps(record, sort_keys=True, allow_nan=False) + '\n'
        for record in records), encoding='utf-8')
    return _declaration(root, path), path


def _raw_bundle_identifier(bundle, model_hash):
    metadata = {
        'rgb': ('rgb', 'camera_color_optical_frame', 640, 480, 'bgr8'),
        'raw_depth': (
            'depth', 'camera_depth_optical_frame', 640, 400, '16UC1'),
        'rgb_camera_info': (
            'rgb_info', 'camera_color_optical_frame', 640, 480, ''),
        'depth_camera_info': (
            'depth_info', 'camera_depth_optical_frame', 640, 400, ''),
    }
    streams = []
    for role in ('rgb', 'raw_depth', 'rgb_camera_info',
                 'depth_camera_info'):
        name, frame_id, width, height, encoding = metadata[role]
        streams.append({
            'name': name,
            'stamp_sec': round(
                bundle['header_stamps_ns'][role] / 1e9, 9),
            'frame_id': frame_id,
            'width': width,
            'height': height,
            'encoding': encoding,
        })
    return _canonical_sha256({
        'streams': streams,
        'model_set_sha256': model_hash,
    })


def _observation_id(
        stamp_sec, object_class, bbox, status, model_hash):
    identity = {
        'stamp_sec': round(float(stamp_sec), 9),
        'frame_id': 'camera_color_optical_frame',
        'object_class': object_class,
        'bbox': [round(float(value), 6) for value in bbox],
        'status': status,
        'model_binding_sha256': model_hash,
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL, hashlib.sha256(encoded).hexdigest()))


def _targets(scene, stamp_sec, model_hash):
    definitions = []
    if scene in ('bin_only', 'bottle_in_bin', 'bottle_outside'):
        definitions.append((
            'trash_bin', [100.0, 100.0, 300.0, 400.0],
            'confirmed', False, {'x': 0.0, 'y': 0.0, 'z': 1.0}))
    if scene == 'bottle_in_bin':
        definitions.append((
            'plastic_bottle', [150.0, 150.0, 220.0, 300.0],
            'already_in_bin', False,
            {'x': 0.1, 'y': 0.0, 'z': 1.0}))
    if scene == 'bottle_outside':
        definitions.append((
            'plastic_bottle', [350.0, 100.0, 450.0, 350.0],
            'active', True, {'x': 0.2, 'y': 0.0, 'z': 1.0}))
    result = []
    for object_class, bbox, status, actionable, position in definitions:
        result.append({
            'observation_id': _observation_id(
                stamp_sec, object_class, bbox, status, model_hash),
            'object_class': object_class,
            'confidence': 0.95,
            'valid': True,
            'actionable': actionable,
            'status': status,
            'error_code': '',
            'position': dict(position),
            'size': {'x': 0.1, 'y': 0.1, 'z': 0.2},
            'bbox': bbox,
            'depth_m': 1.0,
            'depth_valid_pixels': 100,
            'depth_total_pixels': 100,
            'depth_valid_ratio': 1.0,
            'source': 'formal-negative-fixture',
            'position_semantics': 'camera_to_base_transform_applied',
        })
    return result


def _annotations(scene, sequence, targets):
    result = []
    for target in targets:
        relation = 'none'
        if target['object_class'] == 'plastic_bottle':
            relation = (
                'inside_bin' if scene == 'bottle_in_bin'
                else 'outside_bin')
        result.append({
            'instance_id': '{}-{}-{}'.format(
                scene, sequence, target['object_class']),
            'object_class': target['object_class'],
            'bbox': list(target['bbox']),
            'relation': relation,
        })
    return result


def _refresh_formal_bundle_id(payload):
    value = copy.deepcopy(payload)
    value.pop('bundle_id', None)
    payload['bundle_id'] = _canonical_sha256(value)


def _formal_globals(root):
    source_decl = _write_artifact(root, 'global', 'source-admission', {})
    source_path = Path(root) / source_decl['path']

    output_source = (
        OVERLAY_ROOT / 'config' / 'read_only_output_contract.json')
    output_decl, output_path = _write_bytes_artifact(
        root, 'global', 'read-only-output-contract',
        output_source.read_bytes(), suffix='.json')

    manifest_source = (
        OVERLAY_ROOT / 'config'
        / 'dabai_ros1_raw_rgbd_six_topics_v1.json')
    topic_decl, topic_path = _write_bytes_artifact(
        root, 'global', 'expected-topic-manifest',
        manifest_source.read_bytes(), suffix='.json')

    model_source = OVERLAY_ROOT / 'config' / 'model_bindings.json'
    model_decl, model_path = _write_bytes_artifact(
        root, 'global', 'model-bindings', model_source.read_bytes(),
        suffix='.json')
    model_root = Path(root) / 'global' / 'models'
    model_root.mkdir(parents=True, exist_ok=True)
    model_artifacts = {}
    for filename, label in (
            ('nongfu_yolov8n_best.pt', 'plastic_bottle'),
            ('trash_bin_yolov8n_best.pt', 'trash_bin')):
        path = model_root / filename
        path.write_bytes(('synthetic-' + label).encode('ascii'))
        model_artifacts[label] = _declaration(root, path)

    install_value = {
        'gate_id': 'ROS1_NOETIC_FIELD_INSTALL',
        'validated_pass': True,
        'architecture_blockers': [],
        'delivery_ready': False,
        'source_contract': {
            'source_set_sha256': None,
            'contract_sha256': None,
        },
        'evidence_sha256': '2' * 64,
    }
    install_decl = _write_artifact(
        root, 'global', 'field-install', install_value)
    hardware_decl = _write_artifact(root, 'global', 'hardware', {
        'runtime_family': 'ROS1',
        'ros_distro': 'noetic',
        'read_only': True,
        'authorizes_motion': False,
        'camera_only': True,
        'shared_graph': False,
        'mixed_tf': False,
        'validated_pass': True,
        'control_publishers_present': False,
    })
    return {
        'source_binding': source_decl,
        'source_path': source_path,
        'model_binding': {
            'manifest': model_decl,
            'model_root': 'global/models',
            'artifacts': model_artifacts,
        },
        'model_manifest_path': model_path,
        'model_root': model_root,
        'output_contract': output_decl,
        'output_path': output_path,
        'ros1_field_install_validation': install_decl,
        'hardware_readiness': hardware_decl,
        'expected_topic_manifest': topic_decl,
        'topic_manifest_path': topic_path,
    }


def _formal_scene(root, scene, scene_index, globals_value):
    capture_id = 'formal-capture-{}-{}'.format(scene_index, scene)
    task_id = 'formal-task-{}-{}'.format(scene_index, scene)
    model_hash = '3' * 64
    support = _indexer_test_support()
    manifest, connections, messages, _ids = support['_fixture']()
    prefix = (scene + ':').encode('ascii')
    for message in messages:
        message['serialized_payload'] = (
            prefix + message['serialized_payload'])
    support['_attach_connection_header_evidence'](connections, messages)
    index_value = support['inspect_records'](
        connections, messages, capture_id, scene, manifest)

    raw_decl, raw_path = _write_bytes_artifact(
        root, scene, 'capture', prefix, suffix='.bag')
    index_value.update({
        'report_kind': 'formal_rgbd_raw_capture_index',
        'inspection_scope': 'formal_scene_raw_capture',
        'mode': 'formal_camera_only',
        'formal_acceptance': True,
        'diagnostic_completed': False,
        'shared_graph': False,
        'mixed_tf': False,
        'not_in_four_scene_denominator': False,
        'delivery_ready': False,
        'source_capture': _absolute_identity(raw_path),
        'limitations': [],
    })
    index_decl = _write_artifact(
        root, scene, 'raw-index', index_value)
    index_path = Path(root) / index_decl['path']

    frames = []
    for sequence, bundle in enumerate(
            index_value['accepted_bundles'], 1):
        stamp_ns = bundle['header_stamps_ns']['rgb']
        stamp_sec = stamp_ns / 1e9
        targets = _targets(scene, stamp_sec, model_hash)
        frames.append({
            'schema_version': 1,
            'read_only': True,
            'received_unix_sec': stamp_sec + 0.2,
            'transport_latency_sec': 0.2,
            'stamp': {
                'sec': stamp_ns // 1_000_000_000,
                'nanosec': stamp_ns % 1_000_000_000,
            },
            'frame_id': 'camera_color_optical_frame',
            'task_id': task_id,
            'capture_id': capture_id,
            'bundle_id': _raw_bundle_identifier(bundle, model_hash),
            'model_binding_sha256': model_hash,
            'sequence': sequence,
            'valid': True,
            'status': 'valid' if targets else 'no_targets',
            'error_code': '',
            'sync_span_sec': bundle['stamp_span_sec'],
            'processing_latency_sec': 0.1,
            'tf_target_frame': 'base_link',
            'tf_valid': True,
            'tf_transform_applied': True,
            'tf_status': 'applied',
            'tf_error_code': '',
            'targets': targets,
            'scene': scene,
        })
    frames_decl, frames_path = _write_jsonl_artifact(
        root, scene, 'typed-frames', frames)
    collector_value = {
        'schema_version': 1,
        'collector_kind': 'ros1_typed_frame_readonly',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'scene': scene,
        'topic': '/cleanup/perception/frames',
        'message_type': 'limo_cleanup_ros1_perception/PerceptionFrame',
        'task_id': task_id,
        'max_frames': len(frames),
        'duration_sec': 60.0,
        'received_frames': len(frames),
        'unique_frames': len(frames),
        'duplicate_sequences': 0,
        'duplicate_bundle_ids': 0,
        'serialization_errors': 0,
        'interrupted': False,
        'completed_minimum': True,
        'completed_requested_frames': True,
        'output': _absolute_identity(frames_path),
    }
    collector_decl = _write_artifact(
        root, scene, 'collector', collector_value)
    collector_path = Path(root) / collector_decl['path']
    context = {
        'index_path': index_path,
        'frames_path': frames_path,
        'collector_path': collector_path,
        'raw_bag_path': raw_path,
        'workspace_root': WORKSPACE,
        'source_admission_path': globals_value['source_path'],
        'topic_manifest_path': globals_value['topic_manifest_path'],
        'model_manifest_path': globals_value['model_manifest_path'],
        'model_root': globals_value['model_root'],
    }
    binding_value = BINDING.create_binding(
        index_value, frames, collector_value, artifact_context=context)
    assert binding_value.get('association_count') == len(frames), (
        scene, binding_value.get('failures'))
    binding_decl = _write_artifact(
        root, scene, 'typed-raw-binding', binding_value)
    rgb_by_bundle = {
        item['bundle_id']: item['raw_stream_payload_sha256']['rgb']
        for item in binding_value['associations']}

    ground_records = []
    tf_records = []
    xyz_records = []
    depth_records = []
    latency_records = []
    for frame in frames:
        stamp_ns = (
            frame['stamp']['sec'] * 1_000_000_000
            + frame['stamp']['nanosec'])
        annotations = _annotations(
            scene, frame['sequence'], frame['targets'])
        ground_records.append({
            'sequence': frame['sequence'],
            'stamp_ns': stamp_ns,
            'bundle_id': frame['bundle_id'],
            'rgb_payload_sha256': rgb_by_bundle[frame['bundle_id']],
            'annotations': annotations,
        })
        transform_identity = {
            'topic': '/tf_static',
            'connection_id': 6,
            'callerid': '/camera/camera',
            'parent_frame_id': 'base_link',
            'child_frame_id': 'camera_color_optical_frame',
            'lookup_source_frame': 'camera_color_optical_frame',
            'lookup_target_frame': 'base_link',
            'stamp_ns': stamp_ns,
            'translation_m': [0.0, 0.0, 0.0],
            'rotation_xyzw': [0.0, 0.0, 0.0, 1.0],
        }
        tf_records.append({
            'sequence': frame['sequence'],
            'stamp_ns': stamp_ns,
            'bundle_id': frame['bundle_id'],
            **transform_identity,
            'transform_sha256': _canonical_sha256(transform_identity),
            'lookup_succeeded': True,
            'transform_applied': True,
            'output_frame': 'base_link',
            'target_observations': [{
                'observation_id': target['observation_id'],
                'input_position': dict(target['position']),
                'output_position': dict(target['position']),
            } for target in frame['targets']],
        })
        for target in frame['targets']:
            common = {
                'sequence': frame['sequence'],
                'stamp_ns': stamp_ns,
                'bundle_id': frame['bundle_id'],
                'observation_id': target['observation_id'],
            }
            xyz_records.append({
                **common,
                'object_class': target['object_class'],
                'reference_position': dict(target['position']),
                'measured_position': dict(target['position']),
                'error_m': 0.0,
                'reference_artifact_sha256': '4' * 64,
            })
            depth_records.append({
                **common,
                'object_class': target['object_class'],
                'reference_depth_m': target['depth_m'],
                'measured_depth_m': target['depth_m'],
                'valid_pixels': target['depth_valid_pixels'],
                'total_pixels': target['depth_total_pixels'],
                'valid_ratio': target['depth_valid_ratio'],
                'valid': True,
                'error_m': 0.0,
                'reference_artifact_sha256': '5' * 64,
            })
        sensor = stamp_ns / 1e9
        latency_records.append({
            'sequence': frame['sequence'],
            'stamp_ns': stamp_ns,
            'bundle_id': frame['bundle_id'],
            'sensor_stamp_sec': sensor,
            'inference_started_unix_sec': sensor + 0.05,
            'inference_ended_unix_sec': sensor + 0.15,
            'collector_received_unix_sec': sensor + 0.2,
            'sync_span_sec': frame['sync_span_sec'],
            'processing_latency_sec': 0.1,
            'transport_latency_sec': 0.2,
            'end_to_end_latency_sec': 0.2,
        })

    common_summary = {
        'schema_version': 1,
        'scene': scene,
        'capture_id': capture_id,
        'task_id': task_id,
        'ros1_field_install_sha256': '2' * 64,
        'model_binding_sha256': model_hash,
        'synthetic_test_only': False,
    }
    ground_decl = _write_artifact(root, scene, 'ground-truth', {
        **common_summary,
        'report_kind': 'ros1_ground_truth',
        'complete': True,
        'unique_frames': len(ground_records),
        'annotation_count': sum(
            len(record['annotations']) for record in ground_records),
        'records': ground_records,
    })
    tf_decl = _write_artifact(root, scene, 'tf-application', {
        **common_summary,
        'report_kind': 'ros1_tf_application',
        'source_frame': 'camera_color_optical_frame',
        'target_frame': 'base_link',
        'transform_applied': True,
        'mixed_tf': False,
        'tf_valid_frames': len(tf_records),
        'xyz_valid_frames': len(tf_records),
        'records': tf_records,
    })
    xyz_decl = _write_artifact(root, scene, 'xyz-reference', {
        **common_summary,
        'report_kind': 'ros1_xyz_reference',
        'not_applicable': not xyz_records,
        'sample_count': len(xyz_records),
        'max_error_m': 0.0 if xyz_records else None,
        'p95_error_m': 0.0 if xyz_records else None,
        'records': xyz_records,
    })
    depth_decl = _write_artifact(root, scene, 'depth-reference', {
        **common_summary,
        'report_kind': 'ros1_depth_reference',
        'not_applicable': not depth_records,
        'sample_count': len(depth_records),
        'valid_rate': 1.0 if depth_records else None,
        'max_error_m': 0.0 if depth_records else None,
        'p95_error_m': 0.0 if depth_records else None,
        'records': depth_records,
    })
    latency_decl = _write_artifact(root, scene, 'latency', {
        **common_summary,
        'report_kind': 'ros1_latency_evidence',
        'sample_count': len(latency_records),
        'max_latency_sec': 0.2,
        'p95_end_to_end_sec': 0.2,
        'p95_processing_sec': 0.1,
        'p95_sync_sec': 0.001,
        'records': latency_records,
    })
    first_stamp = index_value['accepted_bundles'][0][
        'header_stamps_ns']['rgb']
    last_stamp = index_value['accepted_bundles'][-1][
        'header_stamps_ns']['rgb']
    return {
        'capture_id': capture_id,
        'task_id': task_id,
        'capture_window': {
            'record_start_ns': first_stamp,
            'record_end_ns': last_stamp + 20_000_000,
            'header_start_ns': first_stamp,
            'header_end_ns': last_stamp,
        },
        'raw_bag': raw_decl,
        'raw_index': index_decl,
        'collector_manifest': collector_decl,
        'typed_frames': frames_decl,
        'typed_raw_binding': binding_decl,
        'ground_truth_artifact': ground_decl,
        'tf_artifact': tf_decl,
        'xyz_artifact': xyz_decl,
        'depth_artifact': depth_decl,
        'latency_artifact': latency_decl,
    }


def _formal_payload(root):
    globals_value = _formal_globals(root)
    scenes = {
        scene: _formal_scene(root, scene, index, globals_value)
        for index, scene in enumerate(SCENES)}
    payload = {
        'schema_version': 1,
        'bundle_id': '',
        'runtime_family': 'ROS1',
        'ros_distro': 'noetic',
        'evidence_scope': 'formal_four_scene_rosbag1_rgbd_acceptance',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'delivery_ready': False,
        'source_binding': globals_value['source_binding'],
        'model_binding': globals_value['model_binding'],
        'output_contract': globals_value['output_contract'],
        'ros1_field_install_validation': (
            globals_value['ros1_field_install_validation']),
        'hardware_readiness': globals_value['hardware_readiness'],
        'expected_topic_manifest': globals_value[
            'expected_topic_manifest'],
        'scenes': scenes,
        'required_gates': copy.deepcopy(READINESS.REQUIRED_GATES),
    }
    _refresh_formal_bundle_id(payload)
    return payload


def _artifact_json(root, declaration):
    return json.loads(
        (Path(root) / declaration['path']).read_text(encoding='utf-8'))


def _formal_assess(root, payload):
    _refresh_formal_bundle_id(payload)
    result = READINESS.assess_field_readiness(
        payload, artifact_root=root, workspace_root=WORKSPACE)
    _assert_safe_failure(result)
    assert result['formal_four_scene_pass'] is False
    assert result['formal_tf_3d_pass'] is False
    assert 'readiness_bundle_id_invalid' not in result['failures']
    return result


def _assert_scene_role_failure(result, scene, role):
    failures = result['scene_reports'][scene]['failures']
    assert any(role in failure for failure in failures), (role, failures)


def _raw_bundle(index, stamp_ns):
    streams = ('rgb', 'raw_depth', 'rgb_camera_info', 'depth_camera_info')
    return {
        'index': index,
        'header_stamps_ns': {name: stamp_ns for name in streams},
        'stream_payload_sha256': {
            name: hashlib.sha256(
                '{}:{}:{}'.format(index, stamp_ns, name).encode('utf-8')
            ).hexdigest()
            for name in streams
        },
        'stamp_span_sec': 0.0,
    }


def _minimal_false_positive_binding_fixture():
    capture_id = 'self-reported-capture'
    task_id = 'self-reported-task'
    scene = 'background'
    base_stamp_ns = 2_000_000_000
    bundles = [
        _raw_bundle(index, base_stamp_ns + index * 1_000_000_000)
        for index in range(30)]
    index_report = {
        'inspection_passed': True,
        'formal_acceptance': True,
        'not_in_four_scene_denominator': False,
        'read_only': True,
        'authorizes_motion': False,
        'shared_graph': False,
        'mixed_tf': False,
        'mode': 'formal_camera_only',
        'capture_id': capture_id,
        'scene': scene,
        'accepted_bundles': bundles,
    }
    collector = {
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'scene': scene,
        'task_id': task_id,
    }
    frames = []
    for index, bundle in enumerate(bundles):
        stamp_ns = bundle['header_stamps_ns']['rgb']
        frames.append({
            'stamp': {
                'sec': stamp_ns // 1_000_000_000,
                'nanosec': stamp_ns % 1_000_000_000,
            },
            'sequence': index + 1,
            'bundle_id': '{:064x}'.format(index + 1),
            'model_binding_sha256': '1' * 64,
            'capture_id': capture_id,
            'task_id': task_id,
            'scene': scene,
            'read_only': True,
            'sync_span_sec': 0.0,
            'targets': [],
        })
    return index_report, frames, collector


def _create_binding(index_report, frames, collector, test_only=False):
    parameters = inspect.signature(BINDING.create_binding).parameters
    keywords = {}
    if 'test_only' in parameters:
        keywords['test_only'] = test_only
    return BINDING.create_binding(
        index_report, frames, collector, **keywords)


def _assert_safe_failure(result):
    assert result['read_only'] is True
    assert result['authorizes_motion'] is False
    assert result['delivery_ready'] is False


def test_placeholder_json_and_naked_pass_booleans_never_grant_delivery():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _shallow_self_reported_readiness(root)
        result = READINESS.assess_field_readiness(
            payload, artifact_root=root)
    _assert_safe_failure(result)
    assert result['validated_pass'] is False
    assert result['formal_four_scene_pass'] is False
    assert result['formal_tf_3d_pass'] is False
    assert result['failures']


def test_self_reported_counts_without_live_artifact_audit_fail_closed():
    with TemporaryDirectory() as directory:
        payload = _shallow_self_reported_readiness(Path(directory))
        result = READINESS.assess_field_readiness(payload)
    _assert_safe_failure(result)
    assert result['validated_pass'] is False
    assert any(
        'artifact_live_audit_missing' in failure
        or 'readiness_schema' in failure
        for failure in result['failures'])


def test_minimal_typed_frames_without_frame_depth_tf_cannot_be_formal():
    index_report, frames, collector = (
        _minimal_false_positive_binding_fixture())
    result = _create_binding(index_report, frames, collector)
    _assert_safe_failure(result)
    assert result['formal_acceptance'] is False
    assert result['not_in_four_scene_denominator'] is True
    assert result['failures']


def test_diagnostic_shared_mixed_or_nonformal_raw_index_is_rejected():
    index_report, frames, collector = (
        _minimal_false_positive_binding_fixture())
    cases = (
        ('shared_graph', True),
        ('mixed_tf', True),
        ('mode', 'diagnostic_shared_graph'),
        ('formal_acceptance', False),
        ('not_in_four_scene_denominator', True),
    )
    for key, value in cases:
        mutated = dict(index_report)
        mutated[key] = value
        result = _create_binding(mutated, frames, collector)
        _assert_safe_failure(result)
        assert result['formal_acceptance'] is False
        assert result['not_in_four_scene_denominator'] is True
        assert any(
            failure.startswith('raw_index_')
            for failure in result['failures'])


def test_explicit_test_only_mode_can_never_emit_delivery_ready():
    index_report, frames, collector = (
        _minimal_false_positive_binding_fixture())
    result = _create_binding(
        index_report, frames, collector, test_only=True)
    assert result['read_only'] is True
    assert result['authorizes_motion'] is False
    assert result['delivery_ready'] is False


def test_self_reported_counts_cannot_override_artifact_denominators():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _semantic_self_reported_readiness(root)
        scene = payload['scenes']['background']
        declaration = scene['ground_truth_artifact']
        content = json.loads(
            (root / declaration['path']).read_text(encoding='utf-8'))
        content['unique_frames'] = 29
        content['annotation_count'] = 29
        _rewrite_declared_artifact(root, declaration, content)
        result = READINESS.assess_field_readiness(
            payload, artifact_root=root)
    _assert_safe_failure(result)
    assert result['validated_pass'] is False
    assert result['failures']


def test_artifact_roles_are_not_interchangeable():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _semantic_self_reported_readiness(root)
        scene = payload['scenes']['bin_only']
        scene['ground_truth_artifact'], scene['tf_artifact'] = (
            scene['tf_artifact'], scene['ground_truth_artifact'])
        result = READINESS.assess_field_readiness(
            payload, artifact_root=root)
    _assert_safe_failure(result)
    assert result['validated_pass'] is False
    assert result['failures']


def test_ground_truth_tf_xyz_and_latency_content_are_recomputed():
    mutations = (
        (
            'ground_truth_artifact',
            {'complete': False, 'annotation_count': 0},
            'ground_truth'),
        (
            'tf_artifact',
            {'transform_applied': False},
            'tf_application'),
        (
            'tf_artifact',
            {'xyz_valid_frames': 1},
            'xyz'),
        (
            'latency_artifact',
            {'sample_count': 1},
            'latency'),
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for artifact_key, changes, expected_prefix in mutations:
            payload = _semantic_self_reported_readiness(
                root / expected_prefix)
            artifact_root = root / expected_prefix
            declaration = payload['scenes']['bottle_in_bin'][artifact_key]
            path = artifact_root / declaration['path']
            content = json.loads(path.read_text(encoding='utf-8'))
            content.update(changes)
            _rewrite_declared_artifact(
                artifact_root, declaration, content)
            result = READINESS.assess_field_readiness(
                payload, artifact_root=artifact_root)
            _assert_safe_failure(result)
            assert result['validated_pass'] is False
            assert any(
                expected_prefix in failure
                for failure in result['failures'])


def test_install_and_model_provenance_drift_is_not_self_reportable():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _semantic_self_reported_readiness(root)
        scene = payload['scenes']['bottle_outside']
        for artifact_key in (
                'ground_truth_artifact', 'tf_artifact',
                'latency_artifact'):
            declaration = scene[artifact_key]
            path = root / declaration['path']
            content = json.loads(path.read_text(encoding='utf-8'))
            content['ros1_field_install_sha256'] = '0' * 64
            content['model_binding_sha256'] = '1' * 64
            _rewrite_declared_artifact(root, declaration, content)
        result = READINESS.assess_field_readiness(
            payload, artifact_root=root)
    _assert_safe_failure(result)
    assert result['validated_pass'] is False
    assert result['failures']


def test_duplicate_cross_capture_model_and_bundle_binding_fail_closed():
    index_report, frames, collector = (
        _minimal_false_positive_binding_fixture())
    cases = []
    duplicate = copy.deepcopy(frames)
    duplicate[1]['bundle_id'] = duplicate[0]['bundle_id']
    cases.append(('duplicate_bundle', duplicate))
    crossed = copy.deepcopy(frames)
    crossed[0]['bundle_id'], crossed[1]['bundle_id'] = (
        crossed[1]['bundle_id'], crossed[0]['bundle_id'])
    cases.append(('cross_bundle', crossed))
    capture = copy.deepcopy(frames)
    capture[0]['capture_id'] = 'foreign-capture'
    cases.append(('cross_capture', capture))
    model = copy.deepcopy(frames)
    model[0]['model_binding_sha256'] = '2' * 64
    cases.append(('cross_model', model))
    for name, records in cases:
        result = _create_binding(index_report, records, collector)
        _assert_safe_failure(result)
        assert result['formal_acceptance'] is False, name
        assert result['failures'], name


def test_base_frame_claim_requires_a_real_applied_transform():
    index_report, frames, collector = (
        _minimal_false_positive_binding_fixture())
    for frame in frames:
        frame.update({
            'frame_id': 'camera_color_optical_frame',
            'valid': True,
            'status': 'valid',
            'error_code': '',
            'tf_metadata': {
                'source_frame': 'camera_color_optical_frame',
                'target_frame': 'base_link',
                'transform_applied': False,
                'chain_valid': True,
                'mixed_tf': False,
            },
        })
    result = _create_binding(index_report, frames, collector)
    _assert_safe_failure(result)
    assert result['formal_acceptance'] is False
    assert any(
        'tf_application' in failure or 'typed_frame' in failure
        for failure in result['failures'])


def test_formal_summary_only_empty_records_and_role_swap_fail_closed():
    roles = {
        'ground_truth_artifact': ('ground_truth', 'background'),
        'tf_artifact': ('tf_application', 'background'),
        'xyz_artifact': ('xyz', 'bottle_outside'),
        'depth_artifact': ('depth', 'bottle_outside'),
        'latency_artifact': ('latency', 'background'),
    }
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        originals = {
            key: _artifact_json(
                root, payload['scenes'][scene_name][key])
            for key, (_role, scene_name) in roles.items()}
        for key, (role, scene_name) in roles.items():
            scene = payload['scenes'][scene_name]
            for mode in ('summary_only', 'empty_records'):
                mutated = copy.deepcopy(originals[key])
                if mode == 'summary_only':
                    mutated.pop('records')
                else:
                    mutated['records'] = []
                _rewrite_declared_artifact(root, scene[key], mutated)
                result = _formal_assess(root, payload)
                _assert_scene_role_failure(result, scene_name, role)
                _rewrite_declared_artifact(
                    root, scene[key], originals[key])

        scene = payload['scenes']['background']
        scene['ground_truth_artifact'], scene['tf_artifact'] = (
            scene['tf_artifact'], scene['ground_truth_artifact'])
        result = _formal_assess(root, payload)
        _assert_scene_role_failure(result, 'background', 'ground_truth')
        _assert_scene_role_failure(result, 'background', 'tf_application')


def test_formal_rehashed_single_sample_tamper_cannot_hide_binding_drift():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        declaration = payload['scenes']['background'][
            'ground_truth_artifact']
        value = _artifact_json(root, declaration)
        old_artifact_sha = declaration['sha256']
        old_bundle_id = payload['bundle_id']
        value['records'][0]['bundle_id'] = 'f' * 64
        _rewrite_declared_artifact(root, declaration, value)
        _refresh_formal_bundle_id(payload)
        assert declaration['sha256'] != old_artifact_sha
        assert payload['bundle_id'] != old_bundle_id
        result = _formal_assess(root, payload)
        _assert_scene_role_failure(result, 'background', 'ground_truth')
        assert not any(
            'artifact_identity_mismatch' in failure
            for failure in result['failures'])


def test_formal_duplicate_cross_frame_capture_bundle_and_stamp_fail_closed():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        background = payload['scenes']['background']
        declaration = background['ground_truth_artifact']
        original = _artifact_json(root, declaration)
        cases = {}

        duplicate = copy.deepcopy(original)
        duplicate['records'][1] = copy.deepcopy(duplicate['records'][0])
        cases['duplicate'] = ('background', declaration, duplicate)

        cross_bundle = copy.deepcopy(original)
        cross_bundle['records'][0]['bundle_id'] = (
            cross_bundle['records'][1]['bundle_id'])
        cases['cross_bundle'] = (
            'background', declaration, cross_bundle)

        cross_stamp = copy.deepcopy(original)
        cross_stamp['records'][0]['stamp_ns'] = (
            cross_stamp['records'][1]['stamp_ns'])
        cases['cross_stamp'] = ('background', declaration, cross_stamp)

        bin_declaration = payload['scenes']['bin_only'][
            'ground_truth_artifact']
        bin_original = _artifact_json(root, bin_declaration)
        cross_capture = copy.deepcopy(bin_original)
        cross_capture['records'] = copy.deepcopy(original['records'])
        cross_capture['unique_frames'] = len(cross_capture['records'])
        cross_capture['annotation_count'] = sum(
            len(record['annotations'])
            for record in cross_capture['records'])
        cases['cross_capture'] = (
            'bin_only', bin_declaration, cross_capture)

        for name, (scene_name, target_declaration, mutated) in cases.items():
            _rewrite_declared_artifact(
                root, target_declaration, mutated)
            result = _formal_assess(root, payload)
            _assert_scene_role_failure(
                result, scene_name, 'ground_truth')
            restore = original if scene_name == 'background' else bin_original
            _rewrite_declared_artifact(
                root, target_declaration, restore)


def test_formal_tf_lookup_success_without_applied_transform_fails_closed():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        declaration = payload['scenes']['background']['tf_artifact']
        value = _artifact_json(root, declaration)
        assert value['records'][0]['lookup_succeeded'] is True
        value['records'][0]['transform_applied'] = False
        _rewrite_declared_artifact(root, declaration, value)
        result = _formal_assess(root, payload)
        _assert_scene_role_failure(result, 'background', 'tf_application')


def test_formal_xyz_depth_latency_summaries_must_match_each_record():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        scene = payload['scenes']['bottle_outside']
        cases = (
            ('xyz_artifact', 'xyz', lambda value: value['records'][0][
                'measured_position'].__setitem__('x', 9.0)),
            ('depth_artifact', 'depth', lambda value: value['records'][0].
                __setitem__('measured_depth_m', 9.0)),
            ('latency_artifact', 'latency', lambda value: value['records'][0].
                __setitem__('end_to_end_latency_sec', 0.70)),
        )
        for key, role, mutate in cases:
            declaration = scene[key]
            original = _artifact_json(root, declaration)
            mutated = copy.deepcopy(original)
            mutate(mutated)
            _rewrite_declared_artifact(root, declaration, mutated)
            result = _formal_assess(root, payload)
            _assert_scene_role_failure(
                result, 'bottle_outside', role)
            _rewrite_declared_artifact(root, declaration, original)


def test_formal_ground_truth_records_require_explicit_annotations():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        declaration = payload['scenes']['background'][
            'ground_truth_artifact']
        value = _artifact_json(root, declaration)
        value['records'][0].pop('annotations')
        _rewrite_declared_artifact(root, declaration, value)
        result = _formal_assess(root, payload)
        _assert_scene_role_failure(result, 'background', 'ground_truth')


def test_formal_outer_identity_and_window_must_match_recomputed_chain():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        scene = payload['scenes']['background']
        scene['capture_id'] = 'outer-only-capture-id'
        scene['task_id'] = 'outer-only-task-id'
        scene['capture_window']['record_end_ns'] += 1
        for key in (
                'ground_truth_artifact', 'tf_artifact', 'xyz_artifact',
                'depth_artifact', 'latency_artifact'):
            declaration = scene[key]
            value = _artifact_json(root, declaration)
            value['capture_id'] = scene['capture_id']
            value['task_id'] = scene['task_id']
            _rewrite_declared_artifact(root, declaration, value)
        result = _formal_assess(root, payload)
        scene_failures = result['scene_reports']['background']['failures']
    assert 'scene:background:capture_identity_mismatch' in scene_failures
    assert 'scene:background:task_identity_mismatch' in scene_failures
    assert 'scene:background:capture_window_binding_mismatch' in scene_failures


def test_formal_scene_key_must_match_redecoded_scene_chain():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        payload['scenes']['bin_only'] = copy.deepcopy(
            payload['scenes']['background'])
        result = _formal_assess(root, payload)
        scene_failures = result['scene_reports']['bin_only']['failures']
    assert 'scene:bin_only:scene_identity_mismatch' in scene_failures


def test_artifact_parent_linklike_component_is_rejected():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / 'linked-parent' / 'artifact.json'
        path.parent.mkdir(parents=True)
        path.write_text('{}\n', encoding='utf-8')
        declaration = _declaration(root, path)
        failures = []
        original = READINESS._path_is_linklike

        def simulated_link(path_value):
            return (Path(path_value).name == 'linked-parent'
                    or original(path_value))

        with patch.object(
                READINESS, '_path_is_linklike', side_effect=simulated_link):
            resolved = READINESS._resolve_artifact(
                declaration, root, 'parent-link-probe', failures, set())
    assert resolved is None
    assert 'parent-link-probe:artifact_path_invalid' in failures


def test_cross_scene_content_raw_bundle_and_window_reuse_fail_closed():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        background = payload['scenes']['background']
        bin_only = payload['scenes']['bin_only']

        background_raw = root / background['raw_bag']['path']
        bin_raw = root / bin_only['raw_bag']['path']
        bin_raw.write_bytes(background_raw.read_bytes())
        bin_only['raw_bag']['size_bytes'] = bin_raw.stat().st_size
        bin_only['raw_bag']['sha256'] = _sha256(bin_raw)

        background_latency = root / background['latency_artifact']['path']
        bin_latency = root / bin_only['latency_artifact']['path']
        bin_latency.write_bytes(background_latency.read_bytes())
        bin_only['latency_artifact']['size_bytes'] = bin_latency.stat().st_size
        bin_only['latency_artifact']['sha256'] = _sha256(bin_latency)

        result = _formal_assess(root, payload)
    assert 'four_scene_raw_capture_fingerprint_reused' in result['failures']
    assert 'four_scene_artifact_content_fingerprint_reused' in result[
        'failures']
    assert READINESS._capture_windows_overlap(
        background['capture_window'], bin_only['capture_window']) is True
    window_failures = []
    windows = []
    READINESS._record_capture_window(
        'background', background['capture_window'], windows, window_failures)
    READINESS._record_capture_window(
        'bin_only', bin_only['capture_window'], windows, window_failures)
    assert 'four_scene_capture_window_overlap' in window_failures

    association = {
        'bundle_id': '1' * 64,
        'raw_stream_payload_sha256': {
            'rgb': '2' * 64,
            'raw_depth': '3' * 64,
            'rgb_camera_info': '4' * 64,
            'depth_camera_info': '5' * 64,
        },
    }
    failures = []
    seen = {}
    READINESS._record_raw_bundle_fingerprints(
        'background', {'associations': [association]}, seen, failures)
    READINESS._record_raw_bundle_fingerprints(
        'bin_only', {'associations': [association]}, seen, failures)
    assert 'four_scene_raw_bundle_fingerprint_reused' in failures


def test_expected_topic_manifest_requires_formal_loader_scope():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        formal_source = (
            OVERLAY_ROOT / 'config'
            / 'dabai_ros1_formal_four_scene_six_topics_v1.json')
        formal_decl, _ = _write_bytes_artifact(
            root, 'manifest', formal_source.stem, formal_source.read_bytes(),
            suffix='.json')
        failures = []
        formal_path = READINESS._validate_expected_manifest(
            {'expected_topic_manifest': formal_decl}, root, failures, set())
        assert formal_path is not None
        assert failures == [], failures

        raw_source = (
            OVERLAY_ROOT / 'config'
            / 'dabai_ros1_raw_rgbd_six_topics_v1.json')
        raw_decl, _ = _write_bytes_artifact(
            root, 'manifest', raw_source.stem, raw_source.read_bytes(),
            suffix='.json')
        failures = []
        READINESS._validate_expected_manifest(
            {'expected_topic_manifest': raw_decl}, root, failures, set())
    assert 'expected_topic_manifest_invalid' in failures


def test_overlay_install_self_report_remains_non_authoritative():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _formal_payload(root)
        install = _artifact_json(
            root, payload['ros1_field_install_validation'])
        assert install['validated_pass'] is True
        result = _formal_assess(root, payload)
    assert 'host_install_admission_not_validated' in result['failures']
    assert result['install_authority_scope'] == (
        'overlay_non_authoritative_material_only')
    assert result['host_install_admission_required'] is True
    assert result['delivery_ready'] is False


if __name__ == '__main__':
    import inspect as inspect_module

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_')
        and inspect_module.isfunction(value)]
    for test in tests:
        test()
    print('{} ROS1 semantic readiness tests passed'.format(len(tests)))
