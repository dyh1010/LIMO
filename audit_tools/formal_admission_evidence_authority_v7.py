"""Out-of-band trust-root wrapper for the v8 BLOCKED_OFFLINE candidate.

The production index anchor intentionally remains unset while the source/test
generation is still being stabilized.  Callers may validate an explicitly
anchored candidate only after ``CORE_SOURCE_TRUST_ANCHOR`` is independently
frozen.  Neither entry point can grant runtime, field, motion, or delivery.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import types
from typing import Any, Dict, Mapping, Optional, Tuple


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE_RELATIVE_PATH = (
    "audit_tools/formal_admission_evidence_authority_v7_core.py"
)

# Frozen only in a later, separately authorized phase after the final core
# bytes and all loader/broker negative tests are stable.
CORE_SOURCE_TRUST_ANCHOR: Optional[Mapping[str, Any]] = {
    "path": "audit_tools/formal_admission_evidence_authority_v7_core.py",
    "size_bytes": 222678,
    "sha256": "b67edc0b23345c9d2c9d848883109132dc878ff854f12e0d281e5e27cf00f6b6",
}

# The index anchor is the sole future selection point.  It must remain unset
# through implementation, targeted tests, the complete matrix, the 15-cell
# commit-boundary matrix, and the one-shot O_EXCL generation attempt.
_WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR: Optional[Mapping[str, Any]] = None
PRODUCTION_INDEX_TRUST_ANCHOR: Optional[Mapping[str, Any]] = (
    _WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR if os.name == "nt" else None
)


def _fail_closed(*codes: str) -> Dict[str, Any]:
    return {
        "schema_version": "ros1_formal_admission_evidence_authority/v7",
        "validated_pass": False,
        "semantic_validated_pass": False,
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
        "semantic_evidence_producer_contract_implemented": False,
        "semantic_evidence_producer_offline_algorithm_validated": False,
        "semantic_evidence_producer_production_authority_bound": False,
        "semantic_evidence_producer_formal_evidence_admitted": False,
        "ros1_source_implementation_complete": False,
        "current_evidence": None,
        "artifact_identities": [],
        "failures": list(dict.fromkeys(codes)),
    }


def _is_linklike(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _same_side_stat_projection(info: os.stat_result) -> Tuple[Any, ...]:
    return (
        getattr(info, "st_dev", None), getattr(info, "st_ino", None),
        info.st_mode, info.st_size, getattr(info, "st_mtime_ns", None),
        getattr(info, "st_ctime_ns", None), getattr(info, "st_nlink", 1),
        getattr(info, "st_uid", None), getattr(info, "st_gid", None),
        getattr(info, "st_file_attributes", None),
    )


def _cross_source_stat_projection(info: os.stat_result) -> Tuple[Any, ...]:
    if os.name != "nt":
        return _same_side_stat_projection(info)
    return (
        getattr(info, "st_dev", None), getattr(info, "st_ino", None),
        stat.S_IFMT(info.st_mode), info.st_size,
        getattr(info, "st_mtime_ns", None), getattr(info, "st_nlink", 1),
        getattr(info, "st_uid", None), getattr(info, "st_gid", None),
        getattr(info, "st_file_attributes", None),
    )


def _read_exclusive_regular_bytes(path: Path) -> bytes:
    before = os.lstat(str(path))
    if (
        _is_linklike(before) or not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
    ):
        raise ValueError("source is not an exclusive regular file")
    flags = (
        os.O_RDONLY | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(str(path), flags)
    try:
        opened_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or getattr(opened_before, "st_nlink", 1) != 1
            or _cross_source_stat_projection(opened_before)
            != _cross_source_stat_projection(before)
        ):
            raise ValueError("opened source identity mismatch")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.lstat(str(path))
    raw = b"".join(chunks)
    if (
        _is_linklike(after) or not stat.S_ISREG(after.st_mode)
        or getattr(after, "st_nlink", 1) != 1
        or _same_side_stat_projection(after)
        != _same_side_stat_projection(before)
        or _same_side_stat_projection(opened_after)
        != _same_side_stat_projection(opened_before)
        or _cross_source_stat_projection(opened_after)
        != _cross_source_stat_projection(after)
        or len(raw) != opened_before.st_size
        or len(raw) != opened_after.st_size
    ):
        raise ValueError("source changed while reading")
    return raw


def _load_exact_core(
    workspace: Path,
) -> Tuple[Optional[types.ModuleType], Dict[str, Any], list[str]]:
    anchor = CORE_SOURCE_TRUST_ANCHOR
    if not isinstance(anchor, dict):
        return None, {}, ["formal_authority_v7_core_source_anchor_not_configured"]
    if set(anchor) != {"path", "size_bytes", "sha256"}:
        return None, {}, ["formal_authority_v7_core_source_anchor_invalid"]
    if anchor.get("path") != CORE_SOURCE_RELATIVE_PATH:
        return None, {}, ["formal_authority_v7_core_source_anchor_path_mismatch"]
    root = Path(workspace).resolve(strict=True)
    path = root
    try:
        root_info = os.lstat(str(root))
        if _is_linklike(root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise ValueError("workspace root invalid")
        for part in CORE_SOURCE_RELATIVE_PATH.split("/"):
            path = path / part
            info = os.lstat(str(path))
            if _is_linklike(info):
                raise ValueError("linklike core path")
        raw = _read_exclusive_regular_bytes(path)
    except (OSError, ValueError):
        return None, {}, ["formal_authority_v7_core_source_unreadable"]
    identity = {
        "path": CORE_SOURCE_RELATIVE_PATH,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    failures = [
        "formal_authority_v7_core_source_" + key + "_mismatch"
        for key in ("size_bytes", "sha256")
        if identity[key] != anchor.get(key)
    ]
    if failures:
        return None, identity, failures
    private_name = "_ros1_formal_authority_v7_core_exact_" + identity["sha256"]
    module = types.ModuleType(private_name)
    module.__file__ = str(path)
    module.__package__ = "audit_tools"
    module.__spec__ = None
    previous = sys.modules.get(private_name)
    try:
        sys.modules[private_name] = module
        code = compile(raw, str(path), "exec", dont_inherit=True, optimize=0)
        exec(code, module.__dict__)
    except BaseException:
        return None, identity, ["formal_authority_v7_core_source_execution_failed"]
    finally:
        if previous is None:
            sys.modules.pop(private_name, None)
        else:
            sys.modules[private_name] = previous
    required = (
        "PRODUCTION_POLICY",
        "load_and_resolve_formal_admission_evidence_authority_v7",
    )
    if module.__file__ != str(path) or any(
        not hasattr(module, name) for name in required
    ):
        return None, identity, ["formal_authority_v7_core_source_api_invalid"]
    return module, identity, []


def load_and_resolve_successor_authority(
    index_trust_anchor: Mapping[str, Any],
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve only one caller-supplied exact candidate identity."""
    core, identity, failures = _load_exact_core(workspace)
    if core is None:
        result = _fail_closed(*failures)
        result["core_source_identity"] = identity
        result["core_source_anchor_configured"] = isinstance(
            CORE_SOURCE_TRUST_ANCHOR, dict
        )
        return result
    result = core.load_and_resolve_formal_admission_evidence_authority_v7(
        workspace, index_trust_anchor, core.PRODUCTION_POLICY,
    )
    result["core_source_identity"] = identity
    result["core_source_anchor_configured"] = True
    return result


def load_and_resolve_current_authority(
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Fail closed until a final production index anchor is explicitly frozen."""
    if not isinstance(PRODUCTION_INDEX_TRUST_ANCHOR, dict):
        core, identity, core_failures = _load_exact_core(workspace)
        result = _fail_closed(*(
            core_failures
            + ["formal_authority_v7_production_anchor_not_configured"]
        ))
        result["core_source_identity"] = identity
        result["core_source_anchor_configured"] = core is not None
        result["production_anchor_configured"] = False
        return result
    result = load_and_resolve_successor_authority(
        PRODUCTION_INDEX_TRUST_ANCHOR, workspace,
    )
    result["production_anchor_configured"] = True
    return result


__all__ = [
    "CORE_SOURCE_RELATIVE_PATH", "CORE_SOURCE_TRUST_ANCHOR",
    "PRODUCTION_INDEX_TRUST_ANCHOR", "WORKSPACE_ROOT",
    "load_and_resolve_current_authority",
    "load_and_resolve_successor_authority",
]
