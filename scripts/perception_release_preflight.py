#!/usr/bin/env python3
"""Offline/robot-local preflight for the controlled perception release."""

import argparse
import ast
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path

from perception_release_policy import (
    EXPECTED_MODELS,
    REQUIRED_TOPICS,
    SAFE_PATCH_PATHS,
    sha256_file,
    validate_patch_scope,
    validate_readonly_text,
    validate_source_sums,
)


def canonical_file_manifest(entries, base_path):
    """Reopen and hash the deterministic manifest without ROS imports."""
    if not isinstance(entries, list) or not entries:
        raise ValueError('source manifest entries are missing')
    normalized = []
    names = set()
    paths = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
                'name', 'path', 'size_bytes', 'sha256'}:
            raise ValueError('source manifest entry is invalid')
        entry_path = Path(entry['path'])
        path = (entry_path if entry_path.is_absolute()
                else Path(base_path) / entry_path).resolve(strict=True)
        if (not path.is_file() or entry['name'] in names
                or str(path) in paths or path.stat().st_size != entry['size_bytes']
                or sha256_file(path) != entry['sha256']):
            raise ValueError('source manifest file identity mismatch')
        names.add(entry['name'])
        paths.add(str(path))
        normalized.append({
            'name': entry['name'], 'path': str(path),
            'size_bytes': path.stat().st_size, 'sha256': entry['sha256']})
    normalized.sort(key=lambda item: item['name'])
    source_set = [{
        key: item[key] for key in ('name', 'size_bytes', 'sha256')}
        for item in normalized]
    canonical = json.dumps(
        source_set, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    import hashlib
    return {'sha256': hashlib.sha256(canonical).hexdigest()}


def add_check(checks, name, passed, detail, measured=None):
    """Append one JSON-safe preflight result."""
    item = {'name': name, 'status': 'PASS' if passed else 'FAIL',
            'detail': detail}
    if measured is not None:
        item['measured'] = measured
    checks.append(item)


def literal_defaults(path):
    """Extract literal DeclareLaunchArgument defaults without importing ROS."""
    result = {}
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in ast.walk(tree):
        if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == 'DeclareLaunchArgument'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        for keyword in node.keywords:
            if (
                    keyword.arg == 'default_value'
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)):
                result[node.args[0].value] = keyword.value.value
    return result


def module_version(name):
    """Return a module version without importing GPU frameworks."""
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return 'present-version-unknown'


