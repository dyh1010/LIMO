"""Generate the v7 atomic-CLI/field-producer BLOCKED_OFFLINE generation.

The command is a Windows-host orchestrator.  It runs the document-demotion
suite with the bundled Windows Python and runs POSIX suites through ``wsl.exe
--distribution Ubuntu --cd`` using both ``/usr/bin/python3`` and
``/usr/bin/python3.14`` where the
fixed execution plan requires them.  Logical totals are reconstructed from the
test AST.  Raw Windows symlink skips are accepted only through the one exact
same-ID POSIX companion.

``--plan`` is read-only.  ``--generate`` uses O_EXCL and writes canonical,
report, then index last.  This module is never invoked merely by importing it.
No mode starts ROS, a camera, inference, a network connection, or hardware.
The atomic launcher production CLI is intentionally *not* executed: its
blocked state is bound to the exact already-executed unit-test ID.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import types
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PLAN_MARKER = "ROS1_ATOMIC_CLI_FIELD_PRODUCER_BLOCKED_OFFLINE_PLAN "
GENERATED_MARKER = "ROS1_ATOMIC_CLI_FIELD_PRODUCER_BLOCKED_OFFLINE_GENERATED "
COMMAND_TIMEOUT_SECONDS = 1800
SENSITIVE_ENVIRONMENT = (
    "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "ROS_PACKAGE_PATH", "ROS_MASTER_URI",
    "WSLENV",
)
INNER_ENVIRONMENT: Mapping[str, str] = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}
CORE_RELATIVE_PATH = "audit_tools/formal_admission_evidence_authority_v6_core.py"
WRAPPER_RELATIVE_PATH = "audit_tools/formal_admission_evidence_authority_v6.py"
GENERATION_STATUS_PREPARED = "PREPARED"
GENERATION_STATUS_FAILED_NO_ARTIFACTS = "FAILED_NO_ARTIFACTS"
GENERATION_STATUS_ABANDONED_UNINDEXED = "ABANDONED_UNINDEXED"
GENERATION_STATUS_COMMITTED_UNSELECTED = "COMMITTED_UNSELECTED"
GENERATION_STATUS_SELECTED_BLOCKED_OFFLINE = "SELECTED_BLOCKED_OFFLINE"

# Empty in production until an actual abandoned historical generation is
# independently identified.  Tests may inject an explicit, versioned
# REGISTERED_NONSELECTABLE_GENERATION; successful predecessors are never
# exempted from strict readability and identity checks.
REGISTERED_NONSELECTABLE_GENERATIONS: Tuple[Mapping[str, Any], ...] = ()


class GenerationError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _strict_pairs(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GenerationError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise GenerationError("non_finite_json_constant:" + value)


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
        parse_constant=_reject_constant,
    )


def _stream_identity(raw: bytes) -> Dict[str, Any]:
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _is_linklike(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _workspace_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    info = os.lstat(str(root))
    if _is_linklike(info) or not stat.S_ISDIR(info.st_mode):
        raise GenerationError("workspace_root_invalid")
    return root


def _workspace_path(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if (
        candidate.is_absolute() or not candidate.parts
        or any(part in ("", ".", "..") for part in candidate.parts)
        or candidate.as_posix() != relative or "\\" in relative
    ):
        raise GenerationError("unsafe_workspace_path:" + str(relative))
    path = root
    for part in candidate.parts:
        path = path / part
        if os.path.lexists(str(path)) and _is_linklike(os.lstat(str(path))):
            raise GenerationError("workspace_path_linklike:" + relative)
    return path


def _absolute_regular_identity(path: Path) -> Dict[str, Any]:
    path = Path(os.path.abspath(str(path)))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = os.lstat(str(current))
        if _is_linklike(info):
            raise GenerationError("absolute_path_linklike:" + str(path))
    before = os.lstat(str(path))
    # Windows system binaries are commonly servicing hardlinks into WinSxS.
    # They are not source artifacts and cannot satisfy an nlink=1 policy.
    # Bind the exact opened inode, stable link count, path, bytes and SHA
    # instead; symlink/reparse objects remain forbidden.
    if not stat.S_ISREG(before.st_mode):
        raise GenerationError("absolute_path_not_regular:" + str(path))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, getattr(opened, "st_nlink", 1))
            != (before.st_dev, before.st_ino, getattr(before, "st_nlink", 1))
        ):
            raise GenerationError("absolute_open_identity_mismatch")
        chunks: List[bytes] = []
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
        or (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            getattr(after, "st_nlink", 1),
        ) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            getattr(before, "st_nlink", 1),
        )
        or len(raw) != opened.st_size
    ):
        raise GenerationError("absolute_identity_drift")
    return {
        "path": str(path), "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "hardlink_count": getattr(before, "st_nlink", 1),
    }


def _load_core(root: Path) -> Tuple[types.ModuleType, Mapping[str, Any]]:
    path = _workspace_path(root, CORE_RELATIVE_PATH)
    before = os.lstat(str(path))
    if not stat.S_ISREG(before.st_mode) or getattr(before, "st_nlink", 1) != 1:
        raise GenerationError("core_not_exclusive_regular")
    raw = path.read_bytes()
    after = os.lstat(str(path))
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    ):
        raise GenerationError("core_identity_drift")
    identity = {
        "root_role": "workspace", "path": CORE_RELATIVE_PATH,
        "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    }
    name = "_ros1_atomic_cli_field_producer_authority_v6_" + identity["sha256"]
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = "audit_tools"
    module.__spec__ = None
    previous = sys.modules.get(name)
    try:
        sys.modules[name] = module
        exec(compile(raw, str(path), "exec", dont_inherit=True, optimize=0), module.__dict__)
    except Exception as error:
        raise GenerationError("core_execution_failed") from error
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    for required in (
        "PRODUCTION_POLICY", "collect_source_role_bindings", "suite_inventory",
        "expected_logical_suite_records", "build_canonical_payload",
        "build_report_payload", "build_index_payload",
        "validate_formal_admission_evidence_authority_v6",
        "load_and_resolve_formal_admission_evidence_authority_v6",
        "write_json_exclusive", "_expected_production_cli_argv",
    ):
        if not hasattr(module, required):
            raise GenerationError("core_api_missing:" + required)
    return module, identity


def _wrapper_core_anchor_status(
    root: Path, core_identity: Mapping[str, Any],
) -> Mapping[str, Any]:
    path = _workspace_path(root, WRAPPER_RELATIVE_PATH)
    before = os.lstat(str(path))
    if (
        _is_linklike(before) or not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
    ):
        raise GenerationError("wrapper_source_not_exclusive_regular")
    raw = path.read_bytes()
    after = os.lstat(str(path))
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        or len(raw) != before.st_size
    ):
        raise GenerationError("wrapper_source_identity_drift")
    try:
        tree = ast.parse(raw, filename=str(path))
        values = []
        production_index_values = []
        for node in tree.body:
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "CORE_SOURCE_TRUST_ANCHOR"
            ):
                values.append(ast.literal_eval(node.value))
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "CORE_SOURCE_TRUST_ANCHOR"
                for target in node.targets
            ):
                values.append(ast.literal_eval(node.value))
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR"
            ):
                production_index_values.append(ast.literal_eval(node.value))
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "_WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR"
                for target in node.targets
            ):
                production_index_values.append(ast.literal_eval(node.value))
    except (SyntaxError, TypeError, ValueError) as error:
        raise GenerationError("wrapper_core_anchor_parse_failed") from error
    if len(values) != 1:
        raise GenerationError("wrapper_core_anchor_assignment_count_invalid")
    if len(production_index_values) != 1:
        raise GenerationError(
            "wrapper_production_index_anchor_assignment_count_invalid")
    expected = {
        key: core_identity[key]
        for key in ("path", "size_bytes", "sha256")
    }
    configured = values[0]
    return {
        "wrapper_identity": {
            "root_role": "workspace", "path": WRAPPER_RELATIVE_PATH,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "configured_core_anchor": configured,
        "expected_core_anchor": expected,
        "matches_live_core": configured == expected,
        "configured_production_index_anchor": production_index_values[0],
    }


def _selection_failures_from_wrapper_status(
    status: Mapping[str, Any], index_identity: Mapping[str, Any],
) -> List[str]:
    failures: List[str] = []
    if status.get("configured_core_anchor") is None:
        failures.append("formal_authority_v6_core_source_anchor_not_configured")
    elif status.get("matches_live_core") is not True:
        failures.append("formal_authority_v6_core_source_anchor_mismatch")
    configured_index = status.get("configured_production_index_anchor")
    if configured_index is None:
        failures.append("formal_authority_v6_production_anchor_not_configured")
    elif configured_index != dict(index_identity):
        failures.append("formal_authority_v6_production_anchor_mismatch")
    return failures


def _wrapper_selection_failures(
    root: Path, core_identity: Mapping[str, Any],
    index_identity: Mapping[str, Any],
) -> Tuple[List[str], Mapping[str, Any]]:
    try:
        status = _wrapper_core_anchor_status(root, core_identity)
    except Exception:
        return ["generation_wrapper_anchor_read_failed"], {
            "configured_core_anchor": None,
            "matches_live_core": False,
            "configured_production_index_anchor": None,
        }
    failures = _selection_failures_from_wrapper_status(
        status, index_identity,
    )
    return failures, status


def _execution_workspace_path(root: Path) -> str:
    drive, tail = os.path.splitdrive(str(root.resolve(strict=True)))
    if len(drive) != 2 or drive[1] != ":":
        raise GenerationError("workspace_not_wsl_mappable")
    parts = [item for item in tail.replace("\\", "/").split("/") if item]
    return str(PurePosixPath("/mnt", drive[0].lower(), *parts))


def _find_wsl() -> Tuple[Path, Mapping[str, Any]]:
    raw = shutil.which("wsl.exe")
    if raw is None:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        fallback = Path(system_root) / "System32" / "wsl.exe"
        if not fallback.exists():
            raise GenerationError("wsl_executable_missing")
        path = fallback
    else:
        path = Path(raw)
    return path, _absolute_regular_identity(path)


def _outer_windows_environment() -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            result[key] = value
    if not any(key.lower() == "systemroot" for key in result):
        raise GenerationError("windows_systemroot_missing")
    return result


def _parse_single_marker(stdout: bytes, prefix: str) -> Tuple[Mapping[str, Any], bytes]:
    prefix_raw = prefix.encode("ascii")
    lines = stdout.splitlines()
    markers = [line for line in lines if line.startswith(prefix_raw)]
    nonmarkers = [line for line in lines if line and not line.startswith(prefix_raw)]
    if len(markers) != 1 or nonmarkers:
        raise GenerationError("child_marker_count_or_stdout_invalid")
    raw = markers[0][len(prefix_raw):]
    payload = _strict_json(raw)
    if not isinstance(payload, dict):
        raise GenerationError("child_marker_payload_invalid")
    return payload, raw


def _source_by_key(source_roles: Sequence[Mapping[str, Any]]) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    return {(item["root_role"], item["path"]): item for item in source_roles}


def _source_identity(
    sources: Mapping[Tuple[str, str], Mapping[str, Any]],
    root_role: str, path: str,
) -> Dict[str, Any]:
    item = sources[(root_role, path)]
    return {key: item[key] for key in ("root_role", "path", "size_bytes", "sha256")}


def _frozen_source_mismatches(
    core: Any, source_roles: Sequence[Mapping[str, Any]],
) -> List[str]:
    by_key = _source_by_key(source_roles)
    mismatches: List[str] = []
    for key, expected in core.PRODUCTION_POLICY.frozen_source_identities.items():
        actual = by_key.get(key)
        identity = None if actual is None else {
            name: actual[name]
            for name in ("root_role", "path", "size_bytes", "sha256")
        }
        if identity != expected:
            mismatches.append("{}:{}".format(key[0], key[1]))
    return sorted(mismatches)


def _host_tree_plan_state(
    core: Any, root: Path, policy: Optional[Any] = None,
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    selected_policy = core.PRODUCTION_POLICY if policy is None else policy
    try:
        return (
            core.collect_host_perception_package_tree(
                root, selected_policy,
            ),
            None,
        )
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return None, type(error).__name__ + ":" + str(error)


def _child_command(
    core: Any, root: Path, suite: Mapping[str, Any], definition: Mapping[str, str],
    expected_ids: Sequence[str], wsl_path: Path,
) -> Tuple[List[str], Mapping[str, str], str, Optional[Mapping[str, Any]]]:
    runner = core.UNITTEST_RUNNER if suite["runner"] == "unittest" else core.PYTEST_RUNNER
    if definition["platform"] == "WINDOWS_HOST":
        argv = [
            sys.executable, "-I", "-S", "-B", str(_workspace_path(root, runner)),
        ]
        if suite["runner"] == "pytest_style":
            argv.append("--single-file")
        argv.extend(("--workspace", str(root), "--target", suite["target"], "--import-root", "."))
        for case_id in expected_ids:
            argv.extend(("--expected-id", case_id))
        return argv, _outer_windows_environment(), str(root), None
    wsl_root = _execution_workspace_path(root)
    interpreter = (
        "/usr/bin/python3" if definition["interpreter_role"] == "system_python3_entry"
        else "/usr/bin/python3.14"
    )
    child = [
        "/usr/bin/env", "-i",
        *[key + "=" + value for key, value in sorted(INNER_ENVIRONMENT.items())],
        interpreter, "-I", "-S", "-B",
        str(PurePosixPath(wsl_root, runner)),
    ]
    if suite["runner"] == "pytest_style":
        child.append("--single-file")
    child.extend(("--workspace", wsl_root, "--target", suite["target"], "--import-root", "."))
    for case_id in expected_ids:
        child.extend(("--expected-id", case_id))
    argv = [
        str(wsl_path), "--distribution", core.WSL_DISTRIBUTION,
        "--cd", wsl_root, "--exec", *child,
    ]
    return argv, _outer_windows_environment(), str(root), dict(INNER_ENVIRONMENT)


def _external_wrapper_parent_state(
    core: Any, root: Path, record_id: str, phase: str,
) -> Tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    try:
        signature_before = core.source_runtime_signature(
            root, "workspace", core.GENERATION_WRAPPER_SOURCE_PATH,
        )
        identity = core.source_artifact_identity(
            root, "workspace", core.GENERATION_WRAPPER_SOURCE_PATH,
        )
        signature_after = core.source_runtime_signature(
            root, "workspace", core.GENERATION_WRAPPER_SOURCE_PATH,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise GenerationError(
            "child_external_wrapper_parent_state_unreadable:{}:{}".format(
                record_id, phase,
            )
        ) from error
    if signature_before != signature_after:
        raise GenerationError(
            "child_external_wrapper_parent_state_drift:{}:{}".format(
                record_id, phase,
            )
        )
    return ({
        key: identity[key] for key in ("path", "size_bytes", "sha256")
    }, signature_after)


def _external_wrapper_observation(
    core: Any, definition: Mapping[str, Any], marker: Mapping[str, Any],
    parent_before: Mapping[str, Any],
    signature_before: Sequence[Mapping[str, Any]],
    parent_after: Mapping[str, Any],
    signature_after: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    record_id = definition["record_id"]
    if parent_before != parent_after:
        raise GenerationError(
            "child_external_wrapper_parent_identity_drift:" + record_id
        )
    if signature_before != signature_after:
        raise GenerationError(
            "child_external_wrapper_runtime_drift:" + record_id
        )
    matching_reads = [
        dict(item) for item in marker.get("workspace_source_reads", [])
        if isinstance(item, Mapping)
        and item.get("path") == core.GENERATION_WRAPPER_SOURCE_PATH
    ]
    expected_reads = (
        [dict(parent_before)]
        if record_id == core.GENERATION_WRAPPER_READ_RECORD_ID else []
    )
    if matching_reads != expected_reads:
        raise GenerationError(
            "child_external_wrapper_read_scope_invalid:" + record_id
        )
    observation = {
        "path": core.GENERATION_WRAPPER_SOURCE_PATH,
        "parent_before": dict(parent_before),
        "child_read": dict(parent_before) if expected_reads else None,
        "parent_after": dict(parent_after),
    }
    failures = core._external_wrapper_observation_failures(
        record_id, marker, observation,
        {item["record_id"]: item for item in core.EXECUTION_DEFINITIONS},
    )
    if failures:
        raise GenerationError(
            "child_external_wrapper_observation_invalid:"
            + record_id + ":" + ",".join(failures)
        )
    return observation


def _run_execution_matrix(
    core: Any, root: Path, source_roles: Sequence[Mapping[str, Any]],
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Mapping[str, Any]], Mapping[str, Any]]:
    suites = {item["suite_id"]: item for item in core.suite_inventory(root)}
    sources = _source_by_key(source_roles)
    try:
        workspace_loader_sources = core._workspace_loader_allowed_sources(
            root, source_roles, core.PRODUCTION_POLICY,
        )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        raise GenerationError(
            "workspace_loader_allowed_sources_invalid"
        ) from error
    wsl_path, wsl_identity = _find_wsl()
    matrix_wrapper_identity, matrix_wrapper_signature = (
        _external_wrapper_parent_state(
            core, root, "FULL_MATRIX", "before",
        )
    )
    raw_records: List[Dict[str, Any]] = []
    interpreter_cache: Dict[str, Mapping[str, Any]] = {}
    for definition in core.EXECUTION_DEFINITIONS:
        suite = suites[definition["suite_id"]]
        expected_ids = list(suite["expected_test_ids"])
        if definition["selection"] != "ALL":
            if definition["selection"] not in expected_ids:
                raise GenerationError("execution_selection_missing")
            expected_ids = [definition["selection"]]
        runner_path = core.UNITTEST_RUNNER if suite["runner"] == "unittest" else core.PYTEST_RUNNER
        test_before = core.source_artifact_identity(root, suite["root_role"], suite["target"])
        runner_before = core.source_artifact_identity(root, "workspace", runner_path)
        wrapper_parent_before, wrapper_signature_before = (
            _external_wrapper_parent_state(
                core, root, definition["record_id"], "before",
            )
        )
        if (
            wrapper_parent_before != matrix_wrapper_identity
            or wrapper_signature_before != matrix_wrapper_signature
        ):
            raise GenerationError(
                "child_external_wrapper_matrix_identity_drift_before:"
                + definition["record_id"]
            )
        argv, outer_environment, cwd, recorded_environment = _child_command(
            core, root, suite, definition, expected_ids, wsl_path,
        )
        completed = subprocess.run(
            argv, cwd=cwd, env=dict(outer_environment), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            timeout=COMMAND_TIMEOUT_SECONDS, close_fds=True,
        )
        test_after = core.source_artifact_identity(root, suite["root_role"], suite["target"])
        runner_after = core.source_artifact_identity(root, "workspace", runner_path)
        wrapper_parent_after, wrapper_signature_after = (
            _external_wrapper_parent_state(
                core, root, definition["record_id"], "after",
            )
        )
        if test_before != test_after or runner_before != runner_after:
            raise GenerationError("child_source_identity_drift:" + definition["record_id"])
        marker_prefix = core.UNITTEST_MARKER if suite["runner"] == "unittest" else core.PYTEST_MARKER
        marker, marker_raw = _parse_single_marker(completed.stdout, marker_prefix)
        if completed.returncode != 0:
            raise GenerationError("child_exit_nonzero:" + definition["record_id"])
        for key, expected in (
            ("path", suite["target"]), ("size_bytes", test_before["size_bytes"]),
            ("sha256", test_before["sha256"]), ("expected_ids", expected_ids),
            ("executed_ids", expected_ids), ("collected", len(expected_ids)),
            ("failed", 0),
        ):
            if marker.get(key) != expected:
                raise GenerationError("child_marker_mismatch:{}:{}".format(definition["record_id"], key))
        skipped = marker.get("skipped")
        passed = marker.get("passed")
        if type(skipped) is not int or type(passed) is not int or passed + skipped != len(expected_ids):
            raise GenerationError("child_count_not_conserved:" + definition["record_id"])
        loader_failures = core._workspace_loader_marker_failures(
            marker, test_before, workspace_loader_sources,
            definition["record_id"],
        )
        if loader_failures:
            raise GenerationError(
                "child_workspace_source_only_loader_invalid:"
                + definition["record_id"] + ":" + ",".join(loader_failures)
            )
        wrapper_observation = _external_wrapper_observation(
            core, definition, marker,
            wrapper_parent_before, wrapper_signature_before,
            wrapper_parent_after, wrapper_signature_after,
        )
        if (
            wrapper_parent_after != matrix_wrapper_identity
            or wrapper_signature_after != matrix_wrapper_signature
        ):
            raise GenerationError(
                "child_external_wrapper_matrix_identity_drift_after:"
                + definition["record_id"]
            )
        if definition["record_id"] == "doc_demotion_windows_bundled":
            skipped_ids = list(marker.get("skipped_ids", []))
            if skipped_ids not in ([], [core.DOC_DEMOTION_LINK_CASE_ID]):
                raise GenerationError("windows_skip_set_invalid")
        elif skipped:
            raise GenerationError("unexpected_child_skip:" + definition["record_id"])
        if suite["runner"] == "unittest":
            passed_ids = list(marker.get("passed_ids", []))
            failed_ids = list(marker.get("failed_ids", []))
            skipped_ids = list(marker.get("skipped_ids", []))
            interpreter_identity = marker.get("executable")
            if not isinstance(interpreter_identity, dict):
                raise GenerationError("unittest_interpreter_identity_missing")
            previous = interpreter_cache.get(definition["interpreter_role"])
            if previous is not None and previous != interpreter_identity:
                raise GenerationError("interpreter_role_identity_split")
            interpreter_cache[definition["interpreter_role"]] = interpreter_identity
        else:
            passed_ids = list(expected_ids) if skipped == 0 else []
            failed_ids = []
            skipped_ids = []
            interpreter_identity = None
        raw_records.append({
            "record_id": definition["record_id"],
            "suite_id": definition["suite_id"],
            "platform": definition["platform"],
            "interpreter_role": definition["interpreter_role"],
            "test_artifact_identity": test_before,
            "runner_artifact_identity": runner_before,
            "interpreter_identity": interpreter_identity,
            "orchestrator_identity": wsl_identity if definition["platform"] == "POSIX_WSL" else None,
            "expected_test_ids": expected_ids,
            "executed_test_ids": list(marker["executed_ids"]),
            "passed_ids": passed_ids,
            "failed_ids": failed_ids,
            "skipped_ids": skipped_ids,
            "collected": marker["collected"], "passed": passed,
            "failed": marker["failed"], "skipped": skipped,
            "exit_code": completed.returncode, "marker_count": 1,
            "marker_prefix": marker_prefix, "marker_payload": marker,
            "marker_payload_sha256": _canonical_sha256(marker),
            "argv": list(argv),
            "argv_sha256": _canonical_sha256(argv),
            "environment": dict(
                recorded_environment if recorded_environment is not None else outer_environment
            ),
            "environment_sha256": _canonical_sha256(
                recorded_environment if recorded_environment is not None else outer_environment
            ),
            "stdout": _stream_identity(completed.stdout),
            "stderr": _stream_identity(completed.stderr),
            "external_wrapper_observation": wrapper_observation,
        })
    matrix_wrapper_after, matrix_wrapper_signature_after = (
        _external_wrapper_parent_state(
            core, root, "FULL_MATRIX", "after",
        )
    )
    if (
        matrix_wrapper_after != matrix_wrapper_identity
        or matrix_wrapper_signature_after != matrix_wrapper_signature
    ):
        raise GenerationError("child_external_wrapper_full_matrix_drift")
    # pytest-style records do not expose an executable identity; bind them to
    # the independently observed same-role unittest interpreter.
    for record in raw_records:
        if record["interpreter_identity"] is None:
            identity = interpreter_cache.get(record["interpreter_role"])
            if identity is None:
                raise GenerationError("interpreter_role_not_attested")
            record["interpreter_identity"] = identity
    physical = sorted(raw_records, key=lambda item: item["record_id"])
    physical_failures, physical_by_id = core._validate_physical_records(
        root, physical, source_roles, core.PRODUCTION_POLICY,
    )
    if physical_failures:
        raise GenerationError("physical_validation_failed:" + ",".join(physical_failures))
    composites = core._expected_platform_composites(physical_by_id)
    if not all(item["validated_pass"] for item in composites):
        raise GenerationError("platform_composite_not_closed")
    logical = core.expected_logical_suite_records(root, source_roles)
    # Every logical suite must have one full-file physical record.  The only
    # raw skip is closed by the exact composite above.
    for logical_record in logical:
        full = [
            item for item in physical
            if item["suite_id"] == logical_record["suite_id"]
            and item["expected_test_ids"] == logical_record["expected_test_ids"]
        ]
        if not full or any(item["failed"] for item in full):
            raise GenerationError("logical_suite_missing_full_execution:" + logical_record["suite_id"])
        if logical_record["suite_id"] != "machine_contract_doc_demotion" and any(item["skipped"] for item in full):
            raise GenerationError("logical_suite_unapproved_skip:" + logical_record["suite_id"])
    return logical, physical, composites, interpreter_cache, wsl_identity


def _run_production_cli(
    core: Any, root: Path, source_roles: Sequence[Mapping[str, Any]],
    expectation: Mapping[str, Any], interpreter_identity: Mapping[str, Any],
    wsl_identity: Mapping[str, Any], wsl_path: Path,
    *, _command_runner: Optional[Callable[..., Any]] = None,
) -> Mapping[str, Any]:
    observation_id = expectation["observation_id"]
    try:
        dependency_paths = core.production_runtime_dependency_paths(
            expectation)
    except (KeyError, TypeError, ValueError) as error:
        raise GenerationError(
            "production_cli_runtime_dependency_paths_invalid:"
            + observation_id
        ) from error
    if not dependency_paths:
        raise GenerationError(
            "production_cli_runtime_dependency_paths_invalid:"
            + observation_id
        )
    sources = _source_by_key(source_roles)
    cached_by_path: Dict[str, Mapping[str, Any]] = {}
    dependencies: List[Dict[str, Any]] = []
    for relative in dependency_paths:
        if ("workspace", relative) not in sources:
            raise GenerationError(
                "production_cli_runtime_dependency_source_role_missing:"
                + observation_id + ":" + relative
            )
        cached = _source_identity(sources, "workspace", relative)
        cached_by_path[relative] = cached
        try:
            identity_before = core.source_artifact_identity(
                root, "workspace", relative)
            signature_before = core.source_runtime_signature(
                root, "workspace", relative)
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise GenerationError(
                "production_cli_runtime_dependency_read_failed_before:"
                + observation_id + ":" + relative
            ) from error
        if identity_before != cached:
            code = (
                "production_cli_source_identity_mismatch_before:"
                + observation_id
                if relative == expectation["source_path"]
                else
                "production_cli_runtime_dependency_identity_mismatch_before:"
                + observation_id + ":" + relative
            )
            raise GenerationError(code)
        dependencies.append({
            "path": relative,
            "identity_before": identity_before,
            "signature_before": signature_before,
        })
    source_before = next(
        item["identity_before"] for item in dependencies
        if item["path"] == expectation["source_path"]
    )
    argv = core._expected_production_cli_argv(
        root, expectation, str(wsl_path), source_roles,
        interpreter_identity,
    )
    command_runner = subprocess.run if _command_runner is None else _command_runner
    completed = command_runner(
        argv, cwd=str(root), env=_outer_windows_environment(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=COMMAND_TIMEOUT_SECONDS, close_fds=True,
    )
    for item in dependencies:
        relative = item["path"]
        try:
            item["identity_after"] = core.source_artifact_identity(
                root, "workspace", relative)
            item["signature_after"] = core.source_runtime_signature(
                root, "workspace", relative)
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise GenerationError(
                "production_cli_runtime_dependency_read_failed_after:"
                + observation_id + ":" + relative
            ) from error
    for item in dependencies:
        relative = item["path"]
        if item["identity_after"] != cached_by_path[relative]:
            code = (
                "production_cli_source_identity_mismatch_after:"
                + observation_id
                if relative == expectation["source_path"]
                else
                "production_cli_runtime_dependency_identity_mismatch_after:"
                + observation_id + ":" + relative
            )
            raise GenerationError(code)
    for item in dependencies:
        relative = item["path"]
        if item["signature_after"] != item["signature_before"]:
            code = (
                "production_cli_source_runtime_drift:" + observation_id
                if relative == expectation["source_path"]
                else
                "production_cli_runtime_dependency_runtime_drift:"
                + observation_id + ":" + relative
            )
            raise GenerationError(code)
    source_after = next(
        item["identity_after"] for item in dependencies
        if item["path"] == expectation["source_path"]
    )
    if completed.returncode != expectation["exit_code"]:
        raise GenerationError(
            "production_cli_exit_mismatch:" + observation_id)
    marker_prefix = expectation["marker_prefix"]
    if marker_prefix is not None:
        payload, unused_raw = _parse_single_marker(
            completed.stdout, marker_prefix,
        )
    else:
        try:
            payload = _strict_json(completed.stdout)
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise GenerationError(
                "production_cli_strict_json_marker_invalid:"
                + expectation["observation_id"]
            ) from error
        if (
            not isinstance(payload, dict)
            or expectation["payload_marker_field"] is None
            or payload.get(expectation["payload_marker_field"])
            != expectation["payload_marker_value"]
        ):
            raise GenerationError(
                "production_cli_payload_marker_mismatch:"
                + expectation["observation_id"]
            )
    payload_contract_failures = core.production_payload_contract_failures(
        expectation, payload)
    if payload_contract_failures:
        raise GenerationError(
            "production_payload_" + payload_contract_failures[0] + ":"
            + expectation["observation_id"])
    failures = payload["failures"]
    expected_stdout = core.expected_production_observation_stdout(
        expectation, payload)
    expected_stderr = core.expected_production_observation_stderr(expectation)
    if completed.stdout != expected_stdout:
        raise GenerationError(
            "production_cli_stdout_mismatch:" + observation_id)
    if completed.stderr != expected_stderr:
        raise GenerationError(
            "production_cli_stderr_mismatch:" + observation_id)
    return {
        "observation_id": expectation["observation_id"],
        "source_identity_before": source_before,
        "source_identity_after": source_after,
        "runtime_dependencies": dependencies,
        "interpreter_identity": interpreter_identity,
        "orchestrator_identity": wsl_identity,
        "argv": list(argv),
        "argv_sha256": _canonical_sha256(argv),
        "environment": dict(core.CHILD_ENVIRONMENT),
        "environment_sha256": _canonical_sha256(core.CHILD_ENVIRONMENT),
        "exit_code": completed.returncode, "marker_count": 1,
        "blocked_code": expectation["blocked_code"],
        "failure_codes": list(failures),
        "stdout": _stream_identity(completed.stdout),
        "stderr": _stream_identity(completed.stderr),
        "payload": dict(payload),
        "payload_sha256": _canonical_sha256(payload),
        "expected_fail_closed": True,
        "not_in_logical_denominator": True,
        "not_in_physical_denominator": True,
        "formal_consumer": False, "delivery_ready": False,
        "self_reported_anchor_accepted": False,
        "execution_attempted": True, "supporting_test_id": None,
    }


def _production_observations(
    core: Any, root: Path, source_roles: Sequence[Mapping[str, Any]],
    physical: Sequence[Mapping[str, Any]],
    interpreter_cache: Mapping[str, Mapping[str, Any]],
    wsl_identity: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    wsl_path, verified_wsl = _find_wsl()
    if verified_wsl != wsl_identity:
        raise GenerationError("wsl_identity_drift_before_production_observation")
    observations: List[Mapping[str, Any]] = []
    for expectation in core.PRODUCTION_CLI_EXPECTATIONS:
        if expectation["execution_attempted"]:
            observations.append(_run_production_cli(
                core, root, source_roles, expectation,
                interpreter_cache["system_python314_target"],
                wsl_identity, wsl_path,
            ))
            continue
        # Safety boundary: do not manually invoke atomic --mode.  Require the
        # exact full atomic suite record to prove the supporting test executed
        # and passed under isolated child control.
        supporting = expectation["supporting_test_id"]
        physical_by_id = {item["record_id"]: item for item in physical}
        supporting_records = []
        for record_id in expectation["supporting_record_ids"]:
            record = physical_by_id.get(record_id)
            if (
                record is None
                or record.get("suite_id")
                != expectation["supporting_suite_id"]
                or supporting not in record.get("passed_ids", [])
            ):
                raise GenerationError(
                    "static_supporting_test_not_exact_pass:"
                    + expectation["observation_id"] + ":" + record_id
                )
            supporting_records.append(record)
        sources = _source_by_key(source_roles)
        identity = _source_identity(sources, "workspace", expectation["source_path"])
        static_material = {
            "execution_attempted": False,
            "supporting_test_id": supporting,
            "supporting_record_ids": list(
                expectation["supporting_record_ids"]),
            "blocked_code": expectation["blocked_code"],
        }
        observations.append({
            "observation_id": expectation["observation_id"],
            "source_identity_before": identity, "source_identity_after": identity,
            "runtime_dependencies": [],
            "interpreter_identity": None, "orchestrator_identity": None,
            "argv": ["NOT_EXECUTED_SAFETY_BOUNDARY"],
            "argv_sha256": _canonical_sha256(["NOT_EXECUTED_SAFETY_BOUNDARY"]),
            "environment": {},
            "environment_sha256": _canonical_sha256({}),
            "exit_code": expectation["exit_code"], "marker_count": 0,
            "blocked_code": expectation["blocked_code"],
            "failure_codes": [expectation["blocked_code"]],
            "stdout": _stream_identity(
                core.expected_production_observation_stdout(
                    expectation, static_material)),
            "stderr": _stream_identity(
                core.expected_production_observation_stderr(expectation)),
            "payload": static_material,
            "payload_sha256": _canonical_sha256(static_material),
            "expected_fail_closed": True,
            "not_in_logical_denominator": True,
            "not_in_physical_denominator": True,
            "formal_consumer": False, "delivery_ready": False,
            "self_reported_anchor_accepted": False,
            "execution_attempted": False, "supporting_test_id": supporting,
        })
    observations.sort(key=lambda item: item["observation_id"])
    failures = core._validate_production_observations(
        root, observations, source_roles,
        {item["record_id"]: item for item in physical},
        core.PRODUCTION_POLICY,
    )
    if failures:
        raise GenerationError("production_observation_validation_failed:" + ",".join(failures))
    return observations


def _require_generation_context() -> None:
    if os.name != "nt":
        raise GenerationError("generation_requires_windows_host")
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise GenerationError("generation_requires_I_S_B")
    contaminated = [key for key in SENSITIVE_ENVIRONMENT if os.environ.get(key)]
    if contaminated:
        raise GenerationError("generator_environment_contaminated:" + ",".join(contaminated))


def _output_path(root: Path, relative: str) -> Path:
    path = _workspace_path(root, relative)
    if os.path.lexists(str(path)):
        raise GenerationError("exclusive_output_already_exists:" + relative)
    parent = path.parent
    if not parent.exists() or _is_linklike(os.lstat(str(parent))) or not parent.is_dir():
        raise GenerationError("exclusive_output_parent_invalid:" + relative)
    return path


def _generation_status_result(
    core: Any, status: str, *, artifact_identities: Optional[Mapping[str, Any]] = None,
    failures: Sequence[str] = (),
    candidate_resolver: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    committed = status in {
        GENERATION_STATUS_COMMITTED_UNSELECTED,
        GENERATION_STATUS_SELECTED_BLOCKED_OFFLINE,
    }
    selected = status == GENERATION_STATUS_SELECTED_BLOCKED_OFFLINE
    failure_list = list(dict.fromkeys(str(item) for item in failures))
    abandoned = status == GENERATION_STATUS_ABANDONED_UNINDEXED
    return {
        "generation_id": core.GENERATION_ID,
        "generation_status": status,
        "committed": committed,
        "index_committed": committed,
        "commit_basis": "EXACT_INDEX_BYTES" if committed else None,
        "selected": selected,
        "selection_anchor_unset": (
            "formal_authority_v6_production_anchor_not_configured"
            in failure_list
        ),
        "independent_resolution_pending": committed and not selected,
        "same_identity_retry": False,
        "same_identity_retry_allowed": False,
        "same_generation_retry_forbidden": abandoned or committed,
        "read_only_reinspection": committed,
        "requires_new_version": abandoned,
        "requires_new_generation_id": abandoned,
        "artifact_identities": dict(artifact_identities or {}),
        "failures": failure_list,
        "candidate_resolver_validated_pass": bool(
            isinstance(candidate_resolver, Mapping)
            and candidate_resolver.get("validated_pass") is True
            and not candidate_resolver.get("failures")
        ),
        "accepted_as_offline_release_selection_authority": selected,
        "formal_denominator": 0,
        "formal_consumer": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "delivery_ready": False,
        "authorizes_field_delivery": False,
        "ros1_noetic_runtime_verified": False,
        "ros1_noetic_build_install_verified": False,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "formal_latency_pass": False,
    }


def _current_generation_output_state(
    core: Any, root: Path, core_identity: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Inspect all three same-generation outputs as one commit boundary."""
    relative_by_role = {
        "canonical": core.CANONICAL_RELATIVE_PATH,
        "report": core.REPORT_RELATIVE_PATH,
        "index": core.INDEX_RELATIVE_PATH,
    }
    present = {
        role: os.path.lexists(str(_workspace_path(root, relative)))
        for role, relative in relative_by_role.items()
    }
    if not present["index"] and not present["canonical"] and not present["report"]:
        return _generation_status_result(
            core, GENERATION_STATUS_PREPARED)
    identities: Dict[str, Mapping[str, Any]] = {}
    if not present["index"]:
        for role in ("canonical", "report"):
            if not present[role]:
                continue
            try:
                identity, unused_raw = core._read_regular_identity(
                    root, "workspace", relative_by_role[role])
                identities[role] = {
                    key: identity[key]
                    for key in ("path", "size_bytes", "sha256")
                }
            except (OSError, TypeError, UnicodeError, ValueError):
                pass
        return _generation_status_result(
            core, GENERATION_STATUS_ABANDONED_UNINDEXED,
            artifact_identities=identities,
            failures=["generation_index_o_excl_commit_not_completed"],
        )
    try:
        index_identity, index_raw = core._read_regular_identity(
            root, "workspace", relative_by_role["index"])
        identities["index"] = {
            key: index_identity[key]
            for key in ("path", "size_bytes", "sha256")
        }
        index = _strict_json(index_raw)
    except (GenerationError, OSError, TypeError, UnicodeError, ValueError,
            json.JSONDecodeError):
        return _generation_status_result(
            core, GENERATION_STATUS_ABANDONED_UNINDEXED,
            artifact_identities=identities,
            failures=["generation_current_output_unreadable:index"],
        )
    current_entries = (
        [item for item in index.get("entries", [])
         if isinstance(item, Mapping) and item.get("is_current") is True]
        if isinstance(index, Mapping) else []
    )
    children = index.get("child_artifacts", []) if isinstance(index, Mapping) else []
    def index_identity_valid(value: Any, expected_path: str) -> bool:
        return (
            isinstance(value, Mapping)
            and value.get("path") == expected_path
            and type(value.get("size_bytes")) is int
            and value["size_bytes"] > 0
            and isinstance(value.get("sha256"), str)
            and len(value["sha256"]) == 64
            and all(character in "0123456789abcdef"
                    for character in value["sha256"])
        )
    if (
        not isinstance(index, Mapping)
        or index.get("index_instance_id") != core.INDEX_INSTANCE_ID
        or index.get("generation_id") != core.GENERATION_ID
        or index.get("current_evidence_id") != core.CURRENT_EVIDENCE_ID
        or len(current_entries) != 1
        or current_entries[0].get("evidence_id") != core.CURRENT_EVIDENCE_ID
        or not index_identity_valid(
            current_entries[0], core.REPORT_RELATIVE_PATH)
        or not isinstance(children, list) or len(children) != 1
        or not isinstance(children[0], Mapping)
        or children[0].get("artifact_id") != core.CANONICAL_ARTIFACT_ID
        or children[0].get("canonical_id") != core.CANONICAL_ID
        or not index_identity_valid(
            children[0], core.CANONICAL_RELATIVE_PATH)
    ):
        return _generation_status_result(
            core, GENERATION_STATUS_ABANDONED_UNINDEXED,
            artifact_identities=identities,
            failures=["generation_current_index_not_commit_complete"],
        )

    candidate_failures: List[str] = []
    payloads: Dict[str, Any] = {"index": index}
    for role in ("canonical", "report"):
        if not present[role]:
            candidate_failures.append(
                "generation_current_output_missing:" + role)
            continue
        try:
            identity, raw = core._read_regular_identity(
                root, "workspace", relative_by_role[role])
            identities[role] = {
                key: identity[key]
                for key in ("path", "size_bytes", "sha256")
            }
            payloads[role] = _strict_json(raw)
        except (GenerationError, OSError, TypeError, UnicodeError, ValueError,
                json.JSONDecodeError):
            candidate_failures.append(
                "generation_current_output_unreadable:" + role)
    if "canonical" in identities:
        expected_child = {
            key: children[0][key]
            for key in ("path", "size_bytes", "sha256")
        }
        if identities["canonical"] != expected_child:
            candidate_failures.append(
                "generation_current_output_identity_mismatch:canonical")
    if "report" in identities:
        expected_report = {
            key: current_entries[0][key]
            for key in ("path", "size_bytes", "sha256")
        }
        if identities["report"] != expected_report:
            candidate_failures.append(
                "generation_current_output_identity_mismatch:report")
    complete_triplet = not candidate_failures

    wrapper_failures, wrapper_status = _wrapper_selection_failures(
        root, core_identity, identities["index"],
    )
    try:
        resolver = (
            core.load_and_resolve_formal_admission_evidence_authority_v6(
                root, identities["index"])
            if complete_triplet else {
                "validated_pass": False,
                "accepted_as_offline_release_selection_authority": False,
                "failures": list(candidate_failures),
            }
        )
    except Exception:
        resolver = {
            "validated_pass": False,
            "failures": [
                "generation_post_commit_candidate_resolver_exception"
            ],
        }
    resolver_failures = list(resolver.get("failures", []))
    if (
        resolver.get("validated_pass") is not True
        and not resolver_failures
    ):
        resolver_failures.append(
            "generation_post_commit_candidate_validation_failed")
    selected = (
        complete_triplet
        and wrapper_status.get("matches_live_core") is True
        and wrapper_status.get("configured_production_index_anchor")
        == identities["index"]
        and resolver.get("validated_pass") is True
        and resolver.get("accepted_as_offline_release_selection_authority")
        is True
        and not resolver.get("failures")
    )
    selection_failures = (
        list(candidate_failures) + resolver_failures + wrapper_failures
    )
    return _generation_status_result(
        core,
        (GENERATION_STATUS_SELECTED_BLOCKED_OFFLINE if selected
         else GENERATION_STATUS_COMMITTED_UNSELECTED),
        artifact_identities=identities,
        failures=selection_failures, candidate_resolver=resolver,
    )


