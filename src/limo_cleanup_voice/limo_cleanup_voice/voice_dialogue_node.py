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

"""Safety-gated dialogue node between ASR transcripts and cleanup commands."""

import json
import time

import rclpy
from limo_cleanup_interfaces.msg import CleanupStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .command_parser import confirmation_prompt, parse_command


STATE_LABELS = {
    'idle': '当前空闲',
    'accepted': '任务已接受',
    'waiting_for_executor': '正在等待执行器',
    'dispatching': '正在下发任务',
    'executing': '任务执行中',
    'searching_object': '正在寻找目标',
    'approaching_object': '正在接近目标',
    'aligning_object': '正在对准目标',
    'grasping': '正在抓取',
    'verifying_grasp': '正在确认抓取结果',
    'navigating_to_bin': '正在前往垃圾桶',
    'aligning_bin': '正在对准垃圾桶',
    'dropping': '正在投放',
    'verifying_drop': '正在确认投放结果',
    'cancelling': '正在取消任务',
    'cancelled': '任务已取消',
    'succeeded': '任务已完成',
    'failed': '任务失败',
    'busy': '当前有任务正在执行',
    'rejected': '指令已拒绝',
}


class VoiceDialogueNode(Node):
    """Parse transcripts and forward only confirmed high-level commands."""

    def __init__(self) -> None:
        super().__init__('voice_dialogue')

        self.declare_parameter('transcript_topic', '/voice/transcript')
        self.declare_parameter('intent_topic', '/voice/intent')
        self.declare_parameter('response_topic', '/voice/response_text')
        self.declare_parameter('status_topic', '/voice/status')
        self.declare_parameter(
            'natural_language_topic', '/cleanup/natural_language')
        self.declare_parameter('cleanup_status_topic', '/cleanup/status')
        self.declare_parameter('require_confirmation', True)
        self.declare_parameter('confirmation_timeout_sec', 10.0)
        self.declare_parameter('require_wake_word', False)
        self.declare_parameter('wake_words', ['小莫', '利莫', '机器人'])

        self.require_confirmation = bool(
            self.get_parameter('require_confirmation').value)
        self.confirmation_timeout_sec = float(
            self.get_parameter('confirmation_timeout_sec').value)
        self.require_wake_word = bool(
            self.get_parameter('require_wake_word').value)
        self.wake_words = list(self.get_parameter('wake_words').value)

        status_qos = QoSProfile(depth=20)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.intent_publisher = self.create_publisher(
            String, self.get_parameter('intent_topic').value, status_qos)
        self.response_publisher = self.create_publisher(
            String, self.get_parameter('response_topic').value, 10)
        self.status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value, status_qos)
        self.command_publisher = self.create_publisher(
            String, self.get_parameter('natural_language_topic').value, 10)
        self.create_subscription(
            String,
            self.get_parameter('transcript_topic').value,
            self.transcript_callback,
            10,
        )
        self.create_subscription(
            CleanupStatus,
            self.get_parameter('cleanup_status_topic').value,
            self.cleanup_status_callback,
            status_qos,
        )

        self.pending_command = None
        self.pending_deadline = 0.0
        self.last_cleanup_status = None
        self.publish_status('ready', 'Voice dialogue is ready')

    def transcript_callback(self, message: String) -> None:
        raw_text = message.data.strip()
        intent = parse_command(
            raw_text,
            wake_words=self.wake_words,
            require_wake_word=(
                self.require_wake_word and self.pending_command is None),
        )

        if intent.name == 'ignored':
            self.publish_intent(intent, raw_text, forwarded=False)
            return
        if intent.name == 'empty':
            self.respond('没有听清，请再说一次。')
        elif intent.name == 'confirm':
            self.handle_confirmation(raw_text)
            return
        elif intent.name == 'reject_confirmation':
            self.pending_command = None
            self.pending_deadline = 0.0
            self.respond('已取消待确认指令。')
        elif intent.name == 'stop_task':
            if (
                    self.pending_command is not None
                    and intent.reason == 'cancel phrase'):
                self.pending_command = None
                self.pending_deadline = 0.0
                self.respond('已取消待确认指令。')
                self.publish_intent(intent, raw_text, forwarded=False)
                return
            self.pending_command = None
            self.pending_deadline = 0.0
            self.forward_command(intent.command_text)
            self.respond('已请求停止当前任务。语音停止不能替代物理急停。')
            self.publish_intent(intent, raw_text, forwarded=True)
            return
        elif intent.name == 'report_status':
            self.respond(self.describe_cleanup_status())
        elif intent.name == 'pause_unsupported':
            self.respond('当前任务状态机不支持暂停。你可以说停止任务。')
        elif intent.name == 'resume_unsupported':
            self.respond('当前任务状态机不支持继续，请重新下达清理指令。')
        elif intent.name == 'return_unsupported':
            self.respond('返回功能尚未接入导航状态机，本次不会执行移动。')
        elif intent.name in ('start_cleanup', 'start_touch'):
            if self.require_confirmation:
                self.pending_command = intent.command_text
                self.pending_deadline = (
                    time.monotonic() + self.confirmation_timeout_sec)
                self.respond(confirmation_prompt(intent.command_text))
            else:
                self.forward_command(intent.command_text)
                self.respond('清理指令已提交给任务管理器。')
                self.publish_intent(intent, raw_text, forwarded=True)
                return
        else:
            self.respond('暂不支持这条语音指令，本次不会执行任务。')

        self.publish_intent(intent, raw_text, forwarded=False)

    def handle_confirmation(self, raw_text: str) -> None:
        if self.pending_command is None:
            self.respond('当前没有等待确认的指令。')
            self.publish_raw_intent(
                'confirm', raw_text, None, False, 'no pending command')
            return
        if time.monotonic() > self.pending_deadline:
            expired_command = self.pending_command
            self.pending_command = None
            self.pending_deadline = 0.0
            self.respond('确认已超时，请重新下达清理指令。')
            self.publish_raw_intent(
                'confirm', raw_text, expired_command, False,
                'confirmation expired')
            return

        command_text = self.pending_command
        self.pending_command = None
        self.pending_deadline = 0.0
        self.forward_command(command_text)
        self.respond('已确认，清理指令已提交给任务管理器。')
        self.publish_raw_intent(
            'confirm', raw_text, command_text, True,
            'confirmed pending command')

    def cleanup_status_callback(self, message: CleanupStatus) -> None:
        self.last_cleanup_status = message
        if message.state in ('cancelled', 'succeeded', 'failed', 'rejected'):
            self.respond(self.describe_cleanup_status())

    def describe_cleanup_status(self) -> str:
        if self.last_cleanup_status is None:
            return '尚未收到任务管理器状态。'
        state = self.last_cleanup_status.state
        label = STATE_LABELS.get(state, '当前状态为{}'.format(state))
        progress = max(0.0, min(1.0, self.last_cleanup_status.progress))
        if 0.0 < progress < 1.0:
            return '{}，进度约百分之{}。'.format(
                label, int(round(progress * 100.0)))
        return '{}。'.format(label)

    def forward_command(self, command_text: str) -> None:
        message = String()
        message.data = command_text
        self.command_publisher.publish(message)
        self.get_logger().info(
            'Forwarded high-level command: {}'.format(command_text))

    def respond(self, text: str) -> None:
        message = String()
        message.data = text
        self.response_publisher.publish(message)
        self.get_logger().info('Dialogue response: {}'.format(text))

    def publish_intent(self, intent, raw_text: str, forwarded: bool) -> None:
        self.publish_raw_intent(
            intent.name,
            raw_text,
            intent.command_text,
            forwarded,
            intent.reason,
        )

    def publish_raw_intent(
            self, name: str, raw_text: str, command_text,
            forwarded: bool, reason: str) -> None:
        payload = {
            'intent': name,
            'raw_text': raw_text,
            'command_text': command_text,
            'forwarded': bool(forwarded),
            'reason': reason,
        }
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.intent_publisher.publish(message)

    def publish_status(self, state: str, detail: str) -> None:
        message = String()
        message.data = json.dumps(
            {'state': state, 'detail': detail}, ensure_ascii=False)
        self.status_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceDialogueNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
