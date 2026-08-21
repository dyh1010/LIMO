"""Pure-software, fail-closed AprilTag docking geometry and contracts.

This module calculates poses only.  It has no ROS imports, publishers,
services, action clients, device access, or motion output.
"""

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from types import MappingProxyType

from .apriltag_docking_contract import SIDES
from .tag_docking_adapter import (
    AdapterError, BoundTagPose, calibration_identity_from_payload,
    validate_calibration_payload)


CONFIG_SCHEMA = 'limo_v1_apriltag_docking_config/v1'
ACTION_GOAL_SCHEMA = 'limo_v1_tag_docking_goal/v1'
TARGET_FAMILY = 'tag52h13'
FIELD_FAMILY = 'tag36h11'
SIDE_LABELS = SIDES
MAP_FRAME = 'map'
TAG_FRAME_CONVENTION = 'X_LEFT_Y_DOWN_Z_OUT_OF_FRONT'
CAMERA_FRAME_CONVENTION = 'REP103_OPTICAL_X_RIGHT_Y_DOWN_Z_FORWARD'
PREAPPROACH = 'PREAPPROACH'
FINAL_DOCKING = 'FINAL_DOCKING'


class DockingPolicyError(ValueError):
    """A stable fail-closed error with a machine-readable code."""

    def __init__(self, code, detail):
        self.code = str(code)
        self.detail = str(detail)
        super().__init__('{}: {}'.format(self.code, self.detail))


@dataclass(frozen=True)
class DockingGoal:
    frame_id: str
    target_family: str
    target_id: int
    phase: str
    camera_standoff_m: float
    base_x: float
    base_y: float
    base_yaw: float
    camera_x: float
    camera_y: float
    camera_z: float
    geofence_clearance_m: float

    def to_dict(self):
        return asdict(self)


def _error(code, detail):
    raise DockingPolicyError(code, detail)


def _exact_dict(value, fields, code, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        _error(code, '{} fields must be exactly {}'.format(
            label, sorted(fields)))
    return value


def _finite(value, code, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(code, '{} must be numeric'.format(label))
    result = float(value)
    if not math.isfinite(result):
        _error(code, '{} must be finite'.format(label))
    return result


def _positive(value, code, label):
    result = _finite(value, code, label)
    if result <= 0.0:
        _error(code, '{} must be positive'.format(label))
    return result


def _quaternion(value, code, label):
    if not isinstance(value, list) or len(value) != 4:
        _error(code, '{} must be a four-element xyzw list'.format(label))
    quaternion = tuple(
        _finite(item, code, '{}[{}]'.format(label, index))
        for index, item in enumerate(value))
    norm = math.sqrt(sum(item * item for item in quaternion))
    if abs(norm - 1.0) > 1e-3:
        _error(code, '{} must be normalized'.format(label))
    return tuple(item / norm for item in quaternion)


def _vector3(value, code, label):
    if not isinstance(value, list) or len(value) != 3:
        _error(code, '{} must be a three-element list'.format(label))
    return tuple(
        _finite(item, code, '{}[{}]'.format(label, index))
        for index, item in enumerate(value))


def _quat_multiply(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _quat_conjugate(value):
    return (-value[0], -value[1], -value[2], value[3])


def _rotate(quaternion, vector):
    rotated = _quat_multiply(
        _quat_multiply(quaternion, (vector[0], vector[1], vector[2], 0.0)),
        _quat_conjugate(quaternion))
    return rotated[:3]


def _compose(left_translation, left_rotation,
             right_translation, right_rotation):
    offset = _rotate(left_rotation, right_translation)
    return (
        tuple(a + b for a, b in zip(left_translation, offset)),
        _quat_multiply(left_rotation, right_rotation),
    )


def _inverse(translation, rotation):
    inverse_rotation = _quat_conjugate(rotation)
    inverse_translation = _rotate(
        inverse_rotation, tuple(-item for item in translation))
    return inverse_translation, inverse_rotation


def _rpy(quaternion):
    x, y, z, w = quaternion
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    yaw = math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z))
    return roll, pitch, yaw


def _pose(value, code, label, frame_id=MAP_FRAME):
    _exact_dict(
        value, {'frame_id', 'position_xyz', 'orientation_xyzw'},
        code, label)
    if value['frame_id'] != frame_id:
        _error(code, '{} frame_id must be {}'.format(label, frame_id))
    return (
        _vector3(value['position_xyz'], code, label + '.position_xyz'),
        _quaternion(
            value['orientation_xyzw'], code,
            label + '.orientation_xyzw'))


def _polygon_area(points):
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, points[1:] + points[:1]))


