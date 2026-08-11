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

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    input_mode = LaunchConfiguration('input_mode')
    vosk_model_path = LaunchConfiguration('vosk_model_path')
    wav_path = LaunchConfiguration('wav_path')
    microphone_device = LaunchConfiguration('microphone_device')
    input_sample_rate = LaunchConfiguration('input_sample_rate')
    block_size = LaunchConfiguration('block_size')
    require_confirmation = LaunchConfiguration('require_confirmation')
    require_wake_word = LaunchConfiguration('require_wake_word')
    enable_tts = LaunchConfiguration('enable_tts')
    tts_backend = LaunchConfiguration('tts_backend')

    return LaunchDescription([
        DeclareLaunchArgument('input_mode', default_value='text'),
        DeclareLaunchArgument('vosk_model_path', default_value=(
            '/home/agilex/limo_cleanup_ws/models/'
            'vosk-model-small-cn-0.22')),
        DeclareLaunchArgument('wav_path', default_value=''),
        DeclareLaunchArgument('microphone_device', default_value=''),
        DeclareLaunchArgument('input_sample_rate', default_value='0'),
        DeclareLaunchArgument('block_size', default_value='8000'),
        DeclareLaunchArgument('require_confirmation', default_value='true'),
        DeclareLaunchArgument('require_wake_word', default_value='false'),
        DeclareLaunchArgument('enable_tts', default_value='false'),
        DeclareLaunchArgument('tts_backend', default_value='espeak_ng'),
        Node(
            package='limo_cleanup_voice',
            executable='voice_asr',
            name='voice_asr',
            output='screen',
            parameters=[{
                'input_mode': input_mode,
                'vosk_model_path': vosk_model_path,
                'wav_path': wav_path,
                'microphone_device': microphone_device,
                'input_sample_rate': ParameterValue(
                    input_sample_rate, value_type=int),
                'block_size': ParameterValue(block_size, value_type=int),
            }],
        ),
        Node(
            package='limo_cleanup_voice',
            executable='voice_dialogue',
            name='voice_dialogue',
            output='screen',
            parameters=[{
                'require_confirmation': ParameterValue(
                    require_confirmation, value_type=bool),
                'require_wake_word': ParameterValue(
                    require_wake_word, value_type=bool),
            }],
        ),
        Node(
            package='limo_cleanup_voice',
            executable='voice_tts',
            name='voice_tts',
            output='screen',
            parameters=[{'backend': tts_backend}],
            condition=IfCondition(enable_tts),
        ),
    ])
