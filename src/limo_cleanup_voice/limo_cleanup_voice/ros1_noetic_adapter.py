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

"""Pure fail-closed core for the ROS1/Noetic offline mock adapter."""

import threading
import time
from dataclasses import dataclass

from .command_parser import has_wake_word, parse_command
from .ros1_audio_input import (
    Ros1AudioInputConfig,
    build_audio_input_plan,
)
from .semantic_agent import normalize_non_stop_semantics
from .voice_contract import (
    ACCEPTED_ASR_WAKE_WORDS,
    new_event_id,
    parse_stop_ack,
    stop_broadcast_payload,
    validate_identifier,
)


OFFLINE_PROFILE = 'offline_text_mock'
MOCK_TOPICS = {
    'start_cleanup': '/voice_mock/cleanup/natural_language',
    'start_touch': '/voice_mock/cleanup/natural_language',
    'navigate_to_bin': '/voice_mock/cleanup/navigation_intent',
    'inspect_bottle': '/voice_mock/cleanup/perception_intent',
}
PRODUCTION_TOPICS = frozenset({
    '/cleanup/natural_language',
    '/cleanup/navigation_intent',
    '/cleanup/perception_intent',
})
SUCCESS_ACK_STATES = frozenset({'accepted', 'completed', 'observed'})


@dataclass(frozen=True)
class Ros1AdapterConfig:
    """Immutable adapter boundary; production output is never permitted."""

    profile: str = OFFLINE_PROFILE
    require_wake_word: bool = True
    wake_timeout_ns: int = 5_000_000_000
    confirmation_timeout_ns: int = 10_000_000_000
    stop_debounce_ns: int = 750_000_000
    stop_repeat_count: int = 3
    stop_repeat_interval_ns: int = 75_000_000
    stop_ack_timeout_ns: int = 1_500_000_000
    stop_ack_future_wall_tolerance_ns: int = 5_000_000_000
    stop_ack_sources: tuple = ('cleanup_ros1_stop_gate',)
    allow_ros_publish: bool = False
    allow_production_outputs: bool = False

    def validate(self):
        """Reject every profile that could reach a production endpoint."""
        if self.profile != OFFLINE_PROFILE:
            raise ValueError('only offline_text_mock is implemented')
        if self.allow_ros_publish:
            raise ValueError('ROS publishing is disabled in this adapter')
        if self.allow_production_outputs:
            raise ValueError('production outputs are forbidden')
        if self.require_wake_word is not True:
            raise ValueError('require_wake_word must be exactly true')
        for name in (
                'wake_timeout_ns', 'confirmation_timeout_ns',
                'stop_debounce_ns', 'stop_repeat_count',
                'stop_repeat_interval_ns', 'stop_ack_timeout_ns',
                'stop_ack_future_wall_tolerance_ns'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) \
                    or value <= 0:
                raise ValueError('{} must be a positive integer'.format(name))
        if self.stop_ack_sources != ('cleanup_ros1_stop_gate',):
            raise ValueError(
                'stop_ack_sources must be the exact stop-gate owner')
        if self.stop_ack_future_wall_tolerance_ns != 5_000_000_000:
            raise ValueError(
                'stop ACK future wall tolerance must remain 5 seconds')
        return self


@dataclass(frozen=True)
class AdapterDecision:
    """One in-memory decision; it never performs a ROS publication."""

    state: str
    intent: str
    reason: str
    command_text: object = None
    requires_confirmation: bool = False
    mock_output_plan: object = None
    stop_event: object = None
    stop_epoch: int = 0
    actual_publish_count: int = 0
    production_publish_count: int = 0


