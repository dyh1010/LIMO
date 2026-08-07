import pytest

from limo_cleanup_executor.gripper_backends import (
    DryRunGripperBackend,
    GripperBackendError,
    PymycobotGripperBackend,
)


class FakeMyCobot:
    def __init__(self, port, baud):
        self.port = port
        self.baud = baud
        self.position = 100
        self.calls = []

    def set_gripper_value(self, position, speed, gripper_type):
        self.calls.append((position, speed, gripper_type))
        self.position = position

    def get_gripper_value(self, gripper_type):
        self.calls.append(('read', gripper_type))
        return self.position


def test_dry_run_backend_never_needs_hardware():
    backend = DryRunGripperBackend(initial_position=1.0)

    backend.command_position(0.35, 0.20)

    assert backend.read_position() == pytest.approx(0.35)
    assert backend.commands == [(0.35, 0.20)]


def test_pymycobot_backend_maps_normalized_values():
    backend = PymycobotGripperBackend(
        port='/dev/fake',
        baud=115200,
        gripper_type=1,
        closed_value=0,
        open_value=100,
        client_factory=FakeMyCobot,
    )

    backend.command_position(0.30, 0.25)

    assert backend.client.calls[0] == (30, 25, 1)
    assert backend.read_position() == pytest.approx(0.30)


def test_backend_rejects_invalid_calibration():
    with pytest.raises(GripperBackendError):
        PymycobotGripperBackend(
            port='/dev/fake',
            baud=115200,
            gripper_type=1,
            closed_value=50,
            open_value=50,
            client_factory=FakeMyCobot,
        )
