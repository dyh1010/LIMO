#!/usr/bin/env python3
"""Host-owned arm/gripper local evidence aggregator.

Only a producer-owned staging directory may be supplied.  The workspace,
suite/case authority, source closure, producer and runner contracts are owned
by source code in this workspace.  This module never imports ROS, contacts a
backend, enumerates a port, or grants release/field/delivery authorization.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


AGGREGATE_SCHEMA_ID = "limo.arm_gripper_local_evidence_aggregate"
AGGREGATE_SCHEMA_VERSION = 2
CURRENT_EVIDENCE_STATUS = "CURRENT_LOCAL_OFFLINE_EVIDENCE"
EVIDENCE_CLASS = "LOCAL_OFFLINE_EVIDENCE"
GENERATION_MANIFEST_NAME = "generation_manifest.json"
RESERVATION_NAME = ".reservation.json"
RAW_DIRECTORY = "raw"
SUITE_DIRECTORY = "suites"
POLICY_RELATIVE_PATH = "audit_tools/arm_gripper_local_v3_policy.json"
GENERATOR_RELATIVE_PATH = "audit_tools/arm_gripper_local_evidence_generator.py"
GENERATOR_MARKER = "ARM_GRIPPER_LOCAL_EVIDENCE_GENERATOR_RESULT "
# Replaced with the exact raw policy-file SHA after the producer-owned policy
# is reviewed and frozen.  The all-zero sentinel can never admit evidence.
EXPECTED_POLICY_FILE_SHA256 = "0" * 64
STAGING_ROOT_RELATIVE_PATH = ".arm_gripper_local_evidence_staging"
EVIDENCE_ROOT_RELATIVE_PATH = "evidence/arm_gripper_local_v3"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_BASELINE = "ROS1_NOETIC"
WRAPPER_RUNTIME_STATUS = "ROS2_FOXY_OFFLINE_LEGACY_ONLY"
ROS1_ADAPTER_STATUS = "BLOCKED_MISSING"
LOCAL_HASH_AUTHORITY = (
    "INTEGRITY_ONLY_NO_EXTERNAL_SIGNATURE_OR_AUTHENTICITY_AUTHORITY")

MINIMUM_REQUIRED_SOURCE_PATHS = frozenset({
    "audit_tools/arm_gripper_local_evidence_aggregator.py",
    "audit_tools/arm_gripper_local_evidence_generator.py",
    "audit_tools/arm_gripper_local_static_audit.py",
    "audit_tools/run_pytest_style_tests.py",
    "audit_tools/run_unittest_file_tests.py",
    "audit_tools/test_arm_gripper_local_evidence_aggregator.py",
    "audit_tools/test_arm_gripper_local_evidence_generator.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/arm_gateway_core.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/arm_gripper_field_acceptance.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/arm_motion_release_manifest.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/arm_safety_latch.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/final_gripper_release_manifest.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/gripper_gateway_core.py",
    "src/limo_cleanup_executor/limo_cleanup_executor/gripper_safety_latch.py",
    "src/limo_cleanup_executor/test/test_arm_gateway_core.py",
    "src/limo_cleanup_executor/test/test_arm_gripper_field_acceptance.py",
    "src/limo_cleanup_executor/test/test_arm_gripper_ros1_noetic_contract.py",
    "src/limo_cleanup_executor/test/test_arm_gripper_static_safety.py",
    "src/limo_cleanup_executor/test/test_arm_motion_release_manifest.py",
    "src/limo_cleanup_executor/test/test_arm_safety_latch.py",
    "src/limo_cleanup_executor/test/test_final_gripper_release_manifest.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_core.py",
    "src/limo_cleanup_executor/test/test_gripper_safety_latch.py",
})
# Replaced with the exact reviewed policy closure.  Empty is a fail-closed
# sentinel, never a wildcard or a caller-expandable minimum scope.
EXPECTED_SOURCE_CLOSURE = ()

POLICY_SCHEMA_ID = "limo.arm_gripper_local_evidence_policy"
POLICY_SCHEMA_VERSION = 2
POLICY_KEYS = frozenset({
    "schema_id",
    "schema_version",
    "evidence_status",
    "native_line_ending_hex",
    "generation_manifest_schema",
    "generation_manifest_keys",
    "suite_schema",
    "suite_keys",
    "staging_paths",
    "source_closure",
    "source_closure_sha256",
    "suite_authority",
    "producer_contract",
    "aggregator_contract",
    "policy_payload_sha256",
})
SUITE_AUTHORITY_KEYS = frozenset({
    "suite_id",
    "required",
    "execution_scope",
    "targets",
    "expected_denominator",
    "expected_skips",
})
RUNNER_CONTRACT_KEYS = frozenset({
    "path",
    "schema",
    "kind",
    "mode",
    "marker_prefix",
    "case_results_schema",
    "source_sha256",
})
TARGET_AUTHORITY_KEYS = frozenset({
    "record_id",
    "path",
    "disposition",
    "execution_kind",
    "runner",
    "import_roots",
    "case_ids",
    "case_map_sha256",
    "denominator",
})
EXPECTED_SKIP_KEYS = frozenset({"test_id", "reason"})
TARGET_DISPOSITIONS = frozenset({
    "RUNNER_EXECUTED",
    "STATIC_AUDIT_EXECUTED",
    "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED",
})
EXECUTION_KINDS = frozenset({
    "UNITTEST_FILE",
    "PYTEST_STYLE_FILE",
    "STATIC_AUDIT_JSON",
    "NOT_EXECUTED_ROS_GRAPH_PROHIBITED",
})
ALLOWED_EXECUTION_SCOPES = frozenset({
    "COMPILE",
    "INTEGRATION",
    "PURE_FAKE",
    "STATIC",
    "UNIT",
})
MANDATORY_AUTHORITY_TARGETS = frozenset({
    "audit_tools/test_arm_gripper_local_evidence_aggregator.py",
    "audit_tools/test_arm_gripper_local_evidence_generator.py",
})

RESERVATION_SCHEMA_ID = "limo.arm_gripper_local_evidence_reservation"
RESERVATION_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_ID = "limo.arm_gripper_local_evidence_generation_manifest"
MANIFEST_SCHEMA_VERSION = 2
SUITE_RESULT_SCHEMA_ID = "limo.arm_gripper_local_evidence_suite_result"
SUITE_RESULT_SCHEMA_VERSION = 2
SOURCE_IDENTITY_SCHEMA_ID = "limo.arm_gripper_local_source_identity"
SOURCE_IDENTITY_SCHEMA_VERSION = 2
GENERATOR_RESULT_SCHEMA_ID = (
    "limo.arm_gripper_local_evidence_generator_result")
GENERATOR_RESULT_SCHEMA_VERSION = 2

IDENTITY_KEYS = frozenset({"path", "size_bytes", "sha256"})
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
SUITE_RESULT_KEYS = frozenset({
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
SOURCE_IDENTITY_KEYS = frozenset({
    "schema_id", "schema_version", "authority_policy_sha256", "files",
    "manifest_sha256",
})
TOTAL_KEYS = frozenset({"passed", "failed", "skipped"})
CASE_RESULT_BASE_KEYS = frozenset({"test_id", "outcome"})

UNITTEST_PAYLOAD_KEYS = frozenset({
    "schema_version", "runner_kind", "runner_output_contract",
    "runner_identity_before", "runner_identity_after", "selection_mode",
    "workspace", "import_roots", "path", "resolved_path", "size_bytes",
    "sha256", "target_identity_before", "target_identity_after",
    "requested_ids", "expected_ids", "executed_ids",
    "case_results_schema", "case_results", "passed_ids", "failed_ids",
    "skipped_ids", "discovered_ids", "discovered", "collected", "passed",
    "failed", "skipped", "exit", "result", "failures", "executable",
    "python", "environment", "environment_unchanged_during_execution",
    "environment_restored", "workspace_bytecode_policy",
    "workspace_pyc_bytes_read", "workspace_pyc_attempts_blocked",
    "workspace_source_reads", "workspace_loader_guard_restored",
    "workspace_pyc_audit_hook_active", "workspace_pyc_inode_policy",
    "workspace_pyc_inventory_count", "workspace_pyc_inventory_stable",
    "stdout_marker_count",
})
PYTEST_PAYLOAD_KEYS = frozenset({
    "schema_version", "runner_kind", "runner_output_contract",
    "runner_identity_before", "runner_identity_after", "path", "size_bytes",
    "sha256", "selection_mode", "expected_ids", "discovered_ids",
    "executed_ids", "discovered", "case_results_schema", "case_results",
    "collected", "passed", "failed", "skipped", "exit", "result",
    "workspace_bytecode_policy", "workspace_pyc_bytes_read",
    "workspace_pyc_attempts_blocked", "workspace_source_reads",
    "workspace_loader_guard_restored", "workspace_pyc_audit_hook_active",
    "workspace_pyc_inode_policy", "workspace_pyc_inventory_count",
    "workspace_pyc_inventory_stable",
})
STATIC_PAYLOAD_KEYS = frozenset({
    "schema_id", "schema_version", "passed", "workspace", "scope",
    "python_38_ast", "in_memory_compile", "text_integrity", "findings",
    "lock_scope", "totals",
})

WORKSPACE_BYTECODE_POLICY = "SOURCE_ONLY_REJECT_WORKSPACE_PYC_V1"
WORKSPACE_PYC_INODE_POLICY = "WORKSPACE_PYC_SINGLE_LINK_INODE_V1"
GENERATION_NAME_RE = re.compile(r"^generation-[0-9a-f]{32}$")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STALE_RE = re.compile(r"STALE|SUPERSEDED", re.IGNORECASE)
MAX_STAGING_FILE_BYTES = 64 * 1024 * 1024
MAX_STAGING_TOTAL_BYTES = 512 * 1024 * 1024


class EvidenceRejected(ValueError):
    """Raised when staged evidence is not exactly host-authorized."""


def canonical_json_bytes(value):
    """Return canonical UTF-8 JSON bytes for local integrity hashes."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value):
    """Return a lowercase SHA-256 over canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def runner_json_bytes(value):
    """Match the isolated runners' UTF-8 JSON marker serialization."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def evidence_sha256(report):
    """Hash an aggregate without its self-hash field."""
    payload = dict(report)
    payload.pop("evidence_sha256", None)
    return canonical_sha256(payload)


