from pathlib import Path
import math
import sys
import unittest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_v1_navigation.localization_policy import (  # noqa: E402
    BLOCKED,
    CONVERGING,
    READY,
    WAIT_INITIAL_POSE,
    ChainEvidence,
    ConvergenceConfig,
    InitialPoseEvidence,
    LocalizationConvergence,
    PoseEstimate,
    planar_yaw,
)


class LocalizationPolicyTest(unittest.TestCase):

    def setUp(self):
        self.config = ConvergenceConfig(
            chain_timeout_s=2.0,
            initial_pose_timeout_s=5.0,
            convergence_timeout_s=10.0,
            message_timeout_s=0.5,
            stable_window_s=2.0,
            stable_min_samples=5,
            min_nomotion_updates=3,
        )
        self.manager = LocalizationConvergence(0.0, self.config)

    def _chain(self, now, ok=True, reason='ok'):
        self.manager.update_chain(ChainEvidence(ok, reason, now), now)

    def _initial(self, now=0.1, **overrides):
        values = dict(
            received_monotonic=now,
            source_stamp=100.0 + now,
            ros_now=100.0 + now,
            frame_id='map',
            x=1.0,
            y=2.0,
            yaw=0.2,
            covariance_x=0.25,
            covariance_y=0.25,
            covariance_yaw=0.068,
            source='topic',
        )
        values.update(overrides)
        return InitialPoseEvidence(**values)

    def _estimate(self, now, **overrides):
        values = dict(
            received_monotonic=now,
            source_stamp=100.0 + now,
            ros_now=100.0 + now,
            frame_id='map',
            x=1.0,
            y=2.0,
            yaw=0.2,
            covariance_x=0.008,
            covariance_y=0.009,
            covariance_yaw=0.006,
        )
        values.update(overrides)
        return PoseEstimate(**values)

    def _prepare(self):
        self._chain(0.0)
        self.assertEqual(self.manager.state, WAIT_INITIAL_POSE)
        self.manager.accept_initial_pose(self._initial(), 0.1)
        self.assertEqual(self.manager.state, CONVERGING)

    def test_never_guesses_initial_pose_from_low_covariance(self):
        self._chain(0.0)
        accepted = self.manager.observe_estimate(self._estimate(0.1), 0.1)
        self.assertFalse(accepted)
        self.manager.tick(0.1)
        self.assertEqual(self.manager.state, WAIT_INITIAL_POSE)
        self.assertFalse(self.manager.ready)

    def test_invalid_or_stale_initial_pose_is_rejected(self):
        self._chain(0.0)
        cases = (
            self._initial(frame_id='odom'),
            self._initial(covariance_x=0.0),
            self._initial(covariance_y=5.0),
            self._initial(source_stamp=99.0, ros_now=100.1),
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                with self.assertRaises(ValueError):
                    self.manager.accept_initial_pose(evidence, 0.1)

    def test_ready_requires_nomotion_count_covariance_and_stable_window(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.2), 0.2)
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now in (0.7, 1.2, 1.7, 2.2):
            self.manager.observe_estimate(self._estimate(now), now)
            self.manager.tick(now)
        self.assertEqual(self.manager.state, READY)
        status = self.manager.status(2.2)
        self.assertAlmostEqual(status['estimate']['stddev_x_m'], 0.008 ** 0.5)

    def test_high_covariance_and_unstable_pose_do_not_become_ready(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.2), 0.2)
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now in (0.7, 1.2, 1.7, 2.2):
            self.manager.observe_estimate(self._estimate(
                now, x=1.0 + 0.1 * now), now)
            self.manager.tick(now)
        self.assertEqual(self.manager.state, CONVERGING)
        self.manager.observe_estimate(
            self._estimate(2.3, covariance_x=0.011), 2.3)
        self.assertEqual(self.manager.reason, 'covariance_above_ready_threshold')

    def test_chain_loss_latches_block_and_revokes_ready(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.2), 0.2)
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now in (0.7, 1.2, 1.7, 2.2):
            self.manager.observe_estimate(self._estimate(now), now)
            self.manager.tick(now)
        self.assertTrue(self.manager.ready)
        self._chain(2.3, False, 'scan_stale')
        self.assertEqual(self.manager.state, BLOCKED)
        self.assertFalse(self.manager.ready)
        self.assertIn('scan_stale', self.manager.reason)

    def test_chain_recovery_cannot_reuse_pre_fault_convergence_evidence(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.2), 0.2)
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now in (0.7, 1.2, 1.7):
            self.manager.observe_estimate(self._estimate(now), now)
        self.assertEqual(self.manager.nomotion_successes, 3)
        self.assertGreater(len(self.manager.estimates), 0)

        self._chain(1.8, False, 'scan_stale')
        self.assertEqual(self.manager.state, CONVERGING)
        self.assertEqual(self.manager.nomotion_successes, 0)
        self.assertEqual(len(self.manager.estimates), 0)
        self.assertFalse(self.manager.post_initial_pose_estimate_seen)

        self._chain(1.9, True)
        self.manager.tick(1.9)
        self.assertEqual(self.manager.state, CONVERGING)
        self.assertFalse(self.manager.ready)

    def test_nomotion_failure_and_timeouts_fail_closed(self):
        self._prepare()
        self.manager.record_nomotion_result(False, 'service unavailable')
        self.assertEqual(self.manager.state, CONVERGING)
        self.manager.record_nomotion_result(False, 'service unavailable')
        self.assertEqual(self.manager.state, BLOCKED)

        manager = LocalizationConvergence(0.0, self.config)
        manager.tick(2.0)
        self.assertEqual(manager.state, BLOCKED)
        self.assertIn('chain_validation_timeout', manager.reason)

    def test_new_explicit_pose_recovers_block_only_after_chain_returns(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.15), 0.15)
        self._chain(0.2, False, 'tf_missing')
        self.assertEqual(self.manager.state, CONVERGING)
        self.manager.tick(10.1)
        self.assertEqual(self.manager.state, BLOCKED)
        with self.assertRaises(ValueError):
            self.manager.accept_initial_pose(self._initial(0.3), 0.3)
        self._chain(0.4, True)
        self.manager.accept_initial_pose(self._initial(0.5), 0.5)
        self.assertEqual(self.manager.state, CONVERGING)

    def test_late_initialpose_gets_a_fresh_tf_convergence_grace(self):
        manager = LocalizationConvergence(0.0, self.config)
        manager.update_chain(ChainEvidence(True, 'ok', 60.0), 60.0)
        manager.accept_initial_pose(self._initial(60.1), 60.1)
        manager.update_chain(
            ChainEvidence(False, 'map_tf_missing', 60.2), 60.2)
        manager.tick(60.2)
        self.assertEqual(manager.state, CONVERGING)
        manager.tick(70.100001)
        self.assertEqual(manager.state, BLOCKED)

    def test_ready_jump_revokes_ready_and_requires_new_window(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.2), 0.2)
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now in (0.7, 1.2, 1.7, 2.2):
            self.manager.observe_estimate(self._estimate(now), now)
            self.manager.tick(now)
        self.assertTrue(self.manager.ready)
        self.manager.observe_estimate(self._estimate(2.3, x=1.2), 2.3)
        self.assertEqual(self.manager.state, CONVERGING)
        self.assertFalse(self.manager.ready)

    def test_normal_navigation_motion_does_not_look_like_pose_jump(self):
        self._prepare()
        self.manager.observe_estimate(self._estimate(0.2), 0.2)
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now in (0.7, 1.2, 1.7, 2.2):
            self.manager.observe_estimate(self._estimate(now), now)
            self.manager.tick(now)
        self.assertTrue(self.manager.ready)
        self.manager.set_navigation_active(True, 2.25)
        self.manager.observe_estimate(
            self._estimate(2.3, x=2.0), 2.3, navigation_active=True)
        self.manager.tick(2.3)
        self.assertTrue(self.manager.ready)
        self.assertFalse(self.manager.nomotion_due(3.5))
        self.manager.set_navigation_active(False, 3.6)
        self.assertEqual(self.manager.state, CONVERGING)
        self.assertFalse(self.manager.ready)
        self.assertTrue(self.manager.nomotion_due(3.6))

    def test_pose_epoch_requires_a_strictly_new_amcl_estimate(self):
        self._prepare()
        self.assertFalse(self.manager.observe_estimate(
            self._estimate(0.1), 0.1))
        self.assertFalse(self.manager.post_initial_pose_estimate_seen)
        self.assertEqual(len(self.manager.estimates), 0)

        equal_source = self._estimate(
            0.2, source_stamp=self.manager.initial_pose.source_stamp)
        self.assertFalse(self.manager.observe_estimate(equal_source, 0.2))
        self.assertFalse(self.manager.post_initial_pose_estimate_seen)
        self.assertEqual(len(self.manager.estimates), 0)

        self.assertTrue(self.manager.observe_estimate(
            self._estimate(0.2), 0.2))
        self.assertTrue(self.manager.post_initial_pose_estimate_seen)
        self.assertEqual(len(self.manager.estimates), 1)

    def test_yaw_stability_uses_pairwise_circular_diameter(self):
        self._prepare()
        samples = (
            (0.2, 0.00),
            (0.7, 0.04),
            (1.2, -0.04),
            (1.7, 0.04),
            (2.2, -0.04),
        )
        self.manager.observe_estimate(
            self._estimate(samples[0][0], yaw=samples[0][1]),
            samples[0][0])
        for _index in range(3):
            self.manager.record_nomotion_result(True)
        for now, yaw in samples[1:]:
            self.manager.observe_estimate(
                self._estimate(now, yaw=yaw), now)
            self.manager.tick(now)
        self.assertEqual(self.manager.state, CONVERGING)
        self.assertFalse(self.manager.ready)

        wrap_manager = LocalizationConvergence(0.0, self.config)
        wrap_manager.update_chain(ChainEvidence(True, 'ok', 0.0), 0.0)
        wrap_manager.accept_initial_pose(self._initial(), 0.1)
        wrap_samples = (
            (0.2, math.pi - 0.01),
            (0.7, -math.pi + 0.01),
            (1.2, math.pi - 0.005),
            (1.7, -math.pi + 0.005),
            (2.2, math.pi),
        )
        wrap_manager.observe_estimate(
            self._estimate(wrap_samples[0][0], yaw=wrap_samples[0][1]),
            wrap_samples[0][0])
        for _index in range(3):
            wrap_manager.record_nomotion_result(True)
        for now, yaw in wrap_samples[1:]:
            wrap_manager.observe_estimate(
                self._estimate(now, yaw=yaw), now)
            wrap_manager.tick(now)
        self.assertEqual(wrap_manager.state, READY)

    def test_nomotion_requests_can_trigger_first_new_amcl_but_success_waits(self):
        self._prepare()
        self.assertTrue(self.manager.nomotion_due(0.2))
        self.manager.mark_nomotion_requested(0.2)
        self.assertFalse(self.manager.record_nomotion_result(True))
        self.assertEqual(self.manager.nomotion_successes, 0)
        self.assertIn('ignored', self.manager.reason)

        equal_source = self._estimate(
            0.3, source_stamp=self.manager.initial_pose.source_stamp)
        self.assertFalse(self.manager.observe_estimate(equal_source, 0.3))
        self.assertFalse(self.manager.record_nomotion_result(True))
        self.assertEqual(self.manager.nomotion_successes, 0)

        self.assertTrue(self.manager.observe_estimate(
            self._estimate(0.4), 0.4))
        self.assertFalse(self.manager.nomotion_due(0.4))
        self.assertTrue(self.manager.nomotion_due(1.2))
        self.assertTrue(self.manager.record_nomotion_result(True))
        self.assertEqual(self.manager.nomotion_successes, 1)

        self.manager.accept_initial_pose(self._initial(1.3), 1.3)
        self.assertFalse(self.manager.post_initial_pose_estimate_seen)
        self.assertTrue(self.manager.nomotion_due(1.4))
        self.assertFalse(self.manager.record_nomotion_result(True))
        self.assertEqual(self.manager.nomotion_successes, 0)

    def test_planar_quaternion_validation_rejects_zero_nan_nonunit_and_tilt(self):
        self.assertAlmostEqual(
            planar_yaw(0.0, 0.0, 2.0 ** -0.5, 2.0 ** -0.5),
            1.57079632679)
        cases = (
            (0.0, 0.0, 0.0, 0.0),
            (float('nan'), 0.0, 0.0, 1.0),
            (0.0, 0.0, 0.2, 1.0),
            (0.2, 0.0, 0.0, (1.0 - 0.04) ** 0.5),
        )
        for quaternion in cases:
            with self.subTest(quaternion=quaternion):
                with self.assertRaises(ValueError):
                    planar_yaw(*quaternion)


if __name__ == '__main__':
    unittest.main()