def _evidence_identity_inventory(
    core: Any, root: Path,
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, str]]]:
    evidence_root = _workspace_path(root, "evidence")
    if not evidence_root.exists() or not evidence_root.is_dir():
        raise GenerationError("evidence_inventory_root_missing")
    inventory: List[Mapping[str, Any]] = []
    candidate_ids = {
        "evidence_id": core.CURRENT_EVIDENCE_ID,
        "current_evidence_id": core.CURRENT_EVIDENCE_ID,
        "generation_id": core.GENERATION_ID,
        "index_instance_id": core.INDEX_INSTANCE_ID,
        "artifact_id": core.CANONICAL_ARTIFACT_ID,
        "canonical_id": core.CANONICAL_ID,
        "report_id": core.REPORT_ID,
    }
    candidate_values = frozenset(candidate_ids.values())
    registered_artifacts: Dict[str, Mapping[str, Any]] = {}
    registered_generation_ids: set[str] = set()
    registered_index_ids: set[str] = set()
    current_paths = {
        core.CANONICAL_RELATIVE_PATH,
        core.REPORT_RELATIVE_PATH,
        core.INDEX_RELATIVE_PATH,
    }
    forbidden_registry_paths = current_paths | {
        core.PREDECESSOR_INDEX_IDENTITY["path"],
        core.PREDECESSOR_REPORT_IDENTITY["path"],
        core.PREDECESSOR_CANONICAL_IDENTITY["path"],
    } | {
        path for unused_role, root_role, path
        in core.REQUIRED_SOURCE_ROLE_DEFINITIONS
        if root_role == "workspace"
    }
    for entry in REGISTERED_NONSELECTABLE_GENERATIONS:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {
                "schema_version", "registry_status", "generation_status",
                "generation_id", "index_instance_id", "artifacts",
            }
            or entry.get("schema_version")
            != "registered_nonselectable_generation/v1"
            or entry.get("registry_status")
            != "REGISTERED_NONSELECTABLE_GENERATION"
            or entry.get("generation_status")
            != GENERATION_STATUS_ABANDONED_UNINDEXED
            or not isinstance(entry.get("generation_id"), str)
            or not entry["generation_id"]
            or not isinstance(entry.get("index_instance_id"), str)
            or not entry["index_instance_id"]
            or not isinstance(entry.get("artifacts"), (list, tuple))
            or not entry["artifacts"]
            or entry["generation_id"] in registered_generation_ids
            or entry["index_instance_id"] in registered_index_ids
            or entry["generation_id"] in {
                core.GENERATION_ID,
                core.PREDECESSOR_INDEX_IDENTITY["generation_id"],
            }
            or entry["index_instance_id"] in {
                core.INDEX_INSTANCE_ID,
                core.PREDECESSOR_INDEX_IDENTITY["index_instance_id"],
            }
        ):
            raise GenerationError("nonselectable_generation_registry_invalid")
        registered_generation_ids.add(entry["generation_id"])
        registered_index_ids.add(entry["index_instance_id"])
        artifact_roles: set[str] = set()
        for artifact in entry["artifacts"]:
            artifact_path = (
                artifact.get("path") if isinstance(artifact, Mapping) else None
            )
            candidate_path = (
                PurePosixPath(artifact_path)
                if isinstance(artifact_path, str) else None
            )
            if (
                not isinstance(artifact, Mapping)
                or set(artifact) != {
                    "role", "path", "size_bytes", "sha256",
                }
                or artifact.get("role") not in {
                    "canonical", "report", "index",
                }
                or artifact["role"] in artifact_roles
                or not isinstance(artifact_path, str)
                or not artifact_path
                or candidate_path is None
                or candidate_path.is_absolute()
                or not candidate_path.parts
                or candidate_path.parts[0] != "evidence"
                or any(part in ("", ".", "..")
                       for part in candidate_path.parts)
                or candidate_path.as_posix() != artifact_path
                or "\\" in artifact_path
                or candidate_path.suffix != ".json"
                or type(artifact.get("size_bytes")) is not int
                or artifact["size_bytes"] < 0
                or not isinstance(artifact.get("sha256"), str)
                or len(artifact["sha256"]) != 64
                or any(character not in "0123456789abcdef"
                       for character in artifact["sha256"])
                or artifact_path in registered_artifacts
                or artifact_path in forbidden_registry_paths
            ):
                raise GenerationError(
                    "nonselectable_generation_registry_path_invalid")
            artifact_roles.add(artifact["role"])
            registered_artifacts[artifact_path] = {
                "generation_id": entry["generation_id"],
                "index_instance_id": entry["index_instance_id"],
                "generation_status": entry["generation_status"],
                "role": artifact["role"],
                "identity": {
                    key: artifact[key]
                    for key in ("path", "size_bytes", "sha256")
                },
            }
            try:
                live_identity, unused_raw = core._read_regular_identity(
                    root, "workspace", artifact_path,
                )
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                raise GenerationError(
                    "nonselectable_generation_registry_artifact_unreadable:"
                    + artifact_path
                ) from error
            if {
                key: live_identity[key]
                for key in ("path", "size_bytes", "sha256")
            } != registered_artifacts[artifact_path]["identity"]:
                raise GenerationError(
                    "nonselectable_generation_registry_identity_mismatch:"
                    + artifact_path
                )

    def identifier_items(
        value: Any, location: str = "",
    ) -> Iterable[Tuple[str, Any]]:
        if isinstance(value, dict):
            for key, child in value.items():
                child_location = key if not location else location + "." + key
                if key in candidate_ids:
                    yield child_location, child
                yield from identifier_items(child, child_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                child_location = "{}[{}]".format(location, index)
                yield from identifier_items(child, child_location)
    collisions: List[Mapping[str, str]] = []
    registered_seen: set[str] = set()
    for path in sorted(evidence_root.rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        try:
            identity, raw = core._read_regular_identity(
                root, "workspace", relative,
            )
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise GenerationError(
                "evidence_inventory_unreadable:{}:{}".format(
                    relative, type(error).__name__,
                )
            ) from error
        registered = registered_artifacts.get(relative)
        live_identity = {
            key: identity[key]
            for key in ("path", "size_bytes", "sha256")
        }
        if registered is not None:
            if live_identity != registered["identity"]:
                raise GenerationError(
                    "nonselectable_generation_registry_identity_mismatch:"
                    + relative
                )
            registered_seen.add(relative)
        try:
            payload = _strict_json(raw)
        except (GenerationError, TypeError, UnicodeError, ValueError,
                json.JSONDecodeError) as error:
            if registered is None:
                raise GenerationError(
                    "evidence_inventory_unreadable:{}:{}".format(
                        relative, type(error).__name__,
                    )
                ) from error
            inventory.append({
                **{
                    key: identity[key]
                    for key in ("root_role", "path", "size_bytes", "sha256")
                },
                "identifiers": {},
                "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
                "registry_generation_id": registered["generation_id"],
                "registry_index_instance_id": registered["index_instance_id"],
                "registry_generation_status": registered["generation_status"],
                "registry_artifact_role": registered["role"],
                "strict_json_readable": False,
            })
            continue
        identifiers: Dict[str, str] = {}
        if isinstance(payload, dict):
            for field, value in identifier_items(payload):
                if value is None:
                    continue
                if not isinstance(value, str) or not value:
                    raise GenerationError(
                        "evidence_inventory_identity_invalid:{}:{}".format(
                            relative, field,
                        )
                    )
                identifiers[field] = value
                if value in candidate_values:
                    collisions.append({
                        "path": relative, "field": field, "value": value,
                    })
        inventory_entry = {
            **{
                key: identity[key]
                for key in ("root_role", "path", "size_bytes", "sha256")
            },
            "identifiers": identifiers,
        }
        if registered is not None:
            inventory_entry.update({
                "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
                "registry_generation_id": registered["generation_id"],
                "registry_index_instance_id": registered["index_instance_id"],
                "registry_generation_status": registered["generation_status"],
                "registry_artifact_role": registered["role"],
                "strict_json_readable": True,
            })
        inventory.append(inventory_entry)
    if registered_seen != set(registered_artifacts):
        raise GenerationError("nonselectable_generation_registry_not_fully_seen")
    return inventory, sorted(
        collisions, key=lambda item: (item["path"], item["field"]),
    )


def _plan(root: Path) -> Mapping[str, Any]:
    core, core_identity = _load_core(root)
    core_anchor_status = _wrapper_core_anchor_status(root, core_identity)
    current_output_state = _current_generation_output_state(
        core, root, core_identity)
    if current_output_state["generation_status"] != GENERATION_STATUS_PREPARED:
        outputs = [
            core.CANONICAL_RELATIVE_PATH, core.REPORT_RELATIVE_PATH,
            core.INDEX_RELATIVE_PATH,
        ]
        return {
            "schema_version": (
                "ros1_atomic_cli_field_producer_blocked_offline_plan/v1"
            ),
            "generation_id": core.GENERATION_ID,
            "index_instance_id": core.INDEX_INSTANCE_ID,
            "predecessor": dict(core.PREDECESSOR_INDEX_IDENTITY),
            "canonical_output": core.CANONICAL_RELATIVE_PATH,
            "report_output": core.REPORT_RELATIVE_PATH,
            "index_output": core.INDEX_RELATIVE_PATH,
            "core_identity": dict(core_identity),
            "wrapper_core_anchor_status": core_anchor_status,
            "generation_status": current_output_state["generation_status"],
            "same_identity_retry": False,
            "existing_generation_state": current_output_state,
            "existing_outputs": [
                relative for relative in outputs
                if os.path.lexists(str(_workspace_path(root, relative)))
            ],
            "evidence_inventory_skipped_for_existing_generation": True,
            "ready_to_attempt_generation": False,
            "writes_only_on_generate": True,
            "formal_denominator": 0,
            "formal_consumer": False,
            "delivery_ready": False,
        }
    missing: List[Mapping[str, str]] = []
    for role, root_role, path in core.REQUIRED_SOURCE_ROLE_DEFINITIONS:
        try:
            core.source_artifact_identity(root, root_role, path)
        except (OSError, UnicodeError, ValueError):
            missing.append({"role": role, "root_role": root_role, "path": path})
    source_roles: List[Mapping[str, Any]] = []
    frozen_mismatches: List[str] = []
    host_tree_binding: Optional[Mapping[str, Any]] = None
    host_tree_error: Optional[str] = None
    if not missing:
        try:
            source_roles = core.collect_source_role_bindings(root)
            frozen_mismatches = _frozen_source_mismatches(core, source_roles)
            host_tree_binding, host_tree_error = _host_tree_plan_state(
                core, root,
            )
        except (OSError, UnicodeError, ValueError) as error:
            frozen_mismatches = [type(error).__name__ + ":" + str(error)]
    suites: List[Mapping[str, Any]] = []
    suite_error: Optional[str] = None
    try:
        suites = core.suite_inventory(root)
    except (OSError, SyntaxError, UnicodeError, ValueError) as error:
        suite_error = type(error).__name__ + ":" + str(error)
    outputs = [
        core.CANONICAL_RELATIVE_PATH, core.REPORT_RELATIVE_PATH,
        core.INDEX_RELATIVE_PATH,
    ]
    existing_outputs = [
        item for item in outputs if os.path.lexists(str(_workspace_path(root, item)))
    ]
    evidence_inventory, identity_collisions = _evidence_identity_inventory(
        core, root,
    )
    logical_total = sum(item["logical_count"] for item in suites)
    execution_counts: Dict[str, Optional[int]] = {}
    suite_by_id = {item["suite_id"]: item for item in suites}
    for definition in core.EXECUTION_DEFINITIONS:
        suite = suite_by_id.get(definition["suite_id"])
        execution_counts[definition["record_id"]] = (
            None if suite is None else (
                suite["logical_count"] if definition["selection"] == "ALL" else 1
            )
        )
    physical_total = sum(item for item in execution_counts.values() if isinstance(item, int))
    supporting_present = any(
        core.ATOMIC_SUPPORTING_TEST_ID in item["expected_test_ids"]
        for item in suites if item["suite_id"] == "camera_only_atomic_launcher"
    )
    return {
        "schema_version": "ros1_atomic_cli_field_producer_blocked_offline_plan/v1",
        "generation_id": core.GENERATION_ID,
        "index_instance_id": core.INDEX_INSTANCE_ID,
        "predecessor": dict(core.PREDECESSOR_INDEX_IDENTITY),
        "canonical_output": core.CANONICAL_RELATIVE_PATH,
        "report_output": core.REPORT_RELATIVE_PATH,
        "index_output": core.INDEX_RELATIVE_PATH,
        "core_identity": dict(core_identity),
        "wrapper_core_anchor_status": core_anchor_status,
        "generation_status": current_output_state["generation_status"],
        "same_identity_retry": current_output_state["same_identity_retry"],
        "existing_generation_state": current_output_state,
        "source_role_count": len(core.REQUIRED_SOURCE_ROLE_DEFINITIONS),
        "missing_required_source_roles": missing,
        "frozen_source_identity_mismatches": frozen_mismatches,
        "host_perception_package_tree": host_tree_binding,
        "host_perception_package_tree_error": host_tree_error,
        "suite_inventory": suites,
        "suite_inventory_error": suite_error,
        "logical_expected_recomputed": logical_total,
        "execution_record_counts": execution_counts,
        "physical_expected_recomputed": physical_total,
        "windows_skip_case_id": core.DOC_DEMOTION_LINK_CASE_ID,
        "posix_companion_required": True,
        "atomic_production_cli_execution_forbidden": True,
        "atomic_static_supporting_test_id": core.ATOMIC_SUPPORTING_TEST_ID,
        "atomic_static_supporting_test_present": supporting_present,
        "production_blocked_codes": [item["blocked_code"] for item in core.PRODUCTION_CLI_EXPECTATIONS],
        "existing_outputs": existing_outputs,
        "evidence_identity_inventory": evidence_inventory,
        "evidence_identity_inventory_sha256": _canonical_sha256(
            evidence_inventory
        ),
        "evidence_identity_collisions": identity_collisions,
        "identity_collision_guard_uses_filename_or_mtime": False,
        "ready_to_attempt_generation": bool(
            not missing and not frozen_mismatches
            and host_tree_error is None
            and suite_error is None and not existing_outputs
            and not identity_collisions
            and core_anchor_status["matches_live_core"]
            and current_output_state["generation_status"]
            == GENERATION_STATUS_PREPARED
            and logical_total > 0 and physical_total > 0 and supporting_present
        ),
        "writes_only_on_generate": True,
        "formal_denominator": 0,
        "formal_consumer": False,
        "delivery_ready": False,
    }


def _generate(root: Path) -> Mapping[str, Any]:
    _require_generation_context()
    core, core_identity_before = _load_core(root)
    current_state = _current_generation_output_state(
        core, root, core_identity_before)
    if current_state["generation_status"] != GENERATION_STATUS_PREPARED:
        return current_state

    index_write_completed = False
    index_identity: Optional[Mapping[str, Any]] = None
    core_anchor_status: Optional[Mapping[str, Any]] = None
    try:
        core_anchor_status = _wrapper_core_anchor_status(
            root, core_identity_before,
        )
        if not core_anchor_status["matches_live_core"]:
            raise GenerationError("wrapper_core_source_anchor_mismatch")
        unused_inventory, identity_collisions = _evidence_identity_inventory(
            core, root,
        )
        if identity_collisions:
            raise GenerationError("evidence_identity_collision")
        canonical_path = _output_path(root, core.CANONICAL_RELATIVE_PATH)
        report_path = _output_path(root, core.REPORT_RELATIVE_PATH)
        index_path = _output_path(root, core.INDEX_RELATIVE_PATH)
        source_roles_before = core.collect_source_role_bindings(root)
        frozen_mismatches = _frozen_source_mismatches(
            core, source_roles_before)
        if frozen_mismatches:
            raise GenerationError(
                "frozen_source_identity_mismatch:"
                + ",".join(frozen_mismatches)
            )
        host_tree_before = core.collect_host_perception_package_tree(root)
        overlay_before = core.collect_live_overlay_binding(root)
        logical, physical, composites, interpreters, wsl_identity = (
            _run_execution_matrix(core, root, source_roles_before)
        )
        observations = _production_observations(
            core, root, source_roles_before, physical, interpreters,
            wsl_identity,
        )
        source_roles_after = core.collect_source_role_bindings(root)
        host_tree_after = core.collect_host_perception_package_tree(root)
        overlay_after = core.collect_live_overlay_binding(root)
        core_identity_after = core.source_artifact_identity(
            root, "workspace", CORE_RELATIVE_PATH)
        if (
            source_roles_after != source_roles_before
            or host_tree_after != host_tree_before
            or overlay_after != overlay_before
            or core_identity_after != core_identity_before
        ):
            raise GenerationError("generation_source_closure_drift")
        canonical = core.build_canonical_payload(root, source_roles_after)
        if canonical["live_overlay_binding"] != overlay_after:
            raise GenerationError("canonical_overlay_recompute_mismatch")
        canonical_identity = core.write_json_exclusive(
            canonical_path, canonical, core.CANONICAL_RELATIVE_PATH,
        )
        report = core.build_report_payload(
            root, canonical_identity, source_roles_after, logical, physical,
            composites, observations,
        )
        report_identity = core.write_json_exclusive(
            report_path, report, core.REPORT_RELATIVE_PATH,
        )
        index = core.build_index_payload(
            report_identity, canonical_identity, source_roles_after,
        )
        semantic = core.validate_formal_admission_evidence_authority_v6(
            root, index)
        if (
            not semantic.get("semantic_validated_pass")
            or semantic.get("failures")
        ):
            raise GenerationError(
                "in_memory_index_semantic_validation_failed:"
                + ",".join(semantic.get("failures", [])))

        # Every live-source and semantic check is complete before the index
        # commit boundary.  A canonical/report pair can never select itself.
        if (
            core.collect_source_role_bindings(root) != source_roles_after
            or core.collect_host_perception_package_tree(root)
            != host_tree_after
            or core.collect_live_overlay_binding(root) != overlay_after
            or core.source_artifact_identity(
                root, "workspace", CORE_RELATIVE_PATH)
            != core_identity_after
        ):
            raise GenerationError(
                "generation_source_closure_drift_before_index_commit")
        for output_role, output_relative, expected_identity in (
            ("canonical", core.CANONICAL_RELATIVE_PATH, canonical_identity),
            ("report", core.REPORT_RELATIVE_PATH, report_identity),
        ):
            live_identity, unused_raw = core._read_regular_identity(
                root, "workspace", output_relative,
            )
            if {
                key: live_identity[key]
                for key in ("path", "size_bytes", "sha256")
            } != {
                key: expected_identity[key]
                for key in ("path", "size_bytes", "sha256")
            }:
                raise GenerationError(
                    "generation_output_identity_drift_before_index_commit:"
                    + output_role
                )
        index_identity = core.write_json_exclusive(
            index_path, index, core.INDEX_RELATIVE_PATH,
        )
        index_write_completed = True

        # Exact, independently reopened index bytes are the durable commit
        # record.  This is intentionally stronger and restart-stable compared
        # with remembering whether this process observed a Python return from
        # the writer.  Selection remains a separate wrapper-anchor decision.
        committed_state = _current_generation_output_state(
            core, root, core_identity_after)
        if committed_state.get("generation_status") not in {
            GENERATION_STATUS_COMMITTED_UNSELECTED,
            GENERATION_STATUS_SELECTED_BLOCKED_OFFLINE,
        }:
            wrapper_failures = _selection_failures_from_wrapper_status(
                core_anchor_status, index_identity,
            )
            committed_state = _generation_status_result(
                core, GENERATION_STATUS_COMMITTED_UNSELECTED,
                artifact_identities={
                    "canonical": canonical_identity,
                    "report": report_identity,
                    "index": index_identity,
                },
                failures=(
                    list(committed_state.get("failures", []))
                    + ["generation_post_commit_candidate_validation_failed"]
                    + wrapper_failures
                ),
            )
        logical_total = sum(item["collected"] for item in logical)
        physical_collected = sum(item["collected"] for item in physical)
        physical_passed = sum(item["passed"] for item in physical)
        physical_skipped = sum(item["skipped"] for item in physical)
        result = dict(committed_state)
        result.update({
            "canonical": canonical_identity,
            "report": report_identity,
            "index": index_identity,
            "logical": {
                "passed": logical_total, "failed": 0, "skipped": 0,
            },
            "physical": {
                "collected": physical_collected,
                "passed": physical_passed,
                "failed": 0,
                "skipped": physical_skipped,
                "effective_passed_after_exact_composite": physical_collected,
            },
            "production_cli_observations": [
                {
                    "observation_id": item["observation_id"],
                    "execution_attempted": item["execution_attempted"],
                    "blocked_code": item["blocked_code"],
                }
                for item in observations
            ],
        })
        return result
    except Exception as error:
        try:
            observed = _current_generation_output_state(
                core, root, core_identity_before)
        except Exception as state_error:
            observed = _generation_status_result(
                core,
                (GENERATION_STATUS_ABANDONED_UNINDEXED
                 if any(os.path.lexists(str(_workspace_path(root, relative)))
                        for relative in (
                            core.CANONICAL_RELATIVE_PATH,
                            core.REPORT_RELATIVE_PATH,
                            core.INDEX_RELATIVE_PATH,
                        ))
                 else GENERATION_STATUS_FAILED_NO_ARTIFACTS),
                failures=[
                    "generation_exception:" + type(error).__name__ + ":"
                    + str(error),
                    "generation_state_recompute_exception:"
                    + type(state_error).__name__,
                ],
            )
        observed_committed = observed.get("generation_status") in {
            GENERATION_STATUS_COMMITTED_UNSELECTED,
            GENERATION_STATUS_SELECTED_BLOCKED_OFFLINE,
        }
        durable_commit_known = index_write_completed or observed_committed
        failures = list(observed.get("failures", [])) + [
            ("post_commit_generation_exception:"
             if durable_commit_known else "generation_exception:")
            + type(error).__name__ + ":" + str(error)
        ]
        if durable_commit_known:
            status = GENERATION_STATUS_COMMITTED_UNSELECTED
            failures.append(
                "generation_post_commit_candidate_validation_failed")
            if core_anchor_status is not None:
                known_index_identity = (
                    index_identity
                    or observed.get("artifact_identities", {}).get("index")
                    or {}
                )
                failures.extend(_selection_failures_from_wrapper_status(
                    core_anchor_status, known_index_identity,
                ))
        else:
            any_output = any(
                os.path.lexists(str(_workspace_path(root, relative)))
                for relative in (
                    core.CANONICAL_RELATIVE_PATH,
                    core.REPORT_RELATIVE_PATH,
                    core.INDEX_RELATIVE_PATH,
                )
            )
            status = (
                GENERATION_STATUS_ABANDONED_UNINDEXED
                if any_output else GENERATION_STATUS_FAILED_NO_ARTIFACTS
            )
            if os.path.lexists(str(_workspace_path(
                    root, core.INDEX_RELATIVE_PATH))):
                failures.append(
                    "generation_index_o_excl_commit_not_completed")
        return _generation_status_result(
            core, status,
            artifact_identities=observed.get("artifact_identities", {}),
            failures=failures,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or generate the v7 BLOCKED_OFFLINE authority generation.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--generate", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    options = _parser().parse_args(argv)
    try:
        root = _workspace_root()
        result = _plan(root) if options.plan else _generate(root)
    except Exception as error:
        marker = PLAN_MARKER if options.plan else GENERATED_MARKER
        sys.stdout.write(marker + json.dumps({
            "validated_pass": False,
            "failure": type(error).__name__ + ":" + str(error),
            "formal_consumer": False, "delivery_ready": False,
        }, ensure_ascii=False, sort_keys=True) + "\n")
        return 2
    marker = PLAN_MARKER if options.plan else GENERATED_MARKER
    sys.stdout.write(marker + json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    if options.plan and not result["ready_to_attempt_generation"]:
        return 3
    if not options.plan and result.get("generation_status") in {
        GENERATION_STATUS_PREPARED,
        GENERATION_STATUS_FAILED_NO_ARTIFACTS,
        GENERATION_STATUS_ABANDONED_UNINDEXED,
    }:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
