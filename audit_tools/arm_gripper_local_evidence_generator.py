#!/usr/bin/env python3
"""Host-owned producer for local arm/gripper evidence staging.

The producer has no caller-selected suite, target, runner, source, or output
file.  It accepts only an aggregator reservation below the fixed staging root,
runs the policy's exact 23-target authority, and writes raw local materials.
It never imports ROS or a vendor backend and never grants field readiness.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELATIVE_PATH = "audit_tools/arm_gripper_local_v3_policy.json"
GENERATOR_RELATIVE_PATH = "audit_tools/arm_gripper_local_evidence_generator.py"
STAGING_ROOT_RELATIVE_PATH = ".arm_gripper_local_evidence_staging"
RESERVATION_NAME = ".reservation.json"
MANIFEST_NAME = "generation_manifest.json"
RAW_DIRECTORY = "raw"
SUITE_DIRECTORY = "suites"
GENERATOR_MARKER = "ARM_GRIPPER_LOCAL_EVIDENCE_GENERATOR_RESULT "
CURRENT_STATUS = "CURRENT_LOCAL_OFFLINE_EVIDENCE"
EXECUTION_COMPONENT_BINDING_SCHEMA = (
    "host_owned_execution_component_bootstrap/v1")
EXECUTION_COMPONENT_KIND = "arm_gripper_local_evidence_generator_v2"
EXECUTION_COMPONENT_BINDING_KEYS = frozenset({
    "schema_version", "component_kind", "path", "size_bytes", "sha256",
    "bootstrap_sha256",
})

# The parent process executes each fixed runner from bytes read through one
# O_NOFOLLOW file descriptor.  The SHA check happens before compile/exec, so a
# path-level X->Y->X replacement cannot substitute different executed bytes.
SAME_FD_BOOTSTRAP = """\
import hashlib, os, stat, sys
path = sys.argv[1]
expected = sys.argv[2]
flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
descriptor = os.open(path, flags)
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_nlink', 1) != 1:
        raise RuntimeError('bootstrap_runner_not_exclusive_regular')
    chunks = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    source = b''.join(chunks)
    after = os.fstat(descriptor)
finally:
    os.close(descriptor)
if (before.st_dev, before.st_ino, before.st_size, getattr(before, 'st_mtime_ns', None)) != (after.st_dev, after.st_ino, after.st_size, getattr(after, 'st_mtime_ns', None)):
    raise RuntimeError('bootstrap_runner_changed_while_open')
actual = hashlib.sha256(source).hexdigest()
if actual != expected:
    raise RuntimeError('bootstrap_runner_sha256_mismatch')
arguments = sys.argv[3:]
sys.argv = [path] + arguments
namespace = {'__name__': '__main__', '__file__': path, '__package__': None,
             '__cached__': None, '__spec__': None,
             '__limo_executed_source_sha256__': actual}
