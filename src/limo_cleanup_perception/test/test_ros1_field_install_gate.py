"""Supplemental tests for the ROS1 Noetic field-install gate.

These tests intentionally stay outside the frozen 194-test denominator.  All
source trees, install prefixes, models, logs, and evidence reports are created
under a temporary directory; no ROS graph, camera, or hardware is accessed.
"""

import copy
import hashlib
import json
import shutil
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from limo_cleanup_perception import perception_readiness


WORKSPACE = Path(__file__).resolve().parents[3]
CONTRACT_PATH = (
    WORKSPACE / perception_readiness.ROS1_FIELD_CONTRACT_RELATIVE)
MODEL_MANIFEST_PATH = CONTRACT_PATH.parent / 'model_bindings.json'
_USE_FIXTURE_CANONICAL_BINDING = object()

CANONICAL_BINDING_MISSING = (
    perception_readiness.ROS1_CANONICAL_BINDING_MISSING)
CANONICAL_BINDING_MISMATCH = (
    perception_readiness.ROS1_CANONICAL_BINDING_MISMATCH)
CANONICAL_BINDING_INVALID = (
    perception_readiness.ROS1_CANONICAL_BINDING_INVALID)
TEST_ONLY_SOURCE_BINDING = (
    perception_readiness.ROS1_TEST_ONLY_SOURCE_BINDING)


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path):
    return _sha256_bytes(Path(path).read_bytes())


def _write_bytes(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def _write_text(path, value):
    return _write_bytes(path, value.encode('utf-8'))


def _write_json(path, value):
    return _write_text(
        path, json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')


def _write_fake_wheel(path, distribution, version):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = (
        'Metadata-Version: 2.1\nName: {}\nVersion: {}\n'.format(
            distribution, version))
    dist_info = '{}-{}.dist-info'.format(distribution, version)
    with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr(dist_info + '/METADATA', metadata)
        archive.writestr(
            dist_info + '/WHEEL',
            'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
    return path


def _identity(path, relative_to=None):
    path = Path(path)
    rendered = str(path.resolve())
    if relative_to is not None:
        rendered = path.relative_to(relative_to).as_posix()
    return {
        'path': rendered,
        'size_bytes': path.stat().st_size,
        'sha256': _sha256_file(path),
    }


def _load_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))


def build_complete_ros1_source_workspace(root):
    """Create a complete synthetic ROS1 field runtime source workspace."""
    root = Path(root)
    workspace = root / 'ros1-source-workspace'
    contract = _load_contract()
    package_name = contract['package']['name']
    package_root = workspace / contract['package']['source_root']
    config_root = package_root / 'config'
    config_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        str(CONTRACT_PATH),
        str(config_root / CONTRACT_PATH.name))

    dependency_lines = '\n'.join(
        '  <{0}>{1}</{0}>'.format(tag, name)
        for tag, names in contract['package']['dependency_tags'].items()
        for name in names)
    package_xml = """<?xml version="1.0"?>
<package format="2">
  <name>{package_name}</name>
  <version>0.1.0</version>
  <description>Synthetic read-only ROS1 perception field runtime.</description>
  <maintainer email="test@example.com">Test</maintainer>
  <license>Apache-2.0</license>
  <buildtool_depend>catkin</buildtool_depend>
{dependencies}
  <export>
    <build_type>catkin</build_type>
  </export>
</package>
""".format(package_name=package_name, dependencies=dependency_lines)
    _write_text(package_root / 'package.xml', package_xml)

    component_lines = '\n  '.join(
        contract['package']['required_dependencies'])
    entrypoint_lines = '\n  '.join(
        contract['required_entrypoints'].values())
    launch_lines = '\n    '.join(
        'launch/' + name for name in contract['required_launch_files'])
    config_lines = '\n    '.join(
        'config/' + name for name in contract['required_config_files'])
    fixture_lines = '\n    '.join(
        'fixtures/' + name for name in contract['required_fixture_files'])
    catkin_test_lines = '\n  '.join(
        'catkin_add_nosetests(test/{})'.format(name)
        for name in contract['required_catkin_test_files'])
    message_names = [
        Path(name).name
        for name in contract['interface_modes'][
            'native_ros1_messages']['required_files']]
    cmake = """cmake_minimum_required(VERSION 3.0.2)
project({package_name})
find_package(catkin REQUIRED COMPONENTS
  {components}
)
add_message_files(
  FILES
  {messages}
)
generate_messages(
  DEPENDENCIES geometry_msgs std_msgs
)
catkin_python_setup()
catkin_package()
catkin_install_python(
  PROGRAMS
  {entrypoints}
  DESTINATION ${{CATKIN_PACKAGE_BIN_DESTINATION}}
)
install(
  FILES
    {config_files}
  DESTINATION ${{CATKIN_PACKAGE_SHARE_DESTINATION}}/config
)
install(
  FILES
    {fixture_files}
  DESTINATION ${{CATKIN_PACKAGE_SHARE_DESTINATION}}/fixtures
)
    install(
      FILES
        {launch_files}
      DESTINATION ${{CATKIN_PACKAGE_SHARE_DESTINATION}}/launch
    )
    install(
      FILES
        {message_files}
      DESTINATION ${{CATKIN_PACKAGE_SHARE_DESTINATION}}/msg
    )
if(CATKIN_ENABLE_TESTING)
  {catkin_tests}
endif()
""".format(
        package_name=package_name,
        components=component_lines,
        messages='\n  '.join(message_names),
        entrypoints=entrypoint_lines,
        launch_files=launch_lines,
        message_files='\n    '.join(
            'msg/' + name for name in message_names),
        config_files=config_lines,
        fixture_files=fixture_lines,
        catkin_tests=catkin_test_lines)
    _write_text(package_root / 'CMakeLists.txt', cmake)
    _write_text(
        package_root / 'setup.py',
        ("from setuptools import setup\n"
         "setup(name={!r}, version='0.1.0', "
         "install_requires={!r})\n").format(
             package_name,
             [item['requirement'] for item in contract[
                 'python_runtime_dependency_lock']['requirements']]))

    python_root = package_root / 'src' / package_name
    for module_name in contract['required_python_modules']:
        source = '# synthetic ROS1-only module\n'
        if module_name != '__init__.py':
            source += "MODULE_NAME = {!r}\n".format(module_name)
        _write_text(python_root / module_name, source)
    for entry_name, relative_path in contract['required_entrypoints'].items():
        _write_text(
            package_root / relative_path,
            '#!/usr/bin/env python3\nENTRYPOINT = {!r}\n'.format(entry_name))
    for name in contract['required_launch_files']:
        _write_text(
            package_root / 'launch' / name,
            '<?xml version="1.0"?>\n<launch>\n'
            '  <!-- synthetic read-only perception launch -->\n'
            '</launch>\n')

    capabilities = {
        name: True for name in contract['required_capabilities']}
    _write_json(
        config_root / 'capability_matrix.json',
        {'capabilities': capabilities})
    shutil.copyfile(
        str(MODEL_MANIFEST_PATH),
        str(config_root / 'model_bindings.json'))
    for name in contract['required_config_files']:
        path = config_root / name
        if not path.exists():
            _write_json(path, {'fixture': name, 'read_only': True})
    for name in contract['required_fixture_files']:
        _write_json(
            package_root / 'fixtures' / name,
            {'fixture': name, 'read_only': True})
    canonical_test_root = (
        WORKSPACE / 'ros1_overlay_src' /
        'limo_cleanup_ros1_perception' / 'test')
    for name in contract['required_catkin_test_files']:
        target = package_root / 'test' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(canonical_test_root / name), str(target))
    for relative_path in contract['interface_modes'][
            'native_ros1_messages']['required_files']:
        _write_text(
            package_root / relative_path,
            'std_msgs/Header header\nbool read_only\n')

    audit = perception_readiness.audit_ros1_noetic_field_source_contract(
        workspace=workspace)
    return {
        'workspace': workspace,
        'package_root': package_root,
        'contract': contract,
        'audit': audit,
    }


