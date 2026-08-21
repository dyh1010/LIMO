"""Pure fail-closed freshness and command policy used by the V1 guard."""

from dataclasses import dataclass
import math


ZERO_COMPONENTS = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class CommandValues:
    """ROS Twist values without a ROS dependency."""

    linear_x: float = 0.0
    linear_y: float = 0.0
    linear_z: float = 0.0
    angular_x: float = 0.0
    angular_y: float = 0.0
    angular_z: float = 0.0

    def components(self):
        return (
            self.linear_x, self.linear_y, self.linear_z,
            self.angular_x, self.angular_y, self.angular_z)


ZERO_COMMAND = CommandValues()


@dataclass(frozen=True)
class FreshnessLimits:
    """Maximum accepted ages and conservative command limits."""

    scan_timeout_s: float = 0.5
    odom_timeout_s: float = 0.5
    tf_timeout_s: float = 0.5
    command_timeout_s: float = 0.25
    source_future_tolerance_s: float = 0.1
    min_scan_hz: float = 4.8
    max_scan_hz: float = 7.2
    max_linear_x_mps: float = 0.18
    max_angular_z_rps: float = 0.45


@dataclass(frozen=True)
class FreshnessSnapshot:
    """Latest evidence with monotonic receive times and ROS source stamps."""

    now: float
    ros_now: float = None
    last_scan: float = None
    scan_source_stamp: float = None
    last_odom: float = None
    last_tf: float = None
    tf_source_stamp: float = None
    last_command: float = None
    scan_hz: float = None
    scan_frame_ok: bool = False
    odom_frames_ok: bool = False
    tf_owner_ok: bool = False
    forbidden_tf_owner_present: bool = False


@dataclass(frozen=True)
class SafetyDecision:
    """Output and exact fail-closed reason."""

    output: CommandValues
    allowed: bool
    reason: str


def _age(now, timestamp, label, timeout):
    if timestamp is None:
        return '{}_missing'.format(label)
    age = now - timestamp
    if not math.isfinite(age) or age < 0.0:
        return '{}_time_invalid'.format(label)
    if age >= timeout:
        return '{}_stale'.format(label)
    return None


def _source_age(ros_now, source_stamp, label, timeout, future_tolerance=0.1):
    values = (ros_now, source_stamp, timeout, future_tolerance)
    if any(value is None or not math.isfinite(value) for value in values):
        return '{}_source_time_missing'.format(label)
    if (ros_now <= 0.0 or source_stamp <= 0.0
            or timeout <= 0.0 or future_tolerance < 0.0):
        return '{}_source_time_invalid'.format(label)
    age = ros_now - source_stamp
    if age < -future_tolerance:
        return '{}_source_from_future'.format(label)
    if age >= timeout:
        return '{}_source_stale'.format(label)
    return None


def _validate_command(command, limits):
    if not isinstance(command, CommandValues):
        raise ValueError('command must be CommandValues')
    if any(not math.isfinite(value) for value in command.components()):
        raise ValueError('command values must be finite')
    if any(abs(value) > 0.0 for value in (
            command.linear_y, command.linear_z,
            command.angular_x, command.angular_y)):
        raise ValueError('only planar linear_x/angular_z commands are allowed')
    if abs(command.linear_x) > limits.max_linear_x_mps:
        raise ValueError('linear_x exceeds conservative V1 limit')
    if abs(command.angular_z) > limits.max_angular_z_rps:
        raise ValueError('angular_z exceeds conservative V1 limit')


def evaluate_safety(
        snapshot, command, limits=FreshnessLimits(),
        allow_nonzero=False, driver_timeout_verified=False,
        fault_latched=True):
    """Return zero for every missing, stale, ambiguous, or unauthorized state."""
    try:
        _validate_command(command, limits)
    except ValueError as exc:
        return SafetyDecision(ZERO_COMMAND, False, str(exc))
    if fault_latched:
        return SafetyDecision(ZERO_COMMAND, False, 'fault_latched')
    if not allow_nonzero:
        return SafetyDecision(ZERO_COMMAND, False, 'nonzero_not_authorized')
    if not driver_timeout_verified:
        return SafetyDecision(ZERO_COMMAND, False, 'driver_timeout_unverified')
    for timestamp, label, timeout in (
            (snapshot.last_scan, 'scan', limits.scan_timeout_s),
            (snapshot.last_odom, 'odom', limits.odom_timeout_s),
            (snapshot.last_tf, 'tf', limits.tf_timeout_s),
            (snapshot.last_command, 'command', limits.command_timeout_s)):
        reason = _age(snapshot.now, timestamp, label, timeout)
        if reason:
            return SafetyDecision(ZERO_COMMAND, False, reason)
    for source_stamp, label, timeout in (
            (snapshot.scan_source_stamp, 'scan', limits.scan_timeout_s),
            (snapshot.tf_source_stamp, 'tf', limits.tf_timeout_s)):
        reason = _source_age(
            snapshot.ros_now, source_stamp, label, timeout,
            limits.source_future_tolerance_s)
        if reason:
            return SafetyDecision(ZERO_COMMAND, False, reason)
    if snapshot.scan_hz is None or not math.isfinite(snapshot.scan_hz):
        return SafetyDecision(ZERO_COMMAND, False, 'scan_rate_missing')
    if not limits.min_scan_hz <= snapshot.scan_hz <= limits.max_scan_hz:
        return SafetyDecision(ZERO_COMMAND, False, 'scan_rate_out_of_bounds')
    if not snapshot.scan_frame_ok:
        return SafetyDecision(ZERO_COMMAND, False, 'scan_frame_invalid')
    if not snapshot.odom_frames_ok:
        return SafetyDecision(ZERO_COMMAND, False, 'odom_frames_invalid')
    if snapshot.forbidden_tf_owner_present:
        return SafetyDecision(ZERO_COMMAND, False, 'forbidden_tf_owner_present')
    if not snapshot.tf_owner_ok:
        return SafetyDecision(ZERO_COMMAND, False, 'odom_tf_owner_missing')
    return SafetyDecision(command, True, 'allowed')


class FaultLatch:
    """Latched stop state that never rearms automatically."""

    def __init__(self):
        self.latched = True
        self.reason = 'startup_latched'

    def trip(self, reason):
        self.latched = True
        self.reason = str(reason)

    def rearm(self, health_ready, zero_command, explicit_request):
        if not (health_ready and zero_command and explicit_request):
            return False
        self.latched = False
        self.reason = 'rearmed'
        return True


def slew_limit(
        previous, target, elapsed_s,
        max_linear_accel_mps2, max_angular_accel_rps2):
    """Apply project-owned acceleration bounds to an already safe command."""
    _validate_command(target, FreshnessLimits(
        max_linear_x_mps=max(
            abs(previous.linear_x), abs(target.linear_x), 0.18),
        max_angular_z_rps=max(
            abs(previous.angular_z), abs(target.angular_z), 0.45),
    ))
    if not math.isfinite(elapsed_s) or elapsed_s <= 0.0:
        return ZERO_COMMAND
    linear_step = max_linear_accel_mps2 * elapsed_s
    angular_step = max_angular_accel_rps2 * elapsed_s

    def step(current, requested, maximum_step):
        delta = requested - current
        return current + max(-maximum_step, min(maximum_step, delta))

    return CommandValues(
        linear_x=step(previous.linear_x, target.linear_x, linear_step),
        angular_z=step(
            previous.angular_z, target.angular_z, angular_step),
    )
