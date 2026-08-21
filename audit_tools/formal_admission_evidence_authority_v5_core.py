"""Versioned validator for the v6 camera-runtime BLOCKED_OFFLINE authority.

This module is deliberately independent from every frozen v1-v4 resolver.  It
can authorize only selection of an immutable offline regression generation.  A
successful result never authorizes ROS, a camera, inference, field evidence,
motion, build/install, or delivery.

The production wrapper supplies the only index path/size/SHA-256 trust anchor.
This core reopens that index, its predecessor, report, canonical source child,
and every source role through regular-file descriptors.  Test denominators are
reconstructed from a fixed suite inventory and the live test AST; old totals
such as 187/335 are not accepted as authority.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "ros1_formal_admission_evidence_authority/v5"
CANONICAL_SCHEMA_VERSION = "ros1_blocked_offline_canonical_source/v2"
REPORT_SCHEMA_VERSION = "ros1_blocked_offline_regression_report/v2"
AUTHORITY_FAMILY_ID = "ros1-formal-admission-evidence-authority-20260815-v2"
INDEX_INSTANCE_ID = (
    "ros1-formal-admission-evidence-authority-index-20260815-"
    "v6-runtime-root-closure-blocked-offline"
)
GENERATION_ID = "ros1_camera_runtime_root_closure_blocked_offline_20260815_v6"
GENERATION_SCOPE = (
    "blocked_offline_camera_runtime_root_closure_not_runtime_field_or_delivery"
)
CURRENT_EVIDENCE_ID = (
    "ros1_camera_runtime_root_closure_blocked_offline_regression_20260815_v6"
)
CURRENT_STATUS = "CURRENT_BLOCKED_OFFLINE"
CANONICAL_ID = (
    "ros1-noetic-canonical-source-admission-20260815-"
    "v7-runtime-root-closure-blocked-offline"
)
CANONICAL_ARTIFACT_ID = (
    "ros1_noetic_canonical_source_admission_20260815_"
    "v7_runtime_root_closure_blocked_offline"
)
REPORT_ID = (
    "ros1-camera-runtime-root-closure-blocked-offline-report-20260815-v6"
)
SELECTION_AUTHORITY = (
    "EXTERNAL_FIXED_INDEX_PATH_SIZE_SHA256_STRICT_JSON_AND_HOST_RECOMPUTE"
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
INDEX_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_"
    "v6_runtime_root_closure_blocked_offline.json"
)
REPORT_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_camera_runtime_root_closure_"
    "blocked_offline_v6.json"
)
CANONICAL_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_noetic_canonical_source_admission_20260815_"
    "v7_runtime_root_closure_blocked_offline.json"
)

PREDECESSOR_INDEX_IDENTITY: Mapping[str, Any] = {
    "root_role": "workspace",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_"
        "v5_blocked_offline.json"
    ),
    "size_bytes": 15792,
    "sha256": "b5a6077db8b3da32962c4e22a6603114493be4d7bfbc2a3846666fe8fb6c7941",
    "authority_id": AUTHORITY_FAMILY_ID,
    "index_instance_id": (
        "ros1-formal-admission-evidence-authority-index-20260815-"
        "v5-blocked-offline"
    ),
    "generation_id": "ros1_camera_runtime_install_blocked_offline_20260815_v5",
    "current_evidence_id": (
        "ros1_camera_runtime_install_blocked_offline_regression_20260815_v5"
    ),
}
PREDECESSOR_REPORT_IDENTITY: Mapping[str, Any] = {
    "root_role": "workspace",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_camera_runtime_install_"
        "blocked_offline_v5.json"
    ),
    "size_bytes": 472722,
    "sha256": "0959458ea4be837db91d09356ada3ebb62ad0bc855a44f9ad4a641f9b0e866f0",
}
PREDECESSOR_CANONICAL_IDENTITY: Mapping[str, Any] = {
    "root_role": "workspace",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_noetic_canonical_source_admission_20260815_"
        "v6_blocked_offline.json"
    ),
    "size_bytes": 31881,
    "sha256": "cb15f20d27368ed7bd32ddd2d89a168431653b958da110b588f5562d948f3220",
}

LIVE_OVERLAY_ROOT = "ros1_overlay_src/limo_cleanup_ros1_perception"
REQUIRED_LIVE_OVERLAY_PATHS = (
    "config/dabai_ros1_formal_four_scene_six_topics_v1.json",
    "config/dabai_ros1_raw_rgbd_six_topics_v1.json",
    "launch/perception_v2_formal_capture.launch",
    "scripts/rosbag1_rgbd_indexer.py",
)

HOST_PERCEPTION_PACKAGE_ROOT = (
    "src/limo_cleanup_perception/limo_cleanup_perception"
)
HOST_PERCEPTION_PACKAGE_FILES: Tuple[str, ...] = (
    "__init__.py",
    "detection_gate.py",
    "diagnostic_evidence_lineage.py",
    "dual_model_detector.py",
    "evidence_binding.py",
    "image_conversion.py",
    "mock_perception.py",
    "offline_dual_detector.py",
    "orchestration_contract.py",
    "perception_core.py",
    "perception_evaluator.py",
    "perception_frame_collector.py",
    "perception_frame_io.py",
    "perception_readiness.py",
    "rgbd_bag_indexer.py",
    "rgbd_contract.py",
    "ros1_noetic_field_readiness.py",
    "ros1_source_core_admission.py",
    "stdlib_attestation.py",
    "target_contract.py",
    "task_actions.py",
    "typed_raw_binding.py",
)
HOST_PERCEPTION_CACHE_FILES: Tuple[str, ...] = (
    "__init__.cpython-312.pyc",
    "__init__.cpython-314.pyc",
    "evidence_binding.cpython-312.pyc",
    "evidence_binding.cpython-314.pyc",
    "perception_core.cpython-312.pyc",
    "perception_evaluator.cpython-312.pyc",
    "perception_evaluator.cpython-314.pyc",
    "perception_readiness.cpython-312.pyc",
    "perception_readiness.cpython-314.pyc",
    "rgbd_bag_indexer.cpython-312.pyc",
    "rgbd_bag_indexer.cpython-314.pyc",
    "ros1_source_core_admission.cpython-312.pyc",
    "stdlib_attestation.cpython-312.pyc",
    "stdlib_attestation.cpython-314.pyc",
    "target_contract.cpython-312.pyc",
    "target_contract.cpython-314.pyc",
    "typed_raw_binding.cpython-312.pyc",
    "typed_raw_binding.cpython-314.pyc",
)
ALLOWED_EMPTY_SOURCE_PATHS: Tuple[Tuple[str, str], ...] = ((
    "workspace", HOST_PERCEPTION_PACKAGE_ROOT + "/__init__.py",
),)

# The wrapper is the out-of-band trust root.  Including it in the canonical
# child would create a hash cycle when the final index anchor is frozen.
EXTERNAL_TRUST_ROOT_EXCLUSIONS = (
    "audit_tools/formal_admission_evidence_authority_v5.py",
)

# (role, root_role, path).  ``workspace_parent`` is intentionally explicit;
# no ``..`` path is accepted.  Evidence diagnostics are absent by design.
REQUIRED_SOURCE_ROLE_DEFINITIONS: Tuple[Tuple[str, str, str], ...] = (
    ("camera_runtime_import_probe", "workspace", "audit_tools/ros1_camera_runtime_import_probe.py"),
    ("camera_runtime_import_probe_test", "workspace", "audit_tools/test_ros1_camera_runtime_import_probe.py"),
    ("camera_runtime_install_admission", "workspace", "audit_tools/ros1_camera_runtime_install_admission.py"),
    ("camera_runtime_install_admission_test", "workspace", "audit_tools/test_ros1_camera_runtime_install_admission.py"),
    ("camera_only_atomic_launcher", "workspace", "audit_tools/ros1_camera_only_atomic_launcher.py"),
    ("camera_only_atomic_launcher_test", "workspace", "audit_tools/test_ros1_camera_only_atomic_launcher.py"),
    ("camera_only_field_preflight", "workspace", "audit_tools/ros1_camera_only_field_preflight.py"),
    ("camera_only_field_preflight_test", "workspace", "audit_tools/test_ros1_camera_only_field_preflight.py"),
    ("camera_only_operator_docs", "workspace", "audit_tools/ros1_camera_only_operator_docs.py"),
    ("camera_only_operator_docs_test", "workspace", "audit_tools/test_ros1_camera_only_operator_docs.py"),
    ("machine_contract_doc_demotion", "workspace", "audit_tools/ros1_machine_contract_doc_demotion.py"),
    ("machine_contract_doc_demotion_test", "workspace", "audit_tools/test_ros1_machine_contract_doc_demotion.py"),
    ("legacy_operational_scripts_gate", "workspace", "audit_tools/ros1_legacy_operational_scripts.py"),
    ("legacy_operational_scripts_test", "workspace", "audit_tools/test_ros1_legacy_operational_scripts.py"),
    ("runtime_source_contract_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_runtime_source_contract.py"),
    ("runtime_behavior_nested_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_runtime_behavior.py"),
    *tuple(
        (
            "host_perception_package_file_" + name.replace(".", "_"),
            "workspace",
            HOST_PERCEPTION_PACKAGE_ROOT + "/" + name,
        )
        for name in HOST_PERCEPTION_PACKAGE_FILES
    ),
    *tuple(
        (
            "host_perception_package_cache_" + name.replace(".", "_"),
            "workspace",
            HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/" + name,
        )
        for name in HOST_PERCEPTION_CACHE_FILES
    ),
    ("dabai_runtime_contract_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_dabai_runtime_contract.py"),
    ("dabai_runtime_contract_fixture", "workspace", "src/limo_cleanup_perception/fixtures/ros1_dabai_runtime_contract.json"),
    ("dabai_field_readiness_runbook", "workspace", "docs/PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md"),
    ("dabai_sensor_package_readme", "workspace", "src/limo_cleanup_dabai_sensor/README.md"),
    ("perception_release_policy", "workspace", "scripts/perception_release_policy.py"),
    ("perception_release_preflight", "workspace", "scripts/perception_release_preflight.py"),
    ("perception_release_rollback", "workspace", "scripts/rollback_perception_release.sh"),
    ("perception_release_artifacts_test", "workspace", "src/limo_cleanup_bringup/test/test_perception_release_artifacts.py"),
    ("unittest_isolated_runner", "workspace", "audit_tools/run_unittest_file_tests.py"),
    ("pytest_style_isolated_runner", "workspace", "audit_tools/run_pytest_style_tests.py"),
    ("successor_evidence_generator", "workspace", "audit_tools/generate_ros1_camera_runtime_root_closure_blocked_offline_evidence_v2.py"),
    ("successor_authority_core", "workspace", "audit_tools/formal_admission_evidence_authority_v5_core.py"),
    ("successor_authority_test", "workspace", "audit_tools/test_formal_admission_evidence_authority_v5.py"),
    ("predecessor_authority_resolver", "workspace", "audit_tools/formal_admission_evidence_authority_v4.py"),
    ("predecessor_authority_core", "workspace", "audit_tools/formal_admission_evidence_authority_v4_core.py"),
    ("current_operations_index", "workspace", "docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md"),
    ("hardware_readiness_redirect", "workspace", "docs/HARDWARE_READINESS_ROS1_NOETIC_REDIRECT.md"),
    ("frozen_hardware_readiness_document", "workspace", "docs/hardware_readiness.md"),
    ("frozen_ros1_field_runbook", "workspace", "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md"),
    ("real_camera_readonly_template", "workspace", "docs/REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md"),
    ("foxy_provenance_document", "workspace", "docs/foxy_arm64_deployment.md"),
    ("real_perception_document", "workspace", "docs/real_perception.md"),
    ("manual_reference_document", "workspace", "docs/limo_pro_manual_reference.md"),
    ("hardware_readonly_fail_closed_wrapper", "workspace", "scripts/run_hardware_readonly_acceptance.sh"),
    ("legacy_real_perception_startup_script", "workspace", "scripts/smoke_test_real_perception_startup.sh"),
    ("legacy_perception_mock_script", "workspace", "scripts/smoke_test_perception.sh"),
    ("legacy_foxy_audit_script", "workspace", "scripts/audit_foxy_runtime.sh"),
    ("legacy_mock_system_script", "workspace", "scripts/smoke_test_mock_system.sh"),
    ("retired_dabai_start_script", "workspace", "scripts/start_dabai_camera.sh"),
    ("archived_dabai_launch_reference", "workspace", "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch"),
    ("preflight_predecessor_authority_v4", "workspace", "evidence/perception_v2_offline_20260813/ros1_formal_admission_evidence_authority_index_20260815_v4.json"),
    ("preflight_frozen_canonical_v5", "workspace", "evidence/perception_v2_offline_20260813/ros1_noetic_canonical_source_admission_20260815_v5.json"),
    ("preflight_frozen_report_v4", "workspace", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_v4.json"),
    ("predecessor_authority_index", "workspace", PREDECESSOR_INDEX_IDENTITY["path"]),
    ("predecessor_regression_report", "workspace", PREDECESSOR_REPORT_IDENTITY["path"]),
    ("predecessor_canonical_source", "workspace", PREDECESSOR_CANONICAL_IDENTITY["path"]),
    ("shared_real_machine_correction", "workspace_parent", "REAL_MACHINE_ACCEPTANCE_2026-08-07.md"),
    ("shared_team_coordination", "workspace_parent", "TEAM_COORDINATION.md"),
)

FROZEN_REQUIRED_SOURCE_IDENTITIES: Mapping[Tuple[str, str], Mapping[str, Any]] = {
    ("workspace", PREDECESSOR_INDEX_IDENTITY["path"]): {
        key: PREDECESSOR_INDEX_IDENTITY[key]
        for key in ("root_role", "path", "size_bytes", "sha256")
    },
    ("workspace", PREDECESSOR_REPORT_IDENTITY["path"]): dict(PREDECESSOR_REPORT_IDENTITY),
    ("workspace", PREDECESSOR_CANONICAL_IDENTITY["path"]): dict(PREDECESSOR_CANONICAL_IDENTITY),
    ("workspace", "docs/hardware_readiness.md"): {
        "root_role": "workspace", "path": "docs/hardware_readiness.md",
        "size_bytes": 13274,
        "sha256": "6d48815b660c3f6b0c00fb36dc633d403b540e5a95f0bdedaddc37f33093fd9b",
    },
    ("workspace", "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md"): {
        "root_role": "workspace",
        "path": "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md",
        "size_bytes": 20895,
        "sha256": "eca9e93863e142c65c20f98a3ac38bda6c22dc19435f644e9d3720901e7a5ecd",
    },
    ("workspace", "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch"): {
        "root_role": "workspace",
        "path": "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch",
        "size_bytes": 6446,
        "sha256": "75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e",
    },
    ("workspace", "evidence/perception_v2_offline_20260813/ros1_formal_admission_evidence_authority_index_20260815_v4.json"): {
        "root_role": "workspace",
        "path": "evidence/perception_v2_offline_20260813/ros1_formal_admission_evidence_authority_index_20260815_v4.json",
        "size_bytes": 5015,
        "sha256": "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded",
    },
    ("workspace", "evidence/perception_v2_offline_20260813/ros1_noetic_canonical_source_admission_20260815_v5.json"): {
        "root_role": "workspace",
        "path": "evidence/perception_v2_offline_20260813/ros1_noetic_canonical_source_admission_20260815_v5.json",
        "size_bytes": 9889,
        "sha256": "1c4a9c2901cae292803cec4a700550c2054a26b94e1ae89aacbedb3865e7801a",
    },
    ("workspace", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_v4.json"): {
        "root_role": "workspace",
        "path": "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_v4.json",
        "size_bytes": 1288709,
        "sha256": "dfa7e3f8c53f6157fec5083b26b8fc87b3115dcfb9eb6fbbde2fbcf52775c5be",
    },
    ("workspace_parent", "REAL_MACHINE_ACCEPTANCE_2026-08-07.md"): {
        "root_role": "workspace_parent", "path": "REAL_MACHINE_ACCEPTANCE_2026-08-07.md",
        "size_bytes": 35176,
        "sha256": "6bd1931d53d1bf63accbc1e852801d560110594460437365b8e9819cd5dcb15d",
    },
    ("workspace_parent", "TEAM_COORDINATION.md"): {
        "root_role": "workspace_parent", "path": "TEAM_COORDINATION.md",
        "size_bytes": 37807,
        "sha256": "0edb875b407045f499cdd1315193fdd4785881bb1244f1a367500a0715077531",
    },
    ("workspace", "audit_tools/formal_admission_evidence_authority_v4.py"): {
        "root_role": "workspace",
        "path": "audit_tools/formal_admission_evidence_authority_v4.py",
        "size_bytes": 8038,
        "sha256": "ac2c5012e32fe8641864183dec3115db13a5d99ff2dd973c53081f3941a75e95",
    },
    ("workspace", "audit_tools/formal_admission_evidence_authority_v4_core.py"): {
        "root_role": "workspace",
        "path": "audit_tools/formal_admission_evidence_authority_v4_core.py",
        "size_bytes": 88889,
        "sha256": "b01fa18963084bf7696584d8cd7e31ce42e4be03e5122d2d08dad1d012a1d313",
    },
}

SUITE_DEFINITIONS: Tuple[Mapping[str, str], ...] = (
    {"suite_id": "camera_runtime_import_probe", "root_role": "workspace", "target": "audit_tools/test_ros1_camera_runtime_import_probe.py", "runner": "unittest"},
    {"suite_id": "camera_runtime_install_admission", "root_role": "workspace", "target": "audit_tools/test_ros1_camera_runtime_install_admission.py", "runner": "unittest"},
    {"suite_id": "camera_only_atomic_launcher", "root_role": "workspace", "target": "audit_tools/test_ros1_camera_only_atomic_launcher.py", "runner": "unittest"},
    {"suite_id": "camera_only_field_preflight", "root_role": "workspace", "target": "audit_tools/test_ros1_camera_only_field_preflight.py", "runner": "unittest"},
    {"suite_id": "camera_only_operator_docs", "root_role": "workspace", "target": "audit_tools/test_ros1_camera_only_operator_docs.py", "runner": "unittest"},
    {"suite_id": "machine_contract_doc_demotion", "root_role": "workspace", "target": "audit_tools/test_ros1_machine_contract_doc_demotion.py", "runner": "unittest"},
    {"suite_id": "runtime_source_contract", "root_role": "workspace", "target": "src/limo_cleanup_perception/test/test_ros1_runtime_source_contract.py", "runner": "pytest_style"},
    {"suite_id": "dabai_runtime_contract", "root_role": "workspace", "target": "src/limo_cleanup_perception/test/test_ros1_dabai_runtime_contract.py", "runner": "pytest_style"},
    {"suite_id": "legacy_operational_scripts", "root_role": "workspace", "target": "audit_tools/test_ros1_legacy_operational_scripts.py", "runner": "unittest"},
    {"suite_id": "perception_release_artifacts", "root_role": "workspace", "target": "src/limo_cleanup_bringup/test/test_perception_release_artifacts.py", "runner": "pytest_style"},
    {"suite_id": "successor_authority_validator", "root_role": "workspace", "target": "audit_tools/test_formal_admission_evidence_authority_v5.py", "runner": "unittest"},
)

DOC_DEMOTION_LINK_CASE_ID = (
    "audit_tools/test_ros1_machine_contract_doc_demotion.py::"
    "Ros1MachineContractDocDemotionTest.test_document_symlink_is_rejected"
)

# ``selection`` is either ALL or one exact test ID.  Counts are never stored
# here; they are derived from the test AST at plan/generation/validation time.
EXECUTION_DEFINITIONS: Tuple[Mapping[str, str], ...] = (
    {"record_id": "probe_wsl_python3", "suite_id": "camera_runtime_import_probe", "platform": "POSIX_WSL", "interpreter_role": "system_python3_entry", "selection": "ALL"},
    {"record_id": "probe_wsl_python314", "suite_id": "camera_runtime_import_probe", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "install_wsl_python3", "suite_id": "camera_runtime_install_admission", "platform": "POSIX_WSL", "interpreter_role": "system_python3_entry", "selection": "ALL"},
    {"record_id": "install_wsl_python314", "suite_id": "camera_runtime_install_admission", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "atomic_wsl_python3", "suite_id": "camera_only_atomic_launcher", "platform": "POSIX_WSL", "interpreter_role": "system_python3_entry", "selection": "ALL"},
    {"record_id": "atomic_wsl_python314", "suite_id": "camera_only_atomic_launcher", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "preflight_wsl_python314", "suite_id": "camera_only_field_preflight", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "operator_docs_wsl_python314", "suite_id": "camera_only_operator_docs", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "doc_demotion_windows_bundled", "suite_id": "machine_contract_doc_demotion", "platform": "WINDOWS_HOST", "interpreter_role": "bundled_host_python", "selection": "ALL"},
    {"record_id": "doc_demotion_link_posix_companion", "suite_id": "machine_contract_doc_demotion", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": DOC_DEMOTION_LINK_CASE_ID},
    {"record_id": "runtime_source_windows_bundled", "suite_id": "runtime_source_contract", "platform": "WINDOWS_HOST", "interpreter_role": "bundled_host_python", "selection": "ALL"},
    {"record_id": "dabai_runtime_wsl_python314", "suite_id": "dabai_runtime_contract", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "legacy_scripts_wsl_python314", "suite_id": "legacy_operational_scripts", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "legacy_scripts_wsl_python3", "suite_id": "legacy_operational_scripts", "platform": "POSIX_WSL", "interpreter_role": "system_python3_entry", "selection": "ALL"},
    {"record_id": "perception_release_wsl_python314", "suite_id": "perception_release_artifacts", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
    {"record_id": "successor_authority_wsl_python314", "suite_id": "successor_authority_validator", "platform": "POSIX_WSL", "interpreter_role": "system_python314_target", "selection": "ALL"},
)

UNITTEST_RUNNER = "audit_tools/run_unittest_file_tests.py"
PYTEST_RUNNER = "audit_tools/run_pytest_style_tests.py"
UNITTEST_MARKER = "OFFLINE_UNITTEST_FILE_RESULT "
PYTEST_MARKER = "OFFLINE_PYTEST_FILE_RESULT "
CHILD_ENVIRONMENT: Mapping[str, str] = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}

ATOMIC_SUPPORTING_TEST_ID = (
    "audit_tools/test_ros1_camera_only_atomic_launcher.py::"
    "Ros1CameraOnlyAtomicLauncherTest."
    "test_production_cli_is_blocked_until_runtime_admission_is_bound"
)

PRODUCTION_CLI_EXPECTATIONS: Tuple[Mapping[str, Any], ...] = (
    {"observation_id": "runtime_import_probe_unbound", "source_path": "audit_tools/ros1_camera_runtime_import_probe.py", "exit_code": 1, "marker_count": 1, "blocked_code": "production_runtime_import_probe_not_anchored", "execution_attempted": True, "supporting_test_id": None},
    {"observation_id": "runtime_install_authority_unbound", "source_path": "audit_tools/ros1_camera_runtime_install_admission.py", "exit_code": 4, "marker_count": 1, "blocked_code": "camera_runtime_install_authority_anchor_unavailable", "execution_attempted": True, "supporting_test_id": None},
    {"observation_id": "atomic_runtime_admission_unbound", "source_path": "audit_tools/ros1_camera_only_atomic_launcher.py", "exit_code": 4, "marker_count": 0, "blocked_code": "camera_runtime_install_admission_not_bound", "execution_attempted": False, "supporting_test_id": ATOMIC_SUPPORTING_TEST_ID},
)

BLOCKERS: Tuple[str, ...] = (
    "BLOCKED_OFFLINE_RELEASE_SELECTION_ONLY",
    "CAMERA_RUNTIME_IMPORT_PRODUCTION_SPEC_NOT_BOUND",
    "CAMERA_RUNTIME_INSTALL_AUTHORITY_NOT_BOUND",
    "CAMERA_RUNTIME_INSTALL_ADMISSION_NOT_BOUND",
    "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
    "FORMAL_TF_NOT_VALIDATED",
    "FORMAL_3D_NOT_VALIDATED",
    "FORMAL_LATENCY_NOT_VALIDATED",
    "ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED",
    "ROS1_NOETIC_RUNTIME_NOT_VERIFIED",
)

PRODUCTION_AUTHORITY_STATE: Mapping[str, Any] = {
    "state": "UNBOUND_FAIL_CLOSED",
    "camera_runtime_import_probe_production_spec_bound": False,
    "camera_runtime_install_admission_authority_bound": False,
    "atomic_launcher_runtime_admission_bound": False,
    "self_reported_anchor_accepted": False,
    "production_cli_expected_nonzero": True,
    "required_blocked_codes": [
        item["blocked_code"] for item in PRODUCTION_CLI_EXPECTATIONS
    ],
}

GATE_STATE: Mapping[str, Any] = {
    "active_blockers": list(BLOCKERS),
    "offline_logical_matrix_passed": True,
    "offline_physical_matrix_passed_with_exact_platform_composite": True,
    "regression_passed": False,
    "ros1_source_implementation_complete": True,
    "ros1_noetic_runtime_verified": False,
    "ros1_noetic_build_install_verified": False,
    "ros1_noetic_field_install_pass": False,
    "formal_acceptance": False,
    "formal_denominator": 0,
    "formal_four_scene_frame_denominator": 0,
    "formal_tf_pass": False,
    "formal_3d_pass": False,
    "formal_latency_pass": False,
    "accepted_by_formal_field_evidence_consumer": False,
    "delivery_ready": False,
    "authorizes_field_delivery": False,
}


@dataclass(frozen=True)
class AuthorityPolicy:
    index_relative_path: str = INDEX_RELATIVE_PATH
    report_relative_path: str = REPORT_RELATIVE_PATH
    canonical_relative_path: str = CANONICAL_RELATIVE_PATH
    source_role_definitions: Tuple[Tuple[str, str, str], ...] = REQUIRED_SOURCE_ROLE_DEFINITIONS
    suite_definitions: Tuple[Mapping[str, str], ...] = SUITE_DEFINITIONS
    execution_definitions: Tuple[Mapping[str, str], ...] = EXECUTION_DEFINITIONS
    predecessor_index_identity: Mapping[str, Any] = field(default_factory=lambda: dict(PREDECESSOR_INDEX_IDENTITY))
    predecessor_report_identity: Mapping[str, Any] = field(default_factory=lambda: dict(PREDECESSOR_REPORT_IDENTITY))
    predecessor_canonical_identity: Mapping[str, Any] = field(default_factory=lambda: dict(PREDECESSOR_CANONICAL_IDENTITY))
    frozen_source_identities: Mapping[Tuple[str, str], Mapping[str, Any]] = field(default_factory=lambda: dict(FROZEN_REQUIRED_SOURCE_IDENTITIES))
    live_overlay_root: str = LIVE_OVERLAY_ROOT
    required_live_overlay_paths: Tuple[str, ...] = REQUIRED_LIVE_OVERLAY_PATHS
    host_perception_package_root: Optional[str] = HOST_PERCEPTION_PACKAGE_ROOT
    host_perception_package_files: Tuple[str, ...] = HOST_PERCEPTION_PACKAGE_FILES
    host_perception_cache_files: Tuple[str, ...] = HOST_PERCEPTION_CACHE_FILES
    allowed_empty_source_paths: Tuple[Tuple[str, str], ...] = ALLOWED_EMPTY_SOURCE_PATHS


PRODUCTION_POLICY = AuthorityPolicy()


def _same(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return set(actual) == set(expected) and all(
            _same(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            _same(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _strict_pairs(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant: " + value)


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
        parse_constant=_reject_constant,
    )


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    candidate = PurePosixPath(value)
    return (
        not candidate.is_absolute()
        and all(part not in ("", ".", "..") for part in candidate.parts)
        and candidate.as_posix() == value
    )


def _is_linklike(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _root_for_role(workspace: Path, root_role: str) -> Path:
    root = Path(workspace).resolve(strict=True)
    if root_role == "workspace":
        selected = root
    elif root_role == "workspace_parent":
        selected = root.parent
    else:
        raise ValueError("unknown root role")
    info = os.lstat(str(selected))
    if _is_linklike(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("source root is linklike or not a directory")
    return selected


def _read_regular_identity(
    workspace: Path, root_role: str, relative: str,
) -> Tuple[Dict[str, Any], bytes]:
    if not _safe_relative(relative):
        raise ValueError("unsafe relative path")
    root = _root_for_role(workspace, root_role)
    path = root
    for part in PurePosixPath(relative).parts:
        path = path / part
        info = os.lstat(str(path))
        if _is_linklike(info):
            raise ValueError("linklike path component")
    before = os.lstat(str(path))
    if (
        _is_linklike(before) or not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
    ):
        raise ValueError("artifact is not an exclusive regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or getattr(opened, "st_nlink", 1) != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("opened artifact identity mismatch")
        chunks: List[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    after = os.lstat(str(path))
    if (
        _is_linklike(after) or not stat.S_ISREG(after.st_mode)
        or getattr(after, "st_nlink", 1) != 1
        or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        or len(raw) != opened.st_size
    ):
        raise ValueError("artifact drift while reading")
    return {
        "root_role": root_role,
        "path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, raw


def source_artifact_identity(
    workspace: Path, root_role: str, relative: str,
) -> Dict[str, Any]:
    identity, unused = _read_regular_identity(workspace, root_role, relative)
    return identity


def artifact_identity(workspace: Path, relative: str) -> Dict[str, Any]:
    value = source_artifact_identity(workspace, "workspace", relative)
    return {key: value[key] for key in ("path", "size_bytes", "sha256")}


def _identity_failures(
    value: Any, prefix: str, with_root: bool = False,
    allow_empty: bool = False,
) -> List[str]:
    keys = {"path", "size_bytes", "sha256"}
    if with_root:
        keys.add("root_role")
    if not isinstance(value, dict) or set(value) != keys:
        return [prefix + "_identity_invalid"]
    failures: List[str] = []
    if with_root and value.get("root_role") not in ("workspace", "workspace_parent"):
        failures.append(prefix + "_root_role_invalid")
    if not _safe_relative(value.get("path")):
        failures.append(prefix + "_path_invalid")
    if (
        type(value.get("size_bytes")) is not int
        or value["size_bytes"] < 0
        or (value["size_bytes"] == 0 and not allow_empty)
    ):
        failures.append(prefix + "_size_invalid")
    if not _valid_sha256(value.get("sha256")):
        failures.append(prefix + "_sha256_invalid")
    return failures


def _policy_failures(policy: Any) -> List[str]:
    if not isinstance(policy, AuthorityPolicy):
        return ["formal_authority_v5_policy_invalid"]
    failures: List[str] = []
    for label, path in (
        ("index", policy.index_relative_path),
        ("report", policy.report_relative_path),
        ("canonical", policy.canonical_relative_path),
    ):
        if not _safe_relative(path):
            failures.append("formal_authority_v5_policy_path_invalid:" + label)
    roles = policy.source_role_definitions
    if not roles or any(
        not isinstance(item, tuple) or len(item) != 3
        or not isinstance(item[0], str) or not item[0]
        or item[1] not in ("workspace", "workspace_parent")
        or not _safe_relative(item[2])
        for item in roles
    ):
        failures.append("formal_authority_v5_policy_source_roles_invalid")
    elif (
        len({item[0] for item in roles}) != len(roles)
        or len({(item[1], item[2]) for item in roles}) != len(roles)
    ):
        failures.append("formal_authority_v5_policy_source_roles_duplicate")
    if all(isinstance(item, tuple) and len(item) == 3 for item in roles) and any(
        path.lower().startswith("evidence/")
        and "diagnostic" in path.lower()
        for unused, unused_root, path in roles
    ):
        failures.append("formal_authority_v5_policy_nonformal_diagnostic_forbidden")
    if policy.host_perception_package_root is None:
        if (
            policy.host_perception_package_files
            or policy.host_perception_cache_files
        ):
            failures.append(
                "formal_authority_v5_policy_host_package_inventory_invalid"
            )
    elif (
        not _safe_relative(policy.host_perception_package_root)
        or not isinstance(policy.host_perception_package_files, tuple)
        or not policy.host_perception_package_files
        or tuple(sorted(set(policy.host_perception_package_files)))
        != policy.host_perception_package_files
        or any(
            not isinstance(name, str)
            or not name.endswith(".py")
            or "/" in name or "\\" in name
            for name in policy.host_perception_package_files
        )
    ):
        failures.append(
            "formal_authority_v5_policy_host_package_inventory_invalid"
        )
    elif {
        ("workspace", policy.host_perception_package_root + "/" + name)
        for name in policy.host_perception_package_files
    } - {(root_role, path) for unused, root_role, path in roles}:
        failures.append(
            "formal_authority_v5_policy_host_package_source_roles_incomplete"
        )
    elif (
        not isinstance(policy.host_perception_cache_files, tuple)
        or tuple(sorted(set(policy.host_perception_cache_files)))
        != policy.host_perception_cache_files
        or any(
            not isinstance(name, str)
            or not name.endswith(".pyc")
            or "/" in name or "\\" in name
            for name in policy.host_perception_cache_files
        )
    ):
        failures.append(
            "formal_authority_v5_policy_host_package_cache_inventory_invalid"
        )
    elif {
        (
            "workspace",
            policy.host_perception_package_root + "/__pycache__/" + name,
        )
        for name in policy.host_perception_cache_files
    } - {(root_role, path) for unused, root_role, path in roles}:
        failures.append(
            "formal_authority_v5_policy_host_package_cache_roles_incomplete"
        )
    if (
        not isinstance(policy.allowed_empty_source_paths, tuple)
        or len(set(policy.allowed_empty_source_paths))
        != len(policy.allowed_empty_source_paths)
        or any(
            not isinstance(item, tuple) or len(item) != 2
            or item[0] not in ("workspace", "workspace_parent")
            or not _safe_relative(item[1])
            for item in policy.allowed_empty_source_paths
        )
        or set(policy.allowed_empty_source_paths)
        - {(root_role, path) for unused, root_role, path in roles}
    ):
        failures.append(
            "formal_authority_v5_policy_allowed_empty_sources_invalid"
        )
    suite_ids = [item.get("suite_id") for item in policy.suite_definitions]
    if not suite_ids or len(suite_ids) != len(set(suite_ids)):
        failures.append("formal_authority_v5_policy_suite_inventory_invalid")
    execution_ids = [item.get("record_id") for item in policy.execution_definitions]
    if not execution_ids or len(execution_ids) != len(set(execution_ids)):
        failures.append("formal_authority_v5_policy_execution_inventory_invalid")
    return failures


def collect_source_role_bindings(
    workspace: Path, policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> List[Dict[str, Any]]:
    failures = _policy_failures(policy)
    if failures:
        raise ValueError(",".join(failures))
    records: List[Dict[str, Any]] = []
    for role, root_role, relative in policy.source_role_definitions:
        identity = source_artifact_identity(workspace, root_role, relative)
        records.append({"role": role, **identity})
    records.sort(key=lambda item: (item["root_role"], item["path"]))
    return records


def _source_role_set_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    return _canonical_sha256(list(records))


def _host_perception_tree_snapshot(package: Path) -> Dict[str, Any]:
    package_info = os.lstat(str(package))
    if _is_linklike(package_info) or not stat.S_ISDIR(package_info.st_mode):
        raise ValueError("host perception package root invalid")
    observed: List[str] = []
    cache_path: Optional[Path] = None
    with os.scandir(str(package)) as stream:
        for entry in stream:
            info = entry.stat(follow_symlinks=False)
            if _is_linklike(info):
                raise ValueError("host perception package entry linklike")
            if entry.name == "__pycache__":
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("host perception cache entry invalid")
                cache_path = Path(entry.path)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("host perception package extra non-file entry")
            observed.append(entry.name)
    observed.sort()
    observed_cache: List[str] = []
    cache_identity: Optional[Tuple[int, int, int, int, int]] = None
    if cache_path is not None:
        cache_info = os.lstat(str(cache_path))
        if _is_linklike(cache_info) or not stat.S_ISDIR(cache_info.st_mode):
            raise ValueError("host perception cache root invalid")
        cache_identity = (
            cache_info.st_dev, cache_info.st_ino, cache_info.st_size,
            cache_info.st_mtime_ns, getattr(cache_info, "st_nlink", 1),
        )
        with os.scandir(str(cache_path)) as stream:
            for entry in stream:
                info = entry.stat(follow_symlinks=False)
                if _is_linklike(info):
                    raise ValueError("host perception cache entry linklike")
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("host perception cache extra non-file entry")
                observed_cache.append(entry.name)
    observed_cache.sort()
    return {
        "package_identity": (
            package_info.st_dev, package_info.st_ino, package_info.st_size,
            package_info.st_mtime_ns, getattr(package_info, "st_nlink", 1),
        ),
        "package_files": tuple(observed),
        "cache_identity": cache_identity,
        "cache_files": tuple(observed_cache),
    }


def collect_host_perception_package_tree(
    workspace: Path, policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    package_root = policy.host_perception_package_root
    expected_files = policy.host_perception_package_files
    expected_cache_files = policy.host_perception_cache_files
    if package_root is None:
        if expected_files or expected_cache_files:
            raise ValueError("disabled host package inventory has files")
        return {
            "binding_kind": "disabled_for_test_policy",
            "package_root": None,
            "file_count": 0,
            "source_set_sha256": _canonical_sha256([]),
            "entries": [],
        }
    root = _root_for_role(workspace, "workspace")
    package = root
    for part in PurePosixPath(package_root).parts:
        package = package / part
        info = os.lstat(str(package))
        if _is_linklike(info):
            raise ValueError("host perception package path linklike")
    before_snapshot = _host_perception_tree_snapshot(package)
    if before_snapshot["package_files"] != expected_files:
        raise ValueError("host perception package exact file set mismatch")
    if before_snapshot["cache_files"] != expected_cache_files:
        raise ValueError("host perception cache exact file set mismatch")
    entries: List[Dict[str, Any]] = []
    for name in expected_files:
        identity = source_artifact_identity(
            workspace, "workspace", package_root + "/" + name,
        )
        entries.append({
            "path": name,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        })
    for name in expected_cache_files:
        identity = source_artifact_identity(
            workspace, "workspace",
            package_root + "/__pycache__/" + name,
        )
        entries.append({
            "path": "__pycache__/" + name,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        })
    middle_snapshot = _host_perception_tree_snapshot(package)
    if middle_snapshot != before_snapshot:
        raise ValueError("host perception package tree drift while binding")
    if (
        middle_snapshot["package_files"] != expected_files
        or middle_snapshot["cache_files"] != expected_cache_files
    ):
        raise ValueError("host perception package final exact set mismatch")
    entries.sort(key=lambda item: item["path"])
    final_entries: List[Dict[str, Any]] = []
    for name in expected_files:
        identity = source_artifact_identity(
            workspace, "workspace", package_root + "/" + name,
        )
        final_entries.append({
            "path": name,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        })
    for name in expected_cache_files:
        identity = source_artifact_identity(
            workspace, "workspace",
            package_root + "/__pycache__/" + name,
        )
        final_entries.append({
            "path": "__pycache__/" + name,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        })
    final_entries.sort(key=lambda item: item["path"])
    after_snapshot = _host_perception_tree_snapshot(package)
    if after_snapshot != middle_snapshot or final_entries != entries:
        raise ValueError("host perception package file identity drift")
    payload = {
        "binding_kind": "host_perception_package_exact_source_tree",
        "package_root": package_root,
        "file_count": len(entries),
        "source_set_sha256": _canonical_sha256(entries),
        "entries": entries,
    }
    return payload


def _collect_overlay_entries(workspace: Path, overlay_root: str) -> List[Dict[str, Any]]:
    root = _root_for_role(workspace, "workspace")
    package = root.joinpath(*PurePosixPath(overlay_root).parts)
    if _is_linklike(os.lstat(str(package))):
        raise ValueError("overlay root linklike")
    entries: List[Dict[str, Any]] = []
    for path in package.rglob("*"):
        relative = path.relative_to(package).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_dir():
            if _is_linklike(os.lstat(str(path))):
                raise ValueError("overlay directory linklike")
            continue
        if relative == "config/source_core_binding.json":
            continue
        identity = source_artifact_identity(
            workspace, "workspace", overlay_root + "/" + relative,
        )
        entries.append({
            "path": relative,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        })
    entries.sort(key=lambda item: item["path"])
    if not entries:
        raise ValueError("zero overlay files")
    return entries


def collect_live_overlay_binding(
    workspace: Path, policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    entries = _collect_overlay_entries(workspace, policy.live_overlay_root)
    seen = {item["path"] for item in entries}
    if not set(policy.required_live_overlay_paths).issubset(seen):
        raise ValueError("required overlay path missing")
    payload: Dict[str, Any] = {
        "schema_version": 2,
        "binding_kind": "canonical_project_overlay_exact_tree",
        "test_only": False,
        "canonical_source_root": policy.live_overlay_root,
        "file_count": len(entries),
        "source_set_sha256": _canonical_sha256(entries),
        "entries": entries,
        "source_contract_pass": True,
        "indexer_only_detected": False,
        "architecture_blockers": [],
    }
    payload["binding_sha256"] = _canonical_sha256(payload)
    return payload


def _decorator_parametrize_count(decorator: ast.AST) -> Optional[int]:
    if not isinstance(decorator, ast.Call):
        return None
    function = decorator.func
    if (
        not isinstance(function, ast.Attribute)
        or function.attr != "parametrize" or len(decorator.args) < 2
    ):
        return None
    values = decorator.args[1]
    if not isinstance(values, (ast.List, ast.Tuple)):
        raise ValueError("pytest parametrize values not static")
    return len(values.elts)


def static_test_ids(
    workspace: Path, root_role: str, relative: str, runner: str,
) -> List[str]:
    unused_identity, raw = _read_regular_identity(workspace, root_role, relative)
    tree = ast.parse(raw.decode("utf-8"), filename=relative, feature_version=8)
    result: List[str] = []
    if runner == "unittest":
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    result.append(relative + "::" + node.name + "." + child.name)
    elif runner == "pytest_style":
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            counts = [
                count for count in (
                    _decorator_parametrize_count(item) for item in node.decorator_list
                ) if count is not None
            ]
            if len(counts) > 1 or (counts and counts[0] <= 0):
                raise ValueError("unsupported pytest parametrization")
            base = relative + "::" + node.name
            if counts:
                result.extend(base + "[{}]".format(index) for index in range(counts[0]))
            else:
                result.append(base)
    else:
        raise ValueError("unknown suite runner")
    result.sort()
    if not result or len(result) != len(set(result)):
        raise ValueError("zero or duplicate static test IDs")
    return result


def suite_inventory(
    workspace: Path, policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for definition in policy.suite_definitions:
        ids = static_test_ids(
            workspace, definition["root_role"], definition["target"],
            definition["runner"],
        )
        records.append({
            "suite_id": definition["suite_id"],
            "root_role": definition["root_role"],
            "target": definition["target"],
            "runner": definition["runner"],
            "expected_test_ids": ids,
            "logical_count": len(ids),
        })
    records.sort(key=lambda item: item["suite_id"])
    if len({test_id for item in records for test_id in item["expected_test_ids"]}) != sum(item["logical_count"] for item in records):
        raise ValueError("cross-suite duplicate test ID")
    return records


def _identity_from_source(
    source_by_key: Mapping[Tuple[str, str], Mapping[str, Any]],
    root_role: str, path: str,
) -> Dict[str, Any]:
    item = source_by_key[(root_role, path)]
    return {
        key: item[key]
        for key in ("root_role", "path", "size_bytes", "sha256")
    }


def expected_logical_suite_records(
    workspace: Path, source_roles: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> List[Dict[str, Any]]:
    by_key = {(item["root_role"], item["path"]): item for item in source_roles}
    records: List[Dict[str, Any]] = []
    for suite in suite_inventory(workspace, policy):
        runner_path = UNITTEST_RUNNER if suite["runner"] == "unittest" else PYTEST_RUNNER
        count = suite["logical_count"]
        records.append({
            "suite_id": suite["suite_id"],
            "test_artifact_identity": _identity_from_source(by_key, suite["root_role"], suite["target"]),
            "runner_artifact_identity": _identity_from_source(by_key, "workspace", runner_path),
            "expected_test_ids": suite["expected_test_ids"],
            "executed_test_ids": suite["expected_test_ids"],
            "expected": count,
            "collected": count,
            "passed": count,
            "failed": 0,
            "skipped": 0,
        })
    records.sort(key=lambda item: item["suite_id"])
    return records


def _execution_selection(
    definition: Mapping[str, str], suites: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    ids = list(suites[definition["suite_id"]]["expected_test_ids"])
    selection = definition["selection"]
    if selection == "ALL":
        return ids
    if selection not in ids:
        raise ValueError("execution selection not in suite")
    return [selection]


def _stream_identity_valid(value: Any) -> bool:
    return (
        isinstance(value, dict) and set(value) == {"size_bytes", "sha256"}
        and type(value["size_bytes"]) is int and value["size_bytes"] >= 0
        and _valid_sha256(value["sha256"])
    )


def _execution_workspace_path(workspace: Path) -> str:
    root = Path(workspace).resolve(strict=True)
    if os.name != "nt":
        return str(root)
    drive, tail = os.path.splitdrive(str(root))
    if len(drive) != 2 or drive[1] != ":":
        raise ValueError("workspace is not WSL mappable")
    parts = [item for item in tail.replace("\\", "/").split("/") if item]
    return str(PurePosixPath("/mnt", drive[0].lower(), *parts))


def _interpreter_identity_failures(
    value: Any, role: str, prefix: str,
) -> List[str]:
    required = {
        "entry_path", "entry_is_symlink", "entry_lstat_size_bytes",
        "entry_link_chain", "resolved_target", "isolated", "no_bytecode",
        "version",
    }
    if not isinstance(value, dict) or set(value) != required:
        return [prefix + "_schema_invalid"]
    failures: List[str] = []
    target = value.get("resolved_target")
    if (
        not isinstance(target, dict)
        or set(target) != {
            "path", "size_bytes", "sha256", "regular_file", "is_symlink",
        }
        or type(target.get("size_bytes")) is not int
        or target["size_bytes"] <= 0 or not _valid_sha256(target.get("sha256"))
        or target.get("regular_file") is not True
        or target.get("is_symlink") is not False
    ):
        failures.append(prefix + "_target_invalid")
        target = {}
    if value.get("isolated") is not True or value.get("no_bytecode") is not True:
        failures.append(prefix + "_flags_invalid")
    version = value.get("version")
    if (
        not isinstance(version, list) or len(version) != 3
        or any(type(item) is not int or item < 0 for item in version)
    ):
        failures.append(prefix + "_version_invalid")
    if type(value.get("entry_lstat_size_bytes")) is not int or value["entry_lstat_size_bytes"] <= 0:
        failures.append(prefix + "_entry_size_invalid")
    if not isinstance(value.get("entry_link_chain"), list):
        failures.append(prefix + "_link_chain_invalid")
    if role == "system_python3_entry":
        if (
            value.get("entry_path") != "/usr/bin/python3"
            or value.get("entry_is_symlink") is not True
            or not value.get("entry_link_chain")
            or target.get("path") != "/usr/bin/python3.14"
        ):
            failures.append(prefix + "_python3_entry_invalid")
    elif role == "system_python314_target":
        if (
            value.get("entry_path") != "/usr/bin/python3.14"
            or value.get("entry_is_symlink") is not False
            or value.get("entry_link_chain") != []
            or target.get("path") != "/usr/bin/python3.14"
        ):
            failures.append(prefix + "_python314_entry_invalid")
    elif role == "bundled_host_python":
        entry_path = value.get("entry_path")
        if (
            not isinstance(entry_path, str) or not entry_path
            or value.get("entry_is_symlink") is not False
            or value.get("entry_link_chain") != []
            or target.get("path") != entry_path
        ):
            failures.append(prefix + "_bundled_entry_invalid")
    else:
        failures.append(prefix + "_role_invalid")
    return failures


def _orchestrator_identity_failures(value: Any, prefix: str) -> List[str]:
    required = {"path", "size_bytes", "sha256", "hardlink_count"}
    if not isinstance(value, dict) or set(value) != required:
        return [prefix + "_schema_invalid"]
    failures: List[str] = []
    if not isinstance(value.get("path"), str) or not value["path"]:
        failures.append(prefix + "_path_invalid")
    if type(value.get("size_bytes")) is not int or value["size_bytes"] <= 0:
        failures.append(prefix + "_size_invalid")
    if not _valid_sha256(value.get("sha256")):
        failures.append(prefix + "_sha256_invalid")
    if type(value.get("hardlink_count")) is not int or value["hardlink_count"] <= 0:
        failures.append(prefix + "_hardlink_count_invalid")
    return failures


def _expected_child_argv(
    workspace: Path, definition: Mapping[str, str], suite: Mapping[str, Any],
    expected_ids: Sequence[str], interpreter_identity: Mapping[str, Any],
    orchestrator_identity: Optional[Mapping[str, Any]],
) -> List[str]:
    runner = UNITTEST_RUNNER if suite["runner"] == "unittest" else PYTEST_RUNNER
    if definition["platform"] == "WINDOWS_HOST":
        argv = [
            interpreter_identity["entry_path"], "-I", "-S", "-B",
            str(Path(workspace).resolve(strict=True).joinpath(*PurePosixPath(runner).parts)),
        ]
        if suite["runner"] == "pytest_style":
            argv.append("--single-file")
        argv.extend((
            "--workspace", str(Path(workspace).resolve(strict=True)),
            "--target", suite["target"], "--import-root", ".",
        ))
    else:
        if not isinstance(orchestrator_identity, Mapping) or not isinstance(orchestrator_identity.get("path"), str):
            raise ValueError("missing WSL orchestrator identity")
        wsl_root = _execution_workspace_path(workspace)
        interpreter = (
            "/usr/bin/python3"
            if definition["interpreter_role"] == "system_python3_entry"
            else "/usr/bin/python3.14"
        )
        argv = [
            orchestrator_identity["path"], "--cd", wsl_root, "--exec",
            "/usr/bin/env", "-i",
            *[key + "=" + value for key, value in sorted(CHILD_ENVIRONMENT.items())],
            interpreter, "-I", "-S", "-B",
            str(PurePosixPath(wsl_root, runner)),
        ]
        if suite["runner"] == "pytest_style":
            argv.append("--single-file")
        argv.extend((
            "--workspace", wsl_root, "--target", suite["target"],
            "--import-root", ".",
        ))
    for case_id in expected_ids:
        argv.extend(("--expected-id", case_id))
    return argv


def _validate_physical_records(
    workspace: Path, value: Any, source_roles: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy,
) -> Tuple[List[str], Dict[str, Mapping[str, Any]]]:
    failures: List[str] = []
    if not isinstance(value, list):
        return ["formal_authority_v5_physical_records_invalid"], {}
    suites = {item["suite_id"]: item for item in suite_inventory(workspace, policy)}
    source_by_key = {
        (item["root_role"], item["path"]): item
        for item in source_roles
        if (
            isinstance(item, dict)
            and isinstance(item.get("root_role"), str)
            and isinstance(item.get("path"), str)
        )
    }
    definitions = {item["record_id"]: item for item in policy.execution_definitions}
    by_id: Dict[str, Mapping[str, Any]] = {}
    required_keys = {
        "record_id", "suite_id", "platform", "interpreter_role",
        "test_artifact_identity", "runner_artifact_identity",
        "interpreter_identity", "orchestrator_identity", "expected_test_ids",
        "executed_test_ids", "passed_ids", "failed_ids", "skipped_ids",
        "collected", "passed", "failed", "skipped", "exit_code",
        "marker_count", "marker_prefix", "marker_payload",
        "marker_payload_sha256", "argv", "argv_sha256", "environment",
        "environment_sha256",
        "stdout", "stderr",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != required_keys:
            failures.append("formal_authority_v5_physical_record_schema_invalid")
            continue
        record_id = item.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            failures.append("formal_authority_v5_physical_record_id_invalid")
            continue
        if record_id in by_id:
            failures.append("formal_authority_v5_physical_record_duplicate:" + str(record_id))
            continue
        by_id[record_id] = item
        definition = definitions.get(record_id)
        if definition is None:
            failures.append("formal_authority_v5_physical_record_unknown:" + str(record_id))
            continue
        suite = suites.get(definition["suite_id"])
        if suite is None:
            failures.append("formal_authority_v5_physical_suite_missing:" + str(record_id))
            continue
        expected_ids = _execution_selection(definition, suites)
        runner_path = UNITTEST_RUNNER if suite["runner"] == "unittest" else PYTEST_RUNNER
        expected_scalars = {
            "record_id": record_id,
            "suite_id": definition["suite_id"],
            "platform": definition["platform"],
            "interpreter_role": definition["interpreter_role"],
            "test_artifact_identity": _identity_from_source(source_by_key, suite["root_role"], suite["target"]),
            "runner_artifact_identity": _identity_from_source(source_by_key, "workspace", runner_path),
            "expected_test_ids": expected_ids,
            "executed_test_ids": expected_ids,
            "collected": len(expected_ids),
            "failed": 0,
            "exit_code": 0,
            "marker_count": 1,
            "marker_prefix": UNITTEST_MARKER if suite["runner"] == "unittest" else PYTEST_MARKER,
        }
        for key, expected in expected_scalars.items():
            if not _same(item.get(key), expected):
                failures.append("formal_authority_v5_physical_record_mismatch:{}:{}".format(record_id, key))
        passed_ids = item.get("passed_ids") if isinstance(item.get("passed_ids"), list) else []
        failed_ids = item.get("failed_ids") if isinstance(item.get("failed_ids"), list) else []
        skipped_ids = item.get("skipped_ids") if isinstance(item.get("skipped_ids"), list) else []
        if failed_ids or set(passed_ids).intersection(skipped_ids) or sorted(passed_ids + skipped_ids) != sorted(expected_ids):
            failures.append("formal_authority_v5_physical_outcome_ids_invalid:" + record_id)
        for key, ids in (("passed", passed_ids), ("failed", failed_ids), ("skipped", skipped_ids)):
            if item.get(key) != len(ids):
                failures.append("formal_authority_v5_physical_count_mismatch:{}:{}".format(record_id, key))
        if item.get("collected") != item.get("passed", -1) + item.get("failed", -1) + item.get("skipped", -1):
            failures.append("formal_authority_v5_physical_count_not_conserved:" + record_id)
        if record_id == "doc_demotion_windows_bundled":
            if skipped_ids not in ([], [DOC_DEMOTION_LINK_CASE_ID]):
                failures.append("formal_authority_v5_windows_skip_set_invalid")
        elif skipped_ids:
            failures.append("formal_authority_v5_unapproved_physical_skip:" + record_id)
        failures.extend(_interpreter_identity_failures(
            item.get("interpreter_identity"), definition["interpreter_role"],
            "formal_authority_v5_interpreter_identity:" + record_id,
        ))
        if definition["platform"] == "POSIX_WSL":
            failures.extend(_orchestrator_identity_failures(
                item.get("orchestrator_identity"),
                "formal_authority_v5_wsl_orchestrator_identity:" + record_id,
            ))
        if definition["platform"] == "WINDOWS_HOST" and item.get("orchestrator_identity") is not None:
            failures.append("formal_authority_v5_windows_orchestrator_must_be_null")
        try:
            expected_argv = _expected_child_argv(
                workspace, definition, suite, expected_ids,
                item.get("interpreter_identity"), item.get("orchestrator_identity"),
            )
        except (KeyError, TypeError, ValueError):
            expected_argv = None
            failures.append("formal_authority_v5_physical_argv_recompute_failed:" + record_id)
        if expected_argv is None or not _same(item.get("argv"), expected_argv):
            failures.append("formal_authority_v5_physical_argv_mismatch:" + record_id)
        environment = item.get("environment")
        if definition["platform"] == "POSIX_WSL":
            if not _same(environment, dict(CHILD_ENVIRONMENT)):
                failures.append("formal_authority_v5_physical_environment_mismatch:" + record_id)
        elif (
            not isinstance(environment, dict)
            or not any(key.lower() == "systemroot" for key in environment)
            or any(
                key.upper().startswith("ROS_")
                or key.upper() in {
                    "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP",
                    "PYTHONUSERBASE", "LD_PRELOAD", "LD_LIBRARY_PATH", "WSLENV",
                }
                for key in environment
            )
            or any(key.upper() not in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"} for key in environment)
        ):
            failures.append("formal_authority_v5_windows_environment_invalid:" + record_id)
        marker = item.get("marker_payload")
        if not isinstance(marker, dict) or item.get("marker_payload_sha256") != _canonical_sha256(marker):
            failures.append("formal_authority_v5_marker_payload_invalid:" + record_id)
        else:
            for key, expected in (
                ("path", suite["target"]),
                ("size_bytes", expected_scalars["test_artifact_identity"]["size_bytes"]),
                ("sha256", expected_scalars["test_artifact_identity"]["sha256"]),
                ("expected_ids", expected_ids), ("executed_ids", expected_ids),
                ("collected", len(expected_ids)), ("passed", len(passed_ids)),
                ("failed", 0), ("skipped", len(skipped_ids)),
            ):
                if not _same(marker.get(key), expected):
                    failures.append("formal_authority_v5_marker_mismatch:{}:{}".format(record_id, key))
            if (
                suite["runner"] == "unittest"
                and not _same(marker.get("executable"), item.get("interpreter_identity"))
            ):
                failures.append(
                    "formal_authority_v5_marker_mismatch:{}:executable".format(
                        record_id
                    )
                )
        for key, material in (
            ("argv_sha256", item.get("argv")),
            ("environment_sha256", item.get("environment")),
            ("marker_payload_sha256", item.get("marker_payload")),
        ):
            if not _valid_sha256(item.get(key)):
                failures.append("formal_authority_v5_physical_hash_invalid:{}:{}".format(record_id, key))
            elif item[key] != _canonical_sha256(material):
                failures.append("formal_authority_v5_physical_hash_mismatch:{}:{}".format(record_id, key))
        if not _stream_identity_valid(item.get("stdout")) or not _stream_identity_valid(item.get("stderr")):
            failures.append("formal_authority_v5_physical_stream_identity_invalid:" + record_id)
    if set(by_id) != set(definitions):
        failures.append("formal_authority_v5_physical_record_set_invalid")
    if value != sorted(
        value,
        key=lambda item: (
            item.get("record_id")
            if isinstance(item, dict) and isinstance(item.get("record_id"), str)
            else "\uffff"
        ),
    ):
        failures.append("formal_authority_v5_physical_record_order_invalid")
    role_identities: Dict[str, Any] = {}
    wsl_orchestrator = None
    for record_id, item in by_id.items():
        role = item.get("interpreter_role")
        identity = item.get("interpreter_identity")
        if role in role_identities and role_identities[role] != identity:
            failures.append("formal_authority_v5_interpreter_role_identity_split:" + str(role))
        role_identities[role] = identity
        if item.get("platform") == "POSIX_WSL":
            if wsl_orchestrator is not None and wsl_orchestrator != item.get("orchestrator_identity"):
                failures.append("formal_authority_v5_wsl_orchestrator_identity_split")
            wsl_orchestrator = item.get("orchestrator_identity")
    python3 = role_identities.get("system_python3_entry", {})
    python314 = role_identities.get("system_python314_target", {})
    if python3 and python314 and python3.get("resolved_target") != python314.get("resolved_target"):
        failures.append("formal_authority_v5_python_entry_target_split")
    return failures, by_id


def _expected_platform_composites(
    physical_by_id: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    windows = physical_by_id.get("doc_demotion_windows_bundled", {})
    posix = physical_by_id.get("doc_demotion_link_posix_companion", {})
    windows_skipped = windows.get("skipped_ids") == [DOC_DEMOTION_LINK_CASE_ID]
    windows_passed = DOC_DEMOTION_LINK_CASE_ID in windows.get("passed_ids", [])
    posix_passed = posix.get("passed_ids") == [DOC_DEMOTION_LINK_CASE_ID]
    return [{
        "composite_id": "doc_demotion_linklike_windows_posix",
        "suite_id": "machine_contract_doc_demotion",
        "case_id": DOC_DEMOTION_LINK_CASE_ID,
        "windows_record_id": "doc_demotion_windows_bundled",
        "windows_outcome": "SKIP" if windows_skipped else ("PASS" if windows_passed else "INVALID"),
        "posix_record_id": "doc_demotion_link_posix_companion",
        "posix_outcome": "PASS" if posix_passed else "INVALID",
        "validated_pass": bool((windows_skipped or windows_passed) and posix_passed),
    }]


def _validate_production_observations(
    workspace: Path, value: Any, source_roles: Sequence[Mapping[str, Any]],
    physical_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[str]:
    if not isinstance(value, list):
        return ["formal_authority_v5_production_observations_invalid"]
    expected = {item["observation_id"]: item for item in PRODUCTION_CLI_EXPECTATIONS}
    sources = {
        (item["root_role"], item["path"]): item
        for item in source_roles
        if (
            isinstance(item, dict)
            and isinstance(item.get("root_role"), str)
            and isinstance(item.get("path"), str)
        )
    }
    by_id: Dict[str, Mapping[str, Any]] = {}
    failures: List[str] = []
    keys = {
        "observation_id", "source_identity_before", "source_identity_after",
        "interpreter_identity", "orchestrator_identity", "argv", "argv_sha256",
        "environment", "environment_sha256", "exit_code", "marker_count", "blocked_code",
        "failure_codes", "stdout", "stderr", "payload", "payload_sha256",
        "expected_fail_closed", "not_in_logical_denominator",
        "not_in_physical_denominator", "formal_consumer", "delivery_ready",
        "self_reported_anchor_accepted", "execution_attempted",
        "supporting_test_id",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != keys:
            failures.append("formal_authority_v5_production_observation_schema_invalid")
            continue
        observation_id = item.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            failures.append(
                "formal_authority_v5_production_observation_id_invalid"
            )
            continue
        if observation_id in by_id:
            failures.append("formal_authority_v5_production_observation_duplicate")
            continue
        by_id[observation_id] = item
        definition = expected.get(observation_id)
        if definition is None:
            failures.append("formal_authority_v5_production_observation_unknown")
            continue
        source = sources.get(("workspace", definition["source_path"]))
        expected_identity = {
            key: source[key] for key in ("root_role", "path", "size_bytes", "sha256")
        } if source else None
        for key, wanted in (
            ("source_identity_before", expected_identity),
            ("source_identity_after", expected_identity),
            ("exit_code", definition["exit_code"]),
            ("marker_count", definition["marker_count"]),
            ("blocked_code", definition["blocked_code"]),
            ("failure_codes", [definition["blocked_code"]]),
            ("execution_attempted", definition["execution_attempted"]),
            ("supporting_test_id", definition["supporting_test_id"]),
            ("expected_fail_closed", True),
            ("not_in_logical_denominator", True),
            ("not_in_physical_denominator", True),
            ("formal_consumer", False), ("delivery_ready", False),
            ("self_reported_anchor_accepted", False),
        ):
            if not _same(item.get(key), wanted):
                failures.append("formal_authority_v5_production_observation_mismatch:{}:{}".format(observation_id, key))
        for key in ("argv_sha256", "environment_sha256", "payload_sha256"):
            if not _valid_sha256(item.get(key)):
                failures.append("formal_authority_v5_production_observation_hash_invalid:{}:{}".format(observation_id, key))
        for key, material in (
            ("argv_sha256", item.get("argv")),
            ("environment_sha256", item.get("environment")),
            ("payload_sha256", item.get("payload")),
        ):
            if _valid_sha256(item.get(key)) and item[key] != _canonical_sha256(material):
                failures.append("formal_authority_v5_production_observation_hash_mismatch:{}:{}".format(observation_id, key))
        if definition["execution_attempted"]:
            payload = item.get("payload")
            if (
                not isinstance(payload, dict)
                or payload.get("failures") != [definition["blocked_code"]]
                or payload.get("validated_pass") is not False
                or payload.get("delivery_ready") is not False
            ):
                failures.append(
                    "formal_authority_v5_production_payload_invalid:"
                    + str(observation_id)
                )
            failures.extend(_interpreter_identity_failures(
                item.get("interpreter_identity"), "system_python314_target",
                "formal_authority_v5_production_interpreter_identity:" + str(observation_id),
            ))
            failures.extend(_orchestrator_identity_failures(
                item.get("orchestrator_identity"),
                "formal_authority_v5_production_orchestrator_identity:" + str(observation_id),
            ))
            try:
                wsl_root = _execution_workspace_path(workspace)
                expected_argv = [
                    item["orchestrator_identity"]["path"], "--cd", wsl_root,
                    "--exec", "/usr/bin/env", "-i",
                    *[
                        key + "=" + value
                        for key, value in sorted(CHILD_ENVIRONMENT.items())
                    ],
                    "/usr/bin/python3.14", "-I", "-S", "-B",
                    str(PurePosixPath(wsl_root, definition["source_path"])),
                ]
            except (KeyError, TypeError, ValueError):
                expected_argv = None
                failures.append(
                    "formal_authority_v5_production_argv_recompute_failed:"
                    + str(observation_id)
                )
            if expected_argv is None or not _same(item.get("argv"), expected_argv):
                failures.append(
                    "formal_authority_v5_production_argv_mismatch:"
                    + str(observation_id)
                )
            if not _same(item.get("environment"), dict(CHILD_ENVIRONMENT)):
                failures.append(
                    "formal_authority_v5_production_environment_mismatch:"
                    + str(observation_id)
                )
            if isinstance(physical_by_id, Mapping):
                python314_identities = [
                    record.get("interpreter_identity")
                    for record in physical_by_id.values()
                    if record.get("interpreter_role") == "system_python314_target"
                ]
                wsl_identities = [
                    record.get("orchestrator_identity")
                    for record in physical_by_id.values()
                    if record.get("platform") == "POSIX_WSL"
                ]
                if (
                    not python314_identities
                    or any(identity != item.get("interpreter_identity") for identity in python314_identities)
                ):
                    failures.append(
                        "formal_authority_v5_production_interpreter_identity_split:"
                        + str(observation_id)
                    )
                if (
                    not wsl_identities
                    or any(identity != item.get("orchestrator_identity") for identity in wsl_identities)
                ):
                    failures.append(
                        "formal_authority_v5_production_orchestrator_identity_split:"
                        + str(observation_id)
                    )
        else:
            if item.get("interpreter_identity") is not None or item.get("orchestrator_identity") is not None:
                failures.append("formal_authority_v5_static_observation_execution_identity_forbidden:" + str(observation_id))
            if item.get("argv") != ["NOT_EXECUTED_SAFETY_BOUNDARY"]:
                failures.append(
                    "formal_authority_v5_static_observation_argv_invalid:"
                    + str(observation_id)
                )
            if item.get("environment") != {}:
                failures.append(
                    "formal_authority_v5_static_observation_environment_invalid:"
                    + str(observation_id)
                )
            payload = item.get("payload")
            if (
                not isinstance(payload, dict)
                or set(payload) != {
                    "execution_attempted", "supporting_test_id",
                    "supporting_record_ids", "blocked_code",
                }
                or payload.get("execution_attempted") is not False
                or payload.get("supporting_test_id") != definition["supporting_test_id"]
                or payload.get("blocked_code") != definition["blocked_code"]
                or not isinstance(payload.get("supporting_record_ids"), list)
                or len(payload["supporting_record_ids"]) != len(set(payload["supporting_record_ids"]))
                or any(
                    not isinstance(record_id, str) or not record_id
                    for record_id in payload["supporting_record_ids"]
                )
            ):
                failures.append(
                    "formal_authority_v5_static_observation_payload_invalid:"
                    + str(observation_id)
                )
        if not _stream_identity_valid(item.get("stdout")) or not _stream_identity_valid(item.get("stderr")):
            failures.append("formal_authority_v5_production_observation_stream_invalid:" + str(observation_id))
    if set(by_id) != set(expected):
        failures.append("formal_authority_v5_production_observation_set_invalid")
    if value != sorted(
        value,
        key=lambda item: (
            item.get("observation_id")
            if isinstance(item, dict) and isinstance(item.get("observation_id"), str)
            else "\uffff"
        ),
    ):
        failures.append("formal_authority_v5_production_observation_order_invalid")
    return failures


def build_canonical_payload(
    workspace: Path, source_roles: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    overlay = collect_live_overlay_binding(workspace, policy)
    payload: Dict[str, Any] = {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "artifact_id": CANONICAL_ARTIFACT_ID,
        "canonical_id": CANONICAL_ID,
        "generation_id": GENERATION_ID,
        "status": "CURRENT_BLOCKED_OFFLINE_SOURCE_BINDING",
        "lifecycle": "CURRENT_CHILD",
        "immutable": True,
        "read_only": True,
        "source_implementation_complete": True,
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "gate_state": dict(GATE_STATE),
        "host_perception_package_tree": collect_host_perception_package_tree(
            workspace, policy,
        ),
        "live_overlay_binding": overlay,
        "source_roles": list(source_roles),
        "source_role_count": len(source_roles),
        "source_role_set_sha256": _source_role_set_sha256(source_roles),
        "source_root_roles": ["workspace", "workspace_parent"],
        "external_trust_root_exclusions": list(EXTERNAL_TRUST_ROOT_EXCLUSIONS),
        "non_formal_diagnostics_included": False,
        "blockers": list(BLOCKERS),
        "accepted_by_formal_field_evidence_consumer": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    payload["artifact_binding_sha256"] = _canonical_sha256(payload)
    return payload


def build_report_payload(
    workspace: Path, canonical_identity: Mapping[str, Any],
    source_roles: Sequence[Mapping[str, Any]],
    logical_records: Sequence[Mapping[str, Any]],
    physical_records: Sequence[Mapping[str, Any]],
    platform_composites: Sequence[Mapping[str, Any]],
    production_observations: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    expected_logical = expected_logical_suite_records(workspace, source_roles, policy)
    if not _same(list(logical_records), expected_logical):
        raise ValueError("logical records mismatch")
    physical_failures, by_id = _validate_physical_records(
        workspace, list(physical_records), source_roles, policy,
    )
    if physical_failures:
        raise ValueError(",".join(physical_failures))
    expected_composites = _expected_platform_composites(by_id)
    if not _same(list(platform_composites), expected_composites) or not all(item["validated_pass"] for item in expected_composites):
        raise ValueError("platform composite mismatch")
    production_failures = _validate_production_observations(
        workspace, production_observations, source_roles, by_id,
    )
    if production_failures:
        raise ValueError(",".join(production_failures))
    logical_total = sum(item["collected"] for item in logical_records)
    physical_collected = sum(item["collected"] for item in physical_records)
    physical_passed = sum(item["passed"] for item in physical_records)
    physical_skipped = sum(item["skipped"] for item in physical_records)
    payload: Dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_kind": "perception_v2_blocked_offline_regression",
        "report_id": REPORT_ID,
        "evidence_id": CURRENT_EVIDENCE_ID,
        "generation_id": GENERATION_ID,
        "status": CURRENT_STATUS,
        "lifecycle": "CURRENT",
        "is_current": True,
        "immutable": True,
        "read_only": True,
        "canonical_source_admission": dict(canonical_identity),
        "source_role_set_sha256": _source_role_set_sha256(source_roles),
        "test_matrix": {
            "suite_definition_sha256": _canonical_sha256(list(policy.suite_definitions)),
            "execution_definition_sha256": _canonical_sha256(list(policy.execution_definitions)),
            "logical_suite_records": list(logical_records),
            "logical_expected_total": logical_total,
            "logical_collected": logical_total,
            "logical_passed": logical_total,
            "logical_failed": 0,
            "logical_skipped": 0,
            "physical_execution_records": list(physical_records),
            "platform_composites": list(platform_composites),
            "physical_expected_total": physical_collected,
            "physical_collected": physical_collected,
            "physical_raw_passed": physical_passed,
            "physical_failed": 0,
            "physical_raw_skipped": physical_skipped,
            "physical_effective_passed": physical_collected,
            "failures": [],
        },
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "production_cli_observations": list(production_observations),
        "gate_state": dict(GATE_STATE),
        "regression_passed": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "formal_denominator": 0,
        "ros_graph_started": False,
        "camera_opened": False,
        "inference_started": False,
        "hardware_connected": False,
        "network_used": False,
    }
    payload["report_binding_sha256"] = _canonical_sha256(payload)
    return payload


def build_index_payload(
    report_identity: Mapping[str, Any], canonical_identity: Mapping[str, Any],
    source_roles: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    if report_identity.get("path") != policy.report_relative_path or _identity_failures(dict(report_identity), "report"):
        raise ValueError("invalid report identity")
    if canonical_identity.get("path") != policy.canonical_relative_path or _identity_failures(dict(canonical_identity), "canonical"):
        raise ValueError("invalid canonical identity")
    predecessor = policy.predecessor_index_identity
    old_entry = {
        "evidence_id": predecessor["current_evidence_id"],
        "generation_id": predecessor["generation_id"],
        "status": "STALE_SUPERSEDED_NON_CURRENT_PREDECESSOR",
        "lifecycle": "SUPERSEDED",
        "is_current": False,
        "predecessor_evidence_id": "ros1_runner_platform_composite_offline_regression_20260815_v4",
        "superseded_by_evidence_id": CURRENT_EVIDENCE_ID,
        "report_kind": "perception_v2_blocked_offline_regression",
        **{key: policy.predecessor_report_identity[key] for key in ("path", "size_bytes", "sha256")},
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    current = {
        "evidence_id": CURRENT_EVIDENCE_ID,
        "report_id": REPORT_ID,
        "generation_id": GENERATION_ID,
        "status": CURRENT_STATUS,
        "lifecycle": "CURRENT",
        "is_current": True,
        "predecessor_evidence_id": predecessor["current_evidence_id"],
        "report_kind": "perception_v2_blocked_offline_regression",
        **dict(report_identity),
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_id": AUTHORITY_FAMILY_ID,
        "index_instance_id": INDEX_INSTANCE_ID,
        "generation_id": GENERATION_ID,
        "generation_scope": GENERATION_SCOPE,
        "immutable": True,
        "read_only": True,
        "selection_authority": SELECTION_AUTHORITY,
        "filename_mtime_selection_forbidden": True,
        "uses_filename_or_mtime_authority": False,
        "accepted_as_offline_release_selection_authority": True,
        "accepted_by_formal_field_evidence_consumer": False,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "current_evidence_id": CURRENT_EVIDENCE_ID,
        "current_required_status": CURRENT_STATUS,
        "predecessor_authority_index": dict(predecessor),
        "entries": [old_entry, current],
        "child_artifacts": [{
            "artifact_id": CANONICAL_ARTIFACT_ID,
            "canonical_id": CANONICAL_ID,
            "parent_evidence_id": CURRENT_EVIDENCE_ID,
            "role": "canonical_source_admission_child",
            "status": "BOUND_BLOCKED_OFFLINE_SOURCE_CHILD",
            "lifecycle": "CURRENT_CHILD",
            "is_current": False,
            **dict(canonical_identity),
            "authorizes_field_delivery": False,
        }],
        "source_roles": list(source_roles),
        "source_role_count": len(source_roles),
        "source_role_set_sha256": _source_role_set_sha256(source_roles),
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "gate_state": dict(GATE_STATE),
    }


def _validate_predecessor_payload(payload: Any, policy: AuthorityPolicy) -> List[str]:
    if not isinstance(payload, dict):
        return ["formal_authority_v5_predecessor_payload_invalid"]
    expected = policy.predecessor_index_identity
    failures: List[str] = []
    for key in ("authority_id", "index_instance_id", "generation_id", "current_evidence_id"):
        if payload.get(key) != expected[key]:
            failures.append("formal_authority_v5_predecessor_semantic_mismatch:" + key)
    currents = [
        item for item in payload.get("entries", [])
        if isinstance(item, dict) and item.get("is_current") is True
    ] if isinstance(payload.get("entries"), list) else []
    if len(currents) != 1:
        failures.append("formal_authority_v5_predecessor_current_count_invalid")
    elif currents[0].get("evidence_id") != expected["current_evidence_id"]:
        failures.append("formal_authority_v5_predecessor_current_mismatch")
    if payload.get("accepted_by_formal_field_evidence_consumer") is not False or payload.get("authorizes_field_delivery") is not False:
        failures.append("formal_authority_v5_predecessor_field_promotion_invalid")
    return failures


def _validate_source_roles(
    workspace: Path, value: Any, policy: AuthorityPolicy,
) -> Tuple[List[str], Dict[Tuple[str, str], Mapping[str, Any]]]:
    if not isinstance(value, list):
        return ["formal_authority_v5_source_roles_invalid"], {}
    expected = {(root_role, path): role for role, root_role, path in policy.source_role_definitions}
    by_key: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    failures: List[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"role", "root_role", "path", "size_bytes", "sha256"}:
            failures.append("formal_authority_v5_source_role_invalid:" + str(index))
            continue
        if (
            not isinstance(item.get("role"), str)
            or not isinstance(item.get("root_role"), str)
            or not isinstance(item.get("path"), str)
        ):
            failures.append(
                "formal_authority_v5_source_role_identity_type_invalid:"
                + str(index)
            )
            continue
        key = (item.get("root_role"), item.get("path"))
        if key in by_key:
            failures.append("formal_authority_v5_source_role_duplicate:" + repr(key))
            continue
        by_key[key] = item
        if expected.get(key) != item.get("role"):
            failures.append("formal_authority_v5_source_role_name_mismatch:" + repr(key))
        identity = {name: item.get(name) for name in ("root_role", "path", "size_bytes", "sha256")}
        failures.extend(_identity_failures(
            identity, "formal_authority_v5_source_role", with_root=True,
            allow_empty=(key in policy.allowed_empty_source_paths),
        ))
        try:
            actual = source_artifact_identity(workspace, key[0], key[1])
        except (OSError, UnicodeError, ValueError, TypeError):
            failures.append("formal_authority_v5_source_role_unreadable:" + repr(key))
            continue
        if actual != identity:
            failures.append("formal_authority_v5_source_role_identity_mismatch:" + repr(key))
        frozen = policy.frozen_source_identities.get(key)
        if frozen is not None and not _same(identity, frozen):
            failures.append("formal_authority_v5_frozen_source_identity_mismatch:" + repr(key))
    if set(by_key) != set(expected):
        failures.append("formal_authority_v5_source_role_set_invalid")
    if value != sorted(
        value,
        key=lambda item: (
            (item.get("root_role"), item.get("path"))
            if (
                isinstance(item, dict)
                and isinstance(item.get("root_role"), str)
                and isinstance(item.get("path"), str)
            )
            else ("\uffff", "\uffff")
        ),
    ):
        failures.append("formal_authority_v5_source_role_order_invalid")
    if any(
        str(item.get("path", "")).lower().startswith("evidence/")
        and "diagnostic" in str(item.get("path", "")).lower()
        for item in value if isinstance(item, dict)
    ):
        failures.append("formal_authority_v5_nonformal_diagnostic_source_forbidden")
    try:
        collect_host_perception_package_tree(workspace, policy)
    except (OSError, TypeError, UnicodeError, ValueError):
        failures.append("formal_authority_v5_host_package_tree_invalid")
    return failures, by_key


def _validate_canonical(
    workspace: Path, payload: Any, source_roles: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy,
) -> List[str]:
    if not isinstance(payload, dict):
        return ["formal_authority_v5_canonical_schema_invalid"]
    binding = payload.get("artifact_binding_sha256")
    without = dict(payload)
    without.pop("artifact_binding_sha256", None)
    expected = build_canonical_payload(workspace, source_roles, policy)
    failures: List[str] = []
    if not _same(payload, expected):
        failures.append("formal_authority_v5_canonical_mismatch")
    if not _valid_sha256(binding) or _canonical_sha256(without) != binding:
        failures.append("formal_authority_v5_canonical_binding_invalid")
    return failures


def _validate_report(
    workspace: Path, payload: Any, canonical_identity: Mapping[str, Any],
    source_roles: Sequence[Mapping[str, Any]], policy: AuthorityPolicy,
) -> List[str]:
    if not isinstance(payload, dict):
        return ["formal_authority_v5_report_schema_invalid"]
    failures: List[str] = []
    expected_keys = {
        "schema_version", "report_kind", "report_id", "evidence_id",
        "generation_id", "status", "lifecycle", "is_current", "immutable",
        "read_only", "canonical_source_admission", "source_role_set_sha256",
        "test_matrix", "production_authority_state",
        "production_cli_observations", "gate_state", "regression_passed",
        "accepted_by_formal_field_evidence_consumer", "delivery_ready",
        "authorizes_field_delivery", "formal_denominator", "ros_graph_started",
        "camera_opened", "inference_started", "hardware_connected",
        "network_used", "report_binding_sha256",
    }
    if set(payload) != expected_keys:
        return ["formal_authority_v5_report_schema_invalid"]
    expected_scalars = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_kind": "perception_v2_blocked_offline_regression",
        "report_id": REPORT_ID, "evidence_id": CURRENT_EVIDENCE_ID,
        "generation_id": GENERATION_ID, "status": CURRENT_STATUS,
        "lifecycle": "CURRENT", "is_current": True, "immutable": True,
        "read_only": True, "canonical_source_admission": dict(canonical_identity),
        "source_role_set_sha256": _source_role_set_sha256(source_roles),
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "gate_state": dict(GATE_STATE), "regression_passed": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "delivery_ready": False, "authorizes_field_delivery": False,
        "formal_denominator": 0, "ros_graph_started": False,
        "camera_opened": False, "inference_started": False,
        "hardware_connected": False, "network_used": False,
    }
    for key, expected in expected_scalars.items():
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v5_report_mismatch:" + key)
    matrix = payload.get("test_matrix")
    matrix_keys = {
        "suite_definition_sha256", "execution_definition_sha256",
        "logical_suite_records", "logical_expected_total", "logical_collected",
        "logical_passed", "logical_failed", "logical_skipped",
        "physical_execution_records", "platform_composites",
        "physical_expected_total", "physical_collected", "physical_raw_passed",
        "physical_failed", "physical_raw_skipped", "physical_effective_passed",
        "failures",
    }
    by_id: Dict[str, Mapping[str, Any]] = {}
    if not isinstance(matrix, dict) or set(matrix) != matrix_keys:
        failures.append("formal_authority_v5_report_test_matrix_invalid")
    else:
        expected_logical = expected_logical_suite_records(workspace, source_roles, policy)
        if not _same(matrix.get("logical_suite_records"), expected_logical):
            failures.append("formal_authority_v5_logical_suite_records_mismatch")
        physical_failures, by_id = _validate_physical_records(
            workspace, matrix.get("physical_execution_records"), source_roles, policy,
        )
        failures.extend(physical_failures)
        expected_composites = _expected_platform_composites(by_id)
        if not _same(matrix.get("platform_composites"), expected_composites) or not all(item["validated_pass"] for item in expected_composites):
            failures.append("formal_authority_v5_platform_composite_invalid")
        logical_total = sum(item["collected"] for item in expected_logical)
        physical = matrix.get("physical_execution_records") if isinstance(matrix.get("physical_execution_records"), list) else []
        physical_collected = sum(item.get("collected", -10**9) for item in physical if isinstance(item, dict))
        physical_passed = sum(item.get("passed", -10**9) for item in physical if isinstance(item, dict))
        physical_skipped = sum(item.get("skipped", -10**9) for item in physical if isinstance(item, dict))
        expected_counts = {
            "suite_definition_sha256": _canonical_sha256(list(policy.suite_definitions)),
            "execution_definition_sha256": _canonical_sha256(list(policy.execution_definitions)),
            "logical_expected_total": logical_total, "logical_collected": logical_total,
            "logical_passed": logical_total, "logical_failed": 0,
            "logical_skipped": 0, "physical_expected_total": physical_collected,
            "physical_collected": physical_collected,
            "physical_raw_passed": physical_passed, "physical_failed": 0,
            "physical_raw_skipped": physical_skipped,
            "physical_effective_passed": physical_collected, "failures": [],
        }
        for key, expected in expected_counts.items():
            if not _same(matrix.get(key), expected):
                failures.append("formal_authority_v5_report_test_count_mismatch:" + key)
    failures.extend(_validate_production_observations(
        workspace, payload.get("production_cli_observations"), source_roles,
        by_id,
    ))
    without = dict(payload)
    claimed = without.pop("report_binding_sha256", None)
    if not _valid_sha256(claimed) or _canonical_sha256(without) != claimed:
        failures.append("formal_authority_v5_report_binding_invalid")
    return failures


def _base_result() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_id": AUTHORITY_FAMILY_ID,
        "index_instance_id": INDEX_INSTANCE_ID,
        "generation_id": GENERATION_ID,
        "generation_scope": GENERATION_SCOPE,
        "semantic_validated_pass": False,
        "validated_pass": False,
        "accepted_as_offline_release_selection_authority": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "regression_passed": False, "delivery_ready": False,
        "authorizes_field_delivery": False,
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False, "formal_3d_pass": False,
        "formal_latency_pass": False,
        "ros1_noetic_runtime_verified": False,
        "ros1_noetic_build_install_verified": False,
        "ros1_noetic_field_install_pass": False,
        "ros1_source_implementation_complete": False,
        "current_evidence": None, "artifact_identities": [], "failures": [],
    }


def validate_formal_admission_evidence_authority_v5(
    workspace: Path, payload: Any,
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    result = _base_result()
    failures: List[str] = result["failures"]
    failures.extend(_policy_failures(policy))
    if failures:
        return result
    if not isinstance(payload, dict):
        failures.append("formal_authority_v5_payload_invalid")
        return result
    expected_keys = {
        "schema_version", "authority_id", "index_instance_id", "generation_id",
        "generation_scope", "immutable", "read_only", "selection_authority",
        "filename_mtime_selection_forbidden", "uses_filename_or_mtime_authority",
        "accepted_as_offline_release_selection_authority",
        "accepted_by_formal_field_evidence_consumer", "authorizes_motion",
        "authorizes_field_delivery", "current_evidence_id",
        "current_required_status", "predecessor_authority_index", "entries",
        "child_artifacts", "source_roles", "source_role_count",
        "source_role_set_sha256", "production_authority_state", "gate_state",
    }
    if set(payload) != expected_keys:
        failures.append("formal_authority_v5_top_level_keys_invalid")
    expected_scalars = {
        "schema_version": SCHEMA_VERSION, "authority_id": AUTHORITY_FAMILY_ID,
        "index_instance_id": INDEX_INSTANCE_ID, "generation_id": GENERATION_ID,
        "generation_scope": GENERATION_SCOPE, "immutable": True,
        "read_only": True, "selection_authority": SELECTION_AUTHORITY,
        "filename_mtime_selection_forbidden": True,
        "uses_filename_or_mtime_authority": False,
        "accepted_as_offline_release_selection_authority": True,
        "accepted_by_formal_field_evidence_consumer": False,
        "authorizes_motion": False, "authorizes_field_delivery": False,
        "current_evidence_id": CURRENT_EVIDENCE_ID,
        "current_required_status": CURRENT_STATUS,
        "predecessor_authority_index": dict(policy.predecessor_index_identity),
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "gate_state": dict(GATE_STATE),
    }
    for key, expected in expected_scalars.items():
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v5_top_level_mismatch:" + key)

    source_failures, unused_by_key = _validate_source_roles(workspace, payload.get("source_roles"), policy)
    failures.extend(source_failures)
    source_roles = payload.get("source_roles") if isinstance(payload.get("source_roles"), list) else []
    if payload.get("source_role_count") != len(source_roles):
        failures.append("formal_authority_v5_source_role_count_invalid")
    if payload.get("source_role_set_sha256") != _source_role_set_sha256(source_roles):
        failures.append("formal_authority_v5_source_role_sha256_invalid")

    entries = payload.get("entries")
    by_id: Dict[str, Mapping[str, Any]] = {}
    currents: List[Mapping[str, Any]] = []
    if not isinstance(entries, list) or len(entries) != 2:
        failures.append("formal_authority_v5_entry_count_invalid")
        entries = entries if isinstance(entries, list) else []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str):
            failures.append("formal_authority_v5_entry_invalid")
            continue
        evidence_id = item["evidence_id"]
        if evidence_id in by_id:
            failures.append("formal_authority_v5_duplicate_evidence_id")
        by_id[evidence_id] = item
        if item.get("is_current") is True:
            currents.append(item)
    predecessor_id = policy.predecessor_index_identity["current_evidence_id"]
    if set(by_id) != {predecessor_id, CURRENT_EVIDENCE_ID}:
        failures.append("formal_authority_v5_entry_set_invalid")
    if len(currents) != 1:
        failures.append("formal_authority_v5_current_count_invalid")
    elif currents[0].get("evidence_id") != CURRENT_EVIDENCE_ID:
        failures.append("formal_authority_v5_current_marker_invalid")

    current = by_id.get(CURRENT_EVIDENCE_ID, {})
    old = by_id.get(predecessor_id, {})
    dummy_report = {"path": policy.report_relative_path, "size_bytes": 1, "sha256": "0" * 64}
    dummy_canonical = {"path": policy.canonical_relative_path, "size_bytes": 1, "sha256": "0" * 64}
    expected_entries = build_index_payload(dummy_report, dummy_canonical, source_roles, policy)["entries"]
    if old != expected_entries[0]:
        failures.append("formal_authority_v5_predecessor_entry_mismatch")
    report_identity = {key: current.get(key) for key in ("path", "size_bytes", "sha256")}
    expected_current = build_index_payload(report_identity, dummy_canonical, source_roles, policy)["entries"][1] if not _identity_failures(report_identity, "report") else None
    if expected_current is None or current != expected_current:
        failures.append("formal_authority_v5_current_entry_mismatch")

    children = payload.get("child_artifacts")
    if not isinstance(children, list) or len(children) != 1 or not isinstance(children[0], dict):
        failures.append("formal_authority_v5_child_artifacts_invalid")
        canonical_identity: Dict[str, Any] = {}
    else:
        child = children[0]
        canonical_identity = {key: child.get(key) for key in ("path", "size_bytes", "sha256")}
        expected_child = build_index_payload(dummy_report, canonical_identity, source_roles, policy)["child_artifacts"][0] if not _identity_failures(canonical_identity, "canonical") else None
        if expected_child is None or child != expected_child:
            failures.append("formal_authority_v5_canonical_child_mismatch")

    artifacts = (
        ("predecessor_index", policy.predecessor_index_identity, "predecessor"),
        ("predecessor_report", policy.predecessor_report_identity, "predecessor_report"),
        ("predecessor_canonical", policy.predecessor_canonical_identity, "predecessor_canonical"),
        (CURRENT_EVIDENCE_ID, {"root_role": "workspace", **report_identity}, "report"),
        (CANONICAL_ARTIFACT_ID, {"root_role": "workspace", **canonical_identity}, "canonical"),
    )
    for artifact_id, expected_identity, role in artifacts:
        try:
            identity, raw = _read_regular_identity(
                workspace, expected_identity.get("root_role", "workspace"),
                expected_identity.get("path"),
            )
            result["artifact_identities"].append({"artifact_id": artifact_id, **identity})
        except (OSError, UnicodeError, ValueError, TypeError):
            failures.append("formal_authority_v5_artifact_unreadable:" + artifact_id)
            continue
        expected_file = {key: expected_identity[key] for key in ("root_role", "path", "size_bytes", "sha256")}
        if not _same(identity, expected_file):
            failures.append("formal_authority_v5_artifact_identity_mismatch:" + artifact_id)
        try:
            artifact_payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            failures.append("formal_authority_v5_artifact_strict_json_invalid:" + artifact_id)
            continue
        try:
            if role == "predecessor":
                failures.extend(_validate_predecessor_payload(artifact_payload, policy))
            elif role == "predecessor_report":
                for key, expected in (
                    ("evidence_id", policy.predecessor_index_identity["current_evidence_id"]),
                    ("generation_id", policy.predecessor_index_identity["generation_id"]),
                    ("regression_passed", False), ("delivery_ready", False),
                    ("authorizes_field_delivery", False),
                ):
                    if not isinstance(artifact_payload, dict) or artifact_payload.get(key) != expected:
                        failures.append("formal_authority_v5_predecessor_report_mismatch:" + key)
            elif role == "predecessor_canonical":
                for key, expected in (
                    ("generation_id", policy.predecessor_index_identity["generation_id"]),
                    ("delivery_ready", False), ("authorizes_field_delivery", False),
                ):
                    if not isinstance(artifact_payload, dict) or artifact_payload.get(key) != expected:
                        failures.append("formal_authority_v5_predecessor_canonical_mismatch:" + key)
            elif role == "report":
                failures.extend(_validate_report(workspace, artifact_payload, canonical_identity, source_roles, policy))
            else:
                failures.extend(_validate_canonical(workspace, artifact_payload, source_roles, policy))
        except (KeyError, OSError, SyntaxError, TypeError, UnicodeError, ValueError):
            failures.append("formal_authority_v5_artifact_semantic_recompute_failed:" + artifact_id)

    failures[:] = list(dict.fromkeys(failures))
    if not failures:
        result["semantic_validated_pass"] = True
    return result


def load_and_resolve_formal_admission_evidence_authority_v5(
    workspace: Path, index_trust_anchor: Mapping[str, Any],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    result = _base_result()
    failures: List[str] = []
    failures.extend(_policy_failures(policy))
    failures.extend(_identity_failures(index_trust_anchor, "formal_authority_v5_index_anchor"))
    if isinstance(index_trust_anchor, dict) and index_trust_anchor.get("path") != policy.index_relative_path:
        failures.append("formal_authority_v5_index_anchor_path_mismatch")
    identity: Dict[str, Any] = {}
    raw = b""
    if not failures:
        try:
            identity_with_root, raw = _read_regular_identity(workspace, "workspace", policy.index_relative_path)
            identity = {key: identity_with_root[key] for key in ("path", "size_bytes", "sha256")}
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v5_index_unreadable")
    if identity and identity != dict(index_trust_anchor):
        for key in ("path", "size_bytes", "sha256"):
            if identity.get(key) != index_trust_anchor.get(key):
                failures.append("formal_authority_v5_index_" + key + "_mismatch")
    payload = None
    if raw:
        try:
            payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            failures.append("formal_authority_v5_index_strict_json_invalid")
    validation = validate_formal_admission_evidence_authority_v5(workspace, payload, policy)
    for failure in failures:
        if failure not in validation["failures"]:
            validation["failures"].append(failure)
    if validation["failures"]:
        validation["semantic_validated_pass"] = False
        validation["validated_pass"] = False
        validation["accepted_as_offline_release_selection_authority"] = False
        validation["ros1_source_implementation_complete"] = False
        validation["current_evidence"] = None
    else:
        validation["validated_pass"] = True
        validation["accepted_as_offline_release_selection_authority"] = True
        validation["ros1_source_implementation_complete"] = True
        validation["current_evidence"] = next(
            dict(item) for item in payload["entries"] if item.get("is_current") is True
        )
    validation["index_identity"] = identity
    validation["expected_index_identity"] = dict(index_trust_anchor) if isinstance(index_trust_anchor, Mapping) else {}
    validation["index_relative_path"] = policy.index_relative_path
    validation["filename_mtime_selection_forbidden"] = True
    return validation


def write_json_exclusive(
    path: Path, payload: Mapping[str, Any], reported_path: Optional[str] = None,
) -> Dict[str, Any]:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != "nt":
        directory = os.open(str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    before = os.lstat(str(path))
    if _is_linklike(before) or not stat.S_ISREG(before.st_mode) or getattr(before, "st_nlink", 1) != 1:
        raise ValueError("exclusive output is not an exclusive regular file")
    reopened = path.read_bytes()
    after = os.lstat(str(path))
    if (
        reopened != raw or _strict_json_bytes(reopened) != payload
        or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    ):
        raise ValueError("exclusive output reopen mismatch")
    return {
        "path": reported_path if reported_path is not None else path.name,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


__all__ = [
    "ALLOWED_EMPTY_SOURCE_PATHS", "ATOMIC_SUPPORTING_TEST_ID",
    "AUTHORITY_FAMILY_ID", "AuthorityPolicy", "BLOCKERS",
    "CANONICAL_ARTIFACT_ID", "CANONICAL_ID", "CANONICAL_RELATIVE_PATH",
    "CANONICAL_SCHEMA_VERSION", "CURRENT_EVIDENCE_ID", "CURRENT_STATUS",
    "DOC_DEMOTION_LINK_CASE_ID", "EXECUTION_DEFINITIONS", "GATE_STATE",
    "GENERATION_ID", "GENERATION_SCOPE", "HOST_PERCEPTION_CACHE_FILES",
    "HOST_PERCEPTION_PACKAGE_FILES", "HOST_PERCEPTION_PACKAGE_ROOT",
    "INDEX_INSTANCE_ID",
    "INDEX_RELATIVE_PATH", "PREDECESSOR_CANONICAL_IDENTITY",
    "PREDECESSOR_INDEX_IDENTITY", "PREDECESSOR_REPORT_IDENTITY",
    "PRODUCTION_AUTHORITY_STATE", "PRODUCTION_CLI_EXPECTATIONS",
    "PRODUCTION_POLICY", "REPORT_ID", "REPORT_RELATIVE_PATH",
    "REPORT_SCHEMA_VERSION", "REQUIRED_SOURCE_ROLE_DEFINITIONS",
    "SCHEMA_VERSION", "SUITE_DEFINITIONS", "UNITTEST_MARKER",
    "PYTEST_MARKER", "WORKSPACE_ROOT", "artifact_identity",
    "build_canonical_payload", "build_index_payload", "build_report_payload",
    "collect_host_perception_package_tree", "collect_live_overlay_binding",
    "collect_source_role_bindings",
    "expected_logical_suite_records", "load_and_resolve_formal_admission_evidence_authority_v5",
    "source_artifact_identity", "static_test_ids", "suite_inventory",
    "validate_formal_admission_evidence_authority_v5", "write_json_exclusive",
]
