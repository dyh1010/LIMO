"""Strict, dependency-free configuration policy for the ROS1 V1 overlay."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re


EXPECTED_FRAMES = {
    'map': 'map',
    'odom': 'odom',
    'base': 'base_link',
    'laser': 'laser_link',
}
EXPECTED_TOPICS = {
    'scan': '/scan',
    'odom': '/odom',
    'nav_cmd': '/v1/nav_cmd_vel',
    'driver_cmd': '/v1/driver_cmd_vel',
}
EXPECTED_ODOM_TF_OWNER = '/limo_base_node'
EXPECTED_SCAN_OWNER = '/ydlidar_lidar_publisher'
FORBIDDEN_ODOM_TF_OWNER = '/robot_pose_ekf'
STAGES = frozenset({
    'scan', 'mapping', 'localization', 'navigation_precore', 'navigation'})
NAVIGATION_OUTPUT_TOPICS = {
    'native': '/v1/nav_cmd_vel',
    'integrated': '/cleanup/base/cmd_vel_request',
}


@dataclass(frozen=True)
class MapArtifact:
    """Validated map_server YAML and image pair."""

    map_id: str
    yaml_path: Path
    image_path: Path
    resolution: float
    origin: tuple


def _require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError('{} must be an object'.format(name))
    return value


def _require_exact_keys(mapping, required, name):
    actual = set(mapping)
    expected = set(required)
    if actual != expected:
        raise ValueError(
            '{} keys must be exactly {}; got {}'.format(
                name, sorted(expected), sorted(actual)))


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('{} must be numeric and not bool'.format(name))
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('{} must be finite'.format(name))
    return number


def load_profile(path):
    """Load the JSON-compatible YAML profile and validate it strictly."""
    profile_path = Path(path)
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    validate_profile(profile)
    return profile


def validate_profile(profile):
    """Reject any unsafe, missing, extra, or vendor-coupled profile value."""
    root = _require_mapping(profile, 'profile')
    _require_exact_keys(root, (
        'schema_version', 'frames', 'topics', 'owners', 'scan',
        'freshness', 'tf_timing', 'motion', 'map_policy'), 'profile')
    if root['schema_version'] != 1:
        raise ValueError('schema_version must be 1')

    frames = _require_mapping(root['frames'], 'frames')
    _require_exact_keys(frames, EXPECTED_FRAMES, 'frames')
    if frames != EXPECTED_FRAMES:
        raise ValueError('frames must match the accepted map/odom/base/laser chain')

    topics = _require_mapping(root['topics'], 'topics')
    _require_exact_keys(topics, EXPECTED_TOPICS, 'topics')
    if topics != EXPECTED_TOPICS:
        raise ValueError('topics must use the project-owned /v1 command chain')
    if '/cmd_vel' in topics.values():
        raise ValueError('public /cmd_vel is forbidden in the project profile')

    owners = _require_mapping(root['owners'], 'owners')
    _require_exact_keys(
        owners, ('odom_tf', 'scan', 'forbidden_odom_tf'), 'owners')
    if owners['odom_tf'] != EXPECTED_ODOM_TF_OWNER:
        raise ValueError('odom_tf owner must be /limo_base_node')
    if owners['scan'] != EXPECTED_SCAN_OWNER:
        raise ValueError('scan owner must be /ydlidar_lidar_publisher')
    forbidden = owners['forbidden_odom_tf']
    if not isinstance(forbidden, list) or forbidden != [FORBIDDEN_ODOM_TF_OWNER]:
        raise ValueError('forbidden_odom_tf must contain only /robot_pose_ekf')

    scan = _require_mapping(root['scan'], 'scan')
    _require_exact_keys(scan, (
        'expected_hz', 'min_hz', 'max_hz', 'range_min_m',
        'range_max_m'), 'scan')
    expected_hz = _finite_number(scan['expected_hz'], 'scan.expected_hz')
    min_hz = _finite_number(scan['min_hz'], 'scan.min_hz')
    max_hz = _finite_number(scan['max_hz'], 'scan.max_hz')
    if (expected_hz, min_hz, max_hz) != (6.0, 4.8, 7.2):
        raise ValueError('scan frequency contract must be 6 Hz +/-20 percent')
    if _finite_number(scan['range_min_m'], 'scan.range_min_m') != 0.02:
        raise ValueError('scan range_min_m must be 0.02')
    if _finite_number(scan['range_max_m'], 'scan.range_max_m') != 16.0:
        raise ValueError('scan range_max_m must be 16.0')

    freshness = _require_mapping(root['freshness'], 'freshness')
    bounds = {
        'scan_timeout_s': 0.5,
        'odom_timeout_s': 0.5,
        'tf_timeout_s': 0.5,
        'command_timeout_s': 0.25,
    }
    _require_exact_keys(freshness, bounds, 'freshness')
    for key, maximum in bounds.items():
        value = _finite_number(freshness[key], 'freshness.' + key)
        if value <= 0.0 or value > maximum:
            raise ValueError('{} must be in (0, {}]'.format(key, maximum))

    tf_timing = _require_mapping(root['tf_timing'], 'tf_timing')
    _require_exact_keys(tf_timing, (
        'amcl_transform_tolerance_s',
        'source_future_tolerance_s'), 'tf_timing')
    amcl_transform_tolerance = _finite_number(
        tf_timing['amcl_transform_tolerance_s'],
        'tf_timing.amcl_transform_tolerance_s')
    source_future_tolerance = _finite_number(
        tf_timing['source_future_tolerance_s'],
        'tf_timing.source_future_tolerance_s')
    if amcl_transform_tolerance != 0.05:
        raise ValueError('AMCL transform tolerance must be 0.05 s')
    if source_future_tolerance != 0.10:
        raise ValueError('source future tolerance must be 0.10 s')
    if amcl_transform_tolerance > source_future_tolerance:
        raise ValueError('AMCL transform tolerance exceeds bridge hard cap')

    motion = _require_mapping(root['motion'], 'motion')
    motion_limits = {
        'max_linear_x_mps': 0.20,
        'max_angular_z_rps': 0.50,
        'max_linear_accel_mps2': 0.50,
        'max_angular_accel_rps2': 1.00,
    }
    _require_exact_keys(motion, (
        'allow_nonzero_default', 'driver_timeout_verified',
        *motion_limits.keys()), 'motion')
    if motion['allow_nonzero_default'] is not False:
        raise ValueError('allow_nonzero_default must remain false')
    if motion['driver_timeout_verified'] is not False:
        raise ValueError('baseline driver_timeout_verified must remain false')
    for key, maximum in motion_limits.items():
        value = _finite_number(motion[key], 'motion.' + key)
        if value <= 0.0 or value > maximum:
            raise ValueError('{} exceeds conservative V1 bound'.format(key))
    if motion['max_linear_x_mps'] >= 0.6:
        raise ValueError('vendor 0.6 m/s limit is forbidden')

    map_policy = _require_mapping(root['map_policy'], 'map_policy')
    _require_exact_keys(map_policy, (
        'require_absolute_path', 'reject_vendor_maps',
        'rejected_map_ids'), 'map_policy')
    if map_policy['require_absolute_path'] is not True:
        raise ValueError('map paths must be absolute')
    if map_policy['reject_vendor_maps'] is not True:
        raise ValueError('vendor map directory must be rejected')
    rejected = map_policy['rejected_map_ids']
    if not isinstance(rejected, list) or 'map1017' not in rejected:
        raise ValueError('map1017 must be rejected as a V1 active map')


def validate_amcl_transform_tolerance(profile, path):
    """Require the AMCL TF postdate to equal the shared bridge cap."""
    validate_profile(profile)
    source = Path(path).read_text(encoding='utf-8')
    pattern = re.compile(
        r'^\s*transform_tolerance\s*:\s*([^#\s]+)\s*(?:#.*)?$')
    values = []
    for line in source.splitlines():
        match = pattern.match(line)
        if match:
            values.append(match.group(1))
    if len(values) != 1:
        raise ValueError(
            'AMCL config must define transform_tolerance exactly once')
    try:
        configured = _finite_number(
            float(values[0]), 'amcl.transform_tolerance')
    except ValueError as exc:
        raise ValueError('AMCL transform_tolerance must be numeric') from exc
    expected = profile['tf_timing']['amcl_transform_tolerance_s']
    if configured != expected or configured != 0.05:
        raise ValueError(
            'AMCL transform_tolerance must equal expected 0.05 s')
    return configured


def _parse_map_yaml(path):
    values = {}
    pattern = re.compile(r'^\s*([A-Za-z_]+)\s*:\s*(.*?)\s*$')
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        match = pattern.match(raw_line)
        if match:
            values[match.group(1)] = match.group(2).strip('"\'')
    return values


def validate_map_file(profile, map_file, active_map_id=None):
    """Validate a frozen map without starting map_server."""
    validate_profile(profile)
    path = Path(map_file)
    if not path.is_absolute():
        raise ValueError('map_file must be absolute')
    if path.suffix != '.yaml':
        raise ValueError('map_file must end in .yaml')
    normalized = path.as_posix()
    if '/limo_bringup/maps/' in normalized:
        raise ValueError('vendor map directory is forbidden')
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError('map_file must exist and be non-empty')
    map_id = path.stem
    if map_id in profile['map_policy']['rejected_map_ids']:
        raise ValueError('map_id is rejected: {}'.format(map_id))
    if active_map_id is not None and active_map_id != map_id:
        raise ValueError('active_map_id must exactly match the map stem')

    values = _parse_map_yaml(path)
    required = {
        'image', 'resolution', 'origin', 'negate',
        'occupied_thresh', 'free_thresh'}
    if not required.issubset(values):
        raise ValueError('map YAML is missing required map_server fields')
    image = Path(values['image'])
    if not image.is_absolute():
        image = path.parent / image
    if not image.is_file() or image.stat().st_size <= 0:
        raise ValueError('map image must exist and be non-empty')
    resolution = _finite_number(
        float(values['resolution']), 'map.resolution')
    if resolution <= 0.0:
        raise ValueError('map resolution must be positive')
    origin_text = values['origin'].strip()
    if not (origin_text.startswith('[') and origin_text.endswith(']')):
        raise ValueError('map origin must be a three-value array')
    origin_parts = [part.strip() for part in origin_text[1:-1].split(',')]
    if len(origin_parts) != 3:
        raise ValueError('map origin must have three values')
    origin = tuple(_finite_number(float(part), 'map.origin')
                   for part in origin_parts)
    return MapArtifact(map_id, path, image, resolution, origin)


def validate_runtime_request(
        profile, stage, map_file=None, active_map_id=None,
        allow_nonzero=False, driver_timeout_verified=False,
        mode='native', cmd_vel_output_topic=None):
    """Validate field-stage arguments before any roslaunch invocation."""
    validate_profile(profile)
    if stage not in STAGES:
        raise ValueError('unknown stage: {}'.format(stage))
    if mode not in NAVIGATION_OUTPUT_TOPICS:
        raise ValueError('navigation mode must be native or integrated')
    if stage not in ('navigation_precore', 'navigation') and mode != 'native':
        raise ValueError(
            'integrated mode is valid only for navigation preflight/runtime')
    expected_output = NAVIGATION_OUTPUT_TOPICS[mode]
    if stage in ('navigation_precore', 'navigation'):
        if cmd_vel_output_topic is None:
            cmd_vel_output_topic = expected_output
        if cmd_vel_output_topic != expected_output:
            raise ValueError(
                'cmd_vel_output_topic does not match navigation mode')
    elif cmd_vel_output_topic is not None:
        raise ValueError(
            'cmd_vel_output_topic is valid only for navigation')
    artifact = None
    if stage in ('localization', 'navigation_precore', 'navigation'):
        if not map_file or not active_map_id:
            raise ValueError('map_file and active_map_id are required')
        artifact = validate_map_file(profile, map_file, active_map_id)
    elif map_file is not None or active_map_id is not None:
        raise ValueError('map inputs are not accepted for this stage')
    if allow_nonzero:
        if stage != 'navigation':
            raise ValueError('nonzero output is only valid for navigation')
        if not driver_timeout_verified:
            raise ValueError('driver timeout proof is required for nonzero output')
    return artifact
