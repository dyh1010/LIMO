"""Strict BLOCKED_OFFLINE authority validator for the camera-runtime generation.

This module deliberately contains no production index bytes/SHA-256 anchor.
The final index is selected only by the separate production wrapper through an
externally frozen path/size/SHA-256 identity.  Validation here can grant only
offline release-evidence selection.  It can never grant ROS1/Noetic runtime,
build/install, formal-field, camera, inference, motion, or delivery authority.

The generation is intentionally self-contained: an externally anchored index
binds the report, canonical source artifact, and every required source role;
the validator reopens every bound file, statically enumerates all 155 logical
test IDs, and recomputes the nine physical execution records (263 executions).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "ros1_formal_admission_evidence_authority/v4"
CANONICAL_SCHEMA_VERSION = "ros1_blocked_offline_canonical_source/v1"
REPORT_SCHEMA_VERSION = "ros1_blocked_offline_regression_report/v1"
AUTHORITY_FAMILY_ID = "ros1-formal-admission-evidence-authority-20260815-v2"
INDEX_INSTANCE_ID = (
    "ros1-formal-admission-evidence-authority-index-20260815-v5-blocked-offline"
)
GENERATION_ID = "ros1_camera_runtime_install_blocked_offline_20260815_v5"
GENERATION_SCOPE = (
    "blocked_offline_camera_runtime_install_not_field_or_delivery"
)
CURRENT_EVIDENCE_ID = (
    "ros1_camera_runtime_install_blocked_offline_regression_20260815_v5"
)
CURRENT_STATUS = "CURRENT_BLOCKED_OFFLINE"
CANONICAL_ID = "ros1-noetic-canonical-source-admission-20260815-v6-blocked-offline"
CANONICAL_ARTIFACT_ID = (
    "ros1_noetic_canonical_source_admission_20260815_v6_blocked_offline"
)
REPORT_ID = "ros1-camera-runtime-install-blocked-offline-report-20260815-v5"
SELECTION_AUTHORITY = (
    "EXTERNAL_FIXED_INDEX_PATH_SIZE_SHA256_STRICT_JSON_AND_HOST_RECOMPUTE"
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
INDEX_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_"
    "v5_blocked_offline.json"
)
REPORT_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_camera_runtime_install_"
    "blocked_offline_v5.json"
)
CANONICAL_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_noetic_canonical_source_admission_20260815_"
    "v6_blocked_offline.json"
)

PREDECESSOR_INDEX_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_v4.json"
    ),
    "size_bytes": 5015,
    "sha256": "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded",
    "authority_id": AUTHORITY_FAMILY_ID,
    "index_instance_id": (
        "ros1-formal-admission-evidence-authority-index-20260815-v4"
    ),
    "generation_id": "ros1_runner_platform_composite_20260815_v4",
    "current_evidence_id": (
        "ros1_runner_platform_composite_offline_regression_20260815_v4"
    ),
}

PREDECESSOR_REPORT_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_runner_platform_composite_v4.json"
    ),
    "size_bytes": 1288709,
    "sha256": "dfa7e3f8c53f6157fec5083b26b8fc87b3115dcfb9eb6fbbde2fbcf52775c5be",
}

PREDECESSOR_CANONICAL_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_noetic_canonical_source_admission_20260815_v5.json"
    ),
    "size_bytes": 9889,
    "sha256": "1c4a9c2901cae292803cec4a700550c2054a26b94e1ae89aacbedb3865e7801a",
}

LIVE_OVERLAY_ROOT = "ros1_overlay_src/limo_cleanup_ros1_perception"
LIVE_OVERLAY_FILE_COUNT = 51
LIVE_OVERLAY_CONTRACT_SHA256 = (
    "808abf42856856d8b79a232c60d83a7ca777e681cdb1eaef8a251cddcb6f5abc"
)
LIVE_OVERLAY_SOURCE_SET_SHA256 = (
    "2850f25cdac82e4759a40753db49677d3abe3b881814cf8d1f3e30299523d54e"
)
LIVE_OVERLAY_BINDING_SHA256 = (
    "742231c30627b5209dd26e5243b1cbed5dca4f5d29bae67363f06560ee658b0d"
)
REQUIRED_LIVE_OVERLAY_PATHS = (
    "config/dabai_ros1_formal_four_scene_six_topics_v1.json",
    "config/dabai_ros1_raw_rgbd_six_topics_v1.json",
    "launch/perception_v2_formal_capture.launch",
    "scripts/rosbag1_rgbd_indexer.py",
)

# The wrapper is intentionally excluded.  It is the external trust root that
# receives the final index anchor after this canonical artifact is frozen.
EXTERNAL_TRUST_ROOT_EXCLUSIONS = (
    "audit_tools/formal_admission_evidence_authority_v4.py",
)

REQUIRED_SOURCE_ROLE_PATHS: Tuple[Tuple[str, str], ...] = (
    ("camera_runtime_import_probe", "audit_tools/ros1_camera_runtime_import_probe.py"),
    ("camera_runtime_import_probe_test", "audit_tools/test_ros1_camera_runtime_import_probe.py"),
    ("camera_runtime_install_admission", "audit_tools/ros1_camera_runtime_install_admission.py"),
    ("camera_runtime_install_admission_test", "audit_tools/test_ros1_camera_runtime_install_admission.py"),
    ("camera_only_atomic_launcher", "audit_tools/ros1_camera_only_atomic_launcher.py"),
    ("camera_only_atomic_launcher_test", "audit_tools/test_ros1_camera_only_atomic_launcher.py"),
    ("camera_only_field_preflight", "audit_tools/ros1_camera_only_field_preflight.py"),
    ("camera_only_field_preflight_test", "audit_tools/test_ros1_camera_only_field_preflight.py"),
    ("camera_only_operator_docs", "audit_tools/ros1_camera_only_operator_docs.py"),
    ("camera_only_operator_docs_test", "audit_tools/test_ros1_camera_only_operator_docs.py"),
    ("dabai_runtime_contract_test", "src/limo_cleanup_perception/test/test_ros1_dabai_runtime_contract.py"),
    ("dabai_runtime_contract_fixture", "src/limo_cleanup_perception/fixtures/ros1_dabai_runtime_contract.json"),
    ("unittest_isolated_runner", "audit_tools/run_unittest_file_tests.py"),
    ("pytest_style_isolated_runner", "audit_tools/run_pytest_style_tests.py"),
    ("blocked_offline_evidence_generator", "audit_tools/generate_ros1_camera_runtime_blocked_offline_evidence.py"),
    ("blocked_offline_authority_core", "audit_tools/formal_admission_evidence_authority_v4_core.py"),
    ("blocked_offline_authority_test", "audit_tools/test_formal_admission_evidence_authority_v4.py"),
    ("field_runbook", "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md"),
    ("hardware_readiness_document", "docs/hardware_readiness.md"),
    ("real_perception_document", "docs/real_perception.md"),
    ("manual_reference_document", "docs/limo_pro_manual_reference.md"),
    ("field_readiness_runbook", "docs/PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md"),
    ("dabai_sensor_readme", "src/limo_cleanup_dabai_sensor/README.md"),
    ("retired_dabai_start_script", "scripts/start_dabai_camera.sh"),
    ("predecessor_authority_index", PREDECESSOR_INDEX_IDENTITY["path"]),
    ("predecessor_regression_report", PREDECESSOR_REPORT_IDENTITY["path"]),
    ("predecessor_canonical_source", PREDECESSOR_CANONICAL_IDENTITY["path"]),
    ("historical_runner_platform_diagnostic_v2", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_diagnostic_v2.json"),
    ("historical_canonical_source_binding_v6", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6.json"),
    ("historical_canonical_source_binding_v6_final", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6_final.json"),
    ("historical_canonical_source_binding_v7", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json"),
    ("archived_dabai_launch_reference", "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch"),
    ("predecessor_authority_resolver", "audit_tools/formal_admission_evidence_authority_v3.py"),
    ("startup_screenshot_roslaunch", "evidence/perception_v2_field_20260814/user_startup_screenshots/01_roslaunch_dabai_u3.png"),
    ("startup_screenshot_rqt_command", "evidence/perception_v2_field_20260814/user_startup_screenshots/02_rqt_image_view_command.png"),
    ("startup_screenshot_rqt_stream", "evidence/perception_v2_field_20260814/user_startup_screenshots/03_rqt_color_stream.png"),
    ("diagnostic_shared_graph_bag", "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag"),
    ("diagnostic_shared_graph_manifest", "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.diagnostic-manifest-v3.json"),
    ("diagnostic_shared_graph_formal_gate", "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.formal-gate-v3.json"),
)

FROZEN_REQUIRED_SOURCE_IDENTITIES: Mapping[str, Mapping[str, Any]] = {
    PREDECESSOR_INDEX_IDENTITY["path"]: {
        key: PREDECESSOR_INDEX_IDENTITY[key]
        for key in ("path", "size_bytes", "sha256")
    },
    PREDECESSOR_REPORT_IDENTITY["path"]: dict(PREDECESSOR_REPORT_IDENTITY),
    PREDECESSOR_CANONICAL_IDENTITY["path"]: dict(PREDECESSOR_CANONICAL_IDENTITY),
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_diagnostic_v2.json": {
        "path": "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_diagnostic_v2.json",
        "size_bytes": 1212313,
        "sha256": "fdeffd18244633ccc7e9407dafa606a2799f03fb517be5b11c881aff8d146548",
    },
    "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch": {
        "path": "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch",
        "size_bytes": 6446,
        "sha256": "75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e",
    },
    "evidence/perception_v2_field_20260814/user_startup_screenshots/01_roslaunch_dabai_u3.png": {
        "path": "evidence/perception_v2_field_20260814/user_startup_screenshots/01_roslaunch_dabai_u3.png",
        "size_bytes": 250085,
        "sha256": "64e0132c70931f179d2fd70ff49821e5e24bb16f8ecfdb3ad79054a3d353e7eb",
    },
    "evidence/perception_v2_field_20260814/user_startup_screenshots/02_rqt_image_view_command.png": {
        "path": "evidence/perception_v2_field_20260814/user_startup_screenshots/02_rqt_image_view_command.png",
        "size_bytes": 121298,
        "sha256": "b7905a55dd7ca3476549988990569d7d56c0c633e4f5ba81a906c9544cfbcf28",
    },
    "evidence/perception_v2_field_20260814/user_startup_screenshots/03_rqt_color_stream.png": {
        "path": "evidence/perception_v2_field_20260814/user_startup_screenshots/03_rqt_color_stream.png",
        "size_bytes": 653709,
        "sha256": "d7c85560946b2aa8938b10214f8d7cab29bd6a016cb1823cc1cb3a2bf2e78188",
    },
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag": {
        "path": "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag",
        "size_bytes": 81634393,
        "sha256": "31a9c280aaa8d1ce6f1836bb9a445eafd87fbc5b096967932484c2f4c6982168",
    },
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.diagnostic-manifest-v3.json": {
        "path": "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.diagnostic-manifest-v3.json",
        "size_bytes": 6989444,
        "sha256": "4683b682b908a2325232aa604a3b7e6367dd0404a84baf0013d159ab8da7e08f",
    },
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.formal-gate-v3.json": {
        "path": "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.formal-gate-v3.json",
        "size_bytes": 1661,
        "sha256": "678e51ac185605471f4ec68d2ce67ffcf680f65704aba6567ec12d6014c63966",
    },
    "audit_tools/formal_admission_evidence_authority_v3.py": {
        "path": "audit_tools/formal_admission_evidence_authority_v3.py",
        "size_bytes": 76863,
        "sha256": "ef8fa135d2b1ec8f6ef906975732961ff717af9e9c603fc072f8b1a5959c5f39",
    },
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6.json": {
        "path": "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6.json",
        "size_bytes": 188673,
        "sha256": "d2cb327499c79cd6f90f1ac7f72a9edb52dac85d08cb8dc563d1e078776b6239",
    },
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6_final.json": {
        "path": "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6_final.json",
        "size_bytes": 189637,
        "sha256": "dd7290195cdd6776eb8d8e6d8db4c4cbeb8b87f49be760b7c39fdc9392181a87",
    },
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json": {
        "path": "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json",
        "size_bytes": 190747,
        "sha256": "dac31ed678ff7c3a8f4494c5b865f89a41715ee5555e80ef12a8ba4b895f6789",
    },
}

HISTORICAL_DIAGNOSTIC_SOURCE_PATHS = frozenset({
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_diagnostic_v2.json",
    "evidence/perception_v2_field_20260814/user_startup_screenshots/01_roslaunch_dabai_u3.png",
    "evidence/perception_v2_field_20260814/user_startup_screenshots/02_rqt_image_view_command.png",
    "evidence/perception_v2_field_20260814/user_startup_screenshots/03_rqt_color_stream.png",
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag",
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.diagnostic-manifest-v3.json",
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/v2_ros1_shared_graph_diagnostic_20260814T052442Z.formal-gate-v3.json",
})

FROZEN_REFERENCE_SOURCE_PATHS = frozenset({
    PREDECESSOR_INDEX_IDENTITY["path"],
    PREDECESSOR_REPORT_IDENTITY["path"],
    PREDECESSOR_CANONICAL_IDENTITY["path"],
    "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch",
    "audit_tools/formal_admission_evidence_authority_v3.py",
})

FROZEN_HISTORICAL_SOURCE_PATHS = frozenset({
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6.json",
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v6_final.json",
    "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json",
})

LOGICAL_SUITE_DEFINITIONS: Tuple[Tuple[str, str, str, int], ...] = (
    ("camera_runtime_import_probe", "audit_tools/test_ros1_camera_runtime_import_probe.py", "audit_tools/run_unittest_file_tests.py", 26),
    ("camera_runtime_install_admission", "audit_tools/test_ros1_camera_runtime_install_admission.py", "audit_tools/run_unittest_file_tests.py", 40),
    ("camera_only_atomic_launcher", "audit_tools/test_ros1_camera_only_atomic_launcher.py", "audit_tools/run_unittest_file_tests.py", 42),
    ("camera_only_field_preflight", "audit_tools/test_ros1_camera_only_field_preflight.py", "audit_tools/run_unittest_file_tests.py", 18),
    ("camera_only_operator_docs", "audit_tools/test_ros1_camera_only_operator_docs.py", "audit_tools/run_unittest_file_tests.py", 24),
    ("dabai_runtime_contract", "src/limo_cleanup_perception/test/test_ros1_dabai_runtime_contract.py", "audit_tools/run_pytest_style_tests.py", 5),
)
LOGICAL_EXPECTED_TOTAL = 155

PHYSICAL_EXECUTION_DEFINITIONS: Tuple[Tuple[str, str, str, str, int], ...] = (
    ("probe_posix_python3", "camera_runtime_import_probe", "POSIX_WSL", "system_python3_entry", 26),
    ("probe_posix_python314", "camera_runtime_import_probe", "POSIX_WSL", "system_python314_target", 26),
    ("install_posix_python3", "camera_runtime_install_admission", "POSIX_WSL", "system_python3_entry", 40),
    ("install_posix_python314", "camera_runtime_install_admission", "POSIX_WSL", "system_python314_target", 40),
    ("atomic_posix_python3", "camera_only_atomic_launcher", "POSIX_WSL", "system_python3_entry", 42),
    ("atomic_posix_python314", "camera_only_atomic_launcher", "POSIX_WSL", "system_python314_target", 42),
    ("preflight_posix_python314", "camera_only_field_preflight", "POSIX_WSL", "system_python314_target", 18),
    ("operator_docs_posix_python314", "camera_only_operator_docs", "POSIX_WSL", "system_python314_target", 24),
    ("runtime_contract_posix_python314", "dabai_runtime_contract", "POSIX_WSL", "system_python314_target", 5),
)
PHYSICAL_EXPECTED_TOTAL = 263

PYTHON314_TARGET_IDENTITY: Mapping[str, Any] = {
    "path": "/usr/bin/python3.14",
    "size_bytes": 7477096,
    "sha256": "fa9796cd3a30878e11a2f40372f773d3fcd913fff35e5bee8dd9a036e22e93ab",
}
PYTHON314_VERSION = [3, 14, 4]
CHILD_ENVIRONMENT: Mapping[str, str] = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}

BLOCKERS: Tuple[str, ...] = (
    "BLOCKED_OFFLINE_RELEASE_SELECTION_ONLY",
    "CAMERA_RUNTIME_IMPORT_PRODUCTION_SPEC_NOT_BOUND",
    "CAMERA_RUNTIME_INSTALL_ADMISSION_NOT_BOUND",
    "FORMAL_3D_NOT_VALIDATED",
    "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
    "FORMAL_LATENCY_NOT_VALIDATED",
    "FORMAL_TF_NOT_VALIDATED",
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
    "production_cli_failure_code": (
        "ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
        "camera_runtime_install_admission_not_bound"
    ),
}

GATE_STATE: Mapping[str, Any] = {
    "active_blockers": list(BLOCKERS),
    "offline_logical_matrix_passed": True,
    "offline_physical_matrix_passed": True,
    "regression_passed": False,
    "ros1_source_implementation_complete": True,
    "ros1_noetic_runtime_verified": False,
    "ros1_noetic_build_install_verified": False,
    "ros1_noetic_field_install_pass": False,
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
    required_source_roles: Tuple[Tuple[str, str], ...] = REQUIRED_SOURCE_ROLE_PATHS
    live_overlay_file_count: int = LIVE_OVERLAY_FILE_COUNT
    live_overlay_contract_sha256: str = LIVE_OVERLAY_CONTRACT_SHA256
    live_overlay_source_set_sha256: str = LIVE_OVERLAY_SOURCE_SET_SHA256
    live_overlay_binding_sha256: str = LIVE_OVERLAY_BINDING_SHA256


PRODUCTION_POLICY = AuthorityPolicy()


def _same(actual: Any, expected: Any) -> bool:
    """Recursively compare JSON material with exact Python scalar types."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            set(actual) == set(expected)
            and all(_same(actual[key], expected[key]) for key in expected)
        )
    if isinstance(expected, (list, tuple)):
        return (
            len(actual) == len(expected)
            and all(_same(left, right) for left, right in zip(actual, expected))
        )
    return actual == expected


