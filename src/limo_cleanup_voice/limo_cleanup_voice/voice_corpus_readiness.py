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

"""Audit a prerecorded voice corpus without opening devices or ROS."""

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
import wave
from array import array
from pathlib import Path

from .voice_grammar import DEFAULT_GRAMMAR


LABEL_POLICY = 'filename_labels_are_prompts_not_transcripts'
REQUIRED_COVERAGE_CLASSES = (
    'wake_only',
    'priority_stop',
    'ordinary_intent',
)
ALLOWED_COVERAGE_CLASSES = frozenset(REQUIRED_COVERAGE_CLASSES)
SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
GENERATED_WAV_NAME_PATTERN = re.compile(
    r'^voice_[0-9a-f]{12}_16k_mono_pcm[.]wav$', re.IGNORECASE)
OPENFST_MAGIC = b'\xd6\xfd\xb2\x7e'
MIN_MODEL_BYTES = 1024 * 1024
MIN_HCLR_BYTES = 1024
MIN_GR_BYTES = 32


def sha256_file(path, block_bytes=1024 * 1024):
    """Return a lowercase SHA-256 digest for one file."""
    if block_bytes <= 0:
        raise ValueError('block_bytes must be positive')
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            block = stream.read(block_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _dbfs(value):
    if value <= 0:
        return None
    return 20.0 * math.log10(float(value) / 32768.0)


def _pcm16_statistics(payload, sample_rate):
    samples = array('h')
    samples.frombytes(payload)
    if sys.byteorder != 'little':
        samples.byteswap()

    sample_count = len(samples)
    sum_squares = 0.0
    peak = 0
    clipped = 0
    frame_samples = 320
    frame_sum_squares = 0.0
    frame_sample_count = 0
    frame_rms = []
    for sample in samples:
        absolute = abs(sample)
        square = float(sample) * float(sample)
        sum_squares += square
        frame_sum_squares += square
        frame_sample_count += 1
        peak = max(peak, absolute)
        if absolute >= 32760:
            clipped += 1
        if frame_sample_count == frame_samples:
            frame_rms.append(math.sqrt(
                frame_sum_squares / frame_sample_count))
            frame_sum_squares = 0.0
            frame_sample_count = 0
    if frame_sample_count:
        frame_rms.append(math.sqrt(
            frame_sum_squares / frame_sample_count))

    rms = math.sqrt(sum_squares / sample_count)
    sorted_frames = sorted(frame_rms)
    floor_index = int(math.floor((len(sorted_frames) - 1) * 0.2))
    speech_gate = max(300.0, sorted_frames[floor_index] * 3.0)
    voiced_indexes = [
        index for index, value in enumerate(frame_rms)
        if value >= speech_gate
    ]
    duration = float(sample_count) / sample_rate
    frame_duration = float(frame_samples) / sample_rate
    if voiced_indexes:
        leading = voiced_indexes[0] * frame_duration
        trailing = max(
            0.0,
            duration - ((voiced_indexes[-1] + 1) * frame_duration),
        )
    else:
        leading = duration
        trailing = duration

    return {
        'rms': round(rms, 2),
        'rms_dbfs': (
            None if _dbfs(rms) is None else round(_dbfs(rms), 2)),
        'peak': peak,
        'peak_dbfs': (
            None if _dbfs(peak) is None else round(_dbfs(peak), 2)),
        'clipped_fraction': round(float(clipped) / sample_count, 8),
        'voiced_frame_fraction': round(
            float(len(voiced_indexes)) / len(frame_rms), 4),
        'leading_silence_sec_est': round(leading, 3),
        'trailing_silence_sec_est': round(trailing, 3),
    }


def inspect_pcm16_wav(path, required_rate=16000):
    """Inspect WAV format and conservative speech-quality readiness."""
    wav_path = Path(path).resolve()
    report = {
        'path': str(wav_path),
        'accessed': True,
        'exists': wav_path.is_file(),
        'sha256': None,
        'bytes': None,
        'sample_rate': None,
        'channels': None,
        'sample_width_bytes': None,
        'frame_count': None,
        'duration_sec': None,
        'format_pass': False,
        'quality_pass': False,
        'format_issues': [],
        'quality_issues': [],
    }
    if not report['exists']:
        report['format_issues'].append('WAV file is missing')
        return report

    report['sha256'] = sha256_file(wav_path)
    report['bytes'] = wav_path.stat().st_size
    try:
        with wave.open(str(wav_path), 'rb') as wav_file:
            report['channels'] = wav_file.getnchannels()
            report['sample_width_bytes'] = wav_file.getsampwidth()
            report['sample_rate'] = wav_file.getframerate()
            report['frame_count'] = wav_file.getnframes()
            compression = wav_file.getcomptype()
            payload = wav_file.readframes(report['frame_count'])
    except (EOFError, OSError, wave.Error) as error:
        report['format_issues'].append(
            'invalid WAV: {}: {}'.format(type(error).__name__, error))
        return report

    if compression != 'NONE':
        report['format_issues'].append('WAV must use uncompressed PCM')
    if report['channels'] != 1:
        report['format_issues'].append('WAV must be mono')
    if report['sample_width_bytes'] != 2:
        report['format_issues'].append('WAV must use 16-bit PCM samples')
    if report['sample_rate'] != required_rate:
        report['format_issues'].append(
            'WAV sample rate must be {} Hz'.format(required_rate))
    if report['frame_count'] <= 0:
        report['format_issues'].append('WAV must contain audio frames')

    expected_bytes = (
        report['frame_count']
        * report['channels']
        * report['sample_width_bytes']
    )
    if len(payload) != expected_bytes:
        report['format_issues'].append('WAV data is truncated')
    if report['sample_rate'] > 0:
        report['duration_sec'] = round(
            float(report['frame_count']) / report['sample_rate'], 6)
    else:
        report['format_issues'].append('WAV sample rate must be positive')
    report['format_pass'] = not report['format_issues']
    if not report['format_pass']:
        return report

    statistics = _pcm16_statistics(payload, report['sample_rate'])
    report.update(statistics)
    duration = report['duration_sec']
    rms_dbfs = report['rms_dbfs']
    if duration < 0.25 or duration > 15.0:
        report['quality_issues'].append(
            'duration must be between 0.25 and 15 seconds')
    if rms_dbfs is None:
        report['quality_issues'].append('audio is silent')
    elif rms_dbfs < -45.0 or rms_dbfs > -3.0:
        report['quality_issues'].append(
            'RMS must be between -45 and -3 dBFS')
    if report['clipped_fraction'] > 0.001:
        report['quality_issues'].append('clipped fraction exceeds 0.001')
    if report['voiced_frame_fraction'] < 0.05:
        report['quality_issues'].append(
            'voiced frame fraction must be at least 0.05')
    if report['leading_silence_sec_est'] > 2.0:
        report['quality_issues'].append('leading silence exceeds 2 seconds')
    if report['trailing_silence_sec_est'] > 2.0:
        report['quality_issues'].append('trailing silence exceeds 2 seconds')
    report['quality_pass'] = not report['quality_issues']
    return report


def _blocked_wav_report(path):
    """Return a report without touching a manifest-disallowed path."""
    return {
        'path': str(path),
        'accessed': False,
        'exists': None,
        'sha256': None,
        'bytes': None,
        'sample_rate': None,
        'channels': None,
        'sample_width_bytes': None,
        'frame_count': None,
        'duration_sec': None,
        'format_pass': False,
        'quality_pass': False,
        'format_issues': ['WAV path rejected by manifest policy'],
        'quality_issues': [],
    }


def _read_prefix(path, byte_count=4096):
    with path.open('rb') as stream:
        return stream.read(byte_count)


def _kaldi_model_header_valid(path):
    prefix = _read_prefix(path, 256)
    return (
        prefix.startswith(b'\x00B')
        and b'<TransitionModel>' in prefix
    )


def _openfst_header_valid(path):
    return _read_prefix(path, 4) == OPENFST_MAGIC


def _config_file_valid(path):
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return False
    options = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]
    return bool(options) and all(
        line.startswith('--') and '=' in line for line in options)


