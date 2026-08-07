import math
from dataclasses import dataclass


COMMAND_OPEN = 1
COMMAND_CLOSE = 2
COMMAND_SET_POSITION = 3


class GripperCommandError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedGripperCommand:
    position: float
    speed: float
    verify: bool


def _finite_float(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise GripperCommandError(f'{name} must be finite')
    return result


def normalized_value(value: float, name: str) -> float:
    result = _finite_float(value, name)
    if result < 0.0 or result > 1.0:
        raise GripperCommandError(f'{name} must be between 0.0 and 1.0')
    return result


def resolve_gripper_command(
        command: int,
        position: float,
        speed: float,
        verify: bool,
        default_speed: float) -> ResolvedGripperCommand:
    resolved_default_speed = normalized_value(default_speed, 'default_speed')
    if resolved_default_speed <= 0.0:
        raise GripperCommandError('default_speed must be greater than 0.0')

    requested_speed = _finite_float(speed, 'speed')
    if requested_speed == 0.0:
        requested_speed = resolved_default_speed
    elif requested_speed < 0.0 or requested_speed > 1.0:
        raise GripperCommandError(
            'speed must be 0.0 or between 0.0 and 1.0')

    if command == COMMAND_OPEN:
        requested_position = 1.0
    elif command == COMMAND_CLOSE:
        requested_position = 0.0
    elif command == COMMAND_SET_POSITION:
        requested_position = normalized_value(position, 'position')
    else:
        raise GripperCommandError(f'unsupported command: {command}')

    return ResolvedGripperCommand(
        position=requested_position,
        speed=requested_speed,
        verify=bool(verify),
    )


def validate_raw_calibration(closed_value: int, open_value: int) -> None:
    for value, name in (
            (closed_value, 'closed_value'),
            (open_value, 'open_value')):
        if isinstance(value, bool) or not isinstance(value, int):
            raise GripperCommandError(f'{name} must be an integer')
        if value < 0 or value > 100:
            raise GripperCommandError(f'{name} must be between 0 and 100')
    if closed_value == open_value:
        raise GripperCommandError(
            'closed_value and open_value must be different')


def normalized_to_raw(
        position: float, closed_value: int, open_value: int) -> int:
    resolved_position = normalized_value(position, 'position')
    validate_raw_calibration(closed_value, open_value)
    value = closed_value + (
        resolved_position * (open_value - closed_value))
    return int(round(value))


def raw_to_normalized(
        raw_value: int, closed_value: int, open_value: int) -> float:
    validate_raw_calibration(closed_value, open_value)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise GripperCommandError('raw_value must be an integer')
    if raw_value < 0 or raw_value > 100:
        raise GripperCommandError('raw_value must be between 0 and 100')
    value = (
        (raw_value - closed_value) / (open_value - closed_value))
    return min(1.0, max(0.0, value))


def position_reached(
        measured: float, commanded: float, tolerance: float) -> bool:
    resolved_measured = normalized_value(measured, 'measured')
    resolved_commanded = normalized_value(commanded, 'commanded')
    resolved_tolerance = normalized_value(tolerance, 'tolerance')
    return abs(resolved_measured - resolved_commanded) <= resolved_tolerance