exec(compile(source, path, 'exec', dont_inherit=True), namespace, namespace)
"""

POLICY_SCHEMA_ID = "limo.arm_gripper_local_evidence_policy"
POLICY_SCHEMA_VERSION = 2
RESERVATION_SCHEMA_ID = "limo.arm_gripper_local_evidence_reservation"
RESERVATION_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_ID = "limo.arm_gripper_local_evidence_generation_manifest"
MANIFEST_SCHEMA_VERSION = 2
SUITE_SCHEMA_ID = "limo.arm_gripper_local_evidence_suite_result"
SUITE_SCHEMA_VERSION = 2
SOURCE_SCHEMA_ID = "limo.arm_gripper_local_source_identity"
SOURCE_SCHEMA_VERSION = 2

POLICY_KEYS = frozenset({
    "schema_id", "schema_version", "evidence_status",
    "native_line_ending_hex", "generation_manifest_schema",
    "generation_manifest_keys", "suite_schema", "suite_keys",
    "staging_paths", "source_closure", "source_closure_sha256",
    "suite_authority", "producer_contract", "aggregator_contract",
    "policy_payload_sha256",
})
SUITE_AUTHORITY_KEYS = frozenset({
    "suite_id", "required", "execution_scope", "targets",
    "expected_denominator", "expected_skips",
})
TARGET_AUTHORITY_KEYS = frozenset({
    "record_id", "path", "disposition", "execution_kind", "runner",
    "import_roots", "case_ids", "case_map_sha256", "denominator",
})
RUNNER_KEYS = frozenset({
    "path", "schema", "kind", "mode", "marker_prefix",
    "case_results_schema", "source_sha256",
})
RESERVATION_KEYS = frozenset({
    "schema_id", "schema_version", "state", "authority_policy_sha256",
    "generation_name", "producer_path", "reservation_token_sha256",
})
MANIFEST_KEYS = frozenset({
    "schema_id", "schema_version", "evidence_status",
    "authority_policy_sha256", "reservation_token_sha256",
    "producer_identity", "interpreter_identity_before",
    "interpreter_identity_after", "source_identity_before",
    "source_identity_after", "suite_files", "raw_inventory", "totals",
    "result", "generation_sha256",
})
SUITE_KEYS = frozenset({
    "schema_id", "schema_version", "suite_id", "required",
    "execution_scope", "authority_sha256", "targets", "case_results",
    "totals", "result", "suite_sha256",
})
TARGET_RECORD_KEYS = frozenset({
    "record_id", "path", "disposition", "execution_kind", "runner",
    "import_roots", "expected_ids", "discovered_ids", "case_results",
    "target_identity_before", "target_identity_after",
    "runner_identity_before", "runner_identity_after",
    "interpreter_identity_before", "interpreter_identity_after",
    "raw_stdout", "raw_stderr", "raw_rc", "returncode",
    "payload_sha256", "result",
})

UNITTEST_RUNNER = "audit_tools/run_unittest_file_tests.py"
PYTEST_RUNNER = "audit_tools/run_pytest_style_tests.py"
STATIC_RUNNER = "audit_tools/arm_gripper_local_static_audit.py"
FIXED_RUNNERS = {
    "UNITTEST_FILE": UNITTEST_RUNNER,
    "PYTEST_STYLE_FILE": PYTEST_RUNNER,
    "STATIC_AUDIT_JSON": STATIC_RUNNER,
}
ROS_SMOKE_PATHS = frozenset({
    "src/limo_cleanup_executor/test/test_arm_gateway_ros_smoke.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_ros_smoke.py",
})
FIXED_TARGET_PATHS = frozenset({
    "audit_tools/arm_gripper_local_static_audit.py",
    "audit_tools/test_arm_gripper_local_evidence_aggregator.py",
    "audit_tools/test_arm_gripper_local_evidence_generator.py",
    "src/limo_cleanup_executor/test/test_arm_backends.py",
    "src/limo_cleanup_executor/test/test_arm_gateway_callback_contract.py",
    "src/limo_cleanup_executor/test/test_arm_gateway_core.py",
    "src/limo_cleanup_executor/test/test_arm_gateway_ros_contract.py",
    "src/limo_cleanup_executor/test/test_arm_gateway_ros_smoke.py",
    "src/limo_cleanup_executor/test/test_arm_gripper_field_acceptance.py",
    "src/limo_cleanup_executor/test/test_arm_gripper_ros1_noetic_contract.py",
    "src/limo_cleanup_executor/test/test_arm_gripper_static_safety.py",
    "src/limo_cleanup_executor/test/test_arm_motion_release_manifest.py",
    "src/limo_cleanup_executor/test/test_arm_safety_latch.py",
    "src/limo_cleanup_executor/test/test_final_gripper_release_manifest.py",
    "src/limo_cleanup_executor/test/test_gripper_backends.py",
    "src/limo_cleanup_executor/test/test_gripper_core.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_callback_contract.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_core.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_ros_contract.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_ros_smoke.py",
    "src/limo_cleanup_executor/test/test_gripper_interface_contract.py",
    "src/limo_cleanup_executor/test/test_gripper_safety_latch.py",
    "src/limo_cleanup_executor/test/test_gripper_source_safety.py",
})

_GENERATION_RE = re.compile(r"^generation-[0-9a-f]{32}$")
_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_RECORD_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,79}$")


class GenerationRejected(ValueError):
    """Raised for any authority, reservation, execution, or identity drift."""


def canonical_json_bytes(value):
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _self_hash(value, key):
    payload = dict(value)
    payload.pop(key, None)
    return canonical_sha256(payload)


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise GenerationRejected("duplicate_json_key:" + key)
        value[key] = item
    return value


def _nonfinite(value):
    raise GenerationRejected("nonfinite_json_number:" + value)


def strict_json_loads(raw, label):
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except GenerationRejected:
        raise
    except (UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GenerationRejected(label + "_invalid_json") from error


def _canonical_relative(value, label):
    if not isinstance(value, str) or not value or "\\" in value:
        raise GenerationRejected(label + "_not_canonical_relative")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value
            or any(part in ("", ".", "..") for part in path.parts)):
        raise GenerationRejected(label + "_not_canonical_relative")
    return value


def _is_linklike(path, info):
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    is_junction = getattr(os.path, "isjunction", lambda unused: False)
    return bool(
        stat.S_ISLNK(info.st_mode)
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        or is_junction(str(path)))


def _file_identity(path, relative=None):
    before = os.lstat(str(path))
    if (_is_linklike(path, before) or not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_nlink", 1) != 1):
        raise GenerationRejected("file_not_exclusive_regular:" + str(path))
    raw = path.read_bytes()
    after = os.lstat(str(path))
    projection = lambda item: (
        item.st_dev, item.st_ino, item.st_mode, item.st_size,
        getattr(item, "st_mtime_ns", None), getattr(item, "st_ctime_ns", None),
        getattr(item, "st_nlink", 1),
        getattr(item, "st_file_attributes", None),
    )
    if projection(before) != projection(after) or len(raw) != before.st_size:
        raise GenerationRejected("file_changed_during_read:" + str(path))
    result = {
        "path": relative if relative is not None else str(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return raw, result


def _workspace_file(relative):
    relative = _canonical_relative(relative, "workspace_path")
    current = WORKSPACE_ROOT
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        info = os.lstat(str(current))
        if _is_linklike(current, info) or not stat.S_ISDIR(info.st_mode):
            raise GenerationRejected("workspace_parent_invalid:" + relative)
    path = current / PurePosixPath(relative).parts[-1]
    return path, _file_identity(path, relative)


def _write_exclusive(path, raw):
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(str(path), flags, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    relative = path.relative_to(path.parents[1]).as_posix()
    unused, identity = _file_identity(path, relative)
    return identity


def _load_policy():
    unused_path, pair = _workspace_file(POLICY_RELATIVE_PATH)
    raw, identity = pair
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise GenerationRejected("policy_fixed_lf_invalid")
    policy = strict_json_loads(raw, "policy")
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise GenerationRejected("policy_keys_invalid")
    if (policy["schema_id"] != POLICY_SCHEMA_ID
            or policy["schema_version"] != POLICY_SCHEMA_VERSION
            or policy["evidence_status"] != CURRENT_STATUS
            or policy["native_line_ending_hex"] != "0a"):
        raise GenerationRejected("policy_header_invalid")
    payload = dict(policy)
    declared = payload.pop("policy_payload_sha256", None)
    if declared != canonical_sha256(payload):
        raise GenerationRejected("policy_payload_sha256_mismatch")
    _validate_policy_authority(policy)
    return policy, identity


def _validate_policy_authority(policy):
    closure = policy["source_closure"]
    if (not isinstance(closure, list) or not closure
            or closure != sorted(set(closure))
            or any(_canonical_relative(item, "source_closure") != item
                   for item in closure)
            or policy["source_closure_sha256"] != canonical_sha256(closure)):
        raise GenerationRejected("policy_source_closure_invalid")
    suites = policy["suite_authority"]
    if not isinstance(suites, list) or len(suites) != 4:
        raise GenerationRejected("policy_suite_count_invalid")
    if [item.get("suite_id") for item in suites] != sorted(
            item.get("suite_id") for item in suites):
        raise GenerationRejected("policy_suite_order_invalid")
    target_paths = []
    record_ids = []
    for suite in suites:
        if not isinstance(suite, dict) or set(suite) != SUITE_AUTHORITY_KEYS:
            raise GenerationRejected("policy_suite_keys_invalid")
        if suite["required"] is not True or not isinstance(suite["targets"], list):
            raise GenerationRejected("policy_suite_required_invalid")
        suite_cases = []
        for target in suite["targets"]:
            if not isinstance(target, dict) or set(target) != TARGET_AUTHORITY_KEYS:
                raise GenerationRejected("policy_target_keys_invalid")
            path = _canonical_relative(target["path"], "target_path")
            record_id = target["record_id"]
            if not isinstance(record_id, str) or not _RECORD_RE.fullmatch(record_id):
                raise GenerationRejected("policy_record_id_invalid")
            if path not in closure:
                raise GenerationRejected("policy_target_outside_closure")
            cases = target["case_ids"]
            if (not isinstance(cases, list) or not cases
                    or len(cases) != len(set(cases))
                    or any(not item.startswith(path + "::") for item in cases)
                    or target["denominator"] != len(cases)
                    or target["case_map_sha256"] != canonical_sha256(cases)):
                raise GenerationRejected("policy_case_map_invalid")
            kind = target["execution_kind"]
            runner = target["runner"]
            if kind == "NOT_EXECUTED_ROS_GRAPH_PROHIBITED":
                if path not in ROS_SMOKE_PATHS or runner is not None:
                    raise GenerationRejected("policy_nonexecuted_target_invalid")
            else:
                expected_runner = FIXED_RUNNERS.get(kind)
                if expected_runner is None or not isinstance(runner, dict):
                    raise GenerationRejected("policy_runner_kind_invalid")
                if set(runner) != RUNNER_KEYS or runner["path"] != expected_runner:
                    raise GenerationRejected("policy_runner_path_invalid")
                unused, runner_identity = _workspace_file(expected_runner)
                if runner["source_sha256"] != runner_identity[1]["sha256"]:
                    raise GenerationRejected("policy_runner_sha256_mismatch")
            target_paths.append(path)
            record_ids.append(record_id)
            suite_cases.extend(cases)
        if suite["expected_denominator"] != len(suite_cases):
            raise GenerationRejected("policy_suite_denominator_invalid")
    if (len(target_paths) != 23 or frozenset(target_paths) != FIXED_TARGET_PATHS
            or len(record_ids) != len(set(record_ids))):
        raise GenerationRejected("policy_exact_target_authority_invalid")


def _build_source_identity(policy, policy_sha256):
    files = []
    for relative in policy["source_closure"]:
        unused, pair = _workspace_file(relative)
        files.append(pair[1])
    result = {
        "schema_id": SOURCE_SCHEMA_ID,
        "schema_version": SOURCE_SCHEMA_VERSION,
        "authority_policy_sha256": policy_sha256,
        "files": files,
    }
    result["manifest_sha256"] = canonical_sha256(result)
    return result


def _interpreter_identity():
    raw, identity = _file_identity(Path(sys.executable))
    identity.update({
        "version": [sys.version_info.major, sys.version_info.minor,
                    sys.version_info.micro],
        "implementation": sys.implementation.name,
        "isolated": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "no_user_site": bool(sys.flags.no_user_site),
        "dont_write_bytecode": bool(sys.dont_write_bytecode),
    })
    if not raw:
        raise GenerationRejected("interpreter_empty")
    return identity


def _validate_process_contract(flags=None, environment=None):
    active_flags = sys.flags if flags is None else flags
    active_environment = os.environ if environment is None else environment
    if (not bool(getattr(active_flags, "isolated", False))
            or not bool(getattr(active_flags, "no_site", False))
            or not bool(getattr(active_flags, "no_user_site", False))
            or not bool(getattr(active_flags, "dont_write_bytecode", False))):
        raise GenerationRejected("generator_requires_python_I_S_B")
    forbidden = sorted(
        key for key in ("PYTHONHOME", "PYTHONPATH")
        if key in active_environment)
    if forbidden:
        raise GenerationRejected(
            "generator_environment_contaminated:" + ",".join(forbidden))


def _validate_execution_component_binding(policy, binding=None):
    """Require the aggregator's same-FD generator execution attestation."""
    active = (globals().get("__execution_component_binding__")
              if binding is None else binding)
    if not isinstance(active, dict) or set(active) != (
            EXECUTION_COMPONENT_BINDING_KEYS):
        raise GenerationRejected("generator_execution_binding_invalid")
    unused, pair = _workspace_file(GENERATOR_RELATIVE_PATH)
    identity = pair[1]
    producer_contract = policy.get("producer_contract")
    expected_bootstrap = (
        producer_contract.get("bootstrap_sha256")
        if isinstance(producer_contract, dict) else None)
    if (active["schema_version"] != EXECUTION_COMPONENT_BINDING_SCHEMA
            or active["component_kind"] != EXECUTION_COMPONENT_KIND
            or active["path"] != GENERATOR_RELATIVE_PATH
            or active["size_bytes"] != identity["size_bytes"]
            or active["sha256"] != identity["sha256"]
            or not isinstance(expected_bootstrap, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_bootstrap)
            or active["bootstrap_sha256"] != expected_bootstrap):
        raise GenerationRejected("generator_execution_binding_mismatch")
    return identity


