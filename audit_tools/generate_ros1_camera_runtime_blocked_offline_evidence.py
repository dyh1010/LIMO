#!/usr/bin/env python3
"""Generate the immutable camera-runtime ``BLOCKED_OFFLINE`` evidence pair.

This host-owned utility has only standard-library imports.  It is deliberately
not an authority resolver and never starts ROS, opens a camera, imports a ROS
client, runs inference, or contacts hardware.  It recomputes the live ROS1
overlay binding, runs the exact offline test matrix in isolated child
interpreters, and creates one new canonical binding and one new regression
report with ``O_EXCL``.  It never writes an authority index and never replaces
an existing artifact.

Run from the repository generation that contains this file, using a clean
Linux interpreter with ``-I -B``.  ``--plan`` is read-only; ``--generate`` is
the only writing mode.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import types
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


GENERATION_ID = "ros1_camera_runtime_install_blocked_offline_20260815_v5"
CANONICAL_ID = (
    "ros1-noetic-canonical-source-admission-20260815-v6-blocked-offline")
CANONICAL_ARTIFACT_ID = (
    "ros1_noetic_canonical_source_admission_20260815_v6_blocked_offline")
CANONICAL_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "ros1_noetic_canonical_source_admission_20260815_v6_blocked_offline.json")

REPORT_EVIDENCE_ID = (
    "ros1_camera_runtime_install_blocked_offline_regression_20260815_v5")
REPORT_ID = (
    "ros1-camera-runtime-install-blocked-offline-report-20260815-v5")
REPORT_RELATIVE_PATH = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_"
    "camera_runtime_install_blocked_offline_v5.json")

PLAN_MARKER = "ROS1_CAMERA_RUNTIME_BLOCKED_OFFLINE_EVIDENCE_PLAN "
GENERATED_MARKER = "ROS1_CAMERA_RUNTIME_BLOCKED_OFFLINE_EVIDENCE_GENERATED "

EXPECTED_LIVE_OVERLAY_FILE_COUNT = 51
EXPECTED_LIVE_OVERLAY_SOURCE_SET_SHA256 = (
    "2850f25cdac82e4759a40753db49677d3abe3b881814cf8d1f3e30299523d54e")
EXPECTED_LIVE_OVERLAY_BINDING_SHA256 = (
    "742231c30627b5209dd26e5243b1cbed5dca4f5d29bae67363f06560ee658b0d")
EXPECTED_LOGICAL_COUNT = 155
EXPECTED_PHYSICAL_COUNT = 263
COMMAND_TIMEOUT_SECONDS = 1800

PYTHON_ENTRIES = ("/usr/bin/python3", "/usr/bin/python3.14")
PRIMARY_PYTHON = "/usr/bin/python3.14"
UNITTEST_RUNNER = "audit_tools/run_unittest_file_tests.py"
PYTEST_RUNNER = "audit_tools/run_pytest_style_tests.py"
UNITTEST_MARKER = "OFFLINE_UNITTEST_FILE_RESULT "
PYTEST_MARKER = "OFFLINE_PYTEST_FILE_RESULT "

PREDECESSOR_AUTHORITY = {
    "index_instance_id": (
        "ros1-formal-admission-evidence-authority-index-20260815-v4"),
    "generation_id": "ros1_runner_platform_composite_20260815_v4",
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_v4.json"),
    "size_bytes": 5015,
    "sha256": (
        "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded"),
}

FROZEN_EXPECTED_IDENTITIES: Mapping[str, Tuple[int, str]] = {
    PREDECESSOR_AUTHORITY["path"]: (
        PREDECESSOR_AUTHORITY["size_bytes"], PREDECESSOR_AUTHORITY["sha256"]),
    "evidence/perception_v2_offline_20260813/"
    "ros1_noetic_canonical_source_admission_20260815_v5.json": (
        9889,
        "1c4a9c2901cae292803cec4a700550c2054a26b94e1ae89aacbedb3865e7801a",
    ),
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_runner_platform_composite_v4.json": (
        1288709,
        "dfa7e3f8c53f6157fec5083b26b8fc87b3115dcfb9eb6fbbde2fbcf52775c5be",
    ),
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_"
    "runner_platform_composite_diagnostic_v2.json": (
        1212313,
        "fdeffd18244633ccc7e9407dafa606a2799f03fb517be5b11c881aff8d146548",
    ),
    "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch": (
        6446,
        "75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e",
    ),
    "evidence/perception_v2_field_20260814/user_startup_screenshots/"
    "01_roslaunch_dabai_u3.png": (
        250085,
        "64e0132c70931f179d2fd70ff49821e5e24bb16f8ecfdb3ad79054a3d353e7eb",
    ),
    "evidence/perception_v2_field_20260814/user_startup_screenshots/"
    "02_rqt_image_view_command.png": (
        121298,
        "b7905a55dd7ca3476549988990569d7d56c0c633e4f5ba81a906c9544cfbcf28",
    ),
    "evidence/perception_v2_field_20260814/user_startup_screenshots/"
    "03_rqt_color_stream.png": (
        653709,
        "d7c85560946b2aa8938b10214f8d7cab29bd6a016cb1823cc1cb3a2bf2e78188",
    ),
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/"
    "v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag": (
        81634393,
        "31a9c280aaa8d1ce6f1836bb9a445eafd87fbc5b096967932484c2f4c6982168",
    ),
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/"
    "v2_ros1_shared_graph_diagnostic_20260814T052442Z."
    "diagnostic-manifest-v3.json": (
        6989444,
        "4683b682b908a2325232aa604a3b7e6367dd0404a84baf0013d159ab8da7e08f",
    ),
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/"
    "v2_ros1_shared_graph_diagnostic_20260814T052442Z.formal-gate-v3.json": (
        1661,
        "678e51ac185605471f4ec68d2ce67ffcf680f65704aba6567ec12d6014c63966",
    ),
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_ros1_canonical_source_binding_v6.json": (
        188673,
        "d2cb327499c79cd6f90f1ac7f72a9edb52dac85d08cb8dc563d1e078776b6239",
    ),
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_"
    "ros1_canonical_source_binding_v6_final.json": (
        189637,
        "dd7290195cdd6776eb8d8e6d8db4c4cbeb8b87f49be760b7c39fdc9392181a87",
    ),
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json": (
        190747,
        "dac31ed678ff7c3a8f4494c5b865f89a41715ee5555e80ef12a8ba4b895f6789",
    ),
    "audit_tools/formal_admission_evidence_authority_v3.py": (
        76863,
        "ef8fa135d2b1ec8f6ef906975732961ff717af9e9c603fc072f8b1a5959c5f39",
    ),
}

HOST_SOURCE_PATHS = (
    "audit_tools/ros1_camera_runtime_import_probe.py",
    "audit_tools/ros1_camera_runtime_install_admission.py",
    "audit_tools/ros1_camera_only_atomic_launcher.py",
    "audit_tools/ros1_camera_only_field_preflight.py",
    "audit_tools/ros1_camera_only_operator_docs.py",
    "audit_tools/formal_admission_evidence_authority_v4_core.py",
)
TEST_PATHS = (
    "audit_tools/test_ros1_camera_runtime_import_probe.py",
    "audit_tools/test_ros1_camera_runtime_install_admission.py",
    "audit_tools/test_ros1_camera_only_atomic_launcher.py",
    "audit_tools/test_ros1_camera_only_field_preflight.py",
    "audit_tools/test_ros1_camera_only_operator_docs.py",
    "src/limo_cleanup_perception/test/test_ros1_dabai_runtime_contract.py",
    "audit_tools/test_formal_admission_evidence_authority_v4.py",
)
RUNNER_PATHS = (
    UNITTEST_RUNNER,
    PYTEST_RUNNER,
    "audit_tools/generate_ros1_camera_runtime_blocked_offline_evidence.py",
)
RUNTIME_CONTRACT_PATHS = (
    "src/limo_cleanup_perception/fixtures/ros1_dabai_runtime_contract.json",
)
DOCUMENT_PATHS = (
    "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md",
    "docs/hardware_readiness.md",
    "docs/real_perception.md",
    "docs/limo_pro_manual_reference.md",
    "docs/PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md",
    "src/limo_cleanup_dabai_sensor/README.md",
)
RETIRED_PATHS = ("scripts/start_dabai_camera.sh",)
FROZEN_REFERENCE_PATHS = (
    PREDECESSOR_AUTHORITY["path"],
    "evidence/perception_v2_offline_20260813/"
    "ros1_noetic_canonical_source_admission_20260815_v5.json",
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_runner_platform_composite_v4.json",
    "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch",
    "audit_tools/formal_admission_evidence_authority_v3.py",
)
HISTORICAL_DIAGNOSTIC_PATHS = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260815_"
    "runner_platform_composite_diagnostic_v2.json",
    "evidence/perception_v2_field_20260814/user_startup_screenshots/"
    "01_roslaunch_dabai_u3.png",
    "evidence/perception_v2_field_20260814/user_startup_screenshots/"
    "02_rqt_image_view_command.png",
    "evidence/perception_v2_field_20260814/user_startup_screenshots/"
    "03_rqt_color_stream.png",
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/"
    "v2_ros1_shared_graph_diagnostic_20260814T052442Z.bag",
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/"
    "v2_ros1_shared_graph_diagnostic_20260814T052442Z."
    "diagnostic-manifest-v3.json",
    "evidence/perception_v2_field_20260814/diagnostic_shared_graph/"
    "v2_ros1_shared_graph_diagnostic_20260814T052442Z.formal-gate-v3.json",
)
HISTORICAL_REGRESSION_PATHS = (
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_ros1_canonical_source_binding_v6.json",
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_"
    "ros1_canonical_source_binding_v6_final.json",
    "evidence/perception_v2_offline_20260813/"
    "frozen_offline_regression_20260814_ros1_canonical_source_binding_v7.json",
)

SUITES: Tuple[Mapping[str, Any], ...] = (
    {
        "suite_id": "camera_runtime_import_probe",
        "target": "audit_tools/test_ros1_camera_runtime_import_probe.py",
        "runner": "unittest",
        "logical_count": 26,
        "interpreters": PYTHON_ENTRIES,
    },
    {
        "suite_id": "camera_runtime_install_admission",
        "target": "audit_tools/test_ros1_camera_runtime_install_admission.py",
        "runner": "unittest",
        "logical_count": 40,
        "interpreters": PYTHON_ENTRIES,
    },
    {
        "suite_id": "camera_only_atomic_launcher",
        "target": "audit_tools/test_ros1_camera_only_atomic_launcher.py",
        "runner": "unittest",
        "logical_count": 42,
        "interpreters": PYTHON_ENTRIES,
    },
    {
        "suite_id": "camera_only_field_preflight",
        "target": "audit_tools/test_ros1_camera_only_field_preflight.py",
        "runner": "unittest",
        "logical_count": 18,
        "interpreters": (PRIMARY_PYTHON,),
    },
    {
        "suite_id": "camera_only_operator_docs",
        "target": "audit_tools/test_ros1_camera_only_operator_docs.py",
        "runner": "unittest",
        "logical_count": 24,
        "interpreters": (PRIMARY_PYTHON,),
    },
    {
        "suite_id": "dabai_runtime_contract",
        "target": "src/limo_cleanup_perception/test/"
        "test_ros1_dabai_runtime_contract.py",
        "runner": "pytest_style",
        "logical_count": 5,
        "interpreters": (PRIMARY_PYTHON,),
    },
)

SOURCE_ROLE_DEFINITIONS: Tuple[Tuple[str, str], ...] = (
    ("camera_runtime_import_probe", HOST_SOURCE_PATHS[0]),
    ("camera_runtime_import_probe_test", TEST_PATHS[0]),
    ("camera_runtime_install_admission", HOST_SOURCE_PATHS[1]),
    ("camera_runtime_install_admission_test", TEST_PATHS[1]),
    ("camera_only_atomic_launcher", HOST_SOURCE_PATHS[2]),
    ("camera_only_atomic_launcher_test", TEST_PATHS[2]),
    ("camera_only_field_preflight", HOST_SOURCE_PATHS[3]),
    ("camera_only_field_preflight_test", TEST_PATHS[3]),
    ("camera_only_operator_docs", HOST_SOURCE_PATHS[4]),
    ("camera_only_operator_docs_test", TEST_PATHS[4]),
    ("dabai_runtime_contract_test", TEST_PATHS[5]),
    ("dabai_runtime_contract_fixture", RUNTIME_CONTRACT_PATHS[0]),
    ("unittest_isolated_runner", UNITTEST_RUNNER),
    ("pytest_style_isolated_runner", PYTEST_RUNNER),
    ("blocked_offline_evidence_generator", RUNNER_PATHS[2]),
    ("blocked_offline_authority_core", HOST_SOURCE_PATHS[5]),
    ("blocked_offline_authority_test", TEST_PATHS[6]),
    ("field_runbook", DOCUMENT_PATHS[0]),
    ("hardware_readiness_document", DOCUMENT_PATHS[1]),
    ("real_perception_document", DOCUMENT_PATHS[2]),
    ("manual_reference_document", DOCUMENT_PATHS[3]),
    ("field_readiness_runbook", DOCUMENT_PATHS[4]),
    ("dabai_sensor_readme", DOCUMENT_PATHS[5]),
    ("retired_dabai_start_script", RETIRED_PATHS[0]),
    ("predecessor_authority_index", FROZEN_REFERENCE_PATHS[0]),
    ("predecessor_regression_report", FROZEN_REFERENCE_PATHS[2]),
    ("predecessor_canonical_source", FROZEN_REFERENCE_PATHS[1]),
    ("archived_dabai_launch_reference", FROZEN_REFERENCE_PATHS[3]),
    ("predecessor_authority_resolver", FROZEN_REFERENCE_PATHS[4]),
    ("historical_runner_platform_diagnostic_v2", HISTORICAL_DIAGNOSTIC_PATHS[0]),
    ("startup_screenshot_roslaunch", HISTORICAL_DIAGNOSTIC_PATHS[1]),
    ("startup_screenshot_rqt_command", HISTORICAL_DIAGNOSTIC_PATHS[2]),
    ("startup_screenshot_rqt_stream", HISTORICAL_DIAGNOSTIC_PATHS[3]),
    ("diagnostic_shared_graph_bag", HISTORICAL_DIAGNOSTIC_PATHS[4]),
    ("diagnostic_shared_graph_manifest", HISTORICAL_DIAGNOSTIC_PATHS[5]),
    ("diagnostic_shared_graph_formal_gate", HISTORICAL_DIAGNOSTIC_PATHS[6]),
    ("historical_canonical_source_binding_v6", HISTORICAL_REGRESSION_PATHS[0]),
    ("historical_canonical_source_binding_v6_final", HISTORICAL_REGRESSION_PATHS[1]),
    ("historical_canonical_source_binding_v7", HISTORICAL_REGRESSION_PATHS[2]),
)

PHYSICAL_RECORD_IDS: Mapping[Tuple[str, str], Tuple[str, str]] = {
    ("camera_runtime_import_probe", "/usr/bin/python3"):
        ("probe_posix_python3", "system_python3_entry"),
    ("camera_runtime_import_probe", "/usr/bin/python3.14"):
        ("probe_posix_python314", "system_python314_target"),
    ("camera_runtime_install_admission", "/usr/bin/python3"):
        ("install_posix_python3", "system_python3_entry"),
    ("camera_runtime_install_admission", "/usr/bin/python3.14"):
        ("install_posix_python314", "system_python314_target"),
    ("camera_only_atomic_launcher", "/usr/bin/python3"):
        ("atomic_posix_python3", "system_python3_entry"),
    ("camera_only_atomic_launcher", "/usr/bin/python3.14"):
        ("atomic_posix_python314", "system_python314_target"),
    ("camera_only_field_preflight", "/usr/bin/python3.14"):
        ("preflight_posix_python314", "system_python314_target"),
    ("camera_only_operator_docs", "/usr/bin/python3.14"):
        ("operator_docs_posix_python314", "system_python314_target"),
    ("dabai_runtime_contract", "/usr/bin/python3.14"):
        ("runtime_contract_posix_python314", "system_python314_target"),
}

CHILD_ENVIRONMENT = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}
SENSITIVE_GENERATOR_ENVIRONMENT = (
    "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "ROS_PACKAGE_PATH", "ROS_MASTER_URI",
)


class GenerationError(RuntimeError):
    """Stable local generation failure."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _pretty_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, allow_nan=False, ensure_ascii=False, indent=2,
        sort_keys=True) + "\n").encode("utf-8")


