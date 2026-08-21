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

"""Pure V2 voice-interface contracts shared by runtime and offline tools."""

import json
import math
import re
import time
import uuid


WAKE_WORD = '小莫小莫'
# Exact Vosk lexical observations accepted only at the ASR boundary.  The
# public/user-facing wake phrase remains WAKE_WORD and downstream intents
# never expose these aliases.
ASR_WAKE_WORD_ALIASES = ('小沫小沫',)
ACCEPTED_ASR_WAKE_WORDS = (WAKE_WORD,) + ASR_WAKE_WORD_ALIASES
TRASH_BIN_WAYPOINT = 'trash_bin_staging'
STOP_BROADCAST_SCHEMA_VERSION = 3
STOP_ACK_SCHEMA_VERSION = 2
SEMANTIC_CANDIDATE_SCHEMA_VERSION = 2

_IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$')


def _reject_constant(value):
    raise ValueError('non-finite JSON constant is not allowed: {}'.format(
        value))


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: {}'.format(key))
        result[key] = value
    return result


def loads_strict_object(payload, label):
    """Decode one duplicate-free finite JSON object."""
    if not isinstance(payload, str):
        raise ValueError('{} payload must be a string'.format(label))
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise ValueError('{} payload is invalid JSON'.format(label)) from error
    if not isinstance(value, dict):
        raise ValueError('{} payload must be an object'.format(label))
    return value


def _trimmed_string(value, name, allow_empty=False):
    if not isinstance(value, str) or value != value.strip():
        raise ValueError('{} must be a trimmed string'.format(name))
    if not allow_empty and not value:
        raise ValueError('{} must not be empty'.format(name))
    return value


def _identifier(value, name):
    value = _trimmed_string(value, name)
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError('{} has an invalid format'.format(name))
    return value


def validate_identifier(value, name='identifier'):
    """Validate one public event/process identifier with the wire rule."""
    return _identifier(value, name)


def _positive_int(value, name, allow_zero=False):
    minimum = 0 if allow_zero else 1
    if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum):
        raise ValueError('{} must be an integer >= {}'.format(name, minimum))
    return value


def _confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('confidence must be a number')
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError('confidence must be finite and between 0 and 1')
    return value


def new_event_id(prefix):
    """Return a process-independent identifier suitable for audit joins."""
    return '{}-{}'.format(prefix, uuid.uuid4().hex)


def navigation_stop_payload():
    """Return the strict bridge payload for a high-level safe stop."""
    return {
        'action': 'cancel_navigation',
        'request_safe_stop': True,
    }


def navigation_waypoint_payload(waypoint=TRASH_BIN_WAYPOINT):
    """Return the strict bridge payload for a fixed map waypoint."""
    if not waypoint:
        raise ValueError('waypoint must not be empty')
    return {
        'action': 'navigate_to_waypoint',
        'target_id': waypoint,
        'target_source': 'fixed_map_waypoint',
    }


def perception_inspect_payload():
    """Return the motion-free V2 bottle-inspection intent."""
    return {
        'action': 'inspect_object',
        'object_class': 'plastic_bottle',
        'target_source': 'voice',
    }


def semantic_candidate_payload(
        raw_text, canonical_text, source, confidence=1.0,
        candidate_id=None, wall_time_unix_ns=None, monotonic_ns=None):
    """Build the strict, non-executable semantic candidate schema."""
    return {
        'schema_version': SEMANTIC_CANDIDATE_SCHEMA_VERSION,
        'candidate_id': candidate_id or new_event_id('voice-candidate'),
        'raw_text': raw_text.strip(),
        'canonical_text': canonical_text.strip(),
        'source': source.strip(),
        'confidence': float(confidence),
        'created_wall_time_unix_ns': (
            time.time_ns() if wall_time_unix_ns is None
            else int(wall_time_unix_ns)),
        'created_monotonic_ns': (
            time.monotonic_ns() if monotonic_ns is None
            else int(monotonic_ns)),
    }


def parse_semantic_candidate(payload):
    """Validate an untrusted Agent candidate without executing it."""
    data = loads_strict_object(payload, 'semantic candidate')
    expected = {
        'schema_version', 'candidate_id', 'raw_text', 'canonical_text',
        'source', 'confidence', 'created_wall_time_unix_ns',
        'created_monotonic_ns'}
    if set(data) != expected:
        raise ValueError('semantic candidate fields do not match schema')
    if data['schema_version'] != SEMANTIC_CANDIDATE_SCHEMA_VERSION:
        raise ValueError('semantic candidate version mismatch')
    data['candidate_id'] = _identifier(
        data['candidate_id'], 'candidate_id')
    data['raw_text'] = _trimmed_string(data['raw_text'], 'raw_text')
    data['canonical_text'] = _trimmed_string(
        data['canonical_text'], 'canonical_text')
    data['source'] = _identifier(data['source'], 'source')
    data['confidence'] = _confidence(data['confidence'])
    data['created_wall_time_unix_ns'] = _positive_int(
        data['created_wall_time_unix_ns'], 'created_wall_time_unix_ns')
    data['created_monotonic_ns'] = _positive_int(
        data['created_monotonic_ns'], 'created_monotonic_ns')
    return data