def material_sha256(material):
    """Hash evidence material with an explicit v3 domain separator."""
    return canonical_sha256({
        "domain": "limo.arm_gripper_local_evidence_material/v3",
        "material": material,
    })


def derive_evidence_id(source_manifest_sha256, material_digest):
    """Derive the only accepted evidence ID; callers cannot supply an ID."""
    if (
        not isinstance(source_manifest_sha256, str)
        or _SHA256_RE.fullmatch(source_manifest_sha256) is None
        or not isinstance(material_digest, str)
        or _SHA256_RE.fullmatch(material_digest) is None
    ):
        raise EvidenceRejected("evidence_id_material_sha256_invalid")
    return "ARM_GRIPPER_LOCAL_V3_{}_{}".format(
        source_manifest_sha256[:16], material_digest)


def validate_evidence_id(
        evidence_id, source_manifest_sha256, material_digest):
    """Reject old, synthetic or source/material-unbound evidence IDs."""
    if evidence_id != derive_evidence_id(
            source_manifest_sha256, material_digest):
        raise EvidenceRejected("evidence_id_not_exact_material_derivation")
    return evidence_id


def _duplicate_rejecting_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceRejected("duplicate_json_key:" + key)
        value[key] = item
    return value


def _reject_nonfinite(value):
    raise EvidenceRejected("nonfinite_json_number:" + value)


def strict_json_loads(raw, label="json"):
    """Parse exact UTF-8 JSON, rejecting duplicates and non-finite numbers."""
    if not isinstance(raw, (bytes, bytearray)):
        raise EvidenceRejected(label + "_not_bytes")
    try:
        text = bytes(raw).decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise EvidenceRejected(label + "_not_utf8") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_nonfinite,
        )
    except EvidenceRejected:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise EvidenceRejected(label + "_invalid_json") from error


def _is_linklike(path, info):
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    is_junction = getattr(os.path, "isjunction", lambda unused: False)
    return bool(
        stat.S_ISLNK(info.st_mode)
        or attributes & reparse
        or is_junction(str(path))
    )


def _stat_identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        getattr(info, "st_mtime_ns", None),
        getattr(info, "st_ctime_ns", None),
        getattr(info, "st_nlink", 1),
        getattr(info, "st_uid", None),
        getattr(info, "st_gid", None),
        getattr(info, "st_file_attributes", None),
    )


def _cross_handle_identity(info):
    mode = stat.S_IFMT(info.st_mode) if os.name == "nt" else info.st_mode
    common = (
        info.st_dev,
        info.st_ino,
        mode,
        info.st_size,
        getattr(info, "st_mtime_ns", None),
    )
    if os.name == "nt":
        return common + (
            getattr(info, "st_nlink", 1),
            getattr(info, "st_uid", None),
            getattr(info, "st_gid", None),
            getattr(info, "st_file_attributes", None),
        )
    return common + (
        getattr(info, "st_ctime_ns", None),
        getattr(info, "st_nlink", 1),
        getattr(info, "st_uid", None),
        getattr(info, "st_gid", None),
        getattr(info, "st_file_attributes", None),
    )


def _canonical_relative(value, label):
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceRejected(label + "_not_canonical_relative_posix")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or any(part in ("", ".", "..") for part in pure.parts)
    ):
        raise EvidenceRejected(label + "_not_canonical_relative_posix")
    return pure


