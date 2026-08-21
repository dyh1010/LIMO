"""Pure-software trust-root tests for ROS1 V2 perception admission."""

import copy
import importlib.machinery
import importlib.util
import json
import shutil
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


WORKSPACE = Path(__file__).resolve().parents[3]
HOST_PYTHON = WORKSPACE / 'src' / 'limo_cleanup_perception'
if str(HOST_PYTHON) not in sys.path:
    sys.path.insert(0, str(HOST_PYTHON))

from limo_cleanup_perception import perception_readiness as readiness
from limo_cleanup_perception import ros1_source_core_admission as admission


OVERLAY = (
    WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception')
MODEL_MANIFEST = OVERLAY / 'config' / 'model_bindings.json'
EXPECTED_MODELS = {
    'plastic_bottle': {
        'class_name': 'plastic_bottle',
        'filename': 'nongfu_yolov8n_best.pt',
        'deployment_path': (
            '/home/agilex/limo_cleanup_ws/models/'
            'nongfu_yolov8n_best.pt'),
        'size_bytes': 6244778,
        'sha256': readiness.EXPECTED_MODEL_SHA256['plastic_bottle'],
        'backend': 'ultralytics-yolo-pt',
    },
    'trash_bin': {
        'class_name': 'trash_bin',
        'filename': 'trash_bin_yolov8n_best.pt',
        'deployment_path': (
            '/home/agilex/limo_cleanup_ws/models/'
            'trash_bin_yolov8n_best.pt'),
        'size_bytes': 6231338,
        'sha256': readiness.EXPECTED_MODEL_SHA256['trash_bin'],
        'backend': 'ultralytics-yolo-pt',
    },
}


def _copy_file(source_root, target_root, relative):
    source = Path(source_root) / relative
    target = Path(target_root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_binding_workspace(directory):
    target = Path(directory) / 'workspace'
    paths = {admission.MANIFEST_RELATIVE, admission.VALIDATOR_RELATIVE,
             admission.BEHAVIOR_TEST_RELATIVE}
    for spec in admission.REQUIRED_PAIR_SPECS:
        paths.add(spec['host_relative_path'])
        paths.add(spec['ros1_relative_path'])
    for relative in sorted(paths):
        _copy_file(WORKSPACE, target, relative)
    return target


def _copy_overlay(directory):
    target = Path(directory) / 'limo_cleanup_ros1_perception'
    shutil.copytree(
        OVERLAY, target,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    return target


def _load_package_validator(workspace):
    path = Path(workspace) / admission.VALIDATOR_RELATIVE
    name = '_ros1_source_core_binding_diagnostic_test'
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourceIntegrityTrustRootTest(unittest.TestCase):
    def test_host_admission_passes_without_executing_package_validator(self):
        result = admission.validate_ros1_source_core_admission(WORKSPACE)
        self.assertTrue(result['validated_pass'], result['failures'])
        self.assertEqual([], result['failures'])
        self.assertFalse(result['package_validator_executed'])
        self.assertFalse(result['package_validator_return_value_trusted'])
        self.assertEqual(7, result['pair_count'])
        self.assertEqual(
            admission.MANIFEST_ANCHOR, result['manifest_anchor'])
        self.assertEqual(
            admission.VALIDATOR_ANCHOR, result['validator_anchor'])

        diagnostic = _load_package_validator(WORKSPACE)
        report = diagnostic.validate_source_core_binding(WORKSPACE)
        self.assertTrue(report['validated_pass'], report['failures'])
        expected = (WORKSPACE / admission.MANIFEST_RELATIVE).resolve()
        self.assertEqual(expected, Path(report['manifest_path']).resolve())
        self.assertEqual(
            admission.MANIFEST_RELATIVE,
            report['manifest_identity']['path'])

    def test_fake_exact_shape_pass_validator_and_wrong_paths_are_rejected(self):
        with TemporaryDirectory() as directory:
            workspace = _copy_binding_workspace(directory)
            validator = workspace / admission.VALIDATOR_RELATIVE
            validator.write_text(
                "def validate_source_core_binding(workspace):\n"
                "    return {\n"
                "        'gate_id': 'ROS1_SOURCE_CORE_BINDING',\n"
                "        'validated_pass': True,\n"
                "        'algorithm_id': "
                + repr(admission.ALGORITHM_ID) + ",\n"
                "        'required_pair_ids': "
                + repr(list(admission.REQUIRED_PAIR_IDS)) + ",\n"
                "        'pair_count': 7,\n"
                "        'manifest_path': 'wrong/foreign.json',\n"
                "        'manifest_identity': {\n"
                "            'path': 'wrong/foreign.json',\n"
                "            'size_bytes': 1, 'raw_sha256': '0' * 64},\n"
                "        'failures': []}\n",
                encoding='utf-8')
            fake = _load_package_validator(workspace)
            self.assertTrue(fake.validate_source_core_binding(
                workspace)['validated_pass'])
            result = admission.validate_ros1_source_core_admission(workspace)
            self.assertFalse(result['validated_pass'])
            self.assertFalse(result['package_validator_executed'])
            self.assertTrue(any(
                item.startswith(
                    'ros1_source_core_admission_validator_anchor_mismatch:')
                for item in result['failures']))

    def test_validator_byte_or_semantic_drift_fails_fixed_anchor(self):
        with TemporaryDirectory() as directory:
            workspace = _copy_binding_workspace(directory)
            validator = workspace / admission.VALIDATOR_RELATIVE
            validator.write_text(
                validator.read_text(encoding='utf-8')
                + '\n# self-reported hash updated\n', encoding='utf-8')
            result = admission.validate_ros1_source_core_admission(workspace)
            self.assertFalse(result['validated_pass'])
            self.assertIn(
                'ros1_source_core_admission_validator_anchor_mismatch:'
                'size_bytes', result['failures'])
            self.assertIn(
                'ros1_source_core_admission_validator_anchor_mismatch:sha256',
                result['failures'])

    def test_manifest_and_validator_co_tamper_cannot_move_host_anchor(self):
        with TemporaryDirectory() as directory:
            workspace = _copy_binding_workspace(directory)
            for relative in (
                    admission.REQUIRED_PAIR_SPECS[0]['host_relative_path'],
                    admission.REQUIRED_PAIR_SPECS[0]['ros1_relative_path']):
                path = workspace / relative
                path.write_text(
                    path.read_text(encoding='utf-8')
                    + '\nBOUND_ATTACK_VALUE = 1\n', encoding='utf-8')
            self_consistent = admission.make_live_source_core_manifest(
                workspace)
            manifest = workspace / admission.MANIFEST_RELATIVE
            manifest.write_text(
                json.dumps(
                    self_consistent, ensure_ascii=False, indent=2,
                    sort_keys=True) + '\n', encoding='utf-8')
            validator = workspace / admission.VALIDATOR_RELATIVE
            validator.write_text(
                "def validate_source_core_binding(workspace):\n"
                "    return {'validated_pass': True, 'failures': []}\n",
                encoding='utf-8')
            result = admission.validate_ros1_source_core_admission(workspace)
            self.assertFalse(result['validated_pass'])
            self.assertIn(
                'ros1_source_core_admission_manifest_anchor_mismatch:sha256',
                result['failures'])
            self.assertIn(
                'ros1_source_core_admission_validator_anchor_mismatch:sha256',
                result['failures'])

    def test_host_ros1_and_behavior_test_drift_each_fail_closed(self):
        cases = (
            admission.REQUIRED_PAIR_SPECS[0]['host_relative_path'],
            admission.REQUIRED_PAIR_SPECS[0]['ros1_relative_path'],
            admission.BEHAVIOR_TEST_RELATIVE,
        )
        for index, relative in enumerate(cases):
            with self.subTest(relative=relative), TemporaryDirectory() as root:
                workspace = _copy_binding_workspace(
                    Path(root) / str(index))
                path = workspace / relative
                path.write_text(
                    path.read_text(encoding='utf-8')
                    + '\ndef trust_root_drift_probe():\n    return 1\n',
                    encoding='utf-8')
                result = admission.validate_ros1_source_core_admission(
                    workspace)
                self.assertFalse(result['validated_pass'])
                self.assertTrue(any(
                    'semantic_mismatch' in item
                    or 'live_binding_mismatch' in item
                    for item in result['failures']), result['failures'])

    def test_algorithm_pair_set_and_declared_path_expansion_fail_closed(self):
        mutations = ('algorithm', 'pair', 'path')
        for mutation in mutations:
            with self.subTest(mutation=mutation), TemporaryDirectory() as root:
                workspace = _copy_binding_workspace(root)
                path = workspace / admission.MANIFEST_RELATIVE
                payload = json.loads(path.read_text(encoding='utf-8'))
                if mutation == 'algorithm':
                    payload['algorithm']['package_name_replacements'].append({
                        'from': 'foreign', 'to': 'trusted'})
                elif mutation == 'pair':
                    payload['required_pair_ids'].append('foreign_pair')
                    payload['pairs'].append(copy.deepcopy(payload['pairs'][0]))
                    payload['pairs'][-1]['pair_id'] = 'foreign_pair'
                else:
                    payload['pairs'][0]['host']['path'] = (
                        'src/foreign/evidence_binding.py')
                path.write_text(
                    json.dumps(payload, sort_keys=True) + '\n',
                    encoding='utf-8')
                result = admission.validate_ros1_source_core_admission(
                    workspace)
                self.assertFalse(result['validated_pass'])
                self.assertIn(
                    'ros1_source_core_admission_manifest_anchor_mismatch:'
                    'sha256', result['failures'])
                expected = {
                    'algorithm': (
                        'ros1_source_core_admission_algorithm_invalid'),
                    'pair': (
                        'ros1_source_core_admission_required_pairs_invalid'),
                    'path': (
                        'ros1_source_core_admission_declared_path_invalid:'
                        'evidence_binding:host'),
                }[mutation]
                self.assertIn(expected, result['failures'])

    def test_model_contract_exact_anchor_and_stdlib_surface_pass(self):
        result = readiness._validate_ros1_model_loader(
            OVERLAY, MODEL_MANIFEST, EXPECTED_MODELS)
        self.assertTrue(result['validated_pass'], result['failures'])
        self.assertEqual([], result['failures'])
        self.assertEqual(1, len(result['module_provenance']))
        self.assertEqual(
            list(readiness.ROS1_MODEL_BINDING_CONTRACT_ALLOWED_IMPORTS),
            result['contract_imports'])
        self.assertFalse(result['detector_module_executed'])
        self.assertFalse(result['target_contract_executed'])
        self.assertFalse(result['numpy_required_by_gate'])
        self.assertFalse(result['backend_initialized'])
        self.assertEqual(
            ['plastic_bottle', 'trash_bin'], result['classes'])
        self.assertTrue(result['environment_restored'])

    def test_fake_numpy_and_ros1_modules_are_ignored_and_restored(self):
        names = (
            'numpy', 'limo_cleanup_ros1_perception',
            'limo_cleanup_ros1_perception.target_contract',
            'limo_cleanup_ros1_perception.model_binding_contract',
            'limo_cleanup_ros1_perception.dual_model_detector')
        missing = object()
        saved = {name: sys.modules.get(name, missing) for name in names}
        fakes = {name: types.ModuleType(name) for name in names}
        try:
            sys.modules.update(fakes)
            result = readiness._validate_ros1_model_loader(
                OVERLAY, MODEL_MANIFEST, EXPECTED_MODELS)
            self.assertTrue(result['validated_pass'], result['failures'])
            for name in names:
                self.assertIs(fakes[name], sys.modules[name])
            self.assertTrue(result['host_owned_manifest_parser'])
            self.assertFalse(result['candidate_contract_executed'])
            self.assertFalse(result['candidate_contract_return_value_trusted'])
            self.assertTrue(result['environment_restored'])
        finally:
            for name, value in saved.items():
                if value is missing:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value

    def test_fake_stdlib_modules_fail_identity_without_execution(self):
        names = ('json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing')
        missing = object()
        for name in names:
            with self.subTest(module=name):
                saved = sys.modules.get(name, missing)
                calls = []
                fake = types.ModuleType(name)

                def invoked(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise AssertionError('fake stdlib module executed')

                fake.loads = invoked
                fake.sha256 = invoked
                fake.lstat = invoked
                fake.dataclass = invoked
                fake.Path = invoked
                fake.Mapping = invoked
                sys.modules[name] = fake
                try:
                    result = readiness._validate_ros1_model_loader(
                        OVERLAY, MODEL_MANIFEST, EXPECTED_MODELS)
                    self.assertFalse(result['validated_pass'])
                    self.assertEqual([], calls)
                    self.assertIn(
                        'ros1_field_model_loader_ambient_stdlib_'
                        'identity_mismatch:' + name,
                        result['failures'])
                    self.assertFalse(result['candidate_contract_executed'])
                    self.assertFalse(
                        result['candidate_contract_return_value_trusted'])
                    self.assertTrue(result['host_owned_manifest_parser'])
                    self.assertTrue(result['environment_restored'])
                    self.assertIs(fake, sys.modules[name])
                finally:
                    if saved is missing:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = saved

    def test_non_json_manifest_fails_without_calling_fake_json(self):
        with TemporaryDirectory() as directory:
            package = _copy_overlay(directory)
            manifest = package / 'config/model_bindings.json'
            manifest.write_text('this is not JSON\n', encoding='utf-8')
            missing = object()
            saved = sys.modules.get('json', missing)
            calls = []
            fake = types.ModuleType('json')

            def fake_loads(*args, **kwargs):
                calls.append((args, kwargs))
                return {'models': EXPECTED_MODELS}

            fake.loads = fake_loads
            sys.modules['json'] = fake
            try:
                result = readiness._validate_ros1_model_loader(
                    package, manifest, EXPECTED_MODELS)
                self.assertFalse(result['validated_pass'])
                self.assertEqual([], calls)
                self.assertIs(fake, sys.modules['json'])
                self.assertIn(
                    'ros1_field_model_loader_ambient_stdlib_'
                    'identity_mismatch:json', result['failures'])
                self.assertTrue(result['environment_restored'])
                self.assertFalse(result['candidate_contract_executed'])
                self.assertFalse(
                    result['candidate_contract_return_value_trusted'])
                # Ambient dependency identity is an earlier trust gate than
                # manifest parsing.  A polluted entry must return before even
                # attempting to classify malformed manifest bytes.
                self.assertFalse(any(
                    item.startswith(
                        'ros1_field_model_binding_manifest_invalid:')
                    for item in result['failures']))
                self.assertIsNone(result['manifest_identity'])
            finally:
                if saved is missing:
                    sys.modules.pop('json', None)
                else:
                    sys.modules['json'] = saved

    def test_fake_meta_finder_and_stale_package_path_are_never_used(self):
        calls = []

        class FakeFinder:
            def find_spec(self, fullname, path=None, target=None):
                calls.append(fullname)
                raise AssertionError('ambient finder must be isolated')

        with TemporaryDirectory() as directory:
            stale = Path(directory)
            package = stale / 'limo_cleanup_ros1_perception'
            package.mkdir()
            (package / 'model_binding_contract.py').write_text(
                "raise AssertionError('stale package executed')\n",
                encoding='utf-8')
            saved_path = list(sys.path)
            saved_meta = list(sys.meta_path)
            try:
                sys.path.insert(0, str(stale))
                sys.meta_path.insert(0, FakeFinder())
                result = readiness._validate_ros1_model_loader(
                    OVERLAY, MODEL_MANIFEST, EXPECTED_MODELS)
                self.assertTrue(result['validated_pass'], result['failures'])
                self.assertEqual([], calls)
            finally:
                sys.path[:] = saved_path
                sys.meta_path[:] = saved_meta

    def test_contract_drift_and_nonstdlib_import_fail_before_execution(self):
        with TemporaryDirectory() as directory:
            package = _copy_overlay(directory)
            path = (
                package / 'src' / 'limo_cleanup_ros1_perception'
                / 'model_binding_contract.py')
            path.write_text(
                'import numpy\n' + path.read_text(encoding='utf-8'),
                encoding='utf-8')
            result = readiness._validate_ros1_model_loader(
                package, package / 'config/model_bindings.json',
                EXPECTED_MODELS)
            self.assertFalse(result['validated_pass'])
            self.assertIn(
                'ros1_field_model_binding_contract_import_surface_invalid',
                result['failures'])
            self.assertTrue(any(
                item.startswith(
                    'ros1_field_model_binding_contract_anchor_mismatch:')
                for item in result['failures']))
            self.assertFalse(result['detector_module_executed'])

    def test_manifest_link_identity_is_checked_before_resolve(self):
        original = readiness._path_is_linklike
        manifest = MODEL_MANIFEST.resolve()

        def simulated_link(path):
            try:
                if Path(path).absolute() == manifest.absolute():
                    return True
            except (OSError, RuntimeError):
                pass
            return original(path)

        with patch.object(
                readiness, '_path_is_linklike', side_effect=simulated_link):
            result = readiness._validate_ros1_model_loader(
                OVERLAY, MODEL_MANIFEST, EXPECTED_MODELS)
        self.assertFalse(result['validated_pass'])
        self.assertTrue(any(
            item.startswith('ros1_field_model_binding_manifest_invalid:')
            for item in result['failures']))
        self.assertTrue(result['environment_restored'])

    def test_source_audit_closes_runtime_source_but_field_delivery_stays_blocked(self):
        audit = readiness.audit_ros1_noetic_field_source_contract(WORKSPACE)
        self.assertTrue(audit['source_core_binding']['validated_pass'])
        self.assertTrue(audit['model_loader_validation']['validated_pass'])
        self.assertTrue(audit['formal_rosbag1_admission']['validated_pass'])
        self.assertFalse(
            audit['formal_rosbag1_admission']['field_evidence_admitted'])
        self.assertFalse(audit['capability_matrix_diagnostic'][
            'declarations']['source_core_binding'])
        self.assertFalse(audit['capability_matrix_diagnostic'][
            'authoritative_for_complete_runtime'])
        self.assertTrue(audit['pass'], audit['failures'])
        self.assertTrue(audit['complete_runtime'])
        self.assertEqual([], audit['failures'])
        self.assertEqual([], audit['architecture_blockers'])

        canonical = readiness.make_ros1_canonical_source_binding(
            workspace=WORKSPACE, source_audit=audit, test_only=False)
        with TemporaryDirectory() as directory:
            missing_install_evidence = (
                Path(directory) / 'missing_field_install_evidence.json')
            field_install = (
                readiness.validate_ros1_noetic_field_install_evidence(
                    evidence_path=missing_install_evidence,
                    release_binding={
                        'release_id': 'test-only-missing-field-install',
                        'source_set_sha256': '0' * 64,
                    },
                    expected_model_hashes=readiness.EXPECTED_MODEL_SHA256,
                    workspace=WORKSPACE,
                    source_audit=audit,
                    canonical_source_binding=canonical))
        self.assertFalse(field_install['validated_pass'])
        self.assertFalse(field_install['source_contract_pass'])
        self.assertIn(
            'ros1_field_install_evidence_missing', field_install['failures'])
        self.assertIn(
            readiness.ROS1_CANONICAL_BINDING_MISMATCH,
            field_install['failures'])
        self.assertFalse(field_install['test_only_synthetic_binding'])

        delivery_state = {
            'ros1_noetic_field_install_pass': field_install['validated_pass'],
            'ros1_noetic_build_install_validated': False,
            'formal_four_scene_pass': False,
            'formal_tf_pass': False,
            'formal_3d_pass': False,
            'formal_latency_pass': False,
            'delivery_ready': False,
        }
        self.assertFalse(delivery_state['ros1_noetic_field_install_pass'])
        self.assertFalse(
            delivery_state['ros1_noetic_build_install_validated'])
        self.assertFalse(delivery_state['formal_four_scene_pass'])
        self.assertFalse(delivery_state['formal_tf_pass'])
        self.assertFalse(delivery_state['formal_3d_pass'])
        self.assertFalse(delivery_state['formal_latency_pass'])
        self.assertFalse(delivery_state['delivery_ready'])

    def test_dual_detector_delegates_to_one_parser_contract(self):
        detector = (
            OVERLAY / 'src' / 'limo_cleanup_ros1_perception'
            / 'dual_model_detector.py').read_text(encoding='utf-8')
        contract = (
            OVERLAY / 'src' / 'limo_cleanup_ros1_perception'
            / 'model_binding_contract.py').read_text(encoding='utf-8')
        self.assertIn(
            'from limo_cleanup_ros1_perception.model_binding_contract import',
            detector)
        for definition in (
                'def load_model_bindings(', 'class ModelBinding:',
                'def resolve_model_artifacts(', 'def model_set_sha256('):
            self.assertNotIn(definition, detector)
            self.assertEqual(1, contract.count(definition))
        self.assertNotIn('import numpy', contract)
        self.assertNotIn('limo_cleanup_ros1_perception.', contract)


if __name__ == '__main__':
    unittest.main()