def _source_path_for_role(package_root, contract, role):
    if role == 'package:package.xml':
        return package_root / 'package.xml'
    prefix, value = role.split(':', 1)
    if prefix == 'python':
        return package_root / 'src' / contract['package']['name'] / value
    if prefix == 'entry':
        return package_root / contract['required_entrypoints'][value]
    if prefix == 'config':
        return package_root / 'config' / value
    if prefix == 'fixture':
        return package_root / 'fixtures' / value
    if prefix == 'launch':
        return package_root / 'launch' / value
    if prefix == 'interface':
        return package_root / value
    raise AssertionError('unknown install role: ' + role)


def build_valid_ros1_field_install_fixture(
        root, release_binding=None, model_paths=None, now=2000.0):
    """Build a complete, regular-file-only synthetic field-install proof.

    The returned ``evidence_path`` is suitable for direct validator use.  The
    report carries ``workspace_root`` and callers should not pass a synthetic
    ``source_audit`` override: the validator must live-audit this source tree.
    """
    root = Path(root)
    source = build_complete_ros1_source_workspace(root)
    # A synthetic install fixture can exercise install-evidence mechanics,
    # but it must not clear host-owned source anchors or the current formal
    # rosbag1 architecture blocker.  Keep the live fail-closed audit intact.
    contract = source['contract']
    source_audit = source['audit']
    contract_record = (
        perception_readiness.load_ros1_noetic_field_install_contract(
            source['workspace']))
    isolation_root_path = source['workspace']
    install_root = isolation_root_path / 'install'
    evidence_root = isolation_root_path / 'evidence'
    evidence_root.mkdir(parents=True, exist_ok=True)

    if release_binding is None:
        release_binding = {
            'release_id': 'synthetic-read-only-release-v1',
            'source_set_sha256': _sha256_bytes(b'synthetic-release-source'),
        }
    else:
        release_binding = copy.deepcopy(release_binding)

    expected_tests = perception_readiness._ros1_expected_catkin_test_ids(
        source['workspace'], contract, [])
    test_marker = (
        'LIMO_ROS1_CATKIN_TEST_IDS_SHA256=' +
        expected_tests['test_id_set_sha256'])
    logs = {}
    for name in ('build', 'install', 'test', 'test_result'):
        content = '{} completed without ROS graph startup\n'.format(name)
        if name == 'test_result':
            content += test_marker + '\n'
        path = _write_text(
            evidence_root / 'logs' / (name + '.log'),
            content)
        logs[name] = _identity(path, evidence_root)

    if model_paths is None:
        model_paths = {}
        for label in contract['model_manifest']['required_classes']:
            model_paths[label] = _write_bytes(
                evidence_root / 'input-models' / (label + '.bin'),
                (label + '-model-weights').encode('utf-8'))
    model_bindings = {}
    expected_model_hashes = {}
    for label in contract['model_manifest']['required_classes']:
        source_model = Path(model_paths[label])
        installed_model = evidence_root / 'models' / (label + '.bin')
        installed_model.parent.mkdir(parents=True, exist_ok=True)
        if source_model.resolve() != installed_model.resolve():
            shutil.copyfile(str(source_model), str(installed_model))
        model_bindings[label] = {
            'class_name': label,
            **_identity(installed_model, evidence_root),
        }
        expected_model_hashes[label] = _sha256_file(installed_model)

    runtime_dependency_inventory = []
    for dependency in contract[
            'python_runtime_dependency_lock']['requirements']:
        metadata_path = _write_text(
            install_root / 'lib' / 'python3' /
            'dist-packages' /
            ('{}-{}.dist-info'.format(
                dependency['distribution'],
                dependency['exact_version'])) / 'METADATA',
            'Metadata-Version: 2.1\nName: {}\nVersion: {}\n'.format(
                dependency['distribution'], dependency['exact_version']))
        module_origin = _write_text(
            install_root / 'lib' / 'python3' /
            'dist-packages' /
            dependency['import_name'] / '__init__.py',
            "__version__ = {!r}\n".format(dependency['exact_version']))
        wheel_filename = '{}-{}-py3-none-any.whl'.format(
            dependency['distribution'], dependency['exact_version'])
        distribution_artifact = _write_fake_wheel(
            evidence_root / 'runtime-artifacts' / wheel_filename,
            dependency['distribution'], dependency['exact_version'])
        runtime_dependency_inventory.append({
            'distribution': dependency['distribution'],
            'import_name': dependency['import_name'],
            'requirement': dependency['requirement'],
            'distribution_version': dependency['exact_version'],
            'module_version': dependency['exact_version'],
            'distribution_metadata': _identity(metadata_path),
            'module_origin': _identity(module_origin),
            'distribution_artifact': {
                'filename': wheel_filename,
                'format': 'wheel',
                **_identity(distribution_artifact),
            },
        })

    application_root = install_root / 'lib' / 'python3' / 'dist-packages'
    provisioning_commands = {}
    for item in runtime_dependency_inventory:
        distribution = item['distribution']
        artifact_path = Path(item['distribution_artifact']['path']).resolve()
        log_path = _write_text(
            evidence_root / 'logs' /
            ('runtime-provisioning-' + distribution + '.log'),
            'offline isolated provisioning completed for {}\n'.format(
                distribution))
        provisioning_commands[distribution] = {
            'argv': [
                str(Path(sys.executable).resolve()), '-m', 'pip', '--isolated',
                'install', '--no-index', '--no-deps', '--no-compile',
                '--target', str(application_root.resolve()),
                str(artifact_path)],
            'exit_code': 0,
            'log': _identity(log_path),
        }
    runtime_provisioning = {
        'schema_version': 1,
        'strategy': 'offline_wheels_no_index_no_deps_target',
        'application_root_relative': 'install/lib/python3/dist-packages',
        'python_executable': _identity(Path(sys.executable).resolve()),
        'commands': provisioning_commands,
    }

    junit_artifacts = []
    result_root = isolation_root_path / 'build' / 'test_results'
    for module, test_ids in expected_tests['by_module'].items():
        testcases = ''.join(
            '  <testcase classname="{}" name="{}"/>\n'.format(
                test_id.rsplit('.', 1)[0], test_id.rsplit('.', 1)[1])
            for test_id in test_ids)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<testsuite name="{0}" tests="{1}" failures="0" '
            'errors="0" skipped="0">\n{2}</testsuite>\n').format(
                module, len(test_ids), testcases)
        junit_path = _write_text(result_root / (module + '.xml'), xml)
        junit_artifacts.append(_identity(junit_path))
    catkin_test_results = {
        'schema_version': 1,
        'junit_xml_artifacts': junit_artifacts,
    }

    interface_mode = 'native_ros1_messages'
    required_roles = perception_readiness._ros1_required_install_roles(
        contract, interface_mode)
    artifacts = []
    canonical = []
    for role, installed_relative_path in required_roles.items():
        source_path = _source_path_for_role(
            source['package_root'], contract, role)
        installed_path = install_root / installed_relative_path
        installed_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source_path), str(installed_path))
        identity = _identity(installed_path)
        artifact = {
            'role': role,
            **identity,
            'installed_relative_path': installed_relative_path,
            'source_sha256': _sha256_file(source_path),
            'regular_file': True,
            'linklike': False,
        }
        artifacts.append(artifact)
        canonical.append({
            'role': role,
            'installed_relative_path': installed_relative_path,
            'size_bytes': identity['size_bytes'],
            'sha256': identity['sha256'],
        })
    artifacts.sort(key=lambda item: item['role'])
    canonical.sort(key=lambda item: item['role'])

    artifacts_by_role = {item['role']: item for item in artifacts}

    def installed_import_record(role, module):
        artifact = artifacts_by_role[role]
        return {
            'module': module,
            'import_succeeded': True,
            'installed_relative_path': artifact['installed_relative_path'],
            'path': artifact['path'],
            'size_bytes': artifact['size_bytes'],
            'sha256': artifact['sha256'],
        }

    package_name = contract['package']['name']
    entry_module_files = {
        'dual_model_detector': 'dual_model_detector.py',
        'perception_frame_adapter': 'ros1_adapter.py',
        'perception_frame_collector': 'perception_frame_collector.py',
        'perception_readiness': 'perception_readiness.py',
        'rosbag1_rgbd_indexer': 'rosbag1_rgbd_indexer.py',
        'typed_raw_binding': 'typed_raw_binding.py',
    }
    entrypoint_imports = {}
    for entry_name, filename in entry_module_files.items():
        module_stem = Path(filename).stem
        entrypoint_imports[entry_name] = installed_import_record(
            'python:' + filename,
            '{}.{}'.format(package_name, module_stem))

    generated_root = (
        install_root / 'lib' / 'python3' / 'dist-packages' /
        package_name / 'msg')
    generated_message_imports = {}
    message_names = ('ObjectDetection', 'PerceptionFrame', 'PerceptionTarget')
    for message_name in message_names:
        relative = (
            'lib/python3/dist-packages/{}/msg/_{}.py'.format(
                package_name, message_name))
        generated_path = _write_text(
            install_root / relative,
            'class {}:\n    pass\n'.format(message_name))
        generated_message_imports[message_name] = {
            'module': '{}.msg._{}'.format(package_name, message_name),
            'import_succeeded': True,
            'installed_relative_path': relative,
            **_identity(generated_path),
        }
    generated_package_relative = (
        'lib/python3/dist-packages/{}/msg/__init__.py'.format(package_name))
    generated_package_path = _write_text(
        install_root / generated_package_relative,
        ''.join(
            'from ._{0} import {0}\n'.format(name)
            for name in message_names))
    generated_message_package_import = {
        'module': package_name + '.msg',
        'import_succeeded': True,
        'installed_relative_path': generated_package_relative,
        **_identity(generated_package_path),
    }
    import_smoke = {
        'schema_version': 1,
        'probe_kind': 'ROS1_NOETIC_ISOLATED_PREFIX_IMPORT_SMOKE',
        'workspace_source_removed': True,
        'ros_graph_started': False,
        'fake_ros_api': True,
        'sys_path_relative': ['install/lib/python3/dist-packages'],
        'probe_exit_code': 0,
        'import_failures': [],
        'package_import': installed_import_record(
            'python:__init__.py', package_name),
        'entrypoint_imports': entrypoint_imports,
        'generated_message_package_import': (
            generated_message_package_import),
        'generated_message_imports': generated_message_imports,
    }

    isolation_root = str(isolation_root_path.resolve())
    report = {
        'schema_version': 1,
        'gate_id': perception_readiness.ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'result': 'PASS',
        'generated_at_unix_sec': float(now),
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'nodes_started': False,
        'camera_opened': False,
        'hardware_connected': False,
        'runtime': {
            'ros_major': 1,
            'ros_distro': 'noetic',
            'python': '3.8.10',
            'machine': 'synthetic-offline-host',
        },
        'environment': {
            name: True
            for name in contract['install_policy'][
                'required_environment_flags']
        },
        'implementation': {
            'mode': interface_mode,
            'complete_runtime': True,
            'architecture_blockers': [],
            'capabilities': contract['required_capabilities'],
        },
        'packages': [contract['package']['name']],
        'dependencies': contract['package']['required_dependencies'],
        'runtime_dependency_inventory': runtime_dependency_inventory,
        'runtime_provisioning': runtime_provisioning,
        'catkin_test_results': catkin_test_results,
        'import_smoke': import_smoke,
        'workspace_root': str(source['workspace'].resolve()),
        'source_binding': {
            'release_id': release_binding['release_id'],
            'release_source_set_sha256': release_binding[
                'source_set_sha256'],
            'ros1_source_set_sha256': source_audit['source_set_sha256'],
            'contract_sha256': contract_record['sha256'],
        },
        'source_contract': {
            'passed': True,
            'source_set_sha256': source_audit['source_set_sha256'],
            'contract_sha256': contract_record['sha256'],
            'architecture_blockers': [],
        },
        'model_bindings': model_bindings,
        'isolation_root': isolation_root,
        'commands': perception_readiness._isolated_catkin_argv(
            isolation_root),
        'exit_codes': contract['install_policy']['required_exit_codes'],
        'test_failures': 0,
        'logs': logs,
        'installed_artifacts': artifacts,
        'install_set_sha256': (
            perception_readiness._canonical_identity_set_sha256(canonical)),
    }
    evidence_path = _write_json(
        evidence_root / 'ros1-noetic-field-install.json', report)
    canonical_source_binding = (
        perception_readiness.make_ros1_canonical_source_binding(
            workspace=source['workspace'],
            source_audit=source_audit,
            test_only=True))
    return {
        'declaration': _identity(evidence_path),
        'evidence_path': evidence_path,
        'report': report,
        'workspace': source['workspace'],
        'source': source,
        'release_binding': release_binding,
        'expected_model_hashes': expected_model_hashes,
        'canonical_source_binding': canonical_source_binding,
        'now_unix_sec': float(now),
    }


