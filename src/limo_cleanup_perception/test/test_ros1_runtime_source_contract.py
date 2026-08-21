"""ROS-independent contracts for the complete ROS1 Noetic V2 runtime.

All behavioral fixtures are synthetic and live below a temporary directory.
The tests never import a ROS client, start a graph, open a camera, or authorize
motion.  A synthetic readiness PASS proves only validator behavior; it is not
field or delivery evidence for the project workspace.
"""

import ast
import copy
import hashlib
import importlib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


WORKSPACE = Path(__file__).resolve().parents[3]
OVERLAY = (
    WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception')
OVERLAY_PYTHON = OVERLAY / 'src'
HOST_PYTHON = WORKSPACE / 'src' / 'limo_cleanup_perception'
for candidate in (str(OVERLAY_PYTHON), str(HOST_PYTHON), str(WORKSPACE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from limo_cleanup_perception import perception_readiness as install_readiness


SCENES = (
    'background', 'bin_only', 'bottle_in_bin', 'bottle_outside')
MODEL_BINDINGS = {
    'plastic_bottle': {
        'class_name': 'plastic_bottle',
        'filename': 'nongfu_yolov8n_best.pt',
        'deployment_path': (
            '/home/agilex/limo_cleanup_ws/models/'
            'nongfu_yolov8n_best.pt'),
        'size_bytes': 6244778,
        'sha256': (
            'abe7eaf409e3d24d255a627823f4b107'
            'a8884008ab659901c6c50479b2153512'),
        'backend': 'ultralytics-yolo-pt',
    },
    'trash_bin': {
        'class_name': 'trash_bin',
        'filename': 'trash_bin_yolov8n_best.pt',
        'deployment_path': (
            '/home/agilex/limo_cleanup_ws/models/'
            'trash_bin_yolov8n_best.pt'),
        'size_bytes': 6231338,
        'sha256': (
            '24beb4a7941ba5d783f1937128b5f0f4307b03513'
            '7889c78be1993cad76b8bc5'),
        'backend': 'ultralytics-yolo-pt',
    },
}
OUTPUT_TOPICS = {
    '/cleanup/perception/frames',
    '/cleanup/detection/raw',
    '/cleanup/perception_status',
}
FORBIDDEN_CONTROL_TOPICS = {
    '/cmd_vel',
    '/cleanup/base/safe_cmd_vel',
    '/move_base/goal',
    '/move_base/cancel',
    '/arm_controller/command',
    '/gripper_controller/command',
}


def _load_ros1_module(name):
    importlib.invalidate_caches()
    return importlib.import_module(
        'limo_cleanup_ros1_perception.' + name)


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _copy_overlay_workspace(root):
    workspace = Path(root) / 'workspace'
    target = (
        workspace / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception')
    target.parent.mkdir(parents=True)
    shutil.copytree(OVERLAY, target, ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', '*.pyo'))
    return workspace, target


def _assert_rejected(result, expected):
    assert result['validated_pass'] is False
    assert result['formal_four_scene_pass'] is False
    assert result['formal_tf_3d_pass'] is False
    assert result['delivery_ready'] is False
    assert expected in result['failures']


def _artifact(root, scene, role):
    path = Path(root) / scene / (role + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            'scene': scene,
            'role': role,
            'synthetic_test_only': True,
        }, sort_keys=True) + '\n',
        encoding='utf-8')
    return {
        'path': path.relative_to(root).as_posix(),
        'size_bytes': path.stat().st_size,
        'sha256': _sha256(path),
    }


def _readiness_payload(artifact_root):
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
            'capture_id': 'synthetic-capture-{}-{}'.format(index, scene),
            'task_id': 'synthetic-task-{}-{}'.format(index, scene),
            'ground_truth_artifact': _artifact(
                artifact_root, scene, 'ground-truth'),
            'tf_artifact': _artifact(artifact_root, scene, 'tf'),
            'latency_artifact': _artifact(
                artifact_root, scene, 'latency'),
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


def test_actual_overlay_source_implementation_passes_but_field_stays_blocked():
    audit = install_readiness.audit_ros1_noetic_field_source_contract(
        workspace=WORKSPACE)
    assert audit['pass'] is True
    assert audit['complete_runtime'] is True
    assert audit['interface_mode'] == 'native_ros1_messages'
    assert audit['indexer_only_detected'] is False
    assert install_readiness.ROS1_FORMAL_ROSBAG1_ADMISSION_BLOCKER not in (
        audit['architecture_blockers'])
    assert audit['architecture_blockers'] == []
    assert audit['failures'] == []
    assert audit['source_core_binding']['validated_pass'] is True
    assert audit['source_core_binding']['package_validator_executed'] is False
    assert audit['model_loader_validation']['validated_pass'] is True
    assert audit['model_loader_validation']['detector_module_executed'] is False
    assert audit['model_loader_validation']['target_contract_executed'] is False
    assert audit['model_loader_validation']['numpy_required_by_gate'] is False
    assert audit['formal_rosbag1_admission']['validated_pass'] is True
    assert audit['formal_rosbag1_admission'][
        'formal_mode_literal'] == 'sensor_only_short_sample'
    assert audit['formal_rosbag1_admission'][
        'formal_acceptance_mode_literal'] == 'formal_scene_raw_capture'
    assert audit['formal_rosbag1_admission'][
        'formal_camera_only_mode_literal'] == 'formal_camera_only'
    assert audit['formal_rosbag1_admission'][
        'formal_acceptance_true_literals'] >= 1
    assert audit['formal_rosbag1_admission'][
        'manifest_identity']['sha256'] == (
            install_readiness.ROS1_FORMAL_ROSBAG1_MANIFEST_ANCHOR['sha256'])
    assert audit['formal_rosbag1_admission']['field_evidence_admitted'] is False
    assert audit['formal_rosbag1_admission']['delivery_ready'] is False
    runtime_admission = audit['runtime_implementation_admission']
    assert runtime_admission['validated_pass'] is True
    assert runtime_admission['closes_source_implementation_blocker_only'] is True
    assert runtime_admission['ros1_noetic_install_validated'] is False
    assert runtime_admission['field_evidence_admitted'] is False
    assert runtime_admission['authorizes_field_delivery'] is False
    assert runtime_admission['delivery_ready'] is False
    assert audit['capability_matrix_diagnostic'][
        'authoritative_for_complete_runtime'] is False
    assert audit['capability_matrix_diagnostic'][
        'implementation_validated'] is False

    contract = _load_json(
        OVERLAY / 'config' / 'ros1_noetic_field_install_contract.json')
    assert contract['runtime_family'] == 'ROS1'
    assert contract['ros_distro'] == 'noetic'
    assert contract['required_for_delivery'] is True
    assert contract['indexer_only_sufficient'] is False
    assert set(contract['package']['forbidden_dependencies']) >= {
        'rclpy', 'ament_cmake', 'ament_python',
        'rosidl_default_generators', 'rosidl_default_runtime'}
    assert {
        'dual_model_detector.py', 'evidence_binding.py',
        'image_conversion.py',
        'orchestration_contract.py',
        'perception_core.py', 'perception_frame_collector.py',
        'perception_frame_io.py', 'perception_readiness.py',
        'rgbd_contract.py', 'ros1_adapter.py', 'target_contract.py',
        'typed_raw_binding.py',
    }.issubset(contract['required_python_modules'])
    assert contract['required_launch_files'] == [
        'perception_v2_formal_capture.launch',
        'perception_v2_readonly.launch']
    assert contract['required_catkin_test_files'] == [
        'test_rosbag1_isolated_probe.py',
        'test_rosbag1_rgbd_indexer.py',
        'test_ros1_adapter_pure_fake.py',
        'test_runtime_install_contract.py',
    ]
    assert contract['python_runtime_dependency_lock'] == {
        'lock_id': 'ROS1_NOETIC_PERCEPTION_PYTHON_RUNTIME_V1',
        'version_provenance': {
            'authority': 'latest_verified_limo_jetson_runtime',
            'source_path': 'docs/foxy_arm64_deployment.md',
            'source_scope': 'verified_arm64_runtime_versions',
            'source_declaration_is_install_evidence': False,
        },
        'source_policy': {
            'declaration_path': 'setup.py',
            'exact_pins_required': True,
            'rosdep_claim_forbidden': True,
            'source_declaration_is_install_evidence': False,
        },
        'install_evidence_policy': {
            'distribution_artifact_identity_required': True,
            'distribution_metadata_required': True,
            'fresh_isolated_import_probe_required': True,
            'module_origin_required': True,
            'reported_distribution_version_required': True,
            'reported_module_version_required': True,
            'runtime_provisioning_required': True,
            'regular_files_only': True,
            'linklike_forbidden': True,
        },
        'requirements': [
            {
                'distribution': 'numpy',
                'import_name': 'numpy',
                'exact_version': '1.23.4',
                'requirement': 'numpy==1.23.4',
                'required_for': 'rgbd_array_processing',
                'provisioning_policy': (
                    'isolated_offline_artifact_exact_version'),
                'deployment_source': 'isolated_offline_wheel_artifact',
                'distribution_artifact_provenance_policy': (
                    'required_field_install_artifact_identity'),
                'distribution_artifact_format': 'wheel',
            },
            {
                'distribution': 'torch',
                'import_name': 'torch',
                'exact_version': '2.1.0a0+41361538.nv23.06',
                'requirement': 'torch==2.1.0a0+41361538.nv23.06',
                'required_for': 'dual_model_backend',
                'provisioning_policy': (
                    'isolated_offline_artifact_exact_version'),
                'deployment_source': (
                    'isolated_jetson_vendor_wheel_artifact'),
                'distribution_artifact_provenance_policy': (
                    'required_field_install_artifact_identity'),
                'distribution_artifact_format': 'wheel',
            },
            {
                'distribution': 'ultralytics',
                'import_name': 'ultralytics',
                'exact_version': '8.3.21',
                'requirement': 'ultralytics==8.3.21',
                'required_for': 'dual_model_inference',
                'provisioning_policy': (
                    'isolated_offline_artifact_exact_version'),
                'deployment_source': 'isolated_offline_wheel_artifact',
                'distribution_artifact_provenance_policy': (
                    'required_field_install_artifact_identity'),
                'distribution_artifact_format': 'wheel',
            },
        ],
    }
    setup_source = (OVERLAY / 'setup.py').read_text(encoding='utf-8')
    for requirement in ('numpy==1.23.4',
                        'torch==2.1.0a0+41361538.nv23.06',
                        'ultralytics==8.3.21'):
        assert setup_source.count(repr(requirement)) == 1
    assert 'read_only_output_contract.json' in (
        contract['required_config_files'])
    assert 'dabai_ros1_formal_four_scene_six_topics_v1.json' in (
        contract['required_config_files'])
    assert set(contract['interface_modes'][
        'native_ros1_messages']['required_files']) >= {
            'msg/ObjectDetection.msg',
            'msg/PerceptionFrame.msg',
            'msg/PerceptionTarget.msg',
        }

    for item in audit['source_entries']:
        path = OVERLAY / item['path']
        assert path.is_file()
        assert not install_readiness._path_is_linklike(path)
        assert path.stat().st_size == item['size_bytes']
        assert _sha256(path) == item['sha256']

    manifest = _load_json(OVERLAY / 'config' / 'model_bindings.json')
    assert manifest['runtime_family'] == 'ROS1'
    assert manifest['ros_distro'] == 'noetic'
    assert manifest['read_only'] is True
    assert manifest['authorizes_motion'] is False
    assert manifest['delivery_ready'] is False
    assert manifest['models'] == MODEL_BINDINGS
    assert manifest['load_policy'] == {
        'regular_file_required': True,
        'sha256_required': True,
        'single_exact_class_required': True,
        'missing_model_is_fatal': True,
        'hash_mismatch_is_fatal': True,
        'silent_fallback_or_relabel_forbidden': True,
        'automatic_download_forbidden': True,
    }


def test_formal_rosbag1_source_admission_rejects_drift_and_legacy_manifest():
    baseline = install_readiness._audit_ros1_formal_rosbag1_admission_source(
        OVERLAY)
    assert baseline['validated_pass'] is True
    assert baseline['authorizes_field_delivery'] is False

    original_read_text = Path.read_text
    second_indexer_reads = []

    def reject_second_indexer_read(path, *args, **kwargs):
        if Path(path).name == 'rosbag1_rgbd_indexer.py':
            second_indexer_reads.append(str(path))
            raise AssertionError('indexer source was reopened after hashing')
        return original_read_text(path, *args, **kwargs)

    with patch.object(Path, 'read_text', new=reject_second_indexer_read):
        same_snapshot = (
            install_readiness._audit_ros1_formal_rosbag1_admission_source(
                OVERLAY))
    assert same_snapshot['validated_pass'] is True
    assert second_indexer_reads == []

    with TemporaryDirectory() as directory:
        root = Path(directory)

        workspace, package = _copy_overlay_workspace(root / 'source-drift')
        del workspace
        indexer = (
            package / 'src' / 'limo_cleanup_ros1_perception'
            / 'rosbag1_rgbd_indexer.py')
        indexer.write_text(
            indexer.read_text(encoding='utf-8').replace(
                'def inspect_formal_scene(', 'def inspect_formal_scene_drift(',
                1),
            encoding='utf-8')
        result = (
            install_readiness._audit_ros1_formal_rosbag1_admission_source(
                package))
        assert result['validated_pass'] is False
        assert 'ros1_formal_rosbag1_indexer_identity_mismatch' in (
            result['failures'])
        assert 'ros1_formal_rosbag1_ast_functions_missing' in (
            result['failures'])

        workspace, package = _copy_overlay_workspace(root / 'legacy-manifest')
        del workspace
        legacy = package / 'config' / 'dabai_ros1_raw_rgbd_six_topics_v1.json'
        formal = (
            package / 'config'
            / 'dabai_ros1_formal_four_scene_six_topics_v1.json')
        formal.write_bytes(legacy.read_bytes())
        result = (
            install_readiness._audit_ros1_formal_rosbag1_admission_source(
                package))
        assert result['validated_pass'] is False
        assert 'ros1_formal_rosbag1_manifest_identity_mismatch' in (
            result['failures'])
        assert 'ros1_formal_rosbag1_manifest_policy_invalid' in (
            result['failures'])

        workspace, package = _copy_overlay_workspace(root / 'linked-manifest')
        del workspace
        formal = (
            package / 'config'
            / 'dabai_ros1_formal_four_scene_six_topics_v1.json').resolve()
        original = install_readiness._path_is_linklike

        def simulated_link(path):
            if Path(path).resolve() == formal:
                return True
            return original(path)

        with patch.object(
                install_readiness, '_path_is_linklike',
                side_effect=simulated_link):
            result = (
                install_readiness._audit_ros1_formal_rosbag1_admission_source(
                    package))
        assert result['validated_pass'] is False
        assert 'ros1_formal_rosbag1_manifest_unavailable_or_invalid' in (
            result['failures'])

        workspace, package = _copy_overlay_workspace(root / 'hardlink-indexer')
        del workspace
        indexer = (
            package / 'src' / 'limo_cleanup_ros1_perception'
            / 'rosbag1_rgbd_indexer.py')
        hardlink_target = root / 'hardlink-indexer-target.py'
        shutil.copyfile(indexer, hardlink_target)
        indexer.unlink()
        os.link(hardlink_target, indexer)
        result = (
            install_readiness._audit_ros1_formal_rosbag1_admission_source(
                package))
        assert result['validated_pass'] is False
        assert any(
            item.startswith('ros1_formal_rosbag1_source_unavailable:')
            for item in result['failures'])

        def cooperatively_reanchor(name, manifest_transform,
                                   indexer_transform=None):
            workspace, package = _copy_overlay_workspace(root / name)
            del workspace
            formal = (
                package / 'config'
                / 'dabai_ros1_formal_four_scene_six_topics_v1.json')
            indexer = (
                package / 'src' / 'limo_cleanup_ros1_perception'
                / 'rosbag1_rgbd_indexer.py')
            original_manifest_sha = _sha256(formal)
            formal.write_text(
                manifest_transform(formal.read_text(encoding='utf-8')),
                encoding='utf-8')
            manifest_anchor = dict(
                install_readiness.ROS1_FORMAL_ROSBAG1_MANIFEST_ANCHOR)
            manifest_anchor.update({
                'size_bytes': formal.stat().st_size,
                'sha256': _sha256(formal),
            })
            indexer_source = indexer.read_text(encoding='utf-8').replace(
                original_manifest_sha, manifest_anchor['sha256'])
            if indexer_transform is not None:
                indexer_source = indexer_transform(indexer_source)
            indexer.write_text(indexer_source, encoding='utf-8')
            indexer_anchor = dict(
                install_readiness.ROS1_FORMAL_ROSBAG1_INDEXER_ANCHOR)
            indexer_anchor.update({
                'size_bytes': indexer.stat().st_size,
                'sha256': _sha256(indexer),
            })
            with patch.object(
                    install_readiness,
                    'ROS1_FORMAL_ROSBAG1_MANIFEST_ANCHOR',
                    manifest_anchor), patch.object(
                        install_readiness,
                        'ROS1_FORMAL_ROSBAG1_INDEXER_ANCHOR',
                        indexer_anchor):
                return (
                    install_readiness.
                    _audit_ros1_formal_rosbag1_admission_source(package))

        duplicate = cooperatively_reanchor(
            'duplicate-json-key',
            lambda text: text.replace(
                '  "read_only": true,',
                '  "read_only": false,\n  "read_only": true,', 1))
        assert duplicate['validated_pass'] is False
        assert 'ros1_formal_rosbag1_manifest_unavailable_or_invalid' in (
            duplicate['failures'])

        wrong_type = cooperatively_reanchor(
            'json-type-confusion',
            lambda text: text.replace('  "ros_major": 1,',
                                      '  "ros_major": true,', 1))
        assert wrong_type['validated_pass'] is False
        assert 'ros1_formal_rosbag1_manifest_policy_invalid' in (
            wrong_type['failures'])

        duplicate_function = cooperatively_reanchor(
            'duplicate-function', lambda text: text,
            lambda text: text + '\n\ndef main(args=None, reader_factory=None):\n'
            '    return 0\n')
        assert duplicate_function['validated_pass'] is False
        assert 'ros1_formal_rosbag1_ast_functions_missing' in (
            duplicate_function['failures'])


def test_source_audit_rejects_missing_ros2_link_and_model_hash_drift():
    contract = _load_json(
        OVERLAY / 'config' / 'ros1_noetic_field_install_contract.json')
    package_name = contract['package']['name']
    mutations = (
        (
            'module',
            'src/{}/ros1_adapter.py'.format(package_name),
            'ros1_field_source_missing:src/{}/ros1_adapter.py'.format(
                package_name)),
        (
            'entrypoint', 'scripts/dual_model_detector.py',
            'ros1_field_source_missing:scripts/dual_model_detector.py'),
        (
            'model_manifest', 'config/model_bindings.json',
            'ros1_field_model_manifest_missing_or_invalid'),
        (
            'message', 'msg/ObjectDetection.msg',
            'ros1_field_source_missing:msg/ObjectDetection.msg'),
        (
            'formal_launch', 'launch/perception_v2_formal_capture.launch',
            'ros1_field_source_missing:'
            'launch/perception_v2_formal_capture.launch'),
        (
            'readonly_launch', 'launch/perception_v2_readonly.launch',
            'ros1_field_source_missing:launch/perception_v2_readonly.launch'),
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name, relative, expected in mutations:
            workspace, package = _copy_overlay_workspace(root / name)
            (package / relative).unlink()
            audit = install_readiness.audit_ros1_noetic_field_source_contract(
                workspace=workspace)
            assert audit['pass'] is False
            assert expected in audit['failures']
            assert install_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER in (
                audit['architecture_blockers'])

        workspace, package = _copy_overlay_workspace(root / 'extra-launch')
        (package / 'launch/unreviewed_capture.launch').write_text(
            '<?xml version="1.0"?>\n<launch/>\n', encoding='utf-8')
        audit = install_readiness.audit_ros1_noetic_field_source_contract(
            workspace=workspace)
        assert audit['pass'] is False
        assert 'ros1_field_launch_source_set_invalid' in audit['failures']

        workspace, package = _copy_overlay_workspace(root / 'dependency')
        package_xml = package / 'package.xml'
        package_xml.write_text(
            package_xml.read_text(encoding='utf-8').replace(
                '  <depend>rospy</depend>\n', ''), encoding='utf-8')
        audit = install_readiness.audit_ros1_noetic_field_source_contract(
            workspace=workspace)
        assert audit['pass'] is False
        assert 'ros1_field_dependency_missing:rospy' in audit['failures']

        workspace, package = _copy_overlay_workspace(root / 'runtime-pin')
        setup_path = package / 'setup.py'
        setup_path.write_text(
            setup_path.read_text(encoding='utf-8').replace(
                "'torch==2.1.0a0+41361538.nv23.06'",
                "'torch==9.9.9'"),
            encoding='utf-8')
        audit = install_readiness.audit_ros1_noetic_field_source_contract(
            workspace=workspace)
        assert audit['pass'] is False
        assert 'ros1_runtime_dependency_source_pins_invalid' in (
            audit['failures'])

        workspace, package = _copy_overlay_workspace(root / 'fake-rosdep')
        package_xml = package / 'package.xml'
        package_xml.write_text(
            package_xml.read_text(encoding='utf-8').replace(
                '  <export>\n', '  <exec_depend>ultralytics</exec_depend>\n'
                '  <export>\n'), encoding='utf-8')
        audit = install_readiness.audit_ros1_noetic_field_source_contract(
            workspace=workspace)
        assert audit['pass'] is False
        assert (
            'ros1_runtime_dependency_rosdep_claim_forbidden:'
            'ultralytics' in audit['failures'])

        workspace, package = _copy_overlay_workspace(root / 'ros2')
        adapter = package / 'src' / package_name / 'ros1_adapter.py'
        adapter.write_text('import rclpy\n', encoding='utf-8')
        package_xml = package / 'package.xml'
        package_xml.write_text(
            package_xml.read_text(encoding='utf-8').replace(
                '  <export>\n',
                '  <depend>rclpy</depend>\n'
                '  <depend>ament_python</depend>\n'
                '  <export>\n'), encoding='utf-8')
        audit = install_readiness.audit_ros1_noetic_field_source_contract(
            workspace=workspace)
        assert audit['pass'] is False
        assert 'ros1_field_forbidden_dependency:rclpy' in audit['failures']
        assert 'ros1_field_forbidden_dependency:ament_python' in (
            audit['failures'])
        assert 'ros1_field_ros2_runtime_token:import_rclpy' in (
            audit['failures'])

        workspace, package = _copy_overlay_workspace(root / 'link')
        linked = package / 'src' / package_name / 'ros1_adapter.py'
        original = install_readiness._path_is_linklike

        def simulated_link(path):
            if Path(path).resolve() == linked.resolve():
                return True
            return original(path)

        with patch.object(
                install_readiness, '_path_is_linklike',
                side_effect=simulated_link):
            audit = (
                install_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=workspace))
        assert audit['pass'] is False
        assert (
            'ros1_field_source_link_forbidden:'
            'src/{}/ros1_adapter.py'.format(package_name)
            in audit['failures'])

        for label, field, value, expected in (
                (
                    'plastic_bottle', 'sha256', '0' * 64,
                    'ros1_field_model_hash_mismatch:plastic_bottle'),
                (
                    'trash_bin', 'size_bytes',
                    MODEL_BINDINGS['trash_bin']['size_bytes'] + 1,
                    'ros1_field_model_size_mismatch:trash_bin')):
            workspace, package = _copy_overlay_workspace(
                root / ('model-' + label + '-' + field))
            path = package / 'config' / 'model_bindings.json'
            manifest = _load_json(path)
            manifest['models'][label][field] = value
            path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            audit = install_readiness.audit_ros1_noetic_field_source_contract(
                workspace=workspace)
            assert audit['pass'] is False
            assert expected in audit['failures']


def test_messages_and_wrappers_expose_only_typed_read_only_observations():
    expected_fields = {
        'PerceptionFrame.msg': {
            'time stamp', 'string frame_id', 'string task_id',
            'uint32 sequence', 'string capture_id', 'string bundle_id',
            'string model_binding_sha256', 'string tf_target_frame',
            'bool tf_valid', 'bool tf_transform_applied',
            'string tf_status', 'string tf_error_code',
            'bool valid', 'string status',
            'string error_code', 'float32 sync_span_sec',
            'float32 processing_latency_sec',
            'limo_cleanup_ros1_perception/PerceptionTarget[] targets',
        },
        'PerceptionTarget.msg': {
            'string observation_id', 'string object_class',
            'float32 confidence', 'bool valid', 'bool actionable',
            'string status', 'string error_code',
            'geometry_msgs/Point position', 'geometry_msgs/Vector3 size',
            'float32 bbox_x1', 'float32 bbox_y1', 'float32 bbox_x2',
            'float32 bbox_y2', 'float32 depth_m',
            'uint32 depth_valid_pixels', 'uint32 depth_total_pixels',
            'float32 depth_valid_ratio', 'string source',
            'string position_semantics',
        },
        'ObjectDetection.msg': {
            'time stamp', 'string detection_id', 'string task_id',
            'string object_class', 'float32 confidence', 'string frame_id',
            'geometry_msgs/Point position', 'geometry_msgs/Vector3 size',
        },
    }
    for name, required in expected_fields.items():
        lines = {
            line.strip() for line in (OVERLAY / 'msg' / name).read_text(
                encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')}
        assert lines == required
        assert all('Twist' not in line for line in lines)

    wrappers = {
        'dual_model_detector.py': 'dual_model_detector',
        'perception_frame_adapter.py': 'ros1_adapter',
        'perception_frame_collector.py': 'perception_frame_collector',
        'perception_readiness.py': 'perception_readiness',
        'rosbag1_rgbd_indexer.py': 'rosbag1_rgbd_indexer',
        'typed_raw_binding.py': 'typed_raw_binding',
    }
    for filename, module in wrappers.items():
        source = (OVERLAY / 'scripts' / filename).read_text(encoding='utf-8')
        ast.parse(source)
        assert (
            'from limo_cleanup_ros1_perception.{} import main'.format(module)
            in source)
        assert 'main()' in source
        for forbidden in (
                'rospy.Publisher', 'rospy.Service', 'ServiceProxy',
                'actionlib', 'SimpleActionClient', 'Twist(', 'send_goal('):
            assert forbidden not in source


def test_ros1_adapter_has_exact_read_only_publish_surface():
    adapter = _load_ros1_module('ros1_adapter')
    topics = set(adapter.PERCEPTION_OUTPUT_TOPICS)
    assert topics == OUTPUT_TOPICS
    assert not topics.intersection(FORBIDDEN_CONTROL_TOPICS)

    output_contract = _load_json(
        OVERLAY / 'config' / 'read_only_output_contract.json')
    assert output_contract['runtime_family'] == 'ROS1'
    assert output_contract['ros_distro'] == 'noetic'
    assert output_contract['read_only'] is True
    assert output_contract['authorizes_motion'] is False
    assert output_contract['authorizes_field_delivery'] is False
    assert output_contract['delivery_ready'] is False
    assert output_contract['control_publishers_allowed'] is False
    assert output_contract['services_allowed'] is False
    assert output_contract['actions_allowed'] is False
    assert {
        item['topic'] for item in output_contract['allowed_publish_topics']
    } == OUTPUT_TOPICS
    assert all(
        item['may_trigger_motion'] is False
        for item in output_contract['allowed_publish_topics'])
    assert set(output_contract['forbidden_publish_topics']) == (
        FORBIDDEN_CONTROL_TOPICS)

    production_python = list((OVERLAY / 'src').rglob('*.py'))
    production_python.extend((OVERLAY / 'scripts').glob('*.py'))
    for path in production_python:
        if '__pycache__' in path.parts:
            continue
        source = path.read_text(encoding='utf-8')
        ast.parse(source)
        for forbidden in (
                'geometry_msgs.msg import Twist',
                'from geometry_msgs.msg import Twist',
                'move_base_msgs', 'control_msgs', 'trajectory_msgs',
                'actionlib', 'SimpleActionClient', 'rospy.Service(',
                'rospy.ServiceProxy(', '.send_goal(', 'Twist('):
            assert forbidden not in source, '{}:{}'.format(path, forbidden)


def test_observation_contract_rejects_frame_stamp_depth_and_tf_errors():
    adapter = _load_ros1_module('ros1_adapter')
    projection = {
        'valid': True,
        'error_code': '',
        'point': (0.1, -0.2, 1.0),
        'size': (0.2, 0.3, 0.1),
        'depth_m': 1.0,
        'valid_pixels': 80,
        'total_pixels': 100,
        'valid_ratio': 0.8,
    }
    camera_tf = {
        'source_frame': 'camera_color_optical_frame',
        'target_frame': 'camera_color_optical_frame',
        'stamp_sec': 100.0,
        'transform_applied': False,
        'chain_valid': True,
        'mixed_tf': False,
    }

    assert adapter.validate_observation_contract(
        frame_id='camera_color_optical_frame', stamp_sec=100.0,
        object_class='plastic_bottle', confidence=0.9,
        projection=projection, tf_metadata=camera_tf) == ()

    base_tf = dict(camera_tf)
    base_tf.update({
        'target_frame': 'base_link',
        'transform_applied': True,
    })
    assert adapter.validate_observation_contract(
        frame_id='camera_color_optical_frame', stamp_sec=100.0,
        object_class='trash_bin', confidence=0.8,
        projection=projection, tf_metadata=base_tf) == ()

    cases = []
    for value in ('', ' camera_color_optical_frame', 'camera frame'):
        cases.append(('frame_id', value, 'frame_id_invalid'))
    for value in (0.0, -1.0, math.nan, math.inf, True):
        cases.append(('stamp_sec', value, 'stamp_invalid'))
    for value in ('bottle', 'garbage_bin', '', None):
        cases.append(('object_class', value, 'class_invalid'))
    for value in (-0.1, 1.1, math.nan, math.inf, True):
        cases.append(('confidence', value, 'confidence_invalid'))
    for key, value, expected in cases:
        arguments = {
            'frame_id': 'camera_color_optical_frame',
            'stamp_sec': 100.0,
            'object_class': 'plastic_bottle',
            'confidence': 0.9,
            'projection': projection,
            'tf_metadata': camera_tf,
        }
        arguments[key] = value
        reasons = adapter.validate_observation_contract(**arguments)
        assert expected in reasons, (key, value, reasons)

    projection_cases = (
        ({}, 'projection_invalid'),
        (dict(projection, valid=False), 'projection_invalid'),
        (dict(projection, point=None), 'projection_invalid'),
        (dict(projection, size=None), 'projection_invalid'),
        (dict(projection, depth_m=0.0), 'depth_invalid'),
        (dict(projection, depth_m=math.nan), 'depth_invalid'),
        (dict(projection, valid_pixels=0), 'depth_invalid'),
        (dict(projection, total_pixels=0), 'depth_invalid'),
        (dict(projection, valid_ratio=1.1), 'depth_invalid'),
    )
    for invalid_projection, expected in projection_cases:
        reasons = adapter.validate_observation_contract(
            frame_id='camera_color_optical_frame', stamp_sec=100.0,
            object_class='plastic_bottle', confidence=0.9,
            projection=invalid_projection, tf_metadata=camera_tf)
        assert expected in reasons, (invalid_projection, reasons)

    tf_cases = (
        (None, 'tf_metadata_missing'),
        (dict(camera_tf, chain_valid=False), 'tf_chain_invalid'),
        (dict(camera_tf, source_frame='camera_depth_optical_frame'),
         'tf_frame_mismatch'),
        (dict(camera_tf, stamp_sec=101.0), 'tf_stamp_mismatch'),
        (dict(camera_tf, target_frame='base_link'), 'tf_not_applied'),
        (dict(camera_tf, mixed_tf=True), 'mixed_tf_forbidden'),
    )
    for tf_metadata, expected in tf_cases:
        reasons = adapter.validate_observation_contract(
            frame_id='camera_color_optical_frame', stamp_sec=100.0,
            object_class='trash_bin', confidence=0.8,
            projection=projection, tf_metadata=tf_metadata)
        assert expected in reasons, (tf_metadata, reasons)


def test_observation_id_is_deterministic_and_identity_bound():
    adapter = _load_ros1_module('ros1_adapter')
    arguments = {
        'stamp_sec': 100.25,
        'frame_id': 'camera_color_optical_frame',
        'object_class': 'plastic_bottle',
        'bbox': (10.0, 20.0, 30.0, 40.0),
        'status': 'valid',
        'model_binding_sha256': MODEL_BINDINGS[
            'plastic_bottle']['sha256'],
    }
    first = adapter.build_observation_id(**arguments)
    second = adapter.build_observation_id(**arguments)
    assert first == second
    assert isinstance(first, str)
    assert len(first) >= 32

    variants = {
        'stamp_sec': 100.26,
        'frame_id': 'base_link',
        'object_class': 'trash_bin',
        'bbox': (10.0, 20.0, 30.0, 41.0),
        'status': 'invalid',
        'model_binding_sha256': MODEL_BINDINGS['trash_bin']['sha256'],
    }
    for key, value in variants.items():
        changed = dict(arguments)
        changed[key] = value
        assert adapter.build_observation_id(**changed) != first

    invalid_cases = (
        dict(arguments, stamp_sec=math.nan),
        dict(arguments, frame_id=''),
        dict(arguments, object_class='unknown'),
        dict(arguments, bbox=(1.0, 2.0, 3.0)),
        dict(arguments, bbox=(1.0, 2.0, math.nan, 4.0)),
        dict(arguments, model_binding_sha256='0' * 63),
    )
    for invalid in invalid_cases:
        try:
            adapter.build_observation_id(**invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(
                'invalid observation identity was accepted: {!r}'.format(
                    invalid))


def test_field_readiness_requires_four_formal_live_audited_scenes():
    readiness = _load_ros1_module('perception_readiness')
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payload = _readiness_payload(root)
        result = readiness.assess_field_readiness(
            payload, artifact_root=root)

        # These are intentionally shallow legacy artifacts.  A production
        # readiness assessment must never treat their self-reported booleans
        # and counts as live-audited four-scene evidence.
        assert result['read_only'] is True
        assert result['authorizes_motion'] is False
        assert result['validated_pass'] is False
        assert result['formal_four_scene_pass'] is False
        assert result['formal_tf_3d_pass'] is False
        assert result['delivery_ready'] is False
        assert result['failures']

        no_live_audit = readiness.assess_field_readiness(payload)
        assert no_live_audit['read_only'] is True
        assert no_live_audit['authorizes_motion'] is False
        assert no_live_audit['validated_pass'] is False
        assert no_live_audit['formal_four_scene_pass'] is False
        assert no_live_audit['formal_tf_3d_pass'] is False
        assert no_live_audit['delivery_ready'] is False
        assert no_live_audit['failures']


def test_ros2_provenance_document_demotion_gate_is_task_scoped_and_fail_closed():
    from audit_tools import ros1_machine_contract_doc_demotion as doc_gate

    report = doc_gate.evaluate_machine_contract_docs(WORKSPACE)
    assert report['validated_pass'] is True, report['failures']
    assert report['failures'] == []
    assert report['gate_scope'] == (
        'TASK_SCOPED_NON_FORMAL_DOCUMENT_DEMOTION')
    assert report['contract_document_paths'] == [
        'docs/foxy_arm64_deployment.md']
    assert len(report['contract_document_records']) == 1
    assert len(report['source_declaration_records']) == 2
    assert all(
        record['value'] is False
        for record in report['source_declaration_records'])
    assert report['source_declaration_is_install_evidence'] is False
    assert report['document_demotion_clean'] is True
    assert report['shared_document_demotion_clean'] is True
    assert report[
        'predecessor_authority_v5_identity_and_internal_current_valid'] is True
    assert report['frozen_predecessor_authority_index_instance_id'] == (
        'ros1-formal-admission-evidence-authority-index-20260815-'
        'v5-blocked-offline')
    assert report['accepted_as_offline_release_selection_authority'] is False
    assert report['accepted_by_formal_field_evidence_consumer'] is False
    assert report['ros1_noetic_build_install_verified'] is False
    assert report['ros1_noetic_runtime_verified'] is False
    assert report['formal_four_scene_frame_denominator'] == 0
    assert report['formal_tf_pass'] is False
    assert report['formal_3d_pass'] is False
    assert report['formal_latency_pass'] is False
    assert report['authorizes_field_delivery'] is False
    assert report['delivery_ready'] is False


if __name__ == '__main__':
    import inspect

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(value)]
    for test in tests:
        test()
    print('{} ROS1 runtime source-contract tests passed'.format(len(tests)))
