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
NAVIGATE_TO_BIN_COMMAND = '到垃圾桶旁边'
INSPECT_BOTTLE_COMMAND = '识别矿泉水瓶'

STOP_PHRASES = (
    '停下', '停下来', '停止', '紧急停止', '立即停止', '马上停止',
    '停住', '别动', '不要动', '先别干了', '别走了',
    '不要这么做了', '你休息', '你给我回来', '先不要这么干了',
    '先回来', '行回来', '放下手头的活',
    '停止任务', '终止任务',
    'stop task', 'emergency stop', 'abort task',
)
CONFIRM_PHRASES = ('确认', '确定', '执行', '可以', '是的', 'confirm', 'yes')
REJECT_PHRASES = (
    '不确认', '不要确认', '不能确认', '无法确认', '还没确认', '尚未确认',
    '无需确认', '先别确认', '确认不了', '我不确定', '还没确定',
    '不要执行', '暂不执行', '不可以', '不是的',
    '不用了', '算了', '否', 'no', 'reject',
)
STATUS_PHRASES = ('报告状态', '任务状态', '现在怎么样', '当前状态', 'status')
PAUSE_PHRASES = ('暂停', '暂停任务', 'pause')
RESUME_PHRASES = ('继续', '继续任务', '恢复任务', 'resume')
RETURN_PHRASES = ('返回', '回去', '返回原点', '回充电桩', 'return', 'go home')
START_GENERIC_PHRASES = ('开始清理', '开始任务', '清理垃圾', '打扫一下')
CANCEL_PHRASES = ('取消', '停止', '终止', 'cancel', 'stop', 'abort')
PICK_ACTION_PHRASES = (
    '捡', '捡起', '拾取', '处理', '清理', '收拾', '收一下', '拿走',
    'pick', 'pick up', 'collect', 'handle',
)
NAVIGATE_TO_BIN_PHRASES = (
    '到垃圾桶旁边去', '到垃圾桶旁边', '去垃圾桶旁边',
)
INSPECT_BOTTLE_PHRASES = (
    '识别瓶子', '识别矿泉水瓶', '识别塑料瓶',
    '看看矿泉水瓶', '看一下矿泉水瓶',
    '检查矿泉水瓶', '找矿泉水瓶', '检测矿泉水瓶',
)

_PROTECTED_STOP_PHRASES = ('别动', '不要动', '先别干了', '别走了')
_COMMAND_PREFIXES = (
    '小莫小莫', '机器人', '请你', '请', '麻烦你', '麻烦',
    '现在', '赶紧',
)
_COMMAND_SUFFIXES = ('吧', '一下', '谢谢')
_NEGATION_MARKERS = (
    '不要', '不用', '不必', '别再', '别', '不许', '无需', '无须',
    '不能', '不想', '不应该', '没必要', '不准', '拒绝', '暂不',
    '尚未', '还没', '没有', '没说',
)
_META_MARKERS = (
    '我说', '他说', '她说', '有人说', '电视里', '刚才那句',
    '如果听到', '假如听到', '如果需要', '假如需要', '如果危险',
    '要是需要', '引用', '转述',
    '重复', '测试', '我教你说', '教你说', '听到',
    '不是命令', '是什么意思', '怎么说', '这句话', '这个词', '讨论',
    '这句是', '这是', '下一句是', '示例命令', '字幕显示', '字幕是', '有人喊道',
    '假设命令', '假设说', '录音中有人', '正在学说', '学说', '请问你会',
    '你会不会', '帮我问', '问他', '我想问', '为什么', '刚刚是不是',
    '不代表', '并非', '我反对', '不同意', '不赞成', '别提', '不要说',
    '别让他', '别让她', '是否',
)
_AMBIGUITY_MARKERS = ('还是', '或者', '是否')
_QUOTE_CHARACTERS = '“”‘’「」『』《》\"'


def normalize_text(text: str) -> str:
    """Normalize whitespace and punctuation while preserving Chinese text."""
    lowered = text.strip().lower().replace('\u3000', ' ')
    return re.sub(r'[，。！？、,.!?;；:\s]+', '', lowered)


def _contains_ascii_phrase(text: str, phrase: str) -> bool:
    words = [re.escape(item) for item in phrase.casefold().split()]
    body = r'\s+'.join(words)
    pattern = r'(?<![a-z0-9_]){}(?![a-z0-9_])'.format(body)
    return re.search(pattern, text.casefold()) is not None


def _contains_phrase(text: str, phrase: str) -> bool:
    if re.search(r'[a-zA-Z]', phrase):
        return _contains_ascii_phrase(text, phrase)
    return normalize_text(phrase) in normalize_text(text)


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    return any(_contains_phrase(text, phrase) for phrase in phrases)


