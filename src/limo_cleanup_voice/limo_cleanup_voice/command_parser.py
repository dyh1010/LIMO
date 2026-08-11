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

"""Deterministic parsing for the safety-gated voice command vocabulary."""

import re
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class ParsedIntent:
    """A parsed high-level intent that never contains motion commands."""

    name: str
    command_text: Optional[str]
    requires_confirmation: bool
    reason: str


OBJECT_COMMANDS = (
    (
        'plastic_bottle',
        '捡塑料瓶',
        ('塑料瓶', '矿泉水瓶', '饮料瓶', '瓶子', 'plastic bottle', 'bottle'),
    ),
    ('can', '捡易拉罐', ('易拉罐', '罐子', 'can')),
    ('paper_box', '捡纸盒', ('纸盒', '纸箱', '纸板', 'carton', 'paper box')),
    ('generic_waste', '捡垃圾', ('垃圾', '废物', 'trash', 'garbage', 'waste')),
)

TOUCH_PHRASES = ('触碰', '碰一下', '轻触', '接触', 'touch', 'tap')
BOTTLE_PHRASES = OBJECT_COMMANDS[0][2]
TOUCH_COMMAND = '触碰矿泉水瓶'

STOP_PHRASES = (
    '紧急停止', '立即停止', '马上停止', '停止任务', '终止任务',
    'stop task', 'emergency stop', 'abort task',
)
CONFIRM_PHRASES = ('确认', '确定', '执行', '可以', '是的', 'confirm', 'yes')
REJECT_PHRASES = ('不确认', '不用了', '算了', '否', 'no', 'reject')
STATUS_PHRASES = ('报告状态', '任务状态', '现在怎么样', '当前状态', 'status')
PAUSE_PHRASES = ('暂停', '暂停任务', 'pause')
RESUME_PHRASES = ('继续', '继续任务', '恢复任务', 'resume')
RETURN_PHRASES = ('返回', '回去', '返回原点', '回充电桩', 'return', 'go home')
START_GENERIC_PHRASES = ('开始清理', '开始任务', '清理垃圾', '打扫一下')
CANCEL_PHRASES = ('取消', '停止', '终止', 'cancel', 'stop', 'abort')


def normalize_text(text: str) -> str:
    """Normalize whitespace and punctuation while preserving Chinese text."""
    lowered = text.strip().lower().replace('\u3000', ' ')
    return re.sub(r'[，。！？、,.!?;；:\s]+', '', lowered)


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    return any(normalize_text(phrase) in text for phrase in phrases)


def _strip_wake_word(text: str, wake_words: Iterable[str]):
    normalized = normalize_text(text)
    for wake_word in wake_words:
        word = normalize_text(wake_word)
        if word and word in normalized:
            return normalized.replace(word, '', 1), True
    return normalized, False


def parse_command(
        raw_text: str,
        wake_words: Iterable[str] = (),
        require_wake_word: bool = False) -> ParsedIntent:
    """Convert recognized text to a high-level, auditable intent."""
    text, wake_word_found = _strip_wake_word(raw_text, wake_words)
    if not text:
        return ParsedIntent('empty', None, False, 'empty transcript')

    # A stop request is always honored, even when wake-word gating is enabled.
    if _contains_any(text, STOP_PHRASES):
        return ParsedIntent(
            'stop_task', '停止任务', False, 'explicit stop phrase')
    if require_wake_word and not wake_word_found:
        return ParsedIntent('ignored', None, False, 'wake word was not heard')
    if _contains_any(text, REJECT_PHRASES):
        return ParsedIntent(
            'reject_confirmation', None, False, 'confirmation rejected')
    if _contains_any(text, CONFIRM_PHRASES):
        return ParsedIntent('confirm', None, False, 'confirmation phrase')
    if _contains_any(text, STATUS_PHRASES):
        return ParsedIntent('report_status', None, False, 'status request')
    if _contains_any(text, PAUSE_PHRASES):
        return ParsedIntent(
            'pause_unsupported', None, False,
            'task manager does not expose pause')
    if _contains_any(text, RESUME_PHRASES):
        return ParsedIntent(
            'resume_unsupported', None, False,
            'task manager does not expose resume')
    if _contains_any(text, RETURN_PHRASES):
        return ParsedIntent(
            'return_unsupported', None, False,
            'task manager does not expose return navigation')

    if _contains_any(text, CANCEL_PHRASES):
        return ParsedIntent(
            'stop_task', '停止任务', False, 'cancel phrase')

    if _contains_any(text, TOUCH_PHRASES):
        if _contains_any(text, BOTTLE_PHRASES):
            return ParsedIntent(
                'start_touch', TOUCH_COMMAND, True,
                'recognized touch-only plastic bottle request')
        return ParsedIntent(
            'unsupported', None, False,
            'touch_only supports plastic_bottle only')

    for object_class, command_text, keywords in OBJECT_COMMANDS:
        if _contains_any(text, keywords):
            return ParsedIntent(
                'start_cleanup', command_text, True,
                'recognized object class: ' + object_class)

    if _contains_any(text, START_GENERIC_PHRASES):
        return ParsedIntent(
            'start_cleanup', '捡垃圾', True, 'generic cleanup request')

    return ParsedIntent(
        'unsupported', None, False, 'no command vocabulary match')


def confirmation_prompt(command_text: str) -> str:
    """Create the spoken confirmation question for a normalized command."""
    return '准备执行“{}”。请说确认，或说取消。'.format(command_text)
