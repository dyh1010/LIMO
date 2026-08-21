import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
SCRIPT = PACKAGE_ROOT / 'scripts' / 'v1_acceptance_report.py'


class AcceptanceReportCliTest(unittest.TestCase):

    def test_endpoint_cli_keeps_three_error_classes_and_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / 'endpoint.json'
            output_path = root / 'report.json'
            input_path.write_text(json.dumps({
                'schema': 'limo_v1_endpoint_measurement/v1',
                'active_map_id': 'limo_v1_map',
                'goal': {'x': 1.0, 'y': 0.0, 'yaw': 0.0},
                'amcl_final': {'x': 0.98, 'y': 0.0, 'yaw': 0.0},
                'ground_truth_final': {'x': 0.90, 'y': 0.0, 'yaw': 0.0},
            }), encoding='utf-8')
            result = subprocess.run([
                sys.executable, str(SCRIPT), 'endpoint',
                '--input', str(input_path), '--output', str(output_path),
            ], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output_path.read_text(encoding='utf-8'))
            self.assertIn('amcl_estimation_error', report)
            self.assertIn('controller_estimated_frame_error', report)
            self.assertIn('physical_total_endpoint_error', report)
            self.assertEqual(set(report['checks']), {
                'amcl_estimation_position',
                'navigation_control_endpoint_position',
                'physical_total_endpoint_position',
            })
            self.assertEqual(
                report['configured_controller_contract'][
                    'xy_goal_tolerance_m'], 0.15)
            self.assertIn(
                'not AMCL absolute accuracy',
                report['configured_controller_contract']['note'])

    def test_repeatability_cli_reports_spread_not_absolute_accuracy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / 'samples.csv'
            output_path = root / 'report.json'
            with input_path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['x', 'y', 'yaw'])
                writer.writerows([
                    [1.00, 2.00, 0.10],
                    [1.01, 2.01, 0.11],
                    [0.99, 1.99, 0.09],
                ])
            result = subprocess.run([
                sys.executable, str(SCRIPT), 'repeatability',
                '--csv', str(input_path), '--output', str(output_path),
            ], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output_path.read_text(encoding='utf-8'))
            self.assertFalse(report['absolute_accuracy_proven'])
            self.assertTrue(report['overall_passed'])
            self.assertEqual(report['samples'], 3)

    def test_cli_refuses_to_overwrite_an_existing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / 'samples.csv'
            output_path = root / 'report.json'
            input_path.write_text('x,y,yaw\n0,0,0\n0,0,0\n', encoding='utf-8')
            output_path.write_text('{}\n', encoding='utf-8')
            result = subprocess.run([
                sys.executable, str(SCRIPT), 'repeatability',
                '--csv', str(input_path), '--output', str(output_path),
            ], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn('output file already exists', result.stderr)


if __name__ == '__main__':
    unittest.main()
