from setuptools import find_packages, setup

package_name = 'limo_cleanup_executor'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', [
            'config/arm_gateway_safe.example.yaml',
            'config/arm_gateway_dry_run.yaml',
            'config/arm_gripper_field_acceptance_matrix.json',
            'config/arm_motion_release.example.json',
            'config/final_gripper_release_manifest.json',
            'config/gripper_gateway_dry_run.yaml',
        ]),
        ('share/' + package_name + '/launch', [
            'launch/arm_gateway_dry_run.launch.py',
            'launch/gripper_gateway_dry_run.launch.py',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dyh',
    maintainer_email='dyh@todo.todo',
    description='Execution nodes for the LIMO cleanup robot.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'gripper_controller = '
            'limo_cleanup_executor.gripper_controller:main',
            'mock_executor = limo_cleanup_executor.mock_executor:main',
            'arm_gateway = limo_cleanup_executor.arm_gateway_node:main',
            'gripper_gateway = '
            'limo_cleanup_executor.gripper_gateway_node:main',
            'verify_arm_gripper_field_acceptance = '
            'limo_cleanup_executor.arm_gripper_field_acceptance:main',
        ],
    },
)
