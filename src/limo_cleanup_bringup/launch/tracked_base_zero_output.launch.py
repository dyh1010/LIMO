from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    input_topic = LaunchConfiguration('input_topic')
    output_topic = LaunchConfiguration('output_topic')
    authorization_topic = LaunchConfiguration('authorization_topic')
    safety_topic = LaunchConfiguration('safety_topic')
    topology_ready_topic = LaunchConfiguration('topology_ready_topic')
    publish_rate = LaunchConfiguration('publish_rate')

    return LaunchDescription([
        DeclareLaunchArgument(
            'input_topic',
            default_value='/cleanup/base/cmd_vel_request',
            description='Private command request topic',
        ),
        DeclareLaunchArgument(
            'output_topic',
            default_value='/cleanup/base/safe_cmd_vel',
            description='Private zero-only topic for staged base acceptance',
        ),
        DeclareLaunchArgument(
            'authorization_topic',
            default_value='/cleanup/base/motion_authorized',
            description='Private motion authorization topic',
        ),
        DeclareLaunchArgument(
            'safety_topic',
            default_value='/cleanup/base/safety_clear',
            description='Private safety heartbeat topic',
        ),
        DeclareLaunchArgument(
            'topology_ready_topic',
            default_value='/cleanup/navigation/topology_ready',
            description='Private topology readiness topic',
        ),
        DeclareLaunchArgument(
            'publish_rate',
            default_value='20.0',
            description='Zero command publication rate in Hz',
        ),
        Node(
            package='limo_cleanup_base',
            executable='tracked_base_controller',
            # This zero-latched controller remains the unique safety gateway
            # during bridged navigation; navigation never starts a second one.
            name='cleanup_tracked_base_zero_output',
            output='screen',
            parameters=[{
                'input_topic': input_topic,
                'output_topic': output_topic,
                'authorization_topic': authorization_topic,
                'safety_topic': safety_topic,
                'topology_ready_topic': topology_ready_topic,
                'publish_rate': ParameterValue(
                    publish_rate, value_type=float),
                'allow_base_motion': False,
                'command_timeout': 0.25,
                'heartbeat_timeout': 0.25,
                'require_topology_ready': True,
                'topology_timeout': 0.25,
            }],
        ),
    ])
