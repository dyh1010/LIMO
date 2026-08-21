"""Dependency-free fail-closed AMCL convergence policy for LIMO V1."""

from collections import deque
from dataclasses import asdict, dataclass
import math


STARTUP = 'STARTUP'
WAIT_INITIAL_POSE = 'WAIT_INITIAL_POSE'
CONVERGING = 'CONVERGING'
READY = 'READY'
BLOCKED = 'BLOCKED'


def angular_distance(left, right):
    """Return the smallest absolute angular separation in radians."""
    return abs(math.atan2(math.sin(left - right), math.cos(left - right)))


def planar_yaw(x, y, z, w, norm_tolerance=1e-3, tilt_tolerance=0.02):
    """Validate a normalized near-planar quaternion and return its yaw."""
    values = (x, y, z, w, norm_tolerance, tilt_tolerance)
    if not _finite(values):
        raise ValueError('quaternion values and tolerances must be finite')
    if norm_tolerance <= 0.0 or tilt_tolerance < 0.0:
        raise ValueError('quaternion tolerances are invalid')
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if abs(norm - 1.0) > norm_tolerance:
        raise ValueError('quaternion must be normalized')
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    if abs(roll) > tilt_tolerance or abs(pitch) > tilt_tolerance:
        raise ValueError('quaternion contains non-planar roll or pitch')
    return math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z))


