import ast
import math
import unittest
from pathlib import Path

from limo_cleanup_executor.arm_backends import (
    ArmBackendError,
    DryRunArmBackend,
    PymycobotArmBackend,
    create_arm_backend,
)


MODULE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_executor' / 'arm_backends.py')


class ManualClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeMyCobot280:
    def __init__(
            self, port, baud, timeout=None, thread_lock=None):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.thread_lock = thread_lock
        self.closed = False
        self.reference_frame = 0
        self.end_type = 0
        self.fresh_mode = 0
        self.tool_reference = [0.0] * 6
        self.connected = 1
        self.power_on = 1
        self.error_code = 0
        self.servo_enabled = 1
        self.stop_result = 1
        self.calls = []
        self.close_count = 0

    def get_joint_min_angle(self, joint_id):
        return -170.0

    def get_joint_max_angle(self, joint_id):
        return 170.0

    def get_reference_frame(self):
        return self.reference_frame

    def get_end_type(self):
        return self.end_type

    def get_tool_reference(self):
        return list(self.tool_reference)

    def is_controller_connected(self):
        return self.connected

    def is_power_on(self):
        return self.power_on

    def is_moving(self):
        return 0

    def is_paused(self):
        return 0

    def get_error_information(self):
        return self.error_code

    def get_fresh_mode(self):
        return self.fresh_mode

    def is_all_servo_enable(self):
        return self.servo_enabled

    def get_angles(self):
        return [0.0] * 6

    def get_coords(self):
        return [100.0, 0.0, 200.0, 0.0, 0.0, 0.0]

    def send_angles(self, target, speed):
        self.calls.append(('send_angles', list(target), speed))

    def send_coords(self, target, speed, mode):
        self.calls.append(('send_coords', list(target), speed, mode))

    def stop(self):
        self.calls.append(('stop',))
        return self.stop_result

    def close(self):
        self.close_count += 1
        self.closed = True


def hardware_arguments(**updates):
    arguments = {
        'port': '/dev/elephant',
        'baud': 115200,
        'expected_reference_frame': 0,
        'expected_end_type': 0,
        'expected_tool_reference': [0.0] * 6,
        'project_joint_limits_deg': ((-160.0, 160.0),) * 6,
        'required_fresh_mode': 0,
        'reviewed_max_speed_grade': 10,
        'approved_speed_grades': (5, 10),
        'project_tcp_bounds': (
            (50.0, 250.0),
            (-150.0, 150.0),
            (100.0, 350.0),
            (-180.0, 180.0),
            (-180.0, 180.0),
            (-180.0, 180.0),
        ),
        'allowed_tcp_modes': (0,),
        'acceleration_profile_id': 'reviewed-offline-profile-v1',
        'runtime_release_id': 'offline-release-v1',
        'release_manifest_sha256': 'a' * 64,
        'acceleration_profile_manifest_sha256': 'b' * 64,
        'acceleration_profile_runtime_release_id': 'offline-release-v1',
        'bounded_call_capability': True,
        'deadline_enforcement_capability': True,
        'native_cancel_capability': True,
        'independent_stop_channel_capability': True,
        'persistent_safety_latch_capability': True,
        'client_factory': FakeMyCobot280,
    }
    arguments.update(updates)
    return arguments