def _load_reservation(staging_dir, token, policy_sha256):
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        raise GenerationRejected("reservation_token_format_invalid")
    root = WORKSPACE_ROOT / STAGING_ROOT_RELATIVE_PATH
    root_info = os.lstat(str(root))
    if _is_linklike(root, root_info) or not stat.S_ISDIR(root_info.st_mode):
        raise GenerationRejected("staging_root_invalid")
    candidate = Path(staging_dir)
    if not candidate.is_absolute():
        raise GenerationRejected("staging_dir_must_be_absolute")
    candidate = candidate.resolve(strict=True)
    if candidate.parent != root.resolve(strict=True):
        raise GenerationRejected("staging_dir_outside_fixed_root")
    if not _GENERATION_RE.fullmatch(candidate.name):
        raise GenerationRejected("generation_name_invalid")
    info = os.lstat(str(candidate))
    if _is_linklike(candidate, info) or not stat.S_ISDIR(info.st_mode):
        raise GenerationRejected("generation_dir_invalid")
    if sorted(item.name for item in candidate.iterdir()) != [RESERVATION_NAME]:
        raise GenerationRejected("generation_dir_not_empty_reserved")
    raw, unused_identity = _file_identity(candidate / RESERVATION_NAME)
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise GenerationRejected("reservation_fixed_lf_invalid")
    reservation = strict_json_loads(raw, "reservation")
    token_sha256 = hashlib.sha256(bytes.fromhex(token)).hexdigest()
    if (not isinstance(reservation, dict) or set(reservation) != RESERVATION_KEYS
            or reservation["schema_id"] != RESERVATION_SCHEMA_ID
            or reservation["schema_version"] != RESERVATION_SCHEMA_VERSION
            or reservation["state"] != "RESERVED_FOR_PRODUCER"
            or reservation["authority_policy_sha256"] != policy_sha256
            or reservation["generation_name"] != candidate.name
            or reservation["producer_path"] != GENERATOR_RELATIVE_PATH
            or reservation["reservation_token_sha256"] != token_sha256):
        raise GenerationRejected("reservation_binding_invalid")
    return candidate, token_sha256


