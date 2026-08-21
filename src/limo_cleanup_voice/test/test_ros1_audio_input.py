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

"""ROS-free tests for the reviewed LIMO USB microphone pipeline."""

from pathlib import Path
import wave

import pytest

from limo_cleanup_voice.ros1_audio_input import (
    ASR_CHANNELS,
    ASR_SAMPLE_RATE_HZ,
    AudioInputContractError,
    NATIVE_CHANNELS,
    NATIVE_SAMPLE_RATE_HZ,
    REVIEWED_CAPTURE_DEVICE,
    Ros1AudioInputConfig,
    build_audio_input_plan,
    validate_asr_evidence,
    validate_native_evidence,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _write_wav(path, sample_rate, channels, frames=800):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b'\x00\x00' * channels * frames)


def test_reviewed_capture_and_conversion_argv_are_exact_and_inert(tmp_path):
    plan = build_audio_input_plan(tmp_path, 'wake_probe', 8)

    assert plan.capture_argv == (
        'arecord', '-D', REVIEWED_CAPTURE_DEVICE, '-q',
        '-f', 'S16_LE', '-r', '48000', '-c', '2', '-d', '8',
        str((tmp_path / 'wake_probe_native_48k_stereo.wav').resolve()),
    )
    assert plan.conversion_argv == (
        'sox',
        str((tmp_path / 'wake_probe_native_48k_stereo.wav').resolve()),
        '-r', '16000', '-c', '1',
        str((tmp_path / 'wake_probe_16k_mono.wav').resolve()),
        'remix', '1',
    )
    assert plan.microphone_opened is False
    assert plan.actual_process_count == 0
    assert plan.actual_publish_count == 0
    assert not Path(plan.native_path).exists()
    assert not Path(plan.asr_path).exists()


@pytest.mark.parametrize('field,value', (
    ('profile', 'live_ros'),
    ('capture_device', 'plughw:0,0'),
    ('capture_device', 'default'),
    ('sample_format', 'FLOAT_LE'),
    ('native_sample_rate_hz', 16000),
    ('native_channels', 1),
    ('asr_sample_rate_hz', 48000),
    ('asr_channels', 2),
    ('selected_channel', 2),
    ('max_capture_duration_sec', 30),
))
def test_unreviewed_audio_configuration_fails_closed(field, value):
    with pytest.raises(AudioInputContractError):
        Ros1AudioInputConfig(**{field: value}).validate()


@pytest.mark.parametrize('basename', (
    '', '../escape', '/tmp/escape', 'UPPER', 'voice;move', 'a' * 65,
))
def test_unsafe_or_ambiguous_basename_fails_closed(tmp_path, basename):
    with pytest.raises(AudioInputContractError):
        build_audio_input_plan(tmp_path, basename, 8)


@pytest.mark.parametrize('duration', (0, 11, True, 1.0, '8'))
def test_non_finite_or_unreviewed_duration_fails_closed(tmp_path, duration):
    with pytest.raises(AudioInputContractError):
        build_audio_input_plan(tmp_path, 'wake_probe', duration)


def test_existing_native_or_asr_output_refuses_reuse(tmp_path):
    native = tmp_path / 'wake_probe_native_48k_stereo.wav'
    native.write_bytes(b'existing')
    with pytest.raises(AudioInputContractError, match='already exists'):
        build_audio_input_plan(tmp_path, 'wake_probe', 8)
    native.unlink()
    (tmp_path / 'wake_probe_16k_mono.wav').write_bytes(b'existing')
    with pytest.raises(AudioInputContractError, match='already exists'):
        build_audio_input_plan(tmp_path, 'wake_probe', 8)


def test_native_and_asr_pcm_evidence_validate_exact_formats(tmp_path):
    native = tmp_path / 'native.wav'
    asr = tmp_path / 'asr.wav'
    _write_wav(native, NATIVE_SAMPLE_RATE_HZ, NATIVE_CHANNELS)
    _write_wav(asr, ASR_SAMPLE_RATE_HZ, ASR_CHANNELS)

    native_evidence = validate_native_evidence(native)
    asr_evidence = validate_asr_evidence(asr)

    assert native_evidence.sha256
    assert native_evidence.duration_sec > 0
    assert asr_evidence.sha256
    assert asr_evidence.duration_sec > 0


def test_swapped_or_bad_wav_evidence_fails_closed(tmp_path):
    native = tmp_path / 'native.wav'
    asr = tmp_path / 'asr.wav'
    bad = tmp_path / 'bad.wav'
    _write_wav(native, NATIVE_SAMPLE_RATE_HZ, NATIVE_CHANNELS)
    _write_wav(asr, ASR_SAMPLE_RATE_HZ, ASR_CHANNELS)
    bad.write_bytes(b'not a wav')

    with pytest.raises(AudioInputContractError, match='native WAV'):
        validate_native_evidence(asr)
    with pytest.raises(AudioInputContractError, match='ASR WAV'):
        validate_asr_evidence(native)
    with pytest.raises(AudioInputContractError, match='not a WAV'):
        validate_asr_evidence(bad)


def test_audio_contract_has_no_ros_network_shell_or_control_surface():
    source = (
        PACKAGE_ROOT / 'limo_cleanup_voice' / 'ros1_audio_input.py'
    ).read_text(encoding='utf-8')
    lowered = source.casefold()

    assert 'import rospy' not in source
    assert 'import rclpy' not in source
    assert 'subprocess' not in source
    assert 'shell=true' not in lowered
    assert 'socket' not in lowered
    assert 'cmd_vel' not in lowered
    assert 'geometry_msgs' not in lowered
    assert 'actionlib' not in lowered
