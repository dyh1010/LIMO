#!/usr/bin/env python3
"""Pure static policy helpers for a controlled perception deployment."""

import hashlib
import re
from pathlib import Path


SAFE_PATCH_PATHS = (
    'src/limo_cleanup_perception/limo_cleanup_perception/perception_core.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/rgbd_contract.py',
    'src/limo_cleanup_perception/limo_cleanup_perception/'
    'dual_model_detector.py',
    'src/limo_cleanup_perception/test/test_perception_core.py',
    'src/limo_cleanup_perception/test/test_rgbd_contract.py',
    'src/limo_cleanup_bringup/limo_cleanup_bringup/'
    'hardware_readiness_check.py',
    'src/limo_cleanup_bringup/launch/cleanup_system.launch.py',
    'src/limo_cleanup_bringup/launch/hardware_readonly_acceptance.launch.py',
    'src/limo_cleanup_bringup/launch/real_perception_only.launch.py',
    'src/limo_cleanup_bringup/config/dabai_real.yaml',
    'src/limo_cleanup_bringup/test/test_hardware_readiness_check.py',
    'src/limo_cleanup_bringup/test/test_foxy_launch_compat.py',
    'src/limo_cleanup_bringup/test/test_perception_release_artifacts.py',
    'scripts/perception_release_policy.py',
    'scripts/perception_release_preflight.py',
    'scripts/rollback_perception_release.sh',
)

# These paths are retained only as historical provenance.  They are not part
# of a current deployable patch or a field/install/delivery evidence surface.
HISTORICAL_NONAUTHORITATIVE_DOCUMENTS = (
    'docs/REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md',
)

EXPECTED_MODELS = {
    'nongfu_yolov8n_best.pt': (
        'abe7eaf409e3d24d255a627823f4b107'
        'a8884008ab659901c6c50479b2153512'),
    'trash_bin_yolov8n_best.pt': (
        '24beb4a7941ba5d783f1937128b5f0f4307b03513'
        '7889c78be1993cad76b8bc5'),
}

REQUIRED_TOPICS = {
    'rgb_topic': '/camera/color/image_raw',
    'depth_topic': '/camera/depth/image_raw',
    'camera_info_topic': '/camera/color/camera_info',
    'depth_camera_info_topic': '/camera/depth/camera_info',
}

FORBIDDEN_TEXT = (
    'start_camera:=true',
    'ros2 topic pub',
    'ros2 service call',
    'ros2 action send_goal',
    'rsync --delete',
    'git reset',
    'rm -rf',
)

ACTUATION_TOPICS = (
    '/cmd_vel',
    '/arm_controller/joint_trajectory',
    '/gripper_controller/commands',
)


def sha256_file(path):
    """Return a lowercase SHA-256 digest for one file."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def patch_paths(patch_text):
    """Return normalized destination paths declared by a Git patch."""
    paths = []
    for match in re.finditer(
            r'^diff --git a/(.+?) b/(.+?)$', patch_text, re.MULTILINE):
        old_path, new_path = match.groups()
        if old_path != new_path:
            raise ValueError(
                'renamed patch entries are not allowed: {} -> {}'.format(
                    old_path, new_path))
        paths.append(new_path)
    return tuple(paths)


def validate_patch_scope(patch_text):
    """Return policy failures for a recovery patch file set."""
    failures = []
    try:
        actual = patch_paths(patch_text)
    except ValueError as exc:
        return [str(exc)]
    if len(actual) != len(set(actual)):
        failures.append('patch contains duplicate file entries')
    expected = set(SAFE_PATCH_PATHS)
    actual_set = set(actual)
    for path in sorted(actual_set - expected):
        failures.append('unexpected patch path: ' + path)
    for path in sorted(expected - actual_set):
        failures.append('missing patch path: ' + path)
    return failures


def validate_readonly_text(text):
    """Reject commands that exceed the documented read-only procedure."""
    failures = []
    for line in text.splitlines():
        normalized = line.strip().lower()
        executable = normalized.startswith((
            'ros2 ', 'git ', 'rm ', 'rsync ', 'sudo ', 'tar ', 'cp ',
            'mv ', 'start_camera:=', 'bash ', 'sh ', 'python', 'colcon ',
        ))
        if executable:
            failures.extend(
                'forbidden command or topic text: ' + token
                for token in FORBIDDEN_TEXT
                if token.lower() in normalized
            )
        if not any(topic in normalized for topic in ACTUATION_TOPICS):
            continue
        if normalized.startswith('ros2 topic info -v '):
            continue
        if executable:
            failures.append(
                'actuation topic outside read-only info command: '
                + line.strip())
    return failures


def parse_sha256sums(text):
    """Parse a strict GNU-compatible SHA-256 list."""
    result = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        match = re.fullmatch(r'([0-9a-f]{64})  ([^\r\n]+)', line)
        if match is None:
            raise ValueError(
                'invalid SHA-256 line {}: {}'.format(line_number, line))
        digest, relative = match.groups()
        if relative.startswith('/') or '..' in Path(relative).parts:
            raise ValueError('unsafe SHA-256 path: ' + relative)
        if relative in result:
            raise ValueError('duplicate SHA-256 path: ' + relative)
        result[relative] = digest
    return result


def validate_source_sums(text):
    """Require exactly the controlled patch source paths."""
    try:
        values = parse_sha256sums(text)
    except ValueError as exc:
        return [str(exc)]
    expected = set(SAFE_PATCH_PATHS)
    actual = set(values)
    failures = [
        'unexpected source sum path: ' + item
        for item in sorted(actual - expected)
    ]
    failures.extend(
        'missing source sum path: ' + item
        for item in sorted(expected - actual)
    )
    return failures
