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

"""Regression tests for voice fallback, ASR, and safety gating."""

import json
import hashlib
import queue
import sys
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from std_msgs.msg import String

from limo_cleanup_voice.command_parser import parse_command
from limo_cleanup_voice.voice_asr_node import (
    VoiceAsrNode,
    require_boolean_parameter,
    resample_pcm16_mono,
)
from limo_cleanup_voice.voice_corpus_readiness import (
    LABEL_POLICY,
    REQUIRED_COVERAGE_CLASSES,
    evaluate_corpus_readiness,
    inspect_pcm16_wav,
    validate_vosk_model,
)
from limo_cleanup_voice.voice_contract import (
    navigation_stop_payload,
    navigation_waypoint_payload,
    parse_semantic_candidate,
    parse_stop_ack,
    parse_stop_broadcast,
    perception_inspect_payload,
    semantic_candidate_payload,
    stop_ack_payload,
    stop_broadcast_payload,
)
from limo_cleanup_voice.voice_dialogue_node import VoiceDialogueNode
from limo_cleanup_voice.voice_grammar import DEFAULT_GRAMMAR
from limo_cleanup_voice.semantic_agent import normalize_non_stop_semantics
from limo_cleanup_voice.voice_priority_stop_node import VoicePriorityStopNode
from limo_cleanup_voice.voice_semantic_agent_node import VoiceSemanticAgentNode
from limo_cleanup_voice.voice_offline_eval import (
    evaluate_manifest,
    read_pcm16_mono_wav,
)
from limo_cleanup_voice.voice_preflight import run_preflight
from limo_cleanup_voice.voice_v2_report import generate_report


class DialogueProbe:
    """Run dialogue callbacks without creating a ROS node."""

    expire_pending_command = VoiceDialogueNode.expire_pending_command
    clear_pending_command = VoiceDialogueNode.clear_pending_command
    handle_confirmation = VoiceDialogueNode.handle_confirmation
    forward_confirmed_intent = VoiceDialogueNode.forward_confirmed_intent
    forward_navigation_intent = VoiceDialogueNode.forward_navigation_intent
    publish_navigation_stop = VoiceDialogueNode.publish_navigation_stop
    priority_stop_request_callback = (
        VoiceDialogueNode.priority_stop_request_callback)
    process_transcript = VoiceDialogueNode.process_transcript
    wake_window_active = VoiceDialogueNode.wake_window_active
    arm_wake_window = VoiceDialogueNode.arm_wake_window
    clear_wake_window = VoiceDialogueNode.clear_wake_window

    def __init__(self, require_wake_word=True):
        self.require_confirmation = True
        self.require_wake_word = require_wake_word
        self.wake_words = ['小莫小莫']
        self.trash_bin_waypoint = 'trash_bin_staging'
        self.pending_command = None
        self.pending_intent_name = None
        self.pending_raw_text = None
        self.pending_deadline = 0.0
        self.confirmation_timeout_sec = 10.0
        self.wake_command_timeout_sec = 5.0
        self.wake_deadline = 0.0
        self.responses = []
        self.forwarded = []
        self.intents = []
        self.navigation_requests = []
        self.perception_requests = []
        self.navigation_publisher = SimpleNamespace(
            publish=lambda message: self.navigation_requests.append(
                message.data))
        self.perception_publisher = SimpleNamespace(
            publish=lambda message: self.perception_requests.append(
                message.data))
        self.stop_acks = []
        self.stop_ack_publisher = SimpleNamespace(
            publish=lambda message: self.stop_acks.append(message.data))

    def respond(self, text):
        self.responses.append(text)

    def forward_command(self, command_text):
        self.forwarded.append(command_text)

    def publish_intent(self, intent, raw_text, forwarded):
        self.publish_raw_intent(
            intent.name,
            raw_text,
            intent.command_text,
            forwarded,
            intent.reason,
        )

    def publish_raw_intent(
            self, name, raw_text, command_text, forwarded, reason):
        self.intents.append({
            'intent': name,
            'raw_text': raw_text,
            'command_text': command_text,
            'forwarded': forwarded,
            'reason': reason,
        })


def send_dialogue(probe, text):
    """Send one transcript through the production callback."""
    message = String()
    message.data = text
    VoiceDialogueNode.transcript_callback(probe, message)


def test_text_fallback_strips_and_publishes_transcript():
    class AsrProbe:
        def __init__(self):
            self.published = []

        def publish_transcript(self, text, source):
            self.published.append((text, source))

    probe = AsrProbe()
    message = String()
    message.data = '  小莫小莫，碰一下塑料瓶  '

    VoiceAsrNode.text_callback(probe, message)

    assert probe.published == [('小莫小莫，碰一下塑料瓶', 'text')]


def test_pcm16_resampler_converts_48000_to_16000():
    input_audio = b'\x01\x00' * 4800

    output_audio, state = resample_pcm16_mono(
        input_audio, 48000, 16000)

    assert state is not None
    assert abs(len(output_audio) - 3200) <= 2


def test_pcm16_resampler_rejects_invalid_rates():
    with pytest.raises(ValueError, match='sample rates must be positive'):
        resample_pcm16_mono(b'\x00\x00', 0, 16000)


def _run_fake_recognizer_creation(monkeypatch, use_restricted_grammar):
    calls = {'models': [], 'recognizers': []}

    def fake_model(path):
        calls['models'].append(path)
        return 'fake-model'

    def fake_recognizer(*args):
        calls['recognizers'].append(args)
        return 'fake-recognizer'

    monkeypatch.setitem(sys.modules, 'vosk', SimpleNamespace(
        KaldiRecognizer=fake_recognizer,
        Model=fake_model,
    ))

    class Probe:
        parameters = {
            'vosk_model_path': 'C:/models/vosk-cn',
            'use_restricted_grammar': use_restricted_grammar,
            'grammar_phrases': ['小莫 小莫 捡 矿泉水 瓶', '停下'],
        }

        def get_parameter(self, name):
            return SimpleNamespace(value=self.parameters[name])

    result = VoiceAsrNode.create_recognizer(Probe(), 16000)
    return result, calls


def test_asr_recognizer_defaults_to_unrestricted_no_grammar(monkeypatch):
    result, calls = _run_fake_recognizer_creation(monkeypatch, False)

    assert result == 'fake-recognizer'
    assert calls['models'] == ['C:/models/vosk-cn']
    assert calls['recognizers'] == [('fake-model', 16000.0)]


def test_asr_recognizer_uses_restricted_grammar_only_when_explicit(
        monkeypatch):
    unused_result, calls = _run_fake_recognizer_creation(monkeypatch, True)

    assert calls['recognizers'] == [(
        'fake-model',
        16000.0,
        json.dumps(
            ['小莫 小莫 捡 矿泉水 瓶', '停下'], ensure_ascii=False),
    )]


@pytest.mark.parametrize('invalid_value', (None, 0, 1, 'false', [], {}))
def test_asr_restricted_grammar_switch_rejects_non_boolean(
        monkeypatch, invalid_value):
    with pytest.raises(
            ValueError, match='use_restricted_grammar must be a boolean'):
        _run_fake_recognizer_creation(monkeypatch, invalid_value)


def test_legacy_asr_config_keeps_restricted_grammar_disabled():
    config_path = Path(__file__).resolve().parents[1] / 'config' / \
        'voice_dialogue.yaml'
    source = config_path.read_text(encoding='utf-8')

    assert 'use_restricted_grammar: false' in source
    assert 'BOTTLE_ONLY_EXPERIMENT_BLOCKED_ACCURACY_REGRESSION' in source


def test_microphone_mode_uses_native_rate_and_resamples(monkeypatch):
    created = {}

    class FakeStream:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.started = False

        def start(self):
            self.started = True

    fake_sounddevice = SimpleNamespace(
        query_devices=lambda device, kind: {'default_samplerate': 48000.0},
        RawInputStream=FakeStream,
    )
    monkeypatch.setitem(sys.modules, 'sounddevice', fake_sounddevice)

    class Logger:
        def info(self, message):
            del message

        def warning(self, message):
            del message

    class MicrophoneProbe:
        def __init__(self):
            self.parameters = {
                'sample_rate': 16000,
                'input_sample_rate': 0,
                'block_size': 8000,
                'microphone_device': '0',
            }
            self.audio_queue = queue.Queue(maxsize=32)
            self.audio_stream = None
            self.resample_state = None
            self.capture_sample_rate = 0
            self.recognizer_sample_rate = 0
            self.statuses = []

        def get_parameter(self, name):
            return SimpleNamespace(value=self.parameters[name])

        def get_logger(self):
            return Logger()

        def create_recognizer(self, sample_rate):
            self.recognizer_rate = sample_rate
            return object()

        def create_timer(self, interval, callback):
            self.timer = (interval, callback)

        def drain_audio_queue(self):
            return None

        def publish_status(self, state, detail, **extra):
            self.statuses.append((state, detail, extra))

    probe = MicrophoneProbe()

    VoiceAsrNode.start_microphone_mode(probe)
    created['callback'](b'\x01\x00' * 480, 480, None, None)
    queued_audio = probe.audio_queue.get_nowait()

    assert created['samplerate'] == 48000
    assert created['device'] == 0
    assert created['channels'] == 1
    assert probe.recognizer_rate == 16000
    assert abs(len(queued_audio) - 320) <= 2
    assert probe.audio_stream.started is True
    assert probe.statuses[-1][0] == 'ready'


