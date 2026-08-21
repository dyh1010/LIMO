from pathlib import Path
import sys
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.acceptance_metrics import (  # noqa: E402
    PlanarPose,
    repeatability,
    split_endpoint_errors,
    threshold_result,
)


class AcceptanceMetricsTest(unittest.TestCase):

    def test_endpoint_error_components_are_not_conflated(self):
        result = split_endpoint_errors(
            PlanarPose(1.0, 0.0, 0.0),
            PlanarPose(0.98, 0.0, 0.0),
            PlanarPose(0.90, 0.0, 0.0))
        self.assertAlmostEqual(
            result['amcl_estimation_error']['position_m'], 0.08)
        self.assertAlmostEqual(
            result['controller_estimated_frame_error']['position_m'], 0.02)
        self.assertAlmostEqual(
            result['physical_total_endpoint_error']['position_m'], 0.10)

    def test_repeatability_is_spread_not_absolute_accuracy(self):
        result = repeatability([
            PlanarPose(1.00, 2.00, 0.10),
            PlanarPose(1.02, 1.99, 0.11),
            PlanarPose(0.99, 2.01, 0.09),
        ])
        self.assertEqual(result['samples'], 3)
        self.assertLess(result['stddev_x_m'], 0.02)
        self.assertLess(result['circular_std_yaw_rad'], 0.02)

    def test_nonfinite_and_too_few_samples_are_rejected(self):
        with self.assertRaises(ValueError):
            repeatability([PlanarPose(0.0, 0.0, 0.0)])
        with self.assertRaises(ValueError):
            split_endpoint_errors(
                PlanarPose(0.0, 0.0, 0.0),
                PlanarPose(float('nan'), 0.0, 0.0),
                PlanarPose(0.0, 0.0, 0.0))

    def test_threshold_result_preserves_value_limit_and_pass_fail(self):
        self.assertTrue(threshold_result(0.05, 0.10)['passed'])
        self.assertFalse(threshold_result(0.11, 0.10)['passed'])
        with self.assertRaises(ValueError):
            threshold_result(float('nan'), 0.10)


if __name__ == '__main__':
    unittest.main()
