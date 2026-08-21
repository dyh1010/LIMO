"""Offline fail-closed contract for a future final-tool gripper gateway.

The current ROS ``ControlGripper`` interface predates session, authorization,
STOP and ACK semantics. This core is hardware-independent and unreleased.
"""

import math
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum

from .gripper_core import normalized_value


class GripperGatewayError(RuntimeError):
    """Base error for a rejected or failed gateway operation."""


class GripperMotionRejected(GripperGatewayError):
    """Raised when a request does not pass the local safety policy."""


class _GripperIdentityValidationError(ValueError):
    """Raised when feedback cannot prove the reviewed device identity."""


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


class GripperGatewayState(str, Enum):
    """Locally enforced gripper gateway states."""

    INITIALIZING = 'INITIALIZING'
    READY = 'READY'
    EXECUTING = 'EXECUTING'
    STOPPING = 'STOPPING'
    FAULT_LATCHED = 'FAULT_LATCHED'
    CLOSED = 'CLOSED'


@dataclass(frozen=True)
class GripperGatewayPolicy:
    """Static policy that cannot be relaxed by one command."""

    permit_motion: bool
    reviewed_tool_model: str
    reviewed_tool_revision: str
    reviewed_controller_identity: str
    reviewed_transport_identity: str
    reviewed_protocol_identity: str
    state_max_age_s: float
    command_timeout_s: float
    stop_timeout_s: float
    stable_samples_required: int
    position_tolerance: float
    stationary_position_tolerance: float
    stationary_dwell_s: float
    # Deployment mode is policy-owned.  A transport must never be allowed to
    # downgrade itself to a fake by returning a transport-provided flag.
    backend_execution_mode: str = 'PURE_FAKE'
    runtime_release_id: str = ''
    release_manifest_sha256: str = ''
    motion_profile_id: str = ''
    motion_profile_manifest_sha256: str = ''
    motion_profile_runtime_release_id: str = ''
    approved_speed_grades: tuple = ()
    backend_method_contract_sha256: str = ''
    stop_isolation_architecture_sha256: str = ''
    hung_command_stop_test_report_sha256: str = ''
    persistent_latch_binding: str = ''

    def validate(self):
        """Reject incomplete or unsafe policies."""
        if type(self.permit_motion) is not bool:
            raise ValueError('permit_motion must be a boolean')
        for value, name in (
                (self.reviewed_tool_model, 'reviewed_tool_model'),
                (self.reviewed_tool_revision, 'reviewed_tool_revision'),
                (self.reviewed_controller_identity,
                 'reviewed_controller_identity'),
                (self.reviewed_transport_identity,
                 'reviewed_transport_identity'),
                (self.reviewed_protocol_identity,
                 'reviewed_protocol_identity')):
            if (
                    type(value) is not str
                    or not value
                    or value != value.strip()):
                raise ValueError(
                    '{} must be a non-empty reviewed identity without '
                    'surrounding whitespace'.format(name))
        for value, name in (
                (self.state_max_age_s, 'state_max_age_s'),
                (self.command_timeout_s, 'command_timeout_s'),
                (self.stop_timeout_s, 'stop_timeout_s')):
            if (
                    type(value) not in (int, float)
                    or not math.isfinite(float(value))
                    or float(value) <= 0.0):
                raise ValueError('{} must be positive and finite'.format(name))
        if (
                type(self.stable_samples_required) is not int
                or self.stable_samples_required < 2):
            raise ValueError('stable_samples_required must be at least 2')
        normalized_value(self.position_tolerance, 'position_tolerance')
        normalized_value(
            self.stationary_position_tolerance,
            'stationary_position_tolerance')
        if (
                type(self.stationary_dwell_s) not in (int, float)
                or not math.isfinite(float(self.stationary_dwell_s))
                or float(self.stationary_dwell_s) <= 0.0):
            raise ValueError(
                'stationary_dwell_s must be positive and finite')
        if self.command_timeout_s <= self.stationary_dwell_s:
            raise ValueError(
                'command_timeout_s must exceed stationary_dwell_s')
        if self.stop_timeout_s <= self.stationary_dwell_s:
            raise ValueError(
                'stop_timeout_s must exceed stationary_dwell_s')
        if (
                type(self.backend_execution_mode) is not str
                or self.backend_execution_mode not in ('PURE_FAKE', 'REAL')):
            raise ValueError(
                'backend_execution_mode must be PURE_FAKE or REAL')
        real_values = (
            self.runtime_release_id,
            self.release_manifest_sha256,
            self.motion_profile_id,
            self.motion_profile_manifest_sha256,
            self.motion_profile_runtime_release_id,
            self.backend_method_contract_sha256,
            self.stop_isolation_architecture_sha256,
            self.hung_command_stop_test_report_sha256,
            self.persistent_latch_binding,
        )
        if self.backend_execution_mode == 'PURE_FAKE':
            if any(real_values) or self.approved_speed_grades:
                raise ValueError(
                    'PURE_FAKE policy must not carry real backend release '
                    'or persistent-latch evidence')
            return
        for value, name in zip(
                real_values,
                ('runtime_release_id', 'release_manifest_sha256',
                 'motion_profile_id', 'motion_profile_manifest_sha256',
                 'motion_profile_runtime_release_id',
                 'backend_method_contract_sha256',
                 'stop_isolation_architecture_sha256',
                 'hung_command_stop_test_report_sha256',
                 'persistent_latch_binding')):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(
                    'REAL backend requires exact {}'.format(name))
        for value, name in (
                (self.release_manifest_sha256,
                 'release_manifest_sha256'),
                (self.motion_profile_manifest_sha256,
                 'motion_profile_manifest_sha256'),
                (self.backend_method_contract_sha256,
                 'backend_method_contract_sha256'),
                (self.stop_isolation_architecture_sha256,
                 'stop_isolation_architecture_sha256'),
                (self.hung_command_stop_test_report_sha256,
                 'hung_command_stop_test_report_sha256'),
                (self.persistent_latch_binding,
                 'persistent_latch_binding')):
            if len(value) != 64 or value != value.lower() or any(
                    character not in '0123456789abcdef'
                    for character in value):
                raise ValueError(
                    'REAL backend requires lowercase SHA-256 {}'.format(
                        name))
        if self.motion_profile_runtime_release_id != self.runtime_release_id:
            raise ValueError(
                'REAL backend motion profile runtime release ID must exactly '
                'match runtime_release_id')
        evidence_hashes = (
            self.release_manifest_sha256,
            self.motion_profile_manifest_sha256,
            self.backend_method_contract_sha256,
            self.stop_isolation_architecture_sha256,
            self.hung_command_stop_test_report_sha256,
            self.persistent_latch_binding,
        )
        if len(set(evidence_hashes)) != len(evidence_hashes):
            raise ValueError(
                'REAL backend release, motion profile, execution-safety and '
                'persistent-latch artifacts must be distinct')
        if (
                type(self.approved_speed_grades) is not tuple
                or not self.approved_speed_grades
                or self.approved_speed_grades != tuple(
                    sorted(set(self.approved_speed_grades)))
                or any(
                    type(grade) is not int or not 1 <= grade <= 100
                    for grade in self.approved_speed_grades)):
            raise ValueError(
                'REAL backend requires exact approved speed grades')

    def immutable_copy(self):
        """Return an exact immutable snapshot of validated policy inputs."""
        self.validate()
        snapshot = GripperGatewayPolicy(
            permit_motion=self.permit_motion,
            reviewed_tool_model=self.reviewed_tool_model,
            reviewed_tool_revision=self.reviewed_tool_revision,
            reviewed_controller_identity=self.reviewed_controller_identity,
            reviewed_transport_identity=self.reviewed_transport_identity,
            reviewed_protocol_identity=self.reviewed_protocol_identity,
            state_max_age_s=self.state_max_age_s,
            command_timeout_s=self.command_timeout_s,
            stop_timeout_s=self.stop_timeout_s,
            stable_samples_required=self.stable_samples_required,
            position_tolerance=self.position_tolerance,
            stationary_position_tolerance=(
                self.stationary_position_tolerance),
            stationary_dwell_s=self.stationary_dwell_s,
            backend_execution_mode=self.backend_execution_mode,
            runtime_release_id=self.runtime_release_id,
            release_manifest_sha256=self.release_manifest_sha256,
            motion_profile_id=self.motion_profile_id,
            motion_profile_manifest_sha256=(
                self.motion_profile_manifest_sha256),
            motion_profile_runtime_release_id=(
                self.motion_profile_runtime_release_id),
            approved_speed_grades=tuple(self.approved_speed_grades),
            backend_method_contract_sha256=(
                self.backend_method_contract_sha256),
            stop_isolation_architecture_sha256=(
                self.stop_isolation_architecture_sha256),
            hung_command_stop_test_report_sha256=(
                self.hung_command_stop_test_report_sha256),
            persistent_latch_binding=self.persistent_latch_binding,
        )
        snapshot.validate()
        return snapshot


