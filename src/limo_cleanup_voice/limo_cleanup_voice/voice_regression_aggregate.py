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

"""LEGACY_ROS2_OFFLINE_ONLY aggregate; not a Noetic field verdict."""

import argparse
import configparser
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from shlex import quote


FROZEN_BASELINE = {
    'package_core': 311,
    'bundled_two_core': 295,
    'parser': 116,
    'readiness_core': 38,
    'stop_policy': 9,
    'intent_only': 3,
    'offline_tools': 13,
    'media_foundation': 5,
}

EXPECTED_CONSOLE_ENTRYPOINTS = {
    'voice_acceptance_fixture': (
        'limo_cleanup_voice.voice_acceptance_fixture:main'),
    'voice_asr': 'limo_cleanup_voice.voice_asr_node:main',
    'voice_corpus_readiness': (
        'limo_cleanup_voice.voice_corpus_readiness:main'),
    'voice_dialogue': 'limo_cleanup_voice.voice_dialogue_node:main',
    'voice_model_intake': 'limo_cleanup_voice.voice_model_intake:main',
    'voice_offline_eval': 'limo_cleanup_voice.voice_offline_eval:main',
    'voice_preflight': 'limo_cleanup_voice.voice_preflight:main',
    'voice_priority_stop': (
        'limo_cleanup_voice.voice_priority_stop_node:main'),
    'voice_regression_aggregate': (
        'limo_cleanup_voice.voice_regression_aggregate:main'),
    'voice_semantic_agent': (
        'limo_cleanup_voice.voice_semantic_agent_node:main'),
    'voice_smoke_probe': 'limo_cleanup_voice.voice_smoke_probe:main',
    'voice_tts': 'limo_cleanup_voice.voice_tts_node:main',
    'voice_v2_report': 'limo_cleanup_voice.voice_v2_report:main',
    'voice_wav_transcription_run': (
        'limo_cleanup_voice.voice_wav_transcription_run:main'),
}

PACKAGE_CORE_FILES = (
    'test/test_command_parser.py',
    'test/test_copyright.py',
    'test/test_flake8.py',
    'test/test_pep257.py',
    'test/test_voice_offline_tools_contract.py',
    'test/test_voice_safety.py',
)

STOP_EXPRESSION = (
    'priority_stop_first_publish or priority_stop_repeats_exactly or '
    'priority_stop_repeat_interval or priority_stop_debounce or '
    'stop_ack_is_strict or failed_or_expired_stop_ack or '
    'stop_contract_rejects'
)


def sha256_file(path):
    """Return a lowercase SHA-256 for one file."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def deterministic_tree_hash(paths):
    """Hash a stable list of files while excluding test caches."""
    files = []
    for item in paths:
        root = Path(item)
        if root.is_file():
            files.append(root)
            continue
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = [
                name for name in names
                if name not in {'__pycache__', '.pytest_cache'}
                and not name.endswith('.egg-info')
                and not Path(directory, name).is_symlink()
            ]
            files.extend(
                Path(directory, name) for name in filenames
                if not Path(directory, name).is_symlink()
            )
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda value: str(value).casefold()):
        digest.update(str(path).replace('\\', '/').encode('utf-8'))
        digest.update(b'\0')
        digest.update(bytes.fromhex(sha256_file(path)))
    return {'sha256': digest.hexdigest(), 'file_count': len(files)}


def windows_to_wsl_path(path):
    """Convert one explicit Windows path without searching the host."""
    raw = str(path)
    match = re.match(r'^([A-Za-z]):[\\/](.*)$', raw)
    if not match:
        raise ValueError('workspace must be an absolute Windows drive path')
    drive = match.group(1).lower()
    suffix = match.group(2).replace('\\', '/')
    return '/mnt/{}/{}'.format(drive, suffix)


def parse_pytest_summary(output):
    """Extract pytest pass/fail/skip counts from terminal output."""
    passed = re.findall(r'(\d+) passed', output)
    failed = re.findall(r'(\d+) failed', output)
    skipped = re.findall(r'(\d+) skipped', output)
    collected = re.findall(r'collected (\d+) item', output)
    passed_count = int(passed[-1]) if passed else 0
    return {
        'collected': int(collected[-1]) if collected else passed_count,
        'passed': passed_count,
        'failed': int(failed[-1]) if failed else 0,
        'skipped': int(skipped[-1]) if skipped else 0,
    }


def parse_bundled_summary(output):
    """Extract the repository runner's deterministic summary."""
    match = re.search(
        r'OFFLINE_PYTEST_STYLE collected=(\d+) passed=(\d+) failed=(\d+)',
        output,
    )
    if match is None:
        return {'collected': None, 'passed': 0, 'failed': 1, 'skipped': 0}
    return {
        'collected': int(match.group(1)),
        'passed': int(match.group(2)),
        'failed': int(match.group(3)),
        'skipped': 0,
    }


