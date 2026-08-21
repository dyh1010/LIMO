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

"""Tests for the gated four-WAV deterministic transcription runner."""

import hashlib
import json
import math
import struct
import wave
from pathlib import Path

import pytest

from limo_cleanup_voice.voice_corpus_readiness import (
    LABEL_POLICY,
    REQUIRED_COVERAGE_CLASSES,
    inspect_pcm16_wav,
)
from limo_cleanup_voice.voice_wav_transcription_run import (
    main,
    run_wav_transcription,
    write_json_exclusive,
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_wav(path, frequency_hz):
    sample_rate = 16000
    samples = []
    for index in range(sample_rate):
        if 2400 <= index < 13600:
            sample = int(5000 * math.sin(
                2 * math.pi * frequency_hz * index / sample_rate))
        else:
            sample = 0
        samples.append(sample)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(
            '<{}h'.format(len(samples)), *samples))


def _manifest_fixture(tmp_path):
    definitions = (
        ('ordinary-a', '丢垃圾', 'ordinary_intent', 440),
        ('ordinary-b', '捡矿泉水瓶', 'ordinary_intent', 550),
        ('stop', '停下', 'priority_stop', 660),
        ('wake', '小莫小莫', 'wake_only', 770),
    )
    cases = []
    for index, (case_id, label, coverage, frequency) in enumerate(
            definitions):
        source = tmp_path / '{}.m4a'.format(case_id)
        source.write_bytes(('source-' + case_id).encode('ascii'))
        audio = tmp_path / 'voice_{:012x}_16k_mono_pcm.wav'.format(index + 1)
        _write_wav(audio, frequency)
        statistics = inspect_pcm16_wav(audio)
        cases.append({
            'source_name': source.name,
            'id': case_id,
            'label': label,
            'coverage_class': coverage,
            'source_path': source.name,
            'source_sha256': _sha256(source),
            'source_bytes': source.stat().st_size,
            'source_format': {'subtype': 'fixture'},
            'audio_path': audio.name,
            'wav_sha256': _sha256(audio),
            'wav_bytes': audio.stat().st_size,
            'wav': {
                key: statistics[key] for key in (
                    'sample_rate', 'channels', 'sample_width_bytes',
                    'frame_count', 'duration_sec', 'rms', 'rms_dbfs',
                    'peak', 'peak_dbfs', 'clipped_fraction',
                    'voiced_frame_fraction', 'leading_silence_sec_est',
                    'trailing_silence_sec_est',
                )
            },
            'transcription_status': 'decoded_not_transcribed',
            'transcript': None,
            'intent_status': 'not_evaluated_without_asr',
            'label_is_transcript': False,
        })
    manifest = tmp_path / 'decode_manifest.json'
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')
    return manifest


def _passing_intake(model_path):
    return {
        'schema_version': 1,
        'mode': 'offline_local_vosk_model_intake_no_network',
        'status': 'PASS',
        'delivery_ready': True,
        'model': {
            'path': str(Path(model_path).resolve()),
            'inventory': {
                'directory_sha256': 'a' * 64,
                'file_count': 1,
                'total_bytes': 123,
                'files': [{
                    'path': 'am/final.mdl',
                    'bytes': 123,
                    'sha256': 'b' * 64,
                }],
            },
            'validation': {'ready': True},
        },
        'grammar_probe': {
            'phrases_sha256': 'c' * 64,
            'phrase_count': 16,
            'sample_rate_hz': 16000,
            'attempted': True,
            'passed': True,
        },
        'blocking_issues': [],
    }


class _RecordingTranscriber:
    def __init__(self, model_path, transcripts, calls):
        self.transcripts = iter(transcripts)
        self.calls = calls
        self.calls.append(('load', str(Path(model_path).resolve())))

    def __call__(self, path, sample_rate, payload):
        self.calls.append(('audio', path.name, sample_rate, len(payload)))
        transcript, confidences = next(self.transcripts)
        return {
            'transcript': transcript,
            'word_confidences': confidences,
        }