def _secure_directory(path, label):
    try:
        info = os.lstat(str(path))
    except OSError as error:
        raise EvidenceRejected(label + "_missing") from error
    if _is_linklike(path, info) or not stat.S_ISDIR(info.st_mode):
        raise EvidenceRejected(label + "_linklike_or_not_directory")
    return info


def _secure_relative_path(root, relative, label):
    pure = _canonical_relative(relative, label)
    _secure_directory(root, label + "_root")
    current = root
    for part in pure.parts[:-1]:
        current = current / part
        _secure_directory(current, label + "_parent")
    path = current / pure.parts[-1]
    try:
        info = os.lstat(str(path))
    except OSError as error:
        raise EvidenceRejected(label + "_missing") from error
    if _is_linklike(path, info):
        raise EvidenceRejected(label + "_linklike")
    return path, info


def _secure_read_relative(root, relative, label):
    path, before = _secure_relative_path(root, relative, label)
    if (
        not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
    ):
        raise EvidenceRejected(label + "_not_exclusive_regular_file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise EvidenceRejected(label + "_open_failed") from error
    try:
        try:
            os.set_inheritable(descriptor, False)
        except OSError as error:
            raise EvidenceRejected(label + "_inheritability_failed") from error
        opened_before = os.fstat(descriptor)
        if (
            os.get_inheritable(descriptor)
            or not stat.S_ISREG(opened_before.st_mode)
            or getattr(opened_before, "st_nlink", 1) != 1
            or _cross_handle_identity(before)
            != _cross_handle_identity(opened_before)
        ):
            raise EvidenceRejected(label + "_open_identity_mismatch")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        opened_after = os.fstat(descriptor)
        if _stat_identity(opened_before) != _stat_identity(opened_after):
            raise EvidenceRejected(label + "_changed_while_open")
    finally:
        os.close(descriptor)
    after = os.lstat(str(path))
    if (
        _is_linklike(path, after)
        or not stat.S_ISREG(after.st_mode)
        or getattr(after, "st_nlink", 1) != 1
        or _stat_identity(before) != _stat_identity(after)
        or _cross_handle_identity(opened_after) != _cross_handle_identity(after)
        or len(raw) != before.st_size
    ):
        raise EvidenceRejected(label + "_post_read_identity_mismatch")
    return raw, {
        "path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _secure_read_absolute(path, label):
    candidate = Path(path)
    if not candidate.is_absolute():
        raise EvidenceRejected(label + "_not_absolute")
    chain = list(reversed(candidate.parents))
    for index, parent in enumerate(chain):
        if index == 0 and str(parent) == parent.anchor:
            _secure_directory(parent, label + "_anchor")
        else:
            _secure_directory(parent, label + "_parent")
    raw, identity = _secure_read_relative(
        candidate.parent, candidate.name, label)
    identity["path"] = str(candidate)
    return raw, identity


def read_staging_inventory(generation_dir):
    """Return exact sorted file identities without following linklike paths."""
    root = Path(generation_dir)
    _secure_directory(root, "staging_inventory_root")
    pending = [(root, "")]
    relative_files = []
    while pending:
        directory, relative_directory = pending.pop()
        _secure_directory(directory, "staging_inventory_directory")
        try:
            entries = sorted(
                os.scandir(str(directory)), key=lambda item: item.name)
        except OSError as error:
            raise EvidenceRejected("staging_inventory_scan_failed") from error
        for entry in entries:
            name = entry.name
            relative = (
                name if not relative_directory
                else relative_directory + "/" + name)
            _canonical_relative(relative, "staging_inventory_path")
            path = directory / name
            try:
                info = os.lstat(str(path))
            except OSError as error:
                raise EvidenceRejected(
                    "staging_inventory_lstat_failed") from error
            if _is_linklike(path, info):
                raise EvidenceRejected("staging_inventory_linklike")
            if stat.S_ISDIR(info.st_mode):
                pending.append((path, relative))
            elif stat.S_ISREG(info.st_mode):
                relative_files.append(relative)
            else:
                raise EvidenceRejected("staging_inventory_special_file")
    identities = []
    total = 0
    for relative in sorted(relative_files):
        raw, identity = _secure_read_relative(
            root, relative, "staging_inventory_file")
        if len(raw) > MAX_STAGING_FILE_BYTES:
            raise EvidenceRejected("staging_inventory_file_too_large")
        total += len(raw)
        if total > MAX_STAGING_TOTAL_BYTES:
            raise EvidenceRejected("staging_inventory_total_too_large")
        identities.append(identity)
    return identities


def validate_exact_inventory(actual, expected):
    """Reject missing, extra, reordered or identity-mismatched staging files."""
    if not isinstance(actual, list) or not isinstance(expected, list):
        raise EvidenceRejected("staging_inventory_not_lists")
    for label, entries in (("actual", actual), ("expected", expected)):
        paths = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"path", "size_bytes", "sha256"}
                or not isinstance(entry["path"], str)
                or type(entry["size_bytes"]) is not int
                or entry["size_bytes"] < 0
                or not isinstance(entry["sha256"], str)
                or _SHA256_RE.fullmatch(entry["sha256"]) is None
            ):
                raise EvidenceRejected(
                    "staging_inventory_{}_entry_invalid".format(label))
            _canonical_relative(entry["path"], "staging_inventory_path")
            paths.append(entry["path"])
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise EvidenceRejected(
                "staging_inventory_{}_not_sorted_unique".format(label))
    if actual != expected:
        raise EvidenceRejected("staging_inventory_exact_mismatch")
    return actual


def _validate_identity(value, label, expected=None, relative_path=True):
    if (
        not isinstance(value, dict)
        or set(value) != IDENTITY_KEYS
        or not isinstance(value.get("path"), str)
        or not value["path"]
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] < 0
        or not isinstance(value.get("sha256"), str)
        or _SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise EvidenceRejected(label + "_identity_invalid")
    if relative_path:
        _canonical_relative(value["path"], label + "_path")
    elif not Path(value["path"]).is_absolute():
        raise EvidenceRejected(label + "_path_not_absolute")
    if expected is not None and value != expected:
        raise EvidenceRejected(label + "_identity_mismatch")
    return dict(value)


def _secure_read_canonical_json(root, relative, label):
    raw, identity = _secure_read_relative(root, relative, label)
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise EvidenceRejected(label + "_fixed_lf_contract_invalid")
    value = strict_json_loads(raw, label)
    if canonical_json_bytes(value) + b"\n" != raw:
        raise EvidenceRejected(label + "_not_canonical_json_line")
    return value, identity, raw


def _self_hash(value, key):
    payload = dict(value)
    payload.pop(key, None)
    return canonical_sha256(payload)