def _rewrite_fixture_report(fixture, report):
    fixture['report'] = report
    _write_json(fixture['evidence_path'], report)


def _refresh_install_set(report):
    canonical = [{
        'role': item['role'],
        'installed_relative_path': item['installed_relative_path'],
        'size_bytes': item['size_bytes'],
        'sha256': item['sha256'],
    } for item in report['installed_artifacts']]
    canonical.sort(key=lambda item: item['role'])
    report['install_set_sha256'] = (
        perception_readiness._canonical_identity_set_sha256(canonical))


def _validate(
        fixture,
        canonical_source_binding=_USE_FIXTURE_CANONICAL_BINDING,
        allow_test_synthetic_binding=None):
    if canonical_source_binding is _USE_FIXTURE_CANONICAL_BINDING:
        canonical_source_binding = fixture['canonical_source_binding']
        if allow_test_synthetic_binding is None:
            allow_test_synthetic_binding = True
    elif allow_test_synthetic_binding is None:
        allow_test_synthetic_binding = False
    return perception_readiness.validate_ros1_noetic_field_install_evidence(
        fixture['evidence_path'],
        release_binding=fixture['release_binding'],
        expected_model_hashes=fixture['expected_model_hashes'],
        now_unix_sec=fixture['now_unix_sec'],
        workspace=fixture['workspace'],
        canonical_source_binding=canonical_source_binding,
        allow_test_synthetic_binding=allow_test_synthetic_binding)