def _strip_command_wrappers(text: str) -> str:
    compact = normalize_text(text)
    changed = True
    while changed and compact:
        changed = False
        for prefix in _COMMAND_PREFIXES:
            normalized = normalize_text(prefix)
            if compact.startswith(normalized):
                compact = compact[len(normalized):]
                changed = True
                break
    changed = True
    while changed and compact:
        changed = False
        for suffix in _COMMAND_SUFFIXES:
            normalized = normalize_text(suffix)
            if compact.endswith(normalized):
                compact = compact[:-len(normalized)]
                changed = True
                break
    return compact


def _is_exact_control(text: str, phrases: Iterable[str]) -> bool:
    core = _strip_command_wrappers(text)
    return any(core == normalize_text(phrase) for phrase in phrases)


def _has_meta_or_quoted_context(raw_text: str) -> bool:
    compact = normalize_text(raw_text)
    if any(character in raw_text for character in _QUOTE_CHARACTERS):
        return True
    if any(marker in compact for marker in _META_MARKERS):
        return True
    lowered = raw_text.casefold()
    return any(re.search(pattern, lowered) for pattern in (
        r'\bignore\s+(?:the\s+)?words?\b',
        r'\b(?:say|said|quote|quoted|test|means)\b',
        r'\b(?:example|shouted|not\s+a\s+command)\b',
    ))


def _has_general_negation(raw_text: str) -> bool:
    compact = normalize_text(raw_text)
    if re.search(
            r'(?:不要|不用|不必|别再|别|不许|无需|无须|不能|不想|'
            r'不应该|没必要|不准|拒绝|暂不)(?:你|机器人|让他|让她|让它)?'
            r'(?:给我)?(?:去|到|识别|检查|检测|找|捡|捡起|处理|清理|触碰|碰|'
            r'轻触|接触|执行|确认|确定|开始)', compact):
        return True
    if re.search(r'(?:尚未|还没)(?:确认|确定|执行|开始)', compact):
        return True
    lowered = raw_text.casefold()
    return re.search(
        r"\b(?:do\s+not|don't|never|not|denied)\b", lowered) is not None


def _has_ambiguous_context(raw_text: str) -> bool:
    compact = normalize_text(raw_text)
    if any(marker in compact for marker in _AMBIGUITY_MARKERS):
        return True
    if compact.endswith(('吗', '么', '呢')):
        return True
    if raw_text.rstrip().endswith(('?', '？')):
        return True
    return _has_meta_or_quoted_context(raw_text)


def is_fail_closed_context(raw_text: str) -> bool:
    """Identify negated, quoted, reported, or ambiguous task language."""
    return _has_general_negation(raw_text) or _has_ambiguous_context(raw_text)


def _has_negated_stop(raw_text: str) -> bool:
    compact = normalize_text(raw_text)
    chinese_pattern = (
        r'(?:不要|别|别再|不许|无需|无须|不用|不必|不能|不需要|'
        r'不想|不应该|没必要|不准|没有要求|没说)'
        r'(?:你|机器人|让他|让她|让它)?(?:立即|马上|紧急)?'
        r'(?:停下(?:来)?|停止(?:任务)?|终止(?:任务)?|停住)'
    )
    if re.search(chinese_pattern, compact):
        return True
    lowered = raw_text.casefold()
    return any(re.search(pattern, lowered) for pattern in (
        r"\b(?:do\s+not|don't|never)\s+(?:stop|abort)\b",
        r'\bnot\s+(?:an?\s+)?(?:emergency\s+)?stop\b',
    ))


def _matches_stop_command(raw_text: str) -> bool:
    core = _strip_command_wrappers(raw_text)
    phrases = {normalize_text(phrase) for phrase in STOP_PHRASES}
    if core in phrases:
        return True
    # Restricted-grammar ASR can emit an urgent command more than once when
    # the speaker repeats it (for example ``停下 停下``). Treat only exact
    # repetitions of the same complete phrase as the same command; ambiguity,
    # quotation, and negation gates still run before this helper.
    if any(core == phrase * repeat_count
           for phrase in phrases
           for repeat_count in (2, 3)):
        return True
    for connector in ('然后', '并且', '接着'):
        if connector in core:
            suffix = _strip_command_wrappers(core.rsplit(connector, 1)[1])
            if suffix in phrases:
                return True
    clauses = re.split(r'[，。！；,;!]+', raw_text)
    if len(clauses) > 1:
        final_clause = _strip_command_wrappers(clauses[-1])
        if final_clause in phrases:
            return True
    return False


def is_priority_stop_text(raw_text: str) -> bool:
    """Return true only for explicit highest-priority stop phrases."""
    if not raw_text.strip() or _has_ambiguous_context(raw_text):
        return False
    core = _strip_command_wrappers(raw_text)
    protected = {normalize_text(item) for item in _PROTECTED_STOP_PHRASES}
    if core in protected:
        return True
    if _has_negated_stop(raw_text):
        return False
    return _matches_stop_command(raw_text)