def _validate_totals(value, label, denominator=None, allow_failed=False):
    if not isinstance(value, dict) or set(value) != TOTAL_KEYS:
        raise EvidenceRejected(label + "_totals_schema_invalid")
    for key in sorted(TOTAL_KEYS):
        if type(value[key]) is not int or value[key] < 0:
            raise EvidenceRejected(label + "_totals_value_invalid")
    if denominator is not None and sum(value.values()) != denominator:
        raise EvidenceRejected(label + "_totals_denominator_mismatch")
    if not allow_failed and value["failed"] != 0:
        raise EvidenceRejected(label + "_failed_nonzero")
    return dict(value)


def _expected_skip_map(suite):
    return {
        item["test_id"]: item["reason"]
        for item in suite["expected_skips"]
    }


def _validate_case_results(value, expected_ids, expected_skips, label):
    if not isinstance(value, list) or len(value) != len(expected_ids):
        raise EvidenceRejected(label + "_case_results_length_invalid")
    if [item.get("test_id") if isinstance(item, dict) else None
            for item in value] != list(expected_ids):
        raise EvidenceRejected(label + "_case_results_id_map_invalid")
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            raise EvidenceRejected(label + "_case_result_not_object")
        outcome = item.get("outcome")
        expected_reason = expected_skips.get(item.get("test_id"))
        required_keys = set(CASE_RESULT_BASE_KEYS)
        if outcome != "passed":
            required_keys.add("reason")
        if set(item) != required_keys or outcome not in totals:
            raise EvidenceRejected(label + "_case_result_schema_invalid")
        if expected_reason is None:
            if outcome != "passed":
                raise EvidenceRejected(label + "_unexpected_nonpass")
        elif outcome != "skipped" or item.get("reason") != expected_reason:
            raise EvidenceRejected(label + "_expected_skip_mismatch")
        totals[outcome] += 1
        normalized.append(dict(item))
    if totals["failed"]:
        raise EvidenceRejected(label + "_failed_case_present")
    return normalized, totals


def _validate_source_identity(value, authority, expected, label):
    if not isinstance(value, dict) or set(value) != SOURCE_IDENTITY_KEYS:
        raise EvidenceRejected(label + "_schema_invalid")
    if (
        value["schema_id"] != SOURCE_IDENTITY_SCHEMA_ID
        or value["schema_version"] != SOURCE_IDENTITY_SCHEMA_VERSION
        or value["authority_policy_sha256"] != authority["policy_sha256"]
        or value["manifest_sha256"] != _self_hash(
            value, "manifest_sha256")
    ):
        raise EvidenceRejected(label + "_header_or_self_hash_invalid")
    files = value["files"]
    if not isinstance(files, list):
        raise EvidenceRejected(label + "_files_not_list")
    paths = []
    for item in files:
        identity = _validate_identity(item, label + "_file")
        paths.append(identity["path"])
    if (
        paths != list(authority["source_closure"])
        or len(paths) != len(set(path.casefold() for path in paths))
    ):
        raise EvidenceRejected(label + "_closure_mismatch")
    if expected is not None and value != expected:
        raise EvidenceRejected(label + "_host_identity_mismatch")
    return {item["path"]: dict(item) for item in files}


def _expected_generator_interpreter_identity(process_contract):
    executable = process_contract["executable"]
    return {
        "path": executable["path"],
        "size_bytes": executable["size_bytes"],
        "sha256": executable["sha256"],
        "version": [
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ],
        "implementation": sys.implementation.name,
        "isolated": True,
        "no_site": True,
        "dont_write_bytecode": True,
    }


def _validate_workspace_source_reads(
        reads, source_by_path, target_path, label):
    if not isinstance(reads, list):
        raise EvidenceRejected(label + "_source_reads_not_list")
    paths = []
    observed = {}
    for item in reads:
        identity = _validate_identity(item, label + "_source_read")
        path = identity["path"]
        if not path.endswith(".py"):
            raise EvidenceRejected(label + "_source_read_not_python")
        expected = source_by_path.get(path)
        if expected is None:
            raise EvidenceRejected(label + "_source_read_unbound:" + path)
        if identity != expected:
            raise EvidenceRejected(label + "_source_read_identity_mismatch:" + path)
        paths.append(path)
        observed[path] = identity
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise EvidenceRejected(label + "_source_reads_not_sorted_unique")
    if observed.get(target_path) != source_by_path.get(target_path):
        raise EvidenceRejected(label + "_target_source_read_missing")
    return observed


def _validate_workspace_bytecode_payload(payload, label):
    if payload.get("workspace_bytecode_policy") != WORKSPACE_BYTECODE_POLICY:
        raise EvidenceRejected(label + "_workspace_bytecode_policy_invalid")
    if payload.get("workspace_pyc_bytes_read") != 0:
        raise EvidenceRejected(label + "_workspace_pyc_bytes_read_nonzero")
    if payload.get("workspace_loader_guard_restored") is not True:
        raise EvidenceRejected(label + "_workspace_loader_guard_not_restored")
    if payload.get("workspace_pyc_audit_hook_active") is not True:
        raise EvidenceRejected(label + "_workspace_pyc_audit_hook_inactive")
    if payload.get("workspace_pyc_inode_policy") != WORKSPACE_PYC_INODE_POLICY:
        raise EvidenceRejected(label + "_workspace_pyc_inode_policy_invalid")
    if (
        type(payload.get("workspace_pyc_inventory_count")) is not int
        or payload["workspace_pyc_inventory_count"] < 0
        or payload.get("workspace_pyc_inventory_stable") is not True
    ):
        raise EvidenceRejected(label + "_workspace_pyc_inventory_invalid")
    blocked = payload.get("workspace_pyc_attempts_blocked")
    if not isinstance(blocked, list) or blocked != sorted(set(blocked)):
        raise EvidenceRejected(label + "_workspace_pyc_blocked_paths_invalid")
    for path in blocked:
        pure = _canonical_relative(path, label + "_workspace_pyc_path")
        if not (
            pure.suffix.casefold() == ".pyc"
            or "__pycache__" in tuple(part.casefold() for part in pure.parts)
        ):
            raise EvidenceRejected(label + "_workspace_pyc_path_invalid")


def _validate_runner_executable(value, process_contract, label):
    if not isinstance(value, dict):
        raise EvidenceRejected(label + "_executable_not_object")
    required = {
        "entry_path", "entry_is_symlink", "entry_lstat_size_bytes",
        "entry_link_chain", "resolved_target", "isolated", "no_bytecode",
        "version",
    }
    if set(value) != required:
        raise EvidenceRejected(label + "_executable_schema_invalid")
    target = value["resolved_target"]
    if not isinstance(target, dict) or set(target) != {
            "path", "size_bytes", "sha256", "regular_file", "is_symlink"}:
        raise EvidenceRejected(label + "_executable_target_schema_invalid")
    expected = process_contract["executable"]
    if (
        target["size_bytes"] != expected["size_bytes"]
        or target["sha256"] != expected["sha256"]
        or target["regular_file"] is not True
        or target["is_symlink"] is not False
        or value["isolated"] is not True
        or value["no_bytecode"] is not True
        or value["version"] != [
            sys.version_info.major, sys.version_info.minor,
            sys.version_info.micro]
    ):
        raise EvidenceRejected(label + "_executable_identity_mismatch")


