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

"""Run gated, deterministic Vosk transcription on the four-file corpus."""

import argparse
import hashlib
import importlib
import io
import json
import math
import time
import wave
from pathlib import Path

from . import command_parser as command_parser_module
from . import voice_corpus_readiness as corpus_readiness_module
from . import voice_grammar as voice_grammar_module
from .command_parser import (
    has_wake_word,
    is_priority_stop_text,
    parse_command,
)
from .voice_contract import WAKE_WORD
from .voice_corpus_readiness import (
    evaluate_corpus_readiness,
    sha256_file,
)
from .voice_grammar import DEFAULT_GRAMMAR


EXPECTED_CASE_COUNT = 4
EXPECTED_COVERAGE = {
    'ordinary_intent': 2,
    'priority_stop': 1,
    'wake_only': 1,
}
ORDINARY_INTENTS = frozenset({
    'inspect_bottle',
    'navigate_to_bin',
    'start_cleanup',
    'start_touch',
})
SHA256_LENGTH = 64
RUN_MODE = 'offline_vosk_wav_transcription_no_ros_no_microphone'


def _canonical_sha256(value):
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(rendered).hexdigest()


def _is_sha256(value):
    text = str(value or '')
    return len(text) == SHA256_LENGTH and all(
        character in '0123456789abcdef' for character in text)


def _duration_ms(start_ns, end_ns):
    return round(max(0, end_ns - start_ns) / 1000000.0, 3)


def _path_matches(left, right):
    try:
        return Path(left).resolve() == Path(right).resolve()
    except (OSError, TypeError, ValueError):
        return False


def _source_report(extra_modules=()):
    modules = (
        ('command_parser', command_parser_module),
        ('voice_corpus_readiness', corpus_readiness_module),
        ('voice_grammar', voice_grammar_module),
        ('voice_wav_transcription_run', importlib.import_module(__name__)),
    ) + tuple(extra_modules)
    files = []
    seen = set()
    for name, module in sorted(modules, key=lambda item: item[0]):
        source_value = getattr(module, '__file__', None)
        if not source_value:
            continue
        source_path = Path(source_value).resolve()
        source_key = str(source_path).casefold()
        if source_key in seen or not source_path.is_file():
            continue
        seen.add(source_key)
        files.append({
            'module': name,
            'bytes': source_path.stat().st_size,
            'sha256': sha256_file(source_path),
        })
    return {
        'files': files,
        'bundle_sha256': _canonical_sha256(files),
    }


def _base_report(manifest_path, model_path):
    manifest = Path(manifest_path).resolve()
    return {
        'schema_version': 1,
        'status': 'BLOCKED',
        'mode': RUN_MODE,
        'delivery_ready': False,
        'transcription_status': 'decoded_not_transcribed',
        'ground_truth_transcripts_available': False,
        'accuracy_claimed': False,
        'accuracy_status': 'NOT_EVALUATED_NO_GROUND_TRUTH',
        'label_policy': 'filename_labels_are_prompts_not_transcripts',
        'safety': {
            'network_used': False,
            'ros_graph_used': False,
            'microphone_used': False,
            'hardware_used': False,
            'ordinary_intents_mock_only': True,
            'intent_published': False,
            'labels_used_as_transcripts': False,
        },
        'inputs': {
            'manifest': str(manifest),
            'requested_model_path': (
                str(Path(model_path).resolve())
                if str(model_path or '').strip() else None),
        },
        'model': None,
        'source': _source_report(),
        'corpus': None,
        'input_fingerprint_sha256': None,
        'timing_ms': {},
        'summary': {
            'case_count': 0,
            'completed_count': 0,
            'empty_transcript_count': 0,
            'confidence_available_count': 0,
            'wake_word_detected_count': 0,
            'priority_stop_detected_count': 0,
            'ordinary_intent_candidate_count': 0,
        },
        'blocking_issues': [],
        'cases': [],
    }


def _default_intake_validator():
    module = importlib.import_module(
        '.voice_model_intake', package=__package__)
    validator = getattr(module, 'validate_local_vosk_model')
    return validator, module


