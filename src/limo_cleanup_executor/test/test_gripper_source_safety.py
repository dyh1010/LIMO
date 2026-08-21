from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BACKENDS = (
    PACKAGE_ROOT / 'limo_cleanup_executor' / 'gripper_backends.py')
CONTROLLER = (
    PACKAGE_ROOT / 'limo_cleanup_executor' / 'gripper_controller.py')
LAUNCH = (
    PACKAGE_ROOT.parent / 'limo_cleanup_bringup' / 'launch'
    / 'gripper_control.launch.py')
SYSTEM_LAUNCH = (
    PACKAGE_ROOT.parent / 'limo_cleanup_bringup' / 'launch'
    / 'cleanup_system.launch.py')
CONFIG = (
    PACKAGE_ROOT.parent / 'limo_cleanup_bringup' / 'config'
    / 'gripper_safe.yaml')


def test_legacy_fixture_has_no_vendor_import_or_default_factory():
    source = BACKENDS.read_text(encoding='utf-8')
    forbidden = (
        'import importlib',
        'import pymycobot',
        'from pymycobot',
        'client_factory or',
        'load_pymycobot_factory',
        'except TypeError',
        "getattr(self.client, 'stop'",
    )
    for token in forbidden:
        assert token not in source
    class_source = source[source.index('class PymycobotGripperBackend:'):]
    assert 'explicit callable ' in class_source
    assert 'client_factory is required' in class_source
    assert 'factory was not called' in class_source
    for retired_runtime_token in (
            'client_factory(', 'set_gripper_value', 'get_gripper_value',
            'gripper_type', 'closed_value', 'open_value', '/dev/'):
        assert retired_runtime_token not in class_source


def test_ros_controller_cannot_construct_legacy_fixture():
    source = CONTROLLER.read_text(encoding='utf-8')
    assert 'PymycobotGripperBackend' not in source
    assert 'legacy pymycobot AG hardware backend is forbidden' in source
    assert "self.backend_name == 'dry_run'" in source


def test_launch_and_config_are_dry_run_only_and_use_sentinels():
    launch_source = LAUNCH.read_text(encoding='utf-8')
    system_launch_source = SYSTEM_LAUNCH.read_text(encoding='utf-8')
    config_source = CONFIG.read_text(encoding='utf-8')
    controller_source = CONTROLLER.read_text(encoding='utf-8')
    for source in (
            launch_source,
            system_launch_source,
            config_source,
            controller_source):
        assert 'dry_run' in source
        assert 'UNRESOLVED_DO_NOT_' in source
        assert '/dev/elephant' not in source
        assert '/dev/tty' not in source
        for retired_parameter in (
                "'serial_port'",
                "'baud'",
                "'gripper_type'",
                "'closed_value'",
                "'open_value'",
                'baud: 115200',
                'gripper_type: -1'):
            assert retired_parameter not in source
    assert 'allow_hardware_motion: false' in config_source


def test_controller_failure_paths_request_stop_and_close():
    source = CONTROLLER.read_text(encoding='utf-8')
    for reason in (
            'action cancellation',
            'verification timeout',
            'command or feedback failure',
            'unexpected exception'):
        assert reason in source
    assert "getattr(self.backend, 'close', None)" in source
