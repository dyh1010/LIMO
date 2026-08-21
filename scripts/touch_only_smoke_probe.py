#!/usr/bin/env python3

import sys
import time

import rclpy
from limo_cleanup_interfaces.msg import CleanupStatus, CleanupTask
from rclpy.node import Node
from std_msgs.msg import String


REQUIRED_STATES = (
    'accepted',
    'searching_object',
    'object_detected',
    'planning_standoff',
    'navigating_to_standoff',
    'aligning_touch_pose',
    'pre_touch',
    'touching',
    'retreating',
    'succeeded',
)
FORBIDDEN_STATE_PARTS = ('grasp', 'drop', 'bin', 'gripper')


class TouchOnlySmokeProbe(Node):
    def __init__(self) -> None:
        super().__init__('touch_only_smoke_probe')
        self.command_publisher = self.create_publisher(
            String, '/cleanup/command_text', 10)
        self.tasks = []
        self.statuses = []
        self.create_subscription(
            CleanupTask, '/cleanup/task', self.task_callback, 10)
        self.create_subscription(
            CleanupStatus, '/cleanup/status', self.status_callback, 20)

    def task_callback(self, message: CleanupTask) -> None:
        self.tasks.append(message)

    def status_callback(self, message: CleanupStatus) -> None:
        self.statuses.append(message)

    def wait_for_subscriber(self, timeout_sec: float) -> None:
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if self.command_publisher.get_subscription_count() > 0:
                return
        raise RuntimeError('task manager command subscriber was not ready')

    def run(self) -> None:
        self.wait_for_subscriber(8.0)
        command = String()
        command.data = '触碰矿泉水瓶'
        self.command_publisher.publish(command)

        deadline = time.monotonic() + 10.0
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if any(status.state == 'succeeded' for status in self.statuses):
                break
            if any(
                    status.state in ('failed', 'object_not_found')
                    for status in self.statuses):
                break

        touch_tasks = [
            task for task in self.tasks
            if task.action == 'touch_only'
        ]
        if len(touch_tasks) != 1:
            raise RuntimeError(
                'expected exactly one touch_only task, got {}'.format(
                    len(touch_tasks)))
        task = touch_tasks[0]
        if task.object_class != 'plastic_bottle':
            raise RuntimeError(
                'touch_only task object was {}'.format(task.object_class))

        states = [status.state for status in self.statuses]
        cursor = 0
        for required in REQUIRED_STATES:
            try:
                cursor = states.index(required, cursor) + 1
            except ValueError as error:
                raise RuntimeError(
                    'missing ordered state {}; observed={}'.format(
                        required, states)) from error

        for state in states:
            lowered = state.lower()
            if any(part in lowered for part in FORBIDDEN_STATE_PARTS):
                raise RuntimeError(
                    'forbidden pickup/disposal state observed: {}'.format(
                        state))

        final = next(
            status for status in reversed(self.statuses)
            if status.state == 'succeeded')
        if 'dry-run' not in final.detail:
            raise RuntimeError(
                'success detail did not declare dry-run: {}'.format(
                    final.detail))

        print(
            'LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK: touch_only task '
            'propagated for plastic_bottle')
        print(
            'LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK: ordered states={}'.format(
                ','.join(REQUIRED_STATES)))
        print(
            'LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK: no '
            'grasp/drop/bin/gripper state was observed')
        print(
            'LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK: final result explicitly '
            'declared dry-run')


def main() -> int:
    rclpy.init()
    node = TouchOnlySmokeProbe()
    try:
        node.run()
        return 0
    except Exception as error:
        print('FAIL: {}'.format(error), file=sys.stderr)
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
