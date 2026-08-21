"""Source-level contract tests for the simulation-only gripper ROS node."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
NODE = ROOT / 'limo_cleanup_executor' / 'gripper_gateway_node.py'
LAUNCH = ROOT / 'launch' / 'gripper_gateway_dry_run.launch.py'
CONFIG = ROOT / 'config' / 'gripper_gateway_dry_run.yaml'
SETUP = ROOT / 'setup.py'
SMOKE = ROOT / 'test' / 'test_gripper_gateway_ros_smoke.py'


class GripperGatewayRosContractTest(unittest.TestCase):
    def test_action_shutdown_is_fail_closed(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn('self._core.motion_safety_unresolved', source)
        self.assertIn('self._core.fail_closed_action_boundary(', source)
        self.assertIn(
            'ROS shutdown during active gripper action', source)

    """Ensure the released surface cannot construct or address hardware."""

    def test_node_and_launch_use_python38_syntax(self):
        for path in (NODE, LAUNCH):
            ast.parse(
                path.read_text(encoding='utf-8'),
                filename=str(path),
                feature_version=(3, 8),
            )

    def test_node_contains_no_hardware_or_vendor_entry(self):
        source = NODE.read_text(encoding='utf-8')
        lowered = source.lower()
        for forbidden in (
                'import serial', 'from serial', 'import pymycobot',
                'from pymycobot', "'/dev/", '"/dev/', 'usb.core',
                'socket.', 'subprocess.', 'ssh'):
            self.assertNotIn(forbidden, lowered)
        tree = ast.parse(source)
        called = set()
        for item in ast.walk(tree):
            if isinstance(item, ast.Call):
                if isinstance(item.func, ast.Name):
                    called.add(item.func.id)
                elif isinstance(item.func, ast.Attribute):
                    called.add(item.func.attr)
        self.assertEqual(
            called.intersection({
                'open', '__import__', 'import_module', 'power_on',
                'focus_servo', 'focus_all_servos', 'release_servo',
                'release_all_servos',
            }),
            set(),
        )

    def test_node_refuses_every_backend_except_dry_run(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn("self.backend_name != 'dry_run'", source)
        self.assertIn('gripper hardware is blocked', source)
        self.assertNotIn('PymycobotGripperBackend', source)
        self.assertNotIn('backend_factory=', source)

    def test_real_motion_stays_blocked_without_exact_release_profile_binding(
            self):
        node_source = NODE.read_text(encoding='utf-8')
        core = ROOT / 'limo_cleanup_executor' / 'gripper_gateway_core.py'
        core_source = core.read_text(encoding='utf-8')
        self.assertIn("self.backend_name != 'dry_run'", node_source)
        self.assertIn('DRY_RUN_', node_source)
        self.assertIn('real backend is DISABLED/BLOCKED', core_source)
        for token in (
                'runtime_release_id', 'release_manifest_sha256',
                'motion_profile_id', 'motion_profile_manifest_sha256',
                'motion_profile_runtime_release_id',
                'approved_speed_grades',
                'backend_method_contract_sha256',
                'stop_isolation_architecture_sha256',
                'hung_command_stop_test_report_sha256'):
            self.assertIn(token, core_source)

    def test_capability_gate_is_static_not_adapter_code(self):
        core = ROOT / 'limo_cleanup_executor' / 'gripper_gateway_core.py'
        source = core.read_text(encoding='utf-8')
        self.assertIn("'SAFETY_CAPABILITIES'", source)
        self.assertIn("backend_type.__dict__", source)
        self.assertNotIn("'safety_capabilities',", source)
        self.assertIn('policy-owned mode', source)

    def test_launch_and_config_are_static_motion_disabled(self):
        launch = LAUNCH.read_text(encoding='utf-8')
        config = CONFIG.read_text(encoding='utf-8')
        for source in (launch, config):
            self.assertIn('dry_run', source)
            self.assertNotIn('pymycobot', source)
            self.assertNotIn('/dev/', source)
        self.assertIn("'allow_simulated_motion': False", launch)
        self.assertIn('allow_simulated_motion: false', config)
        self.assertIn('DRY_RUN_TOOL', config)
        self.assertIn('DRY_RUN_PROTOCOL', config)

    def test_action_stop_ack_and_identity_contract_is_wired(self):
        source = NODE.read_text(encoding='utf-8')
        required = (
            'ExecuteGripperMotion', 'StopGripper',
            'AcknowledgeGripperFault', '/cleanup/gripper/execute',
            '/cleanup/gripper/stop',
            '/cleanup/gripper/acknowledge_fault',
            'expected_session_id', 'authorization_id',
            'expected_tool_revision', 'controller_boot_id',
        )
        for token in required:
            self.assertIn(token, source)
        self.assertIn('STATE_PHYSICAL_ESTOP_REQUIRED', source)

    def test_published_validity_uses_core_fresh_health_gate(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn(
            'message.valid = self._core.snapshot_is_valid()', source)
        self.assertIn(
            'message.normalized_position_valid = message.valid', source)

    def test_node_lock_never_wraps_refresh_stop_ack_or_close(self):
        source = NODE.read_text(encoding='utf-8')
        tree = ast.parse(source)
        core_methods = {
            'refresh', 'request_stop', 'acknowledge_local_fault', 'close',
        }
        violations = []
        for item in ast.walk(tree):
            if not isinstance(item, ast.With):
                continue
            holds_node_lock = any(
                isinstance(context.context_expr, ast.Attribute)
                and isinstance(context.context_expr.value, ast.Name)
                and context.context_expr.value.id == 'self'
                and context.context_expr.attr == '_lock'
                for context in item.items
            )
            if not holds_node_lock:
                continue
            for call in ast.walk(item):
                if not isinstance(call, ast.Call):
                    continue
                function = call.func
                if (
                        isinstance(function, ast.Attribute)
                        and function.attr in core_methods
                        and isinstance(function.value, ast.Attribute)
                        and isinstance(function.value.value, ast.Name)
                        and function.value.value.id == 'self'
                        and function.value.attr == '_core'):
                    violations.append(function.attr)
        self.assertEqual(violations, [])

    def test_setup_installs_node_launch_and_config(self):
        source = SETUP.read_text(encoding='utf-8')
        for token in (
                'gripper_gateway = ', 'gripper_gateway_node:main',
                'gripper_gateway_dry_run.launch.py',
                'gripper_gateway_dry_run.yaml',
                'final_gripper_release_manifest.json'):
            self.assertIn(token, source)

    def test_ros_smoke_has_only_dry_run_identity(self):
        source = SMOKE.read_text(encoding='utf-8')
        ast.parse(source, filename=str(SMOKE), feature_version=(3, 8))
        for token in ('/dev/', 'pymycobot', 'serial', 'usb'):
            self.assertNotIn(token, source.lower())
        self.assertIn('DRY_RUN_TOOL', source)


if __name__ == '__main__':
    unittest.main()