def test_missing_model_path_is_blocked_before_intake_or_audio(tmp_path):
    calls = []

    def intake(path):
        calls.append(('intake', path))
        raise AssertionError('intake must not run without an explicit path')

    report = run_wav_transcription(
        tmp_path / 'missing.json',
        '',
        intake_validator=intake,
        transcriber_factory=lambda path: calls.append(('load', path)),
    )

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['transcription_status'] == 'decoded_not_transcribed'
    assert report['cases'] == []
    assert calls == []
    assert report['safety']['labels_used_as_transcripts'] is False


def test_failed_model_gate_is_blocked_before_manifest_or_audio(tmp_path):
    calls = []

    def intake(path):
        calls.append(('intake', path))
        return {
            'status': 'BLOCKED',
            'delivery_ready': False,
            'model': {'path': path},
            'blocking_issues': ['model incomplete'],
        }

    report = run_wav_transcription(
        tmp_path / 'missing.json',
        tmp_path / 'model',
        intake_validator=intake,
        transcriber_factory=lambda path: calls.append(('load', path)),
    )

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['cases'] == []
    assert [call[0] for call in calls] == ['intake']
    assert 'model intake status is not PASS' in report['blocking_issues']
    assert 'model intake: model incomplete' in report['blocking_issues']


def test_mismatched_validated_model_path_is_blocked(tmp_path):
    requested = tmp_path / 'requested-model'

    def intake(_path):
        return _passing_intake(tmp_path / 'different-model')

    report = run_wav_transcription(
        tmp_path / 'missing.json',
        requested,
        intake_validator=intake,
        transcriber_factory=lambda _path: pytest.fail(
            'transcriber must not load after a mismatched model gate'),
    )

    assert report['status'] == 'BLOCKED'
    assert 'validated model path does not match requested path' in (
        report['blocking_issues'])


def test_bad_corpus_blocks_transcriber_after_model_gate(tmp_path):
    calls = []
    model_path = tmp_path / 'model'
    report = run_wav_transcription(
        tmp_path / 'missing.json',
        model_path,
        intake_validator=lambda _path: _passing_intake(model_path),
        transcriber_factory=lambda path: calls.append(('load', path)),
    )

    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['cases'] == []
    assert calls == []
    assert any(
        issue.startswith('corpus readiness failed:')
        for issue in report['blocking_issues'])


def test_complete_run_records_hashes_results_confidence_and_latency(tmp_path):
    manifest = _manifest_fixture(tmp_path)
    model_path = tmp_path / 'model'
    calls = []
    transcripts = [
        ('丢 垃圾', [0.8, 0.9]),
        ('捡 矿泉 水瓶', [0.7, 0.75, 0.8]),
        ('停下', [0.99]),
        ('小莫 小莫', []),
    ]

    def factory(path):
        return _RecordingTranscriber(path, transcripts, calls)

    report = run_wav_transcription(
        manifest,
        model_path,
        intake_validator=lambda _path: _passing_intake(model_path),
        transcriber_factory=factory,
    )

    assert report['status'] == 'COMPLETE'
    assert report['delivery_ready'] is False
    assert report['accuracy_claimed'] is False
    assert report['ground_truth_transcripts_available'] is False
    assert report['input_fingerprint_sha256']
    assert report['model']['directory_sha256'] == 'a' * 64
    assert report['source']['bundle_sha256']
    assert report['corpus']['manifest_sha256'] == _sha256(manifest)
    assert report['corpus']['audio_set_sha256']
    assert report['summary'] == {
        'case_count': 4,
        'completed_count': 4,
        'empty_transcript_count': 0,
        'confidence_available_count': 3,
        'wake_word_detected_count': 1,
        'priority_stop_detected_count': 1,
        'ordinary_intent_candidate_count': 0,
    }
    assert any(
        'final delivery requires the hashed real-WAV' in issue
        for issue in report['blocking_issues'])
    assert len(calls) == 5
    assert calls[0][0] == 'load'
    assert all(call[0] == 'audio' for call in calls[1:])
    stop_case = report['cases'][2]
    assert stop_case['observed']['priority_stop_detected'] is True
    assert stop_case['observed']['parser_intent']['name'] == 'stop_task'
    assert stop_case['confidence']['mean'] == 0.99
    assert stop_case['latency_ms']['asr'] >= 0
    assert stop_case['latency_ms']['end_to_end'] >= 0
    for case in report['cases']:
        assert case['transcript_source'] == 'vosk_offline_audio'
        assert case['evaluation'] == {
            'ground_truth_available': False,
            'accuracy_evaluated': False,
            'coverage_class_used_as_expected_intent': False,
        }
        assert case['observed']['ordinary_intent']['mock_only'] is True
        assert case['observed']['ordinary_intent']['published'] is False


