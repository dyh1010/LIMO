#!/usr/bin/env python3
"""Publish preview-only fixed-bottle plans; never command hardware."""

import json
from pathlib import Path

import rospy
from std_msgs.msg import String

from limo_cleanup_ros1_perception.msg import PerceptionFrame
from limo_cleanup_ros1_manipulation.fixed_bottle_pick_core import (
    PickPlanRejected,
    frame_from_ros_message,
    plan_fixed_bottle_pick,
    plan_to_dict,
    validate_gripper_source_bytes,
    validate_policy,
)


class FixedBottlePickPreviewNode:
    """ROS1 adapter whose only output is a non-executable JSON preview."""

    def __init__(self):
        policy_path = Path(rospy.get_param('~policy_path')).resolve(strict=True)
        self._policy = json.loads(policy_path.read_text(encoding='utf-8'))
        validate_policy(self._policy)
        gripper_source_path = Path(
            rospy.get_param('~gripper_source_path')).resolve(strict=True)
        validate_gripper_source_bytes(
            self._policy, gripper_source_path.read_bytes())
        self._publisher = rospy.Publisher(
            '/cleanup/manipulation/pick_preview', String,
            queue_size=1, latch=False)
        self._subscriber = rospy.Subscriber(
            '/cleanup/perception/frames', PerceptionFrame,
            self._on_frame, queue_size=1)

    def _on_frame(self, message):
        try:
            plan = plan_fixed_bottle_pick(
                self._policy, frame_from_ros_message(message),
                rospy.Time.now().to_sec())
            payload = plan_to_dict(plan)
        except (PickPlanRejected, TypeError, ValueError) as exc:
            payload = {
                'execution_permitted': False,
                'disposition': 'PREVIEW_REJECTED',
                'reason': str(exc),
            }
        self._publisher.publish(String(data=json.dumps(
            payload, sort_keys=True, separators=(',', ':'))))


def main():
    rospy.init_node('cleanup_fixed_bottle_pick_preview', anonymous=False)
    FixedBottlePickPreviewNode()
    rospy.spin()


if __name__ == '__main__':
    main()
