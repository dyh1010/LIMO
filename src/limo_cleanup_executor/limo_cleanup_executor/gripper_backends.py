from .gripper_core import (
    normalized_value,
)


class GripperBackendError(RuntimeError):
    pass


class DryRunGripperBackend:
    def __init__(self, initial_position: float = 1.0) -> None:
        self.position = normalized_value(
            initial_position, 'initial_position')
        self.commands = []
        self.stop_calls = 0
        self.closed = False

    def _ensure_open(self) -> None:
        if self.closed:
            raise GripperBackendError('dry-run gripper backend is closed')

    def command_position(self, position: float, speed: float) -> None:
        self._ensure_open()
        resolved_position = normalized_value(position, 'position')
        resolved_speed = normalized_value(speed, 'speed')
        if resolved_speed <= 0.0:
            raise GripperBackendError('speed must be greater than 0.0')
        self.commands.append((resolved_position, resolved_speed))
        self.position = resolved_position

    def read_position(self) -> float:
        self._ensure_open()
        return self.position

    def stop(self) -> None:
        self._ensure_open()
        self.stop_calls += 1

    def close(self) -> None:
        self.closed = True


class PymycobotGripperBackend:
    """Permanent fail-closed placeholder for the retired AG adapter.

    The old fixture encoded an unverified device route, actuator selector,
    command range and STOP assumption.  Keeping those values executable, even
    behind an injected fake client, risks turning historical guesses into a
    future hardware example.  Construction therefore rejects before invoking
    the explicitly supplied factory.  Final-tool protocol testing belongs in
    the tool-neutral gateway fake backend and a separately reviewed release
    package.
    """

    def __init__(self, client_factory=None) -> None:
        if not callable(client_factory):
            raise GripperBackendError(
                'legacy AG backend DISABLED/BLOCKED: an explicit callable '
                'client_factory is required and no default import or device '
                'open is permitted')
        raise GripperBackendError(
            'legacy AG backend DISABLED/BLOCKED: retired AG parameters and '
            'shared transport STOP semantics are not released; the injected '
            'factory was not called')
