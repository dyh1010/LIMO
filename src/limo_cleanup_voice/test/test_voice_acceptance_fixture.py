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

"""Tests for deterministic offline acceptance fixtures."""

import json
from pathlib import Path

import pytest

from limo_cleanup_voice.voice_acceptance_fixture import (
    generate_acceptance_report,
    main,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE_ROOT / 'fixtures' / (
    'voice_offline_acceptance_fixture.json')


def _manifest_data():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def _write_manifest(tmp_path, data):
    path = tmp_path / 'fixture.json'
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def test_offline_acceptance_fixture_is_fully_green_and_mock_only():
    """The complete fixture must pass without ROS or hardware access."""
    report = generate_acceptance_report(MANIFEST)

    assert report['status'] == 'PASS'
    assert report['mode'] == 'deterministic_offline_mock_no_ros_no_hardware'
    assert report['live_ros_used'] is False
    assert report['hardware_used'] is False
    assert report['high_level_intent_only'] is True
    assert report['transcripts']['case_count'] == 12
    assert report['transcripts']['passed_count'] == 12
    assert report['transcripts']['failed_count'] == 0
    assert report['transcripts']['false_activation_count'] == 0
    assert report['transcripts']['false_activation_rate'] == 0.0
    assert report['semantic_sequence']['step_count'] == 9
    assert report['semantic_sequence']['passed_count'] == 9
    assert report['semantic_sequence']['failed_count'] == 0
    assert report['semantic_sequence']['actual_publish_count'] == 0


def test_user_labeled_vosk_sequence_is_wake_gated_and_mock_only():
    """Real observed transcripts must obey wake, confirm, and stop gates."""
    sequence = generate_acceptance_report(MANIFEST)['semantic_sequence']

    assert sequence['ordinary_intents_mock_only'] is True
    assert sequence['mock_confirmed_high_level_count'] == 1
    assert sequence['priority_stop_count'] == 1
    assert sequence['steps'][1]['canonical_text'] == '开始清理'
    assert sequence['steps'][1]['state'] == 'pending_confirmation'
    assert sequence['steps'][2]['intent'] == 'stop_task'
    assert sequence['steps'][2]['state'] == 'idle'
    assert sequence['steps'][4]['intent'] == 'start_cleanup'
    assert sequence['steps'][5]['intent'] == 'confirm'
    assert all(item['actual_publish_count'] == 0 for item in sequence['steps'])


def test_ordinary_intents_remain_pending_mock_until_confirmation():
    """Ordinary requests must stop at the mock confirmation gate."""
    report = generate_acceptance_report(MANIFEST)
    ordinary = [
        item for item in report['transcripts']['cases']
        if item['category'] == 'ordinary_mock']

    assert len(ordinary) == 2
    assert all(item['pending_confirmation'] for item in ordinary)
    assert all(item['requires_confirmation'] for item in ordinary)
    assert all(
        not item['ordinary_forwarded_before_confirmation']
        for item in ordinary)


def test_noise_near_soundalike_negated_and_unwoken_never_activate():
    """All specified negative transcript categories must remain inert."""
    report = generate_acceptance_report(MANIFEST)
    negative = [
        item for item in report['transcripts']['cases']
        if item['category'] in {
            'noise', 'near_soundalike', 'negated', 'unwoken'}]

    assert len(negative) == 8
    assert all(not item['false_activation'] for item in negative)
    assert all(not item['priority_stop'] for item in negative)
    assert all(not item['pending_confirmation'] for item in negative)


def test_confirmation_after_timeout_is_blocked_and_cleared():
    """A late confirmation must not forward the pending ordinary intent."""
    timeout = generate_acceptance_report(MANIFEST)['confirmation_timeout']

    assert timeout['mode'] == 'mock_confirmation_state_only'
    assert timeout['expired'] is True
    assert timeout['forwarded_after_timeout'] is False
    assert timeout['pending_cleared'] is True
    assert timeout['passed'] is True


def test_stop_fixture_covers_first_publish_repeats_debounce_ack_and_status():
    """The mock stop path must expose every bounded timing contract."""
    stop = generate_acceptance_report(MANIFEST)['stop']

    assert stop['passed'] is True
    assert stop['first_publish_latency_ns'] == 2_000_000
    assert [
        item['attempt'] for item in stop['broadcast_attempts']
    ] == [1, 2, 3]
    assert [
        item['published_monotonic_ns']
        for item in stop['broadcast_attempts']
    ] == sorted(
        item['published_monotonic_ns']
        for item in stop['broadcast_attempts'])
    assert stop['duplicate_results'] == [
        {
            'offset_ns': 749_999_999,
            'state': 'debounced',
            'created_new_event': False,
        },
        {
            'offset_ns': 750_000_000,
            'state': 'new_event_boundary',
            'created_new_event': True,
        },
    ]
    assert stop['ack']['state'] == 'accepted'
    assert stop['ack_timely'] is True
    assert stop['statuses'][-1]['state'] == 'relay_acknowledged'
    assert stop['latency_distribution_ms']['transcript_to_publish'] == {
        'samples': 3,
        'minimum_ms': 2.0,
        'median_ms': 77.0,
        'p95_ms': 152.0,
        'maximum_ms': 152.0,
    }
    assert stop['latency_distribution_ms']['trigger_to_ack_observed'] == {
        'samples': 1,
        'minimum_ms': 120.0,
        'median_ms': 120.0,
        'p95_ms': 120.0,
        'maximum_ms': 120.0,
    }


def test_fixture_rejects_unsafe_mode_or_non_mock_ordinary_intents(tmp_path):
    """Any fixture that permits live ordinary intent handling is invalid."""
    data = _manifest_data()
    data['safety']['ordinary_intents'] = 'live'

    with pytest.raises(ValueError, match='safety boundary'):
        generate_acceptance_report(_write_manifest(tmp_path, data))


def test_fixture_rejects_duplicate_case_ids(tmp_path):
    """Transcript case identifiers must remain unique for audit joins."""
    data = _manifest_data()
    data['transcript_cases'][1]['id'] = data['transcript_cases'][0]['id']

    with pytest.raises(ValueError, match='duplicate transcript case id'):
        generate_acceptance_report(_write_manifest(tmp_path, data))


def test_semantic_sequence_rejects_filename_inference_or_bad_hash(tmp_path):
    """Labeled-corpus evidence must remain explicit and hash-bound."""
    inferred = _manifest_data()
    inferred['semantic_sequence_fixture']['provenance'][
        'filename_inference_used'] = True

    with pytest.raises(ValueError, match='may not infer transcripts'):
        generate_acceptance_report(_write_manifest(tmp_path, inferred))

    bad_hash = _manifest_data()
    bad_hash['semantic_sequence_fixture']['provenance'][
        'asr_evidence_sha256'] = 'not-a-hash'

    with pytest.raises(ValueError, match='not a lowercase SHA-256'):
        generate_acceptance_report(_write_manifest(tmp_path, bad_hash))


def test_semantic_sequence_rejects_duplicate_or_unordered_steps(tmp_path):
    """Sequence joins must have unique IDs and monotonic event time."""
    duplicate = _manifest_data()
    duplicate['semantic_sequence_fixture']['steps'][1]['id'] = (
        duplicate['semantic_sequence_fixture']['steps'][0]['id'])

    with pytest.raises(ValueError, match='duplicate semantic step id'):
        generate_acceptance_report(_write_manifest(tmp_path, duplicate))

    unordered = _manifest_data()
    unordered['semantic_sequence_fixture']['steps'][1]['offset_ms'] = 0

    with pytest.raises(ValueError, match='strictly increasing'):
        generate_acceptance_report(_write_manifest(tmp_path, unordered))


def test_semantic_sequence_expectation_drift_fails_overall_report(tmp_path):
    """A changed expected state must make the top-level report fail."""
    data = _manifest_data()
    data['semantic_sequence_fixture']['steps'][1][
        'expected_state'] = 'idle'

    report = generate_acceptance_report(_write_manifest(tmp_path, data))

    assert report['status'] == 'FAIL'
    assert report['semantic_sequence']['failed_count'] == 1


def test_fixture_rejects_changed_stop_retry_or_timing_contract(tmp_path):
    """Fixture edits cannot silently change the frozen stop policy."""
    data = _manifest_data()
    data['stop_fixture']['repeat_count'] = 4

    with pytest.raises(ValueError, match='repeat_count must be exactly 3'):
        generate_acceptance_report(_write_manifest(tmp_path, data))


def test_cli_creates_report_exclusively_and_refuses_overwrite(tmp_path):
    """The CLI must preserve earlier evidence instead of overwriting it."""
    output = tmp_path / 'report.json'

    assert main([
        '--manifest', str(MANIFEST), '--json-output', str(output)]) == 0
    written = json.loads(output.read_text(encoding='utf-8'))
    assert written['status'] == 'PASS'
    with pytest.raises(ValueError, match='refusing overwrite'):
        main([
            '--manifest', str(MANIFEST), '--json-output', str(output)])


def test_cli_default_manifest_resolves_only_when_main_runs(monkeypatch):
    """The CLI must resolve its packaged default after argument parsing."""
    monkeypatch.setattr(
        'limo_cleanup_voice.voice_acceptance_fixture._default_manifest_path',
        lambda: MANIFEST,
    )

    assert main([]) == 0
