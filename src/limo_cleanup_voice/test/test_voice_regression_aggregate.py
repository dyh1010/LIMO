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

"""Contracts for the one-click frozen offline regression runner."""

import json
from pathlib import Path

import pytest

import limo_cleanup_voice.voice_regression_aggregate as aggregate
from limo_cleanup_voice.voice_regression_aggregate import (
    FROZEN_BASELINE,
    EXPECTED_CONSOLE_ENTRYPOINTS,
    build_wsl_install_audit_command,
    deterministic_tree_hash,
    inspect_install_freshness,
    parse_bundled_summary,
    parse_pytest_summary,
    parse_wsl_install_audit,
    run_wsl_install_freshness,
    windows_to_wsl_path,
)


def test_frozen_baseline_keeps_accepted_counts_exact():
    assert FROZEN_BASELINE == {
        'package_core': 311,
        'bundled_two_core': 295,
        'parser': 116,
        'readiness_core': 38,
        'stop_policy': 9,
        'intent_only': 3,
        'offline_tools': 13,
        'media_foundation': 5,
    }


def test_summary_parsers_are_machine_deterministic():
    pytest_counts = parse_pytest_summary(
        'collected 311 items\n311 passed, 2 warnings in 5.0s')
    bundled_counts = parse_bundled_summary(
        'OFFLINE_PYTEST_STYLE collected=295 passed=295 failed=0')

    assert pytest_counts == {
        'collected': 311, 'passed': 311, 'failed': 0, 'skipped': 0}
    assert bundled_counts == {
        'collected': 295, 'passed': 295, 'failed': 0, 'skipped': 0}


def test_windows_path_conversion_is_explicit_and_search_free(tmp_path):
    del tmp_path
    converted = windows_to_wsl_path(r'C:\Voice Workspace\limo_cleanup_ws')

    assert converted == '/mnt/c/Voice Workspace/limo_cleanup_ws'


def test_tree_hash_detects_content_change(tmp_path):
    item = tmp_path / 'item.txt'
    item.write_text('first', encoding='utf-8')
    before = deterministic_tree_hash([tmp_path])
    item.write_text('second', encoding='utf-8')
    after = deterministic_tree_hash([tmp_path])

    assert before['file_count'] == 1
    assert after['file_count'] == 1
    assert before['sha256'] != after['sha256']


def test_install_freshness_rejects_stale_or_missing_artifacts(tmp_path):
    source = tmp_path / 'src' / 'limo_cleanup_voice' / 'limo_cleanup_voice'
    build = tmp_path / 'build' / 'limo_cleanup_voice' / 'limo_cleanup_voice'
    egg = tmp_path / 'src' / 'limo_cleanup_voice' \
        / 'limo_cleanup_voice.egg-info'
    install = tmp_path / 'install' / 'limo_cleanup_voice' \
        / 'lib' / 'limo_cleanup_voice'
    source.mkdir(parents=True)
    build.mkdir(parents=True)
    egg.mkdir(parents=True)
    install.mkdir(parents=True)
    (source / 'module.py').write_text('safe = True\n', encoding='utf-8')
    (build / 'module.py').write_text('safe = False\n', encoding='utf-8')
    (build / 'stale.py').write_text('stale = True\n', encoding='utf-8')
    (egg / 'entry_points.txt').write_text(
        '[console_scripts]\nvoice_safe = package.module:main\n',
        encoding='utf-8',
    )

    report = inspect_install_freshness(tmp_path)

    assert report['ready'] is False
    assert report['authoritative'] is False
    assert report['module_hash_mismatches'] == ['module.py']
    assert report['stale_build_modules'] == ['stale.py']
    assert report['missing_console_entrypoints'] == ['voice_safe']


def test_wsl_audit_command_checks_import_hashes_and_all_entrypoints():
    command = build_wsl_install_audit_command('/mnt/c/voice/limo_cleanup_ws')

    assert "source install/setup.bash" in command
    assert "importlib.import_module" in command
    assert "importlib.metadata.entry_points" in command
    assert "item.load()" in command
    assert "digest(imported)" in command
    assert 'SOURCE.glob' in command
    assert '*.py' in command
    for name, target in EXPECTED_CONSOLE_ENTRYPOINTS.items():
        assert name in command
        assert target in command
    assert 'ros2 ' not in command
    assert 'pip ' not in command
    assert 'http://' not in command
    assert 'https://' not in command


