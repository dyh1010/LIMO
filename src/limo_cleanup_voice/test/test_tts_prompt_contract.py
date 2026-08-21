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

"""Pure-software tests for finite fail-closed Chinese prompt playback."""

from copy import deepcopy
import hashlib
import wave

import pytest

from limo_cleanup_voice.tts_prompt_contract import (
    HDMI_SINK,
    PROMPT_TEXTS,
    PromptContractError,
    build_prompt_manifest,
    prompt_id_for_response,
    validate_prompt_manifest,
    verified_playback_plan,
    write_manifest_create_only,
)


def _write_wav(path, frames=1600, sample_rate=16000):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b'\x00\x00' * frames)


def _manifest(tmp_path):
    prompts = []
    for prompt_id, text in PROMPT_TEXTS.items():
        filename = '{}.wav'.format(prompt_id)
        path = tmp_path / filename
        _write_wav(path)
        prompts.append({
            'id': prompt_id,
            'text': text,
            'filename': filename,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'channels': 1,
            'sample_width_bytes': 2,
            'sample_rate_hz': 16000,
            'frames': 1600,
            'duration_s': 0.1,
            'compression': 'NONE',
        })
    return {
        'schema_version': 1,
        'mode': 'finite_dialogue_audio_no_control',
        'actual_control_publish_count': 0,
        'prompts': prompts,
    }


def test_complete_manifest_and_verified_plan_are_control_free(tmp_path):
    manifest = _manifest(tmp_path)
    records = validate_prompt_manifest(manifest)
    assert set(records) == set(PROMPT_TEXTS)
    plan = verified_playback_plan('ready', manifest, tmp_path)
    assert plan.argv == (
        'paplay', '--device={}'.format(HDMI_SINK),
        str((tmp_path / 'ready.wav').resolve()),
    )
    assert plan.actual_control_publish_count == 0
    assert plan.duration_s == pytest.approx(0.1)


def test_manifest_builder_inspects_exact_audio_set(tmp_path):
    expected = _manifest(tmp_path)
    observed = build_prompt_manifest(tmp_path)
    assert observed == expected


def test_manifest_writer_is_deterministic_and_create_only(tmp_path):
    manifest = _manifest(tmp_path)
    output = tmp_path / 'manifest.json'
    digest = write_manifest_create_only(manifest, output)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert '"actual_control_publish_count": 0' in output.read_text(
        encoding='utf-8')
    with pytest.raises(PromptContractError, match='already exists'):
        write_manifest_create_only(manifest, output)


@pytest.mark.parametrize('prompt_id,text', list(PROMPT_TEXTS.items()))
def test_response_mapping_requires_exact_whitelisted_text(prompt_id, text):
    assert prompt_id_for_response(text) == prompt_id


@pytest.mark.parametrize('text', [
    '', ' ' + PROMPT_TEXTS['wake_ack'], PROMPT_TEXTS['wake_ack'] + ' ',
    '任意网络文本', False, None,
])
def test_unknown_or_modified_response_fails_closed(text):
    with pytest.raises(PromptContractError):
        prompt_id_for_response(text)


def test_missing_duplicate_and_changed_prompts_fail_closed(tmp_path):
    manifest = _manifest(tmp_path)
    missing = deepcopy(manifest)
    missing['prompts'].pop()
    duplicate = deepcopy(manifest)
    duplicate['prompts'][-1]['id'] = duplicate['prompts'][0]['id']
    changed = deepcopy(manifest)
    changed['prompts'][0]['text'] += '修改'
    for candidate in (missing, duplicate, changed):
        with pytest.raises(PromptContractError):
            validate_prompt_manifest(candidate)


def test_control_publish_count_and_manifest_extras_fail_closed(tmp_path):
    manifest = _manifest(tmp_path)
    published = deepcopy(manifest)
    published['actual_control_publish_count'] = 1
    extra = deepcopy(manifest)
    extra['unexpected'] = True
    for candidate in (published, extra):
        with pytest.raises(PromptContractError):
            validate_prompt_manifest(candidate)


@pytest.mark.parametrize('filename', [
    '../ready.wav', '/tmp/ready.wav', 'READY.wav', 'ready;move.wav',
])
def test_unsafe_filename_fails_closed(tmp_path, filename):
    manifest = _manifest(tmp_path)
    manifest['prompts'][0]['filename'] = filename
    with pytest.raises(PromptContractError):
        validate_prompt_manifest(manifest)


def test_hash_drift_and_bad_wav_fail_closed(tmp_path):
    manifest = _manifest(tmp_path)
    (tmp_path / 'ready.wav').write_bytes(b'drift')
    with pytest.raises(PromptContractError, match='sha256 mismatch'):
        verified_playback_plan('ready', manifest, tmp_path)
    manifest['prompts'][0]['sha256'] = hashlib.sha256(b'drift').hexdigest()
    with pytest.raises(PromptContractError, match='WAV is invalid'):
        verified_playback_plan('ready', manifest, tmp_path)


def test_wrong_sink_and_unknown_id_fail_before_playback(tmp_path):
    manifest = _manifest(tmp_path)
    with pytest.raises(PromptContractError, match='HDMI sink'):
        verified_playback_plan(
            'ready', manifest, tmp_path,
            'alsa_output.usb-control-device')
    with pytest.raises(PromptContractError, match='unknown prompt id'):
        verified_playback_plan('move_base', manifest, tmp_path)
