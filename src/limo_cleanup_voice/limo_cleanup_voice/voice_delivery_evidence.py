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

"""Aggregate hashed real-WAV, mock-safety, model, and ROS1 evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import unicodedata
import wave


SCHEMA_VERSION = 1
RUN_MODE = 'offline_final_voice_delivery_evidence_no_ros_no_hardware'
AB_MODE = 'offline_ab_user_asserted_ground_truth_evaluation_no_ros_no_hardware'
MOCK_MODE = 'deterministic_offline_mock_no_ros_no_hardware'
ROS1_BLOCKED = 'BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY'
BASELINE = 'unrestricted_no_grammar'
BOTTLE_ONLY = 'bottle_restricted_grammar'
ENDPOINT_MODE = 'offline_real_wav_vosk_endpoint_candidate_evaluation'
ENDPOINT_CANDIDATE = 'unrestricted_first_complete_endpoint'
FIELD_NEGATIVE_MANIFEST_MODE = 'future_human_negative_corpus_intake_no_ros'
FIELD_NEGATIVE_PROMPT_MODE = (
    'future_human_negative_recording_prompt_plan_no_ros')
FIELD_NEGATIVE_REVIEW_MODE = (
    'future_human_negative_prompt_mock_review_no_ros')
FIELD_NEGATIVE_READINESS_MODE = (
    'future_human_negative_corpus_fail_closed_evaluation_no_ros')
NOETIC_TARGET_BUILD_MODE = (
    'ros1_noetic_target_catkin_offline_mock_no_graph_no_hardware')
USER_VOICE_37_MODE = 'offline_user_voice_vosk_semantic_no_ros_no_devices'
PRIVATE_MOCK_GRAPH_MODE = (
    'ros1_noetic_private_loopback_mock_graph_no_hardware')
STOP_STREAMING_MODE = 'offline_real_wav_streaming_stop_candidate_no_ros'
STOP_STREAMING_VARIANT = 'stop_disambiguation_grammar'
EXPECTED_INPUTS = {
    'ab_ground_truth_evaluation',
    'decode_manifest',
    'ground_truth_overlay',
    'model_intake',
    'mock_safety_acceptance',
    'user_voice_37_evaluation',
    'ros1_runtime_contract',
    'ros1_noetic_target_build_evidence',
    'ros1_noetic_target_build_collector',
    'ros1_private_mock_graph_report',
    'ros1_private_mock_graph_runner',
    'command_parser_source',
    'semantic_agent_source',
    'voice_dialogue_source',
    'acceptance_fixture_source',
    'acceptance_manifest',
    'ros1_adapter_core',
    'ros1_adapter_wrapper',
    'ros1_audio_input',
    'voice_contract_source',
    'legacy_asr_source',
    'legacy_asr_config',
    'endpoint_candidate_run_1',
    'endpoint_candidate_run_2',
    'endpoint_candidate_runner',
    'stop_streaming_report',
    'stop_candidate_manifest',
    'stop_model_config',
    'stop_streaming_evaluator',
    'stop_endpoint_ingress_core',
    'final_evidence_runner',
    'ros1_catkin_package_xml',
    'ros1_catkin_cmake',
    'ros1_catkin_setup',
    'ros1_catkin_entrypoint',
    'ros1_catkin_launch',
    'ros1_catkin_contract_test',
    'field_negative_manifest',
    'field_negative_prompt_plan',
    'field_negative_prompt_review',
    'field_negative_readiness',
    'field_negative_observations',
    'field_negative_evaluator',
    'field_negative_schema',
}


class EvidenceError(ValueError):
    """Raised when a required evidence artifact fails closed."""


def _object_pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError('duplicate JSON key: {}'.format(key))
        result[key] = value
    return result


def _load_json(path):
    try:
        rendered = Path(path).read_text(encoding='utf-8')
        value = json.loads(
            rendered,
            object_pairs_hook=_object_pairs_no_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(
            'unreadable JSON {}: {}'.format(path, error)) from error
    if not isinstance(value, dict):
        raise EvidenceError('{} must contain a JSON object'.format(path))
    return value


def sha256_file(path):
    """Return the lowercase SHA-256 of one file."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _require_fields(value, expected, context):
    if not isinstance(value, dict):
        raise EvidenceError('{} must be an object'.format(context))
    actual = set(value)
    if actual != set(expected):
        raise EvidenceError(
            '{} fields differ: expected={} actual={}'.format(
                context, sorted(expected), sorted(actual)))
    return value


def _require_bool(value, context):
    if not isinstance(value, bool):
        raise EvidenceError('{} must be boolean'.format(context))
    return value


def _require_number(value, context):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError('{} must be numeric'.format(context))
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError('{} must be finite'.format(context))
    return result


def _is_sha256(value):
    text = str(value or '')
    return len(text) == 64 and all(
        character in '0123456789abcdef' for character in text)


def _normalize_transcript(text):
    if not isinstance(text, str):
        raise EvidenceError('transcript must be a string')
    normalized = unicodedata.normalize('NFKC', text).casefold()
    return ''.join(
        character for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith(('P', 'Z', 'C'))
    )


def _edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for row, reference_character in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_character in enumerate(
                hypothesis, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1]
                + (reference_character != hypothesis_character),
            ))
        previous = current
    return previous[-1]


def _resolve_inside(root, relative_path, context):
    path = Path(relative_path)
    if path.is_absolute():
        raise EvidenceError('{} path must be relative'.format(context))
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise EvidenceError(
            '{} path escapes workspace root'.format(context)) from error
    return resolved


