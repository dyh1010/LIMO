"""Start only the vendor DaBai camera launch file."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Build a driver-only launch description with replaceable package names."""
    driver_package = LaunchConfiguration('driver_package')
    driver_launch_file = LaunchConfiguration('driver_launch_file')
    driver_source = PythonLaunchDescriptionSource(
        PathJoinSubstitution([
            FindPackageShare(driver_package),
            'launch',
            driver_launch_file,
        ]))
    return LaunchDescription([
        DeclareLaunchArgument(
            'driver_package',
            default_value='orbbec_camera',
            description='Installed ROS 2 package that owns the DaBai driver',
        ),
        DeclareLaunchArgument(
            'driver_launch_file',
            default_value='dabai.launch.py',
            description='DaBai launch filename in the vendor package',
        ),
        IncludeLaunchDescription(driver_source),
    ])
