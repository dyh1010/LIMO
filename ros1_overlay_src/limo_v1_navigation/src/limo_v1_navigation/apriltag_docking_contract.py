"""Offline, fail-closed contracts for the AprilTag docking demonstration.

This module intentionally has no ROS imports and never produces motion commands.
It validates the scene inventory and camera-frame observation payload that a future
read-only detector may hand to a separately authorised docking controller.
"""

from __future__ import absolute_import

import math


SCHEMA_VERSION = 'limo_apriltag_docking_observation/v1'
FIXED_FAMILY = 'tag36h11'
OBJECT_FAMILY = 'tag52h13'
FIXED_IDS = frozenset(range(4))
OBJECT_IDS = frozenset(range(12))
SIDES = ('front', 'right', 'back', 'left')
ABORT_REASONS = frozenset((
    'tag_not_visible',
    'wrong_family',
    'unknown_tag_id',
    'duplicate_tag_id',
    'missing_object_side',
    'low_confidence',
    'high_reprojection_error',
    'stale_timestamp',
    'camera_pose_invalid',
    'calibration_missing',
    'tf_input_missing',
    'observation_stale',
    'observation_from_future',
))
CALIBRATION_SCHEMA_VERSION = 'limo_apriltag_docking_calibration_intake/v1'
CAMERA_FRAME = 'camera_color_optical_frame'
FRESHNESS_OWNER = 'host_now_ns'
DEFAULT_MAX_OBSERVATION_AGE_NS = 250000000


class ContractError(ValueError):
    """A required docking input is absent, malformed, or inconsistent."""


def _require(condition, reason):
    if not condition:
        raise ContractError(reason)


def _exact_keys(value, expected, reason):
    _require(isinstance(value, dict), reason + '_must_be_object')
    _require(set(value) == set(expected), reason + '_fields_invalid')
    return value


def _finite_number(value, name):
    _require(isinstance(value, (int, float)) and not isinstance(value, bool),
             name + '_must_be_number')
    _require(math.isfinite(float(value)), name + '_must_be_finite')
    return float(value)


