#!/usr/bin/env python3
"""Offline V1 acceptance report calculator; starts no ROS and no hardware."""

import argparse
import csv
import json
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.acceptance_metrics import (  # noqa: E402
    PlanarPose,
    repeatability,
    split_endpoint_errors,
    threshold_result,
)


REPEATABILITY_MAX_STDDEV_X_M = 0.05
REPEATABILITY_MAX_STDDEV_Y_M = 0.05
REPEATABILITY_MAX_YAW_STDDEV_RAD = 5.0 * 3.141592653589793 / 180.0
AMCL_MAX_POSITION_ERROR_M = 0.10
NAVIGATION_CONTROL_MAX_POSITION_ERROR_M = 0.10
PHYSICAL_ENDPOINT_MAX_POSITION_ERROR_M = 0.15
NAVIGATION_CONTROLLER_XY_GOAL_TOLERANCE_M = 0.15


def _pose(value, name):
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'yaw'}:
        raise ValueError('{} must contain exactly x/y/yaw'.format(name))
    return PlanarPose(value['x'], value['y'], value['yaw'])


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_new(path, payload):
    target = Path(path)
    if not target.is_absolute():
        raise ValueError('output path must be absolute')
    if target.exists():
        raise ValueError('output file already exists')
    if not target.parent.is_dir():
        raise ValueError('output parent directory must already exist')
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8')


def endpoint_report(input_path):
    payload = _read_json(input_path)
    if set(payload) != {
            'schema', 'active_map_id', 'goal', 'amcl_final',
            'ground_truth_final'}:
        raise ValueError('endpoint input fields do not match v1')
    if payload['schema'] != 'limo_v1_endpoint_measurement/v1':
        raise ValueError('endpoint input schema mismatch')
    result = split_endpoint_errors(
        _pose(payload['goal'], 'goal'),
        _pose(payload['amcl_final'], 'amcl_final'),
        _pose(payload['ground_truth_final'], 'ground_truth_final'))
    checks = {
        'amcl_estimation_position': threshold_result(
            result['amcl_estimation_error']['position_m'],
            AMCL_MAX_POSITION_ERROR_M),
        'navigation_control_endpoint_position': threshold_result(
            result['controller_estimated_frame_error']['position_m'],
            NAVIGATION_CONTROL_MAX_POSITION_ERROR_M),
        'physical_total_endpoint_position': threshold_result(
            result['physical_total_endpoint_error']['position_m'],
            PHYSICAL_ENDPOINT_MAX_POSITION_ERROR_M),
    }
    return {
        'schema': 'limo_v1_endpoint_error_report/v1',
        'active_map_id': payload['active_map_id'],
        **result,
        'checks': checks,
        'overall_passed': all(item['passed'] for item in checks.values()),
        'interpretation': {
            'amcl_estimation_error':
                'external truth minus AMCL estimate',
            'controller_estimated_frame_error':
                'navigation control endpoint error: goal minus AMCL final pose',
            'physical_total_endpoint_error':
                'goal minus externally measured final pose',
        },
        'configured_controller_contract': {
            'xy_goal_tolerance_m':
                NAVIGATION_CONTROLLER_XY_GOAL_TOLERANCE_M,
            'note': (
                'move_base may report success inside this estimated-frame '
                'radius; it is not AMCL absolute accuracy'),
        },
    }


def repeatability_report(csv_path):
    rows = []
    with Path(csv_path).open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['x', 'y', 'yaw']:
            raise ValueError('CSV header must be exactly x,y,yaw')
        for row in reader:
            rows.append(PlanarPose(
                float(row['x']), float(row['y']), float(row['yaw'])))
    metrics = repeatability(rows)
    checks = {
        'repeatability_stddev_x': threshold_result(
            metrics['stddev_x_m'], REPEATABILITY_MAX_STDDEV_X_M),
        'repeatability_stddev_y': threshold_result(
            metrics['stddev_y_m'], REPEATABILITY_MAX_STDDEV_Y_M),
        'repeatability_yaw_stddev': threshold_result(
            metrics['circular_std_yaw_rad'],
            REPEATABILITY_MAX_YAW_STDDEV_RAD),
    }
    return {
        'schema': 'limo_v1_localization_repeatability/v1',
        **metrics,
        'checks': checks,
        'overall_passed': all(item['passed'] for item in checks.values()),
        'absolute_accuracy_proven': False,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    endpoint = subparsers.add_parser('endpoint')
    endpoint.add_argument('--input', required=True)
    endpoint.add_argument('--output', required=True)
    spread = subparsers.add_parser('repeatability')
    spread.add_argument('--csv', required=True)
    spread.add_argument('--output', required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        report = (
            endpoint_report(args.input)
            if args.command == 'endpoint'
            else repeatability_report(args.csv))
        _write_new(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('V1_ACCEPTANCE_REPORT_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
