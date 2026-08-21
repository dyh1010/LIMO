"""Pure-software ROS1 runtime, install, and read-only source checks."""

import ast
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = 'limo_cleanup_ros1_perception'
CONTRACT_PATH = (
    PACKAGE_ROOT / 'config' / 'ros1_noetic_field_install_contract.json')
FORBIDDEN_CONTROL_TOKENS = (
    'cmd_vel', 'move_base', 'navigation_goal', 'follow_joint_trajectory',
    'gripper_command', 'geometry_msgs/Twist', 'actionlib.SimpleActionClient',
)


def _strict_json(path):
    def reject_constant(value):
        raise ValueError('non-finite constant: ' + value)

    def reject_duplicates(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate key: ' + key)
            value[key] = item
        return value

    return json.loads(
        Path(path).read_text(encoding='utf-8'),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates)


def _setup_install_requires():
    tree = ast.parse(
        (PACKAGE_ROOT / 'setup.py').read_text(encoding='utf-8'),
        filename='setup.py')
    values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Subscript):
            continue
        if not isinstance(target.value, ast.Name):
            continue
        if target.value.id != 'package_args':
            continue
        try:
            # Python 3.8 exposes subscript keys through ast.Index, while
            # newer interpreters expose the value node directly.
            slice_node = target.slice
            if isinstance(slice_node, ast.Index):
                slice_node = slice_node.value
            key = ast.literal_eval(slice_node)
        except (ValueError, TypeError):
            continue
        if key == 'install_requires':
            values.append(ast.literal_eval(node.value))
    if len(values) != 1:
        raise AssertionError('setup.py must define one literal install_requires')
    return values[0]


