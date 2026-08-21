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

"""LEGACY_ROS2_OFFLINE_ONLY dialogue wrapper; not a Noetic field node."""

import json
import time

import rclpy
from limo_cleanup_interfaces.msg import CleanupStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .command_parser import (
    confirmation_prompt,
    has_wake_word,
    is_priority_stop_text,
    parse_command,
)
from .voice_contract import (
    navigation_stop_payload,
    navigation_waypoint_payload,
    parse_semantic_candidate,
    parse_stop_broadcast,
    perception_inspect_payload,
    stop_ack_payload,
)


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
    'navigating_to_waypoint': '正在前往固定地图点位',
    'base_safe_stopped': '底盘安全停止请求已生效',
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
        self.declare_parameter(
            'semantic_candidate_topic', '/voice/semantic_candidate')
        self.declare_parameter(
            'priority_broadcast_topic', '/voice/priority_broadcast')
        self.declare_parameter(
            'priority_stop_request_topic', '/voice/priority_stop_request')
        self.declare_parameter('stop_ack_topic', '/voice/stop_ack')
        self.declare_parameter(
            'perception_intent_topic', '/cleanup/perception_intent')
        self.declare_parameter('intent_topic', '/voice/intent')
        self.declare_parameter('response_topic', '/voice/response_text')
        self.declare_parameter('status_topic', '/voice/status')
        self.declare_parameter(
            'natural_language_topic', '/cleanup/natural_language')
        self.declare_parameter(
            'navigation_intent_topic', '/cleanup/navigation_intent')
        self.declare_parameter('cleanup_status_topic', '/cleanup/status')
        self.declare_parameter('require_confirmation', True)
        self.declare_parameter('confirmation_timeout_sec', 10.0)
        self.declare_parameter('require_wake_word', True)
        self.declare_parameter('wake_words', ['小莫小莫'])
        self.declare_parameter('wake_command_timeout_sec', 5.0)
        self.declare_parameter(
            'trash_bin_waypoint', 'trash_bin_staging')

        self.require_confirmation = bool(
            self.get_parameter('require_confirmation').value)
        self.confirmation_timeout_sec = float(
            self.get_parameter('confirmation_timeout_sec').value)
        self.require_wake_word = bool(
            self.get_parameter('require_wake_word').value)
        self.wake_words = list(self.get_parameter('wake_words').value)
        self.wake_command_timeout_sec = float(
            self.get_parameter('wake_command_timeout_sec').value)
        self.trash_bin_waypoint = str(
            self.get_parameter('trash_bin_waypoint').value).strip()

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
        self.navigation_publisher = self.create_publisher(
            String, self.get_parameter('navigation_intent_topic').value, 10)
        self.perception_publisher = self.create_publisher(
            String, self.get_parameter('perception_intent_topic').value, 10)
        self.stop_ack_publisher = self.create_publisher(
            String, self.get_parameter('stop_ack_topic').value, 20)
        self.create_subscription(
            String, self.get_parameter('semantic_candidate_topic').value,
            self.semantic_candidate_callback, 20,
        )
        self.create_subscription(
            String, self.get_parameter('priority_broadcast_topic').value,
            self.priority_broadcast_callback, 20,
        )
        self.create_subscription(
            String, self.get_parameter('priority_stop_request_topic').value,
            self.priority_stop_request_callback, 20,
        )
        self.create_subscription(
            CleanupStatus,
            self.get_parameter('cleanup_status_topic').value,
            self.cleanup_status_callback,
            status_qos,
        )

        self.pending_command = None
        self.pending_intent_name = None
        self.pending_raw_text = None
        self.pending_deadline = 0.0
        self.wake_deadline = 0.0
        self.last_cleanup_status = None
        self.publish_status('ready', 'Voice dialogue is ready')

    def transcript_callback(self, message: String) -> None:
        """Process a direct transcript for tests and legacy callers."""
        raw_text = message.data.strip()
        VoiceDialogueNode.process_transcript(self, raw_text, raw_text)

    def semantic_candidate_callback(self, message: String) -> None:
        """Validate an untrusted semantic candidate before dialogue gating."""
        try:
            payload = parse_semantic_candidate(message.data)
        except ValueError as error:
            self.publish_raw_intent(
                'semantic_rejected', '', None, False,
                str(error))
            return
        raw_text = payload['raw_text']
        canonical_text = payload['canonical_text']
        if is_priority_stop_text(raw_text) or is_priority_stop_text(
                canonical_text):
            self.publish_raw_intent(
                'semantic_rejected', raw_text, None, False,
                'stop is reserved for priority broadcaster')
            return
        wake_window_active = VoiceDialogueNode.wake_window_active(self)
        if (
                self.require_wake_word
                and self.pending_command is None
                and not wake_window_active):
            raw_gate = parse_command(
                raw_text,
                wake_words=self.wake_words,
                require_wake_word=True,
            )
            canonical_gate = parse_command(
                canonical_text,
                wake_words=self.wake_words,
                require_wake_word=True,
            )
            if raw_gate.name == 'ignored' \
                    or canonical_gate.name == 'ignored':
                self.publish_raw_intent(
                    'semantic_rejected', raw_text, None, False,
                    'semantic candidate may not change wake-word state')
                return
        if self.pending_command is not None:
            raw_control = parse_command(
                raw_text,
                wake_words=self.wake_words,
                require_wake_word=False,
            )
            canonical_control = parse_command(
                canonical_text,
                wake_words=self.wake_words,
                require_wake_word=False,
            )
            control_names = {
                'confirm', 'reject_confirmation', 'stop_task',
            }
            if raw_control.name != canonical_control.name and (
                    raw_control.name in control_names
                    or canonical_control.name in control_names):
                self.publish_raw_intent(
                    'semantic_rejected', raw_text, None, False,
                    'semantic candidate may not change confirmation state')
                return
        VoiceDialogueNode.process_transcript(
            self, raw_text, canonical_text)

    def priority_broadcast_callback(self, message: String) -> None:
        """Clear dialogue state after the independent stop broadcaster."""
        try:
            payload = parse_stop_broadcast(message.data)
        except ValueError:
            return
        raw_text = payload['raw_text']
        if not is_priority_stop_text(raw_text):
            return
        self.clear_pending_command()
        VoiceDialogueNode.clear_wake_window(self)
        if payload['attempt'] == 1:
            self.respond(
                '已优先广播停止任务、取消导航和安全停止请求。'
                '语音停止不能替代物理急停。')
            self.publish_raw_intent(
                'stop_task', raw_text, '停止任务', True,
                'independent priority stop broadcast')

    def priority_stop_request_callback(self, message: String) -> None:
        """Relay one strict priority event through the sole command owners."""
        try:
            payload = parse_stop_broadcast(message.data)
        except ValueError:
            return
        raw_text = payload['raw_text']
        if not is_priority_stop_text(raw_text):
            return
        self.clear_pending_command()
        VoiceDialogueNode.clear_wake_window(self)
        self.forward_command('停止任务')
        self.publish_navigation_stop(raw_text)
        acknowledgement = String()
        acknowledgement.data = json.dumps(stop_ack_payload(
            event_id=payload['event_id'],
            process_instance_id=payload['process_instance_id'],
            source='voice_dialogue',
            state='accepted',
            detail='Task cancel and navigation safe-stop intents relayed',
        ), ensure_ascii=False)
        self.stop_ack_publisher.publish(acknowledgement)

    def process_transcript(self, raw_text: str, parse_text: str) -> None:
        """Apply deterministic wake, confirmation, and forwarding gates."""
        expired_command = self.expire_pending_command()
        wake_window_active = VoiceDialogueNode.wake_window_active(self)
        intent = parse_command(
            parse_text,
            wake_words=self.wake_words,
            require_wake_word=(
                self.require_wake_word
                and self.pending_command is None
                and not wake_window_active),
        )
        if wake_window_active and self.pending_command is None:
            # A wake-only utterance grants exactly one following transcript.
            # Consume the grant before interpreting that transcript so an
            # unsupported/ambiguous phrase cannot leave the agent armed.
            VoiceDialogueNode.clear_wake_window(self)
        if expired_command is not None and intent.name == 'ignored':
            expired_intent = parse_command(
                parse_text,
                wake_words=self.wake_words,
                require_wake_word=False,
            )
            if expired_intent.name == 'confirm' or (
                    expired_intent.name == 'stop_task'
                    and expired_intent.reason == 'cancel phrase'):
                intent = expired_intent

        if intent.name == 'ignored':
            self.publish_intent(intent, raw_text, forwarded=False)
            return
        if intent.name == 'empty':
            if (
                    self.require_wake_word
                    and raw_text.strip()
                    and has_wake_word(raw_text, self.wake_words)):
                VoiceDialogueNode.arm_wake_window(self)
                self.respond('我在，请说指令。')
            else:
                self.respond('没有听清，请再说一次。')
        elif intent.name == 'confirm':
            if expired_command is not None:
                self.respond('确认已超时，请重新下达清理指令。')
                self.publish_raw_intent(
                    'confirm', raw_text, expired_command, False,
                    'confirmation expired')
                return
            self.handle_confirmation(raw_text)
            return
        elif intent.name == 'reject_confirmation':
            self.clear_pending_command()
            self.respond('已取消待确认指令。')
        elif intent.name == 'stop_task':
            had_pending_command = self.pending_command is not None
            VoiceDialogueNode.clear_wake_window(self)
            if intent.reason == 'cancel phrase':
                self.clear_pending_command()
                if had_pending_command:
                    self.respond('已取消待确认指令。')
                else:
                    self.respond(
                        '当前没有待确认指令，本次不会发送停止请求。')
                self.publish_intent(intent, raw_text, forwarded=False)
                return
            self.clear_pending_command()
            self.forward_command(intent.command_text)
            self.publish_navigation_stop(raw_text)
            self.respond(
                '已请求取消任务和导航，并触发底盘安全停止。'
                '语音停止不能替代物理急停。')
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
        elif intent.name in (
                'start_cleanup', 'start_touch',
                'navigate_to_bin', 'inspect_bottle'):
            # V2 safety contract: actionable voice intents always require a
            # fresh confirmation.  The legacy parameter is retained for
            # launch/config compatibility but cannot disable this gate.
            self.pending_command = intent.command_text
            self.pending_intent_name = intent.name
            self.pending_raw_text = raw_text
            self.pending_deadline = (
                time.monotonic() + self.confirmation_timeout_sec)
            self.respond(confirmation_prompt(intent.command_text))
        else:
            self.respond('暂不支持这条语音指令，本次不会执行任务。')

        self.publish_intent(intent, raw_text, forwarded=False)

    def wake_window_active(self) -> bool:
        """Return whether a wake-only utterance still arms one command."""
        deadline = float(getattr(self, 'wake_deadline', 0.0))
        if deadline <= 0.0:
            return False
        if time.monotonic() > deadline:
            VoiceDialogueNode.clear_wake_window(self)
            return False
        return True

    def arm_wake_window(self) -> None:
        """Arm one bounded command slot after the complete wake phrase."""
        timeout = max(
            0.0, float(getattr(self, 'wake_command_timeout_sec', 5.0)))
        self.wake_deadline = time.monotonic() + timeout

    def clear_wake_window(self) -> None:
        """Clear the one-shot wake grant."""
        self.wake_deadline = 0.0

    def expire_pending_command(self):
        """Clear and return a command whose confirmation window elapsed."""
        if self.pending_command is None:
            return None
        if time.monotonic() <= self.pending_deadline:
            return None
        expired_command = self.pending_command
        self.clear_pending_command()
        return expired_command

    def clear_pending_command(self) -> None:
        """Clear all state associated with a pending confirmation."""
        self.pending_command = None
        self.pending_intent_name = None
        self.pending_raw_text = None
        self.pending_deadline = 0.0

    def handle_confirmation(self, raw_text: str) -> None:
        if self.pending_command is None:
            self.respond('当前没有等待确认的指令。')
            self.publish_raw_intent(
                'confirm', raw_text, None, False, 'no pending command')
            return
        if time.monotonic() > self.pending_deadline:
            expired_command = self.pending_command
            self.clear_pending_command()
            self.respond('确认已超时，请重新下达清理指令。')
            self.publish_raw_intent(
                'confirm', raw_text, expired_command, False,
                'confirmation expired')
            return

        command_text = self.pending_command
        intent_name = self.pending_intent_name or 'start_cleanup'
        pending_raw_text = self.pending_raw_text or raw_text
        self.clear_pending_command()
        forwarded, response, reason = self.forward_confirmed_intent(
            intent_name, command_text, pending_raw_text)
        self.respond(response)
        self.publish_raw_intent(
            'confirm', raw_text, command_text, forwarded, reason)

    def forward_confirmed_intent(
            self, intent_name: str, command_text: str, raw_text: str):
        """Forward one confirmed high-level intent without motion output."""
        if intent_name == 'navigate_to_bin':
            return self.forward_navigation_intent(intent_name, raw_text)
        if intent_name == 'inspect_bottle':
            message = String()
            message.data = json.dumps(
                perception_inspect_payload(), ensure_ascii=False)
            self.perception_publisher.publish(message)
            return (
                True,
                '已提交矿泉水瓶识别请求；本次不会触发移动或抓取。',
                'confirmed motion-free perception intent',
            )
        self.forward_command(command_text)
        return (
            True,
            '已确认，清理指令已提交给任务管理器。',
            'confirmed pending command',
        )

    def forward_navigation_intent(self, intent_name: str, raw_text: str):
        """Publish a navigation intent without coordinates or velocity."""
        if intent_name != 'navigate_to_bin':
            return (
                False,
                '不支持这条导航指令，本次不会移动。',
                'unsupported navigation intent',
            )
        if not self.trash_bin_waypoint:
            return (
                False,
                '垃圾桶固定地图点位未配置，本次不会移动。',
                'trash-bin waypoint is not configured',
            )
        payload = navigation_waypoint_payload(self.trash_bin_waypoint)
        response = '已提交前往垃圾桶固定地图点位的高层导航请求。'

        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.navigation_publisher.publish(message)
        return True, response, 'confirmed high-level navigation intent'

    def publish_navigation_stop(self, raw_text: str) -> None:
        """Request navigation cancellation and downstream safe stopping."""
        message = String()
        message.data = json.dumps(
            navigation_stop_payload(), ensure_ascii=False)
        self.navigation_publisher.publish(message)

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
