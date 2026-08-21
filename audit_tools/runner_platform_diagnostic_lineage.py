"""Fail-closed lineage for one unselected frozen runner diagnostic.

This is deliberately not a formal-evidence selector.  A successful result
only proves that the diagnostic remains the exact non-current bytes recorded
by the sidecar and that the frozen v4 authority remains the formal lineage
predecessor.  It can never authorize field evidence or delivery.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Dict, Iterable, List, Mapping, Tuple


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_RELATIVE_PATH = Path(
    "evidence/perception_v2_offline_20260813/"
    "runner_platform_composite_diagnostic_v2_lineage_v1.json"
)
DIAGNOSTIC_RELATIVE_PATH = Path(
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_runner_platform_composite_"
    "diagnostic_v2.json"
)
AUTHORITY_RELATIVE_PATH = Path(
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_v4.json"
)
SIDECAR_IDENTITY = {
    "path": SIDECAR_RELATIVE_PATH.as_posix(),
    "size_bytes": 2119,
    "sha256": "e9136ea9166e85ac276000355c5e38f3280cfbe40de34fb902d302a6c353fed4",
}
DIAGNOSTIC_IDENTITY = {
    "path": DIAGNOSTIC_RELATIVE_PATH.as_posix(),
    "size_bytes": 1212313,
    "sha256": "fdeffd18244633ccc7e9407dafa606a2799f03fb517be5b11c881aff8d146548",
}
AUTHORITY_IDENTITY = {
    "path": AUTHORITY_RELATIVE_PATH.as_posix(),
    "size_bytes": 5015,
    "sha256": "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded",
}
AUTHORITY_INDEX_ID = (
    "ros1-formal-admission-evidence-authority-index-20260815-v4"
)
AUTHORITY_CURRENT_EVIDENCE_ID = (
    "ros1_runner_platform_composite_offline_regression_20260815_v4"
)


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("nonfinite_json_number:" + value)


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_strict_object,
        parse_constant=_reject_nonfinite,
    )


def _linklike(path: Path) -> bool:
    info = os.lstat(str(path))
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        reparse and getattr(info, "st_file_attributes", 0) & reparse
    )


def _identity(root: Path, relative: Path) -> Mapping[str, Any]:
    root = Path(root).resolve(strict=True)
    path = root.joinpath(*relative.parts)
    candidate = path
    while candidate != root:
        if _linklike(candidate):
            raise OSError("linklike_artifact")
        parent = candidate.parent
        if parent == candidate:
            raise OSError("artifact_escaped_workspace")
        candidate = parent
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    before = os.lstat(str(resolved))
    if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1:
        raise OSError("artifact_not_unique_regular_file")
    raw = resolved.read_bytes()
    after = os.lstat(str(resolved))
    if (
        before.st_size != after.st_size
        or getattr(before, "st_dev", None) != getattr(after, "st_dev", None)
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
        or getattr(before, "st_mtime_ns", None)
        != getattr(after, "st_mtime_ns", None)
    ):
        raise OSError("artifact_changed_during_audit")
    return {
        "path": relative.as_posix(),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw": raw,
    }


def expected_sidecar_payload() -> Mapping[str, Any]:
    return {
        "schema_version": "perception_v2_runner_diagnostic_lineage/v1",
        "lineage_id": (
            "runner-platform-composite-diagnostic-v2-lineage-20260815-v1"
        ),
        "lineage_scope": "non_formal_unselected_local_diagnostic_only",
        "immutable": True,
        "read_only": True,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
        "delivery_ready": False,
        "filename_mtime_selection_forbidden": True,
        "uses_filename_or_mtime_authority": False,
        "selection_authority": (
            "FIXED_SIDECAR_PATH_SIZE_SHA256_STRICT_JSON_AND_"
            "LIVE_ARTIFACT_REOPEN"
        ),
        "diagnostic_artifact": {
            "evidence_id": "runner_platform_composite_diagnostic_v2_unselected",
            **DIAGNOSTIC_IDENTITY,
            "status": "NON_FORMAL_UNSELECTED",
            "lifecycle": "DIAGNOSTIC_ONLY",
            "is_current": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_evidence_consumer": False,
            "may_be_formal_predecessor": False,
        },
        "current_formal_authority": {
            "index_instance_id": AUTHORITY_INDEX_ID,
            **AUTHORITY_IDENTITY,
            "current_evidence_id": AUTHORITY_CURRENT_EVIDENCE_ID,
            "accepted_as_offline_release_selection_authority": True,
            "accepted_by_formal_field_evidence_consumer": False,
            "authorizes_field_delivery": False,
            "delivery_ready": False,
        },
        "formal_successor_policy": {
            "required_predecessor_index_instance_id": AUTHORITY_INDEX_ID,
            "diagnostic_artifact_may_be_predecessor": False,
        },
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "formal_latency_pass": False,
    }


def validate_runner_diagnostic_lineage(
    payload: Any, workspace_root: Path = WORKSPACE_ROOT,
) -> Mapping[str, Any]:
    failures: List[str] = []
    result: Dict[str, Any] = {
        "gate_id": "RUNNER_PLATFORM_DIAGNOSTIC_LINEAGE_V1",
        "read_only": True,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
        "delivery_ready": False,
        "formal_four_scene_frame_denominator": 0,
        "current_formal_authority_index_id": AUTHORITY_INDEX_ID,
        "diagnostic_status": "NON_FORMAL_UNSELECTED",
        "diagnostic_may_be_formal_predecessor": False,
        "observed_identities": {},
        "failures": failures,
        "validated_pass": False,
    }
    expected = expected_sidecar_payload()
    if type(payload) is not dict or payload != expected:
        failures.append("runner_diagnostic_lineage_payload_mismatch")
    try:
        diagnostic = _identity(workspace_root, DIAGNOSTIC_RELATIVE_PATH)
        authority = _identity(workspace_root, AUTHORITY_RELATIVE_PATH)
        result["observed_identities"] = {
            "diagnostic_artifact": {
                key: diagnostic[key] for key in DIAGNOSTIC_IDENTITY
            },
            "current_formal_authority": {
                key: authority[key] for key in AUTHORITY_IDENTITY
            },
        }
        if any(diagnostic[key] != DIAGNOSTIC_IDENTITY[key]
               for key in DIAGNOSTIC_IDENTITY):
            failures.append("runner_diagnostic_live_identity_mismatch")
        if any(authority[key] != AUTHORITY_IDENTITY[key]
               for key in AUTHORITY_IDENTITY):
            failures.append("runner_diagnostic_authority_identity_mismatch")
        diagnostic_payload = _strict_json(diagnostic["raw"])
        authority_payload = _strict_json(authority["raw"])
        if (
            not isinstance(diagnostic_payload, Mapping)
            or diagnostic_payload.get("regression_passed") is not False
            or diagnostic_payload.get("delivery_ready") is not False
            or diagnostic_payload.get("authorizes_motion") is not False
        ):
            failures.append("runner_diagnostic_not_fail_closed")
        if (
            not isinstance(authority_payload, Mapping)
            or authority_payload.get("index_instance_id") != AUTHORITY_INDEX_ID
            or authority_payload.get("current_evidence_id")
            != AUTHORITY_CURRENT_EVIDENCE_ID
            or authority_payload.get(
                "accepted_as_offline_release_selection_authority") is not True
            or authority_payload.get(
                "accepted_by_formal_field_evidence_consumer") is not False
            or authority_payload.get("authorizes_field_delivery") is not False
            or authority_payload.get("gate_state", {}).get("delivery_ready")
            is not False
        ):
            failures.append("runner_diagnostic_current_authority_semantics_invalid")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        failures.append("runner_diagnostic_live_artifact_reopen_failed")
    result["failures"] = sorted(set(failures))
    result["validated_pass"] = not result["failures"]
    return result


def load_and_validate_runner_diagnostic_lineage(
    sidecar_path: Path = None, workspace_root: Path = WORKSPACE_ROOT,
) -> Mapping[str, Any]:
    root = Path(workspace_root).resolve(strict=True)
    expected_path = root.joinpath(*SIDECAR_RELATIVE_PATH.parts)
    supplied = expected_path if sidecar_path is None else Path(sidecar_path)
    if supplied.resolve(strict=False) != expected_path.resolve(strict=False):
        return {
            "gate_id": "RUNNER_PLATFORM_DIAGNOSTIC_LINEAGE_V1",
            "read_only": True,
            "authorizes_motion": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_evidence_consumer": False,
            "delivery_ready": False,
            "validated_pass": False,
            "failures": ["runner_diagnostic_sidecar_path_mismatch"],
        }
    try:
        identity = _identity(root, SIDECAR_RELATIVE_PATH)
        if any(identity[key] != SIDECAR_IDENTITY[key]
               for key in SIDECAR_IDENTITY):
            raise ValueError("sidecar_identity_mismatch")
        payload = _strict_json(identity["raw"])
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {
            "gate_id": "RUNNER_PLATFORM_DIAGNOSTIC_LINEAGE_V1",
            "read_only": True,
            "authorizes_motion": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_evidence_consumer": False,
            "delivery_ready": False,
            "validated_pass": False,
            "failures": ["runner_diagnostic_sidecar_identity_or_json_invalid"],
        }
    result = dict(validate_runner_diagnostic_lineage(payload, root))
    result["sidecar_identity"] = {
        key: identity[key] for key in SIDECAR_IDENTITY
    }
    return result
