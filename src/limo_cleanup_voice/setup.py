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
from glob import glob

from setuptools import find_packages, setup


package_name = 'limo_cleanup_voice'

# LEGACY_ROS2_OFFLINE_ONLY: this ament package is not a ROS1/Noetic field
# entry point.  ROS-independent modules remain valid for offline tests.


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: ['schemas/*.json']},
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml', 'README.md']),
        (
            os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py'),
        ),
        (
            os.path.join('share', package_name, 'config'),
            glob('config/*.yaml'),
        ),
        (
            os.path.join('share', package_name, 'scripts'),
            glob('scripts/*.sh') + glob('scripts/*.ps1'),
        ),
        (
            os.path.join('share', package_name, 'docs'),
            glob('docs/*.md'),
        ),
        (
            os.path.join('share', package_name, 'fixtures'),
            glob('fixtures/*.json'),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dyh',
    maintainer_email='dyh@todo.todo',
    description=(
        'Offline ASR, safety-gated voice intents, and optional TTS for '
        'the LIMO cleanup robot.'
    ),
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'voice_asr = limo_cleanup_voice.voice_asr_node:main',
            'voice_acceptance_fixture = '
            'limo_cleanup_voice.voice_acceptance_fixture:main',
            'voice_corpus_readiness = '
            'limo_cleanup_voice.voice_corpus_readiness:main',
            'voice_dialogue = limo_cleanup_voice.voice_dialogue_node:main',
            'voice_offline_eval = '
            'limo_cleanup_voice.voice_offline_eval:main',
            'voice_model_intake = '
            'limo_cleanup_voice.voice_model_intake:main',
            'voice_preflight = limo_cleanup_voice.voice_preflight:main',
            'voice_regression_aggregate = '
            'limo_cleanup_voice.voice_regression_aggregate:main',
            'voice_priority_stop = '
            'limo_cleanup_voice.voice_priority_stop_node:main',
            'voice_semantic_agent = '
            'limo_cleanup_voice.voice_semantic_agent_node:main',
            'voice_smoke_probe = '
            'limo_cleanup_voice.voice_smoke_probe:main',
            'voice_tts = limo_cleanup_voice.voice_tts_node:main',
            'voice_v2_report = limo_cleanup_voice.voice_v2_report:main',
            'voice_wav_transcription_run = '
            'limo_cleanup_voice.voice_wav_transcription_run:main',
        ],
    },
)
