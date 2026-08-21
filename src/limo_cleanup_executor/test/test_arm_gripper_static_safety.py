import ast
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
ARM_BACKENDS = PACKAGE_ROOT / 'limo_cleanup_executor' / 'arm_backends.py'
ARM_NODE = PACKAGE_ROOT / 'limo_cleanup_executor' / 'arm_gateway_node.py'
GRIPPER_BACKENDS = (
    PACKAGE_ROOT / 'limo_cleanup_executor' / 'gripper_backends.py')
GRIPPER_CONTROLLER = (
    PACKAGE_ROOT / 'limo_cleanup_executor' / 'gripper_controller.py')
GRIPPER_GATEWAY = (
    PACKAGE_ROOT / 'limo_cleanup_executor' / 'gripper_gateway_node.py')
ARM_LAUNCH = PACKAGE_ROOT / 'launch' / 'arm_gateway_dry_run.launch.py'
ARM_DRY_CONFIG = PACKAGE_ROOT / 'config' / 'arm_gateway_dry_run.yaml'
ARM_SAFE_CONFIG = PACKAGE_ROOT / 'config' / 'arm_gateway_safe.example.yaml'
GRIPPER_GATEWAY_LAUNCH = (
    PACKAGE_ROOT / 'launch' / 'gripper_gateway_dry_run.launch.py')
GRIPPER_GATEWAY_CONFIG = (
    PACKAGE_ROOT / 'config' / 'gripper_gateway_dry_run.yaml')
GRIPPER_LAUNCH = (
    PROJECT_ROOT / 'src' / 'limo_cleanup_bringup' / 'launch'
    / 'gripper_control.launch.py')
GRIPPER_CONFIG = (
    PROJECT_ROOT / 'src' / 'limo_cleanup_bringup' / 'config'
    / 'gripper_safe.yaml')


def _read(path):
    return path.read_text(encoding='utf-8')


def _calls(path):
    tree = ast.parse(_read(path), filename=str(path), feature_version=(3, 8))
    resolved = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            resolved.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            resolved.append(node.func.attr)
    return tuple(resolved)


class ArmGripperStaticSafetyTest(unittest.TestCase):
    def test_backend_modules_have_no_runtime_import_or_file_open_calls(self):
        forbidden_calls = {
            '__import__', 'import_module', 'open', 'os_open', 'scandir',
            'listdir', 'glob', 'rglob', 'walk',
        }
        for path in (ARM_BACKENDS, GRIPPER_BACKENDS):
            calls = set(_calls(path))
            self.assertFalse(
                calls & forbidden_calls,
                '{} has forbidden calls: {}'.format(
                    path, sorted(calls & forbidden_calls)))
            source = _read(path)
            for token in (
                    'import pymycobot', 'from pymycobot', 'import serial',
                    'client_factory or', 'load_pymycobot_factory'):
                self.assertNotIn(token, source)

    def test_factories_and_ros_nodes_release_dry_run_only(self):
        arm_backend = _read(ARM_BACKENDS)
        arm_node = _read(ARM_NODE)
        gripper_controller = _read(GRIPPER_CONTROLLER)
        gripper_gateway = _read(GRIPPER_GATEWAY)
        self.assertIn(
            'pymycobot arm backend is not released', arm_backend)
        self.assertIn("self.backend_name != 'dry_run'", arm_node)
        self.assertNotIn('PymycobotArmBackend(', arm_node)
        self.assertIn(
            'legacy pymycobot AG hardware backend is forbidden',
            gripper_controller)
        self.assertNotIn('PymycobotGripperBackend', gripper_controller)
        self.assertIn("self.backend_name != 'dry_run'", gripper_gateway)
        self.assertNotIn('PymycobotGripperBackend', gripper_gateway)

    def test_launch_and_executable_configs_have_no_device_paths(self):
        for path in (
                ARM_LAUNCH, ARM_DRY_CONFIG,
                ARM_SAFE_CONFIG,
                GRIPPER_GATEWAY_LAUNCH, GRIPPER_GATEWAY_CONFIG,
                GRIPPER_LAUNCH, GRIPPER_CONFIG):
            source = _read(path)
            self.assertNotIn('/' + 'dev/', source)
            self.assertNotIn('pymycobot', source)
            if path != ARM_SAFE_CONFIG:
                self.assertIn('dry_run', source)


if __name__ == '__main__':
    unittest.main()
