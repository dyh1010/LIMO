import uuid

import rclpy
from limo_cleanup_interfaces.action import ExecuteCleanup
from limo_cleanup_interfaces.msg import CleanupStatus, CleanupTask
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


OBJECT_KEYWORDS = {
    'plastic_bottle': ('塑料瓶', '矿泉水瓶', '饮料瓶', 'plastic bottle', 'bottle'),
    'can': ('易拉罐', '罐子', 'can'),
    'paper_box': ('纸盒', '纸箱', '纸板', 'carton', 'paper box'),
    'generic_waste': ('垃圾', '废物', 'trash', 'garbage', 'waste'),
}

STOP_KEYWORDS = ('停止', '取消', '终止', 'stop', 'cancel', 'abort')


class TaskManager(Node):
    def __init__(self) -> None:
        super().__init__('cleanup_task_manager')

        status_qos = QoSProfile(depth=20)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.task_publisher = self.create_publisher(
            CleanupTask, '/cleanup/task', 10)
        self.status_publisher = self.create_publisher(
            CleanupStatus, '/cleanup/status', status_qos)
        self.create_subscription(
            String, '/cleanup/command_text', self.command_callback, 10)

        self.execute_client = ActionClient(
            self, ExecuteCleanup, '/cleanup/execute')
        self.dispatch_timer = self.create_timer(
            0.5, self.dispatch_active_task)

        self.active_task = None
        self.goal_future = None
        self.active_goal_handle = None
        self.cancel_requested = False
        self.waiting_reported = False

        self.publish_status('idle', 'Task manager is ready')
        self.get_logger().info(
            'Ready. Waiting for commands on /cleanup/command_text')

    def command_callback(self, message: String) -> None:
        raw_text = message.data.strip()
        normalized = raw_text.lower()

        if not normalized:
            self.publish_status('rejected', 'Command is empty')
            return

        if any(keyword in normalized for keyword in STOP_KEYWORDS):
            self.cancel_active_task(raw_text)
            return

        if self.active_task is not None:
            self.publish_status(
                'busy',
                'A task is already active',
                task_id=self.active_task['task_id'],
            )
            return

        object_class = self.find_object_class(normalized)
        if object_class is None:
            self.publish_status(
                'rejected',
                'No supported object class was found in the command',
            )
            return

        task = {
            'task_id': str(uuid.uuid4()),
            'action': 'pick_and_dispose',
            'object_class': object_class,
            'raw_text': raw_text,
        }
        self.active_task = task
        self.cancel_requested = False
        self.waiting_reported = False
        self.publish_task(task)
        self.publish_status(
            'accepted',
            f'Accepted cleanup task for {object_class}',
            task_id=task['task_id'],
        )
        self.get_logger().info(
            f"Accepted task {task['task_id']}: {object_class}")

    def dispatch_active_task(self) -> None:
        if self.active_task is None:
            return
        if self.goal_future is not None or self.active_goal_handle is not None:
            return

        task_id = self.active_task['task_id']
        if not self.execute_client.server_is_ready():
            if not self.waiting_reported:
                self.publish_status(
                    'waiting_for_executor',
                    'Waiting for the cleanup executor',
                    task_id=task_id,
                )
                self.waiting_reported = True
            return

        goal = ExecuteCleanup.Goal()
        goal.task_id = task_id
        goal.object_class = self.active_task['object_class']
        goal.raw_text = self.active_task['raw_text']

        self.publish_status(
            'dispatching', 'Sending task to the cleanup executor', task_id)
        self.goal_future = self.execute_client.send_goal_async(
            goal, feedback_callback=self.feedback_callback)
        self.goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future) -> None:
        try:
            goal_handle = future.result()
        except Exception as error:  # noqa: BLE001
            self.fail_active_task(f'Failed to send action goal: {error}')
            return

        self.goal_future = None
        if goal_handle is None or not goal_handle.accepted:
            if self.cancel_requested:
                self.finish_active_task(
                    'cancelled', 'Task was cancelled before execution')
            else:
                self.fail_active_task('Cleanup executor rejected the task')
            return

        self.active_goal_handle = goal_handle
        task_id = self.active_task['task_id'] if self.active_task else ''
        self.publish_status(
            'executing', 'Cleanup executor accepted the task', task_id)

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

        if self.cancel_requested:
            goal_handle.cancel_goal_async()

    def feedback_callback(self, feedback_message) -> None:
        if self.active_task is None:
            return
        feedback = feedback_message.feedback
        self.publish_status(
            feedback.state,
            feedback.detail,
            self.active_task['task_id'],
            feedback.progress,
        )

    def result_callback(self, future) -> None:
        if self.active_task is None:
            return

        task_id = self.active_task['task_id']
        try:
            wrapped_result = future.result()
            result = wrapped_result.result
            state = result.final_state or ('succeeded' if result.success else 'failed')
            progress = 1.0 if result.success else 0.0
            detail = result.detail
        except Exception as error:  # noqa: BLE001
            state = 'failed'
            progress = 0.0
            detail = f'Failed to receive action result: {error}'

        self.clear_active_task()
        self.publish_status(state, detail, task_id, progress)
        self.get_logger().info(f'Task {task_id} finished: {state}')

    def cancel_active_task(self, raw_text: str) -> None:
        if self.active_task is None:
            self.publish_status('idle', 'There is no active task to cancel')
            return

        task_id = self.active_task['task_id']
        self.cancel_requested = True
        self.publish_task({
            'task_id': task_id,
            'action': 'cancel',
            'raw_text': raw_text,
        })

        if self.active_goal_handle is not None:
            self.publish_status(
                'cancelling', 'Requesting action cancellation', task_id)
            self.active_goal_handle.cancel_goal_async()
            return

        if self.goal_future is not None:
            self.publish_status(
                'cancelling', 'Cancelling task before execution starts', task_id)
            return

        self.clear_active_task()
        self.publish_status('cancelled', 'Active task was cancelled', task_id)
        self.get_logger().info(f'Cancelled waiting task {task_id}')

    def fail_active_task(self, detail: str) -> None:
        if self.active_task is None:
            return
        task_id = self.active_task['task_id']
        self.clear_active_task()
        self.publish_status('failed', detail, task_id)
        self.get_logger().error(f'Task {task_id} failed: {detail}')

    def finish_active_task(self, state: str, detail: str) -> None:
        if self.active_task is None:
            return
        task_id = self.active_task['task_id']
        self.clear_active_task()
        self.publish_status(state, detail, task_id)

    def clear_active_task(self) -> None:
        self.active_task = None
        self.goal_future = None
        self.active_goal_handle = None
        self.cancel_requested = False
        self.waiting_reported = False

    @staticmethod
    def find_object_class(text: str):
        for object_class, keywords in OBJECT_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return object_class
        return None

    def publish_task(self, payload: dict) -> None:
        message = CleanupTask()
        message.stamp = self.get_clock().now().to_msg()
        message.task_id = payload.get('task_id', '')
        message.action = payload.get('action', '')
        message.object_class = payload.get('object_class', '')
        message.raw_text = payload.get('raw_text', '')
        self.task_publisher.publish(message)

    def publish_status(
            self, state: str, detail: str, task_id=None, progress=0.0) -> None:
        message = CleanupStatus()
        message.stamp = self.get_clock().now().to_msg()
        message.state = state
        message.detail = detail
        message.task_id = task_id or ''
        message.progress = float(progress)
        self.status_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TaskManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