def _words_file_valid(path):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return False
    parsed = []
    for line in lines:
        fields = line.strip().rsplit(maxsplit=1)
        if len(fields) != 2:
            continue
        try:
            word_id = int(fields[1])
        except ValueError:
            continue
        parsed.append((fields[0], word_id))
    return (
        len(parsed) >= 10
        and parsed[0] == ('<eps>', 0)
        and len({word_id for _, word_id in parsed}) == len(parsed)
    )


def _integer_table_valid(path):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return False
    rows = [line.split() for line in lines if line.strip()]
    if not rows:
        return False
    try:
        for row in rows:
            if len(row) < 2:
                return False
            for value in row:
                int(value)
    except ValueError:
        return False
    return True


def _word_boundary_table_valid(path):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return False
    rows = [line.split() for line in lines if line.strip()]
    if len(rows) < 2:
        return False
    allowed_labels = {
        'begin', 'end', 'internal', 'singleton', 'nonword',
    }
    phone_ids = []
    for row in rows:
        if len(row) != 2:
            return False
        try:
            phone_id = int(row[0])
        except ValueError:
            return False
        if phone_id < 0:
            return False
        boundary = row[1]
        if boundary not in allowed_labels:
            try:
                if int(boundary) < 0:
                    return False
            except ValueError:
                return False
        phone_ids.append(phone_id)
    return len(set(phone_ids)) == len(phone_ids)


