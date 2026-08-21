"""Production trust-root wrapper for the BLOCKED_OFFLINE v5 authority.

The core validator is a canonical child source role.  This wrapper is
intentionally out-of-band so its final fixed index path/size/SHA-256 anchor can
be installed only after the immutable index is written and independently
recomputed, without creating a hash cycle.
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
    "audit_tools/formal_admission_evidence_authority_v4_core.py"
)

# Frozen only after the canonical/report source bytes became stable.  Ambient
# ``sys.modules`` or ``sys.meta_path`` objects never become this trust root.
CORE_SOURCE_TRUST_ANCHOR: Optional[Mapping[str, Any]] = {
    "path": CORE_SOURCE_RELATIVE_PATH,
    "size_bytes": 88889,
    "sha256": "b01fa18963084bf7696584d8cd7e31ce42e4be03e5122d2d08dad1d012a1d313",
}

# This remained unset throughout source/report/index construction and was
# frozen only after an independent index identity recomputation.  Removing or
# changing it returns the resolver to a stable fail-closed state.
PRODUCTION_INDEX_TRUST_ANCHOR: Optional[Mapping[str, Any]] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_"
        "v5_blocked_offline.json"
    ),
    "size_bytes": 15792,
    "sha256": "b5a6077db8b3da32962c4e22a6603114493be4d7bfbc2a3846666fe8fb6c7941",
}


def _fail_closed(*codes: str) -> Dict[str, Any]:
    return {
        "schema_version": "ros1_formal_admission_evidence_authority/v4",
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
    if not isinstance(CORE_SOURCE_TRUST_ANCHOR, dict):
        return None, {}, ["formal_authority_v4_core_source_anchor_not_configured"]
    expected_keys = {"path", "size_bytes", "sha256"}
    if set(CORE_SOURCE_TRUST_ANCHOR) != expected_keys:
        return None, {}, ["formal_authority_v4_core_source_anchor_invalid"]
    if CORE_SOURCE_TRUST_ANCHOR.get("path") != CORE_SOURCE_RELATIVE_PATH:
        return None, {}, ["formal_authority_v4_core_source_anchor_path_mismatch"]
    root = Path(workspace).resolve(strict=True)
    path = root
    try:
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
        raw = path.read_bytes()
        after = os.lstat(str(path))
        if (
            _is_linklike(after)
            or not stat.S_ISREG(after.st_mode)
            or getattr(after, "st_nlink", 1) != 1
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        ):
            raise ValueError("core changed while reading")
    except (OSError, ValueError):
        return None, {}, ["formal_authority_v4_core_source_unreadable"]
    identity = {
        "path": CORE_SOURCE_RELATIVE_PATH,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    failures = []
    for key in ("size_bytes", "sha256"):
        if identity[key] != CORE_SOURCE_TRUST_ANCHOR.get(key):
            failures.append("formal_authority_v4_core_source_" + key + "_mismatch")
    if failures:
        return None, identity, failures
    private_name = "_ros1_formal_authority_v4_core_exact_" + identity["sha256"]
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
        return None, identity, ["formal_authority_v4_core_source_execution_failed"]
    finally:
        if previous is None:
            sys.modules.pop(private_name, None)
        else:
            sys.modules[private_name] = previous
    required = (
        "PRODUCTION_POLICY",
        "load_and_resolve_formal_admission_evidence_authority_v4",
    )
    if (
        module.__file__ != str(path)
        or any(not hasattr(module, name) for name in required)
    ):
        return None, identity, ["formal_authority_v4_core_source_api_invalid"]
    return module, identity, []


def load_and_resolve_successor_authority(
    index_trust_anchor: Mapping[str, Any],
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve only the exact caller-supplied externally anchored index."""
    core, identity, failures = _load_exact_core(workspace)
    if core is None:
        result = _fail_closed(*failures)
        result["core_source_identity"] = identity
        result["core_source_anchor_configured"] = isinstance(
            CORE_SOURCE_TRUST_ANCHOR, dict
        )
        return result
    result = core.load_and_resolve_formal_admission_evidence_authority_v4(
        workspace, index_trust_anchor, core.PRODUCTION_POLICY
    )
    result["core_source_identity"] = identity
    result["core_source_anchor_configured"] = True
    return result


def load_and_resolve_current_authority(
    workspace: Path = WORKSPACE_ROOT,
) -> Dict[str, Any]:
    """Resolve the production index, or fail while its anchor is unset."""
    if not isinstance(CORE_SOURCE_TRUST_ANCHOR, dict):
        result = _fail_closed(
            "formal_authority_v4_core_source_anchor_not_configured"
        )
        result["core_source_identity"] = {}
        result["core_source_anchor_configured"] = False
        result["production_anchor_configured"] = isinstance(
            PRODUCTION_INDEX_TRUST_ANCHOR, dict
        )
        return result
    if not isinstance(PRODUCTION_INDEX_TRUST_ANCHOR, dict):
        core, identity, failures = _load_exact_core(workspace)
        result = _fail_closed(
            *(failures + ["formal_authority_v4_production_anchor_not_configured"])
        )
        result["core_source_identity"] = identity
        result["core_source_anchor_configured"] = core is not None
        result["production_anchor_configured"] = False
        return result
    result = load_and_resolve_successor_authority(
        PRODUCTION_INDEX_TRUST_ANCHOR, workspace
    )
    result["production_anchor_configured"] = True
    return result


__all__ = [
    "PRODUCTION_INDEX_TRUST_ANCHOR",
    "CORE_SOURCE_TRUST_ANCHOR",
    "WORKSPACE_ROOT",
    "load_and_resolve_current_authority",
    "load_and_resolve_successor_authority",
]
