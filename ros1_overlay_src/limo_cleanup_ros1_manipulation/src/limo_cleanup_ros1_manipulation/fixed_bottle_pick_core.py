"""Fail-closed fixed-position bottle pickup planning without ROS or hardware."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


SCHEMA_VERSION = 1
OFFLINE_MODE = 'LOCAL_OFFLINE_PREVIEW_ONLY'
TARGET_FRAME = 'arm_base_link'
OBJECT_CLASS = 'plastic_bottle'
APPROVED_GRIPPER_SOURCE_SHA256 = (
    '62508BEA0CB96817099DC8EFDE10FEB034CAD7A844A95FEFDD29A3F57A6BBD18')


class PickPlanRejected(ValueError):
    """Raised when an input cannot produce an offline pickup preview."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PickStage:
    """One immutable stage of the preview-only pickup plan."""

    name: str
    owner: str
    pose_m_rad: Tuple[float, ...] = ()
    gripper_target: int = -1
    gripper_speed: int = -1


@dataclass(frozen=True)
class PickPlan:
    """A preview plan that cannot itself command an arm or gripper."""

    plan_id: str
    observation_id: str
    policy_sha256: str
    stages: Tuple[PickStage, ...]
    execution_permitted: bool = False
    disposition: str = 'PREVIEW_ONLY_REAL_EXECUTION_BLOCKED'


def _reject(condition: bool, code: str) -> None:
    if condition:
        raise PickPlanRejected(code)


def _exact_keys(value: Mapping[str, Any], expected: Sequence[str], label: str) -> None:
    _reject(not isinstance(value, Mapping), label + '_not_mapping')
    if set(value) != set(expected):
        raise PickPlanRejected(label + '_keys_invalid')


def _number(value: Any, code: str) -> float:
    _reject(isinstance(value, bool) or not isinstance(value, (int, float)), code)
    result = float(value)
    _reject(not math.isfinite(result), code)
    return result


def _vector(value: Any, size: int, code: str) -> Tuple[float, ...]:
    _reject(not isinstance(value, list) or len(value) != size, code)
    return tuple(_number(item, code) for item in value)


def _range(value: Any, code: str) -> Tuple[float, float]:
    low, high = _vector(value, 2, code)
    _reject(low >= high, code)
    return low, high


