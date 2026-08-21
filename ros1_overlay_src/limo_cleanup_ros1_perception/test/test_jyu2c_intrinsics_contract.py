import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "jyu2c_intrinsics_640x480.json"


class Jyu2cIntrinsicsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_exact_camera_and_grid_identity(self):
        camera = self.data["camera"]
        self.assertEqual("JYU2C-2083-2603103", camera["serial"])
        self.assertEqual("1bcf", camera["usb_vendor_id"])
        self.assertEqual("2281", camera["usb_model_id"])
        self.assertEqual(
            "/dev/v4l/by-id/usb-JoyandAI_JYU2C-2083_"
            "JYU2C-2083-2603103-video-index0",
            camera["stable_device_path"],
        )
        self.assertEqual((640, 480), (camera["width"], camera["height"]))
        calibration = self.data["calibration"]
        self.assertEqual([11, 8], calibration["checkerboard_inner_corners"])
        self.assertEqual(0.014, calibration["square_size_m"])

    def test_intrinsics_are_finite_and_physically_shaped(self):
        matrix = self.data["camera_matrix"]
        distortion = self.data["distortion_coefficients"]
        self.assertEqual(9, len(matrix))
        self.assertEqual(5, len(distortion))
        self.assertTrue(all(math.isfinite(value) for value in matrix + distortion))
        self.assertGreater(matrix[0], 0.0)
        self.assertGreater(matrix[4], 0.0)
        self.assertTrue(0.0 <= matrix[2] < 640.0)
        self.assertTrue(0.0 <= matrix[5] < 480.0)
        self.assertEqual([0.0, 0.0, 1.0], matrix[6:9])

    def test_reprojection_gates_and_view_denominators(self):
        calibration = self.data["calibration"]
        self.assertEqual(30, calibration["captured_views"])
        self.assertEqual(29, calibration["final_views"])
        self.assertEqual(6, calibration["holdout_views"])
        self.assertLess(calibration["final_rms_px"], 0.25)
        self.assertLess(calibration["holdout_max_rms_px"], 0.25)
        self.assertEqual(["view_04.png"], calibration["excluded_views"])

    def test_intrinsics_never_grant_motion_authority(self):
        self.assertFalse(self.data["motion_authority"])
        self.assertEqual(
            "CALIBRATED_CANDIDATE_PENDING_DEVICE_IDENTITY_REBIND",
            self.data["status"],
        )
        remaining = self.data["remaining_required_gates"]
        self.assertIn("intrinsics_device_identity_rebind", remaining)
        self.assertIn("hand_eye_flange_to_camera", remaining)
        self.assertIn("ik_and_collision_planner", remaining)
        self.assertIn("action_level_motion_authorization", remaining)

    def test_source_identities_are_exact_sha256(self):
        source = self.data["source"]
        for name in ("archive_sha256", "intrinsics_json_sha256", "collector_sha256"):
            value = source[name]
            self.assertEqual(64, len(value))
            int(value, 16)
        self.assertEqual(
            "v1_preview_overlay_not_calibration_evidence",
            source["superseded_capture"],
        )
        self.assertEqual(
            "REBIND_REQUIRED_OR_RECAPTURE",
            source["device_identity_binding"],
        )


if __name__ == "__main__":
    unittest.main()
