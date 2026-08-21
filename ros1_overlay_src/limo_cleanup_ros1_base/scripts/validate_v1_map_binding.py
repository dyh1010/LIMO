#!/usr/bin/env python3
"""Validate and print sealed V1 integrated map inputs; starts no ROS node."""

import argparse
import json
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.map_binding import validate_map_binding  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding-file', required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--binding-token', required=True)
    parser.add_argument('--map-root', required=True)
    arguments = parser.parse_args()
    try:
        result = validate_map_binding(
            arguments.binding_file,
            arguments.binding_sha256,
            arguments.binding_token,
            arguments.map_root,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print('V1_MAP_BINDING_BLOCKED: {}'.format(error), file=sys.stderr)
        return 1
    print(json.dumps({
        'status': 'V1_MAP_BINDING_PASS',
        'binding_sha256': result.binding_sha256,
        'active_map_id': result.active_map_id,
        'map_file': result.map_file,
        'map_image': result.map_image,
        'mode': 'integrated',
        'cmd_vel_output_topic': '/cleanup/base/cmd_vel_request',
    }, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
