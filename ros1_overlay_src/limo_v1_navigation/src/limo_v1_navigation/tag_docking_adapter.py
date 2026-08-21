"""Host-owned, pure-software binding from camera observations to map Tag poses.

The adapter has no ROS or motion API.  It binds one canonical visual observation
to one same-stamp TF geometry snapshot and one host-pinned calibration identity,
then mechanically evaluates T_map_tag = T_map_base * T_base_camera * T_camera_tag.
"""

from __future__ import absolute_import

import hashlib
import hmac
import json
import math
import re
from collections import namedtuple
from types import MappingProxyType

from .apriltag_docking_contract import (
    CALIBRATION_SCHEMA_VERSION,
    CAMERA_FRAME,
    ContractError,
    validate_calibration,
    validate_observation,
)


SOURCE_BUNDLE_SCHEMA = 'limo_v1_tag_pose_source_bundle/v1'
CALIBRATION_IDENTITY_SCHEMA = 'limo_v1_calibration_identity/v1'
CALIBRATION_SHA256_BASIS = 'SORTED_COMPACT_ASCII_JSON_V1'
CALIBRATION_PAYLOAD_SCHEMA = 'limo_v1_base_camera_calibration_geometry/v1'
MAP_FRAME = 'map'
BASE_FRAME = 'base_link'
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_BOUND_POSE_SEAL = object()
BoundTagPoseSnapshot = namedtuple(
    'BoundTagPoseSnapshot', (
        'target_family target_id object_id side_index side_label '
        'timestamp_ns age_ns confidence calibration_sha256 source_sha256 '
        'calibration_translation calibration_orientation pose_map '
        'bound_digest_sha256'))


class AdapterError(ValueError):
    """A source binding, transform, freshness or identity check failed."""


def _require(condition, reason):
    if not condition:
        raise AdapterError(reason)


def _exact_dict(value, keys, reason):
    _require(isinstance(value, dict), reason + '_must_be_object')
    _require(set(value) == set(keys), reason + '_fields_invalid')
    return value


def _finite(value, reason):
    _require(type(value) in (int, float), reason + '_must_be_number')
    value = float(value)
    _require(math.isfinite(value), reason + '_must_be_finite')
    return value


def _translation(value, reason):
    _exact_dict(value, ('x', 'y', 'z'), reason)
    return tuple(_finite(value[key], reason + '_' + key)
                 for key in ('x', 'y', 'z'))


def _quaternion(value, reason):
    _exact_dict(value, ('x', 'y', 'z', 'w'), reason)
    result = tuple(_finite(value[key], reason + '_' + key)
                   for key in ('x', 'y', 'z', 'w'))
    norm = math.sqrt(sum(item * item for item in result))
    _require(0.995 <= norm <= 1.005, reason + '_not_unit')
    return tuple(item / norm for item in result)