def _cross(origin, left, right):
    return ((left[0] - origin[0]) * (right[1] - origin[1])
            - (left[1] - origin[1]) * (right[0] - origin[0]))


def _distance_to_segment(point, start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return 0.0
    fraction = ((point[0] - start[0]) * dx
                + (point[1] - start[1]) * dy) / denominator
    fraction = max(0.0, min(1.0, fraction))
    projection = (start[0] + fraction * dx, start[1] + fraction * dy)
    return math.hypot(point[0] - projection[0], point[1] - projection[1])


def _validate_polygon(raw):
    if not isinstance(raw, list) or len(raw) != 4:
        _error('INVALID_GEOFENCE', 'polygon_map must contain four vertices')
    points = []
    for index, record in enumerate(raw):
        _exact_dict(
            record, {'x', 'y'}, 'INVALID_GEOFENCE',
            'polygon_map[{}]'.format(index))
        points.append((
            _finite(record['x'], 'INVALID_GEOFENCE', 'vertex.x'),
            _finite(record['y'], 'INVALID_GEOFENCE', 'vertex.y')))
    if len(set(points)) != 4 or _polygon_area(points) <= 1e-6:
        _error(
            'INVALID_GEOFENCE',
            'polygon_map must be unique, nondegenerate and counter-clockwise')
    signs = []
    for index in range(4):
        signs.append(_cross(
            points[index], points[(index + 1) % 4],
            points[(index + 2) % 4]))
    if any(value <= 1e-8 for value in signs):
        _error('INVALID_GEOFENCE', 'polygon_map must be strictly convex')
    return tuple(points)


def _goal_clearance(point, polygon):
    if any(
            _cross(polygon[index], polygon[(index + 1) % 4], point)
            < -1e-9 for index in range(4)):
        _error('GEOFENCE_REJECTED', 'base goal is outside the virtual fence')
    return min(
        _distance_to_segment(point, polygon[index], polygon[(index + 1) % 4])
        for index in range(4))


def validate_config(payload):
    """Validate a completed measured configuration and return normalized data."""
    top = {
        'schema', 'template_only', 'measurement_status', 'frames',
        'tag_frame_convention', 'field_tags', 'geofence', 'objects',
        'calibration', 'planning', 'safety'}
    _exact_dict(payload, top, 'CONFIG_SCHEMA_INVALID', 'config')
    if payload['schema'] != CONFIG_SCHEMA:
        _error('CONFIG_SCHEMA_INVALID', 'config schema is unsupported')
    if payload['template_only'] is not False:
        _error(
            'CONFIG_TEMPLATE_INCOMPLETE',
            'template_only must be false after every measurement is filled')
    if payload['measurement_status'] != 'MEASURED_VERIFIED':
        _error(
            'MEASUREMENTS_UNVERIFIED',
            'measurement_status must be MEASURED_VERIFIED')
    frames = _exact_dict(
        payload['frames'], {'map', 'base', 'camera_optical'},
        'CONFIG_SCHEMA_INVALID', 'frames')
    if frames['map'] != MAP_FRAME or frames['base'] != 'base_link':
        _error('CONFIG_SCHEMA_INVALID', 'map/base frames are fixed')
    if not isinstance(frames['camera_optical'], str) or not frames['camera_optical']:
        _error('CONFIG_SCHEMA_INVALID', 'camera_optical frame is missing')
    if payload['tag_frame_convention'] != TAG_FRAME_CONVENTION:
        _error('CONFIG_SCHEMA_INVALID', 'tag frame convention is unsupported')

    field_tags = payload['field_tags']
    if not isinstance(field_tags, list) or len(field_tags) != 4:
        _error('INVALID_FIELD_TAGS', 'four field tags are required')
    observed_field_ids = set()
    for index, record in enumerate(field_tags):
        _exact_dict(
            record, {'family', 'id', 'role', 'measured', 'pose_map'},
            'INVALID_FIELD_TAGS', 'field_tags[{}]'.format(index))
        if (record['family'] != FIELD_FAMILY
                or type(record['id']) is not int
                or record['id'] not in range(4)
                or record['role'] != 'map_anchor'
                or record['measured'] is not True):
            _error('INVALID_FIELD_TAGS', 'field tag identity/measurement invalid')
        _pose(record['pose_map'], 'INVALID_FIELD_TAGS', 'field tag pose')
        observed_field_ids.add(record['id'])
    if observed_field_ids != set(range(4)):
        _error('INVALID_FIELD_TAGS', 'field tag IDs must be exactly 0..3')

    geofence = _exact_dict(
        payload['geofence'], {
            'frame_id', 'measured', 'polygon_map', 'boundary_margin_m',
            'base_footprint_radius_m'},
        'INVALID_GEOFENCE', 'geofence')
    if geofence['frame_id'] != MAP_FRAME or geofence['measured'] is not True:
        _error('INVALID_GEOFENCE', 'geofence must be measured in map')
    polygon = _validate_polygon(geofence['polygon_map'])
    boundary_margin = _positive(
        geofence['boundary_margin_m'], 'INVALID_GEOFENCE',
        'boundary_margin_m')
    footprint_radius = _positive(
        geofence['base_footprint_radius_m'], 'INVALID_GEOFENCE',
        'base_footprint_radius_m')

    objects = payload['objects']
    if not isinstance(objects, list) or len(objects) != 3:
        _error('INVALID_OBJECT_MAP', 'exactly three objects are required')
    observed_objects = set()
    tag_map = {}
    for expected_object_id, record in enumerate(objects):
        _exact_dict(
            record, {'object_id', 'dimensions_m', 'mount_verified', 'tags'},
            'INVALID_OBJECT_MAP', 'object')
        object_id = record['object_id']
        if (type(object_id) is not int or object_id != expected_object_id
                or object_id in observed_objects):
            _error('INVALID_OBJECT_MAP', 'object IDs must be unique 0..2')
        observed_objects.add(object_id)
        dimensions = _exact_dict(
            record['dimensions_m'], {'length', 'width', 'height'},
            'INVALID_OBJECT_MAP', 'object dimensions')
        for name in ('length', 'width', 'height'):
            _positive(
                dimensions[name], 'INVALID_OBJECT_MAP',
                'dimensions_m.' + name)
        if record['mount_verified'] is not True:
            _error('INVALID_OBJECT_MAP', 'tag mounts must be verified')
        if not isinstance(record['tags'], list) or len(record['tags']) != 4:
            _error('INVALID_OBJECT_MAP', 'each object needs four side tags')
        for expected_side_index, tag in enumerate(record['tags']):
            _exact_dict(
                tag, {'family', 'id', 'side_index', 'side_label'},
                'INVALID_OBJECT_MAP', 'object tag')
            tag_id = tag['id']
            expected_tag_id = object_id * 4 + expected_side_index
            if (tag['family'] != TARGET_FAMILY
                    or type(tag_id) is not int
                    or type(tag['side_index']) is not int
                    or tag_id != expected_tag_id
                    or tag_id // 4 != object_id
                    or tag_id % 4 != expected_side_index
                    or tag['side_index'] != expected_side_index
                    or tag['side_label'] != SIDE_LABELS[expected_side_index]
                    or tag_id in tag_map):
                _error('INVALID_OBJECT_MAP', 'object/tag/side mapping invalid')
            tag_map[tag_id] = {
                'object_id': object_id,
                'side_index': tag['side_index'],
                'side_label': tag['side_label'],
            }
    if observed_objects != set(range(3)) or set(tag_map) != set(range(12)):
        _error('INVALID_OBJECT_MAP', 'objects/tags must cover 0..2 and 0..11')

    calibration = _exact_dict(
        payload['calibration'], {'canonical_payload'},
        'EXTRINSIC_UNVERIFIED', 'calibration')
    try:
        extrinsic_translation, extrinsic_rotation = (
            validate_calibration_payload(calibration['canonical_payload']))
        calibration_identity = calibration_identity_from_payload(
            calibration['canonical_payload'])
    except AdapterError as error:
        _error('EXTRINSIC_UNVERIFIED', str(error))
    calibration_binding = MappingProxyType({
        'identity': MappingProxyType(dict(calibration_identity)),
        'translation': tuple(extrinsic_translation),
        'rotation': tuple(extrinsic_rotation),
    })

    planning = _exact_dict(
        payload['planning'], {
            'default_final_standoff_m', 'allowed_final_standoff_m',
            'preapproach_standoff_m'},
        'INVALID_SAFETY_LIMIT', 'planning')
    default_standoff = _positive(
        planning['default_final_standoff_m'], 'INVALID_SAFETY_LIMIT',
        'default_final_standoff_m')
    if abs(default_standoff - 0.40) > 1e-9:
        _error('INVALID_SAFETY_LIMIT', 'first demo standoff must be 0.40 m')
    allowed = planning['allowed_final_standoff_m']
    if (not isinstance(allowed, list) or len(allowed) != 1
            or abs(_finite(
                allowed[0], 'INVALID_SAFETY_LIMIT',
                'allowed_final_standoff_m[0]') - 0.40) > 1e-9):
        _error(
            'INVALID_SAFETY_LIMIT',
            'first demo may allow only 0.40 m final standoff')
    preapproach = _positive(
        planning['preapproach_standoff_m'], 'INVALID_SAFETY_LIMIT',
        'preapproach_standoff_m')
    if not 0.8 <= preapproach <= 1.0:
        _error(
            'INVALID_SAFETY_LIMIT',
            'preapproach standoff must be within 0.8..1.0 m')

    safety_fields = {
        'minimum_detection_confidence', 'max_tag_age_s',
        'max_planar_tilt_deg', 'max_base_goal_z_m',
        'max_linear_speed_mps', 'max_angular_speed_rad_s',
        'docking_timeout_s', 'tag_loss_stop_s',
        'final_standoff_tolerance_m', 'final_lateral_tolerance_m',
        'final_yaw_tolerance_deg', 'require_localization_ready',
        'require_stop_clear', 'require_geofence', 'abort_on_tag_loss',
        'motion_output_enabled'}
    safety = _exact_dict(
        payload['safety'], safety_fields,
        'INVALID_SAFETY_LIMIT', 'safety')
    confidence = _finite(
        safety['minimum_detection_confidence'], 'INVALID_SAFETY_LIMIT',
        'minimum_detection_confidence')
    if not 0.0 < confidence <= 1.0:
        _error('INVALID_SAFETY_LIMIT', 'confidence limit is invalid')
    positive_limits = {}
    for name in safety_fields - {
            'minimum_detection_confidence', 'require_localization_ready',
            'require_stop_clear', 'require_geofence', 'abort_on_tag_loss',
            'motion_output_enabled'}:
        positive_limits[name] = _positive(
            safety[name], 'INVALID_SAFETY_LIMIT', name)
    if positive_limits['max_linear_speed_mps'] > 0.15:
        _error('INVALID_SAFETY_LIMIT', 'linear speed limit exceeds 0.15 m/s')
    if positive_limits['max_angular_speed_rad_s'] > 0.35:
        _error('INVALID_SAFETY_LIMIT', 'angular speed limit exceeds 0.35 rad/s')
    if abs(positive_limits['final_standoff_tolerance_m'] - 0.08) > 1e-9:
        _error('INVALID_SAFETY_LIMIT', 'standoff tolerance must be 0.08 m')
    if abs(positive_limits['final_lateral_tolerance_m'] - 0.05) > 1e-9:
        _error('INVALID_SAFETY_LIMIT', 'lateral tolerance must be 0.05 m')
    if abs(positive_limits['final_yaw_tolerance_deg'] - 5.0) > 1e-9:
        _error('INVALID_SAFETY_LIMIT', 'yaw tolerance must be 5 degrees')
    for name in (
            'require_localization_ready', 'require_stop_clear',
            'require_geofence', 'abort_on_tag_loss'):
        if safety[name] is not True:
            _error('INVALID_SAFETY_LIMIT', name + ' must be true')
    if safety['motion_output_enabled'] is not False:
        _error(
            'INVALID_SAFETY_LIMIT',
            'offline configuration must keep motion_output_enabled false')

    return {
        'payload': payload,
        'frames': frames,
        'polygon': polygon,
        'boundary_margin_m': boundary_margin,
        'footprint_radius_m': footprint_radius,
        'tag_map': tag_map,
        'calibration_binding': calibration_binding,
        'default_final_standoff_m': default_standoff,
        'allowed_final_standoff_m': tuple(float(item) for item in allowed),
        'preapproach_standoff_m': preapproach,
        'safety': dict(safety),
    }


def load_config(path):
    def reject_constant(value):
        raise ValueError('nonfinite_json_constant:' + value)

    def reject_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key:' + key)
            result[key] = value
        return result

    try:
        payload = json.loads(
            Path(path).read_text(encoding='utf-8'),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate)
    except (OSError, ValueError) as exc:
        _error('CONFIG_READ_FAILED', str(exc))
    return validate_config(payload)


def validate_action_goal(config, goal):
    _exact_dict(
        goal, {'schema', 'request_id', 'target_family', 'target_id',
               'standoff_m'},
        'ACTION_GOAL_INVALID', 'action goal')
    if goal['schema'] != ACTION_GOAL_SCHEMA:
        _error('ACTION_GOAL_INVALID', 'goal schema is unsupported')
    if not isinstance(goal['request_id'], str) or not goal['request_id'].strip():
        _error('ACTION_GOAL_INVALID', 'request_id is missing')
    if goal['target_family'] != TARGET_FAMILY:
        _error('INVALID_FAMILY', 'only tag52h13 is accepted for docking')
    if (type(goal['target_id']) is not int
            or goal['target_id'] not in config['tag_map']):
        _error('INVALID_TAG_ID', 'target_id is not mapped to an object side')
    standoff = _positive(
        goal['standoff_m'], 'STANDOFF_NOT_ALLOWED', 'standoff_m')
    if not any(
            abs(standoff - allowed) <= 1e-9
            for allowed in config['allowed_final_standoff_m']):
        _error('STANDOFF_NOT_ALLOWED', 'standoff is not enabled for this demo')
    return {
        'request_id': goal['request_id'].strip(),
        'target_family': goal['target_family'],
        'target_id': goal['target_id'],
        'standoff_m': standoff,
        'mapping': dict(config['tag_map'][goal['target_id']]),
    }


def compute_base_goal(config, bound_tag_pose, camera_standoff_m, phase):
    """Compute a map-frame base goal without sending or forwarding it."""
    if type(bound_tag_pose) is not BoundTagPose:
        _error(
            'TAG_SOURCE_UNBOUND',
            'policy accepts only host-adapter BoundTagPose inputs')
    try:
        bound = bound_tag_pose.verified_snapshot()
    except (AdapterError, TypeError, ValueError) as error:
        _error('TAG_SOURCE_UNBOUND', str(error))
    target_family = bound.target_family
    target_id = bound.target_id
    if target_family != TARGET_FAMILY:
        _error('INVALID_FAMILY', 'only tag52h13 may generate a docking goal')
    if (isinstance(target_id, bool) or not isinstance(target_id, int)
            or target_id not in config['tag_map']):
        _error('INVALID_TAG_ID', 'target ID is not mapped')
    mapping = config['tag_map'][target_id]
    if (bound.object_id != mapping['object_id']
            or bound.side_index != mapping['side_index']
            or bound.side_label != mapping['side_label']):
        _error('TAG_SOURCE_UNBOUND', 'bound target mapping does not match config')
    calibration_binding = config.get('calibration_binding')
    if type(calibration_binding) is not type(MappingProxyType({})):
        _error('TAG_SOURCE_UNBOUND', 'config calibration binding is not immutable')
    if (bound.calibration_sha256
            != calibration_binding['identity']['sha256']):
        _error('TAG_SOURCE_UNBOUND', 'bound calibration does not match config')
    confidence = _finite(
        bound.confidence, 'LOW_CONFIDENCE', 'detection_confidence')
    if confidence < config['safety']['minimum_detection_confidence']:
        _error('LOW_CONFIDENCE', 'detection confidence is below the limit')
    age = _finite(
        bound.age_ns / 1000000000.0,
        'TAG_STALE', 'detection_age_s')
    if age < 0.0 or age > config['safety']['max_tag_age_s']:
        _error('TAG_STALE', 'tag observation is stale or from the future')
    standoff = _positive(
        camera_standoff_m, 'STANDOFF_NOT_ALLOWED', 'camera_standoff_m')
    if phase == PREAPPROACH:
        if abs(standoff - config['preapproach_standoff_m']) > 1e-9:
            _error(
                'STANDOFF_NOT_ALLOWED',
                'preapproach standoff must equal the measured configuration')
    elif phase == FINAL_DOCKING:
        if not any(
                abs(standoff - allowed) <= 1e-9
                for allowed in config['allowed_final_standoff_m']):
            _error('STANDOFF_NOT_ALLOWED', 'final standoff is not allowed')
    else:
        _error('ACTION_GOAL_INVALID', 'phase is unsupported')

    immutable_pose = {
        'frame_id': bound.pose_map['frame_id'],
        'position_xyz': list(bound.pose_map['position_xyz']),
        'orientation_xyzw': list(bound.pose_map['orientation_xyzw']),
    }
    tag_translation, tag_rotation = _pose(
        immutable_pose, 'TAG_POSE_INVALID', 'tag_pose_map')
    outward_normal = _rotate(tag_rotation, (0.0, 0.0, 1.0))
    camera_translation = tuple(
        value + standoff * normal
        for value, normal in zip(tag_translation, outward_normal))
    camera_rotation = _quat_multiply(
        tag_rotation, (0.0, 1.0, 0.0, 0.0))
    inverse_translation, inverse_rotation = _inverse(
        calibration_binding['translation'], calibration_binding['rotation'])
    base_translation, base_rotation = _compose(
        camera_translation, camera_rotation,
        inverse_translation, inverse_rotation)
    roll, pitch, yaw = _rpy(base_rotation)
    max_tilt = math.radians(config['safety']['max_planar_tilt_deg'])
    if abs(roll) > max_tilt or abs(pitch) > max_tilt:
        _error(
            'UNREACHABLE_BASE_POSE',
            'computed base orientation is not planar')
    if abs(base_translation[2]) > config['safety']['max_base_goal_z_m']:
        _error(
            'UNREACHABLE_BASE_POSE',
            'computed base goal height exceeds the planar limit')
    clearance = _goal_clearance(base_translation[:2], config['polygon'])
    required_clearance = (
        config['boundary_margin_m'] + config['footprint_radius_m'])
    if clearance + 1e-9 < required_clearance:
        _error(
            'GEOFENCE_REJECTED',
            'base footprint plus boundary margin exceeds the virtual fence')
    return DockingGoal(
        frame_id=MAP_FRAME,
        target_family=target_family,
        target_id=target_id,
        phase=phase,
        camera_standoff_m=standoff,
        base_x=base_translation[0],
        base_y=base_translation[1],
        base_yaw=yaw,
        camera_x=camera_translation[0],
        camera_y=camera_translation[1],
        camera_z=camera_translation[2],
        geofence_clearance_m=clearance,
    )


def compute_preapproach_goal(
        config, bound_tag_pose):
    return compute_base_goal(
        config, bound_tag_pose,
        config['preapproach_standoff_m'], PREAPPROACH)
