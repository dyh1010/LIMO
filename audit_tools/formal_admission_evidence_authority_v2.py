"""Parameterized trust root for the next ROS1 offline-admission generation.

The previous generation is frozen and remains independently resolvable by
``formal_admission_evidence_authority``.  This module deliberately has no
ambient/default current report: a host caller must provide the exact report
and canonical-source identities before an index can be constructed.  After
exclusive creation, the index identity must be supplied back as an external
path/size/SHA-256 anchor before it can be resolved.

A successful result is an *offline evidence selection* only.  Every field,
delivery, TF, 3D, latency, ROS graph, camera, hardware, and motion capability
is fixed false.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "ros1_formal_admission_evidence_authority/v2"
SPEC_SCHEMA_VERSION = "ros1_formal_admission_evidence_authority_spec/v2"
DEFAULT_AUTHORITY_ID = "ros1-formal-admission-evidence-authority-20260815-v2"
DEFAULT_GENERATION_ID = "ros1_delivery_blocker_layering_20260815_v3"
DEFAULT_GENERATION_SCOPE = (
    "blocked_offline_ros1_delivery_blocker_layering_not_field_delivery"
)
DEFAULT_CURRENT_EVIDENCE_ID = (
    "ros1_delivery_blocker_layering_offline_regression_20260815_v3"
)
DEFAULT_CURRENT_STATUS = "CURRENT_BLOCKED_OFFLINE_BASELINE"
SELECTION_AUTHORITY = (
    "FIXED_INDEX_PATH_EXTERNAL_SIZE_SHA256_STRICT_JSON_AND_SEMANTIC_RECOMPUTE"
)

PREDECESSOR_INDEX_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_v2.json"
    ),
    "size_bytes": 4528,
    "sha256": "b16940fb5cdfbc3982ecf9aedb4c09c152c62b4ce558902ba0f829ef7ab7cf05",
    "status": "SUPERSEDED_NON_CURRENT_INTERMEDIATE_AUTHORITY",
    "lifecycle": "SUPERSEDED",
}
PREDECESSOR_AUTHORITY_CURRENT_EVIDENCE: Mapping[str, Any] = {
    "evidence_id": "ros1_delivery_blocker_layering_offline_regression_20260815_v3",
    "generation_id": "ros1_delivery_blocker_layering_20260815_v3",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_ros1_delivery_blocker_layering_v3.json"
    ),
    "size_bytes": 601070,
    "sha256": "dd97ae1ff4d991d0b0449c947109eab45d9628f885e1646e305463120b8d37f1",
}
SUPERSEDED_REPORT: Mapping[str, Any] = {
    "evidence_id": "ros1_runtime_source_admission_offline_regression_20260815_v2",
    "generation_id": "ros1_runtime_source_admission_20260815_v2",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_ros1_runtime_source_admission_v2.json"
    ),
    "size_bytes": 584827,
    "sha256": "48f530b6411a95b19ed2e8e5bd9e3da69c2fb0a5770e6f1e0c2552090836b887",
    "report_kind": "perception_v2_frozen_offline_regression",
    "predecessor_evidence_id": "ros1_formal_admission_offline_regression_20260815_v1",
}
EMBEDDED_RUNNER_AUTHORITY_EVIDENCE_ID = "ros1_canonical_source_binding_v7"

DEFAULT_TEST_COUNTS: Mapping[str, int] = {
    "expected_grand_total": 194,
    "grand_total_collected": 194,
    "grand_total_passed": 194,
    "supplemental_expected_total": 10,
    "supplemental_collected": 10,
    "supplemental_passed": 10,
    "supplemental_failed": 0,
    "post_fix_expected_total": 57,
    "post_fix_collected": 57,
    "post_fix_passed": 57,
    "post_fix_failed": 0,
    "current_generation_expected_total": 71,
    "current_generation_collected": 71,
    "current_generation_passed": 71,
    "current_generation_failed": 0,
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

DEFAULT_GATE_BLOCKERS: Tuple[str, ...] = DEFAULT_REPORT_BLOCKERS

PYTEST_FILE_RESULT_PREFIX = "OFFLINE_PYTEST_FILE_RESULT "
PYTEST_FILE_RESULT_SCHEMA_VERSION = "offline_pytest_file_result/v1"
PYTEST_FILE_RESULT_RUNNER_KIND = "offline_pytest_style_single_file"
EXPECTED_PYTEST_FILE_PATHS: Tuple[str, ...] = (
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
EXPECTED_PYTEST_FILE_COUNT = len(EXPECTED_PYTEST_FILE_PATHS)
EXPECTED_PYTEST_CASE_TOTAL = 111
EXPECTED_PYTEST_POLICY: Mapping[str, Any] = {
    "environment_allowlist": [
        "COMSPEC", "LANG", "LC_ALL", "PATH", "PATHEXT", "SYSTEMDRIVE",
        "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "WINDIR",
    ],
    "import_roots": ["src/limo_cleanup_perception", "src/limo_cleanup_interfaces", "."],
    "marker_prefix": PYTEST_FILE_RESULT_PREFIX,
    "one_isolated_process_per_unique_file": True,
    "python_isolated_flag": True,
    "python_no_bytecode_flag": True,
    "filename_or_total_only_selection_forbidden": True,
}
PYTEST_MARKER_KEYS = {
    "schema_version", "runner_kind", "path", "size_bytes", "sha256",
    "expected_ids", "executed_ids", "collected", "passed", "failed",
    "skipped", "exit", "result",
}
PYTEST_RECORD_KEYS = {
    "allocations", "collected", "command", "executed_ids", "expected_ids",
    "failed", "failures", "marker_json_length_bytes", "marker_json_sha256",
    "marker_payload", "passed", "path", "post_identity", "pre_identity",
    "skipped", "source_unchanged", "validated_pass",
}
PYTEST_COMMAND_KEYS = {
    "argv", "cwd", "duration_sec", "exit_code", "stderr_head",
    "stderr_length_bytes", "stderr_length_chars", "stderr_sha256",
    "stderr_tail", "stdout_head", "stdout_length_bytes",
    "stdout_length_chars", "stdout_sha256", "stdout_tail", "timed_out",
}

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_INDEX_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_v3.json"
)
PRODUCTION_INDEX_TRUST_ANCHOR: Mapping[str, Any] = {
    "path": PRODUCTION_INDEX_RELATIVE_PATH,
    "size_bytes": 4687,
    "sha256": "c13fcbb5832afc06473fd243c452ded191a688ddb808d43fb6fb2ad6e4ac2f20",
}
PRODUCTION_CURRENT_REPORT_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_ros1_delivery_blocker_layering_v3.json"
    ),
    "size_bytes": 601070,
    "sha256": "dd97ae1ff4d991d0b0449c947109eab45d9628f885e1646e305463120b8d37f1",
}
PRODUCTION_CANONICAL_CHILD_IDENTITY: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_noetic_canonical_source_admission_20260815_v4.json"
    ),
    "size_bytes": 9250,
    "sha256": "c5a5b90bbbcf7c9a3394832e18a01e2c3d43a2c7cd793d3f0f0c707e8116bfd9",
}
PRODUCTION_CANONICAL_EXPECTED: Mapping[str, Any] = {
    "schema_version": 1,
    "binding_kind": "canonical_project_overlay",
    "canonical_source_root": "ros1_overlay_src/limo_cleanup_ros1_perception",
    "file_count": 48,
    "source_contract_pass": True,
    "indexer_only_detected": False,
    "test_only": False,
    "architecture_blockers": [],
}


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number: " + value)


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_nonfinite,
    )


def _same(actual: Any, expected: Any) -> bool:
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


def _is_linklike(path: Path) -> bool:
    info = os.lstat(str(path))
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse)


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    pure = PurePosixPath(value)
    return (
        not pure.is_absolute()
        and ".." not in pure.parts
        and pure.as_posix() == value
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
        if _is_linklike(current):
            raise ValueError("linklike path forbidden")
    path = root.joinpath(*PurePosixPath(relative).parts)
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    info = os.lstat(str(path))
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    raw = path.read_bytes()
    return path, {
        "path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, raw


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _identity_failures(identity: Any, prefix: str) -> List[str]:
    failures: List[str] = []
    if not isinstance(identity, dict) or set(identity) != {
        "path", "size_bytes", "sha256"
    }:
        return [prefix + "_identity_schema_invalid"]
    if not _safe_relative(identity.get("path")):
        failures.append(prefix + "_path_invalid")
    if type(identity.get("size_bytes")) is not int or identity["size_bytes"] <= 0:
        failures.append(prefix + "_size_invalid")
    if not _valid_sha256(identity.get("sha256")):
        failures.append(prefix + "_sha256_invalid")
    return failures


def _canonical_json_sha(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_generation_spec(
    *,
    current_report_identity: Mapping[str, Any],
    canonical_child_identity: Mapping[str, Any],
    index_relative_path: str,
    canonical_expected: Mapping[str, Any],
    authority_id: str = DEFAULT_AUTHORITY_ID,
    generation_id: str = DEFAULT_GENERATION_ID,
    generation_scope: str = DEFAULT_GENERATION_SCOPE,
    current_evidence_id: str = DEFAULT_CURRENT_EVIDENCE_ID,
    current_status: str = DEFAULT_CURRENT_STATUS,
    test_counts: Mapping[str, Any] = DEFAULT_TEST_COUNTS,
    report_blockers: Sequence[str] = DEFAULT_REPORT_BLOCKERS,
    gate_blockers: Sequence[str] = DEFAULT_GATE_BLOCKERS,
) -> Dict[str, Any]:
    """Build host-owned expected state; no value is read from index payload."""
    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "authority_id": authority_id,
        "generation_id": generation_id,
        "generation_scope": generation_scope,
        "current_evidence_id": current_evidence_id,
        "current_status": current_status,
        "index_relative_path": index_relative_path,
        "current_report_identity": dict(current_report_identity),
        "canonical_child_identity": dict(canonical_child_identity),
        "canonical_expected": dict(canonical_expected),
        "test_counts": dict(test_counts),
        "report_blockers": list(report_blockers),
        "gate_blockers": list(gate_blockers),
    }


def make_generation_spec_from_workspace(
    workspace: Path,
    *,
    current_report_relative_path: str,
    canonical_child_relative_path: str,
    index_relative_path: str,
    canonical_expected: Mapping[str, Any],
    **kwargs: Any
) -> Dict[str, Any]:
    """Read exact artifacts once to prepare a not-yet-anchored generation."""
    unused, report_identity, unused_raw = _regular_identity(
        workspace, current_report_relative_path
    )
    unused, canonical_identity, unused_raw = _regular_identity(
        workspace, canonical_child_relative_path
    )
    return make_generation_spec(
        current_report_identity=report_identity,
        canonical_child_identity=canonical_identity,
        index_relative_path=index_relative_path,
        canonical_expected=canonical_expected,
        **kwargs
    )


def _spec_failures(spec: Any) -> List[str]:
    expected_keys = {
        "schema_version", "authority_id", "generation_id", "generation_scope",
        "current_evidence_id", "current_status", "index_relative_path",
        "current_report_identity", "canonical_child_identity",
        "canonical_expected", "test_counts", "report_blockers",
        "gate_blockers",
    }
    failures: List[str] = []
    if not isinstance(spec, dict) or set(spec) != expected_keys:
        return ["formal_authority_v2_spec_schema_invalid"]
    for key, expected in (("schema_version", SPEC_SCHEMA_VERSION),):
        if not _same(spec.get(key), expected):
            failures.append("formal_authority_v2_spec_mismatch:" + key)
    for key in (
        "authority_id", "generation_id", "generation_scope",
        "current_evidence_id", "current_status",
    ):
        if not isinstance(spec.get(key), str) or not spec[key]:
            failures.append("formal_authority_v2_spec_value_invalid:" + key)
    if not _safe_relative(spec.get("index_relative_path")):
        failures.append("formal_authority_v2_spec_index_path_invalid")
    failures.extend(_identity_failures(
        spec.get("current_report_identity"), "formal_authority_v2_current_report"
    ))
    failures.extend(_identity_failures(
        spec.get("canonical_child_identity"), "formal_authority_v2_canonical_child"
    ))
    paths = {
        PREDECESSOR_INDEX_IDENTITY["path"], SUPERSEDED_REPORT["path"],
        spec.get("index_relative_path"),
    }
    for identity_key in ("current_report_identity", "canonical_child_identity"):
        value = spec.get(identity_key)
        if isinstance(value, dict):
            paths.add(value.get("path"))
    if len(paths) != 5:
        failures.append("formal_authority_v2_spec_artifact_path_collision")
    canonical = spec.get("canonical_expected")
    canonical_keys = {
        "schema_version", "binding_kind", "canonical_source_root",
        "file_count", "source_contract_pass", "indexer_only_detected",
        "test_only", "architecture_blockers",
    }
    if not isinstance(canonical, dict) or set(canonical) != canonical_keys:
        failures.append("formal_authority_v2_canonical_expected_invalid")
    else:
        if not _safe_relative(canonical.get("canonical_source_root")):
            failures.append("formal_authority_v2_canonical_root_invalid")
        if type(canonical.get("file_count")) is not int or canonical["file_count"] <= 0:
            failures.append("formal_authority_v2_canonical_file_count_invalid")
        if canonical.get("source_contract_pass") is not True:
            failures.append("formal_authority_v2_canonical_source_not_passed")
        if canonical.get("indexer_only_detected") is not False:
            failures.append("formal_authority_v2_canonical_indexer_only")
        if canonical.get("test_only") is not False:
            failures.append("formal_authority_v2_canonical_test_only")
        if canonical.get("architecture_blockers") != []:
            failures.append("formal_authority_v2_canonical_blockers_nonempty")
    counts = spec.get("test_counts")
    if not isinstance(counts, dict) or set(counts) != set(DEFAULT_TEST_COUNTS):
        failures.append("formal_authority_v2_test_counts_schema_invalid")
    elif any(type(value) is not int or value < 0 for value in counts.values()):
        failures.append("formal_authority_v2_test_counts_invalid")
    for key in ("report_blockers", "gate_blockers"):
        value = spec.get(key)
        if (
            not isinstance(value, list)
            or not value
            or value != sorted(set(value))
            or not all(isinstance(item, str) and item for item in value)
        ):
            failures.append("formal_authority_v2_spec_blockers_invalid:" + key)
    required_gate_blockers = set(spec.get("report_blockers", [])) | {
        "FORMAL_LATENCY_NOT_VALIDATED"
    }
    if not required_gate_blockers.issubset(set(spec.get("gate_blockers", []))):
        failures.append("formal_authority_v2_gate_blockers_incomplete")
    return list(dict.fromkeys(failures))


def expected_index_payload(spec: Mapping[str, Any]) -> Dict[str, Any]:
    failures = _spec_failures(spec)
    if failures:
        raise ValueError("invalid generation spec: " + ",".join(failures))
    current_id = spec["current_evidence_id"]
    predecessor_id = SUPERSEDED_REPORT["evidence_id"]
    current_identity = spec["current_report_identity"]
    canonical_identity = spec["canonical_child_identity"]
    entries = [
        {
            "evidence_id": predecessor_id,
            "generation_id": SUPERSEDED_REPORT["generation_id"],
            "path": SUPERSEDED_REPORT["path"],
            "size_bytes": SUPERSEDED_REPORT["size_bytes"],
            "sha256": SUPERSEDED_REPORT["sha256"],
            "status": "SUPERSEDED_NON_CURRENT",
            "lifecycle": "SUPERSEDED",
            "is_current": False,
            "scope": "blocked_offline_ros1_runtime_source_admission_not_field_delivery",
            "report_kind": SUPERSEDED_REPORT["report_kind"],
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
            "path": current_identity["path"],
            "size_bytes": current_identity["size_bytes"],
            "sha256": current_identity["sha256"],
            "status": spec["current_status"],
            "lifecycle": "CURRENT",
            "is_current": True,
            "scope": spec["generation_scope"],
            "report_kind": "perception_v2_frozen_offline_regression",
            "regression_passed": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
            "predecessor_evidence_id": predecessor_id,
            "superseded_by_evidence_id": None,
        },
    ]
    child_id = "ros1_noetic_canonical_source_admission_20260815_v4"
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_id": spec["authority_id"],
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
        "entries": entries,
        "child_artifacts": [{
            "artifact_id": child_id,
            "parent_evidence_id": current_id,
            "role": "canonical_source_admission_child",
            "path": canonical_identity["path"],
            "size_bytes": canonical_identity["size_bytes"],
            "sha256": canonical_identity["sha256"],
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
        return ["formal_authority_v2_predecessor_index_invalid"]
    if payload.get("schema_version") != "ros1_formal_admission_evidence_authority/v2":
        failures.append("formal_authority_v2_predecessor_schema_invalid")
    if payload.get("current_evidence_id") != (
        PREDECESSOR_AUTHORITY_CURRENT_EVIDENCE["evidence_id"]
    ):
        failures.append("formal_authority_v2_predecessor_current_invalid")
    entries = payload.get("entries")
    currents = [
        item for item in entries
        if isinstance(item, dict) and item.get("is_current") is True
    ] if isinstance(entries, list) else []
    if len(currents) != 1:
        failures.append("formal_authority_v2_predecessor_current_count_invalid")
    elif any(
        not _same(
            currents[0].get(key), PREDECESSOR_AUTHORITY_CURRENT_EVIDENCE[key]
        )
        for key in ("evidence_id", "generation_id", "path", "size_bytes", "sha256")
    ):
        failures.append("formal_authority_v2_predecessor_binding_invalid")
    return failures


def _plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _pytest_parametrize_shape(function: Any) -> Tuple[bool, int]:
    count = 1
    parametrized = False
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = decorator.func
        parts: List[str] = []
        while isinstance(name, ast.Attribute):
            parts.append(name.attr)
            name = name.value
        if isinstance(name, ast.Name):
            parts.append(name.id)
        if not parts or parts[0] != "parametrize" or len(decorator.args) < 2:
            continue
        values = ast.literal_eval(decorator.args[1])
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError("pytest parametrize values must be non-empty")
        parametrized = True
        count *= len(values)
    return parametrized, count


def _static_pytest_case_ids(workspace: Path, relative: str) -> Tuple[str, ...]:
    unused, identity, raw = _regular_identity(workspace, relative)
    tree = ast.parse(
        raw.decode("utf-8"), filename=identity["path"], feature_version=8
    )
    seen = set()
    case_ids: List[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        if node.name in seen:
            raise ValueError("duplicate pytest function")
        seen.add(node.name)
        parametrized, count = _pytest_parametrize_shape(node)
        base = relative + "::" + node.name
        if parametrized:
            case_ids.extend(base + "[{}]".format(index) for index in range(count))
        else:
            case_ids.append(base)
    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("pytest source has zero or duplicate cases")
    return tuple(sorted(case_ids))


def _validate_pytest_file_execution_evidence(
    matrix: Any, workspace: Path
) -> List[str]:
    """Recompute the 15-file/109-case isolated execution ledger."""
    failures: List[str] = []
    if not isinstance(matrix, dict):
        return ["formal_authority_v2_pytest_matrix_invalid"]
    root = Path(workspace).resolve(strict=True)
    expected_policy = dict(EXPECTED_PYTEST_POLICY)
    expected_policy["fixed_cwd"] = str(root)
    policy = matrix.get("pytest_style_file_execution_policy")
    if not _same(policy, expected_policy):
        failures.append("formal_authority_v2_pytest_execution_policy_invalid")

    inventory = matrix.get("pytest_style_file_inventory")
    inventory_keys = {"ordered_paths", "unique_file_count", "failures"}
    if not isinstance(inventory, dict) or set(inventory) != inventory_keys:
        failures.append("formal_authority_v2_pytest_inventory_schema_invalid")
        ordered_paths: List[Any] = []
    else:
        ordered_paths = inventory.get("ordered_paths")
        if ordered_paths != list(EXPECTED_PYTEST_FILE_PATHS):
            failures.append("formal_authority_v2_pytest_inventory_paths_invalid")
        if inventory.get("unique_file_count") != EXPECTED_PYTEST_FILE_COUNT:
            failures.append("formal_authority_v2_pytest_inventory_count_invalid")
        if inventory.get("failures") != []:
            failures.append("formal_authority_v2_pytest_inventory_failures_nonempty")

    records = matrix.get("pytest_style_file_records")
    if not isinstance(records, list):
        return failures + ["formal_authority_v2_pytest_records_invalid"]
    if len(records) != EXPECTED_PYTEST_FILE_COUNT:
        failures.append("formal_authority_v2_pytest_record_denominator_invalid")

    actual_paths: List[Any] = []
    actual_hashes: List[Any] = []
    global_ids: List[str] = []
    totals = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0}
    empty_sha = hashlib.sha256(b"").hexdigest()
    for index, record in enumerate(records):
        prefix = "formal_authority_v2_pytest_record:{}:".format(index)
        if not isinstance(record, dict) or set(record) != PYTEST_RECORD_KEYS:
            _append(failures, prefix + "schema_invalid")
            continue
        path = record.get("path")
        actual_paths.append(path)
        expected_path = (
            EXPECTED_PYTEST_FILE_PATHS[index]
            if index < len(EXPECTED_PYTEST_FILE_PATHS) else None
        )
        if path != expected_path:
            _append(failures, prefix + "path_or_order_invalid")
        try:
            unused, live_identity, unused_raw = _regular_identity(root, path)
            live_ids = list(_static_pytest_case_ids(root, path))
        except (OSError, UnicodeError, SyntaxError, ValueError, TypeError):
            _append(failures, prefix + "live_source_invalid")
            live_identity = None
            live_ids = []

        for role in ("pre_identity", "post_identity"):
            identity = record.get(role)
            if (
                not isinstance(identity, dict)
                or set(identity) != {"path", "size_bytes", "sha256"}
                or not _same(identity, live_identity)
            ):
                _append(failures, prefix + role + "_mismatch")
        if not _same(record.get("pre_identity"), record.get("post_identity")):
            _append(failures, prefix + "source_changed")
        post_identity = record.get("post_identity")
        actual_hashes.append(
            post_identity.get("sha256") if isinstance(post_identity, dict) else None
        )

        expected_ids = record.get("expected_ids")
        executed_ids = record.get("executed_ids")
        if (
            not isinstance(expected_ids, list)
            or expected_ids != live_ids
            or len(expected_ids) != len(set(expected_ids))
        ):
            _append(failures, prefix + "expected_ids_mismatch")
            expected_ids = expected_ids if isinstance(expected_ids, list) else []
        if executed_ids != expected_ids:
            _append(failures, prefix + "executed_ids_mismatch")
        global_ids.extend(item for item in expected_ids if isinstance(item, str))

        allocations = record.get("allocations")
        allocation_ids: List[str] = []
        if not isinstance(allocations, list) or not allocations:
            _append(failures, prefix + "allocations_invalid")
        else:
            for allocation in allocations:
                if not isinstance(allocation, dict) or set(allocation) != {
                    "scope", "suite_id", "expected_ids"
                }:
                    _append(failures, prefix + "allocation_schema_invalid")
                    continue
                ids = allocation.get("expected_ids")
                if (
                    allocation.get("scope") not in {
                        "frozen_full", "frozen_selected", "post_freeze",
                        "post_fix", "current_generation",
                    }
                    or not isinstance(allocation.get("suite_id"), str)
                    or not allocation["suite_id"]
                    or not isinstance(ids, list)
                    or not ids
                    or len(ids) != len(set(ids))
                    or any(not isinstance(item, str) for item in ids)
                ):
                    _append(failures, prefix + "allocation_invalid")
                    continue
                allocation_ids.extend(ids)
        if (
            len(allocation_ids) != len(set(allocation_ids))
            or sorted(allocation_ids) != expected_ids
        ):
            _append(failures, prefix + "allocation_coverage_mismatch")

        count_values: Dict[str, int] = {}
        for key in totals:
            value = record.get(key)
            if not _plain_int(value) or value < 0:
                _append(failures, prefix + "count_invalid:" + key)
                value = 0
            count_values[key] = value
            totals[key] += value
        expected_count = len(live_ids)
        if (
            count_values["collected"] != expected_count
            or count_values["passed"] != expected_count
            or count_values["failed"] != 0
            or count_values["skipped"] != 0
        ):
            _append(failures, prefix + "count_invariant_failed")
        if record.get("failures") != []:
            _append(failures, prefix + "failures_nonempty")
        if record.get("source_unchanged") is not True:
            _append(failures, prefix + "source_unchanged_invalid")
        if record.get("validated_pass") is not True:
            _append(failures, prefix + "validated_pass_invalid")

        marker = record.get("marker_payload")
        if not isinstance(marker, dict) or set(marker) != PYTEST_MARKER_KEYS:
            _append(failures, prefix + "marker_schema_invalid")
            marker = {}
        marker_expected = {
            "schema_version": PYTEST_FILE_RESULT_SCHEMA_VERSION,
            "runner_kind": PYTEST_FILE_RESULT_RUNNER_KIND,
            "path": path,
            "size_bytes": (
                None if live_identity is None else live_identity["size_bytes"]
            ),
            "sha256": None if live_identity is None else live_identity["sha256"],
            "expected_ids": expected_ids,
            "executed_ids": expected_ids,
            "collected": expected_count,
            "passed": expected_count,
            "failed": 0,
            "skipped": 0,
            "exit": 0,
            "result": "PASS",
        }
        if not _same(marker, marker_expected):
            _append(failures, prefix + "marker_semantic_mismatch")
        marker_raw = json.dumps(
            marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        marker_sha = hashlib.sha256(marker_raw).hexdigest()
        if (
            record.get("marker_json_length_bytes") != len(marker_raw)
            or record.get("marker_json_sha256") != marker_sha
        ):
            _append(failures, prefix + "marker_canonical_identity_mismatch")

        command = record.get("command")
        if not isinstance(command, dict) or set(command) != PYTEST_COMMAND_KEYS:
            _append(failures, prefix + "command_schema_invalid")
            command = {}
        argv = command.get("argv")
        expected_argv_tail = [
            "-I", "-B", str(root / "audit_tools/run_pytest_style_tests.py"),
            "--single-file", "--workspace", str(root), "--target",
            str(root.joinpath(*PurePosixPath(path).parts)) if _safe_relative(path) else "",
        ]
        for import_root in EXPECTED_PYTEST_POLICY["import_roots"]:
            expected_argv_tail.extend(("--import-root", import_root))
        for case_id in expected_ids:
            expected_argv_tail.extend(("--expected-id", case_id))
        if (
            not isinstance(argv, list)
            or not argv
            or not isinstance(argv[0], str)
            or not argv[0]
            or argv[1:] != expected_argv_tail
        ):
            _append(failures, prefix + "isolated_command_invalid")
        expected_stdout = PYTEST_FILE_RESULT_PREFIX + marker_raw.decode("utf-8") + "\n"
        stdout_raw = expected_stdout.encode("utf-8")
        duration = command.get("duration_sec")
        if (
            command.get("cwd") != str(root)
            or command.get("exit_code") != 0
            or command.get("timed_out") is not False
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration < 0
        ):
            _append(failures, prefix + "command_result_invalid")
        expected_stdout_head = expected_stdout[:2000]
        expected_stdout_tail = expected_stdout[-2000:]
        if command.get("stdout_head") != expected_stdout_head:
            _append(failures, prefix + "stdout_head_mismatch")
        if command.get("stdout_tail") != expected_stdout_tail:
            _append(failures, prefix + "stdout_tail_mismatch")
        if (
            command.get("stdout_length_bytes") != len(stdout_raw)
            or command.get("stdout_length_chars") != len(expected_stdout)
            or command.get("stdout_sha256")
            != hashlib.sha256(stdout_raw).hexdigest()
        ):
            _append(failures, prefix + "stdout_identity_mismatch")
        if any(command.get(key) != "" for key in ("stderr_head", "stderr_tail")):
            _append(failures, prefix + "stderr_not_empty")
        if (
            command.get("stderr_length_bytes") != 0
            or command.get("stderr_length_chars") != 0
            or command.get("stderr_sha256") != empty_sha
        ):
            _append(failures, prefix + "stderr_identity_mismatch")

    if actual_paths != list(EXPECTED_PYTEST_FILE_PATHS):
        failures.append("formal_authority_v2_pytest_record_paths_invalid")
    if len(actual_paths) != len(set(actual_paths)):
        failures.append("formal_authority_v2_pytest_duplicate_path")
    if (
        len(actual_hashes) != EXPECTED_PYTEST_FILE_COUNT
        or any(not _valid_sha256(value) for value in actual_hashes)
        or len(actual_hashes) != len(set(actual_hashes))
    ):
        failures.append("formal_authority_v2_pytest_hash_set_invalid")
    if (
        len(global_ids) != EXPECTED_PYTEST_CASE_TOTAL
        or len(global_ids) != len(set(global_ids))
    ):
        failures.append("formal_authority_v2_pytest_case_set_invalid")
    expected_totals = {
        "collected": EXPECTED_PYTEST_CASE_TOTAL,
        "passed": EXPECTED_PYTEST_CASE_TOTAL,
        "failed": 0,
        "skipped": 0,
    }
    if totals != expected_totals:
        failures.append("formal_authority_v2_pytest_totals_invalid")
    return list(dict.fromkeys(failures))


def _validate_report(
    payload: Any, spec: Mapping[str, Any], workspace: Path, *, current: bool
) -> List[str]:
    prefix = (
        "formal_authority_v2_current_report"
        if current else "formal_authority_v2_superseded_report"
    )
    failures: List[str] = []
    if not isinstance(payload, dict):
        return [prefix + "_payload_invalid"]
    for key, expected in (
        ("report_kind", "perception_v2_frozen_offline_regression"),
        ("schema_version", 1),
        ("read_only", True),
        ("authorizes_motion", False),
        ("regression_passed", False),
        ("delivery_ready", False),
        ("publishes_ros_messages", False),
        ("ros_graph_started", False),
        ("camera_opened", False),
        ("hardware_connected", False),
    ):
        if not _same(payload.get(key), expected):
            _append(failures, prefix + "_semantic_mismatch:" + key)
    if not current:
        return failures
    matrix = payload.get("test_matrix")
    if not isinstance(matrix, dict):
        failures.append(prefix + "_test_matrix_invalid")
    else:
        for key, expected in spec["test_counts"].items():
            if not _same(matrix.get(key), expected):
                _append(failures, prefix + "_test_count_mismatch:" + key)
        if matrix.get("failures") != []:
            failures.append(prefix + "_test_failures_nonempty")
        failures.extend(_validate_pytest_file_execution_evidence(matrix, workspace))
    source_drift = payload.get("source_drift")
    if not isinstance(source_drift, dict) or source_drift.get("unchanged") is not True:
        failures.append(prefix + "_source_drift_not_unchanged")
    summary = payload.get("delivery_gate_summary")
    if not isinstance(summary, dict):
        return failures + [prefix + "_delivery_gate_summary_invalid"]
    formal = summary.get("formal_field_evidence_gate")
    for key, expected in (
        ("formal_four_scene_frame_denominator", 0),
        ("formal_tf_pass", False),
        ("formal_3d_pass", False),
        ("formal_latency_pass", False),
        ("validated_pass", False),
    ):
        if not isinstance(formal, dict) or not _same(formal.get(key), expected):
            _append(failures, prefix + "_formal_gate_mismatch:" + key)
    field = summary.get("ros1_field_gate")
    for key, expected in (
        ("source_contract_pass", True),
        ("source_implementation_pass", True),
        ("install_evidence_pass", False),
        ("validated_pass", False),
    ):
        if not isinstance(field, dict) or not _same(field.get(key), expected):
            _append(failures, prefix + "_field_gate_mismatch:" + key)
    if not isinstance(field, dict) or not _same(
        field.get("field_evidence_blockers"),
        ["ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING"],
    ):
        failures.append(prefix + "_field_evidence_blockers_invalid")
    if not isinstance(field, dict) or not _same(
        field.get("build_install_blockers"),
        ["ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED"],
    ):
        failures.append(prefix + "_build_install_blockers_invalid")
    canonical = summary.get("ros1_canonical_source_admission_gate")
    canonical_identity = (
        canonical.get("manifest_identity") if isinstance(canonical, dict) else None
    )
    if not isinstance(canonical, dict) or canonical.get("validated_pass") is not True:
        failures.append(prefix + "_canonical_gate_not_validated")
    if not _same(canonical_identity, spec["canonical_child_identity"]):
        failures.append(prefix + "_canonical_identity_mismatch")
    authority = summary.get("evidence_authority_gate")
    if (
        not isinstance(authority, dict)
        or authority.get("current_evidence_id")
        != EMBEDDED_RUNNER_AUTHORITY_EVIDENCE_ID
        or authority.get("authorizes_field_delivery") is not False
        or authority.get("delivery_ready") is not False
    ):
        failures.append(prefix + "_embedded_predecessor_authority_invalid")
    environment = summary.get("environment_gate")
    if (
        not isinstance(environment, dict)
        or environment.get("source_build_failure") is not False
        or "WSL_E_ACCESSDENIED_BEFORE_SHELL_OR_BUILD" not in environment.get("active_blockers", [])
    ):
        failures.append(prefix + "_environment_blocker_invalid")
    blockers = summary.get("delivery_blockers")
    if not _same(blockers, list(spec["report_blockers"])):
        failures.append(prefix + "_required_blockers_missing")
    if summary.get("architecture_blockers") != []:
        failures.append(prefix + "_architecture_blockers_not_empty")
    if not _same(
        summary.get("field_evidence_blockers"),
        ["ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING"],
    ):
        failures.append(prefix + "_summary_field_evidence_blockers_invalid")
    if not _same(
        summary.get("build_install_blockers"),
        ["ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED"],
    ):
        failures.append(prefix + "_summary_build_install_blockers_invalid")
    if not _same(
        summary.get("formal_field_blockers"),
        [
            "FORMAL_3D_NOT_VALIDATED",
            "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
            "FORMAL_LATENCY_NOT_VALIDATED",
            "FORMAL_TF_NOT_VALIDATED",
        ],
    ):
        failures.append(prefix + "_summary_formal_blockers_invalid")
    if summary.get("delivery_ready") is not False:
        failures.append(prefix + "_delivery_summary_not_blocked")
    return failures


def _validate_canonical_child(
    payload: Any, workspace: Path, spec: Mapping[str, Any]
) -> List[str]:
    failures: List[str] = []
    expected_keys = {
        "architecture_blockers", "binding_kind", "binding_sha256",
        "canonical_source_root", "contract_sha256", "entries", "file_count",
        "indexer_only_detected", "schema_version", "source_contract_pass",
        "source_set_sha256", "test_only",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return ["formal_authority_v2_canonical_schema_invalid"]
    expected = spec["canonical_expected"]
    for key, value in expected.items():
        if not _same(payload.get(key), value):
            _append(failures, "formal_authority_v2_canonical_semantic_mismatch:" + key)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return failures + ["formal_authority_v2_canonical_entries_invalid"]
    canonical_entries: List[Mapping[str, Any]] = []
    seen = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            _append(failures, "formal_authority_v2_canonical_entry_invalid:" + str(index))
            continue
        path = item.get("path")
        if (
            not _safe_relative(path)
            or path in seen
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] <= 0
            or not _valid_sha256(item.get("sha256"))
        ):
            _append(failures, "formal_authority_v2_canonical_entry_invalid:" + str(index))
            continue
        seen.add(path)
        canonical_entries.append(dict(item))
        source_relative = payload["canonical_source_root"] + "/" + path
        try:
            unused, identity, unused_raw = _regular_identity(workspace, source_relative)
        except (OSError, ValueError, UnicodeError):
            _append(failures, "formal_authority_v2_canonical_live_source_unreadable:" + path)
            continue
        if (
            identity["size_bytes"] != item["size_bytes"]
            or identity["sha256"] != item["sha256"]
        ):
            _append(failures, "formal_authority_v2_canonical_live_source_mismatch:" + path)
    ordered = sorted(canonical_entries, key=lambda item: item["path"])
    if entries != ordered or payload.get("file_count") != len(ordered):
        failures.append("formal_authority_v2_canonical_entry_set_invalid")
    if payload.get("source_set_sha256") != _canonical_json_sha(ordered):
        failures.append("formal_authority_v2_canonical_source_set_sha256_mismatch")
    without_binding = dict(payload)
    claimed = without_binding.pop("binding_sha256", None)
    if claimed != _canonical_json_sha(without_binding):
        failures.append("formal_authority_v2_canonical_binding_sha256_mismatch")
    return failures


def validate_formal_admission_evidence_authority_v2(
    workspace: Path, payload: Any, spec: Mapping[str, Any]
) -> Dict[str, Any]:
    failures = _spec_failures(spec)
    identities: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "authority_id": spec.get("authority_id") if isinstance(spec, dict) else None,
        "generation_id": spec.get("generation_id") if isinstance(spec, dict) else None,
        "generation_scope": spec.get("generation_scope") if isinstance(spec, dict) else None,
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
        "historical_runtime_not_implemented_observation_superseded": False,
        "current_evidence": None,
        "artifact_identities": identities,
        "failures": failures,
    }
    if failures:
        return result
    expected = expected_index_payload(spec)
    if not isinstance(payload, dict):
        failures.append("formal_authority_v2_payload_invalid")
        return result
    if set(payload) != set(expected):
        failures.append("formal_authority_v2_top_level_keys_invalid")
    for key in set(expected) - {"entries", "child_artifacts"}:
        if not _same(payload.get(key), expected[key]):
            _append(failures, "formal_authority_v2_top_level_mismatch:" + key)
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != 2:
        failures.append("formal_authority_v2_entry_count_invalid")
        entries = entries if isinstance(entries, list) else []
    by_id: Dict[str, Mapping[str, Any]] = {}
    currents: List[Mapping[str, Any]] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            _append(failures, "formal_authority_v2_entry_invalid:" + str(index))
            continue
        evidence_id = item.get("evidence_id")
        if evidence_id in by_id:
            failures.append("formal_authority_v2_duplicate_evidence_id")
        if isinstance(evidence_id, str):
            by_id[evidence_id] = item
        if item.get("is_current") is True:
            currents.append(item)
    expected_by_id = {item["evidence_id"]: item for item in expected["entries"]}
    if set(by_id) != set(expected_by_id):
        failures.append("formal_authority_v2_entry_set_invalid")
    for evidence_id, expected_entry in expected_by_id.items():
        if not _same(by_id.get(evidence_id), expected_entry):
            _append(failures, "formal_authority_v2_entry_mismatch:" + evidence_id)
    if len(currents) != 1:
        failures.append("formal_authority_v2_current_count_invalid")
    elif (
        currents[0].get("evidence_id") != spec["current_evidence_id"]
        or currents[0].get("status") != spec["current_status"]
    ):
        failures.append("formal_authority_v2_current_marker_invalid")
    if not _same(payload.get("child_artifacts"), expected["child_artifacts"]):
        failures.append("formal_authority_v2_child_artifacts_invalid")

    child = expected["child_artifacts"][0]
    artifacts: Sequence[Tuple[str, Mapping[str, Any], str]] = (
        ("predecessor_index", PREDECESSOR_INDEX_IDENTITY, "predecessor_index"),
        (SUPERSEDED_REPORT["evidence_id"], SUPERSEDED_REPORT, "superseded_report"),
        (spec["current_evidence_id"], spec["current_report_identity"], "current_report"),
        (child["artifact_id"], spec["canonical_child_identity"], "canonical_child"),
    )
    for artifact_id, expected_identity, role in artifacts:
        try:
            unused, identity, raw = _regular_identity(workspace, expected_identity["path"])
            identity["artifact_id"] = artifact_id
            identities.append(identity)
        except (OSError, ValueError, UnicodeError):
            _append(failures, "formal_authority_v2_artifact_unreadable:" + artifact_id)
            continue
        if identity["size_bytes"] != expected_identity["size_bytes"]:
            _append(failures, "formal_authority_v2_artifact_size_mismatch:" + artifact_id)
        if identity["sha256"] != expected_identity["sha256"]:
            _append(failures, "formal_authority_v2_artifact_sha256_mismatch:" + artifact_id)
        try:
            artifact_payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            _append(failures, "formal_authority_v2_artifact_strict_json_invalid:" + artifact_id)
            continue
        if role == "predecessor_index":
            failures.extend(_validate_predecessor_index(artifact_payload))
        elif role == "superseded_report":
            failures.extend(_validate_report(
                artifact_payload, spec, Path(workspace), current=False
            ))
        elif role == "current_report":
            failures.extend(_validate_report(
                artifact_payload, spec, Path(workspace), current=True
            ))
        else:
            failures.extend(_validate_canonical_child(artifact_payload, Path(workspace), spec))
    failures[:] = list(dict.fromkeys(failures))
    if not failures:
        result["validated_pass"] = True
        result["accepted_as_offline_release_selection_authority"] = True
        result["ros1_source_implementation_complete"] = True
        result["ros1_source_architecture_blockers"] = []
        result["historical_runtime_not_implemented_observation_superseded"] = True
        result["current_evidence"] = dict(expected["entries"][1])
    return result


def write_index_exclusive(path: Path, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Create one immutable candidate index; never overwrite an old index."""
    target = Path(path)
    raw = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "path": target.name,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def index_identity(workspace: Path, index_relative_path: str) -> Dict[str, Any]:
    unused, identity, unused_raw = _regular_identity(workspace, index_relative_path)
    return identity