def _validate_runner_payload(
        payload, target, record, source_by_path, process_contract, label):
    expected_ids = list(target["case_ids"])
    expected_skips = _expected_skip_map({
        "expected_skips": [
            item for item in record.get("_suite_expected_skips", [])
        ]
    })
    execution_kind = target["execution_kind"]
    expected_keys = (
        UNITTEST_PAYLOAD_KEYS
        if execution_kind == "UNITTEST_FILE"
        else PYTEST_PAYLOAD_KEYS
    )
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise EvidenceRejected(label + "_runner_payload_keys_invalid")
    runner = target["runner"]
    output_contract = {
        "encoding": "UTF-8",
        "json": "SORTED_KEYS_COMPACT_ENSURE_ASCII_FALSE",
        "line_ending_hex": "0a",
    }
    if (
        payload["schema_version"] != runner["schema"]
        or payload["runner_kind"] != runner["kind"]
        or payload["runner_output_contract"] != output_contract
        or payload["selection_mode"] != "selected_ids"
        or payload["path"] != target["path"]
        or payload["expected_ids"] != expected_ids
        or payload["discovered_ids"] != expected_ids
        or payload["executed_ids"] != expected_ids
        or payload["case_results_schema"] != runner["case_results_schema"]
        or payload["case_results"] != record["case_results"]
        or payload["discovered"] != len(expected_ids)
        or payload["collected"] != len(expected_ids)
        or payload["exit"] != 0
        or payload["result"] != record["result"]
    ):
        raise EvidenceRejected(label + "_runner_payload_contract_mismatch")
    totals = _validate_totals({
        "passed": payload["passed"],
        "failed": payload["failed"],
        "skipped": payload["skipped"],
    }, label + "_runner", len(expected_ids))
    if totals != _validate_case_results(
            record["case_results"], expected_ids, expected_skips,
            label + "_runner_cases")[1]:
        raise EvidenceRejected(label + "_runner_totals_mismatch")
    expected_target = source_by_path[target["path"]]
    expected_runner = source_by_path[runner["path"]]
    if (
        payload["size_bytes"] != expected_target["size_bytes"]
        or payload["sha256"] != expected_target["sha256"]
        or payload["runner_identity_before"] != expected_runner
        or payload["runner_identity_after"] != expected_runner
    ):
        raise EvidenceRejected(label + "_runner_or_target_identity_mismatch")
    _validate_workspace_bytecode_payload(payload, label)
    _validate_workspace_source_reads(
        payload["workspace_source_reads"], source_by_path,
        target["path"], label)
    if execution_kind == "UNITTEST_FILE":
        expected_target_runner_identity = {
            "path": target["path"],
            "size_bytes": expected_target["size_bytes"],
            "sha256": expected_target["sha256"],
        }
        if (
            payload["workspace"] != str(WORKSPACE_ROOT.resolve())
            or payload["import_roots"] != target["import_roots"]
            or payload["resolved_path"] != str(
                (WORKSPACE_ROOT / target["path"]).resolve())
            or payload["target_identity_before"] != expected_target_runner_identity
            or payload["target_identity_after"] != expected_target_runner_identity
            or payload["requested_ids"] != expected_ids
            or payload["passed_ids"] != [
                item["test_id"] for item in record["case_results"]
                if item["outcome"] == "passed"]
            or payload["failed_ids"] != []
            or payload["skipped_ids"] != [
                item["test_id"] for item in record["case_results"]
                if item["outcome"] == "skipped"]
            or payload["failures"] != []
            or payload["environment_unchanged_during_execution"] is not True
            or payload["environment_restored"] is not True
            or payload["stdout_marker_count"] != 1
            or payload["python"] != payload["executable"]
        ):
            raise EvidenceRejected(label + "_unittest_payload_contract_mismatch")
        environment = payload["environment"]
        if (
            not isinstance(environment, dict)
            or environment.get("clean") is not True
            or environment.get("contaminated_keys") != []
            or environment.get("cwd") != str(WORKSPACE_ROOT.resolve())
        ):
            raise EvidenceRejected(label + "_unittest_environment_invalid")
        _validate_runner_executable(
            payload["executable"], process_contract, label)
    return totals


def _validate_static_payload(payload, source_by_path, label):
    if not isinstance(payload, dict) or set(payload) != STATIC_PAYLOAD_KEYS:
        raise EvidenceRejected(label + "_static_payload_keys_invalid")
    expected_hashes = {
        path: identity["sha256"]
        for path, identity in source_by_path.items()
    }
    python_count = sum(path.endswith(".py") for path in source_by_path)
    if (
        payload["schema_id"] != "limo.arm_gripper_local_static_audit"
        or payload["schema_version"] != 1
        or payload["passed"] is not True
        or payload["workspace"] != str(WORKSPACE_ROOT.resolve())
        or payload["scope"] != {
            "files": len(expected_hashes), "python_files": python_count,
            "sha256": expected_hashes}
        or payload["python_38_ast"] != {
            "passed": python_count, "failed": 0, "errors": []}
        or payload["in_memory_compile"] != {
            "passed": python_count, "failed": 0, "errors": []}
    ):
        raise EvidenceRejected(label + "_static_payload_identity_mismatch")
    text_integrity = payload["text_integrity"]
    findings = payload["findings"]
    if (
        not isinstance(text_integrity, dict)
        or set(text_integrity) != {
            "conflict_markers", "trailing_whitespace", "tab_lines",
            "missing_final_newline"}
        or any(value != [] for value in text_integrity.values())
        or not isinstance(findings, dict)
        or set(findings) != {
            "backend_vendor_or_dynamic_imports",
            "backend_file_io_or_enumeration", "timeout_thread_wrappers",
            "runtime_device_path_entries", "real_backend_construction_entries",
            "pure_python_ros_imports"}
        or any(value != [] for value in findings.values())
        or payload["totals"] != {
            "static_findings": 0, "text_integrity_findings": 0,
            "ordinary_lock_external_call_violations": 0}
    ):
        raise EvidenceRejected(label + "_static_findings_nonzero")
    lock_scope = payload["lock_scope"]
    expected_paths = [
        "src/limo_cleanup_executor/limo_cleanup_executor/arm_gateway_core.py",
        "src/limo_cleanup_executor/limo_cleanup_executor/arm_gateway_node.py",
        "src/limo_cleanup_executor/limo_cleanup_executor/gripper_gateway_core.py",
        "src/limo_cleanup_executor/limo_cleanup_executor/gripper_gateway_node.py",
    ]
    if (
        not isinstance(lock_scope, list)
        or [item.get("path") if isinstance(item, dict) else None
            for item in lock_scope] != expected_paths
    ):
        raise EvidenceRejected(label + "_static_lock_scope_invalid")
    for item in lock_scope:
        if (
            set(item) != {
                "path", "ordinary_lock_blocks", "external_call_violations"}
            or type(item["ordinary_lock_blocks"]) is not int
            or item["ordinary_lock_blocks"] < 0
            or item["external_call_violations"] != []
        ):
            raise EvidenceRejected(label + "_static_lock_scope_violation")


