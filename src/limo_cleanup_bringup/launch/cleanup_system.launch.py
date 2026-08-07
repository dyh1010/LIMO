from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import (
    AndSubstitution,
    LaunchConfiguration,
    NotSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    use_mock_executor = LaunchConfiguration('use_mock_executor')
    use_mock_perception = LaunchConfiguration('use_mock_perception')
    use_real_perception = LaunchConfiguration('use_real_perception')
    use_detection_gate = LaunchConfiguration('use_detection_gate')
    mock_step_duration = LaunchConfiguration('mock_step_duration')
    mock_detection_delay = LaunchConfiguration('mock_detection_delay')
    mock_detection_confidence = LaunchConfiguration(
        'mock_detection_confidence')
    detection_timeout = LaunchConfiguration('detection_timeout')
    min_detection_confidence = LaunchConfiguration(
        'min_detection_confidence')
    max_detection_age = LaunchConfiguration('max_detection_age')
    bottle_model_path = LaunchConfiguration('bottle_model_path')
    bin_model_path = LaunchConfiguration('bin_model_path')
    rgb_topic = LaunchConfiguration('rgb_topic')
    depth_topic = LaunchConfiguration('depth_topic')
    camera_info_topic = LaunchConfiguration('camera_info_topic')
    detector_device = LaunchConfiguration('detector_device')
    perception_python = LaunchConfiguration('perception_python')
    use_gripper_controller = LaunchConfiguration('use_gripper_controller')
    gripper_backend = LaunchConfiguration('gripper_backend')
    allow_gripper_motion = LaunchConfiguration('allow_gripper_motion')
    confirmed_gripper_model = LaunchConfiguration(
        'confirmed_gripper_model')
    gripper_serial_port = LaunchConfiguration('gripper_serial_port')

    mock_perception_parameters = [{
        'detection_delay': ParameterValue(
            mock_detection_delay, value_type=float),
        'confidence': ParameterValue(
            mock_detection_confidence, value_type=float),
    }]

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_mock_perception',
            default_value='true',
            description='Start the mock object perception node',
        ),
        DeclareLaunchArgument(
            'use_real_perception',
            default_value='false',
            description='Start the RGB-D dual-model perception node',
        ),
        DeclareLaunchArgument(
            'use_mock_executor',
            default_value='true',
            description='Start the mock cleanup action executor',
        ),
        DeclareLaunchArgument(
            'use_detection_gate',
            default_value='true',
            description='Route detections through the quality gate',
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
        DeclareLaunchArgument(
            'min_detection_confidence',
            default_value='0.5',
            description='Minimum confidence accepted by the detection gate',
        ),
        DeclareLaunchArgument(
            'max_detection_age',
            default_value='1.0',
            description='Maximum detection age accepted by the gate',
        ),
        DeclareLaunchArgument(
            'bottle_model_path',
            default_value=(
                '/mnt/c/Users/DYH/Desktop/limo_graphtest/models/'
                'nongfu_yolov8n_best.pt'),
            description='Bottle detector PT or ONNX path',
        ),
        DeclareLaunchArgument(
            'bin_model_path',
            default_value=(
                '/mnt/c/Users/DYH/Desktop/limo_graphtest/models/'
                'trash_bin_yolov8n_best.pt'),
            description='Trash-bin detector PT or ONNX path',
        ),
        DeclareLaunchArgument(
            'rgb_topic',
            default_value='/camera/color/image_raw',
            description='Aligned RGB image topic',
        ),
        DeclareLaunchArgument(
            'depth_topic',
            default_value='/camera/depth_registered/image_raw',
            description='Depth image registered to the RGB pixel grid',
        ),
        DeclareLaunchArgument(
            'camera_info_topic',
            default_value='/camera/color/camera_info',
            description='Camera intrinsics matching the RGB image',
        ),
        DeclareLaunchArgument(
            'detector_device',
            default_value='0',
            description='Ultralytics inference device, e.g. 0 or cpu',
        ),
        DeclareLaunchArgument(
            'perception_python',
            default_value='/home/dyh/robotics/train/venv/bin/python',
            description='Python interpreter containing Ultralytics and Torch',
        ),
        DeclareLaunchArgument(
            'use_gripper_controller',
            default_value='false',
            description='Start the standalone gripper action controller',
        ),
        DeclareLaunchArgument(
            'gripper_backend',
            default_value='dry_run',
            description='Gripper backend: dry_run or pymycobot',
        ),
        DeclareLaunchArgument(
            'allow_gripper_motion',
            default_value='false',
            description='Explicitly authorize real gripper motion',
        ),
        DeclareLaunchArgument(
            'confirmed_gripper_model',
            default_value='mycobot_gripper_ag',
            description='Expected physical gripper model',
        ),
        DeclareLaunchArgument(
            'gripper_serial_port',
            default_value='/dev/ttyACM0',
            description='myCobot serial device',
        ),
        Node(
            package='limo_cleanup_perception',
            executable='mock_perception',
            name='cleanup_mock_perception',
            output='screen',
            parameters=mock_perception_parameters,
            remappings=[('/cleanup/detection', '/cleanup/detection/raw')],
            condition=IfCondition(
                AndSubstitution(use_mock_perception, use_detection_gate)),
        ),
        Node(
            package='limo_cleanup_perception',
            executable='mock_perception',
            name='cleanup_mock_perception',
            output='screen',
            parameters=mock_perception_parameters,
            condition=IfCondition(
                AndSubstitution(
                    use_mock_perception,
                    NotSubstitution(use_detection_gate))),
        ),
        Node(
            package='limo_cleanup_perception',
            executable='dual_model_detector',
            name='cleanup_dual_model_detector',
            output='screen',
            prefix=[perception_python],
            parameters=[{
                'bottle_model_path': bottle_model_path,
                'bin_model_path': bin_model_path,
                'rgb_topic': rgb_topic,
                'depth_topic': depth_topic,
                'camera_info_topic': camera_info_topic,
                'device': detector_device,
                'always_active': False,
                'confidence': ParameterValue(
                    min_detection_confidence, value_type=float),
            }],
            condition=IfCondition(use_real_perception),
        ),
        Node(
            package='limo_cleanup_perception',
            executable='detection_gate',
            name='cleanup_detection_gate',
            output='screen',
            parameters=[{
                'min_confidence': ParameterValue(
                    min_detection_confidence, value_type=float),
                'max_detection_age': ParameterValue(
                    max_detection_age, value_type=float),
            }],
            condition=IfCondition(use_detection_gate),
        ),
        Node(
            package='limo_cleanup_executor',
            executable='gripper_controller',
            name='cleanup_gripper_controller',
            output='screen',
            parameters=[{
                'backend': gripper_backend,
                'allow_hardware_motion': ParameterValue(
                    allow_gripper_motion, value_type=bool),
                'confirmed_gripper_model': confirmed_gripper_model,
                'serial_port': gripper_serial_port,
            }],
            condition=IfCondition(use_gripper_controller),
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