def _run(arguments, cwd=None, timeout_sec=180):
    started = time.monotonic_ns()
    completed = subprocess.run(
        [str(item) for item in arguments],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout_sec,
        check=False,
    )
    elapsed = time.monotonic_ns() - started
    return {
        'exit_code': completed.returncode,
        'elapsed_ms': round(elapsed / 1_000_000.0, 3),
        'output': completed.stdout,
        'output_sha256': hashlib.sha256(
            completed.stdout.encode('utf-8')).hexdigest(),
    }


def _wsl_command(distro, workspace_wsl, command, timeout_sec=180):
    return _run(
        [
            'wsl.exe', '-d', distro, '--cd', workspace_wsl, '--',
            'bash', '-lc', command,
        ],
        timeout_sec=timeout_sec,
    )


def build_wsl_install_audit_command(workspace_wsl):
    """Build a WSL-only install audit without reading host symlinks."""
    script = r'''import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path

EXPECTED = json.loads(__EXPECTED_JSON__)
SOURCE = Path(__SOURCE_JSON__).resolve()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            value.update(block)
    return value.hexdigest()


source_files = {
    path.name: digest(path)
    for path in sorted(SOURCE.glob('*.py'))
}
imported_files = {}
module_mismatches = []
module_errors = []
for filename, source_hash in source_files.items():
    module_name = 'limo_cleanup_voice.' + filename[:-3]
    try:
        module = importlib.import_module(module_name)
        imported = Path(module.__file__).resolve()
        imported_hash = digest(imported)
    except Exception as error:
        module_errors.append(
            '{}: {}: {}'.format(
                module_name, type(error).__name__, error))
        continue
    imported_files[filename] = {
        'path': str(imported),
        'sha256': imported_hash,
    }
    if imported_hash != source_hash:
        module_mismatches.append(filename)

entrypoints = {
    item.name: item
    for item in importlib.metadata.entry_points(group='console_scripts')
    if item.name in EXPECTED
}
entrypoint_reports = []
entrypoint_issues = []
for name, expected in sorted(EXPECTED.items()):
    item = entrypoints.get(name)
    value = item.value if item is not None else None
    loaded = False
    error_text = None
    if item is None:
        entrypoint_issues.append('missing console entrypoint: ' + name)
    elif value != expected:
        entrypoint_issues.append(
            'console entrypoint target mismatch: ' + name)
    else:
        try:
            loaded = callable(item.load())
            if not loaded:
                entrypoint_issues.append(
                    'console entrypoint is not callable: ' + name)
        except Exception as error:
            error_text = '{}: {}'.format(type(error).__name__, error)
            entrypoint_issues.append(
                'console entrypoint failed to load: ' + name)
    entrypoint_reports.append({
        'name': name,
        'expected': expected,
        'value': value,
        'loaded_callable': loaded,
        'error': error_text,
    })

issues = sorted(set(module_errors + module_mismatches + entrypoint_issues))
print(json.dumps({
    'schema_version': 1,
    'ready': bool(source_files) and not issues,
    'source_module_count': len(source_files),
    'imported_module_count': len(imported_files),
    'source_module_hashes': source_files,
    'imported_modules': imported_files,
    'module_hash_mismatches': sorted(module_mismatches),
    'module_import_errors': sorted(module_errors),
    'expected_console_entrypoint_count': len(EXPECTED),
    'console_entrypoints': entrypoint_reports,
    'entrypoint_issues': sorted(entrypoint_issues),
}, sort_keys=True))
'''
    source = '{}/src/limo_cleanup_voice/limo_cleanup_voice'.format(
        workspace_wsl.rstrip('/'))
    script = script.replace(
        '__EXPECTED_JSON__',
        repr(json.dumps(EXPECTED_CONSOLE_ENTRYPOINTS, sort_keys=True)),
    ).replace('__SOURCE_JSON__', repr(source))
    return (
        'source /opt/ros/humble/setup.bash; '
        'source install/setup.bash; '
        'python3 -c {}'.format(quote(script))
    )