def _child_environment():
    if os.name == "nt":
        allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}
        return {key: value for key, value in os.environ.items()
                if key.upper() in allowed}
    return {
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
    }


def _parse_marker(raw, prefix):
    marker = prefix.encode("ascii")
    if b"\r" in raw or raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        raise GenerationRejected("runner_stdout_line_contract_invalid")
    payload_raw = raw[:-1]
    if not payload_raw.startswith(marker):
        raise GenerationRejected("runner_marker_mismatch")
    encoded = payload_raw[len(marker):]
    payload = strict_json_loads(encoded, "runner_payload")
    if canonical_json_bytes(payload) != encoded:
        raise GenerationRejected("runner_payload_not_canonical")
    return payload, hashlib.sha256(encoded).hexdigest()


def _run_process(command, timeout_seconds):
    try:
        completed = subprocess.run(
            command, cwd=str(WORKSPACE_ROOT), env=_child_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout_seconds, check=False,
            close_fds=True)
        return completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as error:
        raise GenerationRejected("runner_timeout") from error


def _fixed_runner_command(target, runner):
    """Build the only allowed same-FD runner bootstrap command."""
    runner_path = runner["path"]
    command = [
        sys.executable, "-I", "-S", "-B", "-c", SAME_FD_BOOTSTRAP,
        str(WORKSPACE_ROOT / runner_path), runner["source_sha256"],
    ]
    if target["execution_kind"] == "STATIC_AUDIT_JSON":
        command.extend(("--workspace", str(WORKSPACE_ROOT)))
        return command
    if target["execution_kind"] == "PYTEST_STYLE_FILE":
        command.append("--single-file")
    command.extend(("--workspace", str(WORKSPACE_ROOT),
                    "--target", target["path"]))
    for root in target["import_roots"]:
        command.extend(("--import-root", root))
    for test_id in target["case_ids"]:
        command.extend(("--expected-id", test_id))
    return command