def validate_aggregator_process_contract(
        flags=None, environment=None, executable=None):
    """Require an isolated, no-bytecode, uncontaminated aggregator process."""
    active_flags = sys.flags if flags is None else flags
    active_environment = os.environ if environment is None else environment
    active_executable = sys.executable if executable is None else executable
    if (
        not bool(getattr(active_flags, "isolated", False))
        or not bool(getattr(active_flags, "dont_write_bytecode", False))
        or not bool(getattr(active_flags, "no_user_site", False))
    ):
        raise EvidenceRejected("aggregator_requires_python_I_B")
    forbidden = sorted(
        key for key in ("PYTHONHOME", "PYTHONPATH")
        if key in active_environment)
    if forbidden:
        raise EvidenceRejected(
            "aggregator_environment_contaminated:" + ",".join(forbidden))
    if not isinstance(active_executable, str) or not active_executable:
        raise EvidenceRejected("aggregator_executable_missing")
    raw, identity = _secure_read_absolute(
        Path(active_executable), "aggregator_executable")
    if identity["sha256"] != hashlib.sha256(raw).hexdigest():
        raise EvidenceRejected("aggregator_executable_identity_invalid")
    return {
        "executable": identity,
        "isolated": True,
        "dont_write_bytecode": True,
        "no_user_site": True,
        "forbidden_environment_present": [],
    }


def _validate_workspace_anchor():
    _secure_directory(WORKSPACE_ROOT, "workspace")
    raw, identity = _secure_read_relative(
        WORKSPACE_ROOT,
        "audit_tools/arm_gripper_local_evidence_aggregator.py",
        "aggregator_source",
    )
    if not raw or identity["sha256"] != hashlib.sha256(raw).hexdigest():
        raise EvidenceRejected("aggregator_source_identity_invalid")
    return identity


def _load_host_policy():
    raw, identity = _secure_read_relative(
        WORKSPACE_ROOT, POLICY_RELATIVE_PATH, "policy_file")
    if identity["sha256"] != EXPECTED_POLICY_FILE_SHA256:
        raise EvidenceRejected("policy_file_sha256_not_frozen_expected")
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise EvidenceRejected("policy_file_fixed_lf_contract_invalid")
    policy = strict_json_loads(raw, "policy_file")
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise EvidenceRejected("policy_keys_invalid")
    if (
        policy.get("schema_id") != POLICY_SCHEMA_ID
        or policy.get("schema_version") != POLICY_SCHEMA_VERSION
    ):
        raise EvidenceRejected("policy_schema_invalid")
    if policy.get("evidence_status") != CURRENT_EVIDENCE_STATUS:
        raise EvidenceRejected("policy_evidence_status_not_current")
    if policy.get("native_line_ending_hex") != "0a":
        raise EvidenceRejected("policy_fixed_lf_mismatch")
    payload = dict(policy)
    declared_payload_sha256 = payload.pop("policy_payload_sha256", None)
    if declared_payload_sha256 != canonical_sha256(payload):
        raise EvidenceRejected("policy_payload_sha256_mismatch")
    return policy, identity


def _validate_source_closure(raw_paths):
    if not isinstance(raw_paths, (tuple, list)) or not raw_paths:
        raise EvidenceRejected("source_closure_not_nonempty_sequence")
    paths = []
    folded = set()
    for raw in raw_paths:
        pure = _canonical_relative(raw, "source_closure_path")
        value = pure.as_posix()
        if value.casefold() in folded:
            raise EvidenceRejected("source_closure_duplicate_path")
        folded.add(value.casefold())
        paths.append(value)
    if paths != sorted(paths):
        raise EvidenceRejected("source_closure_not_sorted")
    if tuple(paths) != tuple(EXPECTED_SOURCE_CLOSURE):
        raise EvidenceRejected("source_closure_not_exact_frozen_scope")
    missing = sorted(MINIMUM_REQUIRED_SOURCE_PATHS - set(paths))
    if missing:
        raise EvidenceRejected(
            "source_closure_missing_required:" + ",".join(missing))
    return tuple(paths)


