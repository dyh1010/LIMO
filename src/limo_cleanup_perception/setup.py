from setuptools import find_packages, setup

package_name = 'limo_cleanup_perception'

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
    maintainer_email='2099439179@qq.com',
    description='Perception nodes for the LIMO cleanup robot.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'mock_perception = '
            'limo_cleanup_perception.mock_perception:main',
            'detection_gate = '
            'limo_cleanup_perception.detection_gate:main',
            'dual_model_detector = '
            'limo_cleanup_perception.dual_model_detector:main',
            'offline_dual_detector = '
            'limo_cleanup_perception.offline_dual_detector:main',
        ],
    },
)
