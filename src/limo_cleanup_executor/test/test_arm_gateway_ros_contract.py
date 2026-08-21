import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
NODE = ROOT / 'limo_cleanup_executor' / 'arm_gateway_node.py'
LAUNCH = ROOT / 'launch' / 'arm_gateway_dry_run.launch.py'
DRY_RUN_CONFIG = ROOT / 'config' / 'arm_gateway_dry_run.yaml'
SAFE_CONFIG = ROOT / 'config' / 'arm_gateway_safe.example.yaml'
SETUP = ROOT / 'setup.py'
PROJECT_ROOT = ROOT.parents[1]
ARM_STATE = PROJECT_ROOT / 'src' / 'limo_cleanup_interfaces' / 'msg' / 'ArmState.msg'
FOXY_SCRIPT = PROJECT_ROOT / 'scripts' / 'verify_arm_gateway_foxy_dry_run.sh'
FOXY_RUNNER = (
    PROJECT_ROOT / 'scripts' / 'run_uploaded_arm_foxy_dry_run.sh')


class ArmGatewayRosContractTest(unittest.TestCase):
    def test_node_and_launch_use_python38_syntax(self):
        for path in (NODE, LAUNCH):
            ast.parse(
                path.read_text(encoding='utf-8'),
                filename=str(path),
                feature_version=(3, 8),
            )

    def test_node_refuses_every_backend_except_dry_run(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn("self.backend_name != 'dry_run'", source)
        self.assertIn('only backend=dry_run is released', source)
        self.assertIn('DryRunArmBackend(', source)
        self.assertNotIn('backend_factory', source)
        self.assertNotIn('create_arm_backend', source)
        self.assertNotIn('from pymycobot', source)
        self.assertNotIn('import serial', source)
        self.assertNotIn('/dev/elephant', source)

    def test_stop_callback_is_not_serialized_behind_action_send_lock(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn('self._lifecycle_lock = threading.RLock()', source)
        stop_source = source[
            source.index('    def stop_callback'):
            source.index('    def acknowledge_callback')]
        acknowledge_source = source[
            source.index('    def acknowledge_callback'):
            source.index('    def destroy_node')]
        execute_source = source[
            source.index('    def execute_callback'):
            source.index('    def _publish_feedback')]
        execute_active_source = execute_source[
            :execute_source.index('        finally:')]
        self.assertNotIn('with self._lifecycle_lock', stop_source)
        self.assertNotIn('with self._lifecycle_lock', acknowledge_source)
        self.assertNotIn(
            'with self._lifecycle_lock', execute_active_source)
        self.assertEqual(
            execute_source.count('with self._lifecycle_lock'), 1)
        self.assertNotIn('self._lock', source)

    def test_arm_state_valid_uses_core_health_and_freshness_contract(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn(
            'message.valid = self._core.snapshot_is_valid()', source)
        self.assertIn(
            'message.physical_stop_required = '
            'self._core.physical_stop_required', source)

    def test_action_waits_for_safe_resolution_and_shutdown_is_fail_closed(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertIn('self._core.motion_safety_unresolved', source)
        self.assertIn('self._core.fail_closed_action_boundary(', source)
        self.assertIn(
            'ROS shutdown during active arm action', source)
        string_literals = {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        }
        self.assertIn(
            'resolved fault without a matching failed command result',
            string_literals,
        )

    def test_node_uses_core_session_and_forwards_authorization_contract(self):
        source = NODE.read_text(encoding='utf-8')
        self.assertNotIn('import uuid', source)
        self.assertNotIn('self._session_id', source)
        self.assertIn('authorization_validator=None', source)
        self.assertIn(
            'authorization_validator=authorization_validator', source)
        self.assertIn(
            'message.session_id = self._core.session_id', source)
        self.assertIn(
            'expected == self._core.session_id', source)
        self.assertGreaterEqual(
            source.count('request.expected_session_id'), 6)
        self.assertGreaterEqual(
            source.count('self._core.session_id'), 5)

    def test_stop_retry_policy_is_explicit_in_node_and_configs(self):
        node = NODE.read_text(encoding='utf-8')
        dry_run = DRY_RUN_CONFIG.read_text(encoding='utf-8')
        safe_example = SAFE_CONFIG.read_text(encoding='utf-8')
        state = ARM_STATE.read_text(encoding='utf-8')
        for name in (
                'approved_speed_grades',
                'max_stop_attempts',
                'stop_retry_interval_s',
                'stop_retry_backoff_factor'):
            self.assertIn(name, node)
            self.assertIn(name, dry_run)
            self.assertIn(name, safe_example)
        self.assertIn('bool physical_stop_required', state)
        self.assertNotIn('/dev/', safe_example)
        for field in ('port: null', 'baud: null', 'expected_serial: null'):
            self.assertIn(field, safe_example)

    def test_ros_smoke_test_requires_no_hardware_identifiers(self):
        source = (
            ROOT / 'test' / 'test_arm_gateway_ros_smoke.py'
        ).read_text(encoding='utf-8')
        self.assertIn('DRY_RUN_NO_DEVICE', source)
        self.assertIn('authorization_validator=', source)
        self.assertIn("purpose not in ('motion', 'ack')", source)
        self.assertNotIn('pymycobot', source)
        self.assertNotIn('/dev/', source)

    def test_launch_hard_codes_dry_run_backend(self):
        source = LAUNCH.read_text(encoding='utf-8')
        self.assertIn("'backend': 'dry_run'", source)
        self.assertNotIn('pymycobot', source)
        self.assertNotIn('/dev/', source)

    def test_setup_installs_node_launch_and_config(self):
        source = SETUP.read_text(encoding='utf-8')
        self.assertIn("'arm_gateway = ", source)
        self.assertIn('arm_gateway_dry_run.launch.py', source)
        self.assertIn('arm_gateway_dry_run.yaml', source)
        self.assertIn('arm_motion_release.example.json', source)

    def test_foxy_dry_run_script_is_hardware_inert(self):
        source = FOXY_SCRIPT.read_text(encoding='utf-8')
        self.assertIn('packages-select limo_cleanup_interfaces', source)
        self.assertIn('test_arm_gateway_ros_smoke.py', source)
        self.assertIn('ROS_LOCALHOST_ONLY=1', source)
        self.assertIn('arm_gateway_dry_run.launch.py', source)
        self.assertNotIn('/dev/elephant', source)
        self.assertNotIn('ros2 action send_goal', source)
        self.assertNotIn('ros2 service call', source)
        self.assertNotIn('sudo', source)
        self.assertNotIn("grep -Eq '/dev/", source)

    def test_foxy_setup_precedes_ros_command_checks(self):
        source = FOXY_SCRIPT.read_text(encoding='utf-8')
        setup_guard = source.index('[ -f "$ros_setup" ]')
        setup_source = source.index('source "$ros_setup"')
        command_loop = source.index(
            'for required_command in awk colcon grep ps python3 ros2')
        first_colcon = source.index('colcon --log-base')

        self.assertLess(setup_guard, setup_source)
        self.assertLess(setup_source, command_loop)
        self.assertLess(command_loop, first_colcon)
        self.assertEqual(source.count('source "$ros_setup"'), 1)

    def test_foxy_v3_scripts_preserve_evidence_and_clean_exact_targets(self):
        runner = FOXY_RUNNER.read_text(encoding='utf-8')
        verifier = FOXY_SCRIPT.read_text(encoding='utf-8')
        combined = runner + verifier

        self.assertIn('/tmp/arm_foxy_dryrun_20260813_v3', runner)
        self.assertIn(
            'domain_id=${ARM_FOXY_DRY_RUN_DOMAIN_ID:-219}', runner)
        self.assertIn(
            'domain_id=${ARM_FOXY_DRY_RUN_DOMAIN_ID:-219}', verifier)
        self.assertIn(
            'timeout_s=${ARM_FOXY_DRY_RUN_TIMEOUT_S:-600}', runner)
        self.assertIn('timeout --signal=TERM --kill-after=15s', runner)
        self.assertIn('arm_foxy_dryrun_20260813_v3_evidence', runner)
        self.assertIn('arm_foxy_dryrun_20260813_v3_summary.log', runner)
        self.assertIn('rm -rf -- "$source_dir" "$work_dir" "$root"', runner)
        self.assertIn('rm -f -- "$bundle"', runner)
        self.assertIn('colcon_test.log', verifier)
        self.assertIn('colcon_test_result.log', verifier)
        self.assertIn('arm_ros_smoke.log', verifier)
        self.assertIn('ROS_LOCALHOST_ONLY=1', combined)
        self.assertIn('export ROS_DOMAIN_ID="$domain_id"', combined)
        self.assertIn('ARM_FOXY_DRY_RUN_DOMAIN_ID', combined)
        self.assertIn('runner_pids_before.txt', runner)
        self.assertIn('runner_process_cleanup.txt', runner)
        self.assertIn('pid_still_matches', runner)

        forbidden = (
            '/' + 'dev/',
            'ros2 action send_goal',
            'ros2 service call',
            'agilex_ws',
            '/opt/elephant',
            'pymycobot/setup',
            'killall',
            'pkill',
        )
        for token in forbidden:
            self.assertNotIn(token, combined)

if __name__ == '__main__':
    unittest.main()
