"""Host-owned successor authority for the runner-platform-composite release.

This module is deliberately separate from the frozen v2 resolver.  It binds
the immutable v3 authority index as its predecessor, the v4 offline report as
its only current evidence, and canonical source admission v5 as a child.

No repository index is created or selected by importing this module.  A
caller must provide an exact external path/size/SHA-256 anchor for the new
index.  Passing validation grants only offline release-evidence selection;
formal field consumption, build/install, delivery, motion, TF, 3D, latency,
ROS graph, camera, inference, remote access, and hardware remain false.
"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from audit_tools import formal_admission_evidence_authority_v2 as _v2


SCHEMA_VERSION = "ros1_formal_admission_evidence_authority/v3"
SPEC_SCHEMA_VERSION = "ros1_formal_admission_evidence_authority_spec/v3"
AUTHORITY_FAMILY_ID = "ros1-formal-admission-evidence-authority-20260815-v2"
DEFAULT_INDEX_INSTANCE_ID = (
    "ros1-formal-admission-evidence-authority-index-20260815-v4"
)
DEFAULT_GENERATION_ID = "ros1_runner_platform_composite_20260815_v4"
DEFAULT_GENERATION_SCOPE = (
    "blocked_offline_ros1_runner_platform_composite_not_field_delivery"
)
DEFAULT_CURRENT_EVIDENCE_ID = (
    "ros1_runner_platform_composite_offline_regression_20260815_v4"
)
DEFAULT_CURRENT_STATUS = "CURRENT_BLOCKED_OFFLINE_BASELINE"
SELECTION_AUTHORITY = (
    "FIXED_INDEX_PATH_EXTERNAL_SIZE_SHA256_STRICT_JSON_AND_SEMANTIC_RECOMPUTE"
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SUCCESSOR_INDEX_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_v4.json"
)
# Host-owned external anchor, filled only after exclusive index creation and
# an independent bytes/SHA-256 recomputation.  Selection never scans by name
# or mtime and never accepts an index-supplied replacement for this value.
PRODUCTION_INDEX_TRUST_ANCHOR: Mapping[str, Any] = {
    "path": SUCCESSOR_INDEX_RELATIVE_PATH,
    "size_bytes": 5015,
    "sha256": "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded",
}

PREDECESSOR_INDEX_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_v3.json"
    ),
    "size_bytes": 4687,
    "sha256": "c13fcbb5832afc06473fd243c452ded191a688ddb808d43fb6fb2ad6e4ac2f20",
    "status": "SUPERSEDED_NON_CURRENT_PREDECESSOR_AUTHORITY",
    "lifecycle": "SUPERSEDED",
    "authority_id": AUTHORITY_FAMILY_ID,
    "generation_id": "ros1_delivery_blocker_layering_20260815_v3",
    "current_evidence_id": (
        "ros1_delivery_blocker_layering_offline_regression_20260815_v3"
    ),
}

SUPERSEDED_REPORT: Mapping[str, Any] = {
    "evidence_id": (
        "ros1_delivery_blocker_layering_offline_regression_20260815_v3"
    ),
    "generation_id": "ros1_delivery_blocker_layering_20260815_v3",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_ros1_delivery_blocker_layering_v3.json"
    ),
    "size_bytes": 601070,
    "sha256": "dd97ae1ff4d991d0b0449c947109eab45d9628f885e1646e305463120b8d37f1",
    "scope": "blocked_offline_ros1_delivery_blocker_layering_not_field_delivery",
    "predecessor_evidence_id": (
        "ros1_runtime_source_admission_offline_regression_20260815_v2"
    ),
}

CURRENT_REPORT_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_runner_platform_composite_v4.json"
    ),
    "size_bytes": 1288709,
    "sha256": "dfa7e3f8c53f6157fec5083b26b8fc87b3115dcfb9eb6fbbde2fbcf52775c5be",
}

CANONICAL_CHILD_ID = "ros1_noetic_canonical_source_admission_20260815_v5"
CANONICAL_CHILD_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_noetic_canonical_source_admission_20260815_v5.json"
    ),
    "size_bytes": 9889,
    "sha256": "1c4a9c2901cae292803cec4a700550c2054a26b94e1ae89aacbedb3865e7801a",
}
CANONICAL_EXPECTED: Mapping[str, Any] = {
    "schema_version": 1,
    "binding_kind": "canonical_project_overlay",
    "canonical_source_root": "ros1_overlay_src/limo_cleanup_ros1_perception",
    "file_count": 50,
    "source_contract_pass": True,
    "indexer_only_detected": False,
    "test_only": False,
    "architecture_blockers": [],
}

EMBEDDED_RUNNER_AUTHORITY_EVIDENCE_ID = "ros1_canonical_source_binding_v7"

DEFAULT_TEST_COUNTS: Mapping[str, int] = {
    "expected_grand_total": 197,
    "grand_total_collected": 197,
    "grand_total_passed": 197,
    "supplemental_expected_total": 10,
    "supplemental_collected": 10,
    "supplemental_passed": 10,
    "supplemental_failed": 0,
    "post_fix_expected_total": 63,
    "post_fix_collected": 63,
    "post_fix_passed": 63,
    "post_fix_failed": 0,
    "current_generation_expected_total": 144,
    "current_generation_collected": 144,
    "current_generation_passed": 144,
    "current_generation_failed": 0,
    "current_generation_physical_expected_total": 147,
    "current_generation_physical_collected": 147,
    "current_generation_physical_passed": 147,
    "current_generation_physical_failed": 0,
    "current_generation_physical_skipped": 0,
    "mandatory_logical_expected_total": 414,
    "mandatory_logical_collected": 414,
    "mandatory_logical_passed": 414,
    "mandatory_physical_expected_total": 417,
}

DEFAULT_REPORT_BLOCKERS: Tuple[str, ...] = (
    "CURRENT_BASELINE_BLOCKED_OFFLINE_ONLY",
    "FORMAL_3D_NOT_VALIDATED",
    "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
    "FORMAL_LATENCY_NOT_VALIDATED",
    "FORMAL_TF_NOT_VALIDATED",
    "ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED",
    "ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING",
    "ROS1_NOETIC_FIELD_INSTALL_NOT_VALIDATED",
    "WSL_E_ACCESSDENIED_BEFORE_SHELL_OR_BUILD",
)
DEFAULT_GATE_BLOCKERS = DEFAULT_REPORT_BLOCKERS

PYTEST_PREFIX = "OFFLINE_PYTEST_FILE_RESULT "
PYTEST_SCHEMA = "offline_pytest_file_result/v1"
PYTEST_RUNNER_KIND = "offline_pytest_style_single_file"
PYTEST_HELPER_IDENTITY: Mapping[str, Any] = {
    "path": "audit_tools/run_pytest_style_tests.py",
    "size_bytes": 20531,
    "sha256": "90bc0cbf6a09e11d3e8ec8daf4de6897a6c91a10a0e64cacf0f88eb298d09ecc",
}
PYTEST_IMPORT_ROOTS = (
    "src/limo_cleanup_perception",
    "src/limo_cleanup_interfaces",
    ".",
)
PYTEST_FILE_PATHS: Tuple[str, ...] = (
    "src/limo_cleanup_perception/test/test_dual_model_source_contract.py",
    "src/limo_cleanup_perception/test/test_offline_dual_detector_source_contract.py",
    "src/limo_cleanup_perception/test/test_orchestration_source_contract.py",
    "src/limo_cleanup_perception/test/test_perception_collector_source_contract.py",
    "src/limo_cleanup_perception/test/test_rgbd_contract.py",
    "src/limo_cleanup_perception/test/test_source_manifest_script.py",
    "src/limo_cleanup_perception/test/test_task_actions.py",
    "src/limo_cleanup_perception/test/test_perception_readiness_source_contract.py",
    "src/limo_cleanup_perception/test/test_camera_query_allowlist.py",
    "src/limo_cleanup_perception/test/test_frozen_regression_runner.py",
    "src/limo_cleanup_perception/test/test_ros1_dabai_runtime_contract.py",
    "src/limo_cleanup_perception/test/test_ros1_model_binding_contract.py",
    "src/limo_cleanup_perception/test/test_ros1_semantic_readiness.py",
    "src/limo_cleanup_perception/test/test_ros1_runtime_source_contract.py",
    "src/limo_cleanup_perception/test/test_ros1_formal_rosbag1_admission.py",
    "src/limo_cleanup_perception/test/test_ros1_delivery_install_gate_layering.py",
)
EXPECTED_PYTEST_CASE_TOTAL = 121

UNITTEST_PREFIX = "OFFLINE_UNITTEST_FILE_RESULT "
UNITTEST_SCHEMA = "offline_unittest_file_result/v1"
UNITTEST_RUNNER_KIND = "stdlib_unittest_single_file_isolated"
UNITTEST_HELPER_IDENTITY: Mapping[str, Any] = {
    "path": "audit_tools/run_unittest_file_tests.py",
    "size_bytes": 25783,
    "sha256": "f8679d38a974dbfcbc6c87908e8485f4e8593d8423bc4b93d896c013acb800b1",
}
UNITTEST_IMPORT_ROOTS = (
    "src/limo_cleanup_perception",
    "ros1_overlay_src/limo_cleanup_ros1_perception/src",
    ".",
)
WINDOWS_UNITTEST_PLAN: Tuple[Tuple[str, str, Any], ...] = (
    ("diagnostic_evidence_lineage",
     "src/limo_cleanup_perception/test/test_diagnostic_evidence_lineage.py", None),
    ("ros1_runtime_behavior",
     "src/limo_cleanup_perception/test/test_ros1_runtime_behavior.py", None),
    ("ros1_runtime_implementation_admission",
     "src/limo_cleanup_perception/test/test_ros1_runtime_implementation_admission.py", None),
    ("ros1_noetic_field_readiness_host",
     "src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness.py", None),
    ("ros1_field_install_new_gates",
     "src/limo_cleanup_perception/test/test_ros1_field_install_gate.py", (
         "Ros1FieldInstallGateTest.test_build_source_space_is_exactly_the_audited_isolation_root",
         "Ros1FieldInstallGateTest.test_distribution_artifact_and_junit_are_host_recomputed",
         "Ros1FieldInstallGateTest.test_host_fresh_import_probe_executes_and_binds_evidence_module",
         "Ros1FieldInstallGateTest.test_validator_recomputes_runtime_dependency_inventory",
         "Ros1FieldInstallGateTest.test_validator_requires_isolated_prefix_import_smoke",
     )),
    ("ros1_adapter_pure_fake",
     "ros1_overlay_src/limo_cleanup_ros1_perception/test/test_ros1_adapter_pure_fake.py", None),
    ("ros1_runtime_install_contract",
     "ros1_overlay_src/limo_cleanup_ros1_perception/test/test_runtime_install_contract.py", None),
    ("ros1_noetic_field_readiness_exact_cli",
     "src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness_exact_cli.py", None),
)
EXPECTED_WINDOWS_UNITTEST_TOTAL = 85

EXACT_CLI_PATH = WINDOWS_UNITTEST_PLAN[-1][1]
HOST_READINESS_PATH = WINDOWS_UNITTEST_PLAN[3][1]
PROBE_TEST_PATH = (
    "ros1_overlay_src/limo_cleanup_ros1_perception/test/"
    "test_rosbag1_isolated_probe.py"
)
EXACT_POSIX_CASE_ID = (
    EXACT_CLI_PATH
    + "::Ros1NoeticFieldReadinessExactCliTest."
      "test_linklike_python_root_is_rejected_before_probe_load"
)
HOST_POSIX_CASE_IDS: Tuple[str, ...] = (
    HOST_READINESS_PATH
    + "::Ros1NoeticFieldReadinessTest."
      "test_linklike_authority_probe_rejects_before_fake_runner",
    HOST_READINESS_PATH
    + "::Ros1NoeticFieldReadinessTest."
      "test_linklike_artifact_is_rejected_when_platform_supports_links",
)
WSL_UNITTEST_PLAN: Tuple[Tuple[str, str, str, Any], ...] = (
    ("ros1_noetic_field_readiness_exact_cli_posix_companion",
     EXACT_CLI_PATH, "/usr/bin/python3", (EXACT_POSIX_CASE_ID,)),
    ("ros1_noetic_field_readiness_host_linklike_authority_posix_companion",
     HOST_READINESS_PATH, "/usr/bin/python3", (HOST_POSIX_CASE_IDS[0],)),
    ("ros1_noetic_field_readiness_host_linklike_artifact_posix_companion",
     HOST_READINESS_PATH, "/usr/bin/python3", (HOST_POSIX_CASE_IDS[1],)),
    ("rosbag1_isolated_probe_python3",
     PROBE_TEST_PATH, "/usr/bin/python3", None),
    ("rosbag1_isolated_probe_python3_14",
     PROBE_TEST_PATH, "/usr/bin/python3.14", None),
)
EXPECTED_WSL_UNITTEST_TOTAL = 39

HOST_EXECUTABLE_IDENTITY: Mapping[str, Any] = {
    "entry_path": (
        "C:\\Users\\DYH\\.cache\\codex-runtimes\\codex-primary-runtime\\"
        "dependencies\\python\\python.exe"
    ),
    "entry_is_symlink": False,
    "entry_lstat_size_bytes": 91648,
    "entry_link_chain": [],
    "resolved_target": {
        "path": (
            "C:\\Users\\DYH\\.cache\\codex-runtimes\\codex-primary-runtime\\"
            "dependencies\\python\\python.exe"
        ),
        "size_bytes": 91648,
        "sha256": "3c6a206b7d93cca823934a83732220dcffd413fd1036d9fb82eebb64599cf7f3",
        "regular_file": True,
        "is_symlink": False,
    },
    "isolated": True,
    "no_bytecode": True,
    "version": [3, 12, 13],
}
WSL_PYTHON_IDENTITIES: Mapping[str, Mapping[str, Any]] = {
    "/usr/bin/python3": {
        "entry_path": "/usr/bin/python3",
        "entry_is_symlink": True,
        "entry_lstat_size_bytes": 10,
        "entry_link_chain": [{
            "path": "/usr/bin/python3",
            "link_target": "python3.14",
            "next_path": "/usr/bin/python3.14",
        }],
        "resolved_target": {
            "path": "/usr/bin/python3.14",
            "size_bytes": 7477096,
            "sha256": "fa9796cd3a30878e11a2f40372f773d3fcd913fff35e5bee8dd9a036e22e93ab",
            "regular_file": True,
            "is_symlink": False,
        },
        "isolated": True,
        "no_bytecode": True,
        "version": [3, 14, 4],
    },
    "/usr/bin/python3.14": {
        "entry_path": "/usr/bin/python3.14",
        "entry_is_symlink": False,
        "entry_lstat_size_bytes": 7477096,
        "entry_link_chain": [],
        "resolved_target": {
            "path": "/usr/bin/python3.14",
            "size_bytes": 7477096,
            "sha256": "fa9796cd3a30878e11a2f40372f773d3fcd913fff35e5bee8dd9a036e22e93ab",
            "regular_file": True,
            "is_symlink": False,
        },
        "isolated": True,
        "no_bytecode": True,
        "version": [3, 14, 4],
    },
}
WSL_LAUNCHER_IDENTITY: Mapping[str, Any] = {
    "path": "C:\\Windows\\System32\\wsl.exe",
    "size_bytes": 278528,
    "sha256": "7e9f5cee6d641481e5a942f0e08563bae9c17ee55f0aad888f9aa0be9a5d4757",
}
WSL_DISTRIBUTION = "Ubuntu"

ENVIRONMENT_ALLOWLIST = [
    "COMSPEC", "LANG", "LC_ALL", "PATH", "PATHEXT", "SYSTEMDRIVE",
    "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "WINDIR",
]


def _same(actual: Any, expected: Any) -> bool:
    return _v2._same(actual, expected)


def _append(failures: List[str], value: str) -> None:
    if value not in failures:
        failures.append(value)


def _strict_json_bytes(raw: bytes) -> Any:
    return _v2._strict_json_bytes(raw)


def _regular_identity(
    workspace: Path, relative: str
) -> Tuple[Path, Dict[str, Any], bytes]:
    return _v2._regular_identity(workspace, relative)


def _safe_relative(value: Any) -> bool:
    return _v2._safe_relative(value)


def _valid_sha256(value: Any) -> bool:
    return _v2._valid_sha256(value)


def _identity_failures(identity: Any, prefix: str) -> List[str]:
    return [
        value.replace("formal_authority_v2", "formal_authority_v3")
        for value in _v2._identity_failures(identity, prefix)
    ]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _plain_int(value: Any) -> bool:
    return type(value) is int


def _windows_to_wsl(path: Path) -> str:
    value = PureWindowsPath(str(path))
    drive = value.drive.rstrip(":").lower()
    if len(drive) != 1 or not drive.isalpha():
        raise ValueError("workspace drive is not convertible to WSL")
    return str(PurePosixPath("/mnt", drive, *value.parts[1:]))


def _absolute_regular_identity(path_value: str) -> Dict[str, Any]:
    path = Path(path_value)
    info = os.lstat(str(path))
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    ):
        raise ValueError("absolute anchor is linklike")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("absolute anchor is not regular")
    raw = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _static_unittest_case_ids(
    workspace: Path, relative: str, selected_names: Any = None
) -> Tuple[str, ...]:
    unused, unused_identity, raw = _regular_identity(workspace, relative)
    tree = ast.parse(raw.decode("utf-8"), filename=relative, feature_version=8)
    by_suffix: Dict[str, List[str]] = {}
    case_ids: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            children = (node,)
            class_name = None
        elif isinstance(node, ast.ClassDef):
            children = tuple(node.body)
            class_name = node.name
        else:
            continue
        for child in children:
            if (
                not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                or not child.name.startswith("test_")
            ):
                continue
            suffix = (
                child.name if class_name is None
                else class_name + "." + child.name
            )
            case_id = relative + "::" + suffix
            by_suffix.setdefault(suffix, []).append(case_id)
            case_ids.append(case_id)
    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("zero or duplicate unittest cases")
    full = tuple(sorted(case_ids))
    if selected_names is None:
        return full
    selected: List[str] = []
    for name in selected_names:
        if name.startswith(relative + "::"):
            case_id = name
        else:
            suffix = name.rsplit("::", 1)[-1]
            matches = by_suffix.get(suffix, [])
            if len(matches) != 1:
                raise ValueError("selected unittest case missing or ambiguous")
            case_id = matches[0]
        if case_id not in full:
            raise ValueError("selected unittest case absent")
        selected.append(case_id)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("selected unittest cases invalid")
    return tuple(sorted(selected))


def make_generation_spec(
    *,
    current_report_identity: Mapping[str, Any],
    canonical_child_identity: Mapping[str, Any],
    index_relative_path: str,
    canonical_expected: Mapping[str, Any] = CANONICAL_EXPECTED,
    authority_id: str = AUTHORITY_FAMILY_ID,
    index_instance_id: str = DEFAULT_INDEX_INSTANCE_ID,
    generation_id: str = DEFAULT_GENERATION_ID,
    generation_scope: str = DEFAULT_GENERATION_SCOPE,
    current_evidence_id: str = DEFAULT_CURRENT_EVIDENCE_ID,
    current_status: str = DEFAULT_CURRENT_STATUS,
    test_counts: Mapping[str, Any] = DEFAULT_TEST_COUNTS,
    report_blockers: Sequence[str] = DEFAULT_REPORT_BLOCKERS,
    gate_blockers: Sequence[str] = DEFAULT_GATE_BLOCKERS,
) -> Dict[str, Any]:
    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "authority_id": authority_id,
        "index_instance_id": index_instance_id,
        "generation_id": generation_id,
        "generation_scope": generation_scope,
        "current_evidence_id": current_evidence_id,
        "current_status": current_status,
        "index_relative_path": index_relative_path,
        "current_report_identity": dict(current_report_identity),
        "canonical_child_identity": dict(canonical_child_identity),
        "canonical_expected": deepcopy(dict(canonical_expected)),
        "test_counts": dict(test_counts),
        "report_blockers": list(report_blockers),
        "gate_blockers": list(gate_blockers),
    }


def successor_generation_spec() -> Dict[str, Any]:
    """Return the fixed report-v4/canonical-v5 candidate generation spec."""
    return make_generation_spec(
        current_report_identity=CURRENT_REPORT_IDENTITY,
        canonical_child_identity=CANONICAL_CHILD_IDENTITY,
        index_relative_path=SUCCESSOR_INDEX_RELATIVE_PATH,
    )


def _spec_failures(spec: Any) -> List[str]:
    keys = {
        "schema_version", "authority_id", "index_instance_id",
        "generation_id", "generation_scope", "current_evidence_id",
        "current_status", "index_relative_path", "current_report_identity",
        "canonical_child_identity", "canonical_expected", "test_counts",
        "report_blockers", "gate_blockers",
    }
    failures: List[str] = []
    if not isinstance(spec, dict) or set(spec) != keys:
        return ["formal_authority_v3_spec_schema_invalid"]
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        failures.append("formal_authority_v3_spec_schema_version_mismatch")
    for key in (
        "authority_id", "index_instance_id", "generation_id",
        "generation_scope", "current_evidence_id", "current_status",
    ):
        if not isinstance(spec.get(key), str) or not spec[key]:
            failures.append("formal_authority_v3_spec_value_invalid:" + key)
    if spec.get("authority_id") != AUTHORITY_FAMILY_ID:
        failures.append("formal_authority_v3_authority_family_mismatch")
    if spec.get("index_instance_id") == PREDECESSOR_INDEX_IDENTITY.get(
        "index_instance_id"
    ):
        failures.append("formal_authority_v3_index_instance_reused")
    if not _safe_relative(spec.get("index_relative_path")):
        failures.append("formal_authority_v3_spec_index_path_invalid")
    failures.extend(_identity_failures(
        spec.get("current_report_identity"),
        "formal_authority_v3_current_report",
    ))
    failures.extend(_identity_failures(
        spec.get("canonical_child_identity"),
        "formal_authority_v3_canonical_child",
    ))
    paths = {
        PREDECESSOR_INDEX_IDENTITY["path"], SUPERSEDED_REPORT["path"],
        spec.get("index_relative_path"),
    }
    for key in ("current_report_identity", "canonical_child_identity"):
        value = spec.get(key)
        if isinstance(value, dict):
            paths.add(value.get("path"))
    if len(paths) != 5:
        failures.append("formal_authority_v3_spec_artifact_path_collision")
    if not _same(spec.get("canonical_expected"), dict(CANONICAL_EXPECTED)):
        failures.append("formal_authority_v3_canonical_expected_mismatch")
    if not _same(spec.get("test_counts"), dict(DEFAULT_TEST_COUNTS)):
        failures.append("formal_authority_v3_test_counts_mismatch")
    for key in ("report_blockers", "gate_blockers"):
        value = spec.get(key)
        if value != sorted(set(DEFAULT_REPORT_BLOCKERS)):
            failures.append("formal_authority_v3_blockers_mismatch:" + key)
    return list(dict.fromkeys(failures))


def expected_index_payload(spec: Mapping[str, Any]) -> Dict[str, Any]:
    failures = _spec_failures(spec)
    if failures:
        raise ValueError("invalid successor generation spec: " + ",".join(failures))
    current_id = spec["current_evidence_id"]
    report = spec["current_report_identity"]
    canonical = spec["canonical_child_identity"]
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_id": spec["authority_id"],
        "index_instance_id": spec["index_instance_id"],
        "generation_id": spec["generation_id"],
        "generation_scope": spec["generation_scope"],
        "immutable": True,
        "read_only": True,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_as_offline_release_selection_authority": True,
        "accepted_by_formal_field_evidence_consumer": False,
        "filename_mtime_selection_forbidden": True,
        "uses_filename_or_mtime_authority": False,
        "selection_authority": SELECTION_AUTHORITY,
        "current_evidence_id": current_id,
        "current_required_status": spec["current_status"],
        "predecessor_authority_index": dict(PREDECESSOR_INDEX_IDENTITY),
        "entries": [
            {
                "evidence_id": SUPERSEDED_REPORT["evidence_id"],
                "generation_id": SUPERSEDED_REPORT["generation_id"],
                "path": SUPERSEDED_REPORT["path"],
                "size_bytes": SUPERSEDED_REPORT["size_bytes"],
                "sha256": SUPERSEDED_REPORT["sha256"],
                "status": "SUPERSEDED_NON_CURRENT",
                "lifecycle": "SUPERSEDED",
                "is_current": False,
                "scope": SUPERSEDED_REPORT["scope"],
                "report_kind": "perception_v2_frozen_offline_regression",
                "regression_passed": False,
                "delivery_ready": False,
                "authorizes_field_delivery": False,
                "predecessor_evidence_id": SUPERSEDED_REPORT[
                    "predecessor_evidence_id"
                ],
                "superseded_by_evidence_id": current_id,
            },
            {
                "evidence_id": current_id,
                "generation_id": spec["generation_id"],
                "path": report["path"],
                "size_bytes": report["size_bytes"],
                "sha256": report["sha256"],
                "status": spec["current_status"],
                "lifecycle": "CURRENT",
                "is_current": True,
                "scope": spec["generation_scope"],
                "report_kind": "perception_v2_frozen_offline_regression",
                "regression_passed": False,
                "delivery_ready": False,
                "authorizes_field_delivery": False,
                "predecessor_evidence_id": SUPERSEDED_REPORT["evidence_id"],
                "superseded_by_evidence_id": None,
            },
        ],
        "child_artifacts": [{
            "artifact_id": CANONICAL_CHILD_ID,
            "parent_evidence_id": current_id,
            "role": "canonical_source_admission_child",
            "path": canonical["path"],
            "size_bytes": canonical["size_bytes"],
            "sha256": canonical["sha256"],
            "status": "BOUND_BLOCKED_SOURCE_CHILD",
            "lifecycle": "CURRENT_CHILD",
            "is_current": False,
            "authorizes_field_delivery": False,
        }],
        "gate_state": {
            "regression_passed": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
            "formal_four_scene_frame_denominator": 0,
            "formal_tf_pass": False,
            "formal_3d_pass": False,
            "formal_latency_pass": False,
            "ros1_noetic_field_install_pass": False,
            "ros1_noetic_build_install_verified": False,
            "ros1_source_implementation_complete": True,
            "ros1_source_architecture_blockers": [],
            "historical_runtime_not_implemented_observation_superseded": True,
            "active_blockers": list(spec["gate_blockers"]),
        },
    }


def _validate_predecessor_index(payload: Any) -> List[str]:
    failures: List[str] = []
    if not isinstance(payload, dict):
        return ["formal_authority_v3_predecessor_index_invalid"]
    for key, expected in (
        ("schema_version", "ros1_formal_admission_evidence_authority/v2"),
        ("authority_id", PREDECESSOR_INDEX_IDENTITY["authority_id"]),
        ("generation_id", PREDECESSOR_INDEX_IDENTITY["generation_id"]),
        ("current_evidence_id", PREDECESSOR_INDEX_IDENTITY["current_evidence_id"]),
        ("accepted_as_offline_release_selection_authority", True),
        ("accepted_by_formal_field_evidence_consumer", False),
        ("authorizes_field_delivery", False),
    ):
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v3_predecessor_mismatch:" + key)
    entries = payload.get("entries")
    currents = [
        item for item in entries
        if isinstance(item, dict) and item.get("is_current") is True
    ] if isinstance(entries, list) else []
    if len(currents) != 1:
        failures.append("formal_authority_v3_predecessor_current_count_invalid")
    elif any(
        not _same(currents[0].get(key), SUPERSEDED_REPORT[key])
        for key in ("evidence_id", "generation_id", "path", "size_bytes", "sha256")
    ):
        failures.append("formal_authority_v3_predecessor_current_binding_invalid")
    return failures


def _validate_pytest_ledger(matrix: Any, workspace: Path) -> List[str]:
    failures: List[str] = []
    if not isinstance(matrix, dict):
        return ["formal_authority_v3_pytest_matrix_invalid"]
    root = Path(workspace).resolve(strict=True)
    expected_policy = {
        "environment_allowlist": ENVIRONMENT_ALLOWLIST,
        "import_roots": list(PYTEST_IMPORT_ROOTS),
        "marker_prefix": PYTEST_PREFIX,
        "one_isolated_process_per_unique_file": True,
        "python_isolated_flag": True,
        "python_no_bytecode_flag": True,
        "filename_or_total_only_selection_forbidden": True,
        "fixed_cwd": str(root),
    }
    if not _same(matrix.get("pytest_style_file_execution_policy"), expected_policy):
        failures.append("formal_authority_v3_pytest_policy_invalid")
    inventory = matrix.get("pytest_style_file_inventory")
    if not isinstance(inventory, dict) or set(inventory) != {
        "ordered_paths", "unique_file_count", "failures"
    }:
        failures.append("formal_authority_v3_pytest_inventory_schema_invalid")
    else:
        if inventory.get("ordered_paths") != list(PYTEST_FILE_PATHS):
            failures.append("formal_authority_v3_pytest_inventory_paths_invalid")
        if inventory.get("unique_file_count") != len(PYTEST_FILE_PATHS):
            failures.append("formal_authority_v3_pytest_inventory_count_invalid")
        if inventory.get("failures") != []:
            failures.append("formal_authority_v3_pytest_inventory_failures")
    records = matrix.get("pytest_style_file_records")
    if not isinstance(records, list) or len(records) != len(PYTEST_FILE_PATHS):
        return failures + ["formal_authority_v3_pytest_record_count_invalid"]
    helper_path, helper_identity, unused = _regular_identity(
        root, PYTEST_HELPER_IDENTITY["path"]
    )
    if not _same(helper_identity, dict(PYTEST_HELPER_IDENTITY)):
        failures.append("formal_authority_v3_pytest_helper_identity_mismatch")
    global_ids: List[str] = []
    totals = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0}
    hashes: List[str] = []
    for index, (record, relative) in enumerate(zip(records, PYTEST_FILE_PATHS)):
        prefix = "formal_authority_v3_pytest_record:{}:".format(index)
        if not isinstance(record, dict) or set(record) != _v2.PYTEST_RECORD_KEYS:
            _append(failures, prefix + "schema_invalid")
            continue
        if record.get("path") != relative:
            _append(failures, prefix + "path_invalid")
        try:
            unused_path, live_identity, unused_raw = _regular_identity(root, relative)
            live_ids = list(_v2._static_pytest_case_ids(root, relative))
        except (OSError, UnicodeError, SyntaxError, ValueError, TypeError):
            _append(failures, prefix + "live_source_invalid")
            continue
        hashes.append(live_identity["sha256"])
        if not _same(record.get("pre_identity"), live_identity) or not _same(
            record.get("post_identity"), live_identity
        ):
            _append(failures, prefix + "source_identity_mismatch")
        if record.get("source_unchanged") is not True:
            _append(failures, prefix + "source_unchanged_invalid")
        expected_ids = record.get("expected_ids")
        if expected_ids != live_ids or record.get("executed_ids") != live_ids:
            _append(failures, prefix + "id_set_mismatch")
        if len(live_ids) != len(set(live_ids)):
            _append(failures, prefix + "duplicate_live_id")
        global_ids.extend(live_ids)
        allocations = record.get("allocations")
        allocated: List[str] = []
        if not isinstance(allocations, list) or not allocations:
            _append(failures, prefix + "allocations_invalid")
        else:
            for item in allocations:
                if not isinstance(item, dict) or set(item) != {
                    "scope", "suite_id", "expected_ids"
                }:
                    _append(failures, prefix + "allocation_schema_invalid")
                    continue
                ids = item.get("expected_ids")
                if (
                    item.get("scope") not in {
                        "frozen_full", "frozen_selected", "post_freeze",
                        "post_fix", "current_generation",
                    }
                    or not isinstance(item.get("suite_id"), str)
                    or not item["suite_id"]
                    or not isinstance(ids, list)
                    or not ids
                    or len(ids) != len(set(ids))
                ):
                    _append(failures, prefix + "allocation_invalid")
                    continue
                allocated.extend(ids)
        if len(allocated) != len(set(allocated)) or sorted(allocated) != live_ids:
            _append(failures, prefix + "allocation_coverage_mismatch")
        for key in totals:
            value = record.get(key)
            if not _plain_int(value) or value < 0:
                _append(failures, prefix + "count_invalid:" + key)
                value = 0
            totals[key] += value
        count = len(live_ids)
        if any((
            record.get("collected") != count,
            record.get("passed") != count,
            record.get("failed") != 0,
            record.get("skipped") != 0,
            record.get("failures") != [],
            record.get("validated_pass") is not True,
        )):
            _append(failures, prefix + "result_invalid")
        marker = record.get("marker_payload")
        marker_expected = {
            "schema_version": PYTEST_SCHEMA,
            "runner_kind": PYTEST_RUNNER_KIND,
            "path": relative,
            "size_bytes": live_identity["size_bytes"],
            "sha256": live_identity["sha256"],
            "expected_ids": live_ids,
            "executed_ids": live_ids,
            "collected": count,
            "passed": count,
            "failed": 0,
            "skipped": 0,
            "exit": 0,
            "result": "PASS",
        }
        if not _same(marker, marker_expected):
            _append(failures, prefix + "marker_mismatch")
        marker_raw = _canonical_json(marker)
        if (
            record.get("marker_json_length_bytes") != len(marker_raw)
            or record.get("marker_json_sha256")
            != hashlib.sha256(marker_raw).hexdigest()
        ):
            _append(failures, prefix + "marker_identity_mismatch")
        command = record.get("command")
        if not isinstance(command, dict) or set(command) != _v2.PYTEST_COMMAND_KEYS:
            _append(failures, prefix + "command_schema_invalid")
            continue
        expected_argv = [
            HOST_EXECUTABLE_IDENTITY["entry_path"], "-I", "-B",
            str(helper_path), "--single-file", "--workspace", str(root),
            "--target", str(root.joinpath(*PurePosixPath(relative).parts)),
        ]
        for value in PYTEST_IMPORT_ROOTS:
            expected_argv.extend(("--import-root", value))
        for value in live_ids:
            expected_argv.extend(("--expected-id", value))
        expected_stdout = PYTEST_PREFIX + marker_raw.decode("utf-8") + "\n"
        failures.extend(_command_failures(
            command, expected_argv, str(root), expected_stdout, prefix
        ))
    if len(global_ids) != EXPECTED_PYTEST_CASE_TOTAL or len(global_ids) != len(
        set(global_ids)
    ):
        failures.append("formal_authority_v3_pytest_case_set_invalid")
    if totals != {
        "collected": EXPECTED_PYTEST_CASE_TOTAL,
        "passed": EXPECTED_PYTEST_CASE_TOTAL,
        "failed": 0,
        "skipped": 0,
    }:
        failures.append("formal_authority_v3_pytest_totals_invalid")
    if len(hashes) != len(set(hashes)):
        failures.append("formal_authority_v3_pytest_duplicate_hash")
    return list(dict.fromkeys(failures))


def _command_failures(
    command: Any,
    expected_argv: Sequence[str],
    expected_cwd: str,
    expected_stdout: str,
    prefix: str,
) -> List[str]:
    failures: List[str] = []
    if not isinstance(command, dict) or set(command) != _v2.PYTEST_COMMAND_KEYS:
        return [prefix + "command_schema_invalid"]
    if command.get("argv") != list(expected_argv):
        failures.append(prefix + "command_argv_mismatch")
    duration = command.get("duration_sec")
    if (
        command.get("cwd") != expected_cwd
        or command.get("exit_code") != 0
        or command.get("timed_out") is not False
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration < 0
    ):
        failures.append(prefix + "command_result_invalid")
    stdout = expected_stdout.encode("utf-8")
    if (
        command.get("stdout_head") != expected_stdout[:2000]
        or command.get("stdout_tail") != expected_stdout[-2000:]
        or command.get("stdout_length_bytes") != len(stdout)
        or command.get("stdout_length_chars") != len(expected_stdout)
        or command.get("stdout_sha256") != hashlib.sha256(stdout).hexdigest()
    ):
        failures.append(prefix + "stdout_identity_mismatch")
    empty_sha = hashlib.sha256(b"").hexdigest()
    if (
        command.get("stderr_head") != ""
        or command.get("stderr_tail") != ""
        or command.get("stderr_length_bytes") != 0
        or command.get("stderr_length_chars") != 0
        or command.get("stderr_sha256") != empty_sha
    ):
        failures.append(prefix + "stderr_not_empty")
    return failures


def _expected_unittest_argv(
    root: Path,
    relative: str,
    expected_ids: Sequence[str],
    platform: str,
    executable_entry: str,
) -> Tuple[List[str], str, str]:
    helper_relative = UNITTEST_HELPER_IDENTITY["path"]
    if platform == "windows":
        execution_root = str(root)
        helper = str(root.joinpath(*PurePosixPath(helper_relative).parts))
        target = str(root.joinpath(*PurePosixPath(relative).parts))
        argv = [executable_entry, "-I", "-B", helper]
        command_cwd = str(root)
    else:
        execution_root = _windows_to_wsl(root)
        helper = str(PurePosixPath(execution_root, helper_relative))
        target = str(PurePosixPath(execution_root, relative))
        argv = [
            WSL_LAUNCHER_IDENTITY["path"], "--distribution", WSL_DISTRIBUTION,
            "--exec", "/usr/bin/env", "-i", "HOME=/tmp", "LANG=C.UTF-8",
            "LC_ALL=C.UTF-8", "PATH=/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE=1", executable_entry, "-I", "-B", helper,
        ]
        command_cwd = str(root)
    argv.extend(("--workspace", execution_root, "--target", target))
    for value in UNITTEST_IMPORT_ROOTS:
        argv.extend(("--import-root", value))
    for value in expected_ids:
        argv.extend(("--expected-id", value))
    return argv, execution_root, target


def _validate_unittest_record(
    record: Any,
    workspace: Path,
    *,
    record_id: str,
    relative: str,
    selected_names: Any,
    platform: str,
    executable_entry: str,
    allowed_skips: Sequence[str],
    allocations_required: bool,
) -> Tuple[List[str], Dict[str, Any]]:
    prefix = "formal_authority_v3_unittest_record:" + record_id + ":"
    failures: List[str] = []
    if not isinstance(record, dict):
        return [prefix + "missing"], {}
    windows_keys = {
        "allocations", "collected", "command", "environment", "executable",
        "executed_ids", "expected_ids", "failed", "failed_ids", "failures",
        "helper_identity", "marker_json_length_bytes", "marker_json_sha256",
        "marker_payload", "passed", "passed_ids", "path", "platform",
        "post_identity", "pre_identity", "record_id", "skipped", "skipped_ids",
        "source_unchanged", "validated_pass",
    }
    wsl_keys = (windows_keys - {"allocations"}) | {
        "requested_executable_entry", "wsl_distribution", "wsl_launcher_identity"
    }
    expected_keys = windows_keys if allocations_required else wsl_keys
    if set(record) != expected_keys:
        failures.append(prefix + "schema_invalid")
    try:
        unused, live_identity, unused_raw = _regular_identity(workspace, relative)
        full_ids = list(_static_unittest_case_ids(workspace, relative))
        expected_ids = list(_static_unittest_case_ids(
            workspace, relative, selected_names
        ))
        unused, helper_identity, unused_raw = _regular_identity(
            workspace, UNITTEST_HELPER_IDENTITY["path"]
        )
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return failures + [prefix + "live_identity_invalid"], {}
    if not _same(helper_identity, dict(UNITTEST_HELPER_IDENTITY)):
        failures.append(prefix + "helper_live_identity_mismatch")
    if (
        record.get("record_id") != record_id
        or record.get("platform") != platform
        or record.get("path") != relative
    ):
        failures.append(prefix + "provenance_mismatch")
    if (
        not _same(record.get("pre_identity"), live_identity)
        or not _same(record.get("post_identity"), live_identity)
        or record.get("source_unchanged") is not True
        or not _same(record.get("helper_identity"), helper_identity)
    ):
        failures.append(prefix + "source_or_helper_identity_mismatch")
    if (
        record.get("expected_ids") != expected_ids
        or record.get("executed_ids") != expected_ids
    ):
        failures.append(prefix + "expected_or_executed_ids_mismatch")
    passed_ids = record.get("passed_ids")
    failed_ids = record.get("failed_ids")
    skipped_ids = record.get("skipped_ids")
    if not all(isinstance(value, list) for value in (
        passed_ids, failed_ids, skipped_ids
    )):
        failures.append(prefix + "outcome_ids_schema_invalid")
        passed_ids, failed_ids, skipped_ids = [], [], []
    outcomes = passed_ids + failed_ids + skipped_ids
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(expected_ids):
        failures.append(prefix + "outcome_partition_invalid")
    if failed_ids or not set(skipped_ids).issubset(set(allowed_skips)):
        failures.append(prefix + "failure_or_unapproved_skip")
    if set(passed_ids) != set(expected_ids) - set(skipped_ids):
        failures.append(prefix + "passed_ids_invalid")
    expected_counts = {
        "collected": len(expected_ids),
        "passed": len(passed_ids),
        "failed": 0,
        "skipped": len(skipped_ids),
    }
    for key, expected in expected_counts.items():
        if not _same(record.get(key), expected):
            failures.append(prefix + "count_mismatch:" + key)
    if record.get("failures") != [] or record.get("validated_pass") is not True:
        failures.append(prefix + "record_not_validated")
    expected_executable = (
        HOST_EXECUTABLE_IDENTITY if platform == "windows"
        else WSL_PYTHON_IDENTITIES[executable_entry]
    )
    if not _same(record.get("executable"), expected_executable):
        failures.append(prefix + "executable_identity_mismatch")
    if platform == "posix_wsl":
        if (
            record.get("requested_executable_entry") != executable_entry
            or record.get("wsl_distribution") != WSL_DISTRIBUTION
            or not _same(record.get("wsl_launcher_identity"), WSL_LAUNCHER_IDENTITY)
        ):
            failures.append(prefix + "wsl_provenance_mismatch")
    argv, execution_root, absolute_target = _expected_unittest_argv(
        Path(workspace).resolve(strict=True), relative, expected_ids,
        platform, executable_entry,
    )
    marker = record.get("marker_payload")
    marker_keys = {
        "schema_version", "runner_kind", "selection_mode", "workspace",
        "import_roots", "path", "resolved_path", "size_bytes", "sha256",
        "target_identity_before", "target_identity_after", "requested_ids",
        "expected_ids", "executed_ids", "passed_ids", "failed_ids",
        "skipped_ids", "discovered_ids", "discovered", "collected", "passed",
        "failed", "skipped", "exit", "result", "failures", "executable",
        "python", "environment", "environment_unchanged_during_execution",
        "environment_restored", "stdout_marker_count",
    }
    if not isinstance(marker, dict) or set(marker) != marker_keys:
        failures.append(prefix + "marker_schema_invalid")
        marker = {}
    absolute_identity = {
        "path": absolute_target,
        "size_bytes": live_identity["size_bytes"],
        "sha256": live_identity["sha256"],
        "regular_file": True,
        "is_symlink": False,
    }
    expected_status = "PASS_WITH_SKIPS" if skipped_ids else "PASS"
    semantic_checks = {
        "schema_version": UNITTEST_SCHEMA,
        "runner_kind": UNITTEST_RUNNER_KIND,
        "selection_mode": "selected_ids",
        "workspace": execution_root,
        "import_roots": list(UNITTEST_IMPORT_ROOTS),
        "path": relative,
        "resolved_path": absolute_target,
        "size_bytes": live_identity["size_bytes"],
        "sha256": live_identity["sha256"],
        "target_identity_before": absolute_identity,
        "target_identity_after": absolute_identity,
        "requested_ids": expected_ids,
        "expected_ids": expected_ids,
        "executed_ids": expected_ids,
        "passed_ids": passed_ids,
        "failed_ids": [],
        "skipped_ids": skipped_ids,
        "discovered_ids": full_ids,
        "discovered": len(full_ids),
        "collected": len(expected_ids),
        "passed": len(passed_ids),
        "failed": 0,
        "skipped": len(skipped_ids),
        "exit": 0,
        "result": expected_status,
        "failures": [],
        "executable": expected_executable,
        "python": expected_executable,
        "environment_unchanged_during_execution": True,
        "environment_restored": True,
        "stdout_marker_count": 1,
    }
    for key, expected in semantic_checks.items():
        if not _same(marker.get(key), expected):
            _append(failures, prefix + "marker_semantic_mismatch:" + key)
    environment = marker.get("environment")
    if (
        not isinstance(environment, dict)
        or environment.get("clean") is not True
        or environment.get("contaminated_keys") != []
        or environment.get("cwd") != execution_root
        or not _same(record.get("environment"), environment)
    ):
        failures.append(prefix + "environment_invalid")
    marker_raw = _canonical_json(marker)
    if (
        record.get("marker_json_length_bytes") != len(marker_raw)
        or record.get("marker_json_sha256")
        != hashlib.sha256(marker_raw).hexdigest()
    ):
        failures.append(prefix + "marker_identity_mismatch")
    expected_stdout = UNITTEST_PREFIX + marker_raw.decode("utf-8") + "\n"
    failures.extend(_command_failures(
        record.get("command"), argv, str(Path(workspace).resolve(strict=True)),
        expected_stdout, prefix,
    ))
    return list(dict.fromkeys(failures)), {
        "expected_ids": expected_ids,
        "full_ids": full_ids,
        "live_identity": live_identity,
        "helper_identity": helper_identity,
        "passed_ids": passed_ids,
        "skipped_ids": skipped_ids,
    }


def _validate_unittest_ledgers(matrix: Any, workspace: Path) -> List[str]:
    failures: List[str] = []
    if not isinstance(matrix, dict):
        return ["formal_authority_v3_unittest_matrix_invalid"]
    root = Path(workspace).resolve(strict=True)
    try:
        host_executable_live = _absolute_regular_identity(
            HOST_EXECUTABLE_IDENTITY["entry_path"]
        )
    except (OSError, ValueError):
        host_executable_live = None
    expected_host_executable_live = {
        "path": HOST_EXECUTABLE_IDENTITY["entry_path"],
        "size_bytes": HOST_EXECUTABLE_IDENTITY["resolved_target"]["size_bytes"],
        "sha256": HOST_EXECUTABLE_IDENTITY["resolved_target"]["sha256"],
    }
    if not _same(host_executable_live, expected_host_executable_live):
        failures.append("formal_authority_v3_host_executable_live_identity_mismatch")
    try:
        wsl_launcher_live = _absolute_regular_identity(
            WSL_LAUNCHER_IDENTITY["path"]
        )
    except (OSError, ValueError):
        wsl_launcher_live = None
    if not _same(wsl_launcher_live, dict(WSL_LAUNCHER_IDENTITY)):
        failures.append("formal_authority_v3_wsl_launcher_live_identity_mismatch")
    expected_policy = {
        "environment_allowlist": ENVIRONMENT_ALLOWLIST,
        "import_roots": list(UNITTEST_IMPORT_ROOTS),
        "marker_prefix": UNITTEST_PREFIX,
        "one_isolated_process_per_file_and_interpreter": True,
        "python_isolated_flag": True,
        "python_no_bytecode_flag": True,
        "filename_mtime_or_total_only_selection_forbidden": True,
        "fixed_cwd": str(root),
        "skip_is_never_counted_as_pass": True,
        "posix_companion_required": True,
        "windows_exact_skip_allowlist": [EXACT_POSIX_CASE_ID],
        "windows_host_readiness_skip_allowlist": list(HOST_POSIX_CASE_IDS),
        "wsl_distribution": WSL_DISTRIBUTION,
        "wsl_python_entries": ["/usr/bin/python3", "/usr/bin/python3.14"],
        "wsl_python_target_identity": dict(
            WSL_PYTHON_IDENTITIES["/usr/bin/python3.14"]["resolved_target"]
        ) | {"path": "/usr/bin/python3.14"},
    }
    expected_policy["wsl_python_target_identity"].pop("regular_file", None)
    expected_policy["wsl_python_target_identity"].pop("is_symlink", None)
    if not _same(matrix.get("unittest_file_execution_policy"), expected_policy):
        failures.append("formal_authority_v3_unittest_policy_invalid")
    expected_paths = [item[1] for item in WINDOWS_UNITTEST_PLAN]
    inventory = matrix.get("unittest_file_inventory")
    if not isinstance(inventory, dict) or set(inventory) != {
        "ordered_paths", "unique_file_count", "failures"
    }:
        failures.append("formal_authority_v3_unittest_inventory_schema_invalid")
    else:
        if inventory.get("ordered_paths") != expected_paths:
            failures.append("formal_authority_v3_unittest_inventory_paths_invalid")
        if inventory.get("unique_file_count") != len(expected_paths):
            failures.append("formal_authority_v3_unittest_inventory_count_invalid")
        if inventory.get("failures") != []:
            failures.append("formal_authority_v3_unittest_inventory_failures")
    windows_records = matrix.get("unittest_file_records")
    if not isinstance(windows_records, list) or len(windows_records) != len(
        WINDOWS_UNITTEST_PLAN
    ):
        return failures + ["formal_authority_v3_windows_record_count_invalid"]
    windows_by_path: Dict[str, Mapping[str, Any]] = {}
    windows_total = 0
    for record, (suite_id, relative, selected) in zip(
        windows_records, WINDOWS_UNITTEST_PLAN
    ):
        allowed = (
            (EXACT_POSIX_CASE_ID,) if relative == EXACT_CLI_PATH
            else HOST_POSIX_CASE_IDS if relative == HOST_READINESS_PATH
            else ()
        )
        item_failures, recomputed = _validate_unittest_record(
            record, root,
            record_id="windows:" + relative,
            relative=relative,
            selected_names=selected,
            platform="windows",
            executable_entry=HOST_EXECUTABLE_IDENTITY["entry_path"],
            allowed_skips=allowed,
            allocations_required=True,
        )
        failures.extend(item_failures)
        if isinstance(record, dict):
            allocations = record.get("allocations")
            expected_allocation = [{
                "scope": "current_generation",
                "suite_id": suite_id,
                "expected_ids": recomputed.get("expected_ids", []),
            }]
            if not _same(allocations, expected_allocation):
                failures.append(
                    "formal_authority_v3_windows_allocation_mismatch:" + suite_id
                )
            windows_total += record.get("collected", 0) if _plain_int(
                record.get("collected")
            ) else 0
            windows_by_path[relative] = record
    if windows_total != EXPECTED_WINDOWS_UNITTEST_TOTAL:
        failures.append("formal_authority_v3_windows_total_invalid")

    wsl_records = matrix.get("wsl_unittest_file_records")
    expected_wsl_ids = [item[0] for item in WSL_UNITTEST_PLAN]
    if not isinstance(wsl_records, dict) or set(wsl_records) != set(expected_wsl_ids):
        return failures + ["formal_authority_v3_wsl_record_set_invalid"]
    if matrix.get("wsl_unittest_file_failures") != []:
        failures.append("formal_authority_v3_wsl_failures_nonempty")
    wsl_total = 0
    wsl_recomputed: Dict[str, Dict[str, Any]] = {}
    for suite_id, relative, executable, selected in WSL_UNITTEST_PLAN:
        record = wsl_records.get(suite_id)
        item_failures, recomputed = _validate_unittest_record(
            record, root, record_id=suite_id, relative=relative,
            selected_names=selected, platform="posix_wsl",
            executable_entry=executable, allowed_skips=(),
            allocations_required=False,
        )
        failures.extend(item_failures)
        wsl_recomputed[suite_id] = recomputed
        if isinstance(record, dict):
            wsl_total += record.get("collected", 0) if _plain_int(
                record.get("collected")
            ) else 0
    if wsl_total != EXPECTED_WSL_UNITTEST_TOTAL:
        failures.append("formal_authority_v3_wsl_total_invalid")

    exact_windows = windows_by_path.get(EXACT_CLI_PATH, {})
    exact_posix = wsl_records.get(WSL_UNITTEST_PLAN[0][0], {})
    exact_ids = _static_unittest_case_ids(root, EXACT_CLI_PATH)
    failures.extend(_validate_exact_composite(
        exact_windows, exact_posix, exact_ids
    ))
    host_windows = windows_by_path.get(HOST_READINESS_PATH, {})
    host_posix = {
        HOST_POSIX_CASE_IDS[0]: wsl_records.get(WSL_UNITTEST_PLAN[1][0]),
        HOST_POSIX_CASE_IDS[1]: wsl_records.get(WSL_UNITTEST_PLAN[2][0]),
    }
    host_ids = _static_unittest_case_ids(root, HOST_READINESS_PATH)
    failures.extend(_validate_host_composite(
        host_windows, host_posix, host_ids
    ))
    failures.extend(_validate_current_generation_suite_material(
        matrix, windows_by_path, wsl_records, root
    ))
    return list(dict.fromkeys(failures))


def _validate_exact_composite(
    windows_record: Mapping[str, Any],
    posix_record: Mapping[str, Any],
    expected_ids: Sequence[str],
) -> List[str]:
    failures: List[str] = []
    if windows_record.get("expected_ids") != list(expected_ids):
        failures.append("formal_authority_v3_exact_windows_ids_mismatch")
    if windows_record.get("skipped_ids") not in ([], [EXACT_POSIX_CASE_ID]):
        failures.append("formal_authority_v3_exact_windows_skip_invalid")
    if (
        posix_record.get("expected_ids") != [EXACT_POSIX_CASE_ID]
        or posix_record.get("passed_ids") != [EXACT_POSIX_CASE_ID]
        or posix_record.get("failed") != 0
        or posix_record.get("skipped") != 0
    ):
        failures.append("formal_authority_v3_exact_posix_not_passed")
    if (
        posix_record.get("post_identity") != windows_record.get("post_identity")
        or posix_record.get("helper_identity") != windows_record.get("helper_identity")
    ):
        failures.append("formal_authority_v3_exact_identity_binding_mismatch")
    if set(windows_record.get("passed_ids", [])) | set(
        posix_record.get("passed_ids", [])
    ) != set(expected_ids):
        failures.append("formal_authority_v3_exact_logical_coverage_invalid")
    return failures


def _validate_host_composite(
    windows_record: Mapping[str, Any],
    posix_records: Mapping[str, Any],
    expected_ids: Sequence[str],
) -> List[str]:
    failures: List[str] = []
    if windows_record.get("expected_ids") != list(expected_ids):
        failures.append("formal_authority_v3_host_windows_ids_mismatch")
    skipped = windows_record.get("skipped_ids")
    if not isinstance(skipped, list) or not set(skipped).issubset(
        set(HOST_POSIX_CASE_IDS)
    ):
        failures.append("formal_authority_v3_host_windows_skip_invalid")
    posix_passed = set()
    record_ids: List[Any] = []
    for case_id in HOST_POSIX_CASE_IDS:
        record = posix_records.get(case_id)
        if not isinstance(record, dict):
            failures.append("formal_authority_v3_host_companion_missing:" + case_id)
            continue
        record_ids.append(record.get("record_id"))
        if (
            record.get("expected_ids") != [case_id]
            or record.get("passed_ids") != [case_id]
            or record.get("failed") != 0
            or record.get("skipped") != 0
        ):
            failures.append("formal_authority_v3_host_companion_not_passed:" + case_id)
        else:
            posix_passed.add(case_id)
        if (
            record.get("post_identity") != windows_record.get("post_identity")
            or record.get("helper_identity") != windows_record.get("helper_identity")
        ):
            failures.append("formal_authority_v3_host_identity_binding_mismatch")
    if len(record_ids) != len(set(record_ids)):
        failures.append("formal_authority_v3_host_duplicate_companion")
    if set(windows_record.get("passed_ids", [])) | posix_passed != set(expected_ids):
        failures.append("formal_authority_v3_host_logical_coverage_invalid")
    return failures


def _validate_current_generation_suite_material(
    matrix: Mapping[str, Any],
    windows_by_path: Mapping[str, Mapping[str, Any]],
    wsl_records: Mapping[str, Mapping[str, Any]],
    workspace: Path,
) -> List[str]:
    failures: List[str] = []
    suites = matrix.get("current_generation_suites")
    expected_suite_counts = {
        "diagnostic_evidence_lineage": 9,
        "readiness_bundle_manifest_binding": 1,
        "ros1_adapter_pure_fake": 2,
        "ros1_delivery_install_gate_layering": 3,
        "ros1_field_install_new_gates": 5,
        "ros1_formal_rosbag1_admission": 18,
        "ros1_formal_rosbag1_source_admission": 1,
        "ros1_noetic_field_readiness_exact_cli": 11,
        "ros1_noetic_field_readiness_host": 22,
        "ros1_runtime_behavior": 10,
        "ros1_runtime_implementation_admission": 20,
        "ros1_runtime_install_contract": 6,
        "rosbag1_isolated_probe_python3": 18,
        "rosbag1_isolated_probe_python3_14": 18,
    }
    if not isinstance(suites, dict) or set(suites) != set(expected_suite_counts):
        return ["formal_authority_v3_current_suite_set_invalid"]
    for suite_id, expected in expected_suite_counts.items():
        item = suites.get(suite_id)
        if not isinstance(item, dict):
            failures.append("formal_authority_v3_current_suite_invalid:" + suite_id)
            continue
        for key, value in (
            ("expected", expected), ("collected", expected),
            ("passed", expected), ("failed", 0), ("skipped", 0),
            ("validated_pass", True),
        ):
            if not _same(item.get(key), value):
                failures.append(
                    "formal_authority_v3_current_suite_count_mismatch:"
                    + suite_id + ":" + key
                )
    exact = suites["ros1_noetic_field_readiness_exact_cli"]
    exact_win = windows_by_path.get(EXACT_CLI_PATH)
    exact_posix = wsl_records.get(WSL_UNITTEST_PLAN[0][0])
    if (
        exact.get("runner") != "platform_composite_isolated_unittest"
        or exact.get("raw_windows") != exact_win
        or exact.get("raw_posix_companion") != exact_posix
        or exact.get("physical_collected") != 12
        or exact.get("physical_passed") != 12
        or exact.get("physical_failed") != 0
        or exact.get("physical_skipped") != 0
        or exact.get("failures") != []
    ):
        failures.append("formal_authority_v3_exact_suite_material_invalid")
    host = suites["ros1_noetic_field_readiness_host"]
    host_win = windows_by_path.get(HOST_READINESS_PATH)
    expected_host_posix = {
        HOST_POSIX_CASE_IDS[0]: wsl_records.get(WSL_UNITTEST_PLAN[1][0]),
        HOST_POSIX_CASE_IDS[1]: wsl_records.get(WSL_UNITTEST_PLAN[2][0]),
    }
    if (
        host.get("runner") != "platform_composite_isolated_unittest"
        or host.get("raw_windows") != host_win
        or host.get("raw_posix_companions") != expected_host_posix
        or host.get("physical_collected") != 24
        or host.get("physical_passed") != 24
        or host.get("physical_failed") != 0
        or host.get("physical_skipped") != 0
        or host.get("failures") != []
    ):
        failures.append("formal_authority_v3_host_suite_material_invalid")
    for suite_id, wsl_id in (
        ("rosbag1_isolated_probe_python3", "rosbag1_isolated_probe_python3"),
        ("rosbag1_isolated_probe_python3_14", "rosbag1_isolated_probe_python3_14"),
    ):
        item = suites[suite_id]
        record = wsl_records[wsl_id]
        if (
            item.get("runner") != "wsl_isolated_unittest_file"
            or item.get("file_identity") != record.get("post_identity")
            or item.get("executable") != record.get("executable")
            or item.get("command") != record.get("command")
        ):
            failures.append("formal_authority_v3_probe_suite_material_invalid:" + suite_id)
    logical = sum(expected_suite_counts.values())
    physical = logical + 3
    if logical != 144 or physical != 147:
        failures.append("formal_authority_v3_internal_suite_denominator_invalid")
    return failures


def _validate_report(
    payload: Any, spec: Mapping[str, Any], workspace: Path, *, current: bool
) -> List[str]:
    prefix = (
        "formal_authority_v3_current_report"
        if current else "formal_authority_v3_superseded_report"
    )
    failures: List[str] = []
    if not isinstance(payload, dict):
        return [prefix + "_payload_invalid"]
    for key, expected in (
        ("report_kind", "perception_v2_frozen_offline_regression"),
        ("schema_version", 1), ("read_only", True),
        ("authorizes_motion", False), ("regression_passed", False),
        ("delivery_ready", False), ("publishes_ros_messages", False),
        ("ros_graph_started", False), ("camera_opened", False),
        ("hardware_connected", False),
    ):
        if not _same(payload.get(key), expected):
            failures.append(prefix + "_semantic_mismatch:" + key)
    if not current:
        return failures
    matrix = payload.get("test_matrix")
    if not isinstance(matrix, dict):
        return failures + [prefix + "_test_matrix_invalid"]
    for key, expected in spec["test_counts"].items():
        if not _same(matrix.get(key), expected):
            failures.append(prefix + "_test_count_mismatch:" + key)
    if matrix.get("failures") != []:
        failures.append(prefix + "_test_failures_nonempty")
    if (
        matrix.get("mandatory_physical_expected_total")
        != matrix.get("expected_grand_total")
        + matrix.get("supplemental_expected_total")
        + matrix.get("post_fix_expected_total")
        + matrix.get("current_generation_physical_expected_total")
    ):
        failures.append(prefix + "_mandatory_physical_recompute_mismatch")
    failures.extend(_validate_pytest_ledger(matrix, workspace))
    failures.extend(_validate_unittest_ledgers(matrix, workspace))
    inventory = payload.get("frozen_inventory")
    manifest = (
        inventory.get("current_generation_wsl_unittest_target_manifest")
        if isinstance(inventory, dict) else None
    )
    expected_wsl_ids = [item[0] for item in WSL_UNITTEST_PLAN]
    expected_manifest = {
        "schema_version": "current_generation_wsl_unittest_target_manifest/v1",
        "expected_record_ids": expected_wsl_ids,
        "actual_record_ids": expected_wsl_ids,
        "expected_target_count": 5,
        "actual_target_count": 5,
        "posix_companion_physical_count": 3,
        "unallocated_record_ids": [],
        "failures": [],
        "validated_pass": True,
    }
    if not _same(manifest, expected_manifest):
        failures.append(prefix + "_wsl_target_manifest_invalid")
    drift = payload.get("source_drift")
    if not isinstance(drift, dict) or not _same(drift, {
        "added": [], "modified": [], "removed": [], "unchanged": True
    }):
        failures.append(prefix + "_source_drift_invalid")
    summary = payload.get("delivery_gate_summary")
    if not isinstance(summary, dict):
        return failures + [prefix + "_delivery_summary_invalid"]
    formal = summary.get("formal_field_evidence_gate")
    for key, expected in (
        ("formal_four_scene_frame_denominator", 0),
        ("formal_tf_pass", False), ("formal_3d_pass", False),
        ("formal_latency_pass", False), ("validated_pass", False),
    ):
        if not isinstance(formal, dict) or not _same(formal.get(key), expected):
            failures.append(prefix + "_formal_gate_mismatch:" + key)
    field = summary.get("ros1_field_gate")
    for key, expected in (
        ("source_contract_pass", True),
        ("source_implementation_pass", True),
        ("install_evidence_pass", False), ("validated_pass", False),
    ):
        if not isinstance(field, dict) or not _same(field.get(key), expected):
            failures.append(prefix + "_field_gate_mismatch:" + key)
    canonical = summary.get("ros1_canonical_source_admission_gate")
    if (
        not isinstance(canonical, dict)
        or canonical.get("validated_pass") is not True
        or not _same(
            canonical.get("manifest_identity"),
            spec["canonical_child_identity"],
        )
    ):
        failures.append(prefix + "_canonical_gate_invalid")
    authority = summary.get("evidence_authority_gate")
    if (
        not isinstance(authority, dict)
        or authority.get("current_evidence_id")
        != EMBEDDED_RUNNER_AUTHORITY_EVIDENCE_ID
        or authority.get("authorizes_field_delivery") is not False
        or authority.get("delivery_ready") is not False
    ):
        failures.append(prefix + "_embedded_authority_invalid")
    environment = summary.get("environment_gate")
    if (
        not isinstance(environment, dict)
        or environment.get("source_build_failure") is not False
        or environment.get("active_blockers")
        != ["WSL_E_ACCESSDENIED_BEFORE_SHELL_OR_BUILD"]
    ):
        failures.append(prefix + "_environment_gate_invalid")
    for key, expected in (
        ("delivery_blockers", list(spec["report_blockers"])),
        ("architecture_blockers", []),
        ("field_evidence_blockers", ["ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING"]),
        ("build_install_blockers", ["ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED"]),
        ("formal_field_blockers", [
            "FORMAL_3D_NOT_VALIDATED", "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
            "FORMAL_LATENCY_NOT_VALIDATED", "FORMAL_TF_NOT_VALIDATED",
        ]),
        ("delivery_ready", False),
    ):
        if not _same(summary.get(key), expected):
            failures.append(prefix + "_summary_mismatch:" + key)
    return list(dict.fromkeys(failures))


def _validate_canonical(
    payload: Any, workspace: Path, spec: Mapping[str, Any]
) -> List[str]:
    return [
        value.replace("formal_authority_v2", "formal_authority_v3")
        for value in _v2._validate_canonical_child(payload, workspace, spec)
    ]


def validate_formal_admission_evidence_authority_v3(
    workspace: Path, payload: Any, spec: Mapping[str, Any]
) -> Dict[str, Any]:
    failures = _spec_failures(spec)
    identities: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "authority_id": spec.get("authority_id") if isinstance(spec, dict) else None,
        "index_instance_id": (
            spec.get("index_instance_id") if isinstance(spec, dict) else None
        ),
        "generation_id": spec.get("generation_id") if isinstance(spec, dict) else None,
        "generation_scope": (
            spec.get("generation_scope") if isinstance(spec, dict) else None
        ),
        "validated_pass": False,
        "accepted_as_offline_release_selection_authority": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "formal_latency_pass": False,
        "ros1_noetic_field_install_pass": False,
        "ros1_noetic_build_install_verified": False,
        "ros1_source_implementation_complete": False,
        "ros1_source_architecture_blockers": ["AUTHORITY_NOT_VALIDATED"],
        "current_evidence": None,
        "artifact_identities": identities,
        "failures": failures,
    }
    if failures:
        return result
    expected = expected_index_payload(spec)
    if not isinstance(payload, dict):
        failures.append("formal_authority_v3_payload_invalid")
        return result
    if set(payload) != set(expected):
        failures.append("formal_authority_v3_top_level_keys_invalid")
    for key in set(expected) - {"entries", "child_artifacts"}:
        if not _same(payload.get(key), expected[key]):
            failures.append("formal_authority_v3_top_level_mismatch:" + key)
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != 2:
        failures.append("formal_authority_v3_entry_count_invalid")
        entries = entries if isinstance(entries, list) else []
    by_id: Dict[str, Mapping[str, Any]] = {}
    currents: List[Mapping[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            failures.append("formal_authority_v3_entry_invalid")
            continue
        evidence_id = item.get("evidence_id")
        if evidence_id in by_id:
            failures.append("formal_authority_v3_duplicate_evidence_id")
        if isinstance(evidence_id, str):
            by_id[evidence_id] = item
        if item.get("is_current") is True:
            currents.append(item)
    expected_by_id = {item["evidence_id"]: item for item in expected["entries"]}
    if set(by_id) != set(expected_by_id):
        failures.append("formal_authority_v3_entry_set_invalid")
    for evidence_id, expected_entry in expected_by_id.items():
        if not _same(by_id.get(evidence_id), expected_entry):
            failures.append("formal_authority_v3_entry_mismatch:" + evidence_id)
    if len(currents) != 1:
        failures.append("formal_authority_v3_current_count_invalid")
    elif currents[0].get("evidence_id") != spec["current_evidence_id"]:
        failures.append("formal_authority_v3_current_marker_invalid")
    if not _same(payload.get("child_artifacts"), expected["child_artifacts"]):
        failures.append("formal_authority_v3_child_artifacts_invalid")

    artifacts: Sequence[Tuple[str, Mapping[str, Any], str]] = (
        ("predecessor_index", PREDECESSOR_INDEX_IDENTITY, "predecessor"),
        (SUPERSEDED_REPORT["evidence_id"], SUPERSEDED_REPORT, "superseded"),
        (spec["current_evidence_id"], spec["current_report_identity"], "current"),
        (CANONICAL_CHILD_ID, spec["canonical_child_identity"], "canonical"),
    )
    root = Path(workspace).resolve(strict=True)
    for artifact_id, expected_identity, role in artifacts:
        try:
            unused, identity, raw = _regular_identity(root, expected_identity["path"])
            identity["artifact_id"] = artifact_id
            identities.append(identity)
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v3_artifact_unreadable:" + artifact_id)
            continue
        if identity["size_bytes"] != expected_identity["size_bytes"]:
            failures.append("formal_authority_v3_artifact_size_mismatch:" + artifact_id)
        if identity["sha256"] != expected_identity["sha256"]:
            failures.append("formal_authority_v3_artifact_sha256_mismatch:" + artifact_id)
        try:
            artifact_payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            failures.append("formal_authority_v3_artifact_strict_json_invalid:" + artifact_id)
            continue
        if role == "predecessor":
            failures.extend(_validate_predecessor_index(artifact_payload))
        elif role == "superseded":
            failures.extend(_validate_report(
                artifact_payload, spec, root, current=False
            ))
        elif role == "current":
            failures.extend(_validate_report(
                artifact_payload, spec, root, current=True
            ))
        else:
            failures.extend(_validate_canonical(artifact_payload, root, spec))
    failures[:] = list(dict.fromkeys(failures))
    if not failures:
        result["validated_pass"] = True
        result["accepted_as_offline_release_selection_authority"] = True
        result["ros1_source_implementation_complete"] = True
        result["ros1_source_architecture_blockers"] = []
        result["current_evidence"] = dict(expected["entries"][1])
    return result


def write_index_exclusive(path: Path, payload: Mapping[str, Any]) -> Dict[str, Any]:
    return _v2.write_index_exclusive(path, payload)


def index_identity(workspace: Path, index_relative_path: str) -> Dict[str, Any]:
    return _v2.index_identity(workspace, index_relative_path)


def load_and_resolve_formal_admission_evidence_authority_v3(
    workspace: Path,
    spec: Mapping[str, Any],
    index_trust_anchor: Mapping[str, Any],
) -> Dict[str, Any]:
    root = Path(workspace).resolve(strict=True)
    failures = _spec_failures(spec)
    anchor_failures = _identity_failures(
        index_trust_anchor, "formal_authority_v3_index_anchor"
    )
    failures.extend(anchor_failures)
    if not anchor_failures and index_trust_anchor.get("path") != spec.get(
        "index_relative_path"
    ):
        failures.append("formal_authority_v3_index_anchor_path_mismatch")
    identity: Dict[str, Any] = {}
    raw = b""
    if not failures:
        try:
            unused, identity, raw = _regular_identity(
                root, spec["index_relative_path"]
            )
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v3_index_unreadable")
    if identity and not _same(identity, dict(index_trust_anchor)):
        for key in ("path", "size_bytes", "sha256"):
            if identity.get(key) != index_trust_anchor.get(key):
                failures.append("formal_authority_v3_index_" + key + "_mismatch")
    try:
        payload = _strict_json_bytes(raw) if raw else None
    except (UnicodeError, ValueError, json.JSONDecodeError):
        failures.append("formal_authority_v3_index_strict_json_invalid")
        payload = None
    validation = validate_formal_admission_evidence_authority_v3(
        root, payload, spec
    )
    for failure in failures:
        _append(validation["failures"], failure)
    if validation["failures"]:
        validation["validated_pass"] = False
        validation["accepted_as_offline_release_selection_authority"] = False
        validation["ros1_source_implementation_complete"] = False
        validation["ros1_source_architecture_blockers"] = [
            "AUTHORITY_NOT_VALIDATED"
        ]
        validation["current_evidence"] = None
    validation["index_identity"] = identity
    validation["expected_index_identity"] = dict(index_trust_anchor)
    validation["index_relative_path"] = spec.get("index_relative_path")
    validation["filename_mtime_selection_forbidden"] = True
    validation["candidate_not_activated_without_external_anchor"] = True
    return validation


def load_and_resolve_successor_authority(
    index_trust_anchor: Mapping[str, Any],
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve the successor only through a caller-supplied external anchor."""
    return load_and_resolve_formal_admission_evidence_authority_v3(
        workspace, successor_generation_spec(), index_trust_anchor
    )


def load_and_resolve_current_authority(
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve the activated successor, or fail while its anchor is unset."""
    if not isinstance(PRODUCTION_INDEX_TRUST_ANCHOR, dict):
        result = load_and_resolve_formal_admission_evidence_authority_v3(
            workspace, successor_generation_spec(), {}
        )
        _append(
            result["failures"],
            "formal_authority_v3_production_anchor_not_configured",
        )
        result["validated_pass"] = False
        result["accepted_as_offline_release_selection_authority"] = False
        result["current_evidence"] = None
        result["production_anchor_configured"] = False
        return result
    result = load_and_resolve_formal_admission_evidence_authority_v3(
        workspace,
        successor_generation_spec(),
        PRODUCTION_INDEX_TRUST_ANCHOR,
    )
    result["production_anchor_configured"] = True
    return result
