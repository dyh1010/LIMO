"""Static regression tests for camera-only operator entry points."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from audit_tools import ros1_camera_only_atomic_launcher as ATOMIC
from audit_tools import ros1_camera_only_operator_docs as DOCS


ROOT = Path(__file__).resolve().parents[1]


class Ros1CameraOnlyOperatorDocsTest(unittest.TestCase):

    def test_current_fixed_document_set_and_retired_script_pass(self):
        report = DOCS.evaluate_operator_docs(ROOT)
        self.assertTrue(report["validated_pass"], report["failures"])
        self.assertEqual(report["failures"], [])
        self.assertEqual(
            report["documents_expected"], list(DOCS.OPERATIONAL_DOCUMENTS))
        self.assertTrue(report["formal_capture_role_allowlisted"])
        self.assertTrue(report["atomic_camera_role_allowlisted"])
        self.assertTrue(report["hardware_readiness_redirect_validated"])
        self.assertEqual(report["legacy_non_authoritative_count"], 25)
        self.assertEqual(report["unapproved_operational_command_count"], 0)
        current_roles = [
            item for item in report["observed_roles"]
            if item["role"] != "LEGACY_NONAUTHORITATIVE"]
        self.assertEqual(
            [item["role"] for item in current_roles],
            ["ATOMIC_CAMERA_DRIVER", "FORMAL_DETECTOR_CAPTURE"])
        for item in report["observed_roles"]:
            self.assertIsInstance(item["line"], int)
            self.assertTrue(item["path"])
            self.assertTrue(item["normalized"])
            self.assertTrue(item["surfaces"])
        self.assertFalse(report["authorizes_field_delivery"])
        self.assertFalse(report["delivery_ready"])

    def test_historical_camera_template_has_exact_demotion_and_route(self):
        text = (ROOT / DOCS.LEGACY_CAMERA_TEMPLATE).read_text(
            encoding="utf-8")
        self.assertEqual(
            tuple(text.splitlines()[:len(DOCS.LEGACY_CAMERA_TEMPLATE_HEADER)]),
            DOCS.LEGACY_CAMERA_TEMPLATE_HEADER)
        self.assertEqual(
            DOCS.scan_document_text(DOCS.LEGACY_CAMERA_TEMPLATE, text), [])
        self.assertIn(
            "docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md", text)
        self.assertIn("ROS1/Noetic is the current field authority", text)
        self.assertIn("ros2 run limo_cleanup_perception", text)
        self.assertIn("ros2 launch limo_cleanup_bringup", text)
        for _, line, _ in DOCS._copyable_lines(text):
            if line:
                self.assertTrue(line.startswith(DOCS.HISTORICAL_PREFIX), line)

    def test_historical_camera_template_missing_or_weak_banner_is_rejected(self):
        text = (ROOT / DOCS.LEGACY_CAMERA_TEMPLATE).read_text(
            encoding="utf-8")
        variants = (
            text.replace(
                DOCS.LEGACY_CAMERA_TEMPLATE_HEADER[0] + "\n", "", 1),
            text.replace("NON_AUTHORITATIVE / DO NOT RUN", "review before use", 1),
            text.replace(
                "docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md",
                "docs/legacy_ros2_camera_notes.md", 1),
        )
        for changed in variants:
            with self.subTest(changed=changed[:80]):
                failures = DOCS.scan_document_text(
                    DOCS.LEGACY_CAMERA_TEMPLATE, changed)
                self.assertIn(
                    "legacy_camera_template_demotion_banner_invalid",
                    failures)

    def test_historical_camera_template_copyable_ros2_is_rejected(self):
        text = (ROOT / DOCS.LEGACY_CAMERA_TEMPLATE).read_text(
            encoding="utf-8")
        changed = text.replace(
            DOCS.HISTORICAL_PREFIX
            + " ros2 run limo_cleanup_perception rgbd_bag_indexer",
            "ros2 run limo_cleanup_perception rgbd_bag_indexer", 1)
        failures = DOCS.scan_document_text(
            DOCS.LEGACY_CAMERA_TEMPLATE, changed)
        self.assertTrue(any(
            item.startswith(
                "legacy_camera_template_copyable_command_not_demoted:")
            for item in failures))

        shell_block = text + "\n```bash\nros2 launch evil_pkg evil.launch\n```\n"
        failures = DOCS.scan_document_text(
            DOCS.LEGACY_CAMERA_TEMPLATE, shell_block)
        self.assertIn("legacy_camera_template_shell_fence_present", failures)
        self.assertTrue(any(
            item.startswith(
                "legacy_camera_template_copyable_command_not_demoted:")
            for item in failures))

    def test_historical_camera_template_cannot_promote_field_or_delivery(self):
        text = (ROOT / DOCS.LEGACY_CAMERA_TEMPLATE).read_text(
            encoding="utf-8")
        changed = text + (
            "\nHistorical ROS2 PASS is current field and delivery PASS.\n")
        failures = DOCS.scan_document_text(
            DOCS.LEGACY_CAMERA_TEMPLATE, changed)
        self.assertIn(
            "legacy_camera_template_historical_pass_promoted", failures)

    def test_ros2_colcon_and_distro_source_surfaces_fail_closed(self):
        variants = {
            "ros2_launch": "ros2 launch evil_pkg evil.launch.py",
            "ros2_run": "ros2 run evil_pkg evil_node",
            "ros2_bag": "ros2 bag record /camera/image_raw",
            "ros2_topic": "ros2 topic pub /cmd_vel X '{}'",
            "ros2_action": "ros2 action send_goal /move X '{}'",
            "ros2_service": "ros2 service call /reset X '{}'",
            "ros2_node": "ros2 node list",
            "rosbag2": "rosbag2 bag info evidence.db3",
            "colcon": "colcon build --merge-install",
            "source_ros2_foxy": "source /opt/ros/foxy/setup.bash",
            "source_ros2_humble": ". /opt/ros/humble/setup.sh",
        }
        for surface, command in variants.items():
            with self.subTest(surface=surface):
                report = DOCS._scan_document_report(
                    "docs/unknown_operator.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertIn(
                    "operator_doc_legacy_surface_not_demoted:"
                    "docs/unknown_operator.md:2:" + surface,
                    report["failures"])
                self.assertEqual(len(report["observed_roles"]), 1)
                observed = report["observed_roles"][0]
                self.assertEqual(
                    observed["role"], "UNAPPROVED_OPERATIONAL_COMMAND")
                self.assertEqual(observed["path"], "docs/unknown_operator.md")
                self.assertEqual(observed["line"], 2)
                self.assertEqual(observed["normalized"], command)
                self.assertEqual(observed["surfaces"], [surface])

    def test_parsed_actual_command_rejects_ros2_quote_and_escape_aliases(self):
        variants = (
            ("ro''s2 topic list", "ros2 topic list", []),
            ('r"os2" topic list', "ros2 topic list", []),
            (r"r\os2 topic list", "ros2 topic list", []),
            ("env SAFE=1 command ro''s2 topic list",
             "env SAFE=1 command ros2 topic list", ["env", "command"]),
            ("/usr/bin/ro''s2 topic list",
             "/usr/bin/ros2 topic list", []),
            ("SAFE=1 ro''s2 topic list",
             "SAFE=1 ros2 topic list", []),
            ("ro''s2 topic \\\n  list", "ros2 topic list", []),
        )
        for command, normalized, wrappers in variants:
            with self.subTest(command=command):
                report = DOCS._scan_document_report(
                    "docs/tokenized.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertTrue(any(
                    item.startswith(
                        "operator_doc_legacy_surface_not_demoted:")
                    for item in report["failures"]))
                self.assertEqual(len(report["observed_roles"]), 1)
                observed = report["observed_roles"][0]
                self.assertEqual(observed["actual_command"], "ros2")
                self.assertEqual(observed["normalized"], normalized)
                self.assertEqual(observed["wrapper_chain"], wrappers)
                logical, parse_failures = DOCS._logical_shell_commands(
                    "```bash\n{}\n```\n".format(command))
                self.assertEqual(parse_failures, [])
                self.assertEqual(observed["raw"], logical[0][1])

        harmless = DOCS._scan_document_report(
            "docs/tokenized.md",
            "```bash\necho ro''s2 topic list\n```\n")
        self.assertEqual(harmless["failures"], [])
        self.assertEqual(harmless["observed_roles"], [])

    def test_wrappers_continuation_prompt_and_semicolon_do_not_hide_ros2(self):
        variants = (
            "sudo ros2 topic pub /cmd_vel X '{}'",
            "env SAFE=1 command ros2 run evil_pkg evil_node",
            "nohup bash -c 'ros2 node list'",
            "echo harmless; ros2 service call /reset X '{}'",
            "$ ros2 launch evil_pkg \\\n  evil.launch.py",
        )
        for command in variants:
            with self.subTest(command=command):
                report = DOCS._scan_document_report(
                    "docs/wrapped.md",
                    "```console\n{}\n```\n".format(command))
                self.assertTrue(any(
                    item.startswith(
                        "operator_doc_legacy_surface_not_demoted:")
                    for item in report["failures"]))
                self.assertTrue(any(
                    item["role"] == "UNAPPROVED_OPERATIONAL_COMMAND"
                    for item in report["observed_roles"]))

    def test_control_flow_execution_wrappers_and_shell_payload_fail_closed(self):
        variants = (
            "timeout 5 ros2 topic pub /cmd_vel X '{}'",
            "setsid ros2 topic pub /cmd_vel X '{}'",
            "nice ros2 topic pub /cmd_vel X '{}'",
            "stdbuf -oL ros2 topic pub /cmd_vel X '{}'",
            "if ros2 topic pub /cmd_vel X '{}'; then true; fi",
            "! ros2 topic pub /cmd_vel X '{}'",
            "{ ros2 topic pub /cmd_vel X '{}'; }",
            "printf 'ros2 topic pub /cmd_vel X {}\\n' | sh",
            "sh -c \"timeout 5 ros2 topic pub /cmd_vel X '{}'\"",
        )
        for command in variants:
            with self.subTest(command=command):
                report = DOCS._scan_document_report(
                    "docs/control.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertTrue(any(
                    item.startswith(
                        "operator_doc_legacy_surface_not_demoted:")
                    for item in report["failures"]), report)
                self.assertTrue(any(
                    item["actual_command"] == "ros2"
                    and item["role"] == "UNAPPROVED_OPERATIONAL_COMMAND"
                    for item in report["observed_roles"]), report)

        dynamic = DOCS._scan_document_report(
            "docs/control.md",
            "```bash\nCMD=ros2; timeout 5 \"$CMD\" topic pub /cmd_vel X '{}'\n```\n")
        self.assertIn(
            "operator_doc_dynamic_command_position:docs/control.md:2",
            dynamic["failures"])

    def test_env_split_ros2_options_aliases_and_blockquotes_fail_closed(self):
        variants = (
            ("env -S 'ros2 topic pub /cmd_vel X {}'", "ros2_topic", "ros2"),
            ("env --split-string='ros2 topic pub /cmd_vel X {}'",
             "ros2_topic", "ros2"),
            ("ros2 --use-python-default-buffering topic pub /cmd_vel X '{}'",
             "ros2_topic", "ros2"),
            ("ros2 param set /camera exposure 10", "ros2_param", "ros2"),
            ("ros2 component load /container pkg plugin",
             "ros2_component", "ros2"),
        )
        for command, surface, actual in variants:
            with self.subTest(command=command):
                report = DOCS._scan_document_report(
                    "docs/extended.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertTrue(any(
                    surface in item for item in report["failures"]), report)
                observed = report["observed_roles"][0]
                self.assertEqual(observed["actual_command"], actual)
                self.assertEqual(observed["surfaces"], [surface])
                self.assertEqual(observed["raw"], command)

        aliases = DOCS._scan_document_report(
            "docs/aliases.md",
            "```bash\n"
            "shopt -s expand_aliases\n"
            "alias r=ros2\n"
            "r topic pub /cmd_vel X '{}'\n"
            "```\n")
        self.assertTrue(any(
            "shell_shopt" in item for item in aliases["failures"]))
        self.assertTrue(any(
            "shell_alias" in item for item in aliases["failures"]))

        for language in ("bash", "text"):
            with self.subTest(blockquote_language=language):
                blockquote = DOCS._scan_document_report(
                    "docs/quoted.md",
                    "> ```{}\n> ros2 topic pub /cmd_vel X '{{}}'\n> ```\n".format(
                        language))
                self.assertTrue(any(
                    "ros2_topic" in item
                    for item in blockquote["failures"]), blockquote)
                observed = blockquote["observed_roles"][0]
                self.assertEqual(observed["line"], 2)
                self.assertEqual(observed["actual_command"], "ros2")

    def test_unknown_ros2_source_variants_and_indirect_execution_fail_closed(self):
        for subcommand in (
                "lifecycle", "daemon", "doctor", "pkg", "multicast",
                "security", "unknown_plugin"):
            with self.subTest(ros2_subcommand=subcommand):
                report = DOCS._scan_document_report(
                    "docs/ros2-other.md",
                    "```bash\n/usr/bin/ros2 {} --help\n```\n".format(
                        subcommand))
                observed = report["observed_roles"][0]
                self.assertEqual(observed["actual_command"], "ros2")
                self.assertEqual(observed["surfaces"], ["ros2_other"])
                self.assertTrue(report["failures"])

        source_variants = (
            ("source /opt/ros/foxy/./setup.bash", "source_ros2_foxy"),
            (". //opt/ros/humble/../humble/setup.sh", "source_ros2_humble"),
            ("source /opt//ros/foxy/setup.zsh", "source_ros2_foxy"),
        )
        for command, surface in source_variants:
            with self.subTest(source_command=command):
                report = DOCS._scan_document_report(
                    "docs/source.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertEqual(
                    report["observed_roles"][0]["surfaces"], [surface])
                self.assertTrue(report["failures"])

        for command in (
                'source "$ROS_ROOT/setup.bash"',
                '. "/opt/ros/$ROS_DISTRO/setup.bash"'):
            with self.subTest(dynamic_source=command):
                failures = DOCS.scan_document_text(
                    "docs/source.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertIn(
                    "operator_doc_dynamic_command_position:docs/source.md:2",
                    failures)

        indirect = {
            "echo 'ros2 topic list' | sh": "shell_interactive_execution",
            "python3 -m ros2cli topic list": "python_ros2cli_module",
            "python3 -c 'print(1)'": "python_inline_execution",
            "bash scripts/legacy.sh": "shell_script_execution",
            "bash -c 'echo safe'": "shell_inline_execution",
            "make check": "build_tool_execution",
            "ninja test": "build_tool_execution",
        }
        for command, surface in indirect.items():
            with self.subTest(indirect_command=command):
                report = DOCS._scan_document_report(
                    "docs/indirect.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertTrue(any(
                    surface in item["surfaces"]
                    for item in report["observed_roles"]), report)
                self.assertTrue(report["failures"])

        harmless = DOCS._scan_document_report(
            "docs/harmless.md",
            "```bash\necho --roslaunch-size-bytes ros2 topic\n```\n")
        self.assertEqual(harmless["failures"], [])
        self.assertEqual(harmless["observed_roles"], [])

        diagram = DOCS._scan_document_report(
            "docs/diagram.md",
            "```text\nROS2 tracked_base_controller\n```\n")
        self.assertEqual(diagram["failures"], [])
        self.assertEqual(diagram["observed_roles"], [])

    def test_only_exact_legacy_marker_demotes_ros2_action_surface(self):
        command = "ros2 topic pub /cmd_vel geometry_msgs/msg/Twist '{}'"
        exact = (
            "```bash\n" + DOCS.LEGACY_NONAUTHORITATIVE_PREFIX
            + " " + command + "\n```\n")
        report = DOCS._scan_document_report("docs/history.md", exact)
        self.assertEqual(report["failures"], [])
        self.assertEqual(len(report["observed_roles"]), 1)
        observed = report["observed_roles"][0]
        self.assertEqual(observed["role"], "LEGACY_NONAUTHORITATIVE")
        self.assertTrue(observed["exact_line_marker"])
        self.assertFalse(observed["document_level_demotion"])
        self.assertEqual(observed["normalized"], command)

        weak = "```bash\n# HISTORICAL VENDOR — DO NOT RUN\n{}\n```\n".format(
            command)
        failures = DOCS.scan_document_text("docs/history.md", weak)
        self.assertTrue(any(
            item.startswith("operator_doc_legacy_surface_not_demoted:")
            for item in failures))

    def test_unknown_fence_ros2_surface_is_classified_and_rejected(self):
        report = DOCS._scan_document_report(
            "docs/unknown.md",
            "```text\nros2 bag record /camera/image_raw\n```\n")
        self.assertIn(
            "operator_doc_legacy_surface_not_demoted:"
            "docs/unknown.md:2:ros2_bag", report["failures"])
        observed = report["observed_roles"][0]
        self.assertEqual(observed["source_kind"], "non_shell_fence")
        self.assertEqual(observed["role"], "UNAPPROVED_OPERATIONAL_COMMAND")

    def test_hardware_document_demotion_requires_exact_redirect_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                    *DOCS.OPERATIONAL_DOCUMENTS,
                    DOCS.HARDWARE_READINESS_REDIRECT,
                    DOCS.RETIRED_SCRIPT):
                source = ROOT.joinpath(*Path(relative).parts)
                target = root.joinpath(*Path(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            redirect = root.joinpath(
                *Path(DOCS.HARDWARE_READINESS_REDIRECT).parts)
            redirect.write_bytes(redirect.read_bytes() + b"\nweak redirect\n")
            report = DOCS.evaluate_operator_docs(root)
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["hardware_readiness_redirect_validated"])
        self.assertIn(
            "hardware_readiness_redirect_identity_invalid",
            report["failures"])
        self.assertGreater(report["unapproved_operational_command_count"], 0)

    def test_removing_historical_marker_is_rejected(self):
        text = (ROOT / DOCS.AUTHORITY_RUNBOOK).read_text(encoding="utf-8")
        changed = text.replace(DOCS.AUTHORITY_HISTORICAL_LINES[0],
                               "source /opt/ros/noetic/setup.bash", 1)
        failures = DOCS.scan_document_text(DOCS.AUTHORITY_RUNBOOK, changed)
        self.assertIn("authority_runbook_historical_marker_invalid", failures)

    def test_uncommented_historical_roslaunch_is_rejected(self):
        text = (ROOT / DOCS.AUTHORITY_RUNBOOK).read_text(encoding="utf-8")
        changed = text.replace(
            DOCS.HISTORICAL_PREFIX +
            " roslaunch astra_camera dabai_u3.launch",
            "roslaunch astra_camera dabai_u3.launch")
        failures = DOCS.scan_document_text(DOCS.AUTHORITY_RUNBOOK, changed)
        self.assertIn(
            "operator_doc_roslaunch_role_not_allowlisted:"
            + DOCS.AUTHORITY_RUNBOOK + ":22", failures)

    def test_other_operator_document_cannot_add_direct_camera_launch(self):
        text = """# operator\n\n```bash\nroslaunch astra_camera dabai_u3.launch\n```\n"""
        failures = DOCS.scan_document_text(
            "docs/hardware_readiness.md", text)
        self.assertEqual(
            failures,
            ["operator_doc_roslaunch_role_not_allowlisted:"
             "docs/hardware_readiness.md:4"])

    def test_retired_script_cannot_restore_execution(self):
        text = """#!/usr/bin/env bash\nexec roslaunch astra_camera dabai_u3.launch\n"""
        failures = DOCS.scan_retired_script_text(text)
        self.assertIn(
            "retired_start_script_executable_token:exec roslaunch", failures)
        self.assertIn(
            "retired_start_script_executable_token:roslaunch astra_camera",
            failures)

    def test_direct_absolute_vendor_and_retired_script_are_rejected(self):
        text = """```sh\nroslaunch \"$ACTUAL_VENDOR_LAUNCH\"\nscripts/start_dabai_camera.sh\n```\n"""
        failures = DOCS.scan_document_text("docs/real_perception.md", text)
        self.assertEqual(len(failures), 2)
        self.assertTrue(any(
            "roslaunch_role_not_allowlisted" in item for item in failures))
        self.assertTrue(any(
            "retired_start_script_invocation" in item for item in failures))

    def test_exact_formal_detector_role_and_console_prompt_are_allowed(self):
        text = (
            "```bash\n"
            "$ roslaunch limo_cleanup_ros1_perception "
            "perception_v2_formal_capture.launch \\\n"
            "  task_id:=\"$TASK_ID\" \\\n"
            "  capture_id:=\"$CAPTURE_ID\"\n"
            "```\n")
        commands, failures = DOCS._logical_shell_commands(text)
        self.assertEqual(failures, [])
        self.assertEqual(commands, [(2, DOCS.FORMAL_CAPTURE_COMMAND)])
        self.assertRegex(commands[0][1], DOCS._FORMAL_CAPTURE_ROLE)
        self.assertEqual(
            DOCS.scan_document_text("docs/real_perception.md", text), [])

    def test_console_prompt_does_not_hide_unapproved_roslaunch(self):
        for command in (
                "$ roslaunch astra_camera dabai_u3.launch",
                "agilex@limo:~/ws$ roslaunch evil_pkg evil.launch"):
            with self.subTest(command=command):
                text = "```console\n{}\n```\n".format(command)
                failures = DOCS.scan_document_text(
                    "docs/hardware_readiness.md", text)
                self.assertTrue(any(
                    "roslaunch_role_not_allowlisted" in item
                    for item in failures))

    def test_roslaunch_backslash_continuation_is_one_rejected_command(self):
        text = (
            "```bash\n"
            "roslaunch astra_camera \\\n"
            "  dabai_u3.launch\n"
            "```\n")
        commands, parse_failures = DOCS._logical_shell_commands(text)
        self.assertEqual(parse_failures, [])
        self.assertEqual(
            commands, [(2, "roslaunch astra_camera dabai_u3.launch")])
        failures = DOCS.scan_document_text(
            "docs/hardware_readiness.md", text)
        self.assertEqual(len(failures), 1)
        self.assertIn("roslaunch_role_not_allowlisted", failures[0])

    def test_roslaunch_wrappers_are_never_allowlisted(self):
        formal = DOCS.FORMAL_CAPTURE_COMMAND
        variants = (
            "sudo " + formal,
            "env SAFE=1 " + formal,
            "command " + formal,
            "nohup " + formal,
            "bash -c '{}'".format(formal),
            "sh -c '{}'".format(formal),
            "/usr/bin/roslaunch evil_pkg evil.launch",
            "roslaunch other_pkg perception_v2_formal_capture.launch",
        )
        for command in variants:
            with self.subTest(command=command):
                text = "```sh\n{}\n```\n".format(command)
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md", text)
                self.assertTrue(any(
                    "roslaunch_role_not_allowlisted" in item
                    for item in failures))
                if command.startswith(("bash ", "sh ")):
                    self.assertTrue(any(
                        "shell_inline_execution" in item
                        for item in failures))
                else:
                    self.assertEqual(len(failures), 1)

    def test_shell_operators_substitution_and_token_join_are_rejected(self):
        variants = (
            "true && roslaunch evil_pkg evil.launch",
            "printf ok | roslaunch evil_pkg evil.launch",
            "echo $(roslaunch evil_pkg evil.launch)",
            "echo `roslaunch evil_pkg evil.launch`",
            "ro''slaunch evil_pkg evil.launch",
        )
        for command in variants:
            with self.subTest(command=command):
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertEqual(len(failures), 1)
                self.assertIn("roslaunch_role_not_allowlisted", failures[0])

    def test_malformed_shell_is_fail_closed(self):
        failures = DOCS.scan_document_text(
            "docs/real_perception.md",
            "```bash\nroslaunch 'unterminated\n```\n")
        self.assertEqual(
            failures,
            ["operator_doc_shell_parse_failed:docs/real_perception.md:2"])

    def test_formal_role_requires_complete_fixed_parameters(self):
        variants = (
            "roslaunch limo_cleanup_ros1_perception "
            "perception_v2_formal_capture.launch",
            DOCS.FORMAL_CAPTURE_COMMAND + " extra:=true",
            DOCS.FORMAL_CAPTURE_COMMAND.replace(
                'capture_id:="$CAPTURE_ID"', 'capture_id:="$OTHER"'),
        )
        for command in variants:
            with self.subTest(command=command):
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertEqual(len(failures), 1)
                self.assertIn("roslaunch_role_not_allowlisted", failures[0])

    def test_exact_atomic_python_role_is_allowlisted_but_wrappers_are_not(self):
        exact = "```bash\n{}\n```\n".format(DOCS.ATOMIC_CAMERA_COMMAND)
        self.assertEqual(
            DOCS.scan_document_text("docs/hardware_readiness.md", exact), [])
        cases = (
            ("sudo " + DOCS.ATOMIC_CAMERA_COMMAND,
             "atomic_cli_execution_prefix_mismatch"),
            (DOCS.ATOMIC_CAMERA_COMMAND + " cmd_vel:=/evil",
             "atomic_cli_unexpected_positional_argument"),
            (DOCS.ATOMIC_CAMERA_COMMAND.replace("python3", "python"),
             "atomic_cli_execution_prefix_mismatch"),
        )
        for command, code in cases:
            with self.subTest(command=command, code=code):
                failures = DOCS.scan_document_text(
                    "docs/hardware_readiness.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertEqual(
                    failures,
                    ["{}:docs/hardware_readiness.md:2".format(code)])

    def test_copyable_atomic_command_matches_exact_production_parser(self):
        tokens, parsed_cleanly = DOCS._shell_tokens(DOCS.ATOMIC_CAMERA_COMMAND)
        self.assertTrue(parsed_cleanly)
        prefix = list(DOCS.ATOMIC_CAMERA_EXEC_PREFIX)
        self.assertEqual(tokens[:len(prefix)], prefix)
        parsed = ATOMIC.parse_args(tokens[len(prefix):])
        self.assertEqual(parsed.mode, ATOMIC.MODE)
        self.assertEqual(
            str(parsed.actual_vendor_launch), "$ACTUAL_VENDOR_LAUNCH")
        self.assertEqual(
            tuple(ATOMIC.CLI_REQUIRED_OPTIONS),
            DOCS.ATOMIC_CAMERA_REQUIRED_OPTIONS)

    def test_copyable_atomic_command_argument_contract_fails_closed(self):
        base = DOCS.ATOMIC_CAMERA_COMMAND
        cases = (
            (base + ' --roslaunch-size-bytes "$ROSLAUNCH_SIZE_BYTES"',
             "atomic_cli_unknown_argument"),
            (base.replace(
                "--mode EXECUTE_AUDITED_CAMERA_ONLY ", ""),
             "atomic_cli_missing_argument:mode"),
            (base + " --mode EXECUTE_AUDITED_CAMERA_ONLY",
             "atomic_cli_duplicate_argument:mode"),
            (base.replace(
                '--actual-vendor-launch "$ACTUAL_VENDOR_LAUNCH"',
                "--actual-vendor-launch"),
             "atomic_cli_missing_argument_value:actual_vendor_launch"),
            (base.replace("EXECUTE_AUDITED_CAMERA_ONLY", "UNSAFE"),
             "atomic_cli_argument_value_mismatch:mode"),
            (base + " unexpected",
             "atomic_cli_unexpected_positional_argument"),
        )
        for command, code in cases:
            with self.subTest(code=code):
                failures = DOCS.scan_document_text(
                    "docs/hardware_readiness.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertEqual(
                    failures,
                    ["{}:docs/hardware_readiness.md:2".format(code)])

    def test_only_exact_historical_marker_comment_is_exempt(self):
        exact = "    " + DOCS.HISTORICAL_PREFIX + (
            " roslaunch astra_camera dabai_u3.launch\n")
        self.assertEqual(
            DOCS.scan_document_text("docs/hardware_readiness.md", exact), [])
        generic = "    # roslaunch astra_camera dabai_u3.launch\n"
        failures = DOCS.scan_document_text(
            "docs/hardware_readiness.md", generic)
        self.assertTrue(any(
            "roslaunch_role_not_allowlisted" in item for item in failures))

    def test_historical_marker_is_an_exact_per_document_inventory(self):
        runbook = (ROOT / DOCS.AUTHORITY_RUNBOOK).read_text(encoding="utf-8")
        changed = runbook + (
            "\n    " + DOCS.HISTORICAL_PREFIX
            + " roslaunch evil_pkg evil.launch\n")
        failures = DOCS.scan_document_text(DOCS.AUTHORITY_RUNBOOK, changed)
        self.assertIn(
            "operator_doc_historical_inventory_invalid:"
            + DOCS.AUTHORITY_RUNBOOK, failures)

        failures = DOCS.scan_document_text(
            "docs/hardware_readiness.md",
            "    " + DOCS.HISTORICAL_PREFIX
            + " roslaunch evil_pkg evil.launch\n")
        self.assertIn(
            "operator_doc_historical_inventory_invalid:"
            "docs/hardware_readiness.md", failures)

    def test_any_gate_failure_clears_both_role_allowlist_declarations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (*DOCS.OPERATIONAL_DOCUMENTS,
                             DOCS.HARDWARE_READINESS_REDIRECT,
                             DOCS.RETIRED_SCRIPT):
                source = ROOT.joinpath(*Path(relative).parts)
                target = root.joinpath(*Path(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            target = root.joinpath(*Path(
                "docs/hardware_readiness.md").parts)
            text = target.read_text(encoding="utf-8")
            text += (
                "\n    " + DOCS.HISTORICAL_PREFIX
                + " roslaunch evil_pkg evil.launch\n")
            target.write_text(text, encoding="utf-8")
            report = DOCS.evaluate_operator_docs(root)
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["formal_capture_role_allowlisted"])
        self.assertFalse(report["atomic_camera_role_allowlisted"])
        self.assertIn(
            "operator_doc_historical_inventory_invalid:"
            "docs/hardware_readiness.md", report["failures"])

    def test_roslaunch_assignment_indirection_is_rejected_without_false_hits(self):
        variants = (
            'CMD=roslaunch; "$CMD" evil_pkg evil.launch',
            'env CMD=/usr/bin/roslaunch sh -c "$CMD evil_pkg evil.launch"',
            "CMD=ro''slaunch; \"$CMD\" evil_pkg evil.launch",
        )
        for command in variants:
            with self.subTest(command=command):
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertTrue(any(
                    "roslaunch_role_not_allowlisted" in item
                    for item in failures))
        for harmless in (
                "echo --roslaunch-size-bytes",
                "echo --roslaunch-sha256",
                "echo crosslaunch"):
            with self.subTest(harmless=harmless):
                self.assertEqual(
                    DOCS.scan_document_text(
                        "docs/real_perception.md",
                        "```bash\n{}\n```\n".format(harmless)), [])

    def test_dynamic_command_name_composition_is_fail_closed(self):
        variants = (
            'A=ros; B=launch; "$A$B" evil_pkg evil.launch',
            'X=; CMD=ros${X}launch; "$CMD" evil_pkg evil.launch',
        )
        for command in variants:
            with self.subTest(command=command):
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertIn(
                    "operator_doc_dynamic_command_position:"
                    "docs/real_perception.md:2", failures)

    def test_non_shell_fence_launch_surface_is_rejected_without_flag_noise(self):
        failures = DOCS.scan_document_text(
            "docs/real_perception.md",
            "```text\nroslaunch evil_pkg evil.launch\n```\n")
        self.assertEqual(
            failures,
            ["operator_doc_non_shell_fence_launch_surface:"
             "docs/real_perception.md:2"])
        malformed = DOCS.scan_document_text(
            "docs/real_perception.md",
            "```text\nroslaunch 'unterminated\n```\n")
        self.assertEqual(
            malformed,
            ["operator_doc_non_shell_fence_parse_failed:"
             "docs/real_perception.md:2",
             "operator_doc_non_shell_fence_launch_surface:"
             "docs/real_perception.md:2"])
        dynamic = DOCS.scan_document_text(
            "docs/real_perception.md",
            "```text\nA=ros; B=launch; \"$A$B\" evil.launch\n```\n")
        self.assertEqual(
            dynamic,
            ["operator_doc_non_shell_fence_dynamic_command_position:"
             "docs/real_perception.md:2"])
        harmless = (
            "```text\n"
            "--roslaunch-size-bytes is evidence metadata\n"
            "crosslaunch is not a command\n"
            "```\n")
        self.assertEqual(
            DOCS.scan_document_text("docs/real_perception.md", harmless), [])

    def test_retired_script_absolute_quoted_and_restored_execution_are_rejected(self):
        for command in (
                "/opt/workspace/scripts/start_dabai_camera.sh",
                "bash -c 'scripts/start_dabai_camera.sh'",
                "sh -c '/opt/workspace/scripts/start_dabai_camera.sh'",
                "scripts/start_dabai_camera.s''h",
                "bash -c '/opt/work'/'scripts/start_dabai_camera.s''h'"):
            with self.subTest(command=command):
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md",
                    "```bash\n{}\n```\n".format(command))
                self.assertTrue(any(
                    "retired_start_script_invocation" in item
                    for item in failures))

        source = (ROOT / DOCS.RETIRED_SCRIPT).read_text(encoding="utf-8")
        for addition in (
                "\nexec /opt/ros/noetic/bin/roslaunch "
                "/tmp/vendor.launch\n",
                "\npython3 -I -S -B "
                "audit_tools/ros1_camera_only_atomic_launcher.py "
                "--mode EXECUTE_AUDITED_CAMERA_ONLY\n"):
            with self.subTest(addition=addition):
                failures = DOCS.scan_retired_script_text(source + addition)
                self.assertIn(
                    "retired_start_script_command_inventory_invalid",
                    failures)

    def test_fence_attributes_and_bracket_console_prompt_are_scanned(self):
        for opening in ('```bash title="launch"', '```{.bash}'):
            with self.subTest(opening=opening):
                failures = DOCS.scan_document_text(
                    "docs/real_perception.md",
                    opening + "\nroslaunch evil_pkg evil.launch\n```\n")
                self.assertTrue(any(
                    "roslaunch_role_not_allowlisted" in item
                    for item in failures))

        text = (
            "```console\n[root@limo ~]# "
            + DOCS.FORMAL_CAPTURE_COMMAND + "\n```\n")
        commands, failures = DOCS._logical_shell_commands(text)
        self.assertEqual(failures, [])
        self.assertEqual(commands, [(2, DOCS.FORMAL_CAPTURE_COMMAND)])
        self.assertEqual(
            DOCS.scan_document_text("docs/real_perception.md", text), [])

    def test_role_allowlist_report_is_computed_not_hardcoded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (*DOCS.OPERATIONAL_DOCUMENTS,
                             DOCS.HARDWARE_READINESS_REDIRECT,
                             DOCS.RETIRED_SCRIPT):
                source = ROOT.joinpath(*Path(relative).parts)
                target = root.joinpath(*Path(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            extra = root.joinpath(
                *Path("docs/hardware_readiness.md").parts)
            text = extra.read_text(encoding="utf-8")
            text += "\n```bash\n{}\n```\n".format(
                DOCS.FORMAL_CAPTURE_COMMAND)
            extra.write_text(text, encoding="utf-8")
            report = DOCS.evaluate_operator_docs(root)
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["formal_capture_role_allowlisted"])
        self.assertIn(
            "formal_capture_role_observation_mismatch", report["failures"])

    def test_cli_emits_one_marker_and_nonzero_for_invalid_gate(self):
        invalid = {
            "schema_version": DOCS.SCHEMA_VERSION,
            "validated_pass": False,
            "failures": ["operator_doc_roslaunch_role_not_allowlisted:x:1"],
            "formal_capture_role_allowlisted": False,
            "atomic_camera_role_allowlisted": False,
            "delivery_ready": False,
        }
        output = io.StringIO()
        with mock.patch.object(
                DOCS, "evaluate_operator_docs", return_value=invalid):
            with redirect_stdout(output):
                exit_code = DOCS.main([])
        self.assertEqual(exit_code, 4)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(DOCS.MARKER))
        payload = json.loads(lines[0][len(DOCS.MARKER):])
        self.assertFalse(payload["validated_pass"])


if __name__ == "__main__":
    unittest.main()
