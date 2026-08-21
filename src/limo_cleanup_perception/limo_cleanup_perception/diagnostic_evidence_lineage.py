"""Fail-closed lineage admission for local diagnostic regression probes.

This module is deliberately independent from the frozen regression runner and
from formal field-evidence admission.  It only identifies three local probe
artifacts by exact path, byte count, SHA-256 digest, and lifecycle status.
Selection by filename or modification time is never authoritative.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Dict, Iterable, List, Mapping, Tuple


SCHEMA_VERSION = "perception_v2_diagnostic_probe_lineage/v1"
LINEAGE_ID = "perception-v2-p2-field-gate-probes-20260814-v1"
LINEAGE_SCOPE = "local_blocked_diagnostic_regression_checkpoints_only"
CURRENT_EVIDENCE_ID = "p2_field_gate_probe_20260814_v3"
CURRENT_REQUIRED_STATUS = "CURRENT_BLOCKED_DIAGNOSTIC_CHECKPOINT"
SELECTION_AUTHORITY = "EXACT_PATH_SIZE_SHA256_STATUS_ONLY"

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
SIDECAR_RELATIVE_PATH = Path(
    "evidence/perception_v2_offline_20260813/"
    "diagnostic_probe_lineage_20260814_v1.json"
)
DEFAULT_SIDECAR_PATH = _WORKSPACE_ROOT / SIDECAR_RELATIVE_PATH

EXPECTED_ENTRIES: Tuple[Mapping[str, Any], ...] = (
    {
        "evidence_id": "p2_field_gate_probe_20260814_v1",
        "path": (
            "C:\\Users\\DYH\\AppData\\Local\\Temp\\"
            "limo_perception_v2_p2_field_gate_probe_20260814_v1.json"
        ),
        "size_bytes": 0,
        "sha256": (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        ),
        "status": "ABORTED_EMPTY",
        "lifecycle": "ABORTED",
        "is_current": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
    },
    {
        "evidence_id": "p2_field_gate_probe_20260814_v2",
        "path": (
            "C:\\Users\\DYH\\AppData\\Local\\Temp\\"
            "limo_perception_v2_p2_field_gate_probe_20260814_v2.json"
        ),
        "size_bytes": 290678,
        "sha256": (
            "647595a6075149a709c607251dcea866"
            "09f1decfd0c23048b7b4130b2a57b2e3"
        ),
        "status": "SUPERSEDED_FAILED_TEST_CHECKPOINT",
        "lifecycle": "SUPERSEDED",
        "is_current": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
    },
    {
        "evidence_id": "p2_field_gate_probe_20260814_v3",
        "path": (
            "C:\\Users\\DYH\\AppData\\Local\\Temp\\"
            "limo_perception_v2_p2_field_gate_probe_20260814_v3.json"
        ),
        "size_bytes": 289500,
        "sha256": (
            "17222c15890ac41824b0fbba5268ef294"
            "48ba61b0e8707d63205f337ea6caab2"
        ),
        "status": CURRENT_REQUIRED_STATUS,
        "lifecycle": "CURRENT",
        "is_current": True,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
    },
)

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "lineage_id",
        "lineage_scope",
        "immutable",
        "read_only",
        "authorizes_motion",
        "authorizes_field_delivery",
        "accepted_by_formal_evidence_consumer",
        "filename_mtime_selection_forbidden",
        "uses_filename_or_mtime_authority",
        "selection_authority",
        "current_evidence_id",
        "current_required_status",
        "entries",
    }
)
_ENTRY_KEYS = frozenset(EXPECTED_ENTRIES[0])


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number is not permitted: " + value)


def _same_exact(actual: Any, expected: Any) -> bool:
    return type(actual) is type(expected) and actual == expected


def _is_linklike(path: Path) -> bool:
    info = os.lstat(str(path))
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _regular_file_identity(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if _is_linklike(path):
        raise ValueError("linklike artifact is forbidden")
    info = os.lstat(str(path))
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("artifact is not a regular file")
    payload = path.read_bytes()
    return {
        "path": str(path.resolve(strict=True)),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _append_once(failures: List[str], failure: str) -> None:
    if failure not in failures:
        failures.append(failure)


def expected_sidecar_payload() -> Dict[str, Any]:
    """Return a fresh canonical sidecar payload for exclusive generation."""
    return {
        "schema_version": SCHEMA_VERSION,
        "lineage_id": LINEAGE_ID,
        "lineage_scope": LINEAGE_SCOPE,
        "immutable": True,
        "read_only": True,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
        "filename_mtime_selection_forbidden": True,
        "uses_filename_or_mtime_authority": False,
        "selection_authority": SELECTION_AUTHORITY,
        "current_evidence_id": CURRENT_EVIDENCE_ID,
        "current_required_status": CURRENT_REQUIRED_STATUS,
        "entries": [dict(item) for item in EXPECTED_ENTRIES],
    }


def validate_diagnostic_evidence_lineage(
    payload: Any,
) -> Dict[str, Any]:
    """Reopen every diagnostic artifact and validate the exact lineage."""
    failures: List[str] = []
    observed_identities: List[Dict[str, Any]] = []
    current_entries: List[Mapping[str, Any]] = []

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "lineage_id": LINEAGE_ID,
        "lineage_scope": LINEAGE_SCOPE,
        "read_only": True,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_evidence_consumer": False,
        "filename_mtime_selection_forbidden": True,
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "delivery_ready": False,
        "failures": failures,
        "artifact_identities": observed_identities,
        "current_evidence": None,
        "validated_pass": False,
    }

    if not isinstance(payload, dict):
        failures.append("diagnostic_lineage_payload_not_object")
        return report
    if frozenset(payload) != _TOP_LEVEL_KEYS:
        failures.append("diagnostic_lineage_top_level_keys_invalid")

    expected_top = expected_sidecar_payload()
    for key in _TOP_LEVEL_KEYS - {"entries"}:
        if not _same_exact(payload.get(key), expected_top[key]):
            _append_once(failures, "diagnostic_lineage_top_level_mismatch:" + key)

    entries = payload.get("entries")
    if not isinstance(entries, list):
        failures.append("diagnostic_lineage_entries_not_list")
        return report
    if len(entries) != len(EXPECTED_ENTRIES):
        failures.append("diagnostic_lineage_entry_count_mismatch")

    expected_by_id = {item["evidence_id"]: item for item in EXPECTED_ENTRIES}
    observed_by_id: Dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            _append_once(
                failures,
                "diagnostic_lineage_entry_not_object:" + str(index),
            )
            continue
        if frozenset(item) != _ENTRY_KEYS:
            _append_once(
                failures,
                "diagnostic_lineage_entry_keys_invalid:" + str(index),
            )
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str):
            _append_once(
                failures,
                "diagnostic_lineage_evidence_id_invalid:" + str(index),
            )
            continue
        if evidence_id in observed_by_id:
            _append_once(failures, "diagnostic_lineage_duplicate_evidence_id")
        observed_by_id[evidence_id] = item
        if item.get("is_current") is True:
            current_entries.append(item)

    if frozenset(observed_by_id) != frozenset(expected_by_id):
        failures.append("diagnostic_lineage_entry_set_mismatch")

    for evidence_id, expected in expected_by_id.items():
        item = observed_by_id.get(evidence_id)
        if item is None:
            continue
        for key in _ENTRY_KEYS:
            if not _same_exact(item.get(key), expected[key]):
                _append_once(
                    failures,
                    "diagnostic_lineage_entry_mismatch:"
                    + evidence_id
                    + ":"
                    + key,
                )

        expected_path = Path(expected["path"])
        try:
            identity = _regular_file_identity(expected_path)
        except (OSError, ValueError) as error:
            observed_identities.append(
                {
                    "evidence_id": evidence_id,
                    "path": str(expected_path),
                    "error_type": type(error).__name__,
                }
            )
            _append_once(
                failures,
                "diagnostic_lineage_artifact_unreadable:" + evidence_id,
            )
            continue
        identity["evidence_id"] = evidence_id
        observed_identities.append(identity)
        if identity["path"] != str(expected_path.resolve(strict=True)):
            _append_once(
                failures,
                "diagnostic_lineage_artifact_path_mismatch:" + evidence_id,
            )
        if identity["size_bytes"] != expected["size_bytes"]:
            _append_once(
                failures,
                "diagnostic_lineage_artifact_size_mismatch:" + evidence_id,
            )
        if identity["sha256"] != expected["sha256"]:
            _append_once(
                failures,
                "diagnostic_lineage_artifact_sha256_mismatch:" + evidence_id,
            )

    if len(current_entries) != 1:
        failures.append("diagnostic_lineage_current_count_invalid")
    else:
        current = current_entries[0]
        if current.get("evidence_id") != CURRENT_EVIDENCE_ID:
            failures.append("diagnostic_lineage_current_id_mismatch")
        if current.get("status") != CURRENT_REQUIRED_STATUS:
            failures.append("diagnostic_lineage_current_status_mismatch")
        if not failures:
            report["current_evidence"] = dict(current)

    report["validated_pass"] = not failures
    return report

def load_and_validate_diagnostic_evidence_lineage(
    sidecar_path: Path = DEFAULT_SIDECAR_PATH,
) -> Dict[str, Any]:
    """Strictly load the one canonical sidecar and validate live artifacts."""
    failures: List[str] = []
    report: Dict[str, Any]
    requested = Path(sidecar_path)
    expected = DEFAULT_SIDECAR_PATH.resolve(strict=False)
    if requested.resolve(strict=False) != expected:
        return {
            "schema_version": SCHEMA_VERSION,
            "validated_pass": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_evidence_consumer": False,
            "failures": ["diagnostic_lineage_sidecar_path_mismatch"],
        }
    try:
        identity = _regular_file_identity(requested)
        raw = requested.read_text(encoding="utf-8")
        payload = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return {
            "schema_version": SCHEMA_VERSION,
            "validated_pass": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_evidence_consumer": False,
            "failures": [
                "diagnostic_lineage_sidecar_invalid:" + type(error).__name__
            ],
        }
    report = validate_diagnostic_evidence_lineage(payload)
    report["sidecar_identity"] = identity
    report["sidecar_path"] = str(requested.resolve(strict=True))
    report["sidecar_relative_path"] = SIDECAR_RELATIVE_PATH.as_posix()
    if failures:
        report["failures"].extend(failures)
        report["validated_pass"] = False
    return report
