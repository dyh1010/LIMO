import threading
import time

import rclpy
from limo_cleanup_interfaces.action import ExecuteCleanup
from limo_cleanup_interfaces.msg import ObjectDetection
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .execution_plan import (
    execution_steps,
    validate_goal,
    validate_mock_safety,
)


class MockCleanupExecutor(Node):
    def __init__(self) -> None:
        super().__init__('cleanup_mock_executor')
        self.declare_parameter('step_duration', 0.6)
        self.declare_parameter('detection_timeout', 5.0)
        self.declare_parameter('dry_run', True)
        self.declare_parameter('allow_arm_motion', False)
        self.step_duration = float(
            self.get_parameter('step_duration').get_parameter_value().double_value)
        self.detection_timeout = float(
            self.get_parameter(
                'detection_timeout').get_parameter_value().double_value)
        self.dry_run = bool(
            self.get_parameter('dry_run').get_parameter_value().bool_value)
        self.allow_arm_motion = bool(
            self.get_parameter(
                'allow_arm_motion').get_parameter_value().bool_value)
        validate_mock_safety(self.dry_run, self.allow_arm_motion)

        self.callback_group = ReentrantCallbackGroup()
        self.busy_lock = threading.Lock()
        self.busy = False
        self.detection_condition = threading.Condition()
        self.detections = {}

        self.create_subscription(
            ObjectDetection,
            '/cleanup/detection',
            self.detection_callback,
            10,
            callback_group=self.callback_group,
        )

        self.action_server = ActionServer(
            self,
            ExecuteCleanup,
            '/cleanup/execute',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )
        self.get_logger().info(
            'Mock executor ready; '
            f'step_duration={self.step_duration:.2f}s; '
            f'detection_timeout={self.detection_timeout:.2f}s; '
            f'dry_run={self.dry_run}; '
            f'allow_arm_motion={self.allow_arm_motion}')

    def detection_callback(self, message: ObjectDetection) -> None:
        if not message.task_id:
            self.get_logger().warning('Ignoring detection without a task_id')
            return

        with self.detection_condition:
            self.detections[message.task_id] = message
            self.detection_condition.notify_all()

        self.get_logger().info(
            f'Received detection {message.detection_id} for '
            f'{message.task_id}: {message.object_class} '
            f'({message.confidence:.0%})')

    def goal_callback(self, goal_request):
        try:
            action = validate_goal(
                goal_request.action,
                goal_request.object_class,
                goal_request.task_id,
            )
        except ValueError as error:
            self.get_logger().warning(f'Rejecting goal: {error}')
            return GoalResponse.REJECT

        with self.busy_lock:
            if self.busy:
                self.get_logger().warning('Rejecting goal because executor is busy')
                return GoalResponse.REJECT
            self.busy = True

        self.get_logger().info(
            f'Accepted goal {goal_request.task_id}: '
            f'{action}/{goal_request.object_class}')
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info(
            f'Accepting cancellation for task {goal_handle.request.task_id}')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        result = ExecuteCleanup.Result()
        task_id = goal_handle.request.task_id
        action = validate_goal(
            goal_handle.request.action,
            goal_handle.request.object_class,
            task_id,
        )

        try:
            self.publish_feedback(
                goal_handle,
                'searching_object',
                0.10,
                'Waiting for a matching perception result',
            )
            detection = self.wait_for_detection(
                goal_handle,
                task_id,
                goal_handle.request.object_class,
            )

            if detection is None:
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.final_state = 'cancelled'
                    result.detail = f'Task {task_id} was cancelled'
                    self.get_logger().info(result.detail)
                    return result

                goal_handle.abort()
                result.success = False
                result.final_state = 'object_not_found'
                result.detail = (
                    f'No matching {goal_handle.request.object_class} '
                    f'detection was received within '
                    f'{self.detection_timeout:.1f}s')
                self.get_logger().warning(result.detail)
                return result

            self.publish_feedback(
                goal_handle,
                'object_detected',
                0.20,
                (
                    f'Detected {detection.object_class} at '
                    f'({detection.position.x:.2f}, '
                    f'{detection.position.y:.2f}, '
                    f'{detection.position.z:.2f}) in '
                    f'{detection.frame_id}'
                ),
            )

            for state, progress, detail in execution_steps(action):
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.final_state = 'cancelled'
                    result.detail = f'Task {task_id} was cancelled'
                    self.get_logger().info(result.detail)
                    return result

                self.publish_feedback(goal_handle, state, progress, detail)
                time.sleep(self.step_duration)

            goal_handle.succeed()
            result.success = True
            result.final_state = 'succeeded'
            result.detail = (
                f'Task {task_id} completed {action} successfully in dry-run'
            )
            self.get_logger().info(result.detail)
            return result
        except Exception as error:  # noqa: BLE001
            goal_handle.abort()
            result.success = False
            result.final_state = 'failed'
            result.detail = f'Mock execution failed: {error}'
            self.get_logger().error(result.detail)
            return result
        finally:
            with self.detection_condition:
                self.detections.pop(task_id, None)
            with self.busy_lock:
                self.busy = False

    def wait_for_detection(
            self, goal_handle, task_id: str, object_class: str):
        deadline = time.monotonic() + self.detection_timeout

        with self.detection_condition:
            while True:
                if goal_handle.is_cancel_requested:
                    return None

                detection = self.detections.get(task_id)
                if (
                        detection is not None
                        and detection.object_class == object_class):
                    return detection

                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None

                self.detection_condition.wait(timeout=min(0.1, remaining))

    def publish_feedback(
            self, goal_handle, state: str, progress: float,
            detail: str) -> None:
        feedback = ExecuteCleanup.Feedback()
        feedback.state = state
        feedback.progress = progress
        feedback.detail = detail
        goal_handle.publish_feedback(feedback)
        self.get_logger().info(
            f'{goal_handle.request.task_id}: {state} ({progress:.0%})')

    def destroy_node(self):
        self.action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MockCleanupExecutor()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