class Ros1NoeticAdapterCore:
    """Serialize transcript decisions behind confirmation and stop barriers."""

    def __init__(
            self, config=None, process_instance_id=None,
            monotonic_ns=None, wall_time_ns=None, audio_input_config=None):
        self.config = (config or Ros1AdapterConfig()).validate()
        self.audio_input_config = (
            audio_input_config or Ros1AudioInputConfig()).validate()
        selected_process_id = (
            new_event_id('voice-ros1-process')
            if process_instance_id is None else process_instance_id)
        self.process_instance_id = validate_identifier(
            selected_process_id, 'process_instance_id')
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._wall_time_ns = wall_time_ns or time.time_ns
        self._lock = threading.RLock()
        self._wake_deadline_ns = 0
        self._pending = None
        self._stop_epoch = 0
        self._active_stop = None

    @property
    def stop_epoch(self):
        """Return the serialized stop generation for audit tests."""
        with self._lock:
            return self._stop_epoch

    @property
    def has_pending(self):
        """Return whether one ordinary high-level intent awaits confirmation."""
        with self._lock:
            return self._pending is not None

    def plan_audio_input(self, staging_root, basename, duration_sec):
        """Return a reviewed finite capture plan without executing I/O."""
        return build_audio_input_plan(
            staging_root,
            basename,
            duration_sec,
            config=self.audio_input_config,
        )

    def _now(self, supplied):
        return int(self._monotonic_ns() if supplied is None else supplied)

    def _expire(self, now_ns):
        if self._wake_deadline_ns and now_ns > self._wake_deadline_ns:
            self._wake_deadline_ns = 0
        if self._pending and now_ns > self._pending['deadline_ns']:
            self._pending = None

    def _decision(self, state, intent, reason, **values):
        return AdapterDecision(
            state=state,
            intent=intent,
            reason=reason,
            stop_epoch=self._stop_epoch,
            **values
        )

    def _stop(self, raw_text, now_ns):
        self._pending = None
        self._wake_deadline_ns = 0
        active = self._active_stop
        if active and now_ns - active['trigger_monotonic_ns'] < (
                self.config.stop_debounce_ns):
            return self._decision(
                'stop_debounced', 'stop_task',
                'duplicate explicit stop reused the active event',
                stop_event=active,
            )
        self._stop_epoch += 1
        event_id = new_event_id('voice-stop')
        trigger_wall_time_unix_ns = int(self._wall_time_ns())
        attempts = [
            {
                'attempt': attempt,
                'offset_ns': (
                    (attempt - 1) * self.config.stop_repeat_interval_ns),
                'payload': stop_broadcast_payload(
                    event_id=event_id,
                    process_instance_id=self.process_instance_id,
                    raw_text=raw_text,
                    attempt=attempt,
                    repeat_count=self.config.stop_repeat_count,
                    trigger_wall_time_unix_ns=(
                        trigger_wall_time_unix_ns),
                    trigger_monotonic_ns=now_ns,
                    published_wall_time_unix_ns=(
                        trigger_wall_time_unix_ns
                        + (attempt - 1)
                        * self.config.stop_repeat_interval_ns),
                    published_monotonic_ns=(
                        now_ns
                        + (attempt - 1)
                        * self.config.stop_repeat_interval_ns),
                ),
                'actual_published': False,
            }
            for attempt in range(1, self.config.stop_repeat_count + 1)
        ]
        event = {
            'schema_version': 1,
            'process_instance_id': self.process_instance_id,
            'event_id': event_id,
            'raw_text': raw_text.strip(),
            'intent': 'stop_task',
            'priority': 'critical',
            'trigger_monotonic_ns': now_ns,
            'trigger_wall_time_unix_ns': trigger_wall_time_unix_ns,
            'repeat_attempts': attempts,
            'ack_deadline_monotonic_ns': (
                now_ns + self.config.stop_ack_timeout_ns),
            'mock_internal_only': True,
            'actual_publish_count': 0,
        }
        self._active_stop = event
        return self._decision(
            'priority_stop_internal', 'stop_task',
            'explicit stop bypassed wake and semantic agent',
            stop_event=event,
        )

    def process_transcript(self, raw_text, now_ns=None):
        """Process one transcript without ROS, I/O, network, or hardware."""
        now_ns = self._now(now_ns)
        with self._lock:
            self._expire(now_ns)
            semantic = normalize_non_stop_semantics(raw_text)
            if semantic is None:
                return self._stop(raw_text, now_ns)

            wake_active = (
                self._wake_deadline_ns > 0
                and now_ns <= self._wake_deadline_ns)
            intent = parse_command(
                semantic.canonical_text,
                wake_words=ACCEPTED_ASR_WAKE_WORDS,
                require_wake_word=(
                    self.config.require_wake_word
                    and self._pending is None
                    and not wake_active),
            )
            if wake_active and self._pending is None:
                self._wake_deadline_ns = 0

            if intent.name == 'empty':
                if has_wake_word(raw_text, ACCEPTED_ASR_WAKE_WORDS):
                    self._wake_deadline_ns = now_ns + (
                        self.config.wake_timeout_ns)
                    return self._decision(
                        'wake_armed', 'empty', 'one-shot wake window armed')
                return self._decision('idle', 'empty', 'empty transcript')

            if intent.name == 'confirm':
                pending = self._pending
                if pending is None:
                    return self._decision(
                        'idle', 'confirm', 'no pending intent')
                self._pending = None
                if pending['stop_epoch'] != self._stop_epoch:
                    return self._decision(
                        'idle', 'confirm', 'stop epoch changed before commit')
                plan = {
                    'topic': MOCK_TOPICS[pending['intent']],
                    'intent': pending['intent'],
                    'command_text': pending['command_text'],
                    'mock_only': True,
                    'actual_published': False,
                }
                return self._decision(
                    'mock_confirmed', 'confirm',
                    'confirmed high-level intent retained as a mock plan',
                    command_text=pending['command_text'],
                    mock_output_plan=plan,
                )

            if intent.name == 'reject_confirmation' or (
                    intent.name == 'stop_task'
                    and intent.reason == 'cancel phrase'):
                self._pending = None
                self._wake_deadline_ns = 0
                return self._decision(
                    'idle', intent.name,
                    'pending intent or wake window cancelled')

            if intent.name in MOCK_TOPICS:
                self._pending = {
                    'intent': intent.name,
                    'command_text': intent.command_text,
                    'deadline_ns': (
                        now_ns + self.config.confirmation_timeout_ns),
                    'stop_epoch': self._stop_epoch,
                }
                return self._decision(
                    'pending_confirmation', intent.name, intent.reason,
                    command_text=intent.command_text,
                    requires_confirmation=True,
                )

            return self._decision('idle', intent.name, intent.reason)

    def observe_stop_ack(self, payload, received_monotonic_ns=None):
        """Validate a correlated ACK without allowing it to gate STOP."""
        now_ns = self._now(received_monotonic_ns)
        with self._lock:
            active = self._active_stop
            if active is None:
                return False
            try:
                ack = parse_stop_ack(payload)
            except (TypeError, ValueError):
                return False
            if ack['event_id'] != active['event_id']:
                return False
            if ack['process_instance_id'] != self.process_instance_id:
                return False
            if ack['source'] not in self.config.stop_ack_sources:
                return False
            if now_ns > active['ack_deadline_monotonic_ns']:
                return False
            wall_now_ns = int(self._wall_time_ns())
            if ack['observed_wall_time_unix_ns'] > (
                    wall_now_ns
                    + self.config.stop_ack_future_wall_tolerance_ns):
                return False
            if ack['state'] not in SUCCESS_ACK_STATES:
                return False
            active['ack_observed'] = True
            active['ack_received_monotonic_ns'] = now_ns
            return True
