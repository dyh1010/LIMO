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
    confirmation_timeout_sec = LaunchConfiguration(
        'confirmation_timeout_sec')
    require_wake_word = LaunchConfiguration('require_wake_word')
    trash_bin_waypoint = LaunchConfiguration('trash_bin_waypoint')
    enable_semantic_agent = LaunchConfiguration('enable_semantic_agent')
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
        DeclareLaunchArgument(
            'confirmation_timeout_sec', default_value='10.0'),
        DeclareLaunchArgument('require_wake_word', default_value='true'),
        DeclareLaunchArgument(
            'trash_bin_waypoint', default_value='trash_bin_staging'),
        DeclareLaunchArgument('enable_semantic_agent', default_value='true'),
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
            executable='voice_priority_stop',
            name='voice_priority_stop',
            output='screen',
        ),
        Node(
            package='limo_cleanup_voice',
            executable='voice_semantic_agent',
            name='voice_semantic_agent',
            output='screen',
            condition=IfCondition(enable_semantic_agent),
        ),
        Node(
            package='limo_cleanup_voice',
            executable='voice_dialogue',
            name='voice_dialogue',
            output='screen',
            parameters=[{
                'require_confirmation': ParameterValue(
                    require_confirmation, value_type=bool),
                'confirmation_timeout_sec': ParameterValue(
                    confirmation_timeout_sec, value_type=float),
                'require_wake_word': ParameterValue(
                    require_wake_word, value_type=bool),
                'trash_bin_waypoint': trash_bin_waypoint,
                'semantic_candidate_topic': '/voice/semantic_candidate',
                'priority_broadcast_topic': '/voice/priority_broadcast',
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