def _model_gate_issues(report, requested_path):
    if not isinstance(report, dict):
        return ['model intake API did not return an object']
    issues = []
    if report.get('status') != 'PASS':
        issues.append('model intake status is not PASS')
    if report.get('delivery_ready') is not True:
        issues.append('model intake delivery_ready is not true')
    model = report.get('model')
    if not isinstance(model, dict):
        issues.append('model intake report is missing model inventory')
        model = {}
    if not _path_matches(model.get('path'), requested_path):
        issues.append('validated model path does not match requested path')
    inventory = model.get('inventory')
    if not isinstance(inventory, dict):
        issues.append('model intake report is missing model inventory')
        inventory = {}
    if not _is_sha256(inventory.get('directory_sha256')):
        issues.append('model directory SHA-256 is missing or invalid')
    files = inventory.get('files')
    if not isinstance(files, list) or not files:
        issues.append('model inventory is empty')
    elif inventory.get('file_count') != len(files):
        issues.append('model inventory file_count does not match files')
    if not isinstance(inventory.get('total_bytes'), int) \
            or inventory.get('total_bytes') <= 0:
        issues.append('model inventory total_bytes is invalid')
    validation = model.get('validation')
    if not isinstance(validation, dict) \
            or validation.get('ready') is not True:
        issues.append('model validation ready gate did not pass')
    grammar_probe = report.get('grammar_probe')
    if not isinstance(grammar_probe, dict):
        issues.append('restricted grammar probe is missing')
    else:
        if grammar_probe.get('attempted') is not True:
            issues.append('restricted grammar probe was not attempted')
        if grammar_probe.get('passed') is not True:
            issues.append('restricted grammar probe did not pass')
        if not _is_sha256(grammar_probe.get('phrases_sha256')):
            issues.append('restricted grammar SHA-256 is invalid')
    return issues


def _model_summary(intake_report):
    model = intake_report.get('model') or {}
    inventory = model.get('inventory') or {}
    probe = intake_report.get('grammar_probe') or {}
    return {
        'path': model.get('path'),
        'directory_sha256': inventory.get('directory_sha256'),
        'file_count': inventory.get('file_count'),
        'total_bytes': inventory.get('total_bytes'),
        'intake_report_sha256': _canonical_sha256(intake_report),
        'grammar_phrases_sha256': probe.get('phrases_sha256'),
        'grammar_phrase_count': probe.get('phrase_count'),
        'grammar_probe_passed': probe.get('passed') is True,
    }


def _corpus_issues(readiness):
    model_issues = set((readiness.get('model') or {}).get('issues') or [])
    return sorted(
        issue for issue in readiness.get('blocking_issues', [])
        if issue not in model_issues)


def _relative_audio_path(audio_path, manifest_path):
    path = Path(audio_path).resolve()
    try:
        return path.relative_to(Path(manifest_path).resolve().parent).as_posix()
    except ValueError:
        return None


def _corpus_summary(readiness):
    files = []
    for case in readiness.get('cases', []):
        audio = case.get('audio') or {}
        files.append({
            'id': case.get('id'),
            'coverage_class': case.get('coverage_class'),
            'audio_path': _relative_audio_path(
                case.get('audio_path'), readiness.get('manifest')),
            'bytes': audio.get('bytes'),
            'sha256': audio.get('sha256'),
            'duration_sec': audio.get('duration_sec'),
        })
    hash_inputs = [
        {
            'id': item['id'],
            'audio_path': item['audio_path'],
            'sha256': item['sha256'],
        }
        for item in files
    ]
    return {
        'manifest': readiness.get('manifest'),
        'manifest_sha256': readiness.get('manifest_sha256'),
        'audio_set_sha256': _canonical_sha256(hash_inputs),
        'case_count': readiness.get('corpus', {}).get('case_count'),
        'total_duration_sec': readiness.get(
            'corpus', {}).get('total_duration_sec'),
        'coverage': readiness.get('corpus', {}).get('coverage'),
        'files': files,
    }


def _corpus_gate_issues(readiness, manifest_path):
    issues = []
    if readiness.get('corpus_ready') is not True:
        issues.extend(_corpus_issues(readiness))
        if not issues:
            issues.append('corpus readiness gate did not pass')
    corpus = readiness.get('corpus') or {}
    if corpus.get('case_count') != EXPECTED_CASE_COUNT:
        issues.append('corpus must contain exactly four WAV cases')
    if corpus.get('coverage') != EXPECTED_COVERAGE:
        issues.append(
            'corpus coverage must be wake=1, priority_stop=1, '
            'ordinary_intent=2')
    if not _is_sha256(readiness.get('manifest_sha256')):
        issues.append('corpus manifest SHA-256 is invalid')
    if not _path_matches(readiness.get('manifest'), manifest_path):
        issues.append('corpus readiness manifest path changed')
    for case in readiness.get('cases', []):
        if _relative_audio_path(
                case.get('audio_path'), manifest_path) is None:
            issues.append(
                'corpus audio path escaped manifest directory: {}'.format(
                    case.get('id')))
    return sorted(set(issues))


