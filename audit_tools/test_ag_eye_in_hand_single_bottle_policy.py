"""Offline contract tests for the AG eye-in-hand single-bottle run card."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "ag_eye_in_hand_single_bottle_experiment_policy.json"
RUN_CARD_PATH = ROOT / "docs" / "AG_EYE_IN_HAND_SINGLE_BOTTLE_RUN_CARD_20260820.md"


def strict_json(path):
    def reject_constant(value):
        raise ValueError("non-finite constant: " + value)

    def reject_duplicates(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key: " + key)
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


class AgEyeInHandSingleBottlePolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = strict_json(POLICY_PATH)
        self.run_card = RUN_CARD_PATH.read_text(encoding="utf-8")

    def test_policy_is_globally_offline_and_fail_closed(self):
        self.assertEqual("OFFLINE_ONLY_REAL_EXECUTION_BLOCKED", self.policy["status"])
        for key in (
            "authorizes_connection",
            "authorizes_power",
            "authorizes_motion",
            "authorizes_field_execution",
        ):
            self.assertIs(False, self.policy[key], key)
        self.assertIn("cannot authorize", self.policy["release_statement"])

    def test_only_two_argument_ag_write_is_candidate(self):
        protocol = self.policy["protocol_candidate"]
        self.assertEqual("set_gripper_value(value, speed)", protocol["write_api_exact"])
        self.assertEqual("FE FE 04 67 VV SS FA", protocol["write_frame_exact"])
        self.assertEqual(2, protocol["write_argument_count"])
        self.assertEqual("get_gripper_value()", protocol["read_position_api_exact"])
        self.assertEqual("FE FE 02 65 FA", protocol["read_position_frame_exact"])
        self.assertEqual("is_gripper_moving()", protocol["read_moving_api_exact"])
        self.assertEqual("FE FE 02 69 FA", protocol["read_moving_frame_exact"])
        self.assertEqual("gripper_type", protocol["forbidden_extension_field"])
        self.assertFalse(protocol["automatic_protocol_detection"])
        self.assertFalse(protocol["fallback_to_extension_frame"])
        self.assertFalse(protocol["command_return_is_ack"])
        self.assertFalse(protocol["software_close_is_stop"])
        self.assertFalse(protocol["torque_or_current_write_authorized"])
        self.assertFalse(protocol["calibration_or_homing_authorized"])
        self.assertEqual(
            {
                "set_gripper_value(value, speed, type)",
                "get_gripper_value(type)",
                "FE FE 05 67 VV SS TT FA",
                "FE FE 03 65 TT FA",
            },
            set(protocol["forbidden_examples"]),
        )

    def test_mount_contract_covers_camera_connector_cable_and_occlusion(self):
        mount = self.policy["mount_contract"]
        self.assertEqual("SIDE_UPPER_BEHIND_FINGERTIP_PLANE", mount["strategy"])
        self.assertEqual("MEASUREMENT_REQUIRED", mount["exact_transform_status"])
        required_true = (
            "camera_body_inside_collision_model",
            "connector_inside_collision_model",
            "cable_inside_swept_envelope",
            "two_point_strain_relief_required",
            "vendor_minimum_bend_radius_required",
            "finger_swept_volume_intersection_forbidden",
            "direct_grasp_center_line_of_sight_required",
            "open_closed_self_occlusion_masks_required",
            "arm_link_occlusion_masks_required",
            "payload_and_center_of_mass_reapproval_required",
        )
        self.assertTrue(all(mount[key] is True for key in required_true))
        self.assertEqual(7, len(mount["required_static_cases"]))

    def test_eye_in_hand_reacquires_after_every_motion(self):
        vision = self.policy["vision_contract"]
        self.assertTrue(vision["global_camera_can_be_occluded_by_arm"])
        self.assertEqual(
            "pregrasp_reacquisition_and_relative_pose_refinement",
            vision["eye_in_hand_role"],
        )
        self.assertFalse(vision["online_learning_during_motion"])
        self.assertFalse(vision["autonomous_exploration"])
        for key in (
            "single_actionable_object_required",
            "fresh_frame_after_each_motion_required",
            "same_bottle_identity_continuity_required",
            "camera_intrinsics_required",
            "hand_eye_transform_required",
            "timestamp_and_frame_identity_required",
            "synthetic_or_template_transform_forbidden",
        ):
            self.assertIs(True, vision[key], key)

    def test_every_field_step_has_observation_stop_and_human_isolation(self):
        steps = self.policy["field_steps"]
        self.assertEqual(["S%02d" % value for value in range(11)], [s["id"] for s in steps])
        self.assertEqual(11, len({step["name"] for step in steps}))
        for step in steps:
            self.assertIsInstance(step["motion"], bool)
            self.assertTrue(step["observation"].strip(), step["id"])
            self.assertTrue(step["stop_condition"].strip(), step["id"])
            self.assertTrue(step["human_isolation"].strip(), step["id"])
        self.assertFalse(any(step["motion"] for step in steps[:5]))
        self.assertEqual(["S05", "S06", "S07", "S08", "S10"], [
            step["id"] for step in steps if step["motion"]
        ])

    def test_physical_stop_and_one_motion_authorization_are_non_negotiable(self):
        safety = self.policy["physical_safety_contract"]
        for key in (
            "base_mechanical_lock_required",
            "base_power_isolation_required",
            "arm_workspace_clear_required",
            "one_operator_one_safety_observer_required",
            "human_power_isolator_in_reach_required",
            "software_stop_is_not_physical_isolation",
            "one_motion_per_explicit_authorization",
            "no_person_in_swept_volume",
            "no_grasped_payload_other_than_one_empty_test_bottle",
            "first_anomaly_no_retry",
        ):
            self.assertIs(True, safety[key], key)

    def test_run_card_does_not_smuggle_an_executable_extended_call(self):
        compact = "".join(self.run_card.split())
        forbidden_calls = (
            "set_gripper_value(5,30,1)",
            "set_gripper_value(100,30,1)",
            "get_gripper_value(1)",
            "mc.set_gripper_calibration()",
            "mc.init_gripper()",
        )
        for token in forbidden_calls:
            self.assertNotIn("".join(token.split()), compact)
        self.assertIn("FEFE0467VVSSFA", compact)
        self.assertIn("FEFE0567VVSSTTFA", compact)
        self.assertIn("明确禁止", self.run_card)

    def test_camera_identity_discrepancy_remains_blocked(self):
        hardware = self.policy["hardware_candidate"]
        self.assertEqual(
            "Intel RealSense D405 side-upper eye-in-hand",
            hardware["wrist_camera_mount_candidate"],
        )
        self.assertEqual("REQUIRED_NOT_VERIFIED", hardware["wrist_camera_identity_status"])
        self.assertIn("JYU2C-2083", self.run_card)
        self.assertIn("不得混称", self.run_card)


if __name__ == "__main__":
    unittest.main()
