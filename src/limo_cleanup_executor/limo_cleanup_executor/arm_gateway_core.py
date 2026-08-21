"""
Fail-closed control core for a future myCobot 280 M5 gateway.

This module deliberately contains no serial-port or ROS construction. A
caller must inject a backend, which makes the safety state machine testable
without importing pymycobot or touching robot hardware.
"""

import math
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


JOINT_COUNT = 6
TCP_FIELD_COUNT = 6
MOVE_J = 0
MOVE_L = 1

BACKEND_METHOD_DEADLINE_NAMES = frozenset((
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
))


class ArmGatewayError(RuntimeError):
    """Base error for rejected or failed arm gateway operations."""


class MotionRejected(ArmGatewayError):
    """Raised when a motion request does not pass the local safety policy."""


class _StopScheduleError(ValueError):
    """Internal STOP schedule failure carrying only a trusted literal."""

    _REASONS = (
        'derived STOP retry delay is invalid',
        'derived STOP retry delay is non-finite',
        'derived STOP retry deadline is non-finite',
    )

    def __init__(self, reason):
        resolved = (
            reason if type(reason) is str and reason in self._REASONS
            else self._REASONS[0]
        )
        self.reason = resolved
        super().__init__(resolved)


class GatewayState(str, Enum):
    """Locally enforced gateway states."""

    INITIALIZING = 'INITIALIZING'
    READY = 'READY'
    EXECUTING = 'EXECUTING'
    STOPPING = 'STOPPING'
    FAULT_LATCHED = 'FAULT_LATCHED'
    CLOSED = 'CLOSED'


@dataclass(frozen=True)
class ArmSnapshot:
    """One validated arm state sample."""

    observed_at: float
    connected: int
    power_on: int
    moving: int
    paused: int
    error_code: int
    fresh_mode: int
    servo_enabled: int
    angles_deg: tuple
    tcp_pose: tuple

    def motion_ready(self, now, max_age_s):
        """Return whether this sample is fresh and allows motion."""
        age = float(now) - self.observed_at
        return (
            0.0 <= age <= max_age_s
            and self.connected == 1
            and self.power_on == 1
            and self.moving == 0
            and self.paused == 0
            and self.error_code == 0
            and self.servo_enabled == 1
        )


@dataclass(frozen=True)
class ArmGatewayPolicy:
    """Static limits that cannot be relaxed by an action request."""

    permit_motion: bool
    max_speed_grade: int
    state_max_age_s: float
    command_timeout_s: float
    stop_timeout_s: float
    stable_samples_required: int
    stationary_dwell_s: float
    stationary_joint_tolerance_deg: float
    joint_tolerance_deg: float
    tcp_translation_tolerance_mm: float
    tcp_rotation_tolerance_deg: float
    joint_limits_deg: tuple
    tcp_bounds: tuple
    named_joint_poses: dict
    acceleration_profile_id: str
    runtime_release_id: str
    release_manifest_sha256: str
    acceleration_profile_manifest_sha256: str
    acceleration_profile_runtime_release_id: str
    expected_real_transport: bool = False
    approved_speed_grades: tuple = ()
    allowed_tcp_modes: tuple = (MOVE_J,)
    required_reference_frame: int = 0
    required_end_type: int = 0
    required_fresh_mode: int = 0
    max_stop_attempts: int = 3
    stop_retry_interval_s: float = 0.50
    stop_retry_backoff_factor: float = 2.0

    def validate(self):
        """Reject incomplete or internally inconsistent policies."""
        if type(self.permit_motion) is not bool:
            raise ValueError('permit_motion must be a boolean')
        if type(self.expected_real_transport) is not bool:
            raise ValueError('expected_real_transport must be a boolean')
        if (
                type(self.max_speed_grade) is not int
                or not 1 <= self.max_speed_grade <= 100):
            raise ValueError('max_speed_grade must be in 1..100')
        if (
                type(self.approved_speed_grades) is not tuple
                or not self.approved_speed_grades):
            raise ValueError(
                'approved speed grades must be an exact non-empty tuple')
        if any(
                type(grade) is not int
                or not 1 <= grade <= self.max_speed_grade
                for grade in self.approved_speed_grades):
            raise ValueError(
                'approved speed grades must be exact integers within the '
                'maximum')
        if (
                self.approved_speed_grades
                != tuple(sorted(set(self.approved_speed_grades)))):
            raise ValueError(
                'approved speed grades must be unique and strictly increasing')
        if not _positive_finite(self.state_max_age_s):
            raise ValueError('state_max_age_s must be positive')
        if not _positive_finite(self.command_timeout_s):
            raise ValueError('command_timeout_s must be positive')
        if not _positive_finite(self.stop_timeout_s):
            raise ValueError('stop_timeout_s must be positive')
        if (
                type(self.max_stop_attempts) is not int
                or not 1 <= self.max_stop_attempts <= 10):
            raise ValueError('max_stop_attempts must be in 1..10')
        if not _positive_finite(self.stop_retry_interval_s):
            raise ValueError('stop_retry_interval_s must be positive')
        if (
                not _finite(self.stop_retry_backoff_factor)
                or self.stop_retry_backoff_factor < 1.0):
            raise ValueError(
                'stop_retry_backoff_factor must be finite and at least 1')
        try:
            maximum_retry_delay = (
                float(self.stop_retry_interval_s)
                * float(self.stop_retry_backoff_factor) ** (
                    self.max_stop_attempts - 1)
            )
        except OverflowError as exc:
            raise ValueError(
                'derived STOP retry delay must be finite') from exc
        if not math.isfinite(maximum_retry_delay):
            raise ValueError('derived STOP retry delay must be finite')
        if (
                type(self.stable_samples_required) is not int
                or self.stable_samples_required < 2):
            raise ValueError('stable_samples_required must be at least 2')
        if not _positive_finite(self.stationary_dwell_s):
            raise ValueError('stationary_dwell_s must be positive')
        if not _positive_finite(self.stationary_joint_tolerance_deg):
            raise ValueError(
                'stationary_joint_tolerance_deg must be positive')
        if not _positive_finite(self.joint_tolerance_deg):
            raise ValueError('joint_tolerance_deg must be positive')
        if not _positive_finite(self.tcp_translation_tolerance_mm):
            raise ValueError(
                'tcp_translation_tolerance_mm must be positive')
        if not _positive_finite(self.tcp_rotation_tolerance_deg):
            raise ValueError('tcp_rotation_tolerance_deg must be positive')
        if (
                type(self.acceleration_profile_id) is not str
                or not self.acceleration_profile_id
                or self.acceleration_profile_id
                != self.acceleration_profile_id.strip()):
            raise ValueError(
                'an exact approved acceleration_profile_id is required')
        for name, value in (
                ('runtime_release_id', self.runtime_release_id),
                ('acceleration_profile_runtime_release_id',
                 self.acceleration_profile_runtime_release_id)):
            if (
                    type(value) is not str
                    or not value
                    or value != value.strip()):
                raise ValueError(
                    '{} must be an exact non-empty string'.format(name))
        if (
                self.acceleration_profile_runtime_release_id
                != self.runtime_release_id):
            raise ValueError(
                'acceleration profile runtime release id must exactly match '
                'runtime_release_id')
        for name, value in (
                ('release_manifest_sha256', self.release_manifest_sha256),
                ('acceleration_profile_manifest_sha256',
                 self.acceleration_profile_manifest_sha256)):
            if (
                    type(value) is not str
                    or len(value) != 64
                    or any(character not in '0123456789abcdef'
                           for character in value)):
                raise ValueError(
                    '{} must be an exact lowercase SHA-256'.format(name))
        if (
                self.release_manifest_sha256
                == self.acceleration_profile_manifest_sha256):
            raise ValueError(
                'release and acceleration-profile manifests must have '
                'different SHA-256 bindings')
        if (
                type(self.joint_limits_deg) is not tuple
                or len(self.joint_limits_deg) != JOINT_COUNT):
            raise ValueError(
                'joint limits must be an exact six-pair tuple')
        if (
                type(self.tcp_bounds) is not tuple
                or len(self.tcp_bounds) != TCP_FIELD_COUNT):
            raise ValueError(
                'TCP bounds must be an exact six-pair tuple')
        for pair in self.joint_limits_deg:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError(
                    'each joint limit must be an exact pair tuple')
            lower, upper = pair
            if not _finite(lower, upper) or lower >= upper:
                raise ValueError('each joint limit must be finite and ordered')
        for pair in self.tcp_bounds:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError(
                    'each TCP bound must be an exact pair tuple')
            lower, upper = pair
            if not _finite(lower, upper) or lower >= upper:
                raise ValueError('each TCP bound must be finite and ordered')
        if (
                type(self.allowed_tcp_modes) is not tuple
                or not self.allowed_tcp_modes):
            raise ValueError(
                'TCP modes must be an exact non-empty tuple')
        if any(type(mode) is not int or mode not in (MOVE_J, MOVE_L)
               for mode in self.allowed_tcp_modes):
            raise ValueError('TCP modes must contain only MOVE_J or MOVE_L')
        if (
                type(self.required_reference_frame) is not int
                or self.required_reference_frame not in (0, 1)):
            raise ValueError('required_reference_frame must be 0 or 1')
        if (
                type(self.required_end_type) is not int
                or self.required_end_type not in (0, 1)):
            raise ValueError('required_end_type must be 0 or 1')
        if (
                type(self.required_fresh_mode) is not int
                or self.required_fresh_mode not in (0, 1)):
            raise ValueError('required_fresh_mode must be 0 or 1')
        if type(self.named_joint_poses) is not dict:
            raise ValueError('named_joint_poses must be an exact dictionary')
        for name, target in self.named_joint_poses.items():
            if (
                    type(name) is not str
                    or not name
                    or name != name.strip()):
                raise ValueError(
                    'named pose names must be exact non-empty strings')
            self.validate_joint_target(target)

    def immutable_copy(self):
        """Return a deep immutable snapshot of validated policy inputs."""
        self.validate()
        snapshot = ArmGatewayPolicy(
            permit_motion=self.permit_motion,
            max_speed_grade=self.max_speed_grade,
            approved_speed_grades=tuple(self.approved_speed_grades),
            state_max_age_s=self.state_max_age_s,
            command_timeout_s=self.command_timeout_s,
            stop_timeout_s=self.stop_timeout_s,
            stable_samples_required=self.stable_samples_required,
            stationary_dwell_s=self.stationary_dwell_s,
            stationary_joint_tolerance_deg=(
                self.stationary_joint_tolerance_deg),
            joint_tolerance_deg=self.joint_tolerance_deg,
            tcp_translation_tolerance_mm=(
                self.tcp_translation_tolerance_mm),
            tcp_rotation_tolerance_deg=self.tcp_rotation_tolerance_deg,
            joint_limits_deg=tuple(
                tuple(pair) for pair in self.joint_limits_deg),
            tcp_bounds=tuple(tuple(pair) for pair in self.tcp_bounds),
            named_joint_poses={
                name: tuple(target)
                for name, target in self.named_joint_poses.items()
            },
            acceleration_profile_id=self.acceleration_profile_id,
            runtime_release_id=self.runtime_release_id,
            release_manifest_sha256=self.release_manifest_sha256,
            acceleration_profile_manifest_sha256=(
                self.acceleration_profile_manifest_sha256),
            acceleration_profile_runtime_release_id=(
                self.acceleration_profile_runtime_release_id),
            expected_real_transport=self.expected_real_transport,
            allowed_tcp_modes=tuple(self.allowed_tcp_modes),
            required_reference_frame=self.required_reference_frame,
            required_end_type=self.required_end_type,
            required_fresh_mode=self.required_fresh_mode,
            max_stop_attempts=self.max_stop_attempts,
            stop_retry_interval_s=self.stop_retry_interval_s,
            stop_retry_backoff_factor=self.stop_retry_backoff_factor,
        )
        snapshot.validate()
        object.__setattr__(
            snapshot,
            'named_joint_poses',
            MappingProxyType(snapshot.named_joint_poses),
        )
        return snapshot

    def validate_joint_target(self, target):
        """Validate a six-joint target against the software limits."""
        values = _numeric_tuple(target, JOINT_COUNT, 'joint target')
        for index, (value, limits) in enumerate(
                zip(values, self.joint_limits_deg), start=1):
            if not limits[0] <= value <= limits[1]:
                raise MotionRejected(
                    'joint {} target {} is outside {}..{}'.format(
                        index, value, limits[0], limits[1]))
        return values

    def validate_tcp_target(self, target):
        """Validate a six-field TCP target against configured bounds."""
        values = _numeric_tuple(target, TCP_FIELD_COUNT, 'TCP target')
        for index, (value, bounds) in enumerate(
                zip(values, self.tcp_bounds), start=1):
            if not bounds[0] <= value <= bounds[1]:
                raise MotionRejected(
                    'TCP field {} target {} is outside {}..{}'.format(
                        index, value, bounds[0], bounds[1]))
        return values


