#!/usr/bin/env python3
"""Dependency-free, exact-denominator AprilTag docking offline regression."""

from pathlib import Path
import unittest


WORKSPACE = Path(__file__).resolve().parents[1]
TEST_ROOT = WORKSPACE / 'offline_tests' / 'v1_apriltag_docking'
EXPECTED = 24


def main():
    suite = unittest.defaultTestLoader.discover(
        str(TEST_ROOT), pattern='test_tag_docking_policy.py',
        top_level_dir=str(TEST_ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun != EXPECTED:
        print('V1_APRILTAG_DOCKING_OFFLINE_BLOCKED: denominator {} != {}'.format(
            result.testsRun, EXPECTED))
        return 2
    if not result.wasSuccessful():
        print('V1_APRILTAG_DOCKING_OFFLINE_BLOCKED: {} failures {} errors'.format(
            len(result.failures), len(result.errors)))
        return 1
    print('V1_APRILTAG_DOCKING_OFFLINE_PASS: {} tests'.format(EXPECTED))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
