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

import time

from std_msgs.msg import String

from limo_cleanup_voice.command_parser import (
    confirmation_prompt,
    normalize_text,
    parse_command,
)
from limo_cleanup_voice.voice_asr_node import (
    DEFAULT_GRAMMAR,
    is_unknown_transcript,
)
from limo_cleanup_voice.voice_dialogue_node import VoiceDialogueNode


def test_normalize_text_removes_punctuation_and_spaces():
    assert normalize_text('  小莫， 捡 塑料瓶！ ') == '小莫捡塑料瓶'


def test_bottle_command_requires_confirmation():
    intent = parse_command('请帮我捡起矿泉水瓶')
    assert intent.name == 'start_cleanup'
    assert intent.command_text == '捡塑料瓶'
    assert intent.requires_confirmation is True


def test_touch_bottle_command_requires_confirmation():
    intent = parse_command('请到目标地点轻触矿泉水瓶')

    assert intent.name == 'start_touch'
    assert intent.command_text == '触碰矿泉水瓶'
    assert intent.requires_confirmation is True


def test_touch_dialogue_enters_confirmation_gate():
    class DialogueProbe:
        require_confirmation = True
        require_wake_word = True
        wake_words = ['小莫', '利莫', '机器人']
        pending_command = None
        pending_deadline = 0.0
        confirmation_timeout_sec = 10.0

        def __init__(self):
            self.responses = []
            self.forwarded = []
            self.intents = []

        def respond(self, text):
            self.responses.append(text)

        def forward_command(self, command_text):
            self.forwarded.append(command_text)

        def publish_intent(self, intent, raw_text, forwarded):
            self.intents.append((intent.name, raw_text, forwarded))

    probe = DialogueProbe()
    message = String()
    message.data = '机器人，碰一下塑料瓶'

    VoiceDialogueNode.transcript_callback(probe, message)

    assert probe.pending_command == '触碰矿泉水瓶'
    assert probe.forwarded == []
    assert any('请说确认' in response for response in probe.responses)
    assert probe.intents == [
        ('start_touch', '机器人，碰一下塑料瓶', False),
    ]


def test_touch_non_bottle_is_not_forwarded():
    intent = parse_command('轻触易拉罐')

    assert intent.name == 'unsupported'
    assert intent.command_text is None


def test_generic_cleanup_maps_to_existing_task_vocabulary():
    intent = parse_command('开始清理')
    assert intent.name == 'start_cleanup'
    assert intent.command_text == '捡垃圾'


def test_stop_is_immediate_and_never_requires_confirmation():
    intent = parse_command('机器人，紧急停止')
    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'
    assert intent.requires_confirmation is False


def test_pause_resume_and_return_are_not_forwarded():
    assert parse_command('暂停任务').name == 'pause_unsupported'
    assert parse_command('继续任务').name == 'resume_unsupported'
    assert parse_command('返回原点').name == 'return_unsupported'


def test_wake_word_can_be_required():
    ignored = parse_command(
        '捡塑料瓶', wake_words=['小莫'], require_wake_word=True)
    accepted = parse_command(
        '小莫，捡塑料瓶', wake_words=['小莫'], require_wake_word=True)
    assert ignored.name == 'ignored'
    assert accepted.name == 'start_cleanup'


def test_emergency_stop_bypasses_wake_word_gate():
    intent = parse_command(
        '紧急停止', wake_words=['小莫'], require_wake_word=True)
    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'


def test_confirmation_and_rejection_are_distinct():
    assert parse_command('确认').name == 'confirm'
    assert parse_command('不确认').name == 'reject_confirmation'


def test_status_and_unsupported_commands():
    assert parse_command('报告状态').name == 'report_status'
    assert parse_command('播放音乐').name == 'unsupported'


def test_confirmation_prompt_contains_canonical_command():
    prompt = confirmation_prompt('捡塑料瓶')
    assert '捡塑料瓶' in prompt
    assert '确认' in prompt


def test_parser_has_no_timing_or_external_side_effects():
    started = time.monotonic()
    parse_command('小莫，请捡塑料瓶', wake_words=['小莫'])
    assert time.monotonic() - started < 0.1


def test_microphone_grammar_uses_complete_wake_word_commands():
    assert '机器人 捡 塑料瓶' in DEFAULT_GRAMMAR
    assert '机器人 碰 一下 塑料瓶' in DEFAULT_GRAMMAR
    assert '小莫 报告 状态' in DEFAULT_GRAMMAR
    assert '机器人' not in DEFAULT_GRAMMAR
    assert '返回' not in DEFAULT_GRAMMAR


def test_vosk_unknown_marker_is_filtered_before_dialogue():
    assert is_unknown_transcript('[unk]') is True
    assert is_unknown_transcript(' <UNK> ') is True
    assert is_unknown_transcript('机器人 捡 塑料瓶') is False
