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
        ],
    },
)
