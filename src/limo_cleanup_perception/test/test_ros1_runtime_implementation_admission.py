"""Host-owned ROS1 runtime implementation admission tests."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from limo_cleanup_perception import perception_readiness as READINESS


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'ros1_overlay_src/limo_cleanup_ros1_perception'
CONTRACT = PACKAGE / 'config/ros1_noetic_field_install_contract.json'


def contract_payload():
    return json.loads(CONTRACT.read_text(encoding='utf-8'))


def copy_package(directory):
    root = Path(directory)
    target = root / 'ros1_overlay_src/limo_cleanup_ros1_perception'
    shutil.copytree(str(PACKAGE), str(target))
    return root, target


def runtime_gate(package=PACKAGE, contract=None):
    return READINESS._audit_ros1_runtime_implementation_admission(
        Path(package), contract or contract_payload())


class Ros1RuntimeImplementationAdmissionTest(unittest.TestCase):

    def assert_blocked(self, report, prefix=None):
        self.assertFalse(report['validated_pass'], report)
        self.assertFalse(report['ros1_noetic_install_validated'])
        self.assertFalse(report['field_evidence_admitted'])
        self.assertFalse(report['authorizes_field_delivery'])
        self.assertFalse(report['delivery_ready'])
        self.assertIn(
            READINESS.ROS1_RUNTIME_IMPLEMENTATION_VALIDATION_BLOCKER,
            report['failures'])
        if prefix is not None:
            self.assertTrue(
                any(item.startswith(prefix) for item in report['failures']),
                report['failures'])

    def assert_behavior_blocked(self, report, failure):
        self.assertFalse(report['validated_pass'], report)
        self.assertIn(failure, report['failures'])
        self.assertFalse(report['ros_graph_started'])
        self.assertFalse(report['camera_opened'])
        self.assertFalse(report['hardware_connected'])
        self.assertFalse(report['authorizes_field_delivery'])
        self.assertFalse(report['delivery_ready'])

    def test_canonical_runtime_source_gate_passes_but_never_install_or_delivery(self):
        report = runtime_gate()
        self.assertTrue(report['validated_pass'], report['failures'])
        self.assertEqual(
            report['gate_id'],
            READINESS.ROS1_RUNTIME_IMPLEMENTATION_ADMISSION_GATE_ID)
        self.assertEqual(
            report['validated_component_count'],
            report['required_component_count'])
        self.assertFalse(report['capability_declarations_consulted'])
        self.assertFalse(report['capability_declarations_can_override'])
        self.assertTrue(report['closes_source_implementation_blocker_only'])
        self.assertFalse(report['ros1_noetic_install_validated'])
        self.assertFalse(report['field_evidence_admitted'])
        self.assertFalse(report['authorizes_field_delivery'])
        self.assertFalse(report['delivery_ready'])

    def test_implementation_validated_flip_is_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root, package = copy_package(directory)
            capability_path = package / 'config/capability_matrix.json'
            capability = json.loads(capability_path.read_text(encoding='utf-8'))
            results = []
            for value in (False, True):
                capability['implementation_validated'] = value
                capability_path.write_text(
                    json.dumps(capability, indent=2) + '\n', encoding='utf-8')
                with mock.patch.object(
                        READINESS, '_validate_ros1_source_core_binding',
                        return_value={
                            'validated_pass': True, 'failures': []}):
                    results.append(
                        READINESS.audit_ros1_noetic_field_source_contract(root))
            self.assertTrue(results[0]['pass'], results[0]['failures'])
            self.assertTrue(results[1]['pass'], results[1]['failures'])
            self.assertFalse(
                results[0]['capability_matrix_diagnostic'][
                    'authoritative_for_complete_runtime'])
            self.assertFalse(
                results[1]['capability_matrix_diagnostic'][
                    'authoritative_for_complete_runtime'])

    def test_all_true_capabilities_cannot_rescue_failed_runtime_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            capability_path = package / 'config/capability_matrix.json'
            capability = json.loads(capability_path.read_text(encoding='utf-8'))
            capability['implementation_validated'] = True
            capability['capabilities'] = {
                key: True for key in capability['capabilities']}
            capability_path.write_text(
                json.dumps(capability, indent=2) + '\n', encoding='utf-8')
            (package / 'src/limo_cleanup_ros1_perception/ros1_adapter.py').unlink()
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_invalid:runtime:ros1_adapter')

    def test_single_capability_true_cannot_rescue_failed_runtime_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            capability_path = package / 'config/capability_matrix.json'
            capability = json.loads(capability_path.read_text(encoding='utf-8'))
            capability['implementation_validated'] = True
            capability['capabilities'] = {
                key: False for key in capability['capabilities']}
            capability['capabilities']['dual_class_detection'] = True
            capability_path.write_text(
                json.dumps(capability, indent=2) + '\n', encoding='utf-8')
            (package / 'src/limo_cleanup_ros1_perception/dual_model_detector.py').unlink()
            self.assert_blocked(
                runtime_gate(package),
                'ros1_runtime_implementation_source_invalid:runtime:dual_model_detector')

    def test_comment_only_source_drift_fails_fixed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'src/limo_cleanup_ros1_perception/perception_core.py'
            path.write_text(
                path.read_text(encoding='utf-8') + '\n# drift\n',
                encoding='utf-8')
            self.assert_blocked(
                runtime_gate(package),
                'ros1_runtime_implementation_source_identity_mismatch:'
                'runtime:perception_core')

    def test_extra_control_publisher_is_rejected_by_identity_and_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'src/limo_cleanup_ros1_perception/ros1_adapter.py'
            source = path.read_text(encoding='utf-8')
            source += "\ndef _forbidden():\n    return rospy.Publisher('/cmd_vel', object)\n"
            path.write_text(source, encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'runtime:ros1_adapter')
            self.assertTrue(any(
                item.startswith('ros1_runtime_control_surface_forbidden:')
                for item in report['failures']), report['failures'])

    def test_launch_camera_include_is_rejected_by_identity_and_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'launch/perception_v2_readonly.launch'
            source = path.read_text(encoding='utf-8').replace(
                '</launch>',
                '<include file="$(find astra_camera)/launch/dabai_u3.launch"/>'
                '</launch>')
            path.write_text(source, encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'launch:perception_v2_readonly')
            self.assertIn('ros1_runtime_read_only_launch_invalid', report['failures'])
            self.assertIn(
                'ros1_runtime_launch_control_include_forbidden:astra_camera',
                report['failures'])

    def test_launch_remap_is_rejected_even_when_target_is_indirect(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'launch/perception_v2_readonly.launch'
            source = path.read_text(encoding='utf-8').replace(
                '  <node pkg="limo_cleanup_ros1_perception"',
                '  <arg name="unreviewed_output" default="/safe-looking"/>\n'
                '  <node pkg="limo_cleanup_ros1_perception"', 1).replace(
                    '  </node>',
                    '    <remap from="/cleanup/perception/frames" '
                    'to="$(arg unreviewed_output)"/>\n  </node>', 1)
            path.write_text(source, encoding='utf-8')

            report = runtime_gate(package)

            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'launch:perception_v2_readonly')
            self.assertIn(
                'ros1_runtime_read_only_launch_invalid', report['failures'])

    def test_launch_execution_override_attributes_are_rejected(self):
        mutations = (
            ('launch-prefix', 'launch-prefix="env"'),
            ('machine', 'machine="remote-host"'),
            ('args', 'args="--unexpected-runtime-mode"'),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, attribute in mutations:
                with self.subTest(attribute=name):
                    unused_root, package = copy_package(root / name)
                    path = package / 'launch/perception_v2_readonly.launch'
                    source = path.read_text(encoding='utf-8').replace(
                        '        output="screen"',
                        '        {}\n        output="screen"'.format(
                            attribute), 1)
                    path.write_text(source, encoding='utf-8')

                    report = runtime_gate(package)

                    self.assert_blocked(
                        report,
                        'ros1_runtime_implementation_source_identity_mismatch:'
                        'launch:perception_v2_readonly')
                    self.assertIn(
                        'ros1_runtime_read_only_launch_invalid',
                        report['failures'])

    def test_launch_exact_allowlist_rejects_reanchored_forbidden_xml(self):
        mutations = {
            'arg_env_substitution': (
                '<arg name="rgb_topic" default="/camera/color/image_raw"/>',
                '<arg name="rgb_topic" default="$(env LIMO_RGB_TOPIC)"/>'),
            'unknown_group_child': (
                '</launch>', '<group ns="unexpected"/>\n</launch>'),
            'nested_rosparam': (
                '  </node>', '    <rosparam command="load" file="x.yaml"/>\n'
                '  </node>'),
            'direct_env_remap': (
                '  </node>',
                '    <remap from="/cleanup/perception/frames" '
                'to="$(env LIMO_OUTPUT_TOPIC)"/>\n  </node>'),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (old, new) in mutations.items():
                with self.subTest(mutation=name):
                    unused_root, package = copy_package(root / name)
                    path = package / 'launch/perception_v2_readonly.launch'
                    source = path.read_text(encoding='utf-8').replace(
                        old, new, 1)
                    path.write_text(source, encoding='utf-8')
                    raw = path.read_bytes()
                    anchor = (
                        'launch/perception_v2_readonly.launch', len(raw),
                        hashlib.sha256(raw).hexdigest())
                    with mock.patch.dict(
                            READINESS.ROS1_RUNTIME_IMPLEMENTATION_ANCHORS,
                            {'launch:perception_v2_readonly': anchor}):
                        report = runtime_gate(package)
                    self.assert_blocked(
                        report, 'ros1_runtime_read_only_launch_invalid')
                    self.assertNotIn(
                        'ros1_runtime_implementation_source_identity_mismatch:'
                        'launch:perception_v2_readonly', report['failures'])

    def test_launch_doctype_or_entity_is_rejected_after_reanchor(self):
        declarations = (
            '<!DOCTYPE launch>\n',
            '<!DOCTYPE launch [<!ENTITY output "screen">]>\n',
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, declaration in enumerate(declarations):
                with self.subTest(declaration=index):
                    unused_root, package = copy_package(root / str(index))
                    path = package / 'launch/perception_v2_readonly.launch'
                    source = path.read_text(encoding='utf-8').replace(
                        '<launch>', declaration + '<launch>', 1)
                    path.write_text(source, encoding='utf-8')
                    raw = path.read_bytes()
                    anchor = (
                        'launch/perception_v2_readonly.launch', len(raw),
                        hashlib.sha256(raw).hexdigest())
                    with mock.patch.dict(
                            READINESS.ROS1_RUNTIME_IMPLEMENTATION_ANCHORS,
                            {'launch:perception_v2_readonly': anchor}):
                        report = runtime_gate(package)
                    self.assert_blocked(
                        report, 'ros1_runtime_read_only_launch_invalid')

    def test_formal_capture_launch_exact_join_contract_survives_reanchor(self):
        mutations = {
            'missing_task_arg': (
                '  <arg name="task_id"/>\n', ''),
            'missing_capture_arg': (
                '  <arg name="capture_id"/>\n', ''),
            'missing_task_param': (
                '    <param name="task_id" value="$(arg task_id)"/>\n', ''),
            'missing_capture_param': (
                '    <param name="capture_id" value="$(arg capture_id)"/>\n',
                ''),
            'missing_formal_mode': (
                '    <param name="formal_capture_mode" value="true"/>\n',
                ''),
            'formal_mode_default_attribute': (
                '<param name="formal_capture_mode" value="true"/>',
                '<param name="formal_capture_mode" default="true"/>'),
            'formal_mode_false': (
                '<param name="formal_capture_mode" value="true"/>',
                '<param name="formal_capture_mode" value="false"/>'),
            'task_default': (
                '<arg name="task_id"/>',
                '<arg name="task_id" default="forged-task"/>'),
            'capture_default': (
                '<arg name="capture_id"/>',
                '<arg name="capture_id" default="reused-capture"/>'),
            'remap': (
                '  </node>',
                '    <remap from="/cleanup/perception/frames" '
                'to="/unreviewed"/>\n  </node>'),
            'include': (
                '</launch>',
                '  <include file="$(find astra_camera)/launch/'
                'dabai_u3.launch"/>\n</launch>'),
            'group': (
                '</launch>', '  <group ns="unexpected"/>\n</launch>'),
            'env_substitution': (
                'default="/camera/color/image_raw"',
                'default="$(env LIMO_RGB_TOPIC)"'),
            'entity': (
                '<launch>',
                '<!DOCTYPE launch [<!ENTITY task "forged">]>\n<launch>'),
            'extra_node': (
                '</launch>',
                '  <node pkg="limo_cleanup_ros1_perception" '
                'type="dual_model_detector.py" name="duplicate"/>\n'
                '</launch>'),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (old, new) in mutations.items():
                with self.subTest(mutation=name):
                    unused_root, package = copy_package(root / name)
                    path = (
                        package / 'launch/perception_v2_formal_capture.launch')
                    source = path.read_text(encoding='utf-8')
                    self.assertIn(old, source)
                    path.write_text(
                        source.replace(old, new, 1), encoding='utf-8')
                    raw = path.read_bytes()
                    anchor = (
                        'launch/perception_v2_formal_capture.launch',
                        len(raw), hashlib.sha256(raw).hexdigest())
                    with mock.patch.dict(
                            READINESS.ROS1_RUNTIME_IMPLEMENTATION_ANCHORS,
                            {'launch:perception_v2_formal_capture': anchor}):
                        report = runtime_gate(package)
                    self.assert_blocked(
                        report,
                        'ros1_runtime_formal_capture_launch_invalid')
                    self.assertNotIn(
                        'ros1_runtime_implementation_source_identity_mismatch:'
                        'launch:perception_v2_formal_capture',
                        report['failures'])

    def test_formal_capture_launch_is_an_independent_required_anchor(self):
        role = 'launch:perception_v2_formal_capture'
        self.assertIn(role, READINESS.ROS1_RUNTIME_IMPLEMENTATION_ANCHORS)
        relative, size_bytes, sha256 = (
            READINESS.ROS1_RUNTIME_IMPLEMENTATION_ANCHORS[role])
        path = PACKAGE / relative
        raw = path.read_bytes()
        self.assertEqual('launch/perception_v2_formal_capture.launch', relative)
        self.assertEqual(len(raw), size_bytes)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sha256)
        report = runtime_gate()
        self.assertNotIn(
            'ros1_runtime_implementation_source_invalid:' + role,
            report['failures'])
        self.assertNotIn(
            'ros1_runtime_implementation_source_identity_mismatch:' + role,
            report['failures'])
        self.assertNotIn(
            'ros1_runtime_formal_capture_launch_invalid', report['failures'])

    def test_evidence_binding_is_required_and_identity_anchored(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = (
                package / 'src/limo_cleanup_ros1_perception/'
                'evidence_binding.py')
            path.unlink()
            self.assert_blocked(
                runtime_gate(package),
                'ros1_runtime_implementation_source_invalid:'
                'runtime:evidence_binding')

        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = (
                package / 'src/limo_cleanup_ros1_perception/'
                'evidence_binding.py')
            path.write_text(
                path.read_text(encoding='utf-8').replace(
                    'def canonical_file_manifest(',
                    'def hijacked_canonical_file_manifest(', 1),
                encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'runtime:evidence_binding')
            self.assertIn(
                'ros1_runtime_component_ast_surface_invalid:'
                'runtime:evidence_binding', report['failures'])

    def test_read_only_output_contract_cannot_enable_control(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'config/read_only_output_contract.json'
            output = json.loads(path.read_text(encoding='utf-8'))
            output['control_publishers_allowed'] = True
            path.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'contract:read_only_output')
            self.assertIn(
                'ros1_runtime_read_only_output_contract_invalid',
                report['failures'])

    def test_dependency_pin_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'setup.py'
            path.write_text(
                path.read_text(encoding='utf-8').replace(
                    'torch==2.1.0a0+41361538.nv23.06', 'torch==9.9.9'),
                encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:build:setup')
            self.assertIn(
                'ros1_runtime_dependency_source_pins_invalid',
                report['failures'])

    def test_bare_python_distribution_rosdep_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'package.xml'
            source = path.read_text(encoding='utf-8').replace(
                '</package>', '  <exec_depend>ultralytics</exec_depend>\n</package>')
            path.write_text(source, encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'build:package_xml')
            self.assertIn(
                'ros1_runtime_dependency_rosdep_claim_forbidden:ultralytics',
                report['failures'])

    def test_model_contract_import_expansion_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'src/limo_cleanup_ros1_perception/model_binding_contract.py'
            path.write_text(
                path.read_text(encoding='utf-8') + '\nimport numpy\n',
                encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'runtime:model_contract')
            self.assertIn(
                'ros1_runtime_model_contract_imports_invalid', report['failures'])

    def test_wrong_entrypoint_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            unused_root, package = copy_package(directory)
            path = package / 'scripts/perception_frame_adapter.py'
            path.write_text(
                path.read_text(encoding='utf-8').replace(
                    'limo_cleanup_ros1_perception.ros1_adapter',
                    'limo_cleanup_ros1_perception.dual_model_detector'),
                encoding='utf-8')
            report = runtime_gate(package)
            self.assert_blocked(
                report,
                'ros1_runtime_implementation_source_identity_mismatch:'
                'entry:perception_frame_adapter')
            self.assertIn(
                'ros1_runtime_entrypoint_ast_invalid:perception_frame_adapter',
                report['failures'])

    def test_linklike_component_fails_closed_without_importing_runtime(self):
        original = READINESS._path_is_linklike

        def linked(path):
            if Path(path).name == 'ros1_adapter.py':
                return True
            return original(Path(path))

        with mock.patch.object(
                READINESS, '_path_is_linklike', side_effect=linked):
            self.assert_blocked(
                runtime_gate(),
                'ros1_runtime_implementation_source_invalid:runtime:ros1_adapter')

    def test_behavior_test_identity_drift_fails_before_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            relative = Path(
                READINESS.ROS1_RUNTIME_BEHAVIOR_TEST_ANCHOR['relative_path'])
            drifted_test = workspace / relative
            drifted_test.parent.mkdir(parents=True)
            drifted_test.write_text(
                '# intentionally drifted behavior test\n', encoding='utf-8')
            with mock.patch.object(
                    READINESS, '_perception_workspace_root',
                    return_value=workspace), mock.patch.object(
                        READINESS.subprocess, 'run') as run:
                report = READINESS._run_ros1_runtime_behavior_admission(PACKAGE)
            run.assert_not_called()
            self.assert_behavior_blocked(
                report, 'ros1_runtime_behavior_test_identity_mismatch')

    def test_behavior_subprocess_result_anomalies_fail_closed(self):
        expected = {
            'tests_run':
                READINESS.ROS1_RUNTIME_BEHAVIOR_TEST_ANCHOR[
                    'expected_test_count'],
            'failures': 0,
            'errors': 0,
            'skipped': 0,
            'expected_failures': 0,
            'unexpected_successes': 0,
            'successful': True,
        }
        cases = []
        failed_result = dict(expected)
        failed_result.update({'failures': 1, 'successful': False})
        cases.append((
            'reported_failure', 0,
            ('LIMO_RUNTIME_BEHAVIOR_RESULT='
             + json.dumps(failed_result, sort_keys=True) + '\n').encode()))
        cases.append((
            'nonzero_exit', 1,
            ('LIMO_RUNTIME_BEHAVIOR_RESULT='
             + json.dumps(expected, sort_keys=True) + '\n').encode()))
        cases.append((
            'wrong_marker', 0,
            ('WRONG_RUNTIME_BEHAVIOR_RESULT='
             + json.dumps(expected, sort_keys=True) + '\n').encode()))

        for name, returncode, stdout in cases:
            with self.subTest(name=name), mock.patch.object(
                    READINESS.subprocess, 'run', return_value=mock.Mock(
                        returncode=returncode, stdout=stdout, stderr=b'')):
                report = READINESS._run_ros1_runtime_behavior_admission(PACKAGE)
            self.assert_behavior_blocked(
                report, 'ros1_runtime_behavior_tests_failed')


if __name__ == '__main__':
    unittest.main()
