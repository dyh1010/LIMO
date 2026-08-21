"""Validate the first JYU2C eye-in-hand bottle candidate sample."""

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / "offline_tests" / "eih_jyu2c_single_bottle_20260820"
MANIFEST = SAMPLE_ROOT / "candidate_manifest.json"


def strict_json(path):
    def reject_duplicates(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key: " + key)
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        object_pairs_hook=reject_duplicates,
    )


def iou(left, right):
    ix1 = max(left[0], right[0])
    iy1 = max(left[1], right[1])
    ix2 = min(left[2], right[2])
    iy2 = min(left[3], right[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / (left_area + right_area - intersection)


class EihJyu2cCandidateSampleTest(unittest.TestCase):
    def setUp(self):
        self.manifest = strict_json(MANIFEST)

    def test_sample_is_candidate_only_and_never_motion_authority(self):
        self.assertEqual(
            "HUMAN_REVIEW_REQUIRED_NOT_TRAINING_AUTHORITY",
            self.manifest["status"],
        )
        self.assertFalse(self.manifest["authorizes_motion"])
        self.assertFalse(self.manifest["authorizes_model_release"])
        self.assertFalse(self.manifest["training_admission"]["allowed_now"])

    def test_image_identity_and_camera_identity_are_exact(self):
        image = SAMPLE_ROOT / self.manifest["image"]["relative_path"]
        self.assertEqual(508982, image.stat().st_size)
        self.assertEqual(
            self.manifest["image"]["sha256"],
            hashlib.sha256(image.read_bytes()).hexdigest(),
        )
        camera = self.manifest["camera"]
        self.assertEqual("JoyandAI", camera["vendor"])
        self.assertEqual("JYU2C-2083", camera["model"])
        self.assertFalse(camera["claimed_d405"])
        self.assertEqual("MISSING", camera["intrinsics_status"])
        self.assertEqual("MISSING", camera["hand_eye_status"])

    def test_candidate_yolo_label_matches_pixel_box(self):
        annotation = self.manifest["candidate_annotation"]
        x1, y1, x2, y2 = annotation["bbox_xyxy_px"]
        expected = (
            ((x1 + x2) / 2.0) / 640.0,
            ((y1 + y2) / 2.0) / 480.0,
            (x2 - x1) / 640.0,
            (y2 - y1) / 480.0,
        )
        for actual, value in zip(annotation["yolo_xywh_normalized"], expected):
            self.assertAlmostEqual(value, actual, places=8)
        label_path = SAMPLE_ROOT / annotation["label_relative_path"]
        fields = label_path.read_text(encoding="utf-8").strip().split()
        self.assertEqual("0", fields[0])
        for actual, value in zip(map(float, fields[1:]), expected):
            self.assertAlmostEqual(value, actual, places=8)

    def test_frozen_model_has_zero_candidate_true_matches(self):
        observation = self.manifest["frozen_model_observation"]
        self.assertEqual(
            "ZERO_TRUE_BOTTLE_MATCH_FOUR_GRIPPER_SELF_FALSE_POSITIVES",
            observation["assessment"],
        )
        self.assertEqual(4, len(observation["detections"]))
        truth = self.manifest["candidate_annotation"]["bbox_xyxy_px"]
        overlaps = [iou(truth, item["bbox_xyxy_px"]) for item in observation["detections"]]
        self.assertLess(max(overlaps), 0.20)

    def test_training_requires_positive_and_negative_dataset_closure(self):
        required = set(self.manifest["training_admission"]["required_before_training"])
        self.assertEqual({
            "independent_bbox_review",
            "camera_intrinsics_capture",
            "train_validation_test_split_by_capture_session",
            "additional_positive_views",
            "gripper_only_negative_frames",
            "empty_scene_negative_frames",
            "frozen_dataset_manifest",
        }, required)


if __name__ == "__main__":
    unittest.main()
