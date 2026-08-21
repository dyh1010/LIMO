"""
Backends for the myCobot arm gateway.

Only the deterministic dry-run backend is currently released. It never
imports pymycobot and never opens a device.  The hardware backend name is
reserved so configuration cannot silently fall through to serial access.
"""

import math
import time


class ArmBackendError(RuntimeError):
    """Raised when a backend cannot safely satisfy a gateway operation."""


class DryRunArmBackend:
    """In-memory six-axis arm used by offline and ROS contract tests."""

    # Static data, not a capability method: the construction gate must never
    # execute adapter code merely to discover whether the adapter is safe.
    SAFETY_CAPABILITIES = {
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
        'acceleration_profile_runtime_release_id': 'DRY_RUN_RELEASE_V1',
        'approved_speed_grades': (10,),
        'max_speed_grade': 10,
        'required_reference_frame': 0,
        'required_end_type': 0,
        'required_fresh_mode': 0,
    }

    def __init__(
            self,
            initial_angles=None,
            initial_tcp_pose=None,
            motion_duration_s=0.20,
            clock=None):
        self._clock = time.monotonic if clock is None else clock
        if type(motion_duration_s) not in (int, float):
            raise ValueError(
                'motion_duration_s must be a built-in number')
        self._motion_duration_s = float(motion_duration_s)
        if (
                not math.isfinite(self._motion_duration_s)
                or self._motion_duration_s < 0.0):
            raise ValueError(
                'motion_duration_s must be finite and non-negative')
        self._angles = list(initial_angles or [0.0] * 6)
        self._tcp_pose = list(
            initial_tcp_pose
            or [100.0, 0.0, 200.0, 0.0, 0.0, 0.0])
        if len(self._angles) != 6 or len(self._tcp_pose) != 6:
            raise ValueError('dry-run arm vectors must contain six values')
        if not all(
                type(value) in (int, float)
                and math.isfinite(float(value))
                for value in self._angles + self._tcp_pose):
            raise ValueError('dry-run arm vectors must be finite numbers')
        self._target_angles = None
        self._target_tcp_pose = None
        self._complete_at = None
        self._moving = 0
        self._paused = 0
        self._closed = False

    def _ensure_open(self):
        if self._closed:
            raise ArmBackendError('dry-run backend is closed')

    def _update(self):
        self._ensure_open()
        if (
                self._moving == 1
                and self._paused == 0
                and self._complete_at is not None
                and self._clock() >= self._complete_at):
            if self._target_angles is not None:
                self._angles = list(self._target_angles)
            if self._target_tcp_pose is not None:
                self._tcp_pose = list(self._target_tcp_pose)
            self._target_angles = None
            self._target_tcp_pose = None
            self._complete_at = None
            self._moving = 0

    def is_controller_connected(self):
        self._update()
        return 1

    def is_power_on(self):
        self._update()
        return 1

    def is_moving(self):
        self._update()
        return self._moving

    def is_paused(self):
        self._update()
        return self._paused

    def get_error_information(self):
        self._update()
        return 0

    def get_fresh_mode(self):
        self._update()
        return 0

    def is_all_servo_enable(self):
        self._update()
        return 1

    def get_angles(self):
        self._update()
        return list(self._angles)

    def get_coords(self):
        self._update()
        return list(self._tcp_pose)

    def get_reference_frame(self):
        self._update()
        return 0

    def get_end_type(self):
        self._update()
        return 0

    def send_angles(self, target, speed):
        self._ensure_open()
        self._target_angles = list(target)
        self._target_tcp_pose = None
        self._start_motion()

    def send_coords(self, target, speed, mode):
        self._ensure_open()
        self._target_tcp_pose = list(target)
        self._target_angles = None
        self._start_motion()

    def _start_motion(self):
        self._paused = 0
        if self._motion_duration_s == 0.0:
            self._moving = 1
            self._complete_at = self._clock()
            self._update()
            return
        self._moving = 1
        self._complete_at = self._clock() + self._motion_duration_s

    def stop(self):
        self._ensure_open()
        self._target_angles = None
        self._target_tcp_pose = None
        self._complete_at = None
        self._moving = 0
        self._paused = 0

    def close(self):
        self._closed = True
        self._moving = 0
        self._target_angles = None
        self._target_tcp_pose = None
        self._complete_at = None


