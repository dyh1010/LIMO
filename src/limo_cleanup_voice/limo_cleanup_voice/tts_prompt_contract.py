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

"""Strict, ROS-free contract for finite Chinese dialogue prompt playback."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import wave


PROMPT_TEXTS = {
    'ready': '你好，我是小莫。语音输出已经连接成功。',
    'wake_ack': '我在，请说指令。',
    'not_understood': '没有听清，请再说一次。',
    'confirm_bin': '你要让我到垃圾桶旁边去吗？请说确认或者取消。',
    'confirm_bottle': '你要让我识别并处理瓶子吗？请说确认或者取消。',
    'cancelled': '已取消，不会执行任务。',
    'mock_confirmed': (
        '已确认。当前为安全测试模式，'
        '不会向底盘或机械臂发送命令。'
    ),
    'stop_ack': (
        '已收到停止指令。'
        '软件停止不能替代物理急停。'
    ),
    'unsupported': '暂不支持这条语音指令，本次不会执行。',
    'confirmation_timeout': '确认已超时，请重新下达指令。',
}

HDMI_SINK = 'alsa_output.platform-3510000.hda.hdmi-stereo'
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_FILENAME = re.compile(r'^[a-z][a-z0-9_]*\.wav$')
_TOP_LEVEL_KEYS = {
    'schema_version', 'mode', 'actual_control_publish_count', 'prompts',
}
_PROMPT_KEYS = {
    'id', 'text', 'filename', 'sha256', 'channels',
    'sample_width_bytes', 'sample_rate_hz', 'frames', 'duration_s',
    'compression',
}


class PromptContractError(ValueError):
    """Raised when prompt evidence or a requested playback is unsafe."""


@dataclass(frozen=True)
class PlaybackPlan:
    """Verified finite playback request with no construction side effects."""

    prompt_id: str
    text: str
    asset_path: str
    sha256: str
    duration_s: float
    argv: tuple
    actual_control_publish_count: int = 0


def _require_exact_type(value, expected_type, label):
    if type(value) is not expected_type:
        raise PromptContractError('{} has invalid type'.format(label))


def validate_prompt_manifest(manifest):
    """Validate a complete create-only manifest without reading files."""
    _require_exact_type(manifest, dict, 'manifest')
    if set(manifest) != _TOP_LEVEL_KEYS:
        raise PromptContractError('manifest keys do not match strict schema')
    if manifest['schema_version'] != 1:
        raise PromptContractError('unsupported prompt schema version')
    if manifest['mode'] != 'finite_dialogue_audio_no_control':
        raise PromptContractError('prompt manifest mode is not fail-closed')
    if manifest['actual_control_publish_count'] != 0:
        raise PromptContractError('prompt manifest may not publish control')
    _require_exact_type(manifest['prompts'], list, 'prompts')

    by_id = {}
    filenames = set()
    for index, record in enumerate(manifest['prompts']):
        label = 'prompts[{}]'.format(index)
        _require_exact_type(record, dict, label)
        if set(record) != _PROMPT_KEYS:
            raise PromptContractError('{} keys do not match schema'.format(
                label))
        prompt_id = record['id']
        _require_exact_type(prompt_id, str, label + '.id')
        if prompt_id not in PROMPT_TEXTS or prompt_id in by_id:
            raise PromptContractError('{} has unknown or duplicate id'.format(
                label))
        if record['text'] != PROMPT_TEXTS[prompt_id]:
            raise PromptContractError('{} text differs from contract'.format(
                label))
        filename = record['filename']
        if type(filename) is not str or not _FILENAME.fullmatch(filename):
            raise PromptContractError('{} filename is unsafe'.format(label))
        if filename in filenames:
            raise PromptContractError('duplicate prompt filename')
        filenames.add(filename)
        digest = record['sha256']
        if type(digest) is not str or not _SHA256.fullmatch(digest):
            raise PromptContractError('{} sha256 is invalid'.format(label))
        for key in ('channels', 'sample_width_bytes', 'sample_rate_hz',
                    'frames'):
            _require_exact_type(record[key], int, label + '.' + key)
        if record['channels'] != 1 or record['sample_width_bytes'] != 2:
            raise PromptContractError('{} must be 16-bit mono'.format(label))
        if not 8000 <= record['sample_rate_hz'] <= 48000:
            raise PromptContractError(
                '{} sample rate is invalid'.format(label))
        if record['frames'] <= 0:
            raise PromptContractError('{} is empty'.format(label))
        if type(record['duration_s']) not in (int, float) \
                or not 0.1 <= record['duration_s'] <= 15.0:
            raise PromptContractError('{} duration is unsafe'.format(label))
        if record['compression'] != 'NONE':
            raise PromptContractError('{} is not PCM'.format(label))
        by_id[prompt_id] = record

    if set(by_id) != set(PROMPT_TEXTS):
        raise PromptContractError('prompt manifest is incomplete')
    return by_id


def prompt_id_for_response(text):
    """Return an exact response id; unknown or normalized text is rejected."""
    _require_exact_type(text, str, 'response text')
    matches = [prompt_id for prompt_id, expected in PROMPT_TEXTS.items()
               if text == expected]
    if len(matches) != 1:
        raise PromptContractError('response text is not an exact safe prompt')
    return matches[0]


def build_prompt_manifest(asset_root):
    """Inspect the exact prompt set and build a deterministic manifest."""
    root = Path(asset_root).resolve(strict=True)
    if not root.is_dir():
        raise PromptContractError('asset root is not a directory')
    prompts = []
    for prompt_id, text in PROMPT_TEXTS.items():
        filename = '{}.wav'.format(prompt_id)
        asset = (root / filename).resolve(strict=True)
        if asset.parent != root or not asset.is_file():
            raise PromptContractError('prompt asset is missing or unsafe')
        try:
            with wave.open(str(asset), 'rb') as audio:
                channels = audio.getnchannels()
                sample_width = audio.getsampwidth()
                sample_rate = audio.getframerate()
                frames = audio.getnframes()
                compression = audio.getcomptype()
        except (EOFError, wave.Error) as error:
            raise PromptContractError('prompt WAV is invalid') from error
        prompts.append({
            'id': prompt_id,
            'text': text,
            'filename': filename,
            'sha256': hashlib.sha256(asset.read_bytes()).hexdigest(),
            'channels': channels,
            'sample_width_bytes': sample_width,
            'sample_rate_hz': sample_rate,
            'frames': frames,
            'duration_s': round(frames / sample_rate, 6),
            'compression': compression,
        })
    manifest = {
        'schema_version': 1,
        'mode': 'finite_dialogue_audio_no_control',
        'actual_control_publish_count': 0,
        'prompts': prompts,
    }
    validate_prompt_manifest(manifest)
    return manifest


def write_manifest_create_only(manifest, output_path):
    """Write one validated manifest without overwriting existing evidence."""
    validate_prompt_manifest(manifest)
    output = Path(output_path)
    if output.name != 'manifest.json':
        raise PromptContractError('manifest output must be manifest.json')
    payload = (json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    try:
        descriptor = os.open(
            str(output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise PromptContractError('manifest output already exists') from error
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(payload)
    except Exception:
        try:
            output.unlink()
        except OSError:
            pass
        raise
    return hashlib.sha256(output.read_bytes()).hexdigest()


def verified_playback_plan(prompt_id, manifest, asset_root,
                           sink=HDMI_SINK):
    """Verify one WAV and return argv without executing a player or shell."""
    if sink != HDMI_SINK:
        raise PromptContractError('audio sink is not the reviewed HDMI sink')
    records = validate_prompt_manifest(manifest)
    if type(prompt_id) is not str or prompt_id not in records:
        raise PromptContractError('unknown prompt id')
    root = Path(asset_root).resolve(strict=True)
    if not root.is_dir():
        raise PromptContractError('asset root is not a directory')
    record = records[prompt_id]
    asset = (root / record['filename']).resolve(strict=True)
    if asset.parent != root or not asset.is_file():
        raise PromptContractError('prompt path escapes the asset root')

    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    if digest != record['sha256']:
        raise PromptContractError('prompt sha256 mismatch')
    try:
        with wave.open(str(asset), 'rb') as audio:
            observed = {
                'channels': audio.getnchannels(),
                'sample_width_bytes': audio.getsampwidth(),
                'sample_rate_hz': audio.getframerate(),
                'frames': audio.getnframes(),
                'compression': audio.getcomptype(),
            }
    except (EOFError, wave.Error) as error:
        raise PromptContractError('prompt WAV is invalid') from error
    for key, value in observed.items():
        if value != record[key]:
            raise PromptContractError('prompt {} mismatch'.format(key))
    duration_s = observed['frames'] / observed['sample_rate_hz']
    if abs(duration_s - float(record['duration_s'])) > 0.001:
        raise PromptContractError('prompt duration mismatch')

    return PlaybackPlan(
        prompt_id=prompt_id,
        text=record['text'],
        asset_path=str(asset),
        sha256=digest,
        duration_s=duration_s,
        argv=('paplay', '--device={}'.format(sink), str(asset)),
    )