def test_labels_are_never_passed_to_transcriber_or_copied_as_transcripts(
        tmp_path):
    manifest = _manifest_fixture(tmp_path)
    model_path = tmp_path / 'model'
    calls = []

    class EmptyTranscriber:
        def __init__(self, path):
            calls.append(('load', str(path)))

        def __call__(self, path, sample_rate, payload):
            calls.append((path.name, sample_rate, len(payload)))
            return {'transcript': '', 'word_confidences': []}

    report = run_wav_transcription(
        manifest,
        model_path,
        intake_validator=lambda _path: _passing_intake(model_path),
        transcriber_factory=EmptyTranscriber,
    )

    labels = {
        case['label']
        for case in json.loads(manifest.read_text(encoding='utf-8'))['cases']
    }
    assert report['status'] == 'FAILED'
    assert report['delivery_ready'] is False
    assert report['transcription_status'] == 'incomplete'
    assert all(case['transcript'] == '' for case in report['cases'])
    assert not labels.intersection(
        case['transcript'] for case in report['cases'])
    assert report['summary']['empty_transcript_count'] == 4
    assert report['safety']['labels_used_as_transcripts'] is False
    assert any(
        'required WAV transcript(s) are empty' in issue
        for issue in report['blocking_issues'])


def test_wav_hash_drift_after_gate_fails_closed(tmp_path, monkeypatch):
    manifest = _manifest_fixture(tmp_path)
    model_path = tmp_path / 'model'
    target = tmp_path / 'voice_000000000001_16k_mono_pcm.wav'
    from limo_cleanup_voice import voice_wav_transcription_run as runner

    original_factory = runner.OfflineVoskTranscriber

    class MutatingFactory:
        def __init__(self, _path):
            target.write_bytes(target.read_bytes() + b'drift')
            self.delegate = original_factory

        def __call__(self, path, sample_rate, payload):
            raise AssertionError('transcriber must not receive drifted WAV')

    report = run_wav_transcription(
        manifest,
        model_path,
        intake_validator=lambda _path: _passing_intake(model_path),
        transcriber_factory=MutatingFactory,
    )

    assert report['status'] == 'FAILED'
    assert report['delivery_ready'] is False
    assert report['cases'] == []
    assert any(
        'WAV SHA-256 changed after corpus readiness' in issue
        for issue in report['blocking_issues'])


def test_exclusive_output_refuses_to_overwrite(tmp_path):
    output = tmp_path / 'report.json'
    write_json_exclusive(output, {'status': 'BLOCKED'})
    original = output.read_text(encoding='utf-8')

    with pytest.raises(FileExistsError):
        write_json_exclusive(output, {'status': 'COMPLETE'})

    assert output.read_text(encoding='utf-8') == original


def test_cli_writes_blocked_report_and_returns_nonzero(tmp_path):
    output = tmp_path / 'blocked.json'
    exit_code = main([
        '--manifest', str(tmp_path / 'missing.json'),
        '--model-path', str(tmp_path / 'missing-model'),
        '--json-output', str(output),
    ])

    report = json.loads(output.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert report['status'] == 'BLOCKED'
    assert report['delivery_ready'] is False
    assert report['cases'] == []
    assert report['transcription_status'] == 'decoded_not_transcribed'


def test_cli_refuses_existing_output_before_runner_execution(
        tmp_path, monkeypatch):
    output = tmp_path / 'existing.json'
    output.write_text('operator-owned\n', encoding='utf-8')
    from limo_cleanup_voice import voice_wav_transcription_run as runner

    monkeypatch.setattr(
        runner,
        'run_wav_transcription',
        lambda *_args, **_kwargs: pytest.fail(
            'runner must not execute when output already exists'),
    )

    with pytest.raises(SystemExit) as error:
        main([
            '--manifest', str(tmp_path / 'missing.json'),
            '--model-path', str(tmp_path / 'missing-model'),
            '--json-output', str(output),
        ])

    assert error.value.code == 2
    assert output.read_text(encoding='utf-8') == 'operator-owned\n'