@dataclass(frozen=True)
class ActiveCommand:
    """A command accepted by the local gateway."""

    command_id: str
    session_id: str
    kind: str
    target: tuple
    speed_grade: int
    mode: int
    authorization_id: str
    started_at: float


@dataclass(frozen=True)
class CommandResult:
    """Final local result of an accepted command."""

    command_id: str
    success: bool
    detail: str
    finished_at: float


def _finite(*values):
    return all(
        type(value) in (int, float)
        and math.isfinite(float(value))
        for value in values
    )


def _positive_finite(value):
    return _finite(value) and float(value) > 0.0


def _safe_stop_reason(value, default):
    """Downgrade malformed metadata without ever delaying a safety STOP."""
    if type(value) is not str or not value or value != value.strip():
        return default
    return value


def _internal_text(value, default):
    """Normalize only trusted built-in diagnostic strings."""
    if type(value) is not str:
        return default
    resolved = value.strip()
    return resolved or default


def _numeric_tuple(value, length, name):
    if type(value) not in (list, tuple) or len(value) != length:
        raise ValueError('{} must contain {} values'.format(name, length))
    if not _finite(*value):
        raise ValueError('{} must contain only finite numbers'.format(name))
    return tuple(float(item) for item in value)


class ArmGatewayCore:
    """State machine around a narrowly scoped myCobot-like backend."""

    def __init__(
            self,
            backend,
            policy,
            clock=None,
            stop_clock=None,
            authorization_validator=None,
            command_id_factory=None,
            persistent_safety_latch=None):
        if type(policy) is not ArmGatewayPolicy:
            raise ValueError('policy must be an exact ArmGatewayPolicy')
        policy = policy.immutable_copy()
        self._lock = threading.RLock()
        self._stop_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._backend = backend
        self._policy = policy
        self._clock = time.monotonic if clock is None else clock
        self._stop_clock = self._clock if stop_clock is None else stop_clock
        self._authorization_validator = authorization_validator
        self._command_id_factory = (
            (lambda: uuid.uuid4().hex)
            if command_id_factory is None else command_id_factory)
        if persistent_safety_latch is not None:
            raise ValueError(
                'core-integrated persistent latch I/O is prohibited; use '
                'the independently bounded release supervisor contract')
        self.session_id = uuid.uuid4().hex
        self.state = GatewayState.INITIALIZING
        self.snapshot = None
        self.active_command = None
        self.last_result = None
        self.fault_reason = ''
        self._stable_samples = 0
        self._last_completion_observed_at = None
        self._completion_stable_since = None
        self._stop_started_at = None
        self._last_stopping_angles = None
        self._stopping_stable_since = None
        self._fault_stationary_verified = False
        self._fault_stable_samples = 0
        self._last_fault_angles = None
        self._fault_stable_since = None
        self._stop_attempt_count = 0
        self._last_stop_attempt_at = None
        self._next_stop_attempt_at = None
        self._physical_stop_required = False
        self._last_clock_value = None
        self._used_authorization_ids = set()
        self._issued_command_ids = set()
        self._motion_send_in_progress = False
        self._stop_send_epoch = None
        self._close_started = False
        self._backend_closed = False
        self._state_epoch = 0
        self._refresh_generation = 0
        self._external_call_state = threading.local()
        self._backend_capabilities = self._read_backend_capabilities()

    def refresh(self):
        """Read and validate one complete state sample."""
        self._reject_reentrant_public_operation('refresh')
        with self._lock:
            self._ensure_not_closed()
            refresh_epoch = self._state_epoch
            self._refresh_generation += 1
            refresh_generation = self._refresh_generation
        observed_at = self._read_clock(
            'state timing clock', expected_epoch=refresh_epoch)
        try:
            snapshot = ArmSnapshot(
                observed_at=observed_at,
                connected=self._call_external_method(
                    'backend is_controller_connected',
                    self._backend, 'is_controller_connected'),
                power_on=self._call_external_method(
                    'backend is_power_on', self._backend, 'is_power_on'),
                moving=self._call_external_method(
                    'backend is_moving', self._backend, 'is_moving'),
                paused=self._call_external_method(
                    'backend is_paused', self._backend, 'is_paused'),
                error_code=self._call_external_method(
                    'backend get_error_information',
                    self._backend, 'get_error_information'),
                fresh_mode=self._call_external_method(
                    'backend get_fresh_mode',
                    self._backend, 'get_fresh_mode'),
                servo_enabled=self._call_external_method(
                    'backend is_all_servo_enable',
                    self._backend, 'is_all_servo_enable'),
                angles_deg=_numeric_tuple(
                    self._call_external_method(
                        'backend get_angles', self._backend, 'get_angles'),
                    JOINT_COUNT, 'angles'),
                tcp_pose=_numeric_tuple(
                    self._call_external_method(
                        'backend get_coords', self._backend, 'get_coords'),
                    TCP_FIELD_COUNT, 'TCP pose'),
            )
        except Exception as exc:
            detail = 'state query failed: {}'.format(type(exc).__name__)
            with self._lock:
                self._require_refresh_commit_allowed(
                    refresh_epoch, refresh_generation, 'state query failure')
                self.snapshot = None
                stop_reason = self._handle_state_query_failure(
                    detail, observed_at)
                reported = self.fault_reason or detail
            if stop_reason:
                try:
                    sent = self.request_stop(stop_reason, self.session_id)
                except ArmGatewayError:
                    sent = False
                with self._lock:
                    if sent and self.state == GatewayState.STOPPING:
                        self.fault_reason = (
                            '{}; best-effort STOP sent on attempt {}/{}'
                            .format(
                                detail,
                                self._stop_attempt_count,
                                self._policy.max_stop_attempts,
                            ))
                    elif (
                            not sent
                            and self.state == GatewayState.FAULT_LATCHED
                            and 'retry throttled' not in self.fault_reason
                            and not self._physical_stop_required):
                        self.fault_reason = (
                            '{}; best-effort STOP retry throttled'.format(
                                detail))
                    reported = self.fault_reason or reported
            raise ArmGatewayError(reported) from exc

        stop_reason = ''
        with self._lock:
            self._require_refresh_commit_allowed(
                refresh_epoch, refresh_generation, 'state query result')
            self.snapshot = snapshot
            issue = self._snapshot_issue(snapshot)
            if (
                    issue
                    or (
                        type(snapshot.moving) is int
                        and snapshot.moving == 1)):
                # A newer unhealthy or moving sample invalidates all prior
                # post-STOP stationary credit before another thread can ACK.
                self._fault_stationary_verified = False
                self._fault_stable_samples = 0
                self._last_fault_angles = None
                self._fault_stable_since = None
            if issue:
                if (
                        self.state == GatewayState.EXECUTING
                        or (
                            type(snapshot.moving) is int
                            and snapshot.moving == 1
                            and self.state != GatewayState.STOPPING
                        )):
                    stop_reason = issue
                elif (
                        self.state == GatewayState.STOPPING
                        or self._motion_safety_unresolved()):
                    stop_reason = self._handle_unverifiable_snapshot(
                        issue, snapshot.observed_at)
                else:
                    self._latch_fault(issue)
            elif (
                    type(snapshot.moving) is int
                    and snapshot.moving == 1
                    and self.state not in (
                        GatewayState.EXECUTING,
                        GatewayState.STOPPING,
                    )):
                stop_reason = 'unexpected motion without an active command'
            elif self.state == GatewayState.INITIALIZING:
                self.state = GatewayState.READY
            elif self.state == GatewayState.EXECUTING:
                stop_reason = self._update_executing(snapshot)
            elif self.state == GatewayState.STOPPING:
                self._update_stopping(snapshot)
            elif self.state == GatewayState.FAULT_LATCHED:
                self._update_fault_latched(snapshot)
        if stop_reason:
            try:
                self.request_stop(stop_reason, self.session_id)
            except ArmGatewayError:
                pass
        return snapshot

    def snapshot_is_valid(self):
        """Return whether the latest sample is fresh and controller-healthy."""
        self._reject_reentrant_public_operation('snapshot_is_valid')
        with self._lock:
            if self.state == GatewayState.CLOSED or self.snapshot is None:
                return False
            validation_epoch = self._state_epoch
            snapshot = self.snapshot
        try:
            now = self._read_clock(
                'state freshness clock', expected_epoch=validation_epoch)
        except ArmGatewayError:
            return False
        with self._lock:
            if (
                    self._state_epoch != validation_epoch
                    or self.snapshot is not snapshot
                    or self.state == GatewayState.CLOSED):
                return False
            age = now - snapshot.observed_at
            return (
                _finite(age)
                and 0.0 <= age <= self._policy.state_max_age_s
                and not self._snapshot_issue(snapshot)
            )

    @property
    def physical_stop_required(self):
        """Return the process-lifetime physical safety escalation latch."""
        self._reject_reentrant_public_operation('physical_stop_required')
        with self._lock:
            return self._physical_stop_required

    @property
    def motion_safety_unresolved(self):
        """Return whether an Action must keep waiting for safe resolution."""
        self._reject_reentrant_public_operation('motion_safety_unresolved')
        with self._lock:
            return self._motion_safety_unresolved()

    def fail_closed_action_boundary(self, reason):
        """Escalate when an Action can no longer poll motion to resolution."""
        self._reject_reentrant_public_operation(
            'fail_closed_action_boundary')
        detail = _safe_stop_reason(
            reason,
            'action boundary ended before stationary verification',
        )
        with self._lock:
            self._ensure_not_closed()
            if not self._motion_safety_unresolved():
                return False
            self._escalate_physical_stop(
                '{}; stationary verification cannot continue'.format(
                    detail))
            can_attempt_stop = self._independent_stop_is_proven()
        if can_attempt_stop:
            try:
                self._send_uncredited_emergency_stop()
            except ArmGatewayError:
                pass
        return True

    def command_named_joint_pose(
            self, name, speed_grade, authorization_id,
            expected_session_id):
        """Send one configured named joint pose after all local checks."""
        self._reject_reentrant_public_operation('command_named_joint_pose')
        with self._lock:
            validation_epoch = self._state_epoch
            snapshot = self._capture_motion_ready_state(
                speed_grade, expected_session_id)
            if type(name) is not str or not name or name != name.strip():
                raise MotionRejected(
                    'joint pose name must be an exact non-empty string')
            resolved_name = name
            if resolved_name not in self._policy.named_joint_poses:
                raise MotionRejected(
                    'joint pose is not approved: {}'.format(
                        resolved_name or '<empty>'))
            target = self._policy.validate_joint_target(
                self._policy.named_joint_poses[resolved_name])
        try:
            motion_time = self._read_clock(
                'motion timing clock', expected_epoch=validation_epoch)
        except ArmGatewayError as exc:
            raise MotionRejected(str(exc)) from exc
        with self._lock:
            self._commit_motion_ready_state(
                snapshot, motion_time, speed_grade, expected_session_id,
                validation_epoch)
        resolved_authorization = self._require_authorization(
            authorization_id, 'motion')
        command = self._new_command(
            'named_joint_pose', target, speed_grade, MOVE_J,
            resolved_authorization, motion_time)
        try:
            final_motion_time = self._read_clock(
                'final motion freshness clock',
                expected_epoch=validation_epoch)
        except ArmGatewayError as exc:
            raise MotionRejected(str(exc)) from exc
        with self._lock:
            self._require_current_epoch(
                validation_epoch, 'joint command validation')
            self._commit_motion_ready_state(
                snapshot, final_motion_time, speed_grade, expected_session_id,
                validation_epoch)
            self._consume_command_identity(command)
            self._motion_send_in_progress = True
            send_epoch = self._state_epoch
        try:
            self._call_external_method(
                'backend send_angles', self._backend, 'send_angles',
                list(target), int(speed_grade))
        except Exception as exc:
            with self._lock:
                self._motion_send_in_progress = False
                if self._state_epoch == send_epoch:
                    send_failure_current = True
                    stop_epoch = self._advance_state_epoch()
                    self._stop_send_epoch = stop_epoch
                else:
                    send_failure_current = False
                    self._escalate_physical_stop(
                        'joint command failed after a newer STOP/close/fault '
                        'state superseded its send epoch')
                    detail = self.fault_reason
            if send_failure_current:
                detail = self._handle_command_send_failure(
                    'joint command send failed', exc, stop_epoch)
            raise ArmGatewayError(detail) from exc
        with self._lock:
            self._motion_send_in_progress = False
            self._require_command_activation_state(
                'joint command', send_epoch)
            self._begin_command(command)
            return command

    def command_tcp_move(
            self, target, speed_grade, mode, authorization_id,
            expected_session_id):
        """Send one bounded TCP target after frame and limit checks."""
        self._reject_reentrant_public_operation('command_tcp_move')
        with self._lock:
            validation_epoch = self._state_epoch
            snapshot = self._capture_motion_ready_state(
                speed_grade, expected_session_id)
            if type(mode) is not int:
                raise MotionRejected('TCP mode must be an exact integer')
            if mode not in self._policy.allowed_tcp_modes:
                raise MotionRejected(
                    'TCP mode {} is not permitted'.format(mode))
            resolved = self._policy.validate_tcp_target(target)
        try:
            motion_time = self._read_clock(
                'motion timing clock', expected_epoch=validation_epoch)
        except ArmGatewayError as exc:
            raise MotionRejected(str(exc)) from exc
        with self._lock:
            self._commit_motion_ready_state(
                snapshot, motion_time, speed_grade, expected_session_id,
                validation_epoch)
        try:
            reference_frame = self._call_external_method(
                'backend get_reference_frame',
                self._backend, 'get_reference_frame')
            end_type = self._call_external_method(
                'backend get_end_type', self._backend, 'get_end_type')
        except Exception as exc:
            with self._lock:
                if self._state_epoch == validation_epoch:
                    self._latch_fault(
                        'TCP frame query failed: {}'.format(
                            type(exc).__name__))
                detail = self.fault_reason or 'TCP frame query was superseded'
            raise ArmGatewayError(detail) from exc
        with self._lock:
            self._require_current_epoch(
                validation_epoch, 'TCP frame validation')
            if (
                    type(reference_frame) is not int
                    or reference_frame
                    != self._policy.required_reference_frame):
                if type(reference_frame) is not int:
                    raise MotionRejected(
                        'reference frame feedback must be an exact integer')
                raise MotionRejected(
                    'reference frame mismatch: expected {}, observed {}'
                    .format(
                        self._policy.required_reference_frame,
                        reference_frame))
            if (
                    type(end_type) is not int
                    or end_type != self._policy.required_end_type):
                if type(end_type) is not int:
                    raise MotionRejected(
                        'end type feedback must be an exact integer')
                raise MotionRejected(
                    'end type mismatch: expected {}, observed {}'.format(
                        self._policy.required_end_type, end_type))
        resolved_authorization = self._require_authorization(
            authorization_id, 'motion')
        command = self._new_command(
            'tcp_move', resolved, speed_grade, mode,
            resolved_authorization, motion_time)
        try:
            final_motion_time = self._read_clock(
                'final motion freshness clock',
                expected_epoch=validation_epoch)
        except ArmGatewayError as exc:
            raise MotionRejected(str(exc)) from exc
        with self._lock:
            self._require_current_epoch(
                validation_epoch, 'TCP command validation')
            self._commit_motion_ready_state(
                snapshot, final_motion_time, speed_grade, expected_session_id,
                validation_epoch)
            self._consume_command_identity(command)
            self._motion_send_in_progress = True
            send_epoch = self._state_epoch
        try:
            self._call_external_method(
                'backend send_coords', self._backend, 'send_coords',
                list(resolved), int(speed_grade), int(mode))
        except Exception as exc:
            with self._lock:
                self._motion_send_in_progress = False
                if self._state_epoch == send_epoch:
                    send_failure_current = True
                    stop_epoch = self._advance_state_epoch()
                    self._stop_send_epoch = stop_epoch
                else:
                    send_failure_current = False
                    self._escalate_physical_stop(
                        'TCP command failed after a newer STOP/close/fault '
                        'state superseded its send epoch')
                    detail = self.fault_reason
            if send_failure_current:
                detail = self._handle_command_send_failure(
                    'TCP command send failed', exc, stop_epoch)
            raise ArmGatewayError(detail) from exc
        with self._lock:
            self._motion_send_in_progress = False
            self._require_command_activation_state(
                'TCP command', send_epoch)
            self._begin_command(command)
            return command

    def request_stop(self, reason, expected_session_id):
        """Send one rate-limited STOP attempt and verify it by polling."""
        self._reject_reentrant_public_operation('request_stop')
        with self._lock:
            self._ensure_not_closed()
            self._require_session(expected_session_id)
            if self._physical_stop_required:
                raise MotionRejected(self._physical_stop_message())
            if (
                    self.state == GatewayState.STOPPING
                    or self._stop_send_epoch is not None):
                return False
            detail = _safe_stop_reason(reason, 'stop requested')
            previous_fault = (
                self.fault_reason
                if self.state == GatewayState.FAULT_LATCHED else '')
            stop_epoch = self._advance_state_epoch()
            # A new STOP reservation supersedes any stationary proof from an
            # older epoch immediately, including while transport is blocked.
            self._fault_stationary_verified = False
            self._fault_stable_samples = 0
            self._last_fault_angles = None
            self._fault_stable_since = None
            self._stop_send_epoch = stop_epoch
        try:
            sent, now = self._send_stop_attempt(expected_epoch=stop_epoch)
        except Exception:
            with self._lock:
                if self._stop_send_epoch == stop_epoch:
                    self._stop_send_epoch = None
            raise
        resolved_detail = (
            '{}; STOP requested: {}; attempt {}/{}'.format(
                previous_fault,
                detail,
                self._stop_attempt_count,
                self._policy.max_stop_attempts,
            )
            if previous_fault else '{}; attempt {}/{}'.format(
                detail,
                self._stop_attempt_count,
                self._policy.max_stop_attempts,
            ))
        with self._lock:
            if self._stop_send_epoch == stop_epoch:
                self._stop_send_epoch = None
            if not sent:
                return False
            self._require_current_epoch(stop_epoch, 'STOP result')
            if self.state == GatewayState.CLOSED:
                raise ArmGatewayError(
                    'STOP returned after the gateway was closed')
            self._enter_stopping(resolved_detail, now)
            return True

    def acknowledge_local_fault(
            self, authorization_id, expected_session_id):
        """Clear only the local latch; never clear a controller error."""
        self._reject_reentrant_public_operation('acknowledge_local_fault')
        with self._lock:
            ack_epoch, snapshot = self._capture_fault_ack_state(
                expected_session_id)
        now = self._read_clock(
            'fault ACK timing clock', expected_epoch=ack_epoch)
        with self._lock:
            self._commit_fault_ack_state(
                expected_session_id, ack_epoch, snapshot, now)
        resolved_authorization = self._require_authorization(
            authorization_id, 'ack')
        try:
            final_ack_time = self._read_clock(
                'final fault ACK freshness clock', expected_epoch=ack_epoch)
        except ArmGatewayError as exc:
            raise MotionRejected(str(exc)) from exc
        with self._lock:
            self._commit_fault_ack_state(
                expected_session_id, ack_epoch, snapshot, final_ack_time)
            if resolved_authorization in self._used_authorization_ids:
                raise MotionRejected(
                    'authorization_id has already been consumed')
            self._used_authorization_ids.add(resolved_authorization)
            if self.active_command is not None:
                self.last_result = CommandResult(
                    command_id=self.active_command.command_id,
                    success=False,
                    detail=self.fault_reason or 'fault acknowledged',
                    finished_at=final_ack_time,
                )
                self.active_command = None
            self.fault_reason = ''
            self.state = GatewayState.READY
            self._fault_stationary_verified = False
            self._fault_stable_samples = 0
            self._last_fault_angles = None
            self._fault_stable_since = None
            self._reset_stop_attempts()
            return True

    def close(self):
        """Best-effort STOP active motion, then permanently close backend."""
        self._reject_reentrant_public_operation('close')
        with self._close_lock:
            with self._lock:
                if self.state == GatewayState.CLOSED and self._backend_closed:
                    return
                errors = []
                first_close_attempt = (
                    not self._close_started
                    and self.state != GatewayState.CLOSED)
                # Reserve shutdown under the ordinary core lock.  All later
                # motion/STOP capture gates reject before external transport
                # can start, so the close plan cannot become stale.
                self._close_started = True
                motion_may_be_active = (
                    self._motion_safety_unresolved()
                    if first_close_attempt else False)
                if first_close_attempt:
                    self._advance_state_epoch()
                    if self._stop_send_epoch is not None:
                        self._escalate_physical_stop(
                            'gateway close superseded an in-flight STOP '
                            'before stationary verification')
                    physical_required = self._physical_stop_required
                else:
                    physical_required = False
            if first_close_attempt:
                if physical_required:
                    errors.append(self._physical_stop_message())
                elif motion_may_be_active:
                    try:
                        sent, _ = self._send_stop_attempt()
                        if sent:
                            errors.append(
                                'shutdown STOP sent on attempt {}/{}; '
                                'stationary state is unverified'.format(
                                    self._stop_attempt_count,
                                    self._policy.max_stop_attempts,
                                ))
                        else:
                            errors.append(
                                'shutdown STOP retry throttled; stationary '
                                'state is unverified')
                    except Exception as exc:
                        errors.append('shutdown STOP failed: {}'.format(
                            type(exc).__name__))
                        with self._lock:
                            if self._physical_stop_required:
                                physical = self._physical_stop_message()
                                if physical not in errors:
                                    errors.append(physical)
                with self._lock:
                    if motion_may_be_active and not self._physical_stop_required:
                        self._escalate_physical_stop(
                            'gateway closed before shutdown STOP stationary '
                            'verification')
                    if self._physical_stop_required:
                        physical = self._physical_stop_message()
                        if physical not in errors:
                            errors.append(physical)
                    # Latch CLOSED before external transport shutdown.
                    self.state = GatewayState.CLOSED
                    self.active_command = None
            close_attempted, close_error = (
                self._try_close_backend_without_stop_overlap())
            if not close_attempted:
                errors.append(
                    'backend close deferred until the in-flight STOP '
                    'transport call returns')
            elif close_error is not None:
                errors.append('backend close failed: {}'.format(
                    type(close_error).__name__))
            if errors:
                raise ArmGatewayError('; '.join(errors))

    def _capture_motion_ready_state(
            self, speed_grade, expected_session_id):
        """Capture a motion gate without executing injected code."""
        self._ensure_not_closed()
        self._require_session(expected_session_id)
        if self._physical_stop_required:
            raise MotionRejected(self._physical_stop_message())
        if not self._policy.permit_motion:
            raise MotionRejected('motion is disabled by static policy')
        if self._motion_send_in_progress:
            raise MotionRejected('another motion send is already in progress')
        if self._stop_send_epoch is not None:
            raise MotionRejected('a STOP send is already in progress')
        if self.state != GatewayState.READY:
            raise MotionRejected(
                'gateway is not READY: {}'.format(self.state.value))
        if type(speed_grade) is not int:
            raise MotionRejected('speed_grade must be an integer')
        if speed_grade not in self._policy.approved_speed_grades:
            raise MotionRejected(
                'speed_grade must be one of the approved grades: {}'.format(
                    self._policy.approved_speed_grades))
        if self.snapshot is None:
            raise MotionRejected('fresh motion-ready state is required')
        issue = self._snapshot_issue(self.snapshot)
        if issue:
            raise MotionRejected(
                'latest controller state is invalid: {}'.format(issue))
        return self.snapshot

    def _commit_motion_ready_state(
            self, snapshot, now, speed_grade, expected_session_id,
            expected_epoch):
        """Recheck a captured motion gate after all external calls."""
        self._require_current_epoch(expected_epoch, 'motion readiness')
        current = self._capture_motion_ready_state(
            speed_grade, expected_session_id)
        if current is not snapshot:
            raise MotionRejected(
                'latest controller state changed during motion validation')
        if not snapshot.motion_ready(now, self._policy.state_max_age_s):
            raise MotionRejected('fresh motion-ready state is required')

    def _require_current_epoch(self, expected_epoch, context):
        if self._state_epoch != expected_epoch:
            raise ArmGatewayError(
                '{} was superseded by a newer STOP/close/fault epoch'.format(
                    context))

    def _require_current_refresh(
            self, expected_epoch, expected_generation, context):
        self._require_current_epoch(expected_epoch, context)
        if self._refresh_generation != expected_generation:
            raise ArmGatewayError(
                '{} was superseded by a newer refresh generation'.format(
                    context))

    def _require_refresh_commit_allowed(
            self, expected_epoch, expected_generation, context):
        self._require_current_refresh(
            expected_epoch, expected_generation, context)
        if self._stop_send_epoch == expected_epoch:
            raise ArmGatewayError(
                '{} cannot commit while the STOP transport call for this '
                'epoch is still in progress'.format(context))

    def _require_command_activation_state(
            self, command_kind, expected_epoch):
        """Do not let a late send overwrite STOP/fault/close state."""
        if (
                self._state_epoch == expected_epoch
                and
                self.state == GatewayState.READY
                and not self.physical_stop_required):
            return
        detail = (
            '{} send completed after a newer STOP/close/fault epoch or after '
            'the gateway left READY; command activation is refused'.format(
                command_kind))
        self._escalate_physical_stop(detail)
        raise ArmGatewayError(self.fault_reason or detail)

    def _capture_fault_ack_state(self, expected_session_id):
        """Capture the ACK gate without running clock or validator code."""
        self._ensure_not_closed()
        self._require_session(expected_session_id)
        if self._physical_stop_required:
            raise MotionRejected(self._physical_stop_message())
        if self._motion_send_in_progress:
            raise MotionRejected(
                'a pre-STOP motion transport call is still in progress')
        if self._stop_send_epoch is not None:
            raise MotionRejected('a STOP transport call is still in progress')
        if self.state != GatewayState.FAULT_LATCHED:
            raise MotionRejected('no local fault is latched')
        if self.snapshot is None:
            raise MotionRejected('a valid state sample is required')
        issue = self._snapshot_issue(self.snapshot)
        if issue:
            raise MotionRejected(
                'controller state is not healthy: {}'.format(issue))
        if not self._fault_stationary_verified:
            raise MotionRejected(
                'stationary state has not been verified across samples')
        if self.snapshot.moving != 0:
            raise MotionRejected('latest controller state is not stationary')
        return self._state_epoch, self.snapshot

    def _commit_fault_ack_state(
            self, expected_session_id, expected_epoch, snapshot, now):
        self._require_current_epoch(expected_epoch, 'fault ACK')
        current_epoch, current_snapshot = self._capture_fault_ack_state(
            expected_session_id)
        if current_epoch != expected_epoch or current_snapshot is not snapshot:
            raise MotionRejected(
                'controller state changed during fault ACK validation')
        if not snapshot.motion_ready(now, self._policy.state_max_age_s):
            raise MotionRejected(
                'fresh stationary controller state is required')

    def _snapshot_issue(self, snapshot):
        for name in (
                'connected', 'power_on', 'moving', 'paused', 'error_code',
                'fresh_mode', 'servo_enabled'):
            if type(getattr(snapshot, name)) is not int:
                return '{} state must be an exact integer'.format(name)
        if snapshot.connected != 1:
            return 'controller is not connected'
        if snapshot.power_on != 1:
            return 'controller is not powered'
        if snapshot.moving not in (0, 1):
            return 'moving state is invalid: {!r}'.format(snapshot.moving)
        if snapshot.paused not in (0, 1):
            return 'paused state is invalid: {!r}'.format(snapshot.paused)
        if snapshot.paused == 1:
            return 'controller is paused'
        if snapshot.error_code != 0:
            return 'controller error code is {!r}'.format(
                snapshot.error_code)
        if snapshot.fresh_mode != self._policy.required_fresh_mode:
            return 'fresh mode mismatch: expected {}, observed {!r}'.format(
                self._policy.required_fresh_mode, snapshot.fresh_mode)
        if snapshot.servo_enabled != 1:
            return 'not all servos are enabled'
        try:
            self._policy.validate_joint_target(snapshot.angles_deg)
        except (MotionRejected, ValueError) as error:
            return 'measured joint state is invalid: {}'.format(
                type(error).__name__)
        try:
            self._policy.validate_tcp_target(snapshot.tcp_pose)
        except (MotionRejected, ValueError) as error:
            return 'measured TCP state is invalid: {}'.format(
                type(error).__name__)
        return ''

    def _new_command(
            self, kind, target, speed_grade, mode, authorization_id,
            started_at):
        command_id_value = self._call_external(
            'command_id_factory', self._command_id_factory)
        if type(command_id_value) is not str:
            raise ArmGatewayError(
                'command_id_factory must return a string')
        command_id = command_id_value.strip()
        if not command_id:
            raise ArmGatewayError(
                'command_id_factory returned an empty command id')
        return ActiveCommand(
            command_id=command_id,
            session_id=self.session_id,
            kind=kind,
            target=target,
            speed_grade=int(speed_grade),
            mode=int(mode),
            authorization_id=authorization_id.strip(),
            started_at=started_at,
        )

    def _consume_command_identity(self, command):
        """Consume replay-sensitive identity before the backend call."""
        if command.command_id in self._issued_command_ids:
            self._latch_fault(
                'command_id is empty or has already been issued')
            raise ArmGatewayError(self.fault_reason)
        if command.authorization_id in self._used_authorization_ids:
            raise MotionRejected(
                'authorization_id has already been consumed')
        self._issued_command_ids.add(command.command_id)
        self._used_authorization_ids.add(command.authorization_id)

    def _require_session(self, expected_session_id):
        if (
                type(expected_session_id) is not str
                or not expected_session_id.strip()
                or expected_session_id != self.session_id):
            raise MotionRejected('stale or empty session id')

    def _require_authorization(self, authorization_id, purpose):
        resolved = (
            authorization_id.strip()
            if type(authorization_id) is str else '')
        if not resolved:
            raise MotionRejected('authorization_id is required')
        if resolved in self._used_authorization_ids:
            raise MotionRejected(
                'authorization_id has already been consumed')
        if self._authorization_validator is None:
            raise MotionRejected(
                'authorization validator is not configured')
        try:
            accepted = self._call_external(
                'authorization validator',
                self._authorization_validator,
                resolved, purpose, self.session_id)
        except Exception as exc:
            raise MotionRejected(
                'authorization validation failed: {}'.format(
                    type(exc).__name__)) from exc
        if accepted is not True:
            raise MotionRejected(
                'authorization_id does not match {} purpose'.format(
                    purpose))
        return resolved

    def _begin_command(self, command):
        # Samples captured before the backend send returned cannot provide
        # completion credit for the newly activated command.
        self._advance_state_epoch()
        self.active_command = command
        self.last_result = None
        self.fault_reason = ''
        self._stable_samples = 0
        self._last_completion_observed_at = None
        self._completion_stable_since = None
        self._fault_stationary_verified = False
        self._fault_stable_samples = 0
        self._last_fault_angles = None
        self._fault_stable_since = None
        self._reset_stop_attempts()
        self.state = GatewayState.EXECUTING

    def _advance_state_epoch(self):
        self._state_epoch += 1
        return self._state_epoch

    def _handle_command_send_failure(self, prefix, error, stop_epoch):
        """Attempt independent STOP without holding the core state lock."""
        detail = '{}: {}'.format(prefix, type(error).__name__)
        try:
            sent, now = self._send_stop_attempt(expected_epoch=stop_epoch)
        except Exception as stop_error:
            detail += '; best-effort STOP failed: {}'.format(
                type(stop_error).__name__)
            sent = False
            now = None
        with self._lock:
            if self._stop_send_epoch == stop_epoch:
                self._stop_send_epoch = None
            if self._state_epoch != stop_epoch:
                self._escalate_physical_stop(
                    '{}; send failure was superseded before STOP commit'
                    .format(detail))
                return self.fault_reason
            if sent:
                detail += '; best-effort STOP sent on attempt {}/{}'.format(
                    self._stop_attempt_count,
                    self._policy.max_stop_attempts,
                )
                self._enter_stopping(detail, now)
            elif self._physical_stop_required:
                self._latch_fault(detail)
            else:
                detail += '; best-effort STOP retry throttled'
                self._latch_fault(detail)
            return self.fault_reason

    def _update_executing(self, snapshot):
        command = self.active_command
        if command is None:
            self._latch_fault('EXECUTING without an active command')
            return
        now = snapshot.observed_at
        elapsed = now - command.started_at
        if not _finite(elapsed) or elapsed < 0.0:
            return 'motion timing clock moved backwards'
        if elapsed > self._policy.command_timeout_s:
            return 'command timeout'
        reached = self._target_reached(command, snapshot)
        distinct_sample = (
            self._last_completion_observed_at is None
            or now > self._last_completion_observed_at
        )
        if snapshot.moving == 0 and reached and distinct_sample:
            self._stable_samples += 1
            self._last_completion_observed_at = now
            if self._completion_stable_since is None:
                self._completion_stable_since = now
        elif snapshot.moving != 0 or not reached:
            self._stable_samples = 0
            self._last_completion_observed_at = None
            self._completion_stable_since = None
        dwell_met = (
            self._completion_stable_since is not None
            and now - self._completion_stable_since
            >= self._policy.stationary_dwell_s
        )
        if (
                self._stable_samples >= self._policy.stable_samples_required
                and dwell_met):
            self.last_result = CommandResult(
                command_id=command.command_id,
                success=True,
                detail='target reached and stable',
                finished_at=now,
            )
            self.active_command = None
            self._stable_samples = 0
            self._last_completion_observed_at = None
            self._completion_stable_since = None
            self.state = GatewayState.READY
        return ''

    def _update_stopping(self, snapshot):
        if self._stop_started_at is None:
            self._latch_fault('STOPPING without a start timestamp')
            return
        now = snapshot.observed_at
        if now - self._stop_started_at > self._policy.stop_timeout_s:
            self._handle_stop_verification_timeout(now)
            return
        stable = (
            snapshot.moving == 0
            and self._last_stopping_angles is not None
            and all(
                abs(current - previous)
                <= self._policy.stationary_joint_tolerance_deg
                for current, previous in zip(
                    snapshot.angles_deg, self._last_stopping_angles)
            )
        )
        self._last_stopping_angles = snapshot.angles_deg
        self._stable_samples = self._stable_samples + 1 if stable else 0
        if stable and self._stopping_stable_since is None:
            self._stopping_stable_since = now
        elif not stable:
            self._stopping_stable_since = None
        dwell_met = (
            self._stopping_stable_since is not None
            and now - self._stopping_stable_since
            >= self._policy.stationary_dwell_s
        )
        if (
                self._stable_samples >= self._policy.stable_samples_required
                and dwell_met):
            command_id = (
                self.active_command.command_id
                if self.active_command is not None else '')
            self.last_result = CommandResult(
                command_id=command_id,
                success=False,
                detail=self.fault_reason or 'motion stopped',
                finished_at=now,
            )
            self.active_command = None
            self._latch_fault(
                self.last_result.detail + '; stationary state verified',
                stationary_verified=True,
            )

    def _update_fault_latched(self, snapshot):
        if (
                self._physical_stop_required
                or self._motion_send_in_progress
                or self._stop_send_epoch is not None):
            self._fault_stationary_verified = False
            self._fault_stable_samples = 0
            self._last_fault_angles = None
            self._fault_stable_since = None
            return
        if self._fault_stationary_verified:
            return
        now = snapshot.observed_at
        if not snapshot.motion_ready(
                now, self._policy.state_max_age_s):
            self._fault_stable_samples = 0
            self._last_fault_angles = None
            self._fault_stable_since = None
            return
        stable = (
            self._last_fault_angles is not None
            and all(
                abs(current - previous)
                <= self._policy.stationary_joint_tolerance_deg
                for current, previous in zip(
                    snapshot.angles_deg, self._last_fault_angles)
            )
        )
        self._last_fault_angles = snapshot.angles_deg
        self._fault_stable_samples = (
            self._fault_stable_samples + 1 if stable else 0)
        if stable and self._fault_stable_since is None:
            self._fault_stable_since = now
        elif not stable:
            self._fault_stable_since = None
        dwell_met = (
            self._fault_stable_since is not None
            and now - self._fault_stable_since
            >= self._policy.stationary_dwell_s
        )
        if (
                self._fault_stable_samples
                >= self._policy.stable_samples_required
                and dwell_met):
            self._fault_stationary_verified = True
            if self.active_command is not None:
                self.last_result = CommandResult(
                    command_id=self.active_command.command_id,
                    success=False,
                    detail=(
                        self.fault_reason
                        or 'fault reached verified stationary state'),
                    finished_at=now,
                )
                self.active_command = None

    def _target_reached(self, command, snapshot):
        if command.kind == 'named_joint_pose':
            return all(
                abs(actual - target)
                <= self._policy.joint_tolerance_deg
                for actual, target in zip(
                    snapshot.angles_deg, command.target)
            )
        if command.kind == 'tcp_move':
            translation_ok = all(
                abs(actual - target)
                <= self._policy.tcp_translation_tolerance_mm
                for actual, target in zip(
                    snapshot.tcp_pose[:3], command.target[:3])
            )
            rotation_ok = all(
                abs(actual - target)
                <= self._policy.tcp_rotation_tolerance_deg
                for actual, target in zip(
                    snapshot.tcp_pose[3:], command.target[3:])
            )
            return translation_ok and rotation_ok
        return False

    def _latch_fault(self, reason, stationary_verified=False):
        self._advance_state_epoch()
        resolved = _internal_text(reason, 'unknown arm fault')
        if (
                self.physical_stop_required
                and self._physical_stop_message() not in resolved):
            resolved += '; ' + self._physical_stop_message()
        self.fault_reason = resolved
        self.state = GatewayState.FAULT_LATCHED
        self._stable_samples = 0
        self._last_completion_observed_at = None
        self._completion_stable_since = None
        self._fault_stationary_verified = bool(stationary_verified)
        self._fault_stable_samples = 0
        self._last_fault_angles = None
        self._fault_stable_since = None
        self._stop_started_at = None
        self._last_stopping_angles = None
        self._stopping_stable_since = None

    def _handle_state_query_failure(self, detail, observed_at):
        """Commit a query failure and return any STOP request for lock-free send."""
        if self._physical_stop_required:
            self._latch_fault(detail)
            return ''
        if self.state == GatewayState.STOPPING:
            if self._stop_started_at is None:
                self._latch_fault(
                    '{}; STOPPING without a start timestamp'.format(detail))
                return ''
            elapsed = observed_at - self._stop_started_at
            if not _finite(elapsed) or elapsed < 0.0:
                self._escalate_physical_stop(
                    '{}; STOP verification timing is invalid'.format(detail))
                return ''
            if elapsed > self._policy.stop_timeout_s:
                self._handle_stop_verification_timeout(observed_at, detail)
            else:
                self.fault_reason = (
                    '{}; STOP verification pending on attempt {}/{}'
                    .format(
                        detail,
                        self._stop_attempt_count,
                        self._policy.max_stop_attempts,
                    ))
            return ''
        if not self._motion_safety_unresolved():
            self._latch_fault(detail)
            return ''
        return detail

    def _handle_unverifiable_snapshot(self, detail, observed_at):
        """Commit verification state and return a STOP reason if required."""
        resolved = '{}; stop state cannot be verified'.format(detail)
        if self.state == GatewayState.STOPPING:
            if self._stop_started_at is None:
                self._latch_fault(
                    '{}; STOPPING without a start timestamp'.format(resolved))
                return ''
            elapsed = observed_at - self._stop_started_at
            if not _finite(elapsed) or elapsed < 0.0:
                self._escalate_physical_stop(
                    '{}; STOP verification timing is invalid'.format(
                        resolved))
            elif elapsed > self._policy.stop_timeout_s:
                self._handle_stop_verification_timeout(observed_at, resolved)
            else:
                self.fault_reason = (
                    '{}; STOP verification pending on attempt {}/{}'
                    .format(
                        resolved,
                        self._stop_attempt_count,
                        self._policy.max_stop_attempts,
                    ))
            return ''
        return resolved

    def _handle_stop_verification_timeout(self, now, context=''):
        detail = (
            'software stop attempt {}/{} was not verified before timeout'
            .format(
                self._stop_attempt_count,
                self._policy.max_stop_attempts,
            ))
        if context:
            detail = '{}; {}'.format(context, detail)
        if self._stop_attempt_count >= self._policy.max_stop_attempts:
            self._escalate_physical_stop(detail)
        else:
            self._schedule_stop_retry(now)
            self._latch_fault(detail)

    def _enter_stopping(self, detail, now):
        if self._motion_send_in_progress:
            self._escalate_physical_stop(
                '{}; STOP returned while a pre-STOP motion transport call '
                'remains in progress, so STOP ordering cannot be verified'
                .format(detail))
            return
        self._advance_state_epoch()
        self.state = GatewayState.STOPPING
        self.fault_reason = detail
        self._stop_started_at = now
        self._stable_samples = 0
        self._last_completion_observed_at = None
        self._completion_stable_since = None
        self._last_stopping_angles = None
        self._stopping_stable_since = None
        self._fault_stationary_verified = False
        self._fault_stable_samples = 0
        self._last_fault_angles = None
        self._fault_stable_since = None

    def _motion_safety_unresolved(self):
        if self._physical_stop_required:
            return True
        hard_unresolved = (
            self._motion_send_in_progress
            or self._stop_send_epoch is not None
            or self.active_command is not None
            or self.state in (
                GatewayState.EXECUTING,
                GatewayState.STOPPING,
            )
            or (
                self.snapshot is not None
                and type(self.snapshot.moving) is int
                and self.snapshot.moving == 1
            )
        )
        if hard_unresolved:
            return True
        if self._fault_stationary_verified:
            return False
        return self._stop_attempt_count > 0

    def _calculate_stop_retry_deadline(self, now, attempt_number):
        try:
            retry_delay = (
                float(self._policy.stop_retry_interval_s)
                * float(self._policy.stop_retry_backoff_factor) ** (
                    attempt_number - 1)
            )
        except (OverflowError, TypeError, ValueError) as exc:
            raise _StopScheduleError(
                'derived STOP retry delay is invalid') from exc
        if not _positive_finite(retry_delay):
            raise _StopScheduleError(
                'derived STOP retry delay is non-finite')
        retry_deadline = now + retry_delay
        if not _finite(retry_deadline):
            raise _StopScheduleError(
                'derived STOP retry deadline is non-finite')
        return retry_deadline

    def _schedule_stop_retry(self, now):
        try:
            self._next_stop_attempt_at = (
                self._calculate_stop_retry_deadline(
                    now, self._stop_attempt_count))
        except _StopScheduleError as exc:
            self._escalate_physical_stop(exc.reason)
            raise ArmGatewayError(self.fault_reason) from exc

    def _stop_clock_now(self):
        return self._read_clock(
            'STOP timing clock', physical_on_failure=True,
            clock_callback=self._stop_clock)

    def _read_clock(
            self, context, physical_on_failure=False, expected_epoch=None,
            clock_callback=None):
        """Return a finite, non-decreasing gateway time value."""
        try:
            now = self._call_external(
                context,
                self._clock if clock_callback is None else clock_callback)
        except Exception as exc:
            detail = '{} failed: {}'.format(context, type(exc).__name__)
            with self._lock:
                if expected_epoch is not None:
                    self._require_current_epoch(expected_epoch, context)
                if physical_on_failure or self._motion_safety_unresolved():
                    self._escalate_physical_stop(detail)
                else:
                    self._latch_fault(detail)
                resolved_detail = self.fault_reason
            raise ArmGatewayError(resolved_detail) from exc
        if not _finite(now):
            detail = '{} received a non-finite clock value'.format(context)
            with self._lock:
                if expected_epoch is not None:
                    self._require_current_epoch(expected_epoch, context)
                if physical_on_failure or self._motion_safety_unresolved():
                    self._escalate_physical_stop(detail)
                else:
                    self._latch_fault(detail)
                resolved_detail = self.fault_reason
            raise ArmGatewayError(resolved_detail)
        resolved = float(now)
        with self._lock:
            if expected_epoch is not None:
                self._require_current_epoch(expected_epoch, context)
            if (
                    self._last_clock_value is not None
                    and resolved < self._last_clock_value):
                detail = '{} moved backwards'.format(context)
                if physical_on_failure or self._motion_safety_unresolved():
                    self._escalate_physical_stop(detail)
                else:
                    self._latch_fault(detail)
                raise ArmGatewayError(self.fault_reason)
            self._last_clock_value = resolved
        return resolved

    def _send_stop_attempt(self, expected_epoch=None):
        try:
            with self._stop_lock:
                now = self._stop_clock_now()
                with self._lock:
                    if expected_epoch is not None:
                        self._require_current_epoch(
                            expected_epoch, 'STOP attempt')
                    if self._physical_stop_required:
                        raise MotionRejected(self._physical_stop_message())
                    if not self._independent_stop_is_proven():
                        self._escalate_physical_stop(
                            'transport cannot prove a bounded independent '
                            'STOP channel')
                        raise MotionRejected(self.fault_reason)
                    if (
                            self._stop_attempt_count
                            >= self._policy.max_stop_attempts):
                        self._escalate_physical_stop(
                            'software STOP attempt limit was already '
                            'exhausted')
                        raise MotionRejected(self.fault_reason)
                    if (
                            self._next_stop_attempt_at is not None
                            and not _finite(self._next_stop_attempt_at)):
                        self._escalate_physical_stop(
                            'stored STOP retry deadline is non-finite')
                        raise ArmGatewayError(self.fault_reason)
                    if (
                            self._next_stop_attempt_at is not None
                            and now < self._next_stop_attempt_at):
                        return False, now
                    attempt_number = self._stop_attempt_count + 1
                    schedule_error = None
                    retry_deadline = None
                    try:
                        retry_deadline = self._calculate_stop_retry_deadline(
                            now, attempt_number)
                    except _StopScheduleError as exc:
                        schedule_error = exc.reason
                    self._stop_attempt_count = attempt_number
                    self._last_stop_attempt_at = now
                try:
                    self._call_external_method(
                        'backend stop', self._backend, 'stop')
                except Exception as exc:
                    with self._lock:
                        if expected_epoch is not None:
                            self._require_current_epoch(
                                expected_epoch, 'STOP failure')
                        failure = (
                            'stop send failed on attempt {}/{}: {}'.format(
                                self._stop_attempt_count,
                                self._policy.max_stop_attempts,
                                type(exc).__name__,
                            ))
                        if schedule_error:
                            failure = '{}; {}'.format(
                                failure, schedule_error)
                            self._escalate_physical_stop(failure)
                        elif (
                                self._stop_attempt_count
                                >= self._policy.max_stop_attempts):
                            self._escalate_physical_stop(failure)
                        else:
                            self._next_stop_attempt_at = retry_deadline
                            self._latch_fault(failure)
                        detail = self.fault_reason
                    raise ArmGatewayError(detail) from exc
                with self._lock:
                    if expected_epoch is not None:
                        self._require_current_epoch(
                            expected_epoch, 'STOP result')
                    if schedule_error:
                        self._escalate_physical_stop(
                            '{}; software STOP was sent on attempt {}/{}'
                            .format(
                                schedule_error,
                                self._stop_attempt_count,
                                self._policy.max_stop_attempts,
                            ))
                        raise ArmGatewayError(self.fault_reason)
                    self._next_stop_attempt_at = retry_deadline
                completed_at = self._read_clock(
                    'STOP completion timing clock',
                    physical_on_failure=True,
                    expected_epoch=expected_epoch,
                    clock_callback=self._stop_clock,
                )
                return True, completed_at
        finally:
            with self._lock:
                close_pending = (
                    self.state == GatewayState.CLOSED
                    and not self._backend_closed)
            if close_pending:
                self._complete_deferred_backend_close()

    def _reset_stop_attempts(self):
        self._stop_attempt_count = 0
        self._last_stop_attempt_at = None
        self._next_stop_attempt_at = None

    def _escalate_physical_stop(self, reason):
        self._physical_stop_required = True
        resolved_reason = _internal_text(
            reason, 'unknown arm safety escalation')
        resolved_reason = (
            '{}; persistent safety-latch acknowledgement must be committed '
            'by the independently bounded release supervisor'.format(
                resolved_reason))
        if self.state == GatewayState.CLOSED:
            self._advance_state_epoch()
            resolved = '{}; {}'.format(
                resolved_reason,
                self._physical_stop_message(),
            )
            self.fault_reason = resolved
            self.active_command = None
            return
        self._latch_fault(
            '{}; {}'.format(
                resolved_reason, self._physical_stop_message()))

    def _read_backend_capabilities(self):
        """Read static evidence without executing any adapter code.

        Capability discovery is an MRO class-dictionary lookup.  A method,
        property, descriptor or instance attribute could open a transport,
        block, or change its answer after observing external state; none is
        invoked by this construction gate.
        """
        capabilities = None
        for backend_type in type(self._backend).__mro__:
            if 'SAFETY_CAPABILITIES' in backend_type.__dict__:
                capabilities = backend_type.__dict__['SAFETY_CAPABILITIES']
                break
        if type(capabilities) is not dict:
            raise ValueError(
                'backend static SAFETY_CAPABILITIES are required')
        expected = {
            'bounded_calls_enforced',
            'method_deadlines_s',
            'native_deadline_enforced',
            'independent_stop_channel',
            'independent_stop_lock_domain',
            'stop_not_queued_behind_commands',
            'native_cancel_enforced',
            'persistent_safety_latch_capability',
            'real_transport',
            'runtime_release_id',
            'release_manifest_sha256',
            'acceleration_profile_id',
            'acceleration_profile_manifest_sha256',
            'acceleration_profile_runtime_release_id',
            'approved_speed_grades',
            'max_speed_grade',
            'required_reference_frame',
            'required_end_type',
            'required_fresh_mode',
        }
        if any(type(name) is not str for name in capabilities):
            raise ValueError(
                'backend safety capability keys must be exact strings')
        if set(capabilities) != expected:
            raise ValueError(
                'backend safety capability keys do not match the contract')
        boolean_names = {
            'bounded_calls_enforced',
            'native_deadline_enforced',
            'independent_stop_channel',
            'independent_stop_lock_domain',
            'stop_not_queued_behind_commands',
            'native_cancel_enforced',
            'persistent_safety_latch_capability',
            'real_transport',
        }
        for name in boolean_names:
            if type(capabilities[name]) is not bool:
                raise ValueError(
                    'backend safety capability {} must be a boolean'.format(
                        name))
        deadlines = capabilities['method_deadlines_s']
        if (
                type(deadlines) is not dict
                or set(deadlines) != BACKEND_METHOD_DEADLINE_NAMES
                or any(type(name) is not str for name in deadlines)):
            raise ValueError(
                'backend method deadlines must be an exact dictionary')
        for name, deadline in deadlines.items():
            if not _positive_finite(deadline):
                raise ValueError(
                    'backend method deadline {} must be a positive finite '
                    'built-in number'.format(name))
        string_names = (
            'runtime_release_id',
            'acceleration_profile_id',
            'acceleration_profile_runtime_release_id',
        )
        for name in string_names:
            value = capabilities[name]
            if (
                    type(value) is not str
                    or not value
                    or value != value.strip()):
                raise ValueError(
                    'backend safety capability {} must be an exact non-empty '
                    'string'.format(name))
        hash_names = (
            'release_manifest_sha256',
            'acceleration_profile_manifest_sha256',
        )
        for name in hash_names:
            value = capabilities[name]
            if (
                    type(value) is not str
                    or len(value) != 64
                    or any(character not in '0123456789abcdef'
                           for character in value)):
                raise ValueError(
                    'backend safety capability {} must be an exact lowercase '
                    'SHA-256'.format(name))
        if (
                capabilities['release_manifest_sha256']
                == capabilities['acceleration_profile_manifest_sha256']):
            raise ValueError(
                'backend release and acceleration-profile SHA-256 bindings '
                'must be different')
        approved_speed_grades = capabilities['approved_speed_grades']
        if (
                type(approved_speed_grades) is not tuple
                or not approved_speed_grades
                or any(type(grade) is not int
                       for grade in approved_speed_grades)):
            raise ValueError(
                'backend safety capability approved_speed_grades must be an '
                'exact non-empty tuple of exact integers')
        integer_names = (
            'max_speed_grade',
            'required_reference_frame',
            'required_end_type',
            'required_fresh_mode',
        )
        for name in integer_names:
            if type(capabilities[name]) is not int:
                raise ValueError(
                    'backend safety capability {} must be an exact integer'.format(
                        name))
        policy_bindings = {
            'real_transport': self._policy.expected_real_transport,
            'runtime_release_id': self._policy.runtime_release_id,
            'release_manifest_sha256': self._policy.release_manifest_sha256,
            'acceleration_profile_id': self._policy.acceleration_profile_id,
            'acceleration_profile_manifest_sha256': (
                self._policy.acceleration_profile_manifest_sha256),
            'acceleration_profile_runtime_release_id': (
                self._policy.acceleration_profile_runtime_release_id),
            'approved_speed_grades': tuple(
                self._policy.approved_speed_grades),
            'max_speed_grade': self._policy.max_speed_grade,
            'required_reference_frame': (
                self._policy.required_reference_frame),
            'required_end_type': self._policy.required_end_type,
            'required_fresh_mode': self._policy.required_fresh_mode,
        }
        for name, expected_value in policy_bindings.items():
            if capabilities[name] != expected_value:
                raise ValueError(
                    'backend safety capability {} does not match the active '
                    'motion policy binding'.format(name))
        if not all((
                capabilities['bounded_calls_enforced'],
                capabilities['native_deadline_enforced'],
                capabilities['independent_stop_channel'],
                capabilities['independent_stop_lock_domain'],
                capabilities['stop_not_queued_behind_commands'],
                capabilities['native_cancel_enforced'])):
            raise ValueError(
                'backend is DISABLED/BLOCKED without native bounded calls, '
                'deadlines, cancellation and an independent prioritized STOP '
                'execution/lock domain')
        if capabilities['real_transport']:
            if not capabilities['persistent_safety_latch_capability']:
                raise ValueError(
                    'real backend is DISABLED/BLOCKED without a persistent '
                    'safety-latch release attestation')
            raise ValueError(
                'real backend is DISABLED/BLOCKED: capability booleans and '
                'matching hashes are necessary but do not independently '
                'verify the release manifest or persistent safety-latch '
                'supervisor attestation')
        elif capabilities['persistent_safety_latch_capability']:
            raise ValueError(
                'pure-fake backend must not claim a persistent hardware '
                'safety-latch attestation')
        resolved = dict(capabilities)
        resolved['method_deadlines_s'] = MappingProxyType(dict(deadlines))
        return MappingProxyType(resolved)

    def _independent_stop_is_proven(self):
        return (
            self._backend_capabilities['bounded_calls_enforced']
            and self._backend_capabilities['native_deadline_enforced']
            and self._backend_capabilities['independent_stop_channel']
            and self._backend_capabilities['independent_stop_lock_domain']
            and self._backend_capabilities['stop_not_queued_behind_commands']
            and self._backend_capabilities['native_cancel_enforced']
        )

    def _send_uncredited_emergency_stop(self):
        """Send an emergency STOP after the physical latch is already set."""
        if not self._independent_stop_is_proven():
            raise ArmGatewayError(
                'transport cannot prove an independent STOP channel')
        acquired = self._stop_lock.acquire(blocking=False)
        if not acquired:
            raise ArmGatewayError(
                'another STOP transport call is already in progress; '
                'no second software STOP is credited and physical '
                'isolation remains required')
        try:
            with self._lock:
                if self.state == GatewayState.CLOSED:
                    return False
                if self._stop_send_epoch is not None:
                    raise ArmGatewayError(
                        'a STOP transaction is awaiting completion commit; '
                        'no second software STOP is credited')
            self._call_external_method(
                'backend emergency stop', self._backend, 'stop')
        except Exception as exc:
            if isinstance(exc, ArmGatewayError):
                raise
            raise ArmGatewayError(
                'emergency STOP send failed: {}'.format(
                    type(exc).__name__)) from exc
        finally:
            self._stop_lock.release()
            with self._lock:
                close_pending = (
                    self.state == GatewayState.CLOSED
                    and not self._backend_closed)
            if close_pending:
                self._complete_deferred_backend_close()
        return True

    def _try_close_backend_without_stop_overlap(self):
        acquired = self._stop_lock.acquire(blocking=False)
        if not acquired:
            return False, None
        try:
            try:
                self._call_external_method(
                    'backend close', self._backend, 'close')
            except Exception as error:
                return True, error
            with self._lock:
                self._backend_closed = True
            return True, None
        finally:
            self._stop_lock.release()

    def _complete_deferred_backend_close(self):
        with self._close_lock:
            with self._lock:
                if (
                        self.state != GatewayState.CLOSED
                        or self._backend_closed):
                    return ''
            attempted, error = self._try_close_backend_without_stop_overlap()
            if not attempted:
                return 'backend close remains deferred behind another STOP'
            if error is None:
                return ''
            detail = 'backend close failed: {}'.format(type(error).__name__)
            with self._lock:
                if detail not in self.fault_reason:
                    self.fault_reason = (
                        '{}; {}'.format(self.fault_reason, detail)
                        if self.fault_reason else detail)
            return detail

    def _physical_stop_message(self):
        return (
            'PHYSICAL EMERGENCY STOP AND POWER ISOLATION REQUIRED; '
            'software STOP attempts are exhausted; local ACK and motion are '
            'prohibited until a new gateway process session is started '
            'after onsite safety verification'
        )

    def _ensure_not_closed(self):
        if self._close_started or self.state == GatewayState.CLOSED:
            raise ArmGatewayError('gateway is closed or closing')

    def _reject_reentrant_public_operation(self, operation):
        if self._external_call_depth() > 0:
            raise ArmGatewayError(
                'reentrant gateway {} is prohibited during {}'.format(
                    operation, self._external_call_context()))

    def _external_call_depth(self):
        return getattr(self._external_call_state, 'depth', 0)

    def _external_call_context(self):
        return getattr(self._external_call_state, 'context', '')

    def _call_external(self, context, callback, *args):
        """Run one injected call while prohibiting same-thread reentry."""
        if self._external_call_depth() > 0:
            raise ArmGatewayError(
                'nested external call is prohibited during {}'.format(
                    self._external_call_context()))
        self._external_call_state.depth = 1
        self._external_call_state.context = context
        try:
            return callback(*args)
        finally:
            self._external_call_state.depth = 0
            self._external_call_state.context = ''

    def _call_external_method(
            self, context, target, method_name, *args):
        """Guard injected method lookup and invocation as one operation."""
        if self._external_call_depth() > 0:
            raise ArmGatewayError(
                'nested external call is prohibited during {}'.format(
                    self._external_call_context()))
        self._external_call_state.depth = 1
        self._external_call_state.context = context
        try:
            callback = getattr(target, method_name, None)
            if not callable(callback):
                raise RuntimeError(
                    '{} method is unavailable'.format(method_name))
            return callback(*args)
        finally:
            self._external_call_state.depth = 0
            self._external_call_state.context = ''