class Ros1FieldInstallGateTest(unittest.TestCase):

    def test_host_fresh_import_probe_executes_and_binds_evidence_module(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_valid_ros1_field_install_fixture(root / 'valid')
            validation = _validate(fixture)
            probe = validation['fresh_import_probe']
            self.assertTrue(probe['validated_pass'], probe)
            self.assertEqual(0, probe['exit_code'])
            self.assertEqual([], probe['failures'])
            modules = {
                item['module'] for item in probe['result']['modules']}
            self.assertIn(
                'limo_cleanup_ros1_perception.evidence_binding', modules)

            fixture = build_valid_ros1_field_install_fixture(root / 'raise')
            report = copy.deepcopy(fixture['report'])
            artifact = next(item for item in report['installed_artifacts']
                            if item['role'] == 'python:evidence_binding.py')
            installed_path = Path(artifact['path'])
            installed_path.write_text(
                installed_path.read_text(encoding='utf-8')
                + '\nraise RuntimeError("import-time failure")\n',
                encoding='utf-8')
            artifact.update(_identity(installed_path))
            _refresh_install_set(report)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_fresh_import_probe_module_invalid:'
                'runtime:evidence_binding', validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'dependency-raise')
            report = copy.deepcopy(fixture['report'])
            dependency = next(item for item in report[
                'runtime_dependency_inventory']
                              if item['distribution'] == 'numpy')
            origin_path = Path(dependency['module_origin']['path'])
            origin_path.write_text(
                origin_path.read_text(encoding='utf-8')
                + 'raise RuntimeError("after correct version")\n',
                encoding='utf-8')
            dependency['module_origin'] = _identity(origin_path)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_fresh_import_probe_dependency_invalid:numpy',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'extra')
            report = copy.deepcopy(fixture['report'])
            package_root = (
                Path(report['isolation_root']) / 'install' / 'lib' /
                'python3' / 'dist-packages' /
                fixture['source']['contract']['package']['name'])
            _write_text(package_root / 'undeclared_runtime.py', 'VALUE = 1\n')
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertTrue(any(
                item.startswith('ros1_field_install_actual_set_invalid:')
                for item in validation['failures']), validation['failures'])

    def test_distribution_artifact_and_junit_are_host_recomputed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            fixture = build_valid_ros1_field_install_fixture(root / 'wheel')
            report = copy.deepcopy(fixture['report'])
            numpy_entry = next(item for item in report[
                'runtime_dependency_inventory']
                               if item['distribution'] == 'numpy')
            Path(numpy_entry['distribution_artifact']['path']).unlink()
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_runtime_dependency_distribution_artifact_'
                'provenance_unavailable:numpy', validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'zero')
            report = copy.deepcopy(fixture['report'])
            declaration = report['catkin_test_results'][
                'junit_xml_artifacts'][0]
            xml_path = Path(declaration['path'])
            _write_text(
                xml_path,
                '<testsuite name="empty" tests="0" failures="0" '
                'errors="0" skipped="0"/>\n')
            declaration.update(_identity(xml_path))
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_catkin_test_id_set_mismatch',
                validation['failures'])
            self.assertIn(
                'ros1_field_catkin_test_count_mismatch',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'marker')
            report = copy.deepcopy(fixture['report'])
            marker = (
                'LIMO_ROS1_CATKIN_TEST_IDS_SHA256=' +
                perception_readiness._ros1_expected_catkin_test_ids(
                    fixture['workspace'], fixture['source']['contract'], [])[
                        'test_id_set_sha256'])
            log_path = (
                fixture['evidence_path'].parent /
                report['logs']['test_result']['path'])
            with log_path.open('a', encoding='utf-8') as stream:
                stream.write(marker + '\n')
            report['logs']['test_result'] = _identity(
                log_path, fixture['evidence_path'].parent)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_catkin_test_marker_invalid',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'failure')
            report = copy.deepcopy(fixture['report'])
            declaration = report['catkin_test_results'][
                'junit_xml_artifacts'][0]
            xml_path = Path(declaration['path'])
            xml = xml_path.read_text(encoding='utf-8')
            xml = xml.replace('failures="0"', 'failures="1"', 1)
            xml = xml.replace('/>', '><failure/></testcase>', 1)
            xml_path.write_text(xml, encoding='utf-8')
            declaration.update(_identity(xml_path))
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_catkin_tests_failed', validation['failures'])

    def test_build_source_space_is_exactly_the_audited_isolation_root(self):
        with TemporaryDirectory() as directory:
            fixture = build_valid_ros1_field_install_fixture(directory)
            report = copy.deepcopy(fixture['report'])
            _write_text(
                Path(report['isolation_root']) / 'src' / 'foreign_package' /
                'CMakeLists.txt', 'project(foreign_package)\n')
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertIn(
                'ros1_field_install_source_space_unbound',
                validation['failures'])
            self.assertIn(
                '--source', report['commands']['build_argv'])
            self.assertIn(
                str(Path(report['isolation_root']).resolve()).replace(
                    '\\', '/') + '/ros1_overlay_src',
                report['commands']['build_argv'])

    def test_indexer_only_source_package_is_architecture_blocked(self):
        with TemporaryDirectory() as directory:
            source = build_complete_ros1_source_workspace(Path(directory))
            contract = source['contract']
            package_root = source['package_root']
            package_name = contract['package']['name']
            keep_modules = {'__init__.py', 'rosbag1_rgbd_indexer.py'}
            for path in (package_root / 'src' / package_name).glob('*.py'):
                if path.name not in keep_modules:
                    path.unlink()
            keep_entries = {'rosbag1_rgbd_indexer.py'}
            for path in (package_root / 'scripts').glob('*.py'):
                if path.name not in keep_entries:
                    path.unlink()

            audit = (
                perception_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=source['workspace']))

            self.assertFalse(audit['pass'])
            self.assertTrue(audit['indexer_only_detected'])
            self.assertIn('ros1_field_indexer_only_package', audit['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                audit['architecture_blockers'])

    def test_source_contract_rejects_missing_required_assets(self):
        cases = (
            (
                'module',
                lambda source: source['package_root'] / 'src' /
                source['contract']['package']['name'] /
                source['contract']['required_python_modules'][1],
                'ros1_field_source_missing:src/{}/{}'.format(
                    _load_contract()['package']['name'],
                    _load_contract()['required_python_modules'][1])),
            (
                'fixture',
                lambda source: source['package_root'] / 'fixtures' /
                source['contract']['required_fixture_files'][0],
                'ros1_field_source_missing:fixtures/' +
                _load_contract()['required_fixture_files'][0]),
            (
                'entrypoint',
                lambda source: source['package_root'] /
                next(iter(
                    source['contract']['required_entrypoints'].values())),
                'ros1_field_source_missing:' +
                next(iter(_load_contract()['required_entrypoints'].values()))),
            (
                'launch',
                lambda source: source['package_root'] / 'launch' /
                source['contract']['required_launch_files'][0],
                'ros1_field_source_missing:launch/' +
                _load_contract()['required_launch_files'][0]),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, path_factory, expected_failure in cases:
                with self.subTest(case=name):
                    source = build_complete_ros1_source_workspace(root / name)
                    path_factory(source).unlink()
                    audit = (
                        perception_readiness.
                        audit_ros1_noetic_field_source_contract(
                            workspace=source['workspace']))
                    self.assertFalse(audit['pass'])
                    self.assertIn(expected_failure, audit['failures'])

            source = build_complete_ros1_source_workspace(root / 'dependency')
            package_xml = source['package_root'] / 'package.xml'
            dependency = source['contract']['package'][
                'required_dependencies'][0]
            text = package_xml.read_text(encoding='utf-8').replace(
                '  <depend>{}</depend>\n'.format(dependency), '')
            package_xml.write_text(text, encoding='utf-8')
            audit = (
                perception_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=source['workspace']))
            self.assertFalse(audit['pass'])
            self.assertIn(
                'ros1_field_dependency_missing:' + dependency,
                audit['failures'])

    def test_source_contract_rejects_rclpy_and_ament_only_runtime(self):
        with TemporaryDirectory() as directory:
            source = build_complete_ros1_source_workspace(Path(directory))
            module = (
                source['package_root'] / 'src' /
                source['contract']['package']['name'] /
                source['contract']['required_python_modules'][1])
            module.write_text('import rclpy\n', encoding='utf-8')
            package_xml = source['package_root'] / 'package.xml'
            package_xml.write_text(
                package_xml.read_text(encoding='utf-8').replace(
                    '  <export>\n',
                    '  <depend>rclpy</depend>\n'
                    '  <depend>ament_python</depend>\n'
                    '  <export>\n'),
                encoding='utf-8')

            audit = (
                perception_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=source['workspace']))

            self.assertFalse(audit['pass'])
            self.assertIn(
                'ros1_field_forbidden_dependency:rclpy', audit['failures'])
            self.assertIn(
                'ros1_field_forbidden_dependency:ament_python',
                audit['failures'])
            self.assertIn(
                'ros1_field_ros2_runtime_token:import_rclpy',
                audit['failures'])

    def test_validator_rejects_ros2_ament_prefix_masquerading_as_ros1(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_valid_ros1_field_install_fixture(root / 'ros2')
            report = copy.deepcopy(fixture['report'])
            report['runtime']['ros_major'] = 2
            report['runtime']['ros_distro'] = 'foxy'
            report['isolation_root'] = '/tmp/limo_v2_ros2_ament_fake'
            report['commands'] = {
                'build_argv': ['colcon', 'build'],
                'test_argv': ['colcon', 'test'],
                'test_result_argv': ['colcon', 'test-result'],
                'install_argv': ['colcon', 'build', '--symlink-install'],
            }
            _rewrite_fixture_report(fixture, report)

            validation = _validate(fixture)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_install_runtime_invalid', validation['failures'])
            self.assertIn(
                'ros1_field_install_isolation_invalid', validation['failures'])
            self.assertIn(
                'ros1_field_install_command_mismatch', validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'evidence_override')
            report = copy.deepcopy(fixture['report'])
            evidence_override = _sha256_bytes(b'evidence-cannot-override')
            report['source_binding'][
                'ros1_source_set_sha256'] = evidence_override
            report['source_contract']['source_set_sha256'] = evidence_override
            _rewrite_fixture_report(fixture, report)

            validation = _validate(fixture)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(CANONICAL_BINDING_MISMATCH, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])

    def test_validator_rejects_linklike_or_non_regular_artifact(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_valid_ros1_field_install_fixture(root / 'declared')
            report = copy.deepcopy(fixture['report'])
            artifact = report['installed_artifacts'][0]
            artifact['regular_file'] = False
            artifact['linklike'] = True
            role = artifact['role']
            _rewrite_fixture_report(fixture, report)

            validation = _validate(fixture)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_install_regular_copy_invalid:' + role,
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'actual')
            artifact = fixture['report']['installed_artifacts'][0]
            installed_path = (
                fixture['evidence_path'].parent / artifact['path']).resolve()
            original_link_check = perception_readiness._path_is_linklike

            def simulated_link_check(path):
                if Path(path).resolve() == installed_path:
                    return True
                return original_link_check(path)

            with patch.object(
                    perception_readiness, '_path_is_linklike',
                    side_effect=simulated_link_check):
                validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_evidence_link_forbidden:installed:' +
                artifact['role'], validation['failures'])

            binding_cases = []
            fixture = build_valid_ros1_field_install_fixture(
                root / 'binding_tamper')
            bad_binding_hash = copy.deepcopy(
                fixture['canonical_source_binding'])
            bad_binding_hash['binding_sha256'] = '0' * 64
            binding_cases.append(('binding_hash', bad_binding_hash))
            bad_entry = copy.deepcopy(fixture['canonical_source_binding'])
            bad_entry['entries'][0]['sha256'] = '1' * 64
            binding_cases.append(('entry', bad_entry))
            for name, binding in binding_cases:
                with self.subTest(canonical_tamper=name):
                    validation = _validate(
                        fixture,
                        canonical_source_binding=binding,
                        allow_test_synthetic_binding=True)
                    self.assertFalse(validation['validated_pass'])
                    self.assertIn(
                        CANONICAL_BINDING_INVALID, validation['failures'])
                    self.assertIn(
                        perception_readiness.
                        ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                        validation['architecture_blockers'])

    def test_formal_capture_launch_install_is_exact_regular_and_closed(self):
        role = 'launch:perception_v2_formal_capture.launch'
        with TemporaryDirectory() as directory:
            root = Path(directory)

            fixture = build_valid_ros1_field_install_fixture(root / 'missing')
            artifact = next(
                item for item in fixture['report']['installed_artifacts']
                if item['role'] == role)
            installed_path = Path(artifact['path'])
            installed_path.unlink()
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_evidence_file_missing:installed:' + role,
                validation['failures'])
            self.assertIn(
                'ros1_field_install_actual_set_invalid:share/'
                'limo_cleanup_ros1_perception/launch',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'extra')
            extra_path = (
                fixture['workspace'] / 'install/share/'
                'limo_cleanup_ros1_perception/launch/unreviewed.launch')
            _write_text(extra_path, '<?xml version="1.0"?>\n<launch/>\n')
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_install_actual_set_invalid:share/'
                'limo_cleanup_ros1_perception/launch',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(root / 'link')
            artifact = next(
                item for item in fixture['report']['installed_artifacts']
                if item['role'] == role)
            installed_path = Path(artifact['path']).resolve()
            original_link_check = perception_readiness._path_is_linklike

            def simulated_formal_launch_link(path):
                if Path(path).resolve() == installed_path:
                    return True
                return original_link_check(path)

            with patch.object(
                    perception_readiness, '_path_is_linklike',
                    side_effect=simulated_formal_launch_link):
                validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_evidence_link_forbidden:installed:' + role,
                validation['failures'])

    def test_validator_rejects_installed_artifact_hash_mismatch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_valid_ros1_field_install_fixture(
                root / 'installed')
            artifact = fixture['report']['installed_artifacts'][0]
            installed_path = fixture['evidence_path'].parent / artifact['path']
            original = installed_path.read_bytes()
            replacement = bytes([original[0] ^ 1]) + original[1:]
            installed_path.write_bytes(replacement)

            validation = _validate(fixture)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_evidence_hash_mismatch:installed:' +
                artifact['role'], validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'source_copy')
            module = (
                fixture['source']['package_root'] / 'src' /
                fixture['source']['contract']['package']['name'] /
                fixture['source']['contract']['required_python_modules'][1])
            module.write_text(
                module.read_text(encoding='utf-8') +
                'COPY_CHANGED_AFTER_CANONICAL_BINDING = True\n',
                encoding='utf-8')

            validation = _validate(fixture)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(CANONICAL_BINDING_MISMATCH, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])

    def test_validator_recomputes_runtime_dependency_inventory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            fixture = build_valid_ros1_field_install_fixture(
                root / 'missing')
            report = copy.deepcopy(fixture['report'])
            report.pop('runtime_dependency_inventory')
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_install_evidence_schema_invalid',
                validation['failures'])
            self.assertIn(
                'ros1_field_runtime_dependency_inventory_invalid',
                validation['failures'])

            for field in ('distribution_version', 'module_version'):
                fixture = build_valid_ros1_field_install_fixture(
                    root / ('wrong-' + field))
                report = copy.deepcopy(fixture['report'])
                entry = next(item for item in report[
                    'runtime_dependency_inventory']
                             if item['distribution'] == 'torch')
                entry[field] = '1.10.1'
                _rewrite_fixture_report(fixture, report)
                validation = _validate(fixture)
                self.assertFalse(validation['validated_pass'])
                self.assertIn(
                    'ros1_field_runtime_dependency_inventory_invalid:torch',
                    validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'metadata-semantic')
            report = copy.deepcopy(fixture['report'])
            entry = next(item for item in report[
                'runtime_dependency_inventory']
                         if item['distribution'] == 'torch')
            metadata_path = (
                fixture['evidence_path'].parent /
                entry['distribution_metadata']['path'])
            metadata_path.write_text(
                'Metadata-Version: 2.1\nName: torch\nVersion: 1.10.1\n',
                encoding='utf-8')
            entry['distribution_metadata'] = _identity(metadata_path)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_runtime_dependency_metadata_invalid:torch',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'module-version-semantic')
            report = copy.deepcopy(fixture['report'])
            entry = next(item for item in report[
                'runtime_dependency_inventory']
                         if item['distribution'] == 'numpy')
            origin_path = (
                fixture['evidence_path'].parent /
                entry['module_origin']['path'])
            origin_path.write_text(
                "__version__ = '1.19.4'\n", encoding='utf-8')
            entry['module_origin'] = _identity(origin_path)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_fresh_import_probe_dependency_invalid:numpy',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'module-origin-path')
            report = copy.deepcopy(fixture['report'])
            entry = next(item for item in report[
                'runtime_dependency_inventory']
                         if item['distribution'] == 'numpy')
            old_origin = (
                fixture['evidence_path'].parent /
                entry['module_origin']['path'])
            stale_origin = _write_bytes(
                fixture['evidence_path'].parent / 'runtime-dependencies' /
                'modules' / 'stale_numpy' / '__init__.py',
                old_origin.read_bytes())
            entry['module_origin'] = _identity(stale_origin)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_runtime_dependency_module_origin_invalid:numpy',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'metadata-origin-path')
            report = copy.deepcopy(fixture['report'])
            entry = next(item for item in report[
                'runtime_dependency_inventory']
                         if item['distribution'] == 'torch')
            old_metadata = (
                fixture['evidence_path'].parent /
                entry['distribution_metadata']['path'])
            stale_metadata = _write_bytes(
                fixture['evidence_path'].parent / 'runtime-dependencies' /
                'torch-stale.dist-info' / 'METADATA',
                old_metadata.read_bytes())
            entry['distribution_metadata'] = _identity(stale_metadata)
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_runtime_dependency_metadata_invalid:torch',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'module-origin-link')
            entry = next(item for item in fixture['report'][
                'runtime_dependency_inventory']
                         if item['distribution'] == 'numpy')
            origin_path = (
                fixture['evidence_path'].parent /
                entry['module_origin']['path']).resolve()
            original_link_check = perception_readiness._path_is_linklike

            def simulated_origin_link(path):
                if Path(path).resolve() == origin_path:
                    return True
                return original_link_check(path)

            with patch.object(
                    perception_readiness, '_path_is_linklike',
                    side_effect=simulated_origin_link):
                validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_evidence_link_forbidden:'
                'runtime_dependency_module_origin:numpy',
                validation['failures'])

    def test_validator_requires_isolated_prefix_import_smoke(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)

            fixture = build_valid_ros1_field_install_fixture(
                root / 'missing-generated')
            report = copy.deepcopy(fixture['report'])
            report['import_smoke']['generated_message_imports'].pop(
                'PerceptionTarget')
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn('ros1_field_import_smoke_invalid',
                          validation['failures'])
            self.assertIn(
                'ros1_field_import_smoke_origin_invalid:'
                'generated_message:PerceptionTarget',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'missing-entry')
            report = copy.deepcopy(fixture['report'])
            report['import_smoke']['entrypoint_imports'].pop(
                'perception_frame_adapter')
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn('ros1_field_import_smoke_invalid',
                          validation['failures'])
            self.assertIn(
                'ros1_field_import_smoke_origin_invalid:'
                'entrypoint:perception_frame_adapter',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'workspace-origin')
            report = copy.deepcopy(fixture['report'])
            workspace_origin = (
                fixture['source']['package_root'] / 'src' /
                fixture['source']['contract']['package']['name'] /
                '__init__.py')
            package_import = report['import_smoke']['package_import']
            package_import.update(_identity(workspace_origin))
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_import_smoke_origin_invalid:package',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'stale-devel')
            report = copy.deepcopy(fixture['report'])
            generated = report['import_smoke'][
                'generated_message_imports']['ObjectDetection']
            generated_path = (
                fixture['evidence_path'].parent / generated['path'])
            stale_path = _write_bytes(
                fixture['evidence_path'].parent / 'devel' / 'lib' /
                'python3' / 'dist-packages' /
                fixture['source']['contract']['package']['name'] / 'msg' /
                '_ObjectDetection.py', generated_path.read_bytes())
            generated.update(_identity(stale_path))
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(
                'ros1_field_import_smoke_origin_invalid:'
                'generated_message:ObjectDetection',
                validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'workspace-not-removed')
            report = copy.deepcopy(fixture['report'])
            report['import_smoke']['workspace_source_removed'] = False
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn('ros1_field_import_smoke_invalid',
                          validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'bool-exit-code')
            report = copy.deepcopy(fixture['report'])
            report['import_smoke']['probe_exit_code'] = False
            _rewrite_fixture_report(fixture, report)
            validation = _validate(fixture)
            self.assertFalse(validation['validated_pass'])
            self.assertIn('ros1_field_import_smoke_invalid',
                          validation['failures'])

    def test_validator_rejects_unentered_environment_and_exit_mismatch(self):
        mutations = (
            (
                'shell_not_entered',
                lambda report: report['environment'].__setitem__(
                    'shell_entered', False),
                'ros1_field_install_environment_not_entered'),
            (
                'build_not_started',
                lambda report: report['environment'].__setitem__(
                    'build_started', False),
                'ros1_field_install_environment_not_entered'),
            (
                'build_exit_nonzero',
                lambda report: report['exit_codes'].__setitem__('build', 1),
                'ros1_field_install_exit_code_failure'),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, mutate, expected_failure in mutations:
                with self.subTest(case=name):
                    fixture = build_valid_ros1_field_install_fixture(
                        root / name)
                    report = copy.deepcopy(fixture['report'])
                    mutate(report)
                    _rewrite_fixture_report(fixture, report)
                    validation = _validate(fixture)
                    self.assertFalse(validation['validated_pass'])
                    self.assertIn(expected_failure, validation['failures'])

            fixture = build_valid_ros1_field_install_fixture(
                root / 'missing_canonical')
            validation = _validate(
                fixture, canonical_source_binding=None,
                allow_test_synthetic_binding=False)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(CANONICAL_BINDING_MISSING, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])

    def test_validator_live_audit_rejects_indexer_only_workspace(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_valid_ros1_field_install_fixture(root / 'valid')
            indexer = build_complete_ros1_source_workspace(root / 'indexer')
            contract = indexer['contract']
            package_root = indexer['package_root']
            package_name = contract['package']['name']
            for path in (package_root / 'src' / package_name).glob('*.py'):
                if path.name not in {'__init__.py', 'rosbag1_rgbd_indexer.py'}:
                    path.unlink()
            for path in (package_root / 'scripts').glob('*.py'):
                if path.name != 'rosbag1_rgbd_indexer.py':
                    path.unlink()
            report = copy.deepcopy(fixture['report'])
            report['workspace_root'] = str(indexer['workspace'].resolve())
            _rewrite_fixture_report(fixture, report)

            validation = _validate(fixture)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(CANONICAL_BINDING_MISMATCH, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])

            project_binding = (
                perception_readiness.make_ros1_canonical_source_binding(
                    workspace=WORKSPACE, test_only=False))
            project_audit = (
                perception_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=WORKSPACE))
            self.assertIs(
                project_binding['source_contract_pass'],
                project_audit['pass'])
            self.assertFalse(project_binding['indexer_only_detected'])
            self.assertEqual(
                project_audit['architecture_blockers'],
                project_binding['architecture_blockers'])
            indexer_audit = (
                perception_readiness.audit_ros1_noetic_field_source_contract(
                    workspace=indexer['workspace']))
            indexer_binding = (
                perception_readiness.make_ros1_canonical_source_binding(
                    workspace=indexer['workspace'],
                    source_audit=indexer_audit,
                    test_only=True))
            self.assertFalse(indexer_binding['source_contract_pass'])
            self.assertTrue(indexer_binding['indexer_only_detected'])
            fixture = build_valid_ros1_field_install_fixture(
                root / 'foreign_complete')

            validation = _validate(
                fixture,
                canonical_source_binding=indexer_binding,
                allow_test_synthetic_binding=True)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(CANONICAL_BINDING_MISMATCH, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])

    def test_complete_synthetic_install_cannot_clear_runtime_blocker(self):
        with TemporaryDirectory() as directory:
            fixture = build_valid_ros1_field_install_fixture(directory)

            validation = _validate(
                fixture,
                canonical_source_binding=fixture[
                    'canonical_source_binding'],
                allow_test_synthetic_binding=True)

            self.assertEqual(sorted({
                TEST_ONLY_SOURCE_BINDING,
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
            }), validation['failures'])
            self.assertFalse(validation['validated_pass'])
            self.assertEqual(
                perception_readiness.ROS1_FIELD_INSTALL_GATE_ID,
                validation['gate_id'])
            self.assertTrue(validation['test_only_synthetic_binding'])
            self.assertFalse(validation['canonical_runtime_complete'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])
            self.assertGreater(validation['installed_artifact_count'], 20)

            # Even a future synthetic source audit that claims every runtime
            # capability must remain mechanically test-only and blocked.
            passing_audit = copy.deepcopy(fixture['source']['audit'])
            passing_audit.update({
                'pass': True,
                'complete_runtime': True,
                'indexer_only_detected': False,
                'architecture_blockers': [],
                'failures': [],
            })
            passing_binding = (
                perception_readiness.make_ros1_canonical_source_binding(
                    workspace=fixture['workspace'],
                    source_audit=passing_audit,
                    test_only=True))
            with patch.object(
                    perception_readiness,
                    'audit_ros1_noetic_field_source_contract',
                    return_value=passing_audit):
                passing_validation = _validate(
                    fixture,
                    canonical_source_binding=passing_binding,
                    allow_test_synthetic_binding=True)
            self.assertEqual(sorted({
                TEST_ONLY_SOURCE_BINDING,
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
            }), passing_validation['failures'])
            self.assertFalse(passing_validation['validated_pass'])
            self.assertFalse(passing_validation['canonical_runtime_complete'])

            # A foreign synthetic binding cannot become production merely by
            # changing its marker and recomputing its self-consistent hash.
            foreign_production = copy.deepcopy(passing_binding)
            foreign_production['test_only'] = False
            foreign_production['binding_kind'] = 'canonical_project_overlay'
            foreign_identity = dict(foreign_production)
            foreign_identity.pop('binding_sha256')
            foreign_production['binding_sha256'] = (
                perception_readiness._canonical_json_sha256(
                    foreign_identity))
            with patch.object(
                    perception_readiness,
                    'audit_ros1_noetic_field_source_contract',
                    return_value=passing_audit):
                foreign_validation = _validate(
                    fixture,
                    canonical_source_binding=foreign_production,
                    allow_test_synthetic_binding=False)
            self.assertFalse(foreign_validation['validated_pass'])
            self.assertIn(
                CANONICAL_BINDING_MISMATCH,
                foreign_validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                foreign_validation['architecture_blockers'])

            # Supplying a forged audit to the production binding constructor
            # cannot replace the live host-owned canonical project audit.
            forged_project_audit = copy.deepcopy(passing_audit)
            forged_project_audit['workspace_root'] = str(WORKSPACE)
            expected_project_binding = (
                perception_readiness.make_ros1_canonical_source_binding(
                    workspace=WORKSPACE, test_only=False))
            actual_project_binding = (
                perception_readiness.make_ros1_canonical_source_binding(
                    workspace=WORKSPACE,
                    source_audit=forged_project_audit,
                    test_only=False))
            self.assertEqual(
                expected_project_binding, actual_project_binding)

            validation = _validate(
                fixture,
                canonical_source_binding=fixture[
                    'canonical_source_binding'],
                allow_test_synthetic_binding=False)
            self.assertFalse(validation['validated_pass'])
            self.assertIn(CANONICAL_BINDING_INVALID, validation['failures'])
            self.assertIn(TEST_ONLY_SOURCE_BINDING, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['architecture_blockers'])

    def test_synthetic_install_is_neither_runtime_nor_delivery_ready(self):
        with TemporaryDirectory() as directory:
            fixture = build_valid_ros1_field_install_fixture(directory)

            validation = _validate(
                fixture,
                canonical_source_binding=fixture[
                    'canonical_source_binding'],
                allow_test_synthetic_binding=True)

            self.assertFalse(validation['validated_pass'])
            self.assertIn(TEST_ONLY_SOURCE_BINDING, validation['failures'])
            self.assertIn(
                perception_readiness.ROS1_RUNTIME_ARCHITECTURE_BLOCKER,
                validation['failures'])
            self.assertTrue(validation['test_only_synthetic_binding'])
            self.assertFalse(validation['canonical_runtime_complete'])
            self.assertNotIn('delivery_ready', validation)
            formal_denominators = {
                'background': 0,
                'bin_only': 0,
                'bottle_in_bin': 0,
                'bottle_outside': 0,
                'tf_valid_frames': 0,
                'xyz_valid_frames': 0,
            }
            delivery_ready = (
                validation['validated_pass']
                and all(value >= 30 for value in formal_denominators.values()))
            self.assertFalse(delivery_ready)


if __name__ == '__main__':
    unittest.main()
