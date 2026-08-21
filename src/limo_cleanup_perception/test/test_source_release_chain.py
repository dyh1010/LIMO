"""End-to-end offline source release evidence tests."""

import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from limo_cleanup_perception import perception_readiness
from src.limo_cleanup_perception.test.test_perception_readiness import (
    TEST_MODEL_HASHES,
    _build_bundle,
)


ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / 'scripts'
RELEASE_ID = 'test-v2-release-0001'
MANIFEST_TIME = 800.0
PREFLIGHT_TIME = 900.0


def _load_script(module_name, filename):
    """Load one filesystem-only script without executing its CLI."""
    scripts_text = str(SCRIPTS)
    if scripts_text not in sys.path:
        sys.path.insert(0, scripts_text)
    spec = importlib.util.spec_from_file_location(
        module_name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity(path):
    """Return a readiness artifact declaration for one temporary file."""
    return {
        'path': path.name,
        'size_bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_controlled_release(root, policy):
    """Create the static release inputs required by the preflight."""
    release = root / 'controlled-release'
    release.mkdir()
    patch_text = ''.join(
        'diff --git a/{0} b/{0}\n'.format(relative)
        for relative in policy.SAFE_PATCH_PATHS)
    (release / 'perception_rgbd_release.diff').write_text(
        patch_text, encoding='utf-8')
    sums = ''.join(
        '{}  {}\n'.format(policy.sha256_file(ROOT / relative), relative)
        for relative in policy.SAFE_PATCH_PATHS)
    (release / 'ROBOT_SOURCE_SHA256SUMS.txt').write_text(
        sums, encoding='utf-8')
    (release / 'DEPLOYMENT_READONLY.md').write_text(
        'Offline filesystem validation only.\n', encoding='utf-8')
    return release


class _FakeYolo:
    """Expose only the frozen single-class names used by the preflight."""

    def __init__(self, path):
        filename = Path(path).name
        self.names = ({0: 'plastic_bottle'} if filename.startswith('nongfu_')
                      else {0: 'trash_bin'})


class SourceReleaseChainTest(unittest.TestCase):
    """Exercise generator, preflight, and readiness using real JSON artifacts."""

    def _generate(self, generator, output):
        with patch.object(sys, 'argv', [
                'generate_perception_source_manifest',
                '--workspace', str(ROOT),
                '--release-id', RELEASE_ID,
                '--generated-at-unix-sec', str(MANIFEST_TIME),
                '--output', str(output)]):
            self.assertEqual(0, generator.main())
        return json.loads(output.read_text(encoding='utf-8'))

    def _build_readiness_bundle(self, root):
        """Use the shared complete fixture with current collector metadata."""
        return _build_bundle(root)

    def _synthetic_ros1_admission(self, bundle, payload):
        """Bind this test to the ROS1 source behind its synthetic evidence."""
        declaration = payload['ros1_field_install_validation']
        evidence_path = Path(declaration['path'])
        if not evidence_path.is_absolute():
            evidence_path = Path(bundle).parent / evidence_path
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        workspace = Path(evidence['workspace_root'])
        canonical_audit = (
            perception_readiness.audit_ros1_noetic_field_source_contract(
                workspace=workspace))
        # This fixture is intentionally synthetic/test-only.  It may exercise
        # validators and release binding, but it can never satisfy the
        # production ROS1 runtime/formal-admission gate.
        self.assertFalse(canonical_audit['pass'])
        self.assertIn(
            perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
            canonical_audit['architecture_blockers'])
        canonical_binding = (
            perception_readiness.make_ros1_canonical_source_binding(
                workspace=workspace, source_audit=canonical_audit,
                test_only=True))
        self.assertTrue(canonical_binding['test_only'])
        return canonical_binding, canonical_audit

    def _preflight(self, module, policy, release, models, manifest, report):
        expected_models = {
            filename: policy.sha256_file(models / filename)
            for filename in (
                'nongfu_yolov8n_best.pt', 'trash_bin_yolov8n_best.pt')}
        fake_ultralytics = types.ModuleType('ultralytics')
        fake_ultralytics.YOLO = _FakeYolo
        versions = {
            'numpy': '1.19.5', 'cv2': '4.5.5', 'torch': '1.10.2',
            'ultralytics': '8.3.21'}
        argv = [
            'perception_release_preflight',
            '--project-root', str(ROOT),
            '--release-dir', str(release),
            '--models-dir', str(models),
            '--release-id', RELEASE_ID,
            '--source-manifest', str(manifest),
            '--require-runtime',
            '--report', str(report),
        ]
        with patch.object(sys, 'argv', argv), patch.object(
                module, 'EXPECTED_MODELS', expected_models), patch.object(
                module, 'module_version', side_effect=versions.get), patch.object(
                module.platform, 'python_version', return_value='3.8.10'), \
                patch.object(module.platform, 'machine', return_value='aarch64'), \
                patch.object(module.time, 'time', return_value=PREFLIGHT_TIME), \
                patch.dict(sys.modules, {'ultralytics': fake_ultralytics}), \
                patch.dict(os.environ, {'ROS_DISTRO': 'foxy'}):
            with redirect_stdout(io.StringIO()):
                return module.main()

    def _bind_generated_artifacts(
            self, root, payload, manifest_path, manifest_value,
            runtime_path):
        manifest_identity = _identity(manifest_path)
        source_set_sha = manifest_value['source_set_sha256']
        payload['release_binding'].update({
            'source_manifest_artifact_sha256': manifest_identity['sha256'],
            'source_set_sha256': source_set_sha,
            'manifest_generated_at_unix_sec': MANIFEST_TIME,
        })
        payload['software_binding']['runtime_preflight'] = _identity(runtime_path)
        build_entry = payload['ros_build_validation']
        build_path = root / build_entry['path']
        build = json.loads(build_path.read_text(encoding='utf-8'))
        build['source_manifest_artifact'] = manifest_identity
        build['source_manifest'] = {
            'required_source_names': manifest_value['required_source_names'],
            'entries': manifest_value['entries'],
            'source_set_sha256': source_set_sha,
        }
        build_path.write_text(
            json.dumps(build, sort_keys=True) + '\n', encoding='utf-8')
        build_entry.update(_identity(build_path))

    def test_real_generator_preflight_readiness_chain_and_tamper_rejection(self):
        generator = _load_script(
            'perception_manifest_generator_e2e',
            'generate_perception_source_manifest.py')
        preflight = _load_script(
            'perception_release_preflight_e2e',
            'perception_release_preflight.py')
        policy = sys.modules['perception_release_policy']
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, payload = self._build_readiness_bundle(root)
            canonical_binding, canonical_audit = (
                self._synthetic_ros1_admission(bundle, payload))
            manifest_path = root / 'generated-source-manifest.json'
            manifest = self._generate(generator, manifest_path)
            self.assertIn(
                'perception:limo_cleanup_perception/typed_raw_binding.py',
                manifest['required_source_names'])
            self.assertEqual(
                manifest['required_source_names'],
                list(perception_readiness._required_build_source_names()))

            models = root / 'models'
            models.mkdir()
            (models / 'nongfu_yolov8n_best.pt').write_bytes(b'bottle-model')
            (models / 'trash_bin_yolov8n_best.pt').write_bytes(b'bin-model')
            release = _write_controlled_release(root, policy)
            runtime_path = root / 'generated-runtime-preflight.json'
            self.assertEqual(0, self._preflight(
                preflight, policy, release, models, manifest_path,
                runtime_path))
            with self.assertRaisesRegex(
                    SystemExit, 'report path must not already exist'):
                self._preflight(
                    preflight, policy, release, models, manifest_path,
                    runtime_path)
            runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
            self.assertTrue(runtime['passed'])
            self.assertEqual(
                _identity(manifest_path)['sha256'],
                runtime['source_manifest_artifact_sha256'])
            self.assertEqual(
                manifest['source_set_sha256'], runtime['source_set_sha256'])

            self._bind_generated_artifacts(
                root, payload, manifest_path, manifest, runtime_path)
            result = perception_readiness.evaluate_readiness(
                bundle, payload, now_unix_sec=2000.0,
                expected_model_hashes=TEST_MODEL_HASHES,
                canonical_source_binding=canonical_binding,
                canonical_source_audit=canonical_audit,
                allow_test_synthetic_binding=True)
            self.assertFalse(result['delivery_ready'])
            self.assertTrue(result['delivery_gate_summary'][
                'formal_four_scene_pass'])
            self.assertTrue(result['delivery_gate_summary'][
                'formal_tf_3d_pass'])
            self.assertIn(
                perception_readiness.ROS1_TEST_ONLY_SOURCE_BINDING,
                result['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                result['failures'])

            tampered_manifest_path = root / 'tampered-source-manifest.json'
            tampered_manifest = copy.deepcopy(manifest)
            tampered_manifest['source_set_sha256'] = '0' * 64
            tampered_manifest_path.write_text(
                json.dumps(tampered_manifest, sort_keys=True) + '\n',
                encoding='utf-8')
            tampered_runtime = root / 'tampered-runtime-preflight.json'
            self.assertEqual(1, self._preflight(
                preflight, policy, release, models, tampered_manifest_path,
                tampered_runtime))
            checks = {
                item['name']: item for item in json.loads(
                    tampered_runtime.read_text(encoding='utf-8'))['checks']}
            self.assertEqual('FAIL', checks['canonical_source_set']['status'])

            manifest['generated_at_unix_sec'] = MANIFEST_TIME + 1.0
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
            payload['release_binding'][
                'source_manifest_artifact_sha256'] = _identity(
                    manifest_path)['sha256']
            build_entry = payload['ros_build_validation']
            build_path = root / build_entry['path']
            build = json.loads(build_path.read_text(encoding='utf-8'))
            build['source_manifest_artifact'] = _identity(manifest_path)
            build_path.write_text(
                json.dumps(build, sort_keys=True) + '\n', encoding='utf-8')
            build_entry.update(_identity(build_path))
            rejected = perception_readiness.evaluate_readiness(
                bundle, payload, now_unix_sec=2000.0,
                expected_model_hashes=TEST_MODEL_HASHES,
                canonical_source_binding=canonical_binding,
                canonical_source_audit=canonical_audit,
                allow_test_synthetic_binding=True)
            self.assertFalse(rejected['delivery_ready'])
            self.assertIn(
                'runtime_release_binding_mismatch', rejected['failures'])


if __name__ == '__main__':
    unittest.main()