class PymycobotArmBackend:
    """Fail-closed placeholder for an unreleased vendor transport.

    Construction always fails before the injected factory is called.  The
    reviewed vendor adapter used one shared transport lock, so a blocked send
    could block STOP.  Metadata or a Python timeout thread cannot repair that
    topology; release requires a genuinely bounded/cancellable call layer and
    an independently schedulable STOP channel with hash-bound evidence.
    """

    def __init__(
            self,
            port,
            baud,
            expected_reference_frame,
            expected_end_type,
            expected_tool_reference,
            project_joint_limits_deg,
            required_fresh_mode,
            reviewed_max_speed_grade,
            approved_speed_grades,
            project_tcp_bounds,
            allowed_tcp_modes,
            acceleration_profile_id,
            runtime_release_id,
            release_manifest_sha256,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id,
            bounded_call_capability,
            deadline_enforcement_capability,
            native_cancel_capability,
            independent_stop_channel_capability,
            persistent_safety_latch_capability,
            client_factory):
        del port
        del baud
        del expected_reference_frame
        del expected_end_type
        del expected_tool_reference
        del project_joint_limits_deg
        del required_fresh_mode
        del project_tcp_bounds
        del allowed_tcp_modes
        if not callable(client_factory):
            raise ArmBackendError(
                'real backend DISABLED/BLOCKED: an explicit callable '
                'client_factory is required and no default import or device '
                'open is permitted')
        if bounded_call_capability is not True:
            raise ArmBackendError(
                'real backend DISABLED/BLOCKED: bounded_call_capability '
                'must be independently verified')
        if deadline_enforcement_capability is not True:
            raise ArmBackendError(
                'real backend DISABLED/BLOCKED: '
                'deadline_enforcement_capability must be independently '
                'verified')
        if native_cancel_capability is not True:
            raise ArmBackendError(
                'real backend DISABLED/BLOCKED: native_cancel_capability '
                'must prove transport-level cancellation; a Python timeout '
                'thread is insufficient')
        if independent_stop_channel_capability is not True:
            raise ArmBackendError(
                'real backend DISABLED/BLOCKED: '
                'independent_stop_channel_capability must be independently '
                'verified')
        if persistent_safety_latch_capability is not True:
            raise ArmBackendError(
                'real backend DISABLED/BLOCKED: '
                'persistent_safety_latch_capability must prove restart-safe '
                'physical-isolation-required persistence')
        self._require_release_binding(
            acceleration_profile_id,
            reviewed_max_speed_grade,
            approved_speed_grades,
            runtime_release_id,
            release_manifest_sha256,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id,
        )
        # The retired adapter design multiplexed ordinary traffic and STOP
        # through one transport lock.  Even affirmative metadata cannot turn
        # that topology into an independent safety channel.
        raise ArmBackendError(
            'real backend DISABLED/BLOCKED: the pymycobot adapter uses one '
            'shared transport lock and cannot prove bounded calls plus an '
            'independent STOP channel')

    @staticmethod
    def _require_release_binding(
            acceleration_profile_id,
            reviewed_max_speed_grade,
            approved_speed_grades,
            runtime_release_id,
            release_manifest_sha256,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id):
        if (
                type(acceleration_profile_id) is not str
                or not acceleration_profile_id
                or acceleration_profile_id
                != acceleration_profile_id.strip()):
            raise ArmBackendError(
                'acceleration_profile_id must be an exact non-empty string')
        if (
                type(reviewed_max_speed_grade) is not int
                or not 1 <= reviewed_max_speed_grade <= 100):
            raise ArmBackendError(
                'reviewed_max_speed_grade must be an exact integer in 1..100')
        if (
                type(approved_speed_grades) is not tuple
                or not approved_speed_grades
                or any(
                    type(grade) is not int
                    or not 1 <= grade <= reviewed_max_speed_grade
                    for grade in approved_speed_grades)
                or tuple(approved_speed_grades)
                != tuple(sorted(set(approved_speed_grades)))):
            raise ArmBackendError(
                'approved_speed_grades must be exact, unique, increasing '
                'integers within reviewed_max_speed_grade')
        values = (
            ('runtime_release_id', runtime_release_id),
            ('acceleration_profile_runtime_release_id',
             acceleration_profile_runtime_release_id),
        )
        for name, value in values:
            if (
                    type(value) is not str
                    or not value
                    or value != value.strip()):
                raise ArmBackendError(
                    '{} must be an exact non-empty string'.format(name))
        if acceleration_profile_runtime_release_id != runtime_release_id:
            raise ArmBackendError(
                'acceleration profile runtime release id mismatch')
        for name, value in (
                ('release_manifest_sha256', release_manifest_sha256),
                ('acceleration_profile_manifest_sha256',
                 acceleration_profile_manifest_sha256)):
            if (
                    type(value) is not str
                    or len(value) != 64
                    or any(character not in '0123456789abcdef'
                           for character in value)):
                raise ArmBackendError(
                    '{} must be an exact lowercase SHA-256'.format(name))
        if release_manifest_sha256 == acceleration_profile_manifest_sha256:
            raise ArmBackendError(
                'release and acceleration-profile manifest SHA-256 bindings '
                'must be different')



def create_arm_backend(name, **kwargs):
    """Construct only explicitly released no-hardware backends."""
    resolved = name if type(name) is str and name == name.strip() else ''
    if resolved == 'dry_run':
        return DryRunArmBackend(**kwargs)
    if resolved == 'pymycobot':
        raise ArmBackendError(
            'pymycobot arm backend is not released; hardware remains blocked')
    raise ArmBackendError(
        'unsupported arm backend: {}'.format(resolved or '<empty>'))
