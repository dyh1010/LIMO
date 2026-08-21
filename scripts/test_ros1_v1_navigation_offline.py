#!/usr/bin/env python3
"""Dependency-free frozen-core regression for ROS1 V1 navigation.

Post-freeze delivery/readiness/runbook contract tests are executed by
``run_v1_frozen_offline_regression.py`` as a separately counted suite.  This
legacy entry deliberately preserves the sealed 113-test core baseline.
"""

from pathlib import Path
import sys
import unittest


WORKSPACE_ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = WORKSPACE_ROOT / 'ros1_overlay_src' / 'limo_v1_navigation'
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

DELIVERY_AUDIT_TESTS = frozenset({
    'test_deployment_runbook_contract.py',
    'test_field_authorization_contract.py',
    'test_frozen_release_readiness.py',
})
EXPECTED_CORE_TESTS = 113


def main():
    test_root = PACKAGE_ROOT / 'test'
    all_tests = tuple(sorted(test_root.glob('test_*.py')))
    missing_delivery = sorted(
        name for name in DELIVERY_AUDIT_TESTS
        if not (test_root / name).is_file())
    if missing_delivery:
        print('ROS1_V1_NAVIGATION_OFFLINE_TEST_BLOCKED: missing delivery '
              'audit modules {}'.format(','.join(missing_delivery)))
        return 1
    core_tests = tuple(
        path for path in all_tests if path.name not in DELIVERY_AUDIT_TESTS)
    suite = unittest.TestSuite()
    for path in core_tests:
        suite.addTests(unittest.defaultTestLoader.discover(
            str(test_root), pattern=path.name, top_level_dir=str(test_root)))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    count = result.testsRun
    if not result.wasSuccessful() or count != EXPECTED_CORE_TESTS:
        print('ROS1_V1_NAVIGATION_OFFLINE_TEST_BLOCKED: {} tests'.format(count))
        return 1
    print('ROS1_V1_NAVIGATION_OFFLINE_TEST_PASS: {} tests'.format(count))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
