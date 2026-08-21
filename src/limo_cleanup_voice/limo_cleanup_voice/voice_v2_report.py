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

"""LEGACY_ROS2_OFFLINE_ONLY callback report using import stubs only."""

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from std_msgs.msg import String

from .voice_dialogue_node import VoiceDialogueNode


NEGATIVE_TRANSCRIPTS = (
    '今天天气不错',
    '播放音乐',
    '到垃圾桶旁边去',
    '到这里来',
    '小莫，去垃圾桶旁边',
    '继续',
    '返回原点',
    '确认',
)


class _DialogueProbe:
    expire_pending_command = VoiceDialogueNode.expire_pending_command
    clear_pending_command = VoiceDialogueNode.clear_pending_command
    handle_confirmation = VoiceDialogueNode.handle_confirmation
    forward_confirmed_intent = VoiceDialogueNode.forward_confirmed_intent
    forward_navigation_intent = VoiceDialogueNode.forward_navigation_intent
    publish_navigation_stop = VoiceDialogueNode.publish_navigation_stop

    def __init__(self):
        self.require_confirmation = True
        self.require_wake_word = True
        self.wake_words = ['小莫小莫']
        self.trash_bin_waypoint = 'trash_bin_staging'
        self.confirmation_timeout_sec = 10.0
        self.pending_command = None
        self.pending_intent_name = None
        self.pending_raw_text = None
        self.pending_deadline = 0.0
        self.responses = []
        self.forwarded = []
        self.intents = []
        self.navigation_requests = []
        self.navigation_publisher = SimpleNamespace(
            publish=lambda message: self.navigation_requests.append(
                json.loads(message.data)))

    def respond(self, text):
        self.responses.append(text)

    def forward_command(self, command_text):
        self.forwarded.append(command_text)

    def publish_intent(self, intent, raw_text, forwarded):
        self.publish_raw_intent(
            intent.name, raw_text, intent.command_text,
            forwarded, intent.reason)

    def publish_raw_intent(
            self, name, raw_text, command_text, forwarded, reason):
        self.intents.append({
            'intent': name,
            'raw_text': raw_text,
            'command_text': command_text,
            'forwarded': bool(forwarded),
            'reason': reason,
        })


def _send(probe, text):
    message = String()
    message.data = text
    VoiceDialogueNode.transcript_callback(probe, message)


def _scenario_checks():
    wake = _DialogueProbe()
    _send(wake, '小莫小莫，捡塑料瓶')
    wake_ok = wake.pending_command == '捡塑料瓶' and not wake.forwarded

    stop = _DialogueProbe()
    _send(stop, '停下')
    stop_ok = (
        stop.forwarded == ['停止任务']
        and stop.navigation_requests == [{
            'action': 'cancel_navigation',
            'request_safe_stop': True,
        }]
    )

    waypoint = _DialogueProbe()
    _send(waypoint, '小莫小莫，到垃圾桶旁边去')
    before_confirmation = not waypoint.navigation_requests
    _send(waypoint, '确认')
    waypoint_ok = before_confirmation and waypoint.navigation_requests == [{
        'action': 'navigate_to_waypoint',
        'target_id': 'trash_bin_staging',
        'target_source': 'fixed_map_waypoint',
    }]

    unsupported = _DialogueProbe()
    _send(unsupported, '小莫小莫，到这里来')
    unsupported_ok = (
        not unsupported.forwarded
        and not unsupported.navigation_requests
        and unsupported.intents[-1]['intent'] == 'unsupported'
    )

    expired = _DialogueProbe()
    _send(expired, '小莫小莫，捡塑料瓶')
    expired.pending_deadline = time.monotonic() - 1.0
    _send(expired, '确认')
    timeout_ok = (
        not expired.forwarded
        and expired.pending_command is None
        and expired.intents[-1]['reason'] == 'confirmation expired'
    )

    false_activation_count = 0
    for transcript in NEGATIVE_TRANSCRIPTS:
        negative = _DialogueProbe()
        _send(negative, transcript)
        if negative.forwarded or negative.navigation_requests:
            false_activation_count += 1

    return {
        'wake_word_gate': wake_ok,
        'stop_highest_priority': stop_ok,
        'trash_bin_confirmation': waypoint_ok,
        'speaker_relative_unsupported': unsupported_ok,
        'confirmation_timeout_blocks': timeout_ok,
        'negative_case_count': len(NEGATIVE_TRANSCRIPTS),
        'false_activation_count': false_activation_count,
    }


def generate_report(iterations=100):
    """Repeat deterministic scenarios and aggregate pass-rate statistics."""
    if iterations <= 0:
        raise ValueError('iterations must be positive')
    counters = {
        'wake_word_gate': 0,
        'stop_highest_priority': 0,
        'trash_bin_confirmation': 0,
        'speaker_relative_unsupported': 0,
        'confirmation_timeout_blocks': 0,
    }
    negative_cases = 0
    false_activations = 0
    for _ in range(iterations):
        checks = _scenario_checks()
        for name in counters:
            counters[name] += int(checks[name])
        negative_cases += checks['negative_case_count']
        false_activations += checks['false_activation_count']

    scenario_rates = {
        name: count / float(iterations)
        for name, count in counters.items()
    }
    status = 'PASS' if (
        all(count == iterations for count in counters.values())
        and false_activations == 0
    ) else 'FAIL'
    return {
        'status': status,
        'mode': 'deterministic_no_ros_no_hardware',
        'iterations': iterations,
        'scenario_pass_counts': counters,
        'scenario_pass_rates': scenario_rates,
        'negative_case_count': negative_cases,
        'false_activation_count': false_activations,
        'false_activation_rate': (
            false_activations / float(negative_cases)
            if negative_cases else 0.0),
    }


def main(args=None):
    """Write repeatable V2 behavior statistics as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--json-output')
    parsed = parser.parse_args(args)
    report = generate_report(parsed.iterations)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if parsed.json_output:
        Path(parsed.json_output).write_text(
            rendered + '\n', encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
