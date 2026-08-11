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

"""ROS graph probe for the text-mode voice safety gate."""

import time

import rclpy
from limo_cleanup_interfaces.msg import CleanupTask
from rclpy.node import Node
from std_msgs.msg import String


class VoiceSmokeProbe(Node):
    """Exercise confirmation and cancellation through public ROS topics."""

    def __init__(self) -> None:
        super().__init__('voice_smoke_probe')
        self.text_publisher = self.create_publisher(
            String, '/voice/text_input', 10)
        self.transcripts = []
        self.responses = []
        self.tasks = []
        self.create_subscription(
            String, '/voice/transcript', self.transcript_callback, 10)
        self.create_subscription(
            String, '/voice/response_text', self.response_callback, 10)
        self.create_subscription(
            CleanupTask, '/cleanup/task', self.task_callback, 10)

    def transcript_callback(self, message: String) -> None:
        self.transcripts.append(message.data)

    def response_callback(self, message: String) -> None:
        self.responses.append(message.data)

    def task_callback(self, message: CleanupTask) -> None:
        self.tasks.append(message)

    def publish_text(self, text: str) -> None:
        message = String()
        message.data = text
        self.text_publisher.publish(message)

    def wait_for(self, predicate, timeout_sec: float, detail: str) -> None:
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if predicate():
                return
        raise RuntimeError('Timed out waiting for {}'.format(detail))

    def run(self) -> None:
        self.wait_for(
            lambda: self.text_publisher.get_subscription_count() > 0,
            8.0,
            '/voice/text_input subscriber',
        )
        self.publish_text('小莫，捡塑料瓶')
        self.wait_for(
            lambda: '小莫，捡塑料瓶' in self.transcripts,
            5.0,
            'ASR text transcript',
        )
        self.wait_for(
            lambda: any('请说确认' in text for text in self.responses),
            5.0,
            'confirmation prompt',
        )

        no_task_deadline = time.monotonic() + 1.0
        while rclpy.ok() and time.monotonic() < no_task_deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
        if self.tasks:
            raise RuntimeError('Cleanup task was published before confirmation')

        self.publish_text('确认')
        self.wait_for(
            lambda: any(
                task.action == 'pick_and_dispose'
                and task.object_class == 'plastic_bottle'
                for task in self.tasks
            ),
            8.0,
            'confirmed plastic_bottle cleanup task',
        )

        self.publish_text('紧急停止')
        self.wait_for(
            lambda: any(task.action == 'cancel' for task in self.tasks),
            8.0,
            'high-level cancel task',
        )

        print('PASS: unconfirmed command was blocked')
        print('PASS: confirmed bottle cleanup task was published')
        print('PASS: emergency stop produced a high-level cancel request')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceSmokeProbe()
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
