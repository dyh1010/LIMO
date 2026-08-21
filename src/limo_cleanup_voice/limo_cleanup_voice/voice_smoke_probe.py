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

"""LEGACY_ROS2_OFFLINE_ONLY graph probe; not a Noetic field test."""

import json
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
        self.navigation_requests = []
        self.priority_broadcasts = []
        self.create_subscription(
            String, '/voice/transcript', self.transcript_callback, 10)
        self.create_subscription(
            String, '/voice/response_text', self.response_callback, 10)
        self.create_subscription(
            CleanupTask, '/cleanup/task', self.task_callback, 10)
        self.create_subscription(
            String,
            '/cleanup/navigation_intent',
            self.navigation_callback,
            10,
        )
        self.create_subscription(
            String,
            '/voice/priority_broadcast',
            self.priority_callback,
            10,
        )

    def transcript_callback(self, message: String) -> None:
        self.transcripts.append(message.data)

    def response_callback(self, message: String) -> None:
        self.responses.append(message.data)

    def task_callback(self, message: CleanupTask) -> None:
        self.tasks.append(message)

    def navigation_callback(self, message: String) -> None:
        self.navigation_requests.append(json.loads(message.data))

    def priority_callback(self, message: String) -> None:
        self.priority_broadcasts.append(json.loads(message.data))

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
        self.publish_text('小莫小莫，捡塑料瓶')
        self.wait_for(
            lambda: '小莫小莫，捡塑料瓶' in self.transcripts,
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

        self.publish_text('停下')
        self.wait_for(
            lambda: any(task.action == 'cancel' for task in self.tasks),
            8.0,
            'high-level cancel task',
        )
        self.wait_for(
            lambda: any(
                request.get('action') == 'cancel_navigation'
                and request.get('request_safe_stop') is True
                for request in self.navigation_requests
            ),
            5.0,
            'navigation cancel and safe-stop request',
        )
        self.wait_for(
            lambda: any(
                item.get('priority') == 'critical'
                and item.get('intent') == 'stop_task'
                for item in self.priority_broadcasts),
            5.0,
            'independent priority stop broadcast',
        )
        stop_request = next(
            request for request in self.navigation_requests
            if request.get('action') == 'cancel_navigation')
        if stop_request != {
                'action': 'cancel_navigation',
                'request_safe_stop': True}:
            raise RuntimeError(
                'Stop intent did not match the strict bridge schema')

        navigation_count = len(self.navigation_requests)
        self.publish_text('小莫小莫，到垃圾桶旁边去')
        self.wait_for(
            lambda: any('垃圾桶旁边' in text for text in self.responses),
            5.0,
            'trash-bin navigation confirmation prompt',
        )
        no_navigation_deadline = time.monotonic() + 1.0
        while rclpy.ok() and time.monotonic() < no_navigation_deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
        if len(self.navigation_requests) != navigation_count:
            raise RuntimeError(
                'Navigation intent was published before confirmation')

        self.publish_text('确认')
        self.wait_for(
            lambda: any(
                request.get('action') == 'navigate_to_waypoint'
                and request.get('target_id') == 'trash_bin_staging'
                for request in self.navigation_requests
            ),
            5.0,
            'confirmed fixed trash-bin waypoint intent',
        )
        waypoint_request = next(
            request for request in self.navigation_requests
            if request.get('action') == 'navigate_to_waypoint')
        if waypoint_request != {
                'action': 'navigate_to_waypoint',
                'target_id': 'trash_bin_staging',
                'target_source': 'fixed_map_waypoint'}:
            raise RuntimeError(
                'Waypoint intent did not match the strict bridge schema')

        navigation_count = len(self.navigation_requests)
        self.publish_text('小莫小莫，到这里来')
        self.wait_for(
            lambda: any('暂不支持' in text for text in self.responses),
            5.0,
            'unsupported speaker-relative request response',
        )
        if len(self.navigation_requests) != navigation_count:
            raise RuntimeError(
                'Unsupported speaker-relative request was forwarded')

        forbidden_topics = (
            '/cmd_vel', '/cmd_vel_nav', '/cmd_vel_teleop',
            '/limo/vel_cmd', '/cleanup/base/safe_cmd_vel',
        )
        for topic in forbidden_topics:
            if self.get_publishers_info_by_topic(topic):
                raise RuntimeError(
                    'Unexpected motion publisher on {}'.format(topic))

        print('PASS: unconfirmed command was blocked')
        print('PASS: confirmed bottle cleanup task was published')
        print('PASS: stop produced task cancel and safe-stop intents')
        print('PASS: stop used the independent priority broadcast path')
        print('PASS: confirmed trash-bin waypoint intent was published')
        print('PASS: speaker-relative request remained unsupported')
        print('PASS: no motion-command publishers were present')


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