def _identity_core(value):
    if not isinstance(value, dict):
        raise GenerationRejected("runner_identity_not_object")
    keys = ("path", "size_bytes", "sha256")
    if any(key not in value for key in keys):
        raise GenerationRejected("runner_identity_core_missing")
    return {key: value[key] for key in keys}


def _source_identity_map(source_identity):
    files = source_identity.get("files") if isinstance(source_identity, dict) else None
    if not isinstance(files, list):
        raise GenerationRejected("source_identity_files_invalid")
    result = {}
    for item in files:
        core = _identity_core(item)
        if core["path"] in result:
            raise GenerationRejected("source_identity_duplicate_path")
        result[core["path"]] = core
    return result


def _validate_runner_loaded_bytes(
        payload, target_path, target_identity, runner_path, runner_identity,
        source_identity):
    """Bind actual loader-returned target/dependency bytes to the source set."""
    source_map = _source_identity_map(source_identity)
    if target_path not in source_map or runner_path not in source_map:
        raise GenerationRejected("runner_or_target_outside_source_identity")
    if _identity_core(target_identity) != source_map[target_path]:
        raise GenerationRejected("target_identity_not_source_bound")
    if _identity_core(runner_identity) != source_map[runner_path]:
        raise GenerationRejected("runner_identity_not_source_bound")

    for key in ("runner_identity_before", "runner_identity_after"):
        if _identity_core(payload.get(key)) != _identity_core(runner_identity):
            raise GenerationRejected("runner_reported_identity_mismatch")
    if payload.get("path") != target_path:
        raise GenerationRejected("runner_reported_target_path_mismatch")
    if payload.get("sha256") != target_identity["sha256"]:
        raise GenerationRejected("runner_reported_target_sha256_mismatch")
    if (payload.get("workspace_loader_guard_restored") is not True
            or payload.get("workspace_pyc_inventory_stable") is not True
            or payload.get("workspace_pyc_bytes_read") != 0):
        raise GenerationRejected("runner_workspace_loader_contract_invalid")
    if runner_path == UNITTEST_RUNNER and (
            payload.get("environment_restored") is not True
            or payload.get("environment_unchanged_during_execution") is not True
            or _identity_core(payload.get("target_identity_before")) !=
            _identity_core(target_identity)
            or _identity_core(payload.get("target_identity_after")) !=
            _identity_core(target_identity)):
        raise GenerationRejected("unittest_environment_or_target_contract_invalid")

    raw_reads = payload.get("workspace_source_reads")
    if not isinstance(raw_reads, list) or not raw_reads:
        raise GenerationRejected("runner_workspace_source_reads_missing")
    reads = {}
    ordered_paths = []
    for item in raw_reads:
        core = _identity_core(item)
        path = core["path"]
        ordered_paths.append(path)
        if path in reads:
            raise GenerationRejected("runner_workspace_source_read_duplicate")
        expected = source_map.get(path)
        if expected is None or core != expected:
            raise GenerationRejected("runner_workspace_source_read_not_bound")
        reads[path] = core
    if ordered_paths != sorted(ordered_paths):
        raise GenerationRejected("runner_workspace_source_reads_not_sorted")
    if reads.get(target_path) != source_map[target_path]:
        raise GenerationRejected("target_executed_bytes_not_source_bound")


