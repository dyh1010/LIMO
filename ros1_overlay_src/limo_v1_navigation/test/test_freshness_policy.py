from pathlib import Path
import math
import sys
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.freshness_policy import (  # noqa: E402
    CommandValues,
    FaultLatch,
    FreshnessLimits,
    FreshnessSnapshot,
    ZERO_COMMAND,
    evaluate_safety,
    slew_limit,
)


class FreshnessPolicyTest(unittest.TestCase):

    def _snapshot(self, **overrides):
        values = dict(
            now=10.0,
            ros_now=100.0,
            last_scan=9.9,
            scan_source_stamp=99.9,
            last_odom=9.9,
            last_tf=9.9,
            tf_source_stamp=99.9,
            last_command=9.9,
            scan_hz=6.0,
            scan_frame_ok=True,
            odom_frames_ok=True,
            tf_owner_ok=True,
            forbidden_tf_owner_present=False,
        )
        values.update(overrides)
        return FreshnessSnapshot(**values)

    def test_fully_proven_command_passes(self):
        command = CommandValues(linear_x=0.1, angular_z=-0.2)
        decision = evaluate_safety(
            self._snapshot(), command,
            allow_nonzero=True,
            driver_timeout_verified=True,
            fault_latched=False)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.output, command)

    def test_every_missing_or_stale_signal_stops(self):
        cases = (
            {'last_scan': None},
            {'last_scan': 9.5},
            {'scan_source_stamp': None},
            {'scan_source_stamp': 99.5},
            {'scan_source_stamp': 100.100001},
            {'last_odom': None},
            {'last_odom': 9.5},
            {'last_tf': None},
            {'last_tf': 9.5},
            {'tf_source_stamp': None},
            {'tf_source_stamp': 99.5},
            {'tf_source_stamp': 100.100001},
            {'last_command': None},
            {'last_command': 9.75},
            {'scan_hz': None},
            {'scan_hz': 4.79},
            {'scan_hz': 7.21},
            {'scan_frame_ok': False},
            {'odom_frames_ok': False},
            {'tf_owner_ok': False},
            {'forbidden_tf_owner_present': True},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                decision = evaluate_safety(
                    self._snapshot(**overrides),
                    CommandValues(linear_x=0.1),
                    allow_nonzero=True,
                    driver_timeout_verified=True,
                    fault_latched=False)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.output, ZERO_COMMAND)

    def test_source_timestamp_boundaries_match_bridge_contract(self):
        passing_cases = (
            {'scan_source_stamp': 99.500001},
            {'scan_source_stamp': 100.1},
            {'tf_source_stamp': 99.500001},
            {'tf_source_stamp': 100.1},
        )
        for overrides in passing_cases:
            with self.subTest(expected='pass', overrides=overrides):
                decision = evaluate_safety(
                    self._snapshot(**overrides),
                    CommandValues(linear_x=0.1),
                    allow_nonzero=True,
                    driver_timeout_verified=True,
                    fault_latched=False)
                self.assertTrue(decision.allowed)

        failing_cases = (
            {'scan_source_stamp': 99.5},
            {'scan_source_stamp': 100.100001},
            {'tf_source_stamp': 99.5},
            {'tf_source_stamp': 100.100001},
        )
        for overrides in failing_cases:
            with self.subTest(expected='fail', overrides=overrides):
                decision = evaluate_safety(
                    self._snapshot(**overrides),
                    CommandValues(linear_x=0.1),
                    allow_nonzero=True,
                    driver_timeout_verified=True,
                    fault_latched=False)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.output, ZERO_COMMAND)

    def test_receive_timestamp_boundaries_match_bridge_contract(self):
        for overrides in (
                {'last_scan': 9.500001},
                {'last_tf': 9.500001}):
            with self.subTest(expected='pass', overrides=overrides):
                decision = evaluate_safety(
                    self._snapshot(**overrides),
                    CommandValues(linear_x=0.1),
                    allow_nonzero=True,
                    driver_timeout_verified=True,
                    fault_latched=False)
                self.assertTrue(decision.allowed)

        for overrides in (
                {'last_scan': 9.5},
                {'last_tf': 9.5}):
            with self.subTest(expected='fail', overrides=overrides):
                decision = evaluate_safety(
                    self._snapshot(**overrides),
                    CommandValues(linear_x=0.1),
                    allow_nonzero=True,
                    driver_timeout_verified=True,
                    fault_latched=False)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.output, ZERO_COMMAND)

    def test_authorization_timeout_proof_and_latch_are_independent(self):
        for kwargs in (
                {'allow_nonzero': False,
                 'driver_timeout_verified': True,
                 'fault_latched': False},
                {'allow_nonzero': True,
                 'driver_timeout_verified': False,
                 'fault_latched': False},
                {'allow_nonzero': True,
                 'driver_timeout_verified': True,
                 'fault_latched': True}):
            with self.subTest(kwargs=kwargs):
                decision = evaluate_safety(
                    self._snapshot(), CommandValues(linear_x=0.1),
                    **kwargs)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.output, ZERO_COMMAND)

    def test_invalid_or_excessive_commands_stop(self):
        commands = (
            CommandValues(linear_y=0.01),
            CommandValues(angular_x=0.01),
            CommandValues(linear_x=math.nan),
            CommandValues(angular_z=math.inf),
            CommandValues(linear_x=0.181),
            CommandValues(angular_z=0.451),
        )
        for command in commands:
            with self.subTest(command=command):
                decision = evaluate_safety(
                    self._snapshot(), command,
                    allow_nonzero=True,
                    driver_timeout_verified=True,
                    fault_latched=False)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.output, ZERO_COMMAND)

    def test_fault_latch_requires_explicit_healthy_zero_rearm(self):
        latch = FaultLatch()
        self.assertFalse(latch.rearm(False, True, True))
        self.assertFalse(latch.rearm(True, False, True))
        self.assertFalse(latch.rearm(True, True, False))
        self.assertTrue(latch.rearm(True, True, True))
        self.assertFalse(latch.latched)
        latch.trip('scan_stale')
        self.assertTrue(latch.latched)
        self.assertEqual(latch.reason, 'scan_stale')

    def test_acceleration_slew_is_conservative(self):
        output = slew_limit(
            ZERO_COMMAND,
            CommandValues(linear_x=0.18, angular_z=0.45),
            0.1, 0.35, 0.8)
        self.assertAlmostEqual(output.linear_x, 0.035)
        self.assertAlmostEqual(output.angular_z, 0.08)


if __name__ == '__main__':
    unittest.main()
