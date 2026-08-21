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

"""LEGACY_ROS2_OFFLINE_ONLY semantic wrapper; not a Noetic field node."""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .semantic_agent import normalize_non_stop_semantics
from .voice_contract import semantic_candidate_payload


class VoiceSemanticAgentNode(Node):
    """Normalize non-stop language without publishing executable commands."""

    def __init__(self):
        super().__init__('voice_semantic_agent')
        self.declare_parameter('transcript_topic', '/voice/transcript')
        self.declare_parameter(
            'candidate_topic', '/voice/semantic_candidate')
        self.publisher = self.create_publisher(
            String, self.get_parameter('candidate_topic').value, 20)
        self.create_subscription(
            String,
            self.get_parameter('transcript_topic').value,
            self.transcript_callback,
            20,
        )

    def transcript_callback(self, message):
        """Suppress stop and publish a strict non-executable candidate."""
        candidate = normalize_non_stop_semantics(message.data)
        if candidate is None:
            return
        payload = semantic_candidate_payload(
            raw_text=candidate.raw_text,
            canonical_text=candidate.canonical_text,
            source=candidate.source,
            confidence=1.0,
        )
        output = String()
        output.data = json.dumps(payload, ensure_ascii=False)
        self.publisher.publish(output)


def main(args=None):
    rclpy.init(args=args)
    node = VoiceSemanticAgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