def _strict_pairs(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non_finite_json_constant:" + value)


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
        parse_constant=_reject_constant)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GenerationError("workspace_relative_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise GenerationError("workspace_relative_path_invalid:" + value)
    normalized = path.as_posix()
    if normalized != value:
        raise GenerationError("workspace_relative_path_not_canonical:" + value)
    return normalized


def _workspace_root() -> Path:
    source = Path(__file__)
    if source.is_symlink():
        raise GenerationError("generator_source_link_forbidden")
    root = source.resolve(strict=True).parents[1]
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise GenerationError("workspace_root_invalid")
    return root


def _workspace_path(root: Path, relative: str, expect_file: bool = True) -> Path:
    relative = _relative_path(relative)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for component in PurePosixPath(relative).parts:
        current = current / component
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise GenerationError("workspace_path_link_forbidden:" + relative)
    resolved = candidate.resolve(strict=True)
    if not _is_relative_to(resolved, root) or resolved != candidate:
        raise GenerationError("workspace_path_resolution_mismatch:" + relative)
    if expect_file:
        metadata = resolved.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise GenerationError("workspace_artifact_not_regular:" + relative)
    return resolved


def _read_regular_identity(path: Path, reported_path: str) -> Mapping[str, Any]:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise GenerationError("artifact_linklike_or_nonregular:" + reported_path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(path), flags)
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (before.st_dev, before.st_ino)):
            raise GenerationError("artifact_changed_before_open:" + reported_path)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (stat.S_ISLNK(after.st_mode) or not stat.S_ISREG(after.st_mode)
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or size != opened.st_size or opened.st_size != after.st_size):
        raise GenerationError("artifact_changed_during_read:" + reported_path)
    return {
        "path": reported_path,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def _workspace_identity(root: Path, relative: str) -> Mapping[str, Any]:
    relative = _relative_path(relative)
    return _read_regular_identity(_workspace_path(root, relative), relative)


def _workspace_bytes(root: Path, relative: str) -> Tuple[bytes, Mapping[str, Any]]:
    path = _workspace_path(root, relative)
    before = _workspace_identity(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(path), flags)
    chunks = []
    try:
        opened = os.fstat(descriptor)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    after = _workspace_identity(root, relative)
    if (before != after or opened.st_size != len(raw)
            or hashlib.sha256(raw).hexdigest() != before["sha256"]):
        raise GenerationError("workspace_artifact_byte_read_drift:" + relative)
    return raw, before


def _external_identity(path: Path) -> Mapping[str, Any]:
    if not path.is_absolute():
        raise GenerationError("external_identity_path_not_absolute")
    if path.is_symlink():
        raise GenerationError("external_identity_target_is_link:" + str(path))
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise GenerationError("external_identity_resolution_mismatch:" + str(path))
    return _read_regular_identity(resolved, str(resolved))


def _executable_identity(entry_text: str) -> Mapping[str, Any]:
    entry = Path(entry_text)
    if not entry.is_absolute():
        raise GenerationError("python_entry_not_absolute:" + entry_text)
    current = entry
    seen = set()
    chain = []
    for _unused in range(64):
        key = str(current)
        if key in seen:
            raise GenerationError("python_entry_link_cycle:" + entry_text)
        seen.add(key)
        metadata = current.lstat()
        if not stat.S_ISLNK(metadata.st_mode):
            break
        link_text = os.readlink(os.fspath(current))
        destination = Path(link_text)
        if not destination.is_absolute():
            destination = current.parent / destination
        destination = Path(os.path.abspath(os.fspath(destination)))
        chain.append({
            "path": str(current),
            "link_text": link_text,
            "next_path": str(destination),
            "lstat_size_bytes": metadata.st_size,
        })
        current = destination
    else:
        raise GenerationError("python_entry_link_chain_too_long:" + entry_text)
    resolved = entry.resolve(strict=True)
    if resolved != current.resolve(strict=True):
        raise GenerationError("python_entry_link_resolution_mismatch:" + entry_text)
    return {
        "entry_path": str(entry),
        "entry_is_symlink": bool(chain),
        "entry_link_chain": chain,
        "resolved_target": _external_identity(resolved),
    }


def _require_clean_generator_context() -> None:
    if not sys.flags.isolated:
        raise GenerationError("generator_requires_python_isolated_mode")
    if not sys.dont_write_bytecode:
        raise GenerationError("generator_requires_python_no_bytecode_mode")
    if not sys.flags.no_site:
        raise GenerationError("generator_requires_python_no_site_mode")
    if not sys.platform.startswith("linux"):
        raise GenerationError("generator_requires_linux_posix_environment")
    contaminated = [
        key for key in SENSITIVE_GENERATOR_ENVIRONMENT
        if os.environ.get(key) not in (None, "")]
    contaminated.extend(
        key for key, value in os.environ.items()
        if key.startswith("ROS_") and value not in (None, ""))
    if contaminated:
        raise GenerationError(
            "generator_environment_contaminated:" + ",".join(sorted(set(contaminated))))


def _artifact_id(relative: str) -> str:
    return "workspace-artifact-" + hashlib.sha256(
        relative.encode("utf-8")).hexdigest()[:32]


def _assert_expected_identity(identity: Mapping[str, Any]) -> None:
    expected = FROZEN_EXPECTED_IDENTITIES.get(identity["path"])
    if expected is None:
        return
    if (identity["size_bytes"], identity["sha256"]) != expected:
        raise GenerationError("frozen_artifact_identity_mismatch:" + identity["path"])


def _assignment_literals(path: Path, names: Sequence[str]) -> Mapping[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = set(names)
    values: Dict[str, Any] = {}
    for node in tree.body:
        name = None
        value_node = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value_node = node.value
        if name in wanted and value_node is not None:
            try:
                values[name] = ast.literal_eval(value_node)
            except (TypeError, ValueError):
                raise GenerationError("source_anchor_not_literal:" + name)
    if set(values) != wanted:
        raise GenerationError(
            "source_anchor_missing:" + ",".join(sorted(wanted - set(values))))
    return values


def _validate_host_source_anchors(
        root: Path, identities: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    """Prove that production anchors remain deliberately unbound and exact."""
    probe_path = _workspace_path(
        root, "audit_tools/ros1_camera_runtime_import_probe.py")
    probe_values = _assignment_literals(probe_path, (
        "PRODUCTION_SPEC_PATH", "PRODUCTION_SPEC_SIZE_BYTES",
        "PRODUCTION_SPEC_SHA256", "PRODUCTION_SPEC_TRUST_ROOT",
    ))
    if any(probe_values[key] is not None for key in probe_values):
        raise GenerationError("production_import_probe_spec_must_remain_unbound")

    admission_path = _workspace_path(
        root, "audit_tools/ros1_camera_runtime_install_admission.py")
    admission_values = _assignment_literals(admission_path, (
        "PRODUCTION_AUTHORITY_PATH", "PRODUCTION_AUTHORITY_SIZE_BYTES",
        "PRODUCTION_AUTHORITY_SHA256", "RUNTIME_IMPORT_PROBE_SIZE_BYTES",
        "RUNTIME_IMPORT_PROBE_SHA256",
    ))
    if admission_values["PRODUCTION_AUTHORITY_PATH"] != (
            "/etc/limo/camera_runtime_install_authority.json"):
        raise GenerationError("production_install_authority_path_drift")
    if (admission_values["PRODUCTION_AUTHORITY_SIZE_BYTES"] is not None
            or admission_values["PRODUCTION_AUTHORITY_SHA256"] is not None):
        raise GenerationError("production_install_authority_must_remain_unbound")
    probe_identity = identities[
        "audit_tools/ros1_camera_runtime_import_probe.py"]
    if (admission_values["RUNTIME_IMPORT_PROBE_SIZE_BYTES"]
            != probe_identity["size_bytes"]
            or admission_values["RUNTIME_IMPORT_PROBE_SHA256"]
            != probe_identity["sha256"]):
        raise GenerationError("install_admission_probe_anchor_mismatch")

    atomic_path = _workspace_path(
        root, "audit_tools/ros1_camera_only_atomic_launcher.py")
    atomic_values = _assignment_literals(atomic_path, (
        "PREFLIGHT_SOURCE_IDENTITY", "RUNTIME_ADMISSION_SOURCE_IDENTITY",
    ))
    expected_preflight = identities[
        "audit_tools/ros1_camera_only_field_preflight.py"]
    expected_admission = identities[
        "audit_tools/ros1_camera_runtime_install_admission.py"]
    if atomic_values["PREFLIGHT_SOURCE_IDENTITY"] != expected_preflight:
        raise GenerationError("atomic_preflight_source_anchor_mismatch")
    if atomic_values["RUNTIME_ADMISSION_SOURCE_IDENTITY"] != expected_admission:
        raise GenerationError("atomic_runtime_admission_source_anchor_mismatch")

    preflight_path = _workspace_path(
        root, "audit_tools/ros1_camera_only_field_preflight.py")
    preflight_values = _assignment_literals(preflight_path, (
        "PREDECESSOR_AUTHORITY_V4", "FROZEN_CANONICAL_V5",
        "FROZEN_REPORT_V4", "DABAI_LAUNCH",
    ))
    expected_predecessor = {
        key: PREDECESSOR_AUTHORITY[key]
        for key in ("path", "size_bytes", "sha256")}
    if preflight_values["PREDECESSOR_AUTHORITY_V4"] != expected_predecessor:
        raise GenerationError("preflight_predecessor_anchor_mismatch")
    expected_frozen = {
        "FROZEN_CANONICAL_V5": (
            "evidence/perception_v2_offline_20260813/"
            "ros1_noetic_canonical_source_admission_20260815_v5.json"),
        "FROZEN_REPORT_V4": (
            "evidence/perception_v2_offline_20260813/"
            "frozen_offline_regression_20260815_runner_platform_composite_v4.json"),
        "DABAI_LAUNCH": (
            "evidence/perception_v2_field_20260814/"
            "ros1_launch_source/dabai_u3.launch"),
    }
    for name, relative in expected_frozen.items():
        identity = identities[relative]
        if preflight_values[name] != identity:
            raise GenerationError("preflight_frozen_anchor_mismatch:" + name)
    return {
        "production_probe_spec_unbound": True,
        "production_install_authority_path": (
            admission_values["PRODUCTION_AUTHORITY_PATH"]),
        "production_install_authority_identity_unbound": True,
        "atomic_transitive_source_anchors_match": True,
        "preflight_frozen_reference_anchors_match": True,
    }


def _validate_overlay_binding(binding: Any) -> Mapping[str, Any]:
    required = {
        "schema_version", "binding_kind", "test_only",
        "canonical_source_root", "contract_sha256", "source_set_sha256",
        "file_count", "entries", "source_contract_pass",
        "indexer_only_detected", "architecture_blockers", "binding_sha256",
    }
    if not isinstance(binding, Mapping) or set(binding) != required:
        raise GenerationError("live_overlay_binding_schema_invalid")
    if (binding["schema_version"] != 1
            or binding["binding_kind"] != "canonical_project_overlay"
            or binding["test_only"] is not False
            or binding["canonical_source_root"]
            != "ros1_overlay_src/limo_cleanup_ros1_perception"
            or binding["file_count"] != EXPECTED_LIVE_OVERLAY_FILE_COUNT
            or binding["source_set_sha256"]
            != EXPECTED_LIVE_OVERLAY_SOURCE_SET_SHA256
            or binding["binding_sha256"]
            != EXPECTED_LIVE_OVERLAY_BINDING_SHA256
            or binding["source_contract_pass"] is not True
            or binding["indexer_only_detected"] is not False
            or binding["architecture_blockers"] != []):
        raise GenerationError("live_overlay_binding_policy_mismatch")
    entries = binding["entries"]
    if not isinstance(entries, list) or len(entries) != binding["file_count"]:
        raise GenerationError("live_overlay_entry_count_mismatch")
    expected_paths = []
    for entry in entries:
        if (not isinstance(entry, Mapping)
                or set(entry) != {"path", "size_bytes", "sha256"}):
            raise GenerationError("live_overlay_entry_schema_invalid")
        expected_paths.append(_relative_path(entry["path"]))
        if (type(entry["size_bytes"]) is not int
                or entry["size_bytes"] < 0
                or not isinstance(entry["sha256"], str)
                or len(entry["sha256"]) != 64
                or entry["sha256"] != entry["sha256"].lower()):
            raise GenerationError("live_overlay_entry_identity_invalid")
    if expected_paths != sorted(expected_paths) or len(set(expected_paths)) != len(
            expected_paths):
        raise GenerationError("live_overlay_entry_order_or_uniqueness_invalid")
    material = dict(binding)
    claimed = material.pop("binding_sha256")
    if _canonical_sha256(material) != claimed:
        raise GenerationError("live_overlay_binding_digest_invalid")
    return dict(binding)


def _make_live_overlay_binding(core: Any, root: Path) -> Mapping[str, Any]:
    """Recompute the exact overlay without importing runtime/numpy modules."""
    collector = getattr(core, "collect_live_overlay_binding", None)
    if not callable(collector):
        raise GenerationError("authority_core_overlay_collector_unavailable")
    core_before = _workspace_identity(
        root, "audit_tools/formal_admission_evidence_authority_v4_core.py")
    binding = collector(root)
    core_after = _workspace_identity(
        root, "audit_tools/formal_admission_evidence_authority_v4_core.py")
    if core_before != core_after:
        raise GenerationError("authority_core_drift_during_overlay_collection")
    return _validate_overlay_binding(binding)


def _add_artifact(
        root: Path, artifacts_by_path: Dict[str, Mapping[str, Any]],
        roles: List[Mapping[str, Any]], relative: str, classification: str,
        formal_use: str, role_id: str, role_kind: str,
        required: bool = True) -> None:
    relative = _relative_path(relative)
    artifact = artifacts_by_path.get(relative)
    if artifact is None:
        identity = _workspace_identity(root, relative)
        _assert_expected_identity(identity)
        artifact = {
            "artifact_id": _artifact_id(relative),
            **identity,
            "classification": classification,
            "formal_use": formal_use,
        }
        artifacts_by_path[relative] = artifact
    elif (artifact["classification"] != classification
            or artifact["formal_use"] != formal_use):
        raise GenerationError("artifact_classification_conflict:" + relative)
    roles.append({
        "role_id": role_id,
        "artifact_id": artifact["artifact_id"],
        "role_kind": role_kind,
        "required": bool(required),
    })


def _build_artifacts_and_roles(
        root: Path, overlay: Mapping[str, Any]) -> Tuple[
            List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Any]]:
    artifacts_by_path: Dict[str, Mapping[str, Any]] = {}
    roles: List[Mapping[str, Any]] = []
    overlay_prefix = "ros1_overlay_src/limo_cleanup_ros1_perception/"
    for entry in overlay["entries"]:
        relative = overlay_prefix + entry["path"]
        _add_artifact(
            root, artifacts_by_path, roles, relative,
            "LIVE_OVERLAY_SOURCE", "SOURCE_BINDING_ONLY_NOT_FIELD_EVIDENCE",
            "live_overlay_source:" + entry["path"], "LIVE_OVERLAY_SOURCE")
        artifact = artifacts_by_path[relative]
        if (artifact["size_bytes"] != entry["size_bytes"]
                or artifact["sha256"] != entry["sha256"]):
            raise GenerationError("live_overlay_artifact_identity_mismatch:" + relative)

    groups = (
        (HOST_SOURCE_PATHS, "HOST_SOURCE",
         "OFFLINE_VALIDATOR_SOURCE_NOT_RUNTIME_AUTHORITY", "host_source"),
        (TEST_PATHS, "TEST", "OFFLINE_TEST_ONLY_NOT_FIELD_EVIDENCE", "test"),
        (RUNNER_PATHS, "RUNNER", "OFFLINE_EXECUTION_PROOF_ONLY", "runner"),
        (RUNTIME_CONTRACT_PATHS, "RUNTIME_CONTRACT_INPUT",
         "DIAGNOSTIC_RUNTIME_CONTRACT_NOT_FIELD_EVIDENCE", "runtime_contract"),
        (DOCUMENT_PATHS, "DOC", "OPERATOR_GUIDANCE_NOT_AUTHORITY", "document"),
        (RETIRED_PATHS, "RETIRED_ENTRY",
         "RETIRED_FAIL_CLOSED_NOT_EXECUTION_AUTHORITY", "retired_entry"),
        (FROZEN_REFERENCE_PATHS, "FROZEN_REFERENCE_ANCHOR",
         "FROZEN_REFERENCE_ONLY_NOT_CURRENT", "frozen_reference"),
        (HISTORICAL_DIAGNOSTIC_PATHS, "HISTORICAL_DIAGNOSTIC_NOT_FORMAL",
         "NOT_FORMAL_NOT_IN_DENOMINATOR", "historical_diagnostic"),
        (HISTORICAL_REGRESSION_PATHS, "HISTORICAL_REGRESSION_NOT_CANONICAL",
         "NOT_FORMAL_NOT_IN_DENOMINATOR", "historical_regression"),
    )
    for paths, classification, formal_use, kind in groups:
        for relative in paths:
            _add_artifact(
                root, artifacts_by_path, roles, relative, classification,
                formal_use, kind + ":" + relative, kind.upper())

    # Multi-role anchors must resolve to the same artifacts already admitted
    # through the complete 51-file overlay rather than creating copies.
    overlay_extra_roles = {
        "ros1_overlay_src/limo_cleanup_ros1_perception/"
        "launch/perception_v2_formal_capture.launch": (
            "formal_capture_launch", "FORMAL_CAPTURE_LAUNCH_SOURCE"),
        "ros1_overlay_src/limo_cleanup_ros1_perception/"
        "src/limo_cleanup_ros1_perception/rosbag1_rgbd_indexer.py": (
            "formal_rosbag1_indexer", "FORMAL_ROSBAG1_INDEXER_SOURCE"),
        "ros1_overlay_src/limo_cleanup_ros1_perception/"
        "config/dabai_ros1_raw_rgbd_six_topics_v1.json": (
            "formal_raw_topic_manifest", "FORMAL_RAW_TOPIC_MANIFEST_SOURCE"),
    }
    for relative, (role_id, role_kind) in overlay_extra_roles.items():
        artifact = artifacts_by_path.get(relative)
        if artifact is None:
            raise GenerationError("overlay_transitive_role_missing:" + relative)
        roles.append({
            "role_id": role_id,
            "artifact_id": artifact["artifact_id"],
            "role_kind": role_kind,
            "required": True,
        })

    artifacts = sorted(artifacts_by_path.values(), key=lambda item: item["path"])
    roles.sort(key=lambda item: item["role_id"])
    if len({item["path"] for item in artifacts}) != len(artifacts):
        raise GenerationError("artifact_path_duplicate")
    if len({item["artifact_id"] for item in artifacts}) != len(artifacts):
        raise GenerationError("artifact_id_duplicate")
    if len({item["role_id"] for item in roles}) != len(roles):
        raise GenerationError("role_id_duplicate")
    valid_artifact_ids = {item["artifact_id"] for item in artifacts}
    if any(item["artifact_id"] not in valid_artifact_ids for item in roles):
        raise GenerationError("role_references_unknown_artifact")
    identities = {item["path"]: {
        key: item[key] for key in ("path", "size_bytes", "sha256")}
        for item in artifacts}
    anchor_attestation = _validate_host_source_anchors(root, identities)
    return artifacts, roles, anchor_attestation


def _load_exact_core(root: Path) -> Tuple[Any, Mapping[str, Any]]:
    relative = "audit_tools/formal_admission_evidence_authority_v4_core.py"
    raw, before = _workspace_bytes(root, relative)
    private_name = "_limo_blocked_offline_authority_v4_core_exact"
    if private_name in sys.modules:
        raise GenerationError("exact_authority_core_private_name_preloaded")
    module = types.ModuleType(private_name)
    module.__file__ = str(_workspace_path(root, relative))
    module.__package__ = ""
    module.__spec__ = None
    sys.modules[private_name] = module
    try:
        code = compile(raw, module.__file__, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(private_name, None)
        raise
    after = _workspace_identity(root, relative)
    if before != after:
        raise GenerationError("authority_core_source_drift_during_exact_load")
    required_exports = (
        "CANONICAL_SCHEMA_VERSION", "REPORT_SCHEMA_VERSION", "GENERATION_ID",
        "CANONICAL_ARTIFACT_ID", "CANONICAL_ID", "CURRENT_EVIDENCE_ID",
        "REPORT_ID", "CANONICAL_RELATIVE_PATH", "REPORT_RELATIVE_PATH",
        "REQUIRED_SOURCE_ROLE_PATHS", "collect_source_role_bindings",
        "build_canonical_payload", "build_report_payload",
    )
    missing = [name for name in required_exports if not hasattr(module, name)]
    if missing:
        raise GenerationError("authority_core_export_missing:" + ",".join(missing))
    expected_scalars = {
        "GENERATION_ID": GENERATION_ID,
        "CANONICAL_ARTIFACT_ID": CANONICAL_ARTIFACT_ID,
        "CANONICAL_ID": CANONICAL_ID,
        "CURRENT_EVIDENCE_ID": REPORT_EVIDENCE_ID,
        "REPORT_ID": REPORT_ID,
        "CANONICAL_RELATIVE_PATH": CANONICAL_RELATIVE_PATH,
        "REPORT_RELATIVE_PATH": REPORT_RELATIVE_PATH,
    }
    for name, expected in expected_scalars.items():
        if getattr(module, name) != expected:
            raise GenerationError("authority_core_constant_mismatch:" + name)
    return module, before


def _source_role_dispositions(
        source_roles: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    frozen = set(FROZEN_REFERENCE_PATHS)
    diagnostics = set(HISTORICAL_DIAGNOSTIC_PATHS)
    historical = set(HISTORICAL_REGRESSION_PATHS)
    records = []
    for item in source_roles:
        path = item["path"]
        if path in frozen:
            disposition = "FROZEN_REFERENCE_ANCHOR"
            denominator_use = "NOT_IN_DENOMINATOR"
        elif path in diagnostics:
            disposition = (
                "HISTORICAL_DIAGNOSTIC_NOT_FORMAL_NOT_IN_DENOMINATOR")
            denominator_use = "NOT_IN_DENOMINATOR"
        elif path in historical:
            disposition = "HISTORICAL_REGRESSION_NOT_CANONICAL"
            denominator_use = "NOT_IN_DENOMINATOR"
        else:
            disposition = "BOUND_SOURCE"
            denominator_use = "SOURCE_ROLE_ONLY"
        records.append({
            "path": path,
            "role": item["role"],
            "disposition": disposition,
            "denominator_use": denominator_use,
        })
    records.sort(key=lambda value: value["path"])
    if len(records) != len(source_roles):
        raise GenerationError("source_role_disposition_count_mismatch")
    return records


def _static_unittest_ids(root: Path, relative: str) -> List[str]:
    path = _workspace_path(root, relative)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    ids = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith("test_")):
                ids.append("{}::{}.{}".format(relative, node.name, child.name))
    ids.sort()
    if not ids or len(ids) != len(set(ids)):
        raise GenerationError("static_unittest_ids_invalid:" + relative)
    return ids


def _decorator_parametrize_count(decorator: ast.AST) -> Optional[int]:
    if not isinstance(decorator, ast.Call):
        return None
    function = decorator.func
    if (not isinstance(function, ast.Attribute)
            or function.attr != "parametrize" or len(decorator.args) < 2):
        return None
    values = decorator.args[1]
    if not isinstance(values, (ast.List, ast.Tuple)):
        raise GenerationError("pytest_parametrize_values_not_static")
    return len(values.elts)


def _static_pytest_ids(root: Path, relative: str) -> List[str]:
    path = _workspace_path(root, relative)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    ids = []
    for node in tree.body:
        if (not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                or not node.name.startswith("test_")):
            continue
        counts = [
            value for value in (
                _decorator_parametrize_count(item)
                for item in node.decorator_list)
            if value is not None]
        if len(counts) > 1:
            raise GenerationError("multiple_pytest_parametrize_decorators")
        count = counts[0] if counts else 1
        if count <= 0:
            raise GenerationError("zero_pytest_parametrize_cases")
        base = relative + "::" + node.name
        if counts:
            ids.extend("{}[{}]".format(base, index) for index in range(count))
        else:
            ids.append(base)
    ids.sort()
    if not ids or len(ids) != len(set(ids)):
        raise GenerationError("static_pytest_ids_invalid:" + relative)
    return ids


def _suite_static_ids(root: Path, suite: Mapping[str, Any]) -> List[str]:
    if suite["runner"] == "unittest":
        ids = _static_unittest_ids(root, suite["target"])
    elif suite["runner"] == "pytest_style":
        ids = _static_pytest_ids(root, suite["target"])
    else:
        raise GenerationError("unknown_suite_runner:" + str(suite["runner"]))
    if len(ids) != suite["logical_count"]:
        raise GenerationError("suite_static_count_mismatch:" + suite["suite_id"])
    return ids


def _stream_identity(raw: bytes) -> Mapping[str, Any]:
    return {
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _parse_single_marker(
        stdout: bytes, prefix_text: str) -> Tuple[Mapping[str, Any], bytes]:
    prefix = prefix_text.encode("ascii")
    if stdout.count(prefix) != 1 or not stdout.startswith(prefix):
        raise GenerationError("child_marker_count_or_position_invalid")
    if not stdout.endswith(b"\n") or b"\n" in stdout[:-1] or b"\r" in stdout:
        raise GenerationError("child_marker_stream_not_single_lf_line")
    raw = stdout[len(prefix):-1]
    if not raw:
        raise GenerationError("child_marker_payload_empty")
    try:
        payload = _strict_json(raw)
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise GenerationError("child_marker_strict_json_invalid") from error
    if not isinstance(payload, Mapping):
        raise GenerationError("child_marker_payload_not_object")
    return dict(payload), raw


def _marker_file_identity_matches(
        value: Any, expected: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    return (
        value.get("size_bytes") == expected["size_bytes"]
        and value.get("sha256") == expected["sha256"])


def _validate_unittest_payload(
        payload: Mapping[str, Any], root: Path, target: Mapping[str, Any],
        expected_ids: Sequence[str], interpreter: Mapping[str, Any]) -> None:
    if (payload.get("schema_version") != "offline_unittest_file_result/v1"
            or payload.get("runner_kind")
            != "stdlib_unittest_single_file_isolated"
            or payload.get("selection_mode") != "selected_ids"
            or payload.get("workspace") != str(root)
            or payload.get("import_roots") != ["."]
            or payload.get("path") != target["path"]
            or payload.get("resolved_path")
            != str(_workspace_path(root, target["path"]))
            or payload.get("size_bytes") != target["size_bytes"]
            or payload.get("sha256") != target["sha256"]
            or payload.get("requested_ids") != list(expected_ids)
            or payload.get("expected_ids") != list(expected_ids)
            or payload.get("executed_ids") != list(expected_ids)
            or payload.get("passed_ids") != list(expected_ids)
            or payload.get("failed_ids") != []
            or payload.get("skipped_ids") != []
            or payload.get("discovered_ids") != list(expected_ids)
            or payload.get("discovered") != len(expected_ids)
            or payload.get("collected") != len(expected_ids)
            or payload.get("passed") != len(expected_ids)
            or payload.get("failed") != 0
            or payload.get("skipped") != 0
            or payload.get("exit") != 0
            or payload.get("result") != "PASS"
            or payload.get("failures") != []
            or payload.get("stdout_marker_count") != 1
            or payload.get("environment_unchanged_during_execution") is not True
            or payload.get("environment_restored") is not True
            or not _marker_file_identity_matches(
                payload.get("target_identity_before"), target)
            or not _marker_file_identity_matches(
                payload.get("target_identity_after"), target)):
        raise GenerationError("unittest_child_payload_mismatch:" + target["path"])
    environment = payload.get("environment")
    if (not isinstance(environment, Mapping)
            or environment.get("clean") is not True
            or environment.get("contaminated_keys") != []
            or environment.get("cwd") != str(root)):
        raise GenerationError("unittest_child_environment_invalid:" + target["path"])
    baseline_paths = environment.get("sys_path_before_import_roots")
    if (not isinstance(baseline_paths, list)
            or any(not isinstance(item, str) for item in baseline_paths)
            or any("site-packages" in item or "dist-packages" in item
                   for item in baseline_paths)):
        raise GenerationError("unittest_child_site_path_present:" + target["path"])
    executable = payload.get("executable")
    if not isinstance(executable, Mapping) or payload.get("python") != executable:
        raise GenerationError("unittest_child_executable_schema_invalid")
    if (executable.get("entry_path") != interpreter["entry_path"]
            or executable.get("entry_is_symlink")
            != interpreter["entry_is_symlink"]
            or executable.get("entry_link_chain")
            != [{
                "path": item["path"],
                "link_target": item["link_text"],
                "next_path": item["next_path"],
            } for item in interpreter["entry_link_chain"]]
            or not _marker_file_identity_matches(
                executable.get("resolved_target"),
                interpreter["resolved_target"])
            or executable.get("isolated") is not True
            or executable.get("no_bytecode") is not True):
        raise GenerationError("unittest_child_executable_identity_mismatch")


def _validate_pytest_payload(
        payload: Mapping[str, Any], target: Mapping[str, Any],
        expected_ids: Sequence[str]) -> None:
    if (set(payload) != {
            "schema_version", "runner_kind", "path", "size_bytes", "sha256",
            "expected_ids", "executed_ids", "collected", "passed", "failed",
            "skipped", "exit", "result"}
            or payload.get("schema_version")
            != "offline_pytest_file_result/v1"
            or payload.get("runner_kind") != "offline_pytest_style_single_file"
            or payload.get("path") != target["path"]
            or payload.get("size_bytes") != target["size_bytes"]
            or payload.get("sha256") != target["sha256"]
            or payload.get("expected_ids") != list(expected_ids)
            or payload.get("executed_ids") != list(expected_ids)
            or payload.get("collected") != len(expected_ids)
            or payload.get("passed") != len(expected_ids)
            or payload.get("failed") != 0
            or payload.get("skipped") != 0
            or payload.get("exit") != 0
            or payload.get("result") != "PASS"):
        raise GenerationError("pytest_child_payload_mismatch:" + target["path"])


def _run_child(
        root: Path, suite: Mapping[str, Any], interpreter_entry: str,
        expected_ids: Sequence[str]) -> Mapping[str, Any]:
    key = (suite["suite_id"], interpreter_entry)
    if key not in PHYSICAL_RECORD_IDS:
        raise GenerationError("physical_record_definition_missing")
    record_id, interpreter_role = PHYSICAL_RECORD_IDS[key]
    runner_relative = (
        UNITTEST_RUNNER if suite["runner"] == "unittest" else PYTEST_RUNNER)
    runner_before = _workspace_identity(root, runner_relative)
    target_before = _workspace_identity(root, suite["target"])
    interpreter_before = _executable_identity(interpreter_entry)
    if suite["runner"] == "unittest":
        argv = [
            interpreter_entry, "-I", "-S", "-B",
            str(_workspace_path(root, runner_relative)),
            "--workspace", str(root), "--target", suite["target"],
            "--import-root", ".",
        ]
        for case_id in expected_ids:
            argv.extend(("--expected-id", case_id))
        marker_prefix = UNITTEST_MARKER
    else:
        argv = [
            interpreter_entry, "-I", "-S", "-B",
            str(_workspace_path(root, runner_relative)), "--single-file",
            "--workspace", str(root), "--target", suite["target"],
            "--import-root", ".",
        ]
        for case_id in expected_ids:
            argv.extend(("--expected-id", case_id))
        marker_prefix = PYTEST_MARKER
    environment = dict(CHILD_ENVIRONMENT)
    completed = subprocess.run(
        argv, cwd=str(root), env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=COMMAND_TIMEOUT_SECONDS, close_fds=True)
    runner_after = _workspace_identity(root, runner_relative)
    target_after = _workspace_identity(root, suite["target"])
    interpreter_after = _executable_identity(interpreter_entry)
    if runner_before != runner_after:
        raise GenerationError("runner_identity_drift:" + record_id)
    if target_before != target_after:
        raise GenerationError("test_identity_drift:" + record_id)
    if interpreter_before != interpreter_after:
        raise GenerationError("interpreter_identity_drift:" + record_id)
    payload, marker_raw = _parse_single_marker(
        completed.stdout, marker_prefix)
    if completed.returncode != 0:
        raise GenerationError("child_exit_nonzero:" + record_id)
    if suite["runner"] == "unittest":
        _validate_unittest_payload(
            payload, root, target_before, expected_ids, interpreter_before)
    else:
        _validate_pytest_payload(payload, target_before, expected_ids)
    return {
        "record_id": record_id,
        "suite_id": suite["suite_id"],
        "platform": "POSIX_WSL",
        "interpreter_role": interpreter_role,
        "interpreter_identity_before": interpreter_before,
        "interpreter_identity_after": interpreter_after,
        "test_artifact_identity_before": target_before,
        "test_artifact_identity_after": target_after,
        "runner_artifact_identity_before": runner_before,
        "runner_artifact_identity_after": runner_after,
        "expected_test_ids": list(expected_ids),
        "executed_test_ids": list(payload["executed_ids"]),
        "collected": payload["collected"],
        "passed": payload["passed"],
        "failed": payload["failed"],
        "skipped": payload["skipped"],
        "exit_code": completed.returncode,
        "argv": argv,
        "argv_sha256": _canonical_sha256(argv),
        "environment": environment,
        "environment_sha256": _canonical_sha256(environment),
        "stdout": _stream_identity(completed.stdout),
        "stderr": _stream_identity(completed.stderr),
        "marker_count": 1,
        "marker_prefix": marker_prefix,
        "marker_raw_sha256": hashlib.sha256(marker_raw).hexdigest(),
        "marker_payload": payload,
        "marker_payload_sha256": _canonical_sha256(payload),
    }


def _logical_suite_record(
        root: Path, suite: Mapping[str, Any], expected_ids: Sequence[str],
        physical_records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    runner_relative = (
        UNITTEST_RUNNER if suite["runner"] == "unittest" else PYTEST_RUNNER)
    matching = [
        item for item in physical_records if item["suite_id"] == suite["suite_id"]]
    if len(matching) != len(suite["interpreters"]):
        raise GenerationError("logical_suite_physical_record_count_mismatch")
    for item in matching:
        if (item["expected_test_ids"] != list(expected_ids)
                or item["executed_test_ids"] != list(expected_ids)
                or item["collected"] != len(expected_ids)
                or item["passed"] != len(expected_ids)
                or item["failed"] != 0 or item["skipped"] != 0):
            raise GenerationError("logical_suite_physical_result_mismatch")
    return {
        "suite_id": suite["suite_id"],
        "test_artifact_identity": _workspace_identity(root, suite["target"]),
        "runner_artifact_identity": _workspace_identity(root, runner_relative),
        "expected_test_ids": list(expected_ids),
        "executed_test_ids": list(expected_ids),
        "expected": len(expected_ids),
        "collected": len(expected_ids),
        "passed": len(expected_ids),
        "failed": 0,
        "skipped": 0,
    }


def _execute_matrix(root: Path) -> Tuple[
        List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    static_by_suite: Dict[str, List[str]] = {}
    all_ids: List[str] = []
    for suite in SUITES:
        ids = _suite_static_ids(root, suite)
        static_by_suite[suite["suite_id"]] = ids
        all_ids.extend(ids)
    if len(all_ids) != EXPECTED_LOGICAL_COUNT or len(set(all_ids)) != len(all_ids):
        raise GenerationError("logical_test_id_denominator_invalid")

    physical = []
    for suite in SUITES:
        ids = static_by_suite[suite["suite_id"]]
        for interpreter in suite["interpreters"]:
            physical.append(_run_child(root, suite, interpreter, ids))
    if len(physical) != 9 or len({item["record_id"] for item in physical}) != 9:
        raise GenerationError("physical_record_inventory_invalid")
    if sum(item["collected"] for item in physical) != EXPECTED_PHYSICAL_COUNT:
        raise GenerationError("physical_execution_denominator_invalid")
    if any(item["failed"] or item["skipped"] for item in physical):
        raise GenerationError("physical_execution_not_all_green")

    logical = [
        _logical_suite_record(
            root, suite, static_by_suite[suite["suite_id"]], physical)
        for suite in SUITES]
    if (sum(item["collected"] for item in logical) != EXPECTED_LOGICAL_COUNT
            or sum(item["passed"] for item in logical) != EXPECTED_LOGICAL_COUNT
            or any(item["failed"] or item["skipped"] for item in logical)):
        raise GenerationError("logical_execution_denominator_invalid")
    return logical, physical


def _production_cli_observation(root: Path) -> Mapping[str, Any]:
    source_relative = "audit_tools/ros1_camera_only_atomic_launcher.py"
    source_before = _workspace_identity(root, source_relative)
    executable_before = _executable_identity(PRIMARY_PYTHON)
    actual_launch = _workspace_path(
        root,
        "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch")
    argv = [
        PRIMARY_PYTHON, "-I", "-S", "-B",
        str(_workspace_path(root, source_relative)),
        "--mode", "EXECUTE_AUDITED_CAMERA_ONLY",
        "--actual-vendor-launch", str(actual_launch),
    ]
    environment = dict(CHILD_ENVIRONMENT)
    completed = subprocess.run(
        argv, cwd=str(root), env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=COMMAND_TIMEOUT_SECONDS, close_fds=True)
    source_after = _workspace_identity(root, source_relative)
    executable_after = _executable_identity(PRIMARY_PYTHON)
    expected_stderr = (
        b"ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
        b"camera_runtime_install_admission_not_bound\n")
    if (completed.returncode != 4 or completed.stdout != b""
            or completed.stderr != expected_stderr):
        raise GenerationError("production_cli_fail_closed_observation_mismatch")
    if source_before != source_after or executable_before != executable_after:
        raise GenerationError("production_cli_identity_drift")
    return {
        "not_in_logical_denominator": True,
        "not_in_physical_denominator": True,
        "expected_fail_closed": True,
        "source_identity_before": source_before,
        "source_identity_after": source_after,
        "interpreter_identity": executable_before,
        "argv": argv,
        "argv_sha256": _canonical_sha256(argv),
        "environment": environment,
        "environment_sha256": _canonical_sha256(environment),
        "exit_code": completed.returncode,
        "stdout": _stream_identity(completed.stdout),
        "stderr": _stream_identity(completed.stderr),
        "expected_stderr_sha256": hashlib.sha256(expected_stderr).hexdigest(),
        "blocked_code": "camera_runtime_install_admission_not_bound",
        "formal_consumer": False,
        "delivery_ready": False,
    }


def _collect_core_source_roles(core: Any, root: Path) -> List[Mapping[str, Any]]:
    core_definitions = tuple(tuple(item) for item in core.REQUIRED_SOURCE_ROLE_PATHS)
    if (len(core_definitions) != len(SOURCE_ROLE_DEFINITIONS)
            or dict(core_definitions) != dict(SOURCE_ROLE_DEFINITIONS)):
        raise GenerationError("generator_core_source_role_definition_mismatch")
    records = list(core.collect_source_role_bindings(root))
    if (len(records) != len(SOURCE_ROLE_DEFINITIONS)
            or len({item.get("path") for item in records}) != len(records)
            or len({item.get("role") for item in records}) != len(records)):
        raise GenerationError("core_source_role_inventory_invalid")
    expected = {path: role for role, path in SOURCE_ROLE_DEFINITIONS}
    for item in records:
        if (not isinstance(item, Mapping)
                or set(item) != {"role", "path", "size_bytes", "sha256"}
                or expected.get(item["path"]) != item["role"]
                or dict(_workspace_identity(root, item["path"])) != {
                    key: item[key] for key in ("path", "size_bytes", "sha256")}
                or type(item["size_bytes"]) is not int
                or item["size_bytes"] <= 0
                or not isinstance(item["sha256"], str)
                or len(item["sha256"]) != 64):
            raise GenerationError("core_source_role_record_invalid")
        _assert_expected_identity(item)
    if [item["path"] for item in records] != sorted(expected):
        raise GenerationError("core_source_role_order_invalid")
    return [dict(item) for item in records]


def _canonical_payload(
        core: Any, root: Path, source_roles: Sequence[Mapping[str, Any]],
        dispositions: Sequence[Mapping[str, Any]],
        production_overlay: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = core.build_canonical_payload(
        root, source_roles, dispositions)
    if not isinstance(payload, dict):
        raise GenerationError("core_canonical_builder_result_invalid")
    if payload.get("live_overlay_binding") != production_overlay:
        raise GenerationError("core_and_production_overlay_binding_mismatch")
    if payload.get("schema_version") != core.CANONICAL_SCHEMA_VERSION:
        raise GenerationError("core_canonical_schema_version_mismatch")
    if payload.get("canonical_id") != CANONICAL_ID:
        raise GenerationError("core_canonical_id_mismatch")
    if payload.get("artifact_id") != CANONICAL_ARTIFACT_ID:
        raise GenerationError("core_canonical_artifact_id_mismatch")
    if payload.get("generation_id") != GENERATION_ID:
        raise GenerationError("core_canonical_generation_id_mismatch")
    if payload.get("status") != "CURRENT_BLOCKED_OFFLINE_SOURCE_BINDING":
        raise GenerationError("core_canonical_status_mismatch")
    if payload.get("source_roles") != list(source_roles):
        raise GenerationError("core_canonical_source_roles_mismatch")
    if payload.get("source_role_dispositions") != list(dispositions):
        raise GenerationError("core_canonical_source_dispositions_mismatch")
    if payload.get("live_overlay_attestation") != {
            "binding_recompute_authority":
            "HOST_OWNED_PURE_STDLIB_EXACT_FILE_CLOSURE",
            "production_factory_executed": False,
            "ambient_numpy_required": False,
            }:
        raise GenerationError("core_canonical_overlay_attestation_mismatch")
    for key in (
            "accepted_by_formal_field_evidence_consumer", "delivery_ready",
            "authorizes_field_delivery"):
        if payload.get(key) is not False:
            raise GenerationError("core_canonical_field_state_not_blocked:" + key)
    material = dict(payload)
    claimed = material.pop("artifact_binding_sha256", None)
    if claimed != _canonical_sha256(material):
        raise GenerationError("core_canonical_binding_digest_invalid")
    return payload


def _interpreter_roles_for_core(
        physical: Sequence[Mapping[str, Any]]) -> Mapping[str, Mapping[str, Any]]:
    roles: Dict[str, Mapping[str, Any]] = {}
    for record in physical:
        role = record["interpreter_role"]
        before = record["interpreter_identity_before"]
        previous = roles.get(role)
        if previous is not None and previous != before:
            raise GenerationError("interpreter_role_identity_split:" + role)
        roles[role] = before
    roles["bundled_host_python"] = _executable_identity(sys.executable)
    return roles


def _report_payload(
        core: Any, root: Path, canonical_identity: Mapping[str, Any],
        source_roles: Sequence[Mapping[str, Any]],
        logical: Sequence[Mapping[str, Any]],
        physical: Sequence[Mapping[str, Any]],
        production_observation: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = core.build_report_payload(
        root, canonical_identity, source_roles, physical,
        production_observation)
    if not isinstance(payload, dict):
        raise GenerationError("core_report_builder_result_invalid")
    matrix = payload.get("test_matrix")
    if not isinstance(matrix, dict):
        raise GenerationError("core_report_test_matrix_missing")
    # The core independently reconstructs the logical suite records.  Require
    # exact agreement with the records cross-checked against the real child
    # markers before accepting the builder's report.
    if matrix.get("logical_suite_records") != list(logical):
        raise GenerationError("core_report_logical_records_mismatch")
    if matrix.get("physical_execution_records") != list(physical):
        raise GenerationError("core_report_physical_records_mismatch")
    expected_counts = {
        "logical_expected_total": EXPECTED_LOGICAL_COUNT,
        "logical_collected": EXPECTED_LOGICAL_COUNT,
        "logical_passed": EXPECTED_LOGICAL_COUNT,
        "logical_failed": 0,
        "logical_skipped": 0,
        "physical_expected_total": EXPECTED_PHYSICAL_COUNT,
        "physical_collected": EXPECTED_PHYSICAL_COUNT,
        "physical_passed": EXPECTED_PHYSICAL_COUNT,
        "physical_failed": 0,
        "physical_skipped": 0,
        "failures": [],
    }
    for key, expected in expected_counts.items():
        if matrix.get(key) != expected:
            raise GenerationError("core_report_count_mismatch:" + key)
    if (payload.get("schema_version") != core.REPORT_SCHEMA_VERSION
            or payload.get("report_id") != REPORT_ID
            or payload.get("evidence_id") != REPORT_EVIDENCE_ID
            or payload.get("generation_id") != GENERATION_ID
            or payload.get("status") != "CURRENT_BLOCKED_OFFLINE"
            or payload.get("production_cli_observation")
            != production_observation
            or payload.get("formal_denominator") != 0
            or payload.get("regression_passed") is not False
            or payload.get("accepted_by_formal_field_evidence_consumer") is not False
            or payload.get("delivery_ready") is not False
            or payload.get("authorizes_field_delivery") is not False):
        raise GenerationError("core_report_blocked_state_mismatch")
    material = dict(payload)
    claimed = material.pop("report_binding_sha256", None)
    if claimed != _canonical_sha256(material):
        raise GenerationError("core_report_binding_digest_invalid")
    return payload


def _output_path(root: Path, relative: str) -> Path:
    relative = _relative_path(relative)
    parts = PurePosixPath(relative).parts
    parent_relative = PurePosixPath(*parts[:-1]).as_posix()
    parent = _workspace_path(root, parent_relative, expect_file=False)
    metadata = parent.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise GenerationError("output_parent_invalid:" + relative)
    path = parent / parts[-1]
    if os.path.lexists(os.fspath(path)):
        raise GenerationError("output_already_exists:" + relative)
    return path


def _write_json_exclusive(
        root: Path, relative: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    path = _output_path(root, relative)
    raw = _pretty_bytes(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(path), flags, 0o444)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise GenerationError("exclusive_output_short_write:" + relative)
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory = os.open(os.fspath(path.parent), directory_flags)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    reopened, identity = _workspace_bytes(root, relative)
    if reopened != raw or _strict_json(reopened) != payload:
        raise GenerationError("exclusive_output_reopen_mismatch:" + relative)
    return identity


def _plan(root: Path) -> Mapping[str, Any]:
    paths = set(path for unused_role, path in SOURCE_ROLE_DEFINITIONS)
    paths.update((CANONICAL_RELATIVE_PATH, REPORT_RELATIVE_PATH))
    missing = []
    existing_outputs = []
    for relative in sorted(paths):
        try:
            candidate = root.joinpath(*PurePosixPath(relative).parts)
            if relative in (CANONICAL_RELATIVE_PATH, REPORT_RELATIVE_PATH):
                if os.path.lexists(os.fspath(candidate)):
                    existing_outputs.append(relative)
            else:
                _workspace_identity(root, relative)
        except (GenerationError, OSError):
            if relative not in (CANONICAL_RELATIVE_PATH, REPORT_RELATIVE_PATH):
                missing.append(relative)
    static_counts = {}
    for suite in SUITES:
        try:
            static_counts[suite["suite_id"]] = len(_suite_static_ids(root, suite))
        except (GenerationError, OSError, SyntaxError, UnicodeError):
            static_counts[suite["suite_id"]] = None
    deep_validation: Mapping[str, Any] = {
        "attempted": False,
        "validated": False,
    }
    if not missing:
        core, core_identity = _load_exact_core(root)
        overlay = _make_live_overlay_binding(core, root)
        artifacts, unused_roles, anchor_attestation = (
            _build_artifacts_and_roles(root, overlay))
        source_roles = _collect_core_source_roles(core, root)
        dispositions = _source_role_dispositions(source_roles)
        canonical = _canonical_payload(
            core, root, source_roles, dispositions, overlay)
        deep_validation = {
            "attempted": True,
            "validated": True,
            "core_identity": core_identity,
            "overlay_file_count": overlay["file_count"],
            "overlay_binding_sha256": overlay["binding_sha256"],
            "complete_artifact_path_count": len(artifacts),
            "source_role_count": len(source_roles),
            "source_role_set_sha256": canonical["source_role_set_sha256"],
            "source_role_disposition_sha256": canonical[
                "source_role_disposition_sha256"],
            "production_anchor_attestation": anchor_attestation,
        }
    return {
        "schema_version": "ros1_camera_runtime_blocked_offline_generation_plan/v1",
        "generation_id": GENERATION_ID,
        "canonical_id": CANONICAL_ID,
        "canonical_artifact_id": CANONICAL_ARTIFACT_ID,
        "canonical_output": CANONICAL_RELATIVE_PATH,
        "report_id": REPORT_ID,
        "report_evidence_id": REPORT_EVIDENCE_ID,
        "report_output": REPORT_RELATIVE_PATH,
        "predecessor": dict(PREDECESSOR_AUTHORITY),
        "logical_expected": EXPECTED_LOGICAL_COUNT,
        "physical_expected": EXPECTED_PHYSICAL_COUNT,
        "suite_static_counts": static_counts,
        "deep_validation": deep_validation,
        "physical_record_ids": [
            PHYSICAL_RECORD_IDS[(suite["suite_id"], interpreter)][0]
            for suite in SUITES for interpreter in suite["interpreters"]],
        "required_python_entries": list(PYTHON_ENTRIES),
        "missing_required_source_roles": missing,
        "existing_outputs": existing_outputs,
        "ready_to_attempt_generation": (
            not missing and not existing_outputs
            and deep_validation.get("validated") is True),
        "writes_authority_index": False,
        "formal_consumer": False,
        "delivery_ready": False,
    }


def _generate(root: Path) -> Mapping[str, Any]:
    # Refuse partial or replacement generations before expensive test work.
    _output_path(root, CANONICAL_RELATIVE_PATH)
    _output_path(root, REPORT_RELATIVE_PATH)
    core, core_identity_before = _load_exact_core(root)

    overlay_before = _make_live_overlay_binding(core, root)
    artifacts_before, unused_roles, anchor_attestation_before = (
        _build_artifacts_and_roles(root, overlay_before))
    source_roles_before = _collect_core_source_roles(core, root)
    dispositions_before = _source_role_dispositions(source_roles_before)
    artifact_paths = {item["path"] for item in artifacts_before}
    if any(item["path"] not in artifact_paths for item in source_roles_before):
        raise GenerationError("source_role_missing_from_complete_artifact_inventory")
    canonical_before = _canonical_payload(
        core, root, source_roles_before, dispositions_before, overlay_before)

    logical, physical = _execute_matrix(root)
    production_observation = _production_cli_observation(root)

    overlay_after = _make_live_overlay_binding(core, root)
    artifacts_after, unused_roles, anchor_attestation_after = (
        _build_artifacts_and_roles(root, overlay_after))
    source_roles_after = _collect_core_source_roles(core, root)
    dispositions_after = _source_role_dispositions(source_roles_after)
    core_identity_after = _workspace_identity(
        root, "audit_tools/formal_admission_evidence_authority_v4_core.py")
    if (overlay_after != overlay_before
            or artifacts_after != artifacts_before
            or source_roles_after != source_roles_before
            or dispositions_after != dispositions_before
            or anchor_attestation_after != anchor_attestation_before
            or core_identity_after != core_identity_before):
        raise GenerationError("generation_source_closure_drift")
    canonical_after = _canonical_payload(
        core, root, source_roles_after, dispositions_after, overlay_after)
    if canonical_after != canonical_before:
        raise GenerationError("canonical_payload_drift_during_test_execution")

    canonical_identity = _write_json_exclusive(
        root, CANONICAL_RELATIVE_PATH, canonical_after)
    report = _report_payload(
        core, root, canonical_identity, source_roles_after, logical, physical,
        production_observation)
    report_identity = _write_json_exclusive(
        root, REPORT_RELATIVE_PATH, report)

    # A final source revalidation prevents a successful report from being
    # emitted after any source role or live overlay changed during output.
    if (_make_live_overlay_binding(core, root) != overlay_after
            or _collect_core_source_roles(core, root) != source_roles_after
            or _workspace_identity(
                root, "audit_tools/formal_admission_evidence_authority_v4_core.py")
            != core_identity_after):
        raise GenerationError("generation_source_closure_drift_after_output")
    return {
        "generation_id": GENERATION_ID,
        "canonical": canonical_identity,
        "report": report_identity,
        "logical": {"passed": 155, "failed": 0, "skipped": 0},
        "physical": {"passed": 263, "failed": 0, "skipped": 0},
        "production_cli_exit": production_observation["exit_code"],
        "production_cli_blocked_code": production_observation["blocked_code"],
        "authority_index_written": False,
        "formal_consumer": False,
        "delivery_ready": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the ROS1 camera-runtime BLOCKED_OFFLINE evidence pair.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--generate", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _require_clean_generator_context()
        root = _workspace_root()
        if Path.cwd().resolve(strict=True) != root:
            raise GenerationError("generator_cwd_must_equal_workspace")
        if args.plan:
            result = _plan(root)
            print(PLAN_MARKER + _canonical_bytes(result).decode("utf-8"), flush=True)
            return 0 if result["ready_to_attempt_generation"] else 3
        result = _generate(root)
        print(GENERATED_MARKER + _canonical_bytes(result).decode("utf-8"), flush=True)
        return 0
    except (GenerationError, OSError, subprocess.SubprocessError,
            SyntaxError, UnicodeError, ValueError, TypeError) as error:
        sys.stderr.write(
            "ROS1_CAMERA_RUNTIME_BLOCKED_OFFLINE_GENERATION_FAILED:"
            + type(error).__name__ + ":" + str(error) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