@dataclass(frozen=True)
class GripperSnapshot:
    """One validated, timestamped feedback sample."""

    observed_at: float
    sample_timestamp: float
    sequence: int
    command_id: str
    tool_model: str
    tool_revision: str
    controller_identity: str
    transport_identity: str
    protocol_identity: str
    controller_boot_id: str
    connected: bool
    valid: bool
    enabled: bool
    moving: bool
    position: float
    fault_code: int

    def motion_ready(self, now, max_age_s):
        """Return whether this sample permits a new command."""
        age = float(now) - self.observed_at
        return (
            0.0 <= age <= max_age_s
            and self.connected
            and self.valid
            and self.enabled
            and not self.moving
            and self.fault_code == 0
        )


@dataclass(frozen=True)
class GripperCommand:
    """One command accepted by the local gateway."""

    command_id: str
    session_id: str
    authorization_id: str
    tool_revision: str
    position: float
    speed: float
    started_at: float


@dataclass(frozen=True)
class GripperCommandResult:
    """Terminal result associated with one command ID."""

    command_id: str
    success: bool
    detail: str
    finished_at: float


class GripperGatewayCore:
    """State machine around an injected final-tool-like backend."""

    def __init__(
            self,
            backend,
            policy,
            clock=None,
            authorization_validator=None,
            command_id_factory=None):
        if type(policy) is not GripperGatewayPolicy:
            raise ValueError('policy must be an exact GripperGatewayPolicy')
        policy = policy.immutable_copy()
        self._lock = threading.RLock()
        self._stop_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._backend = backend
        self._policy = policy
        self._clock = time.monotonic if clock is None else clock
        self._authorization_validator = authorization_validator
        self._command_id_factory = (
            (lambda: uuid.uuid4().hex)
            if command_id_factory is None else command_id_factory)
        self.session_id = uuid.uuid4().hex
        self.state = GripperGatewayState.INITIALIZING
        self.snapshot = None
        self.active_command = None
        self.last_result = None
        self.fault_reason = ''
        self._stop_started_at = None
        self._last_stationary_sequence = None
        self._last_stationary_timestamp = None
        self._last_stationary_position = None
        self._stationary_since = None
        self._last_completion_sequence = None
        self._last_completion_timestamp = None
        self._last_completion_position = None
        self._completion_stable_since = None
        self._last_accepted_sequence = None
        self._last_accepted_timestamp = None
        self._controller_boot_id = None
        self._identity_lockout = False
        self._identity_lockout_reason = ''
        self._stable_samples = 0
        self._fault_stationary_verified = False
        self._stop_unverified = False
        self._physical_stop_required = False
        self._last_clock_value = None
        self._used_authorization_ids = set()
        self._issued_command_ids = set()
        self._close_started = False
        self._backend_close_complete = False
        self._motion_send_in_progress = False
        self._stop_send_in_progress = False
        self._internal_stop_requires_physical = False
        self._state_epoch = 0
        self._refresh_generation = 0
        self._external_call_state = threading.local()
        self._backend_capabilities = self._read_backend_capabilities()

    def refresh(self):
        """Read one complete state sample and advance the state machine."""
        self._reject_reentrant_public_operation('refresh')
        with self._lock:
            self._ensure_open()
            refresh_epoch = self._state_epoch
            self._refresh_generation += 1
            refresh_generation = self._refresh_generation
        observed_at = self._read_clock(
            'state timing clock', expected_epoch=refresh_epoch)
        sample = None
        try:
            sample = self._call_external_method(
                'backend read_state', self._backend, 'read_state')
            snapshot = self._validated_snapshot(sample, observed_at)
        except _GripperIdentityValidationError as error:
            detail = 'identity validation failed: {}'.format(
                type(error).__name__)
            observed_moving = (
                type(sample) is dict and sample.get('moving') is True)
            with self._lock:
                self._require_current_refresh(
                    refresh_epoch, refresh_generation,
                    'identity validation failure')
                self.snapshot = None
                stop_reason = self._lock_identity(
                    detail, observed_moving=observed_moving)
                reported = self.fault_reason
            if stop_reason:
                self._attempt_internal_stop(stop_reason, refresh_epoch)
            raise GripperGatewayError(reported) from error
        except Exception as error:
            detail = 'state query failed: {}'.format(type(error).__name__)
            observed_moving = (
                type(sample) is dict and sample.get('moving') is True)
            with self._lock:
                self._require_current_refresh(
                    refresh_epoch, refresh_generation,
                    'state query failure')
                self.snapshot = None
                stop_reason = self._handle_motion_uncertainty_locked(
                    detail, observed_moving=observed_moving)
                reported = self.fault_reason
            if stop_reason:
                self._attempt_internal_stop(stop_reason, refresh_epoch)
                with self._lock:
                    reported = self.fault_reason or reported
            raise GripperGatewayError(reported) from error

        with self._lock:
            self._require_current_refresh(
                refresh_epoch, refresh_generation, 'state query result')
            stop_reason = self._refresh_locked(snapshot)
        if stop_reason:
            self._attempt_internal_stop(stop_reason, refresh_epoch)
        return snapshot

    def _refresh_locked(self, snapshot):
        if self._identity_lockout:
            return self._handle_motion_uncertainty_locked(
                self._identity_lockout_reason,
                observed_moving=snapshot.moving)
        if (
                self._controller_boot_id is not None
                and snapshot.controller_boot_id != self._controller_boot_id):
            return self._lock_identity(
                'controller_boot_id changed from {!r} to {!r}'.format(
                    self._controller_boot_id, snapshot.controller_boot_id),
                observed_moving=snapshot.moving)
        identity_issue = self._snapshot_identity_issue(snapshot)
        if identity_issue:
            return self._lock_identity(
                identity_issue, observed_moving=snapshot.moving)
        if self._controller_boot_id is None:
            self._controller_boot_id = snapshot.controller_boot_id
        if self._last_accepted_sequence is not None and (
                snapshot.sequence <= self._last_accepted_sequence
                or snapshot.sample_timestamp <= (
                    self._last_accepted_timestamp)):
            self._reset_stationary_evidence()
            self._fault_stationary_verified = False
            detail = 'state sequence/timestamp is stale or non-monotonic'
            return self._handle_motion_uncertainty_locked(
                detail, observed_moving=snapshot.moving)
        self.snapshot = snapshot
        self._last_accepted_sequence = snapshot.sequence
        self._last_accepted_timestamp = snapshot.sample_timestamp
        issue = self._snapshot_issue(snapshot)
        if issue:
            return self._handle_motion_uncertainty_locked(
                issue, observed_moving=snapshot.moving)
        if (
                snapshot.moving
                and self.state not in (
                    GripperGatewayState.EXECUTING,
                    GripperGatewayState.STOPPING)):
            if self.physical_stop_required:
                self._latch_fault(
                    'motion observed while physical stop is required')
                return ''
            return self._prepare_internal_stop_locked(
                'unexpected motion without an active command')
        if self.state == GripperGatewayState.INITIALIZING:
            if snapshot.motion_ready(
                    snapshot.observed_at, self._policy.state_max_age_s):
                self.state = GripperGatewayState.READY
        elif self.state == GripperGatewayState.EXECUTING:
            return self._update_executing(snapshot)
        elif self.state == GripperGatewayState.STOPPING:
            if self._stop_send_in_progress:
                self._reset_stationary_evidence()
                self._fault_stationary_verified = False
            else:
                self._update_stopping(snapshot)
        elif self.state == GripperGatewayState.FAULT_LATCHED:
            if (
                    self.physical_stop_required
                    or self._motion_send_in_progress):
                self._reset_stationary_evidence()
                self._fault_stationary_verified = False
            else:
                self._record_stationary_sample(snapshot)
                if self._stationary_evidence_complete(snapshot.observed_at):
                    self._fault_stationary_verified = True
                    self._stop_unverified = False
        return ''

    @property
    def physical_stop_required(self):
        """Return the process-lifetime physical safety escalation latch."""
        with self._lock:
            return self._physical_stop_required

    def snapshot_is_valid(self):
        """Return whether the latest sample is fresh, healthy and reviewed."""
        self._reject_reentrant_public_operation('snapshot_is_valid')
        with self._lock:
            if (
                    self.state == GripperGatewayState.CLOSED
                    or self.snapshot is None
                    or self._identity_lockout):
                return False
            validation_epoch = self._state_epoch
            snapshot = self.snapshot
        try:
            now = self._read_clock(
                'state freshness clock', expected_epoch=validation_epoch)
        except GripperGatewayError:
            return False
        with self._lock:
            if (
                    self._state_epoch != validation_epoch
                    or self.snapshot is not snapshot
                    or self.state == GripperGatewayState.CLOSED):
                return False
            if not self.snapshot.motion_ready(
                    now, self._policy.state_max_age_s):
                return False
            if self._snapshot_issue(self.snapshot):
                return False
            if self._snapshot_identity_issue(self.snapshot):
                return False
            return self.snapshot.controller_boot_id == self._controller_boot_id

    @property
    def motion_safety_unresolved(self):
        """Return whether an Action must keep waiting for safe resolution."""
        with self._lock:
            self._reject_reentrant_public_operation(
                'motion_safety_unresolved')
            return self._motion_safety_unresolved()

    def fail_closed_action_boundary(self, reason):
        """Escalate when an Action can no longer poll motion to resolution."""
        self._reject_reentrant_public_operation(
            'fail_closed_action_boundary')
        with self._lock:
            self._ensure_open()
            if not self._motion_safety_unresolved():
                return False
            detail = _safe_stop_reason(
                reason,
                'action boundary ended before stationary verification',
            )
            self._escalate_physical_stop(
                '{}; stationary verification cannot continue'.format(
                    detail))
            can_attempt_stop = self._independent_stop_is_proven()
        if can_attempt_stop:
            try:
                self._send_uncredited_emergency_stop()
            except GripperGatewayError:
                pass
        return True

    def command_position(
            self,
            position,
            speed,
            authorization_id,
            expected_session_id,
            expected_tool_revision):
        """Send one command after gates; the injected backend owns its deadline.

        This core prevents a late backend return from committing across a
        newer STOP/close/fault epoch.  It does not make an arbitrary backend
        call bounded; the final backend must separately prove a finite method
        deadline and cancellation or bounded-abandonment policy.
        """
        self._reject_reentrant_public_operation('command_position')
        with self._lock:
            validation_epoch, snapshot = self._capture_motion_ready_state(
                position,
                speed,
                expected_session_id,
                expected_tool_revision,
            )
        now = self._read_clock(
            'motion timing clock', expected_epoch=validation_epoch)
        resolved_authorization = self._require_authorization(
            authorization_id, 'motion')
        command_id_value = self._call_external(
            'command_id_factory', self._command_id_factory)
        with self._lock:
            command, send_epoch = self._commit_motion_command(
                position,
                speed,
                resolved_authorization,
                expected_session_id,
                expected_tool_revision,
                validation_epoch,
                snapshot,
                now,
                command_id_value,
            )
        try:
            self._call_external_method(
                'backend command_position',
                self._backend,
                'command_position',
                command.position,
                command.speed,
                command.command_id,
            )
        except Exception as error:
            with self._lock:
                self._motion_send_in_progress = False
                superseded = self._state_epoch != send_epoch
                closed = self.state == GripperGatewayState.CLOSED
            if superseded:
                with self._lock:
                    detail = (
                        'command send failed after a newer STOP/close/fault '
                        'epoch: {}'.format(type(error).__name__))
                    if not closed:
                        self._escalate_physical_stop(detail)
                    else:
                        self.fault_reason = detail + '; gateway is closed'
                    detail = self.fault_reason
            else:
                failure = 'command send failed: {}'.format(type(error).__name__)
                try:
                    self.request_stop(
                        failure + '; best-effort STOP sent', self.session_id)
                except GripperGatewayError:
                    pass
                with self._lock:
                    detail = self.fault_reason or failure
            raise GripperGatewayError(detail) from error
        with self._lock:
            self._motion_send_in_progress = False
            self._require_command_activation_state(send_epoch)
            # Samples captured before the backend call returned cannot be
            # credited toward completion of the activated command.
            self._advance_state_epoch()
            self._reset_completion_evidence()
            self.state = GripperGatewayState.EXECUTING
            return command

    def _capture_motion_ready_state(
            self,
            position,
            speed,
            expected_session_id,
            expected_tool_revision):
        self._ensure_open()
        self._require_session(expected_session_id)
        if self.physical_stop_required:
            raise GripperMotionRejected(self._physical_stop_message())
        self._require_tool_revision(expected_tool_revision)
        self._require_identity_ready()
        if self._stop_send_in_progress:
            raise GripperMotionRejected(
                'a software STOP send is already in progress')
        if self._stop_unverified:
            raise GripperMotionRejected(
                'a prior software STOP remains unverified')
        if not self._policy.permit_motion:
            raise GripperMotionRejected('motion is disabled by static policy')
        if self._motion_send_in_progress:
            raise GripperMotionRejected(
                'another motion send is already in progress')
        if self.state != GripperGatewayState.READY:
            raise GripperMotionRejected(
                'gateway is not READY: {}'.format(self.state.value))
        resolved_position = normalized_value(position, 'position')
        resolved_speed = normalized_value(speed, 'speed')
        if resolved_speed <= 0.0:
            raise GripperMotionRejected('speed must be greater than 0.0')
        if self.snapshot is None:
            raise GripperMotionRejected(
                'fresh stationary feedback is required')
        return self._state_epoch, self.snapshot

    def _commit_motion_command(
            self,
            position,
            speed,
            resolved_authorization,
            expected_session_id,
            expected_tool_revision,
            expected_epoch,
            snapshot,
            now,
            command_id_value):
        resolved_position = normalized_value(position, 'position')
        resolved_speed = normalized_value(speed, 'speed')
        self._require_current_epoch(expected_epoch, 'motion validation')
        current_epoch, current_snapshot = self._capture_motion_ready_state(
            position, speed, expected_session_id, expected_tool_revision)
        if current_epoch != expected_epoch or current_snapshot is not snapshot:
            raise GripperMotionRejected(
                'latest gripper state changed during motion validation')
        if not snapshot.motion_ready(now, self._policy.state_max_age_s):
            raise GripperMotionRejected(
                'fresh stationary feedback is required')
        if resolved_authorization in self._used_authorization_ids:
            raise GripperMotionRejected(
                'authorization_id has already been consumed')
        if type(command_id_value) is not str:
            raise GripperGatewayError(
                'command_id_factory must return a string')
        command_id = command_id_value.strip()
        if not command_id or command_id in self._issued_command_ids:
            self._latch_fault('command_id is empty or has already been issued')
            raise GripperGatewayError(self.fault_reason)
        command = GripperCommand(
            command_id=command_id,
            session_id=self.session_id,
            authorization_id=resolved_authorization,
            tool_revision=self._policy.reviewed_tool_revision,
            position=resolved_position,
            speed=resolved_speed,
            started_at=now,
        )
        self._issued_command_ids.add(command_id)
        self._used_authorization_ids.add(resolved_authorization)
        self.active_command = command
        self.last_result = None
        self.fault_reason = ''
        self._reset_completion_evidence()
        self._motion_send_in_progress = True
        return command, self._state_epoch

    def request_stop(self, reason, expected_session_id):
        """Send STOP once, then require fresh stationary samples."""
        self._reject_reentrant_public_operation('request_stop')
        with self._lock:
            stop_epoch, detail, previous_fault = (
                self._capture_stop_request_locked(
                    reason, expected_session_id))
        if stop_epoch is None:
            return False
        try:
            stop_started_at = self._read_clock(
                'STOP timing clock', expected_epoch=stop_epoch)
            with self._lock:
                self._commit_stop_request_locked(
                    stop_epoch, stop_started_at)
        except Exception:
            with self._lock:
                self._stop_send_in_progress = False
                self._internal_stop_requires_physical = False
            raise
        try:
            self._send_stop_attempt(expected_epoch=stop_epoch)
            stop_completed_at = self._read_clock(
                'STOP completion timing clock', expected_epoch=stop_epoch)
        except Exception as error:
            with self._lock:
                self._stop_send_in_progress = False
                self._internal_stop_requires_physical = False
                if self._state_epoch != stop_epoch:
                    if self.state == GripperGatewayState.CLOSED:
                        self._physical_stop_required = True
                        self.fault_reason = (
                            'STOP failed after gateway close: {}; {}'.format(
                                type(error).__name__,
                                self._physical_stop_message()))
                    detail = (
                        self.fault_reason
                        or 'STOP failure was superseded')
                    closed = self.state == GripperGatewayState.CLOSED
                else:
                    self._reset_stationary_evidence()
                    self._fault_stationary_verified = False
                    self._escalate_physical_stop(
                        'stop send failed: {}'.format(type(error).__name__))
                    detail = self.fault_reason
                    closed = False
            if closed:
                close_detail = self._complete_deferred_backend_close()
                if close_detail:
                    detail += '; ' + close_detail
            raise GripperGatewayError(detail) from error
        with self._lock:
            if (
                    self._state_epoch != stop_epoch
                    or self.state == GripperGatewayState.CLOSED):
                self._stop_send_in_progress = False
                self._internal_stop_requires_physical = False
                detail = (
                    self.fault_reason
                    or 'STOP returned after the gateway was closed')
                closed = self.state == GripperGatewayState.CLOSED
            else:
                self._commit_successful_stop_locked(
                    stop_epoch, stop_completed_at)
                return True
        if closed:
            close_detail = self._complete_deferred_backend_close()
            if close_detail:
                detail += '; ' + close_detail
        raise GripperGatewayError(detail)

    def _capture_stop_request_locked(self, reason, expected_session_id):
        self._ensure_open()
        self._require_session(expected_session_id)
        if self.physical_stop_required:
            raise GripperGatewayError(self._physical_stop_message())
        self._require_identity_ready()
        if self.state == GripperGatewayState.STOPPING:
            return None, '', ''
        if self._stop_send_in_progress:
            return None, '', ''
        if self._stop_unverified:
            raise GripperGatewayError(
                'a prior software STOP is already unverified; STOP is not '
                'retried')
        detail = _safe_stop_reason(reason, 'stop requested')
        previous_fault = (
            self.fault_reason
            if self.state == GripperGatewayState.FAULT_LATCHED else '')
        stop_epoch = self._advance_state_epoch()
        self._stop_unverified = True
        self._stop_send_in_progress = True
        self.state = GripperGatewayState.STOPPING
        self.fault_reason = (
            '{}; STOP requested: {}'.format(previous_fault, detail)
            if previous_fault else detail)
        self._stop_started_at = None
        self._reset_stationary_evidence()
        self._fault_stationary_verified = False
        return stop_epoch, detail, previous_fault

    def _commit_stop_request_locked(self, stop_epoch, stop_started_at):
        self._require_current_epoch(stop_epoch, 'STOP preparation')
        self._stop_started_at = stop_started_at

    def _commit_successful_stop_locked(self, stop_epoch, stop_completed_at):
        """Start verification only after the STOP transport call returned."""
        self._require_current_epoch(stop_epoch, 'STOP completion')
        self._stop_started_at = stop_completed_at
        self._stop_send_in_progress = False
        self._internal_stop_requires_physical = False
        self._reset_stationary_evidence()
        self._fault_stationary_verified = False
        # Any feedback captured before STOP returned belongs to the old epoch.
        self._advance_state_epoch()
        if self._motion_send_in_progress:
            self._escalate_physical_stop(
                'STOP returned while a pre-STOP motion transport call '
                'remains in progress, so STOP ordering cannot be verified')

    def acknowledge_local_fault(
            self, authorization_id, expected_session_id):
        """Clear only a local latch after fresh stationary evidence."""
        self._reject_reentrant_public_operation('acknowledge_local_fault')
        with self._lock:
            ack_epoch, snapshot = self._capture_fault_ack_state(
                expected_session_id)
        self._read_clock(
            'fault ACK timing clock', expected_epoch=ack_epoch)
        resolved_authorization = self._require_authorization(
            authorization_id, 'ack')
        final_now = self._read_clock(
            'final fault ACK freshness clock', expected_epoch=ack_epoch)
        with self._lock:
            return self._commit_fault_ack(
                resolved_authorization,
                expected_session_id,
                ack_epoch,
                snapshot,
                final_now,
            )

    def _capture_fault_ack_state(self, expected_session_id):
        self._ensure_open()
        self._require_session(expected_session_id)
        if self.physical_stop_required:
            raise GripperMotionRejected(self._physical_stop_message())
        if self._motion_send_in_progress:
            raise GripperMotionRejected(
                'a pre-STOP motion transport call is still in progress')
        self._require_identity_ready()
        if self.state != GripperGatewayState.FAULT_LATCHED:
            raise GripperMotionRejected('no local fault is latched')
        if self.snapshot is None:
            raise GripperMotionRejected(
                'fresh stationary healthy feedback is required')
        if not self._fault_stationary_verified:
            raise GripperMotionRejected(
                'stationary state has not been verified across samples')
        if self._stop_unverified:
            raise GripperMotionRejected(
                'software STOP has not been verified stationary')
        if self._stop_send_in_progress:
            raise GripperMotionRejected(
                'software STOP send is still in progress')
        return self._state_epoch, self.snapshot

    def _commit_fault_ack(
            self,
            resolved_authorization,
            expected_session_id,
            expected_epoch,
            snapshot,
            now):
        self._require_current_epoch(expected_epoch, 'fault ACK')
        current_epoch, current_snapshot = self._capture_fault_ack_state(
            expected_session_id)
        if current_epoch != expected_epoch or current_snapshot is not snapshot:
            raise GripperMotionRejected(
                'gripper state changed during fault ACK validation')
        if not snapshot.motion_ready(now, self._policy.state_max_age_s):
            raise GripperMotionRejected(
                'fresh stationary healthy feedback is required')
        if resolved_authorization in self._used_authorization_ids:
            raise GripperMotionRejected(
                'authorization_id has already been consumed')
        if self.active_command is not None:
            self.last_result = GripperCommandResult(
                command_id=self.active_command.command_id,
                success=False,
                detail=self.fault_reason or 'fault acknowledged',
                finished_at=now,
            )
            self.active_command = None
        self._advance_state_epoch()
        self.fault_reason = ''
        self.state = GripperGatewayState.READY
        self._used_authorization_ids.add(resolved_authorization)
        self._reset_stationary_evidence()
        self._fault_stationary_verified = False
        self._stop_unverified = False
        return True

    def close(self):
        """Close transport and report any unresolved motion safety state."""
        self._reject_reentrant_public_operation('close')
        with self._close_lock:
            with self._lock:
                close_plan = self._close_locked()
            if close_plan is None:
                return
            needs_stop, errors, report_unresolved_safety = close_plan
            if needs_stop:
                try:
                    self._send_stop_attempt()
                except Exception as error:
                    with self._lock:
                        detail = 'shutdown STOP failed: {}'.format(
                            type(error).__name__)
                        errors.append(detail)
                        self._escalate_physical_stop(detail)
                else:
                    with self._lock:
                        self._stop_send_in_progress = False
                        errors.append(
                            'shutdown STOP sent once; stationary state is not '
                            'verified')
                        self._escalate_physical_stop(
                            'gateway closed before shutdown STOP stationary '
                            'verification')
            close_error = None
            close_attempted, close_error = (
                self._try_close_backend_without_stop_overlap())
            with self._lock:
                if not close_attempted:
                    errors.append(
                        'backend close deferred until the in-flight STOP '
                        'transport call returns')
                elif close_error is not None:
                    errors.append('backend close failed: {}'.format(
                        type(close_error).__name__))
                self.state = GripperGatewayState.CLOSED
                self.active_command = None
                self._reset_stationary_evidence()
                if report_unresolved_safety and self.physical_stop_required:
                    physical_message = self._physical_stop_message()
                    if physical_message not in errors:
                        errors.append(physical_message)
            if errors:
                raise GripperGatewayError('; '.join(errors))

    def _close_locked(self):
        if self.state == GripperGatewayState.CLOSED:
            if self._backend_close_complete:
                return None
            return False, [], False
        self._close_started = True
        errors = []
        active_at_close = (
            self.active_command is not None
            or self._motion_send_in_progress
            or self._stop_send_in_progress)
        stopping_at_close = self.state == GripperGatewayState.STOPPING
        unverified_at_close = self._stop_unverified
        needs_stop = (
            active_at_close
            and not stopping_at_close
            and not unverified_at_close
            and not self.physical_stop_required
        )
        if (
                active_at_close
                or stopping_at_close
                or unverified_at_close):
            if not needs_stop:
                detail = 'gateway closed while motion safety was not verified'
                errors.append(detail)
                if not self.physical_stop_required:
                    self._escalate_physical_stop(detail)
        self._advance_state_epoch()
        self.state = GripperGatewayState.CLOSED
        return needs_stop, errors, True

    def _close_backend(self):
        self._call_external_method(
            'backend close', self._backend, 'close')
        self._backend_close_complete = True

    def _try_close_backend_without_stop_overlap(self):
        acquired = self._stop_lock.acquire(blocking=False)
        if not acquired:
            return False, None
        try:
            try:
                self._close_backend()
            except Exception as error:
                return True, error
            return True, None
        finally:
            self._stop_lock.release()

    def _complete_deferred_backend_close(self):
        with self._close_lock:
            with self._lock:
                if (
                        self.state != GripperGatewayState.CLOSED
                        or self._backend_close_complete):
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

    def _validated_snapshot(self, sample, observed_at):
        if type(sample) is not dict:
            raise ValueError('state sample must be an exact dictionary')
        sequence = sample.get('sequence')
        if (
                type(sequence) is not int
                or sequence < 1):
            raise ValueError('state sequence must be a positive integer')
        sample_timestamp = sample.get('sample_timestamp')
        if (
                type(sample_timestamp) not in (int, float)
                or not math.isfinite(float(sample_timestamp))
                or float(sample_timestamp) < 0.0):
            raise ValueError(
                'sample_timestamp must be finite and non-negative')
        command_id = sample.get('command_id')
        if type(command_id) is not str:
            raise ValueError('command_id must be an exact string')
        identities = {}
        for name in (
                'tool_model',
                'tool_revision',
                'controller_identity',
                'transport_identity',
                'protocol_identity',
                'controller_boot_id'):
            value = sample.get(name)
            if (
                    type(value) is not str
                    or not value
                    or value != value.strip()):
                raise _GripperIdentityValidationError(
                    '{} must be a non-empty identity string without '
                    'surrounding whitespace'.format(name))
            identities[name] = value
        fault_code = sample.get('fault_code')
        if (
                type(fault_code) is not int
                or fault_code < 0):
            raise ValueError('fault_code must be a non-negative integer')
        for name in ('connected', 'valid', 'enabled', 'moving'):
            if type(sample.get(name)) is not bool:
                raise ValueError('{} must be a boolean'.format(name))
        return GripperSnapshot(
            observed_at=observed_at,
            sample_timestamp=float(sample_timestamp),
            sequence=sequence,
            command_id=command_id,
            tool_model=identities['tool_model'],
            tool_revision=identities['tool_revision'],
            controller_identity=identities['controller_identity'],
            transport_identity=identities['transport_identity'],
            protocol_identity=identities['protocol_identity'],
            controller_boot_id=identities['controller_boot_id'],
            connected=sample['connected'],
            valid=sample['valid'],
            enabled=sample['enabled'],
            moving=sample['moving'],
            position=normalized_value(sample.get('position'), 'position'),
            fault_code=fault_code,
        )

    @staticmethod
    def _snapshot_issue(snapshot):
        if not snapshot.connected:
            return 'gripper is disconnected'
        if not snapshot.valid:
            return 'gripper feedback is invalid'
        if not snapshot.enabled:
            return 'gripper is not enabled'
        if snapshot.fault_code != 0:
            return 'gripper fault code is {}'.format(snapshot.fault_code)
        return ''

    def _snapshot_identity_issue(self, snapshot):
        expected = (
            ('tool_model', self._policy.reviewed_tool_model),
            ('tool_revision', self._policy.reviewed_tool_revision),
            ('controller_identity',
             self._policy.reviewed_controller_identity),
            ('transport_identity', self._policy.reviewed_transport_identity),
            ('protocol_identity', self._policy.reviewed_protocol_identity),
        )
        for name, reviewed in expected:
            observed = getattr(snapshot, name)
            if observed != reviewed:
                return '{} mismatch: reviewed={!r}, observed={!r}'.format(
                    name, reviewed, observed)
        return ''

    def _update_executing(self, snapshot):
        if self.active_command is None:
            self._latch_fault('EXECUTING without an active command')
            return ''
        now = snapshot.observed_at
        if now - self.active_command.started_at > (
                self._policy.command_timeout_s):
            return self._prepare_internal_stop_locked('command timeout')
        if snapshot.command_id != self.active_command.command_id:
            self._reset_completion_evidence()
            return self._prepare_internal_stop_locked(
                'feedback command id mismatch or rollback')
        if snapshot.moving:
            self._reset_completion_evidence()
            return ''
        if abs(snapshot.position - self.active_command.position) <= (
                self._policy.position_tolerance):
            if (
                    self._last_completion_sequence is not None
                    and (
                        snapshot.sequence <= self._last_completion_sequence
                        or snapshot.sample_timestamp <= (
                            self._last_completion_timestamp))):
                self._reset_completion_evidence()
                return ''
            if (
                    self._last_completion_position is not None
                    and abs(
                        snapshot.position - self._last_completion_position)
                    > self._policy.position_tolerance):
                self._reset_completion_evidence()
            self._last_completion_sequence = snapshot.sequence
            self._last_completion_timestamp = snapshot.sample_timestamp
            self._last_completion_position = snapshot.position
            self._stable_samples += 1
            if self._completion_stable_since is None:
                self._completion_stable_since = now
            dwell = now - self._completion_stable_since
            if not math.isfinite(dwell) or dwell < 0.0:
                self._escalate_physical_stop(
                    'command completion dwell timing is invalid')
                return ''
            if (
                    self._stable_samples
                    < self._policy.stable_samples_required
                    or dwell < self._policy.stationary_dwell_s):
                return ''
            self.last_result = GripperCommandResult(
                command_id=self.active_command.command_id,
                success=True,
                detail='command verified by fresh feedback',
                finished_at=now,
            )
            self.active_command = None
            self._reset_completion_evidence()
            self.state = GripperGatewayState.READY
            return ''
        self._reset_completion_evidence()
        return self._prepare_internal_stop_locked(
            'motion stopped outside position tolerance')

    def _update_stopping(self, snapshot):
        if (
                self._stop_send_in_progress
                or self._motion_send_in_progress):
            self._reset_stationary_evidence()
            self._fault_stationary_verified = False
            return
        if self._stop_started_at is None:
            self._escalate_physical_stop(
                'STOPPING without a start timestamp')
            return
        now = snapshot.observed_at
        elapsed = now - self._stop_started_at
        if not math.isfinite(elapsed) or elapsed < 0.0:
            self._escalate_physical_stop('STOP timing is invalid')
            return
        if elapsed > self._policy.stop_timeout_s:
            self._escalate_physical_stop(
                'STOP verification timeout before stationary evidence')
            return
        if snapshot.moving:
            self._reset_stationary_evidence()
            return
        if (
                self.active_command is not None
                and snapshot.command_id != self.active_command.command_id):
            self._reset_stationary_evidence()
            self._fault_stationary_verified = False
            self._latch_fault(
                'STOP feedback command id mismatch or rollback')
            return
        self._record_stationary_sample(snapshot)
        if self._stationary_evidence_complete(now):
            if self.active_command is not None:
                self.last_result = GripperCommandResult(
                    command_id=self.active_command.command_id,
                    success=False,
                    detail=self.fault_reason or 'STOP completed',
                    finished_at=now,
                )
                self.active_command = None
            self._fault_stationary_verified = True
            self._stop_unverified = False
            self._latch_fault(self.fault_reason or 'STOP completed')

    def _record_stationary_sample(self, snapshot):
        if self._snapshot_issue(snapshot) or snapshot.moving:
            self._reset_stationary_evidence()
            return
        if (
                self._last_stationary_sequence is not None
                and (
                    snapshot.sequence <= self._last_stationary_sequence
                    or snapshot.sample_timestamp <= (
                        self._last_stationary_timestamp))):
            self._reset_stationary_evidence()
            return
        if (
                self._last_stationary_position is not None
                and abs(snapshot.position - self._last_stationary_position)
                > self._policy.stationary_position_tolerance):
            self._reset_stationary_evidence()
            return
        if self._stationary_since is None:
            self._stationary_since = snapshot.observed_at
        self._last_stationary_sequence = snapshot.sequence
        self._last_stationary_timestamp = snapshot.sample_timestamp
        self._last_stationary_position = snapshot.position
        self._stable_samples += 1

    def _stationary_evidence_complete(self, now):
        if (
                self._stable_samples < self._policy.stable_samples_required
                or self._stationary_since is None):
            return False
        dwell = float(now) - self._stationary_since
        if not math.isfinite(dwell) or dwell < 0.0:
            self._escalate_physical_stop(
                'stationary dwell timing is non-finite or moved backwards')
            return False
        return dwell >= self._policy.stationary_dwell_s

    def _reset_stationary_evidence(self):
        self._stable_samples = 0
        self._last_stationary_sequence = None
        self._last_stationary_timestamp = None
        self._last_stationary_position = None
        self._stationary_since = None

    def _reset_completion_evidence(self):
        self._stable_samples = 0
        self._last_completion_sequence = None
        self._last_completion_timestamp = None
        self._last_completion_position = None
        self._completion_stable_since = None

    def _prepare_internal_stop_locked(
            self, reason, require_physical_after_send=False):
        if self.state == GripperGatewayState.STOPPING:
            return ''
        if self.physical_stop_required or self._stop_unverified:
            self._escalate_physical_stop(
                '{}; motion safety remains unresolved'.format(reason))
            return ''
        self._advance_state_epoch()
        self._stop_unverified = True
        self._stop_send_in_progress = True
        self._internal_stop_requires_physical = (
            require_physical_after_send)
        self.state = GripperGatewayState.STOPPING
        self.fault_reason = _safe_stop_reason(reason, 'stop requested')
        self._stop_started_at = None
        self._reset_stationary_evidence()
        self._fault_stationary_verified = False
        return self.fault_reason

    def _attempt_internal_stop(self, reason, unused_expected_epoch):
        with self._lock:
            stop_epoch = self._state_epoch
        try:
            stop_started_at = self._read_clock(
                'STOP timing clock', expected_epoch=stop_epoch)
            with self._lock:
                self._require_current_epoch(
                    stop_epoch, 'internal STOP preparation')
                self._stop_started_at = stop_started_at
            self._send_stop_attempt(expected_epoch=stop_epoch)
            stop_completed_at = self._read_clock(
                'internal STOP completion timing clock',
                expected_epoch=stop_epoch)
        except Exception as error:
            with self._lock:
                self._stop_send_in_progress = False
                self._internal_stop_requires_physical = False
                closed = self.state == GripperGatewayState.CLOSED
                if not closed:
                    self._escalate_physical_stop(
                        '{}; internal STOP failed: {}'.format(
                            reason, type(error).__name__))
            if closed:
                self._complete_deferred_backend_close()
            return False
        with self._lock:
            if self.state == GripperGatewayState.CLOSED:
                self._stop_send_in_progress = False
                self._internal_stop_requires_physical = False
                closed = True
            else:
                self._require_current_epoch(stop_epoch, 'internal STOP result')
                require_physical = self._internal_stop_requires_physical
                self._commit_successful_stop_locked(
                    stop_epoch, stop_completed_at)
                if require_physical and not self._physical_stop_required:
                    self._escalate_physical_stop(
                        '{}; one best-effort STOP was sent but stationary '
                        'state is unverified'.format(reason))
                return True
        if closed:
            self._complete_deferred_backend_close()
        return False

    def _latch_fault(self, reason):
        self._advance_state_epoch()
        resolved = _internal_text(reason, 'unspecified fault')
        if (
                self.physical_stop_required
                and self._physical_stop_message() not in resolved):
            resolved += '; ' + self._physical_stop_message()
        self.fault_reason = resolved
        self.state = GripperGatewayState.FAULT_LATCHED

    def _handle_motion_uncertainty_locked(
            self, detail, observed_moving=False):
        """Route unhealthy or untrusted motion through one STOP reservation."""
        self._reset_stationary_evidence()
        self._fault_stationary_verified = False
        motion_safety_unresolved = (
            observed_moving is True or self._motion_safety_unresolved())
        if not motion_safety_unresolved:
            self._latch_fault(detail)
            return ''
        if (
                self._physical_stop_required
                or self._stop_unverified
                or self._stop_send_in_progress
                or self.state == GripperGatewayState.STOPPING):
            self._escalate_physical_stop(
                '{}; motion safety remains unresolved'.format(detail))
            return ''
        return self._prepare_internal_stop_locked(
            detail, require_physical_after_send=True)

    def _handle_state_query_failure(self, detail):
        """Compatibility wrapper for existing internal call sites."""
        return self._handle_motion_uncertainty_locked(detail)

    def _read_clock(self, context, expected_epoch=None):
        try:
            now = self._call_external(context, self._clock)
        except Exception as error:
            detail = '{} failed: {}'.format(context, type(error).__name__)
            with self._lock:
                if expected_epoch is not None:
                    self._require_current_epoch(expected_epoch, context)
                if self._motion_safety_unresolved():
                    self._escalate_physical_stop(detail)
                else:
                    self._latch_fault(detail)
                reported = self.fault_reason
            raise GripperGatewayError(reported) from error
        if (
                type(now) not in (int, float)
                or not math.isfinite(float(now))):
            detail = '{} received a non-finite clock value'.format(context)
            with self._lock:
                if expected_epoch is not None:
                    self._require_current_epoch(expected_epoch, context)
                self._escalate_physical_stop(detail)
                reported = self.fault_reason
            raise GripperGatewayError(reported)
        resolved = float(now)
        with self._lock:
            if expected_epoch is not None:
                self._require_current_epoch(expected_epoch, context)
            if (
                    self._last_clock_value is not None
                    and resolved < self._last_clock_value):
                detail = '{} moved backwards'.format(context)
                self._escalate_physical_stop(detail)
                raise GripperGatewayError(self.fault_reason)
            self._last_clock_value = resolved
        return resolved

    def _motion_safety_unresolved(self):
        return (
            self._physical_stop_required
            or self._stop_unverified
            or self._motion_send_in_progress
            or self._stop_send_in_progress
            or self.active_command is not None
            or self.state in (
                GripperGatewayState.EXECUTING,
                GripperGatewayState.STOPPING)
            or (
                self.snapshot is not None
                and self.snapshot.moving is True)
        )

    def _escalate_physical_stop(self, reason):
        self._physical_stop_required = True
        self._fault_stationary_verified = False
        self._reset_stationary_evidence()
        detail = '{}; {}'.format(reason, self._physical_stop_message())
        if self.state == GripperGatewayState.CLOSED:
            self._advance_state_epoch()
            self.fault_reason = detail
            return
        self._latch_fault(detail)

    def _advance_state_epoch(self):
        self._state_epoch += 1
        return self._state_epoch

    def _require_current_epoch(self, expected_epoch, context):
        if self._state_epoch != expected_epoch:
            raise GripperGatewayError(
                '{} was superseded by a newer STOP/close/fault epoch'.format(
                    context))

    def _require_current_refresh(
            self, expected_epoch, expected_generation, context):
        self._require_current_epoch(expected_epoch, context)
        if self._refresh_generation != expected_generation:
            raise GripperGatewayError(
                '{} was superseded by a newer refresh generation'.format(
                    context))

    def _send_stop_attempt(self, expected_epoch=None):
        with self._stop_lock:
            with self._lock:
                if expected_epoch is not None:
                    self._require_current_epoch(
                        expected_epoch, 'STOP attempt')
                if self._physical_stop_required:
                    raise GripperGatewayError(self._physical_stop_message())
                if not self._independent_stop_is_proven():
                    self._escalate_physical_stop(
                        'transport cannot prove a bounded independent STOP '
                        'channel')
                    raise GripperGatewayError(self.fault_reason)
            try:
                self._call_external_method(
                    'backend stop', self._backend, 'stop')
            except Exception as error:
                raise GripperGatewayError(
                    'backend STOP failed: {}'.format(
                        type(error).__name__)) from error
            with self._lock:
                if expected_epoch is not None:
                    self._require_current_epoch(
                        expected_epoch, 'STOP result')

    def _read_backend_capabilities(self):
        """Read static safety evidence without calling an adapter method.

        Capability discovery is intentionally an MRO class-dictionary lookup:
        a method/property can open a transport, block, or lie after observing
        a device.  No backend code is invoked during this construction gate.
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
            'execution_mode',
            'bounded_calls_enforced',
            'method_deadlines_s',
            'native_deadline_enforced',
            'native_cancel_enforced',
            'independent_stop_channel',
            'independent_stop_lock_domain',
            'stop_not_queued_behind_commands',
            'release_binding',
            'persistent_latch_binding',
        }
        if set(capabilities) != expected:
            raise ValueError(
                'backend safety capability keys do not match the contract')
        for name in (
                'bounded_calls_enforced', 'native_deadline_enforced',
                'native_cancel_enforced',
                'independent_stop_channel', 'independent_stop_lock_domain',
                'stop_not_queued_behind_commands'):
            if type(capabilities[name]) is not bool:
                raise ValueError(
                    'backend safety capability {} must be a boolean'.format(
                        name))
        if type(capabilities['execution_mode']) is not str:
            raise ValueError(
                'backend execution mode must be an exact string')
        if capabilities['execution_mode'] != self._policy.backend_execution_mode:
            raise ValueError(
                'backend execution mode does not match policy-owned mode')
        if not all((
                capabilities['bounded_calls_enforced'],
                capabilities['native_deadline_enforced'],
                capabilities['native_cancel_enforced'],
                capabilities['independent_stop_channel'],
                capabilities['independent_stop_lock_domain'],
                capabilities['stop_not_queued_behind_commands'])):
            raise ValueError(
                'backend is DISABLED/BLOCKED without native bounded calls, '
                'cancellation and independent STOP isolation')
        deadlines = capabilities['method_deadlines_s']
        if type(deadlines) is not dict or set(deadlines) != {
                'read_state', 'command_position', 'stop', 'close'}:
            raise ValueError(
                'backend method deadlines must be an exact dictionary')
        for name, deadline in deadlines.items():
            if (
                    type(deadline) not in (int, float)
                    or not math.isfinite(float(deadline))
                    or float(deadline) <= 0.0):
                raise ValueError(
                    'backend method deadline {} must be positive and finite'
                    .format(name))
        if self._policy.backend_execution_mode == 'REAL':
            expected_binding = {
                'runtime_release_id': self._policy.runtime_release_id,
                'release_manifest_sha256': (
                    self._policy.release_manifest_sha256),
                'motion_profile_id': self._policy.motion_profile_id,
                'motion_profile_manifest_sha256': (
                    self._policy.motion_profile_manifest_sha256),
                'motion_profile_runtime_release_id': (
                    self._policy.motion_profile_runtime_release_id),
                'approved_speed_grades': self._policy.approved_speed_grades,
                'backend_method_contract_sha256': (
                    self._policy.backend_method_contract_sha256),
                'stop_isolation_architecture_sha256': (
                    self._policy.stop_isolation_architecture_sha256),
                'hung_command_stop_test_report_sha256': (
                    self._policy.hung_command_stop_test_report_sha256),
            }
            release_binding = capabilities['release_binding']
            if (
                    type(release_binding) is not dict
                    or set(release_binding) != set(expected_binding)):
                raise ValueError(
                    'real backend release binding must be an exact dictionary')
            for name, expected_value in expected_binding.items():
                value = release_binding[name]
                if type(value) is not type(expected_value):
                    raise ValueError(
                        'real backend release binding {} has an inexact type'
                        .format(name))
            if release_binding != expected_binding:
                raise ValueError(
                    'real backend is DISABLED/BLOCKED without exact approved '
                    'manifest SHA, runtime release, motion profile, execution '
                    'safety evidence and speed grade binding')
            if (
                    capabilities['persistent_latch_binding']
                    != self._policy.persistent_latch_binding):
                raise ValueError(
                    'real backend is DISABLED/BLOCKED without exact '
                    'persistent latch/release binding')
            raise ValueError(
                'real backend is DISABLED/BLOCKED: matching static metadata '
                'is necessary but cannot independently verify native '
                'deadlines, cancellation, physical STOP isolation or the '
                'persistent-latch supervisor attestation')
        elif (
                capabilities['release_binding'] is not None
                or capabilities['persistent_latch_binding'] is not None):
            raise ValueError(
                'PURE_FAKE backend must not claim real release evidence')
        return dict(capabilities)

    def _independent_stop_is_proven(self):
        return (
            self._backend_capabilities['bounded_calls_enforced']
            and self._backend_capabilities['native_deadline_enforced']
            and self._backend_capabilities['independent_stop_channel']
            and self._backend_capabilities['native_cancel_enforced']
            and self._backend_capabilities['independent_stop_lock_domain']
            and self._backend_capabilities['stop_not_queued_behind_commands']
        )

    def _send_uncredited_emergency_stop(self):
        if not self._independent_stop_is_proven():
            raise GripperGatewayError(
                'transport cannot prove an independent STOP channel')
        acquired = self._stop_lock.acquire(blocking=False)
        if not acquired:
            raise GripperGatewayError(
                'another STOP transport call is already in progress; '
                'no second software STOP is credited and physical '
                'isolation remains required')
        try:
            with self._lock:
                if self.state == GripperGatewayState.CLOSED:
                    return False
                if self._stop_send_in_progress:
                    raise GripperGatewayError(
                        'a STOP transaction is awaiting completion commit; '
                        'no second software STOP is credited')
            self._call_external_method(
                'backend emergency stop', self._backend, 'stop')
        except Exception as error:
            if isinstance(error, GripperGatewayError):
                raise
            raise GripperGatewayError(
                'emergency STOP failed: {}'.format(
                    type(error).__name__)) from error
        finally:
            self._stop_lock.release()
            with self._lock:
                closed = self.state == GripperGatewayState.CLOSED
            if closed:
                self._complete_deferred_backend_close()
        return True

    def _require_command_activation_state(self, expected_epoch):
        if (
                self._state_epoch == expected_epoch
                and self.state == GripperGatewayState.READY
                and not self.physical_stop_required):
            return
        detail = (
            'gripper command send completed after a newer STOP/close/fault '
            'epoch or after the gateway left READY; command activation is '
            'refused')
        self.active_command = None
        self._reset_completion_evidence()
        if self.state == GripperGatewayState.CLOSED:
            resolved = self.fault_reason or detail
            if 'gateway is closed' not in resolved:
                resolved += '; gateway is closed'
            raise GripperGatewayError(resolved)
        self._escalate_physical_stop(detail)
        raise GripperGatewayError(self.fault_reason or detail)

    def _lock_identity(self, reason, observed_moving=False):
        """Permanently reject this process session after identity drift."""
        resolved = _internal_text(reason, 'gripper identity is unresolved')
        self._identity_lockout = True
        self._identity_lockout_reason = (
            '{}; a new gateway process session and reviewed identity are '
            'required'.format(resolved))
        self._reset_stationary_evidence()
        self._fault_stationary_verified = False
        return self._handle_motion_uncertainty_locked(
            self._identity_lockout_reason,
            observed_moving=observed_moving)

    @staticmethod
    def _physical_stop_message():
        return (
            'PHYSICAL EMERGENCY STOP AND POWER ISOLATION REQUIRED; local '
            'ACK, motion, and further software STOP are prohibited until a '
            'new gateway process session starts after onsite safety '
            'verification'
        )

    def _require_session(self, expected_session_id):
        if (
                type(expected_session_id) is not str
                or not expected_session_id.strip()
                or expected_session_id != self.session_id):
            raise GripperMotionRejected('stale or empty session id')

    def _require_tool_revision(self, expected_tool_revision):
        resolved = (
            expected_tool_revision
            if type(expected_tool_revision) is str else '')
        if (
                not resolved
                or resolved != resolved.strip()
                or resolved != self._policy.reviewed_tool_revision):
            raise GripperMotionRejected(
                'expected_tool_revision does not match the reviewed tool '
                'revision')

    def _require_identity_ready(self):
        if self._identity_lockout:
            raise GripperMotionRejected(self._identity_lockout_reason)
        if self.snapshot is None or self._controller_boot_id is None:
            raise GripperMotionRejected(
                'reviewed gripper identity has not been observed')
        issue = self._snapshot_identity_issue(self.snapshot)
        if issue:
            self._lock_identity(issue)
            raise GripperMotionRejected(self._identity_lockout_reason)
        if self.snapshot.controller_boot_id != self._controller_boot_id:
            self._lock_identity('controller_boot_id changed')
            raise GripperMotionRejected(self._identity_lockout_reason)

    def _require_authorization(self, authorization_id, purpose):
        """Run an injected pure, local and bounded authorization check."""
        resolved = (
            authorization_id.strip()
            if type(authorization_id) is str else '')
        if not resolved:
            raise GripperMotionRejected('authorization_id is required')
        with self._lock:
            if resolved in self._used_authorization_ids:
                raise GripperMotionRejected(
                    'authorization_id has already been consumed')
            validator = self._authorization_validator
        if validator is None:
            raise GripperMotionRejected(
                'authorization validator is not configured')
        try:
            accepted = self._call_external(
                'authorization validator',
                validator,
                resolved,
                purpose,
                self.session_id,
            )
        except Exception as error:
            raise GripperMotionRejected(
                'authorization validation failed: {}'.format(
                    type(error).__name__)) from error
        if accepted is not True:
            raise GripperMotionRejected(
                'authorization_id does not match {} purpose'.format(purpose))
        return resolved

    def _ensure_open(self):
        if self._close_started or self.state == GripperGatewayState.CLOSED:
            raise GripperGatewayError('gripper gateway is closed')

    def _reject_reentrant_public_operation(self, operation):
        if self._external_call_depth() > 0:
            raise GripperGatewayError(
                'reentrant gateway {} is prohibited during {}'.format(
                    operation, self._external_call_context()))

    def _external_call_depth(self):
        return getattr(self._external_call_state, 'depth', 0)

    def _external_call_context(self):
        return getattr(self._external_call_state, 'context', '')

    def _call_external(self, context, callback, *args):
        """Run one injected call while prohibiting same-thread reentry."""
        if self._external_call_depth() > 0:
            raise GripperGatewayError(
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
        """Guard injected method lookup, validation and invocation together."""
        if self._external_call_depth() > 0:
            raise GripperGatewayError(
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
