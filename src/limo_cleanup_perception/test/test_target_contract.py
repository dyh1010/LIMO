"""Unit tests for robust read-only 2D-to-3D target projection."""

import ast
import math
import unittest
from pathlib import Path

import numpy as np

from limo_cleanup_perception.perception_core import Detection2D
from limo_cleanup_perception.target_contract import (
    EXPECTED_MODEL_SHA256,
    ProjectionConfig,
    bundle_signature,
    project_detection,
    require_single_class_model,
)


def detection(x1=300, y1=220, x2=340, y2=300):
    """Create one valid bottle detection."""
    return Detection2D('plastic_bottle', 0.9, x1, y1, x2, y2)


CAMERA_MATRIX = (500.0, 0.0, 320.0, 0.0, 500.0, 240.0, 0.0, 0.0, 1.0)


class TargetContractTest(unittest.TestCase):
    """Exercise projection quality, model identity, and bundle identity."""

    def test_integer_and_float_depth_project_to_same_metric_point(self):
        """16UC1 millimetres and 32FC1 metres must agree."""
        integer = np.full((480, 640), 1200, dtype=np.uint16)
        floating = np.full((480, 640), 1.2, dtype=np.float32)
        config = ProjectionConfig()

        first = project_detection(detection(), integer, CAMERA_MATRIX, config)
        second = project_detection(
            detection(), floating, CAMERA_MATRIX, config, '32FC1')

        self.assertTrue(first.valid and second.valid)
        np.testing.assert_allclose(
            first.point, (0.0, 0.048, 1.2), atol=1e-6, rtol=0.0)
        np.testing.assert_allclose(
            second.point, first.point, atol=1e-6, rtol=0.0)
        self.assertEqual(1.0, first.valid_ratio)
        self.assertAlmostEqual(0.01, first.size[2])

    def test_depth_encoding_and_dtype_must_agree(self):
        floating = np.full((480, 640), 1.2, dtype=np.float32)
        integer = np.full((480, 640), 1200, dtype=np.uint16)
        config = ProjectionConfig()
        self.assertEqual(
            'depth_encoding_dtype_mismatch', project_detection(
                detection(), floating, CAMERA_MATRIX, config,
                '16UC1').error_code)
        self.assertEqual(
            'depth_encoding_dtype_mismatch', project_detection(
                detection(), integer, CAMERA_MATRIX, config,
                '32FC1').error_code)
        self.assertEqual(
            'unsupported_depth_encoding', project_detection(
                detection(), integer, CAMERA_MATRIX, config,
                '8UC1').error_code)

    def test_projection_reports_depth_quality_and_fail_closed_errors(self):
        """Sparse, invalid, and out-of-image depth never become targets."""
        sparse = np.zeros((100, 100), dtype=np.uint16)
        sparse[45:47, 45:47] = 1000
        result = project_detection(
            detection(20, 20, 80, 80), sparse,
            (100.0, 0.0, 50.0, 0.0, 100.0, 50.0, 0.0, 0.0, 1.0),
            ProjectionConfig(min_valid_pixels=5),
        )
        self.assertFalse(result.valid)
        self.assertEqual('insufficient_depth_pixels', result.error_code)
        self.assertIsNone(result.point)
        self.assertEqual(4, result.valid_pixels)
        self.assertGreater(result.total_pixels, result.valid_pixels)

        outside = project_detection(
            detection(700, 10, 800, 100),
            np.full((480, 640), 1000, dtype=np.uint16),
            CAMERA_MATRIX, ProjectionConfig())
        self.assertFalse(outside.valid)
        self.assertEqual('bbox_outside_image', outside.error_code)

    def test_projection_rejects_bad_intrinsics_bbox_and_ratio(self):
        """Invalid geometry and quality limits are explicit errors."""
        depth = np.full((100, 100), 1.0, dtype=np.float32)
        bad_intrinsics = project_detection(
            detection(10, 10, 90, 90), depth,
            (0.0, 0.0, 50.0, 0.0, 100.0, 50.0, 0.0, 0.0, 1.0),
            ProjectionConfig(), '32FC1')
        self.assertEqual(
            'camera_intrinsics_not_positive', bad_intrinsics.error_code)

        malformed = project_detection(
            detection(10, 10, float('nan'), 90), depth,
            CAMERA_MATRIX, ProjectionConfig(), '32FC1')
        self.assertEqual('bbox_not_finite', malformed.error_code)

        mostly_empty = np.zeros((100, 100), dtype=np.uint16)
        mostly_empty[40:45, 40:45] = 1000
        ratio = project_detection(
            detection(0, 0, 100, 100), mostly_empty,
            (100.0, 0.0, 50.0, 0.0, 100.0, 50.0, 0.0, 0.0, 1.0),
            ProjectionConfig(min_valid_ratio=0.10))
        self.assertEqual('insufficient_depth_ratio', ratio.error_code)
        self.assertTrue(math.isclose(ratio.valid_ratio, 25 / 1600))

    def test_model_label_contract_rejects_wrong_or_multiclass_weights(self):
        """A swapped or multi-class weight cannot be silently relabeled."""
        require_single_class_model({0: 'plastic_bottle'}, 'plastic_bottle')
        with self.assertRaisesRegex(ValueError, 'expected single class'):
            require_single_class_model({0: 'trash_bin'}, 'plastic_bottle')
        with self.assertRaisesRegex(ValueError, 'expected single class'):
            require_single_class_model(
                {0: 'plastic_bottle', 1: 'can'}, 'plastic_bottle')

    def test_bundle_signature_changes_when_same_rgb_gets_new_depth(self):
        """A new nearest depth may retry an RGB frame without status spam."""
        class Metadata:
            pass

        rgb = Metadata()
        rgb.name, rgb.stamp_sec, rgb.frame_id = 'rgb', 10.0, 'camera'
        rgb.width, rgb.height = 640, 480
        depth = Metadata()
        depth.name, depth.stamp_sec, depth.frame_id = (
            'depth', 10.02, 'camera')
        depth.width, depth.height = 640, 480
        first = bundle_signature(rgb, depth)
        depth.stamp_sec = 10.03
        second = bundle_signature(rgb, depth)
        self.assertNotEqual(first, second)

    def test_model_hashes_match_release_policy(self):
        """Runtime and release gates cannot silently drift model hashes."""
        policy_path = Path(__file__).parents[3] / (
            'scripts/perception_release_policy.py')
        tree = ast.parse(policy_path.read_text(encoding='utf-8'))
        literal = None
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name)
                            and target.id == 'EXPECTED_MODELS'
                            for target in node.targets)):
                literal = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(literal)
        self.assertEqual(
            EXPECTED_MODEL_SHA256['plastic_bottle'],
            literal['nongfu_yolov8n_best.pt'])
        self.assertEqual(
            EXPECTED_MODEL_SHA256['trash_bin'],
            literal['trash_bin_yolov8n_best.pt'])


if __name__ == '__main__':
    unittest.main()
