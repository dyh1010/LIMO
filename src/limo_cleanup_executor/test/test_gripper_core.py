import math

import pytest

from limo_cleanup_executor.gripper_core import (
    COMMAND_CLOSE,
    COMMAND_OPEN,
    COMMAND_SET_POSITION,
    GripperCommandError,
    normalized_to_raw,
    position_reached,
    raw_to_normalized,
    resolve_gripper_command,
)


def test_open_and_close_override_position():
    opened = resolve_gripper_command(
        COMMAND_OPEN, 0.2, 0.5, True, 0.25)
    closed = resolve_gripper_command(
        COMMAND_CLOSE, 0.8, 0.0, False, 0.25)

    assert opened.position == 1.0
    assert opened.speed == 0.5
    assert opened.verify is True
    assert closed.position == 0.0
    assert closed.speed == 0.25
    assert closed.verify is False


def test_set_position_preserves_partial_grasp():
    command = resolve_gripper_command(
        COMMAND_SET_POSITION, 0.32, 0.15, True, 0.25)

    assert command.position == pytest.approx(0.32)
    assert command.speed == pytest.approx(0.15)


@pytest.mark.parametrize(
    'command,position,speed',
    (
        (0, 0.5, 0.5),
        (COMMAND_SET_POSITION, -0.1, 0.5),
        (COMMAND_SET_POSITION, 1.1, 0.5),
        (COMMAND_OPEN, 0.0, -0.1),
        (COMMAND_OPEN, 0.0, 1.1),
        (COMMAND_OPEN, 0.0, math.nan),
    ),
)
def test_invalid_commands_are_rejected(command, position, speed):
    with pytest.raises(GripperCommandError):
        resolve_gripper_command(
            command, position, speed, True, 0.25)


def test_raw_conversion_supports_both_directions():
    assert normalized_to_raw(0.0, 0, 100) == 0
    assert normalized_to_raw(0.25, 0, 100) == 25
    assert normalized_to_raw(1.0, 0, 100) == 100
    assert raw_to_normalized(75, 100, 0) == pytest.approx(0.25)


@pytest.mark.parametrize(
    'raw_value,closed_value,open_value',
    ((9, 10, 90), (91, 10, 90), (9, 90, 10), (91, 90, 10)),
)
def test_raw_feedback_outside_calibrated_endpoints_is_rejected(
        raw_value, closed_value, open_value):
    with pytest.raises(GripperCommandError, match='calibrated endpoint'):
        raw_to_normalized(raw_value, closed_value, open_value)


def test_position_reached_uses_normalized_tolerance():
    assert position_reached(0.28, 0.30, 0.03)
    assert not position_reached(0.20, 0.30, 0.03)


def test_numeric_subclasses_are_rejected_without_conversion_callbacks():
    calls = []

    class ActiveFloat(float):
        def __float__(value):
            calls.append('float')
            return float.__float__(value)

    class ActiveInt(int):
        pass

    with pytest.raises(GripperCommandError, match='built-in number'):
        resolve_gripper_command(
            COMMAND_SET_POSITION, ActiveFloat(0.3), 0.2, True, 0.25)
    with pytest.raises(GripperCommandError, match='integer'):
        raw_to_normalized(ActiveInt(10), 0, 100)
    assert calls == []
