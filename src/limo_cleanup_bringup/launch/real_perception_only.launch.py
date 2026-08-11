"""Sensor-reading real perception without any motion executor."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Start only camera/perception components; never start an actuator."""
    package_share = FindPackageShare('limo_cleanup_bringup')
    config_file = LaunchConfiguration('config_file')
    camera_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                package_share, 'launch', 'dabai_camera.launch.py'])),
        launch_arguments={
            'driver_package': LaunchConfiguration('driver_package'),
            'driver_launch_file': LaunchConfiguration('driver_launch_file'),
            'depth_registration': LaunchConfiguration(
                'depth_registration'),
            'enable_depth_scale': LaunchConfiguration(
                'enable_depth_scale'),
            'enable_ldp': LaunchConfiguration('enable_ldp'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('start_camera')),
    )
    detector = Node(
        package='limo_cleanup_perception',
        executable='dual_model_detector',
        name='cleanup_dual_model_detector',
        output='screen',
        prefix=[LaunchConfiguration('perception_python')],
        parameters=[
            config_file,
            {
                'bottle_model_path': LaunchConfiguration(
                    'bottle_model_path'),
                'bin_model_path': LaunchConfiguration('bin_model_path'),
                'rgb_topic': LaunchConfiguration('rgb_topic'),
                'depth_topic': LaunchConfiguration('depth_topic'),
                'camera_info_topic': LaunchConfiguration(
                    'camera_info_topic'),
                'device': LaunchConfiguration('detector_device'),
                'always_active': ParameterValue(
                    LaunchConfiguration('always_active'), value_type=bool),
            },
        ],
    )
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=PathJoinSubstitution([
                package_share, 'config', 'dabai_real.yaml']),
        ),
        DeclareLaunchArgument('start_camera', default_value='false'),
        DeclareLaunchArgument(
            'driver_package', default_value='orbbec_camera'),
        DeclareLaunchArgument(
            'driver_launch_file', default_value='dabai.launch.py'),
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
            'rgb_topic', default_value='/camera/color/image_raw'),
        DeclareLaunchArgument(
            'depth_topic',
            default_value='/camera/depth/image_raw'),
        DeclareLaunchArgument(
            'camera_info_topic',
            default_value='/camera/color/camera_info'),
        DeclareLaunchArgument(
            'bottle_model_path',
            default_value=(
                '/home/agilex/limo_cleanup_ws/models/'
                'nongfu_yolov8n_best.pt')),
        DeclareLaunchArgument(
            'bin_model_path',
            default_value=(
                '/home/agilex/limo_cleanup_ws/models/'
                'trash_bin_yolov8n_best.pt')),
        DeclareLaunchArgument('detector_device', default_value='0'),
        DeclareLaunchArgument(
            'perception_python',
            default_value='python3',
            description='Python interpreter containing Ultralytics and Torch',
        ),
        DeclareLaunchArgument(
            'always_active',
            default_value='true',
            description='Process RGB-D without waiting for a cleanup task',
        ),
        camera_launch,
        detector,
    ])
