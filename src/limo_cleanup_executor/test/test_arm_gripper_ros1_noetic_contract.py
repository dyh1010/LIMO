"""Source-only audit for the ROS1/Noetic arm/gripper runtime baseline."""

import ast
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from limo_cleanup_executor.arm_gripper_field_acceptance import (
    BOUNDARY_MODES,
    EXPECTED_STAGE_DEFINITIONS,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parents[1]
EXECUTOR_SOURCE = PACKAGE_ROOT / "limo_cleanup_executor"
INTERFACES_ROOT = WORKSPACE_ROOT / "src" / "limo_cleanup_interfaces"
ROS1_OVERLAY = WORKSPACE_ROOT / "ros1_overlay_src"
MATRIX = PACKAGE_ROOT / "config" / "arm_gripper_field_acceptance_matrix.json"
CHECKLIST = WORKSPACE_ROOT / "docs" / "arm_gripper_ros1_noetic_dry_run_checklist.md"
MATRIX_DOC = WORKSPACE_ROOT / "docs" / "arm_gripper_field_acceptance_matrix.md"


class ArmGripperRos1NoeticContractTest(unittest.TestCase):
    """Keep ROS2 wrappers distinct from the missing Noetic integration."""

    def test_machine_stage_a1_is_noetic_and_fail_closed(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        stage = next(item for item in matrix["stages"] if item["id"] == "A1")
        expected = EXPECTED_STAGE_DEFINITIONS["A1"]

        self.assertEqual(stage["kind"], "OFFLINE_ROS1_NOETIC")
        self.assertEqual(stage["operation"], "ROS1_NOETIC_DRY_RUN")
        self.assertEqual(
            stage["current_disposition"],
            "BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER",
        )
        self.assertFalse(stage["execution_permitted_in_current_task"])
        self.assertEqual(stage["required_boundary_permissions"], ["ros_graph_allowed"])
        self.assertEqual(tuple(stage["required_evidence_keys"]), expected["required_evidence_keys"])
        self.assertNotIn("target_allowed", stage["required_boundary_permissions"])
        self.assertFalse(
            any("foxy" in key.lower() for key in stage["required_evidence_keys"])
        )

    def test_trusted_boundary_vocabulary_separates_noetic_fake_from_field(self):
        self.assertEqual(
            BOUNDARY_MODES,
            (
                "PERMANENT_LOCAL_ONLY",
                "ROS1_NOETIC_FAKE_ONLY",
                "FIELD_AUTHORIZED_POLICY",
            ),
        )
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        boundary = matrix["current_task_boundary"]
        self.assertEqual(boundary["mode"], "PERMANENT_LOCAL_ONLY")
        self.assertTrue(all(
            boundary[key] is False
            for key in boundary
            if key != "mode"
        ))

    def test_existing_packages_are_explicit_ros2_wrappers(self):
        executor_package = (PACKAGE_ROOT / "package.xml").read_text(encoding="utf-8")
        executor_setup = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
        interfaces_package = (INTERFACES_ROOT / "package.xml").read_text(
            encoding="utf-8"
        )
        interfaces_cmake = (INTERFACES_ROOT / "CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        arm_node = (EXECUTOR_SOURCE / "arm_gateway_node.py").read_text(
            encoding="utf-8"
        )
        gripper_node = (EXECUTOR_SOURCE / "gripper_gateway_node.py").read_text(
            encoding="utf-8"
        )
        arm_launch = (PACKAGE_ROOT / "launch" / "arm_gateway_dry_run.launch.py").read_text(
            encoding="utf-8"
        )
        arm_config = (PACKAGE_ROOT / "config" / "arm_gateway_dry_run.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("<build_type>ament_python</build_type>", executor_package)
        self.assertIn("<depend>rclpy</depend>", executor_package)
        self.assertIn("ament_index/resource_index/packages", executor_setup)
        self.assertIn("<buildtool_depend>ament_cmake</buildtool_depend>", interfaces_package)
        self.assertIn("rosidl_generate_interfaces", interfaces_cmake)
        self.assertIn("import rclpy", arm_node)
        self.assertIn("import rclpy", gripper_node)
        self.assertIn("from launch_ros.actions import Node", arm_launch)
        self.assertIn("ros__parameters", arm_config)

    def test_reusable_core_manifest_and_latch_modules_are_ros_independent(self):
        reusable = (
            "arm_gateway_core.py",
            "gripper_gateway_core.py",
            "gripper_core.py",
            "arm_motion_release_manifest.py",
            "final_gripper_release_manifest.py",
            "arm_safety_latch.py",
            "gripper_safety_latch.py",
            "arm_gripper_field_acceptance.py",
        )
        forbidden_roots = {"rclpy", "rospy", "actionlib", "roslib", "rosgraph"}
        for name in reusable:
            path = EXECUTOR_SOURCE / name
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path), feature_version=(3, 8))
            imported = set()
            for item in ast.walk(tree):
                if isinstance(item, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in item.names)
                elif isinstance(item, ast.ImportFrom) and item.module:
                    imported.add(item.module.split(".")[0])
            self.assertFalse(
                imported & forbidden_roots,
                "{} imports ROS runtime modules: {}".format(
                    name, sorted(imported & forbidden_roots)
                ),
            )

    def test_ros1_preview_exists_but_real_gateways_remain_missing(self):
        package_names = []
        for package_xml in sorted(ROS1_OVERLAY.rglob("package.xml")):
            root = ET.fromstring(package_xml.read_text(encoding="utf-8"))
            name = root.findtext("name")
            if name:
                package_names.append(name)
        self.assertTrue(package_names)
        self.assertIn("limo_cleanup_ros1_base", package_names)
        self.assertIn("limo_v1_navigation", package_names)
        self.assertIn("limo_cleanup_ros1_manipulation", package_names)
        self.assertFalse(
            any(
                token in name.lower()
                for name in package_names
                for token in ("arm_gateway", "gripper_gateway")
            )
        )
        preview = (
            ROS1_OVERLAY / "limo_cleanup_ros1_manipulation" / "scripts"
            / "fixed_bottle_pick_preview_node.py"
        ).read_text(encoding="utf-8")
        self.assertIn("import rospy", preview)
        self.assertIn("PREVIEW_REJECTED", preview)
        self.assertNotIn("SimpleActionClient", preview)
        self.assertNotIn("ServiceProxy", preview)

    def test_checklist_separates_regression_evidence_from_noetic_compatibility(self):
        source = CHECKLIST.read_text(encoding="utf-8")
        required = (
            "BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER",
            "ROS 2/Foxy",
            "pure-Python",
            "Catkin",
            "rospy",
            "actionlib",
            "唯一 owner",
            "physical-isolation-required",
            "result.json",
            "FAIL-before-build (status=2)",
            "不能把 ROS 2",
            "ROS1_NOETIC_FAKE_ONLY",
            "FIELD_AUTHORIZED_POLICY",
            "`SKIPPED` 永远不等于通过",
            "所有必需 source/build/test/callback/smoke/cleanup 项均为 `PASS`",
        )
        for token in required:
            self.assertIn(token, source)

    def test_default_ros1_owners_and_field_disposition_contract_are_explicit(self):
        checklist = CHECKLIST.read_text(encoding="utf-8")
        for exact_contract in (
                "| arm | `/cleanup_arm_gateway` | `/cleanup/arm/execute` |",
                "| gripper | `/cleanup_gripper_gateway` | `/cleanup/gripper/execute` |",
                "State publisher 必须为非 latched",
                "Actionlib 自动派生的 goal/cancel/status/feedback/result topics",
        ):
            self.assertIn(exact_contract, checklist)

        matrix_doc = MATRIX_DOC.read_text(encoding="utf-8")
        self.assertIn("ROS1_NOETIC_FAKE_ONLY", matrix_doc)
        self.assertIn("FIELD stages must never use `PASS_LOCAL`", matrix_doc)


if __name__ == "__main__":
    unittest.main()
