import threading
import time

import rclpy
from limo_cleanup_interfaces.action import ExecuteCleanup
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


EXECUTION_STEPS = (
    ('searching_object', 0.10, 'Searching for the requested object'),
    ('approaching_object', 0.25, 'Approaching the detected object'),
    ('aligning_object', 0.35, 'Aligning the chassis for pickup'),
    ('grasping', 0.50, 'Closing the gripper around the object'),
    ('verifying_grasp', 0.60, 'Verifying that the object was grasped'),
    ('navigating_to_bin', 0.75, 'Navigating to the trash bin'),
    ('aligning_bin', 0.85, 'Aligning with the trash bin'),
    ('dropping', 0.93, 'Dropping the object into the bin'),
    ('verifying_drop', 0.98, 'Verifying that the object was released'),
)


class MockCleanupExecutor(Node):
    def __init__(self) -> None:
        super().__init__('cleanup_mock_executor')
        self.declare_parameter('step_duration', 0.6)
        self.step_duration = float(
            self.get_parameter('step_duration').get_parameter_value().double_value)

        self.callback_group = ReentrantCallbackGroup()
        self.busy_lock = threading.Lock()
        self.busy = False

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
            f'Mock executor ready; step_duration={self.step_duration:.2f}s')

    def goal_callback(self, goal_request):
        with self.busy_lock:
            if self.busy:
                self.get_logger().warning('Rejecting goal because executor is busy')
                return GoalResponse.REJECT
            self.busy = True

        self.get_logger().info(
            f'Accepted goal {goal_request.task_id}: {goal_request.object_class}')
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info(
            f'Accepting cancellation for task {goal_handle.request.task_id}')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        result = ExecuteCleanup.Result()
        task_id = goal_handle.request.task_id

        try:
            for state, progress, detail in EXECUTION_STEPS:
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.final_state = 'cancelled'
                    result.detail = f'Task {task_id} was cancelled'
                    self.get_logger().info(result.detail)
                    return result

                feedback = ExecuteCleanup.Feedback()
                feedback.state = state
                feedback.progress = progress
                feedback.detail = detail
                goal_handle.publish_feedback(feedback)
                self.get_logger().info(
                    f'{task_id}: {state} ({progress:.0%})')
                time.sleep(self.step_duration)

            goal_handle.succeed()
            result.success = True
            result.final_state = 'succeeded'
            result.detail = f'Task {task_id} completed successfully'
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
            with self.busy_lock:
                self.busy = False

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
