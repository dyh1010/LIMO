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
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Start an optional camera driver and the subscription-only checker."""
    package_share = FindPackageShare('limo_cleanup_bringup')
    config_file = LaunchConfiguration('config_file')
    start_camera = LaunchConfiguration('start_camera')
    driver_package = LaunchConfiguration('driver_package')
    driver_launch_file = LaunchConfiguration('driver_launch_file')
    depth_registration = LaunchConfiguration('depth_registration')
    enable_depth_scale = LaunchConfiguration('enable_depth_scale')
    enable_ldp = LaunchConfiguration('enable_ldp')

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
            'depth_registration': depth_registration,
            'enable_depth_scale': enable_depth_scale,
            'enable_ldp': enable_ldp,
        }.items(),
        condition=IfCondition(start_camera),
    )
    checker = Node(
        package='limo_cleanup_bringup',
        executable='hardware_readiness_check',
        name='cleanup_hardware_readiness',
        output='screen',
        parameters=[
            config_file,
            {
                'rgb_topic': LaunchConfiguration('rgb_topic'),
                'depth_topic': LaunchConfiguration('depth_topic'),
                'camera_info_topic': LaunchConfiguration(
                    'camera_info_topic'),
                'depth_camera_info_topic': LaunchConfiguration(
                    'depth_camera_info_topic'),
                'base_frame': LaunchConfiguration('base_frame'),
                'camera_frame_override': LaunchConfiguration(
                    'camera_frame'),
                'require_tf': ParameterValue(
                    LaunchConfiguration('require_tf'), value_type=bool),
                'check_expected_extrinsics': ParameterValue(
                    LaunchConfiguration('check_expected_extrinsics'),
                    value_type=bool),
                'expected_x': ParameterValue(
                    LaunchConfiguration('expected_x'), value_type=float),
                'expected_y': ParameterValue(
                    LaunchConfiguration('expected_y'), value_type=float),
                'expected_z': ParameterValue(
                    LaunchConfiguration('expected_z'), value_type=float),
                'expected_roll': ParameterValue(
                    LaunchConfiguration('expected_roll'), value_type=float),
                'expected_pitch': ParameterValue(
                    LaunchConfiguration('expected_pitch'), value_type=float),
                'expected_yaw': ParameterValue(
                    LaunchConfiguration('expected_yaw'), value_type=float),
                'translation_tolerance_m': ParameterValue(
                    LaunchConfiguration('translation_tolerance_m'),
                    value_type=float),
                'rotation_tolerance_rad': ParameterValue(
                    LaunchConfiguration('rotation_tolerance_rad'),
                    value_type=float),
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
        DeclareLaunchArgument(
            'rgb_topic',
            default_value='/camera/color/image_raw',
        ),
        DeclareLaunchArgument(
            'depth_topic',
            default_value='/camera/depth/image_raw',
            description='Depth image already registered to RGB pixels',
        ),
        DeclareLaunchArgument(
            'camera_info_topic',
            default_value='/camera/color/camera_info',
        ),
        DeclareLaunchArgument(
            'depth_camera_info_topic',
            default_value='/camera/depth/camera_info',
        ),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument(
            'camera_frame',
            default_value='',
            description='Empty uses the RGB Image header frame_id',
        ),
        DeclareLaunchArgument('require_tf', default_value='true'),
        DeclareLaunchArgument(
            'check_expected_extrinsics', default_value='false',
            description=(
                'Formal readiness requires true and independently measured '
                'expected pose values'),
        ),
        DeclareLaunchArgument('expected_x', default_value='0.0'),
        DeclareLaunchArgument('expected_y', default_value='0.0'),
        DeclareLaunchArgument('expected_z', default_value='0.0'),
        DeclareLaunchArgument('expected_roll', default_value='0.0'),
        DeclareLaunchArgument('expected_pitch', default_value='0.0'),
        DeclareLaunchArgument('expected_yaw', default_value='0.0'),
        DeclareLaunchArgument(
            'translation_tolerance_m', default_value='0.02'),
        DeclareLaunchArgument(
            'rotation_tolerance_rad', default_value='0.05'),
        DeclareLaunchArgument(
            'report_path',
            default_value='/tmp/limo_hardware_readiness.json',
        ),
        camera_launch,
        checker,
    ])
