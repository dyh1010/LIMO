import os

from setuptools import find_packages, setup

package_name = 'limo_cleanup_perception'

setup(
    name=package_name,
    version='0.0.0',
    python_requires='>=3.8',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'fixtures'), [
            'fixtures/orchestration_typed_frames.json',
            'fixtures/perception_readiness_negative_cases.json',
            'fixtures/perception_readiness_missing_bundle.json',
            'fixtures/perception_readiness_bundle_template.json',
            'fixtures/rgbd_expected_topics.json',
            'fixtures/perception_field_intake.schema.json',
            'fixtures/perception_field_intake_template.json',
            'fixtures/dabai_camera_query_allowlist.json',
            'fixtures/ros1_dabai_runtime_contract.json',
        ]),
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
            'perception_evaluator = '
            'limo_cleanup_perception.perception_evaluator:main',
            'perception_frame_collector = '
            'limo_cleanup_perception.perception_frame_collector:main',
            'rgbd_bag_indexer = '
            'limo_cleanup_perception.rgbd_bag_indexer:main',
            'perception_readiness = '
            'limo_cleanup_perception.perception_readiness:main',
            'ros1_noetic_field_readiness = '
            'limo_cleanup_perception.ros1_noetic_field_readiness:main',
            'ros1_semantic_evidence_producer = '
            'limo_cleanup_perception.ros1_semantic_evidence_producer:main',
            'typed_raw_binding = '
            'limo_cleanup_perception.typed_raw_binding:main',
        ],
    },
)