def parse_wsl_install_audit(output):
    """Parse the single JSON object emitted by the WSL install audit."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get('schema_version') == 1:
            return value
    return None


def run_wsl_install_freshness(distro, workspace_wsl):
    """Verify imported modules and entrypoints entirely inside WSL."""
    result = _wsl_command(
        distro,
        workspace_wsl,
        build_wsl_install_audit_command(workspace_wsl),
    )
    parsed = parse_wsl_install_audit(result['output'])
    ready = bool(
        result['exit_code'] == 0
        and parsed is not None
        and parsed.get('ready') is True
        and parsed.get('expected_console_entrypoint_count')
        == len(EXPECTED_CONSOLE_ENTRYPOINTS)
    )
    return {
        'authoritative': True,
        'ready': ready,
        'transport_exit_code': result['exit_code'],
        'elapsed_ms': result['elapsed_ms'],
        'output_sha256': result['output_sha256'],
        'output_tail': result['output'].splitlines()[-20:],
        'audit': parsed,
    }


def _pytest_command(arguments):
    joined = ' '.join(arguments)
    return (
        'source /opt/ros/humble/setup.bash; '
        'source ../../install/setup.bash; '
        'python3 -m pytest -q ' + joined
    )


def _profile_result(name, expected, command_result, parser):
    counts = parser(command_result['output'])
    passed = (
        command_result['exit_code'] == 0
        and counts['collected'] == expected
        and counts['passed'] == expected
        and counts['failed'] == 0
        and counts['skipped'] == 0
    )
    return {
        'name': name,
        'expected': expected,
        'passed': passed,
        'counts': counts,
        'exit_code': command_result['exit_code'],
        'elapsed_ms': command_result['elapsed_ms'],
        'output_sha256': command_result['output_sha256'],
        'output_tail': command_result['output'].splitlines()[-20:],
    }


def inspect_install_freshness(workspace):
    """Compare source/build modules and generated console entrypoints."""
    workspace = Path(workspace).resolve()
    source_package = workspace / 'src' / 'limo_cleanup_voice' \
        / 'limo_cleanup_voice'
    build_package = workspace / 'build' / 'limo_cleanup_voice' \
        / 'limo_cleanup_voice'
    entry_file = workspace / 'src' / 'limo_cleanup_voice' \
        / 'limo_cleanup_voice.egg-info' / 'entry_points.txt'
    install_bin = workspace / 'install' / 'limo_cleanup_voice' \
        / 'lib' / 'limo_cleanup_voice'

    source_files = {
        path.name: sha256_file(path)
        for path in source_package.glob('*.py')
    }
    build_files = {}
    build_unreadable = False
    try:
        build_exists = build_package.exists()
    except OSError:
        build_exists = True
        build_unreadable = True
    if build_exists:
        try:
            build_candidates = list(build_package.glob('*.py'))
        except OSError:
            build_candidates = []
            build_unreadable = True
        for path in build_candidates:
            try:
                build_files[path.name] = sha256_file(path)
            except OSError:
                build_unreadable = True
                continue
    if not build_files:
        build_files = dict(source_files)

    parser = configparser.ConfigParser()
    if entry_file.is_file():
        parser.read(entry_file, encoding='utf-8')
    entries = dict(parser.items('console_scripts')) \
        if parser.has_section('console_scripts') else {}
    missing_entries = sorted(
        name for name in entries
        if not (install_bin / name).is_file()
    )
    module_mismatches = sorted(
        name for name, digest in source_files.items()
        if build_files.get(name) != digest
    )
    stale_build_modules = sorted(set(build_files) - set(source_files))
    return {
        'authoritative': False,
        'ready': bool(source_files) and not build_unreadable and not (
            missing_entries or module_mismatches or stale_build_modules),
        'source_module_count': len(source_files),
        'build_module_count': len(build_files),
        'build_symlink_unreadable_on_host': build_unreadable,
        'console_entrypoint_count': len(entries),
        'console_entrypoints': sorted(entries),
        'missing_console_entrypoints': missing_entries,
        'module_hash_mismatches': module_mismatches,
        'stale_build_modules': stale_build_modules,
    }


def _parse_media_json(output):
    start = output.find('{')
    end = output.rfind('}')
    if start < 0 or end < start:
        return None
    try:
        return json.loads(output[start:end + 1])
    except json.JSONDecodeError:
        return None


def run_aggregate(
        workspace, output_path, fixture_m4a, bundled_python,
        distro='Ubuntu-22.04'):
    """Execute the frozen profiles without starting ROS nodes or hardware."""
    workspace = Path(workspace).resolve()
    output_path = Path(output_path).resolve()
    fixture_m4a = Path(fixture_m4a).resolve()
    bundled_python = Path(bundled_python).resolve()
    package_root = workspace / 'src' / 'limo_cleanup_voice'
    runner = workspace / 'audit_tools' / 'run_pytest_style_tests.py'
    media_test = package_root / 'test' \
        / 'test_decode_voice_m4a_media_foundation.ps1'
    required = [package_root, runner, fixture_m4a, bundled_python, media_test]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError(
            'required local input is missing: ' + ', '.join(missing))
    if output_path.exists():
        raise FileExistsError('report output already exists: {}'.format(
            output_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    before = deterministic_tree_hash([package_root, runner])
    workspace_wsl = windows_to_wsl_path(workspace)
    build = _wsl_command(
        distro,
        workspace_wsl,
        'source /opt/ros/humble/setup.bash; '
        'colcon build --packages-select limo_cleanup_voice '
        '--symlink-install --event-handlers console_cohesion+',
        timeout_sec=300,
    )
    profiles = []
    if build['exit_code'] == 0:
        frozen = _wsl_command(
            distro, workspace_wsl,
            'cd src/limo_cleanup_voice; ' + _pytest_command(
                list(PACKAGE_CORE_FILES)),
        )
        profiles.append(_profile_result(
            'package_core', FROZEN_BASELINE['package_core'],
            frozen, parse_pytest_summary))

        profile_specs = (
            ('parser', ['test/test_command_parser.py']),
            (
                'readiness_core',
                ['test/test_voice_safety.py',
                 '-k', "'corpus_readiness or vosk_model'"],
            ),
            (
                'stop_policy',
                ['test/test_voice_safety.py', '-k',
                 "'{}'".format(STOP_EXPRESSION)],
            ),
            (
                'intent_only',
                ['test/test_voice_safety.py', '-k', 'cross_module'],
            ),
            ('offline_tools', ['test/test_voice_offline_tools_contract.py']),
        )
        for name, arguments in profile_specs:
            result = _wsl_command(
                distro, workspace_wsl,
                'cd src/limo_cleanup_voice; ' + _pytest_command(arguments),
            )
            profiles.append(_profile_result(
                name, FROZEN_BASELINE[name], result, parse_pytest_summary))

        full = _wsl_command(
            distro, workspace_wsl,
            'source /opt/ros/humble/setup.bash; source install/setup.bash; '
            'colcon test --packages-select limo_cleanup_voice '
            '--event-handlers console_cohesion+; '
            'colcon test-result --test-result-base build/limo_cleanup_voice '
            '--verbose',
            timeout_sec=300,
        )
        full_counts = parse_pytest_summary(full['output'])
        current_full = {
            'passed': full['exit_code'] == 0
            and full_counts['passed'] >= FROZEN_BASELINE['package_core']
            and full_counts['failed'] == 0,
            'minimum_passed': FROZEN_BASELINE['package_core'],
            'counts': full_counts,
            'exit_code': full['exit_code'],
            'elapsed_ms': full['elapsed_ms'],
            'output_sha256': full['output_sha256'],
            'output_tail': full['output'].splitlines()[-20:],
        }
    else:
        current_full = {
            'passed': False,
            'minimum_passed': FROZEN_BASELINE['package_core'],
            'counts': None,
            'exit_code': None,
            'output_tail': ['build failed; tests were not run'],
        }

    bundled = _run(
        [
            bundled_python, runner,
            package_root / 'test' / 'test_command_parser.py',
            package_root / 'test' / 'test_voice_safety.py',
        ],
        cwd=workspace,
    )
    profiles.append(_profile_result(
        'bundled_two_core', FROZEN_BASELINE['bundled_two_core'],
        bundled, parse_bundled_summary))

    media = _run(
        [
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', media_test, '-FixtureM4a', fixture_m4a,
        ],
        cwd=workspace,
    )
    media_data = _parse_media_json(media['output'])
    media_passed = bool(
        media['exit_code'] == 0
        and media_data
        and media_data.get('status') == 'PASS'
        and media_data.get('checks_passed')
        == FROZEN_BASELINE['media_foundation']
    )
    profiles.append({
        'name': 'media_foundation',
        'expected': FROZEN_BASELINE['media_foundation'],
        'passed': media_passed,
        'counts': {
            'collected': FROZEN_BASELINE['media_foundation'],
            'passed': media_data.get('checks_passed', 0) if media_data else 0,
            'failed': 0 if media_passed else 1,
            'skipped': 0,
        },
        'exit_code': media['exit_code'],
        'elapsed_ms': media['elapsed_ms'],
        'output_sha256': media['output_sha256'],
        'details': media_data,
        'output_tail': media['output'].splitlines()[-20:],
    })

    host_install = inspect_install_freshness(workspace)
    if build['exit_code'] == 0:
        install = run_wsl_install_freshness(distro, workspace_wsl)
    else:
        install = {
            'authoritative': True,
            'ready': False,
            'transport_exit_code': None,
            'audit': None,
            'output_tail': ['build failed; install audit was not run'],
        }
    after = deterministic_tree_hash([package_root, runner])
    source_stable = before == after
    status = 'PASS' if (
        build['exit_code'] == 0
        and source_stable
        and install['ready']
        and current_full['passed']
        and all(profile['passed'] for profile in profiles)
    ) else 'FAIL'
    report = {
        'schema_version': 1,
        'status': status,
        'mode': 'offline_regression_no_ros_graph_no_hardware',
        'generated_unix_ns': time.time_ns(),
        'workspace': str(workspace),
        'frozen_baseline': FROZEN_BASELINE,
        'source_before': before,
        'source_after': after,
        'source_stable_during_run': source_stable,
        'build': {
            'passed': build['exit_code'] == 0,
            'exit_code': build['exit_code'],
            'elapsed_ms': build['elapsed_ms'],
            'output_sha256': build['output_sha256'],
            'output_tail': build['output'].splitlines()[-20:],
        },
        'install_freshness': install,
        'host_install_observation': host_install,
        'frozen_profiles': profiles,
        'current_full_package': current_full,
        'safety': {
            'live_ros_graph_connected': False,
            'hardware_accessed': False,
            'motion_published': False,
            'ordinary_intents': 'mock_or_pure_logic_only',
        },
    }
    with output_path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return report


def main(args=None):
    """CLI entrypoint for one-click offline regression."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--fixture-m4a', required=True)
    parser.add_argument('--bundled-python', required=True)
    parser.add_argument('--wsl-distro', default='Ubuntu-22.04')
    parsed = parser.parse_args(args)
    try:
        report = run_aggregate(
            parsed.workspace,
            parsed.output,
            parsed.fixture_m4a,
            parsed.bundled_python,
            parsed.wsl_distro,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('{}: {}'.format(type(error).__name__, error), file=sys.stderr)
        return 2
    print(json.dumps({
        'status': report['status'],
        'output': str(Path(parsed.output).resolve()),
        'source_sha256': report['source_after']['sha256'],
    }, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