def test_confirmation_forwards_only_after_fresh_confirmation():
    probe = DialogueProbe()

    send_dialogue(probe, '小莫小莫，碰一下塑料瓶')
    assert probe.forwarded == []

    send_dialogue(probe, '确认')

    assert probe.forwarded == ['触碰矿泉水瓶']
    assert probe.intents[-1]['intent'] == 'confirm'
    assert probe.intents[-1]['forwarded'] is True


@pytest.mark.parametrize('text,pending_intent', (
    ('小莫小莫，捡塑料瓶', 'start_cleanup'),
    ('小莫小莫，到垃圾桶旁边去', 'navigate_to_bin'),
    ('小莫小莫，识别矿泉水瓶', 'inspect_bottle'),
))
def test_actionable_intents_cannot_disable_confirmation_gate(
        text, pending_intent):
    probe = DialogueProbe()
    probe.require_confirmation = False

    send_dialogue(probe, text)

    assert probe.pending_intent_name == pending_intent
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.perception_requests == []
    assert probe.intents[-1]['forwarded'] is False


def test_cancel_clears_fresh_pending_command_without_forwarding():
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫，捡塑料瓶')

    send_dialogue(probe, '取消')

    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.intents[-1]['forwarded'] is False


def test_cancel_without_pending_fails_closed_without_stop_request():
    probe = DialogueProbe(require_wake_word=True)

    send_dialogue(probe, '取消')

    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.intents[-1]['forwarded'] is False


def test_cancel_consumes_wake_only_window_without_stop_request():
    probe = DialogueProbe(require_wake_word=True)
    send_dialogue(probe, '小莫小莫')

    send_dialogue(probe, '取消')

    assert probe.wake_deadline == 0.0
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.intents[-1]['forwarded'] is False


def test_expired_confirmation_never_forwards_command():
    probe = DialogueProbe()
    probe.pending_command = '捡塑料瓶'
    probe.pending_deadline = time.monotonic() - 1.0

    send_dialogue(probe, '确认')

    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.intents[-1]['reason'] == 'confirmation expired'


def test_expired_pending_restores_wake_word_for_new_task():
    probe = DialogueProbe()
    probe.pending_command = '捡塑料瓶'
    probe.pending_deadline = time.monotonic() - 1.0

    send_dialogue(probe, '碰一下塑料瓶')

    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'ignored'


def test_cancel_after_timeout_fails_closed_without_stop_request():
    probe = DialogueProbe()
    probe.pending_command = '捡塑料瓶'
    probe.pending_deadline = time.monotonic() - 1.0

    send_dialogue(probe, '取消')

    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.intents[-1]['forwarded'] is False


def test_emergency_stop_clears_pending_and_forwards_immediately():
    probe = DialogueProbe()
    probe.pending_command = '捡塑料瓶'
    probe.pending_deadline = time.monotonic() + 10.0

    send_dialogue(probe, '紧急停止')

    assert probe.pending_command is None
    assert probe.forwarded == ['停止任务']
    assert probe.intents[-1]['forwarded'] is True
    assert 'cancel_navigation' in probe.navigation_requests[-1]
    assert 'request_safe_stop' in probe.navigation_requests[-1]


def test_stop_is_highest_priority_and_never_waits_for_confirmation():
    probe = DialogueProbe()

    send_dialogue(probe, '小莫小莫，到垃圾桶旁边去，停下')

    assert probe.pending_command is None
    assert probe.forwarded == ['停止任务']
    assert 'cancel_navigation' in probe.navigation_requests[-1]


def test_speaker_relative_request_is_unsupported_and_never_forwarded():
    probe = DialogueProbe()

    send_dialogue(probe, '小莫小莫，到这里来')

    assert probe.pending_command is None
    assert probe.navigation_requests == []
    assert any('暂不支持' in item for item in probe.responses)
    assert probe.intents[-1]['intent'] == 'unsupported'
    assert probe.intents[-1]['forwarded'] is False


def test_trash_bin_request_uses_fixed_waypoint_after_confirmation():
    probe = DialogueProbe()

    send_dialogue(probe, '小莫小莫，到垃圾桶旁边去')
    assert probe.navigation_requests == []
    send_dialogue(probe, '确认')

    assert len(probe.navigation_requests) == 1
    assert 'navigate_to_waypoint' in probe.navigation_requests[0]
    assert 'trash_bin_staging' in probe.navigation_requests[0]
    assert 'fixed_map_waypoint' in probe.navigation_requests[0]


def test_navigation_payloads_match_strict_bridge_schema_exactly():
    probe = DialogueProbe()

    VoiceDialogueNode.publish_navigation_stop(probe, '停下')
    forwarded, _, _ = VoiceDialogueNode.forward_navigation_intent(
        probe, 'navigate_to_bin', '小莫小莫，到垃圾桶旁边去')

    assert forwarded is True
    assert json.loads(probe.navigation_requests[0]) == {
        'action': 'cancel_navigation',
        'request_safe_stop': True,
    }
    assert json.loads(probe.navigation_requests[1]) == {
        'action': 'navigate_to_waypoint',
        'target_id': 'trash_bin_staging',
        'target_source': 'fixed_map_waypoint',
    }


def test_navigation_contract_helpers_match_strict_schema_exactly():
    assert navigation_stop_payload() == {
        'action': 'cancel_navigation',
        'request_safe_stop': True,
    }
    assert navigation_waypoint_payload() == {
        'action': 'navigate_to_waypoint',
        'target_id': 'trash_bin_staging',
        'target_source': 'fixed_map_waypoint',
    }


def test_read_only_preflight_checks_bridge_and_no_hardware_contract():
    received = []

    def strict_parser(payload):
        received.append(json.loads(payload))
        return object()

    package_root = Path(__file__).resolve().parents[1]
    report = run_preflight(package_root, bridge_parser=strict_parser)

    assert report['status'] == 'PASS'
    assert report['mode'] == 'read_only_no_hardware'
    assert received == [
        navigation_stop_payload(),
        navigation_waypoint_payload(),
    ]
    assert all(check['passed'] for check in report['checks'])


def test_read_only_preflight_fails_closed_on_bridge_rejection():
    def rejecting_parser(payload):
        del payload
        raise ValueError('strict rejection')

    package_root = Path(__file__).resolve().parents[1]
    report = run_preflight(package_root, bridge_parser=rejecting_parser)

    assert report['status'] == 'FAIL'
    bridge_check = next(
        check for check in report['checks']
        if check['name'] == 'bridge_parser_readonly')
    assert bridge_check['passed'] is False
    assert 'strict rejection' in bridge_check['detail']