def _strip_wake_word(text: str, wake_words: Iterable[str]):
    normalized = normalize_text(text)
    for wake_word in wake_words:
        word = normalize_text(wake_word)
        if not word or not normalized.startswith(word):
            continue
        raw = text.strip().lower().replace('\u3000', ' ')
        wake_pattern = r'\s*'.join(
            re.escape(character) for character in word)
        match = re.match(r'^\s*' + wake_pattern, raw)
        if match is None:
            continue
        remainder = raw[match.end():]
        if remainder and remainder[0] not in '，。！？、,.!?;；: \t\r\n':
            return normalized, False
        return normalized[len(word):], True
    return normalized, False


def has_wake_word(text: str, wake_words: Iterable[str]) -> bool:
    """Return whether the complete configured wake word was heard."""
    return _strip_wake_word(text, wake_words)[1]


def parse_command(
        raw_text: str,
        wake_words: Iterable[str] = (),
        require_wake_word: bool = False) -> ParsedIntent:
    """Convert recognized text to a high-level, auditable intent."""
    text, wake_word_found = _strip_wake_word(raw_text, wake_words)
    if not text:
        return ParsedIntent('empty', None, False, 'empty transcript')

    # A stop request is always honored, even when wake-word gating is enabled.
    if is_priority_stop_text(raw_text):
        return ParsedIntent(
            'stop_task', '停止任务', False, 'explicit stop phrase')
    if (
            not _has_general_negation(raw_text)
            and not _has_ambiguous_context(raw_text)
            and _is_exact_control(text, CANCEL_PHRASES)):
        return ParsedIntent(
            'stop_task', '停止任务', False, 'cancel phrase')
    if require_wake_word and not wake_word_found:
        return ParsedIntent('ignored', None, False, 'wake word was not heard')
    if _has_ambiguous_context(raw_text):
        return ParsedIntent(
            'unsupported', None, False,
            'negated, quoted, or ambiguous language')
    if _is_exact_control(text, REJECT_PHRASES):
        return ParsedIntent(
            'reject_confirmation', None, False, 'confirmation rejected')
    if _is_exact_control(text, CONFIRM_PHRASES):
        return ParsedIntent('confirm', None, False, 'confirmation phrase')
    if _has_general_negation(raw_text):
        return ParsedIntent(
            'unsupported', None, False,
            'negated, quoted, or ambiguous language')
    if _is_exact_control(text, STATUS_PHRASES):
        return ParsedIntent('report_status', None, False, 'status request')
    if _is_exact_control(text, PAUSE_PHRASES):
        return ParsedIntent(
            'pause_unsupported', None, False,
            'task manager does not expose pause')
    if _is_exact_control(text, RESUME_PHRASES):
        return ParsedIntent(
            'resume_unsupported', None, False,
            'task manager does not expose resume')
    if _is_exact_control(text, RETURN_PHRASES):
        return ParsedIntent(
            'return_unsupported', None, False,
            'task manager does not expose return navigation')

    candidates = []
    if _contains_any(text, NAVIGATE_TO_BIN_PHRASES):
        candidates.append(ParsedIntent(
            'navigate_to_bin', NAVIGATE_TO_BIN_COMMAND, True,
            'fixed trash-bin waypoint request'))

    if _contains_any(text, INSPECT_BOTTLE_PHRASES):
        candidates.append(ParsedIntent(
            'inspect_bottle', INSPECT_BOTTLE_COMMAND, True,
            'motion-free plastic bottle inspection request'))

    touch_requested = _contains_any(text, TOUCH_PHRASES)
    if touch_requested:
        if _contains_any(text, BOTTLE_PHRASES):
            candidates.append(ParsedIntent(
                'start_touch', TOUCH_COMMAND, True,
                'recognized touch-only plastic bottle request'))
        else:
            return ParsedIntent(
                'unsupported', None, False,
                'touch_only supports plastic_bottle only')

    cleanup_candidates = []
    if _contains_any(text, PICK_ACTION_PHRASES):
        for object_class, command_text, keywords in OBJECT_COMMANDS:
            if _contains_any(text, keywords):
                cleanup_candidates.append(ParsedIntent(
                    'start_cleanup', command_text, True,
                    'recognized object class: ' + object_class))
    if cleanup_candidates:
        candidates.extend(cleanup_candidates)
    elif _contains_any(text, START_GENERIC_PHRASES):
        candidates.append(ParsedIntent(
            'start_cleanup', '捡垃圾', True, 'generic cleanup request'))

    unique_candidates = {
        (candidate.name, candidate.command_text): candidate
        for candidate in candidates
    }
    if len(unique_candidates) > 1:
        return ParsedIntent(
            'unsupported', None, False,
            'multiple actionable intents were heard')
    if len(unique_candidates) == 1:
        return next(iter(unique_candidates.values()))

    return ParsedIntent(
        'unsupported', None, False, 'no command vocabulary match')


def confirmation_prompt(command_text: str) -> str:
    """Create the spoken confirmation question for a normalized command."""
    return '准备执行“{}”。请说确认，或说取消。'.format(command_text)
