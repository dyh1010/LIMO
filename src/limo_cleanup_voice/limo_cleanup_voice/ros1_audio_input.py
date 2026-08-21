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

"""ROS-free, zero-execution contract for the reviewed LIMO microphone."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import wave


AUDIO_PLAN_PROFILE = 'offline_audio_plan'
REVIEWED_CAPTURE_DEVICE = 'hw:0,0'
REVIEWED_SAMPLE_FORMAT = 'S16_LE'
NATIVE_SAMPLE_RATE_HZ = 48000
NATIVE_CHANNELS = 2
ASR_SAMPLE_RATE_HZ = 16000
ASR_CHANNELS = 1
SELECTED_CHANNEL = 1
_BASENAME = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


class AudioInputContractError(ValueError):
    """Raised when an audio plan or captured WAV violates the contract."""


@dataclass(frozen=True)
class Ros1AudioInputConfig:
    """Locked format observed on the LIMO USB capture endpoint."""

    profile: str = AUDIO_PLAN_PROFILE
    capture_device: str = REVIEWED_CAPTURE_DEVICE
    sample_format: str = REVIEWED_SAMPLE_FORMAT
    native_sample_rate_hz: int = NATIVE_SAMPLE_RATE_HZ
    native_channels: int = NATIVE_CHANNELS
    asr_sample_rate_hz: int = ASR_SAMPLE_RATE_HZ
    asr_channels: int = ASR_CHANNELS
    selected_channel: int = SELECTED_CHANNEL
    max_capture_duration_sec: int = 10

    def validate(self):
        """Reject unreviewed devices, formats, channels, and durations."""
        expected = {
            'profile': AUDIO_PLAN_PROFILE,
            'capture_device': REVIEWED_CAPTURE_DEVICE,
            'sample_format': REVIEWED_SAMPLE_FORMAT,
            'native_sample_rate_hz': NATIVE_SAMPLE_RATE_HZ,
            'native_channels': NATIVE_CHANNELS,
            'asr_sample_rate_hz': ASR_SAMPLE_RATE_HZ,
            'asr_channels': ASR_CHANNELS,
            'selected_channel': SELECTED_CHANNEL,
            'max_capture_duration_sec': 10,
        }
        for name, required in expected.items():
            value = getattr(self, name)
            if type(value) is not type(required) or value != required:
                raise AudioInputContractError(
                    '{} differs from reviewed capture contract'.format(name))
        return self


@dataclass(frozen=True)
class AudioInputPlan:
    """Side-effect-free argv plan; an external authorized runner owns I/O."""

    native_path: str
    asr_path: str
    capture_argv: tuple
    conversion_argv: tuple
    microphone_opened: bool = False
    actual_process_count: int = 0
    actual_publish_count: int = 0


@dataclass(frozen=True)
class AudioEvidence:
    """Observed immutable identity and header values for one PCM WAV."""

    path: str
    sha256: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frames: int
    duration_sec: float
    compression: str


def _exclusive_child(root, filename, *, must_exist):
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise AudioInputContractError('staging root is not a directory')
    candidate = root_path / filename
    if must_exist:
        resolved = candidate.resolve(strict=True)
    else:
        resolved = candidate.resolve(strict=False)
    if resolved.parent != root_path:
        raise AudioInputContractError('audio path escapes staging root')
    return resolved


def build_audio_input_plan(staging_root, basename, duration_sec, config=None):
    """Return exact finite arecord/sox argv without executing either tool."""
    selected = (config or Ros1AudioInputConfig()).validate()
    if type(basename) is not str or not _BASENAME.fullmatch(basename):
        raise AudioInputContractError('audio basename is invalid')
    if type(duration_sec) is not int or isinstance(duration_sec, bool) \
            or not 1 <= duration_sec <= selected.max_capture_duration_sec:
        raise AudioInputContractError('capture duration is invalid')
    native = _exclusive_child(
        staging_root, basename + '_native_48k_stereo.wav',
        must_exist=False)
    asr = _exclusive_child(
        staging_root, basename + '_16k_mono.wav', must_exist=False)
    if native.exists() or asr.exists():
        raise AudioInputContractError('audio output already exists')
    return AudioInputPlan(
        native_path=str(native),
        asr_path=str(asr),
        capture_argv=(
            'arecord', '-D', selected.capture_device, '-q',
            '-f', selected.sample_format,
            '-r', str(selected.native_sample_rate_hz),
            '-c', str(selected.native_channels),
            '-d', str(duration_sec), str(native),
        ),
        conversion_argv=(
            'sox', str(native),
            '-r', str(selected.asr_sample_rate_hz),
            '-c', str(selected.asr_channels), str(asr),
            'remix', str(selected.selected_channel),
        ),
    )


def inspect_pcm_wav(path):
    """Read one WAV header and hash without changing the file."""
    audio_path = Path(path).resolve(strict=True)
    if not audio_path.is_file():
        raise AudioInputContractError('audio evidence is not a file')
    try:
        with wave.open(str(audio_path), 'rb') as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
            compression = audio.getcomptype()
    except (EOFError, wave.Error) as error:
        raise AudioInputContractError('audio evidence is not a WAV') from error
    if frames <= 0 or sample_rate <= 0:
        raise AudioInputContractError('audio evidence is empty')
    return AudioEvidence(
        path=str(audio_path),
        sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frames=frames,
        duration_sec=frames / sample_rate,
        compression=compression,
    )


def validate_native_evidence(path):
    """Require the exact USB endpoint native PCM format."""
    evidence = inspect_pcm_wav(path)
    if (
            evidence.sample_rate_hz != NATIVE_SAMPLE_RATE_HZ
            or evidence.channels != NATIVE_CHANNELS
            or evidence.sample_width_bytes != 2
            or evidence.compression != 'NONE'):
        raise AudioInputContractError('native WAV format is invalid')
    return evidence


def validate_asr_evidence(path):
    """Require the exact Vosk input PCM format."""
    evidence = inspect_pcm_wav(path)
    if (
            evidence.sample_rate_hz != ASR_SAMPLE_RATE_HZ
            or evidence.channels != ASR_CHANNELS
            or evidence.sample_width_bytes != 2
            or evidence.compression != 'NONE'):
        raise AudioInputContractError('ASR WAV format is invalid')
    return evidence