def _integer_list_valid(path):
    try:
        tokens = path.read_text(encoding='utf-8').split()
    except (OSError, UnicodeError):
        return False
    if not tokens:
        return False
    try:
        return all(int(token) >= 0 for token in tokens)
    except ValueError:
        return False


def _load_vosk_model(
        path, model_loader=None, recognizer_loader=None, grammar_phrases=None):
    runtime_available = model_loader is not None or (
        importlib.util.find_spec('vosk') is not None)
    if not runtime_available:
        return False, False, (
            'Vosk Python runtime is unavailable for grammar readiness check')
    try:
        if model_loader is None:
            from vosk import KaldiRecognizer, Model
            model_loader = Model
            recognizer_loader = KaldiRecognizer
        elif recognizer_loader is None:
            raise RuntimeError(
                'recognizer loader is required with an injected model loader')
        model = model_loader(str(path))
        recognizer_loader(
            model,
            16000.0,
            json.dumps(grammar_phrases or DEFAULT_GRAMMAR,
                       ensure_ascii=False),
        )
    except Exception as error:  # pragma: no cover - depends on local runtime
        return True, False, (
            'Vosk model or restricted-grammar recognizer failed to load: '
            '{}: {}'.format(
                type(error).__name__, error)
        )
    return True, True, None


