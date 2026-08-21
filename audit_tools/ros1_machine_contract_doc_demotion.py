"""Task-scoped, fail-closed gate for legacy ROS2 documentation.

This checker is deliberately separate from the frozen ROS1 release-selection
authority.  It reads one exact ROS1/Noetic machine contract, recursively
enumerates every ``docs/...`` ``source_path``, and requires a strong demotion
banner whenever a referenced document contains ROS2/Foxy/Humble PASS claims.
It also proves the exact identity and internally consistent historical-current
entry of the frozen v5 predecessor.  It deliberately does not decide which
authority generation is globally current; that selection belongs to the
separate externally anchored production resolver.  Passing this gate never
authorizes field use or delivery.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "ros1_machine_contract_doc_demotion/v2"
MARKER = "ROS1_MACHINE_CONTRACT_DOC_DEMOTION "

CONTRACT_RELATIVE_PATH = (
    "ros1_overlay_src/limo_cleanup_ros1_perception/config/"
    "ros1_noetic_field_install_contract.json"
)
CONTRACT_SIZE_BYTES = 7538
CONTRACT_SHA256 = (
    "808abf42856856d8b79a232c60d83a7ca777e681cdb1eaef8a251cddcb6f5abc"
)

AUTHORITY_V5_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_formal_admission_evidence_authority_index_20260815_"
    "v5_blocked_offline.json"
)
AUTHORITY_V5_SIZE_BYTES = 15792
AUTHORITY_V5_SHA256 = (
    "b5a6077db8b3da32962c4e22a6603114493be4d7bfbc2a3846666fe8fb6c7941"
)
AUTHORITY_V5_INDEX_INSTANCE_ID = (
    "ros1-formal-admission-evidence-authority-index-20260815-"
    "v5-blocked-offline"
)
AUTHORITY_V5_GENERATION_ID = (
    "ros1_camera_runtime_install_blocked_offline_20260815_v5"
)
AUTHORITY_V5_CURRENT_EVIDENCE_ID = (
    "ros1_camera_runtime_install_blocked_offline_regression_20260815_v5"
)

EXPECTED_CONTRACT_DOCUMENTS: Tuple[str, ...] = (
    "docs/foxy_arm64_deployment.md",
)

SHARED_DOCUMENT_IDENTITIES: Tuple[Tuple[str, int, str], ...] = (
    (
        "REAL_MACHINE_ACCEPTANCE_2026-08-07.md",
        35176,
        "6bd1931d53d1bf63accbc1e852801d560110594460437365b8e9819cd5dcb15d",
    ),
    (
        "TEAM_COORDINATION.md",
        37807,
        "0edb875b407045f499cdd1315193fdd4785881bb1244f1a367500a0715077531",
    ),
)

HARDWARE_LEGACY_RELATIVE_PATH = "docs/hardware_readiness.md"
HARDWARE_LEGACY_SIZE_BYTES = 13274
HARDWARE_LEGACY_SHA256 = (
    "6d48815b660c3f6b0c00fb36dc633d403b540e5a95f0bdedaddc37f33093fd9b"
)
HARDWARE_REDIRECT_RELATIVE_PATH = (
    "docs/HARDWARE_READINESS_ROS1_NOETIC_REDIRECT.md"
)
HARDWARE_REDIRECT_SIZE_BYTES = 1592
HARDWARE_REDIRECT_SHA256 = (
    "7cca88b27c8add2f91cc3133b06d7f0f8dba9812b10558fe8def795d2415f4a0"
)
HARDWARE_WRAPPER_RELATIVE_PATH = "scripts/run_hardware_readonly_acceptance.sh"
HARDWARE_WRAPPER_SIZE_BYTES = 2124
HARDWARE_WRAPPER_SHA256 = (
    "56132a21fbc974ff86a8133c148698cada229f82d686186add71f24a999c7592"
)
HARDWARE_CURRENT_OPERATIONS_INDEX_RELATIVE_PATH = (
    "docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md"
)
HARDWARE_CURRENT_OPERATIONS_INDEX_SIZE_BYTES = 1418
HARDWARE_CURRENT_OPERATIONS_INDEX_SHA256 = (
    "f915c45471996b42341f9fa62a681227cf11c2fdca4ab29babeeefbdd3572583"
)
HARDWARE_AUTHORITY_RUNBOOK = "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md"
HARDWARE_AUTHORITY_RUNBOOK_SIZE_BYTES = 20759
HARDWARE_AUTHORITY_RUNBOOK_SHA256 = (
    "44e72bb4ec686ee76d816814b26eda4c18adf8145fa2bec05ace5b69aa31be2d"
)
HARDWARE_ATOMIC_LAUNCHER = "audit_tools/ros1_camera_only_atomic_launcher.py"
HARDWARE_LEGACY_OFFLINE_DOMAIN_ID = "197"

HARDWARE_LEGACY_REQUIRED_SURFACES: Tuple[str, ...] = (
    "source /opt/ros/humble/setup.bash",
    "scripts/run_hardware_readonly_acceptance.sh \\",
    "scripts/run_hardware_readonly_acceptance.sh start_camera:=true",
    "ros2 launch limo_cleanup_bringup real_perception_only.launch.py \\",
    "REAL_PERCEPTION_GATE_ACCEPTANCE_PASS",
    "fuser /dev/ttyTHS0",
    "ROS2 graph",
)

HARDWARE_REDIRECT_REQUIRED_TOKENS: Tuple[str, ...] = (
    "NON_AUTHORITATIVE_DO_NOT_RUN",
    "current field authority is ROS1 / Noetic",
    "docs/hardware_readiness.md",
    "13274",
    HARDWARE_LEGACY_SHA256,
    "FROZEN_HISTORICAL_ROS2_PROVENANCE",
    "REAL_PERCEPTION_GATE_ACCEPTANCE_PASS",
    "does not prove or\nauthorize the current ROS1/Noetic build/install",
    HARDWARE_AUTHORITY_RUNBOOK,
    HARDWARE_ATOMIC_LAUNCHER,
    "not a\nrelease-selection authority",
)

HARDWARE_WRAPPER_REQUIRED_TOKENS: Tuple[str, ...] = (
    "BLOCKED_NON_AUTHORITATIVE_HARDWARE_READINESS",
    "--legacy-ros2-offline-only",
    '"${LEGACY_ROS2_OFFLINE_ONLY:-}" != \'1\'',
    '"${ROS_LOCALHOST_ONLY:-}" != \'1\'',
    '"${ROS_DOMAIN_ID:-}" != "${isolated_domain}"',
    "readonly isolated_domain='197'",
    "BLOCKED_LEGACY_ROS2_CAMERA_START_FORBIDDEN",
    "BLOCKED_LEGACY_ROS2_REAL_TOPIC_DEVICE_OR_GRAPH_FORBIDDEN",
    "BLOCKED_LEGACY_ROS2_AMBIENT_GRAPH_CONFIGURATION",
    "LEGACY_ROS2_OFFLINE_ONLY_PURE_STATIC_ACKNOWLEDGEMENT",
    HARDWARE_REDIRECT_RELATIVE_PATH,
    HARDWARE_AUTHORITY_RUNBOOK,
    HARDWARE_ATOMIC_LAUNCHER,
)

DEMOTION_BANNER = """> [!CAUTION]
> **\u964d\u7ea7\u58f0\u660e / DEMOTION BANNER \u2014 `LEGACY_ROS2_OFFLINE_ONLY`**
>
> **\u5f53\u524d\u73b0\u573a\u6743\u5a01\u9ed8\u8ba4 / Current field-authority default: ROS1 Noetic.**
> \u672c\u6587\u4ec5\u4fdd\u7559\u4e3a 2026-08-07 \u7684\u5386\u53f2 ROS 2/Foxy \u8fc1\u79fb\u8bb0\u5f55\u4e0e\u7248\u672c provenance\uff1b\u4e0b\u65b9\u6b63\u6587\u4ec5\u8bb0\u5f55\u5386\u53f2\u4e8b\u5b9e\u3002
> **\u5386\u53f2\u4e14\u975e\u6743\u5a01 / HISTORICAL AND NON-AUTHORITATIVE\uff1a**\u672c\u6587\u4e0d\u5f97\u4f5c\u4e3a\u5f53\u524d ROS1 build/install\u3001\u76f8\u673a\u8fd0\u884c\u3001\u56db\u573a\u666f\u3001TF/3D\u3001latency\u3001field \u6216 delivery PASS\uff0c\u4e5f\u4e0d\u6784\u6210\u4efb\u4f55\u73b0\u573a\u6216\u4ea4\u4ed8\u6388\u6743\u3002"""
HISTORICAL_FOXY_TITLE = "# ROS 2 Foxy / ARM64 \u90e8\u7f72\u5ba1\u8ba1"
EXACT_FOXY_PREFIX = DEMOTION_BANNER + "\n\n" + HISTORICAL_FOXY_TITLE + "\n"

REAL_MACHINE_CORRECTION_PREFIX = """# LIMO Pro \u5b9e\u673a\u53ea\u8bfb\u9a8c\u6536\u8bb0\u5f55\uff082026-08-07\uff09