def _read_frozen_wav(path, expected_sha256):
    wav_path = Path(path)
    content = wav_path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError('WAV SHA-256 changed after corpus readiness')
    with wave.open(io.BytesIO(content), 'rb') as wav_file:
        if wav_file.getnchannels() != 1:
            raise ValueError('WAV input must be mono')
        if wav_file.getsampwidth() != 2:
            raise ValueError('WAV input must use 16-bit PCM samples')
        if wav_file.getframerate() != 16000:
            raise ValueError('WAV input must use a 16000 Hz sample rate')
        frame_count = wav_file.getnframes()
        payload = wav_file.readframes(frame_count)
    return {
        'sample_rate': 16000,
        'frame_count': frame_count,
        'duration_sec': frame_count / 16000.0,
        'payload': payload,
        'sha256': actual_sha256,
    }


def _normalized_transcriber_result(result):
    if not isinstance(result, dict):
        raise TypeError('transcriber result must be an object')
    transcript = result.get('transcript')
    confidences = result.get('word_confidences')
    if not isinstance(transcript, str):
        raise TypeError('transcriber transcript must be a string')
    if not isinstance(confidences, list):
        raise TypeError('transcriber word_confidences must be a list')
    values = []
    for confidence in confidences:
        value = float(confidence)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError('word confidence must be between 0 and 1')
        values.append(value)
    return ' '.join(transcript.split()), values


def _confidence_report(confidences):
    if not confidences:
        return {
            'available': False,
            'word_count': 0,
            'mean': None,
            'minimum': None,
            'maximum': None,
        }
    return {
        'available': True,
        'word_count': len(confidences),
        'mean': round(sum(confidences) / len(confidences), 6),
        'minimum': round(min(confidences), 6),
        'maximum': round(max(confidences), 6),
    }


def _parse_observed_transcript(transcript):
    wake_detected = has_wake_word(transcript, [WAKE_WORD])
    stop_detected = is_priority_stop_text(transcript)
    parsed = parse_command(
        transcript,
        wake_words=[WAKE_WORD],
        require_wake_word=True,
    )
    ordinary_detected = (
        parsed.name in ORDINARY_INTENTS
        and parsed.requires_confirmation is True
    )
    return {
        'wake_word_detected': wake_detected,
        'priority_stop_detected': stop_detected,
        'parser_intent': {
            'name': parsed.name,
            'command_text': parsed.command_text,
            'requires_confirmation': parsed.requires_confirmation,
            'reason': parsed.reason,
        },
        'ordinary_intent': {
            'candidate_detected': ordinary_detected,
            'name': parsed.name if ordinary_detected else None,
            'requires_confirmation': (
                parsed.requires_confirmation if ordinary_detected else False),
            'mock_only': True,
            'confirmation_executed': False,
            'published': False,
        },
    }


def _transcription_gate_issues(cases):
    issues = []
    empty_count = sum(case['transcript_is_empty'] for case in cases)
    if empty_count:
        issues.append(
            '{} required WAV transcript(s) are empty'.format(empty_count))
    stop_cases = [
        case for case in cases
        if case['coverage_class'] == 'priority_stop'
    ]
    if len(stop_cases) != 1 or not stop_cases[0]['observed'][
            'priority_stop_detected']:
        issues.append('required priority-stop WAV was not detected')
    wake_cases = [
        case for case in cases if case['coverage_class'] == 'wake_only'
    ]
    if len(wake_cases) != 1 or not wake_cases[0]['observed'][
            'wake_word_detected']:
        issues.append('required wake-only WAV was not detected')
    ordinary_cases = [
        case for case in cases
        if case['coverage_class'] == 'ordinary_intent'
    ]
    ordinary_safe = all(
        case['observed']['parser_intent']['name'] == 'ignored'
        and not case['observed']['ordinary_intent']['candidate_detected']
        and not case['observed']['ordinary_intent']['published']
        for case in ordinary_cases
    )
    if len(ordinary_cases) != 2 or not ordinary_safe:
        issues.append(
            'unwoken ordinary WAV crossed the fail-closed parser gate')
    return issues


