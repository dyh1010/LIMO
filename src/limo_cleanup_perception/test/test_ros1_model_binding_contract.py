"""Fail-closed ROS1 dual-model manifest and artifact contracts.

The tests are ROS-independent.  Temporary model bytes are synthetic and are
used only to prove validation order; they are never accepted as project model
weights or field evidence.
"""

import ast
import copy
import hashlib
import importlib
import importlib.abc
import json
import shutil
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


WORKSPACE = Path(__file__).resolve().parents[3]
OVERLAY = (
    WORKSPACE / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception')
OVERLAY_PYTHON = OVERLAY / 'src'
HOST_PYTHON = WORKSPACE / 'src' / 'limo_cleanup_perception'
for candidate in (str(OVERLAY_PYTHON), str(HOST_PYTHON)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

MODEL = importlib.import_module(
    'limo_cleanup_ros1_perception.dual_model_detector')
CONTRACT = importlib.import_module(
    'limo_cleanup_ros1_perception.model_binding_contract')
READINESS = importlib.import_module(
    'limo_cleanup_perception.perception_readiness')
MANIFEST_PATH = OVERLAY / 'config' / 'model_bindings.json'
EXPECTED_MODELS = {
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
EXPECTED_POLICY = {
    'regular_file_required': True,
    'sha256_required': True,
    'single_exact_class_required': True,
    'missing_model_is_fatal': True,
    'hash_mismatch_is_fatal': True,
    'silent_fallback_or_relabel_forbidden': True,
    'automatic_download_forbidden': True,
}
HOST_LOADER_WATCHED_MODULES = (
    'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing', 'numpy',
    'limo_cleanup_ros1_perception',
    'limo_cleanup_ros1_perception.model_binding_contract',
    'limo_cleanup_ros1_perception.dual_model_detector',
)


def _fresh_process_loader_probe(
        fake_module_name=None, fake_attestor=False,
        fake_finder_target=None, no_site=True):
    """Run the real host gate after pollution predating its first import."""
    dependency_paths = tuple(
        value for value in sys.path
        if isinstance(value, str) and value
        and ('site-packages' in value or 'dist-packages' in value))
    script = f"""
import sys

host_python = {str(HOST_PYTHON)!r}
overlay_python = {str(OVERLAY_PYTHON)!r}
dependency_paths = {dependency_paths!r}
for candidate in dependency_paths + (overlay_python, host_python):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

fake_module_name = {fake_module_name!r}
fake_attestor = {fake_attestor!r}
fake_finder_target = {fake_finder_target!r}
calls = []
finder_calls = []
fake = None
attestor_fake = None

def invoked(*args, **kwargs):
    calls.append((args, kwargs))
    raise AssertionError('injected callable executed')

if fake_module_name is not None:
    real_modules = {{
        name: __import__(name)
        for name in (
            'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing')}}
    real = real_modules[fake_module_name]
    fake = type(sys)(fake_module_name)
    fake.__dict__.update(real.__dict__)

    class FakeLoader:
        pass

    class FakeSpec:
        origin = 'memory://preimport-' + fake_module_name
        loader = FakeLoader()

    fake.__name__ = fake_module_name
    fake.__spec__ = FakeSpec()
    fake.__loader__ = fake.__spec__.loader
    fake.__file__ = FakeSpec.origin
    fake.__getattr__ = lambda attribute: getattr(real, attribute)
    wrapped = {{
        'json': ('load', 'loads', 'dump', 'dumps'),
        'hashlib': ('sha256', 'new'),
        'stat': ('S_ISREG', 'S_ISLNK'),
        'dataclasses': ('dataclass', 'field', 'asdict'),
        'pathlib': ('Path', 'PurePath'),
        'typing': ('get_origin', 'get_args', 'cast'),
    }}[fake_module_name]
    for attribute in wrapped:
        fake.__dict__[attribute] = invoked
    sys.modules[fake_module_name] = fake

attestor_name = 'limo_cleanup_perception.stdlib_attestation'
if fake_attestor:
    attestor_fake = type(sys)(attestor_name)
    attestor_fake.audit_ambient_stdlib = invoked
    attestor_fake.bootstrap_ambient_stdlib = invoked
    sys.modules[attestor_name] = attestor_fake

if fake_finder_target in (
        'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing'):
    for module_name in (
            'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing'):
        if module_name != fake_finder_target:
            __import__(module_name)

removed_finder_target = None
if fake_finder_target is not None:
    removed_finder_target = sys.modules.pop(fake_finder_target, None)

class AmbientFinder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == fake_finder_target:
            finder_calls.append(fullname)
            raise AssertionError('ambient finder executed for ' + fullname)
        return None

finder = AmbientFinder() if fake_finder_target is not None else None
if finder is not None:
    sys.meta_path.insert(0, finder)

before_path = tuple(sys.path)
before_meta_path = tuple(sys.meta_path)
from limo_cleanup_perception import perception_readiness as readiness
result = readiness._validate_ros1_model_loader(
    {str(OVERLAY)!r},
    {str(MANIFEST_PATH)!r},
    {EXPECTED_MODELS!r})

finder_target_module = (
    sys.modules.get(fake_finder_target)
    if fake_finder_target is not None else None)
finder_target_spec = getattr(finder_target_module, '__spec__', None)

summary = {{
    'validated_pass': result['validated_pass'],
    'failures': result['failures'],
    'ambient_stdlib_identity_clean': result[
        'ambient_stdlib_identity_clean'],
    'environment_restored': result['environment_restored'],
    'candidate_contract_executed': result[
        'candidate_contract_executed'],
    'detector_module_executed': result['detector_module_executed'],
    'target_contract_executed': result['target_contract_executed'],
    'numpy_required_by_gate': result['numpy_required_by_gate'],
    'calls': len(calls),
    'finder_calls': len(finder_calls),
    'finder_target_was_absent': removed_finder_target is None,
    'finder_target_loaded': finder_target_module is not None,
    'finder_target_origin': getattr(finder_target_spec, 'origin', None),
    'fake_object_preserved': (
        True if fake_module_name is None
        else sys.modules.get(fake_module_name) is fake),
    'attestor_fake_preserved': (
        True if not fake_attestor
        else sys.modules.get(attestor_name) is attestor_fake),
    'path_preserved': tuple(sys.path) == before_path,
    'meta_path_preserved': tuple(sys.meta_path) == before_meta_path,
}}
print(repr(summary))
"""
    flags = ['-I']
    if no_site:
        flags.append('-S')
    flags.extend(('-B', '-c', script))
    completed = subprocess.run(
        [sys.executable] + flags,
        cwd=str(WORKSPACE),
        check=True,
        capture_output=True,
        text=True)
    return ast.literal_eval(completed.stdout.strip().splitlines()[-1])


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def _write_manifest(root, payload=None, raw=None):
    path = Path(root) / 'model_bindings.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        raw = json.dumps(
            payload, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False) + '\n'
    path.write_text(raw, encoding='utf-8')
    return path


def _expect_value_error(callback, expected):
    try:
        callback()
    except ValueError as error:
        assert expected in str(error), str(error)
    else:
        raise AssertionError('invalid model binding input was accepted')


def _synthetic_bindings(root):
    root = Path(root)
    bindings = {}
    for label, filename in (
            ('plastic_bottle', 'nongfu_yolov8n_best.pt'),
            ('trash_bin', 'trash_bin_yolov8n_best.pt')):
        path = root / filename
        value = ('synthetic-test-only-' + label).encode('utf-8')
        path.write_bytes(value)
        bindings[label] = MODEL.ModelBinding(
            class_name=label,
            filename=filename,
            deployment_path='/not-used-with-model-root/' + filename,
            size_bytes=len(value),
            sha256=hashlib.sha256(value).hexdigest(),
            backend='ultralytics-yolo-pt')
    return bindings


def _package_modules():
    prefix = 'limo_cleanup_ros1_perception'
    return {
        name: module for name, module in tuple(sys.modules.items())
        if name == prefix or name.startswith(prefix + '.')}


def _validate_loader_with_restored_import_state(
        package_root=OVERLAY, model_path=MANIFEST_PATH):
    before_path = list(sys.path)
    before_meta_path = list(sys.meta_path)
    before_modules = _package_modules()
    missing = object()
    before_watched = {
        name: sys.modules.get(name, missing)
        for name in HOST_LOADER_WATCHED_MODULES}
    try:
        return READINESS._validate_ros1_model_loader(
            package_root, model_path, EXPECTED_MODELS)
    finally:
        assert sys.path == before_path
        assert sys.meta_path == before_meta_path
        after_modules = _package_modules()
        assert set(after_modules) == set(before_modules)
        for name, module in before_modules.items():
            assert after_modules[name] is module
        for name, module in before_watched.items():
            assert sys.modules.get(name, missing) is module


def _assert_provenance_rejected(result, case):
    assert result['validated_pass'] is False, case
    assert result['host_owned_manifest_parser'] is True, case
    assert result['backend_initialized'] is False, case
    assert result['candidate_contract_executed'] is False, case
    assert result['candidate_contract_return_value_trusted'] is False, case
    assert result['environment_restored'] is True, case
    assert result['failures'], case


def _assert_provenance_isolated(result, case):
    assert result['validated_pass'] is True, (case, result['failures'])
    assert result['host_owned_manifest_parser'] is True, case
    assert result['backend_initialized'] is False, case
    assert result['candidate_contract_executed'] is False, case
    assert result['candidate_contract_return_value_trusted'] is False, case
    assert result['detector_module_executed'] is False, case
    assert result['target_contract_executed'] is False, case
    assert result['numpy_required_by_gate'] is False, case
    assert result['environment_restored'] is True, case
    assert result['failures'] == [], case


def _fake_bindings():
    return {
        label: types.SimpleNamespace(**copy.deepcopy(values))
        for label, values in EXPECTED_MODELS.items()}


class _MemoryLoader(importlib.abc.Loader):
    def __init__(self, configure, declared_file=None):
        self.configure = configure
        self.declared_file = declared_file

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        if self.declared_file is not None:
            module.__file__ = str(self.declared_file)
        self.configure(module)


class _FullModelSpoofFinder(importlib.abc.MetaPathFinder):
    def __init__(self, fake_package_path, spoof_declared_paths=False):
        self.fake_package_path = Path(fake_package_path)
        self.spoof_declared_paths = spoof_declared_paths
        self.used = False

    def find_spec(self, fullname, path=None, target=None):
        package = 'limo_cleanup_ros1_perception'
        dual = package + '.dual_model_detector'
        if fullname == package:
            def configure(module):
                self.used = True
                module.__path__ = [str(self.fake_package_path)]
                module.__all__ = ()

            declared = (
                OVERLAY_PYTHON / package / '__init__.py'
                if self.spoof_declared_paths else None)
            loader = _MemoryLoader(configure, declared_file=declared)
            spec = importlib.util.spec_from_loader(
                fullname, loader, is_package=True)
            spec.origin = 'memory://fake-package'
            spec.submodule_search_locations = [
                str(self.fake_package_path)]
            return spec
        if fullname == dual:
            def configure(module):
                self.used = True
                module.load_model_bindings = lambda path: (
                    _fake_bindings(), _sha256(path))

            declared = (
                OVERLAY_PYTHON / package / 'dual_model_detector.py'
                if self.spoof_declared_paths else None)
            loader = _MemoryLoader(configure, declared_file=declared)
            spec = importlib.util.spec_from_loader(fullname, loader)
            spec.origin = 'memory://fake-dual-model-detector'
            return spec
        return None


class _TargetContractSpoofFinder(importlib.abc.MetaPathFinder):
    used = False

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'limo_cleanup_ros1_perception.target_contract':
            return None

        def configure(module):
            self.used = True
            module.EXPECTED_MODEL_SHA256 = {
                label: values['sha256']
                for label, values in EXPECTED_MODELS.items()}
            module.require_single_class_model = lambda names, expected: None

        loader = _MemoryLoader(configure)
        spec = importlib.util.spec_from_loader(fullname, loader)
        spec.origin = 'memory://fake-target-contract'
        return spec


class _NamedSpoofFinder(importlib.abc.MetaPathFinder):
    def __init__(self, module_name):
        self.module_name = module_name
        self.used = False

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.module_name:
            return None

        def configure(module):
            self.used = True
            module.SPOOFED_MODEL_GATE_DEPENDENCY = True

        loader = _MemoryLoader(configure)
        spec = importlib.util.spec_from_loader(fullname, loader)
        spec.origin = 'memory://spoof-' + fullname
        return spec


class DistutilsMetaFinder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.used = False

    def find_spec(self, fullname, path=None, target=None):
        self.used = True
        return None


def _write_fake_model_package(root, spoof_declared_paths=False):
    package = Path(root) / 'limo_cleanup_ros1_perception'
    package.mkdir(parents=True)
    init_lines = ['__all__ = ()']
    dual_lines = [
        'import hashlib',
        'import json',
        'from types import SimpleNamespace',
        '',
        'def load_model_bindings(path):',
        "    data = open(str(path), 'rb').read()",
        "    payload = json.loads(data.decode('utf-8'))",
        '    bindings = {',
        '        name: SimpleNamespace(**values)',
        "        for name, values in payload['models'].items()}",
        '    return bindings, hashlib.sha256(data).hexdigest()',
    ]
    if spoof_declared_paths:
        init_lines.append('__file__ = {!r}'.format(str(
            OVERLAY_PYTHON / 'limo_cleanup_ros1_perception' / '__init__.py')))
        init_lines.append('__path__ = [{!r}]'.format(str(
            OVERLAY_PYTHON / 'limo_cleanup_ros1_perception')))
        dual_lines.append('__file__ = {!r}'.format(str(
            OVERLAY_PYTHON / 'limo_cleanup_ros1_perception'
            / 'dual_model_detector.py')))
    (package / '__init__.py').write_text(
        '\n'.join(init_lines) + '\n', encoding='utf-8')
    (package / 'dual_model_detector.py').write_text(
        '\n'.join(dual_lines) + '\n', encoding='utf-8')
    return package


def _validate_with_path_precedence(first_root):
    original = list(sys.path)
    fake = str(Path(first_root))
    real = str(OVERLAY_PYTHON)
    sys.path[:] = [fake, real] + [
        value for value in original if value not in (fake, real)]
    try:
        return _validate_loader_with_restored_import_state()
    finally:
        sys.path[:] = original


def test_real_manifest_is_exact_and_loads_without_backend_initialization():
    payload = _manifest()
    assert payload == {
        'schema_version': 1,
        'manifest_id': 'limo-ros1-dual-model-bindings-v1',
        'runtime_family': 'ROS1',
        'ros_distro': 'noetic',
        'read_only': True,
        'authorizes_motion': False,
        'delivery_ready': False,
        'runtime': 'ultralytics-8.3.21',
        'load_policy': EXPECTED_POLICY,
        'models': EXPECTED_MODELS,
    }
    bindings, manifest_sha256 = MODEL.load_model_bindings(MANIFEST_PATH)
    assert manifest_sha256 == _sha256(MANIFEST_PATH)
    assert set(bindings) == {'plastic_bottle', 'trash_bin'}
    for label, expected in EXPECTED_MODELS.items():
        assert bindings[label] == MODEL.ModelBinding(**expected)


def test_manifest_top_level_missing_extra_and_value_drift_fail_closed():
    payload = _manifest()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for key in tuple(payload):
            mutated = copy.deepcopy(payload)
            mutated.pop(key)
            path = _write_manifest(root / ('missing-' + key), mutated)
            _expect_value_error(
                lambda path=path: MODEL.load_model_bindings(path),
                'model binding manifest policy is invalid')

        mutated = copy.deepcopy(payload)
        mutated['unexpected'] = 'not-allowed'
        path = _write_manifest(root / 'extra', mutated)
        _expect_value_error(
            lambda: MODEL.load_model_bindings(path),
            'model binding manifest policy is invalid')

        drift = {
            'schema_version': 2,
            'manifest_id': 'foreign-manifest',
            'runtime_family': 'ROS2',
            'ros_distro': 'foxy',
            'read_only': 1,
            'authorizes_motion': True,
            'delivery_ready': True,
            'runtime': 'unbound-runtime',
        }
        for key, value in drift.items():
            mutated = copy.deepcopy(payload)
            mutated[key] = value
            path = _write_manifest(root / ('drift-' + key), mutated)
            _expect_value_error(
                lambda path=path: MODEL.load_model_bindings(path),
                'model binding manifest policy is invalid')

        for key, value, expected in (
                ('load_policy', {}, 'model loading policy is invalid'),
                ('models', {}, 'model binding classes are incomplete')):
            mutated = copy.deepcopy(payload)
            mutated[key] = value
            path = _write_manifest(root / ('drift-' + key), mutated)
            _expect_value_error(
                lambda path=path: MODEL.load_model_bindings(path), expected)


def test_load_policy_and_each_model_entry_are_exact_typed_contracts():
    payload = _manifest()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for key in EXPECTED_POLICY:
            for case in ('missing', 'false'):
                mutated = copy.deepcopy(payload)
                if case == 'missing':
                    mutated['load_policy'].pop(key)
                else:
                    mutated['load_policy'][key] = False
                path = _write_manifest(
                    root / ('policy-' + key + '-' + case), mutated)
                _expect_value_error(
                    lambda path=path: MODEL.load_model_bindings(path),
                    'model loading policy is invalid')
        mutated = copy.deepcopy(payload)
        mutated['load_policy']['extra'] = True
        path = _write_manifest(root / 'policy-extra', mutated)
        _expect_value_error(
            lambda: MODEL.load_model_bindings(path),
            'model loading policy is invalid')

        for label, expected_entry in EXPECTED_MODELS.items():
            for key in expected_entry:
                mutated = copy.deepcopy(payload)
                mutated['models'][label].pop(key)
                path = _write_manifest(
                    root / ('model-' + label + '-missing-' + key), mutated)
                _expect_value_error(
                    lambda path=path: MODEL.load_model_bindings(path),
                    'invalid model binding: ' + label)
            mutated = copy.deepcopy(payload)
            mutated['models'][label]['extra'] = 'not-allowed'
            path = _write_manifest(root / ('model-' + label + '-extra'), mutated)
            _expect_value_error(
                lambda path=path: MODEL.load_model_bindings(path),
                'invalid model binding: ' + label)

            drift_values = {
                'class_name': 'wrong_class',
                'filename': 'wrong.pt',
                'deployment_path': '/tmp/' + expected_entry['filename'],
                'size_bytes': expected_entry['size_bytes'] + 1,
                'sha256': '0' * 64,
                'backend': 'unbound-backend',
            }
            for key, value in drift_values.items():
                mutated = copy.deepcopy(payload)
                mutated['models'][label][key] = value
                path = _write_manifest(
                    root / ('model-' + label + '-drift-' + key), mutated)
                _expect_value_error(
                    lambda path=path: MODEL.load_model_bindings(path),
                    'invalid model binding: ' + label)

            for index, value in enumerate((True, 1.5, '1', 0, -1)):
                mutated = copy.deepcopy(payload)
                mutated['models'][label]['size_bytes'] = value
                path = _write_manifest(
                    root / ('model-{}-bad-size-{}'.format(label, index)),
                    mutated)
                _expect_value_error(
                    lambda path=path: MODEL.load_model_bindings(path),
                    'invalid model binding: ' + label)


def test_duplicate_json_keys_and_non_finite_constants_are_rejected():
    payload = _manifest()
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    duplicate = canonical.replace(
        '{', '{"schema_version":1,', 1)
    non_finite = canonical.replace(
        '"size_bytes":6244778', '"size_bytes":NaN', 1)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        duplicate_path = _write_manifest(root / 'duplicate', raw=duplicate)
        _expect_value_error(
            lambda: MODEL.load_model_bindings(duplicate_path),
            'duplicate JSON key: schema_version')
        non_finite_path = _write_manifest(root / 'nan', raw=non_finite)
        _expect_value_error(
            lambda: MODEL.load_model_bindings(non_finite_path),
            'non-finite JSON constant: NaN')


def test_model_artifacts_are_verified_before_any_backend_is_initialized():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        bindings = _synthetic_bindings(root)
        resolved = MODEL.resolve_model_artifacts(bindings, model_root=root)
        assert set(resolved) == {'plastic_bottle', 'trash_bin'}
        assert all(path.is_file() for path in resolved.values())

        missing_root = root / 'missing'
        missing_root.mkdir()
        _expect_value_error(
            lambda: MODEL.resolve_model_artifacts(
                bindings, model_root=missing_root),
            'model artifact missing: plastic_bottle')

        wrong_size = dict(bindings)
        wrong_size['plastic_bottle'] = replace(
            bindings['plastic_bottle'],
            size_bytes=bindings['plastic_bottle'].size_bytes + 1)
        _expect_value_error(
            lambda: MODEL.resolve_model_artifacts(
                wrong_size, model_root=root),
            'model artifact size mismatch: plastic_bottle')

        wrong_hash = dict(bindings)
        wrong_hash['plastic_bottle'] = replace(
            bindings['plastic_bottle'], sha256='0' * 64)
        _expect_value_error(
            lambda: MODEL.resolve_model_artifacts(
                wrong_hash, model_root=root),
            'model artifact hash mismatch: plastic_bottle')

        manifest_link_target = MANIFEST_PATH.resolve()

        def manifest_linklike(path):
            return Path(path).resolve() == manifest_link_target

        with patch.object(
                CONTRACT, '_path_is_linklike',
                side_effect=manifest_linklike, create=True):
            _expect_value_error(
                lambda: MODEL.load_model_bindings(MANIFEST_PATH),
                'model binding manifest must be a regular file')

        linked_artifact = (root / bindings['plastic_bottle'].filename).resolve()

        def artifact_linklike(path):
            return Path(path).resolve() == linked_artifact

        with patch.object(
                CONTRACT, '_path_is_linklike',
                side_effect=artifact_linklike, create=True):
            _expect_value_error(
                lambda: MODEL.resolve_model_artifacts(
                    bindings, model_root=root),
                'model artifact is not a regular file: plastic_bottle')

        loader_calls = []

        def loader(path):
            loader_calls.append(path)
            raise AssertionError('backend must not initialize')

        (root / bindings['plastic_bottle'].filename).unlink()
        with patch.object(
                MODEL, 'load_model_bindings',
                return_value=(bindings, '1' * 64)):
            _expect_value_error(
                lambda: MODEL.DualModelInference(
                    MANIFEST_PATH, model_root=root, loader=loader),
                'model artifact missing: plastic_bottle')
        assert loader_calls == []


def test_model_loader_ignores_preexisting_fake_modules_and_restores_them():
    package_name = 'limo_cleanup_ros1_perception'
    dual_name = package_name + '.dual_model_detector'
    fake_package = types.ModuleType(package_name)
    fake_package.__path__ = ['preexisting-fake-package']
    fake_dual = types.ModuleType(dual_name)
    fake_calls = []

    def fake_load(path):
        fake_calls.append(path)
        return _fake_bindings(), _sha256(path)

    fake_dual.load_model_bindings = fake_load
    with patch.dict(sys.modules, {
            package_name: fake_package,
            dual_name: fake_dual,
    }, clear=False):
        result = _validate_loader_with_restored_import_state()
        assert fake_calls == []
        assert sys.modules[package_name] is fake_package
        assert sys.modules[dual_name] is fake_dual
        _assert_provenance_isolated(
            result, 'preexisting_fake_sys_modules')


def test_model_loader_rejects_each_fake_stdlib_module_without_executing_it():
    for module_name in (
            'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing'):
        calls = []
        fake = types.ModuleType(module_name)

        def invoked(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError('ambient fake stdlib module executed')

        fake.loads = invoked
        fake.sha256 = invoked
        fake.S_ISREG = invoked
        fake.dataclass = invoked
        fake.Path = invoked
        fake.Mapping = invoked
        with patch.dict(sys.modules, {module_name: fake}, clear=False):
            result = _validate_loader_with_restored_import_state()
            assert sys.modules[module_name] is fake
        assert calls == [], module_name
        _assert_provenance_rejected(
            result, 'fake_sys_modules_' + module_name)
        assert (
            'ros1_field_model_loader_ambient_stdlib_identity_mismatch:'
            + module_name) in result['failures']


def test_model_loader_rejects_preimport_fake_stdlib_in_fresh_processes():
    for module_name in (
            'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing'):
        result = _fresh_process_loader_probe(fake_module_name=module_name)
        expected = (
            'ros1_field_model_loader_ambient_stdlib_identity_mismatch:'
            + module_name)
        assert result['validated_pass'] is False, module_name
        assert result['ambient_stdlib_identity_clean'] is False, module_name
        assert result['failures'] == [expected], (module_name, result)
        assert result['calls'] == 0, module_name
        assert result['fake_object_preserved'] is True, module_name
        assert result['path_preserved'] is True, module_name
        assert result['meta_path_preserved'] is True, module_name
        assert result['environment_restored'] is True, module_name
        assert result['candidate_contract_executed'] is False, module_name
        assert result['detector_module_executed'] is False, module_name
        assert result['target_contract_executed'] is False, module_name
        assert result['numpy_required_by_gate'] is False, module_name


def test_model_loader_accepts_normal_fresh_process():
    result = _fresh_process_loader_probe(no_site=False)
    assert result['validated_pass'] is True, result
    assert result['failures'] == [], result
    assert result['ambient_stdlib_identity_clean'] is True, result
    assert result['environment_restored'] is True, result
    assert result['calls'] == 0, result
    assert result['path_preserved'] is True, result
    assert result['meta_path_preserved'] is True, result
    assert result['candidate_contract_executed'] is False, result
    assert result['detector_module_executed'] is False, result
    assert result['target_contract_executed'] is False, result
    assert result['numpy_required_by_gate'] is False, result


def test_model_loader_ignores_preimport_fake_attestor_module():
    result = _fresh_process_loader_probe(
        fake_attestor=True, no_site=False)
    assert result['validated_pass'] is True, result
    assert result['failures'] == [], result
    assert result['calls'] == 0, result
    assert result['attestor_fake_preserved'] is True, result
    assert result['path_preserved'] is True, result
    assert result['meta_path_preserved'] is True, result
    assert result['environment_restored'] is True, result


def test_model_loader_bypasses_preimport_attestor_and_json_meta_finders():
    for target, no_site in (
            ('limo_cleanup_perception.stdlib_attestation', False),
            ('json', True)):
        result = _fresh_process_loader_probe(
            fake_finder_target=target, no_site=no_site)
        assert result['validated_pass'] is True, (target, result)
        assert result['failures'] == [], (target, result)
        assert result['finder_calls'] == 0, (target, result)
        assert result['finder_target_was_absent'] is True, (target, result)
        if target == 'json':
            assert result['finder_target_loaded'] is True, result
            assert result['finder_target_origin'].replace('\\', '/').endswith(
                '/json/__init__.py'), result
        else:
            assert result['finder_target_loaded'] is False, result
        assert result['path_preserved'] is True, (target, result)
        assert result['meta_path_preserved'] is True, (target, result)
        assert result['environment_restored'] is True, (target, result)


def test_model_loader_rejects_trusted_json_spec_provenance_tamper():
    trusted_json = sys.modules['json']
    trusted_spec = trusted_json.__spec__
    assert trusted_spec is not None
    cases = (
        ('origin', 'memory://tampered-json-origin'),
        ('loader', object()),
    )
    for attribute, tampered in cases:
        original = getattr(trusted_spec, attribute)
        try:
            setattr(trusted_spec, attribute, tampered)
            result = _validate_loader_with_restored_import_state()
            assert sys.modules['json'] is trusted_json
            assert trusted_json.__spec__ is trusted_spec
            assert getattr(trusted_spec, attribute) is tampered
            _assert_provenance_rejected(
                result, 'trusted_json_spec_' + attribute)
            assert (
                'ros1_field_model_loader_ambient_stdlib_identity_mismatch:'
                'json') in result['failures']
            json_provenance = next(
                item for item in result['ambient_stdlib_provenance']
                if item['module'] == 'json')
            assert json_provenance['bound_trusted_object'] is True
            assert json_provenance['spec_object_matches'] is (
                attribute == 'origin')
            match_key = {
                'origin': 'origin_matches',
                'loader': 'loader_object_matches',
            }[attribute]
            assert json_provenance[match_key] is False
        finally:
            setattr(trusted_spec, attribute, original)
        assert getattr(trusted_spec, attribute) is original
        assert sys.modules['json'] is trusted_json


def test_model_loader_isolates_meta_path_full_module_spoofing():
    with TemporaryDirectory() as directory:
        finder = _FullModelSpoofFinder(Path(directory) / 'fake-package')
        sys.meta_path.insert(0, finder)
        try:
            result = _validate_loader_with_restored_import_state()
        finally:
            assert sys.meta_path[0] is finder
            sys.meta_path.pop(0)
    assert finder.used is False
    _assert_provenance_isolated(result, 'meta_path_full_module_spoof')


def test_model_loader_accepts_normal_distutils_meta_finder_without_using_it():
    finder = DistutilsMetaFinder()
    sys.meta_path.insert(0, finder)
    try:
        result = _validate_loader_with_restored_import_state()
    finally:
        assert sys.meta_path[0] is finder
        sys.meta_path.pop(0)
    assert finder.used is False
    _assert_provenance_isolated(result, 'distutils_meta_finder')


def test_model_loader_ignores_fake_root_before_real_source_root():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_fake_model_package(root)
        result = _validate_with_path_precedence(root)
    _assert_provenance_isolated(result, 'fake_root_before_real')


def test_model_loader_does_not_import_fake_detector_dependency():
    finder = _TargetContractSpoofFinder()
    sys.meta_path.insert(0, finder)
    try:
        result = _validate_loader_with_restored_import_state()
    finally:
        assert sys.meta_path[0] is finder
        sys.meta_path.pop(0)
    assert finder.used is False
    _assert_provenance_isolated(result, 'exact_dual_fake_dependency')


def test_model_loader_ignores_stale_regular_copy_before_canonical_source():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        stale_package = root / 'limo_cleanup_ros1_perception'
        shutil.copytree(
            OVERLAY_PYTHON / 'limo_cleanup_ros1_perception', stale_package,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        stale_dual = stale_package / 'dual_model_detector.py'
        stale_dual.write_text(
            stale_dual.read_text(encoding='utf-8')
            + '\n# stale-copy provenance mutation\n',
            encoding='utf-8')
        result = _validate_with_path_precedence(root)
    _assert_provenance_isolated(result, 'stale_regular_copy')


def test_model_loader_does_not_consult_spoofed_package_metadata():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        finder = _FullModelSpoofFinder(
            root / 'wrong-package-path', spoof_declared_paths=True)
        sys.meta_path.insert(0, finder)
        try:
            result = _validate_loader_with_restored_import_state()
        finally:
            assert sys.meta_path[0] is finder
            sys.meta_path.pop(0)
    assert finder.used is False
    _assert_provenance_isolated(result, 'spoofed_file_and_package_path')


if __name__ == '__main__':
    import inspect

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith('test_') and inspect.isfunction(value)]
    for test in tests:
        test()
    print('{} ROS1 model binding contract tests passed'.format(len(tests)))
