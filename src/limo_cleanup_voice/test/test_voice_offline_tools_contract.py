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

"""Independent fail-closed contracts for offline voice tooling."""

import hashlib
import json
import math
import struct
import wave

import pytest

import limo_cleanup_voice.voice_offline_eval as offline_eval
from limo_cleanup_voice.voice_corpus_readiness import (
    LABEL_POLICY,
    REQUIRED_COVERAGE_CLASSES,
    evaluate_corpus_readiness,
    inspect_pcm16_wav,
)
from limo_cleanup_voice.voice_offline_eval import evaluate_manifest


def _write_speech_like_wav(path, frequency_hz=440):
    sample_rate = 16000
    samples = []
    for index in range(sample_rate):
        if 3200 <= index < 12800:
            sample = int(4000 * math.sin(
                2 * math.pi * frequency_hz * index / sample_rate))
        else:
            sample = 0
        samples.append(sample)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack('<{}h'.format(len(samples)), *samples))


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _readiness_fixture(tmp_path):
    definitions = (
        ('wake', '小莫小莫', 'wake_only', '000000000001'),
        ('stop', '停下', 'priority_stop', '000000000002'),
        ('task', '捡矿泉水瓶', 'ordinary_intent', '000000000003'),
    )
    cases = []
    for case_index, definition in enumerate(definitions):
        case_id, label, coverage, suffix = definition
        source = tmp_path / '{}.m4a'.format(case_id)
        source.write_bytes(('source-' + case_id).encode('ascii'))
        audio = tmp_path / 'voice_{}_16k_mono_pcm.wav'.format(suffix)
        _write_speech_like_wav(audio, frequency_hz=440 + case_index * 110)
        statistics = inspect_pcm16_wav(audio)
        cases.append({
            'source_name': source.name,
            'id': 'voice-' + suffix,
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


def test_offline_eval_rejects_missing_ground_truth_before_audio_access(
        tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{
        'id': 'decode-case',
        'audio_path': 'missing.wav',
    }]}), encoding='utf-8')

    with pytest.raises(ValueError, match='requires expected_intent'):
        evaluate_manifest(manifest)


def test_offline_eval_rejects_decode_manifest_schema(tmp_path):
    manifest = tmp_path / 'decode_manifest.json'
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'cases': [],
    }), encoding='utf-8')

    with pytest.raises(ValueError, match='fields must be exactly'):
        evaluate_manifest(manifest)


def test_offline_eval_requires_transcript_ground_truth_or_fixture(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{
        'id': 'intent-only',
        'audio_path': 'missing.wav',
        'expected_intent': 'ignored',
    }]}), encoding='utf-8')

    with pytest.raises(ValueError, match='requires expected_transcript'):
        evaluate_manifest(manifest)


def test_offline_eval_rejects_non_parser_expected_intent_before_audio_access(
        tmp_path, monkeypatch):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [
        {
            'id': 'valid-first-case',
            'audio_path': 'missing-first.wav',
            'transcript_fixture': '',
            'expected_intent': 'empty',
        },
        {
            'id': 'invalid-second-case',
            'audio_path': 'missing-second.wav',
            'transcript_fixture': 'anything',
            'expected_intent': 'direct_twist',
        },
    ]}), encoding='utf-8')
    audio_reads = []

    def record_audio_read(path):
        audio_reads.append(path)
        raise AssertionError('audio must not be read during schema validation')

    monkeypatch.setattr(
        offline_eval, 'read_pcm16_mono_wav', record_audio_read)

    with pytest.raises(ValueError, match='not produced by the parser'):
        evaluate_manifest(manifest)
    assert audio_reads == []


def test_offline_eval_rejects_fixture_overriding_transcript_ground_truth(
        tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{
        'id': 'conflicting-transcripts',
        'audio_path': 'missing.wav',
        'expected_transcript': 'expected ground truth',
        'transcript_fixture': 'fixture override',
        'expected_intent': 'unsupported',
    }]}), encoding='utf-8')

    with pytest.raises(ValueError, match='mutually exclusive'):
        evaluate_manifest(manifest)


@pytest.mark.parametrize('unsafe_audio_path', [
    '../outside.wav',
    '..\\outside.wav',
    'file:///outside.wav',
    'https://example.invalid/audio.wav',
])
def test_offline_eval_rejects_audio_path_escape_or_uri(
        tmp_path, unsafe_audio_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{
        'id': 'unsafe-path',
        'audio_path': unsafe_audio_path,
        'transcript_fixture': '',
        'expected_intent': 'empty',
    }]}), encoding='utf-8')

    with pytest.raises(ValueError, match='audio_path'):
        evaluate_manifest(manifest)


def test_offline_eval_rejects_absolute_audio_path(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{
        'id': 'absolute-path',
        'audio_path': str(tmp_path / 'outside.wav'),
        'transcript_fixture': '',
        'expected_intent': 'empty',
    }]}), encoding='utf-8')

    with pytest.raises(ValueError, match='audio_path'):
        evaluate_manifest(manifest)


def test_offline_eval_rejects_symlink_escape(tmp_path):
    outside_dir = tmp_path.parent / '{}_outside'.format(tmp_path.name)
    outside_dir.mkdir()
    outside_audio = outside_dir / 'outside.wav'
    _write_speech_like_wav(outside_audio)
    linked_audio = tmp_path / 'linked.wav'
    try:
        linked_audio.symlink_to(outside_audio)
    except OSError as error:
        pytest.skip('test environment cannot create symlinks: {}'.format(
            error))

    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{
        'id': 'symlink-escape',
        'audio_path': linked_audio.name,
        'transcript_fixture': '',
        'expected_intent': 'empty',
    }]}), encoding='utf-8')

    with pytest.raises(ValueError, match='escapes the manifest directory'):
        evaluate_manifest(manifest)


def test_readiness_rejects_unlisted_generated_wav(tmp_path):
    manifest = _readiness_fixture(tmp_path)
    baseline = evaluate_corpus_readiness(manifest, tmp_path / 'missing-model')
    assert baseline['corpus_ready'] is True
    assert baseline['corpus']['unlisted_generated_wavs'] == []

    stale = tmp_path / 'voice_ffffffffffff_16k_mono_pcm.wav'
    _write_speech_like_wav(stale)
    report = evaluate_corpus_readiness(manifest, tmp_path / 'missing-model')

    assert report['corpus_ready'] is False
    assert report['delivery_ready'] is False
    assert report['corpus']['unlisted_generated_wavs'] == [stale.name]
    assert 'unlisted generated WAV: {}'.format(stale.name) in (
        report['blocking_issues'])


def test_readiness_ignores_unrelated_non_generated_files(tmp_path):
    manifest = _readiness_fixture(tmp_path)
    (tmp_path / 'operator_notes.wav').write_bytes(
        b'not a generated corpus WAV')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'missing-model')

    assert report['corpus_ready'] is True
    assert report['corpus']['unlisted_generated_wavs'] == []