def main():
    """Run filesystem, hash, dependency, and launch-contract checks only."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--release-dir', type=Path, required=True)
    parser.add_argument('--models-dir', type=Path, required=True)
    parser.add_argument('--require-runtime', action='store_true')
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        raise SystemExit('report path must not already exist')
    root = args.project_root.resolve()
    release = args.release_dir.resolve()
    models = args.models_dir.resolve()
    checks = []
    source_manifest_artifact_sha256 = None
    source_set_sha256 = None
    source_manifest_value = None
    try:
        source_manifest_path = args.source_manifest.resolve(strict=True)
        source_manifest_artifact_sha256 = sha256_file(source_manifest_path)
        source_manifest_value = json.loads(
            source_manifest_path.read_text(encoding='utf-8'))
        if (not isinstance(source_manifest_value, dict)
                or source_manifest_value.get('schema_version') != 1
                or source_manifest_value.get('release_id') != args.release_id
                or source_manifest_value.get('read_only') is not True
                or source_manifest_value.get('authorizes_motion') is not False
                or source_manifest_value.get(
                    'publishes_ros_messages') is not False
                or source_manifest_value.get(
                    'scope') != 'complete_interfaces_and_perception_package_inputs'):
            raise ValueError('source manifest policy mismatch')
        canonical = canonical_file_manifest(
            source_manifest_value['entries'], args.project_root.resolve())
        if (source_manifest_value.get('source_set_sha256')
                != canonical['sha256']):
            raise ValueError('canonical source-set SHA-256 mismatch')
        source_set_sha256 = canonical['sha256']
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError,
            KeyError, TypeError, ValueError):
        source_manifest_artifact_sha256 = None
        source_set_sha256 = None
    add_check(
        checks, 'source_manifest_artifact',
        source_manifest_artifact_sha256 is not None,
        'a concrete current-source manifest is required',
        measured=source_manifest_artifact_sha256)
    add_check(
        checks, 'canonical_source_set', source_set_sha256 is not None,
        'manifest entries must reopen and match the canonical source-set hash',
        measured=source_set_sha256)
    if isinstance(source_manifest_value, dict):
        add_check(
            checks, 'source_manifest_release_id',
            source_manifest_value.get('release_id') == args.release_id,
            'manifest release ID must equal requested release ID',
            measured=source_manifest_value.get('release_id'))

    patch = release / 'perception_rgbd_release.diff'
    sums = release / 'ROBOT_SOURCE_SHA256SUMS.txt'
    runbook = release / 'DEPLOYMENT_READONLY.md'
    add_check(checks, 'patch_present', patch.is_file(), str(patch))
    add_check(checks, 'source_sums_present', sums.is_file(), str(sums))
    add_check(checks, 'runbook_present', runbook.is_file(), str(runbook))
    if patch.is_file():
        failures = validate_patch_scope(patch.read_text(encoding='utf-8'))
        add_check(checks, 'patch_scope_exact', not failures,
                  '; '.join(failures) if failures else
                  'exact {}-file scope'.format(len(SAFE_PATCH_PATHS)))
    if sums.is_file():
        text = sums.read_text(encoding='utf-8')
        failures = validate_source_sums(text)
        add_check(checks, 'source_sum_scope_exact', not failures,
                  '; '.join(failures) if failures else
                  'exact {}-file scope'.format(len(SAFE_PATCH_PATHS)))
        if not failures:
            expected = {}
            for line in text.splitlines():
                digest, relative = line.split('  ', 1)
                expected[relative] = digest
            mismatches = []
            for relative in SAFE_PATCH_PATHS:
                path = root / relative
                if not path.is_file():
                    mismatches.append('missing:' + relative)
                elif sha256_file(path) != expected[relative]:
                    mismatches.append('sha256:' + relative)
            add_check(checks, 'source_hashes_match', not mismatches,
                      '; '.join(mismatches) if mismatches else 'all match')
    if runbook.is_file():
        failures = validate_readonly_text(runbook.read_text(encoding='utf-8'))
        add_check(checks, 'runbook_static_readonly', not failures,
                  '; '.join(failures) if failures else 'no forbidden command')

    model_results = {}
    for filename, expected in EXPECTED_MODELS.items():
        path = models / filename
        actual = sha256_file(path) if path.is_file() else None
        model_results[filename] = actual
        add_check(checks, 'model_' + filename, actual == expected,
                  'exact model hash required', measured=actual)

    launch_dir = root / 'src/limo_cleanup_bringup/launch'
    readonly_defaults = literal_defaults(
        launch_dir / 'hardware_readonly_acceptance.launch.py')
    detector_defaults = literal_defaults(
        launch_dir / 'real_perception_only.launch.py')
    add_check(checks, 'readiness_start_camera_false',
              readonly_defaults.get('start_camera') == 'false',
              'camera driver must not start by default')
    add_check(checks, 'detector_start_camera_false',
              detector_defaults.get('start_camera') == 'false',
              'camera driver must not start by default')
    for name, expected in REQUIRED_TOPICS.items():
        add_check(checks, 'readiness_' + name,
                  readonly_defaults.get(name) == expected,
                  'exact DaBai topic required',
                  measured=readonly_defaults.get(name))
        add_check(checks, 'detector_' + name,
                  detector_defaults.get(name) == expected,
                  'exact DaBai topic required',
                  measured=detector_defaults.get(name))

    modules = {
        name: module_version(name)
        for name in ('numpy', 'cv2', 'torch', 'ultralytics')
    }
    for name, version in modules.items():
        required = args.require_runtime
        add_check(checks, 'python_module_' + name,
                  version is not None or not required,
                  'required' if required else 'optional for static preflight',
                  measured=version)
    if args.require_runtime:
        add_check(checks, 'ultralytics_exact_version',
                  modules['ultralytics'] == '8.3.21',
                  'runtime must use the frozen version',
                  measured=modules['ultralytics'])
        try:
            from ultralytics import YOLO
            loaded_models = {}
            for filename in EXPECTED_MODELS:
                model = YOLO(str(models / filename))
                loaded_models[filename] = dict(model.names)
            add_check(
                checks, 'models_load_and_labels_match',
                loaded_models.get('nongfu_yolov8n_best.pt') == {
                    0: 'plastic_bottle'}
                and loaded_models.get('trash_bin_yolov8n_best.pt') == {
                    0: 'trash_bin'},
                'both YOLO weights must load with exact single-class labels',
                measured=loaded_models)
        except Exception as error:
            add_check(
                checks, 'models_load_and_labels_match', False,
                '{}: {}'.format(type(error).__name__, error))

    report = {
        'schema_version': 1,
        'generated_at_unix_sec': time.time(),
        'mode': 'filesystem_only_no_ros_graph_no_hardware',
        'release_id': args.release_id,
        'source_manifest_artifact_sha256': source_manifest_artifact_sha256,
        'source_set_sha256': source_set_sha256,
        'model_sha256': {
            'plastic_bottle': model_results.get(
                'nongfu_yolov8n_best.pt'),
            'trash_bin': model_results.get(
                'trash_bin_yolov8n_best.pt'),
        },
        'platform': {
            'python': platform.python_version(),
            'machine': platform.machine(),
            'system': platform.system(),
            'ros_distro': os.environ.get('ROS_DISTRO'),
        },
        'models': model_results,
        'checks': checks,
        'passed': all(item['status'] == 'PASS' for item in checks),
    }
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x', encoding='utf-8') as stream:
            stream.write(output + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    print(output)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
