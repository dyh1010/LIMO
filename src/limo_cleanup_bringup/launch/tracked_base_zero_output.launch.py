from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    output_topic = LaunchConfiguration('output_topic')
    publish_rate = LaunchConfiguration('publish_rate')

    return LaunchDescription([
        DeclareLaunchArgument(
            'output_topic',
            default_value='/cleanup/base/safe_cmd_vel',
            description='Private zero-only topic for staged base acceptance',
        ),
        DeclareLaunchArgument(
            'publish_rate',
            default_value='20.0',
            description='Zero command publication rate in Hz',
        ),
        Node(
            package='limo_cleanup_base',
            executable='tracked_base_controller',
            name='cleanup_tracked_base_zero_output',
            output='screen',
            parameters=[{
                'output_topic': output_topic,
                'publish_rate': ParameterValue(
                    publish_rate, value_type=float),
                'allow_base_motion': False,
            }],
        ),
    ])
