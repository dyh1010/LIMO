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

"""Text fallback and optional offline Vosk speech recognition adapter."""

import audioop
import json
import queue
import threading
import wave

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


DEFAULT_GRAMMAR = [
    '小莫 开始 清理', '机器人 开始 清理',
    '小莫 捡 塑料瓶', '机器人 捡 塑料瓶',
    '小莫 捡 易拉罐', '机器人 捡 易拉罐',
    '小莫 捡 纸盒', '机器人 捡 纸盒',
    '小莫 捡 垃圾', '机器人 捡 垃圾',
    '小莫 碰 一下 塑料瓶', '机器人 碰 一下 塑料瓶',
    '小莫 报告 状态', '机器人 报告 状态',
    '确认', '取消', '停止 任务', '紧急 停止', '[unk]',
]

UNKNOWN_TRANSCRIPTS = {'[unk]', '<unk>'}


def is_unknown_transcript(text: str) -> bool:
    """Return true for Vosk's explicit out-of-vocabulary markers."""
    return text.strip().lower() in UNKNOWN_TRANSCRIPTS


class VoiceAsrNode(Node):
    """Publish transcripts from text input, a WAV file, or a microphone."""

    def __init__(self) -> None:
        super().__init__('voice_asr')
        self.declare_parameter('input_mode', 'text')
        self.declare_parameter('text_input_topic', '/voice/text_input')
        self.declare_parameter('transcript_topic', '/voice/transcript')
        self.declare_parameter('status_topic', '/voice/asr_status')
        self.declare_parameter('vosk_model_path', '')
        self.declare_parameter('wav_path', '')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('input_sample_rate', 0)
        self.declare_parameter('block_size', 8000)
        self.declare_parameter('microphone_device', '')
        self.declare_parameter('grammar_phrases', DEFAULT_GRAMMAR)

        self.mode = str(self.get_parameter('input_mode').value)
        status_qos = QoSProfile(depth=10)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.transcript_publisher = self.create_publisher(
            String, self.get_parameter('transcript_topic').value, 10)
        self.status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value, status_qos)
        self.audio_queue = queue.Queue(maxsize=32)
        self.audio_stream = None
        self.recognizer = None
        self.resample_state = None
        self.capture_sample_rate = 0
        self.recognizer_sample_rate = 0
        self.get_logger().info(
            'Initializing voice ASR; mode={}'.format(self.mode))

        if self.mode == 'text':
            self.create_subscription(
                String,
                self.get_parameter('text_input_topic').value,
                self.text_callback,
                10,
            )
            self.publish_status('ready', 'Text fallback mode is ready')
        elif self.mode == 'vosk_microphone':
            self.start_microphone_mode()
        elif self.mode == 'vosk_wav_once':
            self.start_wav_mode()
        else:
            raise ValueError('Unsupported input_mode: {}'.format(self.mode))

    def text_callback(self, message: String) -> None:
        self.publish_transcript(message.data.strip(), 'text')

    def create_recognizer(self, sample_rate: int):
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError(
                'Vosk is not installed; use input_mode=text or install vosk') \
                from error

        model_path = str(self.get_parameter('vosk_model_path').value).strip()
        if not model_path:
            raise RuntimeError('vosk_model_path is required for Vosk modes')
        model = Model(model_path)
        grammar = list(self.get_parameter('grammar_phrases').value)
        return KaldiRecognizer(
            model, float(sample_rate), json.dumps(grammar, ensure_ascii=False))

    def start_microphone_mode(self) -> None:
        self.get_logger().info('Importing sounddevice for microphone mode')
        try:
            import sounddevice
        except ImportError as error:
            raise RuntimeError(
                'sounddevice is not installed; use text mode or install it') \
                from error

        sample_rate = int(self.get_parameter('sample_rate').value)
        input_sample_rate = int(
            self.get_parameter('input_sample_rate').value)
        block_size = int(self.get_parameter('block_size').value)
        device_text = str(
            self.get_parameter('microphone_device').value).strip()
        device = None
        if device_text:
            device = int(device_text) if device_text.isdigit() else device_text

        self.get_logger().info(
            'Resolving microphone device and native sample rate')
        if input_sample_rate <= 0:
            device_info = sounddevice.query_devices(device, 'input')
            input_sample_rate = int(round(device_info['default_samplerate']))

        self.capture_sample_rate = input_sample_rate
        self.recognizer_sample_rate = sample_rate
        self.get_logger().info('Loading offline Vosk model')
        self.recognizer = self.create_recognizer(sample_rate)
        self.get_logger().info('Offline Vosk model loaded')

        def audio_callback(indata, frames, time_info, status):
            del frames, time_info
            if status:
                self.get_logger().warning(str(status))
            audio_bytes = bytes(indata)
            if self.capture_sample_rate != self.recognizer_sample_rate:
                audio_bytes, self.resample_state = audioop.ratecv(
                    audio_bytes,
                    2,
                    1,
                    self.capture_sample_rate,
                    self.recognizer_sample_rate,
                    self.resample_state,
                )
            try:
                self.audio_queue.put_nowait(audio_bytes)
            except queue.Full:
                self.get_logger().warning('Audio queue is full; dropping block')

        self.get_logger().info('Opening PortAudio input stream')
        self.audio_stream = sounddevice.RawInputStream(
            samplerate=input_sample_rate,
            blocksize=block_size,
            device=device,
            dtype='int16',
            channels=1,
            callback=audio_callback,
        )
        self.get_logger().info('Starting PortAudio input stream')
        self.audio_stream.start()
        self.create_timer(0.05, self.drain_audio_queue)
        self.publish_status(
            'ready',
            'Offline Vosk microphone mode is ready',
            capture_sample_rate=input_sample_rate,
            recognizer_sample_rate=sample_rate,
        )
        self.get_logger().info(
            'Offline Vosk microphone ready; capture_rate={}Hz; '
            'recognizer_rate={}Hz; device={}'.format(
                input_sample_rate, sample_rate, device))

    def drain_audio_queue(self) -> None:
        while True:
            try:
                data = self.audio_queue.get_nowait()
            except queue.Empty:
                return
            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                self.publish_transcript(result.get('text', '').strip(), 'vosk')

    def start_wav_mode(self) -> None:
        worker = threading.Thread(target=self.process_wav, daemon=True)
        worker.start()
        self.publish_status('running', 'Reading one WAV file with Vosk')

    def process_wav(self) -> None:
        wav_path = str(self.get_parameter('wav_path').value).strip()
        if not wav_path:
            self.publish_status('error', 'wav_path is required')
            return
        try:
            with wave.open(wav_path, 'rb') as wav_file:
                if wav_file.getnchannels() != 1:
                    raise ValueError('WAV input must be mono')
                if wav_file.getsampwidth() != 2:
                    raise ValueError('WAV input must use 16-bit PCM samples')
                recognizer = self.create_recognizer(wav_file.getframerate())
                while rclpy.ok():
                    data = wav_file.readframes(4000)
                    if not data:
                        break
                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        self.publish_transcript(
                            result.get('text', '').strip(), 'vosk_wav')
                final_result = json.loads(recognizer.FinalResult())
                self.publish_transcript(
                    final_result.get('text', '').strip(), 'vosk_wav')
            self.publish_status('completed', 'WAV recognition completed')
        except Exception as error:  # noqa: BLE001
            self.publish_status('error', str(error))

    def publish_transcript(self, text: str, source: str) -> None:
        cleaned_text = text.strip()
        if not cleaned_text:
            return
        if is_unknown_transcript(cleaned_text):
            self.publish_status(
                'ignored', 'Unknown speech token ignored',
                source=source, text=cleaned_text)
            return
        message = String()
        message.data = cleaned_text
        self.transcript_publisher.publish(message)
        self.publish_status(
            'recognized', 'Transcript published',
            source=source, text=cleaned_text)

    def publish_status(self, state: str, detail: str, **extra) -> None:
        payload = {'state': state, 'detail': detail, 'mode': self.mode}
        payload.update(extra)
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.status_publisher.publish(message)

    def destroy_node(self):
        if self.audio_stream is not None:
            self.audio_stream.stop()
            self.audio_stream.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceAsrNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