def validate_vosk_model(
        model_path, model_loader=None, recognizer_loader=None,
        grammar_phrases=None):
    """Check model structure, signatures, and runtime loadability."""
    configured = bool(str(model_path or '').strip())
    path = Path(model_path).resolve() if configured else None
    final_model = path / 'am' / 'final.mdl' if path else None
    graph_directory = path / 'graph' if path else None
    hclg = graph_directory / 'HCLG.fst' if graph_directory else None
    hclr = graph_directory / 'HCLr.fst' if graph_directory else None
    grammar_graph = graph_directory / 'Gr.fst' if graph_directory else None
    final_present = bool(final_model and final_model.is_file())
    hclg_present = bool(hclg and hclg.is_file())
    words_file = graph_directory / 'words.txt' if graph_directory else None
    word_boundary = graph_directory / 'phones' / 'word_boundary.int' \
        if graph_directory else None
    report = {
        'path': str(path) if path else None,
        'configured': configured,
        'directory_present': bool(path and path.is_dir()),
        'final_mdl_present': final_present,
        'hclg_fst_present': hclg_present,
        'hclr_fst_present': bool(hclr and hclr.is_file()),
        'gr_fst_present': bool(grammar_graph and grammar_graph.is_file()),
        'words_txt_present': bool(words_file and words_file.is_file()),
        'word_boundary_present': bool(
            word_boundary and word_boundary.is_file()),
        'final_mdl_bytes': (
            final_model.stat().st_size
            if final_present else 0),
        'hclg_fst_bytes': (
            hclg.stat().st_size if hclg_present else 0),
        'hclr_fst_bytes': (
            hclr.stat().st_size if hclr and hclr.is_file() else 0),
        'gr_fst_bytes': (
            grammar_graph.stat().st_size
            if grammar_graph and grammar_graph.is_file() else 0),
        'graph_layout': None,
        'static_ready': False,
        'runtime_available': False,
        'loadability_checked': False,
        'loadable': False,
        'ready': False,
        'issues': [],
    }
    if not configured:
        report['issues'].append('Vosk model path is not configured')
    elif not report['directory_present']:
        report['issues'].append('Vosk model directory is missing')
    else:
        if not final_present:
            report['issues'].append('Vosk am/final.mdl is missing')
        elif report['final_mdl_bytes'] < MIN_MODEL_BYTES:
            report['issues'].append('Vosk am/final.mdl is implausibly small')
        elif not _kaldi_model_header_valid(final_model):
            report['issues'].append('Vosk am/final.mdl header is invalid')

        for relative, validator in (
                ('conf/mfcc.conf', _config_file_valid),
                ('conf/model.conf', _config_file_valid),
                ('graph/phones/word_boundary.int',
                 _word_boundary_table_valid)):
            critical = path / relative
            if not critical.is_file():
                report['issues'].append('Vosk {} is missing'.format(relative))
            elif not validator(critical):
                report['issues'].append('Vosk {} is invalid'.format(relative))

        if words_file and words_file.is_file() \
                and not _words_file_valid(words_file):
            report['issues'].append('Vosk graph/words.txt is invalid')

        if hclr and hclr.is_file() \
                and grammar_graph and grammar_graph.is_file():
            report['graph_layout'] = 'dynamic_grammar'
            for graph_path, label, minimum_bytes in (
                    (hclr, 'graph/HCLr.fst', MIN_HCLR_BYTES),
                    (grammar_graph, 'graph/Gr.fst', MIN_GR_BYTES)):
                if graph_path.stat().st_size < minimum_bytes:
                    report['issues'].append(
                        'Vosk {} is implausibly small'.format(label))
                elif not _openfst_header_valid(graph_path):
                    report['issues'].append(
                        'Vosk {} header is invalid'.format(label))
        else:
            report['issues'].append(
                'Vosk restricted grammar requires both graph/HCLr.fst '
                'and graph/Gr.fst')

        disambig = path / 'graph' / 'disambig_tid.int'
        if not disambig.is_file():
            report['issues'].append(
                'Vosk graph/disambig_tid.int is missing')
        elif not _integer_list_valid(disambig):
            report['issues'].append(
                'Vosk graph/disambig_tid.int is invalid')

        report['static_ready'] = not report['issues']
        if report['static_ready']:
            runtime_available, loadable, issue = _load_vosk_model(
                path,
                model_loader=model_loader,
                recognizer_loader=recognizer_loader,
                grammar_phrases=grammar_phrases,
            )
            report['runtime_available'] = runtime_available
            report['loadability_checked'] = runtime_available
            report['loadable'] = loadable
            if issue:
                report['issues'].append(issue)
    report['ready'] = report['static_ready'] and report['loadable']
    return report


def _is_sha256(value):
    return bool(SHA256_PATTERN.fullmatch(str(value or '')))


