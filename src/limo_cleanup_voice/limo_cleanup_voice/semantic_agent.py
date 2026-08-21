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

"""Bounded semantic normalization for non-stop V2 voice requests."""

from dataclasses import dataclass

from .command_parser import (
    is_fail_closed_context,
    is_priority_stop_text,
    normalize_text,
)
from .voice_contract import WAKE_WORD


@dataclass(frozen=True)
class SemanticCandidate:
    """One untrusted semantic candidate for deterministic validation."""

    raw_text: str
    canonical_text: str
    source: str = 'bounded_rules'


BIN_SEMANTIC_PHRASES = (
    '去桶边等着', '去垃圾桶那里', '去垃圾桶那边',
    '到垃圾桶那里', '到垃圾桶那边', '去桶旁边',
)
BOTTLE_SEMANTIC_PHRASES = (
    '处理一下那个瓶子', '处理那个瓶子', '把那个瓶子收一下',
    '收一下那个瓶子', '清理那个瓶子', '处理一下瓶子',
)
INSPECT_BOTTLE_SEMANTIC_PHRASES = (
    '识别一下那个瓶子', '识别那个瓶子', '看看那个瓶子',
    '检查一下那个瓶子', '找一下矿泉水瓶',
)
SPEAKER_RELATIVE_PHRASES = (
    '靠近我', '过来我这边', '到我这里', '来我这里', '来我身边',
)
USER_LABELED_CLEANUP_PHRASES = (
    # The user explicitly declared that the recording title is the spoken
    # ground truth.  Unrestricted Vosk emits the first phrase twice for that
    # recording, so both exact forms are supervised aliases.  Keep this list
    # exact: substring/fuzzy matching would turn nearby speech into a task.
    '丢垃圾', '丢垃圾丢垃圾',
)
_SEMANTIC_PREFIXES = ('请你', '麻烦你', '你', '帮我')
_SEMANTIC_SUFFIXES = ('吧', '谢谢')


def _matches_exact(text, phrases):
    return any(text == normalize_text(phrase) for phrase in phrases)


def _strip_bounded_wrappers(text):
    stripped = text
    for prefix in _SEMANTIC_PREFIXES:
        normalized_prefix = normalize_text(prefix)
        if stripped.startswith(normalized_prefix):
            stripped = stripped[len(normalized_prefix):]
            break
    for suffix in _SEMANTIC_SUFFIXES:
        normalized_suffix = normalize_text(suffix)
        if stripped.endswith(normalized_suffix):
            stripped = stripped[:-len(normalized_suffix)]
            break
    return stripped


def normalize_non_stop_semantics(raw_text, wake_word=WAKE_WORD):
    """Map bounded natural variants to the existing deterministic grammar."""
    cleaned = raw_text.strip()
    if not cleaned:
        return SemanticCandidate(cleaned, cleaned)
    if is_priority_stop_text(cleaned):
        return None
    if is_fail_closed_context(cleaned):
        # Preserve unsafe/ambiguous language verbatim so the deterministic
        # parser can reject it; semantic normalization may never erase the
        # evidence that makes an utterance fail closed.
        return SemanticCandidate(cleaned, cleaned)

    normalized = normalize_text(cleaned)
    has_wake_word = normalize_text(wake_word) in normalized
    prefix = wake_word + '，' if has_wake_word else ''
    without_wake = normalized.replace(normalize_text(wake_word), '', 1)
    bounded_command = _strip_bounded_wrappers(without_wake)

    if _matches_exact(bounded_command, USER_LABELED_CLEANUP_PHRASES):
        canonical = prefix + '开始清理'
    elif _matches_exact(bounded_command, BIN_SEMANTIC_PHRASES):
        canonical = prefix + '到垃圾桶旁边去'
    elif _matches_exact(bounded_command, INSPECT_BOTTLE_SEMANTIC_PHRASES):
        canonical = prefix + '识别矿泉水瓶'
    elif _matches_exact(bounded_command, BOTTLE_SEMANTIC_PHRASES):
        canonical = prefix + '捡塑料瓶'
    elif _matches_exact(bounded_command, SPEAKER_RELATIVE_PHRASES):
        canonical = prefix + '到这里来'
    else:
        canonical = cleaned
    return SemanticCandidate(cleaned, canonical)
