from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    authorized = LaunchConfiguration('stage2_hardware_write_authorized')

    return LaunchDescription([
        DeclareLaunchArgument(
            'stage2_hardware_write_authorized',
            default_value='false',
            description=(
                'Start vendor driver only after stage-2 preflight and '
                'explicit现场 authorization'),
        ),
        Node(
            package='limo_base',
            executable='limo_base',
            name='limo_base_stage2',
            output='screen',
            emulate_tty=True,
            parameters=[{
                'port_name': 'ttyTHS0',
                'odom_frame': 'odom',
                'base_frame': 'base_link',
                'pub_odom_tf': False,
                'use_mcnamu': False,
                'control_rate': 50,
            }],
            remappings=[
                ('/cmd_vel', '/cleanup/base/safe_cmd_vel'),
            ],
            condition=IfCondition(authorized),
        ),
    ])
