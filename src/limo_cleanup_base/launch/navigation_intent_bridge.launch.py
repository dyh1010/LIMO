"""Default-disabled ROS2 consumer for approved V2 navigation intents."""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    RegisterEventHandler,
    Shutdown,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    enable = LaunchConfiguration('enable_navigation_intent_bridge')
    waypoint_file = LaunchConfiguration('waypoint_file')
    active_map = LaunchConfiguration('active_v1_map_id')
    epoch_state_file = LaunchConfiguration('epoch_state_file')
    voice_expected = LaunchConfiguration('voice_expected')
    goal_timeout = LaunchConfiguration('goal_timeout')
    consumer = Node(
        package='limo_cleanup_base',
        executable='navigation_intent_consumer',
        name='cleanup_navigation_intent_consumer',
        output='screen',
        condition=IfCondition(enable),
        parameters=[{
            'enabled': True,
            'waypoint_file': waypoint_file,
            'active_v1_map_id': active_map,
            'epoch_state_file': epoch_state_file,
            'status_timeout': 0.25,
            'goal_timeout': ParameterValue(
                goal_timeout, value_type=float),
            'publish_rate': 20.0,
        }],
    )
    verifier = Node(
        package='limo_cleanup_base',
        executable='navigation_topology_verifier',
        name='verify_ros2_navigation_bridge_topology',
        output='screen',
        condition=IfCondition(enable),
        parameters=[{
            'continuous': True,
            'voice_expected': ParameterValue(
                voice_expected, value_type=bool),
            'safety_source_expected': False,
        }],
    )

    def shutdown_if_process_exits(action, label):
        return RegisterEventHandler(OnProcessExit(
            target_action=action,
            on_exit=[Shutdown(
                reason='critical navigation process exited: {}'.format(
                    label))],
        ))

    return LaunchDescription([
        DeclareLaunchArgument(
            'enable_navigation_intent_bridge', default_value='false'),
        DeclareLaunchArgument('waypoint_file', default_value=''),
        DeclareLaunchArgument('active_v1_map_id', default_value=''),
        DeclareLaunchArgument('epoch_state_file', default_value=''),
        DeclareLaunchArgument('voice_expected', default_value='true'),
        DeclareLaunchArgument('goal_timeout', default_value='120.0'),
        shutdown_if_process_exits(consumer, 'consumer'),
        shutdown_if_process_exits(verifier, 'topology verifier'),
        consumer,
        verifier,
    ])
