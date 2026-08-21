from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_config = PathJoinSubstitution([
        FindPackageShare('limo_cleanup_bringup'),
        'config',
        'gripper_safe.yaml',
    ])

    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=default_config,
            description='Safe gripper controller parameter file',
        ),
        DeclareLaunchArgument(
            'backend',
            default_value='dry_run',
            description='dry_run only; real gripper backend is unreleased',
        ),
        DeclareLaunchArgument(
            'allow_hardware_motion',
            default_value='false',
            description='Explicit hardware motion authorization',
        ),
        DeclareLaunchArgument(
            'confirmed_gripper_model',
            default_value='UNRESOLVED_DO_NOT_CONNECT',
            description='Final physical gripper model is not frozen',
        ),
        Node(
            package='limo_cleanup_executor',
            executable='gripper_controller',
            name='cleanup_gripper_controller',
            output='screen',
            parameters=[
                LaunchConfiguration('config_file'),
                {
                    'backend': LaunchConfiguration('backend'),
                    'allow_hardware_motion': ParameterValue(
                        LaunchConfiguration('allow_hardware_motion'),
                        value_type=bool),
                    'confirmed_gripper_model': LaunchConfiguration(
                        'confirmed_gripper_model'),
                },
            ],
        ),
    ])
