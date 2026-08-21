import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (
    ROOT
    / "src"
    / "limo_cleanup_executor"
    / "config"
    / "ag_gripper_single_bottle_observed.json"
)


class AgGripperSingleBottleObservedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_field_observation_does_not_grant_motion_authority(self):
        self.assertFalse(self.data["production_motion_authority"])
        self.assertEqual(self.data["scope"], "single_bottle_static_grip_only")
        self.assertIn("arm_motion", self.data["not_accepted"])
        self.assertIn("vision_guided_grasp", self.data["not_accepted"])

    def test_exact_observed_grip_baseline(self):
        accepted = self.data["accepted_static_bottle_grip"]
        self.assertEqual(
            {
                "target": accepted["target"],
                "steady_feedback": accepted["steady_feedback"],
                "speed_grade": accepted["speed_grade"],
                "protect_current_readback": accepted["protect_current_readback"],
                "hold_duration_s": accepted["hold_duration_s"],
            },
            {
                "target": 20,
                "steady_feedback": 21,
                "speed_grade": 30,
                "protect_current_readback": 300,
                "hold_duration_s": 15,
            },
        )
        self.assertTrue(accepted["stable"])
        self.assertFalse(accepted["slip_observed"])
        self.assertFalse(accepted["abnormal_noise_or_jitter_observed"])
        self.assertFalse(accepted["abnormal_heat_observed"])

    def test_unverified_tightening_and_hts_torque_stay_rejected(self):
        self.assertIn("tighter_grip_target", self.data["not_accepted"])
        unbound = self.data["unsupported_or_unbound"]
        self.assertTrue(unbound["hts_torque_write"])
        self.assertEqual(unbound["requested_hts_torque"], 500)
        self.assertEqual(unbound["unchanged_hts_torque_readback"], 200)

    def test_ros1_is_default_but_adapter_is_not_claimed(self):
        self.assertEqual(self.data["runtime_default"], "ros1_noetic")
        self.assertIn("ros1_adapter", self.data["not_accepted"])


if __name__ == "__main__":
    unittest.main()