def _append(failures: List[str], value: str) -> None:
    if value not in failures:
        failures.append(value)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant: " + value)


def _strict_json_bytes(raw: bytes) -> Any:
    def pairs(values: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    text = raw.decode("utf-8")
    return json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=_reject_constant,
    )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and str(path) == value
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def _is_linklike(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _regular_identity(
    workspace: Path, relative: str
) -> Tuple[Path, Dict[str, Any], bytes]:
    if not _safe_relative(relative):
        raise ValueError("unsafe relative path")
    root = Path(workspace).resolve(strict=True)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        info = os.lstat(str(current))
        if _is_linklike(info):
            raise ValueError("linklike path component")
        if part != PurePosixPath(relative).parts[-1] and not stat.S_ISDIR(
            info.st_mode
        ):
            raise ValueError("non-directory parent")
    info = os.lstat(str(current))
    if _is_linklike(info) or not stat.S_ISREG(info.st_mode):
        raise ValueError("artifact is not a regular non-link file")
    if getattr(info, "st_nlink", 1) != 1:
        raise ValueError("artifact is hardlinked")
    raw = current.read_bytes()
    after = os.lstat(str(current))
    if (
        _is_linklike(after)
        or not stat.S_ISREG(after.st_mode)
        or getattr(after, "st_nlink", 1) != 1
        or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    ):
        raise ValueError("artifact changed while reading")
    return current, {
        "path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, raw


def artifact_identity(workspace: Path, relative: str) -> Dict[str, Any]:
    unused, identity, unused_raw = _regular_identity(workspace, relative)
    return identity


def _identity_failures(identity: Any, prefix: str) -> List[str]:
    if not isinstance(identity, dict) or set(identity) != {
        "path", "size_bytes", "sha256"
    }:
        return [prefix + "_identity_schema_invalid"]
    failures: List[str] = []
    if not _safe_relative(identity.get("path")):
        failures.append(prefix + "_path_invalid")
    if type(identity.get("size_bytes")) is not int or identity["size_bytes"] <= 0:
        failures.append(prefix + "_size_bytes_invalid")
    if not _valid_sha256(identity.get("sha256")):
        failures.append(prefix + "_sha256_invalid")
    return failures


def _policy_failures(policy: Any) -> List[str]:
    if not isinstance(policy, AuthorityPolicy):
        return ["formal_authority_v4_policy_invalid"]
    failures: List[str] = []
    for key in (
        "index_relative_path", "report_relative_path", "canonical_relative_path"
    ):
        if not _safe_relative(getattr(policy, key)):
            failures.append("formal_authority_v4_policy_path_invalid:" + key)
    if len({policy.index_relative_path, policy.report_relative_path,
            policy.canonical_relative_path}) != 3:
        failures.append("formal_authority_v4_policy_path_collision")
    roles = policy.required_source_roles
    if (
        not isinstance(roles, tuple)
        or not roles
        or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or not _safe_relative(item[1])
            for item in roles
        )
    ):
        failures.append("formal_authority_v4_policy_source_roles_invalid")
    elif (
        len({item[0] for item in roles}) != len(roles)
        or len({item[1] for item in roles}) != len(roles)
    ):
        failures.append("formal_authority_v4_policy_source_roles_duplicate")
    if type(policy.live_overlay_file_count) is not int or policy.live_overlay_file_count <= 0:
        failures.append("formal_authority_v4_policy_overlay_count_invalid")
    for key in (
        "live_overlay_contract_sha256",
        "live_overlay_source_set_sha256",
        "live_overlay_binding_sha256",
    ):
        if not _valid_sha256(getattr(policy, key)):
            failures.append("formal_authority_v4_policy_hash_invalid:" + key)
    return failures


def collect_source_role_bindings(
    workspace: Path, policy: AuthorityPolicy = PRODUCTION_POLICY
) -> List[Dict[str, Any]]:
    failures = _policy_failures(policy)
    if failures:
        raise ValueError(",".join(failures))
    records: List[Dict[str, Any]] = []
    for role, relative in policy.required_source_roles:
        identity = artifact_identity(workspace, relative)
        identity["role"] = role
        records.append(identity)
    records.sort(key=lambda item: item["path"])
    return records


def _source_role_set_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    return _canonical_sha256(list(records))


def source_role_dispositions(
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> List[Dict[str, Any]]:
    """Return the one-to-one machine disposition for every source role."""
    values: List[Dict[str, Any]] = []
    for role, path in policy.required_source_roles:
        if path in HISTORICAL_DIAGNOSTIC_SOURCE_PATHS:
            disposition = "HISTORICAL_DIAGNOSTIC_NOT_FORMAL_NOT_IN_DENOMINATOR"
            denominator_use = "NOT_IN_DENOMINATOR"
        elif path in FROZEN_HISTORICAL_SOURCE_PATHS:
            disposition = "HISTORICAL_REGRESSION_NOT_CANONICAL"
            denominator_use = "NOT_IN_DENOMINATOR"
        elif path in FROZEN_REFERENCE_SOURCE_PATHS:
            disposition = "FROZEN_REFERENCE_ANCHOR"
            denominator_use = "NOT_IN_DENOMINATOR"
        else:
            disposition = "BOUND_SOURCE"
            denominator_use = "SOURCE_ROLE_ONLY"
        values.append({
            "path": path,
            "role": role,
            "disposition": disposition,
            "denominator_use": denominator_use,
        })
    values.sort(key=lambda item: item["path"])
    return values


def _collect_overlay_entries(workspace: Path) -> List[Dict[str, Any]]:
    root = Path(workspace).resolve(strict=True)
    package = root / LIVE_OVERLAY_ROOT
    entries: List[Dict[str, Any]] = []
    excluded = {"config/source_core_binding.json"}
    for path in package.rglob("*"):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(package).as_posix()
        if relative in excluded:
            continue
        source_relative = LIVE_OVERLAY_ROOT + "/" + relative
        identity = artifact_identity(root, source_relative)
        entries.append({
            "path": relative,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        })
    entries.sort(key=lambda item: item["path"])
    return entries


def collect_live_overlay_binding(
    workspace: Path, policy: AuthorityPolicy = PRODUCTION_POLICY
) -> Dict[str, Any]:
    entries = _collect_overlay_entries(workspace)
    binding: Dict[str, Any] = {
        "schema_version": 1,
        "binding_kind": "canonical_project_overlay",
        "test_only": False,
        "canonical_source_root": LIVE_OVERLAY_ROOT,
        "contract_sha256": policy.live_overlay_contract_sha256,
        "source_set_sha256": _canonical_sha256(entries),
        "file_count": len(entries),
        "entries": entries,
        "source_contract_pass": True,
        "indexer_only_detected": False,
        "architecture_blockers": [],
    }
    binding["binding_sha256"] = _canonical_sha256(binding)
    return binding


def build_canonical_payload(
    workspace: Path,
    source_roles: Sequence[Mapping[str, Any]],
    source_role_dispositions_value: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    expected_dispositions = source_role_dispositions(policy)
    if not _same(list(source_role_dispositions_value), expected_dispositions):
        raise ValueError("source role disposition mismatch")
    live = collect_live_overlay_binding(workspace, policy)
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
        "live_overlay_binding": live,
        "live_overlay_attestation": {
            "binding_recompute_authority": (
                "HOST_OWNED_PURE_STDLIB_EXACT_FILE_CLOSURE"
            ),
            "production_factory_executed": False,
            "ambient_numpy_required": False,
        },
        "source_roles": list(source_roles),
        "source_role_count": len(source_roles),
        "source_role_set_sha256": _source_role_set_sha256(source_roles),
        "source_role_dispositions": expected_dispositions,
        "source_role_disposition_sha256": _canonical_sha256(expected_dispositions),
        "external_trust_root_exclusions": list(EXTERNAL_TRUST_ROOT_EXCLUSIONS),
        "blockers": list(BLOCKERS),
        "accepted_by_formal_field_evidence_consumer": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    payload["artifact_binding_sha256"] = _canonical_sha256(payload)
    return payload


def _static_test_ids(workspace: Path, relative: str) -> List[str]:
    unused, unused_identity, raw = _regular_identity(workspace, relative)
    tree = ast.parse(raw.decode("utf-8"), filename=relative, feature_version=8)
    case_ids: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            children: Iterable[Any] = (node,)
            class_name = None
        elif isinstance(node, ast.ClassDef):
            children = node.body
            class_name = node.name
        else:
            continue
        for child in children:
            if (
                not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                or not child.name.startswith("test_")
            ):
                continue
            suffix = child.name if class_name is None else class_name + "." + child.name
            case_ids.append(relative + "::" + suffix)
    case_ids.sort()
    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("zero or duplicate static test IDs")
    return case_ids


def logical_suite_records(
    workspace: Path, source_roles: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    by_path = {item.get("path"): item for item in source_roles}
    records: List[Dict[str, Any]] = []
    for suite_id, test_path, runner_path, expected_count in LOGICAL_SUITE_DEFINITIONS:
        ids = _static_test_ids(workspace, test_path)
        if len(ids) != expected_count:
            raise ValueError("logical suite test count mismatch: " + suite_id)
        records.append({
            "suite_id": suite_id,
            "test_artifact_identity": {
                key: by_path[test_path][key]
                for key in ("path", "size_bytes", "sha256")
            },
            "runner_artifact_identity": {
                key: by_path[runner_path][key]
                for key in ("path", "size_bytes", "sha256")
            },
            "expected_test_ids": ids,
            "executed_test_ids": list(ids),
            "expected": expected_count,
            "collected": expected_count,
            "passed": expected_count,
            "failed": 0,
            "skipped": 0,
        })
    return records


def _expected_interpreter_identity(role: str) -> Dict[str, Any]:
    if role == "system_python3_entry":
        return {
            "entry_path": "/usr/bin/python3",
            "entry_is_symlink": True,
            "entry_link_chain": [{
                "path": "/usr/bin/python3",
                "link_text": "python3.14",
                "next_path": "/usr/bin/python3.14",
                "lstat_size_bytes": 10,
            }],
            "resolved_target": dict(PYTHON314_TARGET_IDENTITY),
        }
    if role == "system_python314_target":
        return {
            "entry_path": "/usr/bin/python3.14",
            "entry_is_symlink": False,
            "entry_link_chain": [],
            "resolved_target": dict(PYTHON314_TARGET_IDENTITY),
        }
    raise ValueError("unknown interpreter role")


def _interpreter_failures(value: Any, role: str, prefix: str) -> List[str]:
    try:
        expected = _expected_interpreter_identity(role)
    except ValueError:
        return [prefix + "_interpreter_role_invalid"]
    if not isinstance(value, dict) or set(value) != set(expected):
        return [prefix + "_interpreter_identity_invalid"]
    if not _same(value, expected):
        return [prefix + "_interpreter_identity_mismatch"]
    return []


def _execution_workspace_path(workspace: Path) -> str:
    root = Path(workspace).resolve(strict=True)
    if os.name != "nt":
        return str(root)
    drive, tail = os.path.splitdrive(str(root))
    if len(drive) != 2 or drive[1] != ":":
        raise ValueError("workspace cannot be mapped to WSL")
    parts = [item for item in tail.replace("\\", "/").split("/") if item]
    return str(PurePosixPath("/mnt", drive[0].lower(), *parts))


def _stream_identity(raw: bytes) -> Dict[str, Any]:
    return {
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_report_payload(
    workspace: Path,
    canonical_identity: Mapping[str, Any],
    source_roles: Sequence[Mapping[str, Any]],
    physical_execution_records: Sequence[Mapping[str, Any]],
    production_cli_observation: Mapping[str, Any],
) -> Dict[str, Any]:
    logical = logical_suite_records(workspace, source_roles)
    physical = [dict(item) for item in physical_execution_records]
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
            "logical_suite_records": logical,
            "logical_expected_total": LOGICAL_EXPECTED_TOTAL,
            "logical_collected": LOGICAL_EXPECTED_TOTAL,
            "logical_passed": LOGICAL_EXPECTED_TOTAL,
            "logical_failed": 0,
            "logical_skipped": 0,
            "physical_execution_records": physical,
            "physical_expected_total": PHYSICAL_EXPECTED_TOTAL,
            "physical_collected": PHYSICAL_EXPECTED_TOTAL,
            "physical_passed": PHYSICAL_EXPECTED_TOTAL,
            "physical_failed": 0,
            "physical_skipped": 0,
            "failures": [],
        },
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "production_cli_observation": dict(production_cli_observation),
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
    report_identity: Mapping[str, Any],
    canonical_identity: Mapping[str, Any],
    source_roles: Sequence[Mapping[str, Any]],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    for identity, expected_path, label in (
        (report_identity, policy.report_relative_path, "report"),
        (canonical_identity, policy.canonical_relative_path, "canonical"),
    ):
        failures = _identity_failures(identity, "formal_authority_v4_" + label)
        if failures or identity.get("path") != expected_path:
            raise ValueError("invalid " + label + " identity")
    current_entry = {
        "evidence_id": CURRENT_EVIDENCE_ID,
        "report_id": REPORT_ID,
        "generation_id": GENERATION_ID,
        "status": CURRENT_STATUS,
        "lifecycle": "CURRENT",
        "is_current": True,
        "predecessor_evidence_id": PREDECESSOR_INDEX_IDENTITY["current_evidence_id"],
        "report_kind": "perception_v2_blocked_offline_regression",
        **dict(report_identity),
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    old_entry = {
        "evidence_id": PREDECESSOR_INDEX_IDENTITY["current_evidence_id"],
        "generation_id": PREDECESSOR_INDEX_IDENTITY["generation_id"],
        "status": "SUPERSEDED_NON_CURRENT_PREDECESSOR",
        "lifecycle": "SUPERSEDED",
        "is_current": False,
        "predecessor_evidence_id": (
            "ros1_delivery_blocker_layering_offline_regression_20260815_v3"
        ),
        "superseded_by_evidence_id": CURRENT_EVIDENCE_ID,
        "report_kind": "perception_v2_frozen_offline_regression",
        **dict(PREDECESSOR_REPORT_IDENTITY),
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
        "predecessor_authority_index": dict(PREDECESSOR_INDEX_IDENTITY),
        "entries": [old_entry, current_entry],
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


def _validate_predecessor_payload(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return ["formal_authority_v4_predecessor_payload_invalid"]
    failures: List[str] = []
    for key in (
        "authority_id", "index_instance_id", "generation_id", "current_evidence_id"
    ):
        if payload.get(key) != PREDECESSOR_INDEX_IDENTITY[key]:
            failures.append("formal_authority_v4_predecessor_semantic_mismatch:" + key)
    currents = [
        item for item in payload.get("entries", [])
        if isinstance(item, dict) and item.get("is_current") is True
    ] if isinstance(payload.get("entries"), list) else []
    if len(currents) != 1:
        failures.append("formal_authority_v4_predecessor_current_count_invalid")
    elif currents[0].get("evidence_id") != PREDECESSOR_INDEX_IDENTITY["current_evidence_id"]:
        failures.append("formal_authority_v4_predecessor_current_mismatch")
    return failures


def _validate_source_roles(
    workspace: Path,
    value: Any,
    policy: AuthorityPolicy,
) -> Tuple[List[str], Dict[str, Mapping[str, Any]]]:
    failures: List[str] = []
    if not isinstance(value, list):
        return ["formal_authority_v4_source_roles_invalid"], {}
    expected = {path: role for role, path in policy.required_source_roles}
    by_path: Dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {
            "role", "path", "size_bytes", "sha256"
        }:
            failures.append("formal_authority_v4_source_role_invalid:" + str(index))
            continue
        path = item.get("path")
        if not isinstance(path, str):
            failures.append("formal_authority_v4_source_role_path_invalid:" + str(index))
            continue
        if path in by_path:
            failures.append("formal_authority_v4_source_role_duplicate:" + str(path))
            continue
        by_path[path] = item
        if expected.get(path) != item.get("role"):
            failures.append("formal_authority_v4_source_role_name_mismatch:" + str(path))
        identity = {key: item.get(key) for key in ("path", "size_bytes", "sha256")}
        failures.extend(_identity_failures(
            identity, "formal_authority_v4_source_role:" + str(path)
        ))
        try:
            actual = artifact_identity(workspace, path)
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v4_source_role_unreadable:" + str(path))
            continue
        if actual != identity:
            failures.append("formal_authority_v4_source_role_identity_mismatch:" + str(path))
        frozen = FROZEN_REQUIRED_SOURCE_IDENTITIES.get(path)
        if frozen is not None and identity != frozen:
            failures.append("formal_authority_v4_frozen_source_identity_mismatch:" + str(path))
    if set(by_path) != set(expected):
        failures.append("formal_authority_v4_source_role_set_invalid")
    if value != sorted(
        value,
        key=lambda item: (
            item.get("path")
            if isinstance(item, dict) and isinstance(item.get("path"), str)
            else "\uffff"
        ),
    ):
        failures.append("formal_authority_v4_source_role_order_invalid")
    return failures, by_path


def _validate_live_overlay(
    workspace: Path, payload: Any, policy: AuthorityPolicy
) -> List[str]:
    expected_keys = {
        "schema_version", "binding_kind", "test_only", "canonical_source_root",
        "contract_sha256", "source_set_sha256", "file_count", "entries",
        "source_contract_pass", "indexer_only_detected", "architecture_blockers",
        "binding_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return ["formal_authority_v4_live_overlay_schema_invalid"]
    failures: List[str] = []
    for key, expected in (
        ("schema_version", 1),
        ("binding_kind", "canonical_project_overlay"),
        ("test_only", False),
        ("canonical_source_root", LIVE_OVERLAY_ROOT),
        ("contract_sha256", policy.live_overlay_contract_sha256),
        ("source_set_sha256", policy.live_overlay_source_set_sha256),
        ("file_count", policy.live_overlay_file_count),
        ("source_contract_pass", True),
        ("indexer_only_detected", False),
        ("architecture_blockers", []),
        ("binding_sha256", policy.live_overlay_binding_sha256),
    ):
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v4_live_overlay_mismatch:" + key)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return failures + ["formal_authority_v4_live_overlay_entries_invalid"]
    seen = set()
    canonical_entries: List[Dict[str, Any]] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            failures.append("formal_authority_v4_live_overlay_entry_invalid:" + str(index))
            continue
        path = item.get("path")
        if not isinstance(path, str):
            failures.append("formal_authority_v4_live_overlay_entry_invalid:" + str(index))
            continue
        if (
            not _safe_relative(path)
            or path in seen
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] <= 0
            or not _valid_sha256(item.get("sha256"))
        ):
            failures.append("formal_authority_v4_live_overlay_entry_invalid:" + str(index))
            continue
        seen.add(path)
        canonical_entries.append(dict(item))
        try:
            actual = artifact_identity(workspace, LIVE_OVERLAY_ROOT + "/" + path)
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v4_live_overlay_unreadable:" + path)
            continue
        if (
            actual["size_bytes"] != item["size_bytes"]
            or actual["sha256"] != item["sha256"]
        ):
            failures.append("formal_authority_v4_live_overlay_identity_mismatch:" + path)
    ordered = sorted(canonical_entries, key=lambda item: item["path"])
    if entries != ordered or len(ordered) != policy.live_overlay_file_count:
        failures.append("formal_authority_v4_live_overlay_entry_set_invalid")
    if not set(REQUIRED_LIVE_OVERLAY_PATHS).issubset(seen):
        failures.append("formal_authority_v4_live_overlay_required_role_missing")
    if _canonical_sha256(ordered) != payload.get("source_set_sha256"):
        failures.append("formal_authority_v4_live_overlay_source_set_mismatch")
    without_binding = dict(payload)
    claimed = without_binding.pop("binding_sha256", None)
    if _canonical_sha256(without_binding) != claimed:
        failures.append("formal_authority_v4_live_overlay_binding_mismatch")
    return failures


def _validate_canonical(
    workspace: Path,
    payload: Any,
    source_roles: Sequence[Mapping[str, Any]],
    source_role_sha: str,
    policy: AuthorityPolicy,
) -> List[str]:
    expected_keys = {
        "schema_version", "artifact_id", "canonical_id", "generation_id", "status", "lifecycle",
        "immutable", "read_only", "source_implementation_complete",
        "production_authority_state", "live_overlay_binding", "live_overlay_attestation", "source_roles",
        "source_role_count", "source_role_set_sha256", "source_role_dispositions",
        "source_role_disposition_sha256",
        "external_trust_root_exclusions", "blockers",
        "accepted_by_formal_field_evidence_consumer", "delivery_ready",
        "authorizes_field_delivery", "artifact_binding_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return ["formal_authority_v4_canonical_schema_invalid"]
    failures: List[str] = []
    expected_scalars = {
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
        "live_overlay_attestation": {
            "binding_recompute_authority": (
                "HOST_OWNED_PURE_STDLIB_EXACT_FILE_CLOSURE"
            ),
            "production_factory_executed": False,
            "ambient_numpy_required": False,
        },
        "source_roles": list(source_roles),
        "source_role_count": len(source_roles),
        "source_role_set_sha256": source_role_sha,
        "source_role_dispositions": source_role_dispositions(policy),
        "source_role_disposition_sha256": _canonical_sha256(
            source_role_dispositions(policy)
        ),
        "external_trust_root_exclusions": list(EXTERNAL_TRUST_ROOT_EXCLUSIONS),
        "blockers": list(BLOCKERS),
        "accepted_by_formal_field_evidence_consumer": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    for key, expected in expected_scalars.items():
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v4_canonical_mismatch:" + key)
    failures.extend(_validate_live_overlay(
        workspace, payload.get("live_overlay_binding"), policy
    ))
    without_binding = dict(payload)
    claimed = without_binding.pop("artifact_binding_sha256", None)
    if not _valid_sha256(claimed) or _canonical_sha256(without_binding) != claimed:
        failures.append("formal_authority_v4_canonical_artifact_binding_invalid")
    return failures


def _validate_logical_suites(
    workspace: Path,
    value: Any,
    source_by_path: Mapping[str, Mapping[str, Any]],
) -> Tuple[List[str], Dict[str, Mapping[str, Any]]]:
    failures: List[str] = []
    if not isinstance(value, list):
        return ["formal_authority_v4_logical_suites_invalid"], {}
    by_id: Dict[str, Mapping[str, Any]] = {}
    definitions = {item[0]: item for item in LOGICAL_SUITE_DEFINITIONS}
    for item in value:
        if not isinstance(item, dict):
            failures.append("formal_authority_v4_logical_suite_invalid")
            continue
        suite_id = item.get("suite_id")
        if not isinstance(suite_id, str):
            failures.append("formal_authority_v4_logical_suite_id_invalid")
            continue
        if suite_id in by_id:
            failures.append("formal_authority_v4_logical_suite_duplicate:" + str(suite_id))
        by_id[suite_id] = item
    if set(by_id) != set(definitions):
        failures.append("formal_authority_v4_logical_suite_set_invalid")
    for suite_id, definition in definitions.items():
        item = by_id.get(suite_id)
        if not isinstance(item, dict):
            continue
        unused, test_path, runner_path, count = definition
        expected_keys = {
            "suite_id", "test_artifact_identity", "runner_artifact_identity",
            "expected_test_ids", "executed_test_ids", "expected", "collected",
            "passed", "failed", "skipped",
        }
        if set(item) != expected_keys:
            failures.append("formal_authority_v4_logical_suite_schema_invalid:" + suite_id)
            continue
        try:
            ids = _static_test_ids(workspace, test_path)
        except (OSError, UnicodeError, ValueError, SyntaxError):
            failures.append("formal_authority_v4_logical_suite_ast_invalid:" + suite_id)
            continue
        expected_test_identity = {
            key: source_by_path.get(test_path, {}).get(key)
            for key in ("path", "size_bytes", "sha256")
        }
        expected_runner_identity = {
            key: source_by_path.get(runner_path, {}).get(key)
            for key in ("path", "size_bytes", "sha256")
        }
        for key, expected in (
            ("test_artifact_identity", expected_test_identity),
            ("runner_artifact_identity", expected_runner_identity),
            ("expected_test_ids", ids),
            ("executed_test_ids", ids),
            ("expected", count), ("collected", count), ("passed", count),
            ("failed", 0), ("skipped", 0),
        ):
            if not _same(item.get(key), expected):
                failures.append(
                    "formal_authority_v4_logical_suite_mismatch:"
                    + suite_id + ":" + key
                )
    if [item.get("suite_id") for item in value if isinstance(item, dict)] != [
        item[0] for item in LOGICAL_SUITE_DEFINITIONS
    ]:
        failures.append("formal_authority_v4_logical_suite_order_invalid")
    return failures, by_id


def _expected_child_argv(
    workspace: Path,
    logical: Mapping[str, Any],
    interpreter_role: str,
    ids: Sequence[str],
) -> List[str]:
    execution_root = _execution_workspace_path(workspace)
    interpreter = _expected_interpreter_identity(interpreter_role)["entry_path"]
    runner = logical["runner_artifact_identity"]["path"]
    target = logical["test_artifact_identity"]["path"]
    argv = [
        interpreter, "-I", "-S", "-B",
        str(PurePosixPath(execution_root, runner)),
    ]
    if runner.endswith("run_pytest_style_tests.py"):
        argv.append("--single-file")
    argv.extend((
        "--workspace", execution_root, "--target", target,
        "--import-root", ".",
    ))
    for case_id in ids:
        argv.extend(("--expected-id", case_id))
    return argv


def _child_file_identity_matches(
    value: Any, expected: Mapping[str, Any], absolute_path: str
) -> bool:
    return (
        isinstance(value, dict)
        and value.get("path") == absolute_path
        and value.get("size_bytes") == expected.get("size_bytes")
        and value.get("sha256") == expected.get("sha256")
        and value.get("regular_file") is True
        and value.get("is_symlink") is False
    )


def _validate_unittest_child_payload(
    workspace: Path,
    payload: Any,
    logical: Mapping[str, Any],
    interpreter: Mapping[str, Any],
    ids: Sequence[str],
    prefix: str,
) -> List[str]:
    if not isinstance(payload, dict):
        return [prefix + "_child_payload_invalid"]
    failures: List[str] = []
    execution_root = _execution_workspace_path(workspace)
    target = logical["test_artifact_identity"]
    target_absolute = str(PurePosixPath(execution_root, target["path"]))
    expected_values = {
        "schema_version": "offline_unittest_file_result/v1",
        "runner_kind": "stdlib_unittest_single_file_isolated",
        "selection_mode": "selected_ids",
        "workspace": execution_root,
        "import_roots": ["."],
        "path": target["path"],
        "resolved_path": target_absolute,
        "size_bytes": target["size_bytes"],
        "sha256": target["sha256"],
        "requested_ids": list(ids),
        "expected_ids": list(ids),
        "executed_ids": list(ids),
        "passed_ids": list(ids),
        "failed_ids": [],
        "skipped_ids": [],
        "discovered_ids": list(ids),
        "discovered": len(ids),
        "collected": len(ids),
        "passed": len(ids),
        "failed": 0,
        "skipped": 0,
        "exit": 0,
        "result": "PASS",
        "failures": [],
        "stdout_marker_count": 1,
        "environment_unchanged_during_execution": True,
        "environment_restored": True,
    }
    for key, expected in expected_values.items():
        if not _same(payload.get(key), expected):
            failures.append(prefix + "_child_mismatch:" + key)
    for key in ("target_identity_before", "target_identity_after"):
        if not _child_file_identity_matches(payload.get(key), target, target_absolute):
            failures.append(prefix + "_child_target_identity_invalid:" + key)
    environment = payload.get("environment")
    if not isinstance(environment, dict):
        failures.append(prefix + "_child_environment_invalid")
    else:
        if (
            environment.get("clean") is not True
            or environment.get("contaminated_keys") != []
            or environment.get("cwd") != execution_root
        ):
            failures.append(prefix + "_child_environment_contaminated")
        sys_path = environment.get("sys_path_before_import_roots")
        if (
            not isinstance(sys_path, list)
            or any(
                not isinstance(item, str)
                or "site-packages" in item
                or "dist-packages" in item
                for item in sys_path
            )
        ):
            failures.append(prefix + "_child_sys_path_invalid")
    executable = payload.get("executable")
    expected_child_chain = [{
        "path": item["path"],
        "link_target": item["link_text"],
        "next_path": item["next_path"],
    } for item in interpreter["entry_link_chain"]]
    if not isinstance(executable, dict):
        failures.append(prefix + "_child_executable_invalid")
    else:
        child_target = executable.get("resolved_target")
        if (
            executable.get("entry_path") != interpreter["entry_path"]
            or executable.get("entry_is_symlink") is not interpreter["entry_is_symlink"]
            or executable.get("entry_link_chain") != expected_child_chain
            or not _child_file_identity_matches(
                child_target,
                interpreter["resolved_target"],
                interpreter["resolved_target"]["path"],
            )
            or executable.get("isolated") is not True
            or executable.get("no_bytecode") is not True
            or executable.get("version") != PYTHON314_VERSION
        ):
            failures.append(prefix + "_child_executable_identity_mismatch")
    if payload.get("python") != executable:
        failures.append(prefix + "_child_python_alias_mismatch")
    return failures


def _validate_pytest_child_payload(
    payload: Any,
    logical: Mapping[str, Any],
    ids: Sequence[str],
    prefix: str,
) -> List[str]:
    expected_keys = {
        "schema_version", "runner_kind", "path", "size_bytes", "sha256",
        "expected_ids", "executed_ids", "collected", "passed", "failed",
        "skipped", "exit", "result",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return [prefix + "_child_payload_schema_invalid"]
    target = logical["test_artifact_identity"]
    expected = {
        "schema_version": "offline_pytest_file_result/v1",
        "runner_kind": "offline_pytest_style_single_file",
        "path": target["path"],
        "size_bytes": target["size_bytes"],
        "sha256": target["sha256"],
        "expected_ids": list(ids),
        "executed_ids": list(ids),
        "collected": len(ids),
        "passed": len(ids),
        "failed": 0,
        "skipped": 0,
        "exit": 0,
        "result": "PASS",
    }
    return [] if _same(payload, expected) else [prefix + "_child_payload_mismatch"]


def _validate_physical_records(
    workspace: Path,
    value: Any,
    logical_by_id: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    failures: List[str] = []
    if not isinstance(value, list):
        return ["formal_authority_v4_physical_records_invalid"]
    by_id: Dict[str, Mapping[str, Any]] = {}
    definitions = {item[0]: item for item in PHYSICAL_EXECUTION_DEFINITIONS}
    for item in value:
        if not isinstance(item, dict):
            failures.append("formal_authority_v4_physical_record_invalid")
            continue
        record_id = item.get("record_id")
        if not isinstance(record_id, str):
            failures.append("formal_authority_v4_physical_record_id_invalid")
            continue
        if record_id in by_id:
            failures.append("formal_authority_v4_physical_record_duplicate:" + str(record_id))
        by_id[record_id] = item
    if set(by_id) != set(definitions):
        failures.append("formal_authority_v4_physical_record_set_invalid")
    expected_keys = {
        "record_id", "suite_id", "platform", "interpreter_role",
        "interpreter_identity_before", "interpreter_identity_after",
        "test_artifact_identity_before", "test_artifact_identity_after",
        "runner_artifact_identity_before", "runner_artifact_identity_after",
        "expected_test_ids", "executed_test_ids", "collected", "passed",
        "failed", "skipped", "exit_code", "argv", "argv_sha256",
        "environment", "environment_sha256", "stdout", "stderr",
        "marker_count", "marker_prefix", "marker_raw_sha256",
        "marker_payload", "marker_payload_sha256",
    }
    for record_id, definition in definitions.items():
        item = by_id.get(record_id)
        if not isinstance(item, dict):
            continue
        unused, suite_id, platform, interpreter_role, count = definition
        if set(item) != expected_keys:
            failures.append("formal_authority_v4_physical_record_schema_invalid:" + record_id)
            continue
        logical = logical_by_id.get(suite_id, {})
        ids = logical.get("expected_test_ids", [])
        for key, expected in (
            ("suite_id", suite_id), ("platform", platform),
            ("interpreter_role", interpreter_role),
            ("test_artifact_identity_before", logical.get("test_artifact_identity")),
            ("test_artifact_identity_after", logical.get("test_artifact_identity")),
            ("runner_artifact_identity_before", logical.get("runner_artifact_identity")),
            ("runner_artifact_identity_after", logical.get("runner_artifact_identity")),
            ("expected_test_ids", ids), ("executed_test_ids", ids),
            ("collected", count), ("passed", count), ("failed", 0),
            ("skipped", 0), ("exit_code", 0), ("marker_count", 1),
        ):
            if not _same(item.get(key), expected):
                failures.append(
                    "formal_authority_v4_physical_record_mismatch:"
                    + record_id + ":" + key
                )
        before = item.get("interpreter_identity_before")
        after = item.get("interpreter_identity_after")
        failures.extend(_interpreter_failures(
            before, interpreter_role,
            "formal_authority_v4_physical_record:" + record_id + ":before",
        ))
        failures.extend(_interpreter_failures(
            after, interpreter_role,
            "formal_authority_v4_physical_record:" + record_id + ":after",
        ))
        if not _same(before, after):
            failures.append("formal_authority_v4_physical_interpreter_drift:" + record_id)
        expected_argv = _expected_child_argv(
            workspace, logical, interpreter_role, ids
        )
        if not _same(item.get("argv"), expected_argv):
            failures.append("formal_authority_v4_physical_argv_invalid:" + record_id)
        if item.get("argv_sha256") != _canonical_sha256(expected_argv):
            failures.append("formal_authority_v4_physical_argv_sha256_invalid:" + record_id)
        if not _same(item.get("environment"), dict(CHILD_ENVIRONMENT)):
            failures.append("formal_authority_v4_physical_environment_invalid:" + record_id)
        if item.get("environment_sha256") != _canonical_sha256(dict(CHILD_ENVIRONMENT)):
            failures.append("formal_authority_v4_physical_environment_sha256_invalid:" + record_id)
        runner = logical.get("runner_artifact_identity", {}).get("path", "")
        marker_prefix = (
            "OFFLINE_PYTEST_FILE_RESULT "
            if isinstance(runner, str) and runner.endswith("run_pytest_style_tests.py")
            else "OFFLINE_UNITTEST_FILE_RESULT "
        )
        if item.get("marker_count") != 1 or item.get("marker_prefix") != marker_prefix:
            failures.append("formal_authority_v4_physical_marker_envelope_invalid:" + record_id)
        marker = item.get("marker_payload")
        if not isinstance(marker, dict):
            failures.append("formal_authority_v4_physical_marker_payload_invalid:" + record_id)
            marker = {}
        marker_raw = _canonical_json(marker)
        if item.get("marker_raw_sha256") != hashlib.sha256(marker_raw).hexdigest():
            failures.append("formal_authority_v4_physical_marker_raw_sha256_invalid:" + record_id)
        if item.get("marker_payload_sha256") != _canonical_sha256(marker):
            failures.append("formal_authority_v4_physical_marker_payload_sha256_invalid:" + record_id)
        expected_stdout = marker_prefix.encode("ascii") + marker_raw + b"\n"
        if not _same(item.get("stdout"), _stream_identity(expected_stdout)):
            failures.append("formal_authority_v4_physical_stdout_identity_invalid:" + record_id)
        stderr = item.get("stderr")
        if (
            not isinstance(stderr, dict)
            or set(stderr) != {"size_bytes", "sha256"}
            or type(stderr.get("size_bytes")) is not int
            or stderr["size_bytes"] < 0
            or not _valid_sha256(stderr.get("sha256"))
        ):
            failures.append("formal_authority_v4_physical_stderr_identity_invalid:" + record_id)
        child_prefix = "formal_authority_v4_physical_record:" + record_id
        if marker_prefix.startswith("OFFLINE_UNITTEST"):
            failures.extend(_validate_unittest_child_payload(
                workspace, marker, logical, before if isinstance(before, dict) else {},
                ids, child_prefix,
            ))
        else:
            failures.extend(_validate_pytest_child_payload(
                marker, logical, ids, child_prefix
            ))
    if [item.get("record_id") for item in value if isinstance(item, dict)] != [
        item[0] for item in PHYSICAL_EXECUTION_DEFINITIONS
    ]:
        failures.append("formal_authority_v4_physical_record_order_invalid")
    return failures


def _validate_production_cli_observation(
    workspace: Path,
    value: Any,
    source_by_path: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    expected_keys = {
        "not_in_logical_denominator", "not_in_physical_denominator",
        "expected_fail_closed", "source_identity_before",
        "source_identity_after", "interpreter_identity", "argv",
        "argv_sha256", "environment", "environment_sha256", "exit_code",
        "stdout", "stderr", "expected_stderr_sha256", "blocked_code",
        "formal_consumer", "delivery_ready",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        return ["formal_authority_v4_production_cli_observation_invalid"]
    failures: List[str] = []
    execution_root = _execution_workspace_path(workspace)
    source = source_by_path.get("audit_tools/ros1_camera_only_atomic_launcher.py", {})
    archive = (
        "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch"
    )
    expected_argv = [
        "/usr/bin/python3.14", "-I", "-S", "-B",
        str(PurePosixPath(execution_root, source.get("path", ""))),
        "--mode", "EXECUTE_AUDITED_CAMERA_ONLY",
        "--actual-vendor-launch", str(PurePosixPath(execution_root, archive)),
    ]
    blocked = (
        b"ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
        b"camera_runtime_install_admission_not_bound\n"
    )
    expected = {
        "not_in_logical_denominator": True,
        "not_in_physical_denominator": True,
        "expected_fail_closed": True,
        "source_identity_before": {
            key: source.get(key) for key in ("path", "size_bytes", "sha256")
        },
        "source_identity_after": {
            key: source.get(key) for key in ("path", "size_bytes", "sha256")
        },
        "interpreter_identity": _expected_interpreter_identity(
            "system_python314_target"
        ),
        "argv": expected_argv,
        "argv_sha256": _canonical_sha256(expected_argv),
        "environment": dict(CHILD_ENVIRONMENT),
        "environment_sha256": _canonical_sha256(dict(CHILD_ENVIRONMENT)),
        "exit_code": 4,
        "stdout": _stream_identity(b""),
        "stderr": _stream_identity(blocked),
        "expected_stderr_sha256": hashlib.sha256(blocked).hexdigest(),
        "blocked_code": "camera_runtime_install_admission_not_bound",
        "formal_consumer": False,
        "delivery_ready": False,
    }
    if not _same(value, expected):
        failures.append("formal_authority_v4_production_cli_observation_mismatch")
    return failures


def _validate_report(
    workspace: Path,
    payload: Any,
    canonical_identity: Mapping[str, Any],
    source_roles: Sequence[Mapping[str, Any]],
    source_by_path: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    expected_keys = {
        "schema_version", "report_kind", "report_id", "evidence_id", "generation_id",
        "status", "lifecycle", "is_current", "immutable", "read_only",
        "canonical_source_admission", "source_role_set_sha256", "test_matrix",
        "production_authority_state", "production_cli_observation", "gate_state", "regression_passed",
        "accepted_by_formal_field_evidence_consumer", "delivery_ready",
        "authorizes_field_delivery", "formal_denominator", "ros_graph_started",
        "camera_opened", "inference_started", "hardware_connected",
        "network_used", "report_binding_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return ["formal_authority_v4_report_schema_invalid"]
    failures: List[str] = []
    expected_scalars = {
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
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
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
    for key, expected in expected_scalars.items():
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v4_report_mismatch:" + key)
    failures.extend(_validate_production_cli_observation(
        workspace, payload.get("production_cli_observation"), source_by_path
    ))
    matrix = payload.get("test_matrix")
    matrix_keys = {
        "logical_suite_records", "logical_expected_total", "logical_collected",
        "logical_passed", "logical_failed", "logical_skipped",
        "physical_execution_records", "physical_expected_total",
        "physical_collected", "physical_passed", "physical_failed",
        "physical_skipped", "failures",
    }
    if not isinstance(matrix, dict) or set(matrix) != matrix_keys:
        failures.append("formal_authority_v4_report_test_matrix_invalid")
    else:
        logical_failures, logical_by_id = _validate_logical_suites(
            workspace, matrix.get("logical_suite_records"), source_by_path
        )
        failures.extend(logical_failures)
        failures.extend(_validate_physical_records(
            workspace, matrix.get("physical_execution_records"), logical_by_id
        ))
        logical_records = matrix.get("logical_suite_records", [])
        physical_records = matrix.get("physical_execution_records", [])
        logical_collected = sum(
            item.get("collected", -10**9)
            for item in logical_records if isinstance(item, dict)
        )
        physical_collected = sum(
            item.get("collected", -10**9)
            for item in physical_records if isinstance(item, dict)
        )
        for key, expected in (
            ("logical_expected_total", LOGICAL_EXPECTED_TOTAL),
            ("logical_collected", logical_collected),
            ("logical_passed", LOGICAL_EXPECTED_TOTAL),
            ("logical_failed", 0), ("logical_skipped", 0),
            ("physical_expected_total", PHYSICAL_EXPECTED_TOTAL),
            ("physical_collected", physical_collected),
            ("physical_passed", PHYSICAL_EXPECTED_TOTAL),
            ("physical_failed", 0), ("physical_skipped", 0),
            ("failures", []),
        ):
            if not _same(matrix.get(key), expected):
                failures.append("formal_authority_v4_report_test_count_mismatch:" + key)
        if logical_collected != LOGICAL_EXPECTED_TOTAL:
            failures.append("formal_authority_v4_logical_denominator_recompute_mismatch")
        if physical_collected != PHYSICAL_EXPECTED_TOTAL:
            failures.append("formal_authority_v4_physical_denominator_recompute_mismatch")
    without_binding = dict(payload)
    claimed = without_binding.pop("report_binding_sha256", None)
    if not _valid_sha256(claimed) or _canonical_sha256(without_binding) != claimed:
        failures.append("formal_authority_v4_report_binding_invalid")
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
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "formal_latency_pass": False,
        "ros1_noetic_runtime_verified": False,
        "ros1_noetic_build_install_verified": False,
        "ros1_noetic_field_install_pass": False,
        "ros1_source_implementation_complete": False,
        "current_evidence": None,
        "artifact_identities": [],
        "failures": [],
    }


def validate_formal_admission_evidence_authority_v4(
    workspace: Path,
    payload: Any,
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    result = _base_result()
    failures: List[str] = result["failures"]
    failures.extend(_policy_failures(policy))
    if failures:
        return result
    if not isinstance(payload, dict):
        failures.append("formal_authority_v4_payload_invalid")
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
        failures.append("formal_authority_v4_top_level_keys_invalid")
    expected_scalars = {
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
        "predecessor_authority_index": dict(PREDECESSOR_INDEX_IDENTITY),
        "production_authority_state": dict(PRODUCTION_AUTHORITY_STATE),
        "gate_state": dict(GATE_STATE),
    }
    for key, expected in expected_scalars.items():
        if not _same(payload.get(key), expected):
            failures.append("formal_authority_v4_top_level_mismatch:" + key)

    source_failures, source_by_path = _validate_source_roles(
        Path(workspace), payload.get("source_roles"), policy
    )
    failures.extend(source_failures)
    source_roles = payload.get("source_roles") if isinstance(payload.get("source_roles"), list) else []
    expected_source_sha = _source_role_set_sha256(source_roles)
    if payload.get("source_role_count") != len(source_roles):
        failures.append("formal_authority_v4_source_role_count_invalid")
    if payload.get("source_role_set_sha256") != expected_source_sha:
        failures.append("formal_authority_v4_source_role_sha256_invalid")

    entries = payload.get("entries")
    by_id: Dict[str, Mapping[str, Any]] = {}
    currents: List[Mapping[str, Any]] = []
    if not isinstance(entries, list) or len(entries) != 2:
        failures.append("formal_authority_v4_entry_count_invalid")
        entries = entries if isinstance(entries, list) else []
    for item in entries:
        if not isinstance(item, dict):
            failures.append("formal_authority_v4_entry_invalid")
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str):
            failures.append("formal_authority_v4_entry_evidence_id_invalid")
            continue
        if evidence_id in by_id:
            failures.append("formal_authority_v4_duplicate_evidence_id")
        by_id[evidence_id] = item
        if item.get("is_current") is True:
            currents.append(item)
    if set(by_id) != {
        PREDECESSOR_INDEX_IDENTITY["current_evidence_id"], CURRENT_EVIDENCE_ID
    }:
        failures.append("formal_authority_v4_entry_set_invalid")
    if len(currents) != 1:
        failures.append("formal_authority_v4_current_count_invalid")
    elif currents[0].get("evidence_id") != CURRENT_EVIDENCE_ID:
        failures.append("formal_authority_v4_current_marker_invalid")
    current = by_id.get(CURRENT_EVIDENCE_ID)
    old = by_id.get(PREDECESSOR_INDEX_IDENTITY["current_evidence_id"])
    if not isinstance(current, dict):
        failures.append("formal_authority_v4_current_entry_missing")
        current = {}
    if not isinstance(old, dict):
        failures.append("formal_authority_v4_predecessor_entry_missing")
        old = {}
    expected_old = build_index_payload(
        {"path": policy.report_relative_path, "size_bytes": 1, "sha256": "0" * 64},
        {"path": policy.canonical_relative_path, "size_bytes": 1, "sha256": "0" * 64},
        source_roles,
        policy,
    )["entries"][0]
    if old != expected_old:
        failures.append("formal_authority_v4_predecessor_entry_mismatch")

    report_identity = {
        key: current.get(key) for key in ("path", "size_bytes", "sha256")
    }
    failures.extend(_identity_failures(
        report_identity, "formal_authority_v4_current_report"
    ))
    if report_identity.get("path") != policy.report_relative_path:
        failures.append("formal_authority_v4_current_report_path_mismatch")
    expected_current = {
        "evidence_id": CURRENT_EVIDENCE_ID,
        "report_id": REPORT_ID,
        "generation_id": GENERATION_ID,
        "status": CURRENT_STATUS,
        "lifecycle": "CURRENT",
        "is_current": True,
        "predecessor_evidence_id": PREDECESSOR_INDEX_IDENTITY["current_evidence_id"],
        "report_kind": "perception_v2_blocked_offline_regression",
        **report_identity,
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
    }
    if current != expected_current:
        failures.append("formal_authority_v4_current_entry_mismatch")

    children = payload.get("child_artifacts")
    if not isinstance(children, list) or len(children) != 1 or not isinstance(children[0], dict):
        failures.append("formal_authority_v4_child_artifacts_invalid")
        canonical_identity = {}
    else:
        child = children[0]
        canonical_identity = {
            key: child.get(key) for key in ("path", "size_bytes", "sha256")
        }
        failures.extend(_identity_failures(
            canonical_identity, "formal_authority_v4_canonical"
        ))
        if canonical_identity.get("path") != policy.canonical_relative_path:
            failures.append("formal_authority_v4_canonical_path_mismatch")
        expected_child = {
            "artifact_id": CANONICAL_ARTIFACT_ID,
            "canonical_id": CANONICAL_ID,
            "parent_evidence_id": CURRENT_EVIDENCE_ID,
            "role": "canonical_source_admission_child",
            "status": "BOUND_BLOCKED_OFFLINE_SOURCE_CHILD",
            "lifecycle": "CURRENT_CHILD",
            "is_current": False,
            **canonical_identity,
            "authorizes_field_delivery": False,
        }
        if child != expected_child:
            failures.append("formal_authority_v4_canonical_child_mismatch")

    artifacts = (
        ("predecessor_index", dict(PREDECESSOR_INDEX_IDENTITY), "predecessor"),
        (CURRENT_EVIDENCE_ID, report_identity, "report"),
        (CANONICAL_ARTIFACT_ID, canonical_identity, "canonical"),
    )
    for artifact_id, expected_identity, role in artifacts:
        relative = expected_identity.get("path")
        if not _safe_relative(relative):
            continue
        try:
            unused, identity, raw = _regular_identity(Path(workspace), relative)
            result["artifact_identities"].append({
                "artifact_id": artifact_id, **identity
            })
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v4_artifact_unreadable:" + artifact_id)
            continue
        for key in ("size_bytes", "sha256"):
            if identity.get(key) != expected_identity.get(key):
                failures.append(
                    "formal_authority_v4_artifact_" + key + "_mismatch:" + artifact_id
                )
        try:
            artifact_payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            failures.append("formal_authority_v4_artifact_strict_json_invalid:" + artifact_id)
            continue
        if role == "predecessor":
            failures.extend(_validate_predecessor_payload(artifact_payload))
        elif role == "report":
            failures.extend(_validate_report(
                Path(workspace), artifact_payload, canonical_identity,
                source_roles, source_by_path,
            ))
        else:
            failures.extend(_validate_canonical(
                Path(workspace), artifact_payload, source_roles,
                expected_source_sha, policy,
            ))

    failures[:] = list(dict.fromkeys(failures))
    if not failures:
        result["semantic_validated_pass"] = True
    return result


def load_and_resolve_formal_admission_evidence_authority_v4(
    workspace: Path,
    index_trust_anchor: Mapping[str, Any],
    policy: AuthorityPolicy = PRODUCTION_POLICY,
) -> Dict[str, Any]:
    result = _base_result()
    failures: List[str] = []
    failures.extend(_policy_failures(policy))
    failures.extend(_identity_failures(
        index_trust_anchor, "formal_authority_v4_index_anchor"
    ))
    if (
        isinstance(index_trust_anchor, dict)
        and index_trust_anchor.get("path") != policy.index_relative_path
    ):
        failures.append("formal_authority_v4_index_anchor_path_mismatch")
    identity: Dict[str, Any] = {}
    raw = b""
    if not failures:
        try:
            unused, identity, raw = _regular_identity(
                Path(workspace), policy.index_relative_path
            )
        except (OSError, UnicodeError, ValueError):
            failures.append("formal_authority_v4_index_unreadable")
    if identity and identity != dict(index_trust_anchor):
        for key in ("path", "size_bytes", "sha256"):
            if identity.get(key) != index_trust_anchor.get(key):
                failures.append("formal_authority_v4_index_" + key + "_mismatch")
    payload = None
    if raw:
        try:
            payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            failures.append("formal_authority_v4_index_strict_json_invalid")
    validation = validate_formal_admission_evidence_authority_v4(
        Path(workspace), payload, policy
    )
    for failure in failures:
        _append(validation["failures"], failure)
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
        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        currents = [
            item for item in entries
            if isinstance(item, dict) and item.get("is_current") is True
        ]
        validation["current_evidence"] = dict(currents[0])
    validation["index_identity"] = identity
    validation["expected_index_identity"] = (
        dict(index_trust_anchor) if isinstance(index_trust_anchor, Mapping) else {}
    )
    validation["index_relative_path"] = policy.index_relative_path
    validation["filename_mtime_selection_forbidden"] = True
    return validation


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> Dict[str, Any]:
    raw = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "path": path,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


__all__ = [
    "AUTHORITY_FAMILY_ID", "AuthorityPolicy", "BLOCKERS",
    "CANONICAL_ARTIFACT_ID", "CANONICAL_RELATIVE_PATH", "CURRENT_EVIDENCE_ID",
    "GENERATION_ID", "GATE_STATE", "INDEX_INSTANCE_ID", "INDEX_RELATIVE_PATH",
    "LOGICAL_EXPECTED_TOTAL", "PHYSICAL_EXPECTED_TOTAL", "PREDECESSOR_INDEX_IDENTITY",
    "PRODUCTION_AUTHORITY_STATE", "PRODUCTION_POLICY", "REPORT_RELATIVE_PATH",
    "REQUIRED_SOURCE_ROLE_PATHS", "WORKSPACE_ROOT", "artifact_identity",
    "build_canonical_payload", "build_index_payload",
    "build_report_payload", "collect_live_overlay_binding", "collect_source_role_bindings",
    "load_and_resolve_formal_admission_evidence_authority_v4", "logical_suite_records",
    "source_role_dispositions", "validate_formal_admission_evidence_authority_v4",
    "write_json_exclusive",
]
