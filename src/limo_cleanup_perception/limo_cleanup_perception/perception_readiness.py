"""Fail-closed, offline readiness gate for formal four-scene evidence."""

from __future__ import annotations

import _frozen_importlib as _host_bootstrap
import _frozen_importlib_external as _host_bootstrap_external
import sys

_STDLIB_ATTESTOR_PRIVATE_NAME = (
    '_limo_cleanup_perception_host_stdlib_attestation_v1')
_STDLIB_ATTESTOR_SIZE_BYTES = 21195
_STDLIB_ATTESTOR_SHA256 = (
    'e94a6be8b17eca37015a2c20eb96308895a3ea234a42741ed9e8d2168893a56e')
_STDLIB_ATTESTOR_FILE = (
    __file__.replace('\\', '/').rsplit('/', 1)[0]
    + '/stdlib_attestation.py')
_WATCHED_STDLIB_MODULES = (
    'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing')


def _failed_external_stdlib_audit(allow_missing=False):
    del allow_missing
    provenance = tuple({
        'module': name,
        'present': name in sys.modules,
        'bound_trusted_object': False,
        'captured_provenance_valid': False,
        'spec_object_matches': False,
        'origin_matches': False,
        'loader_object_matches': False,
        'module_loader_object_matches': False,
        'trusted_origin': None,
        'ambient_origin': None,
        'trusted_loader': None,
        'ambient_loader': None,
        'provenance_valid': False,
        'attestor_identity_valid': False,
    } for name in _WATCHED_STDLIB_MODULES)
    failures = tuple(
        'ros1_field_model_loader_ambient_stdlib_identity_mismatch:' + name
        for name in _WATCHED_STDLIB_MODULES)
    return provenance, failures


def _bootstrap_stdlib_can_skip_finder(provenance, failures):
    try:
        return (
            _STDLIB_ATTESTOR_IDENTITY_VALID is True
            and type(failures) is tuple
            and failures == ()
            and type(provenance) is tuple
            and len(provenance) == len(_WATCHED_STDLIB_MODULES)
            and tuple(
                item.get('module') if type(item) is dict else None
                for item in provenance
            ) == _WATCHED_STDLIB_MODULES
            and all(
                type(item) is dict
                and item.get('present') is True
                and item.get('provenance_valid') is True
                and item.get('attestor_source_sha256')
                == _STDLIB_ATTESTOR_SHA256
                for item in provenance
            )
        )
    except Exception:
        return False


try:
    _attestor_stat = _host_bootstrap_external._os.lstat(
        _STDLIB_ATTESTOR_FILE)
    if (_attestor_stat.st_mode & 0o170000) != 0o100000:
        raise ImportError('stdlib attestor is not a regular non-link file')
    _attestor_loader = _host_bootstrap_external.SourceFileLoader(
        _STDLIB_ATTESTOR_PRIVATE_NAME, _STDLIB_ATTESTOR_FILE)
    _attestor_spec = _host_bootstrap_external.spec_from_file_location(
        _STDLIB_ATTESTOR_PRIVATE_NAME,
        _STDLIB_ATTESTOR_FILE,
        loader=_attestor_loader)
    if _attestor_spec is None or _attestor_spec.loader is not _attestor_loader:
        raise ImportError('stdlib attestor spec unavailable')
    _attestor_module = _host_bootstrap.module_from_spec(_attestor_spec)
    _attestor_loader.exec_module(_attestor_module)
    if (
            _attestor_spec.origin != _STDLIB_ATTESTOR_FILE
            or _attestor_module.__spec__ is not _attestor_spec
            or _attestor_module.__loader__ is not _attestor_loader
            or _attestor_module.__file__ != _STDLIB_ATTESTOR_FILE
            or _attestor_loader.path != _STDLIB_ATTESTOR_FILE
            or _attestor_module.ATTESTOR_SOURCE_SHA256
            != _STDLIB_ATTESTOR_SHA256
            or _attestor_stat.st_size != _STDLIB_ATTESTOR_SIZE_BYTES):
        raise ImportError('stdlib attestor identity mismatch')
except (AttributeError, ImportError, OSError, TypeError, ValueError):
    _external_stdlib_audit = _failed_external_stdlib_audit
    _bootstrap_ambient_stdlib = _failed_external_stdlib_audit
    _STDLIB_ATTESTOR_IDENTITY_VALID = False
else:
    _external_stdlib_audit = _attestor_module.audit_ambient_stdlib
    _bootstrap_ambient_stdlib = _attestor_module.bootstrap_ambient_stdlib
    _begin_canonical_watched_imports = (
        _attestor_module.begin_canonical_watched_imports)
    _end_canonical_watched_imports = (
        _attestor_module.end_canonical_watched_imports)
    _STDLIB_ATTESTOR_IDENTITY_VALID = True

_BOOTSTRAP_STDLIB_PROVENANCE, _BOOTSTRAP_STDLIB_FAILURES = (
    _bootstrap_ambient_stdlib())
_BOOTSTRAP_STDLIB_SKIP_FINDER = _bootstrap_stdlib_can_skip_finder(
    _BOOTSTRAP_STDLIB_PROVENANCE, _BOOTSTRAP_STDLIB_FAILURES)

# A polluted entry process must still be able to import this host gate and get
# a stable failure result.  In that branch, do not import dependency modules
# whose decorators or module initializers could execute an injected stdlib
# callable.  Postponed annotations keep the fail-fast gate importable without
# those runtime-only names.
if not _BOOTSTRAP_STDLIB_FAILURES:
    _use_watched_import_finder = not _BOOTSTRAP_STDLIB_SKIP_FINDER
    if _use_watched_import_finder:
        _watched_import_token = _begin_canonical_watched_imports()
    import argparse
    import ast
    import hashlib
    import json
    import math
    import os
    import re
    import sqlite3
    import stat
    import struct
    import subprocess
    import time
    import xml.etree.ElementTree as ET
    import zipfile
    from pathlib import Path
    from statistics import median
    from typing import Dict, List, Mapping, Optional, Sequence, Tuple

    from limo_cleanup_perception.perception_evaluator import (
        EvaluationThresholds,
        SCENES,
        evaluate_suite,
    )
    from limo_cleanup_perception.evidence_binding import (
        canonical_file_manifest,
        valid_release_id,
    )
    from limo_cleanup_perception.typed_raw_binding import (
        COLLECTOR_KEYS,
        EXPECTED_FORBIDDEN_CONTROL_TOPICS,
        load_formal_typed_records,
    )
    from limo_cleanup_perception.rgbd_bag_indexer import (
        EXPECTED_STREAM_TYPES as RAW_EXPECTED_STREAM_TYPES,
        EXPECTED_TOPIC_MANIFEST_ID,
        FORMAL_RAW_INSPECTION_POLICY,
        MAX_SYNC_SPAN_SEC as RAW_MAX_SYNC_SPAN_SEC,
        default_topic_manifest_path,
        decode_image_pixels,
        inspect_sqlite_bag,
        is_control_topic,
        load_topic_manifest,
    )
    from limo_cleanup_perception.target_contract import EXPECTED_MODEL_SHA256
    from limo_cleanup_perception.ros1_source_core_admission import (
        validate_ros1_source_core_admission,
    )
    if (
            _use_watched_import_finder
            and not _end_canonical_watched_imports(_watched_import_token)):
        _BOOTSTRAP_STDLIB_FAILURES = tuple(
            'ros1_field_model_loader_ambient_stdlib_identity_mismatch:'
            + name for name in _WATCHED_STDLIB_MODULES)


REQUIRED_STREAMS = (
    'rgb', 'aligned_depth', 'rgb_camera_info', 'depth_camera_info')
EXPECTED_STREAM_TYPES = {
    'rgb': 'sensor_msgs/msg/Image',
    'aligned_depth': 'sensor_msgs/msg/Image',
    'rgb_camera_info': 'sensor_msgs/msg/CameraInfo',
    'depth_camera_info': 'sensor_msgs/msg/CameraInfo',
}
REQUIRED_HARDWARE_CHECKS = (
    'rgb_received',
    'aligned_depth_received',
    'camera_info_received',
    'depth_camera_info_received',
    'rgb_depth_same_resolution',
    'camera_info_matches_rgb',
    'depth_camera_info_matches_rgb',
    'camera_intrinsics_valid',
    'depth_camera_intrinsics_valid',
    'rgb_depth_camera_info_timestamp_alignment',
    'rgb_depth_frame_consistency',
    'rgb_camera_info_frame_consistency',
    'rgb_depth_camera_info_frame_consistency',
    'depth_encoding_and_units',
    'base_to_camera_tf',
    'camera_extrinsics_match_measurement',
    'no_actuation_publishers',
    'no_actuation_subscribers',
)
EXPECTED_FRAME_TOPIC = '/cleanup/perception/frames'
EXPECTED_FRAME_TYPE = 'limo_cleanup_interfaces/msg/PerceptionFrame'
EXPECTED_BASE_FRAME = 'base_link'
DEFAULT_CAMERA_FRAME = 'camera_color_optical_frame'
REQUIRED_SOURCE_BASENAMES = (
    'dual_model_detector.py', 'offline_dual_detector.py',
    'perception_core.py', 'perception_evaluator.py',
    'evidence_binding.py',
    'perception_frame_collector.py', 'perception_frame_io.py',
    'perception_readiness.py', 'rgbd_bag_indexer.py', 'rgbd_contract.py',
    'target_contract.py', 'orchestration_contract.py',
    'typed_raw_binding.py')
BUILD_PACKAGE_ROOTS = (
    ('interfaces', 'src/limo_cleanup_interfaces'),
    ('perception', 'src/limo_cleanup_perception'),
)
FORBIDDEN_CONTROL_TOPICS = (
    '/cmd_vel', '/cleanup/base/safe_cmd_vel', '/navigate_to_pose',
    '/arm_controller/joint_trajectory', '/gripper_controller/commands')
TYPED_FRAME_KEYS = {
    'schema_version', 'read_only', 'received_unix_sec',
    'transport_latency_sec', 'stamp', 'frame_id', 'task_id', 'sequence',
    'scene', 'valid', 'status', 'error_code', 'sync_span_sec',
    'processing_latency_sec', 'targets'}
TYPED_TARGET_KEYS = {
    'observation_id', 'object_class', 'confidence', 'valid', 'actionable',
    'status', 'error_code', 'position', 'size', 'bbox', 'depth_m',
    'depth_valid_pixels', 'depth_total_pixels', 'depth_valid_ratio',
    'source', 'position_semantics'}
MIN_UNIQUE_FRAMES = 30
MIN_TARGET_ROI_DEPTH_RATIO = 0.02
MAX_XYZ_ERROR_M = 0.02
MAX_DEPTH_ERROR_M = 0.02
MAX_SYNC_P95_SEC = 0.15
MAX_PROCESSING_P95_SEC = 0.50
MAX_TRANSPORT_P95_SEC = 0.75
MAX_RAW_REJECTION_RATE = 0.05
MAX_RAW_STREAM_UNPAIRED_RATE = 0.05
MAX_TYPED_RAW_UNPAIRED_RATE = 0.05
MAX_EXTRINSIC_TRANSLATION_TOLERANCE_M = 0.02
MAX_EXTRINSIC_ROTATION_TOLERANCE_RAD = 0.05
MAX_FUTURE_SKEW_SEC = 300.0
MAX_FIELD_EVIDENCE_AGE_SEC = 24 * 60 * 60
MAX_SOFTWARE_PROOF_AGE_SEC = 30 * 24 * 60 * 60
ROS2_MIGRATION_INSTALL_GATE_ID = (
    'ROS2_AMENT_MIGRATION_OFFLINE_INSTALL_GATE')
ROS1_FIELD_INSTALL_GATE_ID = 'ROS1_NOETIC_FIELD_INSTALL'
ROS1_RUNTIME_ARCHITECTURE_BLOCKER = (
    'ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED')
ROS1_FIELD_INSTALL_EVIDENCE_MISSING_BLOCKER = (
    'ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING')
ROS1_FIELD_INSTALL_EVIDENCE_NOT_VALIDATED_BLOCKER = (
    'ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_NOT_VALIDATED')
ROS1_BUILD_INSTALL_NOT_VERIFIED_BLOCKER = (
    'ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED')
ROS1_CANONICAL_BINDING_MISSING = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_BINDING_MISSING')
ROS1_CANONICAL_BINDING_MISMATCH = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_BINDING_MISMATCH')
ROS1_CANONICAL_BINDING_INVALID = (
    'ROS1_FIELD_INSTALL_CANONICAL_SOURCE_BINDING_INVALID')
ROS1_TEST_ONLY_SOURCE_BINDING = (
    'ROS1_FIELD_INSTALL_TEST_ONLY_SOURCE_BINDING')
ROS1_FIELD_CONTRACT_RELATIVE = (
    'ros1_overlay_src/limo_cleanup_ros1_perception/config/'
    'ros1_noetic_field_install_contract.json')
ROS1_SOURCE_CORE_BINDING_BLOCKER = (
    'ROS1_SOURCE_CORE_BINDING_NOT_VALIDATED')
ROS1_FORMAL_ROSBAG1_ADMISSION_BLOCKER = (
    'ROS1_FORMAL_ROSBAG1_ADMISSION_NOT_IMPLEMENTED')
ROS1_RUNTIME_IMPLEMENTATION_VALIDATION_BLOCKER = (
    'ROS1_NOETIC_RUNTIME_IMPLEMENTATION_NOT_VALIDATED')
ROS1_RUNTIME_IMPLEMENTATION_ADMISSION_GATE_ID = (
    'ROS1_RUNTIME_IMPLEMENTATION_ADMISSION')
ROS1_RUNTIME_BEHAVIOR_TEST_ANCHOR = {
    'relative_path': (
        'src/limo_cleanup_perception/test/test_ros1_runtime_behavior.py'),
    'size_bytes': 29294,
    'sha256': (
        '15d17863f7d6eacd06043cf4fd7119121da112a048c181186d47bf5f79e51bce'),
    'expected_test_count': 14,
}
ROS1_RUNTIME_IMPLEMENTATION_ANCHORS = {
    'build:cmake': (
        'CMakeLists.txt', 2413,
        '06f39cb1360a96d7cb11990aa4873a3874135c24d198e1d3e67d7dd1ea93e535'),
    'build:package_xml': (
        'package.xml', 927,
        'df07fd234ff1901a101abc742234c282fd061338bd6050d062ffce78814d97d4'),
    'build:setup': (
        'setup.py', 702,
        'bf0a5b4158ec23f72ba9ceb5e335a074d182f112d82690c42cb567d3e69791cb'),
    'entry:dual_model_detector': (
        'scripts/dual_model_detector.py', 148,
        '7be93b45ed4596f6703c0a65c7bb7c570fa2701f3896dc5d2ca754e60937079a'),
    'entry:perception_frame_adapter': (
        'scripts/perception_frame_adapter.py', 141,
        '5089dfcc5aa93d1d015b4ad60e8703798c538486837f09ddf340d62c660c9adf'),
    'entry:perception_frame_collector': (
        'scripts/perception_frame_collector.py', 155,
        '7df816b07aa8120eb2fd28d10bd774bcaa50bd9af6db9006aa01d8477e2ecec8'),
    'entry:perception_readiness': (
        'scripts/perception_readiness.py', 149,
        '54e0bdcd76e670d616152cb2adc5f9fa68663116ea15db757d9d938278512ab8'),
    'entry:rosbag1_rgbd_indexer': (
        'scripts/rosbag1_rgbd_indexer.py', 149,
        '4c5546d950f75beff7cfc57b6f1477e39fc4c064ec15966ecef581fe3fc70620'),
    'entry:typed_raw_binding': (
        'scripts/typed_raw_binding.py', 146,
        '10009177dfad02ba982c3873a763bbf0e7f84fd5fec49105447447db4e75d837'),
    'runtime:dual_model_detector': (
        'src/limo_cleanup_ros1_perception/dual_model_detector.py', 5234,
        '35af03e73571a4236b1560d368bd9eb14ddc66ad884ba3674b20125ddbb3bcf6'),
    'runtime:ros1_adapter': (
        'src/limo_cleanup_ros1_perception/ros1_adapter.py', 25395,
        '30cf2785c93f703ba43c0849971f11a93be3aa256b6a221470fbafe7b5b44e9d'),
    'runtime:formal_producer': (
        'src/limo_cleanup_ros1_perception/rosbag1_rgbd_indexer.py', 119302,
        '92153aec3873e5b1affcb62a6c8a8f33732fd0806142ebb884e41d9c2f1d41cc'),
    'runtime:formal_consumer': (
        'src/limo_cleanup_ros1_perception/typed_raw_binding.py', 85522,
        '99cb0d1779262e9a89c37797e2c31ad93b49da0fe1f14a6897a32e9231788f89'),
    'runtime:model_contract': (
        'src/limo_cleanup_ros1_perception/model_binding_contract.py', 7014,
        '2ce5720e7fc5fbef8d54c6b5640619465bd8bdce4f5c50e97ee55019b085f938'),
    'runtime:perception_core': (
        'src/limo_cleanup_ros1_perception/perception_core.py', 6749,
        '2438bc1fcdce42fb5d4ad9c112a8831696a9aec95821531fb8a574bcf3458d58'),
    'runtime:target_contract': (
        'src/limo_cleanup_ros1_perception/target_contract.py', 8398,
        'b58558651bbbdf7a22b297b3f7cacfbfa27f7038aae0adf3a53457d091eae618'),
    'runtime:rgbd_contract': (
        'src/limo_cleanup_ros1_perception/rgbd_contract.py', 2851,
        'fcbf84e28d266dfb9837a96660d39638a83d1e4f96d79b2359c31d483a3c57d7'),
    'runtime:image_conversion': (
        'src/limo_cleanup_ros1_perception/image_conversion.py', 2258,
        'a5be60045ef3b7ccc36e18e260bfdb68b986c52a91a649b8a21ab584faaa7fdb'),
    'runtime:evidence_binding': (
        'src/limo_cleanup_ros1_perception/evidence_binding.py', 3566,
        '9a2c61b8db6c872ff0439d300dc21bd97d07a008c7aa4f9ffb33db9060bfdab2'),
    'launch:perception_v2_readonly': (
        'launch/perception_v2_readonly.launch', 1464,
        '0185705b93eadb09a9ccc8eb61fd2c25e1a3bf8c9d13064a8f6e98e5c7fed7fc'),
    'launch:perception_v2_formal_capture': (
        'launch/perception_v2_formal_capture.launch', 1633,
        'c835d006d403c89dd61ce8bf76488a2093297bf3c04902799b82b688927c9d42'),
    'contract:read_only_output': (
        'config/read_only_output_contract.json', 1896,
        '02340ee4205991aded52801d7607d0355147d6c5fc8fe816fc034577da52cf2c'),
    'contract:model_bindings': (
        'config/model_bindings.json', 1256,
        '2b24db05298a6560de194435ac4801c1f3c03e6faebeffeacfb1200850db64d8'),
}
ROS1_FORMAL_ROSBAG1_INDEXER_ANCHOR = {
    'module': 'limo_cleanup_ros1_perception.rosbag1_rgbd_indexer',
    'relative_path': (
        'src/limo_cleanup_ros1_perception/rosbag1_rgbd_indexer.py'),
    'size_bytes': 119302,
    'sha256': (
        '92153aec3873e5b1affcb62a6c8a8f33732fd0806142ebb884e41d9c2f1d41cc'),
}
ROS1_FORMAL_ROSBAG1_MANIFEST_ANCHOR = {
    'relative_path': (
        'config/dabai_ros1_formal_four_scene_six_topics_v1.json'),
    'size_bytes': 2866,
    'sha256': (
        '46b135e8aaacce4dc1d552078ff5236299a68efc90ada47420cb6e30ea7fb5f4'),
}
ROS1_MODEL_BINDING_CONTRACT_MODULE = (
    'limo_cleanup_ros1_perception.model_binding_contract')
ROS1_MODEL_BINDING_CONTRACT_ANCHOR = {
    'module': ROS1_MODEL_BINDING_CONTRACT_MODULE,
    'relative_path': (
        'src/limo_cleanup_ros1_perception/model_binding_contract.py'),
    'size_bytes': 7014,
    'sha256': (
        '2ce5720e7fc5fbef8d54c6b5640619465bd8bdce4f5c50e97ee55019b085f938'),
    'ast_semantic_sha256': (
        '7f8c9f5fdb34c27cde12af37859b8645ca2e97393cf66a3970e1f6ed213766d0'),
}
ROS1_MODEL_BINDING_CONTRACT_ALLOWED_IMPORTS = (
    'from:dataclasses:dataclass',
    'from:pathlib:Path',
    'from:typing:Mapping',
    'from:typing:Optional',
    'from:typing:Tuple',
    'import:hashlib',
    'import:json',
    'import:stat',
)
ROS1_MODEL_BINDING_MANIFEST_ANCHOR = {
    'relative_path': 'config/model_bindings.json',
    'size_bytes': 1256,
    'sha256': (
        '2b24db05298a6560de194435ac4801c1f3c03e6faebeffeacfb1200850db64d8'),
}


def _audit_model_loader_ambient_stdlib():
    """Use the interpreter-rooted attestor, never an ambient self-snapshot."""
    return _external_stdlib_audit(allow_missing=False)


def _finite(value, minimum=None, maximum=None) -> bool:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        return False
    return ((minimum is None or value >= minimum)
            and (maximum is None or value <= maximum))


def _lower_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in '0123456789abcdef' for character in value))


def _stamp_ns(stamp) -> Optional[int]:
    if not isinstance(stamp, Mapping):
        return None
    sec = stamp.get('sec')
    nanosec = stamp.get('nanosec')
    if (not isinstance(sec, int) or isinstance(sec, bool)
            or not isinstance(nanosec, int) or isinstance(nanosec, bool)
            or sec < 0 or nanosec < 0 or nanosec >= 1_000_000_000):
        return None
    value = sec * 1_000_000_000 + nanosec
    return value if value > 0 else None


def _percentile(values: Sequence[float], probability: float) -> Optional[float]:
    finite = sorted(float(value) for value in values if _finite(value))
    if not finite:
        return None
    if len(finite) == 1:
        return finite[0]
    index = (len(finite) - 1) * probability
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return finite[lower]
    weight = index - lower
    return finite[lower] * (1.0 - weight) + finite[upper] * weight


def _distribution(values: Sequence[float]) -> Mapping:
    finite = [float(value) for value in values if _finite(value)]
    return {
        'samples': len(finite),
        'p50': median(finite) if finite else None,
        'p95': _percentile(finite, 0.95),
        'max': max(finite) if finite else None,
    }


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest without loading a large artifact."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _required_build_source_names() -> Tuple[str, ...]:
    source_path = Path(__file__).resolve()
    workspace = None
    for candidate in source_path.parents:
        if all((candidate / relative_root).is_dir()
               for _package, relative_root in BUILD_PACKAGE_ROOTS):
            workspace = candidate
            break
    if workspace is None:
        return ()
    result = []
    for package, relative_root in BUILD_PACKAGE_ROOTS:
        package_root = workspace / relative_root
        if any((package_root / marker).exists() for marker in (
                'COLCON_IGNORE', 'AMENT_IGNORE', 'CATKIN_IGNORE')):
            return ()
        for path in package_root.rglob('*'):
            relative = path.relative_to(package_root)
            if (path.is_file() and not path.is_symlink()
                    and not set(relative.parts).intersection({
                        '__pycache__', '.pytest_cache'})
                    and path.suffix.lower() not in ('.pyc', '.pyo')):
                result.append(package + ':' + relative.as_posix())
    return tuple(sorted(result))


def _isolated_colcon_argv(workspace_root: str, isolation_root: str) -> Mapping:
    workspace = Path(workspace_root).as_posix().rstrip('/')
    isolation = Path(isolation_root).as_posix().rstrip('/')
    packages = ['limo_cleanup_interfaces', 'limo_cleanup_perception']
    common = [
        '--packages-select', *packages,
        '--build-base', isolation + '/build',
        '--install-base', isolation + '/install',
        '--executor', 'sequential',
        '--event-handlers', 'console_cohesion+',
    ]
    return {
        'build_argv': [
            'colcon', '--log-base', isolation + '/log', 'build',
            '--base-paths', workspace + '/src', *common],
        'test_argv': [
            'colcon', '--log-base', isolation + '/test-log', 'test',
            '--packages-select', *packages,
            '--build-base', isolation + '/build',
            '--install-base', isolation + '/install',
            '--executor', 'sequential',
            '--event-handlers', 'console_cohesion+'],
        'test_result_argv': [
            'colcon', 'test-result', '--test-result-base',
            isolation + '/build', '--verbose'],
    }


def _path_is_linklike(path: Path) -> bool:
    """Reject symlinks and Windows reparse points for install evidence."""
    try:
        value = Path(path).lstat()
    except OSError:
        return False
    if stat.S_ISLNK(value.st_mode):
        return True
    if (stat.S_ISREG(value.st_mode)
            and getattr(value, 'st_nlink', 1) != 1):
        return True
    attributes = getattr(value, 'st_file_attributes', 0)
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _perception_workspace_root(workspace: Path = None) -> Optional[Path]:
    if workspace is not None:
        try:
            return Path(workspace).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
    source_path = Path(__file__).resolve()
    for candidate in source_path.parents:
        if (candidate / ROS1_FIELD_CONTRACT_RELATIVE).is_file():
            return candidate
    return None


def load_ros1_noetic_field_install_contract(
        workspace: Path = None) -> Mapping:
    """Load and hash the frozen ROS1 field-install contract."""
    root = _perception_workspace_root(workspace)
    failures = []
    path = None if root is None else root / ROS1_FIELD_CONTRACT_RELATIVE
    payload = None
    if path is None or not path.is_file() or _path_is_linklike(path):
        failures.append('ros1_field_install_contract_missing_or_linked')
    else:
        try:
            payload = _strict_json_loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            failures.append('ros1_field_install_contract_invalid_json')
    return {
        'path': None if path is None else str(path.resolve()),
        'size_bytes': None if path is None or not path.is_file()
        else path.stat().st_size,
        'sha256': None if path is None or not path.is_file()
        else sha256_file(path),
        'payload': payload,
        'failures': failures,
    }


def _ros1_contract_schema_failures(contract) -> List[str]:
    failures = []
    expected = {
        'schema_version', 'contract_id', 'runtime_family', 'ros_distro',
        'required_for_delivery', 'indexer_only_sufficient', 'package',
        'required_capabilities', 'required_python_modules',
        'required_entrypoints', 'required_config_files',
        'required_fixture_files', 'required_launch_files',
        'required_catkin_test_files',
        'interface_modes', 'model_manifest',
        'python_runtime_dependency_lock', 'install_policy'}
    if not isinstance(contract, Mapping) or set(contract) != expected:
        failures.append('ros1_field_install_contract_schema_invalid')
        return failures
    if (contract.get('schema_version') != 1
            or contract.get('contract_id') != ROS1_FIELD_INSTALL_GATE_ID
            or contract.get('runtime_family') != 'ROS1'
            or contract.get('ros_distro') != 'noetic'
            or contract.get('required_for_delivery') is not True
            or contract.get('indexer_only_sufficient') is not False):
        failures.append('ros1_field_install_contract_identity_invalid')
    package = contract.get('package')
    if (not isinstance(package, Mapping)
            or set(package) != {
                'name', 'source_root', 'build_type',
                'required_dependencies', 'dependency_tags',
                'forbidden_dependencies'}
            or package.get('name') != 'limo_cleanup_ros1_perception'
            or package.get('source_root')
            != 'ros1_overlay_src/limo_cleanup_ros1_perception'
            or package.get('build_type') != 'catkin'):
        failures.append('ros1_field_install_package_contract_invalid')
    if isinstance(package, Mapping):
        required_dependencies = package.get('required_dependencies')
        forbidden_dependencies = package.get('forbidden_dependencies')
        dependency_tags = package.get('dependency_tags')
        for name, values in (
                ('required_dependencies', required_dependencies),
                ('forbidden_dependencies', forbidden_dependencies)):
            if (not isinstance(values, list) or not values
                    or len(values) != len(set(values))
                    or any(not isinstance(item, str) or not item
                           for item in values)):
                failures.append(
                    'ros1_field_install_contract_invalid:' + name)
        if (isinstance(required_dependencies, list)
                and isinstance(forbidden_dependencies, list)
                and set(required_dependencies).intersection(
                    forbidden_dependencies)):
            failures.append('ros1_field_install_dependency_contract_conflict')
        expected_dependency_tags = {
            'buildtool_depend': ['catkin'],
            'build_depend': ['message_generation'],
            'depend': [
                'cv_bridge', 'geometry_msgs', 'message_filters', 'rosbag',
                'rospy', 'sensor_msgs', 'std_msgs', 'tf2_msgs', 'tf2_ros'],
            'exec_depend': [
                'message_runtime', 'python3-numpy', 'python3-opencv'],
            'test_depend': ['python3-nose'],
        }
        if not _exact_json_value(dependency_tags, expected_dependency_tags):
            failures.append(
                'ros1_field_install_contract_invalid:dependency_tags')
        elif sorted({
                item for tag, values in dependency_tags.items()
                if tag not in {'buildtool_depend', 'test_depend'}
                for item in values}) != sorted(required_dependencies):
            failures.append(
                'ros1_field_install_contract_invalid:dependency_tags')
    collections = (
        'required_capabilities', 'required_python_modules',
        'required_config_files', 'required_fixture_files',
        'required_launch_files', 'required_catkin_test_files')
    for name in collections:
        values = contract.get(name)
        if (not isinstance(values, list) or not values
                or any(not isinstance(item, str) or not item
                       for item in values)
                or len(values) != len(set(values))):
            failures.append('ros1_field_install_contract_invalid:' + name)
    if contract.get('required_launch_files') != [
            'perception_v2_formal_capture.launch',
            'perception_v2_readonly.launch']:
        failures.append(
            'ros1_field_install_contract_invalid:required_launch_files')
    if contract.get('required_catkin_test_files') != [
            'test_rosbag1_isolated_probe.py',
            'test_rosbag1_rgbd_indexer.py',
            'test_ros1_adapter_pure_fake.py',
            'test_runtime_install_contract.py']:
        failures.append(
            'ros1_field_install_contract_invalid:required_catkin_test_files')
    entries = contract.get('required_entrypoints')
    if (not isinstance(entries, Mapping) or not entries
            or any(not isinstance(key, str) or not key
                   or not isinstance(value, str) or not value
                   for key, value in entries.items())):
        failures.append('ros1_field_install_contract_invalid:entrypoints')
    elif (len(set(entries.values())) != len(entries)
          or any(not value.startswith('scripts/')
                 or value.startswith('/') or '\\' in value
                 or '..' in value.split('/') for value in entries.values())):
        failures.append('ros1_field_install_contract_invalid:entrypoints')
    modes = contract.get('interface_modes')
    if (not isinstance(modes, Mapping)
            or set(modes) != {'native_ros1_messages', 'audited_bridge'}
            or any(not isinstance(value, Mapping)
                   or set(value) != {'required_files'}
                   or not isinstance(value.get('required_files'), list)
                   or not value.get('required_files')
                   for value in modes.values())):
        failures.append('ros1_field_install_contract_invalid:interface_modes')
    elif any(
            len(value['required_files']) != len(set(value['required_files']))
            or any(not isinstance(item, str) or not item
                   or item.startswith('/') or '\\' in item
                   or '..' in item.split('/')
                   for item in value['required_files'])
            for value in modes.values()):
        failures.append('ros1_field_install_contract_invalid:interface_modes')
    model_manifest = contract.get('model_manifest')
    if (not isinstance(model_manifest, Mapping)
            or set(model_manifest) != {'path', 'required_classes'}
            or model_manifest.get('path') != 'config/model_bindings.json'
            or model_manifest.get('required_classes') != [
                'plastic_bottle', 'trash_bin']):
        failures.append('ros1_field_install_contract_invalid:model_manifest')
    runtime_lock = contract.get('python_runtime_dependency_lock')
    expected_runtime_lock = {
        'lock_id': 'ROS1_NOETIC_PERCEPTION_PYTHON_RUNTIME_V1',
        'version_provenance': {
            'authority': 'latest_verified_limo_jetson_runtime',
            'source_path': 'docs/foxy_arm64_deployment.md',
            'source_scope': 'verified_arm64_runtime_versions',
            'source_declaration_is_install_evidence': False,
        },
        'source_policy': {
            'declaration_path': 'setup.py',
            'exact_pins_required': True,
            'rosdep_claim_forbidden': True,
            'source_declaration_is_install_evidence': False,
        },
        'install_evidence_policy': {
            'distribution_artifact_identity_required': True,
            'distribution_metadata_required': True,
            'fresh_isolated_import_probe_required': True,
            'module_origin_required': True,
            'reported_distribution_version_required': True,
            'reported_module_version_required': True,
            'runtime_provisioning_required': True,
            'regular_files_only': True,
            'linklike_forbidden': True,
        },
        'requirements': [
            {
                'distribution': 'numpy', 'import_name': 'numpy',
                'exact_version': '1.23.4',
                'requirement': 'numpy==1.23.4',
                'required_for': 'rgbd_array_processing',
                'provisioning_policy': (
                    'isolated_offline_artifact_exact_version'),
                'deployment_source': 'isolated_offline_wheel_artifact',
                'distribution_artifact_provenance_policy': (
                    'required_field_install_artifact_identity'),
                'distribution_artifact_format': 'wheel',
            },
            {
                'distribution': 'torch', 'import_name': 'torch',
                'exact_version': '2.1.0a0+41361538.nv23.06',
                'requirement': 'torch==2.1.0a0+41361538.nv23.06',
                'required_for': 'dual_model_backend',
                'provisioning_policy': (
                    'isolated_offline_artifact_exact_version'),
                'deployment_source': (
                    'isolated_jetson_vendor_wheel_artifact'),
                'distribution_artifact_provenance_policy': (
                    'required_field_install_artifact_identity'),
                'distribution_artifact_format': 'wheel',
            },
            {
                'distribution': 'ultralytics',
                'import_name': 'ultralytics',
                'exact_version': '8.3.21',
                'requirement': 'ultralytics==8.3.21',
                'required_for': 'dual_model_inference',
                'provisioning_policy': (
                    'isolated_offline_artifact_exact_version'),
                'deployment_source': 'isolated_offline_wheel_artifact',
                'distribution_artifact_provenance_policy': (
                    'required_field_install_artifact_identity'),
                'distribution_artifact_format': 'wheel',
            },
        ],
    }
    if not _exact_json_value(runtime_lock, expected_runtime_lock):
        failures.append(
            'ros1_field_install_contract_invalid:python_runtime_dependency_lock')
    policy = contract.get('install_policy')
    if (not isinstance(policy, Mapping)
            or set(policy) != {
                'isolation_prefix', 'source_space_relative',
                'application_root_relative',
                'runtime_provisioning_strategy', 'regular_files_only',
                'required_build_tool', 'forbidden_build_tools',
                'required_exit_codes', 'required_environment_flags'}
            or policy.get('isolation_prefix') != '/tmp/limo_v2_ros1_noetic_'
            or policy.get('source_space_relative') != 'ros1_overlay_src'
            or policy.get('application_root_relative')
            != 'install/lib/python3/dist-packages'
            or policy.get('runtime_provisioning_strategy')
            != 'offline_wheels_no_index_no_deps_target'
            or policy.get('regular_files_only') is not True
            or policy.get('required_build_tool') != 'catkin_make'
            or policy.get('forbidden_build_tools') != ['colcon']
            or policy.get('required_exit_codes') != {
                'build': 0, 'install': 0, 'test': 0, 'test_result': 0}
            or policy.get('required_environment_flags') != [
                'build_started', 'install_created', 'install_started',
                'runtime_provisioning_completed',
                'runtime_provisioning_started',
                'shell_entered', 'tests_started']):
        failures.append('ros1_field_install_contract_invalid:install_policy')
    return failures


def _canonical_identity_set_sha256(entries: Sequence[Mapping]) -> str:
    value = json.dumps(
        list(entries), ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def _ros1_role_source_paths(
        contract: Mapping, interface_mode: str) -> Mapping:
    """Map every required installed role to its audited source file."""
    package_name = contract['package']['name']
    roles = {
        'package:package.xml': 'package.xml',
    }
    for name in contract['required_python_modules']:
        roles['python:' + name] = 'src/{}/{}'.format(package_name, name)
    for name, relative in contract['required_entrypoints'].items():
        roles['entry:' + name] = relative
    for name in contract['required_config_files']:
        roles['config:' + name] = 'config/' + name
    for name in contract['required_fixture_files']:
        roles['fixture:' + name] = 'fixtures/' + name
    for name in contract['required_launch_files']:
        roles['launch:' + name] = 'launch/' + name
    mode = contract['interface_modes'].get(interface_mode, {})
    for relative in mode.get('required_files', []):
        roles['interface:' + relative] = relative
    return dict(sorted(roles.items()))


def _ros1_required_install_roles(
        contract: Mapping, interface_mode: str) -> Mapping:
    package_name = contract['package']['name']
    layouts = {
        'package:package.xml': 'share/{}/package.xml'.format(package_name),
    }
    for name in contract['required_python_modules']:
        layouts['python:' + name] = (
            'lib/python3/dist-packages/{}/{}'.format(package_name, name))
    for name, relative in contract['required_entrypoints'].items():
        layouts['entry:' + name] = 'lib/{}/{}'.format(
            package_name, Path(relative).name)
    for name in contract['required_config_files']:
        layouts['config:' + name] = 'share/{}/config/{}'.format(
            package_name, name)
    for name in contract['required_fixture_files']:
        layouts['fixture:' + name] = 'share/{}/fixtures/{}'.format(
            package_name, name)
    for name in contract['required_launch_files']:
        layouts['launch:' + name] = 'share/{}/launch/{}'.format(
            package_name, name)
    mode = contract['interface_modes'].get(interface_mode, {})
    for relative in mode.get('required_files', []):
        layouts['interface:' + relative] = 'share/{}/{}'.format(
            package_name, relative)
    return dict(sorted(layouts.items()))


def _ros1_required_source_paths(
        contract: Mapping, interface_mode: str) -> Sequence[str]:
    package_name = contract['package']['name']
    paths = {'CMakeLists.txt', 'package.xml', 'setup.py'}
    paths.update(
        'src/{}/{}'.format(package_name, name)
        for name in contract['required_python_modules'])
    paths.update(contract['required_entrypoints'].values())
    paths.update(
        'config/' + name for name in contract['required_config_files'])
    paths.update(
        'fixtures/' + name for name in contract['required_fixture_files'])
    paths.update('launch/' + name for name in contract['required_launch_files'])
    paths.update(
        'test/' + name for name in contract['required_catkin_test_files'])
    paths.update(
        contract['interface_modes'].get(interface_mode, {}).get(
            'required_files', []))
    return tuple(sorted(paths))


def _validate_ros1_source_core_binding(workspace: Path) -> Mapping:
    """Run only the host-owned source admission trust root.

    The ROS1 package validator is deliberately not imported or executed here;
    its code identity is reopened and checked by the host admission module as
    a diagnostic release artifact only.
    """
    try:
        report = validate_ros1_source_core_admission(workspace)
    except Exception as error:
        return {
            'gate_id': 'ROS1_SOURCE_CORE_ADMISSION_V2',
            'required_for_complete_runtime': True,
            'validated_pass': False,
            'package_validator_executed': False,
            'package_validator_return_value_trusted': False,
            'architecture_blockers': [ROS1_SOURCE_CORE_BINDING_BLOCKER],
            'failures': [
                'ros1_source_core_admission_exception:'
                + type(error).__name__],
        }
    if not isinstance(report, Mapping):
        return {
            'gate_id': 'ROS1_SOURCE_CORE_ADMISSION_V2',
            'required_for_complete_runtime': True,
            'validated_pass': False,
            'package_validator_executed': False,
            'package_validator_return_value_trusted': False,
            'architecture_blockers': [ROS1_SOURCE_CORE_BINDING_BLOCKER],
            'failures': ['ros1_source_core_admission_report_invalid'],
        }
    return report


def _exact_module_file_identity(package_root, module_name, filename):
    """Read one exact regular module and bind identity to those same bytes."""
    package_root = Path(package_root).resolve(strict=True)
    package_dir = (
        package_root / 'src' / 'limo_cleanup_ros1_perception')
    path = package_dir / filename
    try:
        candidate = path
        while candidate != package_root:
            if _path_is_linklike(candidate):
                raise OSError('linked path component')
            parent = candidate.parent
            if parent == candidate:
                raise OSError('path escaped package')
            candidate = parent
        resolved = path.resolve(strict=True)
        resolved.relative_to(package_root)
        metadata_before = resolved.stat()
        if not stat.S_ISREG(metadata_before.st_mode):
            raise OSError('not regular')
        raw = resolved.read_bytes()
        metadata_after = resolved.stat()
        stable_fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns')
        if (not stat.S_ISREG(metadata_after.st_mode)
                or metadata_after.st_size != len(raw)
                or any(
                    getattr(metadata_before, name, None)
                    != getattr(metadata_after, name, None)
                    for name in stable_fields)):
            raise OSError('module changed while reading')
    except (OSError, RuntimeError, ValueError):
        raise ValueError(
            'ros1_field_model_loader_module_missing_or_linked:'
            + module_name)
    return resolved, {
        'module': module_name,
        'relative_path': (
            'src/limo_cleanup_ros1_perception/' + filename),
        'path': str(resolved),
        'size_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }, raw


def _model_binding_contract_imports(tree):
    """Return the exact static import surface of the stdlib-only contract."""
    imports = []
    invalid = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    invalid = True
                imports.append('import:' + alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not isinstance(node.module, str):
                invalid = True
                continue
            for alias in node.names:
                if alias.asname is not None:
                    invalid = True
                imports.append(
                    'from:{}:{}'.format(node.module, alias.name))
    return tuple(sorted(imports)), invalid


def _strict_model_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate model manifest JSON key: ' + key)
        value[key] = item
    return value


def _reject_model_nonfinite(value):
    raise ValueError('non-finite model manifest JSON constant: ' + value)


def _strict_model_json_loads(value):
    return json.loads(
        value, object_pairs_hook=_strict_model_json_object,
        parse_constant=_reject_model_nonfinite)


def _host_validate_ros1_model_manifest(
        package_root: Path, model_path: Path,
        expected_models: Mapping) -> Mapping:
    """Parse and validate the real manifest using host-owned code only."""
    failures = []
    identity = None
    payload = None
    models = None
    package_root = Path(package_root).resolve(strict=True)
    expected_path = package_root / ROS1_MODEL_BINDING_MANIFEST_ANCHOR[
        'relative_path']
    try:
        declared = Path(model_path)
        if not declared.is_absolute():
            declared = Path.cwd() / declared
        candidate = declared.absolute()
        while candidate != package_root:
            if _path_is_linklike(candidate):
                raise OSError('linked path component')
            parent = candidate.parent
            if parent == candidate:
                raise OSError('path escaped package')
            candidate = parent
        if _path_is_linklike(package_root):
            raise OSError('linked package root')
        supplied = declared.resolve(strict=True)
        supplied.relative_to(package_root)
        if supplied != expected_path.resolve(strict=True):
            failures.append(
                'ros1_field_model_binding_manifest_path_mismatch')
        if not stat.S_ISREG(supplied.stat().st_mode):
            raise OSError('not regular')
        raw = supplied.read_bytes()
        identity = {
            'relative_path': supplied.relative_to(package_root).as_posix(),
            'path': str(supplied),
            'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }
        for key in ('relative_path', 'size_bytes', 'sha256'):
            if identity.get(key) != ROS1_MODEL_BINDING_MANIFEST_ANCHOR.get(
                    key):
                failures.append(
                    'ros1_field_model_binding_manifest_anchor_mismatch:'
                    + key)
        payload = _strict_model_json_loads(raw.decode('utf-8'))
    except (OSError, RuntimeError, UnicodeError, ValueError,
            json.JSONDecodeError) as error:
        failures.append(
            'ros1_field_model_binding_manifest_invalid:'
            + type(error).__name__)

    expected_top_keys = {
        'schema_version', 'manifest_id', 'runtime_family', 'ros_distro',
        'read_only', 'authorizes_motion', 'delivery_ready', 'runtime',
        'load_policy', 'models'}
    expected_policy = {
        'regular_file_required': True,
        'sha256_required': True,
        'single_exact_class_required': True,
        'missing_model_is_fatal': True,
        'hash_mismatch_is_fatal': True,
        'silent_fallback_or_relabel_forbidden': True,
        'automatic_download_forbidden': True,
    }
    if (
            not isinstance(payload, Mapping)
            or set(payload) != expected_top_keys
            or not isinstance(payload.get('schema_version'), int)
            or isinstance(payload.get('schema_version'), bool)
            or payload.get('schema_version') != 1
            or payload.get('manifest_id')
            != 'limo-ros1-dual-model-bindings-v1'
            or payload.get('runtime_family') != 'ROS1'
            or payload.get('ros_distro') != 'noetic'
            or payload.get('read_only') is not True
            or payload.get('authorizes_motion') is not False
            or payload.get('delivery_ready') is not False
            or payload.get('runtime') != 'ultralytics-8.3.21'
            or payload.get('load_policy') != expected_policy):
        failures.append('ros1_field_model_binding_manifest_policy_invalid')
    else:
        models = payload.get('models')
        if (not isinstance(models, Mapping)
                or set(models) != set(expected_models)):
            failures.append(
                'ros1_field_model_binding_manifest_class_set_invalid')
        else:
            expected_entry_keys = {
                'class_name', 'filename', 'deployment_path', 'size_bytes',
                'sha256', 'backend'}
            for label, expected in expected_models.items():
                item = models.get(label)
                if (
                        not isinstance(item, Mapping)
                        or set(item) != expected_entry_keys
                        or not isinstance(item.get('size_bytes'), int)
                        or isinstance(item.get('size_bytes'), bool)
                        or not _lower_sha256(item.get('sha256'))
                        or dict(item) != dict(expected)):
                    failures.append(
                        'ros1_field_model_binding_manifest_entry_invalid:'
                        + label)
    return {
        'validated_pass': not failures,
        'identity': identity,
        'payload': payload,
        'models': models,
        'failures': sorted(set(failures)),
    }


def _validate_ros1_model_loader(
        package_root: Path, model_path: Path,
        expected_models: Mapping) -> Mapping:
    """Validate model bindings without executing any candidate package code."""
    loader_name = ROS1_MODEL_BINDING_CONTRACT_MODULE
    watched_names = (
        'json', 'hashlib', 'stat', 'dataclasses', 'pathlib', 'typing',
        'numpy', 'limo_cleanup_ros1_perception',
        'limo_cleanup_ros1_perception.model_binding_contract',
        'limo_cleanup_ros1_perception.dual_model_detector',
    )
    missing = object()
    watched_before = {
        name: sys.modules.get(name, missing) for name in watched_names}
    path_before = list(sys.path)
    meta_path_before = list(sys.meta_path)
    stdlib_provenance, stdlib_failures = (
        _audit_model_loader_ambient_stdlib())
    environment_restored = (
        sys.path == path_before
        and sys.meta_path == meta_path_before
        and all(sys.modules.get(name, missing) is value
                for name, value in watched_before.items()))
    if stdlib_failures:
        failures = sorted(set(stdlib_failures))
        return {
            'validated_pass': False,
            'validation_scope': 'manifest_contract_source_admission',
            'loader_module': loader_name,
            'host_owned_manifest_parser': True,
            'manifest_path': str(model_path),
            'manifest_sha256': None,
            'manifest_identity': None,
            'manifest_anchor': dict(ROS1_MODEL_BINDING_MANIFEST_ANCHOR),
            'classes': [],
            'backend_initialized': False,
            'model_artifacts_validated': False,
            'runtime_backend_validated': False,
            'candidate_contract_executed': False,
            'candidate_contract_return_value_trusted': False,
            'detector_module_executed': False,
            'target_contract_executed': False,
            'numpy_required_by_gate': False,
            'module_provenance': [],
            'contract_anchor': dict(ROS1_MODEL_BINDING_CONTRACT_ANCHOR),
            'contract_ast_semantic_sha256': None,
            'contract_imports': [],
            'allowed_contract_imports': list(
                ROS1_MODEL_BINDING_CONTRACT_ALLOWED_IMPORTS),
            'candidate_contract_equivalence_validated': False,
            'ambient_path_entry_count': len(path_before),
            'ambient_meta_path_finder_count': len(meta_path_before),
            'ambient_stdlib_identity_clean': False,
            'ambient_stdlib_provenance': list(stdlib_provenance),
            'environment_restored': environment_restored,
            'failures': failures,
        }
    try:
        package_root = Path(package_root).resolve(strict=True)
    except (OSError, RuntimeError):
        return {
            'validated_pass': False,
            'validation_scope': 'manifest_contract_source_admission',
            'loader_module': loader_name,
            'manifest_path': str(model_path),
            'manifest_sha256': None,
            'classes': [],
            'backend_initialized': False,
            'model_artifacts_validated': False,
            'runtime_backend_validated': False,
            'candidate_contract_executed': False,
            'candidate_contract_return_value_trusted': False,
            'module_provenance': [],
            'contract_imports': [],
            'ambient_stdlib_identity_clean': not stdlib_failures,
            'ambient_stdlib_provenance': list(stdlib_provenance),
            'environment_restored': True,
            'failures': sorted(set(
                stdlib_failures
                + ('ros1_field_model_loader_package_missing',))),
        }

    failures = list(stdlib_failures)
    identity = None
    contract_imports = ()
    contract_ast_sha256 = None
    contract_failures = []
    try:
        contract_path, identity, raw = _exact_module_file_identity(
            package_root, loader_name, 'model_binding_contract.py')
        for key in ('module', 'relative_path', 'size_bytes', 'sha256'):
            if identity.get(key) != ROS1_MODEL_BINDING_CONTRACT_ANCHOR.get(
                    key):
                contract_failures.append(
                    'ros1_field_model_binding_contract_anchor_mismatch:'
                    + key)
        if (len(raw) != identity.get('size_bytes')
                or hashlib.sha256(raw).hexdigest()
                != identity.get('sha256')):
            contract_failures.append(
                'ros1_field_model_binding_contract_snapshot_mismatch')
        source = raw.decode('utf-8').replace('\r\n', '\n')
        if '\r' in source:
            contract_failures.append(
                'ros1_field_model_binding_contract_lone_cr_forbidden')
        tree = ast.parse(
            source, filename=str(contract_path), feature_version=(3, 8))
        contract_ast_sha256 = hashlib.sha256(ast.dump(
            tree, annotate_fields=True,
            include_attributes=False).encode('utf-8')).hexdigest()
        if contract_ast_sha256 != ROS1_MODEL_BINDING_CONTRACT_ANCHOR.get(
                'ast_semantic_sha256'):
            contract_failures.append(
                'ros1_field_model_binding_contract_ast_anchor_mismatch')
        contract_imports, imports_invalid = (
            _model_binding_contract_imports(tree))
        if (imports_invalid
                or contract_imports
                != ROS1_MODEL_BINDING_CONTRACT_ALLOWED_IMPORTS):
            contract_failures.append(
                'ros1_field_model_binding_contract_import_surface_invalid')
    except (OSError, UnicodeError, SyntaxError, ValueError) as error:
        contract_failures.append(
            'ros1_field_model_binding_contract_unavailable:'
            + type(error).__name__)
    failures.extend(contract_failures)

    manifest_validation = _host_validate_ros1_model_manifest(
        package_root, model_path, expected_models)
    failures.extend(manifest_validation['failures'])

    environment_restored = (
        sys.path == path_before
        and sys.meta_path == meta_path_before
        and all(sys.modules.get(name, missing) is value
                for name, value in watched_before.items()))
    if not environment_restored:
        failures.append('ros1_field_model_loader_environment_not_restored')

    models = manifest_validation.get('models')
    manifest_identity = manifest_validation.get('identity') or {}
    failures = sorted(set(failures))
    return {
        'validated_pass': not failures,
        'validation_scope': 'manifest_contract_source_admission',
        'loader_module': loader_name,
        'host_owned_manifest_parser': True,
        'manifest_path': str(model_path),
        'manifest_sha256': manifest_identity.get('sha256'),
        'manifest_identity': manifest_validation.get('identity'),
        'manifest_anchor': dict(ROS1_MODEL_BINDING_MANIFEST_ANCHOR),
        'classes': (
            sorted(models) if isinstance(models, Mapping) else []),
        'backend_initialized': False,
        'model_artifacts_validated': False,
        'runtime_backend_validated': False,
        'candidate_contract_executed': False,
        'candidate_contract_return_value_trusted': False,
        'detector_module_executed': False,
        'target_contract_executed': False,
        'numpy_required_by_gate': False,
        'module_provenance': ([] if identity is None else [identity]),
        'contract_anchor': dict(ROS1_MODEL_BINDING_CONTRACT_ANCHOR),
        'contract_ast_semantic_sha256': contract_ast_sha256,
        'contract_imports': list(contract_imports),
        'allowed_contract_imports': list(
            ROS1_MODEL_BINDING_CONTRACT_ALLOWED_IMPORTS),
        'candidate_contract_equivalence_validated': not contract_failures,
        'ambient_path_entry_count': len(path_before),
        'ambient_meta_path_finder_count': len(meta_path_before),
        'ambient_stdlib_identity_clean': not stdlib_failures,
        'ambient_stdlib_provenance': list(stdlib_provenance),
        'environment_restored': environment_restored,
        'failures': failures,
    }


def _audit_ros1_formal_rosbag1_admission_source(package_root: Path) -> Mapping:
    """Recompute the anchored ROS1 formal rosbag1 source admission gate.

    This host-owned audit never imports or executes the ROS1 package.  It
    reopens the exact indexer and manifest as ordinary non-link files, checks
    their release identities, then independently inspects the AST and manifest
    policy.  Passing this gate proves only that the formal producer/admission
    source generation is present.  It never admits a bag, supplies field
    evidence, or authorizes delivery.
    """
    module_anchor = ROS1_FORMAL_ROSBAG1_INDEXER_ANCHOR
    manifest_anchor = ROS1_FORMAL_ROSBAG1_MANIFEST_ANCHOR
    module_name = module_anchor['module']
    failures = []
    path = None
    identity = None
    source = None
    tree = None
    try:
        path, identity, raw = _exact_module_file_identity(
            package_root, module_name, 'rosbag1_rgbd_indexer.py')
        source = raw.decode('utf-8')
        tree = ast.parse(
            source, filename=str(path), feature_version=(3, 8))
    except (OSError, UnicodeError, SyntaxError, ValueError) as error:
        failures.append(
            'ros1_formal_rosbag1_source_unavailable:'
            + type(error).__name__)

    if identity is not None and (
            identity.get('relative_path') != module_anchor['relative_path']
            or identity.get('size_bytes') != module_anchor['size_bytes']
            or identity.get('sha256') != module_anchor['sha256']
            or len(raw) != identity.get('size_bytes')
            or hashlib.sha256(raw).hexdigest() != identity.get('sha256')):
        failures.append('ros1_formal_rosbag1_indexer_identity_mismatch')

    assignments = {}
    function_counts = {}
    function_nodes = {}
    imports = set()
    true_literals = 0
    false_literals = 0
    if tree is not None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_counts[node.name] = function_counts.get(
                    node.name, 0) + 1
                function_nodes[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    try:
                        assignments[target.id] = ast.literal_eval(node.value)
                    except (TypeError, ValueError):
                        pass
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update('import:' + item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.update(
                    'from:{}:{}'.format(node.module, item.name)
                    for item in node.names)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (isinstance(key, ast.Constant)
                            and key.value == 'formal_acceptance'
                            and isinstance(value, ast.Constant)):
                        if value.value is True:
                            true_literals += 1
                        elif value.value is False:
                            false_literals += 1

        expected_assignments = {
            'EXPECTED_FORMAL_MANIFEST_BASENAME': Path(
                manifest_anchor['relative_path']).name,
            'EXPECTED_FORMAL_MANIFEST_SHA256': manifest_anchor['sha256'],
            'FORMAL_MODE': 'sensor_only_short_sample',
            'DIAGNOSTIC_MODE': 'diagnostic_shared_graph',
            'FORMAL_ACCEPTANCE_MODE': 'formal_scene_raw_capture',
            'FORMAL_CAMERA_ONLY_MODE': 'formal_camera_only',
            'FORMAL_SCENES': (
                'background', 'bin_only', 'bottle_in_bin',
                'bottle_outside'),
        }
        if any(
                assignments.get(name) != value
                for name, value in expected_assignments.items()):
            failures.append('ros1_formal_rosbag1_ast_constants_invalid')
        required_functions = {
            '_formal_bag_identity', '_inspect_records_formal',
            'default_formal_manifest_path', 'inspect_bag',
            'inspect_formal_scene', 'inspect_records',
            'load_formal_manifest', 'main'}
        if any(function_counts.get(name) != 1 for name in required_functions):
            failures.append('ros1_formal_rosbag1_ast_functions_missing')
        expected_imports = {
            'import:argparse', 'import:hashlib', 'import:io', 'import:json',
            'import:math', 'import:os', 'import:re', 'import:stat',
            'import:rosbag',
            'from:pathlib:Path', 'from:typing:Dict', 'from:typing:List',
            'from:typing:Mapping', 'from:typing:Optional',
            'from:typing:Sequence', 'from:typing:Tuple'}
        if imports != expected_imports:
            failures.append('ros1_formal_rosbag1_import_surface_invalid')
        call_contract = {
            'load_formal_manifest': {'load_manifest'},
            'inspect_formal_scene': {
                '_inspect_records_formal', 'load_formal_manifest'},
            'inspect_records': {'inspect_formal_scene'},
            'inspect_bag': {
                '_formal_bag_identity', 'inspect_records',
                'load_formal_manifest'},
            'main': {'inspect_bag', 'parse_args'},
            '_inspect_records_formal': {
                '_accepted_bundles', '_validate_formal_alignment',
                '_validate_formal_capture_window',
                '_validate_formal_isolation_ledger', '_validate_tf_graph',
                '_validated_formal_source_capture'},
        }
        for function_name, required_calls in call_contract.items():
            function_node = function_nodes.get(function_name)
            actual_calls = set()
            referenced_names = set()
            if function_node is not None:
                for nested in ast.walk(function_node):
                    if isinstance(nested, ast.Name):
                        referenced_names.add(nested.id)
                    if isinstance(nested, ast.Call):
                        called = nested.func
                        if isinstance(called, ast.Name):
                            actual_calls.add(called.id)
                        elif isinstance(called, ast.Attribute):
                            actual_calls.add(called.attr)
            if not required_calls.issubset(actual_calls):
                failures.append(
                    'ros1_formal_rosbag1_call_contract_invalid:'
                    + function_name)
            if function_name in ('inspect_bag', 'inspect_records', 'main'):
                if 'FORMAL_CAMERA_ONLY_MODE' not in referenced_names:
                    failures.append(
                        'ros1_formal_rosbag1_mode_branch_missing:'
                        + function_name)
        dynamic_calls = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {'__import__', 'eval', 'exec', 'compile'}}
        if dynamic_calls:
            failures.append('ros1_formal_rosbag1_dynamic_execution_forbidden')
        for token in (
                'rospy.Publisher', 'rospy.Service', 'ServiceProxy',
                'SimpleAction' + 'Client', 'send_' + 'goal(',
                'Twi' + 'st(', '/cmd_vel',
                '/move_base/goal', '/arm_controller/command',
                '/gripper_controller/command'):
            if token in source:
                failures.append(
                    'ros1_formal_rosbag1_control_surface_forbidden:'
                    + token.replace('/', '_').replace(' ', '_'))
        if true_literals < 1 or false_literals < 1:
            failures.append(
                'ros1_formal_rosbag1_acceptance_branches_incomplete')

    manifest_path = Path(package_root) / manifest_anchor['relative_path']
    manifest_identity = None
    manifest = None
    try:
        resolved_package = Path(package_root).resolve(strict=True)
        candidate = manifest_path
        while candidate != resolved_package:
            if _path_is_linklike(candidate):
                raise OSError('linked path component')
            parent = candidate.parent
            if parent == candidate:
                raise OSError('path escaped package')
            candidate = parent
        resolved_manifest = manifest_path.resolve(strict=True)
        resolved_manifest.relative_to(resolved_package)
        if not stat.S_ISREG(resolved_manifest.stat().st_mode):
            raise OSError('manifest is not regular')
        manifest_raw = resolved_manifest.read_bytes()
        manifest_identity = {
            'relative_path': manifest_anchor['relative_path'],
            'path': str(resolved_manifest),
            'size_bytes': len(manifest_raw),
            'sha256': hashlib.sha256(manifest_raw).hexdigest(),
        }
        manifest = _strict_json_loads(manifest_raw.decode('utf-8'))
    except (OSError, RuntimeError, UnicodeError, ValueError,
            json.JSONDecodeError):
        failures.append('ros1_formal_rosbag1_manifest_unavailable_or_invalid')

    if manifest_identity is not None and (
            manifest_identity.get('size_bytes')
            != manifest_anchor['size_bytes']
            or manifest_identity.get('sha256') != manifest_anchor['sha256']):
        failures.append('ros1_formal_rosbag1_manifest_identity_mismatch')

    expected_topics = [
        {
            'role': 'rgb', 'name': '/camera/color/image_raw',
            'type': 'sensor_msgs/Image',
            'md5sum': '060021388200f6f0f447d0fcd9c64743',
            'callerid': '/camera/camera', 'latching': False,
        },
        {
            'role': 'raw_depth', 'name': '/camera/depth/image_raw',
            'type': 'sensor_msgs/Image',
            'md5sum': '060021388200f6f0f447d0fcd9c64743',
            'callerid': '/camera/camera', 'latching': False,
        },
        {
            'role': 'rgb_camera_info',
            'name': '/camera/color/camera_info',
            'type': 'sensor_msgs/CameraInfo',
            'md5sum': 'c9a58c1b0b154e0e6da7578cb991d214',
            'callerid': '/camera/camera', 'latching': True,
        },
        {
            'role': 'depth_camera_info',
            'name': '/camera/depth/camera_info',
            'type': 'sensor_msgs/CameraInfo',
            'md5sum': 'c9a58c1b0b154e0e6da7578cb991d214',
            'callerid': '/camera/camera', 'latching': True,
        },
        {
            'role': 'tf', 'name': '/tf',
            'type': 'tf2_msgs/TFMessage',
            'md5sum': '94810edda583a504dfda3829e70d7eec',
            'callerid': '/camera/camera', 'latching': False,
        },
        {
            'role': 'tf_static', 'name': '/tf_static',
            'type': 'tf2_msgs/TFMessage',
            'md5sum': '94810edda583a504dfda3829e70d7eec',
            'callerid': '/camera/camera', 'latching': True,
        },
    ]
    expected_manifest = {
        'schema_version': 1,
        'manifest_id': 'limo-dabai-ros1-formal-four-scene-six-topics-v1',
        'ros_major': 1,
        'ros_distro': 'noetic',
        'bag_format': 'rosbag1-v2',
        'inspection_scope': 'formal_scene_raw_capture',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'starts_ros_graph': False,
        'driver_callerid': '/camera/camera',
        'allowed_scenes': [
            'background', 'bin_only', 'bottle_in_bin', 'bottle_outside'],
        'min_accepted_bundles': 30,
        'max_sync_span_sec': 0.15,
        'max_record_header_skew_sec': 0.75,
        'max_unpaired_rate': 0.05,
        'capture_window_policy': {
            'source': 'decoded_rgb_depth_headers_and_record_times',
            'isolate_old_latched_camera_info': True,
            'require_isolation_ledger': True,
            'allowed_isolated_roles': [
                'rgb_camera_info', 'depth_camera_info'],
            'max_isolated_messages_per_role': 1,
        },
        'alignment_policy': {
            'require_all_stream_frames_equal': True,
            'require_all_stream_grids_equal': True,
            'require_stable_frame_per_stream': True,
            'require_stable_grid_per_stream': True,
        },
        'tf_policy': {
            'allowed_frame_prefix': 'camera',
            'require_unique_parent_per_child': True,
            'require_unique_owner_per_child': True,
            'forbid_static_dynamic_child_overlap': True,
            'forbidden_frame_ids': [
                'map', 'odom', 'base_footprint', 'base_link', 'laser_link',
                'imu_link', 'arm_base_link', 'gripper_link'],
        },
        'topics': expected_topics,
    }
    manifest_policy_valid = _exact_json_value(manifest, expected_manifest)
    if not manifest_policy_valid:
        failures.append('ros1_formal_rosbag1_manifest_policy_invalid')

    unique_failures = sorted(set(failures))
    if unique_failures:
        unique_failures = sorted(set(
            unique_failures + [ROS1_FORMAL_ROSBAG1_ADMISSION_BLOCKER]))
    return {
        'gate_id': 'ROS1_FORMAL_ROSBAG1_ADMISSION',
        'scope': 'source_implementation_only',
        'validated_pass': not unique_failures,
        'source_identity': identity,
        'manifest_identity': manifest_identity,
        'formal_mode_literal': assignments.get('FORMAL_MODE'),
        'formal_acceptance_mode_literal': assignments.get(
            'FORMAL_ACCEPTANCE_MODE'),
        'formal_camera_only_mode_literal': assignments.get(
            'FORMAL_CAMERA_ONLY_MODE'),
        'formal_scene_literals': list(assignments.get('FORMAL_SCENES', ())),
        'required_functions_present': sorted(function_counts),
        'import_surface': sorted(imports),
        'formal_acceptance_true_literals': true_literals,
        'formal_acceptance_false_literals': false_literals,
        'capability_declaration_can_override': False,
        'authorizes_field_delivery': False,
        'field_evidence_admitted': False,
        'delivery_ready': False,
        'failures': unique_failures,
    }


def _runtime_exact_source(package_root: Path, role: str) -> Mapping:
    """Reopen one host-anchored runtime source without importing it."""
    relative, expected_size, expected_sha = (
        ROS1_RUNTIME_IMPLEMENTATION_ANCHORS[role])
    root = Path(package_root).resolve(strict=True)
    if (not relative or relative.startswith('/') or '\\' in relative
            or '..' in relative.split('/')):
        raise ValueError('runtime anchor path is unsafe')
    path = root.joinpath(*relative.split('/'))
    candidate = path
    while candidate != root:
        if _path_is_linklike(candidate):
            raise OSError('runtime source has linked path component')
        parent = candidate.parent
        if parent == candidate:
            raise OSError('runtime source escaped package')
        candidate = parent
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError('runtime source is not regular')
    raw = resolved.read_bytes()
    identity = {
        'role': role,
        'relative_path': relative,
        'path': str(resolved),
        'size_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'expected_size_bytes': expected_size,
        'expected_sha256': expected_sha,
    }
    identity['identity_valid'] = (
        len(raw) == expected_size and identity['sha256'] == expected_sha)
    if relative.endswith('.py'):
        source = raw.decode('utf-8')
        tree = ast.parse(
            source, filename=str(resolved), feature_version=(3, 8))
        identity['ast_sha256'] = hashlib.sha256(
            ast.dump(tree, include_attributes=False).encode('utf-8')
        ).hexdigest()
    else:
        source = raw.decode('utf-8')
        tree = None
    return {
        'identity': identity,
        'raw': raw,
        'source': source,
        'tree': tree,
    }


def _ast_top_level_names(tree) -> Tuple[set, set]:
    functions = set()
    classes = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
    return functions, classes


def _ast_literal_assignment(tree, name):
    values = []
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            try:
                values.append(ast.literal_eval(node.value))
            except (TypeError, ValueError):
                values.append(None)
    return values[0] if len(values) == 1 else None


def _run_ros1_runtime_behavior_admission(package_root: Path) -> Mapping:
    """Run only nine anchored pure-fake behavior tests in an isolated child."""
    failures = []
    anchor = ROS1_RUNTIME_BEHAVIOR_TEST_ANCHOR
    host_workspace = _perception_workspace_root()
    identity = None
    if host_workspace is None:
        failures.append('ros1_runtime_behavior_host_workspace_unavailable')
    else:
        test_path = host_workspace.joinpath(*anchor['relative_path'].split('/'))
        try:
            candidate = test_path
            while candidate != host_workspace:
                if _path_is_linklike(candidate):
                    raise OSError('behavior test has linked path component')
                parent = candidate.parent
                if parent == candidate:
                    raise OSError('behavior test escaped workspace')
                candidate = parent
            resolved = test_path.resolve(strict=True)
            resolved.relative_to(host_workspace)
            if not stat.S_ISREG(resolved.stat().st_mode):
                raise OSError('behavior test is not regular')
            raw = resolved.read_bytes()
            identity = {
                'relative_path': anchor['relative_path'],
                'path': str(resolved),
                'size_bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(),
            }
            if (identity['size_bytes'] != anchor['size_bytes']
                    or identity['sha256'] != anchor['sha256']):
                failures.append('ros1_runtime_behavior_test_identity_mismatch')
        except (OSError, RuntimeError):
            failures.append('ros1_runtime_behavior_test_unavailable')

    command_report = None
    if not failures:
        host_src = host_workspace / 'src/limo_cleanup_perception'
        overlay_src = (
            Path(package_root).resolve(strict=True)
            / 'src')
        module = (
            'src.limo_cleanup_perception.test.'
            'test_ros1_runtime_behavior')
        selected = [
            module + '.PerceptionPipelineBehaviorTests',
            module + '.Ros1AdapterBehaviorTests',
        ]
        bootstrap = (
            "import json,os,sys,unittest\n"
            "defaults=list(sys.path)\n"
            "fixed=[os.environ['LIMO_HOST_SRC'],"
            "os.environ['LIMO_ROS1_RUNTIME_OVERLAY']+'/src',"
            "os.environ['LIMO_HOST_WORKSPACE']]\n"
            "sys.path[:]=fixed+[item for item in defaults if item not in fixed]\n"
            "suite=unittest.defaultTestLoader.loadTestsFromNames("
            + repr(selected) + ")\n"
            "result=unittest.TextTestRunner(stream=sys.stderr,verbosity=1).run(suite)\n"
            "payload={'tests_run':result.testsRun,'failures':len(result.failures),"
            "'errors':len(result.errors),'skipped':len(result.skipped),"
            "'expected_failures':len(result.expectedFailures),"
            "'unexpected_successes':len(result.unexpectedSuccesses),"
            "'successful':result.wasSuccessful()}\n"
            "print('LIMO_RUNTIME_BEHAVIOR_RESULT='+json.dumps(payload,sort_keys=True))\n"
            "raise SystemExit(0 if result.wasSuccessful() and result.testsRun=="
            + str(anchor['expected_test_count'])
            + " and not result.skipped else 1)\n")
        argv = [sys.executable, '-I', '-B', '-c', bootstrap]
        environment = dict(os.environ)
        for name in (
                'PYTHONPATH', 'PYTHONHOME', 'ROS_MASTER_URI', 'ROS_IP',
                'ROS_HOSTNAME', 'ROS_PACKAGE_PATH'):
            environment.pop(name, None)
        environment.update({
            'PYTHONNOUSERSITE': '1',
            'LIMO_HOST_SRC': str(host_src),
            'LIMO_HOST_WORKSPACE': str(host_workspace),
            'LIMO_ROS1_RUNTIME_OVERLAY': str(
                Path(package_root).resolve(strict=True)),
        })
        try:
            completed = subprocess.run(
                argv, cwd=str(host_workspace), env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=120, check=False)
            stdout = completed.stdout.decode('utf-8', errors='replace')
            stderr = completed.stderr.decode('utf-8', errors='replace')
            command_report = {
                'argv': argv[:4] + ['<host-owned-bootstrap>'],
                'cwd': str(host_workspace),
                'exit_code': completed.returncode,
                'stdout_length_bytes': len(completed.stdout),
                'stdout_sha256': hashlib.sha256(completed.stdout).hexdigest(),
                'stdout_head': stdout[:2048],
                'stdout_tail': stdout[-2048:],
                'stderr_length_bytes': len(completed.stderr),
                'stderr_sha256': hashlib.sha256(completed.stderr).hexdigest(),
                'stderr_head': stderr[:2048],
                'stderr_tail': stderr[-2048:],
                'timed_out': False,
            }
            marker = 'LIMO_RUNTIME_BEHAVIOR_RESULT='
            lines = [line for line in stdout.splitlines()
                     if line.startswith(marker)]
            behavior = None
            if len(lines) == 1:
                try:
                    behavior = _strict_json_loads(lines[0][len(marker):])
                except (ValueError, json.JSONDecodeError):
                    behavior = None
            expected_result = {
                'tests_run': anchor['expected_test_count'],
                'failures': 0,
                'errors': 0,
                'skipped': 0,
                'expected_failures': 0,
                'unexpected_successes': 0,
                'successful': True,
            }
            if (completed.returncode != 0
                    or not _exact_json_value(behavior, expected_result)):
                failures.append('ros1_runtime_behavior_tests_failed')
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or b''
            stderr = error.stderr or b''
            command_report = {
                'argv': argv[:4] + ['<host-owned-bootstrap>'],
                'cwd': str(host_workspace),
                'exit_code': None,
                'stdout_length_bytes': len(stdout),
                'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
                'stderr_length_bytes': len(stderr),
                'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
                'timed_out': True,
            }
            failures.append('ros1_runtime_behavior_test_timeout')
        except (OSError, subprocess.SubprocessError):
            failures.append('ros1_runtime_behavior_test_runner_failed')
    return {
        'gate_id': 'ROS1_RUNTIME_PURE_FAKE_BEHAVIOR_ADMISSION',
        'validated_pass': not failures,
        'test_identity': identity,
        'expected_test_count': anchor['expected_test_count'],
        'command': command_report,
        'ros_graph_started': False,
        'camera_opened': False,
        'hardware_connected': False,
        'authorizes_field_delivery': False,
        'delivery_ready': False,
        'failures': sorted(set(failures)),
    }


def _audit_ros1_runtime_implementation_admission(
        package_root: Path, contract: Mapping) -> Mapping:
    """Host-owned, non-executing ROS1 runtime source admission.

    Capability declarations are deliberately absent from this trust root.
    The gate reopens exact regular files, parses Python/XML/JSON, and checks
    the read-only runtime topology.  Passing proves source implementation
    only; it never proves installation, a ROS runtime, field data, or delivery.
    """
    failures = []
    identities = []
    records = {}
    for role in sorted(ROS1_RUNTIME_IMPLEMENTATION_ANCHORS):
        try:
            record = _runtime_exact_source(package_root, role)
        except (OSError, UnicodeError, SyntaxError, ValueError) as error:
            failures.append(
                'ros1_runtime_implementation_source_invalid:{}:{}'.format(
                    role, type(error).__name__))
            continue
        records[role] = record
        identities.append(record['identity'])
        if record['identity'].get('identity_valid') is not True:
            failures.append(
                'ros1_runtime_implementation_source_identity_mismatch:'
                + role)

    expected_entry_imports = {
        'entry:dual_model_detector': (
            'limo_cleanup_ros1_perception.dual_model_detector', 'main'),
        'entry:perception_frame_adapter': (
            'limo_cleanup_ros1_perception.ros1_adapter', 'main'),
        'entry:perception_frame_collector': (
            'limo_cleanup_ros1_perception.perception_frame_collector', 'main'),
        'entry:perception_readiness': (
            'limo_cleanup_ros1_perception.perception_readiness', 'main'),
        'entry:rosbag1_rgbd_indexer': (
            'limo_cleanup_ros1_perception.rosbag1_rgbd_indexer', 'main'),
        'entry:typed_raw_binding': (
            'limo_cleanup_ros1_perception.typed_raw_binding', 'main'),
    }
    for role, expected_import in expected_entry_imports.items():
        record = records.get(role)
        if record is None:
            continue
        imports = [
            (node.module, alias.name)
            for node in record['tree'].body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names]
        main_calls = [
            node for node in ast.walk(record['tree'])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'main']
        if imports != [expected_import] or len(main_calls) != 1:
            failures.append(
                'ros1_runtime_entrypoint_ast_invalid:' + role.split(':', 1)[1])

    required_surfaces = {
        'runtime:dual_model_detector': (
            {'_validate_config', 'main'},
            {'InferenceConfig', 'DualModelInference'}),
        'runtime:ros1_adapter': (
            {'validate_observation_contract', 'build_observation_id',
             'stream_metadata', 'main'},
            {'PerceptionPipeline', 'Ros1PerceptionAdapter'}),
        'runtime:formal_producer': (
            {'load_formal_manifest', 'inspect_formal_scene', 'inspect_bag',
             'main'}, {'InspectionError', 'Rosbag1Reader'}),
        'runtime:formal_consumer': (
            {'_validate_formal_index',
             '_validate_formal_artifacts_and_redecode',
             'create_binding', 'main'}, set()),
        'runtime:model_contract': (
            {'load_model_bindings', 'resolve_model_artifacts',
             'model_set_sha256'}, {'ModelBinding'}),
        'runtime:perception_core': (
            {'classify_bottles_with_depth', 'select_target_bottle',
             'select_target_bin'}, {'Detection2D', 'BottleClassification'}),
        'runtime:target_contract': (
            {'project_detection', 'require_single_class_model',
             'bundle_signature'}, {'ProjectionConfig', 'ProjectionResult'}),
        'runtime:rgbd_contract': (
            {'validate_rgbd_contract'},
            {'StreamMetadata', 'RgbdContractResult'}),
        'runtime:image_conversion': (
            {'image_message_to_numpy'}, set()),
        'runtime:evidence_binding': (
            {'sha256_file', 'artifact_identity', 'canonical_file_manifest',
             'valid_release_id', 'finite_timestamp'}, set()),
    }
    for role, (required_functions, required_classes) in required_surfaces.items():
        record = records.get(role)
        if record is None:
            continue
        functions, classes = _ast_top_level_names(record['tree'])
        if (not required_functions.issubset(functions)
                or not required_classes.issubset(classes)):
            failures.append(
                'ros1_runtime_component_ast_surface_invalid:' + role)

    detector = records.get('runtime:dual_model_detector')
    if detector is not None:
        detector_source = detector['source']
        for token in (
                'load_model_bindings', 'resolve_model_artifacts',
                'require_single_class_model', 'from ultralytics import YOLO',
                "outputs['plastic_bottle']", "outputs['trash_bin']"):
            if token not in detector_source:
                failures.append(
                    'ros1_runtime_dual_detector_semantic_missing:' + token)

    adapter = records.get('runtime:ros1_adapter')
    allowed_topics = (
        '/cleanup/perception/frames',
        '/cleanup/detection/raw',
        '/cleanup/perception_status',
    )
    if adapter is not None:
        tree = adapter['tree']
        source = adapter['source']
        if _ast_literal_assignment(tree, 'PERCEPTION_OUTPUT_TOPICS') != allowed_topics:
            failures.append('ros1_runtime_adapter_output_topics_invalid')
        publisher_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'Publisher']
        publisher_indexes = []
        for call in publisher_calls:
            if not call.args:
                continue
            first = call.args[0]
            if (isinstance(first, ast.Subscript)
                    and isinstance(first.value, ast.Name)
                    and first.value.id == 'PERCEPTION_OUTPUT_TOPICS'):
                try:
                    publisher_indexes.append(ast.literal_eval(first.slice))
                except (TypeError, ValueError):
                    pass
        if sorted(publisher_indexes) != [0, 1, 2] or len(publisher_calls) != 3:
            failures.append('ros1_runtime_adapter_publishers_invalid')
        subscriber_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'Subscriber']
        if len(subscriber_calls) != 4:
            failures.append('ros1_runtime_adapter_rgbd_subscribers_invalid')
        for token in (
                'allow_headerless=False', 'validate_rgbd_contract(',
                'project_detection(', 'validate_observation_contract(',
                "'tf_chain_available_not_applied_camera_frame_output'",
                "'transform_applied': False",
                "'tf_unavailable_camera_frame_retained'"):
            if token not in source:
                failures.append(
                    'ros1_runtime_adapter_frame_depth_tf_semantic_missing:'
                    + token)

    forbidden_source_tokens = (
        '/cmd_vel', '/move_base/goal', '/move_base/cancel',
        '/arm_controller/command', '/gripper_controller/command',
        'SimpleActionClient', 'send_goal(', 'Twist(',
        'rospy.Service(', 'ServiceProxy(')
    for role, record in records.items():
        if role.startswith('contract:'):
            continue
        source = record['source']
        for token in forbidden_source_tokens:
            if token in source:
                failures.append(
                    'ros1_runtime_control_surface_forbidden:{}:{}'.format(
                        role, token.replace('/', '_')))
        if role != 'runtime:ros1_adapter' and (
                'Publisher(' in source or '.publish(' in source):
            failures.append('ros1_runtime_unexpected_publisher:' + role)

    consumer = records.get('runtime:formal_consumer')
    if consumer is not None:
        for token in (
                '_validate_formal_artifacts_and_redecode(',
                '_validate_formal_accounting_and_isolation(',
                '_validate_formal_alignment(',
                "'formal_acceptance'", "'delivery_ready': False"):
            if token not in consumer['source']:
                failures.append(
                    'ros1_runtime_formal_consumer_semantic_missing:' + token)

    model_contract = records.get('runtime:model_contract')
    if model_contract is not None:
        allowed_import_roots = {
            'hashlib', 'json', 'stat', 'dataclasses', 'pathlib', 'typing'}
        actual_roots = set()
        for node in ast.walk(model_contract['tree']):
            if isinstance(node, ast.Import):
                actual_roots.update(alias.name.split('.')[0]
                                    for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                actual_roots.add(node.module.split('.')[0])
        if actual_roots != allowed_import_roots:
            failures.append('ros1_runtime_model_contract_imports_invalid')

    output_record = records.get('contract:read_only_output')
    if output_record is not None:
        try:
            output = _strict_json_loads(output_record['source'])
        except (ValueError, json.JSONDecodeError):
            output = None
        allowed = output.get('allowed_publish_topics') if isinstance(
            output, Mapping) else None
        actual_topics = [item.get('topic') for item in allowed] if (
            isinstance(allowed, list)
            and all(isinstance(item, Mapping) for item in allowed)) else []
        if (not isinstance(output, Mapping)
                or output.get('read_only') is not True
                or output.get('authorizes_motion') is not False
                or output.get('authorizes_field_delivery') is not False
                or output.get('delivery_ready') is not False
                or output.get('control_publishers_allowed') is not False
                or output.get('services_allowed') is not False
                or output.get('actions_allowed') is not False
                or tuple(actual_topics) != allowed_topics
                or any(item.get('may_trigger_motion') is not False
                       for item in allowed or [])):
            failures.append('ros1_runtime_read_only_output_contract_invalid')

    launch_record = records.get('launch:perception_v2_readonly')
    if launch_record is not None:
        launch_text = launch_record['source']
        try:
            if '<!DOCTYPE' in launch_text or '<!ENTITY' in launch_text:
                raise ET.ParseError('document type or entity is forbidden')
            launch_root = ET.fromstring(launch_text)
        except ET.ParseError:
            launch_root = None
        launch_valid = launch_root is not None
        expected_args = [
            ('rgb_topic', '/camera/color/image_raw'),
            ('depth_topic', '/camera/depth/image_raw'),
            ('rgb_camera_info_topic', '/camera/color/camera_info'),
            ('depth_camera_info_topic', '/camera/depth/camera_info'),
            ('model_manifest',
             '$(find limo_cleanup_ros1_perception)/config/model_bindings.json'),
        ]
        expected_node_attributes = {
            'pkg': 'limo_cleanup_ros1_perception',
            'type': 'dual_model_detector.py',
            'name': 'cleanup_dual_model_detector',
            'output': 'screen',
            'required': 'true',
        }
        expected_params = [
            ('rgb_topic', '$(arg rgb_topic)'),
            ('depth_topic', '$(arg depth_topic)'),
            ('rgb_camera_info_topic', '$(arg rgb_camera_info_topic)'),
            ('depth_camera_info_topic', '$(arg depth_camera_info_topic)'),
            ('model_manifest', '$(arg model_manifest)'),
            ('confidence', '0.35'),
            ('iou', '0.45'),
            ('image_size', '640'),
            ('max_sync_delta_sec', '0.15'),
            ('depth_scale', '0.001'),
            ('opening_height_ratio', '0.62'),
            ('in_bin_overlap', '0.30'),
        ]
        if launch_root is not None:
            children = list(launch_root)
            args = [item for item in children if item.tag == 'arg']
            nodes = [item for item in children if item.tag == 'node']
            launch_valid = (
                launch_root.tag == 'launch'
                and dict(launch_root.attrib) == {}
                and [item.tag for item in children]
                == ['arg'] * len(expected_args) + ['node']
                and len(args) == len(expected_args)
                and all(
                    dict(item.attrib) == {'name': name, 'default': default}
                    and list(item) == []
                    for item, (name, default) in zip(args, expected_args))
                and len(nodes) == 1)
            if len(nodes) == 1:
                node = nodes[0]
                params = list(node)
                launch_valid = launch_valid and (
                    dict(node.attrib) == expected_node_attributes
                    and [item.tag for item in params]
                    == ['param'] * len(expected_params)
                    and len(params) == len(expected_params)
                    and all(
                        dict(item.attrib) == {'name': name, 'value': value}
                        and list(item) == []
                        for item, (name, value) in zip(
                            params, expected_params)))
        if not launch_valid:
            failures.append('ros1_runtime_read_only_launch_invalid')
        for token in (
                'astra_camera', 'dabai_u3.launch', 'move_base', 'cmd_vel',
                'controller_manager', 'robot_state_publisher',
                'ros_control', 'arm_', 'gripper_', '$(env ', '$(optenv ',
                '$(eval '):
            if token in launch_text:
                failures.append(
                    'ros1_runtime_launch_control_include_forbidden:' + token)

    formal_launch_record = records.get('launch:perception_v2_formal_capture')
    if formal_launch_record is not None:
        launch_text = formal_launch_record['source']
        try:
            if '<!DOCTYPE' in launch_text or '<!ENTITY' in launch_text:
                raise ET.ParseError('document type or entity is forbidden')
            launch_root = ET.fromstring(launch_text)
        except ET.ParseError:
            launch_root = None
        expected_args = [
            {'name': 'rgb_topic', 'default': '/camera/color/image_raw'},
            {'name': 'depth_topic', 'default': '/camera/depth/image_raw'},
            {
                'name': 'rgb_camera_info_topic',
                'default': '/camera/color/camera_info',
            },
            {
                'name': 'depth_camera_info_topic',
                'default': '/camera/depth/camera_info',
            },
            {
                'name': 'model_manifest',
                'default': (
                    '$(find limo_cleanup_ros1_perception)/config/'
                    'model_bindings.json'),
            },
            {'name': 'task_id'},
            {'name': 'capture_id'},
        ]
        expected_node_attributes = {
            'pkg': 'limo_cleanup_ros1_perception',
            'type': 'dual_model_detector.py',
            'name': 'cleanup_dual_model_detector',
            'output': 'screen',
            'required': 'true',
        }
        expected_params = [
            ('rgb_topic', '$(arg rgb_topic)'),
            ('depth_topic', '$(arg depth_topic)'),
            ('rgb_camera_info_topic', '$(arg rgb_camera_info_topic)'),
            ('depth_camera_info_topic', '$(arg depth_camera_info_topic)'),
            ('model_manifest', '$(arg model_manifest)'),
            ('formal_capture_mode', 'true'),
            ('task_id', '$(arg task_id)'),
            ('capture_id', '$(arg capture_id)'),
            ('confidence', '0.35'),
            ('iou', '0.45'),
            ('image_size', '640'),
            ('max_sync_delta_sec', '0.15'),
            ('depth_scale', '0.001'),
            ('opening_height_ratio', '0.62'),
            ('in_bin_overlap', '0.30'),
        ]
        launch_valid = launch_root is not None
        if launch_root is not None:
            children = list(launch_root)
            args = [item for item in children if item.tag == 'arg']
            nodes = [item for item in children if item.tag == 'node']
            launch_valid = (
                launch_root.tag == 'launch'
                and dict(launch_root.attrib) == {}
                and [item.tag for item in children]
                == ['arg'] * len(expected_args) + ['node']
                and len(args) == len(expected_args)
                and all(
                    dict(item.attrib) == expected
                    and list(item) == []
                    for item, expected in zip(args, expected_args))
                and len(nodes) == 1)
            if len(nodes) == 1:
                node = nodes[0]
                params = list(node)
                launch_valid = launch_valid and (
                    dict(node.attrib) == expected_node_attributes
                    and [item.tag for item in params]
                    == ['param'] * len(expected_params)
                    and len(params) == len(expected_params)
                    and all(
                        dict(item.attrib) == {'name': name, 'value': value}
                        and list(item) == []
                        for item, (name, value) in zip(
                            params, expected_params)))
        if not launch_valid:
            failures.append('ros1_runtime_formal_capture_launch_invalid')
        for token in (
                'astra_camera', 'dabai_u3.launch', 'move_base', 'cmd_vel',
                'controller_manager', 'robot_state_publisher',
                'ros_control', 'arm_', 'gripper_', '$(env ', '$(optenv ',
                '$(eval ', '<remap', '<include', '<machine', '<group',
                '<rosparam'):
            if token in launch_text:
                failures.append(
                    'ros1_runtime_formal_capture_control_forbidden:' + token)

    setup_record = records.get('build:setup')
    runtime_lock = contract.get('python_runtime_dependency_lock') if isinstance(
        contract, Mapping) else None
    requirements = runtime_lock.get('requirements') if isinstance(
        runtime_lock, Mapping) else None
    expected_pins = [item.get('requirement') for item in requirements] if (
        isinstance(requirements, list)
        and all(isinstance(item, Mapping) for item in requirements)) else []
    if setup_record is not None:
        setup_tree = setup_record['tree']
        install_requires = None
        for node in ast.walk(setup_tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Subscript)):
                target = node.targets[0]
                try:
                    key = ast.literal_eval(target.slice)
                    value = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    continue
                if key == 'install_requires':
                    install_requires = value
        if install_requires != expected_pins:
            failures.append('ros1_runtime_dependency_source_pins_invalid')

    package_record = records.get('build:package_xml')
    if package_record is not None:
        try:
            package_tree = ET.fromstring(package_record['source'])
        except ET.ParseError:
            package_tree = None
        dependency_names = set()
        if package_tree is not None:
            dependency_names = {
                (node.text or '').strip()
                for tag in ('depend', 'build_depend', 'exec_depend')
                for node in package_tree.findall(tag)}
        for forbidden_name in ('numpy', 'torch', 'ultralytics'):
            if forbidden_name in dependency_names:
                failures.append(
                    'ros1_runtime_dependency_rosdep_claim_forbidden:'
                    + forbidden_name)

    cmake_record = records.get('build:cmake')
    if cmake_record is not None:
        cmake = cmake_record['source']
        for relative in (
                contract.get('required_entrypoints', {}).values()
                if isinstance(contract, Mapping) else ()):
            if relative not in cmake:
                failures.append(
                    'ros1_runtime_entrypoint_install_missing:'
                    + Path(relative).name)
        for name in (contract.get('required_launch_files', [])
                     if isinstance(contract, Mapping) else []):
            if 'launch/' + name not in cmake:
                failures.append('ros1_runtime_launch_install_missing:' + name)

    if failures:
        behavior_admission = {
            'gate_id': 'ROS1_RUNTIME_PURE_FAKE_BEHAVIOR_ADMISSION',
            'validated_pass': False,
            'not_run_due_to_source_gate_failure': True,
            'expected_test_count': (
                ROS1_RUNTIME_BEHAVIOR_TEST_ANCHOR['expected_test_count']),
            'ros_graph_started': False,
            'camera_opened': False,
            'hardware_connected': False,
            'authorizes_field_delivery': False,
            'delivery_ready': False,
            'failures': ['ros1_runtime_behavior_not_run_source_invalid'],
        }
    else:
        behavior_admission = _run_ros1_runtime_behavior_admission(package_root)
        if behavior_admission.get('validated_pass') is not True:
            failures.extend(behavior_admission.get('failures', []))

    unique_failures = sorted(set(failures))
    if unique_failures:
        unique_failures = sorted(set(unique_failures + [
            ROS1_RUNTIME_IMPLEMENTATION_VALIDATION_BLOCKER]))
    return {
        'gate_id': ROS1_RUNTIME_IMPLEMENTATION_ADMISSION_GATE_ID,
        'scope': 'source_implementation_only',
        'validated_pass': not unique_failures,
        'source_identities': identities,
        'required_component_count': len(
            ROS1_RUNTIME_IMPLEMENTATION_ANCHORS),
        'validated_component_count': len(identities),
        'behavior_admission': behavior_admission,
        'capability_declarations_consulted': False,
        'capability_declarations_can_override': False,
        'closes_source_implementation_blocker_only': True,
        'ros1_noetic_install_validated': False,
        'field_evidence_admitted': False,
        'authorizes_field_delivery': False,
        'delivery_ready': False,
        'failures': unique_failures,
    }


def audit_ros1_noetic_field_source_contract(
        workspace: Path = None, contract_record: Mapping = None) -> Mapping:
    """Audit whether the workspace contains a complete ROS1 field runtime."""
    root = _perception_workspace_root(workspace)
    record = contract_record or load_ros1_noetic_field_install_contract(root)
    failures = list(record.get('failures', []))
    contract = record.get('payload')
    schema_failures = _ros1_contract_schema_failures(contract)
    failures.extend(schema_failures)
    if root is None or not isinstance(contract, Mapping) or schema_failures:
        return {
            'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
            'scope': 'field_delivery',
            'pass': False,
            'complete_runtime': False,
            'interface_mode': None,
            'indexer_only_detected': False,
            'source_set_sha256': None,
            'source_entries': [],
            'workspace_root': None if root is None else str(root),
            'package_root': None,
            'contract_path': record.get('path'),
            'contract_sha256': record.get('sha256'),
            'architecture_blockers': [ROS1_RUNTIME_ARCHITECTURE_BLOCKER],
            'failures': sorted(set(failures)),
        }
    package = contract['package']
    package_root = root / package['source_root']
    if (not package_root.is_dir() or _path_is_linklike(package_root)):
        failures.append('ros1_field_package_missing_or_linked')
    package_xml = package_root / 'package.xml'
    dependencies = set()
    dependency_tags_valid = False
    try:
        xml = ET.parse(str(package_xml)).getroot()
        expected_dependency_tags = package.get('dependency_tags', {})
        actual_dependency_tags = {}
        dependency_tag_names = {
            'buildtool_depend', 'build_depend', 'build_export_depend',
            'exec_depend', 'depend', 'test_depend', 'doc_depend',
            'conflict', 'replace'}
        for tag in dependency_tag_names:
            values = [(node.text or '').strip() for node in xml.findall(tag)]
            if values:
                actual_dependency_tags[tag] = values
        dependency_tags_valid = (
            isinstance(expected_dependency_tags, Mapping)
            and set(actual_dependency_tags) == set(expected_dependency_tags)
            and all(
                len(values) == len(set(values))
                and sorted(values) == sorted(expected_dependency_tags[tag])
                for tag, values in actual_dependency_tags.items()))
        dependencies = {
            item for tag, values in actual_dependency_tags.items()
            if tag != 'buildtool_depend' for item in values}
        export = xml.find('export')
        build_type = None if export is None else export.findtext('build_type')
        if (xml.findtext('name') != package['name']
                or build_type != 'catkin'
                or not dependency_tags_valid):
            failures.append('ros1_field_package_identity_invalid')
        if not dependency_tags_valid:
            failures.append('ros1_field_dependency_tag_set_invalid')
    except (OSError, ET.ParseError):
        failures.append('ros1_field_package_xml_invalid')
    for name in package['required_dependencies']:
        if name not in dependencies:
            failures.append('ros1_field_dependency_missing:' + name)
    for name in package['forbidden_dependencies']:
        if name in dependencies:
            failures.append('ros1_field_forbidden_dependency:' + name)

    try:
        cmake = (package_root / 'CMakeLists.txt').read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        cmake = ''
        failures.append('ros1_field_cmake_invalid')
    for token in ('find_package(catkin', 'catkin_python_setup()',
                  'catkin_install_python('):
        if token not in cmake:
            failures.append('ros1_field_cmake_missing:' + token)
    for relative in contract['required_entrypoints'].values():
        if relative not in cmake:
            failures.append(
                'ros1_field_entrypoint_not_installed:' + Path(relative).name)
    expected_config_refs = {
        'config/' + name for name in contract['required_config_files']}
    expected_fixture_refs = {
        'fixtures/' + name for name in contract['required_fixture_files']}
    actual_config_refs = set(re.findall(
        r'(?<![A-Za-z0-9_.-])config/([A-Za-z0-9_.-]+)', cmake))
    actual_config_refs = {'config/' + name for name in actual_config_refs}
    actual_fixture_refs = set(re.findall(
        r'(?<![A-Za-z0-9_.-])fixtures/([A-Za-z0-9_.-]+)', cmake))
    actual_fixture_refs = {
        'fixtures/' + name for name in actual_fixture_refs}
    expected_message_refs = set(
        contract['interface_modes']['native_ros1_messages'][
            'required_files'])
    actual_message_refs = set(re.findall(
        r'(?<![A-Za-z0-9_.-])msg/([A-Za-z0-9_.-]+\.msg)', cmake))
    actual_message_refs = {'msg/' + name for name in actual_message_refs}
    expected_entry_refs = set(contract['required_entrypoints'].values())
    actual_entry_refs = set(re.findall(
        r'(?<![A-Za-z0-9_.-])scripts/([A-Za-z0-9_.-]+\.py)', cmake))
    actual_entry_refs = {'scripts/' + name for name in actual_entry_refs}
    expected_launch_refs = {
        'launch/' + name for name in contract['required_launch_files']}
    actual_launch_refs = set(re.findall(
        r'(?<![A-Za-z0-9_.-])launch/([A-Za-z0-9_.-]+)', cmake))
    actual_launch_refs = {'launch/' + name for name in actual_launch_refs}
    expected_test_refs = {
        'test/' + name for name in contract['required_catkin_test_files']}
    actual_test_refs = set(re.findall(
        r'catkin_add_nosetests\(test/([A-Za-z0-9_.-]+\.py)\)', cmake))
    actual_test_refs = {'test/' + name for name in actual_test_refs}
    if (actual_config_refs != expected_config_refs
            or 'DIRECTORY config/' in cmake):
        failures.append('ros1_field_config_install_set_invalid')
    if (actual_fixture_refs != expected_fixture_refs
            or 'DIRECTORY fixtures/' in cmake):
        failures.append('ros1_field_fixture_install_set_invalid')
    if (actual_message_refs != expected_message_refs
            or 'DIRECTORY msg/' in cmake):
        failures.append('ros1_field_message_install_set_invalid')
    if actual_entry_refs != expected_entry_refs:
        failures.append('ros1_field_entrypoint_install_set_invalid')
    if actual_launch_refs != expected_launch_refs:
        failures.append('ros1_field_launch_install_set_invalid')
    if actual_test_refs != expected_test_refs:
        failures.append('ros1_field_catkin_test_set_invalid')
    for name in contract['required_launch_files']:
        if ('launch/' + name not in cmake
                or '${CATKIN_PACKAGE_SHARE_DESTINATION}/launch' not in cmake):
            failures.append('ros1_field_launch_not_installed:' + name)
    for name in contract['required_catkin_test_files']:
        token = 'catkin_add_nosetests(test/{})'.format(name)
        if token not in cmake:
            failures.append('ros1_field_catkin_test_not_registered:' + name)

    modes = []
    for mode_name, mode in contract['interface_modes'].items():
        mode_paths = [package_root / item for item in mode['required_files']]
        if all(path.is_file() and not _path_is_linklike(path)
               for path in mode_paths):
            modes.append(mode_name)
    interface_mode = modes[0] if len(modes) == 1 else None
    if interface_mode is None:
        failures.append('ros1_field_message_or_conversion_layer_missing')
    elif interface_mode == 'native_ros1_messages':
        for token in ('add_message_files(', 'generate_messages('):
            if token not in cmake:
                failures.append('ros1_field_native_message_build_missing')

    selected_mode = interface_mode or 'native_ros1_messages'
    source_entries = []
    expected_paths = _ros1_required_source_paths(contract, selected_mode)
    for relative in expected_paths:
        path = package_root / relative
        if not path.is_file():
            failures.append('ros1_field_source_missing:' + relative)
            continue
        if _path_is_linklike(path):
            failures.append('ros1_field_source_link_forbidden:' + relative)
            continue
        source_entries.append({
            'path': relative,
            'size_bytes': path.stat().st_size,
            'sha256': sha256_file(path),
        })

    python_root = package_root / 'src' / package['name']
    existing_modules = {
        path.name for path in python_root.glob('*.py') if path.is_file()}
    existing_entries = {
        path.name for path in (package_root / 'scripts').glob('*.py')
        if path.is_file()}
    indexer_only = (
        existing_modules.issubset({'__init__.py', 'rosbag1_rgbd_indexer.py'})
        and existing_entries.issubset({'rosbag1_rgbd_indexer.py'}))
    if indexer_only:
        failures.append('ros1_field_indexer_only_package')
    for name in sorted(
            existing_modules - set(contract['required_python_modules'])):
        failures.append('ros1_field_undeclared_python_module:' + name)
    expected_entry_files = {
        Path(relative).name
        for relative in contract['required_entrypoints'].values()}
    expected_launch_files = set(contract['required_launch_files'])
    expected_test_files = set(contract['required_catkin_test_files'])
    expected_message_files = {
        Path(relative).name for relative in expected_message_refs}
    actual_launch_files = {
        item.name for item in (package_root / 'launch').glob('*')
        if item.is_file()}
    actual_test_files = {
        item.name for item in (package_root / 'test').glob('*.py')
        if item.is_file()}
    actual_message_files = {
        item.name for item in (package_root / 'msg').glob('*.msg')
        if item.is_file()}
    for label, actual, expected in (
            ('entrypoint', existing_entries, expected_entry_files),
            ('launch', actual_launch_files, expected_launch_files),
            ('catkin_test', actual_test_files, expected_test_files),
            ('message', actual_message_files, expected_message_files)):
        if actual != expected:
            failures.append('ros1_field_{}_source_set_invalid'.format(label))

    forbidden_tokens = ('import rclpy', 'from rclpy', 'ament_cmake',
                        'ament_python', 'rosidl_')
    scan_paths = [package_xml, package_root / 'CMakeLists.txt']
    scan_paths.extend(
        package_root / relative for relative in expected_paths
        if ((relative.endswith('.py')
             and not relative.startswith('test/'))
            or relative.startswith('launch/')))
    for path in scan_paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            failures.append('ros1_field_source_unreadable:' + path.name)
            continue
        for token in forbidden_tokens:
            if token in text:
                failures.append(
                    'ros1_field_ros2_runtime_token:' + token.replace(' ', '_'))

    source_core_binding = _validate_ros1_source_core_binding(root)
    if source_core_binding.get('validated_pass') is not True:
        failures.append('ros1_field_source_core_binding_not_validated')
        failures.extend(source_core_binding.get('failures', []))

    model_path = package_root / contract['model_manifest']['path']
    try:
        model_manifest = _strict_json_loads(
            model_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        model_manifest = None
        failures.append('ros1_field_model_manifest_missing_or_invalid')
    required_classes = set(contract['model_manifest']['required_classes'])
    models = model_manifest.get('models') if isinstance(
        model_manifest, Mapping) else None
    expected_model_manifest_keys = {
        'schema_version', 'manifest_id', 'runtime_family', 'ros_distro',
        'read_only', 'authorizes_motion', 'delivery_ready', 'runtime',
        'load_policy', 'models'}
    expected_load_policy = {
        'regular_file_required': True,
        'sha256_required': True,
        'single_exact_class_required': True,
        'missing_model_is_fatal': True,
        'hash_mismatch_is_fatal': True,
        'silent_fallback_or_relabel_forbidden': True,
        'automatic_download_forbidden': True,
    }
    expected_model_metadata = {
        'plastic_bottle': {
            'filename': 'nongfu_yolov8n_best.pt',
            'deployment_path': (
                '/home/agilex/limo_cleanup_ws/models/'
                'nongfu_yolov8n_best.pt'),
            'size_bytes': 6244778,
            'sha256': EXPECTED_MODEL_SHA256['plastic_bottle'],
        },
        'trash_bin': {
            'filename': 'trash_bin_yolov8n_best.pt',
            'deployment_path': (
                '/home/agilex/limo_cleanup_ws/models/'
                'trash_bin_yolov8n_best.pt'),
            'size_bytes': 6231338,
            'sha256': EXPECTED_MODEL_SHA256['trash_bin'],
        },
    }
    if (
            not isinstance(model_manifest, Mapping)
            or set(model_manifest) != expected_model_manifest_keys
            or model_manifest.get('schema_version') != 1
            or model_manifest.get('manifest_id')
            != 'limo-ros1-dual-model-bindings-v1'
            or model_manifest.get('runtime_family') != 'ROS1'
            or model_manifest.get('ros_distro') != 'noetic'
            or model_manifest.get('read_only') is not True
            or model_manifest.get('authorizes_motion') is not False
            or model_manifest.get('delivery_ready') is not False
            or model_manifest.get('runtime') != 'ultralytics-8.3.21'
            or model_manifest.get('load_policy') != expected_load_policy
            or not isinstance(models, Mapping)
            or set(models) != required_classes):
        failures.append('ros1_field_model_binding_incomplete')
    if isinstance(models, Mapping):
        expected_entry_keys = {
            'class_name', 'filename', 'deployment_path', 'size_bytes',
            'sha256', 'backend'}
        for label in required_classes:
            item = models.get(label)
            expected = expected_model_metadata.get(label, {})
            if (
                    not isinstance(item, Mapping)
                    or set(item) != expected_entry_keys
                    or item.get('class_name') != label
                    or item.get('filename') != expected.get('filename')
                    or item.get('deployment_path')
                    != expected.get('deployment_path')
                    or item.get('backend') != 'ultralytics-yolo-pt'):
                failures.append('ros1_field_model_binding_incomplete')
                continue
            if item.get('sha256') != expected.get('sha256'):
                failures.append('ros1_field_model_hash_mismatch:' + label)
            if item.get('size_bytes') != expected.get('size_bytes'):
                failures.append('ros1_field_model_size_mismatch:' + label)

    expected_loader_models = {
        label: {
            'class_name': label,
            'filename': values['filename'],
            'deployment_path': values['deployment_path'],
            'size_bytes': values['size_bytes'],
            'sha256': values['sha256'],
            'backend': 'ultralytics-yolo-pt',
        }
        for label, values in expected_model_metadata.items()
    }
    model_loader_validation = _validate_ros1_model_loader(
        package_root, model_path, expected_loader_models)
    if model_loader_validation.get('validated_pass') is not True:
        failures.append('ros1_field_model_loader_not_validated')
        failures.extend(model_loader_validation.get('failures', []))

    formal_rosbag1_admission = (
        _audit_ros1_formal_rosbag1_admission_source(package_root))
    if formal_rosbag1_admission.get('validated_pass') is not True:
        failures.extend(formal_rosbag1_admission.get('failures', []))

    runtime_implementation_admission = (
        _audit_ros1_runtime_implementation_admission(package_root, contract))
    if runtime_implementation_admission.get('validated_pass') is not True:
        failures.extend(
            runtime_implementation_admission.get('failures', []))

    capability_path = package_root / 'config/capability_matrix.json'
    capability_failures = []
    try:
        capability = _strict_json_loads(
            capability_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        capability = None
        capability_failures.append(
            'ros1_field_capability_matrix_missing_or_invalid')
    capability_values = capability.get('capabilities') if isinstance(
        capability, Mapping) else None
    expected_capability_keys = {
        'schema_version', 'matrix_id', 'scope', 'read_only',
        'authorizes_motion', 'delivery_ready', 'implementation_validated',
        'capabilities', 'acceptance_policy'}
    expected_acceptance_policy = {
        'all_capabilities_require_installed_python_implementation': True,
        'source_declaration_does_not_prove_runtime': True,
        'field_delivery_requires_independent_build_runtime_and_four_scene_evidence': True,
    }
    capability_identity_valid = (
        isinstance(capability, Mapping)
        and set(capability) == expected_capability_keys
        and capability.get('schema_version') == 1
        and capability.get('matrix_id')
        == 'limo-v2-ros1-noetic-required-capabilities-v1'
        and capability.get('scope')
        == 'install_contract_not_runtime_or_field_acceptance'
        and capability.get('read_only') is True
        and capability.get('authorizes_motion') is False
        and capability.get('delivery_ready') is False
        and isinstance(capability.get('implementation_validated'), bool)
        and capability.get('acceptance_policy')
        == expected_acceptance_policy)
    if not capability_identity_valid:
        capability_failures.append(
            'ros1_field_capability_matrix_identity_invalid')
    capability_schema_valid = (
        isinstance(capability_values, Mapping)
        and set(capability_values) == set(contract['required_capabilities'])
        and all(isinstance(value, bool)
                for value in capability_values.values()))
    if not capability_schema_valid:
        capability_failures.append(
            'ros1_field_capability_matrix_schema_invalid')
    implementation_validated_declaration = (
        capability.get('implementation_validated')
        if capability_identity_valid else None)
    capability_diagnostic = {
        'path': str(capability_path),
        'declarations': (
            dict(sorted(capability_values.items()))
            if isinstance(capability_values, Mapping) else {}),
        'identity_valid': capability_identity_valid,
        'schema_valid': capability_schema_valid,
        'implementation_validated': implementation_validated_declaration,
        'authoritative_for_complete_runtime': False,
        'consulted_by_runtime_implementation_admission': False,
        'true_declarations_do_not_prove_implementation': True,
        'false_declarations_do_not_replace_source_gate_failures': True,
        'failures': sorted(set(capability_failures)),
    }

    source_entries = sorted(source_entries, key=lambda item: item['path'])
    source_set_sha = _canonical_identity_set_sha256(source_entries)
    unique_failures = sorted(set(failures))
    passed = not unique_failures
    architecture_blockers = []
    if not passed:
        architecture_blockers.append(ROS1_RUNTIME_ARCHITECTURE_BLOCKER)
    if source_core_binding.get('validated_pass') is not True:
        architecture_blockers.append(ROS1_SOURCE_CORE_BINDING_BLOCKER)
    if formal_rosbag1_admission.get('validated_pass') is not True:
        architecture_blockers.append(ROS1_FORMAL_ROSBAG1_ADMISSION_BLOCKER)
    return {
        'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'contract_path': record.get('path'),
        'contract_sha256': record.get('sha256'),
        'pass': passed,
        'complete_runtime': passed,
        'interface_mode': interface_mode,
        'indexer_only_detected': indexer_only,
        'source_file_count': len(source_entries),
        'source_set_sha256': source_set_sha,
        'source_entries': source_entries,
        'source_core_binding': source_core_binding,
        'model_loader_validation': model_loader_validation,
        'formal_rosbag1_admission': formal_rosbag1_admission,
        'runtime_implementation_admission': (
            runtime_implementation_admission),
        'capability_matrix_diagnostic': capability_diagnostic,
        'workspace_root': str(root),
        'package_root': str(package_root.resolve()),
        'architecture_blockers': sorted(set(architecture_blockers)),
        'failures': unique_failures,
    }


def _canonical_json_sha256(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def make_ros1_canonical_source_binding(
        workspace: Path = None, source_audit: Mapping = None,
        test_only: bool = False) -> Mapping:
    """Create an external expected binding for the canonical ROS1 overlay."""
    root = _perception_workspace_root(workspace)
    default_root = _perception_workspace_root()
    if root is None:
        raise ValueError('canonical ROS1 workspace is unavailable')
    if not test_only and (
            default_root is None or root.resolve() != default_root.resolve()):
        raise ValueError(
            'non-test canonical binding must use the project overlay')
    # A production binding is always recomputed from the host's canonical
    # project overlay.  Caller-provided audits are accepted only for explicit
    # test-only fixtures and can never become a production trust root.
    audit = None if not test_only else source_audit
    if (not isinstance(audit, Mapping)
            or audit.get('workspace_root') != str(root)
            or audit.get('contract_sha256') is None):
        audit = audit_ros1_noetic_field_source_contract(root)
    expected_package_root = (
        root / 'ros1_overlay_src' / 'limo_cleanup_ros1_perception').resolve()
    if (not isinstance(audit, Mapping)
            or audit.get('workspace_root') != str(root)
            or audit.get('package_root') != str(expected_package_root)):
        raise ValueError('canonical ROS1 source audit provenance mismatch')
    entries = [dict(item) for item in audit.get('source_entries', [])]
    entries.sort(key=lambda item: item.get('path', ''))
    binding = {
        'schema_version': 1,
        'binding_kind': (
            'test_only_synthetic' if test_only
            else 'canonical_project_overlay'),
        'test_only': bool(test_only),
        'canonical_source_root': (
            'ros1_overlay_src/limo_cleanup_ros1_perception'),
        'contract_sha256': audit.get('contract_sha256'),
        'source_set_sha256': audit.get('source_set_sha256'),
        'file_count': len(entries),
        'entries': entries,
        'source_contract_pass': audit.get('pass') is True,
        'indexer_only_detected': (
            audit.get('indexer_only_detected') is True),
        'architecture_blockers': sorted(set(
            audit.get('architecture_blockers', []))),
    }
    binding['binding_sha256'] = _canonical_json_sha256(binding)
    return binding


def _ros1_canonical_binding_failures(
        binding, contract_record: Mapping,
        allow_test_synthetic_binding: bool) -> List[str]:
    failures = []
    expected_keys = {
        'schema_version', 'binding_kind', 'test_only',
        'canonical_source_root', 'contract_sha256', 'source_set_sha256',
        'file_count', 'entries', 'source_contract_pass',
        'indexer_only_detected', 'architecture_blockers', 'binding_sha256'}
    if not isinstance(binding, Mapping) or set(binding) != expected_keys:
        return [ROS1_CANONICAL_BINDING_INVALID]
    test_only = binding.get('test_only')
    expected_kind = (
        'test_only_synthetic' if test_only is True
        else 'canonical_project_overlay')
    if (not isinstance(test_only, bool)
            or binding.get('schema_version') != 1
            or binding.get('binding_kind') != expected_kind
            or binding.get('canonical_source_root')
            != 'ros1_overlay_src/limo_cleanup_ros1_perception'
            or binding.get('contract_sha256')
            != contract_record.get('sha256')
            or not _lower_sha256(binding.get('source_set_sha256'))
            or not _lower_sha256(binding.get('binding_sha256'))
            or (test_only and not allow_test_synthetic_binding)):
        failures.append(ROS1_CANONICAL_BINDING_INVALID)
    entries = binding.get('entries')
    canonical_entries = []
    if not isinstance(entries, list):
        failures.append(ROS1_CANONICAL_BINDING_INVALID)
        entries = []
    seen_paths = set()
    for item in entries:
        if (not isinstance(item, Mapping)
                or set(item) != {'path', 'size_bytes', 'sha256'}
                or not isinstance(item.get('path'), str)
                or not item.get('path')
                or item.get('path').startswith('/')
                or '\\' in item.get('path', '')
                or '..' in item.get('path', '').split('/')
                or item.get('path') in seen_paths
                or not isinstance(item.get('size_bytes'), int)
                or isinstance(item.get('size_bytes'), bool)
                or item.get('size_bytes') < 0
                or not _lower_sha256(item.get('sha256'))):
            failures.append(ROS1_CANONICAL_BINDING_INVALID)
            continue
        seen_paths.add(item['path'])
        canonical_entries.append(dict(item))
    canonical_entries.sort(key=lambda item: item['path'])
    identity = dict(binding)
    claimed_binding_sha = identity.pop('binding_sha256', None)
    if (entries != canonical_entries
            or binding.get('file_count') != len(canonical_entries)
            or binding.get('source_set_sha256')
            != _canonical_identity_set_sha256(canonical_entries)
            or claimed_binding_sha != _canonical_json_sha256(identity)):
        failures.append(ROS1_CANONICAL_BINDING_INVALID)
    architecture = binding.get('architecture_blockers')
    contract_pass = binding.get('source_contract_pass')
    if (not isinstance(contract_pass, bool)
            or not isinstance(binding.get('indexer_only_detected'), bool)
            or not isinstance(architecture, list)
            or architecture != sorted(set(architecture))
            or any(not isinstance(item, str) or not item
                   for item in architecture)
            or (contract_pass and architecture)
            or (not contract_pass and ROS1_RUNTIME_ARCHITECTURE_BLOCKER
                not in architecture)):
        failures.append(ROS1_CANONICAL_BINDING_INVALID)
    return sorted(set(failures))


def _ros1_audit_matches_canonical_binding(
        audit, binding: Mapping) -> bool:
    """Compare a live source audit with an out-of-band source binding."""
    if not isinstance(audit, Mapping) or not isinstance(binding, Mapping):
        return False
    entries = audit.get('source_entries')
    if not isinstance(entries, list):
        return False
    canonical_entries = [dict(item) for item in entries
                         if isinstance(item, Mapping)]
    canonical_entries.sort(key=lambda item: item.get('path', ''))
    return (
        len(canonical_entries) == len(entries)
        and canonical_entries == binding.get('entries')
        and audit.get('source_file_count') == binding.get('file_count')
        and audit.get('source_set_sha256') == binding.get(
            'source_set_sha256')
        and audit.get('contract_sha256') == binding.get('contract_sha256')
        and (audit.get('pass') is True)
        is binding.get('source_contract_pass')
        and (audit.get('indexer_only_detected') is True)
        is binding.get('indexer_only_detected')
        and sorted(set(audit.get('architecture_blockers', [])))
        == binding.get('architecture_blockers'))


def _isolated_catkin_argv(isolation_root: str) -> Mapping:
    root = str(isolation_root).replace('\\', '/').rstrip('/')
    source = root + '/ros1_overlay_src'
    return {
        'build_argv': [
            'catkin_make', '-C', root, '--source', source,
            '-DCATKIN_ENABLE_TESTING=ON',
            '-DCMAKE_INSTALL_PREFIX=' + root + '/install'],
        'test_argv': [
            'catkin_make', '-C', root, '--source', source, 'run_tests'],
        'test_result_argv': [
            'catkin_test_results', root + '/build/test_results'],
        'install_argv': [
            'catkin_make', '-C', root, '--source', source, 'install'],
    }


def _evidence_file_identity(
        report_path: Path, declaration, label: str,
        failures: List[str]) -> Optional[Mapping]:
    if not isinstance(declaration, Mapping):
        _add_failure(failures, 'ros1_field_evidence_missing:' + label)
        return None
    path = _resolve_path(report_path, declaration.get('path'))
    if path is None or not path.is_file():
        _add_failure(failures, 'ros1_field_evidence_file_missing:' + label)
        return None
    if _path_is_linklike(path):
        _add_failure(failures, 'ros1_field_evidence_link_forbidden:' + label)
    actual = {
        'path': str(path),
        'size_bytes': path.stat().st_size,
        'sha256': sha256_file(path),
    }
    if declaration.get('size_bytes') != actual['size_bytes']:
        _add_failure(failures, 'ros1_field_evidence_size_mismatch:' + label)
    if declaration.get('sha256') != actual['sha256']:
        _add_failure(failures, 'ros1_field_evidence_hash_mismatch:' + label)
    return actual


def _regular_non_link_file_under(path: Path, root: Path) -> Optional[Path]:
    """Resolve one regular file and reject linked ancestors below ``root``."""
    try:
        root = Path(root).resolve(strict=True)
        resolved = Path(path).resolve(strict=True)
        resolved.relative_to(root)
        if _path_is_linklike(root) or _path_is_linklike(resolved):
            return None
        if not stat.S_ISREG(resolved.stat().st_mode):
            return None
        candidate = resolved.parent
        while True:
            if _path_is_linklike(candidate):
                return None
            if candidate == root:
                break
            parent = candidate.parent
            if parent == candidate:
                return None
            candidate = parent
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _metadata_name_version(raw: bytes) -> Optional[Tuple[str, str]]:
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        return None
    names = []
    versions = []
    for line in text.splitlines():
        if line.startswith('Name:'):
            names.append(line.split(':', 1)[1].strip())
        elif line.startswith('Version:'):
            versions.append(line.split(':', 1)[1].strip())
    if len(names) != 1 or len(versions) != 1 or not names[0] or not versions[0]:
        return None
    return names[0], versions[0]


def _validate_distribution_wheel(
        wheel_path: Path, distribution: str, version: str) -> bool:
    """Reopen one offline wheel and verify its embedded distribution identity."""
    try:
        if wheel_path.suffix.lower() != '.whl' or wheel_path.stat().st_size <= 0:
            return False
        with zipfile.ZipFile(str(wheel_path), 'r') as archive:
            names = archive.namelist()
            if (not names or len(names) != len(set(names))
                    or any(
                        not name or name.startswith('/') or '\\' in name
                        or '..' in name.split('/') for name in names)):
                return False
            metadata_names = [
                name for name in names
                if name.endswith('.dist-info/METADATA')]
            if len(metadata_names) != 1:
                return False
            identity = _metadata_name_version(
                archive.read(metadata_names[0]))
            return identity == (distribution, version)
    except (KeyError, OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        return False


def _ros1_expected_catkin_test_ids(
        workspace_root: Path, contract: Mapping,
        failures: List[str]) -> Mapping:
    """Derive the authoritative catkin test IDs from canonical source AST."""
    result = {}
    package_root = (
        Path(workspace_root) / contract['package']['source_root'])
    test_root = package_root / 'test'
    for filename in contract.get('required_catkin_test_files', []):
        path = _regular_non_link_file_under(test_root / filename, test_root)
        module = Path(filename).stem
        ids = []
        if path is None:
            _add_failure(
                failures, 'ros1_field_catkin_expected_test_contract_invalid')
            continue
        try:
            tree = ast.parse(
                path.read_text(encoding='utf-8'), filename=str(path),
                feature_version=(3, 8))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            _add_failure(
                failures, 'ros1_field_catkin_expected_test_contract_invalid')
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith('test_'):
                    ids.append(module + '.' + node.name)
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if (isinstance(
                            child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and child.name.startswith('test_')):
                        ids.append(
                            '{}.{}.{}'.format(module, node.name, child.name))
        if not ids or len(ids) != len(set(ids)):
            _add_failure(
                failures, 'ros1_field_catkin_expected_test_contract_invalid')
            continue
        result[module] = sorted(ids)
    if set(result) != {
            Path(name).stem
            for name in contract.get('required_catkin_test_files', [])}:
        _add_failure(
            failures, 'ros1_field_catkin_expected_test_contract_invalid')
    all_ids = sorted(item for values in result.values() for item in values)
    return {
        'by_module': result,
        'test_ids': all_ids,
        'test_id_set_sha256': _canonical_identity_set_sha256(all_ids),
    }


def _validate_ros1_catkin_test_results(
        isolation_root: Path, workspace_root: Path, contract: Mapping,
        report_declaration, test_result_log_identity,
        report_path: Path, failures: List[str]) -> Mapping:
    """Recompute JUnit outcomes and bind them to the canonical test AST set."""
    expected = _ros1_expected_catkin_test_ids(
        workspace_root, contract, failures)
    expected_ids = expected['test_ids']
    test_result_root = Path(isolation_root) / 'build' / 'test_results'
    declared_artifacts = []
    if (not isinstance(report_declaration, Mapping)
            or set(report_declaration) != {
                'schema_version', 'junit_xml_artifacts'}
            or report_declaration.get('schema_version') != 1
            or not isinstance(
                report_declaration.get('junit_xml_artifacts'), list)):
        _add_failure(failures, 'ros1_field_catkin_test_result_schema_invalid')
    else:
        declared_artifacts = report_declaration['junit_xml_artifacts']
    actual_paths = []
    try:
        resolved_result_root = test_result_root.resolve(strict=True)
        if (_path_is_linklike(resolved_result_root)
                or resolved_result_root.is_file()):
            raise OSError('invalid test result root')
        actual_paths = sorted(
            path.resolve(strict=True)
            for path in resolved_result_root.rglob('*.xml')
            if path.is_file())
    except (OSError, RuntimeError):
        resolved_result_root = None
        _add_failure(failures, 'ros1_field_catkin_test_result_schema_invalid')
    declared_by_path = {}
    artifact_identities = []
    for index, declaration in enumerate(declared_artifacts):
        identity = _evidence_file_identity(
            report_path, declaration,
            'catkin_junit_xml:' + str(index), failures)
        if identity is None:
            _add_failure(
                failures,
                'ros1_field_catkin_test_result_artifact_invalid:' + str(index))
            continue
        resolved = Path(identity['path'])
        if (resolved_result_root is None
                or _regular_non_link_file_under(
                    resolved, resolved_result_root) is None):
            _add_failure(
                failures,
                'ros1_field_catkin_test_result_artifact_invalid:' + str(index))
            continue
        if identity['path'] in declared_by_path:
            _add_failure(failures, 'ros1_field_catkin_test_duplicate_artifact')
        declared_by_path[identity['path']] = identity
        artifact_identities.append(identity)
    actual_rendered = {str(item) for item in actual_paths}
    if (set(declared_by_path) != actual_rendered
            or len(artifact_identities)
            != len(contract.get('required_catkin_test_files', []))):
        _add_failure(failures, 'ros1_field_catkin_test_result_schema_invalid')
    seen_content = set()
    seen_test_ids = set()
    seen_suite_sets = set()
    observed_ids = []
    passed = failed = errors = skipped = 0
    xml_declarations_valid = True
    for index, identity in enumerate(artifact_identities):
        content_key = (identity['size_bytes'], identity['sha256'])
        if content_key in seen_content:
            _add_failure(failures, 'ros1_field_catkin_test_duplicate_artifact')
        seen_content.add(content_key)
        try:
            raw = Path(identity['path']).read_bytes()
            if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
                raise ET.ParseError('DTD/entity forbidden')
            root = ET.fromstring(raw)
            if root.tag != 'testsuite':
                raise ET.ParseError('one testsuite root required')
        except (OSError, ET.ParseError):
            _add_failure(
                failures, 'ros1_field_catkin_test_xml_invalid:' + str(index))
            continue
        testcase_ids = []
        local_failed = local_errors = local_skipped = 0
        testcases = list(root.findall('testcase'))
        if not testcases:
            _add_failure(
                failures, 'ros1_field_catkin_test_xml_invalid:' + str(index))
            xml_declarations_valid = False
        for testcase in testcases:
            classname = testcase.get('classname')
            name = testcase.get('name')
            if (not isinstance(classname, str) or not classname
                    or not isinstance(name, str) or not name):
                _add_failure(
                    failures, 'ros1_field_catkin_test_xml_invalid:' + str(index))
                continue
            test_id = classname + '.' + name
            if test_id in seen_test_ids:
                _add_failure(failures, 'ros1_field_catkin_test_duplicate_testcase')
            seen_test_ids.add(test_id)
            testcase_ids.append(test_id)
            observed_ids.append(test_id)
            failure_nodes = testcase.findall('failure')
            error_nodes = testcase.findall('error')
            skipped_nodes = testcase.findall('skipped')
            if len(failure_nodes) > 1 or len(error_nodes) > 1 or len(skipped_nodes) > 1:
                _add_failure(
                    failures, 'ros1_field_catkin_test_xml_invalid:' + str(index))
            if failure_nodes:
                local_failed += 1
            elif error_nodes:
                local_errors += 1
            elif skipped_nodes:
                local_skipped += 1
            else:
                passed += 1
        suite_key = _canonical_identity_set_sha256(sorted(testcase_ids))
        if suite_key in seen_suite_sets:
            _add_failure(failures, 'ros1_field_catkin_test_duplicate_suite')
        seen_suite_sets.add(suite_key)
        failed += local_failed
        errors += local_errors
        skipped += local_skipped
        declared_counts = {
            'tests': len(testcases),
            'failures': local_failed,
            'errors': local_errors,
            'skipped': local_skipped,
        }
        for key, actual in declared_counts.items():
            value = root.get(key)
            if value is None and key == 'skipped':
                value = '0'
            try:
                value_valid = int(value) == actual and str(int(value)) == value
            except (TypeError, ValueError):
                value_valid = False
            if not value_valid:
                xml_declarations_valid = False
    observed_ids = sorted(observed_ids)
    tests_run = len(observed_ids)
    observed_sha = _canonical_identity_set_sha256(observed_ids)
    if observed_ids != expected_ids:
        _add_failure(failures, 'ros1_field_catkin_test_id_set_mismatch')
    if (not xml_declarations_valid
            or tests_run != passed + failed + errors + skipped
            or tests_run <= 0):
        _add_failure(failures, 'ros1_field_catkin_test_count_mismatch')
    if failed or errors:
        _add_failure(failures, 'ros1_field_catkin_tests_failed')
    if skipped:
        _add_failure(failures, 'ros1_field_catkin_tests_skipped')
    marker = (
        'LIMO_ROS1_CATKIN_TEST_IDS_SHA256=' +
        expected['test_id_set_sha256'])
    marker_count = 0
    if isinstance(test_result_log_identity, Mapping):
        try:
            log_text = Path(test_result_log_identity['path']).read_text(
                encoding='utf-8')
            marker_count = sum(
                1 for line in log_text.splitlines() if line == marker)
        except (OSError, UnicodeError):
            marker_count = 0
    if marker_count != 1 or observed_sha != expected['test_id_set_sha256']:
        _add_failure(failures, 'ros1_field_catkin_test_marker_invalid')
    return {
        'expected_test_count': len(expected_ids),
        'tests_run': tests_run,
        'passed': passed,
        'failed': failed,
        'errors': errors,
        'skipped': skipped,
        'expected_test_id_set_sha256': expected['test_id_set_sha256'],
        'observed_test_id_set_sha256': observed_sha,
        'artifact_identities': artifact_identities,
        'marker': marker,
        'marker_count': marker_count,
    }


_ROS1_FRESH_IMPORT_BOOTSTRAP = r'''
import hashlib
import importlib
import importlib.metadata
import json
import os
import pathlib
import stat
import sys

payload_raw = sys.stdin.buffer.read()
payload = json.loads(payload_raw.decode('utf-8'))
marker = payload['result_marker']
application_root = pathlib.Path(payload['application_root']).resolve(strict=True)
stdlib_paths = []
for item in list(sys.path):
    if not item:
        continue
    normalized = item.replace('\\', '/').lower()
    if '/site-packages' in normalized or '/dist-packages' in normalized:
        continue
    try:
        resolved = pathlib.Path(item).resolve(strict=True)
    except OSError:
        continue
    if str(resolved) not in stdlib_paths:
        stdlib_paths.append(str(resolved))
sys.path[:] = [str(application_root)] + stdlib_paths

for root in payload['import_roots']:
    for name in list(sys.modules):
        if name == root or name.startswith(root + '.'):
            del sys.modules[name]

def identity(path):
    value = pathlib.Path(path).resolve(strict=True)
    mode = value.lstat().st_mode
    if not stat.S_ISREG(mode) or value.is_symlink():
        raise RuntimeError('not_regular')
    raw = value.read_bytes()
    return {
        'path': str(value),
        'size_bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
    }

def module_record(module_name, expected_class=None):
    module = importlib.import_module(module_name)
    origin = getattr(module, '__file__', None)
    spec = getattr(module, '__spec__', None)
    if not origin or spec is None or spec.origin != origin:
        raise RuntimeError('module_origin')
    loader = getattr(module, '__loader__', None)
    if loader is not getattr(spec, 'loader', None):
        raise RuntimeError('module_loader')
    if hasattr(loader, 'get_filename'):
        if pathlib.Path(loader.get_filename(module_name)).resolve() != pathlib.Path(origin).resolve():
            raise RuntimeError('loader_filename')
    record = identity(origin)
    record['module'] = module_name
    record['class_present'] = None
    if expected_class is not None:
        record['class_present'] = isinstance(getattr(module, expected_class, None), type)
        if not record['class_present']:
            raise RuntimeError('message_class')
    return module, record

failures = []
dependencies = []
modules = []
for expected in payload['dependencies']:
    try:
        module, origin = module_record(expected['import_name'])
        distribution = importlib.metadata.distribution(expected['distribution'])
        metadata_path = pathlib.Path(distribution._path) / 'METADATA'
        record = {
            'distribution': expected['distribution'],
            'import_name': expected['import_name'],
            'distribution_version': distribution.version,
            'module_version': getattr(module, '__version__', None),
            'distribution_metadata': identity(metadata_path),
            'module_origin': {key: origin[key] for key in ('path', 'size_bytes', 'sha256')},
        }
        dependencies.append(record)
    except Exception as error:
        failures.append('dependency:{}:{}'.format(expected['distribution'], type(error).__name__))

for expected in payload['modules']:
    try:
        unused, record = module_record(
            expected['module'], expected.get('expected_class'))
        modules.append(record)
    except Exception as error:
        failures.append('module:{}:{}'.format(expected['label'], type(error).__name__))

executable = identity(sys.executable)
result = {
    'schema_version': 1,
    'manifest_sha256': payload['manifest_sha256'],
    'result_marker': marker,
    'application_root': str(application_root),
    'sys_path': list(sys.path),
    'executable': executable,
    'dependencies': dependencies,
    'modules': modules,
    'failures': failures,
}
print(marker + '=' + json.dumps(result, sort_keys=True, separators=(',', ':')))
raise SystemExit(0 if not failures else 7)
'''


def _run_ros1_fresh_import_probe(
        isolation_root: Path, contract: Mapping, dependency_records: Sequence,
        module_expectations: Sequence, failures: List[str]) -> Mapping:
    """Run a host-owned isolated child that freshly imports installed assets."""
    application_relative = contract['install_policy'][
        'application_root_relative']
    application_root = Path(isolation_root) / application_relative
    try:
        application_root = application_root.resolve(strict=True)
        application_root.relative_to(Path(isolation_root).resolve(strict=True))
        if _path_is_linklike(application_root):
            raise OSError('linked application root')
    except (OSError, RuntimeError, ValueError):
        _add_failure(failures, 'ros1_field_fresh_import_probe_invalid')
        return {'validated_pass': False, 'failures': [
            'ros1_field_fresh_import_probe_invalid']}
    manifest = {
        'schema_version': 1,
        'application_root': str(application_root),
        'dependencies': list(dependency_records),
        'modules': list(module_expectations),
        'import_roots': sorted(set(
            [item['import_name'] for item in dependency_records]
            + [item['module'].split('.')[0] for item in module_expectations])),
    }
    manifest_raw = json.dumps(
        manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    marker = 'LIMO_ROS1_FRESH_IMPORT_' + hashlib.sha256(
        os.urandom(32) + manifest_raw).hexdigest()
    payload = dict(manifest)
    payload['manifest_sha256'] = manifest_sha
    payload['result_marker'] = marker
    payload_raw = json.dumps(
        payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    executable = Path(sys.executable)
    executable_identity = None
    try:
        executable = executable.resolve(strict=True)
        if _path_is_linklike(executable) or not stat.S_ISREG(
                executable.stat().st_mode):
            raise OSError('invalid executable')
        executable_identity = {
            'path': str(executable),
            'size_bytes': executable.stat().st_size,
            'sha256': sha256_file(executable),
        }
    except (OSError, RuntimeError):
        _add_failure(failures, 'ros1_field_fresh_import_probe_runner_failed')
        return {'validated_pass': False, 'failures': [
            'ros1_field_fresh_import_probe_runner_failed']}
    argv = [str(executable), '-I', '-B', '-c', _ROS1_FRESH_IMPORT_BOOTSTRAP]
    sanitized_argv = [str(executable), '-I', '-B', '-c',
                      '<host-owned-bootstrap>']
    env = dict(os.environ)
    removed_environment_keys = sorted(
        key for key in env
        if key in {'PYTHONPATH', 'PYTHONHOME'} or key.startswith('ROS_'))
    for key in removed_environment_keys:
        env.pop(key, None)
    state_root = Path(isolation_root) / 'probe_state'
    state_paths = {
        'YOLO_CONFIG_DIR': state_root / 'yolo',
        'MPLCONFIGDIR': state_root / 'matplotlib',
        'XDG_CACHE_HOME': state_root / 'xdg-cache',
        'TORCH_HOME': state_root / 'torch',
    }
    try:
        for value in state_paths.values():
            value.mkdir(parents=True, exist_ok=True)
        for key, value in state_paths.items():
            env[key] = str(value.resolve(strict=True))
    except (OSError, RuntimeError):
        _add_failure(failures, 'ros1_field_fresh_import_probe_runner_failed')
        return {'validated_pass': False, 'failures': [
            'ros1_field_fresh_import_probe_runner_failed']}
    child = None
    timed_out = False
    try:
        child = subprocess.run(
            argv, input=payload_raw, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(Path(isolation_root).resolve()),
            env=env, timeout=120, check=False)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        stdout = error.stdout or b''
        stderr = error.stderr or b''
        _add_failure(failures, 'ros1_field_fresh_import_probe_timeout')
    except (OSError, subprocess.SubprocessError):
        stdout = b''
        stderr = b''
        _add_failure(failures, 'ros1_field_fresh_import_probe_runner_failed')
    else:
        stdout = child.stdout or b''
        stderr = child.stderr or b''
    result = None
    marker_lines = []
    try:
        marker_lines = [
            line for line in stdout.decode('utf-8').splitlines()
            if line.startswith(marker + '=')]
        if len(marker_lines) == 1:
            result = _strict_json_loads(marker_lines[0].split('=', 1)[1])
    except (UnicodeError, ValueError, json.JSONDecodeError):
        result = None
    probe_failures = []
    if timed_out:
        probe_failures.append('ros1_field_fresh_import_probe_timeout')
    if child is None and not timed_out:
        probe_failures.append('ros1_field_fresh_import_probe_runner_failed')
    if len(stdout) > 2 * 1024 * 1024 or len(stderr) > 2 * 1024 * 1024:
        probe_failures.append('ros1_field_fresh_import_probe_output_invalid')
    if len(marker_lines) != 1 or not isinstance(result, Mapping):
        probe_failures.append('ros1_field_fresh_import_probe_marker_invalid')
        result = {} if not isinstance(result, Mapping) else result
    expected_result_keys = {
        'schema_version', 'manifest_sha256', 'result_marker',
        'application_root', 'sys_path', 'executable', 'dependencies',
        'modules', 'failures'}
    if (set(result) != expected_result_keys
            or result.get('schema_version') != 1
            or result.get('manifest_sha256') != manifest_sha
            or result.get('result_marker') != marker
            or result.get('application_root') != str(application_root)
            or result.get('executable') != executable_identity
            or result.get('failures') != []
            or child is None or child.returncode != 0):
        probe_failures.append('ros1_field_fresh_import_probe_invalid')
    expected_sys_path_first = str(application_root)
    actual_sys_path = result.get('sys_path')
    if (not isinstance(actual_sys_path, list) or not actual_sys_path
            or actual_sys_path[0] != expected_sys_path_first
            or any(
                '/site-packages' in str(item).replace('\\', '/').lower()
                or ('/dist-packages' in str(item).replace('\\', '/').lower()
                    and str(item) != expected_sys_path_first)
                or '/devel/' in str(item).replace('\\', '/').lower()
                or '/ros1_overlay_src/' in str(item).replace('\\', '/').lower()
                for item in actual_sys_path)):
        probe_failures.append('ros1_field_fresh_import_probe_sys_path_invalid')
    dependency_actual = {
        item.get('distribution'): item for item in result.get(
            'dependencies', []) if isinstance(item, Mapping)}
    if len(dependency_actual) != len(dependency_records):
        probe_failures.append('ros1_field_fresh_import_probe_invalid')
    for expected in dependency_records:
        actual = dependency_actual.get(expected['distribution'])
        if (not isinstance(actual, Mapping)
                or actual.get('import_name') != expected['import_name']
                or actual.get('distribution_version')
                != expected['exact_version']
                or actual.get('module_version') != expected['exact_version']
                or actual.get('distribution_metadata')
                != expected['distribution_metadata']
                or actual.get('module_origin') != expected['module_origin']):
            probe_failures.append(
                'ros1_field_fresh_import_probe_dependency_invalid:'
                + expected['distribution'])
    module_actual = {
        item.get('module'): item for item in result.get(
            'modules', []) if isinstance(item, Mapping)}
    if len(module_actual) != len(module_expectations):
        probe_failures.append('ros1_field_fresh_import_probe_invalid')
    seen_module_paths = set()
    for expected in module_expectations:
        actual = module_actual.get(expected['module'])
        expected_identity = expected['identity']
        if (not isinstance(actual, Mapping)
                or {key: actual.get(key) for key in (
                    'path', 'size_bytes', 'sha256')} != expected_identity
                or (expected.get('expected_class') is not None
                    and actual.get('class_present') is not True)):
            probe_failures.append(
                'ros1_field_fresh_import_probe_module_invalid:'
                + expected['label'])
        if isinstance(actual, Mapping):
            module_path = actual.get('path')
            if module_path in seen_module_paths:
                probe_failures.append(
                    'ros1_field_fresh_import_probe_artifact_reused')
            seen_module_paths.add(module_path)
    for code in sorted(set(probe_failures)):
        _add_failure(failures, code)
    return {
        'validated_pass': not probe_failures,
        'manifest_sha256': manifest_sha,
        'sanitized_argv': sanitized_argv,
        'executable_identity': executable_identity,
        'removed_environment_keys': removed_environment_keys,
        'state_directories': {
            key: str(value.resolve()) for key, value in state_paths.items()},
        'home_preserved': env.get('HOME') == os.environ.get('HOME'),
        'exit_code': None if child is None else child.returncode,
        'timed_out': timed_out,
        'stdout_length_bytes': len(stdout),
        'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
        'stdout_head': stdout[:512].decode('utf-8', errors='replace'),
        'stdout_tail': stdout[-512:].decode('utf-8', errors='replace'),
        'stderr_length_bytes': len(stderr),
        'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
        'stderr_head': stderr[:512].decode('utf-8', errors='replace'),
        'stderr_tail': stderr[-512:].decode('utf-8', errors='replace'),
        'result_marker': marker,
        'result': result,
        'failures': sorted(set(probe_failures)),
    }


def validate_ros1_noetic_field_install_evidence(
        evidence_path: Path, release_binding: Mapping = None,
        expected_model_hashes: Mapping = None, now_unix_sec: float = None,
        workspace: Path = None, source_audit: Mapping = None,
        canonical_source_binding: Mapping = None,
        allow_test_synthetic_binding: bool = False) -> Mapping:
    """Validate one complete ROS1 install report and copied file inventory."""
    contract_record = load_ros1_noetic_field_install_contract(workspace)
    contract = contract_record.get('payload')
    failures = list(contract_record.get('failures', []))
    failures.extend(_ros1_contract_schema_failures(contract))
    canonical_binding_failures = []
    test_only_binding = (
        isinstance(canonical_source_binding, Mapping)
        and canonical_source_binding.get('test_only') is True)
    if canonical_source_binding is None:
        canonical_binding_failures.append(ROS1_CANONICAL_BINDING_MISSING)
    else:
        binding_schema_failures = _ros1_canonical_binding_failures(
            canonical_source_binding, contract_record,
            allow_test_synthetic_binding)
        if binding_schema_failures:
            canonical_binding_failures.extend(binding_schema_failures)
        else:
            if canonical_source_binding.get('test_only') is False:
                try:
                    expected_project_binding = (
                        make_ros1_canonical_source_binding(test_only=False))
                except (OSError, RuntimeError, TypeError, ValueError):
                    expected_project_binding = None
                if (not isinstance(expected_project_binding, Mapping)
                        or dict(canonical_source_binding)
                        != dict(expected_project_binding)):
                    canonical_binding_failures.append(
                        ROS1_CANONICAL_BINDING_MISMATCH)
            if (source_audit is not None
                    and not _ros1_audit_matches_canonical_binding(
                        source_audit, canonical_source_binding)):
                canonical_binding_failures.append(
                    ROS1_CANONICAL_BINDING_MISMATCH)
    for code in canonical_binding_failures:
        _add_failure(failures, code)
    canonical_binding_valid = not canonical_binding_failures
    if test_only_binding:
        _add_failure(failures, ROS1_TEST_ONLY_SOURCE_BINDING)
    canonical_runtime_complete = (
        canonical_binding_valid
        and not test_only_binding
        and canonical_source_binding.get('source_contract_pass') is True
        and canonical_source_binding.get('indexer_only_detected') is False
        and canonical_source_binding.get('architecture_blockers') == [])
    if not canonical_runtime_complete:
        _add_failure(failures, ROS1_RUNTIME_ARCHITECTURE_BLOCKER)
    path = None
    try:
        path = Path(evidence_path).resolve(strict=True)
    except (TypeError, OSError, RuntimeError):
        _add_failure(failures, 'ros1_field_install_evidence_missing')
    report = None
    if path is not None:
        try:
            report = _strict_json_loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            _add_failure(failures, 'ros1_field_install_evidence_invalid_json')
    expected_keys = {
        'schema_version', 'gate_id', 'scope', 'result',
        'generated_at_unix_sec', 'read_only', 'authorizes_motion',
        'publishes_ros_messages', 'nodes_started', 'camera_opened',
        'hardware_connected', 'runtime', 'environment', 'implementation',
        'packages', 'dependencies', 'source_binding', 'source_contract',
        'model_bindings', 'runtime_dependency_inventory',
        'runtime_provisioning', 'catkin_test_results',
        'import_smoke',
        'workspace_root', 'isolation_root',
        'commands', 'exit_codes',
        'test_failures', 'logs', 'installed_artifacts',
        'install_set_sha256'}
    if not isinstance(report, Mapping) or set(report) != expected_keys:
        _add_failure(failures, 'ros1_field_install_evidence_schema_invalid')
        report = {} if not isinstance(report, Mapping) else report
    if (report.get('schema_version') != 1
            or report.get('gate_id') != ROS1_FIELD_INSTALL_GATE_ID
            or report.get('scope') != 'field_delivery'
            or report.get('result') != 'PASS'):
        _add_failure(failures, 'ros1_field_install_claim_not_pass')
    if (report.get('read_only') is not True
            or report.get('authorizes_motion') is not False
            or report.get('publishes_ros_messages') is not False
            or report.get('nodes_started') is not False
            or report.get('camera_opened') is not False
            or report.get('hardware_connected') is not False):
        _add_failure(failures, 'ros1_field_install_safety_contract_invalid')
    if _contains_forbidden_control_claim(report):
        _add_failure(failures, 'ros1_field_install_nested_control_claim')
    declared_isolation_path = None
    try:
        declared_isolation_path = Path(
            report.get('isolation_root')).resolve(strict=True)
    except (TypeError, OSError, RuntimeError):
        pass
    if now_unix_sec is not None:
        _check_report_freshness(
            report, 'generated_at_unix_sec', now_unix_sec,
            MAX_SOFTWARE_PROOF_AGE_SEC,
            'ros1_field_install_evidence_stale', failures)

    runtime = report.get('runtime')
    if (not isinstance(runtime, Mapping)
            or set(runtime) != {
                'ros_major', 'ros_distro', 'python', 'machine'}
            or runtime.get('ros_major') != 1
            or runtime.get('ros_distro') != 'noetic'
            or runtime.get('python') != '3.8.10'
            or not isinstance(runtime.get('machine'), str)
            or not runtime.get('machine')):
        _add_failure(failures, 'ros1_field_install_runtime_invalid')
    environment = report.get('environment')
    required_flags = (contract.get('install_policy', {}).get(
        'required_environment_flags', []) if isinstance(contract, Mapping)
                      else [])
    if (not isinstance(environment, Mapping)
            or set(environment) != set(required_flags)
            or any(environment.get(name) is not True
                   for name in required_flags)):
        _add_failure(failures, 'ros1_field_install_environment_not_entered')
    implementation = report.get('implementation')
    interface_modes = set(contract.get('interface_modes', {})) if isinstance(
        contract, Mapping) else set()
    if (not isinstance(implementation, Mapping)
            or set(implementation) != {
                'mode', 'complete_runtime', 'architecture_blockers',
                'capabilities'}
            or implementation.get('mode') not in interface_modes
            or implementation.get('complete_runtime') is not True
            or implementation.get('architecture_blockers') != []
            or implementation.get('capabilities') != contract.get(
                'required_capabilities')):
        _add_failure(failures, 'ros1_field_install_runtime_not_complete')
    mode = implementation.get('mode') if isinstance(
        implementation, Mapping) else 'native_ros1_messages'

    package_contract = contract.get('package', {}) if isinstance(
        contract, Mapping) else {}
    if report.get('packages') != [package_contract.get('name')]:
        _add_failure(failures, 'ros1_field_install_package_set_invalid')
    required_dependencies = package_contract.get('required_dependencies', [])
    if (not isinstance(report.get('dependencies'), list)
            or sorted(report.get('dependencies'))
            != sorted(required_dependencies)):
        _add_failure(failures, 'ros1_field_install_dependency_set_invalid')

    runtime_lock = contract.get(
        'python_runtime_dependency_lock', {}) if isinstance(
            contract, Mapping) else {}
    expected_runtime_dependencies = runtime_lock.get('requirements', [])
    runtime_inventory = report.get('runtime_dependency_inventory')
    expected_by_distribution = {
        item['distribution']: item for item in expected_runtime_dependencies
        if isinstance(item, Mapping) and isinstance(
            item.get('distribution'), str)}
    inventory_by_distribution = {}
    runtime_dependency_identities = []
    dependency_probe_records = []
    dependency_artifact_paths = {}
    seen_runtime_paths = set()
    if not isinstance(runtime_inventory, list):
        _add_failure(
            failures, 'ros1_field_runtime_dependency_inventory_invalid')
        runtime_inventory = []
    for index, item in enumerate(runtime_inventory):
        distribution = item.get('distribution') if isinstance(
            item, Mapping) else None
        label = distribution if isinstance(distribution, str) else str(index)
        expected_dependency = expected_by_distribution.get(distribution)
        if (not isinstance(item, Mapping)
                or set(item) != {
                    'distribution', 'import_name', 'requirement',
                    'distribution_version', 'module_version',
                    'distribution_metadata', 'module_origin',
                    'distribution_artifact'}
                or expected_dependency is None
                or distribution in inventory_by_distribution
                or item.get('import_name')
                != expected_dependency.get('import_name')
                or item.get('requirement')
                != expected_dependency.get('requirement')
                or item.get('distribution_version')
                != expected_dependency.get('exact_version')
                or item.get('module_version')
                != expected_dependency.get('exact_version')):
            _add_failure(
                failures,
                'ros1_field_runtime_dependency_inventory_invalid:' + label)
            continue
        metadata_declaration = item.get('distribution_metadata')
        origin_declaration = item.get('module_origin')
        artifact_declaration = item.get('distribution_artifact')
        if (not isinstance(metadata_declaration, Mapping)
                or set(metadata_declaration)
                != {'path', 'size_bytes', 'sha256'}
                or not isinstance(origin_declaration, Mapping)
                or set(origin_declaration)
                != {'path', 'size_bytes', 'sha256'}
                or not isinstance(artifact_declaration, Mapping)
                or set(artifact_declaration) != {
                    'path', 'size_bytes', 'sha256', 'filename', 'format'}
                or artifact_declaration.get('format') != 'wheel'
                or artifact_declaration.get('filename')
                != Path(str(artifact_declaration.get('path'))).name):
            _add_failure(
                failures,
                'ros1_field_runtime_dependency_inventory_invalid:' + label)
            continue
        inventory_by_distribution[distribution] = item
        metadata_identity = _evidence_file_identity(
            path, metadata_declaration,
            'runtime_dependency_distribution_metadata:' + distribution,
            failures) if path else None
        origin_identity = _evidence_file_identity(
            path, origin_declaration,
            'runtime_dependency_module_origin:' + distribution,
            failures) if path else None
        artifact_identity = _evidence_file_identity(
            path, artifact_declaration,
            'runtime_dependency_distribution_artifact:' + distribution,
            failures) if path else None
        for role, identity in (
                ('distribution_metadata', metadata_identity),
                ('module_origin', origin_identity),
                ('distribution_artifact', artifact_identity)):
            if identity is None:
                continue
            resolved_identity_path = identity['path']
            if resolved_identity_path in seen_runtime_paths:
                _add_failure(
                    failures,
                    'ros1_field_runtime_dependency_artifact_reused:'
                    + distribution)
            seen_runtime_paths.add(resolved_identity_path)
            runtime_dependency_identities.append({
                'distribution': distribution,
                'role': role,
                **identity,
            })
        if artifact_identity is None:
            _add_failure(
                failures,
                'ros1_field_runtime_dependency_distribution_artifact_'
                'provenance_unavailable:' + distribution)
        else:
            artifact_path = Path(artifact_identity['path'])
            artifact_root = (
                declared_isolation_path / 'evidence' / 'runtime-artifacts'
                if declared_isolation_path is not None else None)
            if (artifact_root is None
                    or _regular_non_link_file_under(
                        artifact_path, artifact_root) is None
                    or not _validate_distribution_wheel(
                        artifact_path, distribution,
                        expected_dependency.get('exact_version'))):
                _add_failure(
                    failures,
                    'ros1_field_runtime_dependency_distribution_artifact_'
                    'provenance_unavailable:' + distribution)
            else:
                dependency_artifact_paths[distribution] = artifact_path
        if metadata_identity is not None:
            metadata_headers = {}
            metadata_valid = True
            metadata_path = Path(metadata_identity['path'])
            try:
                application_root = (
                    declared_isolation_path / contract['install_policy'][
                        'application_root_relative']).resolve(strict=True)
                metadata_path.relative_to(application_root)
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                application_root = None
            try:
                metadata_text = metadata_path.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                metadata_valid = False
                metadata_text = ''
            for line in metadata_text.splitlines():
                if not line:
                    continue
                if line[:1].isspace() or ':' not in line:
                    metadata_valid = False
                    continue
                name, value = line.split(':', 1)
                if name in metadata_headers:
                    metadata_valid = False
                metadata_headers[name] = value.strip()
            metadata_identity_value = _metadata_name_version(
                metadata_text.encode('utf-8')) if metadata_valid else None
            if (application_root is None
                    or _regular_non_link_file_under(
                        metadata_path, application_root) is None
                    or metadata_path.name != 'METADATA'
                    or not metadata_path.parent.name.endswith('.dist-info')
                    or not metadata_valid
                    or metadata_identity_value != (
                        distribution, expected_dependency.get('exact_version'))):
                _add_failure(
                    failures,
                    'ros1_field_runtime_dependency_metadata_invalid:'
                    + distribution)
        if origin_identity is not None:
            origin_path = Path(origin_identity['path'])
            try:
                expected_origin_path = (
                    declared_isolation_path / contract['install_policy'][
                        'application_root_relative'] /
                    expected_dependency.get('import_name') /
                    '__init__.py').resolve(strict=True)
            except (AttributeError, OSError, RuntimeError, TypeError):
                expected_origin_path = None
            if (expected_origin_path is None
                    or origin_path.resolve() != expected_origin_path
                    or origin_path.name != '__init__.py'
                    or origin_path.parent.name
                    != expected_dependency.get('import_name')
                    or _regular_non_link_file_under(
                        origin_path, expected_origin_path.parent.parent)
                    is None):
                _add_failure(
                    failures,
                    'ros1_field_runtime_dependency_module_origin_invalid:'
                    + distribution)
        if metadata_identity is not None and origin_identity is not None:
            dependency_probe_records.append({
                'distribution': distribution,
                'import_name': expected_dependency.get('import_name'),
                'exact_version': expected_dependency.get('exact_version'),
                'distribution_metadata': metadata_identity,
                'module_origin': origin_identity,
            })
    if set(inventory_by_distribution) != set(expected_by_distribution):
        _add_failure(
            failures, 'ros1_field_runtime_dependency_inventory_invalid')

    runtime_provisioning = report.get('runtime_provisioning')
    provisioning_commands = (
        runtime_provisioning.get('commands')
        if isinstance(runtime_provisioning, Mapping) else None)
    executable_declaration = (
        runtime_provisioning.get('python_executable')
        if isinstance(runtime_provisioning, Mapping) else None)
    executable_identity = _evidence_file_identity(
        path, executable_declaration, 'runtime_provisioning_python', failures
    ) if path else None
    expected_application_relative = (
        contract.get('install_policy', {}).get('application_root_relative')
        if isinstance(contract, Mapping) else None)
    expected_application_root = None
    try:
        expected_application_root = (
            declared_isolation_path / expected_application_relative).resolve(
                strict=True)
    except (AttributeError, OSError, RuntimeError, TypeError):
        pass
    if (not isinstance(runtime_provisioning, Mapping)
            or set(runtime_provisioning) != {
                'schema_version', 'strategy', 'application_root_relative',
                'python_executable', 'commands'}
            or runtime_provisioning.get('schema_version') != 1
            or runtime_provisioning.get('strategy')
            != 'offline_wheels_no_index_no_deps_target'
            or runtime_provisioning.get('application_root_relative')
            != expected_application_relative
            or not isinstance(provisioning_commands, Mapping)
            or set(provisioning_commands) != set(expected_by_distribution)
            or executable_identity is None
            or executable_identity.get('path')
            != str(Path(sys.executable).resolve())):
        _add_failure(failures, 'ros1_field_runtime_provisioning_invalid')
        provisioning_commands = (
            provisioning_commands
            if isinstance(provisioning_commands, Mapping) else {})
    for distribution, dependency in expected_by_distribution.items():
        command = provisioning_commands.get(distribution)
        artifact_path = dependency_artifact_paths.get(distribution)
        expected_argv = None
        if (executable_identity is not None
                and expected_application_root is not None
                and artifact_path is not None):
            expected_argv = [
                executable_identity['path'], '-m', 'pip', '--isolated',
                'install', '--no-index', '--no-deps', '--no-compile',
                '--target', str(expected_application_root),
                str(artifact_path.resolve())]
        if (not isinstance(command, Mapping)
                or set(command) != {'argv', 'exit_code', 'log'}
                or command.get('argv') != expected_argv
                or not isinstance(command.get('exit_code'), int)
                or isinstance(command.get('exit_code'), bool)
                or command.get('exit_code') != 0):
            _add_failure(
                failures,
                'ros1_field_runtime_provisioning_invalid:' + distribution)
            continue
        log_identity = _evidence_file_identity(
            path, command.get('log'),
            'runtime_provisioning_log:' + distribution, failures
        ) if path else None
        if log_identity is None or log_identity['size_bytes'] <= 0:
            _add_failure(
                failures,
                'ros1_field_runtime_provisioning_invalid:' + distribution)

    import_smoke = report.get('import_smoke')
    expected_import_smoke_keys = {
        'schema_version', 'probe_kind', 'workspace_source_removed',
        'ros_graph_started', 'fake_ros_api', 'sys_path_relative',
        'probe_exit_code', 'import_failures', 'package_import',
        'entrypoint_imports', 'generated_message_package_import',
        'generated_message_imports'}
    expected_entry_modules = {
        'dual_model_detector': 'dual_model_detector',
        'perception_frame_adapter': 'ros1_adapter',
        'perception_frame_collector': 'perception_frame_collector',
        'perception_readiness': 'perception_readiness',
        'rosbag1_rgbd_indexer': 'rosbag1_rgbd_indexer',
        'typed_raw_binding': 'typed_raw_binding',
    }
    expected_generated_messages = (
        'ObjectDetection', 'PerceptionFrame', 'PerceptionTarget')
    expected_sys_path_relative = ['install/lib/python3/dist-packages']
    if (not isinstance(import_smoke, Mapping)
            or set(import_smoke) != expected_import_smoke_keys
            or not isinstance(import_smoke.get('schema_version'), int)
            or isinstance(import_smoke.get('schema_version'), bool)
            or import_smoke.get('schema_version') != 1
            or import_smoke.get('probe_kind')
            != 'ROS1_NOETIC_ISOLATED_PREFIX_IMPORT_SMOKE'
            or import_smoke.get('workspace_source_removed') is not True
            or import_smoke.get('ros_graph_started') is not False
            or import_smoke.get('fake_ros_api') is not True
            or import_smoke.get('sys_path_relative')
            != expected_sys_path_relative
            or not isinstance(import_smoke.get('probe_exit_code'), int)
            or isinstance(import_smoke.get('probe_exit_code'), bool)
            or import_smoke.get('probe_exit_code') != 0
            or import_smoke.get('import_failures') != []):
        _add_failure(failures, 'ros1_field_import_smoke_invalid')
        import_smoke = (
            import_smoke if isinstance(import_smoke, Mapping) else {})

    smoke_record_keys = {
        'module', 'import_succeeded', 'installed_relative_path',
        'path', 'size_bytes', 'sha256'}

    def validate_import_smoke_record(
            record, label, expected_module, expected_relative):
        if (not isinstance(record, Mapping)
                or set(record) != smoke_record_keys
                or record.get('module') != expected_module
                or record.get('import_succeeded') is not True
                or record.get('installed_relative_path')
                != expected_relative):
            _add_failure(
                failures, 'ros1_field_import_smoke_origin_invalid:' + label)
            return None
        declaration = {
            key: record.get(key) for key in ('path', 'size_bytes', 'sha256')}
        identity = _evidence_file_identity(
            path, declaration, 'import_smoke:' + label,
            failures) if path else None
        if identity is None:
            return None
        try:
            expected_path = (
                declared_isolation_path / 'install' /
                expected_relative).resolve(
                    strict=True)
        except (OSError, RuntimeError, TypeError):
            expected_path = None
        actual_path = Path(identity['path'])
        try:
            ast.parse(
                actual_path.read_text(encoding='utf-8'),
                filename=str(actual_path), feature_version=(3, 8))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            expected_path = None
        if (expected_path is None
                or actual_path.resolve() != expected_path
                or _path_is_linklike(actual_path)):
            _add_failure(
                failures, 'ros1_field_import_smoke_origin_invalid:' + label)
            return None
        return identity

    package_name = package_contract.get('name')
    package_import = import_smoke.get('package_import')
    validate_import_smoke_record(
        package_import, 'package', package_name,
        'lib/python3/dist-packages/{}/__init__.py'.format(package_name))

    validate_import_smoke_record(
        import_smoke.get('generated_message_package_import'),
        'generated_message_package', '{}.msg'.format(package_name),
        'lib/python3/dist-packages/{}/msg/__init__.py'.format(package_name))

    entrypoint_imports = import_smoke.get('entrypoint_imports')
    if (not isinstance(entrypoint_imports, Mapping)
            or set(entrypoint_imports) != set(expected_entry_modules)
            or set(entrypoint_imports) != set(
                contract.get('required_entrypoints', {}))):
        _add_failure(failures, 'ros1_field_import_smoke_invalid')
        entrypoint_imports = (
            entrypoint_imports
            if isinstance(entrypoint_imports, Mapping) else {})
    for entry_name, module_stem in expected_entry_modules.items():
        validate_import_smoke_record(
            entrypoint_imports.get(entry_name), 'entrypoint:' + entry_name,
            '{}.{}'.format(package_name, module_stem),
            'lib/python3/dist-packages/{}/{}.py'.format(
                package_name, module_stem))

    generated_imports = import_smoke.get('generated_message_imports')
    if (not isinstance(generated_imports, Mapping)
            or set(generated_imports) != set(expected_generated_messages)):
        _add_failure(failures, 'ros1_field_import_smoke_invalid')
        generated_imports = (
            generated_imports
            if isinstance(generated_imports, Mapping) else {})
    for message_name in expected_generated_messages:
        validate_import_smoke_record(
            generated_imports.get(message_name),
            'generated_message:' + message_name,
            '{}.msg._{}'.format(package_name, message_name),
            'lib/python3/dist-packages/{}/msg/_{}.py'.format(
                package_name, message_name))

    source_binding = report.get('source_binding')
    source_contract = report.get('source_contract')
    source_workspace = None
    try:
        source_workspace = Path(report.get('workspace_root')).resolve(
            strict=True)
    except (TypeError, OSError, RuntimeError):
        _add_failure(failures, 'ros1_field_install_workspace_invalid')
    if source_workspace is not None and _path_is_linklike(source_workspace):
        _add_failure(failures, 'ros1_field_install_workspace_link_forbidden')
        source_workspace = None
    if (source_workspace is None or declared_isolation_path is None
            or source_workspace != declared_isolation_path
            or (path is not None
                and path.parent.parent.resolve() != declared_isolation_path)
            or (declared_isolation_path / 'src').exists()):
        _add_failure(failures, 'ros1_field_install_source_space_unbound')
    live_source_audit = None
    if source_workspace is not None:
        live_source_audit = audit_ros1_noetic_field_source_contract(
            source_workspace, contract_record)
    if (canonical_binding_valid
            and not _ros1_audit_matches_canonical_binding(
                live_source_audit, canonical_source_binding)):
        _add_failure(failures, ROS1_CANONICAL_BINDING_MISMATCH)
    if (not isinstance(source_binding, Mapping)
            or set(source_binding) != {
                'release_id', 'release_source_set_sha256',
                'ros1_source_set_sha256', 'contract_sha256'}
            or not isinstance(source_contract, Mapping)
            or set(source_contract) != {
                'passed', 'source_set_sha256', 'contract_sha256',
                'architecture_blockers'}
            or source_contract.get('passed') is not True
            or source_contract.get('architecture_blockers') != []
            or source_contract.get('contract_sha256')
            != contract_record.get('sha256')
            or source_binding.get('contract_sha256')
            != contract_record.get('sha256')
            or source_binding.get('ros1_source_set_sha256')
            != source_contract.get('source_set_sha256')
            or not _lower_sha256(source_contract.get('source_set_sha256'))):
        _add_failure(failures, 'ros1_field_install_source_contract_invalid')
    source_binding_value = source_binding if isinstance(
        source_binding, Mapping) else {}
    source_contract_value = source_contract if isinstance(
        source_contract, Mapping) else {}
    if (canonical_binding_valid
            and (source_binding_value.get('ros1_source_set_sha256')
                 != canonical_source_binding.get('source_set_sha256')
                 or source_contract_value.get('source_set_sha256')
                 != canonical_source_binding.get('source_set_sha256')
                 or source_binding_value.get('contract_sha256')
                 != canonical_source_binding.get('contract_sha256')
                 or source_contract_value.get('contract_sha256')
                 != canonical_source_binding.get('contract_sha256'))):
        _add_failure(failures, ROS1_CANONICAL_BINDING_MISMATCH)
    if (not isinstance(release_binding, Mapping)
            or source_binding_value.get('release_id') != release_binding.get(
                'release_id')
            or source_binding_value.get('release_source_set_sha256')
            != release_binding.get('source_set_sha256')):
        _add_failure(failures, 'ros1_field_install_release_binding_mismatch')
    if (not isinstance(live_source_audit, Mapping)
            or live_source_audit.get('pass') is not True
            or live_source_audit.get('source_set_sha256')
            != source_contract_value.get('source_set_sha256')
            or live_source_audit.get('contract_sha256')
            != contract_record.get('sha256')):
        _add_failure(failures, ROS1_RUNTIME_ARCHITECTURE_BLOCKER)

    isolation_root = report.get('isolation_root')
    isolation_prefix = contract.get('install_policy', {}).get(
        'isolation_prefix') if isinstance(contract, Mapping) else None
    isolation_path = declared_isolation_path
    production_isolation = (
        isinstance(isolation_root, str)
        and isinstance(isolation_prefix, str)
        and isolation_root.replace('\\', '/').startswith(isolation_prefix)
        and '..' not in isolation_root.replace('\\', '/').split('/'))
    synthetic_isolation = (
        test_only_binding
        and allow_test_synthetic_binding
        and isinstance(path, Path)
        and isolation_path is not None
        and path.parent.parent.resolve() == isolation_path)
    if (isolation_path is None
            or _path_is_linklike(isolation_path)
            or not (production_isolation or synthetic_isolation)):
        _add_failure(failures, 'ros1_field_install_isolation_invalid')
    expected_commands = _isolated_catkin_argv(
        isolation_root if isinstance(isolation_root, str) else '')
    if report.get('commands') != expected_commands:
        _add_failure(failures, 'ros1_field_install_command_mismatch')
    if report.get('exit_codes') != contract.get(
            'install_policy', {}).get('required_exit_codes'):
        _add_failure(failures, 'ros1_field_install_exit_code_failure')
    if report.get('test_failures') != 0:
        _add_failure(failures, 'ros1_field_install_tests_failed')

    if not isinstance(path, Path):
        logs = {}
        log_identities = {}
    else:
        logs = report.get('logs')
        log_identities = {}
        if not isinstance(logs, Mapping) or set(logs) != {
                'build', 'install', 'test', 'test_result'}:
            _add_failure(failures, 'ros1_field_install_log_set_invalid')
            logs = {}
        for name, declaration in logs.items():
            identity = _evidence_file_identity(
                path, declaration, 'log:' + name, failures)
            if identity is not None and identity['size_bytes'] <= 0:
                _add_failure(failures, 'ros1_field_install_log_empty:' + name)
            if identity is not None:
                log_identities[name] = identity

    if (declared_isolation_path is not None
            and source_workspace is not None and isinstance(path, Path)):
        catkin_test_admission = _validate_ros1_catkin_test_results(
            declared_isolation_path, source_workspace, contract,
            report.get('catkin_test_results'),
            log_identities.get('test_result'), path, failures)
    else:
        _add_failure(failures, 'ros1_field_catkin_test_result_schema_invalid')
        catkin_test_admission = {
            'expected_test_count': 0, 'tests_run': 0, 'passed': 0,
            'failed': 0, 'errors': 0, 'skipped': 0,
            'artifact_identities': [], 'marker_count': 0}
    if (report.get('test_failures') !=
            catkin_test_admission.get('failed', 0)
            + catkin_test_admission.get('errors', 0)):
        _add_failure(failures, 'ros1_field_catkin_test_count_mismatch')

    model_bindings = report.get('model_bindings')
    expected_models = expected_model_hashes or {}
    required_classes = contract.get('model_manifest', {}).get(
        'required_classes', []) if isinstance(contract, Mapping) else []
    if not isinstance(model_bindings, Mapping) or set(model_bindings) != set(
            required_classes):
        _add_failure(failures, 'ros1_field_install_model_set_invalid')
        model_bindings = {}
    for label in required_classes:
        declaration = model_bindings.get(label)
        if (not isinstance(declaration, Mapping)
                or set(declaration) != {
                    'class_name', 'path', 'size_bytes', 'sha256'}
                or declaration.get('class_name') != label):
            _add_failure(failures, 'ros1_field_install_model_invalid:' + label)
            continue
        identity = _evidence_file_identity(
            path, declaration, 'model:' + label, failures) if path else None
        if (identity is None
                or identity.get('sha256') != expected_models.get(label)):
            _add_failure(
                failures,
                'ros1_field_install_model_hash_mismatch:' + label)

    required_roles = (
        _ros1_required_install_roles(contract, mode)
        if isinstance(contract, Mapping) and mode in interface_modes else {})
    role_sources = _ros1_role_source_paths(contract, mode) if isinstance(
        contract, Mapping) and mode in interface_modes else {}
    source_entries = live_source_audit.get(
        'source_entries', []) if isinstance(live_source_audit, Mapping) else []
    audited_sources = {
        item.get('path'): item.get('sha256')
        for item in source_entries if isinstance(item, Mapping)
    }
    artifacts = report.get('installed_artifacts')
    if not isinstance(artifacts, list):
        artifacts = []
        _add_failure(failures, 'ros1_field_install_artifact_inventory_invalid')
    by_role = {}
    canonical = []
    installed_resolved_paths = set()
    installed_identity_by_role = {}
    install_root = (
        declared_isolation_path / 'install'
        if declared_isolation_path is not None else None)
    live_package_root = (
        source_workspace / contract['package']['source_root']
        if source_workspace is not None else None)
    for item in artifacts:
        if (not isinstance(item, Mapping)
                or set(item) != {
                    'role', 'path', 'installed_relative_path', 'size_bytes',
                    'sha256', 'source_sha256', 'regular_file', 'linklike'}
                or not isinstance(item.get('role'), str)
                or item.get('role') in by_role):
            _add_failure(
                failures, 'ros1_field_install_artifact_inventory_invalid')
            continue
        role = item['role']
        by_role[role] = item
        identity = _evidence_file_identity(
            path, item, 'installed:' + role, failures) if path else None
        expected_installed_path = None
        if install_root is not None and role in required_roles:
            try:
                expected_installed_path = (
                    install_root / required_roles[role]).resolve(strict=True)
            except (OSError, RuntimeError):
                pass
        source_relative = role_sources.get(role)
        source_path = (
            live_package_root / source_relative
            if live_package_root is not None
            and isinstance(source_relative, str) else None)
        source_binding_valid = (
            item.get('source_sha256') == audited_sources.get(source_relative))
        content_valid = False
        if identity is not None and source_path is not None:
            installed_path = Path(identity['path'])
            if role.startswith('entry:'):
                try:
                    installed_text = installed_path.read_text(encoding='utf-8')
                    source_text = source_path.read_text(encoding='utf-8')
                    installed_lines = installed_text.splitlines(keepends=True)
                    source_lines = source_text.splitlines(keepends=True)
                    content_valid = (
                        installed_lines and source_lines
                        and installed_lines[0].startswith('#!')
                        and 'python' in installed_lines[0].lower()
                        and installed_lines[1:] == source_lines[1:]
                        and ast.dump(ast.parse(installed_text))
                        == ast.dump(ast.parse(source_text)))
                except (OSError, UnicodeError, SyntaxError, ValueError):
                    content_valid = False
            else:
                content_valid = (
                    item.get('source_sha256') == item.get('sha256'))
        if identity is not None:
            installed_identity_by_role[role] = identity
            if identity['path'] in installed_resolved_paths:
                _add_failure(
                    failures, 'ros1_field_install_artifact_path_reused')
            installed_resolved_paths.add(identity['path'])
        if (item.get('regular_file') is not True
                or item.get('linklike') is not False
                or identity is None
                or expected_installed_path is None
                or Path(identity['path']).resolve() != expected_installed_path
                or _regular_non_link_file_under(
                    Path(identity['path']), install_root) is None
                or not source_binding_valid or not content_valid):
            _add_failure(
                failures, 'ros1_field_install_regular_copy_invalid:' + role)
        canonical.append({
            'role': role,
            'installed_relative_path': item.get('installed_relative_path'),
            'size_bytes': item.get('size_bytes'),
            'sha256': item.get('sha256'),
        })
    if set(by_role) != set(required_roles):
        _add_failure(failures, 'ros1_field_install_artifact_role_set_invalid')
    for role, relative in required_roles.items():
        if by_role.get(role, {}).get('installed_relative_path') != relative:
            _add_failure(
                failures, 'ros1_field_install_layout_mismatch:' + role)
    canonical = sorted(canonical, key=lambda item: item['role'])
    if report.get('install_set_sha256') != _canonical_identity_set_sha256(
            canonical):
        _add_failure(failures, 'ros1_field_install_set_hash_mismatch')

    expected_installed_sets = {}
    if install_root is not None and isinstance(contract, Mapping):
        package_name = contract['package']['name']
        application_root = install_root / 'lib' / 'python3' / 'dist-packages'
        expected_installed_sets = {
            application_root / package_name: set(
                contract['required_python_modules']) | {'msg'},
            application_root / package_name / 'msg': {
                '__init__.py', '_ObjectDetection.py', '_PerceptionFrame.py',
                '_PerceptionTarget.py'},
            install_root / 'lib' / package_name: {
                Path(value).name
                for value in contract['required_entrypoints'].values()},
            install_root / 'share' / package_name / 'config': set(
                contract['required_config_files']),
            install_root / 'share' / package_name / 'fixtures': set(
                contract['required_fixture_files']),
            install_root / 'share' / package_name / 'launch': set(
                contract['required_launch_files']),
            install_root / 'share' / package_name / 'msg': {
                Path(value).name for value in contract['interface_modes'][
                    'native_ros1_messages']['required_files']},
        }
        for directory, expected_names in expected_installed_sets.items():
            try:
                resolved_directory = directory.resolve(strict=True)
                if (_path_is_linklike(resolved_directory)
                        or not resolved_directory.is_dir()):
                    raise OSError('invalid install directory')
                actual_names = {
                    child.name for child in resolved_directory.iterdir()
                    if child.is_file() or child.is_dir()}
            except (OSError, RuntimeError):
                actual_names = set()
            if actual_names != expected_names:
                _add_failure(
                    failures, 'ros1_field_install_actual_set_invalid:'
                    + str(directory.relative_to(install_root)).replace('\\', '/'))

    module_expectations = []
    if install_root is not None and isinstance(contract, Mapping):
        package_name = contract['package']['name']
        import_roles = {
            'package': ('python:__init__.py', package_name, None),
            'entry:dual_model_detector': (
                'python:dual_model_detector.py',
                package_name + '.dual_model_detector', None),
            'entry:perception_frame_adapter': (
                'python:ros1_adapter.py', package_name + '.ros1_adapter', None),
            'entry:perception_frame_collector': (
                'python:perception_frame_collector.py',
                package_name + '.perception_frame_collector', None),
            'entry:perception_readiness': (
                'python:perception_readiness.py',
                package_name + '.perception_readiness', None),
            'entry:rosbag1_rgbd_indexer': (
                'python:rosbag1_rgbd_indexer.py',
                package_name + '.rosbag1_rgbd_indexer', None),
            'entry:typed_raw_binding': (
                'python:typed_raw_binding.py',
                package_name + '.typed_raw_binding', None),
            'runtime:evidence_binding': (
                'python:evidence_binding.py',
                package_name + '.evidence_binding', None),
        }
        for label, (role, module_name, expected_class) in import_roles.items():
            item = installed_identity_by_role.get(role)
            if isinstance(item, Mapping):
                module_expectations.append({
                    'label': label, 'module': module_name,
                    'expected_class': expected_class,
                    'identity': {
                        key: item.get(key)
                        for key in ('path', 'size_bytes', 'sha256')},
                })
        generated_root = (
            declared_isolation_path / contract['install_policy'][
                'application_root_relative'] / package_name / 'msg')
        generated_specs = [
            ('generated_message_package', package_name + '.msg',
             generated_root / '__init__.py', None),
            ('generated_message:ObjectDetection',
             package_name + '.msg._ObjectDetection',
             generated_root / '_ObjectDetection.py', 'ObjectDetection'),
            ('generated_message:PerceptionFrame',
             package_name + '.msg._PerceptionFrame',
             generated_root / '_PerceptionFrame.py', 'PerceptionFrame'),
            ('generated_message:PerceptionTarget',
             package_name + '.msg._PerceptionTarget',
             generated_root / '_PerceptionTarget.py', 'PerceptionTarget'),
        ]
        for label, module_name, module_path, expected_class in generated_specs:
            regular_path = _regular_non_link_file_under(
                module_path, generated_root)
            if regular_path is None:
                continue
            module_expectations.append({
                'label': label, 'module': module_name,
                'expected_class': expected_class,
                'identity': {
                    'path': str(regular_path),
                    'size_bytes': regular_path.stat().st_size,
                    'sha256': sha256_file(regular_path),
                },
            })
    if (declared_isolation_path is not None
            and len(dependency_probe_records) == len(expected_by_distribution)
            and len(module_expectations) == 12):
        fresh_import_probe = _run_ros1_fresh_import_probe(
            declared_isolation_path, contract, dependency_probe_records,
            module_expectations, failures)
    else:
        _add_failure(failures, 'ros1_field_fresh_import_probe_invalid')
        fresh_import_probe = {
            'validated_pass': False,
            'failures': ['ros1_field_fresh_import_probe_invalid']}

    unique_failures = sorted(set(failures))
    architecture_blockers = []
    if ROS1_RUNTIME_ARCHITECTURE_BLOCKER in unique_failures:
        architecture_blockers.append(ROS1_RUNTIME_ARCHITECTURE_BLOCKER)
    evidence_missing = 'ros1_field_install_evidence_missing' in unique_failures
    field_evidence_blockers = []
    build_install_blockers = []
    if unique_failures:
        field_evidence_blockers.append(
            ROS1_FIELD_INSTALL_EVIDENCE_MISSING_BLOCKER
            if evidence_missing
            else ROS1_FIELD_INSTALL_EVIDENCE_NOT_VALIDATED_BLOCKER)
        build_install_blockers.append(
            ROS1_BUILD_INSTALL_NOT_VERIFIED_BLOCKER)
    return {
        'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
        'scope': 'field_delivery',
        'required_for_delivery': True,
        'claimed_result': report.get('result'),
        'validated_pass': not unique_failures,
        'contract_path': contract_record.get('path'),
        'contract_sha256': contract_record.get('sha256'),
        'architecture_blockers': architecture_blockers,
        'build_install_blockers': build_install_blockers,
        'field_evidence_blockers': field_evidence_blockers,
        'workspace_root': report.get('workspace_root'),
        'source_contract_pass': (
            isinstance(live_source_audit, Mapping)
            and live_source_audit.get('pass') is True),
        'source_set_sha256': (
            live_source_audit.get('source_set_sha256')
            if isinstance(live_source_audit, Mapping) else None),
        'canonical_source_binding_valid': canonical_binding_valid,
        'canonical_runtime_complete': canonical_runtime_complete,
        'test_only_synthetic_binding': test_only_binding,
        'canonical_source_binding_sha256': (
            canonical_source_binding.get('binding_sha256')
            if canonical_binding_valid else None),
        'expected_ros1_source_set_sha256': (
            canonical_source_binding.get('source_set_sha256')
            if canonical_binding_valid else None),
        'expected_ros1_contract_sha256': (
            canonical_source_binding.get('contract_sha256')
            if canonical_binding_valid else None),
        'installed_artifact_count': len(artifacts),
        'runtime_dependency_count': len(inventory_by_distribution),
        'runtime_dependency_identities': runtime_dependency_identities,
        'catkin_test_admission': catkin_test_admission,
        'fresh_import_probe': fresh_import_probe,
        'actual_install_set_directory_count': len(expected_installed_sets),
        'failures': unique_failures,
    }


def _resolve_path(bundle_path: Path, value) -> Optional[Path]:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = bundle_path.parent / candidate
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _add_failure(failures: List[str], code: str) -> None:
    if code not in failures:
        failures.append(code)


def _formal_raw_inspection_admission(
        scene: str, inspection: Mapping, failures: List[str]) -> Mapping:
    """Reject diagnostic/shared evidence before four-scene aggregation.

    Formal admission is an exact positive contract.  Missing, null, stringly
    typed, diagnostic, shared, or denominator-excluded markers all fail closed
    and cannot be overridden by frame counts or later artifact bindings.
    """
    if not isinstance(inspection, Mapping):
        return {
            'admitted_to_formal_scene': False,
            'exclusion_reasons': ['inspection_not_mapping'],
        }
    exclusion_reasons = []
    for field, expected_value in FORMAL_RAW_INSPECTION_POLICY.items():
        actual_value = inspection.get(field)
        mismatch = (
            actual_value is not expected_value
            if isinstance(expected_value, bool)
            else actual_value != expected_value)
        if mismatch:
            exclusion_reasons.append(field)
    if exclusion_reasons:
        _add_failure(failures, 'raw_capture_formal_policy_invalid:' + scene)
    if inspection.get('formal_acceptance') is False:
        _add_failure(failures, 'raw_capture_non_formal:' + scene)
    if inspection.get('shared_graph') is True:
        _add_failure(failures, 'raw_capture_shared_graph:' + scene)
    if inspection.get('mixed_tf') is True:
        _add_failure(failures, 'raw_capture_mixed_tf:' + scene)
    if inspection.get('not_in_four_scene_denominator') is True:
        _add_failure(
            failures, 'raw_capture_excluded_from_scene_denominator:' + scene)
    if (inspection.get('inspection_scope') != 'formal_scene_raw_capture'
            or inspection.get('report_kind')
            != 'formal_rgbd_raw_capture_index'):
        _add_failure(failures, 'raw_capture_diagnostic_scope:' + scene)
    return {
        'formal_acceptance': inspection.get('formal_acceptance'),
        'shared_graph': inspection.get('shared_graph'),
        'mixed_tf': inspection.get('mixed_tf'),
        'not_in_four_scene_denominator': inspection.get(
            'not_in_four_scene_denominator'),
        'report_kind': inspection.get('report_kind'),
        'inspection_scope': inspection.get('inspection_scope'),
        'admitted_to_formal_scene': not exclusion_reasons,
        'exclusion_reasons': exclusion_reasons,
    }


def _artifact(
        bundle_path: Path, declaration, kind: str,
        failures: List[str], bindings: List[Mapping],
        seen_paths: Dict[str, str], required: bool = True) -> Optional[Path]:
    if not isinstance(declaration, Mapping):
        if required:
            _add_failure(failures, 'missing_artifact:' + kind)
        return None
    path = _resolve_path(bundle_path, declaration.get('path'))
    if path is None or not path.is_file():
        _add_failure(failures, 'artifact_missing:' + kind)
        return None
    resolved = str(path)
    previous = seen_paths.get(resolved)
    if previous is not None and previous != kind:
        _add_failure(failures, 'duplicate_artifact_path')
    else:
        seen_paths[resolved] = kind
    actual_size = path.stat().st_size
    actual_sha = sha256_file(path)
    expected_size = declaration.get('size_bytes')
    expected_sha = declaration.get('sha256')
    if (not isinstance(expected_size, int) or isinstance(expected_size, bool)
            or expected_size != actual_size):
        _add_failure(failures, 'artifact_size_mismatch:' + kind)
    if (not isinstance(expected_sha, str)
            or expected_sha.lower() != actual_sha):
        _add_failure(failures, 'artifact_sha256_mismatch:' + kind)
    bindings.append({
        'kind': kind,
        'path': resolved,
        'size_bytes': actual_size,
        'sha256': actual_sha,
        'declared_size_bytes': expected_size,
        'declared_sha256': expected_sha,
    })
    return path


def _artifact_identity_from_declaration(
        bundle_path: Path, declaration) -> Optional[Mapping]:
    if not isinstance(declaration, Mapping):
        return None
    path = _resolve_path(bundle_path, declaration.get('path'))
    if path is None or not path.is_file():
        return None
    return {
        'path': str(path),
        'size_bytes': path.stat().st_size,
        'sha256': sha256_file(path),
    }


def _load_json(path: Optional[Path], kind: str, failures: List[str]):
    if path is None:
        return None
    try:
        value = _strict_json_loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        _add_failure(failures, 'invalid_json_artifact:' + kind)
        return None
    if not isinstance(value, Mapping):
        _add_failure(failures, 'invalid_json_artifact:' + kind)
        return None
    return value


def _reject_nonfinite_json_constant(value):
    raise ValueError('non-finite JSON number is not permitted: ' + value)


def _reject_duplicate_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + str(key))
        result[key] = value
    return result


def _strict_json_loads(value: str):
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_json_object,
        parse_constant=_reject_nonfinite_json_constant)


def _exact_json_value(actual, expected) -> bool:
    """Compare JSON values without Python bool/int equality coercion."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (set(actual) == set(expected)
                and all(
                    _exact_json_value(actual[key], value)
                    for key, value in expected.items()))
    if isinstance(expected, list):
        return (len(actual) == len(expected)
                and all(
                    _exact_json_value(left, right)
                    for left, right in zip(actual, expected)))
    return actual == expected


def _strict_keys(
        value, expected: Sequence[str], failure_code: str,
        failures: List[str]) -> bool:
    if not isinstance(value, Mapping) or set(value) != set(expected):
        _add_failure(failures, failure_code)
        return False
    return True


def _contains_forbidden_control_claim(value) -> bool:
    """Reject nested evidence that tries to authorize or describe controls."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered == 'forbidden_control_topics':
                # This exact collector policy key is a required deny-list, not
                # a publisher/control declaration.
                continue
            if lowered in {
                    'control_topic', 'control_topics',
                    'command_topic', 'command_topics',
                    'publisher', 'publishers',
                    'publishes_topic', 'publishes_topics'}:
                return True
            if lowered in {
                    'authorizes_motion', 'publishes_ros_messages',
                    'frame_id_override'}:
                if lowered == 'frame_id_override' or item is not False:
                    return True
            if lowered == 'topic' and isinstance(item, str):
                message_type = value.get('message_type', value.get('type', ''))
                if is_control_topic(item, message_type):
                    return True
            if lowered in {'message_type', 'type'} and isinstance(item, str):
                if is_control_topic(value.get('topic', ''), item):
                    return True
            if _contains_forbidden_control_claim(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_control_claim(item) for item in value)
    return False


def _raw_stream_unpaired_report(
        topics, unmatched_by_stream, total_stream_messages,
        total_unpaired, total_unpaired_rate) -> Tuple[Mapping, bool, bool]:
    """Validate four-stream unmatched accounting and the per-stream gate."""
    stream_counts = {}
    topics_valid = isinstance(topics, list)
    if topics_valid:
        for item in topics:
            if not isinstance(item, Mapping):
                topics_valid = False
                continue
            role = item.get('role')
            if role not in REQUIRED_STREAMS:
                continue
            count = item.get('message_count')
            if (role in stream_counts or not isinstance(count, int)
                    or isinstance(count, bool) or count <= 0):
                topics_valid = False
                continue
            stream_counts[role] = count
    if set(stream_counts) != set(REQUIRED_STREAMS):
        topics_valid = False
    unmatched_valid = (
        isinstance(unmatched_by_stream, Mapping)
        and set(unmatched_by_stream) == set(REQUIRED_STREAMS)
        and all(isinstance(value, int) and not isinstance(value, bool)
                and value >= 0 for value in unmatched_by_stream.values()))
    rates = {}
    if topics_valid and unmatched_valid:
        for stream in REQUIRED_STREAMS:
            unmatched = unmatched_by_stream[stream]
            count = stream_counts[stream]
            if unmatched > count:
                unmatched_valid = False
                break
            rates[stream] = unmatched / count
    derived_total_messages = sum(stream_counts.values()) if topics_valid else None
    derived_total_unpaired = (
        sum(unmatched_by_stream.values()) if unmatched_valid else None)
    accounting_valid = (
        topics_valid and unmatched_valid
        and isinstance(total_stream_messages, int)
        and not isinstance(total_stream_messages, bool)
        and total_stream_messages == derived_total_messages
        and isinstance(total_unpaired, int)
        and not isinstance(total_unpaired, bool)
        and total_unpaired == derived_total_unpaired
        and 0 <= total_unpaired <= total_stream_messages
        and _finite(total_unpaired_rate, 0.0, 1.0)
        and abs(total_unpaired_rate
                - total_unpaired / total_stream_messages) <= 1e-9)
    threshold_exceeded = (
        accounting_valid
        and any(rate > MAX_RAW_STREAM_UNPAIRED_RATE for rate in rates.values()))
    return {
        'stream_message_count_by_stream': (
            dict(stream_counts) if topics_valid else {}),
        'unmatched_message_count_by_stream': (
            dict(unmatched_by_stream) if unmatched_valid else {}),
        'unpaired_rate_by_stream': rates if accounting_valid else {},
        'total_stream_message_count': total_stream_messages,
        'total_unpaired_message_count': total_unpaired,
        'total_unpaired_rate': total_unpaired_rate,
    }, accounting_valid, threshold_exceeded


def _typed_raw_unpaired_report(
        typed_count, raw_count, unpaired_typed, unpaired_raw,
        frame_bindings, declared_rate) -> Tuple[Mapping, bool, bool]:
    """Validate typed/raw intersection accounting and its two denominators."""
    counts_valid = (
        isinstance(typed_count, int) and not isinstance(typed_count, bool)
        and typed_count > 0
        and isinstance(raw_count, int) and not isinstance(raw_count, bool)
        and raw_count > 0
        and isinstance(unpaired_typed, int)
        and not isinstance(unpaired_typed, bool)
        and 0 <= unpaired_typed <= typed_count
        and isinstance(unpaired_raw, int)
        and not isinstance(unpaired_raw, bool)
        and 0 <= unpaired_raw <= raw_count
        and isinstance(frame_bindings, list))
    if counts_valid:
        paired_count = len(frame_bindings)
        typed_rate = unpaired_typed / typed_count
        raw_rate = unpaired_raw / raw_count
        derived_rate = max(typed_rate, raw_rate)
        accounting_valid = (
            paired_count == typed_count - unpaired_typed
            and paired_count == raw_count - unpaired_raw
            and _finite(declared_rate, 0.0, 1.0)
            and abs(declared_rate - derived_rate) <= 1e-9)
    else:
        paired_count = None
        typed_rate = None
        raw_rate = None
        derived_rate = None
        accounting_valid = False
    threshold_exceeded = (
        accounting_valid
        and (typed_rate > MAX_TYPED_RAW_UNPAIRED_RATE
             or raw_rate > MAX_TYPED_RAW_UNPAIRED_RATE))
    return {
        'typed_frame_count': typed_count,
        'raw_bundle_count': raw_count,
        'paired_count': paired_count,
        'unpaired_typed_count': unpaired_typed,
        'unpaired_raw_bundle_count': unpaired_raw,
        'unpaired_typed_rate': typed_rate,
        'unpaired_raw_bundle_rate': raw_rate,
        'unpaired_rate': derived_rate,
    }, accounting_valid, threshold_exceeded


def _release_binding(payload: Mapping, failures: List[str]) -> Mapping:
    binding = payload.get('release_binding')
    if (not isinstance(binding, Mapping)
            or set(binding) != {
                'release_id', 'source_manifest_artifact_sha256',
                'source_set_sha256',
                'manifest_generated_at_unix_sec'}
            or not valid_release_id(binding.get('release_id'))
            or not isinstance(binding.get(
                'source_manifest_artifact_sha256'), str)
            or len(binding.get('source_manifest_artifact_sha256')) != 64
            or not isinstance(binding.get('source_set_sha256'), str)
            or len(binding.get('source_set_sha256')) != 64
            or not _finite(binding.get('manifest_generated_at_unix_sec'), 0.0)):
        _add_failure(failures, 'release_binding_invalid')
        return {}
    return dict(binding)


def _check_software(
        bundle_path: Path, payload: Mapping, failures: List[str],
        bindings: List[Mapping], seen_paths: Dict[str, str],
        expected_model_hashes: Mapping = None,
        now_unix_sec: float = None, release_binding: Mapping = None) -> Mapping:
    binding = payload.get('software_binding')
    if not isinstance(binding, Mapping):
        _add_failure(failures, 'missing_software_binding')
        return {'models': 0, 'sources': 0}
    models = binding.get('models')
    if not isinstance(models, Mapping):
        _add_failure(failures, 'missing_model_binding')
        models = {}
    model_hashes = {}
    model_filenames = {}
    for label in ('plastic_bottle', 'trash_bin'):
        declaration = models.get(label)
        _artifact(
            bundle_path, declaration, 'model:' + label,
            failures, bindings, seen_paths)
        if isinstance(declaration, Mapping):
            model_hashes[label] = declaration.get('sha256')
            model_filenames[label] = Path(str(
                declaration.get('path', ''))).name
    if model_filenames != {
            'plastic_bottle': 'nongfu_yolov8n_best.pt',
            'trash_bin': 'trash_bin_yolov8n_best.pt'}:
        _add_failure(failures, 'model_filename_binding_mismatch')
    expected_hashes = (EXPECTED_MODEL_SHA256 if expected_model_hashes is None
                       else expected_model_hashes)
    for label in ('plastic_bottle', 'trash_bin'):
        if model_hashes.get(label) != expected_hashes.get(label):
            _add_failure(failures, 'model_hash_mismatch:' + label)
    sources = binding.get('sources')
    if not isinstance(sources, list) or not sources:
        _add_failure(failures, 'missing_source_binding')
        sources = []
    source_names = []
    source_paths = {}
    for index, declaration in enumerate(sources):
        source_path = _artifact(
            bundle_path, declaration, 'source:{}'.format(index),
            failures, bindings, seen_paths)
        if isinstance(declaration, Mapping):
            basename = Path(str(declaration.get('path', ''))).name
            source_names.append(basename)
            source_paths[basename] = source_path
    if (len(source_names) != len(REQUIRED_SOURCE_BASENAMES)
            or len(set(source_names)) != len(source_names)
            or set(source_names) != set(REQUIRED_SOURCE_BASENAMES)):
        _add_failure(failures, 'source_binding_scope_mismatch')
    current_source_root = Path(__file__).resolve().parent
    for basename in REQUIRED_SOURCE_BASENAMES:
        declared_path = source_paths.get(basename)
        current_path = current_source_root / basename
        if not current_path.is_file():
            _add_failure(failures, 'current_source_missing:' + basename)
        elif (declared_path is None or not declared_path.is_file()
              or sha256_file(declared_path) != sha256_file(current_path)):
            _add_failure(failures, 'source_hash_mismatch:' + basename)
    runtime = binding.get('runtime_preflight')
    runtime_path = _artifact(
        bundle_path, runtime, 'runtime_preflight', failures,
        bindings, seen_paths)
    runtime_report = _load_json(
        runtime_path, 'runtime_preflight', failures)
    if now_unix_sec is not None:
        _check_report_freshness(
            runtime_report, 'generated_at_unix_sec', now_unix_sec,
            MAX_SOFTWARE_PROOF_AGE_SEC, 'runtime_preflight_stale', failures)
    runtime_checks = _hardware_check_map(runtime_report) if isinstance(
        runtime_report, Mapping) else {}
    platform = runtime_report.get('platform') if isinstance(
        runtime_report, Mapping) else None
    python_version = platform.get('python') if isinstance(
        platform, Mapping) else None
    machine = platform.get('machine') if isinstance(platform, Mapping) else None
    ros_distro = platform.get('ros_distro') if isinstance(
        platform, Mapping) else None
    required_runtime_checks = (
        'python_module_numpy', 'python_module_cv2', 'python_module_torch',
        'python_module_ultralytics', 'ultralytics_exact_version',
        'source_hashes_match')
    expected_model_checks = {
        'plastic_bottle': 'model_' + model_filenames.get(
            'plastic_bottle', ''),
        'trash_bin': 'model_' + model_filenames.get('trash_bin', ''),
    }
    if (not isinstance(runtime_report, Mapping)
            or runtime_report.get('schema_version') != 1
            or runtime_report.get('passed') is not True
            or runtime_report.get('mode') != (
                'filesystem_only_no_ros_graph_no_hardware')
            or python_version != '3.8.10'
            or machine != 'aarch64'
            or ros_distro != 'foxy'
            or any(runtime_checks.get(name, {}).get('status') != 'PASS'
                   for name in required_runtime_checks)
            or any(
                runtime_checks.get(check_name, {}).get('status') != 'PASS'
                or runtime_checks.get(check_name, {}).get('measured')
                != model_hashes.get(label)
                for label, check_name in expected_model_checks.items())
            or runtime_checks.get(
                'models_load_and_labels_match', {}).get('status') != 'PASS'):
        _add_failure(failures, 'runtime_preflight_not_passed')
    runtime_generated = runtime_report.get('generated_at_unix_sec') if isinstance(
        runtime_report, Mapping) else None
    expected_models = {
        label: model_hashes.get(label)
        for label in ('plastic_bottle', 'trash_bin')}
    if (not isinstance(release_binding, Mapping)
            or not isinstance(runtime_report, Mapping)
            or runtime_report.get('release_id') != release_binding.get(
                'release_id')
            or runtime_report.get('source_manifest_artifact_sha256')
            != release_binding.get('source_manifest_artifact_sha256')
            or runtime_report.get('source_set_sha256') != release_binding.get(
                'source_set_sha256')
            or runtime_report.get('model_sha256') != expected_models
            or not _finite(runtime_generated, release_binding.get(
                'manifest_generated_at_unix_sec'))):
        _add_failure(failures, 'runtime_release_binding_mismatch')
    return {
        'models': len(models),
        'sources': len(sources),
        'model_sha256': expected_models,
        'runtime_preflight_passed': (
            isinstance(runtime_report, Mapping)
            and runtime_report.get('passed') is True),
    }


def _check_report_freshness(
        report: Mapping, field, now_unix_sec: float,
        max_age_sec: float, failure_code: str,
        failures: List[str]) -> None:
    fields = (field,) if isinstance(field, str) else tuple(field)
    generated = None
    if isinstance(report, Mapping):
        for name in fields:
            if report.get(name) is not None:
                generated = report.get(name)
                break
    if (not _finite(generated, 0.0)
            or generated > now_unix_sec + MAX_FUTURE_SKEW_SEC
            or now_unix_sec - generated > max_age_sec):
        _add_failure(failures, failure_code)


def _check_ros_build(
        bundle_path: Path, declaration, failures: List[str],
        bindings: List[Mapping], seen_paths: Dict[str, str],
        now_unix_sec: float = None, release_binding: Mapping = None) -> Mapping:
    failures_before = set(failures)
    path = _artifact(
        bundle_path, declaration, 'ros_build_validation', failures,
        bindings, seen_paths)
    report = _load_json(path, 'ros_build_validation', failures)
    if report is None:
        _add_failure(failures, 'ros_build_validation_not_passed')
        return {
            'gate_id': ROS2_MIGRATION_INSTALL_GATE_ID,
            'scope': 'offline_migration',
            'required_for_field_delivery': False,
            'substitutes_for_ros1_field': False,
            'result': None,
            'claimed_result': None,
            'validated_pass': False,
            'isolated_paths_valid': False,
            'isolated_non_symlink_install': False,
            'legacy_field_deprecated': True,
        }
    if now_unix_sec is not None:
        _check_report_freshness(
            report, 'generated_at_unix_sec', now_unix_sec,
            MAX_SOFTWARE_PROOF_AGE_SEC, 'ros_build_validation_stale', failures)
    if (report.get('schema_version') != 2
            or report.get('result') != 'PASS'
            or report.get('packages') != [
                'limo_cleanup_interfaces', 'limo_cleanup_perception']
            or report.get('exit_codes') != {
                'build': 0, 'test': 0, 'test_result': 0}
            or report.get('test_failures') != 0):
        _add_failure(failures, 'ros_build_validation_not_passed')
    platform = report.get('platform')
    commands = report.get('commands')
    logs = report.get('logs')
    source_manifest = report.get('source_manifest')
    source_manifest_artifact = report.get('source_manifest_artifact')
    workspace_root = report.get('workspace_root')
    isolation_root = report.get('isolation_root')
    cwd = report.get('cwd')
    try:
        workspace_path = Path(workspace_root).resolve(strict=True)
        isolation_posix = str(isolation_root).replace('\\', '/')
        isolation_valid = (
            isolation_posix.startswith('/tmp/limo_v2_colcon_')
            and '..' not in isolation_posix.split('/')
            and Path(cwd).resolve(strict=True) == workspace_path)
    except (TypeError, OSError, RuntimeError):
        workspace_path = None
        isolation_valid = False
    required_build_names = _required_build_source_names()
    if (not isinstance(platform, Mapping)
            or platform.get('ros_distro') != 'foxy'
            or platform.get('python') != '3.8.10'
            or platform.get('machine') != 'aarch64'
            or not isinstance(commands, Mapping)
            or not all(isinstance(commands.get(name), list)
                       and all(isinstance(token, str) and token
                               for token in commands.get(name)) for name in (
                           'build_argv', 'test_argv', 'test_result_argv'))
            or not isolation_valid
            or not isinstance(logs, Mapping)
            or set(logs) != {'build', 'test', 'test_result'}
            or not isinstance(source_manifest, Mapping)
            or not isinstance(source_manifest_artifact, Mapping)
            or source_manifest.get('required_source_names') != list(
                required_build_names)
            or not isinstance(source_manifest.get('source_set_sha256'), str)
            or len(source_manifest.get('source_set_sha256')) != 64):
        _add_failure(failures, 'ros_build_provenance_incomplete')
    source_manifest_path = _artifact(
        bundle_path, source_manifest_artifact,
        'ros_build_source_manifest_artifact', failures, bindings,
        seen_paths)
    source_manifest_file_value = _load_json(
        source_manifest_path, 'ros_build_source_manifest_artifact', failures)
    expected_commands = _isolated_colcon_argv(
        str(workspace_path) if workspace_path is not None else '',
        str(isolation_root) if isinstance(isolation_root, str) else '')
    if commands != expected_commands:
        _add_failure(failures, 'ros_build_command_mismatch')
    for name, item in (logs.items() if isinstance(logs, Mapping) else []):
        _artifact(
            bundle_path, item, 'ros_build_log:' + name,
            failures, bindings, seen_paths)
        log_path = _resolve_path(bundle_path, item.get('path')) if isinstance(
            item, Mapping) else None
        if log_path is None or log_path.stat().st_size <= 0:
            _add_failure(failures, 'ros_build_log_empty:' + name)
    try:
        canonical_manifest = canonical_file_manifest(
            source_manifest.get('entries') if isinstance(
                source_manifest, Mapping) else None,
            workspace_path)
    except (OSError, RuntimeError, ValueError):
        canonical_manifest = None
        _add_failure(failures, 'ros_build_source_manifest_invalid')
    if (not isinstance(source_manifest_file_value, Mapping)
            or source_manifest_file_value.get('schema_version') != 1
            or source_manifest_file_value.get('release_id') != report.get(
                'release_id')
            or source_manifest_file_value.get('read_only') is not True
            or source_manifest_file_value.get('authorizes_motion') is not False
            or source_manifest_file_value.get(
                'publishes_ros_messages') is not False
            or source_manifest_file_value.get(
                'scope') != 'complete_interfaces_and_perception_package_inputs'
            or source_manifest_file_value.get('required_source_names')
            != list(required_build_names)
            or not isinstance(source_manifest, Mapping)
            or source_manifest_file_value.get('entries')
            != (source_manifest.get('entries') if isinstance(
                source_manifest, Mapping) else None)
            or source_manifest_file_value.get('source_set_sha256')
            != (source_manifest.get('source_set_sha256') if isinstance(
                source_manifest, Mapping) else None)
            or source_manifest_artifact.get('sha256')
            != release_binding.get('source_manifest_artifact_sha256')):
        _add_failure(failures, 'ros_build_source_manifest_artifact_invalid')
    if (canonical_manifest is None
            or not isinstance(source_manifest, Mapping)
            or canonical_manifest.get('sha256') != source_manifest.get(
                'source_set_sha256')
            or [item['name'] for item in canonical_manifest.get(
                'entries', [])] != list(required_build_names)):
        _add_failure(failures, 'ros_build_source_manifest_invalid')
    generated = report.get('generated_at_unix_sec')
    if (not isinstance(release_binding, Mapping)
            or report.get('release_id') != release_binding.get('release_id')
            or not isinstance(source_manifest, Mapping)
            or source_manifest.get('source_set_sha256') != release_binding.get(
                'source_set_sha256')
            or not _finite(generated, release_binding.get(
                'manifest_generated_at_unix_sec'))):
        _add_failure(failures, 'ros_build_release_binding_mismatch')
    if report.get('nodes_started') is not False:
        _add_failure(failures, 'ros_build_started_nodes')
    gate_failures = sorted(set(failures) - failures_before)
    return {
        'gate_id': ROS2_MIGRATION_INSTALL_GATE_ID,
        'scope': 'offline_migration',
        'required_for_field_delivery': False,
        'substitutes_for_ros1_field': False,
        'result': report.get('result'),
        'claimed_result': report.get('result'),
        'validated_pass': not gate_failures,
        'isolated_paths_valid': isolation_valid,
        'isolated_non_symlink_install': False,
        'legacy_field_deprecated': True,
        'failures': gate_failures,
    }


def _check_ros1_field_install(
        bundle_path: Path, declaration, failures: List[str],
        bindings: List[Mapping], seen_paths: Dict[str, str],
        now_unix_sec: float, release_binding: Mapping,
        expected_model_hashes: Mapping,
        canonical_source_binding: Mapping,
        canonical_source_audit: Mapping = None,
        allow_test_synthetic_binding: bool = False) -> Mapping:
    """Validate the independent ROS1/Noetic field-install admission gate."""
    path = _artifact(
        bundle_path, declaration, 'ros1_field_install_validation', failures,
        bindings, seen_paths)
    if path is None:
        _add_failure(failures, 'ros1_field_install_validation_not_passed')
        source_implementation_pass = (
            isinstance(canonical_source_audit, Mapping)
            and canonical_source_audit.get('pass') is True
            and isinstance(canonical_source_binding, Mapping)
            and canonical_source_binding.get('test_only') is False
            and canonical_source_binding.get('source_contract_pass') is True
            and canonical_source_binding.get('indexer_only_detected') is False
            and canonical_source_binding.get('architecture_blockers') == [])
        return {
            'gate_id': ROS1_FIELD_INSTALL_GATE_ID,
            'scope': 'field_delivery',
            'required_for_delivery': True,
            'claimed_result': None,
            'validated_pass': False,
            'source_implementation_pass': source_implementation_pass,
            'architecture_blockers': (
                [] if source_implementation_pass
                else [ROS1_RUNTIME_ARCHITECTURE_BLOCKER]),
            'build_install_blockers': [
                ROS1_BUILD_INSTALL_NOT_VERIFIED_BLOCKER],
            'field_evidence_blockers': [
                ROS1_FIELD_INSTALL_EVIDENCE_MISSING_BLOCKER],
            'failures': ['ros1_field_install_evidence_missing'],
        }
    validation = validate_ros1_noetic_field_install_evidence(
        path, release_binding=release_binding,
        expected_model_hashes=expected_model_hashes,
        now_unix_sec=now_unix_sec,
        source_audit=canonical_source_audit,
        canonical_source_binding=canonical_source_binding,
        allow_test_synthetic_binding=allow_test_synthetic_binding)
    for code in validation.get('failures', []):
        _add_failure(failures, code)
    if validation.get('validated_pass') is not True:
        _add_failure(failures, 'ros1_field_install_validation_not_passed')
    return validation


def _hardware_check_map(report: Mapping) -> Dict[str, Mapping]:
    checks = report.get('checks')
    if not isinstance(checks, list):
        return {}
    result = {}
    for item in checks:
        if (isinstance(item, Mapping) and isinstance(item.get('name'), str)
                and item['name'] not in result):
            result[item['name']] = item
        elif isinstance(item, Mapping) and isinstance(item.get('name'), str):
            result[item['name']] = {
                'name': item['name'], 'status': 'DUPLICATE'}
    return result


def _check_hardware(
        bundle_path: Path, declaration, failures: List[str],
        bindings: List[Mapping], seen_paths: Dict[str, str],
        now_unix_sec: float = None) -> Mapping:
    path = _artifact(
        bundle_path, declaration, 'hardware_readiness', failures,
        bindings, seen_paths)
    report = _load_json(path, 'hardware_readiness', failures)
    if report is None:
        _add_failure(failures, 'hardware_readiness_not_passed')
        return {'result': None, 'required_checks_passed': 0}
    if report.get('schema_version') != 1:
        _add_failure(failures, 'invalid_hardware_schema')
    if now_unix_sec is not None:
        _check_report_freshness(
            report, ('generated_at_unix_sec', 'generated_at_unix'), now_unix_sec,
            MAX_FIELD_EVIDENCE_AGE_SEC, 'hardware_readiness_stale', failures)
    if report.get('read_only') is not True or report.get('result') != 'PASS':
        _add_failure(failures, 'hardware_readiness_not_passed')
    checks = _hardware_check_map(report)
    for name in REQUIRED_HARDWARE_CHECKS:
        item = checks.get(name)
        if not isinstance(item, Mapping):
            _add_failure(
                failures, 'required_readiness_check_missing:' + name)
        elif item.get('status') != 'PASS':
            _add_failure(failures, 'required_readiness_check_failed:' + name)
    for name in ('no_actuation_publishers', 'no_actuation_subscribers'):
        item = checks.get(name)
        active_key = ('active_publishers' if name.endswith('publishers')
                      else 'active_subscribers')
        active = item.get('measured', {}).get(active_key) if isinstance(
            item, Mapping) and isinstance(item.get('measured'), Mapping) else None
        if item is None or item.get('status') != 'PASS' or active != {}:
            _add_failure(failures, 'actuation_safety_not_proven')
    tf_check = checks.get('base_to_camera_tf')
    tf_measured = tf_check.get('measured') if isinstance(
        tf_check, Mapping) else None
    if (not isinstance(tf_measured, Mapping)
            or tf_measured.get('parent') != EXPECTED_BASE_FRAME
            or not isinstance(tf_measured.get('child'), str)
            or not tf_measured.get('child')):
        _add_failure(failures, 'hardware_tf_measurement_missing')
    extrinsics = checks.get('camera_extrinsics_match_measurement')
    if (not isinstance(extrinsics, Mapping)
            or not isinstance(extrinsics.get('measured'), Mapping)):
        _add_failure(failures, 'hardware_extrinsics_measurement_missing')
    return {
        'result': report.get('result'),
        'required_checks_passed': sum(
            checks.get(name, {}).get('status') == 'PASS'
            for name in REQUIRED_HARDWARE_CHECKS),
        'required_checks': len(REQUIRED_HARDWARE_CHECKS),
    }


def _hardware_tf_binding(
        hardware_path: Optional[Path], scene_reports: Mapping,
        failures: List[str]) -> None:
    if hardware_path is None:
        return
    try:
        report = json.loads(hardware_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    checks = _hardware_check_map(report) if isinstance(report, Mapping) else {}
    item = checks.get('base_to_camera_tf')
    measured = item.get('measured') if isinstance(item, Mapping) else None
    child = measured.get('child') if isinstance(measured, Mapping) else None
    hardware_translation = measured.get('translation_m') if isinstance(
        measured, Mapping) else None
    hardware_rpy = measured.get('rpy_rad') if isinstance(
        measured, Mapping) else None
    for scene, scene_report in scene_reports.items():
        tf_report = scene_report.get('tf') if isinstance(
            scene_report, Mapping) else None
        if (isinstance(tf_report, Mapping) and tf_report.get('child')
                and child != tf_report.get('child')):
            _add_failure(failures, 'hardware_tf_scene_mismatch:' + scene)
        scene_translation = tf_report.get('translation_m') if isinstance(
            tf_report, Mapping) else None
        if (isinstance(scene_translation, list)
                and isinstance(hardware_translation, list)
                and len(scene_translation) == len(hardware_translation) == 3
                and any(abs(first - second) > 1e-6 for first, second in zip(
                    scene_translation, hardware_translation))):
            _add_failure(failures, 'hardware_tf_numeric_mismatch:' + scene)
        scene_rotation = scene_report.get('tf', {}).get(
            'rotation_xyzw') if isinstance(scene_report, Mapping) else None
        if (isinstance(scene_rotation, list) and len(scene_rotation) == 4
                and isinstance(hardware_rpy, list) and len(hardware_rpy) == 3):
            scene_rpy = _quaternion_to_rpy(scene_rotation)
            if scene_rpy is None or any(
                    abs(first - second) > 1e-6
                    for first, second in zip(scene_rpy, hardware_rpy)):
                _add_failure(
                    failures, 'hardware_tf_rotation_mismatch:' + scene)


def _check_arrangement(
        scene: str, value, failures: List[str], capture_ids: set,
        now_unix_sec: float) -> Mapping:
    if not isinstance(value, Mapping):
        _add_failure(failures, 'missing_arrangement:' + scene)
        return {}
    if set(value) != {
            'capture_id', 'scene_label', 'independently_arranged',
            'operator', 'reviewer', 'started_unix_sec',
            'ended_unix_sec'}:
        _add_failure(failures, 'arrangement_schema_invalid:' + scene)
    capture_id = value.get('capture_id')
    if not isinstance(capture_id, str) or not capture_id:
        _add_failure(failures, 'missing_capture_id:' + scene)
    elif capture_id in capture_ids:
        _add_failure(failures, 'duplicate_capture_id')
    else:
        capture_ids.add(capture_id)
    if value.get('scene_label') != scene:
        _add_failure(failures, 'arrangement_scene_mismatch:' + scene)
    if value.get('independently_arranged') is not True:
        _add_failure(failures, 'scene_not_independently_arranged:' + scene)
    for key in ('operator', 'reviewer'):
        if not isinstance(value.get(key), str) or not value.get(key):
            _add_failure(failures, 'missing_arrangement_' + key + ':' + scene)
    start = value.get('started_unix_sec')
    end = value.get('ended_unix_sec')
    if not _finite(start, 0.0) or not _finite(end, 0.0) or end <= start:
        _add_failure(failures, 'invalid_arrangement_time:' + scene)
    elif end > now_unix_sec + MAX_FUTURE_SKEW_SEC:
        _add_failure(failures, 'capture_time_future:' + scene)
    return dict(value)


def _check_independent_reviewers(
        scene: str, arrangement: Mapping, truth: Mapping,
        failures: List[str], now_unix_sec: float) -> None:
    if not isinstance(arrangement, Mapping) or not isinstance(truth, Mapping):
        return
    roles = (
        arrangement.get('operator'), arrangement.get('reviewer'),
        truth.get('annotator'), truth.get('reviewer'))
    if any(not isinstance(value, str) or not value for value in roles):
        return
    if len(set(roles)) < 3 or truth.get('annotator') == truth.get('reviewer'):
        _add_failure(failures, 'independent_review_not_proven:' + scene)
    reviewed = truth.get('reviewed_at_unix_sec')
    capture_end = arrangement.get('ended_unix_sec')
    if (not _finite(reviewed, 0.0) or not _finite(capture_end, 0.0)
            or reviewed < capture_end
            or reviewed - capture_end > 30 * 24 * 60 * 60):
        _add_failure(failures, 'ground_truth_review_time_invalid:' + scene)
    elif reviewed > now_unix_sec + MAX_FUTURE_SKEW_SEC:
        _add_failure(failures, 'ground_truth_review_time_future:' + scene)


def _check_arrangement_independence(
        arrangements: Mapping[str, Mapping], failures: List[str]) -> None:
    ordered = []
    for scene, value in arrangements.items():
        start = value.get('started_unix_sec') if isinstance(value, Mapping) else None
        end = value.get('ended_unix_sec') if isinstance(value, Mapping) else None
        if _finite(start, 0.0) and _finite(end, 0.0) and end > start:
            ordered.append((float(start), float(end), scene))
    ordered.sort()
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            _add_failure(failures, 'scene_capture_time_overlap')


def _frame_identity(frames: Sequence[Mapping]) -> Tuple[Mapping, List[str]]:
    failures = []
    sequences = []
    stamps = []
    observation_ids = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            failures.append('frame_not_object')
            continue
        sequence = frame.get('sequence')
        sequences.append(
            sequence if isinstance(sequence, int) and not isinstance(
                sequence, bool) else None)
        stamps.append(_stamp_ns(frame.get('stamp')))
        targets = frame.get('targets')
        if isinstance(targets, list):
            for target in targets:
                if isinstance(target, Mapping):
                    observation_ids.append(target.get('observation_id'))
    valid_sequences = [item for item in sequences if item is not None]
    valid_stamps = [item for item in stamps if item is not None]
    valid_observations = [
        item for item in observation_ids if isinstance(item, str) and item]
    identity = {
        'rows': len(frames),
        'valid_sequences': len(valid_sequences),
        'unique_sequences': len(set(valid_sequences)),
        'sequence_unique': (
            len(valid_sequences) == len(frames)
            and len(set(valid_sequences)) == len(valid_sequences)),
        'sequence_strictly_increasing': (
            len(valid_sequences) == len(frames)
            and all(current > previous for previous, current in zip(
                valid_sequences, valid_sequences[1:]))),
        'valid_stamps': len(valid_stamps),
        'stamp_strictly_increasing': (
            len(valid_stamps) == len(frames)
            and all(current > previous for previous, current in zip(
                valid_stamps, valid_stamps[1:]))),
        'observation_ids': len(observation_ids),
        'observation_ids_unique': (
            len(valid_observations) == len(observation_ids)
            and len(set(valid_observations)) == len(valid_observations)),
    }
    if not identity['sequence_unique']:
        failures.append('sequence_not_unique')
    if not identity['sequence_strictly_increasing']:
        failures.append('sequence_not_strictly_increasing')
    if not identity['stamp_strictly_increasing']:
        failures.append('stamp_not_strictly_increasing')
    if not identity['observation_ids_unique']:
        failures.append('duplicate_or_missing_observation_id')
    return identity, failures


def _check_typed_frame_schema(
        scene: str, frames: Sequence[Mapping], failures: List[str]) -> None:
    for frame in frames:
        if not isinstance(frame, Mapping) or set(frame) != TYPED_FRAME_KEYS:
            _add_failure(failures, 'typed_frame_schema_invalid:' + scene)
            continue
        targets = frame.get('targets')
        if not isinstance(targets, list):
            _add_failure(failures, 'typed_target_schema_invalid:' + scene)
            continue
        for target in targets:
            if (not isinstance(target, Mapping)
                    or set(target) != TYPED_TARGET_KEYS):
                _add_failure(failures, 'typed_target_schema_invalid:' + scene)
                break


def _check_manifest(
        scene: str, manifest: Mapping, frames_path: Optional[Path],
        frames: Sequence[Mapping], identity: Mapping,
        failures: List[str]) -> None:
    if not isinstance(manifest, Mapping):
        _add_failure(failures, 'invalid_collector_manifest:' + scene)
        return
    if (set(manifest) != COLLECTOR_KEYS
            or manifest.get('schema_version') != 1
            or manifest.get('read_only') is not True):
        _add_failure(failures, 'invalid_collector_manifest:' + scene)
    if manifest.get('authorizes_motion') is not False:
        _add_failure(failures, 'collector_motion_contract_violation:' + scene)
    if manifest.get('publishes_ros_messages') is not False:
        _add_failure(failures, 'collector_publisher_contract_violation:' + scene)
    if _contains_forbidden_control_claim(manifest):
        _add_failure(failures, 'collector_control_contract_violation:' + scene)
    if manifest.get('scene') != scene:
        _add_failure(failures, 'manifest_scene_mismatch:' + scene)
    if manifest.get('topic') != EXPECTED_FRAME_TOPIC:
        _add_failure(failures, 'manifest_topic_mismatch:' + scene)
    if manifest.get('message_type') != EXPECTED_FRAME_TYPE:
        _add_failure(failures, 'manifest_message_type_mismatch:' + scene)
    forbidden_topics = manifest.get('forbidden_control_topics')
    if (not isinstance(forbidden_topics, list)
            or len(forbidden_topics) != len(EXPECTED_FORBIDDEN_CONTROL_TOPICS)
            or set(forbidden_topics) != EXPECTED_FORBIDDEN_CONTROL_TOPICS):
        _add_failure(failures, 'manifest_control_policy_mismatch:' + scene)
    frame_task_ids = {
        frame.get('task_id') for frame in frames
        if isinstance(frame, Mapping) and isinstance(
            frame.get('task_id'), str) and frame.get('task_id')}
    if (not isinstance(manifest.get('task_id'), str)
            or not manifest.get('task_id')
            or frame_task_ids != {manifest.get('task_id')}):
        _add_failure(failures, 'manifest_task_id_mismatch:' + scene)
    if manifest.get('received_frames') != len(frames):
        _add_failure(failures, 'manifest_count_mismatch:' + scene)
    if manifest.get('unique_sequence_frames') != identity['unique_sequences']:
        _add_failure(failures, 'manifest_count_mismatch:' + scene)
    duplicates = len(frames) - identity['unique_sequences']
    if manifest.get('duplicate_sequences') != duplicates:
        _add_failure(failures, 'manifest_count_mismatch:' + scene)
    if duplicates or manifest.get('duplicate_sequences') != 0:
        _add_failure(failures, 'duplicate_sequences_present:' + scene)
    if manifest.get('serialization_errors') != 0:
        _add_failure(failures, 'serialization_errors_present:' + scene)
    if manifest.get('interrupted') is not False:
        _add_failure(failures, 'capture_interrupted:' + scene)
    if manifest.get('completed_max_frames') is not True:
        _add_failure(failures, 'capture_not_completed:' + scene)
    if (not isinstance(manifest.get('max_frames'), int)
            or isinstance(manifest.get('max_frames'), bool)
            or manifest.get('max_frames') < MIN_UNIQUE_FRAMES):
        _add_failure(failures, 'collector_target_below_minimum:' + scene)
    if (not _finite(manifest.get('duration_sec'), 0.0)
            or manifest.get('duration_sec') <= 0.0):
        _add_failure(failures, 'collector_duration_invalid:' + scene)
    output = manifest.get('output')
    if frames_path is not None and isinstance(output, Mapping):
        output_path = _resolve_path(
            frames_path, output.get('path'))
        if output_path is None or output_path != frames_path:
            _add_failure(failures, 'manifest_frames_path_mismatch:' + scene)
        if output.get('size_bytes') != frames_path.stat().st_size:
            _add_failure(failures, 'manifest_frames_size_mismatch:' + scene)
        if output.get('sha256') != sha256_file(frames_path):
            _add_failure(failures, 'manifest_frames_sha256_mismatch:' + scene)
    else:
        _add_failure(failures, 'manifest_output_binding_missing:' + scene)


def _check_streams(scene: str, rgbd: Mapping, failures: List[str]) -> Mapping:
    if not isinstance(rgbd, Mapping) or rgbd.get('schema_version') != 1:
        _add_failure(failures, 'invalid_rgbd_schema:' + scene)
    streams = rgbd.get('streams') if isinstance(rgbd, Mapping) else None
    if not isinstance(streams, Mapping):
        _add_failure(failures, 'missing_rgbd_streams:' + scene)
        return {}
    optical_frames = []
    grids = []
    stream_ranges = []
    for name in REQUIRED_STREAMS:
        stream = streams.get(name)
        if not isinstance(stream, Mapping):
            _add_failure(failures, 'missing_stream:{}:{}'.format(scene, name))
            continue
        if stream.get('message_type') != EXPECTED_STREAM_TYPES[name]:
            _add_failure(failures, 'stream_type_mismatch:{}:{}'.format(
                scene, name))
        for key in ('topic', 'frame_id'):
            if not isinstance(stream.get(key), str) or not stream.get(key):
                _add_failure(failures, 'stream_metadata_missing:{}:{}:{}'.format(
                    scene, name, key))
        width = stream.get('width')
        height = stream.get('height')
        count = stream.get('message_count')
        if (not isinstance(width, int) or isinstance(width, bool) or width <= 0
                or not isinstance(height, int) or isinstance(height, bool)
                or height <= 0):
            _add_failure(failures, 'invalid_stream_resolution:{}:{}'.format(
                scene, name))
        else:
            grids.append((width, height))
        if not isinstance(count, int) or isinstance(count, bool) or count < MIN_UNIQUE_FRAMES:
            _add_failure(failures, 'insufficient_stream_messages:{}:{}'.format(
                scene, name))
        start = stream.get('first_stamp_unix_sec')
        end = stream.get('last_stamp_unix_sec')
        if not _finite(start, 0.0) or not _finite(end, 0.0) or end < start:
            _add_failure(failures, 'invalid_stream_time_range:{}:{}'.format(
                scene, name))
        else:
            stream_ranges.append((float(start), float(end)))
        frame_id = stream.get('frame_id')
        if isinstance(frame_id, str) and frame_id:
            optical_frames.append(frame_id)
        if name in ('rgb', 'aligned_depth'):
            encoding = stream.get('encoding')
            if not isinstance(encoding, str) or not encoding:
                _add_failure(failures, 'missing_stream_encoding:{}:{}'.format(
                    scene, name))
        if name == 'aligned_depth':
            if stream.get('encoding') not in ('16UC1', 'mono16', '32FC1'):
                _add_failure(failures, 'invalid_depth_encoding:' + scene)
            scale = stream.get('depth_scale_m')
            expected_scale = (
                1.0 if stream.get('encoding') == '32FC1' else 0.001)
            if (not _finite(scale) or scale <= 0.0
                    or abs(scale - expected_scale) > 1e-9):
                _add_failure(failures, 'invalid_depth_scale:' + scene)
        if 'camera_info' in name:
            intrinsics = stream.get('intrinsics')
            if (not isinstance(intrinsics, Mapping)
                    or not _finite(intrinsics.get('fx'))
                    or intrinsics.get('fx') <= 0.0
                    or not _finite(intrinsics.get('fy'))
                    or intrinsics.get('fy') <= 0.0
                    or not _finite(intrinsics.get('cx'))
                    or not _finite(intrinsics.get('cy'))):
                _add_failure(failures, 'invalid_camera_intrinsics:{}:{}'.format(
                    scene, name))
    if grids and len(set(grids)) != 1:
        _add_failure(failures, 'resolution_mismatch:' + scene)
    if optical_frames and len(set(optical_frames)) != 1:
        _add_failure(failures, 'rgbd_frame_mismatch:' + scene)
    sync = rgbd.get('sync_span_sec') if isinstance(rgbd, Mapping) else None
    expected_samples = rgbd.get('accepted_bundle_count') if isinstance(
        rgbd, Mapping) else None
    if (not isinstance(expected_samples, int) or isinstance(
            expected_samples, bool) or expected_samples < MIN_UNIQUE_FRAMES):
        _add_failure(failures, 'rgbd_bundle_count_invalid:' + scene)
        expected_samples = None
    if (not isinstance(sync, list) or len(sync) < MIN_UNIQUE_FRAMES
            or expected_samples is None or len(sync) != expected_samples):
        _add_failure(failures, 'sync_samples_incomplete:' + scene)
        sync_summary = _distribution([])
    else:
        sync_summary = _distribution(sync)
        if sync_summary['samples'] != len(sync):
            _add_failure(failures, 'invalid_sync_sample:' + scene)
        if (sync_summary['p95'] is None
                or sync_summary['p95'] > MAX_SYNC_P95_SEC):
            _add_failure(failures, 'sync_p95_exceeded:' + scene)
        if any(_finite(value) and value > MAX_SYNC_P95_SEC for value in sync):
            _add_failure(failures, 'sync_sample_exceeded:' + scene)
    return {
        'streams': len(streams),
        'frame_ids': sorted(set(optical_frames)),
        'resolutions': [list(item) for item in sorted(set(grids))],
        'sync_span_sec': sync_summary,
        'stream_time_ranges': [list(item) for item in stream_ranges],
    }


def _check_raw_capture(
        bundle_path: Path, scene: str, declaration, arrangement: Mapping,
        rgbd: Mapping, failures: List[str], bindings: List[Mapping],
        seen_paths: Dict[str, str], raw_fingerprints: set,
        now_unix_sec: float) -> Mapping:
    """Re-decode the concrete bag and bind it to every claimed artifact."""
    if not isinstance(declaration, Mapping):
        _add_failure(failures, 'missing_raw_capture:' + scene)
        return {}
    expected_declaration_keys = {
        'capture_id', 'scene_label', 'storage_identifier', 'storage_file',
        'inspection'}
    declaration_schema_valid = set(declaration) == expected_declaration_keys
    if not declaration_schema_valid:
        _add_failure(
            failures, 'raw_capture_declaration_schema_invalid:' + scene)
    if declaration.get('formal_acceptance') is False:
        _add_failure(failures, 'raw_capture_non_formal:' + scene)
    if declaration.get('shared_graph') is True:
        _add_failure(failures, 'raw_capture_shared_graph:' + scene)
    if declaration.get('mixed_tf') is True:
        _add_failure(failures, 'raw_capture_mixed_tf:' + scene)
    if declaration.get('not_in_four_scene_denominator') is True:
        _add_failure(
            failures, 'raw_capture_excluded_from_scene_denominator:' + scene)
    if (declaration.get('capture_id') != arrangement.get('capture_id')
            or declaration.get('scene_label') != scene
            or declaration.get('storage_identifier') != 'sqlite3'):
        _add_failure(failures, 'raw_capture_binding_mismatch:' + scene)
    storage_path = _artifact(
        bundle_path, declaration.get('storage_file'), scene + ':raw_storage',
        failures, bindings, seen_paths)
    inspection_path = _artifact(
        bundle_path, declaration.get('inspection'), scene + ':raw_inspection',
        failures, bindings, seen_paths)
    if storage_path is None:
        _add_failure(failures, 'missing_raw_capture:' + scene)
        return {}
    if storage_path.suffix.lower() != '.db3':
        _add_failure(failures, 'unsupported_raw_capture_storage:' + scene)
    storage_sha = sha256_file(storage_path)
    if storage_sha in raw_fingerprints:
        _add_failure(failures, 'duplicate_raw_capture_fingerprint')
    else:
        raw_fingerprints.add(storage_sha)
    inspection = _load_json(
        inspection_path, scene + ':raw_inspection', failures)
    admission = _formal_raw_inspection_admission(
        scene, inspection, failures)
    if not declaration_schema_valid:
        admission = dict(admission)
        reasons = list(admission.get('exclusion_reasons', []))
        if 'raw_capture_declaration' not in reasons:
            reasons.append('raw_capture_declaration')
        admission['exclusion_reasons'] = reasons
        admission['admitted_to_formal_scene'] = False
    if not isinstance(inspection, Mapping):
        _add_failure(failures, 'raw_capture_inspection_invalid:' + scene)
        return {
            'storage_sha256': storage_sha,
            'formal_scene_admission': admission,
            'accepted_bundles': 0,
            'bundles': [],
            'tf_graph': None,
        }
    if (inspection.get('schema_version') != 3
            or inspection.get('read_only') is not True
            or inspection.get('capture_id') != arrangement.get('capture_id')
            or inspection.get('scene') != scene
            or inspection.get('storage_identifier') != 'sqlite3'
            or inspection.get('source_capture', {}).get('sha256') != storage_sha
            or inspection.get('source_capture', {}).get('size_bytes')
            != storage_path.stat().st_size):
        _add_failure(failures, 'raw_capture_inspection_invalid:' + scene)
    expected_manifest = load_topic_manifest(default_topic_manifest_path())
    manifest_binding = inspection.get('expected_topic_manifest')
    if (not isinstance(manifest_binding, Mapping)
            or manifest_binding.get('manifest_id') != EXPECTED_TOPIC_MANIFEST_ID
            or manifest_binding.get('schema_version') != 1
            or manifest_binding.get('sha256') != expected_manifest['sha256']
            or manifest_binding.get('size_bytes') != expected_manifest[
                'size_bytes']):
        _add_failure(failures, 'raw_topic_manifest_binding_mismatch:' + scene)
    topics = inspection.get('topics')
    messages = inspection.get('messages')
    bundles = inspection.get('accepted_bundles')
    stream_topics = inspection.get('stream_topics')
    if (not isinstance(topics, list) or not isinstance(messages, list)
            or not isinstance(bundles, list)
            or not isinstance(stream_topics, Mapping)):
        _add_failure(failures, 'raw_capture_inspection_incomplete:' + scene)
        return {
            'storage_sha256': storage_sha,
            'formal_scene_admission': admission,
            'accepted_bundles': 0,
            'bundles': [],
            'tf_graph': None,
        }
    try:
        actual = inspect_sqlite_bag(
            storage_path, arrangement.get('capture_id'), scene,
            {name: stream_topics.get(name) for name in REQUIRED_STREAMS},
            default_topic_manifest_path())
    except (OSError, ValueError, TypeError, KeyError):
        actual = None
        _add_failure(failures, 'raw_capture_decode_failed:' + scene)
    actual_topics = actual.get('topics') if isinstance(actual, Mapping) else []
    actual_messages = actual.get('messages') if isinstance(
        actual, Mapping) else []
    if (inspection != actual or topics != actual_topics
            or messages != actual_messages):
        _add_failure(failures, 'raw_capture_sqlite_index_mismatch:' + scene)
    topic_map = {
        item.get('name'): item for item in topics
        if isinstance(item, Mapping) and isinstance(item.get('name'), str)}
    if len(topic_map) != len(topics):
        _add_failure(failures, 'raw_capture_topic_table_invalid:' + scene)
    for stream_name in REQUIRED_STREAMS:
        stream = rgbd.get('streams', {}).get(stream_name) if isinstance(
            rgbd, Mapping) else None
        topic = stream_topics.get(stream_name)
        topic_record = topic_map.get(topic)
        decoded_stream_messages = [
            item for item in actual_messages
            if isinstance(item, Mapping) and item.get('topic') == topic]
        decoded_values = [
            item.get('decoded') for item in decoded_stream_messages
            if isinstance(item.get('decoded'), Mapping)]
        decoded_frames = {
            item.get('frame_id') for item in decoded_values}
        decoded_widths = {item.get('width') for item in decoded_values}
        decoded_heights = {item.get('height') for item in decoded_values}
        decoded_stamps = [item.get('stamp_ns') for item in decoded_values]
        if (not isinstance(stream, Mapping)
                or topic != stream.get('topic')
                or not isinstance(topic_record, Mapping)
                or topic_record.get('type') != RAW_EXPECTED_STREAM_TYPES[
                    stream_name]
                or topic_record.get('message_count') != stream.get(
                    'message_count')
                or len(decoded_values) != topic_record.get('message_count')
                or decoded_frames != {stream.get('frame_id')}
                or decoded_widths != {stream.get('width')}
                or decoded_heights != {stream.get('height')}
                or not decoded_stamps
                or stream.get('first_stamp_unix_sec') != (
                    min(decoded_stamps) / 1e9)
                or stream.get('last_stamp_unix_sec') != (
                    max(decoded_stamps) / 1e9)):
            _add_failure(
                failures, 'raw_capture_stream_binding_mismatch:{}:{}'.format(
                    scene, stream_name))
        elif stream_name in ('rgb', 'aligned_depth') and {
                item.get('encoding') for item in decoded_values
                } != {stream.get('encoding')}:
            _add_failure(
                failures, 'raw_capture_image_metadata_mismatch:{}:{}'.format(
                    scene, stream_name))
        elif 'camera_info' in stream_name:
            decoded_intrinsics = {
                (item.get('intrinsics', {}).get('fx'),
                 item.get('intrinsics', {}).get('fy'),
                 item.get('intrinsics', {}).get('cx'),
                 item.get('intrinsics', {}).get('cy'))
                for item in decoded_values}
            declared = stream.get('intrinsics', {})
            expected_intrinsics = {(
                declared.get('fx'), declared.get('fy'),
                declared.get('cx'), declared.get('cy'))}
            if decoded_intrinsics != expected_intrinsics:
                _add_failure(
                    failures,
                    'raw_capture_camera_intrinsics_mismatch:{}:{}'.format(
                        scene, stream_name))
    control_topics = inspection.get('control_topics')
    derived_control_topics = sorted(
        item.get('name') for item in actual_topics
        if isinstance(item, Mapping) and is_control_topic(
            item.get('name'), item.get('type')))
    if (not isinstance(control_topics, list)
            or sorted(control_topics) != derived_control_topics
            or derived_control_topics):
        _add_failure(failures, 'raw_capture_control_topic_present:' + scene)
    message_map = {}
    for item in messages:
        if not isinstance(item, Mapping):
            continue
        message_id = item.get('message_id')
        if (not isinstance(message_id, int) or isinstance(message_id, bool)
                or message_id in message_map
                or not isinstance(item.get('topic'), str)
                or item.get('topic') not in topic_map
                or not isinstance(item.get('serialized_sha256'), str)
                or len(item.get('serialized_sha256')) != 64
                or item.get('payload_decode_ok') is not True
                or not isinstance(item.get('record_timestamp_ns'), int)
                or not isinstance(item.get('decoded'), Mapping)):
            _add_failure(failures, 'raw_capture_message_index_invalid:' + scene)
            continue
        message_map[message_id] = item
    if len(message_map) != len(messages):
        _add_failure(failures, 'raw_capture_message_index_invalid:' + scene)
    if len(bundles) < MIN_UNIQUE_FRAMES:
        _add_failure(failures, 'raw_capture_bundle_count_invalid:' + scene)
    canonical_bundles = actual.get('accepted_bundles') if isinstance(
        actual, Mapping) else None
    if bundles != canonical_bundles:
        _add_failure(failures, 'raw_capture_bundle_index_mismatch:' + scene)
    derived_sync = [
        item.get('stamp_span_sec') for item in bundles
        if isinstance(item, Mapping)]
    declared_sync = rgbd.get('sync_span_sec') if isinstance(
        rgbd, Mapping) else None
    if (len(derived_sync) != len(bundles)
            or inspection.get('accepted_bundle_count') != len(bundles)
            or rgbd.get('accepted_bundle_count') != len(bundles)
            or not isinstance(declared_sync, list)
            or len(declared_sync) != len(derived_sync)
            or any(abs(first - second) > 1e-9 for first, second in zip(
                declared_sync, derived_sync))):
        _add_failure(failures, 'raw_capture_sync_binding_mismatch:' + scene)
    if any(value > RAW_MAX_SYNC_SPAN_SEC for value in derived_sync):
        _add_failure(
            failures, 'raw_capture_accepted_bundle_over_sync_limit:' + scene)
    candidates = inspection.get('rgb_candidate_count')
    rejected = inspection.get('rejected_rgb_count')
    rejection_rate = inspection.get('rejection_rate')
    reasons = inspection.get('rejection_reasons')
    total_stream_messages = inspection.get('total_stream_message_count')
    total_unpaired = inspection.get('total_unpaired_message_count')
    total_unpaired_rate = inspection.get('total_unpaired_rate')
    unmatched_by_stream = inspection.get('unmatched_message_count_by_stream')
    if (not isinstance(candidates, int) or isinstance(candidates, bool)
            or candidates <= 0
            or not isinstance(rejected, int) or isinstance(rejected, bool)
            or rejected < 0 or rejected > candidates
            or not _finite(rejection_rate, 0.0, 1.0)
            or abs(rejection_rate - rejected / candidates) > 1e-9
            or not isinstance(reasons, Mapping)
            or any(not isinstance(value, int) or isinstance(value, bool)
                   or value < 0 for value in reasons.values())
            or sum(reasons.values()) != rejected):
        _add_failure(failures, 'raw_capture_rejection_accounting_invalid:' + scene)
    elif rejection_rate > MAX_RAW_REJECTION_RATE:
        _add_failure(failures, 'raw_capture_rejection_rate_exceeded:' + scene)
    unpaired_report, unpaired_accounting_valid, unpaired_rate_exceeded = (
        _raw_stream_unpaired_report(
            topics, unmatched_by_stream, total_stream_messages,
            total_unpaired, total_unpaired_rate))
    if not unpaired_accounting_valid:
        _add_failure(failures, 'raw_capture_unpaired_accounting_invalid:' + scene)
    elif unpaired_rate_exceeded:
        _add_failure(failures, 'raw_capture_unpaired_rate_exceeded:' + scene)
    capture_end = arrangement.get('ended_unix_sec') if isinstance(
        arrangement, Mapping) else None
    capture_start = arrangement.get('started_unix_sec') if isinstance(
        arrangement, Mapping) else None
    record_timestamps = [
        item.get('record_timestamp_ns') for item in messages
        if isinstance(item, Mapping) and isinstance(
            item.get('record_timestamp_ns'), int)]
    last_timestamp = max(record_timestamps, default=None)
    if (last_timestamp is not None
            and last_timestamp / 1e9 > now_unix_sec + MAX_FUTURE_SKEW_SEC):
        _add_failure(failures, 'raw_capture_time_future:' + scene)
    if (_finite(capture_end, 0.0) and last_timestamp is not None
            and last_timestamp / 1e9 > float(capture_end)):
        _add_failure(failures, 'raw_capture_outside_capture_window:' + scene)
    if (_finite(capture_start, 0.0) and record_timestamps
            and any(value / 1e9 < float(capture_start)
                    for value in record_timestamps)):
        _add_failure(failures, 'raw_capture_outside_capture_window:' + scene)
    formally_admitted = admission.get('admitted_to_formal_scene') is True
    formal_bundles = bundles if formally_admitted else []
    formal_tf_graph = inspection.get('tf_graph') if formally_admitted else None
    return {
        'storage_sha256': storage_sha,
        'formal_scene_admission': admission,
        'diagnostic_observed_topics': len(topics),
        'diagnostic_observed_messages': len(messages),
        'topics': len(topics) if formally_admitted else 0,
        'messages': len(messages) if formally_admitted else 0,
        'diagnostic_observed_accepted_bundles': len(bundles),
        'accepted_bundles': len(formal_bundles),
        'rgb_candidates': candidates,
        'rejected_rgb': rejected,
        'rejection_rate': rejection_rate,
        'unpaired': unpaired_report,
        'sync_spans_sec': derived_sync,
        'rgb_anchor_timestamps_ns': [
            message_map.get(bundle.get('rgb'), {}).get(
                'decoded', {}).get('stamp_ns')
            for bundle in formal_bundles if isinstance(bundle, Mapping)],
        'bundles': formal_bundles,
        'tf_graph': formal_tf_graph,
    }


def _check_rgbd_time_binding(
        scene: str, arrangement: Mapping, frames: Sequence[Mapping],
        rgbd_report: Mapping, failures: List[str]) -> None:
    if not isinstance(arrangement, Mapping):
        return
    start = arrangement.get('started_unix_sec')
    end = arrangement.get('ended_unix_sec')
    if not _finite(start, 0.0) or not _finite(end, 0.0) or end <= start:
        _add_failure(failures, 'rgbd_capture_window_invalid:' + scene)
        return
    ranges = rgbd_report.get('stream_time_ranges')
    if not isinstance(ranges, list) or len(ranges) != len(REQUIRED_STREAMS):
        _add_failure(failures, 'rgbd_time_range_incomplete:' + scene)
        return
    for value in ranges:
        if (not isinstance(value, list) or len(value) != 2
                or not _finite(value[0], float(start), float(end))
                or not _finite(value[1], float(start), float(end))):
            _add_failure(failures, 'rgbd_outside_capture_window:' + scene)
            break
    stamps = [
        _stamp_ns(frame.get('stamp')) / 1e9
        for frame in frames if isinstance(frame, Mapping)
        and _stamp_ns(frame.get('stamp')) is not None]
    if stamps and not any(
            min(stamps) >= value[0] and max(stamps) <= value[1]
            for value in ranges if isinstance(value, list) and len(value) == 2):
        _add_failure(failures, 'rgbd_typed_stamp_range_mismatch:' + scene)


def _truth_key(value) -> Optional[Tuple[int, int]]:
    if not isinstance(value, Mapping):
        return None
    sequence = value.get('sequence')
    stamp = _stamp_ns(value.get('stamp'))
    if (not isinstance(sequence, int) or isinstance(sequence, bool)
            or stamp is None):
        return None
    return sequence, stamp


def _check_ground_truth(
        scene: str, truth: Mapping, frames: Sequence[Mapping],
        raw_bundles: Sequence[Mapping], failures: List[str]) -> Mapping:
    if not isinstance(truth, Mapping):
        _add_failure(failures, 'missing_ground_truth:' + scene)
        return {}
    expected_keys = {
        'schema_version', 'capture_provenance', 'scene', 'exhaustive',
        'classes', 'annotator', 'reviewer', 'reviewed_at_unix_sec', 'frames'}
    if set(truth) != expected_keys:
        _add_failure(failures, 'ground_truth_schema_invalid:' + scene)
    if truth.get('schema_version') != 2:
        _add_failure(failures, 'invalid_ground_truth_schema:' + scene)
    if truth.get('scene') != scene:
        _add_failure(failures, 'ground_truth_scene_mismatch:' + scene)
    if truth.get('exhaustive') is not True:
        _add_failure(failures, 'ground_truth_not_exhaustive:' + scene)
    classes = truth.get('classes')
    if not isinstance(classes, list) or 'plastic_bottle' not in classes:
        _add_failure(failures, 'missing_bottle_annotation:' + scene)
    if not isinstance(classes, list) or 'trash_bin' not in classes:
        _add_failure(failures, 'missing_trash_bin_annotation:' + scene)
    for key in ('annotator', 'reviewer', 'reviewed_at_unix_sec'):
        value = truth.get(key)
        if ((key == 'reviewed_at_unix_sec' and not _finite(value, 0.0))
                or (key != 'reviewed_at_unix_sec'
                    and (not isinstance(value, str) or not value))):
            _add_failure(failures, 'ground_truth_metadata_missing:' + scene)
    annotations = truth.get('frames')
    if not isinstance(annotations, list):
        _add_failure(failures, 'ground_truth_frames_missing:' + scene)
        return {}
    frame_keys = {_truth_key(frame) for frame in frames}
    truth_keys = [_truth_key(item) for item in annotations]
    if None in frame_keys or None in truth_keys:
        _add_failure(failures, 'ground_truth_identity_invalid:' + scene)
    if (len(set(truth_keys)) != len(truth_keys)
            or set(truth_keys) != frame_keys):
        _add_failure(failures, 'ground_truth_coverage_incomplete:' + scene)
    missing_labels = 0
    relationship_missing = 0
    raw_binding_invalid = 0
    canonical_by_stamp = {}
    if isinstance(raw_bundles, list):
        for bundle in raw_bundles:
            stamp = bundle.get('header_stamps_ns', {}).get(
                'rgb') if isinstance(bundle, Mapping) else None
            if (not isinstance(stamp, int) or isinstance(stamp, bool)
                    or stamp <= 0 or stamp in canonical_by_stamp):
                raw_binding_invalid += 1
                continue
            canonical_by_stamp[stamp] = bundle
    seen_bundle_indices = set()
    raw_by_truth_key = {}
    for item in annotations:
        if not isinstance(item, Mapping):
            missing_labels += 1
            continue
        if set(item) != {
                'sequence', 'stamp', 'raw_rgb', 'presence', 'instances'}:
            raw_binding_invalid += 1
        truth_key = _truth_key(item)
        stamp_ns = truth_key[1] if truth_key is not None else None
        raw_rgb = item.get('raw_rgb')
        expected_bundle = canonical_by_stamp.get(stamp_ns)
        expected_raw = ({
            'bundle_index': expected_bundle.get('index'),
            'message_id': expected_bundle.get('rgb'),
            'header_stamp_ns': expected_bundle.get(
                'header_stamps_ns', {}).get('rgb'),
            'payload_sha256': expected_bundle.get(
                'stream_payload_sha256', {}).get('rgb'),
            'serialized_size_bytes': expected_bundle.get(
                'stream_serialized_size_bytes', {}).get('rgb'),
        } if isinstance(expected_bundle, Mapping) else None)
        if (not isinstance(raw_rgb, Mapping)
                or set(raw_rgb) != {
                    'bundle_index', 'message_id', 'header_stamp_ns',
                    'payload_sha256', 'serialized_size_bytes'}
                or raw_rgb != expected_raw
                or not _lower_sha256(raw_rgb.get('payload_sha256'))
                or not isinstance(raw_rgb.get('serialized_size_bytes'), int)
                or isinstance(raw_rgb.get('serialized_size_bytes'), bool)
                or raw_rgb.get('serialized_size_bytes') <= 0
                or raw_rgb.get('bundle_index') in seen_bundle_indices):
            raw_binding_invalid += 1
        else:
            seen_bundle_indices.add(raw_rgb['bundle_index'])
            raw_by_truth_key[truth_key] = expected_bundle
        presence = item.get('presence')
        if (not isinstance(presence, Mapping)
                or set(presence) != {'plastic_bottle', 'trash_bin'}
                or not isinstance(presence.get('plastic_bottle'), bool)
                or not isinstance(presence.get('trash_bin'), bool)):
            missing_labels += 1
        instances = item.get('instances')
        if not isinstance(instances, list):
            missing_labels += 1
            continue
        instance_presence = {'plastic_bottle': False, 'trash_bin': False}
        instance_ids = set()
        for instance in instances:
            if not isinstance(instance, Mapping):
                missing_labels += 1
                continue
            label = instance.get('object_class')
            expected_instance_keys = {
                'instance_id', 'object_class', 'bbox'} | (
                    {'inside_trash_bin'}
                    if label == 'plastic_bottle' else set())
            bbox = instance.get('bbox')
            if (label not in ('plastic_bottle', 'trash_bin')
                    or set(instance) != expected_instance_keys
                    or not isinstance(bbox, list) or len(bbox) != 4
                    or not all(_finite(value) for value in bbox)
                    or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]):
                missing_labels += 1
            else:
                instance_presence[label] = True
            instance_id = instance.get('instance_id')
            if (not isinstance(instance_id, str) or not instance_id
                    or instance_id in instance_ids):
                missing_labels += 1
            else:
                instance_ids.add(instance_id)
            if label == 'plastic_bottle' and not isinstance(
                    instance.get('inside_trash_bin'), bool):
                relationship_missing += 1
        if isinstance(presence, Mapping) and any(
                presence.get(label) is not observed
                for label, observed in instance_presence.items()):
            missing_labels += 1
    if missing_labels:
        _add_failure(failures, 'ground_truth_labels_incomplete:' + scene)
    if relationship_missing:
        _add_failure(failures, 'bin_relation_annotation_missing:' + scene)
    if (raw_binding_invalid or len(raw_by_truth_key) != len(annotations)
            or len(raw_by_truth_key) != len(frames)):
        _add_failure(failures, 'ground_truth_raw_rgb_binding_mismatch:' + scene)
    return {
        'annotated_frames': len(annotations),
        'coverage_matches': (
            len(set(truth_keys)) == len(truth_keys)
            and set(truth_keys) == frame_keys),
        'raw_rgb_bound_frames': len(raw_by_truth_key),
        'raw_bundles_by_truth_key': raw_by_truth_key,
    }


def _check_truth_semantics(
        scene: str, truth: Mapping, failures: List[str]) -> None:
    if not isinstance(truth, Mapping) or not isinstance(
            truth.get('frames'), list):
        return
    expected = {
        'plastic_bottle': scene in ('bottle_in_bin', 'bottle_outside'),
        'trash_bin': scene != 'background',
    }
    for item in truth['frames']:
        if not isinstance(item, Mapping):
            continue
        if item.get('presence') != expected:
            _add_failure(failures, 'ground_truth_scene_semantics_mismatch:' + scene)
        for instance in item.get('instances', []):
            if not isinstance(instance, Mapping):
                continue
            if instance.get('object_class') == 'plastic_bottle':
                expected_inside = scene == 'bottle_in_bin'
                if instance.get('inside_trash_bin') is not expected_inside:
                    _add_failure(
                        failures, 'bin_relation_scene_mismatch:' + scene)


def _truth_instances(truth: Mapping) -> List[Mapping]:
    result = []
    if not isinstance(truth, Mapping) or not isinstance(
            truth.get('frames'), list):
        return result
    for frame in truth['frames']:
        if not isinstance(frame, Mapping):
            continue
        sequence = frame.get('sequence')
        stamp_ns = _stamp_ns(frame.get('stamp'))
        for instance in frame.get('instances', []):
            if not isinstance(instance, Mapping):
                continue
            result.append({
                'sequence': sequence,
                'stamp_ns': stamp_ns,
                'instance_id': instance.get('instance_id'),
                'object_class': instance.get('object_class'),
                'bbox': instance.get('bbox'),
            })
    return result


def _check_instance_metrics(
        scene: str, truth_instances: Sequence[Mapping], frames: Sequence[Mapping],
        failures: List[str]) -> Mapping:
    truth_by_frame = {}
    for item in truth_instances:
        key = (item.get('sequence'), item.get('stamp_ns'))
        truth_by_frame.setdefault(key, []).append(item)
    frame_by_key = {
        (frame.get('sequence'), _stamp_ns(frame.get('stamp'))): frame
        for frame in frames if isinstance(frame, Mapping)}
    metrics = {}
    matches = {}
    for label in ('plastic_bottle', 'trash_bin'):
        tp = 0
        fp = 0
        fn = 0
        for key in set(truth_by_frame) | set(frame_by_key):
            truths = [item for item in truth_by_frame.get(key, [])
                      if item.get('object_class') == label]
            frame = frame_by_key.get(key, {})
            predictions = [
                item for item in frame.get('targets', [])
                if isinstance(item, Mapping)
                and item.get('object_class') == label]
            for prediction in predictions:
                status = prediction.get('status')
                actionable = prediction.get('actionable')
                if label == 'trash_bin' and (
                        status != 'observed' or actionable is not False):
                    _add_failure(
                        failures, 'trash_bin_status_contract_failed:' + scene)
                if label == 'plastic_bottle':
                    expected_status = (
                        'already_in_bin' if scene == 'bottle_in_bin'
                        else 'active')
                    expected_actionable = scene == 'bottle_outside'
                    if (status != expected_status
                            or actionable is not expected_actionable):
                        _add_failure(
                            failures,
                            'bottle_relation_status_contract_failed:' + scene)
            unmatched_truths = set(range(len(truths)))
            for prediction in sorted(
                    predictions, key=lambda item: item.get('confidence', 0.0),
                    reverse=True):
                best_index = None
                best_iou = 0.0
                for index in unmatched_truths:
                    iou = _bbox_iou(
                        prediction.get('bbox'), truths[index].get('bbox'))
                    if iou > best_iou:
                        best_index = index
                        best_iou = iou
                if best_index is not None and best_iou >= 0.50:
                    tp += 1
                    truth_item = truths[best_index]
                    matches[(
                        key[0], key[1], truth_item.get('instance_id'), label
                    )] = {
                        'observation_id': prediction.get('observation_id'),
                        'prediction_position': prediction.get('position'),
                        'prediction_depth_m': prediction.get('depth_m'),
                        'prediction_depth_valid_ratio': prediction.get(
                            'depth_valid_ratio'),
                        'prediction_bbox': prediction.get('bbox'),
                        'iou': best_iou,
                    }
                    unmatched_truths.remove(best_index)
                else:
                    fp += 1
            fn += len(unmatched_truths)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = (2.0 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        metrics[label] = {
            'tp': tp, 'fp': fp, 'fn': fn,
            'precision': precision, 'recall': recall, 'f1': f1,
            'matching': 'same_sequence_stamp_class_bbox_iou_at_least_0.50',
        }
        if precision < 0.90:
            _add_failure(failures, label + '_instance_precision_below_0.90:' + scene)
        if recall < 0.90:
            _add_failure(failures, label + '_instance_recall_below_0.90:' + scene)
        if f1 < 0.90:
            _add_failure(failures, label + '_instance_f1_below_0.90:' + scene)
    return {'classes': metrics, 'matches': matches}


def _bbox_iou(first, second) -> float:
    if (not isinstance(first, list) or len(first) != 4
            or not isinstance(second, list) or len(second) != 4
            or not all(_finite(value) for value in first + second)):
        return 0.0
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _check_tf(scene: str, tf_data: Mapping, failures: List[str]) -> Mapping:
    if not isinstance(tf_data, Mapping):
        _add_failure(failures, 'missing_tf_metadata:' + scene)
        return {}
    expected_keys = {
        'schema_version', 'capture_provenance', 'parent', 'child',
        'translation_m', 'rotation_xyzw',
        'independent_extrinsics_validated', 'measurement_owner',
        'measurement_source', 'measurement_reference_sha256',
        'measured_at_unix_sec', 'translation_error_m',
        'rotation_error_rad', 'translation_tolerance_m',
        'rotation_tolerance_rad'}
    if set(tf_data) != expected_keys:
        _add_failure(failures, 'tf_artifact_schema_invalid:' + scene)
    if tf_data.get('schema_version') != 1:
        _add_failure(failures, 'invalid_tf_schema:' + scene)
    if (tf_data.get('parent') != EXPECTED_BASE_FRAME
            or not isinstance(tf_data.get('child'), str)
            or not tf_data.get('child')):
        _add_failure(failures, 'tf_parent_child_mismatch:' + scene)
    translation = tf_data.get('translation_m')
    rotation = tf_data.get('rotation_xyzw')
    if (not isinstance(translation, list) or len(translation) != 3
            or not all(_finite(value) for value in translation)
            or not isinstance(rotation, list) or len(rotation) != 4
            or not all(_finite(value) for value in rotation)):
        _add_failure(failures, 'tf_measurement_missing:' + scene)
    elif abs(math.sqrt(sum(value * value for value in rotation)) - 1.0) > 1e-3:
        _add_failure(failures, 'tf_quaternion_not_normalized:' + scene)
    if tf_data.get('independent_extrinsics_validated') is not True:
        _add_failure(failures, 'extrinsics_unvalidated:' + scene)
    if (not isinstance(tf_data.get('measurement_owner'), str)
            or not tf_data.get('measurement_owner')
            or not isinstance(tf_data.get('measurement_source'), str)
            or not tf_data.get('measurement_source')
            or not isinstance(tf_data.get('measurement_reference_sha256'), str)
            or len(tf_data.get('measurement_reference_sha256')) != 64
            or not _finite(tf_data.get('measured_at_unix_sec'), 0.0)):
        _add_failure(failures, 'extrinsics_reference_missing:' + scene)
    translation_error = tf_data.get('translation_error_m')
    rotation_error = tf_data.get('rotation_error_rad')
    translation_tolerance = tf_data.get('translation_tolerance_m')
    rotation_tolerance = tf_data.get('rotation_tolerance_rad')
    if (not _finite(translation_error, 0.0)
            or not _finite(rotation_error, 0.0)
            or not _finite(translation_tolerance, 0.0)
            or not _finite(rotation_tolerance, 0.0)):
        _add_failure(failures, 'extrinsics_measurement_missing:' + scene)
    elif (translation_tolerance > MAX_EXTRINSIC_TRANSLATION_TOLERANCE_M
          or rotation_tolerance > MAX_EXTRINSIC_ROTATION_TOLERANCE_RAD):
        _add_failure(failures, 'extrinsics_tolerance_too_loose:' + scene)
    elif (translation_error > translation_tolerance
          or rotation_error > rotation_tolerance):
        _add_failure(failures, 'extrinsics_tolerance_exceeded:' + scene)
    return {
        'parent': tf_data.get('parent'),
        'child': tf_data.get('child'),
        'translation_m': tf_data.get('translation_m'),
        'rotation_xyzw': tf_data.get('rotation_xyzw'),
        'independent_extrinsics_validated': (
            tf_data.get('independent_extrinsics_validated') is True),
    }


def _check_extrinsics_reference(
        bundle_path: Path, declaration, scene_tf_data: Mapping,
        hardware_path: Optional[Path], failures: List[str],
        bindings: List[Mapping], seen_paths: Dict[str, str]) -> Mapping:
    path = _artifact(
        bundle_path, declaration, 'extrinsics_measurement_reference',
        failures, bindings, seen_paths)
    if path is None:
        _add_failure(failures, 'missing_extrinsics_reference_artifact')
        return {}
    reference_sha = sha256_file(path)
    for scene, tf_data in scene_tf_data.items():
        if (not isinstance(tf_data, Mapping)
                or tf_data.get('measurement_reference_sha256')
                != reference_sha):
            _add_failure(
                failures, 'extrinsics_reference_hash_mismatch:' + scene)
    hardware = _load_json(
        hardware_path, 'hardware_readiness_reference', failures)
    checks = _hardware_check_map(hardware) if isinstance(
        hardware, Mapping) else {}
    measured = checks.get(
        'camera_extrinsics_match_measurement', {}).get('measured')
    if (not isinstance(measured, Mapping)
            or measured.get('measurement_reference_sha256')
            != reference_sha):
        _add_failure(failures, 'hardware_extrinsics_reference_mismatch')
    return {'sha256': reference_sha, 'size_bytes': path.stat().st_size}


def _quaternion_to_rpy(rotation):
    if (not isinstance(rotation, list) or len(rotation) != 4
            or not all(_finite(value) for value in rotation)):
        return None
    x, y, z, w = rotation
    sin_roll = 2.0 * (w * x + y * z)
    cos_roll = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sin_roll, cos_roll)
    sin_pitch = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sin_pitch) if abs(
        sin_pitch) >= 1.0 else math.asin(sin_pitch)
    sin_yaw = 2.0 * (w * z + x * y)
    cos_yaw = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(sin_yaw, cos_yaw)
    return [roll, pitch, yaw]


def _check_tf_time_binding(
        scene: str, arrangement: Mapping, tf_data: Mapping,
        failures: List[str], now_unix_sec: float) -> None:
    if not isinstance(arrangement, Mapping) or not isinstance(tf_data, Mapping):
        return
    measured = tf_data.get('measured_at_unix_sec')
    end = arrangement.get('ended_unix_sec')
    if (not _finite(measured, 0.0) or not _finite(end, 0.0)
            or measured > end or end - measured > 30 * 24 * 60 * 60):
        _add_failure(failures, 'tf_measurement_stale_or_future:' + scene)
    elif measured > now_unix_sec + MAX_FUTURE_SKEW_SEC:
        _add_failure(failures, 'tf_measurement_future:' + scene)


def _check_raw_tf_binding(
        scene: str, arrangement: Mapping, raw_report: Mapping,
        tf_data: Mapping, failures: List[str]) -> None:
    graph = raw_report.get('tf_graph') if isinstance(
        raw_report, Mapping) else None
    transforms = graph.get('transforms') if isinstance(
        graph, Mapping) else None
    if not isinstance(transforms, list) or not transforms:
        _add_failure(failures, 'raw_tf_evidence_missing:' + scene)
        return
    parent = tf_data.get('parent') if isinstance(tf_data, Mapping) else None
    child = tf_data.get('child') if isinstance(tf_data, Mapping) else None
    if (parent != graph.get('base_frame')
            or child != graph.get('camera_frame')):
        _add_failure(failures, 'raw_tf_artifact_chain_mismatch:' + scene)
        return
    composed = graph.get('base_to_camera_transform')
    declared_translation = tf_data.get('translation_m')
    declared_rotation = tf_data.get('rotation_xyzw')
    if (not isinstance(composed, Mapping)
            or any(abs(first - second) > 1e-6 for first, second in zip(
                composed.get('translation_m', []),
                declared_translation or []))
            or any(abs(first - second) > 1e-6 for first, second in zip(
                composed.get('rotation_xyzw', []),
                declared_rotation or []))
            or len(composed.get('translation_m', [])) != 3
            or len(composed.get('rotation_xyzw', [])) != 4):
        _add_failure(failures, 'raw_tf_artifact_numeric_mismatch:' + scene)
    start = arrangement.get('started_unix_sec') if isinstance(
        arrangement, Mapping) else None
    end = arrangement.get('ended_unix_sec') if isinstance(
        arrangement, Mapping) else None
    dynamic = [
        item for item in transforms
        if isinstance(item, Mapping) and item.get('topic') == '/tf']
    if (not _finite(start, 0.0) or not _finite(end, 0.0)
            or not dynamic or any(
                not isinstance(item.get('stamp_ns'), int)
                or item.get('stamp_ns') / 1e9 < float(start)
                or item.get('stamp_ns') / 1e9 > float(end)
                for item in dynamic)):
        _add_failure(failures, 'raw_tf_time_window_mismatch:' + scene)


def _scene_camera_frame(frames: Sequence[Mapping]) -> Optional[str]:
    frame_ids = {
        frame.get('frame_id') for frame in frames
        if isinstance(frame, Mapping) and isinstance(
            frame.get('frame_id'), str) and frame.get('frame_id')}
    return next(iter(frame_ids)) if len(frame_ids) == 1 else None


def _check_frame_chain(
        scene: str, frames: Sequence[Mapping], rgbd_report: Mapping,
        tf_report: Mapping, failures: List[str]) -> None:
    frame_id = _scene_camera_frame(frames)
    if frame_id is None:
        _add_failure(failures, 'frame_id_not_consistent:' + scene)
        return
    rgbd_frames = rgbd_report.get('frame_ids')
    if not isinstance(rgbd_frames, list) or rgbd_frames != [frame_id]:
        _add_failure(failures, 'frame_rgbd_binding_mismatch:' + scene)
    if tf_report.get('child') != frame_id:
        _add_failure(failures, 'tf_frame_binding_mismatch:' + scene)


def _check_xyz(
        scene: str, xyz: Mapping, expected_instances: Sequence[Mapping],
        instance_matches: Mapping, tf_data: Mapping,
        failures: List[str]) -> Mapping:
    if not isinstance(xyz, Mapping):
        _add_failure(failures, 'missing_xyz_ground_truth:' + scene)
        return {}
    if set(xyz) != {
            'schema_version', 'capture_provenance', 'frame_id', 'units',
            'measurement_method', 'samples'}:
        _add_failure(failures, 'xyz_artifact_schema_invalid:' + scene)
    if xyz.get('schema_version') != 1:
        _add_failure(failures, 'invalid_xyz_schema:' + scene)
    if xyz.get('frame_id') != EXPECTED_BASE_FRAME or xyz.get('units') != 'm':
        _add_failure(failures, 'xyz_frame_or_units_mismatch:' + scene)
    if not isinstance(xyz.get('measurement_method'), str) or not xyz.get(
            'measurement_method'):
        _add_failure(failures, 'xyz_measurement_method_missing:' + scene)
    samples = xyz.get('samples')
    errors = []
    expected_keys = {
        (item.get('sequence'), item.get('stamp_ns'), item.get('instance_id'),
         item.get('object_class'))
        for item in expected_instances}
    if not isinstance(samples, list) or len(samples) != len(expected_keys):
        _add_failure(failures, 'xyz_samples_incomplete:' + scene)
        samples = []
    sample_keys = set()
    for item in samples:
        if not isinstance(item, Mapping):
            continue
        prediction_camera = item.get('predicted_camera_xyz_m')
        prediction = item.get('predicted_base_xyz_m')
        truth = item.get('truth_xyz_m')
        if (not isinstance(prediction_camera, list)
                or len(prediction_camera) != 3
                or not isinstance(prediction, list) or len(prediction) != 3
                or not isinstance(truth, list) or len(truth) != 3
                or not all(_finite(value) for value in (
                    prediction_camera + prediction + truth))):
            continue
        sample_keys.add((
            item.get('sequence'), _stamp_ns(item.get('stamp')),
            item.get('instance_id'), item.get('object_class')))
        key = (
            item.get('sequence'), _stamp_ns(item.get('stamp')),
            item.get('instance_id'), item.get('object_class'))
        match = instance_matches.get(key) if isinstance(
            instance_matches, Mapping) else None
        if (not isinstance(match, Mapping)
                or item.get('observation_id') != match.get('observation_id')
                or not isinstance(match.get('prediction_position'), Mapping)
                or not all(_finite(
                    match['prediction_position'].get(axis)) for axis in 'xyz')
                or any(abs(first - second) > 1e-6 for first, second in zip(
                    prediction_camera, [match['prediction_position'][axis]
                                        for axis in 'xyz']))):
            _add_failure(failures, 'xyz_prediction_binding_mismatch:' + scene)
        expected_camera_frame = tf_data.get('child') if isinstance(
            tf_data, Mapping) else None
        if (not isinstance(item.get('predicted_camera_frame'), str)
                or not item.get('predicted_camera_frame')
                or item.get('predicted_camera_frame') != expected_camera_frame):
            _add_failure(failures, 'xyz_camera_frame_mismatch:' + scene)
        transformed = _transform_point(
            prediction_camera, tf_data.get('translation_m'),
            tf_data.get('rotation_xyzw')) if isinstance(
                tf_data, Mapping) else None
        if (transformed is None or any(
                abs(first - second) > 1e-6
                for first, second in zip(prediction, transformed))):
            _add_failure(failures, 'xyz_tf_transform_mismatch:' + scene)
        errors.append(math.sqrt(sum(
            (predicted - expected) ** 2
            for predicted, expected in zip(prediction, truth))))
    summary = _distribution(errors)
    if summary['samples'] != len(samples):
        _add_failure(failures, 'xyz_samples_invalid:' + scene)
    if sample_keys != expected_keys:
        _add_failure(failures, 'xyz_ground_truth_binding_mismatch:' + scene)
    if errors and (summary['p95'] is None or summary['p95'] > MAX_XYZ_ERROR_M
                   or summary['max'] is None
                   or summary['max'] > MAX_XYZ_ERROR_M):
        _add_failure(failures, 'xyz_error_exceeded:' + scene)
    return summary


def _transform_point(point, translation, rotation):
    if (not isinstance(point, list) or len(point) != 3
            or not isinstance(translation, list) or len(translation) != 3
            or not isinstance(rotation, list) or len(rotation) != 4
            or not all(_finite(value) for value in (
                point + translation + rotation))):
        return None
    x, y, z, w = rotation
    px, py, pz = point
    tx = 2.0 * (y * pz - z * py)
    ty = 2.0 * (z * px - x * pz)
    tz = 2.0 * (x * py - y * px)
    rotated = [
        px + w * tx + (y * tz - z * ty),
        py + w * ty + (z * tx - x * tz),
        pz + w * tz + (x * ty - y * tx),
    ]
    return [rotated[index] + translation[index] for index in range(3)]


def _read_raw_depth_messages(
        storage_path: Optional[Path], bundles: Sequence[Mapping],
        failures: List[str], scene: str) -> Mapping:
    """Read only the canonical accepted depth BLOBs for offline remeasurement."""
    if storage_path is None or not isinstance(bundles, list):
        _add_failure(failures, 'raw_depth_payload_missing:' + scene)
        return {}
    expected = {}
    for bundle in bundles:
        if not isinstance(bundle, Mapping):
            continue
        message_id = bundle.get('aligned_depth')
        if (not isinstance(message_id, int) or isinstance(message_id, bool)
                or message_id <= 0 or message_id in expected):
            _add_failure(failures, 'raw_depth_payload_identity_invalid:' + scene)
            return {}
        expected[message_id] = bundle
    if not expected:
        _add_failure(failures, 'raw_depth_payload_missing:' + scene)
        return {}
    try:
        uri = storage_path.resolve(strict=True).as_uri() + '?mode=ro&immutable=1'
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only = ON')
            rows = list(connection.execute(
                'SELECT messages.id AS message_id, topics.name AS topic, '
                'messages.data AS data FROM messages JOIN topics ON '
                'topics.id = messages.topic_id WHERE messages.id IN ({}) '
                'ORDER BY messages.id'.format(
                    ','.join('?' for _ in expected)), tuple(expected)))
        finally:
            connection.close()
    except (OSError, sqlite3.Error, RuntimeError):
        _add_failure(failures, 'raw_depth_payload_read_failed:' + scene)
        return {}
    decoded_by_bundle = {}
    for row in rows:
        message_id = row['message_id']
        bundle = expected.get(message_id)
        payload = row['data']
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        try:
            decoded = decode_image_pixels(payload)
        except (TypeError, ValueError):
            _add_failure(failures, 'raw_depth_payload_decode_failed:' + scene)
            return {}
        expected_hash = bundle.get(
            'stream_payload_sha256', {}).get('aligned_depth')
        expected_size = bundle.get(
            'stream_serialized_size_bytes', {}).get('aligned_depth')
        expected_stamp = bundle.get(
            'header_stamps_ns', {}).get('aligned_depth')
        if (row['topic'] != '/camera/depth/image_raw'
                or hashlib.sha256(payload).hexdigest() != expected_hash
                or len(payload) != expected_size
                or decoded.get('stamp_ns') != expected_stamp):
            _add_failure(failures, 'raw_depth_payload_binding_mismatch:' + scene)
            return {}
        decoded_by_bundle[bundle.get('index')] = {
            'bundle': bundle, 'image': decoded}
    if len(decoded_by_bundle) != len(expected):
        _add_failure(failures, 'raw_depth_payload_missing:' + scene)
        return {}
    return decoded_by_bundle


def _raw_stream_identity(bundle: Mapping, stream: str) -> Optional[Mapping]:
    if not isinstance(bundle, Mapping) or stream not in REQUIRED_STREAMS:
        return None
    return {
        'bundle_index': bundle.get('index'),
        'message_id': bundle.get(stream),
        'header_stamp_ns': bundle.get(
            'header_stamps_ns', {}).get(stream),
        'payload_sha256': bundle.get(
            'stream_payload_sha256', {}).get(stream),
        'serialized_size_bytes': bundle.get(
            'stream_serialized_size_bytes', {}).get(stream),
    }


def _depth_roi_measurement(image: Mapping, roi_xyxy) -> Optional[Mapping]:
    if (not isinstance(image, Mapping) or not isinstance(roi_xyxy, list)
            or len(roi_xyxy) != 4
            or any(not isinstance(value, int) or isinstance(value, bool)
                   for value in roi_xyxy)):
        return None
    width = image.get('width')
    height = image.get('height')
    x1, y1, x2, y2 = roi_xyxy
    if (not isinstance(width, int) or not isinstance(height, int)
            or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height)):
        return None
    encoding = image.get('encoding')
    if encoding in ('16UC1', 'mono16'):
        code = 'H'
        bytes_per_pixel = 2
        scale = 0.001
    elif encoding == '32FC1':
        code = 'f'
        bytes_per_pixel = 4
        scale = 1.0
    else:
        return None
    endian = '>' if image.get('is_bigendian') == 1 else '<'
    step = image.get('step')
    data = image.get('data')
    if (not isinstance(step, int) or step < width * bytes_per_pixel
            or not isinstance(data, bytes) or len(data) != step * height):
        return None
    values = []
    total = (x2 - x1) * (y2 - y1)
    for y in range(y1, y2):
        row_offset = y * step
        for x in range(x1, x2):
            offset = row_offset + x * bytes_per_pixel
            value = struct.unpack_from(endian + code, data, offset)[0] * scale
            if math.isfinite(value) and 0.30 <= value <= 3.00:
                values.append(float(value))
    return {
        'valid_pixel_count': len(values),
        'total_pixel_count': total,
        'valid_ratio': len(values) / total if total else None,
        'measured_depth_m': median(values) if values else None,
        'depth_encoding': encoding,
        'depth_scale_m': scale,
    }


def _prediction_roi(bbox, width: int, height: int) -> Optional[List[int]]:
    if (not isinstance(bbox, list) or len(bbox) != 4
            or not all(_finite(value) for value in bbox)):
        return None
    x1 = max(0, min(width, int(math.floor(bbox[0]))))
    y1 = max(0, min(height, int(math.floor(bbox[1]))))
    x2 = max(0, min(width, int(math.ceil(bbox[2]))))
    y2 = max(0, min(height, int(math.ceil(bbox[3]))))
    if x2 <= x1 or y2 <= y1:
        return None
    box_width = x2 - x1
    box_height = y2 - y1
    roi_x1 = x1 + int(math.floor(box_width * 0.30))
    roi_y1 = y1 + int(math.floor(box_height * 0.30))
    roi_x2 = x1 + int(math.ceil(box_width * 0.70))
    roi_y2 = y1 + int(math.ceil(box_height * 0.70))
    roi_x1 = max(x1, min(x2 - 1, roi_x1))
    roi_y1 = max(y1, min(y2 - 1, roi_y1))
    roi_x2 = max(roi_x1 + 1, min(x2, roi_x2))
    roi_y2 = max(roi_y1 + 1, min(y2, roi_y2))
    return [roi_x1, roi_y1, roi_x2, roi_y2]


def _check_depth_measurement_reference(
        scene: str, reference: Mapping, arrangement: Mapping,
        expected_provenance: Mapping, expected_frame_keys: Sequence[Tuple],
        artifact_sha256: Optional[str], failures: List[str],
        now_unix_sec: float) -> Tuple[Mapping, Mapping]:
    """Validate independently reviewed per-frame expected depth evidence."""
    expected_keys = {
        'schema_version', 'capture_provenance', 'scene', 'capture_id',
        'capture_window', 'units', 'independent_measurement',
        'measurement_owner', 'reviewer', 'reviewed_at_unix_sec', 'samples'}
    if not isinstance(reference, Mapping):
        _add_failure(
            failures, 'depth_measurement_reference_incomplete:' + scene)
        return {}, {}
    if set(reference) != expected_keys:
        _add_failure(
            failures, 'depth_measurement_reference_schema_invalid:' + scene)
    if reference.get('schema_version') != 1:
        _add_failure(
            failures, 'invalid_depth_measurement_reference_schema:' + scene)
    expected_window = ({
        'started_unix_sec': float(arrangement.get('started_unix_sec')),
        'ended_unix_sec': float(arrangement.get('ended_unix_sec')),
    } if isinstance(arrangement, Mapping)
        and _finite(arrangement.get('started_unix_sec'), 0.0)
        and _finite(arrangement.get('ended_unix_sec'), 0.0) else None)
    if (reference.get('capture_provenance') != expected_provenance
            or reference.get('scene') != scene
            or not isinstance(arrangement, Mapping)
            or reference.get('capture_id') != arrangement.get('capture_id')
            or reference.get('capture_window') != expected_window
            or reference.get('units') != 'm'
            or not _lower_sha256(artifact_sha256)):
        _add_failure(
            failures, 'depth_measurement_reference_binding_mismatch:' + scene)
    owner = reference.get('measurement_owner')
    reviewer = reference.get('reviewer')
    operator = arrangement.get('operator') if isinstance(
        arrangement, Mapping) else None
    arrangement_reviewer = arrangement.get('reviewer') if isinstance(
        arrangement, Mapping) else None
    if (reference.get('independent_measurement') is not True
            or any(not isinstance(value, str) or not value for value in (
                operator, arrangement_reviewer, owner, reviewer))
            or owner == operator or reviewer == owner):
        _add_failure(
            failures, 'depth_measurement_independence_not_proven:' + scene)
    reviewed = reference.get('reviewed_at_unix_sec')
    capture_end = arrangement.get('ended_unix_sec') if isinstance(
        arrangement, Mapping) else None
    if (not _finite(reviewed, 0.0) or not _finite(capture_end, 0.0)
            or reviewed < capture_end
            or reviewed - capture_end > 30 * 24 * 60 * 60
            or reviewed > now_unix_sec + MAX_FUTURE_SKEW_SEC):
        _add_failure(
            failures, 'depth_measurement_review_time_invalid:' + scene)

    expected_frame_keys = set(expected_frame_keys)
    samples = reference.get('samples')
    samples_by_key = {}
    reference_ids = set()
    if (not isinstance(samples, list)
            or len(samples) != len(expected_frame_keys)
            or len(samples) < MIN_UNIQUE_FRAMES):
        _add_failure(
            failures, 'depth_measurement_reference_incomplete:' + scene)
        samples = []
    sample_keys = {
        'sequence', 'stamp', 'reference_id', 'measurement_method',
        'expected_depth_m'}
    for sample in samples:
        if not isinstance(sample, Mapping) or set(sample) != sample_keys:
            _add_failure(
                failures,
                'depth_measurement_reference_sample_invalid:' + scene)
            continue
        key = (sample.get('sequence'), _stamp_ns(sample.get('stamp')))
        reference_id = sample.get('reference_id')
        measurement_method = sample.get('measurement_method')
        expected_depth = sample.get('expected_depth_m')
        if (key in samples_by_key or key not in expected_frame_keys
                or not isinstance(reference_id, str) or not reference_id
                or reference_id in reference_ids
                or not isinstance(measurement_method, str)
                or not measurement_method
                or not _finite(expected_depth, 0.0)):
            _add_failure(
                failures,
                'depth_measurement_reference_sample_invalid:' + scene)
            continue
        reference_ids.add(reference_id)
        samples_by_key[key] = {
            'reference_id': reference_id,
            'measurement_method': measurement_method,
            'expected_depth_m': float(expected_depth),
        }
    coverage_matches = set(samples_by_key) == expected_frame_keys
    if not coverage_matches:
        _add_failure(
            failures,
            'depth_measurement_reference_coverage_mismatch:' + scene)
    return {
        'artifact_sha256': artifact_sha256,
        'sample_count': len(samples_by_key),
        'coverage_matches': coverage_matches,
        'measurement_owner': owner,
        'reviewer': reviewer,
    }, samples_by_key


def _check_depth(
        scene: str, depth: Mapping, expected_instances: Sequence[Mapping],
        instance_matches: Mapping, raw_bundles_by_truth_key: Mapping,
        raw_depth_images: Mapping, depth_reference_sha256: Optional[str],
        depth_reference_samples: Mapping,
        failures: List[str]) -> Mapping:
    if not isinstance(depth, Mapping):
        _add_failure(failures, 'depth_quality_incomplete:' + scene)
        return {}
    if set(depth) != {
            'schema_version', 'capture_provenance',
            'projection_min_valid_ratio', 'target_roi_samples',
            'known_distance_samples', 'expected_target_samples',
            'valid_target_samples'}:
        _add_failure(failures, 'depth_artifact_schema_invalid:' + scene)
    if depth.get('schema_version') != 2:
        _add_failure(failures, 'invalid_depth_schema:' + scene)
    roi_samples = depth.get('target_roi_samples')
    known_samples = depth.get('known_distance_samples')
    expected_targets = depth.get('expected_target_samples')
    valid_targets = depth.get('valid_target_samples')
    if (not isinstance(roi_samples, list)
            or len(roi_samples) != len(expected_instances)
            or not isinstance(known_samples, list)
            or len(known_samples) != len(raw_bundles_by_truth_key)
            or len(known_samples) < MIN_UNIQUE_FRAMES
            or not isinstance(expected_targets, int)
            or isinstance(expected_targets, bool) or expected_targets < 0
            or not isinstance(valid_targets, int)
            or isinstance(valid_targets, bool) or valid_targets < 0
            or valid_targets > expected_targets
            or expected_targets != len(expected_instances)):
        _add_failure(failures, 'depth_quality_incomplete:' + scene)
    expected_keys = {
        (item.get('sequence'), item.get('stamp_ns'), item.get('instance_id'),
         item.get('object_class'))
        for item in expected_instances}
    observed_keys = set()
    ratio_values = []
    for item in roi_samples if isinstance(roi_samples, list) else []:
        if not isinstance(item, Mapping):
            continue
        observed_keys.add((
            item.get('sequence'), _stamp_ns(item.get('stamp')),
            item.get('instance_id'), item.get('object_class')))
        key = (
            item.get('sequence'), _stamp_ns(item.get('stamp')),
            item.get('instance_id'), item.get('object_class'))
        match = instance_matches.get(key) if isinstance(
            instance_matches, Mapping) else None
        truth_key = (item.get('sequence'), _stamp_ns(item.get('stamp')))
        bundle = raw_bundles_by_truth_key.get(truth_key) if isinstance(
            raw_bundles_by_truth_key, Mapping) else None
        raw_image = raw_depth_images.get(
            bundle.get('index')) if isinstance(bundle, Mapping) and isinstance(
                raw_depth_images, Mapping) else None
        image = raw_image.get('image') if isinstance(raw_image, Mapping) else None
        roi = _prediction_roi(
            match.get('prediction_bbox') if isinstance(match, Mapping) else None,
            image.get('width') if isinstance(image, Mapping) else 0,
            image.get('height') if isinstance(image, Mapping) else 0)
        measured = _depth_roi_measurement(image, roi)
        if (not isinstance(match, Mapping)
                or item.get('observation_id') != match.get('observation_id')
                or measured is None
                or not _finite(item.get('depth_valid_ratio'))
                or abs(item.get('depth_valid_ratio')
                       - match.get('prediction_depth_valid_ratio', -1.0)) > 1e-6
                or abs(item.get('depth_valid_ratio')
                       - measured.get('valid_ratio', -1.0)) > 1e-6
                or not _finite(item.get('depth_m'))
                or abs(item.get('depth_m')
                       - match.get('prediction_depth_m', -1.0)) > 1e-6
                or measured.get('measured_depth_m') is None
                or abs(item.get('depth_m')
                       - measured.get('measured_depth_m')) > 1e-6):
            _add_failure(failures, 'depth_prediction_binding_mismatch:' + scene)
        ratio_values.append(item.get('depth_valid_ratio'))
    ratios = _distribution(ratio_values)
    errors = []
    known_keys = set()
    reference_ids = set()
    for sample in known_samples if isinstance(known_samples, list) else []:
        if (not isinstance(sample, Mapping)
                or set(sample) != {
                    'sequence', 'stamp', 'reference_id', 'roi_xyxy',
                    'measurement_method', 'measurement_reference_sha256',
                    'estimator', 'raw_depth', 'depth_encoding',
                    'depth_scale_m', 'valid_pixel_count',
                    'total_pixel_count', 'valid_ratio',
                    'expected_depth_m', 'measured_depth_m',
                    'absolute_error_m'}):
            _add_failure(failures, 'known_depth_sample_schema_invalid:' + scene)
            continue
        key = (sample.get('sequence'), _stamp_ns(sample.get('stamp')))
        reference_id = sample.get('reference_id')
        bundle = raw_bundles_by_truth_key.get(key) if isinstance(
            raw_bundles_by_truth_key, Mapping) else None
        raw_depth = sample.get('raw_depth')
        expected_raw = _raw_stream_identity(bundle, 'aligned_depth')
        raw_image = raw_depth_images.get(
            bundle.get('index')) if isinstance(bundle, Mapping) and isinstance(
                raw_depth_images, Mapping) else None
        measured = _depth_roi_measurement(
            raw_image.get('image') if isinstance(raw_image, Mapping) else None,
            sample.get('roi_xyxy'))
        expected_distance = sample.get('expected_depth_m')
        observed_distance = sample.get('measured_depth_m')
        declared_error = sample.get('absolute_error_m')
        independent_reference = depth_reference_samples.get(
            key) if isinstance(depth_reference_samples, Mapping) else None
        invalid = (
            key in known_keys or key not in raw_bundles_by_truth_key
            or not isinstance(reference_id, str) or not reference_id
            or reference_id in reference_ids
            or not isinstance(sample.get('measurement_method'), str)
            or not sample.get('measurement_method')
            or not _lower_sha256(
                sample.get('measurement_reference_sha256'))
            or sample.get('measurement_reference_sha256')
            != depth_reference_sha256
            or not isinstance(independent_reference, Mapping)
            or reference_id != independent_reference.get('reference_id')
            or sample.get('measurement_method')
            != independent_reference.get('measurement_method')
            or sample.get('estimator') != 'median_valid_depth_in_roi'
            or not isinstance(raw_depth, Mapping)
            or set(raw_depth) != {
                'bundle_index', 'message_id', 'header_stamp_ns',
                'payload_sha256', 'serialized_size_bytes'}
            or raw_depth != expected_raw
            or not _lower_sha256(raw_depth.get('payload_sha256'))
            or measured is None
            or sample.get('depth_encoding') != measured.get('depth_encoding')
            or not _finite(sample.get('depth_scale_m'))
            or abs(sample.get('depth_scale_m')
                   - measured.get('depth_scale_m')) > 1e-12
            or sample.get('valid_pixel_count') != measured.get(
                'valid_pixel_count')
            or sample.get('total_pixel_count') != measured.get(
                'total_pixel_count')
            or not _finite(sample.get('valid_ratio'), 0.0, 1.0)
            or abs(sample.get('valid_ratio')
                   - measured.get('valid_ratio', -1.0)) > 1e-9
            or not _finite(expected_distance, 0.0)
            or not _finite(independent_reference.get(
                'expected_depth_m') if isinstance(
                    independent_reference, Mapping) else None, 0.0)
            or abs(expected_distance - independent_reference.get(
                'expected_depth_m', -1.0)) > 1e-9
            or not _finite(observed_distance, 0.0)
            or measured.get('measured_depth_m') is None
            or abs(observed_distance - measured['measured_depth_m']) > 1e-9
            or not _finite(declared_error, 0.0)
            or abs(declared_error
                   - abs(observed_distance - expected_distance)) > 1e-9)
        if invalid:
            _add_failure(failures, 'known_depth_sample_binding_mismatch:' + scene)
            continue
        known_keys.add(key)
        reference_ids.add(reference_id)
        errors.append(declared_error)
    if known_keys != set(raw_bundles_by_truth_key):
        _add_failure(failures, 'known_depth_sample_coverage_mismatch:' + scene)
    if known_keys != set(depth_reference_samples):
        _add_failure(
            failures, 'known_depth_reference_coverage_mismatch:' + scene)
    errors = _distribution(errors)
    if (ratios['samples'] != len(roi_samples)
            if isinstance(roi_samples, list) else True):
        _add_failure(failures, 'invalid_depth_quality_sample:' + scene)
    if observed_keys != expected_keys:
        _add_failure(failures, 'depth_quality_binding_mismatch:' + scene)
    projection_min_ratio = depth.get('projection_min_valid_ratio')
    if (not _finite(projection_min_ratio)
            or abs(projection_min_ratio
                   - MIN_TARGET_ROI_DEPTH_RATIO) > 1e-9):
        _add_failure(failures, 'depth_projection_threshold_mismatch:' + scene)
        projection_min_ratio = MIN_TARGET_ROI_DEPTH_RATIO
    derived_valid_targets = sum(
        _finite(value, projection_min_ratio, 1.0) for value in ratio_values)
    if valid_targets != derived_valid_targets:
        _add_failure(failures, 'depth_valid_count_mismatch:' + scene)
    if expected_targets:
        valid_rate = derived_valid_targets / expected_targets
        if valid_rate < 0.80:
            _add_failure(failures, 'depth_valid_rate_below_threshold:' + scene)
    else:
        valid_rate = 1.0
    if (errors['samples'] == 0 or errors['p95'] is None
            or errors['p95'] > MAX_DEPTH_ERROR_M
            or errors['max'] > MAX_DEPTH_ERROR_M):
        _add_failure(failures, 'known_depth_error_exceeded:' + scene)
    return {
        'target_roi_valid_ratio': ratios,
        'known_distance_error_m': errors,
        'measurement_reference_sha256': depth_reference_sha256,
        'expected_target_samples': expected_targets,
        'valid_target_samples': valid_targets,
        'valid_target_rate': valid_rate,
    }


def _check_latency(
        scene: str, latency: Mapping, frames: Sequence[Mapping],
        failures: List[str], arrangement: Mapping = None,
        now_unix_sec: float = None) -> Mapping:
    if not isinstance(latency, Mapping):
        _add_failure(failures, 'latency_samples_incomplete:' + scene)
        return {}
    if latency.get('clock_domain') != 'system_time_unix':
        _add_failure(failures, 'latency_clock_domain_unproven:' + scene)
    if (latency.get('use_sim_time') is not False
            or latency.get('sensor_stamp_clock') != 'CLOCK_REALTIME'
            or latency.get('receipt_clock') != 'CLOCK_REALTIME'
            or latency.get('synchronization_status') != 'synchronized'
            or latency.get('synchronization_source') not in ('chrony', 'ntp')
            or not _finite(latency.get('verified_at_unix_sec'), 0.0)):
        _add_failure(failures, 'latency_clock_proof_missing:' + scene)
    verified = latency.get('verified_at_unix_sec')
    capture_start = arrangement.get('started_unix_sec') if isinstance(
        arrangement, Mapping) else None
    capture_end = arrangement.get('ended_unix_sec') if isinstance(
        arrangement, Mapping) else None
    if (not _finite(verified, 0.0) or not _finite(capture_start, 0.0)
            or not _finite(capture_end, 0.0)
            or verified > capture_end
            or capture_start - verified > 24 * 60 * 60):
        _add_failure(failures, 'latency_clock_proof_stale_or_future:' + scene)
    if (now_unix_sec is not None and _finite(verified, 0.0)
            and verified > now_unix_sec + MAX_FUTURE_SKEW_SEC):
        _add_failure(failures, 'latency_proof_future:' + scene)
    processing = [frame.get('processing_latency_sec') for frame in frames]
    transport = [frame.get('transport_latency_sec') for frame in frames]
    for frame in frames:
        if not isinstance(frame, Mapping):
            continue
        stamp = _stamp_ns(frame.get('stamp'))
        received = frame.get('received_unix_sec')
        declared = frame.get('transport_latency_sec')
        derived = (received - stamp / 1e9) if (
            stamp is not None and _finite(received)) else None
        if (not _finite(declared, 0.0) or not _finite(derived, 0.0)
                or abs(declared - derived) > 1e-6):
            _add_failure(
                failures, 'transport_latency_binding_mismatch:' + scene)
            break
    processing_summary = _distribution(processing)
    transport_summary = _distribution(transport)
    if processing_summary['samples'] != len(frames):
        _add_failure(failures, 'processing_latency_samples_incomplete:' + scene)
    if transport_summary['samples'] != len(frames):
        _add_failure(failures, 'transport_latency_samples_incomplete:' + scene)
    if (processing_summary['p95'] is None
            or processing_summary['p95'] > MAX_PROCESSING_P95_SEC):
        _add_failure(failures, 'processing_latency_p95_exceeded:' + scene)
    if (processing_summary['max'] is None
            or processing_summary['max'] > MAX_PROCESSING_P95_SEC):
        _add_failure(failures, 'processing_latency_sample_exceeded:' + scene)
    if (transport_summary['p95'] is None
            or transport_summary['p95'] > MAX_TRANSPORT_P95_SEC):
        _add_failure(failures, 'transport_latency_p95_exceeded:' + scene)
    if (transport_summary['max'] is None
            or transport_summary['max'] > MAX_TRANSPORT_P95_SEC):
        _add_failure(failures, 'transport_latency_sample_exceeded:' + scene)
    return {
        'clock_domain': latency.get('clock_domain'),
        'clock_proof': {
            'use_sim_time': latency.get('use_sim_time'),
            'sensor_stamp_clock': latency.get('sensor_stamp_clock'),
            'receipt_clock': latency.get('receipt_clock'),
            'synchronization_source': latency.get('synchronization_source'),
            'synchronization_status': latency.get('synchronization_status'),
        },
        'processing_latency_sec': processing_summary,
        'transport_latency_sec': transport_summary,
    }


def _check_typed_raw_sync_binding(
        scene: str, frames: Sequence[Mapping], raw_report: Mapping,
        binding: Mapping, failures: List[str]) -> None:
    bundles = raw_report.get('bundles') if isinstance(
        raw_report, Mapping) else None
    frame_bindings = binding.get('frame_bindings') if isinstance(
        binding, Mapping) else None
    if not isinstance(bundles, list) or not isinstance(frame_bindings, list):
        _add_failure(failures, 'typed_raw_payload_binding_mismatch:' + scene)
        return
    tf_graph = raw_report.get('tf_graph') if isinstance(
        raw_report, Mapping) else None
    tf_bundles = tf_graph.get('bundle_transforms') if isinstance(
        tf_graph, Mapping) else None
    if not isinstance(tf_bundles, list) or len(tf_bundles) != len(bundles):
        _add_failure(failures, 'typed_raw_tf_binding_mismatch:' + scene)
        return
    raw_by_stamp = {}
    for expected, tf_expected in zip(bundles, tf_bundles):
        stamp = expected.get('header_stamps_ns', {}).get(
            'rgb') if isinstance(expected, Mapping) else None
        if (not isinstance(stamp, int) or isinstance(stamp, bool)
                or stamp <= 0 or stamp in raw_by_stamp):
            _add_failure(failures, 'typed_raw_frame_identity_mismatch:' + scene)
            return
        raw_by_stamp[stamp] = (expected, tf_expected)
    typed_by_stamp = {}
    for row_index, frame in enumerate(frames):
        stamp = _stamp_ns(frame.get('stamp')) if isinstance(
            frame, Mapping) else None
        if stamp is None or stamp in typed_by_stamp:
            _add_failure(failures, 'typed_raw_frame_identity_mismatch:' + scene)
            return
        typed_by_stamp[stamp] = row_index
    intersection = set(typed_by_stamp).intersection(raw_by_stamp)
    if (len(frame_bindings) != len(intersection)
            or binding.get('typed_frame_count') != len(frames)
            or binding.get('raw_bundle_count') != len(bundles)
            or binding.get('unpaired_typed_count')
            != len(frames) - len(intersection)
            or binding.get('unpaired_raw_bundle_count')
            != len(bundles) - len(intersection)):
        _add_failure(failures, 'typed_raw_unpaired_accounting_invalid:' + scene)
    seen_rows = set()
    seen_stamps = set()
    for declared in frame_bindings:
        raw_declared = declared.get('raw_bundle') if isinstance(
            declared, Mapping) else None
        row_index = declared.get('typed_row_index') if isinstance(
            declared, Mapping) else None
        if (not isinstance(row_index, int) or isinstance(row_index, bool)
                or row_index < 0 or row_index >= len(frames)
                or row_index in seen_rows):
            _add_failure(
                failures, 'typed_raw_frame_binding_mismatch:' + scene)
            return
        frame = frames[row_index]
        stamp = _stamp_ns(frame.get('stamp')) if isinstance(
            frame, Mapping) else None
        raw_pair = raw_by_stamp.get(stamp)
        if stamp in seen_stamps or raw_pair is None:
            _add_failure(failures, 'typed_raw_frame_identity_mismatch:' + scene)
            return
        expected, tf_expected = raw_pair
        try:
            frame_sha = hashlib.sha256(json.dumps(
                frame, ensure_ascii=False, sort_keys=True,
                separators=(',', ':')).encode('utf-8')).hexdigest()
        except (TypeError, ValueError):
            frame_sha = None
        if (not _finite(frame.get('sync_span_sec'), 0.0)
                or abs(frame.get('sync_span_sec')
                       - expected.get('stamp_span_sec')) > 1e-6):
            _add_failure(failures, 'typed_raw_sync_binding_mismatch:' + scene)
        if (not isinstance(declared, Mapping)
                or declared.get('typed_row_index') != row_index
                or declared.get('sequence') != frame.get('sequence')
                or declared.get('stamp_ns') != _stamp_ns(frame.get('stamp'))
                or declared.get('frame_id') != frame.get('frame_id')
                or declared.get('typed_frame_sha256') != frame_sha
                or not isinstance(raw_declared, Mapping)):
            _add_failure(
                failures, 'typed_raw_frame_binding_mismatch:' + scene)
            break
        seen_rows.add(row_index)
        seen_stamps.add(stamp)
        declared = raw_declared
        if (declared.get('bundle_index') != expected.get('index')
                or declared.get('rgb_header_stamp_ns') != expected.get(
                    'header_stamps_ns', {}).get('rgb')
                or declared.get('header_stamps_ns') != expected.get(
                    'header_stamps_ns')
                or declared.get('stream_message_ids') != {
                    name: expected.get(name) for name in REQUIRED_STREAMS}
                or declared.get('stream_payload_sha256') != expected.get(
                    'stream_payload_sha256')
                or declared.get('stream_serialized_size_bytes') != expected.get(
                    'stream_serialized_size_bytes')
                or declared.get('stream_record_timestamps_ns') != expected.get(
                    'stream_record_timestamps_ns')
                or declared.get('stream_record_header_skew_sec') != expected.get(
                    'stream_record_header_skew_sec')
                or declared.get('record_timestamp_span_sec') != expected.get(
                    'record_timestamp_span_sec')
                or declared.get('sync_span_sec') != expected.get(
                    'stamp_span_sec')):
            _add_failure(
                failures, 'typed_raw_payload_binding_mismatch:' + scene)
            break
        if (declared.get('tf_sample_set_sha256') != tf_expected.get(
                'sample_set_sha256')
                or declared.get('tf_chain_base_to_camera') != tf_expected.get(
                    'chain_base_to_camera')
                or declared.get('tf_max_dynamic_age_sec') != tf_expected.get(
                    'max_dynamic_age_sec')):
            _add_failure(failures, 'typed_raw_tf_binding_mismatch:' + scene)
            break
    if seen_stamps != intersection:
        _add_failure(failures, 'typed_raw_frame_identity_mismatch:' + scene)


def _check_typed_raw_binding_artifact(
        scene: str, binding: Mapping, arrangement: Mapping,
        frames_path: Optional[Path], manifest_path: Optional[Path],
        raw_storage_path: Optional[Path], raw_inspection_path: Optional[Path],
        release_binding: Mapping,
        model_hashes: Mapping, expected_task_id: Optional[str],
        failures: List[str]) -> Mapping:
    expected_keys = {
        'schema_version', 'read_only', 'authorizes_motion',
        'publishes_ros_messages', 'capture_binding_id', 'capture_id',
        'scene', 'task_id', 'capture_window', 'release_id',
        'source_set_sha256', 'model_sha256', 'typed_frames',
        'collector_manifest', 'raw_capture', 'raw_inspection',
        'expected_topic_manifest', 'frame_bindings', 'typed_frame_count',
        'raw_bundle_count', 'unpaired_typed_count',
        'unpaired_raw_bundle_count', 'unpaired_rate'}
    if (not isinstance(binding, Mapping) or set(binding) != expected_keys
            or binding.get('schema_version') != 1
            or binding.get('read_only') is not True
            or binding.get('authorizes_motion') is not False
            or binding.get('publishes_ros_messages') is not False):
        _add_failure(failures, 'typed_raw_binding_schema_invalid:' + scene)
        return {}
    if _contains_forbidden_control_claim(binding):
        _add_failure(failures, 'typed_raw_binding_control_claim:' + scene)
    capture_window = binding.get('capture_window')
    if (not isinstance(arrangement, Mapping)
            or binding.get('capture_id') != arrangement.get('capture_id')
            or binding.get('scene') != scene
            or capture_window != {
                'started_unix_sec': float(arrangement.get(
                    'started_unix_sec', -1.0)),
                'ended_unix_sec': float(arrangement.get(
                    'ended_unix_sec', -1.0)),
            }):
        _add_failure(failures, 'typed_raw_capture_binding_mismatch:' + scene)
    if (not isinstance(expected_task_id, str) or not expected_task_id
            or binding.get('task_id') != expected_task_id):
        _add_failure(failures, 'typed_raw_task_id_mismatch:' + scene)
    if (binding.get('release_id') != release_binding.get('release_id')
            or binding.get('source_set_sha256') != release_binding.get(
                'source_set_sha256')
            or binding.get('model_sha256') != model_hashes):
        _add_failure(failures, 'typed_raw_release_binding_mismatch:' + scene)
    path_bindings = (
        ('typed_frames', frames_path),
        ('collector_manifest', manifest_path),
        ('raw_capture', raw_storage_path),
        ('raw_inspection', raw_inspection_path),
    )
    for name, path in path_bindings:
        declared = binding.get(name)
        if (path is None or not isinstance(declared, Mapping)
                or declared.get('path') != str(path.resolve())
                or declared.get('size_bytes') != path.stat().st_size
                or declared.get('sha256') != sha256_file(path)):
            _add_failure(
                failures, 'typed_raw_artifact_binding_mismatch:{}:{}'.format(
                    scene, name))
    envelope = {
        key: binding.get(key) for key in (
            'capture_id', 'scene', 'task_id', 'capture_window', 'release_id',
            'source_set_sha256', 'model_sha256', 'typed_frames',
            'collector_manifest', 'raw_capture', 'raw_inspection',
            'expected_topic_manifest')}
    frozen_manifest = load_topic_manifest(default_topic_manifest_path())
    expected_manifest_binding = {
        key: frozen_manifest[key] for key in (
            'manifest_id', 'schema_version', 'size_bytes', 'sha256')}
    if binding.get('expected_topic_manifest') != expected_manifest_binding:
        _add_failure(failures, 'typed_raw_topic_manifest_mismatch:' + scene)
    try:
        canonical = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode('utf-8')
        expected_id = hashlib.sha256(canonical).hexdigest()
    except (TypeError, ValueError):
        expected_id = None
    if binding.get('capture_binding_id') != expected_id:
        _add_failure(failures, 'capture_binding_id_mismatch:' + scene)
    typed_count = binding.get('typed_frame_count')
    raw_count = binding.get('raw_bundle_count')
    unpaired_typed = binding.get('unpaired_typed_count')
    unpaired_raw = binding.get('unpaired_raw_bundle_count')
    declared_rate = binding.get('unpaired_rate')
    frame_bindings = binding.get('frame_bindings')
    unpaired_report, accounting_valid, rate_exceeded = (
        _typed_raw_unpaired_report(
            typed_count, raw_count, unpaired_typed, unpaired_raw,
            frame_bindings, declared_rate))
    if not accounting_valid:
        _add_failure(failures, 'typed_raw_unpaired_accounting_invalid:' + scene)
    elif rate_exceeded:
        _add_failure(failures, 'typed_raw_unpaired_rate_exceeded:' + scene)
    return {
        'capture_binding_id': binding.get('capture_binding_id'),
        **unpaired_report,
    }


def _capture_provenance(binding: Mapping) -> Mapping:
    """Return the immutable capture/release identity copied downstream."""
    if not isinstance(binding, Mapping):
        return {}
    return {
        'capture_binding_id': binding.get('capture_binding_id'),
        'capture_id': binding.get('capture_id'),
        'scene': binding.get('scene'),
        'task_id': binding.get('task_id'),
        'capture_window': binding.get('capture_window'),
        'release_id': binding.get('release_id'),
        'source_set_sha256': binding.get('source_set_sha256'),
        'model_sha256': binding.get('model_sha256'),
        'raw_capture_sha256': binding.get('raw_capture', {}).get('sha256'),
        'raw_inspection_sha256': binding.get('raw_inspection', {}).get(
            'sha256'),
        'expected_topic_manifest': binding.get('expected_topic_manifest'),
    }


def _check_capture_derived_binding(
        scene: str, value: Mapping, expected_provenance: Mapping,
        failures: List[str], kind: str) -> None:
    declared = value.get('capture_provenance') if isinstance(
        value, Mapping) else None
    if (not isinstance(value, Mapping)
            or not isinstance(expected_provenance, Mapping)
            or not expected_provenance
            or declared != expected_provenance):
        _add_failure(
            failures, 'capture_artifact_binding_mismatch:{}:{}'.format(
                scene, kind))


def _check_capture_time_binding(
        scene: str, arrangement: Mapping, frames: Sequence[Mapping],
        failures: List[str], now_unix_sec: float) -> None:
    if not isinstance(arrangement, Mapping):
        return
    start = arrangement.get('started_unix_sec')
    end = arrangement.get('ended_unix_sec')
    if not _finite(start, 0.0) or not _finite(end, 0.0):
        return
    for frame in frames:
        if not isinstance(frame, Mapping):
            continue
        received = frame.get('received_unix_sec')
        stamp = _stamp_ns(frame.get('stamp'))
        stamp_sec = stamp / 1e9 if stamp is not None else None
        if (not _finite(received, float(start), float(end))
                or stamp_sec is None
                or stamp_sec < float(start) or stamp_sec > float(end)):
            _add_failure(failures, 'frame_outside_capture_window:' + scene)
            return
        if (received > now_unix_sec + MAX_FUTURE_SKEW_SEC
                or stamp_sec > now_unix_sec + MAX_FUTURE_SKEW_SEC):
            _add_failure(failures, 'frame_time_future:' + scene)
            return


def _check_scene_evidence_binding(
        bundle_path: Path, scene: str, declaration: Mapping,
        arrangement: Mapping, capture_provenance: Mapping,
        failures: List[str]) -> Mapping:
    """Bind all per-scene evidence identities and one capture window."""
    expected_keys = {
        'schema_version', 'scene', 'capture_id', 'capture_binding_id',
        'capture_window', 'release_id', 'source_set_sha256', 'model_sha256',
        'raw_capture_sha256', 'raw_inspection_sha256',
        'expected_topic_manifest', 'artifacts'}
    binding = declaration.get('evidence_binding') if isinstance(
        declaration, Mapping) else None
    if not isinstance(binding, Mapping) or set(binding) != expected_keys:
        _add_failure(failures, 'scene_evidence_binding_invalid:' + scene)
        return {}
    expected_window = ({
        'started_unix_sec': float(arrangement.get('started_unix_sec')),
        'ended_unix_sec': float(arrangement.get('ended_unix_sec')),
    } if isinstance(arrangement, Mapping)
        and _finite(arrangement.get('started_unix_sec'), 0.0)
        and _finite(arrangement.get('ended_unix_sec'), 0.0) else None)
    expected_artifacts = {
        name: _artifact_identity_from_declaration(
            bundle_path, declaration.get(field))
        for name, field in (
            ('frames', 'frames'),
            ('collector_manifest', 'collector_manifest'),
            ('typed_raw_binding', 'typed_raw_binding'),
            ('rgbd_artifact', 'rgbd_artifact'),
            ('ground_truth', 'ground_truth'),
            ('tf_artifact', 'tf_artifact'),
            ('xyz_ground_truth', 'xyz_ground_truth'),
            ('depth_measurement_reference',
             'depth_measurement_reference'),
            ('depth_quality', 'depth_quality'))}
    expected = {
        'schema_version': 1,
        'scene': scene,
        'capture_id': arrangement.get('capture_id') if isinstance(
            arrangement, Mapping) else None,
        'capture_binding_id': capture_provenance.get('capture_binding_id'),
        'capture_window': expected_window,
        'release_id': capture_provenance.get('release_id'),
        'source_set_sha256': capture_provenance.get('source_set_sha256'),
        'model_sha256': capture_provenance.get('model_sha256'),
        'raw_capture_sha256': capture_provenance.get('raw_capture_sha256'),
        'raw_inspection_sha256': capture_provenance.get(
            'raw_inspection_sha256'),
        'expected_topic_manifest': capture_provenance.get(
            'expected_topic_manifest'),
        'artifacts': expected_artifacts,
    }
    if binding != expected or any(
            value is None for value in expected_artifacts.values()):
        _add_failure(failures, 'scene_evidence_binding_mismatch:' + scene)
    return binding


def evaluate_readiness(
        bundle_path: Path, payload: Mapping,
        now_unix_sec: float = None,
        expected_model_hashes: Mapping = None,
        canonical_source_binding: Mapping = None,
        canonical_source_audit: Mapping = None,
        allow_test_synthetic_binding: bool = False) -> Mapping:
    """Validate a complete evidence bundle without importing or starting ROS."""
    failures = []
    if now_unix_sec is None:
        now_unix_sec = time.time()
    if not _finite(now_unix_sec, 0.0):
        raise ValueError('now_unix_sec must be a finite Unix timestamp')
    bindings = []
    seen_paths = {}
    required_bundle_keys = {
        'schema_version', 'evidence_scope', 'read_only',
        'authorizes_motion', 'publishes_ros_messages', 'release_binding',
        'software_binding', 'ros1_field_install_validation',
        'hardware_readiness',
        'extrinsics_measurement_reference', 'scenes'}
    allowed_bundle_keys = required_bundle_keys | {'ros_build_validation'}
    if (not isinstance(payload, Mapping)
            or not required_bundle_keys.issubset(payload)
            or not set(payload).issubset(allowed_bundle_keys)):
        _add_failure(failures, 'bundle_schema_invalid')
    if payload.get('schema_version') != 1:
        _add_failure(failures, 'invalid_bundle_schema')
    if payload.get('evidence_scope') != 'formal_four_scene_rgbd_acceptance':
        _add_failure(failures, 'invalid_evidence_scope')
    if payload.get('read_only') is not True:
        _add_failure(failures, 'read_only_contract_violation')
    if payload.get('authorizes_motion') is not False:
        _add_failure(failures, 'motion_authorization_present')
    if payload.get('publishes_ros_messages') is not False:
        _add_failure(failures, 'publisher_contract_violation')
    if any(_contains_forbidden_control_claim(payload.get(key)) for key in (
            'release_binding', 'software_binding', 'ros_build_validation',
            'ros1_field_install_validation', 'hardware_readiness',
            'extrinsics_measurement_reference', 'scenes')):
        _add_failure(failures, 'nested_control_contract_violation')

    release_binding = _release_binding(payload, failures)
    if canonical_source_binding is None:
        try:
            canonical_source_audit = (
                audit_ros1_noetic_field_source_contract())
            canonical_source_binding = make_ros1_canonical_source_binding(
                source_audit=canonical_source_audit, test_only=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            canonical_source_binding = None
            canonical_source_audit = None
    elif (canonical_source_audit is None
          and not allow_test_synthetic_binding):
        try:
            canonical_source_audit = (
                audit_ros1_noetic_field_source_contract())
        except (OSError, RuntimeError, TypeError, ValueError):
            canonical_source_audit = None
    software = _check_software(
        bundle_path, payload, failures, bindings, seen_paths,
        expected_model_hashes, now_unix_sec, release_binding)
    migration_failures = []
    ros_build = _check_ros_build(
        bundle_path, payload.get('ros_build_validation'), migration_failures,
        bindings, seen_paths, now_unix_sec, release_binding)
    ros1_field_install = _check_ros1_field_install(
        bundle_path, payload.get('ros1_field_install_validation'), failures,
        bindings, seen_paths, now_unix_sec, release_binding,
        EXPECTED_MODEL_SHA256 if expected_model_hashes is None
        else expected_model_hashes,
        canonical_source_binding=canonical_source_binding,
        canonical_source_audit=canonical_source_audit,
        allow_test_synthetic_binding=allow_test_synthetic_binding)
    hardware_declaration = payload.get('hardware_readiness')
    hardware_path = _resolve_path(
        bundle_path, hardware_declaration.get('path')) if isinstance(
            hardware_declaration, Mapping) else None
    hardware = _check_hardware(
        bundle_path, hardware_declaration, failures, bindings, seen_paths,
        now_unix_sec)
    scenes = payload.get('scenes')
    if not isinstance(scenes, Mapping):
        scenes = {}
        _add_failure(failures, 'scenes_missing')
    elif set(scenes) != set(SCENES):
        _add_failure(failures, 'scene_set_mismatch')
    capture_ids = set()
    global_observation_ids = set()
    global_truth_instance_ids = set()
    scene_reports = {}
    evaluator_scenes = {}
    arrangements = {}
    raw_fingerprints = set()
    scene_tf_data = {}
    expected_scene_declaration_keys = {
        'arrangement', 'frames', 'collector_manifest',
        'typed_raw_binding', 'rgbd_artifact', 'raw_capture',
        'ground_truth', 'tf_artifact', 'xyz_ground_truth',
        'depth_measurement_reference', 'depth_quality',
        'evidence_binding', 'latency'}

    for scene in SCENES:
        scene_failures = []
        declaration = scenes.get(scene)
        if not isinstance(declaration, Mapping):
            _add_failure(failures, 'missing_scene:' + scene)
            scene_reports[scene] = {
                'passed': False, 'failures': ['missing_scene:' + scene]}
            continue
        if set(declaration) != expected_scene_declaration_keys:
            _add_failure(
                scene_failures, 'scene_declaration_schema_invalid:' + scene)
        arrangement = _check_arrangement(
            scene, declaration.get('arrangement'), scene_failures,
            capture_ids, now_unix_sec)
        arrangements[scene] = arrangement
        capture_end = arrangement.get('ended_unix_sec') if isinstance(
            arrangement, Mapping) else None
        if (not _finite(capture_end, 0.0)
                or now_unix_sec - capture_end > MAX_FIELD_EVIDENCE_AGE_SEC):
            _add_failure(
                scene_failures, 'capture_evidence_stale:' + scene)
        frames_path = _artifact(
            bundle_path, declaration.get('frames'), scene + ':frames',
            scene_failures, bindings, seen_paths)
        manifest_path = _artifact(
            bundle_path, declaration.get('collector_manifest'),
            scene + ':collector_manifest', scene_failures, bindings,
            seen_paths)
        frames = []
        if frames_path is not None:
            try:
                frames = load_formal_typed_records(frames_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                _add_failure(scene_failures, 'invalid_frames_artifact:' + scene)
        identity, identity_failures = _frame_identity(frames)
        _check_typed_frame_schema(scene, frames, scene_failures)
        for code in identity_failures:
            _add_failure(scene_failures, code + ':' + scene)
        if identity['unique_sequences'] < MIN_UNIQUE_FRAMES:
            _add_failure(scene_failures, 'insufficient_unique_frames:' + scene)
        task_ids = {
            frame.get('task_id') for frame in frames
            if isinstance(frame, Mapping) and isinstance(
                frame.get('task_id'), str) and frame.get('task_id')}
        if len(task_ids) != 1 or any(
                not isinstance(frame, Mapping)
                or frame.get('schema_version') != 1
                or frame.get('read_only') is not True
                or not isinstance(frame.get('task_id'), str)
                or not frame.get('task_id')
                for frame in frames):
            _add_failure(scene_failures, 'typed_frame_contract_invalid:' + scene)
        frame_ids = {
            frame.get('frame_id') for frame in frames
            if isinstance(frame, Mapping) and isinstance(
                frame.get('frame_id'), str) and frame.get('frame_id')}
        if len(frame_ids) != 1:
            _add_failure(scene_failures, 'frame_id_not_consistent:' + scene)
        for frame in frames:
            if isinstance(frame, Mapping):
                if frame.get('scene') != scene:
                    _add_failure(scene_failures, 'frame_scene_mismatch:' + scene)
                if frame.get('read_only') is not True:
                    _add_failure(scene_failures, 'frame_read_only_violation:' + scene)
                frame_id = frame.get('frame_id')
                if not isinstance(frame_id, str) or not frame_id:
                    _add_failure(scene_failures, 'frame_id_missing:' + scene)
                for target in frame.get('targets', []):
                    if not isinstance(target, Mapping):
                        continue
                    observation_id = target.get('observation_id')
                    if (isinstance(observation_id, str) and observation_id
                            and observation_id in global_observation_ids):
                        _add_failure(
                            scene_failures,
                            'duplicate_observation_id_across_bundle')
                    elif isinstance(observation_id, str) and observation_id:
                        global_observation_ids.add(observation_id)
        manifest = _load_json(
            manifest_path, scene + ':collector_manifest', scene_failures)
        _check_manifest(
            scene, manifest, frames_path, frames, identity, scene_failures)

        binding_path = _artifact(
            bundle_path, declaration.get('typed_raw_binding'),
            scene + ':typed_raw_binding', scene_failures, bindings,
            seen_paths)
        binding_data = _load_json(
            binding_path, scene + ':typed_raw_binding', scene_failures)

        rgbd_path = _artifact(
            bundle_path, declaration.get('rgbd_artifact'),
            scene + ':rgbd', scene_failures, bindings, seen_paths)
        rgbd = _load_json(rgbd_path, scene + ':rgbd', scene_failures)
        rgbd_report = _check_streams(scene, rgbd, scene_failures)
        raw_capture_report = _check_raw_capture(
            bundle_path, scene, declaration.get('raw_capture'), arrangement,
            rgbd, scene_failures, bindings, seen_paths, raw_fingerprints,
            now_unix_sec)
        raw_declaration = declaration.get('raw_capture')
        raw_storage_declaration = raw_declaration.get(
            'storage_file') if isinstance(raw_declaration, Mapping) else None
        raw_inspection_declaration = raw_declaration.get(
            'inspection') if isinstance(raw_declaration, Mapping) else None
        raw_storage_path = _resolve_path(
            bundle_path, raw_storage_declaration.get(
                'path')) if isinstance(raw_storage_declaration, Mapping) else None
        raw_inspection_path = _resolve_path(
            bundle_path, raw_inspection_declaration.get(
                'path')) if isinstance(
                    raw_inspection_declaration, Mapping) else None
        binding_report = _check_typed_raw_binding_artifact(
            scene, binding_data, arrangement, frames_path, manifest_path,
            raw_storage_path, raw_inspection_path, release_binding,
            software.get('model_sha256', {}),
            next(iter(task_ids)) if len(task_ids) == 1 else None,
            scene_failures)
        capture_provenance = _capture_provenance(binding_data)
        _check_scene_evidence_binding(
            bundle_path, scene, declaration, arrangement,
            capture_provenance, scene_failures)
        _check_typed_raw_sync_binding(
            scene, frames, raw_capture_report, binding_data, scene_failures)
        _check_rgbd_time_binding(
            scene, arrangement, frames, rgbd_report, scene_failures)

        truth_path = _artifact(
            bundle_path, declaration.get('ground_truth'),
            scene + ':ground_truth', scene_failures, bindings, seen_paths)
        truth = _load_json(
            truth_path, scene + ':ground_truth', scene_failures)
        _check_capture_derived_binding(
            scene, truth, capture_provenance,
            scene_failures, 'ground_truth')
        truth_report = _check_ground_truth(
            scene, truth, frames, raw_capture_report.get('bundles', []),
            scene_failures)
        raw_bundles_by_truth_key = truth_report.pop(
            'raw_bundles_by_truth_key', {})
        _check_truth_semantics(scene, truth, scene_failures)
        _check_independent_reviewers(
            scene, arrangement, truth, scene_failures, now_unix_sec)
        truth_instances = _truth_instances(truth)
        for instance in truth_instances:
            instance_id = instance.get('instance_id')
            if (not isinstance(instance_id, str) or not instance_id
                    or instance_id in global_truth_instance_ids):
                _add_failure(
                    scene_failures,
                    'duplicate_ground_truth_instance_id_across_bundle')
            else:
                global_truth_instance_ids.add(instance_id)
        instance_evaluation = _check_instance_metrics(
            scene, truth_instances, frames, scene_failures)

        tf_path = _artifact(
            bundle_path, declaration.get('tf_artifact'),
            scene + ':tf', scene_failures, bindings, seen_paths)
        tf_data = _load_json(tf_path, scene + ':tf', scene_failures)
        _check_capture_derived_binding(
            scene, tf_data, capture_provenance,
            scene_failures, 'tf')
        scene_tf_data[scene] = tf_data
        tf_report = _check_tf(scene, tf_data, scene_failures)
        _check_tf_time_binding(
            scene, arrangement, tf_data, scene_failures, now_unix_sec)
        _check_raw_tf_binding(
            scene, arrangement, raw_capture_report, tf_data,
            scene_failures)
        _check_frame_chain(
            scene, frames, rgbd_report, tf_report, scene_failures)

        xyz_path = _artifact(
            bundle_path, declaration.get('xyz_ground_truth'),
            scene + ':xyz', scene_failures, bindings, seen_paths)
        xyz = _load_json(xyz_path, scene + ':xyz', scene_failures)
        _check_capture_derived_binding(
            scene, xyz, capture_provenance,
            scene_failures, 'xyz')
        xyz_report = _check_xyz(
            scene, xyz, truth_instances,
            instance_evaluation.get('matches', {}), tf_data,
            scene_failures)

        depth_path = _artifact(
            bundle_path, declaration.get('depth_quality'),
            scene + ':depth_quality', scene_failures, bindings, seen_paths)
        depth = _load_json(
            depth_path, scene + ':depth_quality', scene_failures)
        depth_reference_path = _artifact(
            bundle_path, declaration.get('depth_measurement_reference'),
            scene + ':depth_measurement_reference', scene_failures,
            bindings, seen_paths)
        depth_reference = _load_json(
            depth_reference_path, scene + ':depth_measurement_reference',
            scene_failures)
        _check_capture_derived_binding(
            scene, depth, capture_provenance,
            scene_failures, 'depth')
        _check_capture_derived_binding(
            scene, depth_reference, capture_provenance,
            scene_failures, 'depth_measurement_reference')
        _check_capture_derived_binding(
            scene, rgbd, capture_provenance,
            scene_failures, 'rgbd')
        _check_capture_derived_binding(
            scene, declaration.get('latency'),
            capture_provenance, scene_failures,
            'latency')
        raw_depth_images = _read_raw_depth_messages(
            raw_storage_path, raw_capture_report.get('bundles', []),
            scene_failures, scene)
        depth_reference_report, depth_reference_samples = (
            _check_depth_measurement_reference(
                scene, depth_reference, arrangement, capture_provenance,
                raw_bundles_by_truth_key.keys(),
                sha256_file(depth_reference_path)
                if depth_reference_path is not None else None,
                scene_failures, now_unix_sec))
        depth_report = _check_depth(
            scene, depth, truth_instances,
            instance_evaluation.get('matches', {}),
            raw_bundles_by_truth_key,
            raw_depth_images,
            depth_reference_report.get('artifact_sha256'),
            depth_reference_samples, scene_failures)
        latency_report = _check_latency(
            scene, declaration.get('latency'), frames, scene_failures,
            arrangement, now_unix_sec)
        _check_capture_time_binding(
            scene, arrangement, frames, scene_failures, now_unix_sec)

        if frames and not scene_failures:
            evaluator_scenes[scene] = frames
        scene_reports[scene] = {
            'arrangement': arrangement,
            'frame_identity': identity,
            'rgbd': rgbd_report,
            'raw_capture': raw_capture_report,
            'typed_raw_binding': binding_report,
            'ground_truth': truth_report,
            'instance_metrics': instance_evaluation.get('classes', {}),
            'tf': tf_report,
            'xyz_error_m': xyz_report,
            'depth_measurement_reference': depth_reference_report,
            'depth_quality': depth_report,
            'latency': latency_report,
            'passed': not scene_failures,
            'failures': scene_failures,
        }
        for code in scene_failures:
            _add_failure(failures, code)

    _check_arrangement_independence(arrangements, failures)
    capture_starts = [
        value.get('started_unix_sec') for value in arrangements.values()
        if isinstance(value, Mapping) and _finite(
            value.get('started_unix_sec'), 0.0)]
    if capture_starts:
        earliest_capture = min(capture_starts)
        for report_name, declaration in (
                ('runtime', payload.get('software_binding', {}).get(
                    'runtime_preflight') if isinstance(
                        payload.get('software_binding'), Mapping) else None),
                ('ros1_field_install', payload.get(
                    'ros1_field_install_validation'))):
            path = _resolve_path(
                bundle_path, declaration.get('path')) if isinstance(
                    declaration, Mapping) else None
            report_data = _load_json(path, report_name + '_time_binding', failures)
            generated = report_data.get('generated_at_unix_sec') if isinstance(
                report_data, Mapping) else None
            if not _finite(generated, 0.0, earliest_capture):
                _add_failure(
                    failures, report_name + '_after_capture_started')
        build_declaration = payload.get('ros_build_validation')
        build_path = _resolve_path(
            bundle_path, build_declaration.get('path')) if isinstance(
                build_declaration, Mapping) else None
        build_data = _load_json(
            build_path, 'build_time_binding', migration_failures)
        build_generated = build_data.get(
            'generated_at_unix_sec') if isinstance(build_data, Mapping) else None
        if not _finite(build_generated, 0.0, earliest_capture):
            _add_failure(
                migration_failures, 'build_after_capture_started')
    _hardware_tf_binding(hardware_path, scene_reports, failures)
    extrinsics_reference = _check_extrinsics_reference(
        bundle_path, payload.get('extrinsics_measurement_reference'),
        scene_tf_data, hardware_path, failures, bindings, seen_paths)

    evaluator = evaluate_suite(
        evaluator_scenes, EvaluationThresholds(), True)
    if not evaluator['passed']:
        _add_failure(failures, 'typed_frame_evaluator_failed')
    formal_four_scene_pass = (
        set(scene_reports) == set(SCENES)
        and all(scene_reports.get(scene, {}).get('passed') is True
                for scene in SCENES)
        and evaluator.get('passed') is True)
    formal_tf_3d_pass = formal_four_scene_pass and all(
        scene_reports.get(scene, {}).get('tf', {}).get(
            'independent_extrinsics_validated') is True
        and isinstance(scene_reports.get(scene, {}).get('xyz_error_m'), Mapping)
        and isinstance(scene_reports.get(scene, {}).get('depth_quality'), Mapping)
        for scene in SCENES)
    architecture_blockers = sorted(set(
        ros1_field_install.get('architecture_blockers', [])))
    build_install_blockers = sorted(set(
        ros1_field_install.get('build_install_blockers', [])))
    field_evidence_blockers = sorted(set(
        ros1_field_install.get('field_evidence_blockers', [])))
    install_gates = {
        ROS2_MIGRATION_INSTALL_GATE_ID: ros_build,
        ROS1_FIELD_INSTALL_GATE_ID: ros1_field_install,
    }
    delivery_gate_summary = {
        'ros2_migration_install_pass': (
            ros_build.get('validated_pass') is True),
        'ros1_field_install_pass': (
            ros1_field_install.get('validated_pass') is True),
        'formal_four_scene_pass': formal_four_scene_pass,
        'formal_tf_3d_pass': formal_tf_3d_pass,
        'architecture_blockers': architecture_blockers,
        'build_install_blockers': build_install_blockers,
        'field_evidence_blockers': field_evidence_blockers,
        'delivery_ready': not failures,
    }
    non_delivery_failures = sorted(set(migration_failures))
    report = {
        'schema_version': 1,
        'evidence_scope': 'formal_four_scene_rgbd_acceptance_readiness',
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'required_scenes': list(SCENES),
        'thresholds': {
            'min_unique_frames_per_scene': MIN_UNIQUE_FRAMES,
            'max_sync_p95_sec': MAX_SYNC_P95_SEC,
            'max_processing_latency_p95_sec': MAX_PROCESSING_P95_SEC,
            'max_transport_latency_p95_sec': MAX_TRANSPORT_P95_SEC,
            'max_raw_rgb_rejection_rate': MAX_RAW_REJECTION_RATE,
            'max_raw_stream_unpaired_rate': MAX_RAW_STREAM_UNPAIRED_RATE,
            'max_typed_raw_unpaired_rate': MAX_TYPED_RAW_UNPAIRED_RATE,
            'max_xyz_error_m': MAX_XYZ_ERROR_M,
            'max_known_depth_error_m': MAX_DEPTH_ERROR_M,
            'min_target_roi_depth_ratio': MIN_TARGET_ROI_DEPTH_RATIO,
            'max_extrinsic_translation_tolerance_m': (
                MAX_EXTRINSIC_TRANSLATION_TOLERANCE_M),
            'max_extrinsic_rotation_tolerance_rad': (
                MAX_EXTRINSIC_ROTATION_TOLERANCE_RAD),
        },
        'input_bundle': {
            'path': str(bundle_path.resolve()),
            'size_bytes': bundle_path.stat().st_size,
            'sha256': sha256_file(bundle_path),
        },
        'artifact_bindings': bindings,
        'evaluated_at_unix_sec': now_unix_sec,
        'extrinsics_measurement_reference': extrinsics_reference,
        'software_binding': software,
        'release_binding': release_binding,
        'ros_build_validation': ros_build,
        'offline_migration_passed': not non_delivery_failures,
        'non_delivery_failures': non_delivery_failures,
        'ros1_field_install_validation': ros1_field_install,
        'install_gates': install_gates,
        'architecture_blockers': architecture_blockers,
        'build_install_blockers': build_install_blockers,
        'field_evidence_blockers': field_evidence_blockers,
        'delivery_gate_summary': delivery_gate_summary,
        'hardware_readiness': hardware,
        'scene_reports': scene_reports,
        'typed_frame_evaluator': evaluator,
        'passed': not failures,
        'delivery_ready': not failures,
        'failures': failures,
    }
    return report


def parse_args():
    """Build the offline one-command readiness CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    return parser.parse_args()


def main():
    """Verify existing evidence only; never start ROS or authorize motion."""
    args = parse_args()
    if args.report.exists():
        raise SystemExit('report path must not already exist')
    if args.bundle.resolve() == args.report.resolve():
        raise SystemExit('bundle and report paths must be different')
    try:
        payload = _strict_json_loads(args.bundle.read_text(encoding='utf-8'))
        if not isinstance(payload, Mapping):
            raise ValueError('readiness bundle must be a JSON object')
        report = evaluate_readiness(args.bundle, payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError,
            TypeError, KeyError, AttributeError, OverflowError) as error:
        report = {
            'schema_version': 1,
            'evidence_scope':
            'formal_four_scene_rgbd_acceptance_readiness',
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'passed': False,
            'delivery_ready': False,
            'failures': ['readiness_evaluation_error'],
            'evaluation_error': {
                'type': type(error).__name__,
                'message': str(error),
            },
        }
        if args.bundle.exists() and args.bundle.is_file():
            report['input_bundle'] = {
                'path': str(args.bundle.resolve()),
                'size_bytes': args.bundle.stat().st_size,
                'sha256': sha256_file(args.bundle),
            }
    report['readiness_source'] = {
        'path': str(Path(__file__).resolve()),
        'size_bytes': Path(__file__).stat().st_size,
        'sha256': sha256_file(Path(__file__)),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True,
            allow_nan=False) + '\n')
    print(json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True,
        allow_nan=False))
    return 0 if report['delivery_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