> **\u5f53\u524d\u6743\u5a01\u8fd0\u884c\u9762\u7ea0\u6b63\uff082026-08-15\uff09\uff1a\u73b0\u573a\u9ed8\u8ba4\u662f ROS1 / Noetic\u3002**
> \u672c\u6587\u4ef6\u4fdd\u7559\u7684 ROS2 Foxy / Humble\u3001ARM64 \u6784\u5efa\u3001\u53ea\u8bfb\u76f8\u673a\u3001\u673a\u68b0\u81c2\u548c\u8bed\u97f3\u201c\u901a\u8fc7\u201d\u7ed3\u8bba\uff0c
> \u4ec5\u662f\u5e26\u65e5\u671f\u7684\u5386\u53f2\u3001\u8fc1\u79fb\u6216\u6865\u63a5 provenance\uff1b\u4e0d\u5f97\u636e\u6b64\u58f0\u660e\u5f53\u524d ROS1 build/install\u3001\u8fd0\u884c\u65f6
> owner\u3001\u771f\u5b9e\u76f8\u673a\u56db\u573a\u666f\u3001TF/3D/latency\u3001\u673a\u68b0\u81c2/\u5939\u722a\u52a8\u4f5c\u3001field \u6216 delivery PASS\u3002
> \u5f53\u524d\u673a\u5668 authority\u3001ROS1 runbook \u548c\u5404\u5b50\u7cfb\u7edf\u6700\u65b0 evidence \u4f18\u5148\uff1b\u76f8\u5e94\u673a\u5668\u95e8\u672a\u72ec\u7acb\u95ed\u5408\u65f6
> \u4e00\u5f8b\u4fdd\u6301 BLOCKED\u3002\u672c\u7ea0\u6b63\u4e0d\u6539\u5199\u4e0b\u65b9\u5386\u53f2\u4e8b\u5b9e\uff0c\u4e5f\u4e0d\u6784\u6210\u4efb\u4f55\u542f\u52a8\u3001\u8fde\u63a5\u6216\u8fd0\u52a8\u6388\u6743\u3002
"""

TEAM_COORDINATION_REQUIRED_SNIPPET = """- `REAL_MACHINE_ACCEPTANCE_2026-08-07.md`\uff08\u5fc5\u987b\u5148\u8bfb\u6587\u4ef6\u9876\u90e8\u7684 ROS1 / Noetic \u5f53\u524d\u6743\u5a01\u7ea0\u6b63\uff1b
  \u6587\u5185 ROS2 Foxy / Humble \u201c\u901a\u8fc7\u201d\u4ec5\u4e3a\u5386\u53f2\u3001\u8fc1\u79fb\u6216\u6865\u63a5 provenance\uff0c\u4e0d\u662f\u5f53\u524d field/delivery PASS\uff09"""

_LEGACY_ROS2_SURFACE = re.compile(
    r"(?:\bROS\s*2\b|\bFoxy\b|\bHumble\b)", re.IGNORECASE
)
_PASS_SURFACE = re.compile(
    r"(?:\bPASS(?:ED|ES|ING)?\b|\bvalidated\b|\baccepted\b|"
    r"\u901a\u8fc7|\u5df2\u5b8c\u6210|\u590d\u6d4b\u786e\u8ba4|\u9a8c\u6536)",
    re.IGNORECASE,
)
_PROMOTION_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "install",
        re.compile(
            r"(?:source_declaration_is_install_evidence\s*=\s*true|"
            r"ros1_noetic_(?:build_)?install_(?:verified|pass)\s*=\s*true|"
            r"CURRENT[_ -]?INSTALL[_ -]?PASS\s*=\s*true)",
            re.IGNORECASE,
        ),
    ),
    (
        "field",
        re.compile(
            r"(?:ros1_noetic_field_install_pass\s*=\s*true|"
            r"formal_consumer\s*=\s*true|"
            r"accepted_by_formal_field_evidence_consumer\s*=\s*true|"
            r"CURRENT[_ -]?FIELD[_ -]?PASS\s*=\s*true)",
            re.IGNORECASE,
        ),
    ),
    (
        "delivery",
        re.compile(
            r"(?:delivery_ready\s*=\s*true|"
            r"authorizes_field_delivery\s*=\s*true|"
            r"CURRENT[_ -]?DELIVERY[_ -]?PASS\s*=\s*true)",
            re.IGNORECASE,
        ),
    ),
)


class _StrictJsonError(ValueError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_linklike(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _safe_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        return None
    parts = candidate.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    normalized = candidate.as_posix()
    if normalized != value:
        return None
    return normalized


def _read_exact_file(
    workspace_root: Path, relative: str, role: str
) -> Tuple[bytes | None, Dict[str, Any], List[str]]:
    failures: List[str] = []
    normalized = _safe_relative_path(relative)
    if normalized is None:
        return None, {}, ["ros1_doc_gate_path_invalid:" + role]

    root = Path(workspace_root)
    try:
        root_info = root.lstat()
    except OSError:
        return None, {}, ["ros1_doc_gate_workspace_unavailable"]
    if _is_linklike(root_info) or not stat.S_ISDIR(root_info.st_mode):
        return None, {}, ["ros1_doc_gate_workspace_linklike_or_not_directory"]
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return None, {}, ["ros1_doc_gate_workspace_unavailable"]

    path = resolved_root
    parts = PurePosixPath(normalized).parts
    before: os.stat_result | None = None
    for index, part in enumerate(parts):
        path = path / part
        try:
            info = path.lstat()
        except OSError:
            failures.append(
                "ros1_doc_gate_artifact_unavailable:{}:{}".format(
                    role, normalized
                )
            )
            return None, {}, failures
        if _is_linklike(info):
            failures.append(
                "ros1_doc_gate_artifact_linklike:{}:{}".format(
                    role, normalized
                )
            )
            return None, {}, failures
        if index < len(parts) - 1:
            if not stat.S_ISDIR(info.st_mode):
                failures.append(
                    "ros1_doc_gate_parent_not_directory:{}:{}".format(
                        role, normalized
                    )
                )
                return None, {}, failures
        else:
            before = info
    if before is None or not stat.S_ISREG(before.st_mode):
        return None, {}, [
            "ros1_doc_gate_artifact_not_regular:{}:{}".format(role, normalized)
        ]
    if getattr(before, "st_nlink", 1) != 1:
        return None, {}, [
            "ros1_doc_gate_artifact_nlink_invalid:{}:{}".format(role, normalized)
        ]

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError:
        return None, {}, [
            "ros1_doc_gate_artifact_open_failed:{}:{}".format(role, normalized)
        ]
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            return None, {}, [
                "ros1_doc_gate_artifact_changed_before_open:{}:{}".format(
                    role, normalized
                )
            ]
        chunks: List[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)

    try:
        after = path.lstat()
    except OSError:
        return None, {}, [
            "ros1_doc_gate_artifact_changed_after_read:{}:{}".format(
                role, normalized
            )
        ]
    if (
        _is_linklike(after)
        or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or after.st_size != before.st_size
        or getattr(after, "st_mtime_ns", None)
        != getattr(before, "st_mtime_ns", None)
        or len(raw) != before.st_size
    ):
        return None, {}, [
            "ros1_doc_gate_artifact_changed_after_read:{}:{}".format(
                role, normalized
            )
        ]
    identity = {
        "path": normalized,
        "size_bytes": len(raw),
        "sha256": _sha256(raw),
    }
    return raw, identity, failures


def _strict_json(raw: bytes, label: str) -> Tuple[Any, List[str]]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        return None, ["ros1_doc_gate_strict_json_utf8_invalid:" + label]

    def reject_constant(value: str) -> None:
        raise _StrictJsonError("non-finite constant: " + value)

    def reject_duplicates(items: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise _StrictJsonError("duplicate key: " + key)
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        ), []
    except (json.JSONDecodeError, _StrictJsonError, TypeError, ValueError):
        return None, ["ros1_doc_gate_strict_json_invalid:" + label]


def _json_path(parent: str, key: str) -> str:
    return parent + "." + key if parent else key


def _walk_contract(
    value: Any, path: str = "$"
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    documents: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    if isinstance(value, Mapping):
        if "source_declaration_is_install_evidence" in value:
            flags.append(
                {
                    "json_path": _json_path(
                        path, "source_declaration_is_install_evidence"
                    ),
                    "value": value.get("source_declaration_is_install_evidence"),
                }
            )
        if "source_path" in value:
            source_path = value.get("source_path")
            if isinstance(source_path, str) and source_path.startswith("docs/"):
                documents.append(
                    {
                        "json_path": _json_path(path, "source_path"),
                        "source_path": source_path,
                        "flag_present": (
                            "source_declaration_is_install_evidence" in value
                        ),
                        "source_declaration_is_install_evidence": value.get(
                            "source_declaration_is_install_evidence"
                        ),
                    }
                )
        for key, child in value.items():
            documents_child, flags_child = _walk_contract(
                child, _json_path(path, str(key))
            )
            documents.extend(documents_child)
            flags.extend(flags_child)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            documents_child, flags_child = _walk_contract(
                child, "{}[{}]".format(path, index)
            )
            documents.extend(documents_child)
            flags.extend(flags_child)
    return documents, flags


def _validate_contract(value: Any) -> Tuple[List[str], Dict[str, Any]]:
    failures: List[str] = []
    if not isinstance(value, Mapping):
        return ["ros1_doc_gate_contract_root_invalid"], {
            "document_records": [],
            "declaration_records": [],
        }
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("contract_id") != "ROS1_NOETIC_FIELD_INSTALL"
        or value.get("runtime_family") != "ROS1"
        or value.get("ros_distro") != "noetic"
    ):
        failures.append("ros1_doc_gate_contract_identity_invalid")

    document_records, declaration_records = _walk_contract(value)
    normalized_paths: List[str] = []
    for record in document_records:
        normalized = _safe_relative_path(record.get("source_path"))
        if normalized is None or not normalized.startswith("docs/"):
            failures.append(
                "ros1_doc_gate_contract_document_path_invalid:"
                + str(record.get("json_path"))
            )
            continue
        normalized_paths.append(normalized)
        if not record.get("flag_present"):
            failures.append(
                "ros1_doc_gate_source_declaration_flag_missing:"
                + str(record.get("json_path"))
            )
        elif record.get("source_declaration_is_install_evidence") is not False:
            failures.append(
                "ros1_doc_gate_source_declaration_not_false:"
                + str(record.get("json_path"))
            )
    if tuple(normalized_paths) != EXPECTED_CONTRACT_DOCUMENTS:
        failures.append("ros1_doc_gate_contract_document_set_mismatch")
    if len(normalized_paths) != len(set(normalized_paths)):
        failures.append("ros1_doc_gate_contract_document_duplicate")
    if not declaration_records:
        failures.append("ros1_doc_gate_source_declaration_flags_missing")
    for record in declaration_records:
        if record.get("value") is not False:
            failures.append(
                "ros1_doc_gate_source_declaration_not_false:"
                + str(record.get("json_path"))
            )
    return failures, {
        "document_records": document_records,
        "declaration_records": declaration_records,
        "document_paths": normalized_paths,
    }


def validate_document_text(relative_path: str, text: str) -> Dict[str, Any]:
    failures: List[str] = []
    has_legacy_surface = bool(_LEGACY_ROS2_SURFACE.search(text))
    has_pass_surface = bool(_PASS_SURFACE.search(text))
    requires_banner = has_legacy_surface and has_pass_surface
    banner_exact = text.startswith(EXACT_FOXY_PREFIX)
    if requires_banner and not banner_exact:
        if not text.startswith("> [!CAUTION]\n"):
            failures.append("ros1_doc_demotion_banner_missing:" + relative_path)
        else:
            failures.append("ros1_doc_demotion_banner_invalid:" + relative_path)
    preamble = text[: max(len(EXACT_FOXY_PREFIX) + 512, 2048)]
    for scope, pattern in _PROMOTION_PATTERNS:
        if pattern.search(preamble):
            failures.append(
                "ros1_doc_current_{}_promotion_forbidden:{}".format(
                    scope, relative_path
                )
            )
    return {
        "failures": sorted(set(failures)),
        "legacy_ros2_surface_present": has_legacy_surface,
        "pass_surface_present": has_pass_surface,
        "demotion_banner_required": requires_banner,
        "demotion_banner_exact": banner_exact,
        "legacy_ros2_offline_only": banner_exact,
        "ros1_noetic_current_field_authority_declared": banner_exact,
    }


def validate_shared_document_text(relative_path: str, text: str) -> Dict[str, Any]:
    failures: List[str] = []
    if relative_path == "REAL_MACHINE_ACCEPTANCE_2026-08-07.md":
        correction_exact = text.startswith(REAL_MACHINE_CORRECTION_PREFIX)
        if not correction_exact:
            failures.append("ros1_doc_shared_real_machine_correction_invalid")
        required_tokens = (
            "ROS1 / Noetic",
            "ROS2 Foxy / Humble",
            "\u5386\u53f2\u3001\u8fc1\u79fb\u6216\u6865\u63a5 provenance",
            "ROS1 build/install",
            "owner",
            "field \u6216 delivery PASS",
            "\u4e0d\u6784\u6210\u4efb\u4f55\u542f\u52a8\u3001\u8fde\u63a5\u6216\u8fd0\u52a8\u6388\u6743",
        )
        if any(token not in text[:1800] for token in required_tokens):
            failures.append("ros1_doc_shared_real_machine_correction_weakened")
        return {
            "failures": sorted(set(failures)),
            "role": "shared_real_machine_acceptance",
            "ros1_noetic_current_field_authority_declared": correction_exact,
            "historical_ros2_pass_demoted": correction_exact,
        }
    if relative_path == "TEAM_COORDINATION.md":
        preamble = text[:2200]
        correction_exact = (
            "## \u5171\u540c\u4e8b\u5b9e\u57fa\u7ebf" in preamble
            and "\u6240\u6709\u4efb\u52a1\u5f00\u59cb\u524d\u5fc5\u987b\u9605\u8bfb\uff1a" in preamble
            and TEAM_COORDINATION_REQUIRED_SNIPPET in preamble
        )
        if not correction_exact:
            failures.append("ros1_doc_shared_team_coordination_correction_invalid")
        return {
            "failures": sorted(set(failures)),
            "role": "shared_team_coordination",
            "ros1_noetic_correction_read_first": correction_exact,
            "historical_ros2_pass_demoted": correction_exact,
        }
    return {
        "failures": ["ros1_doc_shared_document_role_unknown:" + relative_path],
        "role": "unknown",
    }


def inspect_frozen_hardware_document_text(text: str) -> Dict[str, Any]:
    """Inventory the known-dangerous surfaces in the immutable legacy doc.

    These surfaces are not allowlisted as current commands.  They are accepted
    only when the enclosing file retains its exact external size/SHA identity
    and the separately read redirect is exact and clean.
    """
    missing = [
        token for token in HARDWARE_LEGACY_REQUIRED_SURFACES
        if token not in text
    ]
    return {
        "failures": [
            "ros1_doc_hardware_legacy_surface_inventory_mismatch"
        ] if missing else [],
        "required_surface_count": len(HARDWARE_LEGACY_REQUIRED_SURFACES),
        "required_surfaces_present": not missing,
        "missing_surfaces": missing,
        "contains_direct_legacy_ros2_commands": True,
        "commands_are_currently_authoritative": False,
    }


_HARDWARE_REDIRECT_DIRECT_COMMAND_PATTERNS: Tuple[
    Tuple[str, re.Pattern[str]], ...
] = (
    (
        "ros2_launch",
        re.compile(r"(?mi)^\s*(?:[$#]\s*)?ros2\s+launch\b"),
    ),
    (
        "ros2_graph",
        re.compile(r"(?mi)^\s*(?:[$#]\s*)?ros2\s+(?:node|topic|service)\b"),
    ),
    (
        "legacy_wrapper",
        re.compile(
            r"(?mi)^\s*(?:[$#]\s*)?"
            r"(?:\./)?scripts/run_hardware_readonly_acceptance\.sh(?:\s|$)"
        ),
    ),
    (
        "ros2_environment",
        re.compile(
            r"(?mi)^\s*(?:[$#]\s*)?(?:source|\.)\s+"
            r"/opt/ros/(?:foxy|humble)/setup\.bash\b"
        ),
    ),
    (
        "camera_start",
        re.compile(r"(?mi)^\s*[^#\r\n]*start_camera\s*:=\s*true\b"),
    ),
    (
        "uart_or_fuser",
        re.compile(r"(?mi)^\s*(?:[$#]\s*)?(?:sudo\s+)?fuser\s+/dev/"),
    ),
)


def validate_hardware_redirect_text(text: str) -> Dict[str, Any]:
    failures: List[str] = []
    raw = text.encode("utf-8")
    identity_exact = (
        len(raw) == HARDWARE_REDIRECT_SIZE_BYTES
        and _sha256(raw) == HARDWARE_REDIRECT_SHA256
    )
    if not identity_exact:
        failures.append("ros1_doc_hardware_redirect_identity_invalid")

    missing_tokens = [
        token for token in HARDWARE_REDIRECT_REQUIRED_TOKENS
        if token not in text
    ]
    if missing_tokens:
        failures.append("ros1_doc_hardware_redirect_weakened")
    if not text.startswith(
        "# Hardware readiness authority redirect / "
        "\u786c\u4ef6\u5c31\u7eea\u6743\u5a01\u91cd\u5b9a\u5411\n\n> [!CAUTION]\n"
        "> **`NON_AUTHORITATIVE_DO_NOT_RUN`"
    ):
        failures.append("ros1_doc_hardware_redirect_demotion_marker_invalid")

    for label, pattern in _HARDWARE_REDIRECT_DIRECT_COMMAND_PATTERNS:
        if pattern.search(text):
            failures.append(
                "ros1_doc_hardware_redirect_direct_operation_forbidden:"
                + label
            )
    for scope, pattern in _PROMOTION_PATTERNS:
        if pattern.search(text):
            failures.append(
                "ros1_doc_hardware_redirect_current_{}_promotion_forbidden".format(
                    scope
                )
            )

    route_tokens = (
        "Start with this redirect",
        HARDWARE_AUTHORITY_RUNBOOK,
        HARDWARE_ATOMIC_LAUNCHER,
        "remains fail-closed",
    )
    route_exact = all(token in text for token in route_tokens)
    if not route_exact:
        failures.append("ros1_doc_hardware_redirect_route_invalid")
    unique = sorted(set(failures))
    return {
        "failures": unique,
        "identity_exact": identity_exact,
        "demotion_exact": not missing_tokens and not unique,
        "route_exact": route_exact,
        "legacy_document_status": "NON_AUTHORITATIVE_DO_NOT_RUN",
        "accepted_as_release_selection_authority": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "authorizes_field_delivery": False,
        "delivery_ready": False,
    }


def validate_hardware_current_operations_index_text(
    text: str,
) -> Dict[str, Any]:
    failures: List[str] = []
    raw = text.encode("utf-8")
    identity_exact = (
        len(raw) == HARDWARE_CURRENT_OPERATIONS_INDEX_SIZE_BYTES
        and _sha256(raw) == HARDWARE_CURRENT_OPERATIONS_INDEX_SHA256
    )
    if not identity_exact:
        failures.append("ros1_doc_hardware_operations_index_identity_invalid")

    required_tokens = (
        "the only current human-entry route",
        HARDWARE_REDIRECT_RELATIVE_PATH,
        HARDWARE_AUTHORITY_RUNBOOK,
        str(HARDWARE_AUTHORITY_RUNBOOK_SIZE_BYTES),
        HARDWARE_AUTHORITY_RUNBOOK_SHA256,
        HARDWARE_ATOMIC_LAUNCHER,
        "TASK_SCOPED_NON_FORMAL",
        "not a delivery predecessor",
        "field-consumer acceptance, and delivery readiness false",
    )
    if any(token not in text for token in required_tokens):
        failures.append("ros1_doc_hardware_operations_index_weakened")

    positions = [
        text.find(HARDWARE_REDIRECT_RELATIVE_PATH),
        text.find(HARDWARE_AUTHORITY_RUNBOOK),
        text.find(HARDWARE_ATOMIC_LAUNCHER),
    ]
    route_exact = (
        all(position >= 0 for position in positions)
        and positions == sorted(positions)
        and len(set(positions)) == len(positions)
    )
    if not route_exact:
        failures.append("ros1_doc_hardware_operations_index_route_invalid")
    if not text.startswith(
        "# Perception V2 current operations index / \u5f53\u524d\u64cd\u4f5c\u7d22\u5f15\n\n"
        "> [!CAUTION]\n"
    ):
        failures.append("ros1_doc_hardware_operations_index_marker_invalid")
    for label, pattern in _HARDWARE_REDIRECT_DIRECT_COMMAND_PATTERNS:
        if pattern.search(text):
            failures.append(
                "ros1_doc_hardware_operations_index_direct_operation_forbidden:"
                + label
            )
    for scope, pattern in _PROMOTION_PATTERNS:
        if pattern.search(text):
            failures.append(
                "ros1_doc_hardware_operations_index_current_{}_promotion_forbidden".format(
                    scope
                )
            )
    unique = sorted(set(failures))
    return {
        "failures": unique,
        "identity_exact": identity_exact,
        "route_exact": route_exact,
        "accepted_as_release_selection_authority": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "authorizes_field_delivery": False,
        "delivery_ready": False,
    }


_HARDWARE_WRAPPER_ACTIVE_OPERATION = re.compile(
    r"(?mi)^\s*(?:(?:exec|command|nohup|sudo)\s+)*"
    r"(?:ros2|roslaunch|fuser)\b"
)
_HARDWARE_WRAPPER_SOURCE_ROS = re.compile(
    r"(?mi)^\s*(?:source|\.)\s+[^\r\n]*/opt/ros/"
)


def validate_hardware_wrapper_text(text: str) -> Dict[str, Any]:
    failures: List[str] = []
    raw = text.encode("utf-8")
    identity_exact = (
        len(raw) == HARDWARE_WRAPPER_SIZE_BYTES
        and _sha256(raw) == HARDWARE_WRAPPER_SHA256
    )
    if not identity_exact:
        failures.append("ros1_doc_hardware_wrapper_identity_invalid")

    missing = [
        token for token in HARDWARE_WRAPPER_REQUIRED_TOKENS
        if token not in text
    ]
    if missing:
        failures.append("ros1_doc_hardware_wrapper_guard_inventory_invalid")
    if (
        '"${LEGACY_ROS2_OFFLINE_ONLY:-}" != \'1\'' not in text
        or '"$#" -ne 1' not in text
        or '"$1" != \'--legacy-ros2-offline-only\'' not in text
    ):
        failures.append(
            "ros1_doc_hardware_wrapper_legacy_opt_in_guard_missing"
        )
    if (
        '"${ROS_LOCALHOST_ONLY:-}" != \'1\'' not in text
        or '"${ROS_DOMAIN_ID:-}" != "${isolated_domain}"' not in text
        or "readonly isolated_domain='{}'".format(
            HARDWARE_LEGACY_OFFLINE_DOMAIN_ID
        ) not in text
    ):
        failures.append("ros1_doc_hardware_wrapper_isolation_guard_missing")
    if any(
        token not in text
        for token in (
            "ROS_MASTER_URI",
            "ROS_IP",
            "ROS_HOSTNAME",
            "ROS_DISCOVERY_SERVER",
            "CYCLONEDDS_URI",
            "FASTRTPS_DEFAULT_PROFILES_FILE",
        )
    ):
        failures.append(
            "ros1_doc_hardware_wrapper_ambient_graph_guard_missing"
        )
    if any(
        token not in text
        for token in (
            "start_camera:=true",
            "'/camera/'",
            "'/dev/'",
            "ttyTHS",
            "fuser",
            "'ros2 topic'",
            "'ros2 node'",
            "'ros2 launch'",
            "roslaunch",
        )
    ):
        failures.append(
            "ros1_doc_hardware_wrapper_real_surface_guard_missing"
        )
    if (
        HARDWARE_REDIRECT_RELATIVE_PATH not in text
        or HARDWARE_AUTHORITY_RUNBOOK not in text
        or HARDWARE_ATOMIC_LAUNCHER not in text
    ):
        failures.append("ros1_doc_hardware_wrapper_redirect_route_invalid")
    if _HARDWARE_WRAPPER_ACTIVE_OPERATION.search(text):
        failures.append("ros1_doc_hardware_wrapper_active_ros_operation_forbidden")
    if _HARDWARE_WRAPPER_SOURCE_ROS.search(text):
        failures.append("ros1_doc_hardware_wrapper_ros_environment_source_forbidden")

    opt_in_index = text.find(
        '"${LEGACY_ROS2_OFFLINE_ONLY:-}" != \'1\''
    )
    success_index = text.find(
        "LEGACY_ROS2_OFFLINE_ONLY_PURE_STATIC_ACKNOWLEDGEMENT"
    )
    if opt_in_index < 0 or success_index < 0 or opt_in_index > success_index:
        failures.append("ros1_doc_hardware_wrapper_guard_order_invalid")
    unique = sorted(set(failures))
    return {
        "failures": unique,
        "identity_exact": identity_exact,
        "default_fail_closed": "if [[ \"$#\" -eq 0 ]]" in text,
        "legacy_ros2_offline_only_guarded": not unique,
        "invokes_ros": bool(_HARDWARE_WRAPPER_ACTIVE_OPERATION.search(text)),
        "authorizes_field_delivery": False,
        "delivery_ready": False,
    }


def _validate_authority_v5(value: Any) -> List[str]:
    failures: List[str] = []
    if not isinstance(value, Mapping):
        return ["ros1_doc_gate_authority_v5_root_invalid"]
    if (
        value.get("schema_version")
        != "ros1_formal_admission_evidence_authority/v4"
        or value.get("index_instance_id") != AUTHORITY_V5_INDEX_INSTANCE_ID
        or value.get("generation_id") != AUTHORITY_V5_GENERATION_ID
        or value.get("current_evidence_id") != AUTHORITY_V5_CURRENT_EVIDENCE_ID
        or value.get("accepted_as_offline_release_selection_authority") is not True
        or value.get("accepted_by_formal_field_evidence_consumer") is not False
        or value.get("authorizes_field_delivery") is not False
        or value.get("authorizes_motion") is not False
        or value.get("uses_filename_or_mtime_authority") is not False
    ):
        failures.append("ros1_doc_gate_authority_v5_identity_invalid")

    entries = value.get("entries")
    if not isinstance(entries, list):
        failures.append("ros1_doc_gate_authority_v5_entries_invalid")
    else:
        current = [
            item
            for item in entries
            if isinstance(item, Mapping) and item.get("is_current") is True
        ]
        if len(current) != 1:
            failures.append("ros1_doc_gate_authority_v5_current_count_invalid")
        else:
            item = current[0]
            if (
                item.get("evidence_id") != AUTHORITY_V5_CURRENT_EVIDENCE_ID
                or item.get("generation_id") != AUTHORITY_V5_GENERATION_ID
                or item.get("status") != "CURRENT_BLOCKED_OFFLINE"
                or item.get("lifecycle") != "CURRENT"
                or item.get("regression_passed") is not False
                or item.get("delivery_ready") is not False
                or item.get("authorizes_field_delivery") is not False
            ):
                failures.append("ros1_doc_gate_authority_v5_current_invalid")

    gate = value.get("gate_state")
    if not isinstance(gate, Mapping):
        failures.append("ros1_doc_gate_authority_v5_gate_state_invalid")
    else:
        expected_false = (
            "accepted_by_formal_field_evidence_consumer",
            "authorizes_field_delivery",
            "delivery_ready",
            "formal_3d_pass",
            "formal_latency_pass",
            "formal_tf_pass",
            "regression_passed",
            "ros1_noetic_build_install_verified",
            "ros1_noetic_field_install_pass",
            "ros1_noetic_runtime_verified",
        )
        if any(gate.get(key) is not False for key in expected_false):
            failures.append("ros1_doc_gate_authority_v5_gate_state_invalid")
        if type(gate.get("formal_four_scene_frame_denominator")) is not int or (
            gate.get("formal_four_scene_frame_denominator") != 0
        ):
            failures.append("ros1_doc_gate_authority_v5_gate_state_invalid")
    return sorted(set(failures))


def evaluate_machine_contract_docs(workspace_root: Path) -> Dict[str, Any]:
    failures: List[str] = []
    artifacts: List[Dict[str, Any]] = []

    contract_raw, contract_identity, contract_read_failures = _read_exact_file(
        workspace_root, CONTRACT_RELATIVE_PATH, "machine_contract"
    )
    failures.extend(contract_read_failures)
    contract_value: Any = None
    contract_details: Dict[str, Any] = {
        "document_records": [],
        "declaration_records": [],
        "document_paths": [],
    }
    if contract_raw is not None:
        artifacts.append({"role": "machine_contract", **contract_identity})
        if (
            contract_identity.get("size_bytes") != CONTRACT_SIZE_BYTES
            or contract_identity.get("sha256") != CONTRACT_SHA256
        ):
            failures.append("ros1_doc_gate_contract_identity_anchor_mismatch")
        contract_value, json_failures = _strict_json(
            contract_raw, "machine_contract"
        )
        failures.extend(json_failures)
        if not json_failures:
            contract_failures, contract_details = _validate_contract(
                contract_value
            )
            failures.extend(contract_failures)

    document_reports: List[Dict[str, Any]] = []
    for relative in contract_details.get("document_paths", []):
        raw, identity, read_failures = _read_exact_file(
            workspace_root, relative, "contract_document"
        )
        failures.extend(read_failures)
        if raw is None:
            continue
        artifacts.append({"role": "contract_document", **identity})
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_gate_document_utf8_invalid:" + relative)
            continue
        report = validate_document_text(relative, text)
        document_reports.append({"path": relative, **report})
        failures.extend(report["failures"])

    shared_document_reports: List[Dict[str, Any]] = []
    shared_root = Path(workspace_root).parent
    for relative, expected_size, expected_sha256 in SHARED_DOCUMENT_IDENTITIES:
        raw, identity, read_failures = _read_exact_file(
            shared_root, relative, "shared_document"
        )
        failures.extend(read_failures)
        if raw is None:
            continue
        artifacts.append({"role": "shared_document", **identity})
        if (
            identity.get("size_bytes") != expected_size
            or identity.get("sha256") != expected_sha256
        ):
            failures.append(
                "ros1_doc_shared_identity_anchor_mismatch:" + relative
            )
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_shared_utf8_invalid:" + relative)
            continue
        report = validate_shared_document_text(relative, text)
        shared_document_reports.append({"path": relative, **report})
        failures.extend(report["failures"])

    authority_raw, authority_identity, authority_read_failures = _read_exact_file(
        workspace_root, AUTHORITY_V5_RELATIVE_PATH, "authority_v5_index"
    )
    failures.extend(authority_read_failures)
    authority_valid = False
    if authority_raw is not None:
        artifacts.append({"role": "authority_v5_index", **authority_identity})
        if (
            authority_identity.get("size_bytes") != AUTHORITY_V5_SIZE_BYTES
            or authority_identity.get("sha256") != AUTHORITY_V5_SHA256
        ):
            failures.append("ros1_doc_gate_authority_v5_anchor_mismatch")
        authority_value, json_failures = _strict_json(
            authority_raw, "authority_v5_index"
        )
        failures.extend(json_failures)
        if not json_failures:
            authority_failures = _validate_authority_v5(authority_value)
            failures.extend(authority_failures)
            authority_valid = (
                not authority_failures
                and authority_identity.get("size_bytes")
                == AUTHORITY_V5_SIZE_BYTES
                and authority_identity.get("sha256") == AUTHORITY_V5_SHA256
            )

    declaration_records = contract_details.get("declaration_records", [])
    source_declaration_false = bool(declaration_records) and all(
        item.get("value") is False for item in declaration_records
    )
    documents_clean = bool(document_reports) and all(
        not item.get("failures") for item in document_reports
    )
    shared_documents_clean = (
        len(shared_document_reports) == len(SHARED_DOCUMENT_IDENTITIES)
        and all(not item.get("failures") for item in shared_document_reports)
    )

    hardware_legacy_report: Dict[str, Any] = {}
    hardware_legacy_identity_exact = False
    hardware_raw, hardware_identity, hardware_read_failures = _read_exact_file(
        workspace_root, HARDWARE_LEGACY_RELATIVE_PATH, "hardware_legacy_document"
    )
    failures.extend(hardware_read_failures)
    if hardware_raw is None:
        failures.append("ros1_doc_hardware_legacy_document_missing")
    else:
        artifacts.append(
            {"role": "hardware_legacy_document", **hardware_identity}
        )
        hardware_legacy_identity_exact = (
            hardware_identity.get("size_bytes") == HARDWARE_LEGACY_SIZE_BYTES
            and hardware_identity.get("sha256") == HARDWARE_LEGACY_SHA256
        )
        if not hardware_legacy_identity_exact:
            failures.append(
                "ros1_doc_hardware_legacy_identity_anchor_mismatch"
            )
        try:
            hardware_text = hardware_raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_hardware_legacy_utf8_invalid")
        else:
            hardware_legacy_report = inspect_frozen_hardware_document_text(
                hardware_text
            )
            failures.extend(hardware_legacy_report["failures"])

    hardware_redirect_report: Dict[str, Any] = {}
    redirect_raw, redirect_identity, redirect_read_failures = _read_exact_file(
        workspace_root, HARDWARE_REDIRECT_RELATIVE_PATH, "hardware_redirect"
    )
    failures.extend(redirect_read_failures)
    if redirect_raw is None:
        failures.append("ros1_doc_hardware_redirect_missing")
    else:
        artifacts.append({"role": "hardware_authority_redirect", **redirect_identity})
        if (
            redirect_identity.get("size_bytes") != HARDWARE_REDIRECT_SIZE_BYTES
            or redirect_identity.get("sha256") != HARDWARE_REDIRECT_SHA256
        ):
            failures.append("ros1_doc_hardware_redirect_anchor_mismatch")
        try:
            redirect_text = redirect_raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_hardware_redirect_utf8_invalid")
        else:
            hardware_redirect_report = validate_hardware_redirect_text(
                redirect_text
            )
            failures.extend(hardware_redirect_report["failures"])

    hardware_wrapper_report: Dict[str, Any] = {}
    wrapper_raw, wrapper_identity, wrapper_read_failures = _read_exact_file(
        workspace_root, HARDWARE_WRAPPER_RELATIVE_PATH, "hardware_legacy_wrapper"
    )
    failures.extend(wrapper_read_failures)
    if wrapper_raw is None:
        failures.append("ros1_doc_hardware_wrapper_missing")
    else:
        artifacts.append({"role": "hardware_legacy_wrapper", **wrapper_identity})
        if (
            wrapper_identity.get("size_bytes") != HARDWARE_WRAPPER_SIZE_BYTES
            or wrapper_identity.get("sha256") != HARDWARE_WRAPPER_SHA256
        ):
            failures.append("ros1_doc_hardware_wrapper_anchor_mismatch")
        try:
            wrapper_text = wrapper_raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_hardware_wrapper_utf8_invalid")
        else:
            hardware_wrapper_report = validate_hardware_wrapper_text(
                wrapper_text
            )
            failures.extend(hardware_wrapper_report["failures"])

    hardware_operations_index_report: Dict[str, Any] = {}
    operations_raw, operations_identity, operations_read_failures = (
        _read_exact_file(
            workspace_root,
            HARDWARE_CURRENT_OPERATIONS_INDEX_RELATIVE_PATH,
            "hardware_current_operations_index",
        )
    )
    failures.extend(operations_read_failures)
    if operations_raw is None:
        failures.append("ros1_doc_hardware_operations_index_missing")
    else:
        artifacts.append(
            {"role": "hardware_current_operations_index", **operations_identity}
        )
        if (
            operations_identity.get("size_bytes")
            != HARDWARE_CURRENT_OPERATIONS_INDEX_SIZE_BYTES
            or operations_identity.get("sha256")
            != HARDWARE_CURRENT_OPERATIONS_INDEX_SHA256
        ):
            failures.append("ros1_doc_hardware_operations_index_anchor_mismatch")
        try:
            operations_text = operations_raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_hardware_operations_index_utf8_invalid")
        else:
            hardware_operations_index_report = (
                validate_hardware_current_operations_index_text(operations_text)
            )
            failures.extend(hardware_operations_index_report["failures"])

    runbook_identity_exact = False
    runbook_raw, runbook_identity, runbook_read_failures = _read_exact_file(
        workspace_root, HARDWARE_AUTHORITY_RUNBOOK, "hardware_authority_runbook"
    )
    failures.extend(runbook_read_failures)
    if runbook_raw is None:
        failures.append("ros1_doc_hardware_authority_runbook_missing")
    else:
        artifacts.append({"role": "hardware_authority_runbook", **runbook_identity})
        runbook_identity_exact = (
            runbook_identity.get("size_bytes")
            == HARDWARE_AUTHORITY_RUNBOOK_SIZE_BYTES
            and runbook_identity.get("sha256")
            == HARDWARE_AUTHORITY_RUNBOOK_SHA256
        )
        if not runbook_identity_exact:
            failures.append(
                "ros1_doc_hardware_authority_runbook_anchor_mismatch"
            )
        try:
            runbook_raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("ros1_doc_hardware_authority_runbook_utf8_invalid")

    hardware_redirect_clean = bool(hardware_redirect_report) and not (
        hardware_redirect_report.get("failures")
    )
    hardware_wrapper_clean = bool(hardware_wrapper_report) and not (
        hardware_wrapper_report.get("failures")
    )
    hardware_legacy_demoted = (
        hardware_legacy_identity_exact
        and bool(hardware_legacy_report)
        and not hardware_legacy_report.get("failures")
        and hardware_redirect_clean
        and hardware_wrapper_clean
    )
    if hardware_legacy_report and not hardware_legacy_demoted:
        failures.append("ros1_doc_hardware_legacy_not_safely_demoted")

    hardware_operations_index_clean = bool(
        hardware_operations_index_report
    ) and not hardware_operations_index_report.get("failures")
    hardware_current_operational_route_valid = (
        hardware_legacy_demoted
        and hardware_operations_index_clean
        and runbook_identity_exact
    )
    if hardware_legacy_demoted and not hardware_current_operational_route_valid:
        failures.append("ros1_doc_hardware_current_operational_route_invalid")

    unique_failures = sorted(set(failures))
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_scope": "TASK_SCOPED_NON_FORMAL_DOCUMENT_DEMOTION",
        "validated_pass": not unique_failures,
        "failures": unique_failures,
        "contract_identity": contract_identity,
        "contract_document_records": contract_details.get(
            "document_records", []
        ),
        "contract_document_paths": contract_details.get("document_paths", []),
        "source_declaration_records": declaration_records,
        "source_declaration_is_install_evidence": (
            False if source_declaration_false else None
        ),
        "document_reports": document_reports,
        "document_demotion_clean": documents_clean,
        "shared_document_reports": shared_document_reports,
        "shared_document_demotion_clean": shared_documents_clean,
        "hardware_legacy_document_identity": hardware_identity,
        "hardware_legacy_document_report": hardware_legacy_report,
        "hardware_redirect_identity": redirect_identity,
        "hardware_redirect_report": hardware_redirect_report,
        "hardware_wrapper_identity": wrapper_identity,
        "hardware_wrapper_report": hardware_wrapper_report,
        "hardware_current_operations_index_identity": operations_identity,
        "hardware_current_operations_index_report": (
            hardware_operations_index_report
        ),
        "hardware_authority_runbook_identity": runbook_identity,
        "hardware_legacy_document_demoted": hardware_legacy_demoted,
        "hardware_current_operational_route": (
            [
                HARDWARE_CURRENT_OPERATIONS_INDEX_RELATIVE_PATH,
                HARDWARE_REDIRECT_RELATIVE_PATH,
                HARDWARE_AUTHORITY_RUNBOOK,
                HARDWARE_ATOMIC_LAUNCHER,
            ] if hardware_current_operational_route_valid else []
        ),
        "hardware_current_operational_route_valid": (
            hardware_current_operational_route_valid
        ),
        "artifacts": artifacts,
        "frozen_predecessor_authority_index_instance_id": (
            AUTHORITY_V5_INDEX_INSTANCE_ID if authority_valid else None
        ),
        "frozen_predecessor_authority_evidence_id": (
            AUTHORITY_V5_CURRENT_EVIDENCE_ID if authority_valid else None
        ),
        "predecessor_authority_v5_identity_and_internal_current_valid": (
            authority_valid
        ),
        "accepted_as_offline_release_selection_authority": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "authorizes_field_delivery": False,
        "authorizes_motion": False,
        "formal_four_scene_frame_denominator": 0,
        "ros1_noetic_build_install_verified": False,
        "ros1_noetic_runtime_verified": False,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "formal_latency_pass": False,
        "delivery_ready": False,
    }


def main(args: Sequence[str] | None = None) -> int:
    if args:
        raise SystemExit("no arguments accepted")
    workspace = Path(__file__).resolve().parents[1]
    report = evaluate_machine_contract_docs(workspace)
    sys.stdout.write(
        MARKER
        + json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    return 0 if report["validated_pass"] else 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
