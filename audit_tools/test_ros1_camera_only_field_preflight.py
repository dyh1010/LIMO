"""Pure-software tests for the inert ROS1 camera-only static preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from audit_tools import ros1_camera_only_field_preflight as PREFLIGHT


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md"
PINNED = (
    PREFLIGHT.PREDECESSOR_AUTHORITY_V4,
    PREFLIGHT.FROZEN_CANONICAL_V5,
    PREFLIGHT.FROZEN_REPORT_V4,
    PREFLIGHT.DABAI_LAUNCH,
    PREFLIGHT.FORMAL_CAPTURE_LAUNCH,
)


def _copy_pinned_workspace(destination: Path) -> None:
    for expected in PINNED:
        source = ROOT.joinpath(*Path(expected["path"]).parts)
        target = destination.joinpath(*Path(expected["path"]).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _write_executable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if os.name != "nt":
        path.chmod(0o755)


def _complete_environment(root: Path) -> Path:
    setup = root / "opt" / "ros" / "noetic" / "setup.bash"
    setup.parent.mkdir(parents=True, exist_ok=True)
    setup.write_bytes(b"# inert fixture; never sourced\n")
    _write_executable(
        root / "usr" / "bin" / "catkin_make", b"#!/bin/sh\nexit 99\n")
    _write_executable(
        root / "usr" / "bin" / "cmake", b"#!/bin/sh\nexit 99\n")
    python = root / "usr" / "bin" / "python3.10"
    _write_executable(python, b"#!/bin/sh\nexit 99\n")
    return python


class Ros1CameraOnlyFieldPreflightTest(unittest.TestCase):

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="ros1-camera-static-preflight-")
        self.temp_root = Path(self.temporary.name)
        self.workspace = self.temp_root / "workspace"
        self.environment = self.temp_root / "environment"
        self.workspace.mkdir()
        self.environment.mkdir()
        _copy_pinned_workspace(self.workspace)
        self.actual_vendor_launch = (
            self.temp_root / "live_vendor" / "dabai_u3.launch")
        self.actual_vendor_launch.parent.mkdir(parents=True)
        shutil.copyfile(
            ROOT.joinpath(*Path(PREFLIGHT.DABAI_LAUNCH["path"]).parts),
            self.actual_vendor_launch)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _evaluate_actual(
            self, actual_vendor_launch, expected_actual_vendor_launch_path):
        python = _complete_environment(self.environment)
        with mock.patch.object(
                PREFLIGHT, "PRODUCTION_VENDOR_LAUNCH_PATH",
                str(expected_actual_vendor_launch_path)):
            return PREFLIGHT.evaluate_preflight(
                self.workspace,
                self.environment,
                actual_vendor_launch=actual_vendor_launch,
                python_executable=python,
                python_version=(3, 10, 12),
            )

    def _evaluate(self):
        return self._evaluate_actual(
            self.actual_vendor_launch, self.actual_vendor_launch)

    def test_complete_static_surface_passes_but_never_authorizes_field(self):
        result = self._evaluate()
        self.assertTrue(result["preflight_pass"], result["failures"])
        self.assertTrue(result["lineage_reference_pass"])
        self.assertTrue(result["static_launch_safety_pass"])
        self.assertTrue(result["toolchain"]["validated_pass"])
        archive = result["launch_admission"]["dabai_archive_reference"]
        live = result["launch_admission"]["actual_vendor_launch"]
        self.assertEqual(
            archive["reference_role"],
            "FROZEN_VENDOR_LAUNCH_REFERENCE_ONLY")
        self.assertFalse(archive["selected_as_execution_target"])
        self.assertEqual(
            live["execution_target_role"], "EXPLICIT_LIVE_VENDOR_LAUNCH")
        self.assertTrue(live["archive_live_identity_match"])
        self.assertTrue(live["stable_across_semantic_validation"])
        self.assertTrue(live["static_camera_only_semantics_pass"])
        for key in (
                "starts_ros_graph", "starts_camera", "runs_inference",
                "records_rosbag", "publishes_ros_messages",
                "publishes_control_messages", "authorizes_motion",
                "authorizes_field_delivery",
                "accepted_by_formal_field_evidence_consumer",
                "formal_consumer", "formal_acceptance", "formal_tf_pass",
                "formal_3d_pass", "formal_latency_pass", "delivery_ready"):
            self.assertFalse(result[key], key)
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)
        self.assertIn(
            "ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED", result["blockers"])
        self.assertIn(
            "ROS1_FORMAL_FOUR_SCENE_EVIDENCE_MISSING", result["blockers"])

    def test_missing_noetic_surface_is_stable_environment_blocker(self):
        python = self.environment / "usr" / "bin" / "python3.10"
        _write_executable(python, b"#!/bin/sh\nexit 99\n")
        result = PREFLIGHT.evaluate_preflight(
            self.workspace, self.environment,
            actual_vendor_launch=self.actual_vendor_launch,
            python_executable=python, python_version=(3, 10, 12))
        self.assertFalse(result["preflight_pass"])
        self.assertFalse(result["toolchain"]["validated_pass"])
        self.assertIn("ROS1_NOETIC_TOOLCHAIN_NOT_AVAILABLE", result["failures"])
        self.assertIn(
            "ROS1_NOETIC_SETUP_BASH_NOT_AVAILABLE", result["failures"])
        self.assertIn("ROS1_CATKIN_MAKE_NOT_AVAILABLE", result["failures"])
        self.assertIn("ROS1_CMAKE_NOT_AVAILABLE", result["failures"])
        self.assertNotIn("ROS1_SOURCE_BUILD_FAILED", result["blockers"])
        self.assertFalse(result["delivery_ready"])

    def test_frozen_lineage_is_exact_and_reference_only(self):
        result = self._evaluate()
        predecessor = result["predecessor_authority_v4"]
        self.assertEqual(predecessor["path"], PREFLIGHT.PREDECESSOR_AUTHORITY_V4["path"])
        self.assertEqual(predecessor["size_bytes"], 5015)
        self.assertEqual(
            predecessor["sha256"],
            "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded")
        self.assertEqual(predecessor["reference_role"], "FROZEN_PREDECESSOR_ONLY")
        self.assertFalse(predecessor["selected_as_new_field_authority"])
        references = result["frozen_predecessor_references"]
        self.assertFalse(references["canonical_v5"]["reinterpreted_for_live_source"])
        self.assertFalse(references["report_v4"]["reinterpreted_as_field_evidence"])

    def test_each_frozen_identity_drift_fails_closed(self):
        for expected, code in (
                (PREFLIGHT.PREDECESSOR_AUTHORITY_V4,
                 "predecessor_authority_v4_sha256_mismatch"),
                (PREFLIGHT.FROZEN_CANONICAL_V5,
                 "frozen_canonical_v5_reference_sha256_mismatch"),
                (PREFLIGHT.FROZEN_REPORT_V4,
                 "frozen_report_v4_reference_sha256_mismatch")):
            with self.subTest(path=expected["path"]):
                _copy_pinned_workspace(self.workspace)
                path = self.workspace.joinpath(*Path(expected["path"]).parts)
                raw = bytearray(path.read_bytes())
                raw[-1] ^= 1
                path.write_bytes(raw)
                result = self._evaluate()
                self.assertFalse(result["lineage_reference_pass"])
                self.assertFalse(result["preflight_pass"])
                self.assertIn(code, result["failures"])
                self.assertFalse(result["delivery_ready"])

    def test_predecessor_semantics_cannot_promote_field_or_delivery(self):
        source = ROOT.joinpath(
            *Path(PREFLIGHT.PREDECESSOR_AUTHORITY_V4["path"]).parts)
        value = json.loads(source.read_text(encoding="utf-8"))
        value["accepted_by_formal_field_evidence_consumer"] = True
        value["authorizes_field_delivery"] = True
        value["gate_state"]["delivery_ready"] = True
        raw = json.dumps(value, sort_keys=True).encode("utf-8")
        self.assertEqual(
            PREFLIGHT._validate_predecessor_payload(raw),
            ["predecessor_authority_v4_semantic_mismatch"])

    def test_real_launch_bytes_have_exact_static_semantics(self):
        dabai = ROOT.joinpath(*Path(PREFLIGHT.DABAI_LAUNCH["path"]).parts)
        formal = ROOT.joinpath(*Path(PREFLIGHT.FORMAL_CAPTURE_LAUNCH["path"]).parts)
        self.assertEqual(PREFLIGHT._validate_dabai_launch_bytes(dabai.read_bytes()), [])
        self.assertEqual(PREFLIGHT._validate_formal_launch_bytes(formal.read_bytes()), [])
        root = ET.fromstring(dabai.read_bytes())
        args = [item for item in list(root) if item.tag == "arg"]
        node = [item for item in root.iter() if item.tag == "node"][0]
        params = [item for item in list(node) if item.tag == "param"]
        remaps = [item for item in list(node) if item.tag == "remap"]
        self.assertEqual(len(PREFLIGHT.DABAI_ARG_DEFAULTS), 52)
        self.assertEqual(len(PREFLIGHT.DABAI_PARAM_ORDER), 52)
        self.assertEqual(len(args), 52)
        self.assertEqual(len(params), 52)
        self.assertEqual(len(remaps), 1)

    def test_formal_launch_requires_explicit_task_and_capture_and_exact_topology(self):
        path = ROOT.joinpath(*Path(PREFLIGHT.FORMAL_CAPTURE_LAUNCH["path"]).parts)
        baseline = path.read_text(encoding="utf-8")
        mutations = {
            "missing_task": baseline.replace('  <arg name="task_id"/>\n', ""),
            "default_capture": baseline.replace(
                '<arg name="capture_id"/>',
                '<arg name="capture_id" default="self-reported"/>'),
            "missing_formal_mode": baseline.replace(
                '    <param name="formal_capture_mode" value="true"/>\n', ""),
            "wrong_formal_mode": baseline.replace(
                'name="formal_capture_mode" value="true"',
                'name="formal_capture_mode" value="false"'),
            "remap": baseline.replace(
                "  </node>",
                '    <remap from="/cleanup/perception/frames" '
                'to="/cmd_vel"/>\n  </node>'),
            "extra_node": baseline.replace(
                "</launch>",
                '<node pkg="rogue" type="rogue" name="rogue"/>\n</launch>'),
            "env_substitution": baseline.replace(
                'value="$(arg task_id)"', 'value="$(env TASK_ID)"'),
            "entity": baseline.replace(
                "<launch>", '<!DOCTYPE launch [<!ENTITY x "task">]>\n<launch>'),
        }
        for name, value in mutations.items():
            with self.subTest(name=name):
                self.assertTrue(
                    PREFLIGHT._validate_formal_launch_bytes(
                        value.encode("utf-8")))

    def test_dabai_control_surface_or_unknown_topology_is_rejected(self):
        path = ROOT.joinpath(*Path(PREFLIGHT.DABAI_LAUNCH["path"]).parts)
        baseline = path.read_text(encoding="utf-8")
        for name, value in {
                "control_remap": baseline.replace(
                    "</node>", '<remap from="x" to="/cmd_vel"/>\n</node>'),
                "include": baseline.replace(
                    "</launch>", '<include file="control.launch"/>\n</launch>'),
                "environment": baseline.replace(
                    'default="camera"', 'default="$(env CAMERA_NAME)"', 1),
                "entity": baseline.replace(
                    "<launch>", '<!DOCTYPE launch [<!ENTITY x "camera">]>\n<launch>'),
                "extra_arg": baseline.replace(
                    "    <group ns=", '    <arg name="extra" default="x"/>\n'
                    "    <group ns=", 1),
                "duplicate_arg": baseline.replace(
                    '<arg name="camera_name" default="camera"/>',
                    '<arg name="camera_name" default="camera"/>\n'
                    '    <arg name="camera_name" default="camera"/>', 1),
                "extra_param": baseline.replace(
                    "            <remap from=",
                    '            <param name="extra" value="x"/>\n'
                    "            <remap from=", 1),
                "duplicate_param": baseline.replace(
                    '<param name="camera_name" value="$(arg camera_name)"/>',
                    '<param name="camera_name" value="$(arg camera_name)"/>\n'
                    '            <param name="camera_name" '
                    'value="$(arg camera_name)"/>', 1),
                "param_command": baseline.replace(
                    '<param name="camera_name" value="$(arg camera_name)"/>',
                    '<param name="camera_name" command="/bin/true"/>', 1),
                "param_textfile": baseline.replace(
                    '<param name="camera_name" value="$(arg camera_name)"/>',
                    '<param name="camera_name" textfile="/etc/passwd"/>', 1),
                "param_binfile": baseline.replace(
                    '<param name="camera_name" value="$(arg camera_name)"/>',
                    '<param name="camera_name" binfile="/tmp/payload"/>', 1),
                "unapproved_param_type": baseline.replace(
                    '<param name="camera_name" value="$(arg camera_name)"/>',
                    '<param name="camera_name" type="str" '
                    'value="$(arg camera_name)"/>', 1),
                "unknown_node_child": baseline.replace(
                    "            <remap from=",
                    '            <env name="X" value="Y"/>\n'
                    "            <remap from=", 1),
                "unknown_node_attribute": baseline.replace(
                    'output="screen">', 'output="screen" respawn="true">', 1),
        }.items():
            with self.subTest(name=name):
                self.assertTrue(
                    PREFLIGHT._validate_dabai_launch_bytes(value.encode("utf-8")))

    def test_actual_vendor_launch_is_required_absolute_and_exact_path_bound(self):
        missing = self._evaluate_actual(None, self.actual_vendor_launch)
        self.assertFalse(missing["preflight_pass"])
        self.assertIn("actual_vendor_launch_required", missing["failures"])

        relative = self._evaluate_actual(
            Path("dabai_u3.launch"), self.actual_vendor_launch)
        self.assertFalse(relative["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_path_not_absolute", relative["failures"])

        wrong_fixed_target = PREFLIGHT.evaluate_preflight(
            self.workspace,
            self.environment,
            actual_vendor_launch=self.actual_vendor_launch,
            python_executable=_complete_environment(self.environment),
            python_version=(3, 10, 12),
        )
        self.assertFalse(wrong_fixed_target["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_exact_path_mismatch",
            wrong_fixed_target["failures"])
        self.assertEqual(
            wrong_fixed_target["launch_admission"]["actual_vendor_launch"]
            ["production_required_path"],
            PREFLIGHT.PRODUCTION_VENDOR_LAUNCH_PATH)

    def test_safe_archive_cannot_substitute_for_malicious_actual_launch(self):
        baseline = self.actual_vendor_launch.read_text(encoding="utf-8")
        self.actual_vendor_launch.write_text(
            baseline.replace(
                "</node>", '<remap from="x" to="/cmd_vel"/>\n</node>'),
            encoding="utf-8")
        result = self._evaluate()
        archive = result["launch_admission"]["dabai_archive_reference"]
        live = result["launch_admission"]["actual_vendor_launch"]
        self.assertTrue(archive["static_camera_only_semantics_pass"])
        self.assertFalse(live["static_camera_only_semantics_pass"])
        self.assertFalse(result["static_launch_safety_pass"])
        self.assertIn("actual_vendor_launch_sha256_mismatch", result["failures"])
        self.assertTrue(any(
            item.startswith("actual_vendor_launch_semantic:")
            for item in result["failures"]))
        self.assertFalse(result["delivery_ready"])

    def test_actual_vendor_launch_archive_reuse_and_nonregular_are_rejected(self):
        archive_path = self.workspace.joinpath(
            *Path(PREFLIGHT.DABAI_LAUNCH["path"]).parts)
        reused = self._evaluate_actual(archive_path, archive_path)
        self.assertFalse(reused["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_reuses_archive_reference",
            reused["failures"])

        self.actual_vendor_launch.unlink()
        self.actual_vendor_launch.mkdir()
        nonregular = self._evaluate()
        self.assertFalse(nonregular["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_artifact_linklike_or_nonregular",
            nonregular["failures"])

    def test_actual_vendor_launch_hardlink_or_wrong_basename_is_rejected(self):
        backing = self.actual_vendor_launch.with_name("backing.launch")
        shutil.copyfile(self.actual_vendor_launch, backing)
        self.actual_vendor_launch.unlink()
        os.link(backing, self.actual_vendor_launch)
        hardlink = self._evaluate()
        self.assertFalse(hardlink["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_artifact_not_unique", hardlink["failures"])

        wrong_name = self.actual_vendor_launch.with_name("resolved.launch")
        self.actual_vendor_launch.unlink()
        backing.unlink()
        shutil.copyfile(
            ROOT.joinpath(*Path(PREFLIGHT.DABAI_LAUNCH["path"]).parts),
            wrong_name)
        wrong = self._evaluate_actual(wrong_name, wrong_name)
        self.assertFalse(wrong["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_path_policy_mismatch", wrong["failures"])

    def test_actual_vendor_launch_symlink_and_parent_link_are_rejected(self):
        target = self.actual_vendor_launch.with_name("target.launch")
        shutil.copyfile(self.actual_vendor_launch, target)
        self.actual_vendor_launch.unlink()
        try:
            self.actual_vendor_launch.symlink_to(target.name)
        except (NotImplementedError, OSError):
            self.skipTest("platform does not permit an unprivileged symlink")
        linked = self._evaluate()
        self.assertFalse(linked["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_artifact_linklike_or_nonregular",
            linked["failures"])

        self.actual_vendor_launch.unlink()
        target.replace(self.actual_vendor_launch)
        linked_parent = self.temp_root / "linked_vendor"
        linked_parent.symlink_to(
            self.actual_vendor_launch.parent, target_is_directory=True)
        through_parent = linked_parent / "dabai_u3.launch"
        parent_link = self._evaluate_actual(through_parent, through_parent)
        self.assertFalse(parent_link["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_parent_chain_linklike",
            parent_link["failures"])

    def test_actual_vendor_launch_post_semantic_identity_drift_is_rejected(self):
        original_validator = PREFLIGHT._validate_dabai_launch_bytes
        calls = {"count": 0}

        def mutate_after_live_validation(raw):
            calls["count"] += 1
            failures = original_validator(raw)
            if calls["count"] == 2:
                self.actual_vendor_launch.write_bytes(raw + b"\n")
            return failures

        with mock.patch.object(
                PREFLIGHT, "_validate_dabai_launch_bytes",
                side_effect=mutate_after_live_validation):
            result = self._evaluate()
        self.assertEqual(calls["count"], 2)
        self.assertFalse(result["preflight_pass"])
        self.assertIn(
            "actual_vendor_launch_identity_changed_after_validation",
            result["failures"])
        self.assertTrue(any(
            item.startswith("actual_vendor_launch_postcheck_")
            for item in result["failures"]))
        self.assertFalse(
            result["launch_admission"]["actual_vendor_launch"]
            ["stable_across_semantic_validation"])
        self.assertFalse(result["delivery_ready"])

    def test_linklike_formal_launch_is_rejected_when_supported(self):
        python = _complete_environment(self.environment)
        path = self.workspace.joinpath(
            *Path(PREFLIGHT.FORMAL_CAPTURE_LAUNCH["path"]).parts)
        target = path.with_name("formal-target.launch")
        target.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(target.name)
        except (NotImplementedError, OSError):
            self.skipTest("platform does not permit an unprivileged symlink")
        with mock.patch.object(
                PREFLIGHT, "PRODUCTION_VENDOR_LAUNCH_PATH",
                str(self.actual_vendor_launch)):
            result = PREFLIGHT.evaluate_preflight(
                self.workspace, self.environment,
                actual_vendor_launch=self.actual_vendor_launch,
                python_executable=python, python_version=(3, 10, 12))
        self.assertFalse(result["static_launch_safety_pass"])
        self.assertFalse(result["preflight_pass"])
        self.assertTrue(any(
            item.startswith("formal_capture_launch_")
            for item in result["failures"]))

    def test_cli_emits_one_strict_json_marker_and_returns_blocked(self):
        command = [
            sys.executable,
            "-B",
            str(ROOT / "audit_tools" / "ros1_camera_only_field_preflight.py"),
            "--actual-vendor-launch",
            PREFLIGHT.PRODUCTION_VENDOR_LAUNCH_PATH,
        ]
        completed = subprocess.run(
            command, cwd=str(ROOT), check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(completed.returncode, 3, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 1, completed.stdout)
        self.assertTrue(lines[0].startswith(PREFLIGHT.MARKER))
        payload = json.loads(lines[0][len(PREFLIGHT.MARKER):])
        self.assertFalse(payload["preflight_pass"])
        self.assertFalse(payload["formal_consumer"])
        self.assertFalse(payload["delivery_ready"])
        self.assertEqual(completed.stderr, "")

    def test_cli_missing_or_relative_actual_vendor_launch_fails_closed(self):
        base = [
            sys.executable,
            "-B",
            str(ROOT / "audit_tools" / "ros1_camera_only_field_preflight.py"),
        ]
        missing = subprocess.run(
            base, cwd=str(ROOT), check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(missing.stdout, "")
        self.assertIn("--actual-vendor-launch", missing.stderr)

        relative = subprocess.run(
            base + ["--actual-vendor-launch", "dabai_u3.launch"],
            cwd=str(ROOT), check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(relative.returncode, 3, relative.stderr)
        lines = relative.stdout.splitlines()
        self.assertEqual(len(lines), 1, relative.stdout)
        payload = json.loads(lines[0][len(PREFLIGHT.MARKER):])
        self.assertIn(
            "actual_vendor_launch_path_not_absolute", payload["failures"])
        self.assertFalse(payload["preflight_pass"])
        self.assertFalse(payload["delivery_ready"])

    def test_runbook_uses_formal_launch_and_current_host_intake(self):
        value = RUNBOOK.read_text(encoding="utf-8")
        future_capture = value.split(
            "## 5. Future isolated aligned capture", 1)[1]
        for required in (
                "perception_v2_formal_capture.launch",
                'task_id:="$TASK_ID"',
                'capture_id:="$CAPTURE_ID"',
                "ros1_camera_only_field_preflight.py",
                "ros1_noetic_field_readiness.py",
                "host-owned ROS1/Noetic field-readiness intake",
                "implemented in `ros1_noetic_field_readiness.py`"):
            self.assertIn(required, value)
        for required in (
                "readonly ACTUAL_VENDOR_LAUNCH=/opt/limo/ros1_camera_runtime/"
                "share/astra_camera/launch/dabai_u3.launch",
                '--actual-vendor-launch "$ACTUAL_VENDOR_LAUNCH"',
                "ros1_camera_only_atomic_launcher.py",
                "--mode EXECUTE_AUDITED_CAMERA_ONLY",
                "/proc/self/fd/<sealed-fd>",
                "F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL",
                "ROS_PACKAGE_PATH",
                "archive is reference-only"):
            self.assertIn(required, future_capture)
        self.assertNotIn(
            "    roslaunch astra_camera dabai_u3.launch", future_capture)
        self.assertNotIn(
            '    roslaunch "$ACTUAL_VENDOR_LAUNCH"', future_capture)
        self.assertNotIn(
            "A future host-owned ROS1 consumer must bind", value)


if __name__ == "__main__":
    unittest.main()
