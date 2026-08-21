# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Read-only intake gate for an explicitly supplied local Vosk model."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from .voice_corpus_readiness import sha256_file, validate_vosk_model
from .voice_grammar import DEFAULT_GRAMMAR


REPORT_SCHEMA_ID = (
    'urn:limo-cleanup:voice:asr-model-intake-readiness:v1')
REPORT_MODE = 'offline_local_vosk_model_intake_no_network_no_ros'
SCHEMA_FILENAME = 'asr_model_intake_readiness.schema.json'
TREE_HASH_ALGORITHM = 'sha256-tree-json-lines-v1'
URI_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://')
WINDOWS_DRIVE_PATTERN = re.compile(r'^[A-Za-z]:[\\/]')


def _canonical_json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _schema_path():
    return Path(__file__).resolve().parent / 'schemas' / SCHEMA_FILENAME


def _source_artifacts():
    package_directory = Path(__file__).resolve().parent
    paths = (
        Path(__file__).resolve(),
        package_directory / 'voice_corpus_readiness.py',
        package_directory / 'voice_grammar.py',
        _schema_path(),
    )
    artifacts = []
    issues = []
    for path in paths:
        if not path.is_file():
            issues.append(
                'validator artifact is missing: {}'.format(path.name))
            continue
        artifacts.append({
            'name': path.name,
            'bytes': path.stat().st_size,
            'sha256': sha256_file(path),
        })
    return artifacts, issues


def _validate_explicit_local_path(model_path):
    raw = str(model_path or '').strip()
    issues = []
    if not raw:
        return raw, None, ['model path must be explicitly provided']
    if URI_PATTERN.match(raw):
        issues.append('model path must not be a URI')
    if raw.startswith(('\\\\', '//')):
        issues.append('model path must not be a UNC or network path')
    try:
        candidate = Path(raw)
    except (TypeError, ValueError) as error:
        return raw, None, [
            'model path is invalid: {}: {}'.format(
                type(error).__name__, error)]
    if not candidate.is_absolute():
        issues.append('model path must be an explicit absolute local path')
    if os.name != 'nt' and WINDOWS_DRIVE_PATTERN.match(raw):
        issues.append('model path must use the native local path syntax')
    if issues:
        return raw, None, issues
    try:
        if candidate.is_symlink():
            issues.append('model directory itself must not be a symlink')
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        issues.append(
            'model path could not be resolved: {}: {}'.format(
                type(error).__name__, error))
        return raw, None, issues
    if not resolved.exists():
        issues.append('Vosk model directory is missing')
    elif not resolved.is_dir():
        issues.append('Vosk model path is not a directory')
    return raw, resolved, issues


def _file_digest_with_stability_check(path, initial_stat):
    digest = sha256_file(path)
    final_stat = path.stat(follow_symlinks=False)
    stable = (
        initial_stat.st_size == final_stat.st_size
        and initial_stat.st_mtime_ns == final_stat.st_mtime_ns
    )
    if os.name != 'nt':
        stable = stable and (
            initial_stat.st_dev == final_stat.st_dev
            and initial_stat.st_ino == final_stat.st_ino
        )
    return digest, stable


def _inventory_model(root):
    files = []
    issues = []

    def visit(directory, relative_parts):
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(
                    iterator,
                    key=lambda item: item.name.encode('utf-8'),
                )
        except OSError as error:
            issues.append(
                'model directory cannot be read: {}: {}: {}'.format(
                    '/'.join(relative_parts) or '.',
                    type(error).__name__, error))
            return
        for entry in entries:
            relative = relative_parts + (entry.name,)
            relative_name = '/'.join(relative)
            try:
                if entry.is_symlink():
                    issues.append(
                        'model tree contains a symlink: {}'.format(
                            relative_name))
                    continue
                entry_stat = entry.stat(follow_symlinks=False)
                mode = entry_stat.st_mode
                if stat.S_ISDIR(mode):
                    visit(Path(entry.path), relative)
                elif stat.S_ISREG(mode):
                    digest, stable = _file_digest_with_stability_check(
                        Path(entry.path), entry_stat)
                    if not stable:
                        issues.append(
                            'model file changed while hashing: {}'.format(
                                relative_name))
                        continue
                    files.append({
                        'path': relative_name,
                        'bytes': entry_stat.st_size,
                        'sha256': digest,
                    })
                else:
                    issues.append(
                        'model tree contains a non-regular entry: '
                        '{}'.format(relative_name))
            except OSError as error:
                issues.append(
                    'model entry cannot be read: {}: {}: {}'.format(
                        relative_name, type(error).__name__, error))

    visit(root, ())
    files.sort(key=lambda item: item['path'].encode('utf-8'))
    tree_digest = hashlib.sha256()
    for item in files:
        tree_digest.update(_canonical_json_bytes(item))
        tree_digest.update(b'\n')
    return {
        'algorithm': TREE_HASH_ALGORITHM,
        'directory_sha256': tree_digest.hexdigest(),
        'file_count': len(files),
        'total_bytes': sum(item['bytes'] for item in files),
        'files': files,
    }, issues


