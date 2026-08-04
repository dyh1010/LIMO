from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    use_mock_executor = LaunchConfiguration('use_mock_executor')
    use_mock_perception = LaunchConfiguration('use_mock_perception')
    mock_step_duration = LaunchConfiguration('mock_step_duration')
    mock_detection_delay = LaunchConfiguration('mock_detection_delay')
    mock_detection_confidence = LaunchConfiguration(
        'mock_detection_confidence')
    detection_timeout = LaunchConfiguration('detection_timeout')

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_mock_perception',
            default_value='true',
            description='Start the mock object perception node',
        ),
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
        DeclareLaunchArgument(
            'mock_detection_delay',
            default_value='1.0',
            description='Delay before publishing a mock detection',
        ),
        DeclareLaunchArgument(
            'mock_detection_confidence',
            default_value='0.92',
            description='Confidence assigned to mock detections',
        ),
        DeclareLaunchArgument(
            'detection_timeout',
            default_value='5.0',
            description='Maximum time the executor waits for a detection',
        ),
        Node(
            package='limo_cleanup_perception',
            executable='mock_perception',
            name='cleanup_mock_perception',
            output='screen',
            parameters=[{
                'detection_delay': ParameterValue(
                    mock_detection_delay, value_type=float),
                'confidence': ParameterValue(
                    mock_detection_confidence, value_type=float),
            }],
            condition=IfCondition(use_mock_perception),
        ),
        Node(
            package='limo_cleanup_executor',
            executable='mock_executor',
            name='cleanup_mock_executor',
            output='screen',
            parameters=[{
                'step_duration': ParameterValue(
                    mock_step_duration, value_type=float),
                'detection_timeout': ParameterValue(
                    detection_timeout, value_type=float),
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
