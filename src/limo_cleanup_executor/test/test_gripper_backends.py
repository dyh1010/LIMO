import ast
from pathlib import Path

import pytest

from limo_cleanup_executor.gripper_backends import (
    DryRunGripperBackend,
    GripperBackendError,
    PymycobotGripperBackend,
)


def test_dry_run_backend_never_needs_hardware():
    backend = DryRunGripperBackend(initial_position=1.0)
    backend.command_position(0.35, 0.20)
    assert backend.read_position() == pytest.approx(0.35)
    assert backend.commands == [(0.35, 0.20)]


def test_dry_run_offers_stop_and_close():
    backend = DryRunGripperBackend()
    backend.stop()
    backend.close()
    assert backend.stop_calls == 1
    with pytest.raises(GripperBackendError, match='closed'):
        backend.read_position()


def test_legacy_ag_placeholder_requires_explicit_callable_factory():
    for factory in (None, 'not-callable', 1, True):
        with pytest.raises(
                GripperBackendError,
                match='explicit callable client_factory'):
            PymycobotGripperBackend(client_factory=factory)


def test_legacy_ag_placeholder_never_calls_injected_factory():
    calls = []

    def forbidden_factory(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('retired AG factory must never run')

    with pytest.raises(
            GripperBackendError,
            match='DISABLED/BLOCKED.*factory was not called'):
        PymycobotGripperBackend(client_factory=forbidden_factory)
    assert calls == []


def test_legacy_ag_placeholder_exposes_no_executable_protocol_methods():
    for method_name in (
            'command_position', 'read_position', 'stop', 'close'):
        assert not hasattr(PymycobotGripperBackend, method_name)


def test_source_has_no_dynamic_hardware_or_retired_ag_protocol_path():
    backend_path = (
        Path(__file__).resolve().parents[1]
        / 'limo_cleanup_executor' / 'gripper_backends.py')
    source = backend_path.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(backend_path))
    calls = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
    assert not calls.intersection({
        '__import__', 'import_module', 'open', 'os_open', 'scandir',
        'listdir', 'glob', 'rglob', 'walk',
    })
    class_source = source[source.index('class PymycobotGripperBackend:'):]
    for token in (
            'import pymycobot', 'from pymycobot', 'import serial',
            'load_pymycobot_factory', 'client_factory or', 'client_factory(',
            'set_gripper_value', 'get_gripper_value', 'gripper_type',
            'closed_value', 'open_value', '/dev/', 'threading',
            'ThreadPoolExecutor'):
        assert token not in class_source