class OfflineVoskTranscriber:
    """Load one local Vosk model and transcribe PCM16 WAV payloads."""

    def __init__(self, model_path):
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError('Vosk Python runtime is unavailable') from error
        self._model = Model(str(Path(model_path).resolve()))
        self._recognizer_type = KaldiRecognizer
        self._grammar = json.dumps(DEFAULT_GRAMMAR, ensure_ascii=False)

    @staticmethod
    def _result_fields(rendered):
        data = json.loads(rendered)
        if not isinstance(data, dict):
            raise ValueError('Vosk result must be an object')
        text = str(data.get('text', '')).strip()
        confidences = []
        words = data.get('result', [])
        if words is None:
            words = []
        if not isinstance(words, list):
            raise ValueError('Vosk word result must be a list')
        for word in words:
            if isinstance(word, dict) and 'conf' in word:
                confidences.append(word['conf'])
        return text, confidences

    def __call__(self, audio_path, sample_rate, pcm16_bytes):
        """Return transcript and Vosk word confidences for one WAV."""
        del audio_path
        recognizer = self._recognizer_type(
            self._model,
            float(sample_rate),
            self._grammar,
        )
        if hasattr(recognizer, 'SetWords'):
            recognizer.SetWords(True)
        transcripts = []
        confidences = []
        for offset in range(0, len(pcm16_bytes), 8000):
            block = pcm16_bytes[offset:offset + 8000]
            if recognizer.AcceptWaveform(block):
                text, words = self._result_fields(recognizer.Result())
                if text:
                    transcripts.append(text)
                confidences.extend(words)
        text, words = self._result_fields(recognizer.FinalResult())
        if text:
            transcripts.append(text)
        confidences.extend(words)
        return {
            'transcript': ' '.join(transcripts).strip(),
            'word_confidences': confidences,
        }


def _failed_report(report, issue, start_ns, clock_ns):
    report['status'] = 'FAILED'
    report['delivery_ready'] = False
    report['transcription_status'] = 'incomplete'
    report['blocking_issues'].append(issue)
    report['blocking_issues'] = sorted(set(report['blocking_issues']))
    report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
    return report


