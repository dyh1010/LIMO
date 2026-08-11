"""Measured base-to-camera static transform template, disabled by default."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Create an opt-in static transform publisher for measured extrinsics."""
    arguments = [
        DeclareLaunchArgument(
            'publish_extrinsics',
            default_value='false',
            description='Publish the measured static transform',
        ),
        DeclareLaunchArgument('parent_frame', default_value='base_link'),
        DeclareLaunchArgument('child_frame', default_value='camera_link'),
        DeclareLaunchArgument('x', default_value='0.0'),
        DeclareLaunchArgument('y', default_value='0.0'),
        DeclareLaunchArgument('z', default_value='0.0'),
        DeclareLaunchArgument('roll', default_value='0.0'),
        DeclareLaunchArgument('pitch', default_value='0.0'),
        DeclareLaunchArgument('yaw', default_value='0.0'),
    ]
    publisher = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='cleanup_camera_extrinsics',
        output='screen',
        arguments=[
            LaunchConfiguration('x'),
            LaunchConfiguration('y'),
            LaunchConfiguration('z'),
            LaunchConfiguration('yaw'),
            LaunchConfiguration('pitch'),
            LaunchConfiguration('roll'),
            LaunchConfiguration('parent_frame'),
            LaunchConfiguration('child_frame'),
        ],
        condition=IfCondition(LaunchConfiguration('publish_extrinsics')),
    )
    return LaunchDescription(arguments + [publisher])
