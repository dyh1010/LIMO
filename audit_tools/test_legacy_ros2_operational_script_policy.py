"""Pure-local tests for legacy ROS2 operational-script demotion."""

from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from audit_tools import legacy_ros2_operational_script_policy as POLICY


ROOT = Path(__file__).resolve().parents[1]


class LegacyRos2OperationalScriptPolicyTests(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in (
                POLICY.INVENTORY_RELATIVE_PATH.as_posix(),
                *(POLICY.LEGACY_PATHS + POLICY.BRIDGE_ALLOWLIST
                  + POLICY.COMPANION_PATHS)):
            source = ROOT.joinpath(*relative.split("/"))
            target = self.root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def tearDown(self):
        self.temporary.cleanup()

    def _mutate(self, relative, old, new):
        path = self.root.joinpath(*relative.split("/"))
        source = path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        path.write_text(source.replace(old, new, 1), encoding="utf-8")

    def _assert_workspace_failure(self, code_fragment):
        result = POLICY.validate_workspace(self.root)
        self.assertFalse(result["validated_pass"])
        self.assertTrue(
            any(code_fragment in failure for failure in result["failures"]),
            result["failures"],
        )

    def test_real_inventory_and_workspace_pass_static_contract(self):
        result = POLICY.validate_workspace(ROOT)
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertEqual(result["field_runtime_authority"], "ROS1_NOETIC")
        self.assertEqual(result["legacy_script_count"], 5)
        self.assertEqual(result["bridge_exception_count"], 2)
        self.assertEqual(result["companion_static_contract_count"], 5)
        self.assertFalse(result["authorizes_ros_start"])
        self.assertFalse(result["authorizes_hardware_access"])
        self.assertFalse(result["authorizes_motion"])
        self.assertFalse(result["authorizes_goal"])
        self.assertFalse(result["authorizes_nonzero_twist"])
        self.assertFalse(result["authorizes_recovery"])
        self.assertFalse(result["release_pin_may_be_updated"])
        self.assertEqual(len(result["observed_scripts"]), 7)
        self.assertEqual(len(result["observed_companions"]), 5)
        self.assertTrue(result["source_tree_contract_only"])
        self.assertFalse(result["installed_runtime_resolution_verified"])
        self.assertFalse(result["runtime_execution_ready"])
        for observed in (
                result["observed_scripts"] + result["observed_companions"]):
            self.assertGreater(observed["size_bytes"], 0)
            self.assertRegex(observed["sha256"], r"^[0-9a-f]{64}$")

    def test_inventory_is_exact_and_cannot_self_authorize(self):
        payload = deepcopy(POLICY._expected_inventory())
        payload["safety_boundary"]["authorizes_motion"] = True
        result = POLICY.validate_workspace(self.root, payload)
        self.assertFalse(result["validated_pass"])
        self.assertIn("inventory_payload_mismatch", result["failures"])
        payload = deepcopy(POLICY._expected_inventory())
        payload["legacy_ros2_scripts"].pop()
        result = POLICY.validate_workspace(self.root, payload)
        self.assertFalse(result["validated_pass"])
        self.assertIn("inventory_payload_mismatch", result["failures"])

    def test_bridge_exception_is_path_exact_not_content_based(self):
        bridge_path = ROOT / "scripts" / "ros1_base_bridge_preflight.sh"
        source = bridge_path.read_text(encoding="utf-8")
        allowed = POLICY.validate_operational_script(
            "scripts/ros1_base_bridge_preflight.sh", source)
        copied = POLICY.validate_operational_script(
            "scripts/copied_ros1_base_bridge_preflight.sh", source)
        self.assertTrue(allowed["validated_pass"], allowed["failures"])
        self.assertTrue(allowed["identity_validated"])
        self.assertTrue(allowed["authoritative_static_gate"])
        self.assertEqual(
            copied["classification"], "UNLISTED_OPERATIONAL_SCRIPT_REJECTED")
        self.assertFalse(copied["validated_pass"])
        self.assertFalse(copied["identity_validated"])
        self.assertFalse(copied["authoritative_static_gate"])

    def test_guard_must_be_exact_and_precede_all_operations(self):
        path = "scripts/smoke_test_touch_only.sh"
        self._mutate(
            path,
            "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE-}",
            "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE-true}",
        )
        self._assert_workspace_failure("exact_opt_in_guard_count_not_one")
        operations = (
            "source /tmp/forbidden_setup.bash",
            "ros2 node list",
            "python3 /tmp/forbidden_probe.py",
            "fuser /dev/ttyTHS0",
        )
        for operation in operations:
            with self.subTest(operation=operation):
                self.tearDown()
                self.setUp()
                target = self.root / path
                source = target.read_text(encoding="utf-8")
                target.write_text(
                    source.replace(
                        "#!/usr/bin/env bash\n",
                        "#!/usr/bin/env bash\n" + operation + "\n",
                        1,
                    ),
                    encoding="utf-8",
                )
                self._assert_workspace_failure(
                    "guard_occurs_after_operational_command")

    def test_active_scripts_reject_global_shared_hardware_and_real_gates(self):
        cases = (
            ("export ROS_LOCALHOST_ONLY=1", "export ROS_LOCALHOST_ONLY=0",
             "global_discovery_enabled"),
            ("export ROS_DOMAIN_ID=221", "export ROS_DOMAIN_ID=137",
             "shared_domain_137_enabled"),
            ("allow_base_motion:=false", "allow_base_motion:=true",
             "hardware_real_or_command_token_present"),
            ("use_tracked_base_controller:=false",
             "use_tracked_base_controller:=true",
             "hardware_real_or_command_token_present"),
            ("allow_arm_motion:=false", "allow_arm_motion:=true",
             "hardware_real_or_command_token_present"),
            ("use_gripper_controller:=false", "use_gripper_controller:=true",
             "hardware_real_or_command_token_present"),
            ("use_real_perception:=false", "use_real_perception:=true",
             "hardware_real_or_command_token_present"),
            ("use_mock_perception:=true", "use_mock_perception:=false",
             "missing_fixed_safety_argument"),
            ("use_mock_executor:=true", "use_mock_executor:=false",
             "missing_fixed_safety_argument"),
            ("executor_dry_run:=true", "executor_dry_run:=false",
             "missing_fixed_safety_argument"),
        )
        path = "scripts/smoke_test_touch_only.sh"
        for old, new, failure in cases:
            with self.subTest(mutation=new):
                self.tearDown()
                self.setUp()
                self._mutate(path, old, new)
                self._assert_workspace_failure(failure)

    def test_active_scripts_reject_production_topic_and_undemoted_pass(self):
        path = "scripts/smoke_test_tracked_zero_guard.sh"
        self._mutate(
            path,
            "/test/cleanup/tracked_zero_output",
            "/cleanup/base/safe_cmd_vel",
        )
        self._assert_workspace_failure("production_command_topic_present")
        self.tearDown()
        self.setUp()
        self._mutate(
            path,
            "LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS",
            "TRACKED_ZERO_GUARD_SMOKE_PASS",
        )
        self._assert_workspace_failure("mock_pass_not_immediately_demoted")
        self.tearDown()
        self.setUp()
        path = "scripts/smoke_test_tracked_zero_launch.sh"
        self._mutate(
            path,
            'topology_ready_topic:="${TEST_PREFIX}/topology_ready" \\\n',
            'topology_ready_topic:="${TEST_PREFIX}/topology_ready" \\\n'
            '  diagnostic_topic:="${TEST_PREFIX}/diagnostic" \\\n',
        )
        self._assert_workspace_failure("topic_bindings_not_exact_test_only_set")

    def test_active_scripts_reject_unapproved_ros2_cli_operations(self):
        path = "scripts/smoke_test_touch_only.sh"
        target = self.root / path
        source = target.read_text(encoding="utf-8")
        target.write_text(
            source.replace(
                "echo 'LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS'",
                "ros2 topic echo /test/unapproved\n"
                "echo 'LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS'",
                1,
            ),
            encoding="utf-8",
        )
        self._assert_workspace_failure("unapproved_ros2_cli_operation")

    def test_retired_shims_reject_restored_ros_or_device_paths(self):
        path = "scripts/tracked_base_stage2_preflight.sh"
        target = self.root / path
        source = target.read_text(encoding="utf-8")
        target.write_text(
            source.replace(
                "exit 64", "source /opt/ros/foxy/setup.bash\nexit 64", 1),
            encoding="utf-8",
        )
        self._assert_workspace_failure(
            "retired_shim_contains_ros_or_device_operation")

    def test_zero_launch_companion_keeps_production_defaults_and_hard_false(self):
        path = POLICY.COMPANION_PATHS[0]
        self._mutate(
            path,
            "default_value='/cleanup/base/cmd_vel_request'",
            "default_value='/test/unsafe_default'",
        )
        self._assert_workspace_failure("production_topic_defaults_changed")
        self.tearDown()
        self.setUp()
        self._mutate(
            path, "'allow_base_motion': False", "'allow_base_motion': True")
        self._assert_workspace_failure("allow_base_motion_not_literal_false")
        self.tearDown()
        self.setUp()
        self._mutate(
            path,
            "'topology_ready_topic': topology_ready_topic,",
            "'wrong_topic': topology_ready_topic,",
        )
        self._assert_workspace_failure(
            "five_topic_parameters_not_forwarded_exactly")
        self.tearDown()
        self.setUp()
        self._mutate(
            path,
            "'topology_ready_topic': topology_ready_topic,",
            "'topology_ready_topic': topology_ready_topic,\n"
            "                'diagnostic_topic': '/test/diagnostic',",
        )
        self._assert_workspace_failure("extra_or_missing_topic_parameter")

    def test_zero_probe_publishers_are_exact_test_topics_only(self):
        path = POLICY.COMPANION_PATHS[1]
        self._mutate(
            path,
            "TEST_REQUEST_TOPIC = TEST_PREFIX + '/request'",
            "TEST_REQUEST_TOPIC = '/cleanup/base/cmd_vel_request'",
        )
        self._assert_workspace_failure(
            "publisher_topics_not_exact_test_only_set")
        self._assert_workspace_failure("production_private_topic_literal_present")
        self.tearDown()
        self.setUp()
        self._mutate(
            path,
            "TEST_PREFIX = '/test/legacy_ros2_offline/tracked_zero_launch'",
            "TEST_PREFIX = '/test/legacy_ros2_offline/tracked_zero_launch'\n"
            "TEST_PREFIX = '/test/duplicate_must_fail'",
        )
        self._assert_workspace_failure("duplicate_fixed_topic_constant")
        self.tearDown()
        self.setUp()
        target = self.root.joinpath(*path.split("/"))
        source = target.read_text(encoding="utf-8")
        target.write_text(
            source.replace(
                "self.output_subscription = self.create_subscription(",
                "self.extra_publisher = self.create_publisher(\n"
                "            Twist, TEST_OUTPUT_TOPIC, 10)\n"
                "        self.output_subscription = self.create_subscription(",
                1,
            ),
            encoding="utf-8",
        )
        self._assert_workspace_failure(
            "publisher_topics_not_exact_test_only_set")

    def test_zero_verifier_is_fixed_test_topic_and_has_no_publisher(self):
        path = POLICY.COMPANION_PATHS[2]
        self._mutate(
            path,
            "SAFE_COMMAND_TOPIC = '/test/cleanup/tracked_zero_output'",
            "SAFE_COMMAND_TOPIC = '/cleanup/base/safe_cmd_vel'",
        )
        self._assert_workspace_failure("safe_command_topic_not_fixed_test_topic")
        self.tearDown()
        self.setUp()
        target = self.root.joinpath(*path.split("/"))
        source = target.read_text(encoding="utf-8")
        target.write_text(
            source.replace(
                "self.command_subscription = self.create_subscription(",
                "self.command_publisher = self.create_publisher(\n"
                "            Twist, SAFE_COMMAND_TOPIC, 1)\n"
                "        self.command_subscription = self.create_subscription(",
                1,
            ),
            encoding="utf-8",
        )
        self._assert_workspace_failure("verifier_contains_publisher")

    def test_touch_probe_is_only_ordinary_mock_text_intent(self):
        path = POLICY.COMPANION_PATHS[3]
        self._mutate(
            path,
            "String, '/cleanup/command_text', 10",
            "String, '/cmd_vel', 10",
        )
        self._assert_workspace_failure(
            "touch_probe_not_single_ordinary_text_intent")
        self._assert_workspace_failure(
            "touch_probe_motion_or_hardware_token_present")
        self.tearDown()
        self.setUp()
        target = self.root.joinpath(*path.split("/"))
        source = target.read_text(encoding="utf-8")
        target.write_text(
            source.replace(
                "LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK",
                "HISTORICAL_MOCK_CHECK",
            ),
            encoding="utf-8",
        )
        self._assert_workspace_failure("legacy_mock_check_marker_missing")

    def test_touch_launch_dependency_keeps_all_safe_defaults(self):
        path = POLICY.COMPANION_PATHS[4]
        self._mutate(
            path,
            "'allow_base_motion',\n            default_value='false'",
            "'allow_base_motion',\n            default_value='true'",
        )
        self._assert_workspace_failure("touch_launch_safe_defaults_changed")
        self._assert_workspace_failure("static_contract_identity_mismatch")
        self.tearDown()
        self.setUp()
        self._mutate(
            path,
            "'use_real_perception',\n            default_value='false'",
            "'use_real_perception',\n            default_value='true'",
        )
        self._assert_workspace_failure("touch_launch_safe_defaults_changed")

    def test_bridge_allowlist_rejects_generic_guard_and_all_topics(self):
        path = "scripts/ros1_base_bridge_preflight.sh"
        target = self.root / path
        source = target.read_text(encoding="utf-8")
        target.write_text(
            source + "\n# LEGACY_ROS2_OFFLINE_ONLY\n", encoding="utf-8")
        self._assert_workspace_failure(
            "generic_legacy_guard_applied_to_bridge_exception")
        self.tearDown()
        self.setUp()
        target = self.root / path
        source = target.read_text(encoding="utf-8")
        target.write_text(source + "\n# --bridge-all-topics\n", encoding="utf-8")
        self._assert_workspace_failure("bridge_all_topics_forbidden")

    def test_exact_identity_blocks_semantic_obfuscation_and_hidden_operations(self):
        mutations = (
            (
                POLICY.COMPANION_PATHS[0],
                "from launch import LaunchDescription",
                "from launch import LaunchDescription\n"
                "# ExecuteProcess(cmd=['ros2','run','limo_base','driver'])",
            ),
            (
                POLICY.COMPANION_PATHS[1],
                "self.request_publisher = self.create_publisher(",
                "self.request_publisher = getattr(\n"
                "            self, 'create_' + 'publisher')(",
            ),
            (
                POLICY.RETIRED_LEGACY[0],
                "echo 'BLOCKED: legacy tracked-base hardware preflight is permanently retired.' >&2",
                "bash /tmp/hidden_operation.sh\n"
                "echo 'BLOCKED: legacy tracked-base hardware preflight is permanently retired.' >&2",
            ),
            (
                POLICY.BRIDGE_ALLOWLIST[0],
                "# This script never starts a node, opens /dev/ttyTHS0, or publishes a message.",
                "# This script never starts a node, opens /dev/ttyTHS0, or publishes a message.\n"
                "# ros2 topic pub /cmd_vel hidden",
            ),
        )
        for path, old, new in mutations:
            with self.subTest(path=path):
                self.tearDown()
                self.setUp()
                self._mutate(path, old, new)
                self._assert_workspace_failure(
                    "static_contract_identity_mismatch")

    def test_negative_guard_values_exit_64_without_running_ros(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash, "bash is required for shell early-exit tests")
        for relative in POLICY.LEGACY_PATHS:
            path = ROOT.joinpath(*relative.split("/"))
            values = (None, "", "0", "true")
            if relative in POLICY.RETIRED_LEGACY:
                values = values + ("1",)
            for value in values:
                with self.subTest(path=relative, value=value):
                    environment = os.environ.copy()
                    for unsafe_shell_hook in ("BASH_ENV", "ENV", "CDPATH"):
                        environment.pop(unsafe_shell_hook, None)
                    if value is None:
                        environment.pop("LIMO_ALLOW_LEGACY_ROS2_OFFLINE", None)
                    else:
                        environment["LIMO_ALLOW_LEGACY_ROS2_OFFLINE"] = value
                    completed = subprocess.run(
                        [bash, "--noprofile", "--norc", str(path)],
                        cwd=str(ROOT),
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(
                        completed.returncode, 64,
                        (relative, value, completed.stdout, completed.stderr),
                    )

    def test_all_inventory_shell_files_pass_bash_syntax_only(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash, "bash is required for syntax-only tests")
        for relative in POLICY.LEGACY_PATHS + POLICY.BRIDGE_ALLOWLIST:
            path = ROOT.joinpath(*relative.split("/"))
            with self.subTest(path=relative):
                completed = subprocess.run(
                    [bash, "--noprofile", "--norc", "-n", str(path)],
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode, 0,
                    (relative, completed.stdout, completed.stderr),
                )


if __name__ == "__main__":
    unittest.main()
