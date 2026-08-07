"""Strictly read-only camera, depth, CameraInfo, and TF acceptance."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile, ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Start an optional camera driver and the subscription-only checker."""
    package_share = FindPackageShare('limo_cleanup_bringup')
    config_file = LaunchConfiguration('config_file')
    start_camera = LaunchConfiguration('start_camera')
    driver_package = LaunchConfiguration('driver_package')
    driver_launch_file = LaunchConfiguration('driver_launch_file')

    camera_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                package_share,
                'launch',
                'dabai_camera.launch.py',
            ])),
        launch_arguments={
            'driver_package': driver_package,
            'driver_launch_file': driver_launch_file,
        }.items(),
        condition=IfCondition(start_camera),
    )
    checker = Node(
        package='limo_cleanup_bringup',
        executable='hardware_readiness_check',
        name='cleanup_hardware_readiness',
        output='screen',
        parameters=[
            ParameterFile(config_file, allow_substs=True),
            {
                'rgb_topic': LaunchConfiguration('rgb_topic'),
                'depth_topic': LaunchConfiguration('depth_topic'),
                'camera_info_topic': LaunchConfiguration(
                    'camera_info_topic'),
                'base_frame': LaunchConfiguration('base_frame'),
                'camera_frame_override': LaunchConfiguration(
                    'camera_frame'),
                'require_tf': ParameterValue(
                    LaunchConfiguration('require_tf'), value_type=bool),
                'report_path': LaunchConfiguration('report_path'),
            },
        ],
    )
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=PathJoinSubstitution([
                package_share, 'config', 'dabai_real.yaml']),
            description='Real-hardware parameter file',
        ),
        DeclareLaunchArgument(
            'start_camera',
            default_value='false',
            description='Start only the DaBai driver before checking',
        ),
        DeclareLaunchArgument(
            'driver_package',
            default_value='orbbec_camera',
        ),
        DeclareLaunchArgument(
            'driver_launch_file',
            default_value='dabai.launch.py',
        ),
        DeclareLaunchArgument(
            'rgb_topic',
            default_value='/camera/color/image_raw',
        ),
        DeclareLaunchArgument(
            'depth_topic',
            default_value='/camera/depth_registered/image_raw',
            description='Depth image already registered to RGB pixels',
        ),
        DeclareLaunchArgument(
            'camera_info_topic',
            default_value='/camera/color/camera_info',
        ),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument(
            'camera_frame',
            default_value='',
            description='Empty uses the RGB Image header frame_id',
        ),
        DeclareLaunchArgument('require_tf', default_value='true'),
        DeclareLaunchArgument(
            'report_path',
            default_value='/tmp/limo_hardware_readiness.json',
        ),
        camera_launch,
        checker,
    ])
