"""Out-of-band trust-root wrapper for the v7 BLOCKED_OFFLINE authority.

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
    "audit_tools/formal_admission_evidence_authority_v6_core.py"
)

# Independently frozen after the core bytes, commit-boundary matrix, and
# fail-closed loader checks became stable.  This anchors only the validator
# implementation; the production evidence index remains deliberately unset.
CORE_SOURCE_TRUST_ANCHOR: Optional[Mapping[str, Any]] = {
    "path": "audit_tools/formal_admission_evidence_authority_v6_core.py",
    "size_bytes": 168104,
    "sha256": "61196cc8f000842de14216a57eb51d7808c52bb99005cb73c41dd49087386c56",
}

# Frozen only after canonical/report/index O_EXCL writes and an independent
# resolver validation on the final bytes.  This selects offline release
# evidence only; it cannot authorize runtime, field evidence, or delivery.
_WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR: Optional[Mapping[str, Any]] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260816_v7_"
        "atomic_cli_field_producer_blocked_offline.json"
    ),
    "size_bytes": 36978,
    "sha256": "4efd869828196b0996647453d2c8ba5670211686efa5ad8ddd9edf0a70b4a7c3",
}
PRODUCTION_INDEX_TRUST_ANCHOR: Optional[Mapping[str, Any]] = (
    _WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR if os.name == "nt" else None
)


def _fail_closed(*codes: str) -> Dict[str, Any]:
    return {
        "schema_version": "ros1_formal_admission_evidence_authority/v6",
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


def _load_exact_core(
    workspace: Path,
) -> Tuple[Optional[types.ModuleType], Dict[str, Any], list[str]]:
    anchor = CORE_SOURCE_TRUST_ANCHOR
    if not isinstance(anchor, dict):
        return None, {}, ["formal_authority_v6_core_source_anchor_not_configured"]
    if set(anchor) != {"path", "size_bytes", "sha256"}:
        return None, {}, ["formal_authority_v6_core_source_anchor_invalid"]
    if anchor.get("path") != CORE_SOURCE_RELATIVE_PATH:
        return None, {}, ["formal_authority_v6_core_source_anchor_path_mismatch"]
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
        before = os.lstat(str(path))
        if (
            not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_nlink", 1) != 1
        ):
            raise ValueError("core is not an exclusive regular file")
        flags = (
            os.O_RDONLY | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(str(path), flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or getattr(opened, "st_nlink", 1) != 1
                or (opened.st_dev, opened.st_ino)
                != (before.st_dev, before.st_ino)
            ):
                raise ValueError("opened core identity mismatch")
            chunks = []
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
            raise ValueError("core changed while reading")
    except (OSError, ValueError):
        return None, {}, ["formal_authority_v6_core_source_unreadable"]
    identity = {
        "path": CORE_SOURCE_RELATIVE_PATH,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    failures = [
        "formal_authority_v6_core_source_" + key + "_mismatch"
        for key in ("size_bytes", "sha256")
        if identity[key] != anchor.get(key)
    ]
    if failures:
        return None, identity, failures
    private_name = "_ros1_formal_authority_v6_core_exact_" + identity["sha256"]
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
        return None, identity, ["formal_authority_v6_core_source_execution_failed"]
    finally:
        if previous is None:
            sys.modules.pop(private_name, None)
        else:
            sys.modules[private_name] = previous
    required = (
        "PRODUCTION_POLICY",
        "load_and_resolve_formal_admission_evidence_authority_v6",
    )
    if module.__file__ != str(path) or any(
        not hasattr(module, name) for name in required
    ):
        return None, identity, ["formal_authority_v6_core_source_api_invalid"]
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
    result = core.load_and_resolve_formal_admission_evidence_authority_v6(
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
            + ["formal_authority_v6_production_anchor_not_configured"]
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
