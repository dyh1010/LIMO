"""Pure-software tests for the task-scoped ROS2 document demotion gate."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from audit_tools import ros1_machine_contract_doc_demotion as GATE


ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = ROOT.parent
CONTRACT = ROOT / GATE.CONTRACT_RELATIVE_PATH
AUTHORITY = ROOT / GATE.AUTHORITY_V5_RELATIVE_PATH
FOXY_DOC = ROOT / GATE.EXPECTED_CONTRACT_DOCUMENTS[0]
HARDWARE_DOC = ROOT / GATE.HARDWARE_LEGACY_RELATIVE_PATH
HARDWARE_REDIRECT = ROOT / GATE.HARDWARE_REDIRECT_RELATIVE_PATH
HARDWARE_WRAPPER = ROOT / GATE.HARDWARE_WRAPPER_RELATIVE_PATH
HARDWARE_OPERATIONS_INDEX = (
    ROOT / GATE.HARDWARE_CURRENT_OPERATIONS_INDEX_RELATIVE_PATH
)
HARDWARE_RUNBOOK = ROOT / GATE.HARDWARE_AUTHORITY_RUNBOOK


def _strict_load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_utf8_exact(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _bannered_foxy_text() -> str:
    text = FOXY_DOC.read_text(encoding="utf-8")
    if text.startswith(GATE.EXACT_FOXY_PREFIX):
        return text
    if not text.startswith(GATE.HISTORICAL_FOXY_TITLE + "\n"):
        raise AssertionError("unexpected historical Foxy document title")
    return GATE.DEMOTION_BANNER + "\n\n" + text


class Ros1MachineContractDocDemotionTest(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.shared = Path(self.temporary.name)
        self.workspace = self.shared / "limo_cleanup_ws"
        self.workspace.mkdir()
        self._copy_baseline()

    def tearDown(self):
        self.temporary.cleanup()

    def _copy(self, source: Path, relative: str, root: Path | None = None):
        base = self.workspace if root is None else root
        target = base.joinpath(*Path(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    def _copy_baseline(self):
        self.contract_path = self._copy(CONTRACT, GATE.CONTRACT_RELATIVE_PATH)
        self.authority_path = self._copy(
            AUTHORITY, GATE.AUTHORITY_V5_RELATIVE_PATH
        )
        self.foxy_path = self.workspace.joinpath(
            *Path(GATE.EXPECTED_CONTRACT_DOCUMENTS[0]).parts
        )
        self.foxy_path.parent.mkdir(parents=True, exist_ok=True)
        _write_utf8_exact(self.foxy_path, _bannered_foxy_text())
        self.hardware_path = self._copy(
            HARDWARE_DOC, GATE.HARDWARE_LEGACY_RELATIVE_PATH
        )
        self.hardware_redirect_path = self._copy(
            HARDWARE_REDIRECT, GATE.HARDWARE_REDIRECT_RELATIVE_PATH
        )
        self.hardware_wrapper_path = self._copy(
            HARDWARE_WRAPPER, GATE.HARDWARE_WRAPPER_RELATIVE_PATH
        )
        self.hardware_operations_index_path = self._copy(
            HARDWARE_OPERATIONS_INDEX,
            GATE.HARDWARE_CURRENT_OPERATIONS_INDEX_RELATIVE_PATH,
        )
        self.hardware_runbook_path = self._copy(
            HARDWARE_RUNBOOK, GATE.HARDWARE_AUTHORITY_RUNBOOK
        )
        self.shared_paths = {}
        for relative, _, _ in GATE.SHARED_DOCUMENT_IDENTITIES:
            self.shared_paths[relative] = self._copy(
                SHARED_ROOT / relative, relative, self.shared
            )

    def _evaluate(self):
        return GATE.evaluate_machine_contract_docs(self.workspace)

    def test_current_workspace_passes_and_never_promotes_field_or_delivery(self):
        report = GATE.evaluate_machine_contract_docs(ROOT)
        self.assertTrue(report["validated_pass"], report["failures"])
        self.assertEqual(report["failures"], [])
        self.assertFalse(report["accepted_as_offline_release_selection_authority"])
        self.assertFalse(report["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(report["authorizes_field_delivery"])
        self.assertFalse(report["delivery_ready"])
        self.assertEqual(report["formal_four_scene_frame_denominator"], 0)
        self.assertTrue(report["hardware_legacy_document_demoted"])
        self.assertTrue(report["hardware_current_operational_route_valid"])
        self.assertEqual(
            report["hardware_current_operational_route"],
            [
                GATE.HARDWARE_CURRENT_OPERATIONS_INDEX_RELATIVE_PATH,
                GATE.HARDWARE_REDIRECT_RELATIVE_PATH,
                GATE.HARDWARE_AUTHORITY_RUNBOOK,
                GATE.HARDWARE_ATOMIC_LAUNCHER,
            ],
        )

    def test_recursive_contract_inventory_and_false_declarations_are_exact(self):
        report = self._evaluate()
        self.assertTrue(report["validated_pass"], report["failures"])
        self.assertEqual(
            report["contract_document_paths"],
            list(GATE.EXPECTED_CONTRACT_DOCUMENTS),
        )
        self.assertEqual(len(report["contract_document_records"]), 1)
        self.assertEqual(len(report["source_declaration_records"]), 2)
        self.assertTrue(
            all(
                item["value"] is False
                for item in report["source_declaration_records"]
            )
        )
        self.assertIs(report["source_declaration_is_install_evidence"], False)
        self.assertTrue(
            report[
                "predecessor_authority_v5_identity_and_internal_current_valid"
            ]
        )
        self.assertEqual(
            report["frozen_predecessor_authority_index_instance_id"],
            GATE.AUTHORITY_V5_INDEX_INSTANCE_ID,
        )

    def test_missing_banner_is_rejected(self):
        text = _bannered_foxy_text()
        _write_utf8_exact(
            self.foxy_path, text[len(GATE.DEMOTION_BANNER) + 2 :]
        )
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_demotion_banner_missing:"
            + GATE.EXPECTED_CONTRACT_DOCUMENTS[0],
            report["failures"],
        )

    def test_weakened_banner_is_rejected(self):
        text = _bannered_foxy_text().replace(
            "LEGACY_ROS2_OFFLINE_ONLY", "LEGACY_ROS2_REFERENCE_ONLY", 1
        )
        _write_utf8_exact(self.foxy_path, text)
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_demotion_banner_invalid:"
            + GATE.EXPECTED_CONTRACT_DOCUMENTS[0],
            report["failures"],
        )

    def test_install_field_and_delivery_promotions_are_rejected(self):
        cases = {
            "install": "CURRENT_INSTALL_PASS=true",
            "field": "CURRENT_FIELD_PASS=true",
            "delivery": "CURRENT_DELIVERY_PASS=true",
        }
        baseline = _bannered_foxy_text()
        for scope, promotion in cases.items():
            with self.subTest(scope=scope):
                changed = baseline.replace(
                    "\n\n" + GATE.HISTORICAL_FOXY_TITLE,
                    "\n> " + promotion + "\n\n" + GATE.HISTORICAL_FOXY_TITLE,
                    1,
                )
                _write_utf8_exact(self.foxy_path, changed)
                report = self._evaluate()
                self.assertFalse(report["validated_pass"])
                self.assertIn(
                    "ros1_doc_current_{}_promotion_forbidden:{}".format(
                        scope, GATE.EXPECTED_CONTRACT_DOCUMENTS[0]
                    ),
                    report["failures"],
                )

    def test_source_declaration_true_or_missing_is_rejected(self):
        baseline = _strict_load(CONTRACT)
        for mode in ("true", "missing"):
            with self.subTest(mode=mode):
                changed = copy.deepcopy(baseline)
                provenance = changed["python_runtime_dependency_lock"][
                    "version_provenance"
                ]
                if mode == "true":
                    provenance["source_declaration_is_install_evidence"] = True
                else:
                    del provenance["source_declaration_is_install_evidence"]
                _write_json(self.contract_path, changed)
                report = self._evaluate()
                self.assertFalse(report["validated_pass"])
                expected_fragment = (
                    "ros1_doc_gate_source_declaration_not_false:"
                    if mode == "true"
                    else "ros1_doc_gate_source_declaration_flag_missing:"
                )
                self.assertTrue(
                    any(
                        item.startswith(expected_fragment)
                        for item in report["failures"]
                    ),
                    report["failures"],
                )
        shutil.copyfile(CONTRACT, self.contract_path)

    def test_contract_document_path_escape_substitution_and_duplicate_fail(self):
        baseline = _strict_load(CONTRACT)
        cases = ("../escape.md", "/absolute.md", "docs\\escape.md")
        for value in cases:
            with self.subTest(value=value):
                changed = copy.deepcopy(baseline)
                changed["python_runtime_dependency_lock"]["version_provenance"][
                    "source_path"
                ] = value
                _write_json(self.contract_path, changed)
                report = self._evaluate()
                self.assertFalse(report["validated_pass"])
                self.assertIn(
                    "ros1_doc_gate_contract_document_set_mismatch",
                    report["failures"],
                )
        changed = copy.deepcopy(baseline)
        changed["extra_provenance"] = {
            "source_path": GATE.EXPECTED_CONTRACT_DOCUMENTS[0],
            "source_declaration_is_install_evidence": False,
        }
        _write_json(self.contract_path, changed)
        report = self._evaluate()
        self.assertIn(
            "ros1_doc_gate_contract_document_duplicate", report["failures"]
        )

    def test_document_symlink_is_rejected(self):
        target = self.foxy_path.with_name("foxy_real.md")
        self.foxy_path.replace(target)
        try:
            os.symlink(target.name, self.foxy_path)
        except (OSError, NotImplementedError) as error:
            self.skipTest("symlink unavailable: {}".format(error))
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_gate_artifact_linklike:contract_document:"
            + GATE.EXPECTED_CONTRACT_DOCUMENTS[0],
            report["failures"],
        )

    def test_strict_json_rejects_duplicate_nan_and_trailing_content(self):
        cases = (
            b'{"schema_version":1,"schema_version":1}',
            b'{"schema_version":NaN}',
            b'{} trailing',
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.contract_path.write_bytes(raw)
                report = self._evaluate()
                self.assertFalse(report["validated_pass"])
                self.assertIn(
                    "ros1_doc_gate_strict_json_invalid:machine_contract",
                    report["failures"],
                )

    def test_shared_real_machine_correction_missing_or_weakened_fails(self):
        path = self.shared_paths["REAL_MACHINE_ACCEPTANCE_2026-08-07.md"]
        baseline = path.read_text(encoding="utf-8")
        for changed in (
            baseline[len(GATE.REAL_MACHINE_CORRECTION_PREFIX) :],
            baseline.replace("ROS1 build/install", "ROS1 source only", 1),
        ):
            with self.subTest():
                _write_utf8_exact(path, changed)
                report = self._evaluate()
                self.assertFalse(report["validated_pass"])
                self.assertTrue(
                    any(
                        item.startswith(
                            "ros1_doc_shared_real_machine_correction_"
                        )
                        for item in report["failures"]
                    ),
                    report["failures"],
                )
        shutil.copyfile(
            SHARED_ROOT / "REAL_MACHINE_ACCEPTANCE_2026-08-07.md", path
        )

    def test_shared_team_coordination_read_first_correction_is_exact(self):
        path = self.shared_paths["TEAM_COORDINATION.md"]
        baseline = path.read_text(encoding="utf-8")
        for changed in (
            baseline.replace("\u5fc5\u987b\u5148\u8bfb\u6587\u4ef6\u9876\u90e8", "\u53ef\u9009\u9605\u8bfb", 1),
            baseline.replace("\u4e0d\u662f\u5f53\u524d field/delivery PASS", "\u53ef\u4f5c\u4e3a field PASS", 1),
        ):
            with self.subTest():
                _write_utf8_exact(path, changed)
                report = self._evaluate()
                self.assertFalse(report["validated_pass"])
                self.assertIn(
                    "ros1_doc_shared_team_coordination_correction_invalid",
                    report["failures"],
                )

    def test_frozen_hardware_document_identity_and_surfaces_are_exact(self):
        report = self._evaluate()
        self.assertTrue(report["validated_pass"], report["failures"])
        self.assertEqual(
            report["hardware_legacy_document_identity"],
            {
                "path": GATE.HARDWARE_LEGACY_RELATIVE_PATH,
                "size_bytes": GATE.HARDWARE_LEGACY_SIZE_BYTES,
                "sha256": GATE.HARDWARE_LEGACY_SHA256,
            },
        )
        legacy = report["hardware_legacy_document_report"]
        self.assertTrue(legacy["required_surfaces_present"])
        self.assertTrue(legacy["contains_direct_legacy_ros2_commands"])
        self.assertFalse(legacy["commands_are_currently_authoritative"])

    def test_frozen_hardware_document_drift_is_rejected_not_reinterpreted(self):
        baseline = self.hardware_path.read_bytes()
        self.hardware_path.write_bytes(baseline + b"\n")
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_hardware_legacy_identity_anchor_mismatch",
            report["failures"],
        )
        self.assertFalse(report["hardware_legacy_document_demoted"])

    def test_missing_or_weakened_hardware_redirect_is_rejected(self):
        baseline = self.hardware_redirect_path.read_text(encoding="utf-8")
        self.hardware_redirect_path.unlink()
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn("ros1_doc_hardware_redirect_missing", report["failures"])

        _write_utf8_exact(
            self.hardware_redirect_path,
            baseline.replace(
                "NON_AUTHORITATIVE_DO_NOT_RUN", "REFERENCE_ONLY"
            ),
        )
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_hardware_redirect_weakened", report["failures"]
        )
        self.assertIn(
            "ros1_doc_hardware_redirect_demotion_marker_invalid",
            report["failures"],
        )

    def test_hardware_redirect_rejects_copied_legacy_operational_commands(self):
        baseline = HARDWARE_REDIRECT.read_text(encoding="utf-8")
        cases = {
            "ros2_launch": "ros2 launch evil_pkg evil.launch",
            "ros2_graph": "ros2 topic list",
            "legacy_wrapper": (
                "scripts/run_hardware_readonly_acceptance.sh "
                "start_camera:=true"
            ),
            "ros2_environment": "source /opt/ros/humble/setup.bash",
            "camera_start": "start_camera:=true",
            "uart_or_fuser": "fuser /dev/ttyTHS0",
        }
        for label, command in cases.items():
            with self.subTest(label=label):
                result = GATE.validate_hardware_redirect_text(
                    baseline + "\n" + command + "\n"
                )
                self.assertIn(
                    "ros1_doc_hardware_redirect_direct_operation_forbidden:"
                    + label,
                    result["failures"],
                )

    def test_hardware_redirect_rejects_historical_pass_promotion(self):
        baseline = HARDWARE_REDIRECT.read_text(encoding="utf-8")
        for scope, statement in (
            ("install", "CURRENT_INSTALL_PASS=true"),
            ("field", "CURRENT_FIELD_PASS=true"),
            ("delivery", "CURRENT_DELIVERY_PASS=true"),
        ):
            with self.subTest(scope=scope):
                result = GATE.validate_hardware_redirect_text(
                    baseline + "\n" + statement + "\n"
                )
                self.assertIn(
                    "ros1_doc_hardware_redirect_current_{}_promotion_forbidden".format(
                        scope
                    ),
                    result["failures"],
                )

    def test_wrapper_default_block_and_exact_offline_guard_are_required(self):
        baseline = HARDWARE_WRAPPER.read_text(encoding="utf-8")
        result = GATE.validate_hardware_wrapper_text(baseline)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["default_fail_closed"])
        self.assertTrue(result["legacy_ros2_offline_only_guarded"])
        self.assertFalse(result["invokes_ros"])

        weakened = baseline.replace(
            '"${LEGACY_ROS2_OFFLINE_ONLY:-}" != \'1\'',
            '"${ALLOW_ANY_RUNTIME:-}" != \'1\'',
            1,
        )
        result = GATE.validate_hardware_wrapper_text(weakened)
        self.assertIn(
            "ros1_doc_hardware_wrapper_legacy_opt_in_guard_missing",
            result["failures"],
        )

    def test_wrapper_isolation_and_redirect_cannot_be_weakened(self):
        baseline = HARDWARE_WRAPPER.read_text(encoding="utf-8")
        cases = (
            (
                baseline.replace("ROS_LOCALHOST_ONLY", "ALLOW_GLOBAL", 1),
                "ros1_doc_hardware_wrapper_isolation_guard_missing",
            ),
            (
                baseline.replace("ROS_MASTER_URI", "IGNORED_MASTER", 1),
                "ros1_doc_hardware_wrapper_ambient_graph_guard_missing",
            ),
            (
                baseline.replace(
                    GATE.HARDWARE_REDIRECT_RELATIVE_PATH,
                    "docs/hardware_readiness.md",
                ),
                "ros1_doc_hardware_wrapper_redirect_route_invalid",
            ),
        )
        for changed, expected in cases:
            with self.subTest(expected=expected):
                result = GATE.validate_hardware_wrapper_text(changed)
                self.assertIn(expected, result["failures"])

    def test_wrapper_rejects_ros_camera_graph_uart_and_environment_execution(self):
        baseline = HARDWARE_WRAPPER.read_text(encoding="utf-8")
        cases = (
            "ros2 launch limo_cleanup_bringup real_perception_only.launch.py "
            "start_camera:=true",
            "ros2 topic echo /camera/color/image_raw",
            "ros2 node list",
            "fuser /dev/ttyTHS0",
            "source /opt/ros/humble/setup.bash",
            "roslaunch astra_camera dabai_u3.launch",
        )
        for command in cases:
            with self.subTest(command=command):
                result = GATE.validate_hardware_wrapper_text(
                    baseline + "\n" + command + "\n"
                )
                expected = (
                    "ros1_doc_hardware_wrapper_ros_environment_source_forbidden"
                    if command.startswith("source ")
                    else "ros1_doc_hardware_wrapper_active_ros_operation_forbidden"
                )
                self.assertIn(expected, result["failures"])

    def test_current_operations_index_binds_sidecar_runbook_atomic_order(self):
        report = self._evaluate()
        self.assertTrue(report["validated_pass"], report["failures"])
        index = report["hardware_current_operations_index_report"]
        self.assertEqual(index["failures"], [])
        self.assertTrue(index["identity_exact"])
        self.assertTrue(index["route_exact"])
        self.assertFalse(index["accepted_as_release_selection_authority"])
        self.assertFalse(index["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(index["authorizes_field_delivery"])
        self.assertFalse(index["delivery_ready"])
        self.assertEqual(
            report["hardware_authority_runbook_identity"],
            {
                "path": GATE.HARDWARE_AUTHORITY_RUNBOOK,
                "size_bytes": GATE.HARDWARE_AUTHORITY_RUNBOOK_SIZE_BYTES,
                "sha256": GATE.HARDWARE_AUTHORITY_RUNBOOK_SHA256,
            },
        )

    def test_missing_weakened_or_reordered_operations_index_is_rejected(self):
        baseline = self.hardware_operations_index_path.read_text(
            encoding="utf-8"
        )
        self.hardware_operations_index_path.unlink()
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_hardware_operations_index_missing", report["failures"]
        )

        weakened = baseline.replace("TASK_SCOPED_NON_FORMAL", "CURRENT_FORMAL")
        _write_utf8_exact(self.hardware_operations_index_path, weakened)
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_hardware_operations_index_weakened", report["failures"]
        )

        reordered = baseline.replace(
            GATE.HARDWARE_ATOMIC_LAUNCHER,
            GATE.HARDWARE_REDIRECT_RELATIVE_PATH,
            1,
        ).replace(
            GATE.HARDWARE_REDIRECT_RELATIVE_PATH,
            GATE.HARDWARE_ATOMIC_LAUNCHER,
            1,
        )
        result = GATE.validate_hardware_current_operations_index_text(reordered)
        self.assertIn(
            "ros1_doc_hardware_operations_index_route_invalid",
            result["failures"],
        )

    def test_frozen_ros1_runbook_drift_breaks_current_route(self):
        self.hardware_runbook_path.write_bytes(
            self.hardware_runbook_path.read_bytes() + b"\n"
        )
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_hardware_authority_runbook_anchor_mismatch",
            report["failures"],
        )
        self.assertIn(
            "ros1_doc_hardware_current_operational_route_invalid",
            report["failures"],
        )
        self.assertFalse(report["hardware_current_operational_route_valid"])

    def test_predecessor_v5_anchor_and_internal_current_are_required(self):
        value = _strict_load(AUTHORITY)
        current = next(item for item in value["entries"] if item["is_current"])
        duplicate = copy.deepcopy(current)
        duplicate["evidence_id"] = "duplicate-current"
        value["entries"].append(duplicate)
        _write_json(self.authority_path, value)
        report = self._evaluate()
        self.assertFalse(report["validated_pass"])
        self.assertIn(
            "ros1_doc_gate_authority_v5_anchor_mismatch", report["failures"]
        )
        self.assertIn(
            "ros1_doc_gate_authority_v5_current_count_invalid",
            report["failures"],
        )
        self.assertIsNone(
            report["frozen_predecessor_authority_index_instance_id"]
        )

    def test_cli_emits_one_strict_marker_and_nonzero_on_gate_failure(self):
        invalid = {
            "schema_version": GATE.SCHEMA_VERSION,
            "validated_pass": False,
            "failures": ["ros1_doc_demotion_banner_missing:x"],
            "accepted_as_offline_release_selection_authority": False,
            "accepted_by_formal_field_evidence_consumer": False,
            "delivery_ready": False,
        }
        output = io.StringIO()
        with mock.patch.object(
            GATE, "evaluate_machine_contract_docs", return_value=invalid
        ):
            with redirect_stdout(output):
                exit_code = GATE.main([])
        self.assertEqual(exit_code, 4)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(GATE.MARKER))
        payload = json.loads(lines[0][len(GATE.MARKER) :])
        self.assertFalse(payload["validated_pass"])


if __name__ == "__main__":
    unittest.main()