def run_wav_transcription(
        manifest_path,
        model_path,
        *,
        intake_validator=None,
        transcriber_factory=None,
        clock_ns=None):
    """Run model-gated offline transcription without claiming accuracy."""
    clock_ns = clock_ns or time.perf_counter_ns
    start_ns = clock_ns()
    report = _base_report(manifest_path, model_path)
    model_text = str(model_path or '').strip()
    if not model_text:
        report['blocking_issues'] = [
            'an explicit user-provided local model path is required']
        report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
        return report

    intake_module = None
    try:
        if intake_validator is None:
            intake_validator, intake_module = _default_intake_validator()
        intake_start = clock_ns()
        intake_report = intake_validator(model_text)
        report['timing_ms']['model_intake'] = _duration_ms(
            intake_start, clock_ns())
    except Exception as error:  # noqa: BLE001 - serialized fail-closed report
        report['blocking_issues'] = [
            'model intake validation failed: {}: {}'.format(
                type(error).__name__, error)]
        report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
        return report

    if intake_module is not None:
        report['source'] = _source_report((
            ('voice_model_intake', intake_module),
        ))
    try:
        report['model'] = _model_summary(intake_report)
    except (TypeError, ValueError) as error:
        report['blocking_issues'] = [
            'model intake report is not deterministic JSON: {}'.format(error)]
        report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
        return report
    gate_issues = _model_gate_issues(intake_report, model_text)
    if gate_issues:
        declared_issues = intake_report.get('blocking_issues')
        if isinstance(declared_issues, list):
            gate_issues.extend(
                'model intake: {}'.format(issue)
                for issue in declared_issues
                if isinstance(issue, str) and issue.strip()
            )
        report['blocking_issues'] = sorted(set(gate_issues))
        report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
        return report

    try:
        corpus_start = clock_ns()
        readiness = evaluate_corpus_readiness(manifest_path, None)
        report['timing_ms']['corpus_readiness'] = _duration_ms(
            corpus_start, clock_ns())
        report['corpus'] = _corpus_summary(readiness)
    except Exception as error:  # noqa: BLE001 - serialized fail-closed report
        report['blocking_issues'] = [
            'corpus readiness failed: {}: {}'.format(
                type(error).__name__, error)]
        report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
        return report
    corpus_gate_issues = _corpus_gate_issues(readiness, manifest_path)
    if corpus_gate_issues:
        report['blocking_issues'] = corpus_gate_issues
        report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
        return report

    report['input_fingerprint_sha256'] = _canonical_sha256({
        'model_sha256': report['model']['directory_sha256'],
        'source_sha256': report['source']['bundle_sha256'],
        'manifest_sha256': report['corpus']['manifest_sha256'],
        'audio_set_sha256': report['corpus']['audio_set_sha256'],
    })
    try:
        factory = transcriber_factory or OfflineVoskTranscriber
        load_start = clock_ns()
        transcriber = factory(model_text)
        report['timing_ms']['transcriber_load'] = _duration_ms(
            load_start, clock_ns())
    except Exception as error:  # noqa: BLE001 - serialized failure report
        return _failed_report(
            report,
            'transcriber initialization failed: {}: {}'.format(
                type(error).__name__, error),
            start_ns,
            clock_ns,
        )

    for case in readiness['cases']:
        try:
            audio = _read_frozen_wav(
                case['audio_path'], case['audio']['sha256'])
            case_start = clock_ns()
            raw_result = transcriber(
                Path(case['audio_path']),
                audio['sample_rate'],
                audio['payload'],
            )
            asr_end = clock_ns()
            transcript, confidences = _normalized_transcriber_result(
                raw_result)
            observed = _parse_observed_transcript(transcript)
            parse_end = clock_ns()
        except Exception as error:  # noqa: BLE001 - serialized failure report
            return _failed_report(
                report,
                'case {} transcription failed: {}: {}'.format(
                    case.get('id'), type(error).__name__, error),
                start_ns,
                clock_ns,
            )

        asr_ms = _duration_ms(case_start, asr_end)
        parse_ms = _duration_ms(asr_end, parse_end)
        total_ms = _duration_ms(case_start, parse_end)
        duration_ms = audio['duration_sec'] * 1000.0
        confidence = _confidence_report(confidences)
        report['cases'].append({
            'id': case['id'],
            'coverage_class': case['coverage_class'],
            'audio_path': _relative_audio_path(
                case['audio_path'], manifest_path),
            'audio_sha256': audio['sha256'],
            'duration_sec': round(audio['duration_sec'], 6),
            'transcript': transcript,
            'transcript_source': 'vosk_offline_audio',
            'transcript_is_empty': not bool(transcript),
            'confidence': confidence,
            'latency_ms': {
                'asr': asr_ms,
                'intent_parse': parse_ms,
                'end_to_end': total_ms,
                'real_time_factor': (
                    round(asr_ms / duration_ms, 6)
                    if duration_ms else None),
            },
            'observed': observed,
            'evaluation': {
                'ground_truth_available': False,
                'accuracy_evaluated': False,
                'coverage_class_used_as_expected_intent': False,
            },
        })

    if sha256_file(Path(manifest_path).resolve()) != (
            report['corpus']['manifest_sha256']):
        return _failed_report(
            report,
            'corpus manifest changed during transcription',
            start_ns,
            clock_ns,
        )

    cases = report['cases']
    report['summary'] = {
        'case_count': len(cases),
        'completed_count': len(cases),
        'empty_transcript_count': sum(
            case['transcript_is_empty'] for case in cases),
        'confidence_available_count': sum(
            case['confidence']['available'] for case in cases),
        'wake_word_detected_count': sum(
            case['observed']['wake_word_detected'] for case in cases),
        'priority_stop_detected_count': sum(
            case['observed']['priority_stop_detected'] for case in cases),
        'ordinary_intent_candidate_count': sum(
            case['observed']['ordinary_intent']['candidate_detected']
            for case in cases),
    }
    transcription_issues = _transcription_gate_issues(cases)
    report['status'] = 'FAILED' if transcription_issues else 'COMPLETE'
    report['delivery_ready'] = False
    report['transcription_status'] = (
        'incomplete' if transcription_issues else 'completed')
    report['blocking_issues'] = transcription_issues + [
        'final delivery requires the hashed real-WAV ground-truth A/B, '
        'accuracy thresholds, and ROS1 runtime gate',
    ]
    report['timing_ms']['total'] = _duration_ms(start_ns, clock_ns())
    return report


def write_json_exclusive(path, report):
    """Create a JSON report without overwriting an existing output."""
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    with Path(path).open('x', encoding='utf-8', newline='\n') as output:
        output.write(rendered)


def main(args=None):
    """Run gated transcription and exclusively create its JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--json-output', required=True)
    parsed = parser.parse_args(args)
    output_path = Path(parsed.json_output)
    if output_path.exists():
        parser.error('json output already exists; refusing to overwrite')
    report = run_wav_transcription(parsed.manifest, parsed.model_path)
    try:
        write_json_exclusive(output_path, report)
    except FileExistsError:
        parser.error('json output already exists; refusing to overwrite')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
