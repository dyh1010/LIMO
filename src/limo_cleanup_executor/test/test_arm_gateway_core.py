import ast
from dataclasses import replace
import math
import threading
import unittest
from pathlib import Path

from limo_cleanup_executor.arm_gateway_core import (
    ArmGatewayCore,
    ArmGatewayError,
    ArmGatewayPolicy,
    GatewayState,
    MOVE_J,
    MOVE_L,
    MotionRejected,
)


MODULE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_executor' / 'arm_gateway_core.py')


FAKE_BACKEND_CAPABILITIES = {
    'bounded_calls_enforced': True,
    'method_deadlines_s': {
        'is_controller_connected': 1.0,
        'is_power_on': 1.0,
        'is_moving': 1.0,
        'is_paused': 1.0,
        'get_error_information': 1.0,
        'get_fresh_mode': 1.0,
        'is_all_servo_enable': 1.0,
        'get_angles': 1.0,
        'get_coords': 1.0,
        'get_reference_frame': 1.0,
        'get_end_type': 1.0,
        'send_angles': 1.0,
        'send_coords': 1.0,
        'stop': 1.0,
        'close': 1.0,
    },
    'native_deadline_enforced': True,
    'independent_stop_channel': True,
    'independent_stop_lock_domain': True,
    'stop_not_queued_behind_commands': True,
    'native_cancel_enforced': True,
    'persistent_safety_latch_capability': False,
    'real_transport': False,
    'runtime_release_id': 'offline-release-v1',
    'release_manifest_sha256': 'a' * 64,
    'acceleration_profile_id': 'offline-profile-v1',
    'acceleration_profile_manifest_sha256': 'b' * 64,
    'acceleration_profile_runtime_release_id': 'offline-release-v1',
    'approved_speed_grades': (5, 10),
    'max_speed_grade': 10,
    'required_reference_frame': 0,
    'required_end_type': 0,
    'required_fresh_mode': 0,
}


BACKEND_OPERATION_METHODS = (
    'is_controller_connected',
    'is_power_on',
    'is_moving',
    'is_paused',
    'get_error_information',
    'get_fresh_mode',
    'is_all_servo_enable',
    'get_angles',
    'get_coords',
    'get_reference_frame',
    'get_end_type',
    'send_angles',
    'send_coords',
    'stop',
    'close',
)


def trap_backend_operations(backend):
    backend.operation_calls = []
    for method_name in BACKEND_OPERATION_METHODS:
        setattr(
            backend,
            method_name,
            lambda *unused_args, name=method_name: (
                backend.operation_calls.append(name)))


class ManualClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeArmBackend:
    SAFETY_CAPABILITIES = FAKE_BACKEND_CAPABILITIES

    def __init__(self):
        self.connected = 1
        self.power_on = 1
        self.moving = 0
        self.paused = 0
        self.error_code = 0
        self.fresh_mode = 0
        self.servo_enabled = 1
        self.angles = [0.0] * 6
        self.coords = [100.0, 0.0, 200.0, 0.0, 0.0, 0.0]
        self.reference_frame = 0
        self.end_type = 0
        self.sent_angles = []
        self.sent_coords = []
        self.stop_count = 0
        self.closed = False
        self.close_count = 0
        self.fail_joint_send = False
        self.fail_tcp_send = False
        self.fail_state_query = False
        self.fail_frame_query = False
        self.fail_stop = False
        self.fail_close = False

    def is_controller_connected(self):
        return self.connected

    def is_power_on(self):
        return self.power_on

    def is_moving(self):
        return self.moving

    def is_paused(self):
        return self.paused

    def get_error_information(self):
        return self.error_code

    def get_fresh_mode(self):
        return self.fresh_mode

    def is_all_servo_enable(self):
        return self.servo_enabled

    def get_angles(self):
        if self.fail_state_query:
            raise OSError('simulated state read failure')
        return list(self.angles)

    def get_coords(self):
        return list(self.coords)

    def get_reference_frame(self):
        if self.fail_frame_query:
            raise OSError('simulated frame read failure')
        return self.reference_frame

    def get_end_type(self):
        return self.end_type

    def send_angles(self, target, speed):
        if self.fail_joint_send:
            raise OSError('simulated serial write failure')
        self.sent_angles.append((list(target), speed))

    def send_coords(self, target, speed, mode):
        if self.fail_tcp_send:
            raise OSError('simulated serial write failure')
        self.sent_coords.append((list(target), speed, mode))

    def stop(self):
        self.stop_count += 1
        if self.fail_stop:
            raise OSError('simulated STOP write failure')

    def close(self):
        self.close_count += 1
        self.closed = True
        if self.fail_close:
            raise OSError('simulated transport close failure')


class BlockingSendBackend(FakeArmBackend):
    def __init__(self):
        super().__init__()
        self.send_entered = threading.Event()
        self.release_send = threading.Event()

    def send_angles(self, target, speed):
        self.send_entered.set()
        self.release_send.wait()
        super().send_angles(target, speed)


class IndependentStopBlockingSendBackend(BlockingSendBackend):
    """Fake transport whose STOP path is independent from a hung send."""

    def __init__(self):
        super().__init__()
        self.stop_entered = threading.Event()

    def stop(self):
        self.stop_entered.set()
        super().stop()


class BlockingStopBackend(FakeArmBackend):
    def __init__(self):
        super().__init__()
        self.stop_entered = threading.Event()
        self.release_stop = threading.Event()

    def stop(self):
        self.stop_count += 1
        self.stop_entered.set()
        self.release_stop.wait()


class FailingBlockingStopBackend(BlockingStopBackend):
    def stop(self):
        super().stop()
        raise OSError('simulated late STOP failure')


class BlockingFailureRecoveryStopBackend(FakeArmBackend):
    """Block the STOP attempted after an ordinary motion-send failure."""

    def __init__(self):
        super().__init__()
        self.stop_entered = threading.Event()
        self.release_stop = threading.Event()

    def stop(self):
        self.stop_count += 1
        self.stop_entered.set()
        self.release_stop.wait()


class BlockingQueryBackend(IndependentStopBlockingSendBackend):
    def __init__(self, fail_after_release=False):
        super().__init__()
        self.query_entered = threading.Event()
        self.release_query = threading.Event()
        self.fail_after_release = fail_after_release

    def get_angles(self):
        self.query_entered.set()
        self.release_query.wait()
        if self.fail_after_release:
            raise OSError('simulated late state query failure')
        return super().get_angles()


class OneBlockingSnapshotBackend(FakeArmBackend):
    """Capture one old angle sample and return it after a newer refresh."""

    def __init__(self):
        super().__init__()
        self.block_next_query = False
        self.query_entered = threading.Event()
        self.release_query = threading.Event()

    def get_angles(self):
        captured = list(self.angles)
        if self.block_next_query:
            self.block_next_query = False
            self.query_entered.set()
            self.release_query.wait()
        return captured


class BlockingClock:
    def __init__(self, value=100.0):
        self.value = value
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self):
        self.entered.set()
        self.release.wait()
        return self.value


class UnprovenStopBackend(FakeArmBackend):
    SAFETY_CAPABILITIES = dict(
        FAKE_BACKEND_CAPABILITIES,
        independent_stop_channel=False,
        independent_stop_lock_domain=False,
        stop_not_queued_behind_commands=False,
        native_cancel_enforced=False,
    )


class UnsafeRealTransportBackend(FakeArmBackend):
    SAFETY_CAPABILITIES = dict(
        FAKE_BACKEND_CAPABILITIES,
        bounded_calls_enforced=False,
        native_deadline_enforced=False,
        independent_stop_channel=False,
        independent_stop_lock_domain=False,
        stop_not_queued_behind_commands=False,
        native_cancel_enforced=False,
        real_transport=True,
    )


class CallbackSendBackend(FakeArmBackend):
    def __init__(self):
        super().__init__()
        self.before_send_return = None
        self.fail_after_callback = False

    def send_angles(self, target, speed):
        super().send_angles(target, speed)
        if self.before_send_return is not None:
            self.before_send_return()
        if self.fail_after_callback:
            raise OSError('simulated failure after callback')


class FakePersistentLatch:
    def __init__(self, active=False, fail_read=False, fail_write=False):
        self._active = active
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.reasons = []

    @property
    def active(self):
        if self.fail_read:
            raise OSError('simulated persistent latch read failure')
        return self._active

    def latch(self, reason):
        if self.fail_write:
            raise OSError('simulated persistent latch write failure')
        self.reasons.append(reason)
        self._active = True


