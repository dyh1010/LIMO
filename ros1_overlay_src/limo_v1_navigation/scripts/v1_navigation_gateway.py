#!/usr/bin/env python3
"""READY-gated ROS1 point-to-point goal/cancel/status gateway."""

import json
import math
from pathlib import Path
import threading
import sys
import time


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.localization_policy import planar_yaw  # noqa: E402
from limo_v1_navigation.navigation_gate_policy import (  # noqa: E402
    CANCELED,
    FAILED,
    SUCCEEDED,
    GoalGenerationGate,
    GoalRequest,
    NavigationGate,
)


class V1NavigationGateway:
    """The only accepted public goal ingress for native V1 navigation."""

    def __init__(
            self, rospy, actionlib, MoveBaseAction, MoveBaseGoal,
            PoseStamped, Bool, String, Trigger, TriggerResponse,
            GoalStatus):
        self.rospy = rospy
        self.MoveBaseGoal = MoveBaseGoal
        self.String = String
        self.TriggerResponse = TriggerResponse
        self.GoalStatus = GoalStatus
        self.localization_timeout_s = float(rospy.get_param(
            '~localization_timeout_s', 0.5))
        self.guard_timeout_s = float(rospy.get_param(
            '~guard_timeout_s', 0.5))
        if (
                not math.isfinite(self.localization_timeout_s)
                or not 0.0 < self.localization_timeout_s <= 1.0
                or not math.isfinite(self.guard_timeout_s)
                or not 0.0 < self.guard_timeout_s <= 1.0):
            raise ValueError('gateway heartbeat timeouts must be in (0, 1]')
        self.gate = NavigationGate()
        self.lock = threading.RLock()
        self.goal_gate = GoalGenerationGate()
        self.enabled = bool(rospy.get_param('~enabled', False))
        self.allow_goal_forwarding = bool(rospy.get_param(
            '~allow_goal_forwarding', False))
        self.active_goal_generation = None
        self.state_generation = 0
        self.guard_latched = True
        self.guard_receive = None
        self.next_request_id = 0
        self.client = actionlib.SimpleActionClient(
            '/v1/private_move_base', MoveBaseAction)
        self.status_publisher = rospy.Publisher(
            '/v1/navigation/status', String, queue_size=1, latch=True)
        self.error_publisher = rospy.Publisher(
            '/v1/navigation/error', String, queue_size=1, latch=True)
        rospy.Subscriber(
            '/v1/localization/ready', Bool,
            self._localization_callback, queue_size=10)
        rospy.Subscriber(
            '/v1/navigation/goal', PoseStamped,
            self._goal_callback, queue_size=1)
        rospy.Subscriber(
            '/v1/navigation/cancel', Bool,
            self._cancel_callback, queue_size=10)
        rospy.Subscriber(
            '/v1/cmd_guard/stop_latched', Bool,
            self._stop_latched_callback, queue_size=10)
        rospy.Service('~arm', Trigger, self._arm)
        rospy.Service('~cancel', Trigger, self._cancel_service)
        rospy.Timer(rospy.Duration(0.10), self._timer)
        self._publish_status(time.monotonic(), 'startup')

    def _localization_callback(self, message):
        now = time.monotonic()
        with self.lock:
            was_cancel_required = self.gate.cancel_required
            self.gate.update_localization(bool(message.data), now)
            if self.gate.cancel_required and not was_cancel_required:
                self.state_generation += 1
                self._invalidate_and_cancel_locked()
            self._publish_status(now, 'localization_ready')

    def _stop_latched_callback(self, message):
        now = time.monotonic()
        with self.lock:
            self.guard_latched = bool(message.data)
            self.guard_receive = now
            if self.guard_latched:
                self.gate.trip('command_guard_stop_latched')
                self.state_generation += 1
                self._invalidate_and_cancel_locked()
            self._publish_status(now, 'command_guard_heartbeat')

    def _guard_health(self, now):
        if self.guard_receive is None:
            return False, 'command_guard_heartbeat_missing'
        age = now - self.guard_receive
        if not math.isfinite(age) or age < 0.0 or age >= self.guard_timeout_s:
            return False, 'command_guard_heartbeat_stale'
        if self.guard_latched:
            return False, 'command_guard_stop_latched'
        return True, 'healthy'

    def _arm(self, _request):
        now = time.monotonic()
        with self.lock:
            if not self.enabled or not self.allow_goal_forwarding:
                return self.TriggerResponse(
                    success=False, message='goal forwarding is disabled')
            guard_healthy, guard_reason = self._guard_health(now)
            if not guard_healthy:
                self.gate.trip(guard_reason)
                self._invalidate_and_cancel_locked()
                self._publish_status(now, 'arm_blocked')
                return self.TriggerResponse(
                    success=False, message=guard_reason)
            self.gate.update_action_server(
                self.client.wait_for_server(self.rospy.Duration(0.0)))
            decision = self.gate.arm(now, self.localization_timeout_s)
            self._publish_status(now, 'arm')
        return self.TriggerResponse(
            success=decision.accepted, message=decision.reason)

    def _goal_callback(self, message):
        now = time.monotonic()
        try:
            if not self.enabled or not self.allow_goal_forwarding:
                raise RuntimeError('goal forwarding is disabled')
            with self.lock:
                self.next_request_id += 1
                request_id = 'gateway-{}'.format(self.next_request_id)
                observed_state_generation = self.state_generation
            goal = GoalRequest(
                request_id=request_id,
                frame_id=message.header.frame_id.lstrip('/'),
                x=message.pose.position.x,
                y=message.pose.position.y,
                yaw=planar_yaw(
                    message.pose.orientation.x,
                    message.pose.orientation.y,
                    message.pose.orientation.z,
                    message.pose.orientation.w),
            )
            move_goal = self.MoveBaseGoal()
            move_goal.target_pose = message
            with self.lock:
                if observed_state_generation != self.state_generation:
                    self._publish_error(now, 'goal_invalidated_before_accept')
                    self._publish_status(now, 'goal_rejected')
                    return
                guard_healthy, guard_reason = self._guard_health(now)
                if not guard_healthy:
                    self.gate.trip(guard_reason)
                    self._invalidate_and_cancel_locked()
                    self._publish_error(now, guard_reason)
                    self._publish_status(now, 'goal_rejected')
                    return
                decision = self.gate.submit(
                    goal, now, self.localization_timeout_s)
                if not decision.accepted:
                    self._publish_error(now, decision.reason)
                    self._publish_status(now, 'goal_rejected')
                    return
                generation = self.goal_gate.reserve()
                self.active_goal_generation = generation

            def send():
                self.client.send_goal(
                    move_goal,
                    done_cb=lambda status, result: self._done_callback(
                        generation, status, result),
                    active_cb=lambda: self._active_callback(generation),
                    feedback_cb=lambda feedback: self._feedback_callback(
                        generation, feedback))

            if not self.goal_gate.commit(generation, send):
                with self.lock:
                    if self.active_goal_generation == generation:
                        self.active_goal_generation = None
                    self._publish_error(now, self.gate.reason)
                    self._publish_status(now, 'goal_invalidated_before_send')
                return
            with self.lock:
                if (self.active_goal_generation != generation
                        or not self.goal_gate.is_current(generation)):
                    return
                self._publish_status(now, 'goal_forwarded')
        except (ValueError, RuntimeError) as exc:
            self._publish_error(now, 'invalid_goal:{}'.format(exc))
            self._publish_status(now, 'goal_rejected')

    def _cancel_callback(self, message):
        if message.data:
            self._cancel('cancel_topic')

    def _cancel_service(self, _request):
        decision = self._cancel('cancel_service')
        return self.TriggerResponse(
            success=True, message=decision.reason)

    def _cancel(self, reason):
        now = time.monotonic()
        with self.lock:
            decision = self.gate.cancel(reason)
            self.state_generation += 1
            self._invalidate_and_cancel_locked()
            self._publish_status(now, 'cancel')
        return decision

    def _invalidate_and_cancel_locked(self):
        self.active_goal_generation = None
        self.goal_gate.invalidate(self.client.cancel_all_goals)

    def _active_callback(self, generation):
        with self.lock:
            if (generation != self.active_goal_generation
                    or not self.goal_gate.is_current(generation)):
                return
            self._publish_status(time.monotonic(), 'move_base_active')

    def _feedback_callback(self, generation, message):
        with self.lock:
            if (generation != self.active_goal_generation
                    or not self.goal_gate.is_current(generation)):
                return
            now = time.monotonic()
            payload = self.gate.status(now, self.localization_timeout_s)
            payload['event'] = 'feedback'
            payload['feedback'] = {
                'frame_id': message.base_position.header.frame_id,
                'x': message.base_position.pose.position.x,
                'y': message.base_position.pose.position.y,
            }
            self._publish_payload(payload)

    def _done_callback(self, generation, status, result):
        with self.lock:
            if (generation != self.active_goal_generation
                    or not self.goal_gate.is_current(generation)):
                return
            now = time.monotonic()
            if status == self.GoalStatus.SUCCEEDED:
                terminal, reason = SUCCEEDED, 'move_base_succeeded'
            elif status in (
                    self.GoalStatus.PREEMPTED, self.GoalStatus.RECALLED):
                terminal, reason = CANCELED, 'move_base_canceled'
            else:
                terminal, reason = FAILED, 'move_base_status_{}'.format(status)
            self.gate.complete(terminal, reason)
            self.active_goal_generation = None
            self.goal_gate.invalidate()
            self._publish_status(now, 'move_base_done')
        del result

    def _timer(self, _event):
        now = time.monotonic()
        server_ready = self.client.wait_for_server(
            self.rospy.Duration(0.0))
        with self.lock:
            was_cancel_required = self.gate.cancel_required
            self.gate.update_action_server(server_ready)
            self.gate.tick(now, self.localization_timeout_s)
            guard_healthy, guard_reason = self._guard_health(now)
            if not guard_healthy and (self.gate.armed
                                      or self.gate.active_goal is not None):
                self.gate.trip(guard_reason)
            if self.gate.cancel_required and not was_cancel_required:
                self.state_generation += 1
                self._invalidate_and_cancel_locked()
            self._publish_status(now, 'timer')

    def _publish_error(self, now, reason):
        message = self.String()
        message.data = json.dumps({
            'schema': 'limo_v1_navigation_error/v1',
            'monotonic': now,
            'reason': str(reason),
        }, sort_keys=True, separators=(',', ':'))
        self.error_publisher.publish(message)

    def _publish_payload(self, payload):
        message = self.String()
        message.data = json.dumps(
            payload, sort_keys=True, separators=(',', ':'))
        self.status_publisher.publish(message)

    def _publish_status(self, now, event):
        payload = self.gate.status(now, self.localization_timeout_s)
        payload.update({
            'schema': 'limo_v1_navigation_status/v1',
            'event': event,
            'software_stop_boundary': (
                'cancel/zero is not a physical e-stop or power disconnect'),
            'gateway_enabled': self.enabled,
            'allow_goal_forwarding': self.allow_goal_forwarding,
            'guard_health': self._guard_health(now)[1],
            'guard_latched': self.guard_latched,
        })
        self._publish_payload(payload)


def main():
    try:
        import actionlib
        import rospy
        from actionlib_msgs.msg import GoalStatus
        from geometry_msgs.msg import PoseStamped
        from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
        from std_msgs.msg import Bool, String
        from std_srvs.srv import Trigger, TriggerResponse
        rospy.init_node('v1_navigation_gateway', anonymous=False)
        V1NavigationGateway(
            rospy, actionlib, MoveBaseAction, MoveBaseGoal, PoseStamped,
            Bool, String, Trigger, TriggerResponse, GoalStatus)
        rospy.spin()
        return 0
    except (ImportError, RuntimeError, ValueError) as exc:
        print('V1_NAVIGATION_GATEWAY_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
