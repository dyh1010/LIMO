"""Regression tests for the fixed visual legacy operational-script gate."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from audit_tools import ros1_legacy_operational_scripts as GATE


ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_bytes().decode("utf-8", errors="strict")


def _drop_stripped_block(text: str, expected: tuple[str, ...]) -> str:
    lines = text.splitlines()
    for index in range(len(lines)):
        if tuple(value.strip() for value in lines[index:index + len(expected)]) == expected:
            del lines[index:index + len(expected)]
            return "\n".join(lines) + "\n"
    raise AssertionError("expected block not found")


class Ros1LegacyOperationalScriptsTest(unittest.TestCase):

    @contextmanager
    def _fixture(self, overrides=None, omitted=()):
        override_map = dict(overrides or {})
        omitted_set = set(omitted)
        with tempfile.TemporaryDirectory(
                prefix="ros1_legacy_operational_scripts_") as directory:
            root = Path(directory)
            for relative_path in GATE.SCRIPT_PATHS:
                if relative_path in omitted_set:
                    continue
                target = root.joinpath(*Path(relative_path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = override_map.get(
                    relative_path, (ROOT / relative_path).read_bytes())
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
                target.write_bytes(raw)
            yield root

    def test_current_fixed_inventory_passes_and_reports_exact_identity(self):
        report = GATE.evaluate_legacy_scripts(ROOT)
        self.assertTrue(report["validated_pass"], report["failures"])
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["scripts_expected"], list(GATE.SCRIPT_PATHS))
        self.assertEqual(len(report["artifacts"]), 4)
        for artifact, relative_path in zip(
                report["artifacts"], GATE.SCRIPT_PATHS):
            raw = (ROOT / relative_path).read_bytes()
            self.assertEqual(artifact["path"], relative_path)
            self.assertEqual(artifact["size_bytes"], len(raw))
            self.assertEqual(
                artifact["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertTrue(artifact["ordinary_non_link_file"])
        self.assertFalse(report["runtime_execution_performed"])
        self.assertEqual(report["ros_commands_executed"], 0)
        self.assertEqual(report["exec_calls"], 0)
        self.assertEqual(report["formal_denominator"], 0)
        self.assertFalse(report["ros1_noetic_runtime_install_validated"])
        self.assertFalse(report["formal_consumer"])
        self.assertFalse(report["authorizes_field_delivery"])
        self.assertFalse(report["delivery_ready"])

    def test_bridge_allowlist_is_explicitly_excluded_from_fixed_inventory(self):
        with self._fixture() as root:
            for relative_path in GATE.EXCLUDED_ROS1_ROS2_BRIDGE_ALLOWLIST:
                target = root.joinpath(*Path(relative_path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(
                    b"#!/bin/sh\nros2 topic pub /bridge x y\n")
            report = GATE.evaluate_legacy_scripts(root)
        self.assertTrue(report["validated_pass"], report["failures"])
        self.assertEqual(
            report["bridge_allowlist_explicitly_excluded"],
            list(GATE.EXCLUDED_ROS1_ROS2_BRIDGE_ALLOWLIST))
        self.assertEqual(
            [item["path"] for item in report["artifacts"]],
            list(GATE.SCRIPT_PATHS))

    def test_unset_empty_zero_and_true_guard_cases_exit_64_without_ros_or_exec(self):
        for relative_path in GATE.SCRIPT_PATHS:
            with self.subTest(path=relative_path):
                scan = GATE.scan_script_text(relative_path, _text(relative_path))
                invalid = [case for case in scan["guard_cases"]
                           if case["case"] != "exact_opt_in"]
                self.assertEqual(
                    [case["case"] for case in invalid],
                    ["unset", "empty", "zero", "true"])
                self.assertTrue(all(case["guard_validated"] for case in invalid))
                self.assertTrue(all(case["exit_code"] == 64 for case in invalid))
                self.assertTrue(all(not case["would_execute_ros"] for case in invalid))
                self.assertTrue(all(not case["would_call_exec"] for case in invalid))
                self.assertFalse(scan["runtime_execution_performed"])
                self.assertEqual(scan["ros_commands_executed"], 0)
                self.assertEqual(scan["exec_calls"], 0)

        # The same ID is the POSIX companion for the static proof above.  It
        # invokes only the invalid guard paths, never the opt-in mock bodies.
        # Windows retains the byte-level proof without a platform skip; the
        # release runner executes this ID again under its anchored POSIX
        # interpreter to obtain the real /bin/bash result.
        if os.name == "posix":
            with tempfile.TemporaryDirectory(
                    prefix="ros1_legacy_guard_shell_") as directory:
                temporary = Path(directory)
                fake_bin = temporary / "bin"
                fake_bin.mkdir()
                sentinel = temporary / "external_command_called"
                helper = (
                    "#!/bin/sh\n"
                    "printf '%s\\n' \"$0\" >> \"$LEGACY_SENTINEL\"\n"
                    "exit 99\n")
                for name in (
                        "ros2", "roslaunch", "colcon", "python", "python3",
                        "setsid", "curl", "wget", "ssh", "v4l2-ctl"):
                    target = fake_bin / name
                    target.write_bytes(helper.encode("utf-8"))
                    target.chmod(0o755)
                for relative_path in GATE.SCRIPT_PATHS:
                    for label, value in GATE.INVALID_OPT_IN_CASES:
                        with self.subTest(
                                shell_path=relative_path, shell_case=label):
                            environment = {
                                "HOME": str(temporary),
                                "LEGACY_SENTINEL": str(sentinel),
                                "PATH": str(fake_bin) + ":/usr/bin:/bin",
                                "TMPDIR": str(temporary),
                            }
                            if value is not None:
                                environment[GATE.OPT_IN_VARIABLE] = value
                            completed = subprocess.run(
                                ["/bin/bash", str(ROOT / relative_path)],
                                cwd=str(ROOT),
                                env=environment,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                check=False,
                                timeout=5,
                            )
                            self.assertEqual(
                                completed.returncode, 64,
                                completed.stderr.decode(
                                    "utf-8", errors="replace"))
                            self.assertFalse(
                                sentinel.exists(),
                                sentinel.read_text(encoding="utf-8")
                                if sentinel.exists() else "")

    def test_exact_opt_in_still_blocks_both_permanent_shims_without_execution(self):
        for relative_path in sorted(GATE.PERMANENT_SHIMS):
            with self.subTest(path=relative_path):
                scan = GATE.scan_script_text(relative_path, _text(relative_path))
                cases = [case for case in scan["guard_cases"]
                         if case["case"] == "exact_opt_in"]
                self.assertEqual(len(cases), 1)
                self.assertTrue(cases[0]["guard_validated"])
                self.assertEqual(cases[0]["exit_code"], 65)
                self.assertFalse(cases[0]["would_execute_ros"])
                self.assertFalse(cases[0]["would_call_exec"])
        if os.name == "posix":
            with tempfile.TemporaryDirectory(
                    prefix="ros1_legacy_shim_shell_") as directory:
                temporary = Path(directory)
                fake_bin = temporary / "bin"
                fake_bin.mkdir()
                sentinel = temporary / "external_command_called"
                helper = (
                    "#!/bin/sh\n"
                    "printf '%s\\n' \"$0\" >> \"$LEGACY_SENTINEL\"\n"
                    "exit 99\n")
                for name in (
                        "ros2", "roslaunch", "colcon", "python", "python3",
                        "setsid", "curl", "wget", "ssh", "v4l2-ctl"):
                    target = fake_bin / name
                    target.write_bytes(helper.encode("utf-8"))
                    target.chmod(0o755)
                environment = {
                    "HOME": str(temporary),
                    "LEGACY_SENTINEL": str(sentinel),
                    GATE.OPT_IN_VARIABLE: "1",
                    "PATH": str(fake_bin) + ":/usr/bin:/bin",
                    "TMPDIR": str(temporary),
                }
                for relative_path in sorted(GATE.PERMANENT_SHIMS):
                    with self.subTest(shell_path=relative_path):
                        completed = subprocess.run(
                            ["/bin/bash", str(ROOT / relative_path)],
                            cwd=str(ROOT),
                            env=environment,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False,
                            timeout=5,
                        )
                        self.assertEqual(
                            completed.returncode, 65,
                            completed.stderr.decode(
                                "utf-8", errors="replace"))
                        self.assertFalse(
                            sentinel.exists(),
                            sentinel.read_text(encoding="utf-8")
                            if sentinel.exists() else "")

    def test_missing_duplicate_or_weakened_guard_is_rejected(self):
        relative_path = "scripts/smoke_test_perception.sh"
        baseline = _text(relative_path)
        mutations = {
            "missing": baseline.replace(GATE.GUARD_LINE, "if false; then", 1),
            "duplicate": baseline.replace(
                GATE.GUARD_LINE, GATE.GUARD_LINE + "\n" + GATE.GUARD_LINE, 1),
            "weakened": baseline.replace(" != '1'", " == '0'", 1),
        }
        for label, changed in mutations.items():
            with self.subTest(label=label):
                scan = GATE.scan_script_text(relative_path, changed)
                self.assertIn(
                    "legacy_script_guard_count_invalid:" + relative_path,
                    scan["failures"])
                self.assertTrue(all(
                    not case["guard_validated"] for case in scan["guard_cases"]))

    def test_guard_after_source_or_ros2_is_rejected_before_any_execution(self):
        relative_path = "scripts/smoke_test_perception.sh"
        changed = _text(relative_path).replace(
            GATE.GUARD_LINE,
            "source /tmp/untrusted/setup.bash\n"
            "ros2 topic list\n" + GATE.GUARD_LINE,
            1)
        scan = GATE.scan_script_text(relative_path, changed)
        self.assertIn(
            "legacy_script_preguard_inventory_invalid:" + relative_path,
            scan["failures"])
        self.assertFalse(scan["runtime_execution_performed"])
        self.assertEqual(scan["ros_commands_executed"], 0)
        self.assertEqual(scan["exec_calls"], 0)

    def test_missing_or_weakened_authority_banner_is_rejected(self):
        relative_path = "scripts/smoke_test_real_perception_startup.sh"
        baseline = _text(relative_path)
        for label, changed in (
                ("missing", baseline.replace(
                    "# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY\n", "", 1)),
                ("weakened", baseline.replace(
                    "# NOT_FIELD_OR_DELIVERY_EVIDENCE",
                    "# MAY_BE_FIELD_EVIDENCE", 1))):
            with self.subTest(label=label):
                failures = GATE.scan_script_text(
                    relative_path, changed)["failures"]
                self.assertIn(
                    "legacy_script_banner_invalid:" + relative_path,
                    failures)

    def test_permanent_real_perception_shim_rejects_reachable_model_or_ros2(self):
        relative_path = "scripts/smoke_test_real_perception_startup.sh"
        first_tail = GATE.EXPECTED_SHIM_TAIL[relative_path][0]
        changed = _text(relative_path).replace(
            first_tail,
            "source /opt/ros/foxy/setup.bash\n"
            "ros2 launch limo_cleanup_perception real_perception_only.launch.py\n"
            "python3 -c 'from ultralytics import YOLO'\n" + first_tail,
            1)
        failures = GATE.scan_script_text(relative_path, changed)["failures"]
        self.assertIn(
            "legacy_script_permanent_shim_tail_invalid:" + relative_path,
            failures)

    def test_foxy_graph_or_overlay_body_cannot_be_made_reachable(self):
        relative_path = "scripts/audit_foxy_runtime.sh"
        changed = _text(relative_path).replace("exit 65", "true", 1)
        failures = GATE.scan_script_text(relative_path, changed)["failures"]
        self.assertIn(
            "legacy_script_permanent_shim_tail_invalid:" + relative_path,
            failures)
        self.assertIn(
            "legacy_script_permanent_shim_exit_missing:" + relative_path,
            failures)

    def test_mock_scripts_require_exact_isolation_domains_and_localhost(self):
        perception = "scripts/smoke_test_perception.sh"
        wrong_domain = _text(perception).replace(
            "readonly isolated_domain='193'",
            "readonly isolated_domain='0'", 1)
        failures = GATE.scan_script_text(perception, wrong_domain)["failures"]
        self.assertIn("legacy_script_domain_invalid:" + perception, failures)

        mock_system = "scripts/smoke_test_mock_system.sh"
        missing_localhost = _text(mock_system).replace(
            "export ROS_LOCALHOST_ONLY=1\n", "", 1)
        failures = GATE.scan_script_text(
            mock_system, missing_localhost)["failures"]
        self.assertIn(
            "legacy_script_isolation_environment_invalid:" + mock_system,
            failures)

        override_after_source = _text(perception).replace(
            "export ROS_LOCALHOST_ONLY=1\n",
            "export ROS_LOCALHOST_ONLY=1\n"
            "export ROS_LOCALHOST_ONLY=0\n"
            "export ROS_DOMAIN_ID=0\n",
            1,
        )
        failures = GATE.scan_script_text(
            perception, override_after_source)["failures"]
        self.assertIn(
            "legacy_script_isolation_environment_inventory_invalid:" +
            perception,
            failures,
        )

    def test_mock_safety_array_is_exact_complete_and_ordered(self):
        relative_path = "scripts/smoke_test_perception.sh"
        baseline = _text(relative_path)
        mutations = (
            baseline.replace("  use_mock_executor:=true\n", "", 1),
            baseline.replace(
                "  allow_base_motion:=false\n)",
                "  allow_base_motion:=false\n  unexpected_gate:=true\n)", 1),
            baseline.replace(
                "  use_mock_perception:=true\n  use_real_perception:=false",
                "  use_real_perception:=false\n  use_mock_perception:=true", 1),
        )
        for index, changed in enumerate(mutations):
            with self.subTest(index=index):
                failures = GATE.scan_script_text(
                    relative_path, changed)["failures"]
                self.assertIn(
                    "legacy_script_mock_safety_args_invalid:" + relative_path,
                    failures)

    def test_real_perception_camera_and_motion_enabling_arguments_are_rejected(self):
        relative_path = "scripts/smoke_test_mock_system.sh"
        baseline = _text(relative_path)
        replacements = (
            ("use_real_perception:=false", "use_real_perception:=true"),
            ("allow_arm_motion:=false", "allow_arm_motion:=true"),
            ("allow_gripper_motion:=false", "allow_gripper_motion:=true"),
            ("allow_base_motion:=false", "allow_base_motion:=true"),
            ("use_detection_gate:=true", "start_camera:=true"),
        )
        for original, unsafe in replacements:
            with self.subTest(unsafe=unsafe):
                changed = baseline.replace(original, unsafe, 1)
                failures = GATE.scan_script_text(
                    relative_path, changed)["failures"]
                self.assertIn(
                    "legacy_script_unsafe_configuration:{}:{}".format(
                        relative_path, unsafe), failures)

        perception = "scripts/smoke_test_perception.sh"
        composed = _text(perception).replace(
            'start_system "$normal_launch"',
            "unsafe_gate='use_real_perception:=true'\n"
            'start_system "$normal_launch" "$unsafe_gate"',
            1,
        )
        failures = GATE.scan_script_text(perception, composed)["failures"]
        self.assertIn(
            "legacy_script_mock_scenario_inventory_invalid:" + perception,
            failures,
        )

    def test_ros2_launch_topic_and_message_roles_are_exactly_allowlisted(self):
        relative_path = "scripts/smoke_test_perception.sh"
        baseline = _text(relative_path)
        mutations = (
            baseline.replace(
                "ros2 launch limo_cleanup_bringup cleanup_system.launch.py",
                "ros2 launch evil_pkg evil.launch.py", 1),
            baseline.replace("/cleanup/status", "/camera/color/image_raw", 1),
            baseline.replace("std_msgs/msg/String", "sensor_msgs/msg/Image", 1),
            baseline.replace(
                "cleanup_system.launch.py",
                "cleanup_system.launch.py; ros2 topic pub /cmd_vel X '{}'",
                1,
            ),
        )
        for index, changed in enumerate(mutations):
            with self.subTest(index=index):
                failures = GATE.scan_script_text(
                    relative_path, changed)["failures"]
                self.assertTrue(any(
                    failure.startswith(
                        "legacy_script_ros2_role_not_allowlisted:" +
                        relative_path + ":")
                    for failure in failures), failures)
        for command in (
                'CMD=ros2\n"$CMD" topic list',
                "bash -c 'ros2 topic list'",
                "python3 -c 'from ultralytics import YOLO'",
                "cat /dev/video0",
                "curl https://camera.invalid/status"):
            with self.subTest(disallowed_command=command):
                changed = baseline.replace(
                    "export ROS_LOCALHOST_ONLY=1",
                    command + "\nexport ROS_LOCALHOST_ONLY=1", 1)
                failures = GATE.scan_script_text(
                    relative_path, changed)["failures"]
                self.assertTrue(any(
                    failure.startswith(
                        "legacy_script_disallowed_command_surface:" +
                        relative_path + ":")
                    for failure in failures), failures)

        insertion_point = (
            "test_dir=$(mktemp -d /tmp/limo_cleanup_perception.XXXXXX)")
        indirect_variants = {
            "absolute_ros2": (
                "/opt/ros/foxy/bin/ros2 topic pub /cmd_vel X Y"),
            "dynamic_timeout": (
                "CMD=ros2\n"
                "timeout 5 \"$CMD\" topic pub /cmd_vel X Y"),
            "dynamic_function": (
                "CMD=ros2\n"
                "run_it() { \"$CMD\" topic pub /cmd_vel X Y; }\n"
                "run_it"),
            "alias": (
                "shopt -s expand_aliases\n"
                "alias r=ros2\n"
                "r topic pub /cmd_vel X Y"),
            "perl_system": (
                "perl -e 'system(\"ros2 topic pub /cmd_vel X Y\")'"),
            "awk_system": (
                "awk 'BEGIN { system(\"ros2 topic pub /cmd_vel X Y\") }'"),
        }
        for label, injected in indirect_variants.items():
            with self.subTest(indirect_variant=label):
                changed = baseline.replace(
                    insertion_point,
                    injected + "\n" + insertion_point,
                    1,
                )
                scan = GATE.scan_script_text(relative_path, changed)
                self.assertIn(
                    "legacy_script_reachable_command_inventory_invalid:" +
                    relative_path,
                    scan["failures"],
                )
                self.assertFalse(scan["runtime_execution_performed"])
                self.assertEqual(scan["ros_commands_executed"], 0)
                self.assertEqual(scan["exec_calls"], 0)
        absolute_failures = GATE.scan_script_text(
            relative_path,
            baseline.replace(
                insertion_point,
                indirect_variants["absolute_ros2"] + "\n" +
                insertion_point,
                1,
            ),
        )["failures"]
        self.assertTrue(any(
            failure.startswith(
                "legacy_script_ros2_role_not_allowlisted:" +
                relative_path + ":")
            for failure in absolute_failures), absolute_failures)

    def test_ambient_underlay_and_python_loader_inputs_are_rejected(self):
        relative_path = "scripts/smoke_test_mock_system.sh"
        baseline = _text(relative_path)
        for assignment in (
                "export ROS_PACKAGE_PATH=/tmp/shadow",
                "export PYTHONPATH=/tmp/shadow",
                "export PYTHONHOME=/tmp/shadow",
                "export LD_PRELOAD=/tmp/shadow.so"):
            with self.subTest(assignment=assignment):
                changed = baseline.replace(
                    "export ROS_LOCALHOST_ONLY=1",
                    "export ROS_LOCALHOST_ONLY=1\n" + assignment, 1)
                failures = GATE.scan_script_text(
                    relative_path, changed)["failures"]
                self.assertIn(
                    "legacy_script_ambient_runtime_input:" + relative_path,
                    failures)

    def test_mock_system_workspace_override_and_missing_argument_guard_are_rejected(self):
        relative_path = "scripts/smoke_test_mock_system.sh"
        baseline = _text(relative_path)
        override = baseline.replace(
            GATE.MOCK_SYSTEM_ROOT_COMMANDS[1],
            'workspace="${1:-/tmp/untrusted}"', 1)
        failures = GATE.scan_script_text(relative_path, override)["failures"]
        self.assertIn(
            "legacy_script_workspace_root_invalid:" + relative_path,
            failures)

        missing_guard = _drop_stripped_block(
            baseline, GATE.MOCK_SYSTEM_ARGUMENT_GUARD)
        failures = GATE.scan_script_text(
            relative_path, missing_guard)["failures"]
        self.assertIn(
            "legacy_script_workspace_argument_guard_invalid:" + relative_path,
            failures)

    def test_missing_nonregular_linklike_and_hardlink_artifacts_fail_closed(self):
        relative_path = GATE.SCRIPT_PATHS[0]
        with self._fixture(omitted=(relative_path,)) as root:
            report = GATE.evaluate_legacy_scripts(root)
        self.assertIn(
            "legacy_script_unavailable:" + relative_path,
            report["failures"])

        with self._fixture(omitted=(relative_path,)) as root:
            target = root.joinpath(*Path(relative_path).parts)
            target.mkdir(parents=True)
            report = GATE.evaluate_legacy_scripts(root)
        self.assertIn(
            "legacy_script_artifact_not_regular:" + relative_path,
            report["failures"])

        with self._fixture() as root:
            original = GATE._is_linklike

            def target_linklike(metadata):
                return original(metadata) or stat.S_ISREG(metadata.st_mode)

            with mock.patch.object(GATE, "_is_linklike", target_linklike):
                report = GATE.evaluate_legacy_scripts(root)
        self.assertTrue(any(
            failure.startswith("legacy_script_artifact_linklike:")
            for failure in report["failures"]), report["failures"])

        with self._fixture(omitted=(relative_path,)) as root:
            target = root.joinpath(*Path(relative_path).parts)
            source = root / "hardlink_source.sh"
            source.write_bytes((ROOT / relative_path).read_bytes())
            os.link(str(source), str(target))
            report = GATE.evaluate_legacy_scripts(root)
        self.assertIn(
            "legacy_script_artifact_hardlink:" + relative_path,
            report["failures"])

    def test_invalid_utf8_and_shell_parse_corruption_fail_closed(self):
        relative_path = "scripts/smoke_test_real_perception_startup.sh"
        with self._fixture(overrides={relative_path: b"\xff\xfe"}) as root:
            report = GATE.evaluate_legacy_scripts(root)
        self.assertIn(
            "legacy_script_utf8_invalid:" + relative_path,
            report["failures"])

        relative_path = "scripts/smoke_test_perception.sh"
        changed = _text(relative_path).replace(
            "export ROS_LOCALHOST_ONLY=1",
            "ros2 'unterminated\nexport ROS_LOCALHOST_ONLY=1", 1)
        failures = GATE.scan_script_text(relative_path, changed)["failures"]
        self.assertTrue(any(
            failure.startswith(
                "legacy_script_shell_parse_failed:" + relative_path + ":")
            for failure in failures), failures)

    def test_cli_emits_one_strict_json_marker_for_pass_and_fail_closed_args(self):
        for arguments, expected_exit, expected_pass in (
                ([], 0, True),
                (["--scan-directory"], 64, False)):
            with self.subTest(arguments=arguments):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = GATE.main(arguments)
                self.assertEqual(exit_code, expected_exit)
                lines = output.getvalue().splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith(GATE.MARKER))
                self.assertEqual(lines[0].count(GATE.MARKER), 1)
                payload = json.loads(lines[0][len(GATE.MARKER):])
                self.assertIs(payload["validated_pass"], expected_pass)
                self.assertFalse(payload["runtime_execution_performed"])
                self.assertEqual(payload["ros_commands_executed"], 0)
                self.assertEqual(payload["exec_calls"], 0)
                self.assertFalse(payload["delivery_ready"])


if __name__ == "__main__":
    unittest.main()