def test_wsl_audit_parser_uses_last_machine_json_line():
    payload = {
        'schema_version': 1,
        'ready': True,
        'expected_console_entrypoint_count': len(
            EXPECTED_CONSOLE_ENTRYPOINTS),
    }
    output = 'setup warning\n{}\n'.format(json.dumps(payload))

    assert parse_wsl_install_audit(output) == payload
    assert parse_wsl_install_audit('no json here') is None


def test_wsl_install_freshness_requires_transport_and_complete_audit(
        monkeypatch):
    payload = {
        'schema_version': 1,
        'ready': True,
        'expected_console_entrypoint_count': len(
            EXPECTED_CONSOLE_ENTRYPOINTS),
    }

    def successful_command(*unused_args, **unused_kwargs):
        return {
            'exit_code': 0,
            'elapsed_ms': 1.0,
            'output': json.dumps(payload) + '\n',
            'output_sha256': 'a' * 64,
        }

    monkeypatch.setattr(
        'limo_cleanup_voice.voice_regression_aggregate._wsl_command',
        successful_command,
    )
    passed = run_wsl_install_freshness('Ubuntu-22.04', '/mnt/c/ws')

    payload['expected_console_entrypoint_count'] -= 1
    incomplete = run_wsl_install_freshness('Ubuntu-22.04', '/mnt/c/ws')

    assert passed['authoritative'] is True
    assert passed['ready'] is True
    assert incomplete['ready'] is False


def test_expected_console_entrypoints_are_exact_and_complete():
    assert EXPECTED_CONSOLE_ENTRYPOINTS == {
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


def test_host_unreadable_symlink_install_is_not_authoritative(
        tmp_path, monkeypatch):
    source = tmp_path / 'src' / 'limo_cleanup_voice' / 'limo_cleanup_voice'
    source.mkdir(parents=True)
    (source / 'module.py').write_text('safe = True\n', encoding='utf-8')
    build = tmp_path / 'build' / 'limo_cleanup_voice' \
        / 'limo_cleanup_voice'
    original_exists = Path.exists

    def unreadable_build(path):
        if path == build:
            raise OSError('Windows cannot follow WSL symlink')
        return original_exists(path)

    monkeypatch.setattr(Path, 'exists', unreadable_build)

    report = inspect_install_freshness(tmp_path)

    assert report['authoritative'] is False
    assert report['build_symlink_unreadable_on_host'] is True
    assert report['ready'] is False


def test_aggregate_refuses_existing_report_before_any_command(
        tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    package = workspace / 'src' / 'limo_cleanup_voice'
    package.mkdir(parents=True)
    runner = workspace / 'audit_tools' / 'run_pytest_style_tests.py'
    runner.parent.mkdir(parents=True)
    runner.write_text('', encoding='utf-8')
    media = package / 'test' / 'test_decode_voice_m4a_media_foundation.ps1'
    media.parent.mkdir(parents=True)
    media.write_text('', encoding='utf-8')
    fixture = tmp_path / 'fixture.m4a'
    fixture.write_bytes(b'fixture')
    python = tmp_path / 'python.exe'
    python.write_bytes(b'python')
    output = tmp_path / 'existing.json'
    output.write_text('preserve', encoding='utf-8')
    calls = []
    monkeypatch.setattr(
        aggregate, '_run', lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        aggregate, '_wsl_command',
        lambda *args, **kwargs: calls.append(args))

    with pytest.raises(FileExistsError, match='already exists'):
        aggregate.run_aggregate(
            workspace, output, fixture, python)

    assert output.read_text(encoding='utf-8') == 'preserve'
    assert calls == []


def test_aggregate_source_never_starts_ros_or_accesses_hardware():
    source = Path(__file__).parents[1] / 'limo_cleanup_voice' \
        / 'voice_regression_aggregate.py'
    text = source.read_text(encoding='utf-8')

    assert 'ros2 launch' not in text
    assert 'ros2 topic' not in text
    assert '/cmd_vel' not in text
    assert 'colcon build --packages-select limo_cleanup_voice' in text
    assert 'colcon test --packages-select limo_cleanup_voice' in text
    assert "output_path.open('x'" in text
