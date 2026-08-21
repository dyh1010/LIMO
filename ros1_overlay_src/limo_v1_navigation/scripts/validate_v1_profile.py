#!/usr/bin/env python3
"""Offline/static validator for V1 profile and frozen map inputs."""

import argparse
import json
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.config_policy import (  # noqa: E402
    load_profile,
    validate_amcl_transform_tolerance,
    validate_runtime_request,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--profile',
        default=str(PACKAGE_ROOT / 'config' / 'v1_navigation_profile.yaml'))
    parser.add_argument(
        '--stage', choices=('scan', 'mapping', 'localization', 'navigation'),
        default='scan')
    parser.add_argument('--map-file')
    parser.add_argument('--active-map-id')
    parser.add_argument(
        '--mode', choices=('native', 'integrated'), default='native')
    parser.add_argument('--cmd-vel-output-topic')
    parser.add_argument('--allow-nonzero', action='store_true')
    parser.add_argument('--driver-timeout-verified', action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        profile = load_profile(args.profile)
        validate_amcl_transform_tolerance(
            profile, PACKAGE_ROOT / 'config' / 'amcl.yaml')
        artifact = validate_runtime_request(
            profile,
            stage=args.stage,
            map_file=args.map_file,
            active_map_id=args.active_map_id,
            allow_nonzero=args.allow_nonzero,
            driver_timeout_verified=args.driver_timeout_verified,
            mode=args.mode,
            cmd_vel_output_topic=args.cmd_vel_output_topic,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('V1_PROFILE_BLOCKED: {}'.format(exc), file=sys.stderr)
        return 1
    result = {
        'status': 'V1_PROFILE_STATIC_PASS',
        'stage': args.stage,
        'mode': args.mode,
        'allow_nonzero': args.allow_nonzero,
        'map_id': artifact.map_id if artifact else None,
        'map_file': str(artifact.yaml_path) if artifact else None,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
