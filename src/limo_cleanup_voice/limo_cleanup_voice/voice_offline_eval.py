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

"""Evaluate prerecorded WAV cases without opening an audio input device."""

import argparse
import json
import wave
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from .command_parser import normalize_text, parse_command
from .voice_contract import WAKE_WORD
from .voice_grammar import DEFAULT_GRAMMAR


EVALUATION_CASE_FIELDS = frozenset({
    'id',
    'audio_path',
    'expected_transcript',
    'expected_intent',
    'negative',
    'transcript_fixture',
})
ACTIONABLE_INTENTS = frozenset({
    'start_cleanup',
    'start_touch',
    'navigate_to_bin',
    'inspect_bottle',
    'stop_task',
})
PARSER_INTENT_NAMES = frozenset({
    'empty',
    'stop_task',
    'ignored',
    'reject_confirmation',
    'confirm',
    'unsupported',
    'report_status',
    'pause_unsupported',
    'resume_unsupported',
    'return_unsupported',
    'navigate_to_bin',
    'inspect_bottle',
    'start_touch',
    'start_cleanup',
})


def _resolve_manifest_audio_path(audio_path, manifest_dir, case_id):
    """Resolve one contained, relative manifest audio path."""
    raw_path = audio_path.strip()
    path_variants = (PurePosixPath(raw_path), PureWindowsPath(raw_path))
    if urlsplit(raw_path).scheme:
        raise ValueError(
            'manifest case {} audio_path must not be a URI'.format(case_id))
    if any(path.anchor or path.drive for path in path_variants):
        raise ValueError(
            'manifest case {} audio_path must be relative to the manifest'
            .format(case_id))
    if any(
            part == '..'
            for path in path_variants
            for part in path.parts):
        raise ValueError(
            'manifest case {} audio_path must not contain parent traversal'
            .format(case_id))

    resolved_path = (manifest_dir / Path(raw_path)).resolve()
    try:
        resolved_path.relative_to(manifest_dir)
    except ValueError as error:
        raise ValueError(
            'manifest case {} audio_path escapes the manifest directory'
            .format(case_id)) from error
    return resolved_path


def _validated_evaluation_cases(data, manifest_dir):
    """Validate explicit ground truth before reading audio or loading ASR."""
    if not isinstance(data, dict) or set(data) != {'cases'}:
        raise ValueError(
            'evaluation manifest fields must be exactly: cases')
    cases = data['cases']
    if not isinstance(cases, list) or not cases:
        raise ValueError('manifest must contain a non-empty cases list')

    validated = []
    case_ids = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(
                'manifest case {} must be an object'.format(index))
        unknown_fields = sorted(set(case) - EVALUATION_CASE_FIELDS)
        if unknown_fields:
            raise ValueError(
                'manifest case {} has unknown evaluation fields: {}'.format(
                    index, ', '.join(unknown_fields)))

        case_id = case.get('id')
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(
                'manifest case {} requires a non-empty id'.format(index))
        case_id = case_id.strip()
        if case_id in case_ids:
            raise ValueError('duplicate manifest case id: {}'.format(case_id))
        case_ids.add(case_id)

        audio_path = case.get('audio_path')
        if not isinstance(audio_path, str) or not audio_path.strip():
            raise ValueError(
                'manifest case {} requires audio_path'.format(case_id))
        expected_intent = case.get('expected_intent')
        if not isinstance(expected_intent, str) \
                or not expected_intent.strip():
            raise ValueError(
                'manifest case {} requires expected_intent ground '
                'truth'.format(case_id))
        expected_intent = expected_intent.strip()
        if expected_intent not in PARSER_INTENT_NAMES:
            raise ValueError(
                'manifest case {} expected_intent is not produced by the '
                'parser: {}'.format(case_id, expected_intent))

        has_expected_transcript = 'expected_transcript' in case
        has_fixture = 'transcript_fixture' in case
        if not has_expected_transcript and not has_fixture:
            raise ValueError(
                'manifest case {} requires expected_transcript ground truth; '
                'transcript_fixture is allowed only for fixture/CI '
                'mode'.format(case_id))
        if has_expected_transcript and has_fixture:
            raise ValueError(
                'manifest case {} expected_transcript and '
                'transcript_fixture are mutually exclusive'.format(case_id))
        if has_expected_transcript and not isinstance(
                case['expected_transcript'], str):
            raise ValueError(
                'manifest case {} expected_transcript must be a string'.format(
                    case_id))
        if has_fixture and not isinstance(case['transcript_fixture'], str):
            raise ValueError(
                'manifest case {} transcript_fixture must be a string'.format(
                    case_id))
        if 'negative' in case and not isinstance(case['negative'], bool):
            raise ValueError(
                'manifest case {} negative must be boolean'.format(case_id))
        resolved_audio_path = _resolve_manifest_audio_path(
            audio_path, manifest_dir, case_id)
        normalized_case = dict(case)
        normalized_case['id'] = case_id
        normalized_case['audio_path'] = audio_path.strip()
        normalized_case['expected_intent'] = expected_intent
        validated.append((normalized_case, resolved_audio_path))
    return validated