def _validate_static_scope(payload, source_identity):
    source_map = _source_identity_map(source_identity)
    scope = payload.get("scope") if isinstance(payload, dict) else None
    hashes = scope.get("sha256") if isinstance(scope, dict) else None
    expected = {path: item["sha256"] for path, item in source_map.items()}
    if hashes != expected or scope.get("files") != len(expected):
        raise GenerationRejected("static_audit_scope_not_exact_source_identity")


def _raw_material(generation_dir, record_id, stdout, stderr, returncode):
    raw_dir = generation_dir / RAW_DIRECTORY
    rc_raw = (str(returncode) + "\n").encode("ascii")
    identities = {}
    for suffix, value in (("stdout.bin", stdout), ("stderr.bin", stderr),
                          ("rc.txt", rc_raw)):
        filename = record_id + "." + suffix
        identity = _write_exclusive(raw_dir / filename, value)
        identity["path"] = RAW_DIRECTORY + "/" + filename
        identities[suffix] = identity
    return identities


def _expected_skip_map(suite):
    return {item["test_id"]: item["reason"] for item in suite["expected_skips"]}


def _validate_case_results(case_results, expected_ids, expected_skips):
    if (not isinstance(case_results, list)
            or [item.get("test_id") for item in case_results] != expected_ids):
        raise GenerationRejected("case_results_id_map_invalid")
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    for item in case_results:
        outcome = item.get("outcome")
        expected_reason = expected_skips.get(item.get("test_id"))
        expected_keys = {"test_id", "outcome"}
        if outcome != "passed":
            expected_keys.add("reason")
        if set(item) != expected_keys or outcome not in totals:
            raise GenerationRejected("case_result_schema_invalid")
        if expected_reason is None and outcome != "passed":
            raise GenerationRejected("unexpected_nonpass_case")
        if expected_reason is not None and (
                outcome != "skipped" or item.get("reason") != expected_reason):
            raise GenerationRejected("expected_skip_mismatch")
        totals[outcome] += 1
    return totals


def _ast_case_ids(path, target_relative):
    raw, unused_identity = _file_identity(path, target_relative)
    tree = ast.parse(raw.decode("utf-8"), filename=target_relative,
                     feature_version=(3, 8))
    classes = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = sorted(
            child.name for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name.startswith("test"))
        if methods:
            classes.append((node.name, methods))
    return [target_relative + "::" + class_name + "." + method
            for class_name, methods in sorted(classes) for method in methods]