def _validate_suite_authority(raw_suites, source_closure):
    if not isinstance(raw_suites, (tuple, list)) or len(raw_suites) != 4:
        raise EvidenceRejected("suite_authority_must_have_exactly_four_suites")
    suite_ids = []
    normalized = []
    all_case_ids = set()
    all_target_paths = set()
    all_record_ids = set()
    static_skipped_case_ids = set()
    for entry in raw_suites:
        if not isinstance(entry, dict) or set(entry) != SUITE_AUTHORITY_KEYS:
            raise EvidenceRejected("suite_authority_entry_not_object")
        suite_id = entry["suite_id"]
        if not isinstance(suite_id, str) or not suite_id:
            raise EvidenceRejected("suite_authority_suite_id_invalid")
        if entry["required"] is not True:
            raise EvidenceRejected("suite_authority_suite_not_required")
        if entry["execution_scope"] not in ALLOWED_EXECUTION_SCOPES:
            raise EvidenceRejected("suite_authority_scope_invalid")

        targets = entry["targets"]
        if not isinstance(targets, list) or not targets:
            raise EvidenceRejected("suite_targets_invalid")
        target_paths = []
        record_ids = []
        suite_case_ids = []
        for target in targets:
            if (
                not isinstance(target, dict)
                or set(target) != TARGET_AUTHORITY_KEYS
            ):
                raise EvidenceRejected("suite_target_keys_invalid")
            target_path = _canonical_relative(
                target["path"], "suite_target_path").as_posix()
            if target_path not in source_closure:
                raise EvidenceRejected("suite_target_outside_source_closure")
            record_id = target["record_id"]
            if (
                not isinstance(record_id, str)
                or not record_id
                or "/" in record_id
                or "\\" in record_id
                or record_id in all_record_ids
            ):
                raise EvidenceRejected("suite_record_id_invalid_or_duplicate")
            disposition = target["disposition"]
            execution_kind = target["execution_kind"]
            if (
                disposition not in TARGET_DISPOSITIONS
                or execution_kind not in EXECUTION_KINDS
            ):
                raise EvidenceRejected("suite_execution_contract_invalid")
            expected_pair = {
                "RUNNER_EXECUTED": {
                    "UNITTEST_FILE", "PYTEST_STYLE_FILE"},
                "STATIC_AUDIT_EXECUTED": {"STATIC_AUDIT_JSON"},
                "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED": {
                    "NOT_EXECUTED_ROS_GRAPH_PROHIBITED"},
            }
            if execution_kind not in expected_pair[disposition]:
                raise EvidenceRejected("suite_execution_disposition_mismatch")

            runner = target["runner"]
            if disposition == (
                    "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED"):
                if runner is not None:
                    raise EvidenceRejected("nonexecuted_target_has_runner")
            else:
                if (
                    not isinstance(runner, dict)
                    or set(runner) != RUNNER_CONTRACT_KEYS
                ):
                    raise EvidenceRejected(
                        "suite_target_runner_contract_invalid")
                runner_path = _canonical_relative(
                    runner["path"], "target_runner_path").as_posix()
                if runner_path not in source_closure:
                    raise EvidenceRejected(
                        "target_runner_outside_source_closure")
                for key in (
                        "schema", "kind", "mode", "case_results_schema"):
                    if not isinstance(runner[key], str) or not runner[key]:
                        raise EvidenceRejected(
                            "target_runner_field_invalid:" + key)
                marker_prefix = runner["marker_prefix"]
                if execution_kind == "STATIC_AUDIT_JSON":
                    if marker_prefix is not None:
                        raise EvidenceRejected(
                            "static_audit_marker_prefix_must_be_null")
                elif not isinstance(marker_prefix, str) or not marker_prefix:
                    raise EvidenceRejected(
                        "target_runner_marker_prefix_invalid")
                if (
                    not isinstance(runner["source_sha256"], str)
                    or _SHA256_RE.fullmatch(runner["source_sha256"]) is None
                ):
                    raise EvidenceRejected("target_runner_sha256_invalid")

            import_roots = target["import_roots"]
            if not isinstance(import_roots, list):
                raise EvidenceRejected("target_import_roots_not_list")
            normalized_roots = [
                _canonical_relative(root, "target_import_root").as_posix()
                for root in import_roots
            ]
            if (
                normalized_roots != sorted(normalized_roots)
                or len(normalized_roots) != len(set(normalized_roots))
            ):
                raise EvidenceRejected("target_import_roots_not_sorted_unique")
            if disposition == (
                    "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED") and (
                    normalized_roots):
                raise EvidenceRejected("nonexecuted_target_has_import_roots")
            case_ids = target["case_ids"]
            if (
                not isinstance(case_ids, list)
                or not case_ids
                or any(not isinstance(case, str) or not case for case in case_ids)
                or len(case_ids) != len(set(case_ids))
                or any(
                    not case.startswith(target_path + "::")
                    for case in case_ids)
                or type(target["denominator"]) is not int
                or target["denominator"] != len(case_ids)
                or target["case_map_sha256"] != canonical_sha256(case_ids)
                or target["disposition"] not in TARGET_DISPOSITIONS
            ):
                raise EvidenceRejected("suite_authority_case_map_invalid")
            if target_path in all_target_paths:
                raise EvidenceRejected("suite_target_reused_across_suites")
            if any(case in all_case_ids for case in case_ids):
                raise EvidenceRejected("suite_case_reused_across_suites")
            target_paths.append(target_path)
            record_ids.append(record_id)
            suite_case_ids.extend(case_ids)
            all_target_paths.add(target_path)
            all_record_ids.add(record_id)
            all_case_ids.update(case_ids)
            if target["disposition"] == (
                    "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED"):
                static_skipped_case_ids.update(case_ids)
        if (
            target_paths != sorted(target_paths)
            or record_ids != sorted(record_ids)
        ):
            raise EvidenceRejected("suite_targets_not_sorted")
        if (
            type(entry["expected_denominator"]) is not int
            or entry["expected_denominator"] != len(suite_case_ids)
        ):
            raise EvidenceRejected("suite_expected_denominator_mismatch")
        skips = entry["expected_skips"]
        if not isinstance(skips, list):
            raise EvidenceRejected("suite_expected_skips_not_list")
        skip_ids = []
        for skip in skips:
            if (
                not isinstance(skip, dict)
                or set(skip) != EXPECTED_SKIP_KEYS
                or not isinstance(skip["test_id"], str)
                or skip["test_id"] not in suite_case_ids
                or not isinstance(skip["reason"], str)
                or not skip["reason"].strip()
                or skip["reason"] != skip["reason"].strip()
            ):
                raise EvidenceRejected("suite_expected_skip_invalid")
            skip_ids.append(skip["test_id"])
        if len(skip_ids) != len(set(skip_ids)):
            raise EvidenceRejected("suite_expected_skip_duplicate")
        if not static_skipped_case_ids.intersection(suite_case_ids).issubset(
                set(skip_ids)):
            raise EvidenceRejected("static_nonexecuted_case_not_expected_skip")
        suite_ids.append(suite_id)
        normalized.append(json.loads(json.dumps(entry)))
    if suite_ids != sorted(suite_ids) or len(suite_ids) != len(set(suite_ids)):
        raise EvidenceRejected("suite_authority_ids_not_sorted_unique")
    if not MANDATORY_AUTHORITY_TARGETS.issubset(all_target_paths):
        raise EvidenceRejected("suite_authority_missing_aggregator_generator_tests")
    return tuple(normalized)


def load_host_authority():
    """Load and cross-check the fixed non-executable authority policy."""
    aggregator_identity = _validate_workspace_anchor()
    policy, policy_identity = _load_host_policy()
    source_closure = _validate_source_closure(policy["source_closure"])
    if policy["source_closure_sha256"] != canonical_sha256(
            list(source_closure)):
        raise EvidenceRejected("source_closure_sha256_mismatch")
    suites = _validate_suite_authority(
        policy["suite_authority"], set(source_closure))
    return {
        "aggregator_identity": aggregator_identity,
        "policy_identity": policy_identity,
        "source_closure": source_closure,
        "suite_authority": suites,
        "policy": policy,
        "policy_sha256": policy_identity["sha256"],
    }


