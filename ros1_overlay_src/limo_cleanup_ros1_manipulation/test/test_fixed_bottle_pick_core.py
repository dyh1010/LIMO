"""Pure-fake tests for fixed-position bottle pickup preview planning."""

import copy
import json
import math
import unittest
from pathlib import Path

from limo_cleanup_ros1_manipulation.fixed_bottle_pick_core import (
    PickPlanRejected,
    evaluate_user_approved_hold,
    frame_from_ros_message,
    plan_fixed_bottle_pick,
    plan_to_dict,
    policy_sha256,
    validate_gripper_source_bytes,
    validate_policy,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def valid_policy():
    return {
        'schema_version': 1,
        'mode': 'LOCAL_OFFLINE_PREVIEW_ONLY',
        'object_class': 'plastic_bottle',
        'target_frame': 'arm_base_link',
        'minimum_confidence': 0.8,
        'maximum_target_age_s': 0.25,
        'fixed_target': {
            'position_m': [0.20, 0.00, 0.04],
            'position_tolerance_m': 0.02,
            'orientation_attestation_id': 'FIXTURE-ORIENTATION-TEST-ONLY',
            'tool_rpy_rad': [math.pi, 0.0, 0.0],
        },
        'geometry': {
            'target_to_grasp_tcp_m': [0.0, 0.0, 0.02],
            'pregrasp_clearance_m': 0.10,
            'lift_clearance_m': 0.12,
        },
        'workspace': {
            'x_m': [0.10, 0.30],
            'y_m': [-0.10, 0.10],
            'z_m': [0.05, 0.30],
        },
        'gripper': {
            'source_config_sha256': (
                '62508BEA0CB96817099DC8EFDE10FEB034CAD7A844A95FEFDD29A3F57A6BBD18'),
            'gripper_type': 1,
            'open_target': 100,
            'bottle_60mm_target': 5,
            'speed': 30,
            'protect_current': 300,
            'hold_success': {
                'moving_required': True,
                'feedback_range': [18, 20],
                'bottle_clamped_required': True,
                'no_abnormal_sound_required': True,
                'no_overheat_required': True,
            },
        },
        'runtime': {
            'dry_run': True,
            'allow_arm_motion': False,
            'allow_gripper_motion': False,
            'vendor_backend_allowed': False,
            'device_access_allowed': False,
        },
    }


def valid_frame():
    return {
        'frame_id': 'arm_base_link',
        'stamp_s': 10.0,
        'status': 'targets_ready',
        'tf_valid': True,
        'targets': [{
            'observation_id': 'bottle-1',
            'object_class': 'plastic_bottle',
            'confidence': 0.95,
            'valid': True,
            'actionable': True,
            'status': 'active',
            'position': {'x': 0.20, 'y': 0.00, 'z': 0.04},
        }],
    }


def assert_rejected(testcase, code, policy=None, frame=None, now_s=10.1):
    with testcase.assertRaisesRegex(PickPlanRejected, '^' + code + '$'):
        plan_fixed_bottle_pick(
            policy if policy is not None else valid_policy(),
            frame if frame is not None else valid_frame(), now_s)


class FixedBottlePickCoreTest(unittest.TestCase):
    """Verify planning, fail-closed inputs and the approved hold rule."""

    def test_valid_preview_has_exact_five_stages_and_never_permits_execution(self):
        policy = valid_policy()
        plan = plan_fixed_bottle_pick(policy, valid_frame(), 10.1)
        self.assertFalse(plan.execution_permitted)
        self.assertEqual('PREVIEW_ONLY_REAL_EXECUTION_BLOCKED', plan.disposition)
        self.assertEqual(policy_sha256(policy), plan.policy_sha256)
        self.assertEqual([
            'open_gripper', 'move_pregrasp', 'descend_to_grasp',
            'close_hold', 'lift_vertical',
        ], [stage.name for stage in plan.stages])
        self.assertEqual(100, plan.stages[0].gripper_target)
        self.assertEqual(5, plan.stages[3].gripper_target)
        self.assertEqual(30, plan.stages[3].gripper_speed)
        self.assertEqual(
            (0.20, 0.00, 0.16, math.pi, 0.0, 0.0),
            plan.stages[1].pose_m_rad)
        self.assertEqual(
            (0.20, 0.00, 0.06, math.pi, 0.0, 0.0),
            plan.stages[2].pose_m_rad)
        self.assertEqual(
            (0.20, 0.00, 0.18, math.pi, 0.0, 0.0),
            plan.stages[4].pose_m_rad)
        self.assertFalse(plan_to_dict(plan)['execution_permitted'])

    def test_committed_policy_is_intentionally_blocked_until_geometry_is_measured(self):
        policy = json.loads((
            PACKAGE_ROOT / 'config' / 'fixed_bottle_pick_offline.json'
        ).read_text(encoding='utf-8'))
        with self.assertRaises(PickPlanRejected):
            validate_policy(policy)

    def test_policy_rejects_unknown_keys_and_non_offline_runtime(self):
        policy = valid_policy()
        policy['unexpected'] = True
        assert_rejected(self, 'policy_keys_invalid', policy=policy)
        for key in (
                'allow_arm_motion', 'allow_gripper_motion',
                'vendor_backend_allowed', 'device_access_allowed'):
            policy = valid_policy()
            policy['runtime'][key] = True
            assert_rejected(self, key + '_must_be_false', policy=policy)
        policy = valid_policy()
        policy['runtime']['dry_run'] = False
        assert_rejected(self, 'dry_run_required', policy=policy)

    def test_policy_rejects_missing_orientation_and_bad_gripper_binding(self):
        policy = valid_policy()
        policy['fixed_target']['orientation_attestation_id'] = ''
        assert_rejected(self, 'orientation_attestation_missing', policy=policy)
        policy = valid_policy()
        policy['gripper']['source_config_sha256'] = '0' * 64
        assert_rejected(self, 'gripper_source_hash_invalid', policy=policy)
        policy = valid_policy()
        policy['gripper']['hold_success']['moving_required'] = False
        assert_rejected(self, 'moving_required_must_be_true', policy=policy)

    def test_runtime_gripper_source_bytes_are_mechanically_bound(self):
        policy = valid_policy()
        with self.assertRaisesRegex(
                PickPlanRejected, '^gripper_source_bytes_mismatch$'):
            validate_gripper_source_bytes(policy, b'forged-config')
        with self.assertRaisesRegex(PickPlanRejected, '^gripper_source_empty$'):
            validate_gripper_source_bytes(policy, b'')

    def test_frame_identity_freshness_and_tf_fail_closed(self):
        cases = (
            ('frame_not_arm_base_link', 'frame_id', 'base_link'),
            ('frame_tf_invalid', 'tf_valid', False),
            ('frame_not_ready', 'status', 'searching'),
        )
        for code, key, value in cases:
            frame = valid_frame()
            frame[key] = value
            assert_rejected(self, code, frame=frame)
        assert_rejected(self, 'frame_stale', now_s=10.3)
        assert_rejected(self, 'frame_from_future', now_s=9.9)

    def test_target_validity_count_confidence_and_fixed_fixture_fail_closed(self):
        frame = valid_frame()
        frame['targets'][0]['valid'] = False
        assert_rejected(self, 'exactly_one_actionable_bottle_required', frame=frame)
        frame = valid_frame()
        frame['targets'].append(copy.deepcopy(frame['targets'][0]))
        frame['targets'][1]['observation_id'] = 'bottle-2'
        assert_rejected(self, 'exactly_one_actionable_bottle_required', frame=frame)
        frame = valid_frame()
        frame['targets'][0]['confidence'] = 0.79
        assert_rejected(self, 'confidence_below_minimum', frame=frame)
        frame = valid_frame()
        frame['targets'][0]['position']['x'] = 0.23
        assert_rejected(
            self, 'target_outside_fixed_fixture_tolerance', frame=frame)

    def test_nonfinite_and_out_of_workspace_poses_are_rejected(self):
        frame = valid_frame()
        frame['targets'][0]['position']['z'] = math.nan
        assert_rejected(self, 'target_position_invalid', frame=frame)
        policy = valid_policy()
        policy['workspace']['z_m'] = [0.10, 0.30]
        assert_rejected(self, 'grasp_outside_workspace', policy=policy)
        policy = valid_policy()
        policy['workspace']['z_m'] = [0.05, 0.17]
        assert_rejected(self, 'lift_outside_workspace', policy=policy)

    def test_user_approved_continuous_hold_is_success(self):
        observation = {
            'moving': True,
            'feedback_value': 19,
            'bottle_clamped': True,
            'no_abnormal_sound': True,
            'no_overheat': True,
            'faulted': False,
        }
        self.assertTrue(evaluate_user_approved_hold(valid_policy(), observation))

    def test_hold_requires_moving_true_and_all_operator_observations(self):
        base = {
            'moving': True,
            'feedback_value': 19,
            'bottle_clamped': True,
            'no_abnormal_sound': True,
            'no_overheat': True,
            'faulted': False,
        }
        mutations = (
            ('moving', False, 'hold_moving_not_true'),
            ('feedback_value', 21, 'hold_feedback_outside_range'),
            ('bottle_clamped', False, 'bottle_not_clamped'),
            ('no_abnormal_sound', False, 'abnormal_sound_not_cleared'),
            ('no_overheat', False, 'overheat_not_cleared'),
            ('faulted', True, 'hold_faulted'),
        )
        for key, value, code in mutations:
            observation = dict(base)
            observation[key] = value
            with self.assertRaisesRegex(PickPlanRejected, '^' + code + '$'):
                evaluate_user_approved_hold(valid_policy(), observation)

    def test_ros_message_mapping_is_ros_import_free(self):
        class Value:
            pass

        message = Value()
        message.stamp = Value()
        message.stamp.to_sec = lambda: 10.0
        message.tf_target_frame = 'arm_base_link'
        message.status = 'targets_ready'
        message.tf_valid = True
        target = Value()
        target.observation_id = 'bottle-1'
        target.object_class = 'plastic_bottle'
        target.confidence = 0.95
        target.valid = True
        target.actionable = True
        target.status = 'active'
        target.position = Value()
        target.position.x = 0.20
        target.position.y = 0.00
        target.position.z = 0.04
        message.targets = [target]
        self.assertEqual(valid_frame(), frame_from_ros_message(message))

    def test_ros1_top_level_stamp_is_required_not_ros2_header_stamp(self):
        class Value:
            pass

        message = Value()
        message.header = Value()
        message.header.stamp = Value()
        message.header.stamp.to_sec = lambda: 10.0
        message.tf_target_frame = 'arm_base_link'
        message.status = 'targets_ready'
        message.tf_valid = True
        message.targets = []
        frame = frame_from_ros_message(message)
        self.assertTrue(math.isnan(frame['stamp_s']))
        assert_rejected(self, 'frame_stamp_invalid', frame=frame)


if __name__ == '__main__':
    unittest.main()
