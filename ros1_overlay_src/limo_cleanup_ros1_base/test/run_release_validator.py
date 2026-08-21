#!/usr/bin/env python3
"""Offline entry point for the Linux secure V1 release validator."""

from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.map_binding import validate_release_files  # noqa: E402


def main():
    v1_root = PACKAGE_ROOT.parent / 'limo_v1_navigation'
    result = validate_release_files(v1_root)
    print('VALIDATE_RELEASE_FILES_PASS:{}'.format(len(result)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
