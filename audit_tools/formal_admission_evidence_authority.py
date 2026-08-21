"""Trust-anchored selector for the ROS1 formal-admission offline generation.

This authority is intentionally narrower than field readiness.  A successful
selection only identifies one blocked offline regression report and its
canonical-source child.  It can never authorize field evidence, delivery,
ROS, a camera, or motion.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "ros1_formal_admission_evidence_authority/v1"
AUTHORITY_ID = "ros1-formal-admission-evidence-authority-20260815-v1"
GENERATION_ID = "ros1_formal_admission_20260815_v1"
GENERATION_SCOPE = (
    "blocked_offline_ros1_formal_admission_generation_not_field_delivery"
)
CURRENT_EVIDENCE_ID = "ros1_formal_admission_offline_regression_20260815_v1"
CURRENT_STATUS = "CURRENT_BLOCKED_ROS1_FORMAL_ADMISSION_OFFLINE_BASELINE"
PREDECESSOR_EVIDENCE_ID = "ros1_canonical_source_binding_v7"
SELECTION_AUTHORITY = (
    "FIXED_INDEX_PATH_EXTERNAL_SIZE_SHA256_STRICT_JSON_AND_SEMANTIC_RECOMPUTE"
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
INDEX_RELATIVE_PATH = Path(
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_v1.json"
)
CURRENT_REPORT_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_ros1_formal_admission_v1.json"
)
CANONICAL_CHILD_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_noetic_canonical_source_admission_20260815_v2.json"
)
PREDECESSOR_REPORT_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json"
)
PREDECESSOR_INDEX_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "perception_v2_evidence_authority_index_20260814_v1.json"
)

# This host-owned anchor is filled only after the new index is exclusively
# created.  The index cannot self-assert either value.
INDEX_TRUST_ANCHOR: Mapping[str, Any] = {
    "path": INDEX_RELATIVE_PATH.as_posix(),
    "size_bytes": 4254,
    "sha256": "443550161d9ad1bcb90a5e77870aeadf1bb5b8cbce8b36adc867edc2ac91166b",
}

PREDECESSOR_INDEX_IDENTITY: Mapping[str, Any] = {
    "path": PREDECESSOR_INDEX_RELATIVE_PATH,
    "size_bytes": 2620,
    "sha256": "b4fcfb11c37cf44a4be61cd14d4cf1e28eee5657037887e403a021e9959a5283",
    "status": "HISTORICAL_PREVIOUS_GENERATION_AUTHORITY",
    "lifecycle": "HISTORICAL_SUPERSEDED",
}

EXPECTED_EVIDENCE_ENTRIES: Tuple[Mapping[str, Any], ...] = (
    {
        "evidence_id": PREDECESSOR_EVIDENCE_ID,
        "generation_id": "perception_v2_canonical_source_binding_20260814_v1",
        "path": PREDECESSOR_REPORT_RELATIVE_PATH,
        "size_bytes": 190747,
        "sha256": "dac31ed678ff7c3a8f4494c5b865f89a41715ee5555e80ef12a8ba4b895f6789",
        "status": "HISTORICAL_PRIOR_GENERATION_SUPERSEDED",
        "lifecycle": "HISTORICAL_SUPERSEDED",
        "is_current": False,
        "scope": "offline_regression_only_not_field_3d_tf_build_or_runtime",
        "report_kind": "perception_v2_frozen_offline_regression",
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "predecessor_evidence_id": None,
        "superseded_by_evidence_id": CURRENT_EVIDENCE_ID,
    },
    {
        "evidence_id": CURRENT_EVIDENCE_ID,
        "generation_id": GENERATION_ID,
        "path": CURRENT_REPORT_RELATIVE_PATH,
        "size_bytes": 318601,
        "sha256": "afff0f9b5fb98f5e1cdf8cf448741ea020b38c846ef1fab2680dbcfcaef426d6",
        "status": CURRENT_STATUS,
        "lifecycle": "CURRENT",
        "is_current": True,
        "scope": GENERATION_SCOPE,
        "report_kind": "perception_v2_frozen_offline_regression",
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "predecessor_evidence_id": PREDECESSOR_EVIDENCE_ID,
        "superseded_by_evidence_id": None,
    },
)

EXPECTED_CHILD_ARTIFACTS: Tuple[Mapping[str, Any], ...] = (
    {
        "artifact_id": "ros1_noetic_canonical_source_admission_20260815_v2",
        "parent_evidence_id": CURRENT_EVIDENCE_ID,
        "role": "canonical_source_admission_child",
        "path": CANONICAL_CHILD_RELATIVE_PATH,
        "size_bytes": 8219,
        "sha256": "2627c4f64e7ae8074ffe17bd9febbbc1d772c69cb01b6b97ed76d91419924e09",
        "status": "BOUND_BLOCKED_SOURCE_CHILD",
        "lifecycle": "CURRENT_CHILD",
        "is_current": False,
        "authorizes_field_delivery": False,
    },
)

EXPECTED_GATE_STATE: Mapping[str, Any] = {
    "regression_passed": False,
    "delivery_ready": False,
    "authorizes_field_delivery": False,
    "formal_four_scene_frame_denominator": 0,
    "formal_tf_pass": False,
    "formal_3d_pass": False,
    "ros1_noetic_field_install_pass": False,
    "ros1_noetic_runtime_pass": False,
    "active_blockers": [
        "FORMAL_3D_NOT_VALIDATED",
        "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
        "FORMAL_TF_NOT_VALIDATED",
        "ROS1_NOETIC_FIELD_INSTALL_NOT_VALIDATED",
        "ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED",
        "WSL_E_ACCESSDENIED_BEFORE_SHELL_OR_BUILD",
    ],
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
    if isinstance(expected, list):
        return (
            len(actual) == len(expected)
            and all(_same(left, right) for left, right in zip(actual, expected))
        )
    if isinstance(expected, tuple):
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
    return (not pure.is_absolute() and ".." not in pure.parts
            and pure.as_posix() == value)


def _regular_identity(workspace: Path, relative: str) -> Tuple[Path, Dict[str, Any], bytes]:
    if not _safe_relative(relative):
        raise ValueError("unsafe relative path")
    root = Path(workspace).resolve(strict=True)
    path = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if _is_linklike(current):
            raise ValueError("linklike path forbidden")
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


def expected_index_payload() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_id": AUTHORITY_ID,
        "generation_id": GENERATION_ID,
        "generation_scope": GENERATION_SCOPE,
        "immutable": True,
        "read_only": True,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_as_offline_release_selection_authority": True,
        "accepted_by_formal_field_evidence_consumer": False,
        "filename_mtime_selection_forbidden": True,
        "uses_filename_or_mtime_authority": False,
        "selection_authority": SELECTION_AUTHORITY,
        "current_evidence_id": CURRENT_EVIDENCE_ID,
        "current_required_status": CURRENT_STATUS,
        "predecessor_authority_index": dict(PREDECESSOR_INDEX_IDENTITY),
        "entries": [dict(item) for item in EXPECTED_EVIDENCE_ENTRIES],
        "child_artifacts": [dict(item) for item in EXPECTED_CHILD_ARTIFACTS],
        "gate_state": dict(EXPECTED_GATE_STATE),
    }


def _canonical_json_sha(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_frozen_report(payload: Any, *, current: bool) -> List[str]:
    prefix = "current_report" if current else "predecessor_report"
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
    expected_counts = {
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
        "current_generation_expected_total": 25,
        "current_generation_collected": 25,
        "current_generation_passed": 25,
        "current_generation_failed": 0,
    }
    if not isinstance(matrix, dict):
        failures.append(prefix + "_test_matrix_invalid")
    else:
        for key, expected in expected_counts.items():
            if not _same(matrix.get(key), expected):
                _append(failures, prefix + "_test_count_mismatch:" + key)
        if matrix.get("failures") != []:
            failures.append(prefix + "_test_failures_nonempty")
    if not isinstance(payload.get("source_drift"), dict) or (
        payload["source_drift"].get("unchanged") is not True
    ):
        failures.append(prefix + "_source_drift_not_unchanged")
    summary = payload.get("delivery_gate_summary")
    if not isinstance(summary, dict):
        return failures + [prefix + "_delivery_gate_summary_invalid"]
    formal = summary.get("formal_field_evidence_gate")
    for key, expected in (
        ("formal_four_scene_frame_denominator", 0),
        ("formal_tf_pass", False),
        ("formal_3d_pass", False),
        ("validated_pass", False),
    ):
        if not isinstance(formal, dict) or not _same(formal.get(key), expected):
            _append(failures, prefix + "_formal_gate_mismatch:" + key)
    field = summary.get("ros1_field_gate")
    for key in ("install_evidence_pass", "source_contract_pass", "validated_pass"):
        if not isinstance(field, dict) or field.get(key) is not False:
            _append(failures, prefix + "_field_install_gate_not_blocked:" + key)
    authority = summary.get("evidence_authority_gate")
    if not isinstance(authority, dict) or (
        authority.get("current_evidence_id") != PREDECESSOR_EVIDENCE_ID
        or authority.get("authorizes_field_delivery") is not False
    ):
        failures.append(prefix + "_embedded_predecessor_authority_invalid")
    canonical = summary.get("ros1_canonical_source_admission_gate")
    identity = canonical.get("manifest_identity") if isinstance(canonical, dict) else None
    child = EXPECTED_CHILD_ARTIFACTS[0]
    if not isinstance(identity, dict) or any(
        not _same(identity.get(key), child[key])
        for key in ("path", "size_bytes", "sha256")
    ):
        failures.append(prefix + "_canonical_child_identity_mismatch")
    blockers = summary.get("delivery_blockers")
    if not isinstance(blockers, list) or not set(EXPECTED_GATE_STATE["active_blockers"]).issubset(set(blockers)):
        failures.append(prefix + "_required_blockers_missing")
    return failures


def _validate_canonical_child(payload: Any, workspace: Path) -> List[str]:
    failures: List[str] = []
    expected_keys = {
        "architecture_blockers", "binding_kind", "binding_sha256",
        "canonical_source_root", "contract_sha256", "entries", "file_count",
        "indexer_only_detected", "schema_version", "source_contract_pass",
        "source_set_sha256", "test_only",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return ["canonical_child_schema_invalid"]
    expected_values = {
        "schema_version": 1,
        "binding_kind": "canonical_project_overlay",
        "canonical_source_root": "ros1_overlay_src/limo_cleanup_ros1_perception",
        "file_count": 42,
        "source_contract_pass": False,
        "indexer_only_detected": False,
        "test_only": False,
        "architecture_blockers": ["ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED"],
    }
    for key, expected in expected_values.items():
        if not _same(payload.get(key), expected):
            _append(failures, "canonical_child_semantic_mismatch:" + key)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return failures + ["canonical_child_entries_invalid"]
    canonical_entries: List[Mapping[str, Any]] = []
    seen = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            _append(failures, "canonical_child_entry_invalid:" + str(index))
            continue
        path = item.get("path")
        if (not _safe_relative(path) or path in seen
                or type(item.get("size_bytes")) is not int
                or item["size_bytes"] <= 0
                or not isinstance(item.get("sha256"), str)
                or len(item["sha256"]) != 64):
            _append(failures, "canonical_child_entry_invalid:" + str(index))
            continue
        seen.add(path)
        canonical_entries.append(dict(item))
        source_relative = payload["canonical_source_root"] + "/" + path
        try:
            unused, identity, unused_raw = _regular_identity(workspace, source_relative)
        except (OSError, ValueError):
            _append(failures, "canonical_child_live_source_unreadable:" + path)
            continue
        if identity["size_bytes"] != item["size_bytes"] or identity["sha256"] != item["sha256"]:
            _append(failures, "canonical_child_live_source_identity_mismatch:" + path)
    ordered = sorted(canonical_entries, key=lambda item: item["path"])
    if entries != ordered or payload.get("file_count") != len(ordered):
        failures.append("canonical_child_entry_set_or_order_invalid")
    source_set = _canonical_json_sha(ordered)
    if payload.get("source_set_sha256") != source_set:
        failures.append("canonical_child_source_set_sha256_mismatch")
    without_binding = dict(payload)
    claimed = without_binding.pop("binding_sha256", None)
    if claimed != _canonical_json_sha(without_binding):
        failures.append("canonical_child_binding_sha256_mismatch")
    return failures


def _validate_predecessor_index(payload: Any) -> List[str]:
    failures: List[str] = []
    if not isinstance(payload, dict):
        return ["predecessor_authority_payload_invalid"]
    if payload.get("current_evidence_id") != PREDECESSOR_EVIDENCE_ID:
        failures.append("predecessor_authority_current_id_invalid")
    entries = payload.get("entries")
    currents = [item for item in entries if isinstance(item, dict) and item.get("is_current") is True] if isinstance(entries, list) else []
    if len(currents) != 1:
        failures.append("predecessor_authority_current_count_invalid")
    elif any(
        not _same(currents[0].get(key), EXPECTED_EVIDENCE_ENTRIES[0][key])
        for key in ("evidence_id", "path", "size_bytes", "sha256", "delivery_ready", "regression_passed", "authorizes_field_delivery")
    ):
        failures.append("predecessor_authority_v7_binding_invalid")
    return failures


def validate_formal_admission_evidence_authority(
    workspace: Path, payload: Any
) -> Dict[str, Any]:
    failures: List[str] = []
    identities: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "authority_id": AUTHORITY_ID,
        "generation_id": GENERATION_ID,
        "generation_scope": GENERATION_SCOPE,
        "validated_pass": False,
        "accepted_as_offline_release_selection_authority": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "regression_passed": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "ros1_noetic_field_install_pass": False,
        "current_evidence": None,
        "artifact_identities": identities,
        "failures": failures,
    }
    expected = expected_index_payload()
    if not isinstance(payload, dict):
        failures.append("formal_authority_payload_invalid")
        return result
    if set(payload) != set(expected):
        failures.append("formal_authority_top_level_keys_invalid")
    for key in set(expected) - {"entries", "child_artifacts", "predecessor_authority_index", "gate_state"}:
        if not _same(payload.get(key), expected[key]):
            _append(failures, "formal_authority_top_level_mismatch:" + key)
    for key in ("predecessor_authority_index", "gate_state"):
        if not _same(payload.get(key), expected[key]):
            _append(failures, "formal_authority_top_level_mismatch:" + key)
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != len(EXPECTED_EVIDENCE_ENTRIES):
        failures.append("formal_authority_entry_count_invalid")
        entries = entries if isinstance(entries, list) else []
    by_id: Dict[str, Mapping[str, Any]] = {}
    currents: List[Mapping[str, Any]] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            _append(failures, "formal_authority_entry_invalid:" + str(index))
            continue
        evidence_id = item.get("evidence_id")
        if evidence_id in by_id:
            failures.append("formal_authority_duplicate_evidence_id")
        if isinstance(evidence_id, str):
            by_id[evidence_id] = item
        if item.get("is_current") is True:
            currents.append(item)
    expected_by_id = {item["evidence_id"]: item for item in EXPECTED_EVIDENCE_ENTRIES}
    if set(by_id) != set(expected_by_id):
        failures.append("formal_authority_entry_set_invalid")
    for evidence_id, expected_entry in expected_by_id.items():
        if not _same(by_id.get(evidence_id), expected_entry):
            _append(failures, "formal_authority_entry_mismatch:" + evidence_id)
    if len(currents) != 1:
        failures.append("formal_authority_current_count_invalid")
    elif currents[0].get("evidence_id") != CURRENT_EVIDENCE_ID or currents[0].get("status") != CURRENT_STATUS:
        failures.append("formal_authority_current_marker_invalid")
    children = payload.get("child_artifacts")
    if not _same(children, [dict(item) for item in EXPECTED_CHILD_ARTIFACTS]):
        failures.append("formal_authority_child_artifacts_invalid")

    artifacts: Sequence[Tuple[str, Mapping[str, Any], str]] = (
        ("predecessor_index", PREDECESSOR_INDEX_IDENTITY, "predecessor_index"),
        (PREDECESSOR_EVIDENCE_ID, EXPECTED_EVIDENCE_ENTRIES[0], "predecessor_report"),
        (CURRENT_EVIDENCE_ID, EXPECTED_EVIDENCE_ENTRIES[1], "current_report"),
        (EXPECTED_CHILD_ARTIFACTS[0]["artifact_id"], EXPECTED_CHILD_ARTIFACTS[0], "canonical_child"),
    )
    for artifact_id, expected_identity, role in artifacts:
        try:
            unused, identity, raw = _regular_identity(workspace, expected_identity["path"])
            identity["artifact_id"] = artifact_id
            identities.append(identity)
        except (OSError, ValueError, UnicodeError):
            _append(failures, "formal_authority_artifact_unreadable:" + artifact_id)
            continue
        if identity["size_bytes"] != expected_identity["size_bytes"]:
            _append(failures, "formal_authority_artifact_size_mismatch:" + artifact_id)
        if identity["sha256"] != expected_identity["sha256"]:
            _append(failures, "formal_authority_artifact_sha256_mismatch:" + artifact_id)
        try:
            artifact_payload = _strict_json_bytes(raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            _append(failures, "formal_authority_artifact_strict_json_invalid:" + artifact_id)
            continue
        if role == "predecessor_index":
            failures.extend(_validate_predecessor_index(artifact_payload))
        elif role == "predecessor_report":
            failures.extend(_validate_frozen_report(artifact_payload, current=False))
        elif role == "current_report":
            failures.extend(_validate_frozen_report(artifact_payload, current=True))
        else:
            failures.extend(_validate_canonical_child(artifact_payload, Path(workspace)))
    failures[:] = list(dict.fromkeys(failures))
    if not failures:
        result["validated_pass"] = True
        result["accepted_as_offline_release_selection_authority"] = True
        result["current_evidence"] = dict(EXPECTED_EVIDENCE_ENTRIES[1])
    return result


def load_and_resolve_formal_admission_evidence_authority(
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve only the fixed externally anchored index; never scan or sort."""
    root = Path(workspace).resolve(strict=True)
    failures: List[str] = []
    identity: Dict[str, Any] = {}
    try:
        unused, identity, raw = _regular_identity(root, INDEX_RELATIVE_PATH.as_posix())
    except (OSError, ValueError, UnicodeError):
        failures.append("formal_authority_index_unreadable")
        raw = b""
    if identity:
        if identity["path"] != INDEX_TRUST_ANCHOR["path"]:
            failures.append("formal_authority_index_path_mismatch")
        if identity["size_bytes"] != INDEX_TRUST_ANCHOR["size_bytes"]:
            failures.append("formal_authority_index_size_mismatch")
        if identity["sha256"] != INDEX_TRUST_ANCHOR["sha256"]:
            failures.append("formal_authority_index_sha256_mismatch")
    try:
        payload = _strict_json_bytes(raw) if raw else None
    except (UnicodeError, ValueError, json.JSONDecodeError):
        failures.append("formal_authority_index_strict_json_invalid")
        payload = None
    validation = validate_formal_admission_evidence_authority(root, payload)
    for failure in failures:
        _append(validation["failures"], failure)
    if validation["failures"]:
        validation["validated_pass"] = False
        validation["accepted_as_offline_release_selection_authority"] = False
        validation["current_evidence"] = None
    validation["index_identity"] = identity
    validation["expected_index_identity"] = dict(INDEX_TRUST_ANCHOR)
    validation["index_relative_path"] = INDEX_RELATIVE_PATH.as_posix()
    validation["filename_mtime_selection_forbidden"] = True
    return validation