def _inside_directory(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _relative_path_parts(raw):
    """Return portable relative parts or a fail-closed rejection reason."""
    normalized = str(raw or '').strip().replace('\\', '/')
    if not normalized:
        return None, 'path is empty'
    if normalized.startswith('//') or re.match(r'^[A-Za-z]:', normalized):
        return None, 'path is absolute or drive-qualified'
    if normalized.startswith('/'):
        return None, 'path is absolute'
    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', normalized):
        return None, 'path is a URI'
    parts = []
    for part in normalized.split('/'):
        if not part or part == '.':
            continue
        if part == '..':
            parts.append(part)
            continue
        parts.append(part)
    if not parts:
        return (), None
    return tuple(parts), None


def _declared_parent_depth(raw):
    normalized = str(raw or '').strip().replace('\\', '/')
    depth = 0
    maximum = 0
    for part in normalized.split('/'):
        if not part or part == '.':
            continue
        if part == '..':
            depth -= 1
            maximum = max(maximum, -depth)
        else:
            depth += 1
    return maximum


def _resolve_manifest_path(value, manifest_directory):
    """Resolve Windows or POSIX manifest paths on either host OS."""
    raw = str(value or '').strip()
    parts, issue = _relative_path_parts(raw)
    if issue:
        return None, issue
    return (manifest_directory.joinpath(*parts)).resolve(), None


def load_corpus_manifest(manifest_path):
    """Load a strict corpus manifest and collect fail-closed issues."""
    path = Path(manifest_path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('manifest root must be an object')

    issues = []
    cases = data.get('cases')
    if data.get('schema_version') != 2:
        issues.append('schema_version must be 2')
    if data.get('mode') != 'windows_media_foundation_offline_no_ros':
        issues.append('mode must be windows_media_foundation_offline_no_ros')
    if data.get('label_policy') != LABEL_POLICY:
        issues.append('label_policy must declare labels are not transcripts')
    declared_coverage = data.get('required_coverage_classes')
    if declared_coverage != list(REQUIRED_COVERAGE_CLASSES):
        issues.append('required_coverage_classes is not the fixed V2 set')
    source_root_value = str(data.get('source_root', '')).strip()
    if not source_root_value:
        issues.append('source_root is required')
        source_root = path.parent
        source_root_allowed = False
    else:
        source_root, source_root_issue = _resolve_manifest_path(
            source_root_value, path.parent)
        source_root_allowed = source_root_issue is None
        if not source_root_allowed:
            issues.append(
                'source_root must be a relative project path: {}'.format(
                    source_root_issue))
            source_root = path.parent
        elif not source_root.is_dir():
            issues.append('source_root directory is missing')
            source_root_allowed = False
        elif _declared_parent_depth(source_root_value) > 1:
            issues.append(
                'source_root may traverse at most one parent directory')
            source_root_allowed = False
        elif source_root not in {path.parent, path.parent.parent}:
            issues.append(
                'source_root must be the manifest directory or its '
                'direct parent')
            source_root_allowed = False
    if not isinstance(cases, list) or not cases:
        issues.append('manifest must contain a non-empty cases list')
        cases = []

    normalized = []
    ids = {}
    labels = {}
    audio_paths = {}
    audio_hashes = {}
    duplicate_labels = []
    for index, case in enumerate(cases):
        case_issues = []
        if not isinstance(case, dict):
            issues.append('case {} must be an object'.format(index))
            continue
        allowed_case_fields = {
            'source_name', 'id', 'label', 'coverage_class',
            'label_is_transcript', 'source_path', 'source_sha256',
            'source_bytes', 'source_format', 'audio_path', 'wav_sha256',
            'wav_bytes', 'wav', 'transcription_status', 'transcript',
            'intent_status',
        }
        unknown_case_fields = sorted(set(case) - allowed_case_fields)
        if unknown_case_fields:
            case_issues.append(
                'unknown manifest fields: {}'.format(
                    ', '.join(unknown_case_fields)))
        case_id = str(case.get('id', '')).strip()
        label = str(case.get('label', '')).strip()
        coverage = str(case.get('coverage_class', '')).strip()
        audio_value = str(case.get('audio_path', '')).strip()
        audio_path, audio_path_issue = _resolve_manifest_path(
            audio_value, path.parent)
        if audio_path is None:
            audio_path = path.parent

        if not case_id:
            case_issues.append('id is required')
        elif case_id in ids:
            case_issues.append('duplicate id: {}'.format(case_id))
        else:
            ids[case_id] = index
        if not label:
            case_issues.append('label is required')
        elif label in labels:
            duplicate_labels.append(label)
            case_issues.append('duplicate label: {}'.format(label))
        else:
            labels[label] = index
        if case.get('label_is_transcript') is not False:
            case_issues.append('label_is_transcript must be false')
        if coverage not in ALLOWED_COVERAGE_CLASSES:
            case_issues.append('unknown coverage_class: {}'.format(coverage))
        audio_path_allowed = (
            bool(audio_value)
            and audio_path_issue is None
            and _inside_directory(audio_path, path.parent)
        )
        if not audio_value:
            case_issues.append('audio_path is required')
        elif audio_path_issue:
            case_issues.append(
                'audio_path must be relative to the manifest: {}'.format(
                    audio_path_issue))
        elif not _inside_directory(audio_path, path.parent):
            case_issues.append('audio_path escapes the manifest directory')
        audio_key = str(audio_path).casefold()
        if audio_key in audio_paths:
            case_issues.append('duplicate audio_path: {}'.format(audio_value))
        else:
            audio_paths[audio_key] = index
        expected_hash = str(case.get('wav_sha256', '')).strip()
        if not _is_sha256(expected_hash):
            case_issues.append('wav_sha256 must be 64 lowercase hex chars')
        elif expected_hash in audio_hashes:
            case_issues.append('duplicate wav_sha256: {}'.format(
                expected_hash))
        else:
            audio_hashes[expected_hash] = index
        if case.get('transcription_status') == 'decoded_not_transcribed':
            if case.get('transcript') is not None:
                case_issues.append(
                    'decoded_not_transcribed requires transcript=null')
            if case.get('intent_status') != 'not_evaluated_without_asr':
                case_issues.append(
                    'decoded audio must not claim an evaluated intent')
        elif case.get('transcription_status') != 'transcribed':
            case_issues.append('unknown transcription_status')
        if case.get('transcription_status') == 'transcribed':
            if not isinstance(case.get('transcript'), str):
                case_issues.append('transcribed case requires text transcript')
            if case.get('intent_status') != 'evaluated':
                case_issues.append(
                    'transcribed case requires intent_status=evaluated')
        if case.get('intent_status') not in {
                'not_evaluated_without_asr', 'evaluated'}:
            case_issues.append('unknown intent_status')
        if not isinstance(case.get('source_bytes'), int) \
                or case.get('source_bytes') <= 0:
            case_issues.append('source_bytes must be a positive integer')
        if not isinstance(case.get('wav_bytes'), int) \
                or case.get('wav_bytes') <= 0:
            case_issues.append('wav_bytes must be a positive integer')
        source_format = case.get('source_format')
        if not isinstance(source_format, dict):
            case_issues.append('source_format must be an object')

        normalized.append({
            'index': index,
            'case': case,
            'id': case_id or 'case-{}'.format(index + 1),
            'label': label,
            'coverage_class': coverage,
            'audio_path': audio_path,
            'audio_path_allowed': audio_path_allowed,
            'issues': case_issues,
        })
        issues.extend(
            '{}: {}'.format(case_id or index, item)
            for item in case_issues
        )

    declared_audio_paths = {
        item['audio_path'] for item in normalized
        if item['audio_path_allowed']
    }
    generated_wavs = sorted(
        (
            item.resolve() for item in path.parent.iterdir()
            if item.is_file()
            and GENERATED_WAV_NAME_PATTERN.fullmatch(item.name)
        ),
        key=lambda item: item.name.casefold(),
    )
    unlisted_generated_wavs = [
        item.name for item in generated_wavs
        if item not in declared_audio_paths
    ]
    issues.extend(
        'unlisted generated WAV: {}'.format(name)
        for name in unlisted_generated_wavs
    )

    return {
        'path': path,
        'sha256': sha256_file(path),
        'data': data,
        'cases': normalized,
        'valid': not issues,
        'issues': issues,
        'duplicate_label_groups': sorted(set(duplicate_labels)),
        'unlisted_generated_wavs': unlisted_generated_wavs,
        'source_root': source_root,
        'source_root_allowed': source_root_allowed,
    }


def _metadata_matches(case, audio):
    declared = case.get('wav')
    if not isinstance(declared, dict):
        return False, ['manifest WAV statistics are missing']
    issues = []
    exact_fields = (
        'sample_rate',
        'channels',
        'sample_width_bytes',
        'frame_count',
        'peak',
    )
    for field in exact_fields:
        if declared.get(field) != audio.get(field):
            issues.append('manifest {} does not match WAV'.format(field))
    tolerance_fields = {
        'duration_sec': 0.000001,
        'rms': 0.01,
        'rms_dbfs': 0.01,
        'peak_dbfs': 0.01,
        'clipped_fraction': 0.00000001,
        'voiced_frame_fraction': 0.0001,
        'leading_silence_sec_est': 0.001,
        'trailing_silence_sec_est': 0.001,
    }
    for field, tolerance in tolerance_fields.items():
        declared_value = declared.get(field)
        actual_value = audio.get(field)
        if declared_value is None or actual_value is None:
            if declared_value != actual_value:
                issues.append('manifest {} does not match WAV'.format(field))
            continue
        try:
            difference = abs(float(declared_value) - float(actual_value))
        except (TypeError, ValueError):
            issues.append('manifest {} is not numeric'.format(field))
            continue
        if difference > tolerance:
            issues.append('manifest {} does not match WAV'.format(field))
    return not issues, issues


def evaluate_corpus_readiness(manifest_path, model_path=None):
    """Return a JSON-safe delivery-readiness report without using ASR."""
    manifest = load_corpus_manifest(manifest_path)
    model = validate_vosk_model(model_path)
    case_reports = []
    blocking = list(manifest['issues'])
    coverage = {name: 0 for name in REQUIRED_COVERAGE_CLASSES}
    transcribed = 0
    evaluated = 0
    total_duration = 0.0
    for item in manifest['cases']:
        case = item['case']
        audio = (
            inspect_pcm16_wav(item['audio_path'])
            if item['audio_path_allowed']
            else _blocked_wav_report(item['audio_path'])
        )
        total_duration += float(audio.get('duration_sec') or 0.0)
        if item['coverage_class'] in coverage:
            coverage[item['coverage_class']] += 1
        expected_hash = str(case.get('wav_sha256', '')).strip()
        hash_match = (
            _is_sha256(expected_hash)
            and audio.get('sha256') == expected_hash
        )
        case_issues = list(item['issues'])
        source_hash_match = False
        source_value = str(case.get('source_path', '')).strip()
        source_path, source_path_issue = _resolve_manifest_path(
            source_value, manifest['source_root'])
        if source_path is None:
            source_path = manifest['source_root']
        source_path_allowed = (
            bool(source_value)
            and manifest['source_root_allowed']
            and source_path_issue is None
            and _inside_directory(source_path, manifest['source_root'])
        )
        if not source_path_allowed:
            case_issues.append(
                'source_path must stay within relative source_root')
        if (
                source_path_allowed
                and source_path.is_file()
                and _is_sha256(case.get('source_sha256'))):
            source_hash_match = (
                sha256_file(source_path) == case.get('source_sha256'))
        metadata_match, metadata_issues = _metadata_matches(case, audio)
        case_issues.extend(audio['format_issues'])
        case_issues.extend(audio['quality_issues'])
        case_issues.extend(metadata_issues)
        if not hash_match:
            case_issues.append('WAV SHA-256 does not match manifest')
        if not source_hash_match:
            case_issues.append('source SHA-256 does not match manifest')
        if source_path_allowed and source_path.is_file() \
                and case.get('source_bytes') != (
                source_path.stat().st_size):
            case_issues.append('source_bytes does not match source file')
        if audio.get('bytes') is not None and case.get('wav_bytes') != (
                audio['bytes']):
            case_issues.append('wav_bytes does not match WAV file')
        if case.get('transcription_status') == 'transcribed':
            if str(case.get('transcript', '')).strip():
                transcribed += 1
        if case.get('intent_status') == 'evaluated':
            evaluated += 1
        ready = not case_issues
        blocking.extend(
            '{}: {}'.format(item['id'], issue)
            for issue in case_issues
        )
        case_reports.append({
            'id': item['id'],
            'label': item['label'],
            'label_is_transcript': case.get('label_is_transcript'),
            'coverage_class': item['coverage_class'],
            'audio_path': str(item['audio_path']),
            'audio': audio,
            'wav_hash_match': hash_match,
            'source_hash_match': source_hash_match,
            'manifest_audio_metadata_match': metadata_match,
            'transcription_status': case.get('transcription_status'),
            'transcript': case.get('transcript'),
            'intent_status': case.get('intent_status'),
            'ready': ready,
            'issues': case_issues,
        })

    missing_coverage = [
        name for name, count in coverage.items() if count == 0
    ]
    for name in missing_coverage:
        blocking.append('missing coverage class: {}'.format(name))
    if not model['ready']:
        blocking.extend(model['issues'])
    case_count = len(case_reports)
    corpus_ready = (
        manifest['valid']
        and case_count > 0
        and all(case['ready'] for case in case_reports)
        and not missing_coverage
    )
    if case_count and transcribed == case_count:
        transcription_status = 'transcribed'
    elif transcribed:
        transcription_status = 'partially_transcribed'
    else:
        transcription_status = 'decoded_not_transcribed'
    delivery_ready = (
        corpus_ready
        and model['ready']
        and transcribed == case_count
        and evaluated == case_count
    )
    if delivery_ready:
        status = 'PASS'
    elif corpus_ready:
        status = 'INCOMPLETE'
    else:
        status = 'FAIL'
    return {
        'schema_version': 1,
        'status': status,
        'mode': 'offline_corpus_readiness_no_asr_no_ros',
        'manifest': str(manifest['path']),
        'manifest_sha256': manifest['sha256'],
        'label_policy': manifest['data'].get('label_policy'),
        'corpus': {
            'case_count': case_count,
            'total_duration_sec': round(total_duration, 6),
            'coverage': coverage,
            'missing_coverage': missing_coverage,
            'duplicate_label_groups': (
                manifest['duplicate_label_groups']),
            'unlisted_generated_wavs': (
                manifest['unlisted_generated_wavs']),
            'format_pass_count': sum(
                case['audio']['format_pass'] for case in case_reports),
            'quality_pass_count': sum(
                case['audio']['quality_pass'] for case in case_reports),
            'hash_pass_count': sum(
                case['wav_hash_match'] for case in case_reports),
            'source_hash_pass_count': sum(
                case['source_hash_match'] for case in case_reports),
            'metadata_pass_count': sum(
                case['manifest_audio_metadata_match']
                for case in case_reports),
            'transcribed_count': transcribed,
            'intent_evaluated_count': evaluated,
        },
        'model': model,
        'transcription_status': transcription_status,
        'corpus_ready': corpus_ready,
        'delivery_ready': delivery_ready,
        'blocking_issues': sorted(set(blocking)),
        'cases': case_reports,
    }


def main(args=None):
    """Audit a corpus and emit a deterministic JSON readiness report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--model-path')
    parser.add_argument('--json-output')
    parsed = parser.parse_args(args)
    try:
        report = evaluate_corpus_readiness(
            parsed.manifest, parsed.model_path)
    except (OSError, ValueError) as error:
        report = {
            'schema_version': 1,
            'status': 'ERROR',
            'mode': 'offline_corpus_readiness_no_asr_no_ros',
            'delivery_ready': False,
            'error': '{}: {}'.format(type(error).__name__, error),
        }
        exit_code = 2
    else:
        exit_code = 0 if report['delivery_ready'] else 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if parsed.json_output:
        Path(parsed.json_output).write_text(
            rendered + '\n', encoding='utf-8')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
