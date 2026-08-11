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
    depth_registration = LaunchConfiguration('depth_registration')
    enable_depth_scale = LaunchConfiguration('enable_depth_scale')
    enable_ldp = LaunchConfiguration('enable_ldp')
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
        DeclareLaunchArgument(
            'depth_registration',
            default_value='true',
            description='Register depth to the RGB pixel grid',
        ),
        DeclareLaunchArgument(
            'enable_depth_scale',
            default_value='true',
            description='Publish metric depth using the camera depth scale',
        ),
        DeclareLaunchArgument(
            'enable_ldp',
            default_value='false',
            description='Disable LDP because it produced zero depth pixels',
        ),
        IncludeLaunchDescription(
            driver_source,
            launch_arguments={
                'depth_registration': depth_registration,
                'enable_depth_scale': enable_depth_scale,
                'enable_ldp': enable_ldp,
            }.items(),
        ),
    ])
