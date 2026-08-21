"""Start the arm gateway with an in-memory backend and no device access."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Return a dry-run-only launch description."""
    return LaunchDescription([
        DeclareLaunchArgument(
            'allow_simulated_motion',
            default_value='false',
            description=(
                'Permit only in-memory simulated arm motion; this never '
                'enables hardware'),
        ),
        DeclareLaunchArgument(
            'poll_hz',
            default_value='10.0',
        ),
        DeclareLaunchArgument(
            'dry_run_motion_duration_s',
            default_value='0.20',
        ),
        Node(
            package='limo_cleanup_executor',
            executable='arm_gateway',
            name='cleanup_arm_gateway',
            output='screen',
            parameters=[{
                'backend': 'dry_run',
                'allow_simulated_motion': ParameterValue(
                    LaunchConfiguration('allow_simulated_motion'),
                    value_type=bool,
                ),
                'poll_hz': ParameterValue(
                    LaunchConfiguration('poll_hz'), value_type=float),
                'dry_run_motion_duration_s': ParameterValue(
                    LaunchConfiguration('dry_run_motion_duration_s'),
                    value_type=float,
                ),
            }],
        ),
    ])
