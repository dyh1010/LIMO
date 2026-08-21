import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MotionLimits:
    max_linear_speed: float = 0.12
    max_angular_speed: float = 0.35
    max_linear_acceleration: float = 0.20
    max_angular_acceleration: float = 0.60
    unsupported_axis_epsilon: float = 1e-6


@dataclass(frozen=True)
class PlanarCommand:
    linear_x: float = 0.0
    angular_z: float = 0.0


@dataclass(frozen=True)
class PermissionInputs:
    allow_base_motion: bool
    now: float
    request_time: float = -1.0
    authorization: bool = False
    authorization_time: float = -1.0
    safety_clear: bool = False
    safety_time: float = -1.0
    require_topology_ready: bool = False
    topology_ready: bool = False
    topology_time: float = -1.0
    command_timeout: float = 0.25
    heartbeat_timeout: float = 0.50
    topology_timeout: float = 0.25


def _bounded(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _slew(previous: float, target: float, maximum_delta: float) -> float:
    return previous + _bounded(target - previous, maximum_delta)


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError('{} must be finite'.format(name))


def validate_limits(limits: MotionLimits) -> None:
    for name, value in (
            ('max_linear_speed', limits.max_linear_speed),
            ('max_angular_speed', limits.max_angular_speed),
            ('max_linear_acceleration', limits.max_linear_acceleration),
            ('max_angular_acceleration', limits.max_angular_acceleration),
            ('unsupported_axis_epsilon', limits.unsupported_axis_epsilon)):
        _require_finite(name, value)
        if value <= 0.0:
            raise ValueError('{} must be positive'.format(name))


def reject_unsupported_axes(
        linear_y: float,
        linear_z: float,
        angular_x: float,
        angular_y: float,
        epsilon: float = 1e-6) -> None:
    values = {
        'linear.y': linear_y,
        'linear.z': linear_z,
        'angular.x': angular_x,
        'angular.y': angular_y,
    }
    _require_finite('unsupported_axis_epsilon', epsilon)
    if epsilon <= 0.0:
        raise ValueError('unsupported_axis_epsilon must be positive')
    for name, value in values.items():
        _require_finite(name, value)
    invalid = [
        name for name, value in values.items() if abs(value) > epsilon
    ]
    if invalid:
        raise ValueError(
            'tracked mode rejects unsupported axes: {}'.format(
                ', '.join(invalid)))


def validate_planar_command(command: PlanarCommand) -> None:
    _require_finite('command.linear_x', command.linear_x)
    _require_finite('command.angular_z', command.angular_z)


def limited_command(
        requested: PlanarCommand,
        previous: PlanarCommand,
        dt: float,
        limits: MotionLimits) -> PlanarCommand:
    validate_limits(limits)
    validate_planar_command(requested)
    validate_planar_command(previous)
    _require_finite('dt', dt)
    if dt <= 0.0:
        raise ValueError('dt must be positive')

    target_linear = _bounded(
        requested.linear_x, limits.max_linear_speed)
    target_angular = _bounded(
        requested.angular_z, limits.max_angular_speed)
    return PlanarCommand(
        linear_x=_slew(
            previous.linear_x,
            target_linear,
            limits.max_linear_acceleration * dt),
        angular_z=_slew(
            previous.angular_z,
            target_angular,
            limits.max_angular_acceleration * dt),
    )


def _is_fresh(now: float, timestamp: float, timeout: float) -> bool:
    values = (now, timestamp, timeout)
    if not all(math.isfinite(value) for value in values):
        return False
    if now < 0.0 or timestamp < 0.0 or timeout <= 0.0:
        return False
    if timestamp > now:
        return False
    return now - timestamp <= timeout


def permission_reason(inputs: PermissionInputs) -> str:
    if not inputs.allow_base_motion:
        return 'base_motion_disabled'
    if not _is_fresh(
            inputs.now, inputs.request_time, inputs.command_timeout):
        return 'command_missing_or_stale'
    if not inputs.authorization:
        return 'motion_not_authorized'
    if not _is_fresh(
            inputs.now,
            inputs.authorization_time,
            inputs.heartbeat_timeout):
        return 'authorization_stale'
    if not inputs.safety_clear:
        return 'safety_not_clear'
    if not _is_fresh(
            inputs.now, inputs.safety_time, inputs.heartbeat_timeout):
        return 'safety_heartbeat_stale'
    if inputs.require_topology_ready:
        if not inputs.topology_ready:
            return 'topology_not_ready'
        if not _is_fresh(
                inputs.now,
                inputs.topology_time,
                inputs.topology_timeout):
            return 'topology_heartbeat_stale'
    return 'allowed'
