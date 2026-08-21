# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""LEGACY_ROS2_OFFLINE_ONLY launch; not a ROS1/Noetic field entry point."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    bringup_share = get_package_share_directory('limo_cleanup_bringup')
    voice_share = get_package_share_directory('limo_cleanup_voice')

    cleanup_launch = os.path.join(
        bringup_share, 'launch', 'cleanup_system.launch.py')
    voice_launch = os.path.join(
        voice_share, 'launch', 'voice_dialogue.launch.py')

    input_mode = LaunchConfiguration('voice_input_mode')
    vosk_model_path = LaunchConfiguration('vosk_model_path')
    microphone_device = LaunchConfiguration('microphone_device')
    input_sample_rate = LaunchConfiguration('input_sample_rate')
    block_size = LaunchConfiguration('block_size')
    mock_step_duration = LaunchConfiguration('mock_step_duration')
    confirmation_timeout_sec = LaunchConfiguration(
        'confirmation_timeout_sec')
    require_wake_word = LaunchConfiguration('require_wake_word')
    trash_bin_waypoint = LaunchConfiguration('trash_bin_waypoint')
    enable_tts = LaunchConfiguration('enable_tts')

    return LaunchDescription([
        DeclareLaunchArgument('voice_input_mode', default_value='text'),
        DeclareLaunchArgument('vosk_model_path', default_value=(
            '/home/agilex/limo_cleanup_ws/models/'
            'vosk-model-small-cn-0.22')),
        DeclareLaunchArgument('microphone_device', default_value=''),
        DeclareLaunchArgument('input_sample_rate', default_value='0'),
        DeclareLaunchArgument('block_size', default_value='8000'),
        DeclareLaunchArgument('mock_step_duration', default_value='0.6'),
        DeclareLaunchArgument(
            'confirmation_timeout_sec', default_value='10.0'),
        DeclareLaunchArgument('require_wake_word', default_value='true'),
        DeclareLaunchArgument(
            'trash_bin_waypoint', default_value='trash_bin_staging'),
        DeclareLaunchArgument('enable_tts', default_value='false'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(cleanup_launch),
            launch_arguments={
                'use_mock_perception': 'true',
                'use_real_perception': 'false',
                'use_mock_executor': 'true',
                'use_detection_gate': 'true',
                'mock_step_duration': mock_step_duration,
                'executor_dry_run': 'true',
                'allow_arm_motion': 'false',
                'use_gripper_controller': 'false',
                'allow_gripper_motion': 'false',
                'use_tracked_base_controller': 'false',
                'allow_base_motion': 'false',
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(voice_launch),
            launch_arguments={
                'input_mode': input_mode,
                'vosk_model_path': vosk_model_path,
                'microphone_device': microphone_device,
                'input_sample_rate': input_sample_rate,
                'block_size': block_size,
                'confirmation_timeout_sec': confirmation_timeout_sec,
                'require_wake_word': require_wake_word,
                'trash_bin_waypoint': trash_bin_waypoint,
                'enable_tts': enable_tts,
            }.items(),
        ),
    ])