def load_and_resolve_formal_admission_evidence_authority_v2(
    workspace: Path,
    spec: Mapping[str, Any],
    index_trust_anchor: Mapping[str, Any],
) -> Dict[str, Any]:
    """Resolve only the caller-fixed path and externally supplied identity."""
    root = Path(workspace).resolve(strict=True)
    failures = _spec_failures(spec)
    identity: Dict[str, Any] = {}
    anchor_failures = _identity_failures(
        index_trust_anchor, "formal_authority_v2_index_anchor"
    )
    failures.extend(anchor_failures)
    if not anchor_failures and index_trust_anchor["path"] != spec["index_relative_path"]:
        failures.append("formal_authority_v2_index_anchor_path_mismatch")
    raw = b""
    if not failures:
        try:
            unused, identity, raw = _regular_identity(root, spec["index_relative_path"])
        except (OSError, ValueError, UnicodeError):
            failures.append("formal_authority_v2_index_unreadable")
    if identity and not _same(identity, dict(index_trust_anchor)):
        if identity.get("path") != index_trust_anchor.get("path"):
            failures.append("formal_authority_v2_index_path_mismatch")
        if identity.get("size_bytes") != index_trust_anchor.get("size_bytes"):
            failures.append("formal_authority_v2_index_size_mismatch")
        if identity.get("sha256") != index_trust_anchor.get("sha256"):
            failures.append("formal_authority_v2_index_sha256_mismatch")
    try:
        payload = _strict_json_bytes(raw) if raw else None
    except (UnicodeError, ValueError, json.JSONDecodeError):
        failures.append("formal_authority_v2_index_strict_json_invalid")
        payload = None
    validation = validate_formal_admission_evidence_authority_v2(root, payload, spec)
    for failure in failures:
        _append(validation["failures"], failure)
    if validation["failures"]:
        validation["validated_pass"] = False
        validation["accepted_as_offline_release_selection_authority"] = False
        validation["ros1_source_implementation_complete"] = False
        validation["ros1_source_architecture_blockers"] = [
            "AUTHORITY_NOT_VALIDATED"
        ]
        validation[
            "historical_runtime_not_implemented_observation_superseded"
        ] = False
        validation["current_evidence"] = None
    validation["index_identity"] = identity
    validation["expected_index_identity"] = dict(index_trust_anchor)
    validation["index_relative_path"] = spec.get("index_relative_path")
    validation["filename_mtime_selection_forbidden"] = True
    return validation


def production_generation_spec() -> Dict[str, Any]:
    """Return the host-fixed immutable v3-report/v4-canonical generation."""
    return make_generation_spec(
        current_report_identity=PRODUCTION_CURRENT_REPORT_IDENTITY,
        canonical_child_identity=PRODUCTION_CANONICAL_CHILD_IDENTITY,
        index_relative_path=PRODUCTION_INDEX_RELATIVE_PATH,
        canonical_expected=PRODUCTION_CANONICAL_EXPECTED,
    )


def load_and_resolve_current_authority(
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve the one production index through its external host anchor."""
    return load_and_resolve_formal_admission_evidence_authority_v2(
        workspace,
        production_generation_spec(),
        PRODUCTION_INDEX_TRUST_ANCHOR,
    )