class DryRunArmBackendTest(unittest.TestCase):
    def test_module_uses_python38_syntax(self):
        ast.parse(
            MODULE.read_text(encoding='utf-8'),
            filename=str(MODULE),
            feature_version=(3, 8),
        )

    def test_dry_run_static_capability_binding_is_exact(self):
        self.assertEqual(
            DryRunArmBackend.SAFETY_CAPABILITIES,
            {
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
                'runtime_release_id': 'DRY_RUN_RELEASE_V1',
                'release_manifest_sha256': (
                    '0db63372cc24980532f650205fbb3537d02609ac62d52d76704e6dc7eaff9f83'),
                'acceleration_profile_id': 'DRY_RUN_ONLY',
                'acceleration_profile_manifest_sha256': (
                    'cfd2f55631a9406ac5191bb09c38c3f3f678b8788ace2920d4966b3b3d56260e'),
                'acceleration_profile_runtime_release_id': (
                    'DRY_RUN_RELEASE_V1'),
                'approved_speed_grades': (10,),
                'max_speed_grade': 10,
                'required_reference_frame': 0,
                'required_end_type': 0,
                'required_fresh_mode': 0,
            },
        )

    def test_module_has_no_vendor_import_or_unsafe_state_changing_calls(self):
        tree = ast.parse(MODULE.read_text(encoding='utf-8'))
        imported = []
        called = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or '')
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.append(node.func.attr)
        self.assertFalse(any(
            name == 'pymycobot' or name.startswith('pymycobot.')
            for name in imported))
        forbidden_calls = {
            '__import__',
            'import_module',
            'open',
            'power_on',
            'focus_servo',
            'focus_all_servos',
            'clear_error_information',
            'resume',
            'release_servo',
            'release_all_servos',
        }
        self.assertEqual(forbidden_calls.intersection(called), set())

    def test_dry_run_joint_motion_completes_in_memory(self):
        clock = ManualClock()
        backend = DryRunArmBackend(
            motion_duration_s=0.2, clock=clock)
        target = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        backend.send_angles(target, 5)
        self.assertEqual(backend.is_moving(), 1)
        self.assertEqual(backend.get_angles(), [0.0] * 6)
        clock.advance(0.2)
        self.assertEqual(backend.is_moving(), 0)
        self.assertEqual(backend.get_angles(), target)

    def test_stop_does_not_jump_to_commanded_target(self):
        clock = ManualClock()
        backend = DryRunArmBackend(
            motion_duration_s=1.0, clock=clock)
        backend.send_coords(
            [120.0, 0.0, 220.0, 0.0, 0.0, 0.0], 5, 0)
        backend.stop()
        clock.advance(2.0)
        self.assertEqual(backend.is_moving(), 0)
        self.assertEqual(
            backend.get_coords(),
            [100.0, 0.0, 200.0, 0.0, 0.0, 0.0],
        )

    def test_factory_refuses_hardware_backend(self):
        with self.assertRaisesRegex(ArmBackendError, 'not released'):
            create_arm_backend('pymycobot')

    def test_closed_backend_rejects_queries(self):
        backend = DryRunArmBackend()
        backend.close()
        with self.assertRaisesRegex(ArmBackendError, 'closed'):
            backend.get_angles()

    def test_initial_vectors_must_be_finite(self):
        with self.assertRaisesRegex(ValueError, 'finite numbers'):
            DryRunArmBackend(initial_angles=[math.nan] + [0.0] * 5)
        with self.assertRaisesRegex(ValueError, 'finite numbers'):
            DryRunArmBackend(
                initial_tcp_pose=[100.0, 0.0, math.inf, 0.0, 0.0, 0.0])

    def test_motion_duration_must_be_finite(self):
        for value in (math.nan, math.inf, -1.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'finite'):
                    DryRunArmBackend(motion_duration_s=value)

    def test_dry_run_constructor_does_not_evaluate_clock_truthiness(self):
        calls = []

        class ActiveClock:
            def __bool__(self):
                calls.append('bool')
                raise AssertionError('truthiness must not be evaluated')

            def __call__(self):
                return 100.0

        clock = ActiveClock()
        backend = DryRunArmBackend(clock=clock)
        self.assertIs(backend._clock, clock)
        self.assertEqual(calls, [])

    def test_numeric_subclasses_are_rejected_without_callbacks(self):
        calls = []

        class ActiveFloat(float):
            def __float__(value):
                calls.append('float')
                return float.__float__(value)

        class ActiveInt(int):
            def __le__(value, other):
                calls.append('le')
                return int.__le__(value, other)

        with self.assertRaises(ValueError):
            DryRunArmBackend(motion_duration_s=ActiveFloat(0.2))
        arguments = hardware_arguments(
            baud=ActiveInt(115200),
            client_factory=FakeMyCobot280,
        )
        with self.assertRaises(ArmBackendError):
            PymycobotArmBackend(**arguments)
        self.assertEqual(calls, [])

    def test_hardware_adapter_contract_runs_with_fake_client_only(self):
        calls = []

        def factory(*args, **kwargs):
            calls.append((args, kwargs))
            return FakeMyCobot280(*args, **kwargs)

        with self.assertRaisesRegex(
                ArmBackendError, 'shared transport lock'):
            PymycobotArmBackend(**hardware_arguments(
                client_factory=factory))
        self.assertEqual(calls, [])

    def test_hardware_adapter_rejects_unstable_port_before_factory(self):
        called = []

        def factory(*args, **kwargs):
            called.append((args, kwargs))
            return FakeMyCobot280(*args, **kwargs)

        with self.assertRaisesRegex(ArmBackendError, 'shared transport lock'):
            PymycobotArmBackend(
                **hardware_arguments(
                    port='/dev/ttyUSB0', client_factory=factory)
            )
        self.assertEqual(called, [])

    def test_hardware_adapter_rejects_active_port_subclass_before_factory(self):
        calls = []

        class ActivePort(str):
            def __eq__(value, other):
                calls.append('eq')
                return True

            def __ne__(value, other):
                calls.append('ne')
                return False

        factory_calls = []

        def factory(*args, **kwargs):
            factory_calls.append((args, kwargs))
            return FakeMyCobot280(*args, **kwargs)

        with self.assertRaisesRegex(ArmBackendError, 'shared transport lock'):
            PymycobotArmBackend(**hardware_arguments(
                port=ActivePort('/dev/elephant'), client_factory=factory))
        self.assertEqual(calls, [])
        self.assertEqual(factory_calls, [])

    def test_hardware_adapter_requires_injected_factory(self):
        with self.assertRaisesRegex(
                ArmBackendError, 'explicit callable client_factory'):
            PymycobotArmBackend(
                **hardware_arguments(client_factory=None)
            )
        with self.assertRaisesRegex(
                ArmBackendError, 'explicit callable client_factory'):
            PymycobotArmBackend(
                **hardware_arguments(client_factory='not-callable')
            )

    def test_hardware_adapter_requires_reviewed_tool_limits_and_fresh_mode(self):
        required = (
            'expected_tool_reference',
            'project_joint_limits_deg',
            'required_fresh_mode',
            'reviewed_max_speed_grade',
            'project_tcp_bounds',
            'allowed_tcp_modes',
            'acceleration_profile_id',
            'runtime_release_id',
            'release_manifest_sha256',
            'acceleration_profile_manifest_sha256',
            'acceleration_profile_runtime_release_id',
            'bounded_call_capability',
            'deadline_enforcement_capability',
            'native_cancel_capability',
            'independent_stop_channel_capability',
            'persistent_safety_latch_capability',
            'client_factory',
        )
        complete = hardware_arguments()
        for missing in required:
            with self.subTest(missing=missing):
                arguments = dict(complete)
                arguments.pop(missing)
                with self.assertRaises(TypeError):
                    PymycobotArmBackend(**arguments)

    def test_hardware_adapter_refuses_before_factory_for_all_legacy_inputs(self):
        class WrongFrame(FakeMyCobot280):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.reference_frame = 1

        class WrongFreshMode(FakeMyCobot280):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fresh_mode = 1

        class BooleanFrame(FakeMyCobot280):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.reference_frame = False

        class BooleanLimit(FakeMyCobot280):
            def get_joint_min_angle(self, joint_id):
                return False

        cases = (
            (
                {'client_factory': WrongFrame},
                'reference frame mismatch',
            ),
            (
                {'client_factory': WrongFreshMode},
                'fresh mode mismatch',
            ),
            (
                {'client_factory': BooleanFrame},
                'reference frame mismatch',
            ),
            (
                {'client_factory': BooleanLimit},
                'controller joint limits must be numeric',
            ),
            (
                {
                    'client_factory': FakeMyCobot280,
                    'expected_tool_reference': [1.0] * 6,
                },
                'tool reference mismatch',
            ),
            (
                {
                    'client_factory': FakeMyCobot280,
                    'project_joint_limits_deg': ((-180.0, 180.0),) * 6,
                },
                'strict subset',
            ),
            (
                {
                    'client_factory': FakeMyCobot280,
                    'project_joint_limits_deg': ((-170.0, 160.0),) * 6,
                },
                'strict subset',
            ),
            (
                {
                    'client_factory': FakeMyCobot280,
                    'project_joint_limits_deg': ((-160.0, 170.0),) * 6,
                },
                'strict subset',
            ),
        )
        for updates, expected in cases:
            with self.subTest(expected=expected):
                arguments = hardware_arguments()
                arguments.update(updates)
                with self.assertRaisesRegex(
                        ArmBackendError, 'shared transport lock'):
                    PymycobotArmBackend(**arguments)

    def test_hardware_adapter_rejects_missing_capability_and_release_binding(self):
        cases = (
            ({'bounded_call_capability': False}, 'bounded_call_capability'),
            ({'bounded_call_capability': 1}, 'bounded_call_capability'),
            ({'deadline_enforcement_capability': False},
             'deadline_enforcement_capability'),
            ({'deadline_enforcement_capability': 1},
             'deadline_enforcement_capability'),
            ({'native_cancel_capability': False},
             'native_cancel_capability'),
            ({'native_cancel_capability': 1},
             'native_cancel_capability'),
            ({'independent_stop_channel_capability': False},
             'independent_stop_channel_capability'),
            ({'persistent_safety_latch_capability': False},
             'persistent_safety_latch_capability'),
            ({'persistent_safety_latch_capability': 1},
             'persistent_safety_latch_capability'),
            ({'runtime_release_id': ''}, 'runtime_release_id'),
            ({'acceleration_profile_id': ''}, 'acceleration_profile_id'),
            ({'reviewed_max_speed_grade': 0},
             'reviewed_max_speed_grade'),
            ({'reviewed_max_speed_grade': True},
             'reviewed_max_speed_grade'),
            ({'approved_speed_grades': ()}, 'approved_speed_grades'),
            ({'approved_speed_grades': [5, 10]}, 'approved_speed_grades'),
            ({'approved_speed_grades': (5, 5)}, 'approved_speed_grades'),
            ({'approved_speed_grades': (10, 5)}, 'approved_speed_grades'),
            ({'approved_speed_grades': (5, 11)}, 'approved_speed_grades'),
            ({'approved_speed_grades': (True,)}, 'approved_speed_grades'),
            ({'release_manifest_sha256': 'a' * 63},
             'release_manifest_sha256'),
            ({'release_manifest_sha256': 'A' * 64},
             'release_manifest_sha256'),
            ({'acceleration_profile_manifest_sha256': 'z' * 64},
             'acceleration_profile_manifest_sha256'),
            ({'acceleration_profile_manifest_sha256': 'a' * 64},
             'must be different'),
            ({'acceleration_profile_runtime_release_id': 'stale-release'},
             'runtime release id mismatch'),
        )
        for updates, expected in cases:
            with self.subTest(updates=updates):
                factory_calls = []

                def factory(*args, **kwargs):
                    factory_calls.append((args, kwargs))
                    return FakeMyCobot280(*args, **kwargs)

                arguments = hardware_arguments(client_factory=factory)
                arguments.update(updates)
                with self.assertRaisesRegex(ArmBackendError, expected):
                    PymycobotArmBackend(**arguments)
                self.assertEqual(factory_calls, [])

    def test_hardware_adapter_rejects_active_config_subclasses_before_factory(self):
        calls = []

        class ActiveString(str):
            def strip(value, *args, **kwargs):
                calls.append('strip')
                return str.strip(value, *args, **kwargs)

        class ActiveList(list):
            def __iter__(value):
                calls.append('iter')
                return list.__iter__(value)

        cases = (
            {'acceleration_profile_id': ActiveString('reviewed-profile')},
            {'allowed_tcp_modes': ActiveList([0])},
            {'expected_tool_reference': ActiveList([0.0] * 6)},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                factory_calls = []

                def factory(*args, **kwargs):
                    factory_calls.append((args, kwargs))
                    return FakeMyCobot280(*args, **kwargs)

                arguments = hardware_arguments(client_factory=factory)
                arguments.update(updates)
                with self.assertRaises(ArmBackendError):
                    PymycobotArmBackend(**arguments)
                self.assertEqual(factory_calls, [])
        self.assertEqual(calls, [])

    def test_factory_rejects_active_backend_name_without_strip(self):
        calls = []

        class ActiveString(str):
            def strip(value, *args, **kwargs):
                calls.append('strip')
                return str.strip(value, *args, **kwargs)

        with self.assertRaisesRegex(ArmBackendError, 'unsupported'):
            create_arm_backend(ActiveString('dry_run'))
        self.assertEqual(calls, [])

    def test_hardware_placeholder_has_no_operational_methods(self):
        for name in (
                'send_angles', 'send_coords', 'stop', 'close',
                'is_controller_connected', 'get_angles'):
            self.assertFalse(hasattr(PymycobotArmBackend, name), name)

    def test_hardware_placeholder_has_no_timeout_thread_or_shared_lock(self):
        source = MODULE.read_text(encoding='utf-8')
        class_source = source[source.index('class PymycobotArmBackend:'):]
        self.assertNotIn('threading.Thread', class_source)
        self.assertNotIn('RLock(', class_source)
        self.assertNotIn('client_factory(', class_source)
        self.assertIn('shared transport lock', class_source)

    def test_hardware_placeholder_requires_factory_and_exact_release_profile(self):
        source = MODULE.read_text(encoding='utf-8')
        class_source = source[source.index('class PymycobotArmBackend:'):]
        for token in (
                'callable(client_factory)',
                'acceleration_profile_id',
                'reviewed_max_speed_grade',
                'approved_speed_grades',
                'runtime_release_id',
                'release_manifest_sha256',
                'acceleration_profile_manifest_sha256'):
            self.assertIn(token, class_source)
        self.assertNotIn('client_factory or', class_source)
        self.assertNotIn('__import__(', class_source)
        self.assertNotIn('import_module(', class_source)

    def test_dry_run_capabilities_are_static_not_executable_discovery(self):
        source = MODULE.read_text(encoding='utf-8')
        dry_run_source = source[
            source.index('class DryRunArmBackend:'):
            source.index('class PymycobotArmBackend:')]
        self.assertIn('SAFETY_CAPABILITIES = {', dry_run_source)
        self.assertNotIn('def safety_capabilities', dry_run_source)

if __name__ == '__main__':
    unittest.main()
