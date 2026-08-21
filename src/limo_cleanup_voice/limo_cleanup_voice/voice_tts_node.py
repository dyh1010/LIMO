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

"""LEGACY_ROS2_OFFLINE_ONLY TTS wrapper; not a Noetic field node."""

import json
import queue
import subprocess
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class VoiceTtsNode(Node):
    """Speak dialogue responses without invoking a command shell."""

    def __init__(self) -> None:
        super().__init__('voice_tts')
        self.declare_parameter('backend', 'none')
        self.declare_parameter('response_topic', '/voice/response_text')
        self.declare_parameter('status_topic', '/voice/tts_status')
        self.declare_parameter('executable', 'espeak-ng')
        self.declare_parameter('voice', 'cmn')
        self.declare_parameter('rate', 155)

        self.backend = str(self.get_parameter('backend').value)
        self.speech_queue = queue.Queue(maxsize=10)
        self.status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value, 10)
        self.create_subscription(
            String,
            self.get_parameter('response_topic').value,
            self.response_callback,
            10,
        )

        self.worker = threading.Thread(target=self.speech_worker, daemon=True)
        self.worker.start()
        self.publish_status('ready', 'TTS backend: {}'.format(self.backend))

    def response_callback(self, message: String) -> None:
        text = message.data.strip()
        if not text:
            return
        try:
            self.speech_queue.put_nowait(text)
        except queue.Full:
            self.publish_status('busy', 'Speech queue is full')

    def speech_worker(self) -> None:
        while rclpy.ok():
            try:
                text = self.speech_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.backend == 'none':
                self.publish_status('muted', text)
                continue
            if self.backend != 'espeak_ng':
                self.publish_status(
                    'error', 'Unsupported TTS backend: {}'.format(self.backend))
                continue
            try:
                subprocess.run(
                    [
                        str(self.get_parameter('executable').value),
                        '-v', str(self.get_parameter('voice').value),
                        '-s', str(int(self.get_parameter('rate').value)),
                        text,
                    ],
                    check=True,
                    timeout=20.0,
                )
                self.publish_status('spoken', text)
            except Exception as error:  # noqa: BLE001
                self.publish_status('error', str(error))

    def publish_status(self, state: str, detail: str) -> None:
        message = String()
        message.data = json.dumps(
            {'state': state, 'detail': detail}, ensure_ascii=False)
        self.status_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceTtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
