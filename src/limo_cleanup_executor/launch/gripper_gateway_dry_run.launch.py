"""Launch the simulation-only gripper gateway."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('limo_cleanup_executor'),
        'config',
        'gripper_gateway_dry_run.yaml',
    )
    return LaunchDescription([
        Node(
            package='limo_cleanup_executor',
            executable='gripper_gateway',
            name='cleanup_gripper_gateway',
            output='screen',
            parameters=[config, {
                'backend': 'dry_run',
                'allow_simulated_motion': False,
            }],
        ),
    ])
