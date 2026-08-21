"""Generate the v6 runtime-root-closure BLOCKED_OFFLINE evidence generation.

The command is a Windows-host orchestrator.  It runs the document-demotion
suite with the bundled Windows Python and runs POSIX suites through ``wsl.exe
--cd`` using both ``/usr/bin/python3`` and ``/usr/bin/python3.14`` where the
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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PLAN_MARKER = "ROS1_RUNTIME_ROOT_CLOSURE_BLOCKED_OFFLINE_PLAN "
GENERATED_MARKER = "ROS1_RUNTIME_ROOT_CLOSURE_BLOCKED_OFFLINE_GENERATED "
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
CORE_RELATIVE_PATH = "audit_tools/formal_admission_evidence_authority_v5_core.py"
WRAPPER_RELATIVE_PATH = "audit_tools/formal_admission_evidence_authority_v5.py"


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
    name = "_ros1_runtime_root_closure_authority_v5_" + identity["sha256"]
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = "audit_tools"
    module.__spec__ = None
    previous = sys.modules.get(name)
    try:
        sys.modules[name] = module
        exec(compile(raw, str(path), "exec", dont_inherit=True, optimize=0), module.__dict__)
    except BaseException as error:
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
        "validate_formal_admission_evidence_authority_v5",
        "load_and_resolve_formal_admission_evidence_authority_v5",
        "write_json_exclusive",
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
    except (SyntaxError, TypeError, ValueError) as error:
        raise GenerationError("wrapper_core_anchor_parse_failed") from error
    if len(values) != 1:
        raise GenerationError("wrapper_core_anchor_assignment_count_invalid")
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
    }


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
    argv = [str(wsl_path), "--cd", wsl_root, "--exec", *child]
    return argv, _outer_windows_environment(), str(root), dict(INNER_ENVIRONMENT)


def _run_execution_matrix(
    core: Any, root: Path, source_roles: Sequence[Mapping[str, Any]],
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Mapping[str, Any]], Mapping[str, Any]]:
    suites = {item["suite_id"]: item for item in core.suite_inventory(root)}
    sources = _source_by_key(source_roles)
    wsl_path, wsl_identity = _find_wsl()
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
        })
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
) -> Mapping[str, Any]:
    sources = _source_by_key(source_roles)
    source_before = core.source_artifact_identity(
        root, "workspace", expectation["source_path"],
    )
    wsl_root = _execution_workspace_path(root)
    child = [
        "/usr/bin/env", "-i",
        *[key + "=" + value for key, value in sorted(INNER_ENVIRONMENT.items())],
        "/usr/bin/python3.14", "-I", "-S", "-B",
        str(PurePosixPath(wsl_root, expectation["source_path"])),
    ]
    argv = [str(wsl_path), "--cd", wsl_root, "--exec", *child]
    completed = subprocess.run(
        argv, cwd=str(root), env=_outer_windows_environment(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=COMMAND_TIMEOUT_SECONDS, close_fds=True,
    )
    source_after = core.source_artifact_identity(
        root, "workspace", expectation["source_path"],
    )
    if source_before != source_after or completed.returncode != expectation["exit_code"]:
        raise GenerationError("production_cli_identity_or_exit_mismatch:" + expectation["observation_id"])
    marker_prefix = (
        "ROS1_CAMERA_RUNTIME_IMPORT_PROBE "
        if expectation["observation_id"] == "runtime_import_probe_unbound"
        else "ROS1_CAMERA_RUNTIME_INSTALL_ADMISSION "
    )
    payload, unused_raw = _parse_single_marker(completed.stdout, marker_prefix)
    failures = payload.get("failures")
    if failures != [expectation["blocked_code"]]:
        raise GenerationError("production_cli_blocked_code_mismatch:" + expectation["observation_id"])
    if payload.get("validated_pass") is not False or payload.get("delivery_ready") is not False:
        raise GenerationError("production_cli_fail_closed_flags_invalid")
    identity = _source_identity(sources, "workspace", expectation["source_path"])
    return {
        "observation_id": expectation["observation_id"],
        "source_identity_before": identity, "source_identity_after": identity,
        "interpreter_identity": interpreter_identity,
        "orchestrator_identity": wsl_identity,
        "argv": list(argv),
        "argv_sha256": _canonical_sha256(argv),
        "environment": dict(INNER_ENVIRONMENT),
        "environment_sha256": _canonical_sha256(INNER_ENVIRONMENT),
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
        supporting_records = [
            item for item in physical
            if item["suite_id"] == "camera_only_atomic_launcher"
            and supporting in item["passed_ids"]
        ]
        if len(supporting_records) != 2:
            raise GenerationError("atomic_static_supporting_test_not_dual_pass")
        sources = _source_by_key(source_roles)
        identity = _source_identity(sources, "workspace", expectation["source_path"])
        expected_stderr = (
            "ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
            + expectation["blocked_code"] + "\n"
        ).encode("utf-8")
        static_material = {
            "execution_attempted": False,
            "supporting_test_id": supporting,
            "supporting_record_ids": sorted(item["record_id"] for item in supporting_records),
            "blocked_code": expectation["blocked_code"],
        }
        observations.append({
            "observation_id": expectation["observation_id"],
            "source_identity_before": identity, "source_identity_after": identity,
            "interpreter_identity": None, "orchestrator_identity": None,
            "argv": ["NOT_EXECUTED_SAFETY_BOUNDARY"],
            "argv_sha256": _canonical_sha256(["NOT_EXECUTED_SAFETY_BOUNDARY"]),
            "environment": {},
            "environment_sha256": _canonical_sha256({}),
            "exit_code": expectation["exit_code"], "marker_count": 0,
            "blocked_code": expectation["blocked_code"],
            "failure_codes": [expectation["blocked_code"]],
            "stdout": _stream_identity(b""), "stderr": _stream_identity(expected_stderr),
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
    collisions: List[Mapping[str, str]] = []
    for path in sorted(evidence_root.rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        try:
            identity, raw = core._read_regular_identity(
                root, "workspace", relative,
            )
            payload = _strict_json(raw)
        except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise GenerationError(
                "evidence_inventory_unreadable:{}:{}".format(
                    relative, type(error).__name__,
                )
            ) from error
        identifiers: Dict[str, str] = {}
        if isinstance(payload, dict):
            for key in candidate_ids:
                value = payload.get(key)
                if value is None:
                    continue
                if not isinstance(value, str) or not value:
                    raise GenerationError(
                        "evidence_inventory_identity_invalid:{}:{}".format(
                            relative, key,
                        )
                    )
                identifiers[key] = value
                if value == candidate_ids[key]:
                    collisions.append({
                        "path": relative, "field": key, "value": value,
                    })
        inventory.append({
            **{
                key: identity[key]
                for key in ("root_role", "path", "size_bytes", "sha256")
            },
            "identifiers": identifiers,
        })
    return inventory, sorted(
        collisions, key=lambda item: (item["path"], item["field"]),
    )


def _plan(root: Path) -> Mapping[str, Any]:
    core, core_identity = _load_core(root)
    core_anchor_status = _wrapper_core_anchor_status(root, core_identity)
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
        "schema_version": "ros1_runtime_root_closure_blocked_offline_plan/v2",
        "generation_id": core.GENERATION_ID,
        "index_instance_id": core.INDEX_INSTANCE_ID,
        "predecessor": dict(core.PREDECESSOR_INDEX_IDENTITY),
        "canonical_output": core.CANONICAL_RELATIVE_PATH,
        "report_output": core.REPORT_RELATIVE_PATH,
        "index_output": core.INDEX_RELATIVE_PATH,
        "core_identity": dict(core_identity),
        "wrapper_core_anchor_status": core_anchor_status,
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
    frozen_mismatches = _frozen_source_mismatches(core, source_roles_before)
    if frozen_mismatches:
        raise GenerationError(
            "frozen_source_identity_mismatch:" + ",".join(frozen_mismatches)
        )
    host_tree_before = core.collect_host_perception_package_tree(root)
    overlay_before = core.collect_live_overlay_binding(root)
    logical, physical, composites, interpreters, wsl_identity = (
        _run_execution_matrix(core, root, source_roles_before)
    )
    observations = _production_observations(
        core, root, source_roles_before, physical, interpreters, wsl_identity,
    )
    source_roles_after = core.collect_source_role_bindings(root)
    host_tree_after = core.collect_host_perception_package_tree(root)
    overlay_after = core.collect_live_overlay_binding(root)
    core_identity_after = core.source_artifact_identity(root, "workspace", CORE_RELATIVE_PATH)
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
    semantic = core.validate_formal_admission_evidence_authority_v5(root, index)
    if not semantic.get("semantic_validated_pass") or semantic.get("failures"):
        raise GenerationError("in_memory_index_semantic_validation_failed:" + ",".join(semantic.get("failures", [])))
    # Index is last: no validation failure before this point can select a
    # partial canonical/report pair.
    index_identity = core.write_json_exclusive(
        index_path, index, core.INDEX_RELATIVE_PATH,
    )
    resolved = core.load_and_resolve_formal_admission_evidence_authority_v5(
        root, index_identity,
    )
    if (
        not resolved.get("validated_pass")
        or not resolved.get("accepted_as_offline_release_selection_authority")
        or resolved.get("accepted_by_formal_field_evidence_consumer")
        or resolved.get("delivery_ready") or resolved.get("failures")
    ):
        raise GenerationError("fresh_resolver_validation_failed")
    if (
        core.collect_source_role_bindings(root) != source_roles_after
        or core.collect_host_perception_package_tree(root) != host_tree_after
        or core.collect_live_overlay_binding(root) != overlay_after
    ):
        raise GenerationError("generation_source_closure_drift_after_output")
    logical_total = sum(item["collected"] for item in logical)
    physical_collected = sum(item["collected"] for item in physical)
    physical_passed = sum(item["passed"] for item in physical)
    physical_skipped = sum(item["skipped"] for item in physical)
    return {
        "generation_id": core.GENERATION_ID,
        "canonical": canonical_identity, "report": report_identity,
        "index": index_identity,
        "logical": {"passed": logical_total, "failed": 0, "skipped": 0},
        "physical": {
            "collected": physical_collected, "passed": physical_passed,
            "failed": 0, "skipped": physical_skipped,
            "effective_passed_after_exact_composite": physical_collected,
        },
        "production_cli_observations": [
            {"observation_id": item["observation_id"], "execution_attempted": item["execution_attempted"], "blocked_code": item["blocked_code"]}
            for item in observations
        ],
        "resolver_validated_pass": True,
        "accepted_as_offline_release_selection_authority": True,
        "formal_denominator": 0, "formal_consumer": False,
        "delivery_ready": False, "authorizes_field_delivery": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or generate the v6 BLOCKED_OFFLINE authority generation.",
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
    except (GenerationError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