def _target_record(
        generation_dir, suite, target, policy, source_identity):
    target_path = target["path"]
    target_file = WORKSPACE_ROOT / PurePosixPath(target_path)
    unused, before_pair = _workspace_file(target_path)
    before = before_pair[1]
    interpreter_before = _interpreter_identity()
    expected_ids = list(target["case_ids"])
    expected_skips = _expected_skip_map(suite)
    runner = target["runner"]
    raw_stdout = raw_stderr = raw_rc = None
    returncode = None
    payload_sha256 = None
    runner_before = runner_after = None

    if target["execution_kind"] == "NOT_EXECUTED_ROS_GRAPH_PROHIBITED":
        discovered_ids = _ast_case_ids(target_file, target_path)
        case_results = [{
            "test_id": test_id,
            "outcome": "skipped",
            "reason": expected_skips[test_id],
        } for test_id in expected_ids]
    else:
        runner_path = runner["path"]
        unused, runner_before_pair = _workspace_file(runner_path)
        runner_before = runner_before_pair[1]
        command = _fixed_runner_command(target, runner)
        stdout, stderr, returncode = _run_process(
            command, policy["producer_contract"]["runner_timeout_seconds"])
        materials = _raw_material(
            generation_dir, target["record_id"], stdout, stderr, returncode)
        raw_stdout = materials["stdout.bin"]
        raw_stderr = materials["stderr.bin"]
        raw_rc = materials["rc.txt"]
        if target["execution_kind"] == "STATIC_AUDIT_JSON":
            payload = strict_json_loads(stdout, "static_audit")
            payload_sha256 = hashlib.sha256(stdout).hexdigest()
            discovered_ids = expected_ids
            case_results = [{"test_id": expected_ids[0], "outcome": "passed"}]
            if (returncode != 0 or payload.get("passed") is not True
                    or payload.get("schema_id") !=
                    "limo.arm_gripper_local_static_audit"):
                raise GenerationRejected("static_audit_failed")
            _validate_static_scope(payload, source_identity)
        else:
            payload, payload_sha256 = _parse_marker(
                stdout, runner["marker_prefix"])
            discovered_ids = payload.get("discovered_ids")
            case_results = payload.get("case_results")
            if (returncode != 0 or payload.get("exit") != 0
                    or payload.get("result") not in ("PASS", "PASS_WITH_SKIPS")
                    or payload.get("schema_version") != runner["schema"]
                    or payload.get("runner_kind") != runner["kind"]
                    or payload.get("case_results_schema") !=
                    runner["case_results_schema"]
                    or payload.get("expected_ids") != expected_ids
                    or payload.get("executed_ids") != expected_ids):
                raise GenerationRejected("runner_result_contract_invalid")
            _validate_runner_loaded_bytes(
                payload, target_path, before, runner_path, runner_before,
                source_identity)
        unused, runner_after_pair = _workspace_file(runner_path)
        runner_after = runner_after_pair[1]
        if runner_before != runner_after:
            raise GenerationRejected("runner_identity_drift")

    if discovered_ids != expected_ids:
        raise GenerationRejected("discovered_ids_not_exact_expected")
    totals = _validate_case_results(case_results, expected_ids, expected_skips)
    unused, after_pair = _workspace_file(target_path)
    after = after_pair[1]
    interpreter_after = _interpreter_identity()
    if before != after:
        raise GenerationRejected("target_identity_drift")
    if interpreter_before != interpreter_after:
        raise GenerationRejected("interpreter_identity_drift")
    result = "PASS_WITH_SKIPS" if totals["skipped"] else "PASS"
    record = {
        "record_id": target["record_id"], "path": target_path,
        "disposition": target["disposition"],
        "execution_kind": target["execution_kind"], "runner": runner,
        "import_roots": list(target["import_roots"]),
        "expected_ids": expected_ids, "discovered_ids": discovered_ids,
        "case_results": case_results,
        "target_identity_before": before, "target_identity_after": after,
        "runner_identity_before": runner_before,
        "runner_identity_after": runner_after,
        "interpreter_identity_before": interpreter_before,
        "interpreter_identity_after": interpreter_after,
        "raw_stdout": raw_stdout, "raw_stderr": raw_stderr,
        "raw_rc": raw_rc, "returncode": returncode,
        "payload_sha256": payload_sha256, "result": result,
    }
    if set(record) != TARGET_RECORD_KEYS:
        raise GenerationRejected("target_record_internal_schema_invalid")
    return record, totals