def read_pcm16_mono_wav(path):
    """Read and validate a mono 16-bit PCM WAV file."""
    wav_path = Path(path)
    with wave.open(str(wav_path), 'rb') as wav_file:
        if wav_file.getnchannels() != 1:
            raise ValueError('WAV input must be mono')
        if wav_file.getsampwidth() != 2:
            raise ValueError('WAV input must use 16-bit PCM samples')
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        audio = wav_file.readframes(frame_count)
    return {
        'path': str(wav_path.resolve()),
        'sample_rate': sample_rate,
        'frame_count': frame_count,
        'duration_sec': (
            float(frame_count) / sample_rate if sample_rate else 0.0),
        'audio': audio,
    }


def recognize_wav_vosk(path, model_path, grammar=None):
    """Recognize one WAV with offline Vosk and no microphone access."""
    try:
        from vosk import KaldiRecognizer, Model
    except ImportError as error:
        raise RuntimeError('Vosk is required for WAV recognition') from error

    audio = read_pcm16_mono_wav(path)
    model = Model(str(model_path))
    recognizer = KaldiRecognizer(
        model,
        float(audio['sample_rate']),
        json.dumps(grammar or DEFAULT_GRAMMAR, ensure_ascii=False),
    )
    transcripts = []
    block_bytes = 8000
    payload = audio['audio']
    for offset in range(0, len(payload), block_bytes):
        if recognizer.AcceptWaveform(payload[offset:offset + block_bytes]):
            result = json.loads(recognizer.Result())
            if result.get('text', '').strip():
                transcripts.append(result['text'].strip())
    final_result = json.loads(recognizer.FinalResult())
    if final_result.get('text', '').strip():
        transcripts.append(final_result['text'].strip())
    return ' '.join(transcripts).strip()


def evaluate_manifest(manifest_path, model_path=None, transcriber=None):
    """Evaluate a JSON manifest of WAV files and expected V2 outcomes."""
    path = Path(manifest_path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    cases = _validated_evaluation_cases(data, path.parent)

    results = []
    negative_count = 0
    false_activations = 0
    for case, audio_path in cases:
        case_id = case['id']
        audio = read_pcm16_mono_wav(audio_path)

        if transcriber is not None:
            transcript = str(transcriber(audio_path, case)).strip()
            transcript_source = 'injected_transcriber'
        elif 'transcript_fixture' in case:
            transcript = str(case['transcript_fixture']).strip()
            transcript_source = 'manifest_fixture'
        else:
            if not model_path:
                raise ValueError(
                    'model_path is required without transcript_fixture')
            transcript = recognize_wav_vosk(audio_path, model_path)
            transcript_source = 'vosk_wav'

        intent = parse_command(
            transcript,
            wake_words=[WAKE_WORD],
            require_wake_word=True,
        )
        expected_transcript = case.get(
            'expected_transcript', case.get('transcript_fixture'))
        expected_intent = case['expected_intent'].strip()
        transcript_match = (
            normalize_text(transcript) == normalize_text(expected_transcript))
        intent_match = intent.name == expected_intent
        negative = bool(case.get('negative', False))
        activated = intent.name in ACTIONABLE_INTENTS
        if negative:
            negative_count += 1
            if activated:
                false_activations += 1
        results.append({
            'id': case_id,
            'audio_path': audio['path'],
            'duration_sec': round(audio['duration_sec'], 6),
            'sample_rate': audio['sample_rate'],
            'transcript': transcript,
            'transcript_source': transcript_source,
            'expected_transcript': expected_transcript,
            'expected_intent': expected_intent,
            'intent': intent.name,
            'transcript_match': transcript_match,
            'intent_match': intent_match,
            'negative': negative,
            'false_activation': negative and activated,
            'passed': transcript_match and intent_match
            and not (negative and activated),
        })

    passed = sum(1 for item in results if item['passed'])
    report = {
        'status': 'PASS' if passed == len(results) else 'FAIL',
        'mode': 'offline_wav_no_microphone',
        'manifest': str(path),
        'case_count': len(results),
        'passed_count': passed,
        'failed_count': len(results) - passed,
        'negative_count': negative_count,
        'false_activation_count': false_activations,
        'false_activation_rate': (
            float(false_activations) / negative_count
            if negative_count else 0.0),
        'cases': results,
    }
    return report


def main(args=None):
    """Evaluate prerecorded files and emit a reproducible JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--model-path')
    parser.add_argument('--json-output')
    parsed = parser.parse_args(args)
    report = evaluate_manifest(parsed.manifest, parsed.model_path)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if parsed.json_output:
        Path(parsed.json_output).write_text(
            rendered + '\n', encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
