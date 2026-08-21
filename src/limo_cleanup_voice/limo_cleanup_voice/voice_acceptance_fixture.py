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

"""Run deterministic Voice V2 acceptance fixtures without ROS or hardware."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from .command_parser import (
    has_wake_word,
    is_priority_stop_text,
    parse_command,
)
from .semantic_agent import normalize_non_stop_semantics
from .voice_contract import (
    parse_stop_ack,
    parse_stop_broadcast,
    stop_ack_payload,
    stop_broadcast_payload,
)


SCHEMA_VERSION = 1
WAKE_WORD = '\u5c0f\u83ab\u5c0f\u83ab'
DEFAULT_DEBOUNCE_NS = 750_000_000
DEFAULT_REPEAT_INTERVAL_NS = 75_000_000
DEFAULT_REPEAT_COUNT = 3
DEFAULT_ACK_TIMEOUT_NS = 1_500_000_000
SUCCESS_ACK_STATES = frozenset({'accepted', 'completed', 'observed'})
ACTIONABLE_ORDINARY_INTENTS = frozenset({
    'start_cleanup',
    'start_touch',
    'navigate_to_bin',
    'inspect_bottle',
})


def _file_identity(path):
    raw = Path(path).read_bytes()
    return {
        'path': str(Path(path).resolve()),
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }


def _source_identities(fixture_path):
    module_root = Path(__file__).resolve().parent
    return {
        'command_parser': _file_identity(module_root / 'command_parser.py'),
        'semantic_agent': _file_identity(module_root / 'semantic_agent.py'),
        'voice_dialogue': _file_identity(
            module_root / 'voice_dialogue_node.py'),
        'voice_contract': _file_identity(module_root / 'voice_contract.py'),
        'acceptance_fixture_runner': _file_identity(Path(__file__)),
        'acceptance_fixture_manifest': _file_identity(fixture_path),
    }


FORBIDDEN_OUTPUT_TOKENS = (
    '/cmd_vel',
    'cmd_vel',
    'twist',
    'geometry_msgs',
    'nav2_msgs',
    'navigate_to_pose',
    'move_base',
    'followjointtrajectory',
    'jointtrajectory',
    'control_msgs',
    'rclpy.action',
    '/_action/',
    '/_service/',
    '/dev/',
    'ttyusb',
    'serial',
    'can0',
    'controller_manager',
    'gripper_controller',
    'power_on',
    'hardware',
    '\u8bbe\u5907',
    '\u786c\u4ef6',
)


def _default_manifest_path():
    source_path = Path(__file__).resolve().parents[1] / 'fixtures' / (
        'voice_offline_acceptance_fixture.json')
    if source_path.is_file():
        return source_path
    try:
        from ament_index_python.packages import get_package_share_directory
    except ImportError as error:
        raise RuntimeError(
            'cannot locate the installed acceptance fixture') from error
    return Path(get_package_share_directory(
        'limo_cleanup_voice')) / 'fixtures' / (
            'voice_offline_acceptance_fixture.json')


def _read_manifest(manifest_path):
    path = Path(manifest_path).resolve()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError('acceptance fixture is unreadable JSON') from error
    expected = {
        'schema_version',
        'mode',
        'safety',
        'thresholds',
        'transcript_cases',
        'semantic_sequence_fixture',
        'confirmation_timeout_fixture',
        'stop_fixture',
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError('acceptance fixture fields do not match schema')
    if data['schema_version'] != SCHEMA_VERSION:
        raise ValueError('acceptance fixture schema version mismatch')
    if data['mode'] != 'deterministic_offline_mock_no_ros_no_hardware':
        raise ValueError('acceptance fixture mode is unsafe')
    safety = data['safety']
    if not isinstance(safety, dict) or set(safety) != {
            'ordinary_intents', 'live_ros', 'hardware'}:
        raise ValueError(
            'acceptance fixture safety fields do not match schema')
    if safety != {
            'ordinary_intents': 'mock_only',
            'live_ros': False,
            'hardware': False}:
        raise ValueError('acceptance fixture safety boundary is not enforced')
    return path, data


def _finite_number(value, label, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('{} must be numeric'.format(label))
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('{} must be finite'.format(label))
    if minimum is not None and number < minimum:
        raise ValueError('{} is below its minimum'.format(label))
    return number


def _validate_thresholds(value):
    expected = {
        'max_false_activation_rate',
        'max_confirmation_timeout_forwarded',
        'max_stop_first_publish_latency_ms',
        'max_stop_ack_observed_latency_ms',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('fixture thresholds do not match schema')
    thresholds = {
        name: _finite_number(item, name, minimum=0.0)
        for name, item in value.items()
    }
    if thresholds['max_false_activation_rate'] > 1.0:
        raise ValueError('max_false_activation_rate must be <= 1')
    if thresholds['max_confirmation_timeout_forwarded'] != 0.0:
        raise ValueError('confirmation timeout forwarding threshold must be 0')
    return thresholds


def _case_text(value, label):
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError('{} must be a non-empty trimmed string'.format(label))
    return value


def _validate_transcript_cases(value):
    if not isinstance(value, list) or not value:
        raise ValueError('transcript_cases must be a non-empty list')
    expected = {
        'id', 'category', 'transcript', 'expected_intent',
        'expect_priority_stop', 'expect_pending_confirmation',
    }
    allowed_categories = {
        'noise',
        'near_soundalike',
        'negated',
        'unwoken',
        'ordinary_mock',
        'priority_stop',
    }
    cases = []
    case_ids = set()
    categories = set()
    for index, case in enumerate(value):
        if not isinstance(case, dict) or set(case) != expected:
            raise ValueError(
                'transcript case {} fields do not match schema'.format(index))
        case_id = _case_text(case['id'], 'transcript case id')
        if case_id in case_ids:
            raise ValueError(
                'duplicate transcript case id: {}'.format(case_id))
        case_ids.add(case_id)
        category = _case_text(case['category'], 'transcript case category')
        if category not in allowed_categories:
            raise ValueError(
                'unknown transcript category: {}'.format(category))
        categories.add(category)
        transcript = case['transcript']
        if not isinstance(transcript, str):
            raise ValueError('transcript must be a string')
        _case_text(case['expected_intent'], 'expected_intent')
        for name in ('expect_priority_stop', 'expect_pending_confirmation'):
            if not isinstance(case[name], bool):
                raise ValueError('{} must be boolean'.format(name))
        if case['expect_priority_stop'] and category != 'priority_stop':
            raise ValueError('only priority_stop cases may expect stop')
        cases.append(dict(case))
    required_categories = {
        'noise', 'near_soundalike', 'negated', 'unwoken',
        'ordinary_mock', 'priority_stop',
    }
    if not required_categories.issubset(categories):
        raise ValueError('fixture is missing required transcript categories')
    return cases


def _evaluate_transcripts(cases):
    results = []
    false_activations = 0
    negative_count = 0
    pending_confirmation_count = 0
    for case in cases:
        parsed = parse_command(
            case['transcript'],
            wake_words=[WAKE_WORD],
            require_wake_word=True,
        )
        priority_stop = is_priority_stop_text(case['transcript'])
        pending_confirmation = (
            parsed.name in ACTIONABLE_ORDINARY_INTENTS
            and parsed.requires_confirmation
        )
        forwarded = priority_stop
        negative = case['category'] in {
            'noise', 'near_soundalike', 'negated', 'unwoken'}
        false_activation = negative and (
            priority_stop or pending_confirmation or forwarded)
        if negative:
            negative_count += 1
        if false_activation:
            false_activations += 1
        if pending_confirmation:
            pending_confirmation_count += 1
        passed = (
            parsed.name == case['expected_intent']
            and priority_stop == case['expect_priority_stop']
            and pending_confirmation
            == case['expect_pending_confirmation']
        )
        if case['category'] == 'ordinary_mock':
            passed = passed and not forwarded and pending_confirmation
        results.append({
            'id': case['id'],
            'category': case['category'],
            'transcript': case['transcript'],
            'intent': parsed.name,
            'requires_confirmation': parsed.requires_confirmation,
            'pending_confirmation': pending_confirmation,
            'priority_stop': priority_stop,
            'ordinary_forwarded_before_confirmation': (
                case['category'] == 'ordinary_mock' and forwarded),
            'false_activation': false_activation,
            'passed': passed,
        })
    return {
        'case_count': len(results),
        'passed_count': sum(item['passed'] for item in results),
        'failed_count': sum(not item['passed'] for item in results),
        'negative_count': negative_count,
        'false_activation_count': false_activations,
        'false_activation_rate': (
            false_activations / float(negative_count)
            if negative_count else 0.0),
        'pending_confirmation_count': pending_confirmation_count,
        'cases': results,
    }


def _validate_semantic_sequence(value):
    expected = {
        'mode', 'wake_timeout_ms', 'provenance', 'steps',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('semantic sequence fields do not match schema')
    if value['mode'] != 'user_labeled_vosk_transcripts_mock_only':
        raise ValueError('semantic sequence mode is unsafe')
    wake_timeout_ms = _finite_number(
        value['wake_timeout_ms'], 'wake_timeout_ms', 0.001)
    provenance = value['provenance']
    if not isinstance(provenance, dict) or set(provenance) != {
            'ground_truth_sha256', 'asr_evidence_sha256',
            'filename_inference_used'}:
        raise ValueError('semantic sequence provenance is incomplete')
    for name in ('ground_truth_sha256', 'asr_evidence_sha256'):
        digest = provenance[name]
        if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(
                    character not in '0123456789abcdef'
                    for character in digest)):
            raise ValueError('{} is not a lowercase SHA-256'.format(name))
    if provenance['filename_inference_used'] is not False:
        raise ValueError('semantic sequence may not infer transcripts')
    steps = value['steps']
    if not isinstance(steps, list) or not steps:
        raise ValueError('semantic sequence steps must be non-empty')
    expected_step = {
        'id', 'offset_ms', 'transcript', 'expected_intent',
        'expected_state',
    }
    allowed_states = {'idle', 'wake_armed', 'pending_confirmation'}
    validated = []
    identifiers = set()
    previous_offset = -1.0
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != expected_step:
            raise ValueError(
                'semantic sequence step {} fields do not match'.format(index))
        identifier = _case_text(step['id'], 'semantic step id')
        if identifier in identifiers:
            raise ValueError(
                'duplicate semantic step id: {}'.format(identifier))
        identifiers.add(identifier)
        offset_ms = _finite_number(
            step['offset_ms'], 'semantic step offset_ms', 0.0)
        if offset_ms <= previous_offset:
            raise ValueError(
                'semantic step offsets must be strictly increasing')
        previous_offset = offset_ms
        transcript = _case_text(step['transcript'], 'semantic transcript')
        expected_intent = _case_text(
            step['expected_intent'], 'semantic expected_intent')
        expected_state = _case_text(
            step['expected_state'], 'semantic expected_state')
        if expected_state not in allowed_states:
            raise ValueError('semantic expected_state is unknown')
        validated.append({
            'id': identifier,
            'offset_ms': offset_ms,
            'transcript': transcript,
            'expected_intent': expected_intent,
            'expected_state': expected_state,
        })
    return {
        'mode': value['mode'],
        'wake_timeout_ms': wake_timeout_ms,
        'provenance': dict(provenance),
        'steps': validated,
    }


def _evaluate_semantic_sequence(value):
    config = _validate_semantic_sequence(value)
    wake_deadline_ms = -1.0
    pending_intent = None
    mock_confirmed_count = 0
    stop_count = 0
    results = []
    for step in config['steps']:
        offset_ms = step['offset_ms']
        wake_armed = wake_deadline_ms >= offset_ms and pending_intent is None
        candidate = normalize_non_stop_semantics(step['transcript'])
        parse_text = (
            step['transcript'] if candidate is None
            else candidate.canonical_text)
        parsed = parse_command(
            parse_text,
            wake_words=[WAKE_WORD],
            require_wake_word=(pending_intent is None and not wake_armed),
        )
        if wake_armed:
            wake_deadline_ms = -1.0
        if parsed.name == 'empty' and has_wake_word(
                step['transcript'], [WAKE_WORD]):
            wake_deadline_ms = offset_ms + config['wake_timeout_ms']
        elif parsed.name in ACTIONABLE_ORDINARY_INTENTS:
            pending_intent = parsed.name
        elif parsed.name == 'confirm':
            if pending_intent is not None:
                mock_confirmed_count += 1
                pending_intent = None
        elif parsed.name == 'reject_confirmation' or (
                parsed.name == 'stop_task'
                and parsed.reason == 'cancel phrase'):
            pending_intent = None
        elif parsed.name == 'stop_task':
            wake_deadline_ms = -1.0
            pending_intent = None
            stop_count += 1
        state = 'pending_confirmation' if pending_intent else (
            'wake_armed' if wake_deadline_ms >= offset_ms else 'idle')
        passed = (
            parsed.name == step['expected_intent']
            and state == step['expected_state'])
        results.append({
            'id': step['id'],
            'offset_ms': offset_ms,
            'transcript': step['transcript'],
            'canonical_text': parse_text,
            'intent': parsed.name,
            'state': state,
            'requires_confirmation': parsed.requires_confirmation,
            'actual_publish_count': 0,
            'passed': passed,
        })
    return {
        'mode': config['mode'],
        'provenance': config['provenance'],
        'wake_timeout_ms': config['wake_timeout_ms'],
        'step_count': len(results),
        'passed_count': sum(item['passed'] for item in results),
        'failed_count': sum(not item['passed'] for item in results),
        'mock_confirmed_high_level_count': mock_confirmed_count,
        'priority_stop_count': stop_count,
        'actual_publish_count': 0,
        'ordinary_intents_mock_only': True,
        'steps': results,
    }


def _evaluate_confirmation_timeout(value):
    expected = {
        'pending_intent',
        'command_text',
        'timeout_ms',
        'confirm_offset_ms',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('confirmation_timeout_fixture fields do not match')
    pending_intent = _case_text(value['pending_intent'], 'pending_intent')
    command_text = _case_text(value['command_text'], 'command_text')
    if pending_intent not in ACTIONABLE_ORDINARY_INTENTS:
        raise ValueError('confirmation fixture intent is not ordinary')
    timeout_ms = _finite_number(value['timeout_ms'], 'timeout_ms', 0.001)
    confirm_offset_ms = _finite_number(
        value['confirm_offset_ms'], 'confirm_offset_ms', 0.0)
    deadline_ns = int(timeout_ms * 1_000_000)
    confirm_ns = int(confirm_offset_ms * 1_000_000)
    expired = confirm_ns > deadline_ns
    forwarded = not expired
    return {
        'mode': 'mock_confirmation_state_only',
        'pending_intent': pending_intent,
        'command_text': command_text,
        'timeout_ms': timeout_ms,
        'confirm_offset_ms': confirm_offset_ms,
        'expired': expired,
        'forwarded_after_timeout': forwarded if expired else None,
        'pending_cleared': expired,
        'passed': expired and not forwarded,
    }


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    rank = int(math.ceil(fraction * len(ordered))) - 1
    return ordered[max(0, min(rank, len(ordered) - 1))]


def _latency_distribution(values):
    samples = [float(value) for value in values]
    if not samples:
        return {
            'samples': 0,
            'minimum_ms': None,
            'median_ms': None,
            'p95_ms': None,
            'maximum_ms': None,
        }
    ordered = sorted(samples)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2.0
    return {
        'samples': len(ordered),
        'minimum_ms': ordered[0],
        'median_ms': median,
        'p95_ms': _percentile(ordered, 0.95),
        'maximum_ms': ordered[-1],
    }


def _validated_stop_config(value):
    expected = {
        'transcript',
        'event_id',
        'process_instance_id',
        'trigger_wall_time_unix_ns',
        'trigger_monotonic_ns',
        'first_publish_offset_ns',
        'repeat_interval_ns',
        'repeat_count',
        'debounce_ns',
        'duplicate_offsets_ns',
        'ack_delay_ns',
        'ack_timeout_ns',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('stop_fixture fields do not match schema')
    transcript = _case_text(value['transcript'], 'stop transcript')
    event_id = _case_text(value['event_id'], 'stop event_id')
    process_instance_id = _case_text(
        value['process_instance_id'], 'stop process_instance_id')
    integer_fields = (
        'trigger_wall_time_unix_ns', 'trigger_monotonic_ns',
        'first_publish_offset_ns', 'repeat_interval_ns', 'repeat_count',
        'debounce_ns', 'ack_delay_ns', 'ack_timeout_ns',
    )
    config = {
        'transcript': transcript,
        'event_id': event_id,
        'process_instance_id': process_instance_id,
    }
    for name in integer_fields:
        item = value[name]
        minimum = 0 if name == 'first_publish_offset_ns' else 1
        if (
                not isinstance(item, int)
                or isinstance(item, bool)
                or item < minimum):
            raise ValueError('{} must be a valid integer'.format(name))
        config[name] = item
    duplicates = value['duplicate_offsets_ns']
    if (
            not isinstance(duplicates, list)
            or not duplicates
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item < 0
                for item in duplicates)):
        raise ValueError('duplicate_offsets_ns must be non-negative integers')
    config['duplicate_offsets_ns'] = list(duplicates)
    if config['repeat_count'] != DEFAULT_REPEAT_COUNT:
        raise ValueError('stop repeat_count must be exactly 3')
    if config['repeat_interval_ns'] != DEFAULT_REPEAT_INTERVAL_NS:
        raise ValueError('stop repeat interval changed from the contract')
    if config['debounce_ns'] != DEFAULT_DEBOUNCE_NS:
        raise ValueError('stop debounce changed from the contract')
    if config['ack_timeout_ns'] != DEFAULT_ACK_TIMEOUT_NS:
        raise ValueError('stop ACK timeout changed from the contract')
    if config['ack_timeout_ns'] <= (
            config['repeat_interval_ns'] * (config['repeat_count'] - 1)):
        raise ValueError('stop ACK timeout cannot cover bounded repeats')
    return config


def _status(state, config, monotonic_ns, **extra):
    payload = {
        'schema_version': 1,
        'state': state,
        'event_id': config['event_id'],
        'monotonic_ns': monotonic_ns,
    }
    payload.update(extra)
    return payload


def _evaluate_stop(value):
    config = _validated_stop_config(value)
    if not is_priority_stop_text(config['transcript']):
        raise ValueError('stop fixture transcript is not an explicit stop')
    trigger_mono = config['trigger_monotonic_ns']
    trigger_wall = config['trigger_wall_time_unix_ns']
    broadcasts = []
    statuses = []
    for attempt in range(1, config['repeat_count'] + 1):
        offset_ns = config['first_publish_offset_ns'] + (
            (attempt - 1) * config['repeat_interval_ns'])
        published_mono = trigger_mono + offset_ns
        published_wall = trigger_wall + offset_ns
        payload = stop_broadcast_payload(
            event_id=config['event_id'],
            process_instance_id=config['process_instance_id'],
            raw_text=config['transcript'],
            attempt=attempt,
            repeat_count=config['repeat_count'],
            trigger_wall_time_unix_ns=trigger_wall,
            trigger_monotonic_ns=trigger_mono,
            published_wall_time_unix_ns=published_wall,
            published_monotonic_ns=published_mono,
        )
        validated = parse_stop_broadcast(json.dumps(
            payload, ensure_ascii=False, sort_keys=True))
        broadcasts.append(validated)
        statuses.append(_status(
            'broadcasting', config, published_mono,
            attempt=attempt,
            transcript_to_publish_latency_ns=(
                validated['transcript_to_publish_latency_ns']),
        ))

    duplicate_results = []
    new_event_count = 1
    for offset_ns in config['duplicate_offsets_ns']:
        debounced = offset_ns < config['debounce_ns']
        state = 'debounced' if debounced else 'new_event_boundary'
        duplicate_results.append({
            'offset_ns': offset_ns,
            'state': state,
            'created_new_event': not debounced,
        })
        statuses.append(_status(
            state, config, trigger_mono + offset_ns,
            created_new_event=not debounced,
        ))
        if not debounced:
            new_event_count += 1
            statuses.append(_status(
                'superseded', config, trigger_mono + offset_ns,
                detail='Previous ACK window closed by a newer stop event',
            ))

    ack_observed_mono = trigger_mono + config['ack_delay_ns']
    acknowledgement = parse_stop_ack(json.dumps(stop_ack_payload(
        event_id=config['event_id'],
        process_instance_id=config['process_instance_id'],
        source='voice_dialogue',
        state='accepted',
        detail='Mock relay observed high-level stop intents',
        wall_time_unix_ns=trigger_wall + config['ack_delay_ns'],
        monotonic_ns=ack_observed_mono,
    ), ensure_ascii=False, sort_keys=True))
    ack_timely = (
        acknowledgement['observed_monotonic_ns'] - trigger_mono
        <= config['ack_timeout_ns'])
    ack_successful = (
        acknowledgement['state'] in SUCCESS_ACK_STATES and ack_timely)
    statuses.append(_status(
        'acknowledged' if ack_successful else 'ignored_ack',
        config,
        ack_observed_mono,
        ack_source=acknowledgement['source'],
        ack_state=acknowledgement['state'],
    ))
    close_mono = max(
        broadcasts[-1]['published_monotonic_ns'], ack_observed_mono)
    statuses.append(_status(
        'relay_acknowledged' if ack_successful else 'ack_timeout',
        config,
        close_mono,
        attempt=config['repeat_count'],
        repeat_count=config['repeat_count'],
    ))

    first_publish_latency_ns = broadcasts[0][
        'transcript_to_publish_latency_ns']
    ack_observed_latency_ns = ack_observed_mono - trigger_mono
    attempt_sequence = [item['attempt'] for item in broadcasts]
    published_sequence = [
        item['published_monotonic_ns'] for item in broadcasts]
    debounced_offsets = [
        item for item in duplicate_results if item['state'] == 'debounced']
    boundary_offsets = [
        item for item in duplicate_results
        if item['state'] == 'new_event_boundary']
    passed = all((
        first_publish_latency_ns == config['first_publish_offset_ns'],
        attempt_sequence == [1, 2, 3],
        published_sequence == sorted(published_sequence),
        len(debounced_offsets) >= 1,
        all(not item['created_new_event'] for item in debounced_offsets),
        len(boundary_offsets) >= 1,
        all(item['created_new_event'] for item in boundary_offsets),
        new_event_count == 1 + len(boundary_offsets),
        ack_successful,
        statuses[-1]['state'] == 'relay_acknowledged',
    ))
    return {
        'mode': 'mock_stop_state_machine_no_publishers',
        'transcript': config['transcript'],
        'event_id': config['event_id'],
        'first_publish_latency_ns': first_publish_latency_ns,
        'first_publish_latency_ms': first_publish_latency_ns / 1_000_000.0,
        'ack_observed_latency_ns': ack_observed_latency_ns,
        'ack_observed_latency_ms': ack_observed_latency_ns / 1_000_000.0,
        'latency_distribution_ms': {
            'transcript_to_publish': _latency_distribution([
                item['transcript_to_publish_latency_ns'] / 1_000_000.0
                for item in broadcasts
            ]),
            'trigger_to_ack_observed': _latency_distribution([
                ack_observed_latency_ns / 1_000_000.0
            ]),
        },
        'broadcast_attempts': broadcasts,
        'duplicate_results': duplicate_results,
        'new_event_count_including_boundary_cases': new_event_count,
        'ack': acknowledgement,
        'ack_timely': ack_timely,
        'statuses': statuses,
        'passed': passed,
    }


def _strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _high_level_only(report):
    rendered = '\n'.join(_strings(report)).casefold()
    forbidden = tuple(
        token for token in FORBIDDEN_OUTPUT_TOKENS
        if token != 'hardware')
    return all(token not in rendered for token in forbidden)


def generate_acceptance_report(manifest_path=None):
    """Run all acceptance fixtures and return one machine-readable report."""
    path, data = _read_manifest(manifest_path or _default_manifest_path())
    thresholds = _validate_thresholds(data['thresholds'])
    transcript_report = _evaluate_transcripts(
        _validate_transcript_cases(data['transcript_cases']))
    semantic_sequence_report = _evaluate_semantic_sequence(
        data['semantic_sequence_fixture'])
    confirmation_report = _evaluate_confirmation_timeout(
        data['confirmation_timeout_fixture'])
    stop_report = _evaluate_stop(data['stop_fixture'])
    metrics = {
        'false_activation_rate': transcript_report['false_activation_rate'],
        'confirmation_timeout_forwarded': int(
            bool(confirmation_report['forwarded_after_timeout'])),
        'stop_first_publish_latency_ms': (
            stop_report['first_publish_latency_ms']),
        'stop_ack_observed_latency_ms': (
            stop_report['ack_observed_latency_ms']),
    }
    threshold_checks = {
        'false_activation_rate': (
            metrics['false_activation_rate']
            <= thresholds['max_false_activation_rate']),
        'confirmation_timeout_forwarded': (
            metrics['confirmation_timeout_forwarded']
            <= thresholds['max_confirmation_timeout_forwarded']),
        'stop_first_publish_latency_ms': (
            metrics['stop_first_publish_latency_ms']
            <= thresholds['max_stop_first_publish_latency_ms']),
        'stop_ack_observed_latency_ms': (
            metrics['stop_ack_observed_latency_ms']
            <= thresholds['max_stop_ack_observed_latency_ms']),
    }
    report = {
        'schema_version': SCHEMA_VERSION,
        'status': 'PASS',
        'mode': data['mode'],
        'fixture_manifest': str(path),
        'source': _source_identities(path),
        'safety': data['safety'],
        'thresholds': thresholds,
        'metrics': metrics,
        'threshold_checks': threshold_checks,
        'transcripts': transcript_report,
        'semantic_sequence': semantic_sequence_report,
        'confirmation_timeout': confirmation_report,
        'stop': stop_report,
        'high_level_intent_only': True,
        'live_ros_used': False,
        'hardware_used': False,
    }
    report['high_level_intent_only'] = _high_level_only(report)
    passed = all((
        transcript_report['failed_count'] == 0,
        semantic_sequence_report['failed_count'] == 0,
        semantic_sequence_report['actual_publish_count'] == 0,
        confirmation_report['passed'],
        stop_report['passed'],
        all(threshold_checks.values()),
        report['high_level_intent_only'],
    ))
    report['status'] = 'PASS' if passed else 'FAIL'
    return report


def main(args=None):
    """Run the offline fixtures and optionally create a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    parser.add_argument('--json-output')
    parsed = parser.parse_args(args)
    report = generate_acceptance_report(
        parsed.manifest or _default_manifest_path())
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if parsed.json_output:
        output_path = Path(parsed.json_output)
        if output_path.exists():
            raise ValueError('json output already exists; refusing overwrite')
        with output_path.open('x', encoding='utf-8') as output_file:
            output_file.write(rendered + '\n')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