def _empty_inventory():
    return {
        'algorithm': TREE_HASH_ALGORITHM,
        'directory_sha256': None,
        'file_count': 0,
        'total_bytes': 0,
        'files': [],
    }


def _blocked_validation(path, issues):
    return {
        'path': str(path) if path else None,
        'configured': bool(path),
        'directory_present': bool(path and path.is_dir()),
        'static_ready': False,
        'runtime_available': False,
        'loadability_checked': False,
        'loadable': False,
        'ready': False,
        'issues': list(issues),
    }


def validate_local_vosk_model(
        model_path, *, model_loader=None, recognizer_loader=None):
    """
    Return a deterministic intake report for one explicit local path.

    Notes
    -----
    This function performs no discovery, network access, download, install,
    device access, or ROS interaction. Every filesystem read stays within the
    directory named by ``model_path`` plus this installed validator package.

    """
    raw_path, resolved_path, path_issues = _validate_explicit_local_path(
        model_path)
    artifacts, artifact_issues = _source_artifacts()
    grammar_payload = _canonical_json_bytes(DEFAULT_GRAMMAR)
    grammar_sha256 = hashlib.sha256(grammar_payload).hexdigest()
    blocking = list(path_issues) + list(artifact_issues)
    inventory = _empty_inventory()

    if resolved_path is not None and not path_issues:
        inventory, inventory_issues = _inventory_model(resolved_path)
        blocking.extend(inventory_issues)
    else:
        inventory_issues = []

    if resolved_path is not None and not path_issues and not inventory_issues:
        validation = validate_vosk_model(
            resolved_path,
            model_loader=model_loader,
            recognizer_loader=recognizer_loader,
            grammar_phrases=DEFAULT_GRAMMAR,
        )
        blocking.extend(validation.get('issues', []))
    else:
        validation = _blocked_validation(resolved_path, blocking)

    grammar_probe = {
        'sample_rate_hz': 16000,
        'phrase_count': len(DEFAULT_GRAMMAR),
        'phrases_sha256': grammar_sha256,
        'attempted': bool(validation.get('loadability_checked')),
        'passed': bool(validation.get('loadable')),
    }
    delivery_ready = bool(
        not blocking
        and inventory['file_count'] > 0
        and validation.get('ready')
        and grammar_probe['passed']
    )
    return {
        'schema_id': REPORT_SCHEMA_ID,
        'schema_version': 1,
        'mode': REPORT_MODE,
        'status': 'PASS' if delivery_ready else 'BLOCKED',
        'delivery_ready': delivery_ready,
        'input': {
            'provided_model_path': raw_path,
            'path_policy': 'explicit_absolute_local_directory_only',
            'automatic_search_performed': False,
            'network_access_performed': False,
            'download_performed': False,
            'install_performed': False,
        },
        'model': {
            'path': str(resolved_path) if resolved_path else None,
            'inventory': inventory,
            'validation': validation,
        },
        'grammar_probe': grammar_probe,
        'validator': {
            'artifacts': artifacts,
        },
        'blocking_issues': sorted(set(blocking)),
    }


def _render_report(report):
    return json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def _write_exclusive(path, payload):
    output = Path(path)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(payload)


def main(args=None, *, model_loader=None, recognizer_loader=None):
    """Validate one explicitly supplied model and emit JSON only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--model-path', required=True,
        help='Explicit absolute path to an existing local Vosk directory')
    parser.add_argument(
        '--json-output',
        help='Create this JSON file exclusively; existing files are refused')
    parsed = parser.parse_args(args)
    report = validate_local_vosk_model(
        parsed.model_path,
        model_loader=model_loader,
        recognizer_loader=recognizer_loader,
    )
    rendered = _render_report(report)
    if parsed.json_output:
        try:
            _write_exclusive(parsed.json_output, rendered)
        except (FileExistsError, OSError) as error:
            print(rendered, end='')
            print(
                'JSON output was not created: {}: {}'.format(
                    type(error).__name__, error),
                file=sys.stderr,
            )
            return 2
    print(rendered, end='')
    return 0 if report['delivery_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
