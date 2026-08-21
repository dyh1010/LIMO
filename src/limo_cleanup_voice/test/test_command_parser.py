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

import pytest
from std_msgs.msg import String

from limo_cleanup_voice.command_parser import (
    confirmation_prompt,
    is_priority_stop_text,
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
        expire_pending_command = VoiceDialogueNode.expire_pending_command
        clear_pending_command = VoiceDialogueNode.clear_pending_command
        require_confirmation = True
        require_wake_word = True
        wake_words = ['小莫小莫']
        pending_command = None
        pending_intent_name = None
        pending_raw_text = None
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
    message.data = '小莫小莫，碰一下塑料瓶'

    VoiceDialogueNode.transcript_callback(probe, message)

    assert probe.pending_command == '触碰矿泉水瓶'
    assert probe.forwarded == []
    assert any('请说确认' in response for response in probe.responses)
    assert probe.intents == [
        ('start_touch', '小莫小莫，碰一下塑料瓶', False),
    ]


def test_touch_non_bottle_is_not_forwarded():
    intent = parse_command('轻触易拉罐')

    assert intent.name == 'unsupported'
    assert intent.command_text is None


def test_generic_cleanup_maps_to_existing_task_vocabulary():
    intent = parse_command('开始清理')
    assert intent.name == 'start_cleanup'
    assert intent.command_text == '捡垃圾'


def test_simple_object_vocabulary_recognizes_supported_classes():
    bottle = parse_command('小莫小莫，捡矿泉水瓶')
    can = parse_command('小莫小莫，捡易拉罐')
    paper_box = parse_command('小莫小莫，捡纸盒')

    assert bottle.command_text == '捡塑料瓶'
    assert can.command_text == '捡易拉罐'
    assert paper_box.command_text == '捡纸盒'


def test_bottle_spoken_alias_keeps_existing_canonical_targets():
    cleanup = parse_command(
        '小莫小莫，捡瓶子',
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )
    inspection = parse_command(
        '小莫小莫，识别瓶子',
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )

    assert cleanup.name == 'start_cleanup'
    assert cleanup.command_text == '捡塑料瓶'
    assert cleanup.requires_confirmation is True
    assert inspection.name == 'inspect_bottle'
    assert inspection.command_text == '识别矿泉水瓶'
    assert inspection.requires_confirmation is True


@pytest.mark.parametrize('text', (
    '捡瓶子',
    '小莫小莫，瓶子',
    '小莫小莫，捡瓶盖',
    '小莫小莫，识别瓶装水',
    '小莫小莫，不要捡瓶子',
))
def test_bottle_alias_never_bypasses_wake_action_or_negation_gate(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name in {'ignored', 'unsupported', 'reject_confirmation'}
    assert intent.command_text is None
    assert intent.requires_confirmation is False


def test_stop_is_immediate_and_never_requires_confirmation():
    intent = parse_command('机器人，紧急停止')
    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'
    assert intent.requires_confirmation is False


def test_repeated_direct_stop_from_asr_is_still_immediate():
    intent = parse_command(
        '停下 停下', wake_words=['小莫小莫'], require_wake_word=True)

    assert is_priority_stop_text('停下 停下') is True
    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'
    assert intent.requires_confirmation is False


@pytest.mark.parametrize('text', (
    '不要这么做了',
    '你休息一下吧',
    '你给我回来',
    '先不要这么干了',
    '先回来吧',
    '放下手头的活吧',
))
def test_user_recorded_natural_stop_is_immediate(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert is_priority_stop_text(text) is True
    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'
    assert intent.requires_confirmation is False


@pytest.mark.parametrize('text', (
    '我说“不要这么做了”',
    '这句是你休息一下吧',
    '有人说你给我回来',
    '字幕显示先不要这么干了',
    '是否先回来吧',
    '下一句是放下手头的活吧',
))
def test_reported_or_ambiguous_natural_stop_is_fail_closed(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert is_priority_stop_text(text) is False
    assert intent.name in {'ignored', 'unsupported'}
    assert intent.command_text is None


def test_observed_vosk_alias_for_xian_huilai_is_exact_and_fail_closed():
    direct = parse_command(
        '行 回来 吧', wake_words=['小莫小莫'], require_wake_word=True)
    reported = parse_command(
        '这句是行回来吧',
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )
    negated = parse_command(
        '不行回来吧',
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )

    assert direct.name == 'stop_task'
    assert direct.requires_confirmation is False
    assert reported.name in {'ignored', 'unsupported'}
    assert negated.name in {'ignored', 'unsupported'}


@pytest.mark.parametrize('text', (
    '别的不说小莫捡起瓶子来是真快',
    '呃那个谁让小莫把垃圾丢一下吧',
    '没有小莫的话我们丢垃圾的活该怎么办呀',
    '你看这个小莫',
    '我觉得目前来说小莫应该做不到这样的事',
    '现在小莫的功能已经很强大了',
    '小莫的发展前景不错',
    '小莫去哪里了你有看到他吗',
    '这地上的瓶子还得小莫来捡',
    '别管那个瓶子',
    '别捡瓶子',
    '不要管地上的瓶子了',
    '不要停下',
    '不用去垃圾桶',
    '你不用捡垃圾了',
    '你不用去了',
    '你手上的工作不用再做了',
))
def test_user_recorded_related_or_negated_text_stays_ignored(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert is_priority_stop_text(text) is False
    assert intent.name == 'ignored'
    assert intent.command_text is None
    assert intent.requires_confirmation is False


def test_natural_stop_exactness_robustness_matrix():
    phrases = (
        '不要这么做了',
        '你休息一下吧',
        '你给我回来',
        '先不要这么干了',
        '先回来吧',
        '放下手头的活吧',
        '行回来吧',
    )
    direct_templates = (
        '{}',
        '机器人，{}',
        '请你{}',
        '现在{}',
    )
    rejected_templates = (
        '我说“{}”',
        '这句是{}',
        '有人说{}',
        '请不要说{}',
        '{}是什么意思',
        '是否{}',
        '我觉得{}很奇怪',
        '{}以后再讨论',
        '不执行{}',
    )
    direct_count = 0
    rejected_count = 0
    for phrase in phrases:
        for template in direct_templates:
            text = template.format(phrase)
            intent = parse_command(
                text,
                wake_words=['小莫小莫'],
                require_wake_word=True,
            )
            assert is_priority_stop_text(text) is True
            assert intent.name == 'stop_task'
            assert intent.requires_confirmation is False
            direct_count += 1
        for template in rejected_templates:
            text = template.format(phrase)
            intent = parse_command(
                text,
                wake_words=['小莫小莫'],
                require_wake_word=True,
            )
            assert is_priority_stop_text(text) is False
            assert intent.name in {'ignored', 'unsupported'}
            assert intent.command_text is None
            rejected_count += 1

    assert direct_count == 28
    assert rejected_count == 63


def test_pause_resume_and_return_are_not_forwarded():
    assert parse_command('暂停任务').name == 'pause_unsupported'
    assert parse_command('继续任务').name == 'resume_unsupported'
    assert parse_command('返回原点').name == 'return_unsupported'


def test_wake_word_can_be_required():
    ignored = parse_command(
        '小莫，捡塑料瓶', wake_words=['小莫小莫'], require_wake_word=True)
    accepted = parse_command(
        '小莫小莫，捡塑料瓶',
        wake_words=['小莫小莫'], require_wake_word=True)
    assert ignored.name == 'ignored'
    assert accepted.name == 'start_cleanup'


def test_spaced_asr_wake_word_prefix_is_accepted():
    intent = parse_command(
        '小莫 小莫 捡 矿泉水 瓶',
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )

    assert intent.name == 'start_cleanup'


@pytest.mark.parametrize('text', (
    '小莫小莫斯科，捡矿泉水瓶',
    '捡矿泉水瓶，小莫小莫',
    '电视播放小莫小莫捡矿泉水瓶',
    '别人喊小莫小莫捡矿泉水瓶',
    '叫做小莫小莫的机器人捡矿泉水瓶',
    '请不要说小莫小莫然后捡矿泉水瓶',
    '这是小莫小莫捡矿泉水瓶的例句',
))
def test_wake_word_must_be_a_command_prefix(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name == 'ignored'
    assert intent.command_text is None


def test_emergency_stop_bypasses_wake_word_gate():
    intent = parse_command(
        '紧急停止', wake_words=['小莫小莫'], require_wake_word=True)
    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'


def test_cancel_bypasses_wake_word_gate():
    intent = parse_command(
        '取消', wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name == 'stop_task'
    assert intent.reason == 'cancel phrase'


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
    parse_command('小莫小莫，请捡塑料瓶', wake_words=['小莫小莫'])
    assert time.monotonic() - started < 0.1


def test_microphone_grammar_uses_complete_wake_word_commands():
    assert '小莫 小莫 捡 塑料瓶' in DEFAULT_GRAMMAR
    assert '小莫 小莫 捡 瓶子' in DEFAULT_GRAMMAR
    assert '小莫 小莫 识别 瓶子' in DEFAULT_GRAMMAR
    assert not any('矿泉水瓶' in phrase for phrase in DEFAULT_GRAMMAR)
    assert not any('矿泉水 瓶' in phrase for phrase in DEFAULT_GRAMMAR)
    assert '小莫 小莫 碰 一下 塑料瓶' in DEFAULT_GRAMMAR
    assert '小莫 小莫 到 垃圾桶 旁边 去' in DEFAULT_GRAMMAR
    assert '小莫' not in DEFAULT_GRAMMAR
    assert '机器人 捡 塑料瓶' not in DEFAULT_GRAMMAR
    assert '返回' not in DEFAULT_GRAMMAR


def test_vosk_unknown_marker_is_filtered_before_dialogue():
    assert is_unknown_transcript('[unk]') is True
    assert is_unknown_transcript(' <UNK> ') is True
    assert is_unknown_transcript('小莫 小莫 捡 塑料瓶') is False


def test_stop_phrase_has_priority_over_navigation_words():
    intent = parse_command(
        '小莫小莫，到垃圾桶旁边去然后停下',
        wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name == 'stop_task'
    assert intent.command_text == '停止任务'


def test_navigation_intents_require_confirmation():
    trash_bin = parse_command('小莫小莫，到垃圾桶旁边去')

    assert trash_bin.name == 'navigate_to_bin'
    assert trash_bin.command_text == '到垃圾桶旁边'
    assert trash_bin.requires_confirmation is True


def test_bottle_inspection_is_motion_free_and_requires_confirmation():
    intent = parse_command('小莫小莫，识别矿泉水瓶')

    assert intent.name == 'inspect_bottle'
    assert intent.command_text == '识别矿泉水瓶'
    assert intent.requires_confirmation is True


def test_speaker_relative_navigation_is_not_supported():
    intent = parse_command('小莫小莫，到这里来')

    assert intent.name == 'unsupported'
    assert intent.command_text is None


@pytest.mark.parametrize('text', (
    '不要停下',
    '别停下来',
    '请不要停止',
    '不需要紧急停止',
    '没有要求立即停止',
    '我没说停下',
    '刚才那句停下不是命令',
    '如果听到停下不要执行',
    '不要停止任务',
    '无需终止任务',
    'do not stop task',
    'not an emergency stop',
    'ignore the words abort task',
    'nonstop task commentary',
    '我不想你停下',
    '不应该停下',
    '没必要停下',
    '不准停下',
    '我正在学说停下',
    '请问你会停下',
    '是否停下',
    '别让他停下',
    '下一句是，停下',
    '示例命令，停下',
    '字幕显示，停下',
    '有人喊道，停下',
    '假设命令为，停下',
    '停下？',
    'this is an example, stop task',
    'someone shouted, stop task',
    'not a command, stop task',
    'stop task?',
))
def test_negated_or_quoted_stop_does_not_trigger_priority_path(text):
    """Stop is urgent, but a negated/quoted token is not a stop command."""
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert is_priority_stop_text(text) is False
    assert intent.name in {'ignored', 'unsupported', 'reject_confirmation'}


@pytest.mark.parametrize('text', (
    '不要确认',
    '不能确认',
    '无法确认',
    '还没确认',
    '尚未确认',
    '无需确认',
    '先别确认',
    '确认不了',
    '我不确定',
    '还没确定',
    '不要执行',
    '暂不执行',
    '不可以',
    '不是的',
    'confirmation denied',
))
def test_negated_or_uncertain_reply_never_confirms(text):
    intent = parse_command(text)

    assert intent.name in {'reject_confirmation', 'unsupported'}
    assert intent.name != 'confirm'


@pytest.mark.parametrize('text', (
    '小莫小莫，不要到垃圾桶旁边去',
    '小莫小莫，不用去垃圾桶旁边',
    '小莫小莫，不要识别矿泉水瓶',
    '小莫小莫，不必检查矿泉水瓶',
    '小莫小莫，不要捡矿泉水瓶',
    '小莫小莫，不用处理塑料瓶',
    '小莫小莫，别触碰矿泉水瓶',
))
def test_negated_task_request_fails_closed(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name in {'reject_confirmation', 'unsupported'}
    assert intent.command_text is None
    assert intent.requires_confirmation is False


@pytest.mark.parametrize('text', (
    '小莫小莫，我不想你到垃圾桶旁边去',
    '小莫小莫，不应该到垃圾桶旁边去',
    '小莫小莫，没必要识别矿泉水瓶',
    '小莫小莫，我正在学说到垃圾桶旁边去',
    '小莫小莫，请问你会到垃圾桶旁边去',
    '小莫小莫，是否捡矿泉水瓶',
    '小莫小莫，别让他捡矿泉水瓶',
    '小莫小莫，帮我问他到垃圾桶旁边去',
    '小莫小莫，如果需要就到垃圾桶旁边去',
    '小莫小莫，我教你说到垃圾桶旁边去',
    '小莫小莫，听到识别矿泉水瓶会怎样',
    '小莫小莫，这句是到垃圾桶旁边去',
    '小莫小莫，要是需要就到垃圾桶旁边去',
    '小莫小莫，如果危险就捡矿泉水瓶',
    '小莫小莫，我想问你能否到垃圾桶旁边去',
    '小莫小莫，你为什么识别矿泉水瓶',
    '小莫小莫，你刚刚是不是捡矿泉水瓶',
    '小莫小莫，这不代表捡矿泉水瓶',
    '小莫小莫，并非要你到垃圾桶旁边去',
    '小莫小莫，千万不要给我捡矿泉水瓶',
))
def test_reported_or_indirect_task_request_fails_closed(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name == 'unsupported'
    assert intent.command_text is None
    assert intent.requires_confirmation is False


@pytest.mark.parametrize('text', (
    '小莫小莫，到垃圾桶旁边还是识别矿泉水瓶',
    '小莫小莫，捡矿泉水瓶还是不要捡',
    '小莫小莫，可以去垃圾桶旁边吗',
    '小莫小莫，我说确认了吗',
    '小莫小莫，电视里有人说执行',
))
def test_ambiguous_or_metalinguistic_utterance_fails_closed(text):
    intent = parse_command(
        text, wake_words=['小莫小莫'], require_wake_word=True)

    assert intent.name == 'unsupported'
    assert intent.command_text is None


@pytest.mark.parametrize('text', (
    '确认？', '执行？', '可以？', '是的？',
    'confirm?', 'yes?',
))
def test_question_form_never_confirms(text):
    assert parse_command(text).name != 'confirm'


def test_english_stop_substring_is_not_a_cancel_command():
    intent = parse_command(
        'stopping task report',
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )

    assert intent.name == 'ignored'
