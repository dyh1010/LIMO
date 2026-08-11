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
    require_wake_word = LaunchConfiguration('require_wake_word')
    enable_tts = LaunchConfiguration('enable_tts')

    return LaunchDescription([
        DeclareLaunchArgument('voice_input_mode', default_value='text'),
        DeclareLaunchArgument('vosk_model_path', default_value=(
            '/home/agilex/limo_cleanup_ws/models/'
            'vosk-model-small-cn-0.22')),
        DeclareLaunchArgument('microphone_device', default_value=''),
        DeclareLaunchArgument('input_sample_rate', default_value='0'),
        DeclareLaunchArgument('block_size', default_value='8000'),
        DeclareLaunchArgument('require_wake_word', default_value='false'),
        DeclareLaunchArgument('enable_tts', default_value='false'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(cleanup_launch),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(voice_launch),
            launch_arguments={
                'input_mode': input_mode,
                'vosk_model_path': vosk_model_path,
                'microphone_device': microphone_device,
                'input_sample_rate': input_sample_rate,
                'block_size': block_size,
                'require_wake_word': require_wake_word,
                'enable_tts': enable_tts,
            }.items(),
        ),
    ])
