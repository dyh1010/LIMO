import importlib
from typing import Callable, Optional

from .gripper_core import (
    GripperCommandError,
    normalized_to_raw,
    normalized_value,
    raw_to_normalized,
    validate_raw_calibration,
)


class GripperBackendError(RuntimeError):
    pass


class DryRunGripperBackend:
    def __init__(self, initial_position: float = 1.0) -> None:
        self.position = normalized_value(
            initial_position, 'initial_position')
        self.commands = []

    def command_position(self, position: float, speed: float) -> None:
        resolved_position = normalized_value(position, 'position')
        resolved_speed = normalized_value(speed, 'speed')
        if resolved_speed <= 0.0:
            raise GripperBackendError('speed must be greater than 0.0')
        self.commands.append((resolved_position, resolved_speed))
        self.position = resolved_position

    def read_position(self) -> float:
        return self.position


def load_pymycobot_factory() -> Callable:
    candidates = (
        ('pymycobot', 'MyCobot280'),
        ('pymycobot.mycobot280', 'MyCobot280'),
        ('pymycobot.mycobot', 'MyCobot'),
    )
    errors = []
    for module_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as error:
            errors.append(f'{module_name}.{class_name}: {error}')
    raise GripperBackendError(
        'pymycobot driver not found; tried ' + '; '.join(errors))


class PymycobotGripperBackend:
    def __init__(
            self,
            port: str,
            baud: int,
            gripper_type: int,
            closed_value: int,
            open_value: int,
            client_factory: Optional[Callable] = None) -> None:
        if not port:
            raise GripperBackendError('serial port must not be empty')
        if baud <= 0:
            raise GripperBackendError('baud must be greater than zero')
        if gripper_type < 0:
            raise GripperBackendError(
                'gripper_type must be zero or greater')
        try:
            validate_raw_calibration(closed_value, open_value)
        except GripperCommandError as error:
            raise GripperBackendError(str(error)) from error

        factory = client_factory or load_pymycobot_factory()
        try:
            self.client = factory(port, baud)
        except Exception as error:
            raise GripperBackendError(
                f'failed to open myCobot connection on {port}: {error}'
            ) from error

        self.gripper_type = gripper_type
        self.closed_value = closed_value
        self.open_value = open_value

    def command_position(self, position: float, speed: float) -> None:
        try:
            raw_position = normalized_to_raw(
                position, self.closed_value, self.open_value)
            resolved_speed = normalized_value(speed, 'speed')
        except GripperCommandError as error:
            raise GripperBackendError(str(error)) from error
        if resolved_speed <= 0.0:
            raise GripperBackendError('speed must be greater than 0.0')
        raw_speed = max(1, min(100, int(round(resolved_speed * 100))))

        setter = getattr(self.client, 'set_gripper_value', None)
        if setter is None:
            raise GripperBackendError(
                'pymycobot client has no set_gripper_value method')
        try:
            try:
                response = setter(
                    raw_position, raw_speed, self.gripper_type)
            except TypeError:
                response = setter(raw_position, raw_speed)
        except Exception as error:
            raise GripperBackendError(
                f'gripper command failed: {error}') from error
        if response is False:
            raise GripperBackendError('gripper command was rejected')

    def read_position(self) -> float:
        getter = getattr(self.client, 'get_gripper_value', None)
        if getter is None:
            raise GripperBackendError(
                'pymycobot client has no get_gripper_value method')
        try:
            try:
                raw_value = getter(self.gripper_type)
            except TypeError:
                raw_value = getter()
        except Exception as error:
            raise GripperBackendError(
                f'failed to read gripper position: {error}') from error

        if isinstance(raw_value, (list, tuple)):
            if not raw_value:
                raise GripperBackendError(
                    'gripper returned an empty position response')
            raw_value = raw_value[0]
        if isinstance(raw_value, bool):
            raise GripperBackendError(
                f'invalid gripper position response: {raw_value!r}')
        try:
            raw_integer = int(raw_value)
            return raw_to_normalized(
                raw_integer, self.closed_value, self.open_value)
        except (TypeError, ValueError, GripperCommandError) as error:
            raise GripperBackendError(
                f'invalid gripper position response: {raw_value!r}'
            ) from error