def canonical_policy_bytes(policy: Mapping[str, Any]) -> bytes:
    """Return deterministic bytes used to bind a plan to its policy."""
    return json.dumps(
        policy, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')


def policy_sha256(policy: Mapping[str, Any]) -> str:
    """Return the canonical policy identity."""
    return hashlib.sha256(canonical_policy_bytes(policy)).hexdigest().upper()


def validate_gripper_source_bytes(
        policy: Mapping[str, Any], payload: bytes) -> str:
    """Bind the runtime gripper file bytes to the approved field record."""
    validate_policy(policy)
    _reject(not isinstance(payload, bytes) or not payload, 'gripper_source_empty')
    digest = hashlib.sha256(payload).hexdigest().upper()
    _reject(
        digest != policy['gripper']['source_config_sha256'],
        'gripper_source_bytes_mismatch')
    return digest


def validate_policy(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a complete host-owned offline policy."""
    _exact_keys(policy, (
        'schema_version', 'mode', 'object_class', 'target_frame',
        'minimum_confidence', 'maximum_target_age_s', 'fixed_target',
        'geometry', 'workspace', 'gripper', 'runtime',
    ), 'policy')
    _reject(policy['schema_version'] != SCHEMA_VERSION, 'schema_version_invalid')
    _reject(policy['mode'] != OFFLINE_MODE, 'mode_not_offline_preview')
    _reject(policy['object_class'] != OBJECT_CLASS, 'object_class_invalid')
    _reject(policy['target_frame'] != TARGET_FRAME, 'target_frame_invalid')

    minimum_confidence = _number(
        policy['minimum_confidence'], 'minimum_confidence_invalid')
    _reject(not 0.0 < minimum_confidence <= 1.0, 'minimum_confidence_invalid')
    maximum_target_age_s = _number(
        policy['maximum_target_age_s'], 'maximum_target_age_invalid')
    _reject(maximum_target_age_s <= 0.0, 'maximum_target_age_invalid')

    fixed = policy['fixed_target']
    _exact_keys(fixed, (
        'position_m', 'position_tolerance_m', 'orientation_attestation_id',
        'tool_rpy_rad',
    ), 'fixed_target')
    position_m = _vector(fixed['position_m'], 3, 'fixed_position_invalid')
    position_tolerance_m = _number(
        fixed['position_tolerance_m'], 'position_tolerance_invalid')
    _reject(position_tolerance_m <= 0.0, 'position_tolerance_invalid')
    orientation_attestation_id = fixed['orientation_attestation_id']
    _reject(
        not isinstance(orientation_attestation_id, str)
        or not orientation_attestation_id.strip(),
        'orientation_attestation_missing')
    tool_rpy_rad = _vector(fixed['tool_rpy_rad'], 3, 'tool_rpy_invalid')

    geometry = policy['geometry']
    _exact_keys(geometry, (
        'target_to_grasp_tcp_m', 'pregrasp_clearance_m', 'lift_clearance_m',
    ), 'geometry')
    target_to_grasp = _vector(
        geometry['target_to_grasp_tcp_m'], 3, 'target_to_grasp_invalid')
    pregrasp_clearance = _number(
        geometry['pregrasp_clearance_m'], 'pregrasp_clearance_invalid')
    lift_clearance = _number(
        geometry['lift_clearance_m'], 'lift_clearance_invalid')
    _reject(pregrasp_clearance <= 0.0, 'pregrasp_clearance_invalid')
    _reject(lift_clearance <= 0.0, 'lift_clearance_invalid')

    workspace = policy['workspace']
    _exact_keys(workspace, ('x_m', 'y_m', 'z_m'), 'workspace')
    workspace_ranges = tuple(
        _range(workspace[key], 'workspace_' + key + '_invalid')
        for key in ('x_m', 'y_m', 'z_m')
    )

    gripper = policy['gripper']
    _exact_keys(gripper, (
        'source_config_sha256', 'gripper_type', 'open_target',
        'bottle_60mm_target', 'speed', 'protect_current', 'hold_success',
    ), 'gripper')
    source_hash = gripper['source_config_sha256']
    _reject(
        not isinstance(source_hash, str)
        or source_hash != APPROVED_GRIPPER_SOURCE_SHA256,
        'gripper_source_hash_invalid')
    for key, low, high in (
            ('gripper_type', 1, 1), ('open_target', 0, 100),
            ('bottle_60mm_target', 0, 100), ('speed', 1, 100),
            ('protect_current', 1, 10000)):
        value = gripper[key]
        _reject(type(value) is not int or not low <= value <= high, key + '_invalid')
    _reject(
        gripper['bottle_60mm_target'] >= gripper['open_target'],
        'gripper_targets_invalid')
    hold = gripper['hold_success']
    _exact_keys(hold, (
        'moving_required', 'feedback_range', 'bottle_clamped_required',
        'no_abnormal_sound_required', 'no_overheat_required',
    ), 'hold_success')
    _reject(hold['moving_required'] is not True, 'moving_required_must_be_true')
    feedback_range = _range(hold['feedback_range'], 'feedback_range_invalid')
    for key in (
            'bottle_clamped_required', 'no_abnormal_sound_required',
            'no_overheat_required'):
        _reject(hold[key] is not True, key + '_must_be_true')

    runtime = policy['runtime']
    _exact_keys(runtime, (
        'dry_run', 'allow_arm_motion', 'allow_gripper_motion',
        'vendor_backend_allowed', 'device_access_allowed',
    ), 'runtime')
    _reject(runtime['dry_run'] is not True, 'dry_run_required')
    for key in (
            'allow_arm_motion', 'allow_gripper_motion',
            'vendor_backend_allowed', 'device_access_allowed'):
        _reject(runtime[key] is not False, key + '_must_be_false')

    return {
        'minimum_confidence': minimum_confidence,
        'maximum_target_age_s': maximum_target_age_s,
        'fixed_position_m': position_m,
        'position_tolerance_m': position_tolerance_m,
        'tool_rpy_rad': tool_rpy_rad,
        'target_to_grasp_tcp_m': target_to_grasp,
        'pregrasp_clearance_m': pregrasp_clearance,
        'lift_clearance_m': lift_clearance,
        'workspace_ranges': workspace_ranges,
        'feedback_range': feedback_range,
    }


def _position_inside(position: Sequence[float], ranges) -> bool:
    return all(low <= value <= high for value, (low, high) in zip(position, ranges))


def _target_position(target: Mapping[str, Any]) -> Tuple[float, float, float]:
    position = target.get('position')
    _reject(not isinstance(position, Mapping), 'target_position_invalid')
    _exact_keys(position, ('x', 'y', 'z'), 'target_position')
    return tuple(
        _number(position[key], 'target_position_invalid')
        for key in ('x', 'y', 'z')
    )


def plan_fixed_bottle_pick(
        policy: Mapping[str, Any], frame: Mapping[str, Any],
        now_s: float) -> PickPlan:
    """Build a five-stage preview plan from one fresh ROS1 perception frame."""
    normalized = validate_policy(policy)
    current_time = _number(now_s, 'now_invalid')
    _exact_keys(frame, (
        'frame_id', 'stamp_s', 'status', 'tf_valid', 'targets',
    ), 'frame')
    _reject(frame['frame_id'] != TARGET_FRAME, 'frame_not_arm_base_link')
    _reject(frame['tf_valid'] is not True, 'frame_tf_invalid')
    _reject(frame['status'] != 'targets_ready', 'frame_not_ready')
    stamp_s = _number(frame['stamp_s'], 'frame_stamp_invalid')
    age = current_time - stamp_s
    _reject(age < 0.0, 'frame_from_future')
    _reject(age > normalized['maximum_target_age_s'], 'frame_stale')
    targets = frame['targets']
    _reject(not isinstance(targets, list), 'targets_not_list')
    candidates = [
        target for target in targets
        if isinstance(target, Mapping)
        and target.get('object_class') == OBJECT_CLASS
        and target.get('valid') is True
        and target.get('actionable') is True
        and target.get('status') == 'active'
    ]
    _reject(len(candidates) != 1, 'exactly_one_actionable_bottle_required')
    target = candidates[0]
    observation_id = target.get('observation_id')
    _reject(
        not isinstance(observation_id, str) or not observation_id.strip(),
        'observation_id_missing')
    confidence = _number(target.get('confidence'), 'confidence_invalid')
    _reject(
        confidence < normalized['minimum_confidence'],
        'confidence_below_minimum')
    position = _target_position(target)
    drift = math.sqrt(sum(
        (actual - expected) ** 2
        for actual, expected in zip(position, normalized['fixed_position_m'])
    ))
    _reject(
        drift > normalized['position_tolerance_m'],
        'target_outside_fixed_fixture_tolerance')

    grasp_xyz = tuple(
        value + offset
        for value, offset in zip(position, normalized['target_to_grasp_tcp_m'])
    )
    pregrasp_xyz = (
        grasp_xyz[0], grasp_xyz[1],
        grasp_xyz[2] + normalized['pregrasp_clearance_m'],
    )
    lift_xyz = (
        grasp_xyz[0], grasp_xyz[1],
        grasp_xyz[2] + normalized['lift_clearance_m'],
    )
    for name, stage_position in (
            ('pregrasp', pregrasp_xyz), ('grasp', grasp_xyz),
            ('lift', lift_xyz)):
        _reject(
            not _position_inside(stage_position, normalized['workspace_ranges']),
            name + '_outside_workspace')
    rpy = normalized['tool_rpy_rad']
    pose = lambda xyz: tuple(xyz) + tuple(rpy)
    gripper = policy['gripper']
    stages = (
        PickStage(
            'open_gripper', 'gripper', gripper_target=gripper['open_target'],
            gripper_speed=gripper['speed']),
        PickStage('move_pregrasp', 'arm', pose(pregrasp_xyz)),
        PickStage('descend_to_grasp', 'arm', pose(grasp_xyz)),
        PickStage(
            'close_hold', 'gripper',
            gripper_target=gripper['bottle_60mm_target'],
            gripper_speed=gripper['speed']),
        PickStage('lift_vertical', 'arm', pose(lift_xyz)),
    )
    policy_hash = policy_sha256(policy)
    plan_id = hashlib.sha256(
        (policy_hash + '|' + observation_id + '|' + str(stamp_s)).encode('utf-8')
    ).hexdigest().upper()
    return PickPlan(plan_id, observation_id, policy_hash, stages)


def evaluate_user_approved_hold(
        policy: Mapping[str, Any], observation: Mapping[str, Any]) -> bool:
    """Apply the operator-approved continuous-hold success definition."""
    normalized = validate_policy(policy)
    _exact_keys(observation, (
        'moving', 'feedback_value', 'bottle_clamped',
        'no_abnormal_sound', 'no_overheat', 'faulted',
    ), 'hold_observation')
    _reject(observation['moving'] is not True, 'hold_moving_not_true')
    feedback = _number(observation['feedback_value'], 'hold_feedback_invalid')
    low, high = normalized['feedback_range']
    _reject(not low <= feedback <= high, 'hold_feedback_outside_range')
    _reject(observation['bottle_clamped'] is not True, 'bottle_not_clamped')
    _reject(
        observation['no_abnormal_sound'] is not True,
        'abnormal_sound_not_cleared')
    _reject(observation['no_overheat'] is not True, 'overheat_not_cleared')
    _reject(observation['faulted'] is not False, 'hold_faulted')
    return True


def frame_from_ros_message(message: Any) -> Dict[str, Any]:
    """Map the existing ROS1 PerceptionFrame shape without importing ROS."""
    stamp = getattr(message, 'stamp', None)
    stamp_s = float(stamp.to_sec()) if stamp is not None else math.nan
    targets = []
    for item in getattr(message, 'targets', ()):
        targets.append({
            'observation_id': str(getattr(item, 'observation_id', '')),
            'object_class': str(getattr(item, 'object_class', '')),
            'confidence': float(getattr(item, 'confidence', math.nan)),
            'valid': getattr(item, 'valid', None),
            'actionable': getattr(item, 'actionable', None),
            'status': str(getattr(item, 'status', '')),
            'position': {
                'x': float(getattr(getattr(item, 'position', None), 'x', math.nan)),
                'y': float(getattr(getattr(item, 'position', None), 'y', math.nan)),
                'z': float(getattr(getattr(item, 'position', None), 'z', math.nan)),
            },
        })
    return {
        'frame_id': str(getattr(message, 'tf_target_frame', '')),
        'stamp_s': stamp_s,
        'status': str(getattr(message, 'status', '')),
        'tf_valid': getattr(message, 'tf_valid', None),
        'targets': targets,
    }


def plan_to_dict(plan: PickPlan) -> Dict[str, Any]:
    """Convert a preview plan to a JSON-safe record."""
    return {
        'plan_id': plan.plan_id,
        'observation_id': plan.observation_id,
        'policy_sha256': plan.policy_sha256,
        'execution_permitted': plan.execution_permitted,
        'disposition': plan.disposition,
        'stages': [
            {
                'name': stage.name,
                'owner': stage.owner,
                'pose_m_rad': list(stage.pose_m_rad),
                'gripper_target': stage.gripper_target,
                'gripper_speed': stage.gripper_speed,
            }
            for stage in plan.stages
        ],
    }