def _write_silent_wav(
        path, channels=1, sample_width=2, rate=16000, frame_count=160):
    with wave.open(str(path), 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(rate)
        wav_file.writeframes(
            b'\x00' * channels * sample_width * frame_count)


def _write_tone_wav(path, rate=16000, frame_count=16000, amplitude=7000):
    samples = bytearray()
    for index in range(frame_count):
        if index < 1600 or index >= frame_count - 1600:
            sample = 0
        else:
            sample = amplitude if (index // 80) % 2 == 0 else -amplitude
        samples.extend(int(sample).to_bytes(2, 'little', signed=True))
    with wave.open(str(path), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(bytes(samples))


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _readiness_manifest(tmp_path, model_path=None):
    labels = (
        ('wake', '小莫小莫', 'wake_only'),
        ('stop', '停下', 'priority_stop'),
        ('task', '捡矿泉水瓶', 'ordinary_intent'),
    )
    cases = []
    for index, (case_id, label, coverage) in enumerate(labels):
        audio_path = tmp_path / '{}.wav'.format(case_id)
        source_path = tmp_path / '{}.m4a'.format(case_id)
        _write_tone_wav(audio_path, amplitude=6000 + index * 500)
        source_path.write_bytes(('source-' + case_id).encode())
        audio = inspect_pcm16_wav(audio_path)
        cases.append({
            'id': case_id,
            'label': label,
            'coverage_class': coverage,
            'label_is_transcript': False,
            'source_path': source_path.name,
            'source_sha256': _sha256(source_path),
            'source_bytes': source_path.stat().st_size,
            'source_format': {
                'subtype': 'AAC',
                'sample_rate': 48000,
                'channels': 1,
                'bits_per_sample': 16,
                'bitrate': 64000,
            },
            'audio_path': audio_path.name,
            'wav_sha256': audio['sha256'],
            'wav_bytes': audio_path.stat().st_size,
            'wav': {
                key: audio[key]
                for key in (
                    'sample_rate', 'channels', 'sample_width_bytes',
                    'frame_count', 'duration_sec', 'rms', 'rms_dbfs',
                    'peak', 'peak_dbfs', 'clipped_fraction',
                    'voiced_frame_fraction', 'leading_silence_sec_est',
                    'trailing_silence_sec_est',
                )
            },
            'transcription_status': 'decoded_not_transcribed',
            'transcript': None,
            'intent_status': 'not_evaluated_without_asr',
        })
    manifest = tmp_path / 'decode_manifest.json'
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')
    return manifest, cases, model_path


def test_offline_wav_manifest_reports_v2_intents_and_false_triggers(tmp_path):
    wake_audio = tmp_path / 'wake.wav'
    negative_audio = tmp_path / 'background.wav'
    _write_silent_wav(wake_audio)
    _write_silent_wav(negative_audio)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({
        'cases': [
            {
                'id': 'wake-waypoint',
                'audio_path': wake_audio.name,
                'transcript_fixture': '小莫小莫，到垃圾桶旁边去',
                'expected_intent': 'navigate_to_bin',
            },
            {
                'id': 'background',
                'audio_path': negative_audio.name,
                'transcript_fixture': '今天天气不错',
                'expected_intent': 'ignored',
                'negative': True,
            },
        ],
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_manifest(manifest)

    assert report['status'] == 'PASS'
    assert report['case_count'] == 2
    assert report['passed_count'] == 2
    assert report['negative_count'] == 1
    assert report['false_activation_count'] == 0
    assert report['false_activation_rate'] == 0.0


def test_offline_wav_reader_rejects_stereo_input(tmp_path):
    stereo_audio = tmp_path / 'stereo.wav'
    _write_silent_wav(stereo_audio, channels=2)

    with pytest.raises(ValueError, match='WAV input must be mono'):
        read_pcm16_mono_wav(stereo_audio)


def test_corpus_readiness_reports_missing_model_without_fake_transcript(
        tmp_path):
    manifest, _, _ = _readiness_manifest(tmp_path)

    report = evaluate_corpus_readiness(
        manifest, tmp_path / 'missing-model')

    assert report['status'] == 'INCOMPLETE', report['blocking_issues']
    assert report['corpus_ready'] is True
    assert report['delivery_ready'] is False
    assert report['transcription_status'] == 'decoded_not_transcribed'
    assert report['corpus']['case_count'] == 3
    assert report['corpus']['format_pass_count'] == 3
    assert report['corpus']['quality_pass_count'] == 3
    assert report['corpus']['hash_pass_count'] == 3
    assert report['corpus']['source_hash_pass_count'] == 3
    assert report['corpus']['metadata_pass_count'] == 3
    assert all(case['transcript'] is None for case in report['cases'])
    assert all(
        case['label_is_transcript'] is False for case in report['cases'])
    assert 'Vosk model directory is missing' in report['blocking_issues']


def test_corpus_readiness_rejects_duplicate_label_and_hash_drift(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[1]['label'] = cases[0]['label']
    cases[2]['wav_sha256'] = '0' * 64
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['status'] == 'FAIL'
    assert report['corpus_ready'] is False
    assert report['delivery_ready'] is False
    assert report['corpus']['duplicate_label_groups'] == ['小莫小莫']
    assert any('duplicate label' in item for item in report['blocking_issues'])
    assert report['corpus']['hash_pass_count'] == 2


def test_corpus_readiness_rejects_duplicate_id_path_and_audio_hash(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    duplicate_audio = tmp_path / 'duplicate.wav'
    duplicate_audio.write_bytes((tmp_path / 'wake.wav').read_bytes())
    cases[1]['id'] = cases[0]['id']
    cases[1]['audio_path'] = cases[0]['audio_path']
    cases[2]['audio_path'] = duplicate_audio.name
    cases[2]['wav_sha256'] = cases[0]['wav_sha256']
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert any('duplicate id' in item for item in report['blocking_issues'])
    assert any(
        'duplicate audio_path' in item for item in report['blocking_issues'])
    assert any(
        'duplicate wav_sha256' in item for item in report['blocking_issues'])


def test_corpus_readiness_rejects_unknown_absolute_path_field(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['wav_path'] = str((tmp_path / 'wake.wav').resolve())
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert any(
        'unknown manifest fields: wav_path' in item
        for item in report['blocking_issues'])


def test_corpus_readiness_rejects_bad_empty_and_non_pcm_wav(tmp_path):
    bad = tmp_path / 'bad.wav'
    bad.write_bytes(b'not a wave file')
    empty = tmp_path / 'empty.wav'
    _write_silent_wav(empty, frame_count=0)
    non_pcm = tmp_path / 'eight-bit.wav'
    _write_silent_wav(non_pcm, sample_width=1, frame_count=16000)

    bad_report = inspect_pcm16_wav(bad)
    empty_report = inspect_pcm16_wav(empty)
    non_pcm_report = inspect_pcm16_wav(non_pcm)

    assert bad_report['format_pass'] is False
    assert any('invalid WAV' in item for item in bad_report['format_issues'])
    assert empty_report['format_pass'] is False
    assert 'WAV must contain audio frames' in empty_report['format_issues']
    assert non_pcm_report['format_pass'] is False
    assert 'WAV must use 16-bit PCM samples' in (
        non_pcm_report['format_issues'])


def test_corpus_readiness_rejects_wrong_rate_and_clipping(tmp_path):
    wrong_rate = tmp_path / 'wrong-rate.wav'
    _write_tone_wav(wrong_rate, rate=48000, frame_count=48000)
    clipped = tmp_path / 'clipped.wav'
    _write_tone_wav(clipped, amplitude=32767)

    rate_report = inspect_pcm16_wav(wrong_rate)
    clipped_report = inspect_pcm16_wav(clipped)

    assert rate_report['format_pass'] is False
    assert 'WAV sample rate must be 16000 Hz' in (
        rate_report['format_issues'])
    assert clipped_report['format_pass'] is True
    assert clipped_report['quality_pass'] is False
    assert 'clipped fraction exceeds 0.001' in (
        clipped_report['quality_issues'])


def test_corpus_readiness_rejects_sparse_voice_and_zero_rate(tmp_path):
    sparse = tmp_path / 'sparse.wav'
    samples = bytearray(b'\x00\x00' * (15 * 16000))
    for frame_start in (0, 15 * 16000 - 320):
        for index in range(frame_start, frame_start + 320):
            offset = index * 2
            samples[offset:offset + 2] = int(7000).to_bytes(
                2, 'little', signed=True)
    with wave.open(str(sparse), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(bytes(samples))

    sparse_report = inspect_pcm16_wav(sparse)
    assert sparse_report['quality_pass'] is False
    assert 'voiced frame fraction must be at least 0.05' in (
        sparse_report['quality_issues'])

    class ZeroRateWav:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def getnchannels(self):
            return 1

        def getsampwidth(self):
            return 2

        def getframerate(self):
            return 0

        def getnframes(self):
            return 1

        def getcomptype(self):
            return 'NONE'

        def readframes(self, frame_count):
            del frame_count
            return b'\x00\x00'

    zero_rate = tmp_path / 'zero-rate.wav'
    zero_rate.write_bytes(b'placeholder')
    original_wave_open = wave.open
    wave.open = lambda *args, **kwargs: ZeroRateWav()
    try:
        report = inspect_pcm16_wav(zero_rate)
    finally:
        wave.open = original_wave_open

    assert report['format_pass'] is False
    assert 'WAV sample rate must be positive' in report['format_issues']


def test_corpus_readiness_rejects_silent_audio_and_missing_coverage(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    silent = tmp_path / 'wake.wav'
    _write_silent_wav(silent, frame_count=16000)
    audio = inspect_pcm16_wav(silent)
    cases[0]['wav_sha256'] = audio['sha256']
    cases[0]['wav'] = {
        key: audio.get(key)
        for key in (
            'sample_rate', 'channels', 'sample_width_bytes', 'frame_count',
            'duration_sec', 'rms', 'rms_dbfs', 'peak', 'peak_dbfs',
            'clipped_fraction', 'voiced_frame_fraction',
            'leading_silence_sec_est', 'trailing_silence_sec_est',
        )
    }
    cases = [case for case in cases if case['coverage_class'] != 'priority_stop']
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['status'] == 'FAIL'
    assert report['corpus']['quality_pass_count'] == 1
    assert report['corpus']['missing_coverage'] == ['priority_stop']
    assert any('audio is silent' in item for item in report['blocking_issues'])


def test_corpus_readiness_rejects_label_as_transcript_and_path_escape(
        tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['label_is_transcript'] = True
    cases[1]['audio_path'] = '../outside.wav'
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert any(
        'label_is_transcript must be false' in item
        for item in report['blocking_issues'])
    assert any(
        'audio_path escapes the manifest directory' in item
        for item in report['blocking_issues'])


def test_corpus_readiness_rejects_absolute_source_path(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['source_path'] = str((tmp_path / 'wake.m4a').resolve())
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert any(
        'source_path must stay within relative source_root' in item
        for item in report['blocking_issues'])


def test_corpus_readiness_rejects_absolute_audio_path(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['audio_path'] = str((tmp_path / 'wake.wav').resolve())
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert any(
        'audio_path must be relative to the manifest' in item
        for item in report['blocking_issues'])
    assert report['cases'][0]['audio']['accessed'] is False
    assert report['cases'][0]['audio']['exists'] is None
    assert report['cases'][0]['audio']['sha256'] is None


@pytest.mark.parametrize('audio_path', (
    r'C:\outside.wav',
    r'C:outside.wav',
    r'\\server\share\outside.wav',
    r'\rooted\outside.wav',
    '/outside.wav',
    r'..\outside.wav',
    'file:///outside.wav',
))
def test_corpus_readiness_rejects_portable_audio_path_escape(
        tmp_path, audio_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['audio_path'] = audio_path
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert report['cases'][0]['audio']['accessed'] is False


@pytest.mark.parametrize('source_root', (
    r'C:\outside',
    r'C:outside',
    r'\\server\share\outside',
    '/outside',
    'file:///outside',
))
def test_corpus_readiness_rejects_portable_source_root_escape(
        tmp_path, source_root):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': source_root,
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert all(case['source_hash_match'] is False for case in report['cases'])
    assert any(
        'source_root must be a relative project path' in item
        for item in report['blocking_issues'])


def test_corpus_readiness_rejects_unrelated_relative_source_root(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    unrelated = tmp_path.parent / 'unrelated-source-root'
    unrelated.mkdir(exist_ok=True)
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '../unrelated-source-root',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert all(case['source_hash_match'] is False for case in report['cases'])
    assert any(
        'source_root must be the manifest directory or its direct parent'
        in item
        for item in report['blocking_issues'])


def test_corpus_readiness_rejects_deep_ancestor_source_root(tmp_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '../..',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert all(case['source_hash_match'] is False for case in report['cases'])
    assert any(
        'source_root may traverse at most one parent directory'
        in item for item in report['blocking_issues'])


@pytest.mark.parametrize('source_path', (
    r'C:\outside.m4a',
    r'C:outside.m4a',
    r'\\server\share\outside.m4a',
    r'\rooted\outside.m4a',
    '/outside.m4a',
    r'..\outside.m4a',
    'file:///outside.m4a',
))
def test_corpus_readiness_rejects_portable_source_path_escape(
        tmp_path, source_path):
    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['source_path'] = source_path
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert report['cases'][0]['source_hash_match'] is False


def test_corpus_readiness_rejects_symlinks_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / 'outside-voice-files'
    outside.mkdir(exist_ok=True)
    outside_audio = outside / 'outside.wav'
    outside_source = outside / 'outside.m4a'
    _write_tone_wav(outside_audio)
    outside_source.write_bytes(b'outside-source')
    audio_link = tmp_path / 'audio-link.wav'
    source_link = tmp_path / 'source-link.m4a'
    try:
        audio_link.symlink_to(outside_audio)
        source_link.symlink_to(outside_source)
    except (NotImplementedError, OSError):
        pytest.skip('symlinks are unavailable in this environment')

    manifest, cases, _ = _readiness_manifest(tmp_path)
    cases[0]['audio_path'] = audio_link.name
    cases[0]['source_path'] = source_link.name
    manifest.write_text(json.dumps({
        'schema_version': 2,
        'mode': 'windows_media_foundation_offline_no_ros',
        'label_policy': LABEL_POLICY,
        'source_root': '.',
        'required_coverage_classes': list(REQUIRED_COVERAGE_CLASSES),
        'cases': cases,
    }, ensure_ascii=False), encoding='utf-8')

    report = evaluate_corpus_readiness(manifest, tmp_path / 'model')

    assert report['delivery_ready'] is False
    assert report['cases'][0]['audio']['accessed'] is False
    assert report['cases'][0]['source_hash_match'] is False


def _write_plausible_vosk_model(model):
    (model / 'am').mkdir(parents=True)
    (model / 'conf').mkdir()
    (model / 'graph' / 'phones').mkdir(parents=True)
    model_header = b'\x00B<TransitionModel> '
    (model / 'am' / 'final.mdl').write_bytes(
        model_header + b'\x00' * (1024 * 1024 - len(model_header)))
    graph_header = b'\xd6\xfd\xb2\x7e'
    (model / 'graph' / 'HCLr.fst').write_bytes(
        graph_header + b'\x00' * (1024 * 1024 - len(graph_header)))
    (model / 'graph' / 'Gr.fst').write_bytes(
        graph_header + b'\x00' * (64 - len(graph_header)))
    (model / 'conf' / 'mfcc.conf').write_text(
        '--sample-frequency=16000\n--num-mel-bins=40\n',
        encoding='utf-8')
    (model / 'conf' / 'model.conf').write_text(
        '--endpoint.silence-phones=1:2:3\n', encoding='utf-8')
    words = ['<eps> 0'] + [
        'word{} {}'.format(index, index) for index in range(1, 10)
    ]
    (model / 'graph' / 'words.txt').write_text(
        '\n'.join(words) + '\n', encoding='utf-8')
    (model / 'graph' / 'phones' / 'word_boundary.int').write_text(
        '1 0\n2 1\n', encoding='utf-8')
    (model / 'graph' / 'disambig_tid.int').write_text(
        '1\n2\n3\n', encoding='utf-8')


def test_vosk_model_readiness_requires_structure_and_loadability(tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    assert validate_vosk_model(model)['ready'] is False
    (model / 'am').mkdir()
    (model / 'am' / 'final.mdl').write_bytes(b'model')
    assert validate_vosk_model(model)['ready'] is False
    (model / 'graph').mkdir()
    (model / 'graph' / 'HCLG.fst').write_bytes(b'graph')

    small_report = validate_vosk_model(model)

    assert small_report['ready'] is False
    assert 'Vosk am/final.mdl is implausibly small' in (
        small_report['issues'])
    assert 'Vosk restricted grammar requires both graph/HCLr.fst ' \
        'and graph/Gr.fst' in small_report['issues']
    (model / 'am' / 'final.mdl').write_bytes(b'm' * (1024 * 1024))
    (model / 'graph' / 'HCLG.fst').write_bytes(b'g' * (1024 * 1024))

    filler_report = validate_vosk_model(model)

    assert filler_report['ready'] is False
    assert filler_report['static_ready'] is False
    assert 'Vosk am/final.mdl header is invalid' in filler_report['issues']
    assert 'Vosk restricted grammar requires both graph/HCLr.fst ' \
        'and graph/Gr.fst' in filler_report['issues']
    assert 'Vosk conf/mfcc.conf is missing' in filler_report['issues']

    plausible_model = tmp_path / 'plausible-model'
    _write_plausible_vosk_model(plausible_model)
    report = validate_vosk_model(
        plausible_model,
        model_loader=lambda unused: object(),
        recognizer_loader=lambda model, rate, grammar: object(),
    )

    assert report['ready'] is True
    assert report['issues'] == []
    assert report['static_ready'] is True
    assert report['runtime_available'] is True
    assert report['loadability_checked'] is True
    assert report['loadable'] is True


def test_vosk_model_readiness_rejects_loader_failure(tmp_path):
    model = tmp_path / 'model'
    _write_plausible_vosk_model(model)

    def reject_model(unused):
        raise RuntimeError('corrupt model')

    report = validate_vosk_model(
        model,
        model_loader=reject_model,
        recognizer_loader=lambda model, rate, grammar: object(),
    )

    assert report['static_ready'] is True
    assert report['loadability_checked'] is True
    assert report['loadable'] is False
    assert report['ready'] is False
    assert any(
        'Vosk model or restricted-grammar recognizer failed to load: '
        'RuntimeError: corrupt model' in item
        for item in report['issues'])


def test_vosk_model_readiness_rejects_restricted_grammar_failure(tmp_path):
    model = tmp_path / 'model'
    _write_plausible_vosk_model(model)

    def reject_grammar(unused_model, unused_rate, unused_grammar):
        raise RuntimeError('dynamic grammar unavailable')

    report = validate_vosk_model(
        model,
        model_loader=lambda unused: object(),
        recognizer_loader=reject_grammar,
    )

    assert report['static_ready'] is True
    assert report['loadability_checked'] is True
    assert report['loadable'] is False
    assert report['ready'] is False
    assert any(
        'dynamic grammar unavailable' in item for item in report['issues'])


def test_vosk_model_readiness_probes_complete_deployment_grammar(tmp_path):
    model = tmp_path / 'model'
    _write_plausible_vosk_model(model)
    captured = {}

    def capture_grammar(unused_model, sample_rate, grammar_json):
        captured['sample_rate'] = sample_rate
        captured['grammar'] = json.loads(grammar_json)
        return object()

    report = validate_vosk_model(
        model,
        model_loader=lambda unused: object(),
        recognizer_loader=capture_grammar,
    )

    assert report['ready'] is True
    assert captured['sample_rate'] == 16000.0
    assert captured['grammar'] == DEFAULT_GRAMMAR


def test_vosk_model_readiness_rejects_gr_fst_below_exact_boundary(tmp_path):
    model = tmp_path / 'model'
    _write_plausible_vosk_model(model)
    graph = model / 'graph' / 'Gr.fst'
    graph.write_bytes(b'\xd6\xfd\xb2\x7e' + b'\x00' * 27)

    report = validate_vosk_model(
        model,
        model_loader=lambda unused: object(),
        recognizer_loader=lambda model, rate, grammar: object(),
    )

    assert report['static_ready'] is False
    assert 'Vosk graph/Gr.fst is implausibly small' in report['issues']

    graph.write_bytes(b'\xd6\xfd\xb2\x7e' + b'\x00' * 28)
    boundary_report = validate_vosk_model(
        model,
        model_loader=lambda unused: object(),
        recognizer_loader=lambda model, rate, grammar: object(),
    )
    assert boundary_report['ready'] is True


def test_real_recording_manifest_is_corpus_ready_without_asr_model():
    package_root = Path(__file__).resolve().parents[1]
    project_root = package_root.parents[2]
    manifest = (
        project_root / 'conv' / 'decoded_16k_mono'
        / 'decode_manifest.json'
    )
    if not manifest.is_file():
        pytest.skip('local prerecorded corpus is not present')

    report = evaluate_corpus_readiness(
        manifest,
        project_root / 'limo_cleanup_ws' / 'models'
        / 'vosk-model-small-cn-0.22',
    )

    assert report['status'] == 'INCOMPLETE', report['blocking_issues']
    assert report['corpus_ready'] is True
    assert report['delivery_ready'] is False
    assert report['transcription_status'] == 'decoded_not_transcribed'
    assert report['corpus']['case_count'] == 4
    assert report['corpus']['format_pass_count'] == 4
    assert report['corpus']['quality_pass_count'] == 4
    assert report['corpus']['hash_pass_count'] == 4
    assert report['corpus']['source_hash_pass_count'] == 4
    assert report['corpus']['metadata_pass_count'] == 4
    assert report['corpus']['coverage'] == {
        'wake_only': 1,
        'priority_stop': 1,
        'ordinary_intent': 2,
    }
    assert report['blocking_issues'] == [
        'Vosk model directory is missing']


def test_repeatable_v2_statistics_have_zero_false_activations():
    report = generate_report(iterations=10)

    assert report['status'] == 'PASS'
    assert report['iterations'] == 10
    assert report['false_activation_count'] == 0
    assert report['false_activation_rate'] == 0.0
    assert all(
        count == 10
        for count in report['scenario_pass_counts'].values())


def _priority_probe():
    class Publisher:
        def __init__(self):
            self.messages = []

        def publish(self, message):
            self.messages.append(message.data)

    statuses = Publisher()
    probe = SimpleNamespace(
        priority_publisher=Publisher(),
        stop_request_publisher=Publisher(),
        status_publisher=statuses,
        debounce_sec=0.75,
        repeat_count=3,
        repeat_interval_sec=0.075,
        ack_timeout_sec=1.5,
        _state_lock=threading.RLock(),
        _active_event=None,
        _process_instance_id='voice-stop-process-test0001',
        _last_trigger_monotonic_ns=-1,
        _last_event_id='',
    )
    probe.publish_status = lambda state, detail, event_id, **extra: (
        VoicePriorityStopNode.publish_status(
            probe, state, detail, event_id, **extra))
    probe._publish_attempt_locked = lambda: (
        VoicePriorityStopNode._publish_attempt_locked(probe))
    return probe


def test_priority_stop_first_publish_is_immediate_and_exact():
    probe = _priority_probe()
    message = String()
    message.data = '先别干了'
    started_ns = time.monotonic_ns()

    VoicePriorityStopNode.transcript_callback(probe, message)

    assert len(probe.priority_publisher.messages) == 1
    assert probe.priority_publisher.messages == (
        probe.stop_request_publisher.messages)
    broadcast = parse_stop_broadcast(probe.priority_publisher.messages[0])
    assert broadcast['priority'] == 'critical'
    assert broadcast['intent'] == 'stop_task'
    assert broadcast['raw_text'] == '先别干了'
    assert broadcast['attempt'] == 1
    assert broadcast['repeat_count'] == 3
    assert broadcast['published_monotonic_ns'] >= started_ns
    assert broadcast['transcript_to_publish_latency_ns'] >= 0


def test_priority_stop_repeats_exactly_and_timestamps_are_monotonic():
    probe = _priority_probe()
    message = String()
    message.data = '停下'
    VoicePriorityStopNode.transcript_callback(probe, message)

    for _ in range(2):
        probe._active_event['last_publish_monotonic_ns'] = (
            time.monotonic_ns()
            - int(probe.repeat_interval_sec * 1_000_000_000) - 1)
        VoicePriorityStopNode.repeat_timer_callback(probe)
    VoicePriorityStopNode.repeat_timer_callback(probe)

    broadcasts = [
        parse_stop_broadcast(item)
        for item in probe.priority_publisher.messages]
    assert [item['attempt'] for item in broadcasts] == [1, 2, 3]
    assert len({item['event_id'] for item in broadcasts}) == 1
    assert [item['published_monotonic_ns'] for item in broadcasts] == sorted(
        item['published_monotonic_ns'] for item in broadcasts)
    assert len(probe.stop_request_publisher.messages) == 3


def test_priority_stop_repeat_interval_has_an_exact_boundary():
    probe = _priority_probe()
    message = String()
    message.data = '停下'
    VoicePriorityStopNode.transcript_callback(probe, message)
    interval_ns = int(probe.repeat_interval_sec * 1_000_000_000)
    original_monotonic_ns = time.monotonic_ns
    boundary_ns = probe._active_event['last_publish_monotonic_ns']
    try:
        time.monotonic_ns = lambda: boundary_ns + interval_ns - 1
        VoicePriorityStopNode.repeat_timer_callback(probe)
        assert len(probe.priority_publisher.messages) == 1

        time.monotonic_ns = lambda: boundary_ns + interval_ns
        VoicePriorityStopNode.repeat_timer_callback(probe)
        assert len(probe.priority_publisher.messages) == 2
        broadcast = parse_stop_broadcast(
            probe.priority_publisher.messages[-1])
        assert broadcast['attempt'] == 2
    finally:
        time.monotonic_ns = original_monotonic_ns


def test_priority_stop_debounce_does_not_create_a_new_event():
    probe = _priority_probe()
    message = String()
    message.data = '停下'
    VoicePriorityStopNode.transcript_callback(probe, message)
    event_id = probe._last_event_id

    VoicePriorityStopNode.transcript_callback(probe, message)

    assert probe._last_event_id == event_id
    assert len(probe.priority_publisher.messages) == 1
    states = [
        json.loads(item)['state'] for item in probe.status_publisher.messages]
    assert 'debounced' in states


def test_priority_stop_debounce_has_an_exact_window_boundary():
    probe = _priority_probe()
    message = String()
    message.data = '停下'
    now_ns = 10_000_000_000
    original_monotonic_ns = time.monotonic_ns
    time.monotonic_ns = lambda: now_ns
    try:
        VoicePriorityStopNode.transcript_callback(probe, message)
        first_event_id = probe._last_event_id
        debounce_ns = int(probe.debounce_sec * 1_000_000_000)

        now_ns = 10_000_000_000 + debounce_ns - 1
        VoicePriorityStopNode.transcript_callback(probe, message)

        assert probe._last_event_id == first_event_id
        assert len(probe.priority_publisher.messages) == 1

        now_ns += 1
        VoicePriorityStopNode.transcript_callback(probe, message)
    finally:
        time.monotonic_ns = original_monotonic_ns

    assert probe._last_event_id != first_event_id
    assert len(probe.priority_publisher.messages) == 2
    states = [
        json.loads(item)['state'] for item in probe.status_publisher.messages]
    assert states.count('debounced') == 1
    assert states.count('superseded') == 1


def test_stop_ack_is_strict_correlated_and_observable():
    probe = _priority_probe()
    message = String()
    message.data = '停下'
    VoicePriorityStopNode.transcript_callback(probe, message)
    event_id = probe._last_event_id

    wrong = String()
    wrong.data = json.dumps(stop_ack_payload(
        'voice-stop-00000000wrong', probe._process_instance_id,
        'voice_dialogue', 'accepted',
        'wrong event'))
    VoicePriorityStopNode.ack_callback(probe, wrong)
    assert probe._active_event['ack_sources'] == {}

    malformed = String()
    malformed.data = '{"schema_version":1,"schema_version":1}'
    VoicePriorityStopNode.ack_callback(probe, malformed)
    assert probe._active_event['ack_sources'] == {}

    correct = String()
    correct.data = json.dumps(stop_ack_payload(
        event_id, probe._process_instance_id,
        'voice_dialogue', 'accepted', 'relayed'))
    VoicePriorityStopNode.ack_callback(probe, correct)
    assert probe._active_event['ack_sources'] == {
        'voice_dialogue': 'accepted'}
    states = [
        json.loads(item)['state'] for item in probe.status_publisher.messages]
    assert 'ignored_ack' in states
    assert 'invalid_ack' in states
    assert 'acknowledged' in states


@pytest.mark.parametrize('ack_state', ('rejected', 'error'))
def test_failed_or_expired_stop_ack_never_satisfies_ack_window(ack_state):
    probe = _priority_probe()
    message = String()
    message.data = '停下'
    VoicePriorityStopNode.transcript_callback(probe, message)
    event_id = probe._last_event_id

    failed = String()
    failed.data = json.dumps(stop_ack_payload(
        event_id, probe._process_instance_id,
        'voice_dialogue', ack_state, 'relay did not accept stop'))
    VoicePriorityStopNode.ack_callback(probe, failed)
    probe._active_event['attempt'] = probe.repeat_count
    probe._active_event['trigger_monotonic_ns'] = (
        time.monotonic_ns()
        - int(probe.ack_timeout_sec * 1_000_000_000) - 1)

    VoicePriorityStopNode.repeat_timer_callback(probe)

    assert probe._active_event is None
    states = [
        json.loads(item)['state'] for item in probe.status_publisher.messages]
    assert 'relay_acknowledged' not in states
    assert states[-1] == 'ack_timeout'

    expired = String()
    expired.data = json.dumps(stop_ack_payload(
        event_id, probe._process_instance_id,
        'voice_dialogue', 'accepted', 'late relay ACK'))
    VoicePriorityStopNode.ack_callback(probe, expired)

    assert probe._active_event is None
    states = [
        json.loads(item)['state'] for item in probe.status_publisher.messages]
    assert states[-1] == 'ignored_ack'
    assert 'relay_acknowledged' not in states


def test_stop_contract_rejects_duplicate_keys_and_keeps_navigation_exact():
    payload = stop_broadcast_payload(
        'voice-stop-000000001', 'voice-stop-process-test0001',
        '停下', 1, 3, 100, 200, 300, 400)
    assert parse_stop_broadcast(json.dumps(payload))['attempt'] == 1
    ack = stop_ack_payload(
        'voice-stop-000000001', 'voice-stop-process-test0001',
        'voice_dialogue', 'accepted', 'ok', 500, 600)
    assert parse_stop_ack(json.dumps(ack))['state'] == 'accepted'
    assert parse_stop_broadcast(json.dumps(payload))[
        'process_instance_id'] == 'voice-stop-process-test0001'
    assert parse_stop_ack(json.dumps(ack))[
        'process_instance_id'] == 'voice-stop-process-test0001'
    missing_broadcast_process = dict(payload)
    missing_broadcast_process.pop('process_instance_id')
    missing_ack_process = dict(ack)
    missing_ack_process.pop('process_instance_id')
    with pytest.raises(ValueError, match='fields do not match'):
        parse_stop_broadcast(json.dumps(missing_broadcast_process))
    with pytest.raises(ValueError, match='fields do not match'):
        parse_stop_ack(json.dumps(missing_ack_process))
    with pytest.raises(ValueError, match='invalid JSON'):
        parse_stop_broadcast('{"schema_version":3,"schema_version":3}')
    assert navigation_stop_payload() == {
        'action': 'cancel_navigation',
        'request_safe_stop': True,
    }


def test_priority_stop_ignores_non_stop_language():
    class Publisher:
        def __init__(self):
            self.messages = []

        def publish(self, message):
            self.messages.append(message.data)

    probe = _priority_probe()
    message = String()
    message.data = '小莫小莫，到垃圾桶旁边去'

    VoicePriorityStopNode.transcript_callback(probe, message)

    assert probe.priority_publisher.messages == []
    assert probe.stop_request_publisher.messages == []


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
def test_priority_stop_ignores_negated_or_quoted_stop_language(text):
    """A stop token in negated/meta speech must not broadcast a stop."""
    probe = _priority_probe()
    message = String()
    message.data = text

    VoicePriorityStopNode.transcript_callback(probe, message)

    assert probe.priority_publisher.messages == []
    assert probe.stop_request_publisher.messages == []


@pytest.mark.parametrize('text', (
    '不要确认',
    '不能确认',
    '还没确认',
    '我不确定',
    '不要执行',
    '不可以',
    '不是的',
))
def test_negated_confirmation_cannot_forward_pending_navigation(text):
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫，到垃圾桶旁边去')

    send_dialogue(probe, text)

    assert probe.navigation_requests == []
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] != 'confirm'


@pytest.mark.parametrize('text', ('不确认', '不要执行', '算了'))
def test_explicit_rejection_clears_pending_without_forwarding(text):
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫，到垃圾桶旁边去')

    send_dialogue(probe, text)

    assert probe.pending_command is None
    assert probe.navigation_requests == []
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'reject_confirmation'


@pytest.mark.parametrize('text', (
    '确认？', '执行？', '可以？', '是的？',
    'confirm?', 'yes?',
))
def test_question_confirmation_preserves_pending_without_forwarding(text):
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫，到垃圾桶旁边去')

    send_dialogue(probe, text)

    assert probe.pending_command == '到垃圾桶旁边'
    assert probe.navigation_requests == []
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] != 'confirm'


@pytest.mark.parametrize('text', (
    '小莫小莫，不要到垃圾桶旁边去',
    '小莫小莫，不要识别矿泉水瓶',
    '小莫小莫，不要捡矿泉水瓶',
    '小莫小莫，别触碰矿泉水瓶',
))
def test_negated_task_does_not_enter_confirmation_state(text):
    probe = DialogueProbe()

    send_dialogue(probe, text)

    assert probe.pending_command is None
    assert probe.navigation_requests == []
    assert probe.perception_requests == []
    assert probe.forwarded == []


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
def test_reported_or_indirect_task_does_not_enter_confirmation_state(text):
    probe = DialogueProbe()

    send_dialogue(probe, text)

    assert probe.pending_command is None
    assert probe.navigation_requests == []
    assert probe.perception_requests == []
    assert probe.forwarded == []


def test_priority_broadcast_clears_pending_without_duplicate_stop_output():
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫，捡塑料瓶')
    broadcast = String()
    broadcast.data = json.dumps(stop_broadcast_payload(
        'voice-stop-000000001', 'voice-stop-process-test0001',
        '停下', 1, 3, 100, 200, 300, 400),
        ensure_ascii=False)

    VoiceDialogueNode.priority_broadcast_callback(probe, broadcast)

    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.intents[-1]['reason'] == (
        'independent priority stop broadcast')

    send_dialogue(probe, '确认')
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'ignored'
    assert probe.intents[-1]['reason'] == 'wake word was not heard'


def test_priority_stop_request_relays_exact_outputs_and_acknowledges():
    probe = DialogueProbe()
    probe.pending_command = '捡塑料瓶'
    probe.pending_intent_name = 'start_cleanup'
    probe.pending_deadline = time.monotonic() + 10.0
    request = String()
    request.data = json.dumps(stop_broadcast_payload(
        'voice-stop-000000001', 'voice-stop-process-test0001',
        '停下', 1, 3, 100, 200, 300, 400),
        ensure_ascii=False)

    VoiceDialogueNode.priority_stop_request_callback(probe, request)

    assert probe.pending_command is None
    assert probe.forwarded == ['停止任务']
    assert json.loads(probe.navigation_requests[0]) == {
        'action': 'cancel_navigation',
        'request_safe_stop': True,
    }
    acknowledgement = parse_stop_ack(probe.stop_acks[0])
    assert acknowledgement['event_id'] == 'voice-stop-000000001'
    assert acknowledgement['source'] == 'voice_dialogue'
    assert acknowledgement['state'] == 'accepted'


def test_bottle_inspection_requires_confirmation_and_never_moves():
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫，识别矿泉水瓶')

    assert probe.perception_requests == []
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    send_dialogue(probe, '确认')

    assert json.loads(probe.perception_requests[0]) == (
        perception_inspect_payload())
    assert probe.forwarded == []
    assert probe.navigation_requests == []


@pytest.mark.parametrize('text,intent_name,canonical_command', (
    ('小莫小莫，捡瓶子', 'start_cleanup', '捡塑料瓶'),
    ('小莫小莫，识别瓶子', 'inspect_bottle', '识别矿泉水瓶'),
))
def test_bottle_voice_alias_stays_pending_and_high_level_only(
        text, intent_name, canonical_command):
    probe = DialogueProbe()

    send_dialogue(probe, text)

    assert probe.pending_intent_name == intent_name
    assert probe.pending_command == canonical_command
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.perception_requests == []
    assert probe.intents[-1]['forwarded'] is False


@pytest.mark.parametrize('text', (
    '捡瓶子',
    '小莫小莫，捡瓶盖',
    '小莫小莫，识别瓶装水',
    '小莫小莫，不要捡瓶子',
))
def test_bottle_alias_negative_cases_never_create_pending_or_output(text):
    probe = DialogueProbe()

    send_dialogue(probe, text)

    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.perception_requests == []


def test_semantic_agent_normalizes_only_non_stop_candidates():
    waypoint = normalize_non_stop_semantics('小莫小莫，你去桶边等着')
    bottle = normalize_non_stop_semantics('小莫小莫，处理一下那个瓶子')
    speaker = normalize_non_stop_semantics('小莫小莫，过来我这边')
    cleanup = normalize_non_stop_semantics('小莫小莫，丢垃圾丢垃圾')

    assert waypoint.canonical_text == '小莫小莫，到垃圾桶旁边去'
    assert bottle.canonical_text == '小莫小莫，捡塑料瓶'
    assert speaker.canonical_text == '小莫小莫，到这里来'
    assert cleanup.canonical_text == '小莫小莫，开始清理'
    assert normalize_non_stop_semantics('停下') is None


@pytest.mark.parametrize('text', (
    '小莫小莫，我喜欢去垃圾桶那里拍照',
    '小莫小莫，讨论处理一下那个瓶子的方案',
    '小莫小莫，识别一下那个瓶子的说法很自然',
    '小莫小莫，等会儿再靠近我',
    '小莫小莫，丢垃圾丢垃圾以后记得汇报',
))
def test_semantic_agent_does_not_promote_phrase_substrings(text):
    candidate = normalize_non_stop_semantics(text)

    assert candidate is not None
    assert candidate.canonical_text == text


@pytest.mark.parametrize('text, canonical', (
    ('小莫小莫，请你去桶边等着吧', '小莫小莫，到垃圾桶旁边去'),
    ('小莫小莫，麻烦你处理一下那个瓶子', '小莫小莫，捡塑料瓶'),
    ('小莫小莫，帮我识别一下那个瓶子', '小莫小莫，识别矿泉水瓶'),
))
def test_semantic_agent_accepts_only_bounded_polite_wrappers(
        text, canonical):
    candidate = normalize_non_stop_semantics(text)

    assert candidate is not None
    assert candidate.canonical_text == canonical


@pytest.mark.parametrize('raw_text', (
    '小莫小莫，丢垃圾',
    '小莫小莫，丢 垃圾 丢 垃圾',
))
def test_user_labeled_cleanup_alias_requires_confirmation(raw_text):
    candidate = normalize_non_stop_semantics(raw_text)
    parsed = parse_command(
        candidate.canonical_text,
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )

    assert candidate.canonical_text == '小莫小莫，开始清理'
    assert parsed.name == 'start_cleanup'
    assert parsed.command_text == '捡垃圾'
    assert parsed.requires_confirmation is True


@pytest.mark.parametrize('raw_text', (
    '丢垃圾',
    '丢垃圾丢垃圾',
    '小莫小莫，别丢垃圾',
    '小莫小莫，丢垃圾桶',
    '小莫小莫，这是丢垃圾的例句',
))
def test_user_labeled_cleanup_alias_fails_closed_outside_exact_gate(raw_text):
    candidate = normalize_non_stop_semantics(raw_text)
    parsed = parse_command(
        candidate.canonical_text,
        wake_words=['小莫小莫'],
        require_wake_word=True,
    )

    assert parsed.name in ('ignored', 'unsupported')
    assert parsed.requires_confirmation is False


def test_wake_only_then_user_labeled_command_enters_confirmation_once():
    probe = DialogueProbe()

    send_dialogue(probe, '小莫小莫')

    assert probe.wake_window_active() is True
    assert probe.pending_command is None
    assert probe.responses[-1] == '我在，请说指令。'

    candidate = normalize_non_stop_semantics('丢 垃圾 丢 垃圾')
    candidate_message = String()
    candidate_message.data = json.dumps(semantic_candidate_payload(
        candidate.raw_text,
        candidate.canonical_text,
        candidate.source,
        1.0,
    ), ensure_ascii=False)
    VoiceDialogueNode.semantic_candidate_callback(probe, candidate_message)

    assert probe.wake_window_active() is False
    assert probe.pending_intent_name == 'start_cleanup'
    assert probe.pending_command == '捡垃圾'
    assert probe.forwarded == []


def test_wake_only_window_expires_and_never_creates_pending():
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫')
    probe.wake_deadline = time.monotonic() - 1.0

    candidate = normalize_non_stop_semantics('丢垃圾')
    VoiceDialogueNode.process_transcript(
        probe, candidate.raw_text, candidate.canonical_text)

    assert probe.wake_window_active() is False
    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'ignored'


def test_wake_only_window_is_consumed_by_unsupported_language():
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫')

    send_dialogue(probe, '今天天气不错')
    send_dialogue(probe, '捡矿泉水瓶')

    assert probe.wake_window_active() is False
    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'ignored'


@pytest.mark.parametrize('text', (
    '不要丢垃圾',
    '这是丢垃圾的例句',
    '捡矿泉水瓶还是丢垃圾',
    '今天天气不错',
))
def test_wake_window_fail_closed_language_is_one_shot(text):
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫')

    candidate = normalize_non_stop_semantics(text)
    VoiceDialogueNode.process_transcript(
        probe, candidate.raw_text, candidate.canonical_text)

    assert probe.wake_window_active() is False
    assert probe.pending_command is None
    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert probe.perception_requests == []


def test_near_wake_never_arms_next_ordinary_intent():
    probe = DialogueProbe()

    send_dialogue(probe, '小魔小魔')
    candidate = normalize_non_stop_semantics('捡矿泉水瓶')
    VoiceDialogueNode.process_transcript(
        probe, candidate.raw_text, candidate.canonical_text)

    assert probe.wake_window_active() is False
    assert probe.pending_command is None
    assert probe.intents[-1]['intent'] == 'ignored'


def test_wake_window_has_exact_deadline_boundary(monkeypatch):
    probe = DialogueProbe()
    probe.wake_deadline = 105.0
    now = {'value': 105.0}
    monkeypatch.setattr(time, 'monotonic', lambda: now['value'])

    assert probe.wake_window_active() is True
    now['value'] = 105.000001
    assert probe.wake_window_active() is False


def test_repeated_complete_wake_refreshes_one_shot_deadline(monkeypatch):
    probe = DialogueProbe()
    now = {'value': 100.0}
    monkeypatch.setattr(time, 'monotonic', lambda: now['value'])

    send_dialogue(probe, '小莫小莫')
    assert probe.wake_deadline == 105.0
    now['value'] = 104.0
    send_dialogue(probe, '小莫小莫')

    assert probe.wake_deadline == 109.0
    assert probe.pending_command is None


def test_priority_stop_clears_wake_only_window():
    probe = DialogueProbe()
    send_dialogue(probe, '小莫小莫')
    request = String()
    request.data = json.dumps(stop_broadcast_payload(
        'voice-stop-000000001', 'voice-stop-process-test0001',
        '停下', 1, 3, 100, 200, 300, 400),
        ensure_ascii=False)

    VoiceDialogueNode.priority_broadcast_callback(probe, request)

    assert probe.wake_window_active() is False
    assert probe.pending_command is None
    assert probe.forwarded == []


@pytest.mark.parametrize('text', (
    '小莫小莫，我不想你去桶边等着',
    '小莫小莫，不应该去垃圾桶那边',
    '小莫小莫，我正在学说去桶边等着',
    '小莫小莫，请问你会处理一下那个瓶子',
    '小莫小莫，别让他处理那个瓶子',
    '小莫小莫，如果需要就去桶边等着',
    '小莫小莫，我教你说去桶边等着',
    '小莫小莫，听到处理一下那个瓶子会怎样',
    '小莫小莫，这是去桶边等着的例句',
    '小莫小莫，我不赞成去桶边等着',
    '小莫小莫，我反对处理那个瓶子',
    '小莫小莫，不同意去垃圾桶那边',
    '小莫小莫，字幕是处理一下那个瓶子',
))
def test_semantic_agent_never_erases_fail_closed_context(text):
    candidate = normalize_non_stop_semantics(text)

    assert candidate.canonical_text == text


def test_semantic_node_suppresses_stop_and_publishes_candidate():
    published = []
    probe = SimpleNamespace(
        publisher=SimpleNamespace(
            publish=lambda message: published.append(message.data)))
    stop = String()
    stop.data = '停下'
    waypoint = String()
    waypoint.data = '小莫小莫，你去桶边等着'

    VoiceSemanticAgentNode.transcript_callback(probe, stop)
    VoiceSemanticAgentNode.transcript_callback(probe, waypoint)

    assert len(published) == 1
    parsed = parse_semantic_candidate(published[0])
    assert parsed['raw_text'] == '小莫小莫，你去桶边等着'
    assert parsed['canonical_text'] == '小莫小莫，到垃圾桶旁边去'
    assert parsed['source'] == 'bounded_rules'
    assert parsed['confidence'] == 1.0


def test_dialogue_rejects_agent_stop_and_unknown_schema_fields():
    probe = DialogueProbe()
    stop_candidate = String()
    stop_candidate.data = json.dumps(semantic_candidate_payload(
        '请停下', '停下', 'untrusted_agent', 0.9), ensure_ascii=False)
    unknown_field = String()
    unknown_payload = semantic_candidate_payload(
        '小莫小莫，去桶边等着', '小莫小莫，到垃圾桶旁边去',
        'untrusted_agent', 0.9)
    unknown_payload['velocity'] = 1.0
    unknown_field.data = json.dumps(unknown_payload, ensure_ascii=False)

    VoiceDialogueNode.semantic_candidate_callback(probe, stop_candidate)
    VoiceDialogueNode.semantic_candidate_callback(probe, unknown_field)

    assert probe.forwarded == []
    assert probe.navigation_requests == []
    assert [item['intent'] for item in probe.intents] == [
        'semantic_rejected', 'semantic_rejected']


def test_semantic_candidate_still_uses_confirmation_gate():
    probe = DialogueProbe()
    candidate = String()
    candidate.data = json.dumps(semantic_candidate_payload(
        '小莫小莫，你去桶边等着', '小莫小莫，到垃圾桶旁边去',
        'bounded_rules', 1.0), ensure_ascii=False)

    VoiceDialogueNode.semantic_candidate_callback(probe, candidate)

    assert probe.pending_intent_name == 'navigate_to_bin'
    assert probe.navigation_requests == []
    assert probe.intents[-1]['raw_text'] == '小莫小莫，你去桶边等着'


@pytest.mark.parametrize('raw_text,canonical_text', (
    ('去垃圾桶旁边', '小莫小莫，到垃圾桶旁边去'),
    ('识别矿泉水瓶', '小莫小莫，识别矿泉水瓶'),
    ('小莫小莫，去垃圾桶旁边', '到垃圾桶旁边去'),
))
def test_semantic_candidate_cannot_change_wake_word_state(
        raw_text, canonical_text):
    probe = DialogueProbe()
    candidate = String()
    candidate.data = json.dumps(semantic_candidate_payload(
        raw_text, canonical_text, 'untrusted_agent', 1.0),
        ensure_ascii=False)

    VoiceDialogueNode.semantic_candidate_callback(probe, candidate)

    assert probe.pending_command is None
    assert probe.navigation_requests == []
    assert probe.perception_requests == []
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'semantic_rejected'
    assert probe.intents[-1]['reason'] == (
        'semantic candidate may not change wake-word state')


@pytest.mark.parametrize('raw_text,canonical_text', (
    ('今天天气不错', '确认'),
    ('不要确认', '确认'),
    ('确认', '今天天气不错'),
    ('取消', '确认'),
))
def test_semantic_candidate_cannot_change_confirmation_state(
        raw_text, canonical_text):
    probe = DialogueProbe()
    probe.pending_command = '到垃圾桶旁边'
    probe.pending_intent_name = 'navigate_to_bin'
    probe.pending_raw_text = '小莫小莫，到垃圾桶旁边去'
    probe.pending_deadline = time.monotonic() + 10.0
    candidate = String()
    candidate.data = json.dumps(semantic_candidate_payload(
        raw_text, canonical_text, 'untrusted_agent', 1.0),
        ensure_ascii=False)

    VoiceDialogueNode.semantic_candidate_callback(probe, candidate)

    assert probe.pending_command == '到垃圾桶旁边'
    assert probe.navigation_requests == []
    assert probe.perception_requests == []
    assert probe.forwarded == []
    assert probe.intents[-1]['intent'] == 'semantic_rejected'
    assert probe.intents[-1]['reason'] == (
        'semantic candidate may not change confirmation state')


def test_rollback_and_field_acceptance_templates_cover_safety_boundaries():
    package_root = Path(__file__).resolve().parents[1]
    rollback = (
        package_root / 'docs' / 'VOICE_DEPLOYMENT_ROLLBACK.md'
    ).read_text(encoding='utf-8')
    acceptance = (
        package_root / 'docs' / 'VOICE_FIELD_ACCEPTANCE_TEMPLATE.md'
    ).read_text(encoding='utf-8')

    assert 'VOICE_BRIDGE_EXACT_PAYLOAD_READONLY_PASS' in rollback
    assert '到这里来' in rollback
    assert 'voice_input_mode:=text' in rollback
    assert 'Physical emergency-stop check completed' in acceptance
    assert 'trash_bin_staging' in acceptance
    assert 'silence/background/ordinary speech' in acceptance
    assert 'BLOCKED_ROS1_ADAPTER_OFFLINE_ONLY' in acceptance
    assert 'process_instance_id' in acceptance
    assert 'not a safety gate' in acceptance
    assert 'offline_text_mock' in acceptance


def test_production_voice_nodes_have_no_motion_command_interfaces():
    package_root = Path(__file__).resolve().parents[1]
    production_files = [
        package_root / 'limo_cleanup_voice' / 'command_parser.py',
        package_root / 'limo_cleanup_voice' / 'semantic_agent.py',
        package_root / 'limo_cleanup_voice' / 'voice_asr_node.py',
        package_root / 'limo_cleanup_voice' / 'voice_corpus_readiness.py',
        package_root / 'limo_cleanup_voice' / 'voice_dialogue_node.py',
        package_root / 'limo_cleanup_voice' / 'voice_priority_stop_node.py',
        package_root / 'limo_cleanup_voice' / 'voice_semantic_agent_node.py',
        package_root / 'limo_cleanup_voice' / 'voice_tts_node.py',
        package_root / 'package.xml',
    ]
    forbidden_tokens = (
        '/cmd_vel', 'geometry_msgs', 'Twist', 'FollowJointTrajectory',
        'power_on', '/cleanup/gripper', 'nav2_msgs',
    )

    combined_source = '\n'.join(
        path.read_text(encoding='utf-8') for path in production_files)

    for token in forbidden_tokens:
        assert token not in combined_source


def test_full_system_voice_launch_pins_no_hardware_mode():
    package_root = Path(__file__).resolve().parents[1]
    launch_source = (
        package_root / 'launch' / 'full_system_with_voice.launch.py'
    ).read_text(encoding='utf-8')
    required_settings = (
        "'use_mock_perception': 'true'",
        "'use_real_perception': 'false'",
        "'use_mock_executor': 'true'",
        "'executor_dry_run': 'true'",
        "'allow_arm_motion': 'false'",
        "'use_gripper_controller': 'false'",
        "'allow_gripper_motion': 'false'",
        "'use_tracked_base_controller': 'false'",
        "'allow_base_motion': 'false'",
    )

    for setting in required_settings:
        assert setting in launch_source


def test_voice_launch_keeps_foxy_override_fix_and_timeout_parameter():
    package_root = Path(__file__).resolve().parents[1]
    launch_source = (
        package_root / 'launch' / 'voice_dialogue.launch.py'
    ).read_text(encoding='utf-8')

    assert 'voice_dialogue.yaml' not in launch_source
    assert "DeclareLaunchArgument('input_mode', default_value='text')" in (
        launch_source)
    assert "'confirmation_timeout_sec'" in launch_source
    assert "DeclareLaunchArgument('require_wake_word', default_value='true')" \
        in launch_source
    assert "DeclareLaunchArgument('enable_semantic_agent'" in launch_source
    assert "executable='voice_priority_stop'" in launch_source
    assert "DeclareLaunchArgument('enable_priority_stop'" not in launch_source


@pytest.fixture
def cross_module_voice_contract_fixture():
    """Build production-callback probes without initializing a ROS graph."""
    def semantic_candidate(raw_text):
        published = []
        agent_probe = SimpleNamespace(
            publisher=SimpleNamespace(
                publish=lambda message: published.append(message.data)))
        transcript = String()
        transcript.data = raw_text

        VoiceSemanticAgentNode.transcript_callback(agent_probe, transcript)

        assert len(published) == 1
        message = String()
        message.data = published[0]
        return message, parse_semantic_candidate(message.data)

    def priority_stop_event(raw_text='停下'):
        priority_probe = _priority_probe()
        transcript = String()
        transcript.data = raw_text

        VoicePriorityStopNode.transcript_callback(priority_probe, transcript)

        assert priority_probe.priority_publisher.messages == (
            priority_probe.stop_request_publisher.messages)
        assert len(priority_probe.stop_request_publisher.messages) == 1
        request = String()
        request.data = priority_probe.stop_request_publisher.messages[0]
        return (
            priority_probe,
            request,
            parse_stop_broadcast(request.data),
        )

    def string_values(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield str(key)
                yield from string_values(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from string_values(item)
        elif isinstance(value, str):
            yield value

    def assert_high_level_only(*outputs):
        values = tuple(string_values(outputs))
        rendered = '\n'.join(values).casefold()
        forbidden = (
            '/cmd_vel', 'cmd_vel', 'twist', 'geometry_msgs',
            'nav2_msgs', 'move_base', 'navigate_to_pose', '/_action/',
            'actionclient', 'actionserver', 'rclpy.action',
            'followjointtrajectory', 'jointtrajectory', 'control_msgs',
            '/_service/', 'serviceclient', 'create_client', 'call_async',
            '/dev/', 'device', 'ttyusb', 'serial', 'can0',
            'controller_manager', 'gripper_controller', 'power_on',
            'hardware', '设备', '硬件',
        )
        for token in forbidden:
            assert token not in rendered
        assert all(not item.startswith('/') for item in values)

    return SimpleNamespace(
        semantic_candidate=semantic_candidate,
        priority_stop_event=priority_stop_event,
        assert_high_level_only=assert_high_level_only,
    )


def test_cross_module_stop_remains_an_internal_high_level_event(
        cross_module_voice_contract_fixture):
    contract = cross_module_voice_contract_fixture
    _, request, event = contract.priority_stop_event()
    dialogue = DialogueProbe()

    VoiceDialogueNode.priority_stop_request_callback(dialogue, request)

    navigation = json.loads(dialogue.navigation_requests[0])
    acknowledgement = parse_stop_ack(dialogue.stop_acks[0])
    assert event['intent'] == 'stop_task'
    assert event['source'] == 'voice_priority_stop'
    assert dialogue.forwarded == ['停止任务']
    assert navigation == navigation_stop_payload()
    assert acknowledgement['source'] == 'voice_dialogue'
    assert acknowledgement['state'] == 'accepted'
    contract.assert_high_level_only(
        event,
        dialogue.forwarded,
        navigation,
        acknowledgement,
        dialogue.intents,
    )


def test_cross_module_candidates_require_confirmation_before_high_level_output(
        cross_module_voice_contract_fixture):
    contract = cross_module_voice_contract_fixture
    navigation_message, navigation_candidate = contract.semantic_candidate(
        '小莫小莫，你去桶边等着')
    navigation_dialogue = DialogueProbe()

    VoiceDialogueNode.semantic_candidate_callback(
        navigation_dialogue, navigation_message)

    assert navigation_dialogue.pending_intent_name == 'navigate_to_bin'
    assert navigation_dialogue.navigation_requests == []
    send_dialogue(navigation_dialogue, '确认')
    navigation = json.loads(navigation_dialogue.navigation_requests[0])
    assert navigation == navigation_waypoint_payload()

    bottle_message, bottle_candidate = contract.semantic_candidate(
        '小莫小莫，识别一下那个瓶子')
    bottle_dialogue = DialogueProbe()

    VoiceDialogueNode.semantic_candidate_callback(
        bottle_dialogue, bottle_message)

    assert bottle_dialogue.pending_intent_name == 'inspect_bottle'
    assert bottle_dialogue.perception_requests == []
    send_dialogue(bottle_dialogue, '确认')
    perception = json.loads(bottle_dialogue.perception_requests[0])
    assert perception == perception_inspect_payload()
    assert navigation_candidate['source'] == 'bounded_rules'
    assert bottle_candidate['source'] == 'bounded_rules'
    contract.assert_high_level_only(
        navigation_candidate,
        navigation,
        bottle_candidate,
        perception,
        navigation_dialogue.intents,
        bottle_dialogue.intents,
    )


def test_cross_module_timeout_and_cancel_never_emit_executable_output(
        cross_module_voice_contract_fixture):
    contract = cross_module_voice_contract_fixture
    timeout_message, timeout_candidate = contract.semantic_candidate(
        '小莫小莫，你去桶边等着')
    timeout_dialogue = DialogueProbe()
    VoiceDialogueNode.semantic_candidate_callback(
        timeout_dialogue, timeout_message)
    timeout_dialogue.pending_deadline = time.monotonic() - 1.0

    send_dialogue(timeout_dialogue, '确认')

    assert timeout_dialogue.pending_command is None
    assert timeout_dialogue.forwarded == []
    assert timeout_dialogue.navigation_requests == []
    assert timeout_dialogue.perception_requests == []
    assert timeout_dialogue.intents[-1]['reason'] == 'confirmation expired'

    cancel_message, cancel_candidate = contract.semantic_candidate(
        '小莫小莫，识别一下那个瓶子')
    cancel_dialogue = DialogueProbe()
    VoiceDialogueNode.semantic_candidate_callback(
        cancel_dialogue, cancel_message)

    send_dialogue(cancel_dialogue, '取消')

    assert cancel_dialogue.pending_command is None
    assert cancel_dialogue.forwarded == []
    assert cancel_dialogue.navigation_requests == []
    assert cancel_dialogue.perception_requests == []
    assert cancel_dialogue.intents[-1]['forwarded'] is False
    contract.assert_high_level_only(
        timeout_candidate,
        timeout_dialogue.intents,
        cancel_candidate,
        cancel_dialogue.intents,
    )
