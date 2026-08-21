"""Offline ROS2 migration candidate; never the ROS1 Noetic field entry."""

import hashlib
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource


EXPECTED_VENDOR_LAUNCH_SHA256 = (
    '955c98ac653182241a26ae3b4cc4eba3937d1529cd60c0361b23d05f2e4e7aaf'
)
FIXED_DRIVER_ARGUMENTS = {
    'camera_name': 'camera',
    'serial_number': 'CC1WC520183',
    'enable_color': 'true',
    'color_width': '640',
    'color_height': '480',
    'color_fps': '30',
    'color_format': 'MJPG',
    'enable_depth': 'true',
    'depth_width': '640',
    'depth_height': '400',
    'depth_fps': '30',
    'depth_format': 'Y11',
    'enable_ir': 'false',
    'enable_point_cloud': 'false',
    'enable_colored_point_cloud': 'false',
    'depth_registration': 'true',
    'enable_depth_scale': 'true',
    'enable_ldp': 'false',
    'enable_frame_sync': 'true',
    'publish_tf': 'true',
    'tf_publish_rate': '10.0',
}


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_camera_actions(_context):
    vendor_launch = (
        Path(get_package_share_directory('orbbec_camera'))
        / 'launch' / 'dabai.launch.py'
    )
    if not vendor_launch.is_file():
        raise RuntimeError('pinned Orbbec DaBai launch is missing')
    actual_sha256 = _sha256_file(vendor_launch)
    if actual_sha256 != EXPECTED_VENDOR_LAUNCH_SHA256:
        raise RuntimeError(
            'pinned Orbbec DaBai launch SHA-256 mismatch: {}'.format(
                actual_sha256))
    camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(vendor_launch)),
        launch_arguments=FIXED_DRIVER_ARGUMENTS.items(),
    )
    return [GroupAction(
        actions=[camera],
        scoped=True,
        forwarding=False,
    )]


def generate_launch_description():
    """Validate the vendor source before exposing the one camera action."""
    return LaunchDescription([
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        SetEnvironmentVariable('ROS_DOMAIN_ID', '137'),
        SetEnvironmentVariable('ROS2CLI_NO_DAEMON', '1'),
        OpaqueFunction(function=_validated_camera_actions),
    ])
