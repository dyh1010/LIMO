from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'limo_cleanup_base'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dyh',
    maintainer_email='dyh@todo.todo',
    description='Fail-closed tracked-base motion gateway for LIMO Cleanup.',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'navigation_intent_consumer = '
            'limo_cleanup_base.navigation_intent_consumer:main',
            'navigation_topology_verifier = '
            'limo_cleanup_base.navigation_topology_verifier:main',
            'zero_stage_handoff_verifier = '
            'limo_cleanup_base.zero_stage_handoff_verifier:main',
            'tracked_base_controller = '
            'limo_cleanup_base.tracked_base_controller:main',
        ],
    },
)