def object_for_tag(tag_id):
    """Return the immutable object/side mapping for a tag52h13 ID."""
    _require(isinstance(tag_id, int) and not isinstance(tag_id, bool)
             and tag_id in OBJECT_IDS, 'unknown_object_tag_id')
    return {'object_index': tag_id // 4, 'side': SIDES[tag_id % 4]}


def validate_inventory(entries):
    """Validate all four fixed tags and all twelve movable-object tag faces.

    Each entry must contain ``family`` and ``id``.  tag52h13 entries must also
    match their deterministic object/side assignment; tag36h11 entries may not
    be represented as movable-object faces.
    """
    _require(isinstance(entries, list), 'inventory_must_be_list')
    fixed = set()
    movable = set()
    for entry in entries:
        _require(isinstance(entry, dict), 'inventory_entry_must_be_object')
        family = entry.get('family')
        tag_id = entry.get('id')
        _require(isinstance(tag_id, int) and not isinstance(tag_id, bool),
                 'tag_id_must_be_integer')
        key = (family, tag_id)
        if family == FIXED_FAMILY:
            _exact_keys(entry, ('family', 'id'), 'fixed_inventory_entry')
            _require(tag_id in FIXED_IDS, 'unknown_fixed_tag_id')
            _require(key not in fixed, 'duplicate_tag_id')
            _require('object_index' not in entry and 'side' not in entry,
                     'fixed_tag_cannot_be_object_face')
            fixed.add(key)
        elif family == OBJECT_FAMILY:
            _exact_keys(entry, ('family', 'id', 'object_index', 'side'),
                        'object_inventory_entry')
            _require(tag_id in OBJECT_IDS, 'unknown_object_tag_id')
            _require(key not in movable, 'duplicate_tag_id')
            mapping = object_for_tag(tag_id)
            _require(entry.get('object_index') == mapping['object_index'],
                     'object_tag_object_mapping_invalid')
            _require(entry.get('side') == mapping['side'],
                     'object_tag_side_mapping_invalid')
            movable.add(key)
        else:
            raise ContractError('wrong_family')
    _require({tag_id for _family, tag_id in fixed} == FIXED_IDS,
             'missing_fixed_tag')
    _require({tag_id for _family, tag_id in movable} == OBJECT_IDS,
             'missing_object_side')
    return {
        'fixed_tag_count': len(fixed),
        'object_tag_count': len(movable),
        'object_count': 3,
        'object_sides_per_object': 4,
    }


def target_descriptor(family, tag_id):
    """Return a target description or fail closed for non-docking tags."""
    _require(family == OBJECT_FAMILY, 'wrong_family')
    mapping = object_for_tag(tag_id)
    return {
        'family': family,
        'id': tag_id,
        'object_index': mapping['object_index'],
        'side': mapping['side'],
    }


def _validate_pose(pose):
    _exact_keys(pose, ('frame_id', 'translation_m', 'orientation_xyzw'),
                'camera_pose')
    _require(pose.get('frame_id') == CAMERA_FRAME,
             'camera_pose_frame_invalid')
    translation = pose.get('translation_m')
    quaternion = pose.get('orientation_xyzw')
    _exact_keys(translation, ('x', 'y', 'z'), 'camera_translation')
    _exact_keys(quaternion, ('x', 'y', 'z', 'w'), 'camera_orientation')
    for key in ('x', 'y', 'z'):
        _finite_number(translation.get(key), 'camera_translation_' + key)
    for key in ('x', 'y', 'z', 'w'):
        _finite_number(quaternion.get(key), 'camera_orientation_' + key)
    norm = math.sqrt(sum(float(quaternion[key]) ** 2
                         for key in ('x', 'y', 'z', 'w')))
    _require(0.995 <= norm <= 1.005, 'camera_orientation_not_unit')
    _require(float(translation['z']) > 0.0, 'tag_behind_camera')


def _validate_tf_inputs(tf_inputs, timestamp_ns, host_now_ns, max_age_ns):
    _exact_keys(tf_inputs, ('map_to_base_link', 'base_link_to_camera'),
                'tf_inputs')
    ages = {}
    for name, parent, child in (
            ('map_to_base_link', 'map', 'base_link'),
            ('base_link_to_camera', 'base_link', CAMERA_FRAME)):
        value = tf_inputs.get(name)
        _exact_keys(value, ('available', 'parent_frame', 'child_frame',
                            'timestamp_ns'), name)
        _require(value.get('available') is True, name + '_unavailable')
        _require(value.get('parent_frame') == parent, name + '_parent_invalid')
        _require(value.get('child_frame') == child, name + '_child_invalid')
        _require(value.get('timestamp_ns') == timestamp_ns,
                 name + '_timestamp_mismatch')
        ages[name] = _validate_host_freshness(
            value.get('timestamp_ns'), host_now_ns, max_age_ns)
    return ages


def _validate_host_freshness(timestamp_ns, host_now_ns, max_age_ns):
    """V1-compatible consumer-owned freshness: host now minus source stamp."""
    _require(isinstance(timestamp_ns, int) and not isinstance(timestamp_ns, bool)
             and timestamp_ns > 0, 'timestamp_invalid')
    _require(isinstance(host_now_ns, int) and host_now_ns > 0,
             'host_now_ns_missing')
    _require(not isinstance(host_now_ns, bool), 'host_now_ns_missing')
    _require(isinstance(max_age_ns, int) and not isinstance(max_age_ns, bool)
             and max_age_ns > 0,
             'max_observation_age_invalid')
    age_ns = host_now_ns - timestamp_ns
    _require(age_ns >= 0, 'observation_from_future')
    _require(age_ns < max_age_ns, 'observation_stale')
    return age_ns


def _positive(value, name):
    value = _finite_number(value, name)
    _require(value > 0.0, name + '_must_be_positive')
    return value


def validate_calibration(calibration):
    """Validate all camera, extrinsic, installation and map-survey prerequisites."""
    _exact_keys(calibration, (
        'schema_version', 'status', 'recorded_timestamp_ns',
        'camera_intrinsics', 'base_link_to_camera_extrinsics',
        'tag_installation_checklist',
        'abort_if_any_required_value_missing', 'notes'), 'calibration')
    _require(calibration.get('schema_version') == CALIBRATION_SCHEMA_VERSION,
             'calibration_schema_invalid')
    _require(calibration.get('status') == 'RECORDED',
             'calibration_status_not_recorded')
    recorded_timestamp = calibration.get('recorded_timestamp_ns')
    _require(isinstance(recorded_timestamp, int)
             and not isinstance(recorded_timestamp, bool)
             and recorded_timestamp > 0,
             'calibration_recorded_timestamp_missing')
    _require(calibration.get('abort_if_any_required_value_missing') is True,
             'calibration_abort_policy_missing')
    _require(isinstance(calibration.get('notes'), str)
             and calibration['notes'].strip(), 'calibration_notes_missing')
    camera = calibration.get('camera_intrinsics')
    _exact_keys(camera, (
        'camera_frame', 'image_width_px', 'image_height_px',
        'fx', 'fy', 'cx', 'cy', 'distortion_model',
        'distortion_coefficients', 'calibration_timestamp_ns'),
        'camera_intrinsics')
    _require(camera.get('camera_frame') == CAMERA_FRAME, 'camera_frame_invalid')
    for key in ('image_width_px', 'image_height_px'):
        value = camera.get(key)
        _require(isinstance(value, int) and not isinstance(value, bool)
                 and 16 <= value <= 16384, 'camera_' + key + '_invalid')
    for key in ('fx', 'fy'):
        value = _positive(camera.get(key), 'camera_' + key)
        _require(value <= 100000.0, 'camera_' + key + '_out_of_range')
    for key in ('cx', 'cy'):
        _finite_number(camera.get(key), 'camera_' + key)
    _require(0.0 <= float(camera['cx']) < camera['image_width_px'],
             'camera_cx_out_of_range')
    _require(0.0 <= float(camera['cy']) < camera['image_height_px'],
             'camera_cy_out_of_range')
    _require(camera.get('distortion_model') in (
        'plumb_bob', 'rational_polynomial', 'equidistant'),
        'distortion_model_invalid')
    coefficients = camera.get('distortion_coefficients')
    _require(isinstance(coefficients, list) and 4 <= len(coefficients) <= 14,
             'distortion_coefficients_missing')
    for index, coefficient in enumerate(coefficients):
        _finite_number(coefficient, 'distortion_coefficient_{}'.format(index))
    _require(isinstance(camera.get('calibration_timestamp_ns'), int) and
             not isinstance(camera['calibration_timestamp_ns'], bool) and
             camera['calibration_timestamp_ns'] > 0,
             'camera_calibration_timestamp_missing')
    _require(camera['calibration_timestamp_ns'] <= recorded_timestamp,
             'camera_calibration_timestamp_after_record')
    extrinsics = calibration.get('base_link_to_camera_extrinsics')
    _exact_keys(extrinsics, (
        'parent_frame', 'child_frame', 'translation_m',
        'orientation_xyzw', 'calibration_timestamp_ns'),
        'camera_extrinsics')
    _require(extrinsics.get('parent_frame') == 'base_link',
             'extrinsics_parent_frame_invalid')
    _require(extrinsics.get('child_frame') == CAMERA_FRAME,
             'extrinsics_child_frame_invalid')
    _validate_pose({'frame_id': extrinsics.get('child_frame'),
                    'translation_m': extrinsics.get('translation_m'),
                    'orientation_xyzw': extrinsics.get('orientation_xyzw')})
    for key in ('x', 'y', 'z'):
        _require(abs(float(extrinsics['translation_m'][key])) <= 2.0,
                 'extrinsics_translation_{}_out_of_range'.format(key))
    _require(isinstance(extrinsics.get('calibration_timestamp_ns'), int) and
             not isinstance(extrinsics['calibration_timestamp_ns'], bool) and
             extrinsics['calibration_timestamp_ns'] > 0,
             'extrinsics_calibration_timestamp_missing')
    _require(extrinsics['calibration_timestamp_ns'] <= recorded_timestamp,
             'extrinsics_calibration_timestamp_after_record')
    tags = calibration.get('tag_installation_checklist')
    _exact_keys(tags, (
        'field_tag_size_m', 'object_tag_size_m',
        'object_tag_center_height_m', 'installation_verified_timestamp_ns',
        'fixed_field_tag_measurements', 'object_dimensions_m',
        'tag_flatness_checked', 'tag_nonreflective_checked',
        'tag_unoccluded_checked', 'tag_faces_outward_checked'),
        'tag_installation_checklist')
    field_size = _positive(tags.get('field_tag_size_m'), 'field_tag_size')
    object_size = _positive(tags.get('object_tag_size_m'), 'object_tag_size')
    center_height = _positive(
        tags.get('object_tag_center_height_m'), 'object_tag_center_height')
    _require(0.18 <= field_size <= 0.20, 'field_tag_size_out_of_range')
    _require(0.12 <= object_size <= 0.16, 'object_tag_size_out_of_range')
    installation_timestamp = tags.get('installation_verified_timestamp_ns')
    _require(isinstance(installation_timestamp, int)
             and not isinstance(installation_timestamp, bool)
             and 0 < installation_timestamp <= recorded_timestamp,
             'installation_verified_timestamp_invalid')
    fixed_measurements = tags.get('fixed_field_tag_measurements')
    _require(isinstance(fixed_measurements, list) and len(fixed_measurements) == 4,
             'fixed_tag_map_measurements_missing')
    measured_ids = set()
    for measurement in fixed_measurements:
        _exact_keys(measurement, (
            'family', 'id', 'frame_id', 'position_m',
            'measurement_timestamp_ns', 'measured_verified'),
            'fixed_tag_measurement')
        _require(measurement.get('family') == FIXED_FAMILY,
                 'fixed_tag_measurement_family_invalid')
        tag_id = measurement.get('id')
        _require(isinstance(tag_id, int) and not isinstance(tag_id, bool)
                 and tag_id in FIXED_IDS and tag_id not in measured_ids,
                 'fixed_tag_measurement_id_invalid')
        measured_ids.add(tag_id)
        _require(measurement.get('frame_id') == 'map',
                 'fixed_tag_measurement_frame_invalid')
        _require(measurement.get('measured_verified') is True,
                 'fixed_tag_measurement_not_verified')
        measurement_timestamp = measurement.get('measurement_timestamp_ns')
        _require(isinstance(measurement_timestamp, int)
                 and not isinstance(measurement_timestamp, bool)
                 and 0 < measurement_timestamp <= recorded_timestamp,
                 'fixed_tag_measurement_timestamp_invalid')
        position = measurement.get('position_m')
        _exact_keys(position, ('x', 'y', 'z', 'yaw'),
                    'fixed_tag_measurement_position')
        for key in ('x', 'y', 'z', 'yaw'):
            _finite_number(position.get(key), 'fixed_tag_{}_{}'.format(tag_id, key))
        _require(all(abs(float(position[key])) <= 100.0
                     for key in ('x', 'y')), 'fixed_tag_xy_out_of_range')
        _require(0.0 <= float(position['z']) <= 5.0,
                 'fixed_tag_z_out_of_range')
        _require(-math.pi <= float(position['yaw']) <= math.pi,
                 'fixed_tag_yaw_out_of_range')
    _require(measured_ids == FIXED_IDS, 'fixed_tag_map_measurements_missing')
    dimensions = tags.get('object_dimensions_m')
    _require(isinstance(dimensions, list) and len(dimensions) == 3,
             'object_dimensions_missing')
    measured_objects = set()
    for dimension in dimensions:
        _exact_keys(dimension, (
            'object_index', 'length', 'width', 'height',
            'measured_verified'), 'object_dimension')
        object_index = dimension.get('object_index')
        _require(isinstance(object_index, int)
                 and not isinstance(object_index, bool)
                 and object_index in (0, 1, 2)
                 and object_index not in measured_objects,
                 'object_dimension_index_invalid')
        measured_objects.add(object_index)
        _require(dimension.get('measured_verified') is True,
                 'object_dimension_not_verified')
        for key in ('length', 'width', 'height'):
            value = _positive(
                dimension.get(key), 'object_{}_{}'.format(object_index, key))
            _require(value <= 5.0, 'object_dimension_out_of_range')
        _require(center_height <= float(dimension['height']),
                 'object_tag_center_height_exceeds_object')
    _require(measured_objects == {0, 1, 2}, 'object_dimensions_missing')
    for key in ('tag_flatness_checked', 'tag_nonreflective_checked',
                'tag_unoccluded_checked', 'tag_faces_outward_checked'):
        _require(tags.get(key) is True, key + '_missing')
    return {'decision': 'ACCEPT', 'camera_frame': CAMERA_FRAME,
            'fixed_tag_measurement_count': 4, 'object_dimension_count': 3}


def validate_observation(observation, host_now_ns,
                         max_age_ns=DEFAULT_MAX_OBSERVATION_AGE_NS,
                         min_confidence=0.70, max_reprojection_error_px=2.0):
    """Validate a live detector result without inventing a map-frame pose.

    Accepted payloads contain the tag pose only in the camera optical frame plus
    same-timestamp map/base and base/camera TF *inputs*.  A future controller may
    transform those inputs; this function intentionally never emits ``map_pose``.
    """
    _exact_keys(observation, (
        'schema_version', 'target', 'timestamp_ns', 'visible',
        'camera_frame_pose', 'quality', 'tf_inputs', 'decision',
        'failure_reason'), 'observation')
    _require(observation.get('schema_version') == SCHEMA_VERSION,
             'observation_schema_invalid')
    _require('map_pose' not in observation and 'base_pose' not in observation,
             'map_pose_must_not_be_fabricated')
    target = observation.get('target')
    _exact_keys(target, ('family', 'id', 'object_index', 'side'), 'target')
    descriptor = target_descriptor(target.get('family'), target.get('id'))
    _require(target == descriptor, 'target_mapping_invalid')
    timestamp_ns = observation.get('timestamp_ns')
    _require(isinstance(timestamp_ns, int) and not isinstance(timestamp_ns, bool)
             and timestamp_ns > 0,
             'timestamp_invalid')
    age_ns = _validate_host_freshness(timestamp_ns, host_now_ns, max_age_ns)
    _require(observation.get('visible') is True, 'tag_not_visible')
    quality = observation.get('quality')
    _exact_keys(quality, ('confidence', 'reprojection_error_px'), 'quality')
    confidence = _finite_number(quality.get('confidence'), 'confidence')
    reprojection = _finite_number(quality.get('reprojection_error_px'),
                                  'reprojection_error')
    _require(confidence >= min_confidence, 'low_confidence')
    _require(reprojection <= max_reprojection_error_px,
             'high_reprojection_error')
    _validate_pose(observation.get('camera_frame_pose'))
    tf_ages = _validate_tf_inputs(
        observation.get('tf_inputs'), timestamp_ns, host_now_ns, max_age_ns)
    _require(observation.get('decision') == 'ACCEPT', 'decision_not_accept')
    _require(observation.get('failure_reason') is None,
             'accepted_observation_has_failure_reason')
    return {'decision': 'ACCEPT', 'target': descriptor,
            'timestamp_ns': timestamp_ns, 'host_now_ns': host_now_ns,
            'age_ns': age_ns, 'freshness_owner': FRESHNESS_OWNER,
            'tf_age_ns': tf_ages,
            'map_pose_provided': False}


def abort_observation(family, tag_id, timestamp_ns, reason):
    """Return the only permitted result for missing or low-quality observations."""
    target = target_descriptor(family, tag_id)
    _require(isinstance(timestamp_ns, int) and timestamp_ns > 0,
             'timestamp_invalid')
    _require(reason in ABORT_REASONS, 'abort_reason_invalid')
    return {
        'schema_version': SCHEMA_VERSION,
        'target': target,
        'timestamp_ns': timestamp_ns,
        'visible': False,
        'camera_frame_pose': None,
        'quality': None,
        'tf_inputs': None,
        'decision': 'ABORT',
        'failure_reason': reason,
    }