def stop_broadcast_payload(
        event_id, process_instance_id, raw_text, attempt, repeat_count,
        trigger_wall_time_unix_ns, trigger_monotonic_ns,
        published_wall_time_unix_ns=None, published_monotonic_ns=None):
    """Build one attempt of an idempotent priority-stop event."""
    published_wall = (
        time.time_ns() if published_wall_time_unix_ns is None
        else int(published_wall_time_unix_ns))
    published_mono = (
        time.monotonic_ns() if published_monotonic_ns is None
        else int(published_monotonic_ns))
    return {
        'schema_version': STOP_BROADCAST_SCHEMA_VERSION,
        'event_id': event_id,
        'process_instance_id': process_instance_id,
        'priority': 'critical',
        'intent': 'stop_task',
        'command_text': '停止任务',
        'raw_text': raw_text.strip(),
        'source': 'voice_priority_stop',
        'attempt': int(attempt),
        'repeat_count': int(repeat_count),
        'trigger_wall_time_unix_ns': int(trigger_wall_time_unix_ns),
        'trigger_monotonic_ns': int(trigger_monotonic_ns),
        'published_wall_time_unix_ns': published_wall,
        'published_monotonic_ns': published_mono,
        'transcript_to_publish_latency_ns': max(
            0, published_mono - int(trigger_monotonic_ns)),
    }


def parse_stop_broadcast(payload):
    """Validate the priority broadcast consumed by dialogue/observers."""
    data = loads_strict_object(payload, 'stop broadcast')
    expected = {
        'schema_version', 'event_id', 'process_instance_id',
        'priority', 'intent', 'command_text',
        'raw_text', 'source', 'attempt', 'repeat_count',
        'trigger_wall_time_unix_ns', 'trigger_monotonic_ns',
        'published_wall_time_unix_ns', 'published_monotonic_ns',
        'transcript_to_publish_latency_ns'}
    if set(data) != expected:
        raise ValueError('stop broadcast fields do not match schema')
    if data['schema_version'] != STOP_BROADCAST_SCHEMA_VERSION:
        raise ValueError('stop broadcast version mismatch')
    data['event_id'] = _identifier(data['event_id'], 'event_id')
    data['process_instance_id'] = _identifier(
        data['process_instance_id'], 'process_instance_id')
    if data['priority'] != 'critical' or data['intent'] != 'stop_task':
        raise ValueError('stop broadcast priority/intent mismatch')
    if data['command_text'] != '停止任务':
        raise ValueError('stop broadcast command mismatch')
    data['raw_text'] = _trimmed_string(data['raw_text'], 'raw_text')
    if data['source'] != 'voice_priority_stop':
        raise ValueError('stop broadcast source mismatch')
    attempt = _positive_int(data['attempt'], 'attempt')
    repeat_count = _positive_int(data['repeat_count'], 'repeat_count')
    if attempt > repeat_count:
        raise ValueError('stop broadcast attempt exceeds repeat_count')
    for name in (
            'trigger_wall_time_unix_ns', 'trigger_monotonic_ns',
            'published_wall_time_unix_ns', 'published_monotonic_ns'):
        data[name] = _positive_int(data[name], name)
    data['transcript_to_publish_latency_ns'] = _positive_int(
        data['transcript_to_publish_latency_ns'],
        'transcript_to_publish_latency_ns', allow_zero=True)
    if data['published_monotonic_ns'] < data['trigger_monotonic_ns']:
        raise ValueError('stop broadcast monotonic timestamp moved backwards')
    expected_latency = (
        data['published_monotonic_ns'] - data['trigger_monotonic_ns'])
    if data['transcript_to_publish_latency_ns'] != expected_latency:
        raise ValueError('stop broadcast latency does not match timestamps')
    return data


def stop_ack_payload(
        event_id, process_instance_id, source, state, detail,
        wall_time_unix_ns=None, monotonic_ns=None):
    """Build a diagnostic ACK that never gates or delays stop output."""
    return {
        'schema_version': STOP_ACK_SCHEMA_VERSION,
        'event_id': event_id,
        'process_instance_id': process_instance_id,
        'source': source,
        'state': state,
        'detail': detail,
        'observed_wall_time_unix_ns': (
            time.time_ns() if wall_time_unix_ns is None
            else int(wall_time_unix_ns)),
        'observed_monotonic_ns': (
            time.monotonic_ns() if monotonic_ns is None
            else int(monotonic_ns)),
    }


def parse_stop_ack(payload):
    """Validate one optional downstream stop acknowledgement."""
    data = loads_strict_object(payload, 'stop acknowledgement')
    expected = {
        'schema_version', 'event_id', 'process_instance_id',
        'source', 'state', 'detail',
        'observed_wall_time_unix_ns', 'observed_monotonic_ns'}
    if set(data) != expected:
        raise ValueError('stop acknowledgement fields do not match schema')
    if data['schema_version'] != STOP_ACK_SCHEMA_VERSION:
        raise ValueError('stop acknowledgement version mismatch')
    data['event_id'] = _identifier(data['event_id'], 'event_id')
    data['process_instance_id'] = _identifier(
        data['process_instance_id'], 'process_instance_id')
    data['source'] = _identifier(data['source'], 'source')
    if data['state'] not in {
            'accepted', 'completed', 'observed', 'rejected', 'error'}:
        raise ValueError('unsupported stop acknowledgement state')
    data['detail'] = _trimmed_string(
        data['detail'], 'detail', allow_empty=True)
    data['observed_wall_time_unix_ns'] = _positive_int(
        data['observed_wall_time_unix_ns'], 'observed_wall_time_unix_ns')
    data['observed_monotonic_ns'] = _positive_int(
        data['observed_monotonic_ns'], 'observed_monotonic_ns')
    return data