@dataclass(frozen=True)
class ConvergenceConfig:
    """All thresholds are explicit and expressed in SI units."""

    chain_timeout_s: float = 15.0
    initial_pose_timeout_s: float = 300.0
    convergence_timeout_s: float = 30.0
    message_timeout_s: float = 0.5
    future_tolerance_s: float = 0.10
    stable_window_s: float = 3.0
    stable_min_samples: int = 8
    max_covariance_x: float = 0.010
    max_covariance_y: float = 0.010
    max_covariance_yaw: float = 0.010
    max_stable_position_span_m: float = 0.050
    max_stable_yaw_span_rad: float = 0.050
    max_ready_position_jump_m: float = 0.100
    max_ready_yaw_jump_rad: float = 0.100
    nomotion_update_period_s: float = 1.0
    min_nomotion_updates: int = 10
    max_consecutive_nomotion_failures: int = 2
    max_initial_covariance_xy: float = 4.0
    max_initial_covariance_yaw: float = 3.0

    def validate(self):
        numeric_positive = (
            'chain_timeout_s', 'initial_pose_timeout_s',
            'convergence_timeout_s', 'message_timeout_s',
            'stable_window_s', 'max_covariance_x', 'max_covariance_y',
            'max_covariance_yaw', 'max_stable_position_span_m',
            'max_stable_yaw_span_rad', 'max_ready_position_jump_m',
            'max_ready_yaw_jump_rad', 'nomotion_update_period_s',
            'max_initial_covariance_xy', 'max_initial_covariance_yaw')
        for name in numeric_positive:
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError('{} must be numeric'.format(name))
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError('{} must be finite and positive'.format(name))
        if (
                not math.isfinite(self.future_tolerance_s)
                or self.future_tolerance_s < 0.0):
            raise ValueError('future_tolerance_s must be finite and nonnegative')
        for name in (
                'stable_min_samples', 'min_nomotion_updates',
                'max_consecutive_nomotion_failures'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError('{} must be a positive integer'.format(name))
        if self.stable_min_samples < 2:
            raise ValueError('stable_min_samples must be at least two')
        if self.message_timeout_s > self.chain_timeout_s:
            raise ValueError('message timeout cannot exceed chain timeout')


@dataclass(frozen=True)
class ChainEvidence:
    """One continuously evaluated map/sensor/TF/owner snapshot."""

    ok: bool
    reason: str
    observed_monotonic: float


@dataclass(frozen=True)
class InitialPoseEvidence:
    """Validated planar initial pose supplied by a human or bound file."""

    received_monotonic: float
    source_stamp: float
    ros_now: float
    frame_id: str
    x: float
    y: float
    yaw: float
    covariance_x: float
    covariance_y: float
    covariance_yaw: float
    source: str = 'topic'


@dataclass(frozen=True)
class PoseEstimate:
    """Planar AMCL estimate and the three covariance diagonal entries."""

    received_monotonic: float
    source_stamp: float
    ros_now: float
    frame_id: str
    x: float
    y: float
    yaw: float
    covariance_x: float
    covariance_y: float
    covariance_yaw: float


def _finite(values):
    return all(isinstance(value, (int, float))
               and not isinstance(value, bool)
               and math.isfinite(float(value)) for value in values)


def _validate_message_time(received, source_stamp, ros_now, now, config):
    if not _finite((received, source_stamp, ros_now, now)):
        raise ValueError('message timestamps must be finite')
    receive_age = now - received
    source_age = ros_now - source_stamp
    if receive_age < 0.0 or receive_age >= config.message_timeout_s:
        raise ValueError('message receive time is stale or future-dated')
    if source_stamp <= 0.0 or ros_now <= 0.0:
        raise ValueError('ROS source time must be positive')
    if not (-config.future_tolerance_s
            <= source_age < config.message_timeout_s):
        raise ValueError('message source time is stale or future-dated')


def validate_initial_pose(evidence, now, config):
    """Reject missing, stale, non-map, non-finite, or overbroad initial poses."""
    if not isinstance(evidence, InitialPoseEvidence):
        raise ValueError('initial pose evidence has the wrong type')
    _validate_message_time(
        evidence.received_monotonic, evidence.source_stamp,
        evidence.ros_now, now, config)
    if evidence.frame_id != 'map':
        raise ValueError('initial pose frame must be map')
    values = (
        evidence.x, evidence.y, evidence.yaw,
        evidence.covariance_x, evidence.covariance_y,
        evidence.covariance_yaw)
    if not _finite(values):
        raise ValueError('initial pose values must be finite')
    if not all(value > 0.0 for value in (
            evidence.covariance_x, evidence.covariance_y,
            evidence.covariance_yaw)):
        raise ValueError('initial pose covariance diagonal must be positive')
    if (
            evidence.covariance_x > config.max_initial_covariance_xy
            or evidence.covariance_y > config.max_initial_covariance_xy
            or evidence.covariance_yaw > config.max_initial_covariance_yaw):
        raise ValueError('initial pose covariance exceeds the accepted bound')
    if evidence.source not in ('topic', 'persisted'):
        raise ValueError('initial pose source must be topic or persisted')
    return evidence


def validate_estimate(estimate, now, config):
    """Validate AMCL message timing, frame, values, and covariance domain."""
    if not isinstance(estimate, PoseEstimate):
        raise ValueError('AMCL estimate has the wrong type')
    _validate_message_time(
        estimate.received_monotonic, estimate.source_stamp,
        estimate.ros_now, now, config)
    if estimate.frame_id != 'map':
        raise ValueError('AMCL estimate frame must be map')
    values = (
        estimate.x, estimate.y, estimate.yaw,
        estimate.covariance_x, estimate.covariance_y,
        estimate.covariance_yaw)
    if not _finite(values):
        raise ValueError('AMCL estimate values must be finite')
    if any(value < 0.0 for value in (
            estimate.covariance_x, estimate.covariance_y,
            estimate.covariance_yaw)):
        raise ValueError('AMCL covariance diagonal cannot be negative')
    return estimate


class LocalizationConvergence:
    """State machine that never declares READY from a pose guess alone."""

    def __init__(self, start_monotonic, config=ConvergenceConfig()):
        config.validate()
        if not _finite((start_monotonic,)):
            raise ValueError('start_monotonic must be finite')
        self.config = config
        self.start_monotonic = float(start_monotonic)
        self.state = STARTUP
        self.reason = 'waiting_for_valid_chain'
        self.chain = ChainEvidence(False, 'not_observed', start_monotonic)
        self.chain_ready_since = None
        self.ever_chain_ready = False
        self.initial_pose = None
        self.convergence_started = None
        self.estimates = deque(maxlen=512)
        self.latest_estimate = None
        self.ready_reference = None
        self.nomotion_successes = 0
        self.nomotion_failures = 0
        self.last_nomotion_request = None
        self.ready_monotonic = None
        self.navigation_active = False
        self.post_initial_pose_estimate_seen = False

    @property
    def ready(self):
        return self.state == READY

    def _clear_convergence(self):
        self.estimates.clear()
        self.latest_estimate = None
        self.ready_reference = None
        self.ready_monotonic = None

    def _block(self, reason):
        self.state = BLOCKED
        self.reason = str(reason)
        self.ready_monotonic = None

    def block(self, reason):
        """Latch an externally detected malformed-input or runtime fault."""
        self._clear_convergence()
        self._block(reason)

    def update_chain(self, evidence, now):
        if not isinstance(evidence, ChainEvidence):
            raise ValueError('chain evidence has the wrong type')
        if not _finite((now, evidence.observed_monotonic)):
            raise ValueError('chain timing must be finite')
        was_chain_ok = self.chain.ok
        self.chain = evidence
        if evidence.ok:
            if self.chain_ready_since is None:
                self.chain_ready_since = now
            self.ever_chain_ready = True
            if self.state == STARTUP:
                self.state = WAIT_INITIAL_POSE
                self.reason = 'waiting_for_explicit_initial_pose'
            return
        self.chain_ready_since = None
        if self.state == CONVERGING:
            if was_chain_ok:
                self.estimates.clear()
                self.latest_estimate = None
                self.nomotion_successes = 0
                self.nomotion_failures = 0
                self.last_nomotion_request = None
                self.post_initial_pose_estimate_seen = False
            self.reason = 'waiting_for_amcl_chain_after_initial_pose:{}'.format(
                evidence.reason)
        elif self.state == READY:
            self._clear_convergence()
            self._block('chain_lost:{}'.format(evidence.reason))
        elif self.state != BLOCKED:
            self.state = STARTUP
            self.reason = 'chain_not_ready:{}'.format(evidence.reason)

    def accept_initial_pose(self, evidence, now):
        """A new explicit pose is also the only recovery from a latched block."""
        validate_initial_pose(evidence, now, self.config)
        if not self.chain.ok:
            raise ValueError('initial pose rejected while chain is not ready')
        self.initial_pose = evidence
        self.convergence_started = now
        self.nomotion_successes = 0
        self.nomotion_failures = 0
        self.last_nomotion_request = None
        self.post_initial_pose_estimate_seen = False
        self._clear_convergence()
        self.state = CONVERGING
        self.reason = 'collecting_amcl_covariance_window'
        return True

    def reset(self, now):
        """Clear a software latch without inventing or retaining a pose."""
        if not _finite((now,)):
            raise ValueError('reset time must be finite')
        self.initial_pose = None
        self.convergence_started = None
        self.nomotion_successes = 0
        self.nomotion_failures = 0
        self.last_nomotion_request = None
        self.post_initial_pose_estimate_seen = False
        self._clear_convergence()
        if self.chain.ok:
            self.state = WAIT_INITIAL_POSE
            self.reason = 'waiting_for_explicit_initial_pose'
            self.chain_ready_since = now
        else:
            self.state = STARTUP
            self.reason = 'waiting_for_valid_chain'

    def _estimate_is_below_thresholds(self, estimate):
        return (
            estimate.covariance_x <= self.config.max_covariance_x
            and estimate.covariance_y <= self.config.max_covariance_y
            and estimate.covariance_yaw <= self.config.max_covariance_yaw)

    def observe_estimate(self, estimate, now, navigation_active=None):
        validate_estimate(estimate, now, self.config)
        if navigation_active is not None:
            self.navigation_active = bool(navigation_active)
        if self.initial_pose is None or self.state in (STARTUP, WAIT_INITIAL_POSE):
            self.reason = 'amcl_pose_ignored_until_explicit_initial_pose'
            return False
        if (
                estimate.received_monotonic
                <= self.initial_pose.received_monotonic
                or estimate.source_stamp <= self.initial_pose.source_stamp):
            self.reason = 'amcl_pose_not_newer_than_initial_pose'
            return False
        if self.state == BLOCKED:
            return False
        self.latest_estimate = estimate
        self.post_initial_pose_estimate_seen = True
        if not self._estimate_is_below_thresholds(estimate):
            self.estimates.clear()
            if self.state == READY:
                self.state = CONVERGING
                self.convergence_started = now
            self.ready_monotonic = None
            self.reason = 'covariance_above_ready_threshold'
            return False
        if (
                self.state == READY
                and not self.navigation_active
                and self.ready_reference is not None):
            position_jump = math.hypot(
                estimate.x - self.ready_reference.x,
                estimate.y - self.ready_reference.y)
            yaw_jump = angular_distance(estimate.yaw, self.ready_reference.yaw)
            if (
                    position_jump > self.config.max_ready_position_jump_m
                    or yaw_jump > self.config.max_ready_yaw_jump_rad):
                self.estimates.clear()
                self.state = CONVERGING
                self.convergence_started = now
                self.ready_monotonic = None
                self.reason = 'ready_pose_jump_requires_reconvergence'
        self.estimates.append(estimate)
        oldest_allowed = now - 2.0 * self.config.stable_window_s
        while (self.estimates
               and self.estimates[0].received_monotonic < oldest_allowed):
            self.estimates.popleft()
        return True

    def set_navigation_active(self, active, now):
        """Suppress no-motion logic while moving and revalidate after stop."""
        if not _finite((now,)):
            raise ValueError('navigation activity time must be finite')
        active = bool(active)
        was_active = self.navigation_active
        self.navigation_active = active
        if was_active and not active and self.state == READY:
            self.state = CONVERGING
            self.reason = 'post_navigation_stationary_revalidation'
            self.convergence_started = now
            self.nomotion_successes = 0
            self.nomotion_failures = 0
            self.last_nomotion_request = None
            self.estimates.clear()
            self.ready_reference = None
            self.ready_monotonic = None
        return self.state

    def nomotion_due(self, now, navigation_active=None):
        if navigation_active is None:
            navigation_active = self.navigation_active
        if (
                self.state != CONVERGING
                or not self.chain.ok
                or self.initial_pose is None
                or navigation_active):
            return False
        return (
            self.last_nomotion_request is None
            or now - self.last_nomotion_request
            >= self.config.nomotion_update_period_s)

    def mark_nomotion_requested(self, now):
        if not _finite((now,)):
            raise ValueError('nomotion request time must be finite')
        self.last_nomotion_request = now

    def record_nomotion_result(self, success, error=''):
        if success:
            if not self.post_initial_pose_estimate_seen:
                self.reason = (
                    'nomotion_update_ignored_until_post_initialpose_amcl')
                return False
            self.nomotion_successes += 1
            self.nomotion_failures = 0
            return True
        self.nomotion_failures += 1
        self.reason = 'nomotion_update_failed:{}'.format(error or 'unknown')
        if (self.nomotion_failures
                >= self.config.max_consecutive_nomotion_failures):
            self._block(self.reason)
        return False

    def _stable_window(self):
        if not self.estimates:
            return []
        latest_time = self.estimates[-1].received_monotonic
        return [
            item for item in self.estimates
            if item.received_monotonic
            >= latest_time - self.config.stable_window_s - 1e-9]

    def _window_is_stable(self):
        window = self._stable_window()
        if len(window) < self.config.stable_min_samples:
            return False
        duration = (
            window[-1].received_monotonic
            - window[0].received_monotonic)
        if duration + 1e-9 < self.config.stable_window_s:
            return False
        xs = [item.x for item in window]
        ys = [item.y for item in window]
        position_span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        yaw_span = max(
            angular_distance(left.yaw, right.yaw)
            for index, left in enumerate(window)
            for right in window[index + 1:])
        return (
            position_span <= self.config.max_stable_position_span_m
            and yaw_span <= self.config.max_stable_yaw_span_rad)

    def tick(self, now):
        if not _finite((now,)):
            raise ValueError('tick time must be finite')
        if self.state == BLOCKED:
            return self.state
        if not self.chain.ok:
            timeout_anchor = (
                self.convergence_started
                if self.state == CONVERGING
                and self.convergence_started is not None
                else self.start_monotonic)
            timeout = (
                self.config.convergence_timeout_s
                if self.state == CONVERGING
                else self.config.chain_timeout_s)
            if now - timeout_anchor >= timeout:
                self._block('chain_validation_timeout:{}'.format(
                    self.chain.reason))
            return self.state
        if self.state == WAIT_INITIAL_POSE:
            if (
                    self.chain_ready_since is not None
                    and now - self.chain_ready_since
                    >= self.config.initial_pose_timeout_s):
                self._block('explicit_initial_pose_timeout')
            return self.state
        if self.state not in (CONVERGING, READY):
            return self.state
        if self.latest_estimate is None:
            if (
                    self.convergence_started is not None
                    and now - self.convergence_started
                    >= self.config.convergence_timeout_s):
                self._block('amcl_pose_timeout_during_convergence')
            return self.state
        latest_age = now - self.latest_estimate.received_monotonic
        if latest_age < 0.0 or latest_age >= self.config.message_timeout_s:
            if self.state == READY:
                self.state = CONVERGING
                self.convergence_started = now
                self.ready_monotonic = None
                self.reason = 'amcl_pose_became_stale'
            elif (
                    self.convergence_started is not None
                    and now - self.convergence_started
                    >= self.config.convergence_timeout_s):
                self._block('amcl_pose_stale_timeout')
            return self.state
        if self.state == CONVERGING:
            if (
                    self.convergence_started is not None
                    and now - self.convergence_started
                    >= self.config.convergence_timeout_s):
                self._block('covariance_stability_timeout')
                return self.state
            if (
                    self.nomotion_successes >= self.config.min_nomotion_updates
                    and self._window_is_stable()):
                self.state = READY
                self.reason = 'localization_ready'
                self.ready_monotonic = now
                self.ready_reference = self.latest_estimate
        return self.state

    def status(self, now):
        latest = self.latest_estimate
        window = self._stable_window()
        result = {
            'state': self.state,
            'ready': self.ready,
            'reason': self.reason,
            'chain_ok': self.chain.ok,
            'chain_reason': self.chain.reason,
            'initial_pose_received': self.initial_pose is not None,
            'initial_pose_source': (
                self.initial_pose.source if self.initial_pose else None),
            'post_initial_pose_estimate_seen': (
                self.post_initial_pose_estimate_seen),
            'nomotion_successes': self.nomotion_successes,
            'nomotion_consecutive_failures': self.nomotion_failures,
            'stable_samples': len(window),
            'stable_duration_s': (
                window[-1].received_monotonic
                - window[0].received_monotonic if len(window) >= 2 else 0.0),
            'ready_monotonic': self.ready_monotonic,
            'navigation_active': self.navigation_active,
            'thresholds': asdict(self.config),
        }
        if latest is not None:
            result['estimate'] = {
                'x': latest.x,
                'y': latest.y,
                'yaw': latest.yaw,
                'covariance_x': latest.covariance_x,
                'covariance_y': latest.covariance_y,
                'covariance_yaw': latest.covariance_yaw,
                'stddev_x_m': math.sqrt(latest.covariance_x),
                'stddev_y_m': math.sqrt(latest.covariance_y),
                'stddev_yaw_rad': math.sqrt(latest.covariance_yaw),
                'receive_age_s': now - latest.received_monotonic,
            }
        else:
            result['estimate'] = None
        return result
