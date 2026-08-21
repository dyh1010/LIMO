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

"""LEGACY_ROS2_OFFLINE_ONLY stop wrapper; not a Noetic field node."""

import json
import math
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .command_parser import is_priority_stop_text
from .voice_contract import (
    new_event_id,
    parse_stop_ack,
    stop_broadcast_payload,
)


class VoicePriorityStopNode(Node):
    """Broadcast stop without waiting for semantic-agent processing."""

    def __init__(self):
        super().__init__('voice_priority_stop')
        self.declare_parameter('transcript_topic', '/voice/transcript')
        self.declare_parameter(
            'priority_topic', '/voice/priority_broadcast')
        self.declare_parameter(
            'stop_request_topic', '/voice/priority_stop_request')
        self.declare_parameter('ack_topic', '/voice/stop_ack')
        self.declare_parameter('status_topic', '/voice/stop_status')
        self.declare_parameter('debounce_sec', 0.75)
        self.declare_parameter('repeat_count', 3)
        self.declare_parameter('repeat_interval_sec', 0.075)
        self.declare_parameter('ack_timeout_sec', 1.5)
        self.debounce_sec = float(
            self.get_parameter('debounce_sec').value)
        self.repeat_count = int(
            self.get_parameter('repeat_count').value)
        self.repeat_interval_sec = float(
            self.get_parameter('repeat_interval_sec').value)
        self.ack_timeout_sec = float(
            self.get_parameter('ack_timeout_sec').value)
        timings = (
            self.debounce_sec,
            self.repeat_interval_sec,
            self.ack_timeout_sec,
        )
        if (
                not all(math.isfinite(item) for item in timings)
                or self.debounce_sec < 0.0
                or self.repeat_interval_sec <= 0.0
                or self.ack_timeout_sec <= 0.0
                or self.repeat_count <= 0
                or self.ack_timeout_sec <= (
                    self.repeat_interval_sec * (self.repeat_count - 1))):
            raise ValueError(
                'stop debounce/repeat/ACK parameters are invalid')
        priority_qos = QoSProfile(depth=20)
        priority_qos.reliability = ReliabilityPolicy.RELIABLE
        priority_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.priority_publisher = self.create_publisher(
            String, self.get_parameter('priority_topic').value, priority_qos)
        self.stop_request_publisher = self.create_publisher(
            String,
            self.get_parameter('stop_request_topic').value,
            priority_qos,
        )
        self.status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value, priority_qos)
        self.create_subscription(
            String,
            self.get_parameter('transcript_topic').value,
            self.transcript_callback,
            20,
        )
        self.create_subscription(
            String,
            self.get_parameter('ack_topic').value,
            self.ack_callback,
            20,
        )
        self._state_lock = threading.RLock()
        self._process_instance_id = new_event_id('voice-stop-process')
        self._active_event = None
        self._last_trigger_monotonic_ns = -1
        self._last_event_id = ''
        self.repeat_timer = self.create_timer(
            min(self.repeat_interval_sec, 0.05),
            self.repeat_timer_callback,
        )
        self.publish_status(
            'ready', 'Priority stop broadcaster is ready', event_id='')

    def transcript_callback(self, message):
        """Broadcast only explicit stop phrases on the priority path."""
        raw_text = message.data.strip()
        if not is_priority_stop_text(raw_text):
            return
        trigger_monotonic_ns = time.monotonic_ns()
        trigger_wall_time_unix_ns = time.time_ns()
        with self._state_lock:
            debounce_ns = int(self.debounce_sec * 1_000_000_000)
            if (
                    self._last_trigger_monotonic_ns >= 0
                    and trigger_monotonic_ns
                    - self._last_trigger_monotonic_ns < debounce_ns):
                self.publish_status(
                    'debounced',
                    'Repeated ASR stop transcript was coalesced',
                    event_id=self._last_event_id,
                    raw_text=raw_text,
                )
                return
            if self._active_event is not None:
                previous = self._active_event
                self.publish_status(
                    'superseded',
                    'A newer explicit stop event superseded this ACK window',
                    event_id=previous['event_id'],
                    attempt=previous['attempt'],
                    repeat_count=self.repeat_count,
                    ack_sources=sorted(previous['ack_sources']),
                )
            event_id = new_event_id('voice-stop')
            self._last_trigger_monotonic_ns = trigger_monotonic_ns
            self._last_event_id = event_id
            self._active_event = {
                'event_id': event_id,
                'process_instance_id': self._process_instance_id,
                'raw_text': raw_text,
                'trigger_wall_time_unix_ns': trigger_wall_time_unix_ns,
                'trigger_monotonic_ns': trigger_monotonic_ns,
                'attempt': 0,
                'last_publish_monotonic_ns': -1,
                'ack_sources': {},
            }
            self._publish_attempt_locked()

    def _publish_attempt_locked(self):
        """Publish one complete high-level stop attempt while holding lock."""
        event = self._active_event
        if event is None or event['attempt'] >= self.repeat_count:
            return
        event['attempt'] += 1
        published_wall_time_unix_ns = time.time_ns()
        published_monotonic_ns = time.monotonic_ns()
        event['last_publish_monotonic_ns'] = published_monotonic_ns

        priority = String()
        priority.data = json.dumps(stop_broadcast_payload(
            event_id=event['event_id'],
            process_instance_id=event['process_instance_id'],
            raw_text=event['raw_text'],
            attempt=event['attempt'],
            repeat_count=self.repeat_count,
            trigger_wall_time_unix_ns=event['trigger_wall_time_unix_ns'],
            trigger_monotonic_ns=event['trigger_monotonic_ns'],
            published_wall_time_unix_ns=published_wall_time_unix_ns,
            published_monotonic_ns=published_monotonic_ns,
        ), ensure_ascii=False)
        self.priority_publisher.publish(priority)
        self.stop_request_publisher.publish(priority)

        self.publish_status(
            'broadcasting',
            'Priority stop attempt published',
            event_id=event['event_id'],
            raw_text=event['raw_text'],
            attempt=event['attempt'],
            repeat_count=self.repeat_count,
            transcript_to_publish_latency_ns=(
                published_monotonic_ns
                - event['trigger_monotonic_ns']),
        )

    def repeat_timer_callback(self):
        """Perform bounded retries and close the diagnostic ACK window."""
        with self._state_lock:
            event = self._active_event
            if event is None:
                return
            now_monotonic_ns = time.monotonic_ns()
            interval_ns = int(self.repeat_interval_sec * 1_000_000_000)
            if (
                    event['attempt'] < self.repeat_count
                    and now_monotonic_ns
                    - event['last_publish_monotonic_ns'] >= interval_ns):
                self._publish_attempt_locked()
                event = self._active_event
            if event is None:
                return
            successful_acks = sorted(
                source for source, state in event['ack_sources'].items()
                if state in {'accepted', 'completed', 'observed'})
            if event['attempt'] >= self.repeat_count and successful_acks:
                self.publish_status(
                    'relay_acknowledged',
                    'Bounded stop broadcast completed; relay ACK observed',
                    event_id=event['event_id'],
                    attempt=event['attempt'],
                    repeat_count=self.repeat_count,
                    ack_sources=successful_acks,
                )
                self._active_event = None
                return
            timeout_ns = int(self.ack_timeout_sec * 1_000_000_000)
            if (
                    event['attempt'] >= self.repeat_count
                    and now_monotonic_ns
                    - event['trigger_monotonic_ns'] >= timeout_ns):
                self.publish_status(
                    'ack_timeout',
                    'Stop outputs were sent; no successful ACK was observed',
                    event_id=event['event_id'],
                    attempt=event['attempt'],
                    repeat_count=self.repeat_count,
                    ack_sources=sorted(event['ack_sources']),
                )
                self._active_event = None

    def ack_callback(self, message):
        """Observe optional ACKs without ever gating stop publication."""
        try:
            acknowledgement = parse_stop_ack(message.data)
        except ValueError as error:
            self.publish_status(
                'invalid_ack', str(error), event_id=self._last_event_id)
            return
        with self._state_lock:
            event = self._active_event
            if (
                    event is None
                    or acknowledgement['event_id'] != event['event_id']
                    or acknowledgement['process_instance_id']
                    != event['process_instance_id']):
                self.publish_status(
                    'ignored_ack',
                    'ACK does not match the active stop event',
                    event_id=acknowledgement['event_id'],
                    ack_source=acknowledgement['source'],
                )
                return
            event['ack_sources'][acknowledgement['source']] = (
                acknowledgement['state'])
            self.publish_status(
                'acknowledged',
                acknowledgement['detail'] or 'Stop event was observed',
                event_id=event['event_id'],
                ack_source=acknowledgement['source'],
                ack_state=acknowledgement['state'],
                attempt=event['attempt'],
                repeat_count=self.repeat_count,
            )

    def publish_status(self, state, detail, event_id, **extra):
        """Publish a timestamped, transient-local stop diagnostic state."""
        payload = {
            'schema_version': 1,
            'state': state,
            'detail': detail,
            'event_id': event_id,
            'wall_time_unix_ns': time.time_ns(),
            'monotonic_ns': time.monotonic_ns(),
        }
        payload.update(extra)
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.status_publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = VoicePriorityStopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
