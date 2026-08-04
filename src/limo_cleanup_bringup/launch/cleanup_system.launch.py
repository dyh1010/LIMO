from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    use_mock_executor = LaunchConfiguration('use_mock_executor')
    mock_step_duration = LaunchConfiguration('mock_step_duration')

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_mock_executor',
            default_value='true',
            description='Start the mock cleanup action executor',
        ),
        DeclareLaunchArgument(
            'mock_step_duration',
            default_value='0.6',
            description='Duration of each mock execution step in seconds',
        ),
        Node(
            package='limo_cleanup_executor',
            executable='mock_executor',
            name='cleanup_mock_executor',
            output='screen',
            parameters=[{
                'step_duration': ParameterValue(
                    mock_step_duration, value_type=float),
            }],
            condition=IfCondition(use_mock_executor),
        ),
        Node(
            package='limo_cleanup_core',
            executable='task_manager',
            name='cleanup_task_manager',
            output='screen',
        ),
        Node(
            package='limo_cleanup_language',
            executable='language_node',
            name='cleanup_language_understanding',
            output='screen',
        ),
    ])