def produce(staging_dir, reservation_token):
    _validate_process_contract()
    policy, policy_identity = _load_policy()
    bound_producer_identity = _validate_execution_component_binding(policy)
    generation_dir, token_sha256 = _load_reservation(
        staging_dir, reservation_token, policy_identity["sha256"])
    os.mkdir(str(generation_dir / RAW_DIRECTORY))
    os.mkdir(str(generation_dir / SUITE_DIRECTORY))
    source_before = _build_source_identity(policy, policy_identity["sha256"])
    interpreter_before = _interpreter_identity()
    unused, producer_pair = _workspace_file(GENERATOR_RELATIVE_PATH)
    producer_identity = producer_pair[1]
    if producer_identity != bound_producer_identity:
        raise GenerationRejected("producer_identity_changed_after_bootstrap")
    if producer_identity["sha256"] != policy["producer_contract"]["source_sha256"]:
        raise GenerationRejected("producer_source_sha256_mismatch")

    suite_files = []
    raw_inventory = []
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    for suite in policy["suite_authority"]:
        records = []
        case_results = []
        suite_totals = {"passed": 0, "failed": 0, "skipped": 0}
        for target in suite["targets"]:
            record, target_totals = _target_record(
                generation_dir, suite, target, policy, source_before)
            records.append(record)
            case_results.extend(record["case_results"])
            for key in suite_totals:
                suite_totals[key] += target_totals[key]
            for key in ("raw_stdout", "raw_stderr", "raw_rc"):
                if record[key] is not None:
                    raw_inventory.append(record[key])
        if len(case_results) != suite["expected_denominator"]:
            raise GenerationRejected("suite_case_denominator_drift")
        suite_result = "PASS_WITH_SKIPS" if suite_totals["skipped"] else "PASS"
        report = {
            "schema_id": SUITE_SCHEMA_ID,
            "schema_version": SUITE_SCHEMA_VERSION,
            "suite_id": suite["suite_id"], "required": True,
            "execution_scope": suite["execution_scope"],
            "authority_sha256": canonical_sha256(suite),
            "targets": records, "case_results": case_results,
            "totals": suite_totals, "result": suite_result,
        }
        report["suite_sha256"] = _self_hash(report, "suite_sha256")
        if set(report) != SUITE_KEYS:
            raise GenerationRejected("suite_internal_schema_invalid")
        relative = SUITE_DIRECTORY + "/" + suite["suite_id"] + ".json"
        identity = _write_exclusive(
            generation_dir / PurePosixPath(relative),
            canonical_json_bytes(report) + b"\n")
        identity["path"] = relative
        suite_files.append(identity)
        for key in totals:
            totals[key] += suite_totals[key]

    source_after = _build_source_identity(policy, policy_identity["sha256"])
    interpreter_after = _interpreter_identity()
    if source_before != source_after:
        raise GenerationRejected("source_identity_drift")
    if interpreter_before != interpreter_after:
        raise GenerationRejected("interpreter_identity_drift")
    suite_files.sort(key=lambda item: item["path"])
    raw_inventory.sort(key=lambda item: item["path"])
    manifest = {
        "schema_id": MANIFEST_SCHEMA_ID,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evidence_status": CURRENT_STATUS,
        "authority_policy_sha256": policy_identity["sha256"],
        "reservation_token_sha256": token_sha256,
        "producer_identity": producer_identity,
        "interpreter_identity_before": interpreter_before,
        "interpreter_identity_after": interpreter_after,
        "source_identity_before": source_before,
        "source_identity_after": source_after,
        "suite_files": suite_files, "raw_inventory": raw_inventory,
        "totals": totals,
        "result": "PASS_WITH_SKIPS" if totals["skipped"] else "PASS",
    }
    manifest["generation_sha256"] = _self_hash(
        manifest, "generation_sha256")
    if set(manifest) != MANIFEST_KEYS:
        raise GenerationRejected("manifest_internal_schema_invalid")
    manifest_identity = _write_exclusive(
        generation_dir / MANIFEST_NAME,
        canonical_json_bytes(manifest) + b"\n")
    manifest_identity["path"] = MANIFEST_NAME
    return manifest, manifest_identity


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--reservation-token", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        manifest, identity = produce(
            args.staging_dir, args.reservation_token)
        result = {
            "schema_id": "limo.arm_gripper_local_evidence_generator_result",
            "schema_version": 2, "result": "PASS",
            "generation_sha256": manifest["generation_sha256"],
            "manifest": identity,
        }
        status = 0
    except GenerationRejected as error:
        result = {
            "schema_id": "limo.arm_gripper_local_evidence_generator_result",
            "schema_version": 2, "result": "REJECTED_NOT_EVIDENCE",
            "reason": str(error),
        }
        status = 2
    sys.stdout.buffer.write(
        GENERATOR_MARKER.encode("ascii")
        + canonical_json_bytes(result)
        + b"\n")
    sys.stdout.buffer.flush()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
