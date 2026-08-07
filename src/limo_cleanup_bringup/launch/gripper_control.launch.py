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
            description='dry_run or pymycobot',
        ),
        DeclareLaunchArgument(
            'allow_hardware_motion',
            default_value='false',
            description='Explicit hardware motion authorization',
        ),
        DeclareLaunchArgument(
            'confirmed_gripper_model',
            default_value='mycobot_gripper_ag',
            description='Expected physical gripper model',
        ),
        DeclareLaunchArgument(
            'serial_port',
            default_value='/dev/ttyACM0',
            description='myCobot serial device',
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
                    'serial_port': LaunchConfiguration('serial_port'),
                },
            ],
        ),
    ])