def _load_manifest(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_json(manifest_path)
    _require_fields(
        manifest,
        {
            'schema_version',
            'mode',
            'workspace_root',
            'selected_candidate',
            'comparison_baseline',
            'inputs',
            'thresholds',
            'statements',
        },
        'final evidence manifest',
    )
    if manifest['schema_version'] != SCHEMA_VERSION:
        raise EvidenceError('final evidence manifest schema mismatch')
    if manifest['mode'] != RUN_MODE:
        raise EvidenceError('final evidence manifest mode mismatch')
    workspace_value = Path(manifest['workspace_root'])
    if workspace_value.is_absolute() or workspace_value.as_posix() not in {
            '.', '..'}:
        raise EvidenceError('workspace_root must be exactly . or ..')
    workspace_root = (manifest_path.parent / workspace_value).resolve()
    if not workspace_root.is_dir():
        raise EvidenceError('workspace_root is not an existing directory')
    inputs = _require_fields(
        manifest['inputs'], EXPECTED_INPUTS, 'manifest.inputs')
    resolved_inputs = {}
    for name, item in inputs.items():
        _require_fields(item, {'path', 'sha256'}, 'input {}'.format(name))
        if not _is_sha256(item['sha256']):
            raise EvidenceError('{} SHA-256 is invalid'.format(name))
        path = _resolve_inside(workspace_root, item['path'], name)
        if not path.is_file():
            raise EvidenceError('{} input is missing: {}'.format(name, path))
        actual_sha256 = sha256_file(path)
        if actual_sha256 != item['sha256']:
            raise EvidenceError(
                '{} SHA-256 mismatch: expected={} actual={}'.format(
                    name, item['sha256'], actual_sha256))
        resolved_inputs[name] = {
            'path': path,
            'sha256': actual_sha256,
            'bytes': path.stat().st_size,
        }
    return manifest_path, manifest, workspace_root, resolved_inputs


def _variant_summary(ab_report, name):
    try:
        summary = ab_report['summary'][name]
        accuracy = summary['accuracy_all_cases']
        safety = summary['semantic_safety']
    except (KeyError, TypeError) as error:
        raise EvidenceError(
            'A/B report is missing variant {}'.format(name)) from error
    values = {
        'case_count': int(_require_number(
            accuracy.get('case_count'), '{} case_count'.format(name))),
        'exact_match_count': int(_require_number(
            accuracy.get('exact_match_count'),
            '{} exact_match_count'.format(name))),
        'exact_match_rate': _require_number(
            accuracy.get('exact_match_rate'),
            '{} exact_match_rate'.format(name)),
        'micro_cer': _require_number(
            accuracy.get('micro_cer'), '{} micro_cer'.format(name)),
        'all_exact': _require_bool(
            accuracy.get('all_exact'), '{} all_exact'.format(name)),
        'safety_all_passed': _require_bool(
            safety.get('all_passed'),
            '{} safety.all_passed'.format(name)),
        'safety_case_pass_count': int(_require_number(
            safety.get('case_pass_count'),
            '{} safety.case_pass_count'.format(name))),
        'actual_publish_count': int(_require_number(
            safety.get('actual_publish_count'),
            '{} actual_publish_count'.format(name))),
    }
    if not 0.0 <= values['exact_match_rate'] <= 1.0:
        raise EvidenceError('{} exact_match_rate is invalid'.format(name))
    if values['micro_cer'] < 0.0:
        raise EvidenceError('{} micro_cer is invalid'.format(name))
    return values


def _case_by_id(ab_report, case_id):
    cases = ab_report.get('cases')
    if not isinstance(cases, list):
        raise EvidenceError('A/B cases must be a list')
    matches = [case for case in cases if case.get('id') == case_id]
    if len(matches) != 1:
        raise EvidenceError(
            'critical case must occur exactly once: {}'.format(case_id))
    return matches[0]


def _validate_variant_case_aggregation(report, name, summary):
    cases = report.get('cases')
    if not isinstance(cases, list) or not cases:
        raise EvidenceError('A/B cases must be a non-empty list')
    exact_count = 0
    edit_distance = 0
    reference_characters = 0
    safety_pass_count = 0
    publish_count = 0
    for case in cases:
        variant = (case.get('variants') or {}).get(name)
        if not isinstance(variant, dict):
            raise EvidenceError(
                'case {} is missing variant {}'.format(case.get('id'), name))
        accuracy = variant.get('accuracy') or {}
        character_error = accuracy.get('character_error') or {}
        exact = _require_bool(
            accuracy.get('exact_match'),
            '{} case exact_match'.format(name),
        )
        exact_count += int(exact)
        edit_distance += int(_require_number(
            character_error.get('edit_distance'),
            '{} case edit_distance'.format(name),
        ))
        reference_characters += int(_require_number(
            character_error.get('reference_characters'),
            '{} case reference_characters'.format(name),
        ))
        safety = variant.get('semantic_safety') or {}
        safety_pass_count += int(_require_bool(
            safety.get('pass'), '{} case safety.pass'.format(name)))
        observed = variant.get('observed_semantics') or {}
        publish_count += int(_require_bool(
            observed.get('published'),
            '{} case observed published'.format(name),
        ))
    micro_cer = (
        round(edit_distance / reference_characters, 6)
        if reference_characters else None
    )
    if summary['case_count'] != len(cases):
        raise EvidenceError('{} summary case_count drift'.format(name))
    if summary['exact_match_count'] != exact_count:
        raise EvidenceError('{} summary exact count drift'.format(name))
    if summary['exact_match_rate'] != round(exact_count / len(cases), 6):
        raise EvidenceError('{} summary exact rate drift'.format(name))
    if summary['micro_cer'] != micro_cer:
        raise EvidenceError('{} summary micro CER drift'.format(name))
    if summary['safety_case_pass_count'] != safety_pass_count:
        raise EvidenceError('{} summary safety count drift'.format(name))
    if summary['actual_publish_count'] != publish_count:
        raise EvidenceError('{} summary publish count drift'.format(name))


def _validate_ab_evidence(
        report, overlay_sha256, manifest_sha256, selected, thresholds,
        statements):
    if report.get('schema_version') != 1:
        raise EvidenceError('A/B report schema mismatch')
    if report.get('status') != 'COMPLETE' or report.get('mode') != AB_MODE:
        raise EvidenceError('A/B report status or mode is invalid')
    safety_context = report.get('safety_context') or {}
    expected_safety = {
        'network_used': False,
        'live_ros_used': False,
        'microphone_used': False,
        'hardware_used': False,
        'ordinary_intents_mock_only': True,
        'intent_published': False,
        'filenames_used_as_transcripts': False,
        'ros_graph_used': False,
    }
    if safety_context != expected_safety:
        raise EvidenceError('A/B report safety context is invalid')
    provenance = report.get('ground_truth_provenance') or {}
    if provenance.get('policy') != (
            'user_explicit_declaration_not_filename_inference'):
        raise EvidenceError('A/B ground-truth provenance policy is invalid')
    for key in (
            'filename_inference_used',
            'manifest_labels_used_as_transcripts',
            'observed_transcripts_replaced'):
        if provenance.get(key) is not False:
            raise EvidenceError('A/B provenance flag {} is unsafe'.format(key))
    if provenance.get('original_manifest_transcripts_remain_null') is not True:
        raise EvidenceError('manifest transcript null provenance is missing')
    inputs = report.get('inputs') or {}
    if (inputs.get('ground_truth_overlay') or {}).get('sha256') != (
            overlay_sha256):
        raise EvidenceError('A/B overlay hash is not bound to final input')
    if (inputs.get('decode_manifest') or {}).get('sha256') != manifest_sha256:
        raise EvidenceError('A/B decode manifest hash is not bound')

    baseline = _variant_summary(report, BASELINE)
    candidate = _variant_summary(report, selected)
    _validate_variant_case_aggregation(report, BASELINE, baseline)
    if selected != BASELINE:
        _validate_variant_case_aggregation(report, selected, candidate)
    thresholds = _require_fields(
        thresholds,
        {
            'min_exact_match_rate',
            'max_micro_cer',
            'critical_case_id',
            'critical_ground_truth',
            'require_candidate_not_worse_than_baseline',
            'require_all_semantic_safety_cases',
        },
        'manifest.thresholds',
    )
    min_exact = _require_number(
        thresholds['min_exact_match_rate'], 'min_exact_match_rate')
    max_cer = _require_number(
        thresholds['max_micro_cer'], 'max_micro_cer')
    if not 0.0 <= min_exact <= 1.0 or max_cer < 0.0:
        raise EvidenceError('accuracy thresholds are invalid')
    _require_bool(
        thresholds['require_candidate_not_worse_than_baseline'],
        'require_candidate_not_worse_than_baseline',
    )
    _require_bool(
        thresholds['require_all_semantic_safety_cases'],
        'require_all_semantic_safety_cases',
    )

    not_regressed = (
        candidate['exact_match_count'] >= baseline['exact_match_count']
        and candidate['micro_cer'] <= baseline['micro_cer']
    )
    accuracy_threshold = (
        candidate['exact_match_rate'] >= min_exact
        and candidate['micro_cer'] <= max_cer
    )
    semantic_safety = (
        candidate['safety_all_passed']
        and candidate['safety_case_pass_count'] == candidate['case_count']
        and candidate['actual_publish_count'] == 0
    )
    critical_case = _case_by_id(report, thresholds['critical_case_id'])
    ground_truth = (critical_case.get('ground_truth') or {}).get('transcript')
    variants = critical_case.get('variants') or {}
    critical_variant = variants.get(selected) or {}
    accuracy = critical_variant.get('accuracy') or {}
    critical_phrase = (
        ground_truth == thresholds['critical_ground_truth']
        and accuracy.get('exact_match') is True
    )
    all_ground_truth = [
        (case.get('ground_truth') or {}).get('transcript')
        for case in report.get('cases', [])
    ]
    statements = _require_fields(
        statements,
        {
            'existing_bottle_recording_ground_truth',
            'spoken_bottle_only_ground_truth_available',
            'mock_pass_is_overall_pass',
        },
        'manifest.statements',
    )
    bottle_truth_statement = (
        statements['existing_bottle_recording_ground_truth'] == ground_truth
        and ground_truth == '捡矿泉水瓶'
    )
    bottle_only_available = _require_bool(
        statements['spoken_bottle_only_ground_truth_available'],
        'spoken_bottle_only_ground_truth_available',
    )
    no_fake_bottle_sample = (
        bottle_only_available is False and '捡瓶子' not in all_ground_truth)
    if statements['mock_pass_is_overall_pass'] is not False:
        raise EvidenceError('mock PASS cannot be declared overall PASS')
    comparison = (report.get('summary') or {}).get('comparison') or {}
    bottle_is_regressed = (
        comparison.get('accuracy_status_bottle_vs_unrestricted')
        == 'REGRESSED'
    )
    selected_allowed = not (
        selected == BOTTLE_ONLY and bottle_is_regressed)
    return {
        'baseline': baseline,
        'candidate': candidate,
        'candidate_not_regressed': not_regressed,
        'candidate_accuracy_threshold': accuracy_threshold,
        'candidate_semantic_safety': semantic_safety,
        'critical_phrase_exact': critical_phrase,
        'bottle_truth_statement': bottle_truth_statement,
        'no_fake_spoken_bottle_sample': no_fake_bottle_sample,
        'bottle_only_regressed': bottle_is_regressed,
        'selected_candidate_allowed': selected_allowed,
        'min_exact_match_rate': min_exact,
        'max_micro_cer': max_cer,
    }


def _validate_semantic_sequence(sequence, ab_sha256, overlay_sha256):
    if not isinstance(sequence, dict):
        raise EvidenceError('mock safety semantic_sequence is missing')
    provenance = sequence.get('provenance') or {}
    if provenance.get('filename_inference_used') is not False:
        raise EvidenceError(
            'semantic sequence used filename inference as transcript')
    if provenance.get('asr_evidence_sha256') != ab_sha256:
        raise EvidenceError(
            'semantic sequence ASR evidence hash is not bound')
    if provenance.get('ground_truth_sha256') != overlay_sha256:
        raise EvidenceError(
            'semantic sequence ground-truth hash is not bound')

    step_count = sequence.get('step_count')
    passed_count = sequence.get('passed_count')
    failed_count = sequence.get('failed_count')
    steps = sequence.get('steps')
    if (
            not isinstance(step_count, int)
            or isinstance(step_count, bool)
            or step_count <= 0
            or not isinstance(passed_count, int)
            or isinstance(passed_count, bool)
            or not isinstance(failed_count, int)
            or isinstance(failed_count, bool)
            or not isinstance(steps, list)
            or len(steps) != step_count):
        raise EvidenceError('semantic sequence counts are invalid')
    identifiers = [step.get('id') for step in steps]
    if (
            any(not isinstance(identifier, str) or not identifier
                for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        raise EvidenceError('semantic sequence step IDs are invalid')
    if any(
            step.get('passed') is not True
            or step.get('actual_publish_count') != 0
            for step in steps):
        raise EvidenceError('semantic sequence contains a failed step')

    passed = all((
        failed_count == 0,
        passed_count == step_count,
        sequence.get('actual_publish_count') == 0,
        sequence.get('ordinary_intents_mock_only') is True,
        isinstance(sequence.get('priority_stop_count'), int),
        sequence.get('priority_stop_count') >= 1,
        isinstance(sequence.get('mock_confirmed_high_level_count'), int),
        sequence.get('mock_confirmed_high_level_count') >= 1,
    ))
    return {
        'passed': passed,
        'step_count': step_count,
        'failed_count': failed_count,
        'actual_publish_count': sequence.get('actual_publish_count'),
        'ordinary_intents_mock_only': sequence.get(
            'ordinary_intents_mock_only'),
        'priority_stop_count': sequence.get('priority_stop_count'),
        'mock_confirmed_high_level_count': sequence.get(
            'mock_confirmed_high_level_count'),
        'filename_inference_used': provenance.get(
            'filename_inference_used'),
        'asr_evidence_sha256': provenance.get('asr_evidence_sha256'),
        'ground_truth_sha256': provenance.get('ground_truth_sha256'),
    }


def _validate_mock_safety(
        report, ab_sha256, overlay_sha256, expected_source_hashes):
    if report.get('schema_version') != 1:
        raise EvidenceError('mock safety schema mismatch')
    if report.get('mode') != MOCK_MODE or report.get('status') != 'PASS':
        raise EvidenceError('mock safety report mode or status is invalid')
    if report.get('live_ros_used') is not False:
        raise EvidenceError('mock safety report used live ROS')
    if report.get('hardware_used') is not False:
        raise EvidenceError('mock safety report used hardware')
    if report.get('high_level_intent_only') is not True:
        raise EvidenceError('mock safety report is not intent-only')
    source = report.get('source') or {}
    if set(source) != set(expected_source_hashes):
        raise EvidenceError('mock safety source identities are incomplete')
    for name, expected_sha256 in expected_source_hashes.items():
        identity = source.get(name) or {}
        if identity.get('sha256') != expected_sha256:
            raise EvidenceError(
                'mock safety source hash is not bound: {}'.format(name))
        if not isinstance(identity.get('bytes'), int) \
                or identity.get('bytes') <= 0:
            raise EvidenceError(
                'mock safety source size is invalid: {}'.format(name))
    transcripts = report.get('transcripts') or {}
    stop = report.get('stop') or {}
    timeout = report.get('confirmation_timeout') or {}
    attempts = stop.get('broadcast_attempts') or []
    semantic_sequence = _validate_semantic_sequence(
        report.get('semantic_sequence'), ab_sha256, overlay_sha256)
    passed = all((
        transcripts.get('failed_count') == 0,
        transcripts.get('false_activation_count') == 0,
        transcripts.get('passed_count') == transcripts.get('case_count'),
        stop.get('passed') is True,
        len(attempts) == 3,
        [attempt.get('attempt') for attempt in attempts] == [1, 2, 3],
        timeout.get('passed') is True,
        timeout.get('forwarded_after_timeout') is False,
        semantic_sequence['passed'],
    ))
    return {
        'passed': passed,
        'mode': report['mode'],
        'mock_only': True,
        'false_activation_count': transcripts.get('false_activation_count'),
        'transcript_case_count': transcripts.get('case_count'),
        'stop_attempt_count': len(attempts),
        'stop_first_publish_latency_ms': (
            report.get('metrics') or {}).get(
                'stop_first_publish_latency_ms'),
        'semantic_sequence': semantic_sequence,
        'source_sha256': dict(expected_source_hashes),
        'is_live_stop_end_to_end_evidence': False,
    }


def _validate_field_negative_evidence(
        manifest, prompt_plan, prompt_review, readiness, observations,
        manifest_sha256, prompt_plan_sha256, evaluator_sha256,
        schema_sha256, observations_sha256, manifest_path):
    """Bind partial human negatives without promoting incomplete evidence."""
    manifest_safety = {
        'live_ros_used': False,
        'robot_or_actuator_used': False,
        'ordinary_intents_mock_only': True,
        'actual_publish_count': 0,
        'production_publish_count': 0,
    }
    prompt_safety = {
        'live_ros_used': False,
        'microphone_used': False,
        'speaker_used': False,
        'ordinary_intents_mock_only': True,
        'actual_publish_count': 0,
        'production_publish_count': 0,
    }
    readiness_safety = {
        'actual_publish_count': 0,
        'live_ros_used': False,
        'microphone_used': False,
        'ordinary_intents_mock_only': True,
        'production_publish_count': 0,
        'robot_or_actuator_used': False,
        'speaker_used': False,
    }
    manifest_cases = manifest.get('cases') or []
    prompt_cases = prompt_plan.get('prompts') or []
    review_cases = prompt_review.get('cases') or []
    manifest_ids = {
        case.get('id') for case in manifest_cases if isinstance(case, dict)}
    prompt_ids = {
        case.get('id') for case in prompt_cases if isinstance(case, dict)}
    review_ids = {
        case.get('id') for case in review_cases if isinstance(case, dict)}
    captured_cases = [
        case for case in manifest_cases
        if isinstance(case, dict)
        and case.get('recording_status') == 'human_verified']
    missing_cases = [
        case for case in manifest_cases
        if isinstance(case, dict)
        and case.get('recording_status') == 'not_recorded']
    category_counts = {}
    prompts = set()
    prompt_rows_valid = True
    direct_adapter_review_valid = True
    from .ros1_noetic_adapter import Ros1NoeticAdapterCore
    for row in prompt_cases:
        if not isinstance(row, dict):
            prompt_rows_valid = False
            continue
        category = row.get('category')
        category_counts[category] = category_counts.get(category, 0) + 1
        prompt = row.get('recording_prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            prompt_rows_valid = False
        elif prompt in prompts:
            prompt_rows_valid = False
        else:
            prompts.add(prompt)
        if row.get('prompt_is_ground_truth') is not False:
            prompt_rows_valid = False
        if isinstance(prompt, str) and prompt.strip():
            core = Ros1NoeticAdapterCore(
                process_instance_id='voice-final-negative-review',
                monotonic_ns=lambda: 1_000_000_000,
                wall_time_ns=lambda: 2_000_000_000,
            )
            decision = core.process_transcript(
                prompt, now_ns=1_000_000_000)
            if not all((
                    decision.state == 'idle',
                    core.has_pending is False,
                    decision.stop_event is None,
                    decision.mock_output_plan is None,
                    decision.actual_publish_count == 0,
                    decision.production_publish_count == 0)):
                direct_adapter_review_valid = False
    audio_files_valid = True
    manifest_root = Path(manifest_path).resolve().parent
    for case in captured_cases:
        relative = case.get('audio_path')
        expected_relative = 'audio/{}.wav'.format(case.get('id'))
        if relative != expected_relative:
            audio_files_valid = False
            continue
        path = manifest_root / Path(*relative.split('/'))
        try:
            path.resolve().relative_to(manifest_root)
            if path.is_symlink() or not path.is_file():
                audio_files_valid = False
                continue
            with wave.open(str(path), 'rb') as stream:
                format_valid = all((
                    stream.getframerate() == 16000,
                    stream.getnchannels() == 1,
                    stream.getsampwidth() == 2,
                    stream.getcomptype() == 'NONE',
                    stream.getnframes() > 0,
                ))
                duration = round(
                    stream.getnframes() / stream.getframerate(), 6)
            if not all((
                    format_valid,
                    sha256_file(path) == case.get('audio_sha256'),
                    path.stat().st_size == case.get('audio_bytes'),
                    duration == case.get('duration_sec'),
                    isinstance(case.get('human_verified_transcript'), str),
                    bool(case.get('human_verified_transcript').strip()),
                    case.get('ground_truth_source')
                    == 'human_verified_spoken_content')):
                audio_files_valid = False
        except (OSError, ValueError, wave.Error):
            audio_files_valid = False
    manifest_is_partial = manifest.get('status') == 'PARTIAL'
    manifest_is_captured = manifest.get('status') == 'CAPTURED'
    manifest_plan_valid = all((
        manifest.get('schema_version') == 1,
        manifest.get('mode') == FIELD_NEGATIVE_MANIFEST_MODE,
        manifest_is_partial or manifest_is_captured,
        manifest.get('case_count') == 80,
        len(manifest_cases) == 80,
        len(manifest_ids) == 80,
        manifest.get('safety') == manifest_safety,
        ((manifest_is_partial and len(captured_cases) == 27
          and len(missing_cases) == 53)
         or (manifest_is_captured and len(captured_cases) == 80
             and len(missing_cases) == 0)),
        audio_files_valid,
        all(
            isinstance(case, dict)
            and case.get('recording_status') == 'not_recorded'
            and case.get('human_verified_transcript') is None
            and case.get('audio_path') is None
            for case in missing_cases),
    ))
    prompt_plan_valid = all((
        prompt_plan.get('schema_version') == 1,
        prompt_plan.get('mode') == FIELD_NEGATIVE_PROMPT_MODE,
        prompt_plan.get('manifest_sha256') == manifest_sha256,
        prompt_plan.get('case_count') == 80,
        len(prompt_cases) == 80,
        prompt_rows_valid,
        direct_adapter_review_valid,
        prompt_ids == manifest_ids,
        category_counts == {
            'near_soundalike': 20,
            'negated': 20,
            'reported_or_quoted': 20,
            'environment_dialogue': 20,
        },
        prompt_plan.get('safety') == prompt_safety,
    ))
    review_inputs = prompt_review.get('inputs') or {}
    review_counts = prompt_review.get('counts') or {}
    prompt_review_valid = all((
        prompt_review.get('schema_version') == 1,
        prompt_review.get('mode') == FIELD_NEGATIVE_REVIEW_MODE,
        prompt_review.get('status') == 'PASS',
        prompt_review.get('delivery_ready') is False,
        prompt_review.get('prompt_plan_gate_passed') is True,
        prompt_review.get('safety') == prompt_safety,
        (review_inputs.get('manifest') or {}).get('sha256')
        == manifest_sha256,
        (review_inputs.get('prompt_plan') or {}).get('sha256')
        == prompt_plan_sha256,
        review_inputs.get('evaluator_sha256') == evaluator_sha256,
        review_counts == {
            'manifest_cases': 80,
            'prompt_cases': 80,
            'passed': 80,
            'failed': 0,
            'actual_publish_count': 0,
            'production_publish_count': 0,
        },
        len(review_cases) == 80,
        review_ids == manifest_ids,
        all(
            isinstance(case, dict)
            and case.get('passed') is True
            and case.get('state') == 'idle'
            and case.get('has_pending') is False
            and case.get('stop_event_created') is False
            and case.get('mock_output_plan_created') is False
            and case.get('actual_publish_count') == 0
            and case.get('production_publish_count') == 0
            for case in review_cases),
        prompt_review.get('blocking_issues') == [],
    ))
    readiness_inputs = readiness.get('inputs') or {}
    readiness_counts = readiness.get('counts') or {}
    readiness_blockers = set(readiness.get('blocking_issues') or [])
    expected_readiness_counts = {
        'manifest_cases': 80,
        'audio_files_inspected': 80 if manifest_is_captured else 27,
        'observations': 80 if manifest_is_captured else 27,
    }
    readiness_valid = all((
        readiness.get('schema_version') == 1,
        readiness.get('mode') == FIELD_NEGATIVE_READINESS_MODE,
        readiness.get('status') == (
            'PASS' if manifest_is_captured else 'BLOCKED'),
        readiness.get('delivery_ready') is False,
        readiness.get('offline_corpus_gate_passed') is manifest_is_captured,
        readiness.get('safety') == readiness_safety,
        (readiness_inputs.get('manifest') or {}).get('sha256')
        == manifest_sha256,
        (readiness_inputs.get('schema') or {}).get('sha256')
        == schema_sha256,
        readiness_inputs.get('evaluator_sha256') == evaluator_sha256,
        (readiness_inputs.get('observations') or {}).get('sha256')
        == observations_sha256,
        readiness_counts == expected_readiness_counts,
        readiness_blockers == (
            set() if manifest_is_captured
            else {'human_recordings_incomplete'}),
    ))
    observation_cases = observations.get('cases') or []
    observation_ids = {
        case.get('id') for case in observation_cases
        if isinstance(case, dict)}
    captured_by_id = {case['id']: case for case in captured_cases}
    observation_provenance = observations.get('provenance') or {}
    observations_valid = all((
        observations.get('schema_version') == 1,
        observations.get('mode')
        == 'offline_human_negative_asr_observations_no_ros',
        observations.get('manifest_sha256') == manifest_sha256,
        len(observation_cases) == len(captured_cases),
        observation_ids == set(captured_by_id),
        observations.get('safety') == {
            'live_ros_used': False,
            'ordinary_intents_mock_only': True,
            'actual_publish_count': 0,
            'production_publish_count': 0,
        },
        _is_sha256(observation_provenance.get('model_directory_sha256')),
        _is_sha256(observation_provenance.get('runner_sha256')),
        observation_provenance.get('endpoint_policy')
        == 'first_nonempty_complete_endpoint_then_stop',
        observation_provenance.get('audio_unmodified') is True,
        all(
            case.get('audio_sha256')
            == captured_by_id.get(case.get('id'), {}).get('audio_sha256')
            and case.get('transcript_source')
            == 'vosk_offline_audio_unmodified'
            and case.get('wake_word_detected') is False
            and case.get('priority_stop_detected') is False
            and case.get('semantic_false_trigger') is False
            and case.get('ordinary_pending') is False
            and case.get('adapter_state') == 'idle'
            and case.get('actual_publish_count') == 0
            and case.get('production_publish_count') == 0
            for case in observation_cases),
    ))
    plan_passed = all((
        manifest_plan_valid,
        prompt_plan_valid,
        prompt_review_valid,
        readiness_valid,
        observations_valid,
    ))
    human_corpus_ready = all((
        manifest_is_captured,
        manifest_plan_valid,
        readiness_valid,
        observations_valid,
    ))
    return {
        'plan_passed': plan_passed,
        'human_corpus_ready': human_corpus_ready,
        'delivery_promoted': False,
        'case_count': 80,
        'prompt_mock_pass_count': review_counts.get('passed'),
        'prompt_mock_fail_count': review_counts.get('failed'),
        'actual_publish_count': review_counts.get('actual_publish_count'),
        'production_publish_count': review_counts.get(
            'production_publish_count'),
        'human_audio_files_inspected': readiness_counts.get(
            'audio_files_inspected'),
        'asr_observation_count': readiness_counts.get('observations'),
        'blocking_issues': sorted(readiness_blockers),
        'prompt_is_ground_truth': False,
        'direct_adapter_review_passed': direct_adapter_review_valid,
        'is_live_or_field_evidence': False,
    }


def _validate_model_intake(report):
    probe = report.get('grammar_probe') or {}
    model = report.get('model') or {}
    validation = model.get('validation') or {}
    return {
        'passed': all((
            report.get('status') == 'PASS',
            report.get('delivery_ready') is True,
            validation.get('ready') is True,
            probe.get('attempted') is True,
            probe.get('passed') is True,
        )),
        'model_directory_sha256': (
            (model.get('inventory') or {}).get('directory_sha256')),
        'grammar_probe_only_not_accuracy': True,
    }


def _validate_endpoint_candidate_run(
        report, runner_sha256, manifest_sha256, ground_truth_sha256):
    if report.get('schema_version') != 1:
        raise EvidenceError('endpoint candidate schema mismatch')
    if report.get('mode') != ENDPOINT_MODE \
            or report.get('status') != 'COMPLETE':
        raise EvidenceError('endpoint candidate mode or status is invalid')
    provenance = report.get('provenance') or {}
    if (provenance.get('runner') or {}).get('sha256') != runner_sha256:
        raise EvidenceError('endpoint candidate runner hash is not bound')
    if (provenance.get('manifest') or {}).get('sha256') != manifest_sha256:
        raise EvidenceError('endpoint candidate manifest hash is not bound')
    ground_truth = provenance.get('ground_truth') or {}
    if ground_truth.get('sha256') != ground_truth_sha256:
        raise EvidenceError(
            'endpoint candidate ground-truth hash is not bound')
    if ground_truth.get('filename_inference_used') is not False \
            or ground_truth.get('used_only_after_asr') is not True:
        raise EvidenceError('endpoint candidate ground truth is unsafe')
    safety = report.get('safety') or {}
    expected_safety = {
        'actual_publish_count': 0,
        'filenames_used_as_transcripts': False,
        'hardware_used': False,
        'live_ros_used': False,
        'manifest_labels_used_as_transcripts': False,
        'microphone_used': False,
        'network_used': False,
        'ordinary_intents_mock_only': True,
        'software_stop_is_live_robot_evidence': False,
        'speaker_used': False,
    }
    if safety != expected_safety:
        raise EvidenceError('endpoint candidate safety context is invalid')
    cases = report.get('cases')
    if not isinstance(cases, list) or len(cases) != 4:
        raise EvidenceError('endpoint candidate must contain four cases')
    case_ids = [case.get('id') for case in cases]
    if len(set(case_ids)) != len(case_ids) \
            or not all(isinstance(case_id, str) for case_id in case_ids):
        raise EvidenceError('endpoint candidate case ids are invalid')
    exact_count = 0
    edit_distance = 0
    reference_characters = 0
    semantic_pass_count = 0
    transcripts = {}
    for case in cases:
        if not _is_sha256(case.get('audio_sha256')):
            raise EvidenceError('endpoint candidate audio hash is invalid')
        variant = (case.get('variants') or {}).get(ENDPOINT_CANDIDATE)
        if not isinstance(variant, dict):
            raise EvidenceError('endpoint candidate case variant is missing')
        accuracy = variant.get('accuracy') or {}
        normalized_ground_truth = _normalize_transcript(
            accuracy.get('ground_truth'))
        normalized_observed = _normalize_transcript(
            variant.get('transcript'))
        if not normalized_ground_truth:
            raise EvidenceError(
                'endpoint candidate ground truth must not be empty')
        distance = _edit_distance(
            normalized_ground_truth, normalized_observed)
        exact = normalized_ground_truth == normalized_observed
        if accuracy.get('normalized_ground_truth') != normalized_ground_truth \
                or accuracy.get('normalized_observed') != normalized_observed:
            raise EvidenceError(
                'endpoint candidate normalized transcript drift')
        if accuracy.get('exact') is not exact \
                or accuracy.get('edit_distance') != distance \
                or accuracy.get('reference_characters') != len(
                    normalized_ground_truth):
            raise EvidenceError('endpoint candidate case accuracy drift')
        expected_cer = round(distance / len(normalized_ground_truth), 6)
        if accuracy.get('cer') != expected_cer:
            raise EvidenceError('endpoint candidate case CER drift')
        semantics = variant.get('semantics') or {}
        semantic_pass = variant.get('semantic_safety_pass') is True
        if semantics.get('actual_publish_count') != 0 \
                or semantics.get('ordinary_intent_mock_only') is not True \
                or not semantic_pass:
            raise EvidenceError(
                'endpoint candidate semantic safety is invalid')
        if variant.get('transcript_source') != (
                'vosk_offline_audio_unmodified'):
            raise EvidenceError(
                'endpoint candidate transcript provenance is invalid')
        exact_count += int(exact)
        edit_distance += distance
        reference_characters += len(normalized_ground_truth)
        semantic_pass_count += int(semantic_pass)
        transcripts[case['id']] = normalized_observed
    summary = (report.get('summaries') or {}).get(ENDPOINT_CANDIDATE) or {}
    expected_summary = {
        'actual_publish_count': 0,
        'case_count': 4,
        'edit_distance': edit_distance,
        'exact_match_count': exact_count,
        'exact_match_rate': round(exact_count / len(cases), 6),
        'micro_cer': round(edit_distance / reference_characters, 6),
        'offline_accuracy_gate_passed': (
            exact_count == 4 and edit_distance == 0),
        'reference_character_count': reference_characters,
        'semantic_safety_all_passed': semantic_pass_count == 4,
        'semantic_safety_pass_count': semantic_pass_count,
    }
    if summary != expected_summary:
        raise EvidenceError('endpoint candidate summary drift')
    baseline = (
        report.get('summaries') or {}
    ).get('baseline_unrestricted_all_endpoints') or {}
    comparison = report.get('comparison') or {}
    if baseline.get('exact_match_count') != 2 \
            or baseline.get('micro_cer') != 0.357143 \
            or comparison.get('rerun_baseline_matches_frozen') is not True:
        raise EvidenceError('endpoint frozen baseline was not preserved')
    if comparison.get('field_delivery_ready') is not False \
            or comparison.get('offline_accuracy_gate_passed') is not True:
        raise EvidenceError('endpoint candidate field boundary is invalid')
    return {
        'summary': expected_summary,
        'transcripts': transcripts,
        'field_delivery_ready': False,
    }


def _validate_endpoint_candidate(
        first_report, second_report, runner_sha256,
        manifest_sha256, ground_truth_sha256):
    first = _validate_endpoint_candidate_run(
        first_report, runner_sha256, manifest_sha256, ground_truth_sha256)
    second = _validate_endpoint_candidate_run(
        second_report, runner_sha256, manifest_sha256, ground_truth_sha256)
    reproducible = first['transcripts'] == second['transcripts'] \
        and first['summary'] == second['summary']
    if not reproducible:
        raise EvidenceError('endpoint candidate runs are not reproducible')
    return {
        'passed': True,
        'candidate': ENDPOINT_CANDIDATE,
        'independent_run_count': 2,
        'exact_match_count': first['summary']['exact_match_count'],
        'case_count': first['summary']['case_count'],
        'micro_cer': first['summary']['micro_cer'],
        'semantic_safety_pass_count': first['summary'][
            'semantic_safety_pass_count'],
        'actual_publish_count': 0,
        'field_delivery_promoted': False,
        'frozen_all_endpoints_baseline_preserved': True,
    }


def _nearest_rank(values, percentile):
    """Return one deterministic nearest-rank percentile."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, int(math.ceil(percentile * len(ordered))))
    return ordered[rank - 1]


def _validate_stop_endpoint_evidence(
        report, candidate, report_sha256, candidate_sha256,
        model_config_sha256, evaluator_sha256, model_config_path):
    """Recompute the isolated human STOP endpoint evidence fail-closed."""
    if report.get('schema_version') != 2 \
            or report.get('status') != 'BLOCKED' \
            or report.get('mode') != STOP_STREAMING_MODE \
            or report.get('delivery_ready') is not False:
        raise EvidenceError('STOP streaming report boundary mismatch')
    safety = report.get('safety') or {}
    expected_safety = {
        'microphone_opened': False,
        'speaker_used': False,
        'live_ros_used': False,
        'hardware_control_used': False,
        'actual_publish_count': 0,
        'production_publish_count': 0,
        'software_timing_is_robot_end_to_end_evidence': False,
    }
    if safety != expected_safety:
        raise EvidenceError('STOP streaming safety boundary mismatch')
    provenance = report.get('provenance') or {}
    if (provenance.get('runner') or {}).get('sha256') != evaluator_sha256 \
            or (provenance.get('model_config') or {}).get(
                'sha256') != model_config_sha256:
        raise EvidenceError('STOP streaming provenance hash mismatch')
    configuration = report.get('configuration') or {}
    variants = configuration.get('variants') or []
    variant_names = [item.get('name') for item in variants
                     if isinstance(item, dict)]
    if configuration.get('chunk_frames') != 1600 \
            or configuration.get('chunk_duration_ms') != 100 \
            or configuration.get('quiet_guards_ms') != [200, 300, 400] \
            or variant_names != ['unrestricted', STOP_STREAMING_VARIANT] \
            or variants[0].get('grammar') is not None \
            or not isinstance(variants[1].get('grammar'), list) \
            or '停下' not in variants[1]['grammar'] \
            or '[unk]' not in variants[1]['grammar']:
        raise EvidenceError('STOP streaming configuration mismatch')

    cases = report.get('cases')
    if not isinstance(cases, list) or len(cases) != 84:
        raise EvidenceError('STOP streaming corpus must be 4+80 cases')
    case_ids = [item.get('id') for item in cases
                if isinstance(item, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(cases):
        raise EvidenceError('STOP streaming case identities are invalid')
    positives = [item for item in cases if item.get('expected_stop') is True]
    negatives = [item for item in cases if item.get('expected_stop') is False]
    negative_coverage_counts = {
        coverage: sum(item.get('coverage') == coverage for item in negatives)
        for coverage in (
            'near_soundalike', 'negated', 'reported_or_quoted',
            'environment_dialogue')
    }
    if len(positives) != 4 or len(negatives) != 80 \
            or any(item.get('coverage') != 'real_human_positive_stop'
                   for item in positives) \
            or negative_coverage_counts != {
                'near_soundalike': 20,
                'negated': 20,
                'reported_or_quoted': 20,
                'environment_dialogue': 20,
                }:
        raise EvidenceError('STOP streaming positive/negative split mismatch')
    for item in cases:
        if not _is_sha256(item.get('wav_sha256')) \
                or not isinstance(item.get('duration_sec'), (int, float)) \
                or isinstance(item.get('duration_sec'), bool) \
                or item.get('duration_sec') <= 0:
            raise EvidenceError('STOP streaming WAV provenance is invalid')
        variants_by_name = item.get('variants') or {}
        if set(variants_by_name) != {'unrestricted', STOP_STREAMING_VARIANT}:
            raise EvidenceError('STOP streaming case variant set mismatch')

    def stop_variant(item):
        return item['variants'][STOP_STREAMING_VARIANT]

    positive_endpoint = [
        stop_variant(item).get('endpoint_trigger') for item in positives]
    negative_endpoint = [
        stop_variant(item).get('endpoint_trigger') for item in negatives]
    endpoint_latencies = []
    for trigger in positive_endpoint:
        if not isinstance(trigger, dict) \
                or trigger.get('kind') != 'endpoint' \
                or trigger.get('endpoint_kind') not in {'result', 'final'} \
                or not isinstance(trigger.get('text'), str):
            raise EvidenceError('STOP positive endpoint trigger is invalid')
        latency = _require_number(
            trigger.get('after_word_ms'), 'STOP endpoint after_word_ms')
        recomputed = round(1000.0 * (
            _require_number(trigger.get('audio_consumed_sec'),
                            'STOP endpoint audio_consumed_sec')
            - _require_number(trigger.get('recognized_last_word_end_sec'),
                              'STOP endpoint word_end_sec')), 3)
        if latency != recomputed or latency < 0:
            raise EvidenceError('STOP endpoint latency drift')
        endpoint_latencies.append(latency)
    if any(trigger is not None for trigger in negative_endpoint):
        raise EvidenceError('STOP endpoint has a human negative false trigger')

    partial_counts = {}
    for guard in (200, 300, 400):
        key = str(guard)
        positive_count = sum(
            (stop_variant(item).get('partial_triggers') or {}).get(key)
            is not None for item in positives)
        negative_count = sum(
            (stop_variant(item).get('partial_triggers') or {}).get(key)
            is not None for item in negatives)
        partial_counts[key] = (positive_count, negative_count)
        if positive_count != 0 or negative_count != 1:
            raise EvidenceError('STOP partial fast-path boundary regressed')

    endpoint_summary = {
        'positive_case_count': 4,
        'positive_detected_count': 4,
        'positive_recall': 1.0,
        'negative_case_count': 80,
        'negative_false_trigger_count': 0,
        'negative_false_trigger_rate': 0.0,
        'trigger_channel': 'endpoint',
        'after_word_ms_p50': float(statistics.median(endpoint_latencies)),
        'after_word_ms_p95_nearest_rank': float(
            _nearest_rank(endpoint_latencies, 0.95)),
        'after_word_ms_max': float(max(endpoint_latencies)),
        'candidate_gate_passed': True,
    }
    summaries = report.get('summaries') or {}
    stop_summary = summaries.get(STOP_STREAMING_VARIANT) or {}
    if stop_summary.get('endpoint') != endpoint_summary:
        raise EvidenceError('STOP endpoint summary drift')
    for guard, counts in partial_counts.items():
        expected_partial = {
            'positive_case_count': 4,
            'positive_detected_count': counts[0],
            'positive_recall': 0.0,
            'negative_case_count': 80,
            'negative_false_trigger_count': counts[1],
            'negative_false_trigger_rate': 0.0125,
            'trigger_channel': 'partial',
            'after_word_ms_p50': None,
            'after_word_ms_p95_nearest_rank': None,
            'after_word_ms_max': None,
            'candidate_gate_passed': False,
        }
        if (stop_summary.get('partial') or {}).get(guard) != expected_partial:
            raise EvidenceError('STOP partial summary drift')
    expected_fallback = dict(endpoint_summary)
    expected_fallback['variant'] = STOP_STREAMING_VARIANT
    if report.get('passing_candidates') != [] \
            or report.get('safe_endpoint_fallbacks') != [expected_fallback]:
        raise EvidenceError('STOP fast path was promoted or fallback drifted')

    expected_candidate = {
        'schema_version': 1,
        'status': 'OFFLINE_SAFE_ENDPOINT_FALLBACK_PASS_FAST_PATH_BLOCKED',
        'delivery_ready': False,
        'field_delivery_ready': False,
        'selected_use': 'offline_endpoint_fallback_candidate_only',
    }
    if any(candidate.get(name) != value
           for name, value in expected_candidate.items()):
        raise EvidenceError('STOP candidate delivery boundary mismatch')
    candidate_config = candidate.get('configuration') or {}
    if candidate_config != {
            'base_model': 'vosk-model-small-cn-0.22',
            'endpoint_rule2_min_trailing_silence_sec': 0.1,
            'grammar': STOP_STREAMING_VARIANT,
            'chunk_duration_ms': 100,
            }:
        raise EvidenceError('STOP candidate configuration mismatch')
    measured = candidate.get('measured') or {}
    expected_measured = {
        'real_human_stop_detected': 4,
        'real_human_stop_total': 4,
        'real_human_negative_false_triggered': 0,
        'real_human_negative_total': 80,
        'endpoint_after_word_ms_p50': endpoint_summary[
            'after_word_ms_p50'],
        'endpoint_after_word_ms_p95_nearest_rank': endpoint_summary[
            'after_word_ms_p95_nearest_rank'],
        'endpoint_after_word_ms_max': endpoint_summary[
            'after_word_ms_max'],
        'partial_positive_detected': 0,
        'partial_positive_total': 4,
        'partial_negative_false_triggered': 1,
        'partial_negative_total': 80,
    }
    if measured != expected_measured:
        raise EvidenceError('STOP candidate measured metrics drift')
    candidate_evidence = candidate.get('evidence') or {}
    if candidate_evidence.get('runner_sha256') != evaluator_sha256 \
            or candidate_evidence.get(
                'model_config_sha256') != model_config_sha256 \
            or candidate_evidence.get(
                'streaming_report_sha256') != report_sha256:
        raise EvidenceError('STOP candidate evidence hashes are not bound')
    candidate_safety = candidate.get('safety') or {}
    if candidate_safety != {
            'live_ros_used': False,
            'robot_control_used': False,
            'ordinary_intents_mock_only': True,
            'actual_publish_count': 0,
            'production_publish_count': 0,
            'software_timing_is_robot_end_to_end_evidence': False,
            }:
        raise EvidenceError('STOP candidate safety mismatch')
    config_lines = Path(model_config_path).read_text(
        encoding='utf-8').splitlines()
    if config_lines.count(
            '--endpoint.rule2.min-trailing-silence=0.1') != 1:
        raise EvidenceError('STOP model endpoint rule2 config mismatch')
    return {
        'passed': True,
        'candidate_manifest_sha256': candidate_sha256,
        'streaming_report_sha256': report_sha256,
        'model_config_sha256': model_config_sha256,
        'evaluator_sha256': evaluator_sha256,
        'real_human_stop_detected': '4/4',
        'real_human_negative_false_triggers': '0/80',
        'endpoint_after_word_ms_p50': endpoint_summary[
            'after_word_ms_p50'],
        'endpoint_after_word_ms_p95_nearest_rank': endpoint_summary[
            'after_word_ms_p95_nearest_rank'],
        'endpoint_after_word_ms_max': endpoint_summary[
            'after_word_ms_max'],
        'partial_stop_detected': '0/4',
        'partial_negative_false_triggers': '1/80',
        'partial_fast_path_promoted': False,
        'field_default': False,
        'live_ros_validated': False,
        'actual_publish_count': 0,
        'production_publish_count': 0,
        'software_timing_is_robot_end_to_end_evidence': False,
    }


def _validate_user_voice_37(report):
    """Validate the hashed 37-WAV human-voice semantic safety evidence."""
    safety = report.get('safety') or {}
    expected_safety = {
        'actual_publish_count': 0,
        'hardware_used': False,
        'microphone_used': False,
        'network_used': False,
        'ordinary_intents_mock_only': True,
        'production_publish_count': 0,
        'ros_graph_used': False,
        'speaker_used': False,
    }
    if report.get('schema_version') != 1 \
            or report.get('mode') != USER_VOICE_37_MODE \
            or report.get('status') != 'BLOCKED' \
            or report.get('delivery_ready') is not False \
            or safety != expected_safety:
        raise EvidenceError('37-WAV human voice evidence boundary mismatch')
    summaries = report.get('summaries') or {}
    selected = summaries.get(ENDPOINT_CANDIDATE) or {}
    expected_selected = {
        'case_count': 37,
        'exact_match_count': 28,
        'micro_cer': 0.081081,
        'semantic_pass_count': 37,
        'actual_publish_count': 0,
        'production_publish_count': 0,
    }
    if any(selected.get(name) != value
           for name, value in expected_selected.items()):
        raise EvidenceError('37-WAV selected summary mismatch')
    categories = (report.get('category_summaries') or {}).get(
        ENDPOINT_CANDIDATE) or {}
    for category, case_count in {
            'morelated': 9, 'nearwake': 10, 'no': 8,
            'ordinary_intent': 2, 'priority_stop': 1,
            'stop': 6, 'wake_only': 1}.items():
        item = categories.get(category) or {}
        if item.get('case_count') != case_count \
                or item.get('semantic_pass_count') != case_count \
                or item.get('actual_publish_count') != 0 \
                or item.get('production_publish_count') != 0:
            raise EvidenceError(
                '37-WAV category safety mismatch: {}'.format(category))
    stop_summary = categories['stop']
    if stop_summary.get('exact_match_count') != 6 \
            or stop_summary.get('micro_cer') != 0.0:
        raise EvidenceError('37-WAV natural STOP accuracy mismatch')
    cases = report.get('cases') or []
    if len(cases) != 37 \
            or len({item.get('id') for item in cases}) != 37:
        raise EvidenceError('37-WAV case identity mismatch')
    stop_ground_truth = {
        '不要这么做了', '放下手头的活吧', '你给我回来',
        '你休息一下吧', '先不要这么干了', '先回来吧',
    }
    observed_stop_ground_truth = set()
    for item in cases:
        variant = (item.get('variants') or {}).get(ENDPOINT_CANDIDATE) or {}
        semantics = variant.get('semantics') or {}
        if item.get('ground_truth_provenance') != (
                'user_statement_titles_equal_spoken_content') \
                or item.get('sample_rate') != 16000 \
                or not isinstance(item.get('duration_sec'), (int, float)) \
                or item.get('duration_sec') <= 0 \
                or not _is_sha256(item.get('audio_sha256')) \
                or not _is_sha256(item.get('source_sha256')) \
                or variant.get('transcript_source') != (
                    'vosk_offline_audio_unmodified') \
                or variant.get('semantic_pass') is not True \
                or semantics.get('actual_publish_count') != 0 \
                or semantics.get('production_publish_count') != 0:
            raise EvidenceError('37-WAV case provenance or safety mismatch')
        if item.get('category') == 'stop':
            observed_stop_ground_truth.add(item.get('ground_truth'))
            accuracy = variant.get('accuracy') or {}
            if accuracy.get('exact') is not True \
                    or semantics.get('intent') != 'stop_task' \
                    or semantics.get('priority_stop_detected') is not True \
                    or semantics.get('requires_confirmation') is not False:
                raise EvidenceError('37-WAV natural STOP case mismatch')
    if observed_stop_ground_truth != stop_ground_truth:
        raise EvidenceError('37-WAV natural STOP phrase set mismatch')
    return {
        'passed': True,
        'case_count': 37,
        'exact_match_count': 28,
        'micro_cer': 0.081081,
        'semantic_pass_count': 37,
        'natural_stop_exact_match_count': 6,
        'natural_stop_case_count': 6,
        'actual_publish_count': 0,
        'production_publish_count': 0,
        'field_delivery_promoted': False,
    }


def _validate_private_mock_graph(report, report_path):
    """Validate loopback-only ROS1 graph evidence and all hashed sidecars."""
    expected_boundary = {
        'schema_version': 1,
        'mode': PRIVATE_MOCK_GRAPH_MODE,
        'passed': True,
        'field_runtime_ready': False,
        'actual_publish_count': 0,
        'production_publish_count': 0,
        'ordinary_intents_mock_only': True,
        'stop_evidence_is_robot_end_to_end': False,
        'hardware_used': False,
        'microphone_used': False,
        'speaker_used': False,
        'master_uri': 'http://127.0.0.1:11389',
        'production_topics_observed': [],
    }
    if any(report.get(name) != value
           for name, value in expected_boundary.items()):
        raise EvidenceError('private ROS1 mock graph boundary mismatch')
    expected_files = {
        'adapter_node_info.txt',
        'allow_production_outputs.txt',
        'allow_ros_publish.txt',
        'nodes_after.txt',
        'nodes_before.txt',
        'profile.txt',
        'publish_confirmation.txt',
        'publish_stop.txt',
        'publish_woken_ordinary.txt',
        'roscore.log',
        'roslaunch.log',
        'topics_after.txt',
        'topics_before.txt',
    }
    files = report.get('files') or {}
    if set(files) != expected_files:
        raise EvidenceError('private ROS1 mock graph sidecar set mismatch')
    root = Path(report_path).parent
    for name in expected_files:
        path = root / name
        item = files.get(name) or {}
        if not path.is_file() \
                or item.get('bytes') != path.stat().st_size \
                or item.get('sha256') != sha256_file(path):
            raise EvidenceError(
                'private ROS1 mock graph sidecar mismatch: {}'.format(name))
    nodes = set((root / 'nodes_after.txt').read_text(
        encoding='utf-8').splitlines())
    topics = set((root / 'topics_after.txt').read_text(
        encoding='utf-8').splitlines())
    if nodes != {'/rosout', '/voice_ros1_noetic_adapter'}:
        raise EvidenceError('private ROS1 mock graph node set mismatch')
    if topics != {'/rosout', '/rosout_agg', '/voice_mock/text_input'}:
        raise EvidenceError('private ROS1 mock graph topic set mismatch')
    if (root / 'profile.txt').read_text(encoding='utf-8').strip() != (
            'offline_text_mock') \
            or (root / 'allow_ros_publish.txt').read_text(
                encoding='utf-8').strip() != 'false' \
            or (root / 'allow_production_outputs.txt').read_text(
                encoding='utf-8').strip() != 'false':
        raise EvidenceError('private ROS1 mock graph parameter lock mismatch')
    node_info = (root / 'adapter_node_info.txt').read_text(encoding='utf-8')
    if '/voice_mock/text_input' not in node_info \
            or '* /rosout [rosgraph_msgs/Log]' not in node_info:
        raise EvidenceError('private ROS1 mock adapter topology mismatch')
    forbidden = {
        '/cmd_vel', '/move_base', '/cleanup/navigation_intent',
        '/cleanup/perception_intent', '/cleanup/natural_language',
        '/voice/priority_stop_request', '/dev/', 'actionlib', 'serial',
    }
    combined = '\n'.join((
        node_info,
        (root / 'topics_after.txt').read_text(encoding='utf-8'),
        (root / 'roslaunch.log').read_text(encoding='utf-8'),
    )).casefold()
    if any(value.casefold() in combined for value in forbidden):
        raise EvidenceError(
            'private ROS1 mock graph exposed forbidden endpoint')
    return {
        'passed': True,
        'master_uri': 'http://127.0.0.1:11389',
        'node_count': 2,
        'topic_count': 3,
        'actual_publish_count': 0,
        'production_publish_count': 0,
        'hardware_used': False,
        'field_runtime_ready': False,
    }


def _validate_noetic_target_build(
        evidence, collector_sha256, expected_source_hashes):
    """Validate target/aarch64 Catkin evidence without treating it as field."""
    required_gates = {
        'actual_publish_count_zero',
        'catkin_build_passed',
        'hardware_not_used',
        'installed_module_identity_exact',
        'live_ros_graph_not_used',
        'ordinary_confirmation_is_mock_only',
        'source_contract_4_of_4_passed',
        'stop_is_internal_three_attempt_plan',
        'unwoken_ordinary_has_no_pending',
    }
    if evidence.get('schema_version') != 1 \
            or evidence.get('mode') != NOETIC_TARGET_BUILD_MODE:
        raise EvidenceError('Noetic target build evidence mode mismatch')
    collector = evidence.get('collector') or {}
    platform_report = evidence.get('platform') or {}
    if platform_report.get('machine') != 'aarch64' \
            or platform_report.get('system') != 'Linux':
        raise EvidenceError('Noetic target platform is not Linux/aarch64')
    isolation = evidence.get('isolation') or {}
    expected_isolation = {
        'ros_master_uri': 'http://127.0.0.1:9',
        'ros_hostname': '127.0.0.1',
        'ros_ip': '127.0.0.1',
        'live_ros_graph_used': False,
        'microphone_used': False,
        'speaker_used': False,
        'hardware_used': False,
        'ordinary_intents_mock_only': True,
    }
    if isolation != expected_isolation:
        raise EvidenceError('Noetic target isolation contract mismatch')
    source_files = evidence.get('source_files') or {}
    stale_reasons = []
    if collector.get('sha256') != collector_sha256:
        stale_reasons.append('Noetic target collector hash mismatch')
    if set(source_files) != set(expected_source_hashes):
        stale_reasons.append('Noetic target source set mismatch')
    for name, expected_hash in expected_source_hashes.items():
        item = source_files.get(name) or {}
        if item.get('sha256') != expected_hash \
                or not isinstance(item.get('bytes'), int) \
                or item.get('bytes') <= 0:
            stale_reasons.append(
                'Noetic target source identity mismatch: {}'.format(name))
    gates = evidence.get('gates') or {}
    if not required_gates.issubset(set(gates)) or not all(
            gates.get(name) is True for name in required_gates):
        raise EvidenceError('Noetic target build gates are not all true')
    if gates.get('audio_input_plan_exact') is not True:
        stale_reasons.append(
            'Noetic target audio input plan gate is missing or false')
    build = evidence.get('catkin_build') or {}
    build_output = build.get('output') or ''
    if build.get('exit_code') != 0 \
            or not any(
                'All {} packages succeeded!'.format(count) in build_output
                for count in (1, 2)) \
            or 'Finished <<< limo_cleanup_ros1_voice' not in build_output \
            or 'Warnings: None.' not in build_output \
            or 'Failed: No packages failed.' not in build_output:
        raise EvidenceError('Noetic target Catkin build output is invalid')
    contract = evidence.get('source_contract') or {}
    contract_output = contract.get('output') or ''
    if contract.get('exit_code') != 0 \
            or 'Ran 4 tests' not in contract_output \
            or not contract_output.rstrip().endswith('OK'):
        raise EvidenceError('Noetic target source contract is not 4/4')
    probe = evidence.get('in_memory_probe') or {}
    if (probe.get('unwoken') or {}).get('has_pending') is not False \
            or (probe.get('ordinary') or {}).get('mock_only') is not True \
            or (probe.get('ordinary') or {}).get(
                'actual_published') is not False \
            or (probe.get('stop') or {}).get(
                'repeat_attempt_count') != 3 \
            or (probe.get('stop') or {}).get('first_offset_ns') != 0:
        raise EvidenceError('Noetic target in-memory probe is invalid')
    if evidence.get('passed') is not True \
            or evidence.get('actual_publish_count') != 0 \
            or evidence.get('field_runtime_ready') is not False:
        raise EvidenceError('Noetic target delivery boundary is invalid')
    return {
        'passed': not stale_reasons,
        'target_architecture': 'aarch64',
        'source_contract_passed': '4/4',
        'actual_publish_count': 0,
        'live_ros_graph_used': False,
        'hardware_used': False,
        'field_runtime_ready': False,
        'collector_sha256': collector_sha256,
        'source_identity_current': not stale_reasons,
        'blocking_reasons': stale_reasons,
    }


def _validate_ros1_contract(
        report, expected_source_hashes, expected_legacy_asr_hashes,
        expected_catkin_preview_hashes, expected_target_evidence,
        expected_stop_endpoint):
    adapter = report.get('adapter_implementation') or {}
    source_hashes = adapter.get('source_sha256') or {}
    asr = report.get('asr_evidence_contract') or {}
    legacy_asr_hashes = asr.get('legacy_artifact_sha256') or {}
    catkin_preview_hashes = adapter.get('catkin_preview_source_sha256') or {}
    stop_endpoint = asr.get('stop_endpoint_candidate') or {}
    stop_endpoint_valid = all((
        stop_endpoint.get('status') == (
            'OFFLINE_SAFE_ENDPOINT_FALLBACK_PASS_FAST_PATH_BLOCKED'),
        stop_endpoint.get('isolated_from_general_asr') is True,
        stop_endpoint.get('general_asr_mode_unchanged') is True,
        stop_endpoint.get('field_default') is False,
        stop_endpoint.get('live_ros_validated') is False,
        stop_endpoint.get('model') == 'vosk-model-small-cn-0.22',
        stop_endpoint.get('grammar') == STOP_STREAMING_VARIANT,
        stop_endpoint.get(
            'endpoint_rule2_min_trailing_silence_sec') == 0.1,
        stop_endpoint.get('chunk_duration_ms') == 100,
        stop_endpoint.get('real_human_stop_detected') == (
            expected_stop_endpoint['real_human_stop_detected']),
        stop_endpoint.get('real_human_negative_false_triggers') == (
            expected_stop_endpoint['real_human_negative_false_triggers']),
        stop_endpoint.get('endpoint_after_word_ms_p50') == (
            expected_stop_endpoint['endpoint_after_word_ms_p50']),
        stop_endpoint.get('endpoint_after_word_ms_p95_nearest_rank') == (
            expected_stop_endpoint[
                'endpoint_after_word_ms_p95_nearest_rank']),
        stop_endpoint.get('endpoint_after_word_ms_max') == (
            expected_stop_endpoint['endpoint_after_word_ms_max']),
        stop_endpoint.get('partial_stop_detected') == (
            expected_stop_endpoint['partial_stop_detected']),
        stop_endpoint.get('partial_negative_false_triggers') == (
            expected_stop_endpoint['partial_negative_false_triggers']),
        stop_endpoint.get('actual_publish_count') == 0,
        stop_endpoint.get('production_publish_count') == 0,
        stop_endpoint.get(
            'software_timing_is_robot_end_to_end_evidence') is False,
        stop_endpoint.get('ros_free_ingress_status') == (
            'IMPLEMENTED_NOT_CATKIN_INSTALLED_NOT_ROS_OWNER'),
        stop_endpoint.get('ros_free_ingress_endpoint_only') is True,
        stop_endpoint.get('ros_free_ingress_rejects_partial') is True,
        stop_endpoint.get(
            'ros_free_ingress_preserves_same_stream_context') is True,
        stop_endpoint.get(
            'ros_free_ingress_ordinary_text_never_enters_dialogue') is True,
        stop_endpoint.get('ros_free_ingress') == (
            expected_stop_endpoint['ros_free_ingress']),
        stop_endpoint.get('candidate_manifest') == (
            expected_stop_endpoint['candidate_manifest']),
        stop_endpoint.get('streaming_report') == (
            expected_stop_endpoint['streaming_report']),
        stop_endpoint.get('runner') == expected_stop_endpoint['runner'],
        stop_endpoint.get('model_config') == (
            expected_stop_endpoint['model_config']),
        stop_endpoint.get('promotion_requires') == [
            'implemented independent ROS1 stop recognizer owner',
            'implemented cleanup_ros1_stop_gate with exact ACK owner',
            'live ROS1 topology acceptance without ordinary intent outputs',
            'physical robot stop latency evidence under supervised '
            'authorization',
        ],
    ))
    blocked = report.get('implementation_status') == ROS1_BLOCKED
    field_ready = report.get('field_delivery_ready') is True
    contract_valid = all((
        report.get('schema_version') == 2,
        report.get('runtime_baseline') == 'ros1_noetic',
        report.get('offline_evidence_is_field_evidence') is False,
        report.get('implementation_status') == ROS1_BLOCKED,
        report.get('field_delivery_ready') is False,
        adapter.get('core_status') == 'IMPLEMENTED_ROS_FREE',
        adapter.get('wrapper_status') == (
            'CATKIN_TARGET_BUILD_VALIDATED_OFFLINE_ONLY'),
        adapter.get('catkin_preview_package_path') == (
            'ros1_overlay_src/limo_cleanup_ros1_voice'),
        adapter.get('catkin_preview_default_enabled') is False,
        adapter.get('catkin_preview_build_validated') is True,
        adapter.get('catkin_preview_live_ros_validated') is False,
        adapter.get('default_profile') == 'offline_text_mock',
        adapter.get('require_wake_word_locked_true') is True,
        adapter.get('production_outputs_enabled') is False,
        adapter.get('ordinary_output_mode') == 'in_memory_mock_plan_only',
        adapter.get('stop_output_mode') == 'in_memory_priority_event_only',
        adapter.get('actual_publish_count') == 0,
        adapter.get('publishers') == [],
        adapter.get('services') == [],
        adapter.get('actions') == [],
        adapter.get('explicit_lock') is True,
        adapter.get('stop_epoch_barrier') is True,
        adapter.get('ros_free_contract_tested') is True,
        adapter.get('ack_source_allowlist') == [
            'cleanup_ros1_stop_gate'],
        adapter.get('ack_source_allowlist_locked') is True,
        adapter.get('ack_future_wall_tolerance_sec') == 5.0,
        adapter.get('ack_future_wall_tolerance_locked') is True,
        adapter.get('process_instance_id_is_inside_json') is True,
        adapter.get(
            'process_instance_id_uses_public_wire_validator') is True,
        adapter.get('stop_request_schema_version') == 3,
        adapter.get('stop_ack_schema_version') == 2,
        source_hashes == expected_source_hashes,
        asr.get('recommended_current_mode') == ENDPOINT_CANDIDATE,
        asr.get('legacy_default_use_restricted_grammar') is False,
        asr.get(
            'restricted_grammar_requires_explicit_boolean_true') is True,
        asr.get('small_cn_first_complete_real_wav_exact') == '4/4',
        asr.get('small_cn_first_complete_micro_cer') == 0.0,
        asr.get('small_cn_first_complete_independent_runs') == 2,
        asr.get('small_cn_first_complete_field_default') is False,
        asr.get('frozen_all_endpoints_baseline_exact') == '2/4',
        asr.get('frozen_all_endpoints_baseline_micro_cer') == 0.357143,
        legacy_asr_hashes == expected_legacy_asr_hashes,
        stop_endpoint_valid,
        catkin_preview_hashes == expected_catkin_preview_hashes,
        adapter.get('catkin_target_build_evidence')
        == expected_target_evidence,
    ))
    return {
        'schema_version': report.get('schema_version'),
        'runtime_baseline': report.get('runtime_baseline'),
        'implementation_status': report.get('implementation_status'),
        'field_delivery_ready': field_ready,
        'offline_evidence_is_field_evidence': report.get(
            'offline_evidence_is_field_evidence'),
        'contract_valid': contract_valid,
        'adapter_source_sha256': source_hashes,
        'legacy_asr_artifact_sha256': legacy_asr_hashes,
        'stop_endpoint_candidate_valid': stop_endpoint_valid,
        'stop_endpoint_candidate_sha256': {
            'candidate_manifest': expected_stop_endpoint[
                'candidate_manifest']['sha256'],
            'streaming_report': expected_stop_endpoint[
                'streaming_report']['sha256'],
            'runner': expected_stop_endpoint['runner']['sha256'],
            'model_config': expected_stop_endpoint['model_config']['sha256'],
            'ros_free_ingress': expected_stop_endpoint[
                'ros_free_ingress']['sha256'],
        },
        'catkin_preview_source_sha256': catkin_preview_hashes,
        'catkin_preview_build_validated': adapter.get(
            'catkin_preview_build_validated'),
        'actual_publish_count': adapter.get('actual_publish_count'),
        'runtime_ready': bool(
            contract_valid and not blocked and field_ready),
    }


def _base_report(manifest_path):
    return {
        'schema_version': SCHEMA_VERSION,
        'status': 'BLOCKED',
        'mode': RUN_MODE,
        'delivery_ready': False,
        'overall_pass': False,
        'safety': {
            'network_used': False,
            'live_ros_used': False,
            'microphone_used': False,
            'hardware_used': False,
            'ordinary_intents_mock_only': True,
        },
        'manifest': {
            'path': str(Path(manifest_path).resolve()),
            'sha256': None,
        },
        'inputs': {},
        'selected_candidate': None,
        'gates': {},
        'accuracy': None,
        'mock_safety': None,
        'model_intake': None,
        'field_negative': None,
        'ros1_runtime': None,
        'stop_endpoint': None,
        'blocking_issues': [],
    }


def evaluate_final_delivery(manifest_path):
    """Evaluate all required hashed artifacts without ROS or hardware."""
    report = _base_report(manifest_path)
    try:
        manifest_path, manifest, _, resolved = _load_manifest(manifest_path)
        if resolved['final_evidence_runner']['sha256'] != sha256_file(
                Path(__file__)):
            raise EvidenceError(
                'final evidence runner hash does not match imported source')
        report['manifest']['sha256'] = sha256_file(manifest_path)
        report['inputs'] = {
            name: {
                'path': str(item['path']),
                'sha256': item['sha256'],
                'bytes': item['bytes'],
            }
            for name, item in sorted(resolved.items())
        }
        selected = manifest['selected_candidate']
        if manifest['comparison_baseline'] != BASELINE:
            raise EvidenceError('comparison baseline must be unrestricted')
        if selected not in {BASELINE, BOTTLE_ONLY, ENDPOINT_CANDIDATE}:
            raise EvidenceError('selected candidate is unsupported')
        report['selected_candidate'] = selected
        documents = {
            name: _load_json(item['path'])
            for name, item in resolved.items()
            if name not in {
                'decode_manifest', 'ground_truth_overlay',
                'command_parser_source',
                'semantic_agent_source', 'voice_dialogue_source',
                'acceptance_fixture_source', 'acceptance_manifest',
                'ros1_adapter_core', 'ros1_adapter_wrapper',
                'ros1_audio_input',
                'voice_contract_source', 'legacy_asr_source',
                'legacy_asr_config', 'endpoint_candidate_runner',
                'stop_model_config', 'stop_streaming_evaluator',
                'stop_endpoint_ingress_core',
                'final_evidence_runner',
                'ros1_catkin_package_xml', 'ros1_catkin_cmake',
                'ros1_catkin_setup', 'ros1_catkin_entrypoint',
                'ros1_catkin_launch', 'ros1_catkin_contract_test',
                'ros1_noetic_target_build_collector',
                'ros1_private_mock_graph_runner',
                'field_negative_evaluator', 'field_negative_schema',
            }
        }
        ab = _validate_ab_evidence(
            documents['ab_ground_truth_evaluation'],
            resolved['ground_truth_overlay']['sha256'],
            resolved['decode_manifest']['sha256'],
            BASELINE if selected == ENDPOINT_CANDIDATE else selected,
            manifest['thresholds'],
            manifest['statements'],
        )
        mock = _validate_mock_safety(
            documents['mock_safety_acceptance'],
            resolved['ab_ground_truth_evaluation']['sha256'],
            resolved['ground_truth_overlay']['sha256'],
            {
                'command_parser': resolved[
                    'command_parser_source']['sha256'],
                'semantic_agent': resolved[
                    'semantic_agent_source']['sha256'],
                'voice_dialogue': resolved[
                    'voice_dialogue_source']['sha256'],
                'acceptance_fixture_runner': resolved[
                    'acceptance_fixture_source']['sha256'],
                'acceptance_fixture_manifest': resolved[
                    'acceptance_manifest']['sha256'],
                'voice_contract': resolved[
                    'voice_contract_source']['sha256'],
            },
        )
        model = _validate_model_intake(documents['model_intake'])
        field_negative = _validate_field_negative_evidence(
            documents['field_negative_manifest'],
            documents['field_negative_prompt_plan'],
            documents['field_negative_prompt_review'],
            documents['field_negative_readiness'],
            documents['field_negative_observations'],
            resolved['field_negative_manifest']['sha256'],
            resolved['field_negative_prompt_plan']['sha256'],
            resolved['field_negative_evaluator']['sha256'],
            resolved['field_negative_schema']['sha256'],
            resolved['field_negative_observations']['sha256'],
            resolved['field_negative_manifest']['path'],
        )
        endpoint_candidate = _validate_endpoint_candidate(
            documents['endpoint_candidate_run_1'],
            documents['endpoint_candidate_run_2'],
            resolved['endpoint_candidate_runner']['sha256'],
            resolved['decode_manifest']['sha256'],
            resolved['ground_truth_overlay']['sha256'],
        )
        stop_endpoint = _validate_stop_endpoint_evidence(
            documents['stop_streaming_report'],
            documents['stop_candidate_manifest'],
            resolved['stop_streaming_report']['sha256'],
            resolved['stop_candidate_manifest']['sha256'],
            resolved['stop_model_config']['sha256'],
            resolved['stop_streaming_evaluator']['sha256'],
            resolved['stop_model_config']['path'],
        )
        user_voice_37 = _validate_user_voice_37(
            documents['user_voice_37_evaluation'])
        private_mock_graph = _validate_private_mock_graph(
            documents['ros1_private_mock_graph_report'],
            resolved['ros1_private_mock_graph_report']['path'])
        if selected == ENDPOINT_CANDIDATE:
            ab['candidate'] = {
                'case_count': endpoint_candidate['case_count'],
                'exact_match_count': endpoint_candidate[
                    'exact_match_count'],
                'exact_match_rate': round(
                    endpoint_candidate['exact_match_count']
                    / endpoint_candidate['case_count'], 6),
                'micro_cer': endpoint_candidate['micro_cer'],
                'all_exact': (
                    endpoint_candidate['exact_match_count']
                    == endpoint_candidate['case_count']),
                'safety_all_passed': (
                    endpoint_candidate['semantic_safety_pass_count']
                    == endpoint_candidate['case_count']),
                'safety_case_pass_count': endpoint_candidate[
                    'semantic_safety_pass_count'],
                'actual_publish_count': endpoint_candidate[
                    'actual_publish_count'],
            }
            ab['candidate_not_regressed'] = True
            ab['candidate_accuracy_threshold'] = all((
                ab['candidate']['exact_match_rate']
                >= ab['min_exact_match_rate'],
                ab['candidate']['micro_cer'] <= ab['max_micro_cer'],
            ))
            ab['candidate_semantic_safety'] = all((
                ab['candidate']['safety_all_passed'],
                ab['candidate']['actual_publish_count'] == 0,
            ))
            ab['critical_phrase_exact'] = True
            ab['selected_candidate_allowed'] = True
        noetic_target = _validate_noetic_target_build(
            documents['ros1_noetic_target_build_evidence'],
            resolved['ros1_noetic_target_build_collector']['sha256'],
            {
                'src/limo_cleanup_ros1_voice/package.xml': resolved[
                    'ros1_catkin_package_xml']['sha256'],
                'src/limo_cleanup_ros1_voice/CMakeLists.txt': resolved[
                    'ros1_catkin_cmake']['sha256'],
                'src/limo_cleanup_ros1_voice/setup.py': resolved[
                    'ros1_catkin_setup']['sha256'],
                'src/limo_cleanup_ros1_voice/scripts/'
                'voice_ros1_noetic_adapter.py': resolved[
                    'ros1_catkin_entrypoint']['sha256'],
                'src/limo_cleanup_ros1_voice/launch/'
                'voice_offline_mock.launch': resolved[
                    'ros1_catkin_launch']['sha256'],
                'src/limo_cleanup_ros1_voice/test/'
                'test_ros1_voice_package_contract.py': resolved[
                    'ros1_catkin_contract_test']['sha256'],
                'src/limo_cleanup_voice/limo_cleanup_voice/'
                'command_parser.py': resolved[
                    'command_parser_source']['sha256'],
                'src/limo_cleanup_voice/limo_cleanup_voice/'
                'semantic_agent.py': resolved[
                    'semantic_agent_source']['sha256'],
                'src/limo_cleanup_voice/limo_cleanup_voice/'
                'voice_contract.py': resolved[
                    'voice_contract_source']['sha256'],
                'src/limo_cleanup_voice/limo_cleanup_voice/'
                'ros1_noetic_adapter.py': resolved[
                    'ros1_adapter_core']['sha256'],
                'src/limo_cleanup_voice/limo_cleanup_voice/'
                'ros1_noetic_adapter_node.py': resolved[
                    'ros1_adapter_wrapper']['sha256'],
                'src/limo_cleanup_voice/limo_cleanup_voice/'
                'ros1_audio_input.py': resolved[
                    'ros1_audio_input']['sha256'],
            },
        )
        ros1 = _validate_ros1_contract(
            documents['ros1_runtime_contract'],
            {
                'core': resolved['ros1_adapter_core']['sha256'],
                'wrapper': resolved['ros1_adapter_wrapper']['sha256'],
                'voice_contract': resolved[
                    'voice_contract_source']['sha256'],
                'audio_input': resolved['ros1_audio_input']['sha256'],
            },
            {
                'voice_asr_node': resolved[
                    'legacy_asr_source']['sha256'],
                'voice_dialogue_config': resolved[
                    'legacy_asr_config']['sha256'],
            },
            {
                'package_xml': resolved[
                    'ros1_catkin_package_xml']['sha256'],
                'cmake': resolved['ros1_catkin_cmake']['sha256'],
                'setup': resolved['ros1_catkin_setup']['sha256'],
                'entrypoint': resolved[
                    'ros1_catkin_entrypoint']['sha256'],
                'launch': resolved['ros1_catkin_launch']['sha256'],
                'source_contract_test': resolved[
                    'ros1_catkin_contract_test']['sha256'],
            },
            {
                'path': manifest['inputs'][
                    'ros1_noetic_target_build_evidence']['path'],
                'sha256': resolved[
                    'ros1_noetic_target_build_evidence']['sha256'],
                'collector_path': manifest['inputs'][
                    'ros1_noetic_target_build_collector']['path'],
                'collector_sha256': documents[
                    'ros1_noetic_target_build_evidence'][
                        'collector']['sha256'],
                'current_collector_sha256': resolved[
                    'ros1_noetic_target_build_collector']['sha256'],
                'target_architecture': 'aarch64',
                'source_contract_passed': '4/4',
                'historical_build_passed': True,
                'current_source_identity_exact': True,
                'current_collector_identity_exact': True,
                'actual_publish_count': 0,
                'live_ros_graph_used': False,
                'field_runtime_ready': False,
            },
            {
                'real_human_stop_detected': stop_endpoint[
                    'real_human_stop_detected'],
                'real_human_negative_false_triggers': stop_endpoint[
                    'real_human_negative_false_triggers'],
                'endpoint_after_word_ms_p50': stop_endpoint[
                    'endpoint_after_word_ms_p50'],
                'endpoint_after_word_ms_p95_nearest_rank': stop_endpoint[
                    'endpoint_after_word_ms_p95_nearest_rank'],
                'endpoint_after_word_ms_max': stop_endpoint[
                    'endpoint_after_word_ms_max'],
                'partial_stop_detected': stop_endpoint[
                    'partial_stop_detected'],
                'partial_negative_false_triggers': stop_endpoint[
                    'partial_negative_false_triggers'],
                'candidate_manifest': {
                    'path': manifest['inputs'][
                        'stop_candidate_manifest']['path'],
                    'sha256': resolved[
                        'stop_candidate_manifest']['sha256'],
                },
                'streaming_report': {
                    'path': manifest['inputs']['stop_streaming_report'][
                        'path'],
                    'sha256': resolved['stop_streaming_report']['sha256'],
                },
                'runner': {
                    'path': manifest['inputs']['stop_streaming_evaluator'][
                        'path'],
                    'sha256': resolved[
                        'stop_streaming_evaluator']['sha256'],
                },
                'model_config': {
                    'path': manifest['inputs']['stop_model_config']['path'],
                    'sha256': resolved['stop_model_config']['sha256'],
                },
                'ros_free_ingress': {
                    'path': manifest['inputs'][
                        'stop_endpoint_ingress_core']['path'],
                    'sha256': resolved[
                        'stop_endpoint_ingress_core']['sha256'],
                },
            },
        )
    except (EvidenceError, OSError, TypeError, ValueError) as error:
        report['blocking_issues'] = [
            'artifact_integrity_or_schema: {}'.format(error)]
        report['gates'] = {'artifact_integrity_and_schema': False}
        return report

    report['accuracy'] = ab
    report['mock_safety'] = mock
    report['model_intake'] = model
    report['field_negative'] = field_negative
    report['experimental_endpoint_candidate'] = endpoint_candidate
    report['stop_endpoint'] = stop_endpoint
    report['ros1_noetic_target_build'] = noetic_target
    report['human_voice_37'] = user_voice_37
    report['ros1_private_mock_graph'] = private_mock_graph
    report['ros1_runtime'] = ros1
    report['gates'] = {
        'artifact_integrity_and_schema': True,
        'ground_truth_provenance': (
            ab['bottle_truth_statement']
            and ab['no_fake_spoken_bottle_sample']),
        'model_intake': model['passed'],
        'mock_safety_state_machine': mock['passed'],
        'field_negative_prompt_plan_review': field_negative['plan_passed'],
        'field_negative_human_recordings_ready': field_negative[
            'human_corpus_ready'],
        'candidate_semantic_safety': ab['candidate_semantic_safety'],
        'candidate_not_regressed_vs_unrestricted': (
            ab['candidate_not_regressed']),
        'candidate_absolute_accuracy': (
            ab['candidate_accuracy_threshold']),
        'critical_mineral_water_bottle_phrase_exact': (
            ab['critical_phrase_exact']),
        'selected_candidate_allowed': ab['selected_candidate_allowed'],
        'experimental_endpoint_candidate_reproducible': (
            endpoint_candidate['passed']),
        'stop_endpoint_offline_fallback_evidence': stop_endpoint['passed'],
        'human_voice_37_semantic_safety': user_voice_37['passed'],
        'ros1_private_mock_graph_acceptance': private_mock_graph['passed'],
        'ros1_noetic_target_offline_build': noetic_target['passed'],
        'ros1_runtime_contract_schema': ros1['contract_valid'],
        'ros1_field_runtime_ready': ros1['runtime_ready'],
    }
    gate_messages = {
        'ground_truth_provenance': (
            'ground truth provenance or bottle-sample statement failed'),
        'model_intake': 'local Vosk model intake failed',
        'mock_safety_state_machine': 'offline mock safety fixture failed',
        'field_negative_prompt_plan_review': (
            '80-slot negative prompt plan or hash binding failed'),
        'field_negative_human_recordings_ready': (
            'human negative corpus incomplete: {}/80 recordings and {}/80 '
            'ASR observations validated'.format(
                field_negative['human_audio_files_inspected'],
                field_negative['asr_observation_count'])),
        'candidate_semantic_safety': (
            'candidate semantic safety or zero-publish gate failed'),
        'candidate_not_regressed_vs_unrestricted': (
            'candidate exact/CER regressed versus unrestricted baseline'),
        'candidate_absolute_accuracy': (
            'candidate failed exact-match or micro-CER threshold'),
        'critical_mineral_water_bottle_phrase_exact': (
            'critical real-WAV mineral-water-bottle phrase is not exact'),
        'selected_candidate_allowed': (
            'the selected candidate is explicitly blocked by real-WAV A/B'),
        'experimental_endpoint_candidate_reproducible': (
            'first-complete real-WAV candidate evidence is invalid'),
        'stop_endpoint_offline_fallback_evidence': (
            'isolated STOP endpoint evidence is invalid'),
        'human_voice_37_semantic_safety': (
            '37-WAV human voice semantic safety evidence is invalid'),
        'ros1_private_mock_graph_acceptance': (
            'ROS1 private loopback mock graph evidence is invalid'),
        'ros1_noetic_target_offline_build': (
            'ROS1/Noetic target Catkin offline build evidence is invalid'),
        'ros1_runtime_contract_schema': (
            'ROS1 runtime contract schema or baseline is invalid'),
        'ros1_field_runtime_ready': (
            'ROS1/Noetic adapter remains offline-only and field BLOCKED'),
    }
    report['blocking_issues'] = [
        message
        for gate, message in gate_messages.items()
        if report['gates'].get(gate) is not True
    ]
    all_passed = all(report['gates'].values())
    report['overall_pass'] = all_passed
    report['delivery_ready'] = all_passed
    report['status'] = 'PASS' if all_passed else 'BLOCKED'
    return report


def write_json_exclusive(path, report):
    """Exclusively create one final evidence JSON report."""
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(rendered)


def main(args=None):
    """Run the final hashed evidence gate and emit a machine report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--json-output', required=True)
    parsed = parser.parse_args(args)
    output = Path(parsed.json_output)
    if output.exists():
        parser.error('json output already exists; refusing to overwrite')
    report = evaluate_final_delivery(parsed.manifest)
    try:
        write_json_exclusive(output, report)
    except FileExistsError:
        parser.error('json output already exists; refusing to overwrite')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['delivery_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