def build_host_source_identity(authority):
    """Hash the exact host-owned source closure; callers cannot select it."""
    files = []
    for relative in authority["source_closure"]:
        raw, identity = _secure_read_relative(
            WORKSPACE_ROOT, relative, "source_file")
        if identity["sha256"] != hashlib.sha256(raw).hexdigest():
            raise EvidenceRejected("source_file_sha256_internal_mismatch")
        files.append(identity)
    payload = {
        "schema_id": "limo.arm_gripper_local_source_identity",
        "schema_version": 2,
        "authority_policy_sha256": authority["policy_sha256"],
        "files": files,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def validate_authority_source_bindings(authority, source_identity):
    """Bind every target runner contract to the exact source-closure bytes."""
    if not isinstance(source_identity, dict) or not isinstance(
            source_identity.get("files"), list):
        raise EvidenceRejected("source_identity_files_invalid")
    by_path = {}
    for identity in source_identity["files"]:
        if (
            not isinstance(identity, dict)
            or set(identity) != {"path", "size_bytes", "sha256"}
            or identity["path"] in by_path
        ):
            raise EvidenceRejected("source_identity_entry_invalid")
        by_path[identity["path"]] = identity
    if set(by_path) != set(authority["source_closure"]):
        raise EvidenceRejected("source_identity_closure_mismatch")
    for suite in authority["suite_authority"]:
        for target in suite["targets"]:
            if target["path"] not in by_path:
                raise EvidenceRejected("target_source_identity_missing")
            runner = target["runner"]
            if runner is None:
                continue
            runner_identity = by_path.get(runner["path"])
            if runner_identity is None:
                raise EvidenceRejected("runner_source_identity_missing")
            if runner["source_sha256"] != runner_identity["sha256"]:
                raise EvidenceRejected("runner_source_sha256_mismatch")
    return True


def parse_exact_marker(raw, marker_prefix, label="runner_stdout"):
    """Parse one canonical UTF-8 marker line with the fixed LF contract."""
    if not isinstance(marker_prefix, str) or not marker_prefix:
        raise EvidenceRejected(label + "_marker_prefix_invalid")
    try:
        prefix = marker_prefix.encode("ascii")
    except UnicodeEncodeError as error:
        raise EvidenceRejected(label + "_marker_prefix_not_ascii") from error
    if b"\r" in raw:
        raise EvidenceRejected(label + "_unexpected_cr")
    if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        raise EvidenceRejected(label + "_fixed_lf_contract_invalid")
    line = raw[:-1]
    if not line.startswith(prefix):
        raise EvidenceRejected(label + "_marker_prefix_mismatch")
    payload_raw = line[len(prefix):]
    if not payload_raw:
        raise EvidenceRejected(label + "_marker_payload_missing")
    payload = strict_json_loads(payload_raw, label + "_marker_payload")
    if runner_json_bytes(payload) != payload_raw:
        raise EvidenceRejected(label + "_marker_payload_not_canonical")
    return payload, {
        "marker_prefix": marker_prefix,
        "line_ending_hex": "0a",
        "payload_sha256": hashlib.sha256(payload_raw).hexdigest(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _fixed_blocked_truth():
    return {
        "runtime_baseline": RUNTIME_BASELINE,
        "wrapper_runtime_status": WRAPPER_RUNTIME_STATUS,
        "ros1_adapter": ROS1_ADAPTER_STATUS,
        "real_backend": {"arm": "BLOCKED", "gripper": "BLOCKED"},
        "release": False,
        "field": False,
        "delivery": False,
        "hardware": False,
        "readiness": "BLOCKED",
        "local_hash_authority": LOCAL_HASH_AUTHORITY,
    }


def _rejection_report(code, staging_dir=None):
    report = {
        "schema_id": AGGREGATE_SCHEMA_ID,
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "evidence_status": "REJECTED_NOT_EVIDENCE",
        "evidence_class": EVIDENCE_CLASS,
        "staging_dir": str(staging_dir) if staging_dir is not None else None,
        "input_accepted": False,
        "local_offline_result": "BLOCKED",
        "rejections": [{"code": code}],
        **_fixed_blocked_truth(),
    }
    report["evidence_sha256"] = evidence_sha256(report)
    return report


def aggregate_staging(staging_dir):
    """Validate producer staging; strict missing bindings reject immediately."""
    process_contract = validate_aggregator_process_contract()
    authority = load_host_authority()
    source_before = build_host_source_identity(authority)
    validate_authority_source_bindings(authority, source_before)

    staging_root = WORKSPACE_ROOT / STAGING_ROOT_RELATIVE_PATH
    _secure_directory(staging_root, "staging_root")
    candidate = Path(staging_dir)
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    try:
        candidate_relative = candidate.relative_to(staging_root).as_posix()
    except ValueError as error:
        raise EvidenceRejected("staging_dir_outside_fixed_root") from error
    pure = _canonical_relative(candidate_relative, "staging_generation")
    if len(pure.parts) != 1:
        raise EvidenceRejected("staging_dir_not_direct_generation_child")
    generation_dir = staging_root / pure.parts[0]
    _secure_directory(generation_dir, "staging_generation")
    manifest_raw, unused_manifest_identity = _secure_read_relative(
        generation_dir, GENERATION_MANIFEST_NAME, "generation_manifest")
    manifest = strict_json_loads(manifest_raw, "generation_manifest")

    expected_manifest_schema = authority["policy"].get(
        "generation_manifest_schema")
    if not isinstance(expected_manifest_schema, str):
        raise EvidenceRejected("policy_generation_manifest_schema_missing")
    if manifest.get("schema_id") != expected_manifest_schema:
        raise EvidenceRejected("generation_manifest_schema_mismatch")
    if manifest.get("evidence_status") != CURRENT_EVIDENCE_STATUS:
        status = manifest.get("evidence_status")
        if isinstance(status, str) and _STALE_RE.search(status):
            raise EvidenceRejected("stale_or_superseded_evidence_status")
        raise EvidenceRejected("generation_manifest_status_not_current")
    if manifest.get("authority_policy_sha256") != authority["policy_sha256"]:
        raise EvidenceRejected("generation_manifest_policy_sha256_mismatch")
    if manifest.get("source_identity_before") != source_before:
        raise EvidenceRejected("generation_manifest_source_before_mismatch")
    if manifest.get("interpreter_identity_before") != (
            process_contract["executable"]):
        raise EvidenceRejected(
            "generation_manifest_aggregator_interpreter_mismatch")

    staging_contract = authority["policy"].get("aggregator_contract")
    if not isinstance(staging_contract, dict):
        raise EvidenceRejected("policy_staging_contract_missing")
    required_contract_keys = {
        "manifest_keys",
        "suite_schema",
        "suite_keys",
        "staging_paths",
    }
    if set(staging_contract) != required_contract_keys:
        raise EvidenceRejected("policy_staging_contract_keys_invalid")
    if set(manifest) != set(staging_contract["manifest_keys"]):
        raise EvidenceRejected("generation_manifest_keys_invalid")

    raise EvidenceRejected(
        "staging_suite_raw_independent_validator_pending_exact_producer_v2")


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Validate one host-produced local arm/gripper staging directory; "
            "release, field, delivery, hardware and real backends stay blocked."))
    parser.add_argument("--staging-dir", required=True)
    return parser


def main(argv=None):
    """Return 1 for a valid-but-blocked report or 2 for rejected input."""
    args = _parser().parse_args(argv)
    try:
        validate_aggregator_process_contract()
        report = aggregate_staging(args.staging_dir)
        status = 1
    except EvidenceRejected as error:
        report = _rejection_report(str(error), args.staging_dir)
        status = 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
