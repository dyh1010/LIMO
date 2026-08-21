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

"""ROS1/Noetic thin wrapper that exposes a zero-publish mock profile."""

from .ros1_noetic_adapter import Ros1AdapterConfig, Ros1NoeticAdapterCore


def _runtime_config(rospy):
    config = Ros1AdapterConfig(
        profile=rospy.get_param('~profile', 'offline_text_mock'),
        allow_ros_publish=rospy.get_param('~allow_ros_publish', False),
        allow_production_outputs=rospy.get_param(
            '~allow_production_outputs', False),
    )
    return config.validate()


def main():
    """Start only the explicitly enabled, zero-production ROS1 mock shell."""
    import rospy
    from std_msgs.msg import String

    rospy.init_node('voice_ros1_noetic_adapter', anonymous=False)
    config = _runtime_config(rospy)
    core = Ros1NoeticAdapterCore(config=config)

    def transcript_callback(message):
        decision = core.process_transcript(message.data)
        rospy.logdebug(
            'offline voice decision state=%s intent=%s publish_count=%d',
            decision.state,
            decision.intent,
            decision.actual_publish_count,
        )

    rospy.Subscriber(
        '/voice/text_input', String, transcript_callback,
        queue_size=1, tcp_nodelay=True)
    rospy.logwarn(
        'ROS1 voice adapter is zero-publish offline mock only; '
        'ordinary/STOP outputs remain in-memory')
    rospy.spin()


if __name__ == '__main__':
    main()