def _multiply(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _rotate(quaternion, vector):
    conjugate = (-quaternion[0], -quaternion[1],
                 -quaternion[2], quaternion[3])
    result = _multiply(
        _multiply(quaternion, (vector[0], vector[1], vector[2], 0.0)),
        conjugate)
    return result[:3]


def _compose(left_translation, left_rotation,
             right_translation, right_rotation):
    offset = _rotate(left_rotation, right_translation)
    return (
        tuple(a + b for a, b in zip(left_translation, offset)),
        _multiply(left_rotation, right_rotation),
    )


def canonical_observation_sha256(observation):
    try:
        raw = json.dumps(
            observation, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as error:
        raise AdapterError('observation_not_canonical_json:' + str(error))
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(payload):
    try:
        raw = json.dumps(
            payload, sort_keys=True, separators=(',', ':'),
            ensure_ascii=True, allow_nan=False).encode('ascii')
    except (TypeError, ValueError) as error:
        raise AdapterError('canonical_json_invalid:' + str(error))
    return hashlib.sha256(raw).hexdigest()


def canonical_calibration_payload(calibration):
    """Canonical full calibration payload; geometry is read only from it."""
    try:
        validate_calibration(calibration)
    except ContractError as error:
        raise AdapterError('calibration_rejected:' + str(error))
    return {
        'schema_version': CALIBRATION_PAYLOAD_SCHEMA,
        'calibration_schema_version': CALIBRATION_SCHEMA_VERSION,
        'calibration': calibration,
    }


def calibration_identity_from_payload(payload):
    """Identify canonical calibration geometry, not an unverified SHA label."""
    validate_calibration_payload(payload)
    return {
        'schema_version': CALIBRATION_IDENTITY_SCHEMA,
        'calibration_schema_version': CALIBRATION_SCHEMA_VERSION,
        'sha256_basis': CALIBRATION_SHA256_BASIS,
        'sha256': _canonical_sha256(payload),
        'parent_frame': BASE_FRAME,
        'child_frame': CAMERA_FRAME,
    }


def calibration_identity_from_calibration(calibration):
    return calibration_identity_from_payload(canonical_calibration_payload(calibration))


def validate_calibration_payload(value):
    """Validate canonical bytes and return their base-to-camera geometry."""
    _exact_dict(value, (
        'schema_version', 'calibration_schema_version', 'calibration'),
        'calibration_payload')
    _require(value['schema_version'] == CALIBRATION_PAYLOAD_SCHEMA,
             'calibration_payload_schema_invalid')
    _require(value['calibration_schema_version'] == CALIBRATION_SCHEMA_VERSION,
             'calibration_payload_version_invalid')
    try:
        validate_calibration(value['calibration'])
    except ContractError as error:
        raise AdapterError('calibration_payload_rejected:' + str(error))
    extrinsics = value['calibration']['base_link_to_camera_extrinsics']
    _require(extrinsics['parent_frame'] == BASE_FRAME,
             'calibration_payload_parent_frame_invalid')
    _require(extrinsics['child_frame'] == CAMERA_FRAME,
             'calibration_payload_child_frame_invalid')
    return (_translation(extrinsics['translation_m'],
                         'calibration_payload_translation'),
            _quaternion(extrinsics['orientation_xyzw'],
                        'calibration_payload_orientation'))


def validate_calibration_identity(value):
    _exact_dict(value, (
        'schema_version', 'calibration_schema_version', 'sha256_basis', 'sha256',
        'parent_frame', 'child_frame'), 'calibration_identity')
    _require(value['schema_version'] == CALIBRATION_IDENTITY_SCHEMA,
             'calibration_identity_schema_invalid')
    _require(value['calibration_schema_version'] == CALIBRATION_SCHEMA_VERSION,
             'calibration_payload_schema_invalid')
    _require(value['sha256_basis'] == CALIBRATION_SHA256_BASIS,
             'calibration_sha256_basis_invalid')
    _require(isinstance(value['sha256'], str)
             and _SHA256.fullmatch(value['sha256']) is not None,
             'calibration_sha256_invalid')
    _require(value['parent_frame'] == BASE_FRAME,
             'calibration_parent_frame_invalid')
    _require(value['child_frame'] == CAMERA_FRAME,
             'calibration_child_frame_invalid')
    return dict(value)


def _transform(value, parent, child, timestamp_ns, reason,
               calibration_sha256=None):
    keys = {
        'parent_frame', 'child_frame', 'timestamp_ns',
        'translation_m', 'orientation_xyzw'}
    if calibration_sha256 is not None:
        keys.add('calibration_sha256')
    _exact_dict(value, keys, reason)
    _require(value['parent_frame'] == parent, reason + '_parent_invalid')
    _require(value['child_frame'] == child, reason + '_child_invalid')
    _require(type(value['timestamp_ns']) is int
             and value['timestamp_ns'] == timestamp_ns,
             reason + '_timestamp_mismatch')
    if calibration_sha256 is not None:
        _require(value['calibration_sha256'] == calibration_sha256,
                 reason + '_calibration_identity_mismatch')
    return (
        _translation(value['translation_m'], reason + '_translation'),
        _quaternion(value['orientation_xyzw'], reason + '_orientation'),
    )


class BoundTagPose(object):
    """Opaque policy input; only ``adapt_observation_to_map_pose`` may seal it."""

    __slots__ = (
        '_target_family', '_target_id', '_object_id', '_side_index',
        '_side_label', '_timestamp_ns', '_age_ns', '_confidence',
        '_calibration_sha256', '_source_sha256', '_pose_map',
        '_calibration_translation', '_calibration_orientation',
        '_bound_digest_sha256', '_seal', '_frozen')

    def __init__(self, target, timestamp_ns, age_ns, confidence,
                 calibration_sha256, source_sha256, pose_map,
                 calibration_geometry=None, _seal=None):
        if _seal is not _BOUND_POSE_SEAL:
            raise AdapterError('bound_tag_pose_direct_construction_forbidden')
        _exact_dict(pose_map, ('frame_id', 'position_xyz', 'orientation_xyzw'),
                    'bound_tag_pose_map')
        _require(pose_map['frame_id'] == MAP_FRAME,
                 'bound_tag_pose_map_frame_invalid')
        object.__setattr__(self, '_target_family', str(target['family']))
        object.__setattr__(self, '_target_id', int(target['id']))
        object.__setattr__(self, '_object_id', int(target['object_index']))
        object.__setattr__(self, '_side_index', int(target['id']) % 4)
        object.__setattr__(self, '_side_label', str(target['side']))
        object.__setattr__(self, '_timestamp_ns', int(timestamp_ns))
        object.__setattr__(self, '_age_ns', int(age_ns))
        object.__setattr__(self, '_confidence', float(confidence))
        object.__setattr__(self, '_calibration_sha256',
                           str(calibration_sha256))
        object.__setattr__(self, '_source_sha256', str(source_sha256))
        pose_translation = tuple(
            _finite(item, 'bound_tag_pose_position')
            for item in pose_map['position_xyz'])
        pose_orientation = tuple(
            _finite(item, 'bound_tag_pose_orientation')
            for item in pose_map['orientation_xyzw'])
        _require(len(pose_translation) == 3 and len(pose_orientation) == 4,
                 'bound_tag_pose_map_shape_invalid')
        _require(isinstance(calibration_geometry, tuple) and
                 len(calibration_geometry) == 2,
                 'bound_tag_pose_calibration_geometry_invalid')
        object.__setattr__(self, '_calibration_translation',
                           tuple(calibration_geometry[0]))
        object.__setattr__(self, '_calibration_orientation',
                           tuple(calibration_geometry[1]))
        object.__setattr__(self, '_pose_map', MappingProxyType({
            'frame_id': MAP_FRAME,
            'position_xyz': pose_translation,
            'orientation_xyzw': pose_orientation,
        }))
        object.__setattr__(self, '_seal', _seal)
        object.__setattr__(self, '_bound_digest_sha256',
                           self._recompute_bound_digest())
        object.__setattr__(self, '_frozen', True)

    def __setattr__(self, _name, _value):
        raise AdapterError('bound_tag_pose_immutable')

    @property
    def target_family(self): return self._target_family

    @property
    def target_id(self): return self._target_id

    @property
    def object_id(self): return self._object_id

    @property
    def side_index(self): return self._side_index

    @property
    def side_label(self): return self._side_label

    @property
    def timestamp_ns(self): return self._timestamp_ns

    @property
    def age_ns(self): return self._age_ns

    @property
    def confidence(self): return self._confidence

    @property
    def calibration_sha256(self): return self._calibration_sha256

    @property
    def calibration_translation(self): return self._calibration_translation

    @property
    def calibration_orientation(self): return self._calibration_orientation

    @property
    def source_sha256(self): return self._source_sha256

    @property
    def pose_map(self): return self._pose_map

    @property
    def bound_digest_sha256(self): return self._bound_digest_sha256

    def _canonical_bound_payload(self):
        return {
            'target': {
                'family': self._target_family,
                'id': self._target_id,
                'object_id': self._object_id,
                'side_index': self._side_index,
                'side_label': self._side_label,
            },
            'timestamp_ns': self._timestamp_ns,
            'age_ns': self._age_ns,
            'confidence': self._confidence,
            'calibration_sha256': self._calibration_sha256,
            'calibration_translation': list(self._calibration_translation),
            'calibration_orientation': list(self._calibration_orientation),
            'source_sha256': self._source_sha256,
            'pose_map': {
                'frame_id': self._pose_map['frame_id'],
                'position_xyz': list(self._pose_map['position_xyz']),
                'orientation_xyzw': list(self._pose_map['orientation_xyzw']),
            },
        }

    def _recompute_bound_digest(self):
        return _canonical_sha256(self._canonical_bound_payload())

    def verified_snapshot(self):
        _require(self._seal is _BOUND_POSE_SEAL,
                 'bound_tag_pose_seal_invalid')
        recomputed = self._recompute_bound_digest()
        _require(hmac.compare_digest(
            recomputed, self._bound_digest_sha256),
            'bound_tag_pose_digest_mismatch')
        return BoundTagPoseSnapshot(
            self._target_family, self._target_id, self._object_id,
            self._side_index, self._side_label, self._timestamp_ns,
            self._age_ns, self._confidence, self._calibration_sha256,
            self._source_sha256, self._calibration_translation,
            self._calibration_orientation, self._pose_map, recomputed)

    def is_source_bound(self):
        try:
            self.verified_snapshot()
            return True
        except (AdapterError, TypeError, ValueError):
            return False


def adapt_observation_to_map_pose(
        source_bundle, host_now_ns, max_age_ns,
        expected_calibration_identity):
    """Return a sealed map-frame Tag pose or reject the complete source bundle."""
    _exact_dict(source_bundle, (
        'schema_version', 'observation_sha256', 'observation',
        'tf_geometry', 'calibration_payload', 'calibration_identity'),
        'source_bundle')
    _require(source_bundle['schema_version'] == SOURCE_BUNDLE_SCHEMA,
             'source_bundle_schema_invalid')
    expected_identity = validate_calibration_identity(
        expected_calibration_identity)
    supplied_identity = validate_calibration_identity(
        source_bundle['calibration_identity'])
    _require(supplied_identity == expected_identity,
             'calibration_identity_mismatch')
    calibration_geometry = validate_calibration_payload(
        source_bundle['calibration_payload'])
    _require(calibration_identity_from_payload(
        source_bundle['calibration_payload']) == expected_identity,
        'calibration_identity_geometry_mismatch')

    observation = source_bundle['observation']
    digest = canonical_observation_sha256(observation)
    _require(source_bundle['observation_sha256'] == digest,
             'observation_source_sha256_mismatch')
    try:
        validated = validate_observation(
            observation, host_now_ns=host_now_ns, max_age_ns=max_age_ns)
    except ContractError as error:
        raise AdapterError('observation_rejected:' + str(error))

    geometry = _exact_dict(source_bundle['tf_geometry'], (
        'observation_sha256', 'timestamp_ns', 'map_to_base_link',
        'base_link_to_camera'), 'tf_geometry')
    _require(geometry['observation_sha256'] == digest,
             'tf_observation_source_swap')
    _require(type(geometry['timestamp_ns']) is int
             and geometry['timestamp_ns'] == validated['timestamp_ns'],
             'tf_geometry_timestamp_mismatch')
    map_base = _transform(
        geometry['map_to_base_link'], MAP_FRAME, BASE_FRAME,
        validated['timestamp_ns'], 'map_to_base_link')
    base_camera = _transform(
        geometry['base_link_to_camera'], BASE_FRAME, CAMERA_FRAME,
        validated['timestamp_ns'], 'base_link_to_camera',
        calibration_sha256=expected_identity['sha256'])
    _require(base_camera == calibration_geometry,
             'base_camera_calibration_geometry_mismatch')

    camera_pose = observation['camera_frame_pose']
    camera_tag = (
        _translation(camera_pose['translation_m'], 'camera_tag_translation'),
        _quaternion(camera_pose['orientation_xyzw'], 'camera_tag_orientation'),
    )
    map_camera = _compose(
        map_base[0], map_base[1], base_camera[0], base_camera[1])
    map_tag = _compose(
        map_camera[0], map_camera[1], camera_tag[0], camera_tag[1])
    pose_map = {
        'frame_id': MAP_FRAME,
        'position_xyz': list(map_tag[0]),
        'orientation_xyzw': list(map_tag[1]),
    }
    return BoundTagPose(
        target=validated['target'], timestamp_ns=validated['timestamp_ns'],
        age_ns=validated['age_ns'],
        confidence=float(observation['quality']['confidence']),
        calibration_sha256=expected_identity['sha256'],
        source_sha256=digest, pose_map=pose_map,
        calibration_geometry=calibration_geometry,
        _seal=_BOUND_POSE_SEAL)