class RuntimeInstallContractTest(unittest.TestCase):

    def setUp(self):
        self.contract = _strict_json(CONTRACT_PATH)

    def test_runtime_dependency_lock_is_exact_and_not_install_proof(self):
        lock = self.contract['python_runtime_dependency_lock']
        self.assertEqual(
            'ROS1_NOETIC_PERCEPTION_PYTHON_RUNTIME_V1', lock['lock_id'])
        self.assertEqual({
            'authority': 'latest_verified_limo_jetson_runtime',
            'source_path': 'docs/foxy_arm64_deployment.md',
            'source_scope': 'verified_arm64_runtime_versions',
            'source_declaration_is_install_evidence': False,
        }, lock['version_provenance'])
        self.assertEqual({
            'declaration_path': 'setup.py',
            'exact_pins_required': True,
            'rosdep_claim_forbidden': True,
            'source_declaration_is_install_evidence': False,
        }, lock['source_policy'])
        self.assertEqual({
            'distribution_artifact_identity_required': True,
            'distribution_metadata_required': True,
            'fresh_isolated_import_probe_required': True,
            'module_origin_required': True,
            'reported_distribution_version_required': True,
            'reported_module_version_required': True,
            'runtime_provisioning_required': True,
            'regular_files_only': True,
            'linklike_forbidden': True,
        }, lock['install_evidence_policy'])
        expected = [
            ('numpy', 'numpy', '1.23.4', 'numpy==1.23.4'),
            ('torch', 'torch', '2.1.0a0+41361538.nv23.06',
             'torch==2.1.0a0+41361538.nv23.06'),
            ('ultralytics', 'ultralytics', '8.3.21',
             'ultralytics==8.3.21'),
        ]
        actual = [
            (item['distribution'], item['import_name'],
             item['exact_version'], item['requirement'])
            for item in lock['requirements']]
        self.assertEqual(expected, actual)
        self.assertTrue(all(
            item['provisioning_policy']
            == 'isolated_offline_artifact_exact_version'
            and item['distribution_artifact_provenance_policy']
            == 'required_field_install_artifact_identity'
            and item['distribution_artifact_format'] == 'wheel'
            for item in lock['requirements']))
        self.assertEqual({
            'numpy': 'isolated_offline_wheel_artifact',
            'torch': 'isolated_jetson_vendor_wheel_artifact',
            'ultralytics': 'isolated_offline_wheel_artifact',
        }, {
            item['distribution']: item['deployment_source']
            for item in lock['requirements']})
        self.assertEqual(
            [item[3] for item in expected], _setup_install_requires())

        package_xml = ET.parse(str(PACKAGE_ROOT / 'package.xml')).getroot()
        ros_dependencies = {
            (node.text or '').strip()
            for tag in ('depend', 'build_depend', 'exec_depend')
            for node in package_xml.findall(tag)}
        self.assertTrue({'numpy', 'torch', 'ultralytics'}.isdisjoint(
            ros_dependencies))
        actual_dependency_tags = {
            tag: [(node.text or '').strip() for node in package_xml.findall(tag)]
            for tag in self.contract['package']['dependency_tags']}
        self.assertEqual(
            self.contract['package']['dependency_tags'], actual_dependency_tags)

    def test_required_runtime_source_inventory_is_complete(self):
        modules = self.contract['required_python_modules']
        self.assertIn('image_conversion.py', modules)
        self.assertEqual(
            [
                'perception_v2_formal_capture.launch',
                'perception_v2_readonly.launch',
            ],
            self.contract['required_launch_files'])
        self.assertEqual([
            'test_rosbag1_isolated_probe.py',
            'test_rosbag1_rgbd_indexer.py',
            'test_ros1_adapter_pure_fake.py',
            'test_runtime_install_contract.py',
        ], self.contract['required_catkin_test_files'])
        package_python = PACKAGE_ROOT / 'src' / PACKAGE_NAME
        for name in modules:
            path = package_python / name
            self.assertTrue(path.is_file(), str(path))
            self.assertFalse(path.is_symlink(), str(path))
        for name in self.contract['required_launch_files']:
            path = PACKAGE_ROOT / 'launch' / name
            self.assertTrue(path.is_file(), str(path))
            self.assertFalse(path.is_symlink(), str(path))
        for name in self.contract['required_catkin_test_files']:
            path = PACKAGE_ROOT / 'test' / name
            self.assertTrue(path.is_file(), str(path))
            self.assertFalse(path.is_symlink(), str(path))

    def test_entrypoints_are_exact_read_only_wrappers(self):
        expected_targets = {
            'dual_model_detector': (
                'limo_cleanup_ros1_perception.dual_model_detector'),
            'perception_frame_adapter': (
                'limo_cleanup_ros1_perception.ros1_adapter'),
            'perception_frame_collector': (
                'limo_cleanup_ros1_perception.perception_frame_collector'),
            'perception_readiness': (
                'limo_cleanup_ros1_perception.perception_readiness'),
            'rosbag1_rgbd_indexer': (
                'limo_cleanup_ros1_perception.rosbag1_rgbd_indexer'),
            'typed_raw_binding': (
                'limo_cleanup_ros1_perception.typed_raw_binding'),
        }
        self.assertEqual(
            set(expected_targets), set(self.contract['required_entrypoints']))
        for role, relative in self.contract['required_entrypoints'].items():
            path = PACKAGE_ROOT / relative
            source = path.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=relative)
            imports = [
                node for node in tree.body if isinstance(node, ast.ImportFrom)]
            self.assertEqual(1, len(imports), relative)
            self.assertEqual(expected_targets[role], imports[0].module)
            self.assertEqual(['main'], [item.name for item in imports[0].names])
            self.assertTrue(source.startswith('#!/usr/bin/env python3\n'))
            self.assertFalse(any(token in source
                                 for token in FORBIDDEN_CONTROL_TOKENS))

    def test_config_and_launch_are_strict_read_only_assets(self):
        for name in self.contract['required_config_files']:
            payload = _strict_json(PACKAGE_ROOT / 'config' / name)
            self.assertIsInstance(payload, dict, name)
        for name in self.contract['required_fixture_files']:
            payload = _strict_json(PACKAGE_ROOT / 'fixtures' / name)
            self.assertIsInstance(payload, dict, name)

        launch_roots = {}
        for name in self.contract['required_launch_files']:
            launch_path = PACKAGE_ROOT / 'launch' / name
            source = launch_path.read_text(encoding='utf-8')
            root = ET.fromstring(source)
            launch_roots[name] = root
            self.assertEqual('launch', root.tag, name)
            self.assertEqual([], root.findall('include'), name)
            self.assertEqual([], root.findall('remap'), name)
            nodes = root.findall('node')
            self.assertEqual(1, len(nodes), name)
            self.assertEqual(PACKAGE_NAME, nodes[0].get('pkg'), name)
            self.assertEqual('dual_model_detector.py', nodes[0].get('type'), name)
            self.assertFalse(any(token in source
                                 for token in FORBIDDEN_CONTROL_TOKENS), name)

        formal_root = launch_roots['perception_v2_formal_capture.launch']
        formal_args = {
            item.get('name'): item for item in formal_root.findall('arg')}
        self.assertEqual(
            {'rgb_topic', 'depth_topic', 'rgb_camera_info_topic',
             'depth_camera_info_topic', 'model_manifest', 'task_id',
             'capture_id'}, set(formal_args))
        self.assertNotIn('default', formal_args['task_id'].attrib)
        self.assertNotIn('default', formal_args['capture_id'].attrib)
        formal_node = formal_root.findall('node')[0]
        formal_params = {
            item.get('name'): item.get('value')
            for item in formal_node.findall('param')}
        self.assertEqual(15, len(formal_params))
        self.assertEqual('true', formal_params['formal_capture_mode'])
        self.assertEqual('$(arg task_id)', formal_params['task_id'])
        self.assertEqual('$(arg capture_id)', formal_params['capture_id'])

        readonly_root = launch_roots['perception_v2_readonly.launch']
        self.assertNotIn(
            'task_id', {item.get('name') for item in readonly_root.findall('arg')})
        self.assertNotIn(
            'capture_id',
            {item.get('name') for item in readonly_root.findall('arg')})

        cmake = (PACKAGE_ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
        for name in self.contract['required_launch_files']:
            self.assertIn('    launch/' + name, cmake)
        self.assertNotIn('DIRECTORY launch/', cmake)

    def test_generated_message_contract_matches_adapter_fields(self):
        expected = {
            'ObjectDetection.msg': {
                'time stamp', 'string detection_id', 'string task_id',
                'string object_class', 'float32 confidence',
                'string frame_id', 'geometry_msgs/Point position',
                'geometry_msgs/Vector3 size',
            },
            'PerceptionFrame.msg': {
                'time stamp', 'string frame_id', 'string task_id',
                'uint32 sequence', 'string capture_id', 'string bundle_id',
                'string model_binding_sha256', 'string tf_target_frame',
                'bool tf_valid', 'bool tf_transform_applied',
                'string tf_status', 'string tf_error_code', 'bool valid',
                'string status', 'string error_code',
                'float32 sync_span_sec', 'float32 processing_latency_sec',
                (PACKAGE_NAME + '/PerceptionTarget[] targets'),
            },
            'PerceptionTarget.msg': {
                'string observation_id', 'string object_class',
                'float32 confidence', 'bool valid', 'bool actionable',
                'string status', 'string error_code',
                'geometry_msgs/Point position',
                'geometry_msgs/Vector3 size', 'float32 bbox_x1',
                'float32 bbox_y1', 'float32 bbox_x2', 'float32 bbox_y2',
                'float32 depth_m', 'uint32 depth_valid_pixels',
                'uint32 depth_total_pixels', 'float32 depth_valid_ratio',
                'string source', 'string position_semantics',
            },
        }
        for name, fields in expected.items():
            actual = {
                line.strip()
                for line in (PACKAGE_ROOT / 'msg' / name).read_text(
                    encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#')}
            self.assertEqual(fields, actual, name)
        cmake = (PACKAGE_ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
        self.assertIn('add_message_files(', cmake)
        self.assertIn('generate_messages(', cmake)

    def test_python_import_surface_has_no_ros2_or_control_chain(self):
        forbidden_import_roots = {
            'rclpy', 'ament_cmake', 'ament_python', 'rosidl_runtime_py'}
        package_python = PACKAGE_ROOT / 'src' / PACKAGE_NAME
        for name in self.contract['required_python_modules']:
            path = package_python / name
            source = path.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=name)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(item.name.split('.')[0]
                                    for item in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split('.')[0])
            self.assertTrue(forbidden_import_roots.isdisjoint(imported), name)
            self.assertFalse(any(token in source
                                 for token in FORBIDDEN_CONTROL_TOKENS), name)


if __name__ == '__main__':
    unittest.main()