def make_policy(permit_motion=False):
    return ArmGatewayPolicy(
        permit_motion=permit_motion,
        max_speed_grade=10,
        approved_speed_grades=(5, 10),
        state_max_age_s=0.25,
        command_timeout_s=2.0,
        stop_timeout_s=1.0,
        stable_samples_required=2,
        stationary_dwell_s=0.10,
        stationary_joint_tolerance_deg=0.01,
        joint_tolerance_deg=0.5,
        tcp_translation_tolerance_mm=1.0,
        tcp_rotation_tolerance_deg=1.0,
        joint_limits_deg=((-160.0, 160.0),) * 6,
        tcp_bounds=(
            (-250.0, 250.0),
            (-250.0, 250.0),
            (0.0, 400.0),
            (-180.0, 180.0),
            (-180.0, 180.0),
            (-180.0, 180.0),
        ),
        named_joint_poses={
            'inspection': (10.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        },
        acceleration_profile_id='offline-profile-v1',
        runtime_release_id='offline-release-v1',
        release_manifest_sha256='a' * 64,
        acceleration_profile_manifest_sha256='b' * 64,
        acceleration_profile_runtime_release_id='offline-release-v1',
        allowed_tcp_modes=(MOVE_J,),
        required_fresh_mode=0,
        max_stop_attempts=3,
        stop_retry_interval_s=0.25,
        stop_retry_backoff_factor=2.0,
    )


def allow_test_authorization(value, purpose, session_id):
    return (
        bool((value or '').strip())
        and purpose in ('motion', 'ack')
        and bool((session_id or '').strip())
    )


def ready_core(
        permit_motion=True,
        authorization_validator=allow_test_authorization,
        command_id_factory=None):
    backend = FakeArmBackend()
    clock = ManualClock()
    core = ArmGatewayCore(
        backend,
        make_policy(permit_motion),
        clock=clock,
        stop_clock=clock,
        authorization_validator=authorization_validator,
        command_id_factory=command_id_factory,
    )
    core.refresh()
    if core.state != GatewayState.READY:
        raise AssertionError('test fixture did not become READY')
    return core, backend, clock


class ArmGatewayCoreTest(unittest.TestCase):
    @staticmethod
    def _capture_call(callback, *args):
        try:
            return 'returned', callback(*args)
        except Exception as exc:
            return 'error', exc

    def test_module_uses_python38_syntax(self):
        ast.parse(
            MODULE.read_text(encoding='utf-8'),
            filename=str(MODULE),
            feature_version=(3, 8),
        )

    def test_motion_is_disabled_by_default_policy(self):
        core, backend, _ = ready_core(permit_motion=False)
        with self.assertRaisesRegex(
                MotionRejected, 'disabled by static policy'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])

    def test_backend_capability_gate_blocks_unproven_real_transport(self):
        with self.assertRaisesRegex(
                ValueError, 'DISABLED/BLOCKED'):
            ArmGatewayCore(
                UnsafeRealTransportBackend(),
                replace(
                    make_policy(True), expected_real_transport=True),
                clock=ManualClock(),
                authorization_validator=allow_test_authorization,
            )

    def test_real_backend_capability_binding_must_exactly_match_policy(self):
        mismatches = {
            'runtime_release_id': 'stale-release',
            'release_manifest_sha256': 'c' * 64,
            'acceleration_profile_id': 'stale-profile',
            'acceleration_profile_manifest_sha256': 'c' * 64,
            'acceleration_profile_runtime_release_id': 'stale-release',
            'approved_speed_grades': (5,),
            'max_speed_grade': 9,
            'required_reference_frame': 1,
            'required_end_type': 1,
            'required_fresh_mode': 1,
        }
        for name, value in mismatches.items():
            with self.subTest(name=name):
                capabilities = dict(FAKE_BACKEND_CAPABILITIES)
                capabilities.update({
                    'persistent_safety_latch_capability': True,
                    'real_transport': True,
                })
                capabilities[name] = value
                backend_type = type(
                    'ClaimedRealBackend',
                    (FakeArmBackend,),
                    {'SAFETY_CAPABILITIES': capabilities},
                )
                backend = backend_type()
                trap_backend_operations(backend)
                with self.assertRaisesRegex(
                        ValueError, 'does not match.*policy binding'):
                    ArmGatewayCore(
                        backend,
                        replace(
                            make_policy(True), expected_real_transport=True),
                        clock=ManualClock(),
                        authorization_validator=allow_test_authorization,
                    )
                self.assertEqual(backend.operation_calls, [])

    def test_exactly_bound_real_backend_metadata_remains_blocked_without_attestation(self):
        class ClaimedRealBackend(FakeArmBackend):
            SAFETY_CAPABILITIES = dict(
                FAKE_BACKEND_CAPABILITIES,
                persistent_safety_latch_capability=True,
                real_transport=True,
            )

        backend = ClaimedRealBackend()
        trap_backend_operations(backend)
        with self.assertRaisesRegex(
                ValueError, 'do not independently verify'):
            ArmGatewayCore(
                backend,
                replace(make_policy(True), expected_real_transport=True),
                clock=ManualClock(),
                authorization_validator=allow_test_authorization,
            )
        self.assertEqual(backend.operation_calls, [])

    def test_real_backend_requires_deadline_and_persistent_latch_attestation(self):
        cases = (
            ('native_deadline_enforced', False),
            ('independent_stop_lock_domain', False),
            ('stop_not_queued_behind_commands', False),
            ('persistent_safety_latch_capability', False),
        )
        for name, value in cases:
            with self.subTest(name=name):
                capabilities = dict(
                    FAKE_BACKEND_CAPABILITIES,
                    persistent_safety_latch_capability=True,
                    real_transport=True,
                )
                capabilities[name] = value
                backend_type = type(
                    'ClaimedRealBackend',
                    (FakeArmBackend,),
                    {'SAFETY_CAPABILITIES': capabilities},
                )
                backend = backend_type()
                trap_backend_operations(backend)
                with self.assertRaisesRegex(ValueError, 'DISABLED/BLOCKED'):
                    ArmGatewayCore(
                        backend,
                        replace(
                            make_policy(True), expected_real_transport=True),
                        clock=ManualClock(),
                        authorization_validator=allow_test_authorization,
                    )
                self.assertEqual(backend.operation_calls, [])

    def test_transport_classification_must_match_trusted_policy(self):
        cases = (
            (True, False),
            (False, True),
        )
        for expected_real, reported_real in cases:
            with self.subTest(
                    expected_real=expected_real,
                    reported_real=reported_real):
                capabilities = dict(
                    FAKE_BACKEND_CAPABILITIES,
                    persistent_safety_latch_capability=reported_real,
                    real_transport=reported_real,
                )
                backend_type = type(
                    'CapabilityBackend',
                    (FakeArmBackend,),
                    {'SAFETY_CAPABILITIES': capabilities},
                )
                backend = backend_type()
                trap_backend_operations(backend)
                with self.assertRaisesRegex(
                        ValueError, 'real_transport.*policy binding'):
                    ArmGatewayCore(
                        backend,
                        replace(
                            make_policy(True),
                            expected_real_transport=expected_real),
                        clock=ManualClock(),
                        authorization_validator=allow_test_authorization,
                    )
                self.assertEqual(backend.operation_calls, [])

    def test_dry_run_backend_metadata_matches_released_default_binding(self):
        from limo_cleanup_executor.arm_backends import DryRunArmBackend

        policy = replace(
            make_policy(True),
            approved_speed_grades=(10,),
            acceleration_profile_id='DRY_RUN_ONLY',
            runtime_release_id='DRY_RUN_RELEASE_V1',
            release_manifest_sha256=(
                '0db63372cc24980532f650205fbb3537d02609ac62d52d76704e6dc7eaff9f83'),
            acceleration_profile_manifest_sha256=(
                'cfd2f55631a9406ac5191bb09c38c3f3f678b8788ace2920d4966b3b3d56260e'),
            acceleration_profile_runtime_release_id='DRY_RUN_RELEASE_V1',
        )
        core = ArmGatewayCore(
            DryRunArmBackend(),
            policy,
            clock=ManualClock(),
            authorization_validator=allow_test_authorization,
        )
        self.assertEqual(core.state, GatewayState.INITIALIZING)
        self.assertFalse(core._backend_capabilities['real_transport'])

    def test_backend_capability_schema_rejects_missing_extra_and_subclasses(self):
        class ActiveString(str):
            pass

        class ActiveInt(int):
            pass

        class ActiveTuple(tuple):
            pass

        class ActiveDict(dict):
            pass

        cases = []
        missing = dict(FAKE_BACKEND_CAPABILITIES)
        missing.pop('runtime_release_id')
        cases.append(('missing', missing, 'keys do not match'))
        extra = dict(FAKE_BACKEND_CAPABILITIES)
        extra['unexpected'] = True
        cases.append(('extra', extra, 'keys do not match'))
        active_key = dict(FAKE_BACKEND_CAPABILITIES)
        active_key[ActiveString('unexpected')] = active_key.pop(
            'runtime_release_id')
        cases.append(('active-key', active_key, 'exact strings'))
        active_mapping = ActiveDict(FAKE_BACKEND_CAPABILITIES)
        cases.append((
            'active-mapping', active_mapping,
            'static SAFETY_CAPABILITIES are required'))
        active_string = dict(FAKE_BACKEND_CAPABILITIES)
        active_string['runtime_release_id'] = ActiveString(
            'offline-release-v1')
        cases.append(('active-string', active_string, 'exact non-empty string'))
        active_hash = dict(FAKE_BACKEND_CAPABILITIES)
        active_hash['release_manifest_sha256'] = ActiveString('a' * 64)
        cases.append(('active-hash', active_hash, 'exact lowercase SHA-256'))
        active_int = dict(FAKE_BACKEND_CAPABILITIES)
        active_int['max_speed_grade'] = ActiveInt(10)
        cases.append(('active-int', active_int, 'exact integer'))
        active_tuple = dict(FAKE_BACKEND_CAPABILITIES)
        active_tuple['approved_speed_grades'] = ActiveTuple((5, 10))
        cases.append(('active-tuple', active_tuple, 'exact non-empty tuple'))
        active_bool = dict(FAKE_BACKEND_CAPABILITIES)
        active_bool['native_deadline_enforced'] = 1
        cases.append(('active-deadline-bool', active_bool, 'must be a boolean'))
        active_latch_bool = dict(FAKE_BACKEND_CAPABILITIES)
        active_latch_bool['persistent_safety_latch_capability'] = 1
        cases.append(('active-latch-bool', active_latch_bool, 'must be a boolean'))
        missing_deadline = dict(FAKE_BACKEND_CAPABILITIES)
        missing_deadline['method_deadlines_s'] = dict(
            FAKE_BACKEND_CAPABILITIES['method_deadlines_s'])
        missing_deadline['method_deadlines_s'].pop('stop')
        cases.append((
            'missing-stop-deadline', missing_deadline,
            'method deadlines must be an exact dictionary'))
        active_deadlines = dict(FAKE_BACKEND_CAPABILITIES)
        active_deadlines['method_deadlines_s'] = ActiveDict(
            FAKE_BACKEND_CAPABILITIES['method_deadlines_s'])
        cases.append((
            'active-deadlines', active_deadlines,
            'method deadlines must be an exact dictionary'))
        nonpositive_deadline = dict(FAKE_BACKEND_CAPABILITIES)
        nonpositive_deadline['method_deadlines_s'] = dict(
            FAKE_BACKEND_CAPABILITIES['method_deadlines_s'])
        nonpositive_deadline['method_deadlines_s']['stop'] = 0.0
        cases.append((
            'nonpositive-stop-deadline', nonpositive_deadline,
            'must be a positive finite built-in number'))
        duplicate_hash = dict(FAKE_BACKEND_CAPABILITIES)
        duplicate_hash['acceleration_profile_manifest_sha256'] = (
            duplicate_hash['release_manifest_sha256'])
        cases.append((
            'duplicate-manifest-hash', duplicate_hash,
            'SHA-256 bindings must be different'))

        for label, capabilities, message in cases:
            with self.subTest(label=label):
                backend_type = type(
                    'CapabilityBackend',
                    (FakeArmBackend,),
                    {'SAFETY_CAPABILITIES': capabilities},
                )
                backend = backend_type()
                trap_backend_operations(backend)
                with self.assertRaisesRegex(ValueError, message):
                    ArmGatewayCore(
                        backend,
                        make_policy(True),
                        clock=ManualClock(),
                        authorization_validator=allow_test_authorization,
                    )
                self.assertEqual(backend.operation_calls, [])

    def test_capability_method_and_instance_attribute_are_never_invoked(self):
        calls = []

        class MethodOnlyBackend(FakeArmBackend):
            SAFETY_CAPABILITIES = None

            def safety_capabilities(self):
                calls.append('method')
                self.close()
                return dict(FAKE_BACKEND_CAPABILITIES)

        backend = MethodOnlyBackend()
        backend.SAFETY_CAPABILITIES = dict(FAKE_BACKEND_CAPABILITIES)
        with self.assertRaisesRegex(
                ValueError, 'static SAFETY_CAPABILITIES are required'):
            ArmGatewayCore(
                backend,
                make_policy(True),
                clock=ManualClock(),
                authorization_validator=allow_test_authorization,
            )
        self.assertEqual(calls, [])
        self.assertEqual(backend.close_count, 0)

    def test_core_freezes_static_capability_evidence_after_construction(self):
        capabilities = dict(FAKE_BACKEND_CAPABILITIES)
        capabilities['method_deadlines_s'] = dict(
            FAKE_BACKEND_CAPABILITIES['method_deadlines_s'])
        backend_type = type(
            'MutableCapabilityBackend',
            (FakeArmBackend,),
            {'SAFETY_CAPABILITIES': capabilities},
        )
        core = ArmGatewayCore(
            backend_type(),
            make_policy(True),
            clock=ManualClock(),
            authorization_validator=allow_test_authorization,
        )
        capabilities['native_deadline_enforced'] = False
        capabilities['method_deadlines_s']['stop'] = 0.0
        self.assertTrue(
            core._backend_capabilities['native_deadline_enforced'])
        self.assertEqual(
            core._backend_capabilities['method_deadlines_s']['stop'], 1.0)
        with self.assertRaises(TypeError):
            core._backend_capabilities['native_deadline_enforced'] = False
        with self.assertRaises(TypeError):
            core._backend_capabilities['method_deadlines_s']['stop'] = 0.0

    def test_core_snapshots_named_poses_against_post_construction_mutation(self):
        mutable_target = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        policy = replace(
            make_policy(True),
            named_joint_poses={'inspection': mutable_target},
        )
        core = ArmGatewayCore(
            FakeArmBackend(),
            policy,
            clock=ManualClock(),
            authorization_validator=allow_test_authorization,
        )
        mutable_target[0] = 200.0
        policy.named_joint_poses['inspection'] = (200.0,) * 6
        policy.named_joint_poses['injected'] = (0.0,) * 6
        object.__setattr__(policy, 'max_speed_grade', 100)
        self.assertEqual(
            core._policy.named_joint_poses['inspection'],
            (10.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        )
        self.assertNotIn('injected', core._policy.named_joint_poses)
        self.assertEqual(core._policy.max_speed_grade, 10)
        with self.assertRaises(TypeError):
            core._policy.named_joint_poses['injected'] = (0.0,) * 6

    def test_unproven_stop_channel_is_blocked_before_public_use(self):
        backend = UnprovenStopBackend()
        trap_backend_operations(backend)
        clock = ManualClock()
        with self.assertRaisesRegex(
                ValueError, 'DISABLED/BLOCKED'):
            ArmGatewayCore(
                backend,
                make_policy(True),
                clock=clock,
                stop_clock=clock,
                authorization_validator=allow_test_authorization,
            )
        self.assertEqual(backend.operation_calls, [])

    def test_inflight_stop_reservation_blocks_motion_and_duplicate_stop(self):
        backend = BlockingStopBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        outcomes = []

        stop = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.request_stop, 'blocking STOP', core.session_id)))
        stop.start()
        self.assertTrue(backend.stop_entered.wait(timeout=1.0))

        with self.assertRaisesRegex(MotionRejected, 'STOP send'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-during-stop', core.session_id)
        self.assertFalse(core.request_stop(
            'duplicate STOP', core.session_id))
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.stop_count, 1)

        backend.release_stop.set()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertEqual(outcomes, [('returned', True)])
        self.assertEqual(core.state, GatewayState.STOPPING)

    def test_send_failure_recovery_stop_reserves_epoch_and_blocks_new_motion(self):
        backend = BlockingFailureRecoveryStopBackend()
        backend.fail_joint_send = True
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        outcomes = []

        failed_send = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.command_named_joint_pose,
                'inspection', 5, 'auth-failed-send', core.session_id)))
        failed_send.start()
        self.assertTrue(backend.stop_entered.wait(timeout=1.0))

        backend.fail_joint_send = False
        with self.assertRaisesRegex(MotionRejected, 'STOP send'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-during-recovery-stop', core.session_id)
        self.assertEqual(backend.sent_angles, [])

        backend.release_stop.set()
        failed_send.join(timeout=1.0)
        self.assertFalse(failed_send.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][0], 'error')
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertIsNone(core.active_command)

    def test_close_supersedes_blocked_stop_and_late_stop_cannot_commit(self):
        backend = BlockingStopBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        outcomes = []

        stop = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.request_stop, 'blocking STOP', core.session_id)))
        stop.start()
        self.assertTrue(backend.stop_entered.wait(timeout=1.0))

        with self.assertRaisesRegex(
                ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
            core.close()
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertTrue(core.physical_stop_required)

        backend.release_stop.set()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][0], 'error')
        self.assertIn('superseded', str(outcomes[0][1]))
        self.assertEqual(core.state, GatewayState.CLOSED)

    def test_blocked_stop_never_overlaps_boundary_stop_or_backend_close(self):
        class OverlapTrackingStopBackend(FakeArmBackend):
            def __init__(self):
                super().__init__()
                self.stop_entered = threading.Event()
                self.release_stop = threading.Event()
                self.stop_active = False
                self.close_overlap = []

            def stop(self):
                self.stop_count += 1
                self.stop_active = True
                self.stop_entered.set()
                self.release_stop.wait()
                self.stop_active = False

            def close(self):
                self.close_overlap.append(self.stop_active)
                super().close()

        backend = OverlapTrackingStopBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        stop_outcome = []
        stop = threading.Thread(target=lambda: stop_outcome.append(
            self._capture_call(
                core.request_stop, 'blocking STOP', core.session_id)))
        stop.start()
        self.assertTrue(backend.stop_entered.wait(timeout=1.0))

        boundary_outcome = []
        boundary = threading.Thread(target=lambda: boundary_outcome.append(
            self._capture_call(
                core.fail_closed_action_boundary,
                'action deadline ended')))
        boundary.start()
        boundary.join(timeout=0.2)
        boundary_was_blocked = boundary.is_alive()
        try:
            with self.assertRaisesRegex(
                    ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
                core.close()
            self.assertEqual(backend.close_count, 0)
            self.assertEqual(backend.close_overlap, [])
        finally:
            backend.release_stop.set()
            stop.join(timeout=1.0)
            boundary.join(timeout=1.0)

        self.assertFalse(boundary_was_blocked)
        self.assertFalse(stop.is_alive())
        self.assertFalse(boundary.is_alive())
        self.assertEqual(boundary_outcome, [('returned', True)])
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 1)
        self.assertEqual(backend.close_overlap, [False])
        self.assertEqual(len(stop_outcome), 1)
        self.assertEqual(stop_outcome[0][0], 'error')
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertTrue(core.physical_stop_required)

    def test_close_supersedes_blocked_stop_failure_without_state_revival(self):
        backend = FailingBlockingStopBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        outcomes = []

        stop = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.request_stop, 'blocking STOP', core.session_id)))
        stop.start()
        self.assertTrue(backend.stop_entered.wait(timeout=1.0))

        with self.assertRaisesRegex(
                ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
            core.close()
        close_epoch = core._state_epoch
        backend.release_stop.set()
        stop.join(timeout=1.0)

        self.assertFalse(stop.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][0], 'error')
        self.assertIn('superseded', str(outcomes[0][1]))
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertTrue(core.physical_stop_required)
        self.assertGreaterEqual(core._state_epoch, close_epoch)

    def test_session_validator_and_purpose_are_fail_closed(self):
        core, backend, _ = ready_core(authorization_validator=None)
        with self.assertRaisesRegex(MotionRejected, 'validator'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])

        def integer_validator(unused_value, unused_purpose, unused_session):
            return 1

        core, backend, _ = ready_core(
            authorization_validator=integer_validator)
        with self.assertRaisesRegex(MotionRejected, 'motion purpose'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])

        calls = []

        def validator(value, purpose, session_id):
            calls.append((value, purpose, session_id))
            return purpose == 'ack'

        core, backend, _ = ready_core(authorization_validator=validator)
        with self.assertRaisesRegex(MotionRejected, 'motion purpose'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(
            calls, [('auth-1', 'motion', core.session_id)])
        self.assertEqual(backend.sent_angles, [])

        def exploding_validator(unused_value, unused_purpose, unused_session):
            raise RuntimeError('validator unavailable')

        core, backend, _ = ready_core(
            authorization_validator=exploding_validator)
        with self.assertRaisesRegex(
                MotionRejected, 'authorization validation failed'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])

    def test_motion_stop_and_ack_require_current_core_session(self):
        core, backend, _ = ready_core()
        with self.assertRaisesRegex(TypeError, 'expected_session_id'):
            core.command_named_joint_pose('inspection', 5, 'auth-1')
        with self.assertRaisesRegex(TypeError, 'expected_session_id'):
            core.request_stop('operator STOP')
        core._latch_fault('local fault')
        with self.assertRaisesRegex(TypeError, 'expected_session_id'):
            core.acknowledge_local_fault('ack-auth-1')
        fault_before_stale_ack = core.fault_reason
        with self.assertRaisesRegex(MotionRejected, 'session'):
            core.acknowledge_local_fault(
                'ack-auth-stale', 'stale-session')
        self.assertEqual(core._used_authorization_ids, set())
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(core.fault_reason, fault_before_stale_ack)
        with self.assertRaisesRegex(MotionRejected, 'session'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', 'stale-session')
        with self.assertRaisesRegex(MotionRejected, 'session'):
            core.request_stop('operator STOP', 'stale-session')
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.stop_count, 0)

    def test_authorization_and_command_id_consumed_before_backend_call(self):
        ids = iter(('accepted-before-error', 'accepted-before-error'))
        core, backend, clock = ready_core(
            command_id_factory=lambda: next(ids))
        backend.fail_joint_send = True
        with self.assertRaisesRegex(ArmGatewayError, 'send failed'):
            core.command_named_joint_pose(
                'inspection', 5, 'motion-auth-1', core.session_id)
        self.assertIn('motion-auth-1', core._used_authorization_ids)
        self.assertIn('accepted-before-error', core._issued_command_ids)

        backend.fail_joint_send = False
        backend.moving = 0
        core.refresh()
        clock.advance(0.01)
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        self.assertTrue(core.acknowledge_local_fault(
            'ack-auth-1', core.session_id))
        with self.assertRaisesRegex(MotionRejected, 'consumed'):
            core.command_named_joint_pose(
                'inspection', 5, 'motion-auth-1', core.session_id)
        with self.assertRaisesRegex(ArmGatewayError, 'already been issued'):
            core.command_named_joint_pose(
                'inspection', 5, 'motion-auth-2', core.session_id)
        self.assertNotIn('motion-auth-2', core._used_authorization_ids)
        self.assertEqual(len(backend.sent_angles), 0)

    def test_concurrent_same_authorization_sends_exactly_once(self):
        core, backend, _ = ready_core()
        start_barrier = threading.Barrier(3)
        outcomes = []

        def command_worker():
            start_barrier.wait()
            try:
                command = core.command_named_joint_pose(
                    'inspection', 5, 'shared-auth', core.session_id)
                outcomes.append(('sent', command.command_id))
            except MotionRejected as exc:
                outcomes.append(('rejected', str(exc)))

        first = threading.Thread(target=command_worker)
        second = threading.Thread(target=command_worker)
        first.start()
        second.start()
        start_barrier.wait()
        first.join()
        second.join()

        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual([item[0] for item in outcomes].count('sent'), 1)
        self.assertEqual([item[0] for item in outcomes].count('rejected'), 1)
        rejection = next(item[1] for item in outcomes
                         if item[0] == 'rejected')
        self.assertIn('not READY', rejection)
        self.assertEqual(core._used_authorization_ids, {'shared-auth'})
        self.assertEqual(len(core._issued_command_ids), 1)

    def test_concurrent_duplicate_command_id_is_atomically_rejected(self):
        barrier = threading.Barrier(2)
        factory_calls = []

        def duplicate_id_factory():
            factory_calls.append(threading.current_thread().name)
            if len(factory_calls) <= 2:
                barrier.wait()
            return 'duplicate-command-id'

        core, backend, _ = ready_core(
            command_id_factory=duplicate_id_factory)
        outcomes = []

        def command_worker(authorization_id):
            try:
                command = core.command_named_joint_pose(
                    'inspection', 5, authorization_id, core.session_id)
                outcomes.append(('sent', command.command_id))
            except Exception as exc:
                outcomes.append(('error', exc))

        first = threading.Thread(
            target=command_worker, args=('auth-first',))
        second = threading.Thread(
            target=command_worker, args=('auth-second',))
        first.start()
        second.start()
        first.join(timeout=1.0)
        second.join(timeout=1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual([kind for kind, value in outcomes].count('sent'), 1)
        errors = [value for kind, value in outcomes if kind == 'error']
        self.assertEqual(len(errors), 1)
        self.assertTrue(
            'superseded' in str(errors[0])
            or 'not READY' in str(errors[0]))
        self.assertEqual(
            core._issued_command_ids, {'duplicate-command-id'})
        self.assertEqual(len(core._used_authorization_ids), 1)

    def test_slow_motion_validator_cannot_reuse_an_expired_snapshot(self):
        validator_clock = {}

        def slow_validator(value, purpose, session_id):
            validator_clock['clock'].advance(0.30)
            return allow_test_authorization(value, purpose, session_id)

        core, backend, clock = ready_core(
            authorization_validator=slow_validator)
        validator_clock['clock'] = clock

        with self.assertRaisesRegex(
                MotionRejected, 'fresh motion-ready state'):
            core.command_named_joint_pose(
                'inspection', 5, 'slow-validator-auth', core.session_id)

        self.assertEqual(backend.sent_angles, [])
        self.assertNotIn(
            'slow-validator-auth', core._used_authorization_ids)
        self.assertEqual(core._issued_command_ids, set())

    def test_slow_command_id_factory_cannot_reuse_an_expired_snapshot(self):
        factory_clock = {}

        def slow_command_id_factory():
            factory_clock['clock'].advance(0.30)
            return 'slow-factory-command'

        core, backend, clock = ready_core(
            command_id_factory=slow_command_id_factory)
        factory_clock['clock'] = clock

        with self.assertRaisesRegex(
                MotionRejected, 'fresh motion-ready state'):
            core.command_named_joint_pose(
                'inspection', 5, 'slow-factory-auth', core.session_id)

        self.assertEqual(backend.sent_angles, [])
        self.assertNotIn('slow-factory-auth', core._used_authorization_ids)
        self.assertNotIn(
            'slow-factory-command', core._issued_command_ids)

    def test_stop_does_not_wait_for_blocked_validator_and_supersedes_motion(self):
        validator_entered = threading.Event()
        release_validator = threading.Event()

        def validator(value, purpose, session_id):
            validator_entered.set()
            release_validator.wait()
            return allow_test_authorization(value, purpose, session_id)

        core, backend, _ = ready_core(authorization_validator=validator)
        motion_outcome = []
        stop_outcome = []
        stop_started = threading.Event()
        stop_returned = threading.Event()

        def motion_worker():
            try:
                motion_outcome.append(('sent', core.command_named_joint_pose(
                    'inspection', 5, 'auth-1', core.session_id)))
            except Exception as exc:
                motion_outcome.append(('error', exc))

        def stop_worker():
            stop_started.set()
            try:
                stop_outcome.append(('returned', core.request_stop(
                    'concurrent STOP', core.session_id)))
            except Exception as exc:
                stop_outcome.append(('error', exc))
            finally:
                stop_returned.set()

        motion = threading.Thread(target=motion_worker)
        motion.start()
        validator_entered.wait()
        stop = threading.Thread(target=stop_worker)
        stop.start()
        stop_started.wait()
        self.assertTrue(stop_returned.wait(timeout=1.0))
        stop_was_blocked = not stop_returned.is_set()
        release_validator.set()
        motion.join()
        stop.join()

        self.assertFalse(stop_was_blocked)
        self.assertEqual(motion_outcome[0][0], 'error')
        self.assertIn('superseded', str(motion_outcome[0][1]))
        self.assertEqual(stop_outcome, [('returned', True)])
        self.assertEqual(len(backend.sent_angles), 0)
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertIsNone(core.active_command)

    def test_same_thread_validator_stop_is_rejected_without_backend_send(self):
        reentry_errors = []
        core_holder = {}

        def validator(value, purpose, session_id):
            try:
                core_holder['core'].request_stop('validator STOP', session_id)
            except Exception as exc:
                reentry_errors.append(exc)
            return allow_test_authorization(value, purpose, session_id)

        core, backend, _ = ready_core(authorization_validator=validator)
        core_holder['core'] = core

        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(len(reentry_errors), 1)
        self.assertIsInstance(reentry_errors[0], ArmGatewayError)
        self.assertIn('reentrant gateway request_stop', str(reentry_errors[0]))
        self.assertEqual(backend.stop_count, 0)
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(core.state, GatewayState.EXECUTING)
        self.assertEqual(core.active_command, command)

    def test_close_does_not_wait_for_backend_send_and_late_result_is_rejected(self):
        backend = BlockingSendBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        motion_outcome = []
        close_outcome = []
        close_started = threading.Event()
        close_returned = threading.Event()

        def motion_worker():
            try:
                motion_outcome.append(('sent', core.command_named_joint_pose(
                    'inspection', 5, 'auth-1', core.session_id)))
            except Exception as exc:
                motion_outcome.append(('error', exc))

        def close_worker():
            close_started.set()
            try:
                core.close()
            except ArmGatewayError as exc:
                close_outcome.append(str(exc))
            finally:
                close_returned.set()

        motion = threading.Thread(target=motion_worker)
        motion.start()
        backend.send_entered.wait()
        closer = threading.Thread(target=close_worker)
        closer.start()
        close_started.wait()
        close_was_blocked = not close_returned.is_set()
        backend.release_send.set()
        motion.join()
        closer.join()

        self.assertFalse(close_was_blocked)
        self.assertEqual(motion_outcome[0][0], 'error')
        self.assertIsInstance(motion_outcome[0][1], ArmGatewayError)
        self.assertIn('activation is refused', str(motion_outcome[0][1]))
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(len(close_outcome), 1)
        self.assertIn('stationary state is unverified', close_outcome[0])
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertIsNone(core.active_command)
        with self.assertRaisesRegex(ArmGatewayError, 'gateway is closed'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-2', core.session_id)

    def test_stop_does_not_wait_for_blocked_send_and_late_send_cannot_commit(self):
        backend = IndependentStopBlockingSendBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        motion_outcome = []

        def motion_worker():
            try:
                motion_outcome.append(('sent', core.command_named_joint_pose(
                    'inspection', 5, 'auth-blocked', core.session_id)))
            except Exception as exc:
                motion_outcome.append(('error', exc))

        motion = threading.Thread(target=motion_worker)
        motion.start()
        self.assertTrue(backend.send_entered.wait(timeout=1.0))

        stop_outcome = []
        stop = threading.Thread(target=lambda: stop_outcome.append(
            core.request_stop('concurrent STOP', core.session_id)))
        stop.start()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertEqual(stop_outcome, [True])
        self.assertTrue(backend.stop_entered.is_set())
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.physical_stop_required)
        self.assertTrue(core.motion_safety_unresolved)

        backend.release_send.set()
        motion.join(timeout=1.0)
        self.assertFalse(motion.is_alive())
        self.assertEqual(motion_outcome[0][0], 'error')
        self.assertIn('activation is refused', str(motion_outcome[0][1]))
        self.assertTrue(core.physical_stop_required)
        self.assertNotEqual(core.state, GatewayState.EXECUTING)
        self.assertIsNone(core.active_command)

    def test_prior_stationary_credit_cannot_mask_second_blocked_stop_or_new_motion(self):
        backend = BlockingStopBackend()
        backend.release_stop.set()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()

        backend.moving = 1
        self.assertTrue(core.request_stop(
            'first STOP', core.session_id))
        backend.moving = 0
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core._fault_stationary_verified)
        self.assertFalse(core.motion_safety_unresolved)
        clock.advance(0.15)

        backend.release_stop.clear()
        backend.stop_entered.clear()
        backend.moving = 1
        refresh_outcome = []
        refresh = threading.Thread(target=lambda: refresh_outcome.append(
            self._capture_call(core.refresh)))
        refresh.start()
        try:
            self.assertTrue(backend.stop_entered.wait(timeout=1.0))
            self.assertEqual(backend.stop_count, 2)
            self.assertFalse(core._fault_stationary_verified)
            self.assertTrue(core.motion_safety_unresolved)

            self.assertTrue(core.fail_closed_action_boundary(
                'second STOP remains blocked'))
            self.assertTrue(core.physical_stop_required)
            self.assertTrue(core.motion_safety_unresolved)
            self.assertEqual(backend.stop_count, 2)
        finally:
            backend.release_stop.set()
            refresh.join(timeout=1.0)

        self.assertFalse(refresh.is_alive())
        self.assertEqual(len(refresh_outcome), 1)
        self.assertEqual(backend.stop_count, 2)
        self.assertTrue(core.physical_stop_required)
        self.assertNotEqual(core.state, GatewayState.READY)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.acknowledge_local_fault(
                'ack-after-late-stop', core.session_id)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.request_stop('duplicate STOP', core.session_id)
        self.assertEqual(backend.stop_count, 2)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.command_named_joint_pose(
                'inspection', 5, 'motion-after-late-stop', core.session_id)
        with self.assertRaisesRegex(
                ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
            core.close()
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(backend.stop_count, 2)

    def test_idle_close_reservation_blocks_new_send_before_stale_close_plan_commits(self):
        class BlockingClosePlanCore(ArmGatewayCore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.block_close_plan = False
                self.close_plan_entered = threading.Event()
                self.release_close_plan = threading.Event()

            def _motion_safety_unresolved(self):
                if (
                        self.block_close_plan
                        and self._close_started
                        and self.state != GatewayState.CLOSED):
                    self.close_plan_entered.set()
                    self.release_close_plan.wait()
                return super()._motion_safety_unresolved()

        backend = BlockingSendBackend()
        clock = ManualClock()
        core = BlockingClosePlanCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        core.block_close_plan = True
        close_outcome = []
        motion_outcome = []
        motion_started = threading.Event()
        closer = threading.Thread(target=lambda: close_outcome.append(
            self._capture_call(core.close)))
        closer.start()
        self.assertTrue(core.close_plan_entered.wait(timeout=1.0))

        def motion_worker():
            motion_started.set()
            motion_outcome.append(self._capture_call(
                core.command_named_joint_pose,
                'inspection', 5, 'close-race-motion', core.session_id))

        motion = threading.Thread(target=motion_worker)
        motion.start()
        self.assertTrue(motion_started.wait(timeout=1.0))
        try:
            self.assertFalse(backend.send_entered.wait(timeout=0.05))
            self.assertTrue(motion.is_alive())
        finally:
            core.release_close_plan.set()
            closer.join(timeout=1.0)
            motion.join(timeout=1.0)

        self.assertFalse(closer.is_alive())
        self.assertFalse(motion.is_alive())
        self.assertEqual(close_outcome, [('returned', None)])
        self.assertEqual(len(motion_outcome), 1)
        self.assertEqual(motion_outcome[0][0], 'error')
        self.assertIn('closed or closing', str(motion_outcome[0][1]))
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.stop_count, 0)
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertFalse(core.physical_stop_required)

    def test_close_reservation_cannot_miss_new_blocked_stop_or_leave_closed_unverified_without_physical_latch(self):
        backend = BlockingStopBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        core.command_named_joint_pose(
            'inspection', 5, 'active-before-close', core.session_id)
        close_outcome = []
        closer = threading.Thread(target=lambda: close_outcome.append(
            self._capture_call(core.close)))
        closer.start()
        try:
            self.assertTrue(backend.stop_entered.wait(timeout=1.0))
            duplicate_outcome = []
            duplicate = threading.Thread(target=lambda: duplicate_outcome.append(
                self._capture_call(
                    core.request_stop,
                    'STOP racing close', core.session_id)))
            duplicate.start()
            duplicate.join(timeout=1.0)
            self.assertFalse(duplicate.is_alive())
            self.assertEqual(len(duplicate_outcome), 1)
            self.assertEqual(duplicate_outcome[0][0], 'error')
            self.assertIn('closed or closing', str(duplicate_outcome[0][1]))
            self.assertEqual(backend.stop_count, 1)
        finally:
            backend.release_stop.set()
            closer.join(timeout=1.0)

        self.assertFalse(closer.is_alive())
        self.assertEqual(len(close_outcome), 1)
        self.assertEqual(close_outcome[0][0], 'error')
        self.assertIn('stationary state is unverified', str(
            close_outcome[0][1]))
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertTrue(core.motion_safety_unresolved)
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 1)

    def test_arm_ack_rejects_stationary_credit_while_pre_stop_send_is_pending(self):
        backend = IndependentStopBlockingSendBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        motion_outcome = []
        motion = threading.Thread(target=lambda: motion_outcome.append(
            self._capture_call(
                core.command_named_joint_pose,
                'inspection', 5, 'pre-stop-send', core.session_id)))
        motion.start()
        self.assertTrue(backend.send_entered.wait(timeout=1.0))

        backend.moving = 1
        backend.error_code = 16
        core.refresh()
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.physical_stop_required)

        backend.moving = 0
        backend.error_code = 0
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        try:
            self.assertTrue(core.motion_safety_unresolved)
            self.assertTrue(core.physical_stop_required)
            self.assertFalse(core._fault_stationary_verified)
            self.assertNotEqual(core.state, GatewayState.READY)
            with self.assertRaisesRegex(
                    MotionRejected, 'PHYSICAL EMERGENCY STOP'):
                core.acknowledge_local_fault(
                    'ack-before-old-send-returns', core.session_id)
            with self.assertRaisesRegex(
                    MotionRejected, 'PHYSICAL EMERGENCY STOP'):
                core.request_stop('duplicate STOP', core.session_id)
            self.assertEqual(backend.stop_count, 1)
        finally:
            backend.release_send.set()
            motion.join(timeout=1.0)

        self.assertFalse(motion.is_alive())
        self.assertEqual(len(motion_outcome), 1)
        self.assertEqual(motion_outcome[0][0], 'error')
        self.assertIn('activation is refused', str(motion_outcome[0][1]))
        self.assertTrue(core.physical_stop_required)
        self.assertTrue(core.motion_safety_unresolved)
        self.assertEqual(backend.stop_count, 1)

    def test_refresh_captured_before_activation_cannot_complete_command(self):
        class BlockingCommandAndLateSnapshotBackend(FakeArmBackend):
            def __init__(self):
                super().__init__()
                self.send_entered = threading.Event()
                self.release_send = threading.Event()
                self.snapshot_captured = threading.Event()
                self.release_snapshot = threading.Event()
                self.block_next_coords = False

            def send_angles(self, target, speed):
                super().send_angles(target, speed)
                self.angles = list(target)
                self.moving = 0
                self.send_entered.set()
                self.release_send.wait()

            def get_coords(self):
                captured = super().get_coords()
                if self.block_next_coords:
                    self.block_next_coords = False
                    self.snapshot_captured.set()
                    self.release_snapshot.wait()
                return captured

        backend = BlockingCommandAndLateSnapshotBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        pre_activation_epoch = core._state_epoch
        command_outcome = []
        command = threading.Thread(target=lambda: command_outcome.append(
            self._capture_call(
                core.command_named_joint_pose,
                'inspection', 5, 'auth-1', core.session_id)))
        command.start()
        self.assertTrue(backend.send_entered.wait(timeout=1.0))

        core.refresh()
        pre_activation_snapshot = core.snapshot
        self.assertEqual(core.state, GatewayState.READY)
        self.assertIsNone(core.last_result)
        self.assertEqual(core._stable_samples, 0)

        backend.block_next_coords = True
        late_refresh_outcome = []
        late_refresh = threading.Thread(target=lambda: late_refresh_outcome.append(
            self._capture_call(core.refresh)))
        late_refresh.start()
        self.assertTrue(backend.snapshot_captured.wait(timeout=1.0))
        late_refresh_generation = core._refresh_generation
        backend.release_send.set()
        command.join(timeout=1.0)
        self.assertFalse(command.is_alive())
        self.assertEqual(command_outcome[0][0], 'returned')
        activation_epoch = core._state_epoch
        self.assertEqual(activation_epoch, pre_activation_epoch + 1)
        self.assertEqual(
            core._refresh_generation, late_refresh_generation)

        backend.release_snapshot.set()
        late_refresh.join(timeout=1.0)
        self.assertFalse(late_refresh.is_alive())
        self.assertEqual(len(late_refresh_outcome), 1)
        self.assertEqual(late_refresh_outcome[0][0], 'error')
        self.assertIn('superseded', str(late_refresh_outcome[0][1]))
        self.assertEqual(core._state_epoch, activation_epoch)
        self.assertEqual(
            core._refresh_generation, late_refresh_generation)
        self.assertIs(core.snapshot, pre_activation_snapshot)
        self.assertEqual(core.state, GatewayState.EXECUTING)
        self.assertIsNone(core.last_result)
        self.assertEqual(core._stable_samples, 0)

        core.refresh()
        self.assertEqual(core.state, GatewayState.EXECUTING)
        self.assertEqual(core._stable_samples, 1)
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.READY)
        self.assertTrue(core.last_result.success)

    def test_refresh_captured_before_stop_return_cannot_verify_stationary(self):
        class BlockingStopAndLateSnapshotBackend(FakeArmBackend):
            def __init__(self):
                super().__init__()
                self.stop_entered = threading.Event()
                self.release_stop = threading.Event()
                self.snapshot_captured = threading.Event()
                self.release_snapshot = threading.Event()
                self.block_next_coords = False

            def stop(self):
                self.stop_count += 1
                self.angles = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                self.moving = 0
                self.stop_entered.set()
                self.release_stop.wait()

            def get_coords(self):
                captured = super().get_coords()
                if self.block_next_coords:
                    self.block_next_coords = False
                    self.snapshot_captured.set()
                    self.release_snapshot.wait()
                return captured

        backend = BlockingStopAndLateSnapshotBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        pre_stop_snapshot = core.snapshot
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        pre_stop_epoch = core._state_epoch
        stop_outcome = []
        stop = threading.Thread(target=lambda: stop_outcome.append(
            self._capture_call(
                core.request_stop, 'operator STOP', core.session_id)))
        stop.start()
        self.assertTrue(backend.stop_entered.wait(timeout=1.0))
        reservation_epoch = core._state_epoch
        self.assertEqual(reservation_epoch, pre_stop_epoch + 1)

        backend.block_next_coords = True
        late_refresh_outcome = []
        late_refresh = threading.Thread(target=lambda: late_refresh_outcome.append(
            self._capture_call(core.refresh)))
        late_refresh.start()
        self.assertTrue(backend.snapshot_captured.wait(timeout=1.0))
        late_refresh_generation = core._refresh_generation
        backend.release_stop.set()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertEqual(stop_outcome, [('returned', True)])
        stop_commit_epoch = core._state_epoch
        self.assertEqual(stop_commit_epoch, reservation_epoch + 1)
        self.assertEqual(
            core._refresh_generation, late_refresh_generation)

        backend.release_snapshot.set()
        late_refresh.join(timeout=1.0)
        self.assertFalse(late_refresh.is_alive())
        self.assertEqual(len(late_refresh_outcome), 1)
        self.assertEqual(late_refresh_outcome[0][0], 'error')
        self.assertIn('superseded', str(late_refresh_outcome[0][1]))
        self.assertEqual(core._state_epoch, stop_commit_epoch)
        self.assertEqual(
            core._refresh_generation, late_refresh_generation)
        self.assertIs(core.snapshot, pre_stop_snapshot)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(core._stable_samples, 0)
        self.assertIsNone(core._last_stopping_angles)

        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(core._stable_samples, 0)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(core._stable_samples, 1)
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core._fault_stationary_verified)

    def test_stop_does_not_wait_for_blocked_refresh_and_late_success_is_dropped(self):
        backend = BlockingQueryBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        backend.release_query.set()
        core.refresh()
        original_snapshot = core.snapshot
        backend.release_query.clear()
        backend.angles = [1.0] * 6
        outcomes = []

        refresh = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(core.refresh)))
        refresh.start()
        self.assertTrue(backend.query_entered.wait(timeout=1.0))

        stop = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.request_stop, 'STOP during query', core.session_id)))
        stop.start()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertTrue(backend.stop_entered.is_set())
        self.assertEqual(core.state, GatewayState.STOPPING)

        backend.release_query.set()
        refresh.join(timeout=1.0)
        self.assertFalse(refresh.is_alive())
        self.assertIs(core.snapshot, original_snapshot)
        refresh_errors = [value for kind, value in outcomes if kind == 'error']
        self.assertEqual(len(refresh_errors), 1)
        self.assertIn('superseded', str(refresh_errors[0]))

    def test_late_refresh_cannot_overwrite_a_newer_refresh_same_state_epoch(self):
        backend = OneBlockingSnapshotBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        backend.block_next_query = True
        outcomes = []
        older = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(core.refresh)))
        older.start()
        self.assertTrue(backend.query_entered.wait(timeout=1.0))

        clock.advance(0.01)
        backend.angles = [20.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        newer = core.refresh()
        self.assertEqual(newer.angles_deg[0], 20.0)

        backend.release_query.set()
        older.join(timeout=1.0)
        self.assertFalse(older.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0][0], 'error')
        self.assertIn('newer refresh generation', str(outcomes[0][1]))
        self.assertIs(core.snapshot, newer)
        self.assertEqual(core.snapshot.angles_deg[0], 20.0)

    def test_stop_does_not_wait_for_blocked_refresh_and_late_failure_is_dropped(self):
        backend = BlockingQueryBackend(fail_after_release=True)
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            stop_clock=clock,
            authorization_validator=allow_test_authorization,
        )
        backend.fail_after_release = False
        backend.release_query.set()
        core.refresh()
        backend.release_query.clear()
        backend.fail_after_release = True
        outcomes = []

        refresh = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(core.refresh)))
        refresh.start()
        self.assertTrue(backend.query_entered.wait(timeout=1.0))
        self.assertTrue(core.request_stop(
            'STOP before late query failure', core.session_id))
        stop_epoch = core._state_epoch
        stop_reason = core.fault_reason
        backend.release_query.set()
        refresh.join(timeout=1.0)

        self.assertFalse(refresh.is_alive())
        self.assertEqual(core._state_epoch, stop_epoch)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(core.fault_reason, stop_reason)
        self.assertIn('superseded', str(outcomes[0][1]))

    def test_stop_does_not_wait_for_blocked_snapshot_clock(self):
        backend = FakeArmBackend()
        setup_clock = ManualClock()
        blocking_clock = BlockingClock(setup_clock.now)
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=setup_clock,
            stop_clock=setup_clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        core._clock = blocking_clock
        outcomes = []

        validator = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(core.snapshot_is_valid)))
        validator.start()
        self.assertTrue(blocking_clock.entered.wait(timeout=1.0))
        stop = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.request_stop, 'STOP during clock', core.session_id)))
        stop.start()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertEqual(core.state, GatewayState.STOPPING)

        blocking_clock.release.set()
        validator.join(timeout=1.0)
        self.assertFalse(validator.is_alive())
        self.assertIn(('returned', False), outcomes)

    def test_stop_does_not_wait_for_blocked_ack_validator(self):
        validator_entered = threading.Event()
        release_validator = threading.Event()

        def validator(value, purpose, session_id):
            if purpose == 'ack':
                validator_entered.set()
                release_validator.wait()
            return allow_test_authorization(value, purpose, session_id)

        core, backend, clock = ready_core(
            authorization_validator=validator)
        core._latch_fault('local test fault')
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        outcomes = []
        ack = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.acknowledge_local_fault,
                'ack-blocked', core.session_id)))
        ack.start()
        self.assertTrue(validator_entered.wait(timeout=1.0))

        stop = threading.Thread(target=lambda: outcomes.append(
            self._capture_call(
                core.request_stop, 'STOP during ACK', core.session_id)))
        stop.start()
        stop.join(timeout=1.0)
        self.assertFalse(stop.is_alive())
        self.assertEqual(core.state, GatewayState.STOPPING)

        release_validator.set()
        ack.join(timeout=1.0)
        self.assertFalse(ack.is_alive())
        ack_errors = [value for kind, value in outcomes if kind == 'error']
        self.assertEqual(len(ack_errors), 1)
        self.assertIn('superseded', str(ack_errors[0]))

    def test_stop_then_late_send_failure_cannot_overwrite_stop_epoch(self):
        backend = IndependentStopBlockingSendBackend()
        backend.fail_joint_send = True
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        motion_outcome = []

        def motion_worker():
            try:
                core.command_named_joint_pose(
                    'inspection', 5, 'auth-late-failure', core.session_id)
            except Exception as exc:
                motion_outcome.append(exc)

        motion = threading.Thread(target=motion_worker)
        motion.start()
        self.assertTrue(backend.send_entered.wait(timeout=1.0))
        self.assertTrue(core.request_stop(
            'concurrent STOP before send failure', core.session_id))
        stop_epoch = core._state_epoch
        stop_attempts = backend.stop_count

        backend.release_send.set()
        motion.join(timeout=1.0)

        self.assertFalse(motion.is_alive())
        self.assertEqual(len(motion_outcome), 1)
        self.assertIn('newer STOP/close/fault', str(motion_outcome[0]))
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(backend.stop_count, stop_attempts)
        self.assertGreater(core._state_epoch, stop_epoch)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertIsNone(core.active_command)

    def test_close_then_late_send_failure_preserves_closed_state(self):
        backend = BlockingSendBackend()
        backend.fail_joint_send = True
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        motion_outcome = []

        def motion_worker():
            try:
                core.command_named_joint_pose(
                    'inspection', 5, 'auth-close-failure', core.session_id)
            except Exception as exc:
                motion_outcome.append(exc)

        motion = threading.Thread(target=motion_worker)
        motion.start()
        self.assertTrue(backend.send_entered.wait(timeout=1.0))
        with self.assertRaisesRegex(
                ArmGatewayError, 'stationary state is unverified'):
            core.close()
        close_epoch = core._state_epoch

        backend.release_send.set()
        motion.join(timeout=1.0)

        self.assertFalse(motion.is_alive())
        self.assertEqual(len(motion_outcome), 1)
        self.assertIn('newer STOP/close/fault', str(motion_outcome[0]))
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertTrue(core.physical_stop_required)
        self.assertGreater(core._state_epoch, close_epoch)
        self.assertIsNone(core.active_command)

    def test_stop_uses_core_lock_only_for_short_state_commits(self):
        source = MODULE.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(MODULE))
        core_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == 'ArmGatewayCore')
        request_stop = next(
            node for node in core_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == 'request_stop')
        stop_calls = [
            node for node in ast.walk(request_stop)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == '_send_stop_attempt'
        ]
        self.assertEqual(len(stop_calls), 1)
        core_lock_blocks = [
            node for node in ast.walk(request_stop)
            if isinstance(node, ast.With)
            and any(
                isinstance(item.context_expr, ast.Attribute)
                and isinstance(item.context_expr.value, ast.Name)
                and item.context_expr.value.id == 'self'
                and item.context_expr.attr == '_lock'
                for item in node.items)
        ]
        self.assertEqual(len(core_lock_blocks), 3)
        for block in core_lock_blocks:
            locked_calls = {
                node.func.attr
                for node in ast.walk(block)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            }
            self.assertTrue({
                '_send_stop_attempt', '_call_external',
                '_call_external_method',
            }.isdisjoint(locked_calls))

    def test_core_lock_blocks_never_call_injected_or_transport_code(self):
        source = MODULE.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(MODULE))
        core_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == 'ArmGatewayCore')
        forbidden = {
            '_call_external',
            '_call_external_method',
            '_read_clock',
            '_stop_clock_now',
            '_send_stop_attempt',
            '_send_uncredited_emergency_stop',
            '_require_authorization',
            '_new_command',
            '_read_backend_capabilities',
        }
        violations = []
        for method in (
                node for node in core_class.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for block in ast.walk(method):
                if not isinstance(block, ast.With):
                    continue
                if not any(
                        isinstance(item.context_expr, ast.Attribute)
                        and isinstance(item.context_expr.value, ast.Name)
                        and item.context_expr.value.id == 'self'
                        and item.context_expr.attr == '_lock'
                        for item in block.items):
                    continue
                called = {
                    node.func.attr
                    for node in ast.walk(block)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                }
                overlap = sorted(called & forbidden)
                if overlap:
                    violations.append((method.name, block.lineno, overlap))
        self.assertEqual(violations, [])

    def test_physical_escalation_advances_epoch_once(self):
        core, unused_backend, unused_clock = ready_core()
        before = core._state_epoch
        core._escalate_physical_stop('test physical isolation escalation')
        self.assertEqual(core._state_epoch, before + 1)
        self.assertTrue(core.physical_stop_required)

    def test_core_rejects_integrated_persistent_latch_io(self):
        with self.assertRaisesRegex(
                ValueError, 'independently bounded release supervisor'):
            ArmGatewayCore(
                FakeArmBackend(),
                make_policy(True),
                clock=ManualClock(),
                authorization_validator=allow_test_authorization,
                persistent_safety_latch=FakePersistentLatch(),
            )

    def test_reentrant_close_then_send_failure_stays_fail_closed(self):
        backend = CallbackSendBackend()
        backend.fail_after_callback = True
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        close_outcome = []

        def close_before_failure():
            try:
                core.close()
            except ArmGatewayError as exc:
                close_outcome.append(str(exc))

        backend.before_send_return = close_before_failure
        with self.assertRaisesRegex(
                ArmGatewayError, 'send failed.*best-effort STOP sent'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(len(close_outcome), 1)
        self.assertIn('reentrant gateway close is prohibited', close_outcome[0])
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertIsNone(core.active_command)

    def test_reentrant_close_during_send_is_rejected(self):
        backend = CallbackSendBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        close_outcome = []

        def close_before_send_returns():
            try:
                core.close()
            except ArmGatewayError as exc:
                close_outcome.append(str(exc))

        backend.before_send_return = close_before_send_returns
        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(len(close_outcome), 1)
        self.assertIn('reentrant gateway close is prohibited', close_outcome[0])
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(backend.stop_count, 0)
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(core.state, GatewayState.EXECUTING)
        self.assertEqual(core.active_command, command)

    def test_reentrant_motion_during_send_is_rejected_before_backend(self):
        backend = CallbackSendBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        nested_outcome = []

        def nested_motion():
            try:
                core.command_named_joint_pose(
                    'inspection', 5, 'auth-2', core.session_id)
            except ArmGatewayError as exc:
                nested_outcome.append(str(exc))

        backend.before_send_return = nested_motion
        outer = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(len(nested_outcome), 1)
        self.assertIn('reentrant gateway', nested_outcome[0])
        self.assertEqual(core.active_command, outer)
        self.assertEqual(core.state, GatewayState.EXECUTING)
        self.assertEqual(core._used_authorization_ids, {'auth-1'})

    def test_backend_callback_cannot_reenter_stop_or_close(self):
        backend = CallbackSendBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core.refresh()
        reentry_errors = []

        def reenter_gateway():
            for operation in (
                    lambda: core.request_stop(
                        'reentrant STOP', core.session_id),
                    core.close):
                try:
                    operation()
                except Exception as exc:
                    reentry_errors.append(exc)

        backend.before_send_return = reenter_gateway
        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(len(reentry_errors), 2)
        self.assertTrue(all(
            isinstance(exc, ArmGatewayError)
            and 'reentrant gateway' in str(exc)
            for exc in reentry_errors))
        self.assertEqual(backend.stop_count, 0)
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(core.active_command, command)
        self.assertEqual(core.state, GatewayState.EXECUTING)

    def test_backend_method_lookup_cannot_reenter_close(self):
        lookup_errors = []
        core_holder = {}

        class DescriptorBackend(FakeArmBackend):
            def __getattribute__(self, name):
                if name == 'send_angles' and 'core' in core_holder:
                    try:
                        core_holder['core'].close()
                    except Exception as exc:
                        lookup_errors.append(exc)
                return super().__getattribute__(name)

        backend = DescriptorBackend()
        clock = ManualClock()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
        )
        core_holder['core'] = core
        core.refresh()
        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(len(lookup_errors), 1)
        self.assertIsInstance(lookup_errors[0], ArmGatewayError)
        self.assertIn(
            'reentrant gateway close is prohibited',
            str(lookup_errors[0]))
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(len(backend.sent_angles), 1)
        self.assertEqual(core.active_command, command)
        self.assertEqual(core.state, GatewayState.EXECUTING)

    def test_command_id_factory_rejects_objects_without_string_coercion(self):
        coercion_calls = []
        backend = FakeArmBackend()
        clock = ManualClock()
        core_holder = {}

        class ReentrantCommandId:
            def __str__(self):
                coercion_calls.append(True)
                core_holder['core'].close()
                return 'COERCED_COMMAND'

        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
            command_id_factory=lambda: ReentrantCommandId(),
        )
        core_holder['core'] = core
        core.refresh()
        with self.assertRaisesRegex(
                ArmGatewayError, 'must return a string'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(coercion_calls, [])
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(core.state, GatewayState.READY)
        self.assertNotIn('auth-1', core._used_authorization_ids)

    def test_command_id_factory_rejects_string_subclass_before_strip(self):
        strip_calls = []
        backend = FakeArmBackend()
        clock = ManualClock()
        core_holder = {}

        class ReentrantString(str):
            def strip(self, *args, **kwargs):
                strip_calls.append(True)
                core_holder['core'].close()
                return super().strip(*args, **kwargs)

        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=clock,
            authorization_validator=allow_test_authorization,
            command_id_factory=lambda: ReentrantString('SUBCLASS_ID'),
        )
        core_holder['core'] = core
        core.refresh()
        with self.assertRaisesRegex(
                ArmGatewayError, 'must return a string'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)

        self.assertEqual(strip_calls, [])
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(core.state, GatewayState.READY)
        self.assertNotIn('auth-1', core._used_authorization_ids)

    def test_session_and_authorization_reject_string_subclass_before_strip(self):
        strip_calls = []
        core, backend, _ = ready_core()

        class ReentrantString(str):
            def strip(value, *args, **kwargs):
                strip_calls.append(str.__str__(value))
                core.close()
                return str.strip(value, *args, **kwargs)

        with self.assertRaisesRegex(MotionRejected, 'session id'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1',
                ReentrantString(core.session_id))
        with self.assertRaisesRegex(MotionRejected, 'authorization_id'):
            core.command_named_joint_pose(
                'inspection', 5, ReentrantString('auth-1'), core.session_id)
        self.assertEqual(strip_calls, [])
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.close_count, 0)

    def test_pre_send_validation_and_id_failure_do_not_consume(self):
        factory_calls = []

        def command_id_factory():
            factory_calls.append(True)
            if len(factory_calls) == 1:
                raise RuntimeError('id generation failed')
            return 'generated-after-retry'

        core, backend, _ = ready_core(
            command_id_factory=command_id_factory)
        with self.assertRaisesRegex(MotionRejected, 'not approved'):
            core.command_named_joint_pose(
                'unknown', 5, 'motion-auth-1', core.session_id)
        self.assertNotIn('motion-auth-1', core._used_authorization_ids)
        self.assertEqual(factory_calls, [])

        with self.assertRaisesRegex(RuntimeError, 'id generation failed'):
            core.command_named_joint_pose(
                'inspection', 5, 'motion-auth-1', core.session_id)
        self.assertNotIn('motion-auth-1', core._used_authorization_ids)
        self.assertEqual(core._issued_command_ids, set())
        self.assertEqual(backend.sent_angles, [])

        command = core.command_named_joint_pose(
            'inspection', 5, 'motion-auth-1', core.session_id)
        self.assertEqual(command.command_id, 'generated-after-retry')
        self.assertEqual(command.session_id, core.session_id)

    def test_ack_authorization_is_purpose_bound_and_one_time(self):
        allowed = {
            'motion': {'motion-auth-1'},
            'ack': {'ack-auth-1'},
        }

        def validator(value, purpose, unused_session_id):
            return value in allowed[purpose]

        core, backend, clock = ready_core(authorization_validator=validator)
        core.request_stop('operator STOP', core.session_id)
        backend.moving = 0
        core.refresh()
        clock.advance(0.01)
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        with self.assertRaisesRegex(MotionRejected, 'ack purpose'):
            core.acknowledge_local_fault(
                'motion-auth-1', core.session_id)
        self.assertTrue(core.acknowledge_local_fault(
            'ack-auth-1', core.session_id))

        core.request_stop('second STOP', core.session_id)
        core.refresh()
        clock.advance(0.01)
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        with self.assertRaisesRegex(MotionRejected, 'consumed'):
            core.acknowledge_local_fault(
                'ack-auth-1', core.session_id)

    def test_policy_rejects_nonfinite_and_invalid_safety_parameters(self):
        invalid_updates = (
            {'permit_motion': 1},
            {'expected_real_transport': 1},
            {'approved_speed_grades': ()},
            {'approved_speed_grades': [5, 10]},
            {'approved_speed_grades': (True,)},
            {'approved_speed_grades': (5, 5)},
            {'approved_speed_grades': (10, 5)},
            {'approved_speed_grades': (11,)},
            {'state_max_age_s': math.nan},
            {'command_timeout_s': math.inf},
            {'stop_timeout_s': 0.0},
            {'max_stop_attempts': 0},
            {'max_stop_attempts': True},
            {'stop_retry_interval_s': 0.0},
            {'stop_retry_backoff_factor': 0.5},
            {'stable_samples_required': True},
            {'stable_samples_required': 1},
            {'stationary_dwell_s': 0.0},
            {'stationary_joint_tolerance_deg': math.nan},
            {'joint_tolerance_deg': 0.0},
            {'tcp_translation_tolerance_mm': math.nan},
            {'tcp_rotation_tolerance_deg': -1.0},
            {'acceleration_profile_id': ''},
            {'runtime_release_id': ''},
            {'release_manifest_sha256': 'a' * 63},
            {'release_manifest_sha256': 'A' * 64},
            {'acceleration_profile_manifest_sha256': 'z' * 64},
            {'acceleration_profile_manifest_sha256': 'a' * 64},
            {'acceleration_profile_runtime_release_id': 'stale-release'},
            {'required_reference_frame': 2},
            {'required_end_type': -1},
            {'required_fresh_mode': 2},
            {'joint_limits_deg': [(-160.0, 160.0)] * 6},
            {'joint_limits_deg': ([-160.0, 160.0],) * 6},
            {'tcp_bounds': [(-1.0, 1.0)] * 6},
            {'tcp_bounds': ([-1.0, 1.0],) * 6},
            {'allowed_tcp_modes': [MOVE_J]},
        )
        for updates in invalid_updates:
            with self.subTest(updates=updates):
                policy = replace(make_policy(), **updates)
                with self.assertRaises(ValueError):
                    policy.validate()

    def test_policy_rejects_active_string_and_mapping_subclasses(self):
        calls = []

        class ActiveString(str):
            def strip(value, *args, **kwargs):
                calls.append('strip')
                return str.strip(value, *args, **kwargs)

        class ActiveDict(dict):
            def items(value):
                calls.append('items')
                return dict.items(value)

        cases = (
            replace(
                make_policy(),
                acceleration_profile_id=ActiveString('profile')),
            replace(
                make_policy(),
                named_joint_poses={
                    ActiveString('inspection'):
                    (10.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                }),
            replace(
                make_policy(),
                named_joint_poses=ActiveDict({
                    'inspection': (10.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                })),
        )
        for policy in cases:
            with self.subTest(policy=policy):
                with self.assertRaises(ValueError):
                    policy.validate()
        self.assertEqual(calls, [])

    def test_core_rejects_policy_subclass_without_calling_overrides(self):
        calls = []

        class ActivePolicy(ArmGatewayPolicy):
            def immutable_copy(value):
                calls.append('immutable_copy')
                return value

        original = make_policy()
        active = ActivePolicy(**original.__dict__)
        with self.assertRaisesRegex(
                ValueError, 'exact ArmGatewayPolicy'):
            ArmGatewayCore(
                FakeArmBackend(),
                active,
                clock=ManualClock(),
                authorization_validator=allow_test_authorization,
            )
        self.assertEqual(calls, [])

    def test_constructor_does_not_evaluate_injected_callable_truthiness(self):
        calls = []

        class ActiveCallable:
            def __init__(self, value):
                self.value = value

            def __bool__(self):
                calls.append('bool')
                raise AssertionError('truthiness must not be evaluated')

            def __call__(self):
                return self.value

        clock = ActiveCallable(100.0)
        stop_clock = ActiveCallable(100.0)
        command_id_factory = ActiveCallable('command-id')
        core = ArmGatewayCore(
            FakeArmBackend(),
            make_policy(),
            clock=clock,
            stop_clock=stop_clock,
            authorization_validator=allow_test_authorization,
            command_id_factory=command_id_factory,
        )
        self.assertIs(core._clock, clock)
        self.assertIs(core._stop_clock, stop_clock)
        self.assertIs(core._command_id_factory, command_id_factory)
        self.assertEqual(calls, [])

    def test_named_pose_rejects_and_stop_reason_downgrades_string_subclass(self):
        calls = []
        core, backend, _ = ready_core()

        class ActiveString(str):
            def strip(value, *args, **kwargs):
                calls.append('strip')
                core.close()
                return str.strip(value, *args, **kwargs)

        with self.assertRaisesRegex(MotionRejected, 'pose name'):
            core.command_named_joint_pose(
                ActiveString('inspection'), 5, 'auth-1', core.session_id)
        self.assertTrue(core.request_stop(
            ActiveString('operator STOP'), core.session_id))
        self.assertEqual(calls, [])
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertIn('stop requested', core.fault_reason)

    def test_speed_grade_subclass_is_rejected_without_callbacks(self):
        calls = []
        core, backend, _ = ready_core()

        class ActiveInt(int):
            def __le__(value, other):
                calls.append('le')
                core.close()
                return int.__le__(value, other)

        with self.assertRaisesRegex(MotionRejected, 'integer'):
            core.command_named_joint_pose(
                'inspection', ActiveInt(5), 'auth-1', core.session_id)
        self.assertEqual(calls, [])
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.stop_count, 0)
        self.assertEqual(backend.close_count, 0)
        self.assertEqual(core.state, GatewayState.READY)

    def test_active_integer_feedback_is_rejected_without_callbacks(self):
        calls = []
        backend = FakeArmBackend()
        policy = make_policy(True)
        core = ArmGatewayCore(backend, policy, clock=ManualClock())

        class ActiveInt(int):
            def __eq__(value, other):
                calls.append('eq')
                core.close()
                return int.__eq__(value, other)

        backend.moving = ActiveInt(0)
        snapshot = core.refresh()
        self.assertEqual(calls, [])
        self.assertEqual(type(snapshot.moving), ActiveInt)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertIn('exact integer', core.fault_reason)
        self.assertEqual(backend.stop_count, 0)
        self.assertEqual(backend.close_count, 0)

    def test_policy_rejects_nonfinite_derived_stop_retry_delay(self):
        policies = (
            replace(
                make_policy(),
                max_stop_attempts=3,
                stop_retry_interval_s=1e308,
                stop_retry_backoff_factor=2.0,
            ),
            replace(
                make_policy(),
                max_stop_attempts=10,
                stop_retry_interval_s=1.0,
                stop_retry_backoff_factor=1e200,
            ),
        )
        for policy in policies:
            with self.subTest(policy=policy):
                with self.assertRaisesRegex(
                        ValueError, 'derived STOP retry delay'):
                    policy.validate()

    def test_motion_requires_fresh_state_and_authorization(self):
        core, backend, clock = ready_core()
        with self.assertRaisesRegex(MotionRejected, 'authorization_id'):
            core.command_named_joint_pose(
                'inspection', 5, '', core.session_id)
        clock.advance(0.30)
        with self.assertRaisesRegex(MotionRejected, 'fresh motion-ready'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])

    def test_motion_rechecks_limits_on_latest_snapshot(self):
        core, backend, _ = ready_core()
        backend.angles = [999.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        core.snapshot = replace(
            core.snapshot,
            angles_deg=tuple(backend.angles),
        )
        with self.assertRaisesRegex(MotionRejected, 'latest controller state'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])

    def test_required_fresh_mode_is_fail_closed(self):
        backend = FakeArmBackend()
        backend.fresh_mode = 1
        core = ArmGatewayCore(
            backend, make_policy(True), clock=ManualClock())
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertIn('fresh mode mismatch', core.fault_reason)
        self.assertFalse(core.snapshot_is_valid())

    def test_snapshot_valid_requires_fresh_healthy_state(self):
        core, backend, clock = ready_core()
        self.assertTrue(core.snapshot_is_valid())
        clock.advance(0.26)
        self.assertFalse(core.snapshot_is_valid())
        backend.error_code = 16
        core.refresh()
        self.assertFalse(core.snapshot_is_valid())

    def test_named_pose_rejects_unapproved_name_and_excess_speed(self):
        core, backend, _ = ready_core()
        with self.assertRaisesRegex(MotionRejected, 'not approved'):
            core.command_named_joint_pose(
                'home', 5, 'auth-1', core.session_id)
        with self.assertRaisesRegex(MotionRejected, 'approved grades'):
            core.command_named_joint_pose(
                'inspection', 11, 'auth-1', core.session_id)
        with self.assertRaisesRegex(MotionRejected, 'approved grades'):
            core.command_named_joint_pose(
                'inspection', 6, 'auth-2', core.session_id)
        self.assertEqual(backend.sent_angles, [])

    def test_named_pose_finishes_after_distinct_measured_samples_and_dwell(self):
        core, backend, clock = ready_core()
        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(
            backend.sent_angles,
            [([10.0, 0.0, 0.0, 0.0, 0.0, 0.0], 5)],
        )
        self.assertEqual(core.state, GatewayState.EXECUTING)

        backend.moving = 1
        core.refresh()
        self.assertEqual(core.state, GatewayState.EXECUTING)

        backend.moving = 0
        backend.angles = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        core.refresh()
        self.assertEqual(core.state, GatewayState.EXECUTING)
        for _ in range(5):
            core.refresh()
        self.assertEqual(core.state, GatewayState.EXECUTING)
        clock.advance(0.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.EXECUTING)
        clock.advance(0.10)
        core.refresh()
        self.assertEqual(core.state, GatewayState.READY)
        self.assertEqual(core.last_result.command_id, command.command_id)
        self.assertTrue(core.last_result.success)

    def test_tcp_feedback_objects_cannot_reenter_via_formatting(self):
        calls = []
        core, backend, _ = ready_core()

        class ActiveFeedback:
            def __format__(value, unused_spec):
                calls.append('format')
                core.command_named_joint_pose(
                    'inspection', 5, 'nested-auth', core.session_id)
                return '0'

            def __eq__(value, unused_other):
                calls.append('eq')
                return False

        backend.reference_frame = ActiveFeedback()
        with self.assertRaisesRegex(MotionRejected, 'exact integer'):
            core.command_tcp_move(
                [120.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                5, MOVE_J, 'outer-auth', core.session_id)
        self.assertEqual(calls, [])
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(backend.sent_coords, [])
        self.assertEqual(core.state, GatewayState.READY)
        self.assertNotIn('outer-auth', core._used_authorization_ids)

    def test_tcp_move_checks_frame_end_type_mode_and_bounds(self):
        core, backend, _ = ready_core()
        target = [120.0, 0.0, 220.0, 0.0, 0.0, 0.0]

        backend.reference_frame = 1
        with self.assertRaisesRegex(
                MotionRejected, 'reference frame mismatch'):
            core.command_tcp_move(
                target, 5, MOVE_J, 'auth-1', core.session_id)
        backend.reference_frame = 0
        backend.end_type = 1
        with self.assertRaisesRegex(MotionRejected, 'end type mismatch'):
            core.command_tcp_move(
                target, 5, MOVE_J, 'auth-1', core.session_id)
        backend.end_type = 0
        backend.reference_frame = False
        with self.assertRaisesRegex(
                MotionRejected, 'reference frame feedback'):
            core.command_tcp_move(
                target, 5, MOVE_J, 'auth-1', core.session_id)
        backend.reference_frame = 0
        backend.end_type = False
        with self.assertRaisesRegex(MotionRejected, 'end type feedback'):
            core.command_tcp_move(
                target, 5, MOVE_J, 'auth-1', core.session_id)
        backend.end_type = 0
        with self.assertRaisesRegex(MotionRejected, 'not permitted'):
            core.command_tcp_move(
                target, 5, MOVE_L, 'auth-1', core.session_id)
        with self.assertRaisesRegex(MotionRejected, 'outside'):
            core.command_tcp_move(
                [999.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                5, MOVE_J, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_coords, [])

    def test_tcp_frame_query_failure_latches_fault(self):
        core, backend, _ = ready_core()
        backend.fail_frame_query = True
        with self.assertRaisesRegex(ArmGatewayError, 'frame query failed'):
            core.command_tcp_move(
                [120.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                5,
                MOVE_J,
                'auth-1',
                core.session_id,
            )
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.sent_coords, [])

    def test_nonzero_controller_error_latches_fault_without_motion(self):
        backend = FakeArmBackend()
        backend.error_code = 3
        core = ArmGatewayCore(
            backend, make_policy(True), clock=ManualClock())
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertIn('error code', core.fault_reason)
        self.assertEqual(backend.sent_angles, [])

    def test_unexpected_motion_without_command_requests_stop(self):
        backend = FakeArmBackend()
        backend.moving = 1
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=ManualClock(),
        )
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('unexpected motion', core.fault_reason)

    def test_paused_or_out_of_bounds_state_cannot_be_ready(self):
        cases = (
            ('paused', lambda backend: setattr(backend, 'paused', 1)),
            (
                'joint',
                lambda backend: setattr(
                    backend,
                    'angles',
                    [999.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ),
            (
                'TCP',
                lambda backend: setattr(
                    backend,
                    'coords',
                    [999.0, 0.0, 200.0, 0.0, 0.0, 0.0],
                ),
            ),
        )
        for expected, mutate in cases:
            with self.subTest(expected=expected):
                backend = FakeArmBackend()
                mutate(backend)
                core = ArmGatewayCore(
                    backend,
                    make_policy(True),
                    clock=ManualClock(),
                )
                core.refresh()
                self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
                self.assertIn(expected, core.fault_reason)
                self.assertEqual(backend.sent_angles, [])

    def test_error_during_motion_requests_stop(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        backend.error_code = 16
        core.refresh()
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertIn('error code', core.fault_reason)

    def test_command_send_failure_latches_fault(self):
        core, backend, _ = ready_core()
        backend.fail_joint_send = True
        with self.assertRaisesRegex(ArmGatewayError, 'send failed'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('best-effort STOP sent', core.fault_reason)

    def test_tcp_send_failure_attempts_stop_and_latches_fault(self):
        core, backend, _ = ready_core()
        backend.fail_tcp_send = True
        with self.assertRaisesRegex(ArmGatewayError, 'TCP command send failed'):
            core.command_tcp_move(
                [120.0, 0.0, 220.0, 0.0, 0.0, 0.0],
                5,
                MOVE_J,
                'auth-1',
                core.session_id,
            )
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)

    def test_send_failure_records_stop_failure(self):
        core, backend, _ = ready_core()
        backend.fail_joint_send = True
        backend.fail_stop = True
        with self.assertRaisesRegex(ArmGatewayError, 'STOP failed'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)

    def test_state_query_failure_invalidates_snapshot_and_stops_motion(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        backend.fail_state_query = True
        with self.assertRaisesRegex(ArmGatewayError, 'state query failed'):
            core.refresh()
        self.assertIsNone(core.snapshot)
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('best-effort STOP sent', core.fault_reason)

    def test_external_exception_text_cannot_reenter_motion(self):
        events = []
        string_calls = []

        class ReentrantError(Exception):
            def __str__(error):
                string_calls.append(True)
                core.command_named_joint_pose(
                    'inspection', 5, 'evil-auth', core.session_id)
                return 'untrusted exception detail'

        class ReentrantReadBackend(FakeArmBackend):
            def get_angles(self):
                events.append('READ')
                raise ReentrantError()

            def send_angles(self, target, speed):
                events.append('MOTION')
                return super().send_angles(target, speed)

            def stop(self):
                events.append('STOP')
                return super().stop()

        backend = ReentrantReadBackend()
        core = ArmGatewayCore(
            backend,
            make_policy(True),
            clock=ManualClock(),
            authorization_validator=allow_test_authorization,
        )
        with self.assertRaisesRegex(ArmGatewayError, 'OSError|ReentrantError'):
            core.refresh()
        self.assertEqual(string_calls, [])
        self.assertNotIn('MOTION', events)
        self.assertIsNone(core.active_command)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)

    def test_state_query_failure_within_stop_window_does_not_repeat_stop(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        backend.fail_state_query = True
        with self.assertRaises(ArmGatewayError):
            core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)

        clock.advance(0.75)
        with self.assertRaisesRegex(
                ArmGatewayError, 'STOP verification pending'):
            core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)

    def test_continuous_state_query_failure_retries_and_escalates(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        backend.fail_state_query = True

        with self.assertRaises(ArmGatewayError):
            core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)

        clock.advance(1.01)
        with self.assertRaisesRegex(ArmGatewayError, 'before timeout'):
            core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.stop_count, 1)
        with self.assertRaisesRegex(ArmGatewayError, 'retry throttled'):
            core.refresh()
        self.assertEqual(backend.stop_count, 1)

        clock.advance(0.25)
        with self.assertRaises(ArmGatewayError):
            core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 2)

        clock.advance(1.01)
        with self.assertRaisesRegex(ArmGatewayError, 'before timeout'):
            core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        clock.advance(0.50)
        with self.assertRaises(ArmGatewayError):
            core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 3)

        clock.advance(1.01)
        with self.assertRaisesRegex(
                ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
            core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(backend.stop_count, 3)

    def test_nonfinite_stop_clock_escalates_without_sending_stop(self):
        core, backend, clock = ready_core()
        backend.moving = 1
        clock.now = math.nan
        with self.assertRaisesRegex(ArmGatewayError, 'non-finite clock'):
            core.request_stop('unsafe clock', core.session_id)
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(backend.stop_count, 0)

    def test_nonfinite_refresh_clock_fails_closed_before_state_acceptance(self):
        backend = FakeArmBackend()
        clock = ManualClock()
        clock.now = math.nan
        core = ArmGatewayCore(backend, make_policy(True), clock=clock)
        with self.assertRaisesRegex(ArmGatewayError, 'state timing clock'):
            core.refresh()
        self.assertIsNone(core.snapshot)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.sent_angles, [])

    def test_nonfinite_motion_clock_rejects_without_sending_command(self):
        core, backend, clock = ready_core()
        clock.now = math.nan
        with self.assertRaisesRegex(MotionRejected, 'motion timing clock'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-1', core.session_id)
        self.assertEqual(backend.sent_angles, [])
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)

    def test_backward_clock_during_motion_escalates_not_success(self):
        core, backend, clock = ready_core()
        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 0
        backend.angles = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        clock.now = command.started_at - 0.01
        with self.assertRaisesRegex(ArmGatewayError, 'moved backwards'):
            core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(backend.stop_count, 0)
        self.assertIsNone(core.last_result)

    def test_unverifiable_stop_snapshots_reach_physical_escalation(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        core.request_stop('operator STOP', core.session_id)
        self.assertEqual(backend.stop_count, 1)

        backend.connected = 0
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        clock.advance(0.25)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 2)
        clock.advance(1.01)
        core.refresh()
        clock.advance(0.50)
        core.refresh()
        self.assertEqual(backend.stop_count, 3)
        clock.advance(1.01)
        core.refresh()
        self.assertTrue(core.physical_stop_required)

    def test_nonfinite_runtime_retry_delay_sends_once_then_escalates(self):
        policy = make_policy(True)
        backend = FakeArmBackend()
        core = ArmGatewayCore(backend, policy, clock=ManualClock())
        core.refresh()
        object.__setattr__(
            core._policy, 'stop_retry_interval_s', math.inf)
        with self.assertRaisesRegex(ArmGatewayError, 'retry delay'):
            core.request_stop('invalid runtime delay', core.session_id)
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(core._stop_attempt_count, 1)
        self.assertEqual(backend.stop_count, 1)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.request_stop(
                'software retry forbidden', core.session_id)
        self.assertEqual(backend.stop_count, 1)

    def test_nonfinite_runtime_retry_deadline_sends_once_then_escalates(self):
        policy = replace(
            make_policy(True),
            stop_retry_interval_s=1e308,
            stop_retry_backoff_factor=1.0,
        )
        backend = FakeArmBackend()
        clock = ManualClock()
        core = ArmGatewayCore(backend, policy, clock=clock)
        core.refresh()
        clock.now = 1e308
        with self.assertRaisesRegex(ArmGatewayError, 'retry deadline'):
            core.request_stop('overflowing deadline', core.session_id)
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(core._stop_attempt_count, 1)
        self.assertEqual(backend.stop_count, 1)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.request_stop(
                'software retry forbidden', core.session_id)
        self.assertEqual(backend.stop_count, 1)

    def test_stop_return_is_not_stationary_confirmation(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        self.assertTrue(core.request_stop(
            'operator cancel', core.session_id))
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(core.state, GatewayState.STOPPING)

        backend.moving = 0
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertIn('stationary state verified', core.fault_reason)

    def test_same_timestamp_samples_cannot_verify_stationary_state(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        core.request_stop('operator cancel', core.session_id)
        backend.moving = 0
        for _ in range(10):
            core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertFalse(core._fault_stationary_verified)

    def test_command_timeout_requests_stop(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        clock.advance(2.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('command timeout', core.fault_reason)
        self.assertIn('attempt 1/3', core.fault_reason)

    def test_stop_timeout_latches_fault(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        core.request_stop('timeout verification', core.session_id)
        backend.moving = 1
        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertIn('not verified before timeout', core.fault_reason)

    def test_fault_latched_stop_is_available_and_requires_verification(self):
        core, backend, _ = ready_core()
        core._latch_fault('original fault')
        backend.moving = 1
        self.assertTrue(core.request_stop(
            'operator STOP', core.session_id))
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('original fault', core.fault_reason)
        self.assertIn('operator STOP', core.fault_reason)

    def test_fault_snapshot_with_motion_attempts_stop(self):
        core, backend, _ = ready_core()
        core._latch_fault('original fault')
        backend.moving = 1
        backend.error_code = 16
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)

    def test_fault_latched_healthy_motion_attempts_stop(self):
        core, backend, _ = ready_core()
        core._latch_fault('original fault')
        backend.moving = 1
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('unexpected motion', core.fault_reason)

    def test_motion_after_stop_timeout_triggers_another_stop_attempt(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        core.request_stop('first STOP', core.session_id)
        self.assertEqual(backend.stop_count, 1)
        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.stop_count, 1)
        clock.advance(0.25)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 2)
        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.stop_count, 2)
        clock.advance(0.50)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 3)

    def test_motion_safety_resolution_stays_unresolved_until_stationary(self):
        core, backend, clock = ready_core()
        command = core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.moving = 1
        core.request_stop('operator STOP', core.session_id)
        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.motion_safety_unresolved)

        backend.moving = 0
        backend.angles = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        clock.advance(0.25)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.motion_safety_unresolved)
        clock.advance(0.01)
        core.refresh()
        self.assertTrue(core.motion_safety_unresolved)
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertFalse(core.motion_safety_unresolved)
        self.assertEqual(core.last_result.command_id, command.command_id)
        self.assertFalse(core.last_result.success)

    def test_action_boundary_shutdown_escalates_unresolved_motion(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        self.assertTrue(core.fail_closed_action_boundary(
            'ROS shutdown during active arm action'))
        self.assertTrue(core.physical_stop_required)
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.stop_count, 1)
        self.assertIn('ROS shutdown', core.fault_reason)

    def test_stop_retries_use_backoff_and_escalate_after_limit(self):
        core, backend, clock = ready_core()
        backend.moving = 1
        self.assertTrue(core.request_stop(
            'first STOP', core.session_id))
        self.assertEqual(backend.stop_count, 1)

        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.stop_count, 1)
        clock.advance(0.25)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 2)

        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertEqual(backend.stop_count, 2)
        clock.advance(0.50)
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        self.assertEqual(backend.stop_count, 3)

        clock.advance(1.01)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.physical_stop_required)
        self.assertIn('PHYSICAL EMERGENCY STOP', core.fault_reason)
        self.assertIn('POWER ISOLATION REQUIRED', core.fault_reason)

        clock.advance(100.0)
        core.refresh()
        self.assertEqual(backend.stop_count, 3)
        self.assertTrue(core.physical_stop_required)

    def test_physical_stop_escalation_cannot_be_acknowledged_or_rearmed(self):
        policy = replace(
            make_policy(True),
            max_stop_attempts=1,
            stop_retry_interval_s=0.10,
        )
        backend = FakeArmBackend()
        clock = ManualClock()
        core = ArmGatewayCore(backend, policy, clock=clock)
        core.refresh()
        backend.moving = 1
        core.request_stop('single STOP', core.session_id)
        clock.advance(1.01)
        core.refresh()
        self.assertTrue(core.physical_stop_required)

        backend.moving = 0
        for _ in range(3):
            core.refresh()
            clock.advance(0.11)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.acknowledge_local_fault(
                'manual-review-1', core.session_id)
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.request_stop(
                'software retry forbidden', core.session_id)
        core.state = GatewayState.READY
        with self.assertRaisesRegex(
                MotionRejected, 'PHYSICAL EMERGENCY STOP'):
            core.command_named_joint_pose(
                'inspection', 5, 'manual-review-1', core.session_id)
        self.assertEqual(backend.stop_count, 1)

    def test_verified_stop_ack_resets_attempt_budget(self):
        core, backend, clock = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        core.request_stop('operator STOP', core.session_id)
        self.assertEqual(core._stop_attempt_count, 1)
        backend.moving = 0
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(core.acknowledge_local_fault(
            'manual-review-1', core.session_id))
        self.assertEqual(core._stop_attempt_count, 0)
        self.assertIsNone(core._next_stop_attempt_at)

        core.command_named_joint_pose(
            'inspection', 5, 'auth-2', core.session_id)
        backend.moving = 1
        self.assertTrue(core.request_stop(
            'second operator STOP', core.session_id))
        self.assertEqual(core._stop_attempt_count, 1)

    def test_close_attempts_stop_when_command_may_be_active(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        with self.assertRaises(ArmGatewayError) as raised:
            core.close()
        detail = str(raised.exception)
        self.assertIn('stationary state is unverified', detail)
        self.assertIn('PHYSICAL EMERGENCY STOP', detail)
        self.assertEqual(backend.stop_count, 1)
        self.assertTrue(backend.closed)
        self.assertEqual(backend.close_count, 1)
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertIsNone(core.active_command)
        self.assertTrue(core.physical_stop_required)

        core.close()
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 1)

    def test_close_respects_stop_retry_throttle(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        core.request_stop('operator STOP', core.session_id)
        self.assertEqual(backend.stop_count, 1)

        with self.assertRaisesRegex(
                ArmGatewayError, 'retry throttled.*unverified'):
            core.close()
        self.assertEqual(backend.stop_count, 1)
        self.assertTrue(backend.closed)
        self.assertEqual(core.state, GatewayState.CLOSED)

    def test_close_does_not_exceed_stop_attempt_limit(self):
        policy = replace(make_policy(True), max_stop_attempts=1)
        backend = FakeArmBackend()
        core = ArmGatewayCore(backend, policy, clock=ManualClock())
        core.refresh()
        backend.moving = 1
        core.request_stop('single STOP', core.session_id)
        self.assertEqual(backend.stop_count, 1)

        with self.assertRaisesRegex(
                ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
            core.close()
        self.assertEqual(backend.stop_count, 1)
        self.assertTrue(core.physical_stop_required)
        self.assertTrue(backend.closed)
        self.assertEqual(core.state, GatewayState.CLOSED)

    def test_close_after_physical_escalation_skips_software_stop(self):
        policy = replace(make_policy(True), max_stop_attempts=1)
        backend = FakeArmBackend()
        clock = ManualClock()
        core = ArmGatewayCore(backend, policy, clock=clock)
        core.refresh()
        backend.moving = 1
        core.request_stop('single STOP', core.session_id)
        clock.advance(1.01)
        core.refresh()
        self.assertTrue(core.physical_stop_required)

        with self.assertRaisesRegex(
                ArmGatewayError, 'PHYSICAL EMERGENCY STOP'):
            core.close()
        self.assertEqual(backend.stop_count, 1)
        self.assertTrue(backend.closed)
        self.assertEqual(core.state, GatewayState.CLOSED)

    def test_close_reports_stop_failure_but_still_closes(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.fail_stop = True
        with self.assertRaisesRegex(ArmGatewayError, 'shutdown STOP failed'):
            core.close()
        self.assertTrue(backend.closed)
        self.assertEqual(core.state, GatewayState.CLOSED)

    def test_close_aggregates_stop_and_transport_close_failures(self):
        core, backend, _ = ready_core()
        core.command_named_joint_pose(
            'inspection', 5, 'auth-1', core.session_id)
        backend.fail_stop = True
        backend.fail_close = True
        with self.assertRaises(ArmGatewayError) as raised:
            core.close()
        self.assertIn('shutdown STOP failed', str(raised.exception))
        self.assertIn('backend close failed', str(raised.exception))
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 1)
        self.assertEqual(core.state, GatewayState.CLOSED)
        self.assertIsNone(core.active_command)

        with self.assertRaisesRegex(
                ArmGatewayError, 'backend close failed'):
            core.close()
        self.assertEqual(backend.stop_count, 1)
        self.assertEqual(backend.close_count, 2)
        with self.assertRaisesRegex(ArmGatewayError, 'gateway is closed'):
            core.command_named_joint_pose(
                'inspection', 5, 'auth-2', core.session_id)

        backend.fail_close = False
        core.close()
        self.assertEqual(backend.close_count, 3)
        core.close()
        self.assertEqual(backend.close_count, 3)

    def test_local_fault_ack_never_calls_controller_clear(self):
        core, backend, clock = ready_core()
        core._latch_fault('test latch')
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        self.assertTrue(
            core.acknowledge_local_fault(
                'manual-review-1', core.session_id))
        self.assertEqual(core.state, GatewayState.READY)
        self.assertFalse(hasattr(backend, 'clear_error_information'))

    def test_fault_ack_requires_verified_stationary_state(self):
        core, backend, clock = ready_core()
        core._latch_fault('test latch')
        backend.moving = 1
        core.refresh()
        self.assertEqual(core.state, GatewayState.STOPPING)
        with self.assertRaisesRegex(MotionRejected, 'no local fault'):
            core.acknowledge_local_fault(
                'manual-review-1', core.session_id)

        backend.moving = 0
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()
        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertTrue(
            core.acknowledge_local_fault(
                'manual-review-1', core.session_id))

    def test_slow_ack_validator_cannot_clear_with_an_expired_snapshot(self):
        validator_clock = {}

        def slow_ack_validator(value, purpose, session_id):
            if purpose == 'ack':
                validator_clock['clock'].advance(0.30)
            return allow_test_authorization(value, purpose, session_id)

        core, backend, clock = ready_core(
            authorization_validator=slow_ack_validator)
        validator_clock['clock'] = clock
        core._latch_fault('test latch')
        core.refresh()
        core.refresh()
        clock.advance(0.11)
        core.refresh()

        with self.assertRaisesRegex(
                MotionRejected, 'fresh stationary controller state'):
            core.acknowledge_local_fault(
                'slow-ack-auth', core.session_id)

        self.assertEqual(core.state, GatewayState.FAULT_LATCHED)
        self.assertNotIn('slow-ack-auth', core._used_authorization_ids)
        self.assertFalse(backend.closed)

    def test_close_is_idempotent(self):
        core, backend, _ = ready_core()
        core.close()
        core.close()
        self.assertTrue(backend.closed)
        self.assertEqual(core.state, GatewayState.CLOSED)


if __name__ == '__main__':
    unittest.main()
