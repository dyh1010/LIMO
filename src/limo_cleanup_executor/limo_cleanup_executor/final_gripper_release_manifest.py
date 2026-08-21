#!/usr/bin/env python3
"""Validate the evidence-bound final replacement-gripper release manifest.

This module is deliberately limited to JSON and filesystem inputs.  It does
not import ROS, vendor libraries, serial libraries, or hardware backends.
"""

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath


SCHEMA_ID = "limo.final_gripper_release_manifest"
SCHEMA_VERSION = 4

SECTION_NAMES = (
    "tool_identity",
    "controller_firmware",
    "transport_protocol",
    "cad_sources",
    "units",
    "flange_tcp",
    "motion_limits",
    "mass_properties",
    "collision_cable_envelope",
    "electrical",
    "passive_power_loss_safety",
    "contact_human_safety",
    "durability_maintenance",
    "backend_execution_safety",
    "feedback_contract",
    "stop_stationary_ack",
    "transport_owner",
    "legacy_input_policy",
)

TOP_LEVEL_KEYS = (
    "schema_id",
    "schema_version",
    "manifest_id",
    "manifest_revision",
    "created_at_utc",
    "release_requested",
    "release_approved",
) + SECTION_NAMES + ("evidence_records",)

REVIEW_KEYS = (
    "reviewed",
    "evidence_ids",
    "reviewer",
    "reviewed_at_utc",
    "disposition",
)

EVIDENCE_KEYS = (
    "evidence_id",
    "sections",
    "source",
    "artifact",
    "artifact_sha256",
    "method",
    "result",
    "reviewer",
    "reviewed_at_utc",
    "applicability",
    "disposition",
)

ALLOWED_EVIDENCE_METHODS = {
    "CONTROLLED_DOCUMENT",
    "DE_ENERGIZED_STATIC_MEASUREMENT",
}

FEEDBACK_FIELD_NAMES = (
    "connected",
    "valid",
    "enabled",
    "moving",
    "opened_limit",
    "closed_limit",
    "normalized_position",
    "jaw_opening_m",
    "supply_voltage_v",
    "motor_current_a",
    "grip_force_n",
    "temperature_c",
    "fault_code",
)

MANDATORY_FEEDBACK_FIELDS = frozenset((
    "connected",
    "valid",
    "enabled",
    "moving",
    "normalized_position",
    "fault_code",
))

FEEDBACK_SUPPORT_VALUES = frozenset(("SUPPORTED", "UNSUPPORTED"))

EXPECTED_UNITS = {
    "length": "m",
    "angle": "rad",
    "mass": "kg",
    "inertia": "kg*m^2",
    "force": "N",
    "voltage": "V",
    "current": "A",
    "time": "s",
    "angular_velocity": "rad/s",
    "angular_acceleration": "rad/s^2",
}

HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

LEGACY_STRING_PATTERNS = (
    (
        "retired AG product identity",
        re.compile(r"mycobot[\s_-]*gripper[\s_-]*ag", re.IGNORECASE),
    ),
    (
        "retired AG gripper type",
        re.compile(r"gripper[\s_-]*type\s*[:=]\s*1\b", re.IGNORECASE),
    ),
    (
        "retired AG 0..100 range",
        re.compile(r"(?<!\d)0\s*(?:\.\.|[-~–—])\s*100(?!\d)"),
    ),
    (
        "retired 255 fully-open interpretation",
        re.compile(
            r"(?:\b255\b.{0,32}\b(?:fully[\s_-]*)?open\b|"
            r"\b(?:fully[\s_-]*)?open\b.{0,32}\b255\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "retired AG 20--45 mm opening",
        re.compile(
            r"\b20\s*(?:\.\.|[-~–—]{1,2})\s*45\s*mm\b",
            re.IGNORECASE,
        ),
    ),
    (
        "historical or generated mass assumption",
        re.compile(r"\b(?:100|115|170)\s*g\b", re.IGNORECASE),
    ),
    (
        "generated staging geometry",
        re.compile(r"\b(?:68\.84|34\.42)\s*mm\b", re.IGNORECASE),
    ),
    (
        "generated staging TCP",
        re.compile(
            r"\(?\s*0(?:\.0+)?\s*,\s*0\.0931\s*,\s*0\.0025\s*\)?"
        ),
    ),
    (
        "unreviewed torque register assumption",
        re.compile(
            r"gripper[\s_-]*torque\s*[:=]\s*500\b", re.IGNORECASE
        ),
    ),
    (
        "unreviewed protection-current register assumption",
        re.compile(
            r"protect[\s_-]*current\s*[:=]\s*200\b", re.IGNORECASE
        ),
    ),
    (
        "generic servo identity guess",
        re.compile(r"\b(?:sg90|mg90s|mg996r)\b", re.IGNORECASE),
    ),
    (
        "retired Atom or shared-arm transport",
        re.compile(
            r"(?:\batom\b|\bshared[\s_-]*arm(?:[\s_-]*transport)?\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "generic or hobby servo identity guess",
        re.compile(
            r"(?:"
            r"\b(?:generic|hobby|rc|unbranded|unknown)\b.{0,24}"
            r"\bservo(?:motor)?\b|"
            r"\bservo(?:motor)?\b.{0,24}"
            r"\b(?:generic|hobby|rc|unbranded|unknown)\b|"
            r"(?:通用|航模|模型|无品牌|未知).{0,8}舵机|"
            r"舵机.{0,8}(?:通用|航模|模型|无品牌|未知)"
            r")",
            re.IGNORECASE,
        ),
    ),
)

BACKEND_EXECUTION_ARTIFACT_FIELDS = (
    "backend_method_contract_sha256",
    "stop_isolation_architecture_sha256",
    "hung_command_stop_test_report_sha256",
)

BACKEND_METHOD_NAMES = (
    "read_state",
    "command_position",
    "stop",
    "close",
)

BACKEND_EXECUTION_ARTIFACT_MAX_BYTES = 128 * 1024


def _normalize_legacy_scan_text(value):
    """Return a compatibility-normalized string for denylist matching.

    Safety evidence may contain non-ASCII prose, so the validator does not
    reject Unicode globally.  It does, however, normalize compatibility
    characters (including full-width Latin letters/digits), case-fold text,
    remove formatting controls that can split a token, and canonicalize dash
    punctuation before applying the retired-input denylist.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold()
    resolved = []
    for character in normalized:
        category = unicodedata.category(character)
        if category == "Cf":
            continue
        if category == "Pd" or character in ("\N{MINUS SIGN}", "\N{SMALL HYPHEN-MINUS}"):
            resolved.append("-")
        elif character.isspace():
            resolved.append(" ")
        else:
            resolved.append(character)
    return "".join(resolved)

WINDOWS_RESERVED_PATH_NAMES = frozenset(
    ("CON", "PRN", "AUX", "NUL", "CLOCK$")
    + tuple("COM{}".format(index) for index in range(1, 10))
    + tuple("LPT{}".format(index) for index in range(1, 10))
)


class ManifestLoadError(ValueError):
    """Raised when strict JSON decoding cannot produce a manifest."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ManifestIssue:
    """One deterministic schema error or release blocker."""

    code: str
    path: str
    message: str

    def as_dict(self):
        """Return a JSON-safe issue representation."""
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class ManifestValidationResult:
    """Schema and release-gate result for one manifest."""

    errors: tuple
    blockers: tuple

    @property
    def schema_valid(self):
        """Return whether the manifest satisfies the strict schema."""
        return not self.errors

    @property
    def release_ready(self):
        """Return whether no schema error or release blocker remains."""
        return not self.errors and not self.blockers

    def as_dict(self):
        """Return a deterministic JSON-safe validation report."""
        return {
            "schema_id": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "schema_valid": self.schema_valid,
            "release_ready": self.release_ready,
            "error_count": len(self.errors),
            "blocker_count": len(self.blockers),
            "errors": [item.as_dict() for item in self.errors],
            "blockers": [item.as_dict() for item in self.blockers],
        }


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ManifestLoadError(
                "DUPLICATE_KEY",
                "duplicate JSON object key: {}".format(key),
            )
        value[key] = item
    return value


def _reject_json_constant(value):
    raise ManifestLoadError(
        "NON_FINITE_JSON_NUMBER",
        "non-finite JSON number is forbidden: {}".format(value),
    )


def loads_manifest(text):
    """Decode one manifest using strict duplicate and number handling."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ManifestLoadError:
        raise
    except json.JSONDecodeError as error:
        raise ManifestLoadError(
            "INVALID_JSON",
            "invalid JSON at line {}, column {}: {}".format(
                error.lineno,
                error.colno,
                error.msg,
            ),
        )


def load_manifest(path):
    """Read and strictly decode a UTF-8 manifest path."""
    manifest_path = Path(path)
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ManifestLoadError(
            "MANIFEST_READ_FAILED",
            "cannot read manifest {}: {}".format(manifest_path, error),
        )
    return loads_manifest(text)


def canonical_cad_inventory_sha256(files):
    """Hash the canonical UTF-8 JSON representation of CAD file entries."""
    payload = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path):
    """Hash one explicitly selected local file without loading it at once."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _validation_result(errors=(), blockers=()):
    key = lambda item: (item.path, item.code, item.message)
    return ManifestValidationResult(
        errors=tuple(sorted(set(errors), key=key)),
        blockers=tuple(sorted(set(blockers), key=key)),
    )


def _merge_validation_results(*results):
    errors = []
    blockers = []
    for result in results:
        errors.extend(result.errors)
        blockers.extend(result.blockers)
    return _validation_result(errors=errors, blockers=blockers)


def _binding_block(blockers, code, path, message):
    blockers.append(ManifestIssue(code, path, message))


def _safe_binding_relative_path(value):
    if type(value) is not str or not value.strip():
        return False, "path must be a non-empty string"
    if "\\" in value or "\x00" in value:
        return False, "path must use normalized forward slashes"
    if re.match(r"^[A-Za-z]:", value):
        return False, "drive-qualified path is forbidden"
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(
            part in ("", ".", "..") for part in parsed.parts):
        return False, "path must be normalized and relative"
    for part in parsed.parts:
        if ":" in part or part.endswith((" ", ".")):
            return False, "alternate-stream and ambiguous path syntax is forbidden"
        reserved_name = part.split(".", 1)[0].upper()
        if reserved_name in WINDOWS_RESERVED_PATH_NAMES:
            return False, "reserved device path component is forbidden"
    return True, None


def _prepare_binding_root(value, label, blockers):
    issue_path = "$.__binding__.{}_root".format(label)
    required_code = "{}_ROOT_REQUIRED".format(label.upper())
    if value is None:
        _binding_block(
            blockers,
            required_code,
            issue_path,
            "an explicit local {} root is required".format(label),
        )
        return None
    if not isinstance(value, (str, Path)):
        _binding_block(
            blockers,
            "{}_ROOT_INVALID".format(label.upper()),
            issue_path,
            "{} root must be a filesystem path".format(label),
        )
        return None
    raw = str(value)
    normalized = raw.replace("\\", "/").casefold()
    if (
            normalized == "/dev"
            or normalized.startswith("/dev/")
            or raw.startswith("\\\\.\\")
            or raw.startswith("\\\\?\\")):
        _binding_block(
            blockers,
            "{}_ROOT_UNSAFE".format(label.upper()),
            issue_path,
            "device and special namespace roots are forbidden",
        )
        return None
    root = Path(value)
    if not root.is_absolute():
        _binding_block(
            blockers,
            "{}_ROOT_NOT_ABSOLUTE".format(label.upper()),
            issue_path,
            "{} root must be absolute".format(label),
        )
        return None
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        _binding_block(
            blockers,
            "{}_ROOT_UNAVAILABLE".format(label.upper()),
            issue_path,
            "{} root is unavailable: {}".format(label, error),
        )
        return None
    if not resolved.is_dir():
        _binding_block(
            blockers,
            "{}_ROOT_NOT_DIRECTORY".format(label.upper()),
            issue_path,
            "{} root is not a directory".format(label),
        )
        return None
    return resolved


def _verify_bound_file(
        root, relative, expected_hash, path, label, blockers,
        expected_size=None, capture_bytes=False,
        capture_limit=BACKEND_EXECUTION_ARTIFACT_MAX_BYTES):
    safe, reason = _safe_binding_relative_path(relative)
    if not safe:
        _binding_block(
            blockers,
            "{}_PATH_UNSAFE".format(label.upper()),
            path,
            reason,
        )
        return None
    if type(expected_hash) is not str or HASH_PATTERN.fullmatch(
            expected_hash) is None:
        return None
    unresolved = root.joinpath(*PurePosixPath(relative).parts)
    try:
        if unresolved.is_symlink():
            _binding_block(
                blockers,
                "{}_SYMLINK_FORBIDDEN".format(label.upper()),
                path,
                "bound release files must not be symbolic links",
            )
            return None
    except OSError as error:
        _binding_block(
            blockers,
            "{}_FILE_READ_FAILED".format(label.upper()),
            path,
            "bound file metadata could not be read: {}".format(error),
        )
        return None
    try:
        candidate = unresolved.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        _binding_block(
            blockers,
            "{}_FILE_MISSING".format(label.upper()),
            path,
            "bound file is unavailable: {}".format(error),
        )
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        _binding_block(
            blockers,
            "{}_PATH_ESCAPE".format(label.upper()),
            path,
            "resolved path escapes its approved root",
        )
        return None
    if not candidate.is_file():
        _binding_block(
            blockers,
            "{}_PATH_NOT_FILE".format(label.upper()),
            path,
            "bound path is not an ordinary file",
        )
        return None
    captured = None
    try:
        stat = candidate.stat()
        if capture_bytes and stat.st_size <= capture_limit:
            captured = candidate.read_bytes()
            actual_hash = hashlib.sha256(captured).hexdigest()
        else:
            actual_hash = _file_sha256(candidate)
    except OSError as error:
        _binding_block(
            blockers,
            "{}_FILE_READ_FAILED".format(label.upper()),
            path,
            "bound file could not be read: {}".format(error),
        )
    if capture_bytes and stat.st_size > capture_limit:
        _binding_block(
            blockers,
            "BACKEND_EXECUTION_ARTIFACT_TOO_LARGE",
            path,
            "machine-readable backend execution evidence exceeds {} bytes"
            .format(capture_limit),
        )
        return None
    if type(expected_size) is int and stat.st_size != expected_size:
        _binding_block(
            blockers,
            "{}_FILE_SIZE_MISMATCH".format(label.upper()),
            path,
            "declared {} bytes but bound file has {}".format(
                expected_size, stat.st_size
            ),
        )
    if actual_hash.lower() != expected_hash.lower():
        _binding_block(
            blockers,
            "{}_FILE_HASH_MISMATCH".format(label.upper()),
            path,
            "bound file SHA-256 does not match the manifest",
        )
    if actual_hash.lower() != expected_hash.lower():
        captured = None
    result = {
        "path": relative,
        "sha256": actual_hash,
        "size_bytes": stat.st_size,
    }
    if capture_bytes:
        result["content"] = captured
    return result


def _declared_file_hashes(value, path="$"):
    """Yield every content hash claim that must bind to a real local file."""
    if type(value) is dict:
        for key in sorted(value):
            item_path = path + "." + key
            item = value[key]
            if (
                    key == "source_snapshot_sha256"
                    and path == "$.cad_sources"):
                continue
            if (
                    (key == "sha256" or key.endswith("_sha256"))
                    and type(item) is str
                    and HASH_PATTERN.fullmatch(item)):
                yield item_path, item.lower()
            yield from _declared_file_hashes(item, item_path)
    elif type(value) is list:
        for index, item in enumerate(value):
            yield from _declared_file_hashes(
                item, "{}[{}]".format(path, index)
            )


def _claim_top_level_section(path):
    if not path.startswith("$."):
        return None
    section = path[2:].split(".", 1)[0].split("[", 1)[0]
    return section if section in SECTION_NAMES else None


def _claim_is_cad_bound(path):
    return (
        path == "$.tool_identity.assembly_sha256"
        or path == "$.cad_sources.assembly_sha256"
        or path.startswith("$.cad_sources.files[")
    )


def _execution_artifact_block(blockers, code, path, message):
    _binding_block(blockers, code, path, message)


def _decode_execution_artifact(content, path, blockers):
    if content is None:
        _execution_artifact_block(
            blockers,
            "BACKEND_EXECUTION_ARTIFACT_UNAVAILABLE",
            path,
            "machine-readable backend execution evidence is unavailable",
        )
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        _execution_artifact_block(
            blockers,
            "BACKEND_EXECUTION_ARTIFACT_ENCODING_INVALID",
            path,
            "backend execution evidence must be canonical UTF-8 JSON",
        )
        return None
    try:
        value = loads_manifest(text)
    except ManifestLoadError as error:
        _execution_artifact_block(
            blockers,
            "BACKEND_EXECUTION_ARTIFACT_INVALID_JSON",
            path,
            "backend execution evidence is not strict JSON: {}".format(
                error.code),
        )
        return None
    if type(value) is not dict:
        _execution_artifact_block(
            blockers,
            "BACKEND_EXECUTION_ARTIFACT_SCHEMA_MISMATCH",
            path,
            "backend execution evidence must be an exact JSON object",
        )
        return None
    return value


def _artifact_exact_object(value, expected_keys, path, blockers, code):
    if (
            type(value) is not dict
            or any(type(key) is not str for key in value)
            or set(value) != set(expected_keys)):
        _execution_artifact_block(
            blockers,
            code,
            path,
            "machine-readable evidence keys do not match the exact contract",
        )
        return False
    return True


def _artifact_string(value):
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
    )


def _artifact_number(value):
    return (
        type(value) in (int, float)
        and math.isfinite(float(value))
    )


def _backend_execution_binding(manifest):
    backend = manifest.get("backend_execution_safety")
    if type(backend) is not dict:
        return None
    release = backend.get("release_binding")
    profile = backend.get("motion_profile_binding")
    if type(release) is not dict or type(profile) is not dict:
        return None
    expected = {
        "runtime_release_id": release.get("runtime_release_id"),
        "release_manifest_sha256": release.get("release_manifest_sha256"),
        "motion_profile_id": profile.get("profile_id"),
        "motion_profile_manifest_sha256": profile.get(
            "profile_manifest_sha256"),
        "approved_speed_grades": profile.get("approved_speed_grades"),
    }
    if (
            not all(_artifact_string(expected[key]) for key in (
                "runtime_release_id",
                "release_manifest_sha256",
                "motion_profile_id",
                "motion_profile_manifest_sha256",
            ))
            or type(expected["approved_speed_grades"]) is not list):
        return None
    return expected


def _validate_execution_binding(value, expected, path, blockers, code):
    keys = (
        "runtime_release_id",
        "release_manifest_sha256",
        "motion_profile_id",
        "motion_profile_manifest_sha256",
        "approved_speed_grades",
    )
    if not _artifact_exact_object(value, keys, path, blockers, code):
        return False
    if value != expected:
        _execution_artifact_block(
            blockers,
            "BACKEND_EXECUTION_BINDING_MISMATCH",
            path,
            "execution evidence does not exactly bind the active runtime, "
            "release manifest, motion profile and speed grades",
        )
        return False
    return True


def _validate_method_contract_artifact(
        value, manifest, expected_binding, path, blockers):
    code = "BACKEND_METHOD_CONTRACT_NOT_PROVEN"
    keys = ("schema_id", "schema_version", "binding", "methods")
    if not _artifact_exact_object(value, keys, path, blockers, code):
        return
    if (
            value.get("schema_id")
            != "limo.gripper_backend_method_contract"
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1):
        _execution_artifact_block(
            blockers, code, path,
            "backend method evidence schema is not the released version",
        )
        return
    if not _validate_execution_binding(
            value.get("binding"), expected_binding,
            path + ".binding", blockers, code):
        return
    methods = value.get("methods")
    if not _artifact_exact_object(
            methods, BACKEND_METHOD_NAMES, path + ".methods",
            blockers, code):
        return
    backend = manifest["backend_execution_safety"]
    for method in BACKEND_METHOD_NAMES:
        method_path = path + ".methods." + method
        contract = methods.get(method)
        contract_keys = (
            "deadline_s",
            "timeout_handling",
            "native_deadline_enforced",
            "native_timeout_implementation",
            "python_timeout_thread_used",
        )
        if not _artifact_exact_object(
                contract, contract_keys, method_path, blockers, code):
            continue
        deadline = contract.get("deadline_s")
        expected_deadline = backend["method_deadlines_s"].get(method)
        handling = contract.get("timeout_handling")
        expected_handling = backend["method_timeout_handling"].get(method)
        expected_implementation = {
            "CANCELLABLE": "NATIVE_CANCEL",
            "BOUNDED_ABANDONMENT": "NATIVE_BOUNDED_CALL",
        }.get(expected_handling)
        if (
                not _artifact_number(deadline)
                or float(deadline) <= 0.0
                or deadline != expected_deadline
                or type(handling) is not str
                or handling != expected_handling
                or contract.get("native_deadline_enforced") is not True
                or contract.get("native_timeout_implementation")
                != expected_implementation
                or contract.get("python_timeout_thread_used") is not False):
            _execution_artifact_block(
                blockers,
                code,
                method_path,
                "method deadline/cancellation evidence is not exact native "
                "bounded-call evidence",
            )


def _validate_stop_architecture_artifact(
        value, manifest, expected_binding, path, blockers):
    code = "STOP_ISOLATION_ARCHITECTURE_NOT_PROVEN"
    keys = (
        "schema_id",
        "schema_version",
        "binding",
        "motion_executor_id",
        "stop_executor_id",
        "motion_channel_id",
        "stop_channel_id",
        "motion_lock_domain_id",
        "stop_lock_domain_id",
        "independent_executor",
        "independent_channel",
        "independent_lock_domain",
        "stop_not_queued_behind_normal_commands",
        "shared_adapter_lock",
    )
    if not _artifact_exact_object(value, keys, path, blockers, code):
        return
    if (
            value.get("schema_id")
            != "limo.gripper_stop_isolation_architecture"
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1):
        _execution_artifact_block(
            blockers, code, path,
            "STOP isolation architecture schema is not the released version",
        )
        return
    if not _validate_execution_binding(
            value.get("binding"), expected_binding,
            path + ".binding", blockers, code):
        return
    identity_pairs = (
        ("motion_executor_id", "stop_executor_id"),
        ("motion_channel_id", "stop_channel_id"),
        ("motion_lock_domain_id", "stop_lock_domain_id"),
    )
    for normal_name, stop_name in identity_pairs:
        normal = value.get(normal_name)
        stop = value.get(stop_name)
        if (
                not _artifact_string(normal)
                or not _artifact_string(stop)
                or normal == stop):
            _execution_artifact_block(
                blockers,
                code,
                path + "." + stop_name,
                "motion and STOP executor/channel/lock identities must be "
                "exact, non-empty and different",
            )
    isolation = manifest["backend_execution_safety"]["stop_isolation"]
    if (
            value.get("independent_executor") is not True
            or value.get("independent_channel") is not True
            or value.get("independent_lock_domain") is not True
            or value.get("stop_not_queued_behind_normal_commands") is not True
            or value.get("shared_adapter_lock") is not False
            or value.get("independent_executor")
            is not isolation.get("independent_executor")
            or value.get("independent_lock_domain")
            is not isolation.get("independent_lock_domain")
            or value.get("stop_not_queued_behind_normal_commands")
            is not isolation.get("not_queued_behind_normal_commands")):
        _execution_artifact_block(
            blockers,
            code,
            path,
            "STOP must use a distinct executor, channel and lock domain and "
            "must not share the ordinary adapter lock or queue",
        )


def _validate_hung_stop_report_artifact(
        value, manifest, expected_binding, path, blockers):
    code = "HUNG_COMMAND_STOP_PROBE_NOT_PROVEN"
    keys = (
        "schema_id",
        "schema_version",
        "binding",
        "command_method",
        "command_call_id",
        "stop_call_id",
        "motion_send_entered_at_s",
        "stop_requested_at_s",
        "stop_completed_at_s",
        "motion_send_released_at_s",
        "stop_deadline_s",
        "stop_completed",
        "stop_completed_before_send_release",
        "late_command_result_rejected",
        "deadline_miss_fails_closed",
        "physical_isolation_required_on_failure",
        "final_state",
    )
    if not _artifact_exact_object(value, keys, path, blockers, code):
        return
    if (
            value.get("schema_id")
            != "limo.gripper_hung_command_stop_report"
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1):
        _execution_artifact_block(
            blockers, code, path,
            "hung-command STOP report schema is not the released version",
        )
        return
    if not _validate_execution_binding(
            value.get("binding"), expected_binding,
            path + ".binding", blockers, code):
        return
    numeric_names = (
        "motion_send_entered_at_s",
        "stop_requested_at_s",
        "stop_completed_at_s",
        "motion_send_released_at_s",
        "stop_deadline_s",
    )
    if any(
            not _artifact_number(value.get(name))
            or float(value.get(name)) < 0.0
            for name in numeric_names):
        _execution_artifact_block(
            blockers, code, path,
            "hung-command STOP report timestamps/deadline must be finite and "
            "non-negative",
        )
        return
    entered = float(value["motion_send_entered_at_s"])
    requested = float(value["stop_requested_at_s"])
    completed = float(value["stop_completed_at_s"])
    released = float(value["motion_send_released_at_s"])
    deadline = float(value["stop_deadline_s"])
    expected_deadline = manifest["backend_execution_safety"][
        "stop_isolation"]["hung_command_stop_deadline_s"]
    if (
            value.get("command_method") != "command_position"
            or not _artifact_string(value.get("command_call_id"))
            or not _artifact_string(value.get("stop_call_id"))
            or value.get("command_call_id") == value.get("stop_call_id")
            or not entered <= requested <= completed < released
            or deadline <= 0.0
            or value.get("stop_deadline_s") != expected_deadline
            or completed - requested > deadline
            or value.get("stop_completed") is not True
            or value.get("stop_completed_before_send_release") is not True
            or value.get("late_command_result_rejected") is not True
            or value.get("deadline_miss_fails_closed") is not True
            or value.get("physical_isolation_required_on_failure") is not True
            or value.get("final_state") != "FAULT_LATCHED"):
        _execution_artifact_block(
            blockers,
            code,
            path,
            "hung motion send did not prove bounded independent STOP, late "
            "result rejection and fail-closed physical escalation",
        )


def _validate_backend_execution_artifacts(
        manifest, payloads_by_hash, blockers):
    backend = manifest.get("backend_execution_safety")
    expected_binding = _backend_execution_binding(manifest)
    if type(backend) is not dict or expected_binding is None:
        return
    validators = {
        "backend_method_contract_sha256":
            _validate_method_contract_artifact,
        "stop_isolation_architecture_sha256":
            _validate_stop_architecture_artifact,
        "hung_command_stop_test_report_sha256":
            _validate_hung_stop_report_artifact,
    }
    for field in BACKEND_EXECUTION_ARTIFACT_FIELDS:
        path = "$.backend_execution_safety." + field
        artifact_hash = backend.get(field)
        if (
                type(artifact_hash) is not str
                or HASH_PATTERN.fullmatch(artifact_hash) is None):
            continue
        content = payloads_by_hash.get(artifact_hash.lower())
        value = _decode_execution_artifact(content, path, blockers)
        if value is not None:
            validators[field](
                value, manifest, expected_binding, path, blockers)


def validate_manifest_bindings(manifest, artifact_root=None, cad_root=None):
    """Bind reviewed claims to explicitly selected, disconnected local files."""
    blockers = []
    artifact_path = _prepare_binding_root(
        artifact_root, "artifact", blockers
    )
    cad_path = _prepare_binding_root(cad_root, "cad", blockers)
    if type(manifest) is not dict:
        _binding_block(
            blockers,
            "MANIFEST_UNAVAILABLE_FOR_BINDING",
            "$",
            "a decoded manifest object is required for file binding",
        )
        return _validation_result(blockers=blockers)

    bound_hashes = set()
    evidence_hash_sections = {}
    execution_payloads_by_hash = {}
    neutral_hashes = set()
    cad_hashes = set()
    execution_claim_hashes = set()
    backend = manifest.get("backend_execution_safety")
    if type(backend) is dict:
        for field in BACKEND_EXECUTION_ARTIFACT_FIELDS:
            value = backend.get(field)
            if type(value) is str and HASH_PATTERN.fullmatch(value):
                execution_claim_hashes.add(value.lower())
    if artifact_path is not None:
        records = manifest.get("evidence_records")
        if type(records) is list:
            for index, record in enumerate(records):
                if type(record) is not dict:
                    continue
                record_hash = record.get("artifact_sha256")
                capture_execution = (
                    type(record_hash) is str
                    and HASH_PATTERN.fullmatch(record_hash) is not None
                    and record_hash.lower() in execution_claim_hashes
                )
                actual = _verify_bound_file(
                    artifact_path,
                    record.get("artifact"),
                    record_hash,
                    "$.evidence_records[{}].artifact".format(index),
                    "artifact",
                    blockers,
                    capture_bytes=capture_execution,
                )
                if actual is not None:
                    actual_hash = actual["sha256"].lower()
                    bound_hashes.add(actual_hash)
                    sections = record.get("sections")
                    if type(sections) is list:
                        evidence_hash_sections.setdefault(
                            actual_hash, set()
                        ).update(
                            section for section in sections
                            if section in SECTION_NAMES
                        )
                    if (
                            capture_execution
                            and actual.get("content") is not None):
                        execution_payloads_by_hash[
                            actual_hash] = actual["content"]
        cad = manifest.get("cad_sources")
        if type(cad) is dict:
            actual = _verify_bound_file(
                artifact_path,
                cad.get("neutral_assembly_path"),
                cad.get("neutral_assembly_sha256"),
                "$.cad_sources.neutral_assembly_path",
                "artifact",
                blockers,
            )
            if actual is not None:
                actual_hash = actual["sha256"].lower()
                bound_hashes.add(actual_hash)
                neutral_hashes.add(actual_hash)

    if cad_path is not None:
        cad = manifest.get("cad_sources")
        declared_paths = set()
        actual_entries = []
        if type(cad) is dict and type(cad.get("files")) is list:
            for index, entry in enumerate(cad["files"]):
                if type(entry) is not dict:
                    continue
                relative = entry.get("path")
                if type(relative) is str:
                    declared_paths.add(relative)
                actual = _verify_bound_file(
                    cad_path,
                    relative,
                    entry.get("sha256"),
                    "$.cad_sources.files[{}].path".format(index),
                    "cad",
                    blockers,
                    expected_size=entry.get("size_bytes"),
                )
                if actual is not None:
                    actual["role"] = entry.get("role")
                    actual_entries.append(actual)
                    actual_hash = actual["sha256"].lower()
                    bound_hashes.add(actual_hash)
                    cad_hashes.add(actual_hash)
            try:
                actual_paths = set()
                for item in cad_path.rglob("*"):
                    relative = item.relative_to(cad_path).as_posix()
                    if item.is_symlink():
                        _binding_block(
                            blockers,
                            "CAD_ROOT_SYMLINK_FORBIDDEN",
                            "$.__binding__.cad_root",
                            "CAD root contains symbolic link: {}".format(
                                relative
                            ),
                        )
                    elif item.is_dir():
                        continue
                    elif item.is_file():
                        actual_paths.add(relative)
                    else:
                        _binding_block(
                            blockers,
                            "CAD_ROOT_SPECIAL_ENTRY_FORBIDDEN",
                            "$.__binding__.cad_root",
                            "CAD root contains non-file entry: {}".format(
                                relative
                            ),
                        )
            except OSError as error:
                _binding_block(
                    blockers,
                    "CAD_ROOT_ENUMERATION_FAILED",
                    "$.__binding__.cad_root",
                    "CAD root inventory could not be read: {}".format(error),
                )
            else:
                for relative in sorted(actual_paths - declared_paths):
                    _binding_block(
                        blockers,
                        "CAD_ROOT_UNDECLARED_FILE",
                        "$.__binding__.cad_root",
                        "CAD root contains undeclared file: {}".format(
                            relative
                        ),
                    )
            if len(actual_entries) == len(cad["files"]):
                actual_entries.sort(key=lambda item: item["path"])
                declared_snapshot = cad.get("source_snapshot_sha256")
                if (
                        type(declared_snapshot) is str
                        and HASH_PATTERN.fullmatch(declared_snapshot)
                        and canonical_cad_inventory_sha256(actual_entries)
                        != declared_snapshot.lower()):
                    _binding_block(
                        blockers,
                        "CAD_BOUND_SNAPSHOT_MISMATCH",
                        "$.cad_sources.source_snapshot_sha256",
                        "bound CAD inventory digest does not match manifest",
                    )
    for claim_path, claim_hash in _declared_file_hashes(manifest):
        if claim_path.startswith("$.evidence_records["):
            claim_bound = claim_hash in evidence_hash_sections
            scope_mismatch = False
        elif _claim_is_cad_bound(claim_path):
            claim_bound = claim_hash in cad_hashes
            scope_mismatch = False
        elif claim_path == "$.cad_sources.neutral_assembly_sha256":
            claim_bound = claim_hash in neutral_hashes
            scope_mismatch = False
        else:
            section = _claim_top_level_section(claim_path)
            allowed_sections = evidence_hash_sections.get(claim_hash, set())
            claim_bound = section is not None and section in allowed_sections
            scope_mismatch = (
                claim_hash in bound_hashes
                and section is not None
                and section not in allowed_sections
            )
        if not claim_bound:
            if scope_mismatch:
                code = "HASH_EVIDENCE_SCOPE_MISMATCH"
                message = (
                    "declared SHA-256 is bound to a real file, but its "
                    "evidence record does not cover this manifest section"
                )
            else:
                code = "UNBOUND_DECLARED_HASH"
                message = (
                    "declared SHA-256 is not bound to an approved local "
                    "artifact for this claim"
                )
            _binding_block(
                blockers,
                code,
                claim_path,
                message,
            )
    _validate_backend_execution_artifacts(
        manifest, execution_payloads_by_hash, blockers)
    return _validation_result(blockers=blockers)


class _Validator:
    def __init__(self):
        self.errors = []
        self.blockers = []
        self.reviews = []
        self.evidence = {}

    def error(self, code, path, message):
        self.errors.append(ManifestIssue(code, path, message))

    def block(self, code, path, message):
        self.blockers.append(ManifestIssue(code, path, message))

    def exact_object(self, value, path, keys):
        if type(value) is not dict:
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected object, got {}".format(type(value).__name__),
            )
            return False
        expected = set(keys)
        actual = set(value)
        for key in sorted(expected - actual):
            self.error(
                "MISSING_KEY",
                path + "." + key,
                "required key is missing",
            )
        for key in sorted(actual - expected):
            self.error(
                "UNKNOWN_KEY",
                path + "." + key,
                "unknown key is forbidden",
            )
        return not (expected - actual or actual - expected)

    def boolean(self, value, path):
        if type(value) is not bool:
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected boolean, got {}".format(type(value).__name__),
            )
            return False
        return True

    def integer(self, value, path, minimum=None):
        if type(value) is not int:
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected integer, got {}".format(type(value).__name__),
            )
            return False
        if minimum is not None and value < minimum:
            self.error(
                "VALUE_OUT_OF_RANGE",
                path,
                "value must be at least {}".format(minimum),
            )
            return False
        return True

    def nullable_integer(
            self, value, path, code="REQUIRED_VALUE_UNKNOWN",
            minimum=None):
        if value is None:
            self.block(
                code,
                path,
                "required reviewed integer value is unknown",
            )
            return False
        return self.integer(value, path, minimum=minimum)

    def number(self, value, path, minimum=None, strictly_positive=False):
        if type(value) not in (int, float):
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected number, got {}".format(type(value).__name__),
            )
            return False
        if not math.isfinite(value):
            self.error("NON_FINITE_NUMBER", path, "number must be finite")
            return False
        if strictly_positive and value <= 0:
            self.error(
                "VALUE_OUT_OF_RANGE", path, "value must be greater than zero"
            )
            return False
        if minimum is not None and value < minimum:
            self.error(
                "VALUE_OUT_OF_RANGE",
                path,
                "value must be at least {}".format(minimum),
            )
            return False
        return True

    def nullable_number(
            self, value, path, code="REQUIRED_VALUE_UNKNOWN",
            minimum=None, strictly_positive=False):
        if value is None:
            self.block(
                code,
                path,
                "required reviewed numeric value is unknown",
            )
            return False
        return self.number(
            value,
            path,
            minimum=minimum,
            strictly_positive=strictly_positive,
        )

    def nullable_string(
            self, value, path, code="REQUIRED_VALUE_UNKNOWN"):
        if value is None:
            self.block(code, path, "required reviewed string value is unknown")
            return False
        if type(value) is not str:
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected string or null, got {}".format(
                    type(value).__name__
                ),
            )
            return False
        if not value.strip():
            self.error("EMPTY_STRING", path, "string must not be empty")
            return False
        return True

    def nullable_enum(
            self, value, path, allowed,
            code="REQUIRED_VALUE_UNKNOWN"):
        if not self.nullable_string(value, path, code=code):
            return False
        if value not in allowed:
            self.error(
                "INVALID_ENUM",
                path,
                "value must be one of: {}".format(
                    ", ".join(sorted(allowed))
                ),
            )
            return False
        return True

    def required_string(self, value, path):
        if type(value) is not str:
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected string, got {}".format(type(value).__name__),
            )
            return False
        if not value.strip():
            self.error("EMPTY_STRING", path, "string must not be empty")
            return False
        return True

    def hash_value(
            self, value, path, required=True,
            unknown_code="REQUIRED_VALUE_UNKNOWN"):
        if value is None:
            if required:
                self.block(
                    unknown_code,
                    path,
                    "required reviewed SHA-256 value is unknown",
                )
            return False
        if type(value) is not str:
            self.error(
                "TYPE_MISMATCH",
                path,
                "expected SHA-256 string or null, got {}".format(
                    type(value).__name__
                ),
            )
            return False
        if HASH_PATTERN.fullmatch(value) is None:
            self.error(
                "INVALID_HASH",
                path,
                "SHA-256 must contain exactly 64 hexadecimal characters",
            )
            return False
        return True

    def timestamp(self, value, path, required=True):
        if value is None:
            if required:
                self.block(
                    "REQUIRED_VALUE_UNKNOWN",
                    path,
                    "required UTC review timestamp is unknown",
                )
            return False
        if type(value) is not str or UTC_PATTERN.fullmatch(value) is None:
            self.error(
                "INVALID_UTC_TIMESTAMP",
                path,
                "timestamp must use YYYY-MM-DDTHH:MM:SSZ",
            )
            return False
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            self.error(
                "INVALID_UTC_TIMESTAMP",
                path,
                "timestamp contains an invalid calendar date or time",
            )
            return False
        return True

    def required_assertion(
            self, value, path, expected=True,
            code="REQUIRED_ASSERTION_FALSE"):
        if not self.boolean(value, path):
            return False
        if value is not expected:
            self.block(
                code,
                path,
                "release requires the reviewed value {!r}".format(expected),
            )
            return False
        return True

    def review(self, section, value, path):
        if not self.exact_object(value, path, REVIEW_KEYS):
            return
        reviewed = value.get("reviewed")
        self.boolean(reviewed, path + ".reviewed")
        evidence_ids = value.get("evidence_ids")
        if type(evidence_ids) is not list:
            self.error(
                "TYPE_MISMATCH",
                path + ".evidence_ids",
                "expected array of evidence IDs",
            )
        else:
            for index, evidence_id in enumerate(evidence_ids):
                self.required_string(
                    evidence_id,
                    "{}[{}]".format(path + ".evidence_ids", index),
                )
            if len(evidence_ids) != len(set(
                    item for item in evidence_ids if type(item) is str)):
                self.error(
                    "DUPLICATE_EVIDENCE_REFERENCE",
                    path + ".evidence_ids",
                    "evidence references must be unique",
                )
        reviewer = value.get("reviewer")
        reviewed_at = value.get("reviewed_at_utc")
        disposition = value.get("disposition")
        if reviewer is not None:
            self.required_string(reviewer, path + ".reviewer")
        if reviewed_at is not None:
            self.timestamp(reviewed_at, path + ".reviewed_at_utc")
        if disposition not in (None, "ACCEPTED", "REJECTED"):
            self.error(
                "INVALID_ENUM",
                path + ".disposition",
                "disposition must be ACCEPTED, REJECTED, or null",
            )
        if reviewed is False:
            self.block(
                "REVIEW_INCOMPLETE",
                path + ".reviewed",
                "section has not been reviewed",
            )
        elif reviewed is True:
            if type(evidence_ids) is list and not evidence_ids:
                self.block(
                    "REVIEW_EVIDENCE_MISSING",
                    path + ".evidence_ids",
                    "reviewed section requires evidence",
                )
            if reviewer is None:
                self.block(
                    "REVIEWER_UNKNOWN",
                    path + ".reviewer",
                    "reviewed section requires a reviewer",
                )
            if reviewed_at is None:
                self.block(
                    "REVIEW_TIME_UNKNOWN",
                    path + ".reviewed_at_utc",
                    "reviewed section requires a UTC timestamp",
                )
            if disposition != "ACCEPTED":
                self.block(
                    "REVIEW_NOT_ACCEPTED",
                    path + ".disposition",
                    "release requires an ACCEPTED section review",
                )
        self.reviews.append((section, path, value))

    def range_object(self, value, path, minimum=None):
        if value is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                path,
                "required reviewed range is unknown",
            )
            return None
        if not self.exact_object(value, path, ("minimum", "maximum")):
            return None
        low = value.get("minimum")
        high = value.get("maximum")
        low_ok = self.number(low, path + ".minimum", minimum=minimum)
        high_ok = self.number(high, path + ".maximum", minimum=minimum)
        if low_ok and high_ok and low >= high:
            self.error(
                "INVALID_RANGE",
                path,
                "minimum must be strictly less than maximum",
            )
        return value if low_ok and high_ok else None

    def vector(self, value, path, length):
        if type(value) is not list:
            self.error("TYPE_MISMATCH", path, "expected numeric array")
            return False
        if len(value) != length:
            self.error(
                "INVALID_VECTOR_LENGTH",
                path,
                "expected {} elements".format(length),
            )
            return False
        return all(
            self.number(item, "{}[{}]".format(path, index))
            for index, item in enumerate(value)
        )

    def transform(self, value, path):
        if value is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                path,
                "required reviewed 6D transform is unknown",
            )
            return None
        keys = ("translation_m", "rotation_xyzw")
        if not self.exact_object(value, path, keys):
            return None
        translation_ok = self.vector(
            value.get("translation_m"), path + ".translation_m", 3
        )
        quaternion = value.get("rotation_xyzw")
        quaternion_ok = self.vector(
            quaternion, path + ".rotation_xyzw", 4
        )
        if quaternion_ok:
            norm = math.sqrt(sum(item * item for item in quaternion))
            if abs(norm - 1.0) > 1e-3:
                self.error(
                    "INVALID_QUATERNION",
                    path + ".rotation_xyzw",
                    "quaternion norm must be within 0.001 of one",
                )
                quaternion_ok = False
        return value if translation_ok and quaternion_ok else None

    def aabb(self, value, path, frame_names):
        if value is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                path,
                "required reviewed envelope is unknown",
            )
            return None
        keys = ("frame", "minimum_m", "maximum_m", "artifact_sha256")
        if not self.exact_object(value, path, keys):
            return None
        frame = value.get("frame")
        frame_ok = self.required_string(frame, path + ".frame")
        if frame_ok and frame not in frame_names:
            self.error(
                "UNKNOWN_FRAME",
                path + ".frame",
                "envelope frame must name a declared gripper frame",
            )
            frame_ok = False
        low = value.get("minimum_m")
        high = value.get("maximum_m")
        low_ok = self.vector(low, path + ".minimum_m", 3)
        high_ok = self.vector(high, path + ".maximum_m", 3)
        if low_ok and high_ok:
            for index, (minimum, maximum) in enumerate(zip(low, high)):
                if minimum >= maximum:
                    self.error(
                        "INVALID_ENVELOPE",
                        "{}[{}]".format(path, index),
                        "every envelope minimum must be below its maximum",
                    )
        hash_ok = self.hash_value(
            value.get("artifact_sha256"), path + ".artifact_sha256"
        )
        return value if frame_ok and low_ok and high_ok and hash_ok else None

    def validate_evidence(self, records):
        path = "$.evidence_records"
        if type(records) is not list:
            self.error("TYPE_MISMATCH", path, "expected evidence array")
            return
        for index, record in enumerate(records):
            item_path = "{}[{}]".format(path, index)
            if not self.exact_object(record, item_path, EVIDENCE_KEYS):
                continue
            evidence_id = record.get("evidence_id")
            if self.required_string(evidence_id, item_path + ".evidence_id"):
                if evidence_id in self.evidence:
                    self.error(
                        "DUPLICATE_EVIDENCE_ID",
                        item_path + ".evidence_id",
                        "evidence ID must be unique",
                    )
                else:
                    self.evidence[evidence_id] = record
            sections = record.get("sections")
            if type(sections) is not list:
                self.error(
                    "TYPE_MISMATCH",
                    item_path + ".sections",
                    "expected non-empty section array",
                )
            else:
                if not sections:
                    self.error(
                        "EMPTY_EVIDENCE_SCOPE",
                        item_path + ".sections",
                        "evidence must apply to at least one section",
                    )
                for section_index, section in enumerate(sections):
                    section_path = "{}[{}]".format(
                        item_path + ".sections", section_index
                    )
                    if self.required_string(section, section_path):
                        if section not in SECTION_NAMES:
                            self.error(
                                "UNKNOWN_EVIDENCE_SECTION",
                                section_path,
                                "evidence names an unknown section",
                            )
                if len(sections) != len(set(
                        item for item in sections if type(item) is str)):
                    self.error(
                        "DUPLICATE_EVIDENCE_SECTION",
                        item_path + ".sections",
                        "evidence section names must be unique",
                    )
            for key in (
                    "source", "artifact", "result", "reviewer",
                    "applicability"):
                self.required_string(record.get(key), item_path + "." + key)
            self.hash_value(
                record.get("artifact_sha256"),
                item_path + ".artifact_sha256",
            )
            method = record.get("method")
            if self.required_string(method, item_path + ".method"):
                if method not in ALLOWED_EVIDENCE_METHODS:
                    self.error(
                        "INVALID_EVIDENCE_METHOD",
                        item_path + ".method",
                        "method must be controlled-document or "
                        "de-energized static measurement",
                    )
            self.timestamp(
                record.get("reviewed_at_utc"),
                item_path + ".reviewed_at_utc",
            )
            disposition = record.get("disposition")
            if disposition not in ("ACCEPTED", "REJECTED"):
                self.error(
                    "INVALID_ENUM",
                    item_path + ".disposition",
                    "evidence disposition must be ACCEPTED or REJECTED",
                )

    def validate_review_references(self):
        referenced = set()
        for section, path, review in self.reviews:
            evidence_ids = review.get("evidence_ids")
            if type(evidence_ids) is not list:
                continue
            for evidence_id in evidence_ids:
                if type(evidence_id) is not str:
                    continue
                referenced.add(evidence_id)
                record = self.evidence.get(evidence_id)
                if record is None:
                    self.error(
                        "UNKNOWN_EVIDENCE_ID",
                        path + ".evidence_ids",
                        "unknown evidence reference: {}".format(evidence_id),
                    )
                    continue
                if section not in record.get("sections", []):
                    self.error(
                        "EVIDENCE_SCOPE_MISMATCH",
                        path + ".evidence_ids",
                        "evidence {} does not cover {}".format(
                            evidence_id, section
                        ),
                    )
                if record.get("disposition") != "ACCEPTED":
                    self.block(
                        "EVIDENCE_NOT_ACCEPTED",
                        path + ".evidence_ids",
                        "referenced evidence {} is not accepted".format(
                            evidence_id
                        ),
                    )
        for evidence_id in sorted(set(self.evidence) - referenced):
            self.error(
                "ORPHAN_EVIDENCE",
                "$.evidence_records",
                "evidence is not referenced by a section: {}".format(
                    evidence_id
                ),
            )

    def validate_tool_identity(self, value):
        path = "$.tool_identity"
        keys = (
            "tool_model",
            "tool_revision",
            "assembly_configuration",
            "serial_or_lot",
            "tool_architecture",
            "complete_replacement",
            "legacy_ag_components_retained",
            "ag_retention_map_sha256",
            "assembly_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "tool_model", "tool_revision", "assembly_configuration",
                "serial_or_lot"):
            self.nullable_string(value.get(key), path + "." + key)
        self.nullable_enum(
            value.get("tool_architecture"),
            path + ".tool_architecture",
            ("COMPLETE_REPLACEMENT",),
            code="TOOL_ARCHITECTURE_UNRESOLVED",
        )
        self.required_assertion(
            value.get("complete_replacement"),
            path + ".complete_replacement",
        )
        self.required_assertion(
            value.get("legacy_ag_components_retained"),
            path + ".legacy_ag_components_retained",
            expected=False,
            code="LEGACY_AG_RETENTION_UNRESOLVED",
        )
        retention_map = value.get("ag_retention_map_sha256")
        self.hash_value(
            retention_map,
            path + ".ag_retention_map_sha256",
            required=False,
        )
        if retention_map is not None:
            self.error(
                "AG_RETENTION_MAP_FORBIDDEN_FOR_REPLACEMENT",
                path + ".ag_retention_map_sha256",
                "this manifest is replacement-only; original-AG evidence "
                "must use a separate AG-specific release package",
            )
        self.hash_value(
            value.get("assembly_sha256"), path + ".assembly_sha256"
        )
        self.review("tool_identity", value.get("review"), path + ".review")

    def validate_controller_firmware(self, value):
        path = "$.controller_firmware"
        keys = (
            "actuator_manufacturer",
            "actuator_model",
            "actuator_hardware_revision",
            "controller_manufacturer",
            "controller_model",
            "controller_hardware_revision",
            "controller_serial",
            "firmware_revision",
            "compatibility_matrix_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "actuator_manufacturer", "actuator_model",
                "actuator_hardware_revision", "controller_manufacturer",
                "controller_model", "controller_hardware_revision",
                "controller_serial"):
            self.nullable_string(value.get(key), path + "." + key)
        self.nullable_string(
            value.get("firmware_revision"),
            path + ".firmware_revision",
            code="FIRMWARE_REVISION_UNKNOWN",
        )
        self.hash_value(
            value.get("compatibility_matrix_sha256"),
            path + ".compatibility_matrix_sha256",
        )
        self.review(
            "controller_firmware", value.get("review"), path + ".review"
        )

    def validate_transport_protocol(self, value):
        path = "$.transport_protocol"
        keys = (
            "transport_type",
            "physical_layer_specification",
            "protocol_name",
            "protocol_revision",
            "protocol_definition_sha256",
            "native_command_unit",
            "timing_and_addressing_specification",
            "frame_and_integrity_specification",
            "ack_nak_specification",
            "command_id_specification",
            "ordering_and_replay_specification",
            "watchdog_and_disconnect_specification",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "transport_type", "physical_layer_specification",
                "protocol_name", "protocol_revision", "native_command_unit",
                "timing_and_addressing_specification",
                "frame_and_integrity_specification", "ack_nak_specification",
                "command_id_specification",
                "ordering_and_replay_specification",
                "watchdog_and_disconnect_specification"):
            self.nullable_string(value.get(key), path + "." + key)
        self.hash_value(
            value.get("protocol_definition_sha256"),
            path + ".protocol_definition_sha256",
        )
        self.review(
            "transport_protocol", value.get("review"), path + ".review"
        )

    def safe_relative_path(self, value, path):
        if not self.required_string(value, path):
            return False
        if "\\" in value:
            self.error(
                "UNSAFE_RELATIVE_PATH",
                path,
                "manifest paths must use forward slashes",
            )
            return False
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or any(
                part in ("", ".", "..") for part in parsed.parts):
            self.error(
                "UNSAFE_RELATIVE_PATH",
                path,
                "path must be normalized and relative",
            )
            return False
        if re.match(r"^[A-Za-z]:", value):
            self.error(
                "UNSAFE_RELATIVE_PATH",
                path,
                "drive-qualified path is forbidden",
            )
            return False
        return True

    def validate_cad_sources(self, value):
        path = "$.cad_sources"
        keys = (
            "source_snapshot_name",
            "source_snapshot_sha256",
            "file_count",
            "total_size_bytes",
            "assembly_path",
            "assembly_sha256",
            "neutral_assembly_path",
            "neutral_assembly_sha256",
            "controlled_bom_sha256",
            "controlled_drawing_sha256",
            "files",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        self.required_string(
            value.get("source_snapshot_name"), path + ".source_snapshot_name"
        )
        self.hash_value(
            value.get("source_snapshot_sha256"),
            path + ".source_snapshot_sha256",
        )
        count_ok = self.integer(
            value.get("file_count"), path + ".file_count", minimum=1
        )
        size_ok = self.integer(
            value.get("total_size_bytes"),
            path + ".total_size_bytes",
            minimum=1,
        )
        assembly_path = value.get("assembly_path")
        self.safe_relative_path(assembly_path, path + ".assembly_path")
        self.hash_value(
            value.get("assembly_sha256"),
            path + ".assembly_sha256",
        )
        neutral_path = value.get("neutral_assembly_path")
        if neutral_path is None:
            self.block(
                "NEUTRAL_CAD_UNKNOWN",
                path + ".neutral_assembly_path",
                "controlled STEP or Parasolid assembly is missing",
            )
        else:
            self.safe_relative_path(
                neutral_path, path + ".neutral_assembly_path"
            )
        self.hash_value(
            value.get("neutral_assembly_sha256"),
            path + ".neutral_assembly_sha256",
            unknown_code="NEUTRAL_CAD_UNKNOWN",
        )
        self.hash_value(
            value.get("controlled_bom_sha256"),
            path + ".controlled_bom_sha256",
            unknown_code="CONTROLLED_BOM_UNKNOWN",
        )
        self.hash_value(
            value.get("controlled_drawing_sha256"),
            path + ".controlled_drawing_sha256",
            unknown_code="CONTROLLED_DRAWING_UNKNOWN",
        )
        files = value.get("files")
        valid_entries = []
        if type(files) is not list:
            self.error("TYPE_MISMATCH", path + ".files", "expected file array")
        else:
            seen_paths = set()
            for index, entry in enumerate(files):
                entry_path = "{}[{}]".format(path + ".files", index)
                entry_keys = ("path", "role", "sha256", "size_bytes")
                if not self.exact_object(entry, entry_path, entry_keys):
                    continue
                relative = entry.get("path")
                path_ok = self.safe_relative_path(
                    relative, entry_path + ".path"
                )
                if path_ok:
                    if relative in seen_paths:
                        self.error(
                            "DUPLICATE_CAD_PATH",
                            entry_path + ".path",
                            "CAD paths must be unique",
                        )
                    seen_paths.add(relative)
                role = entry.get("role")
                role_ok = self.required_string(role, entry_path + ".role")
                if role_ok and role not in ("ASSEMBLY", "PART", "TOOLING"):
                    self.error(
                        "INVALID_ENUM",
                        entry_path + ".role",
                        "role must be ASSEMBLY, PART, or TOOLING",
                    )
                    role_ok = False
                hash_ok = self.hash_value(
                    entry.get("sha256"),
                    entry_path + ".sha256",
                )
                entry_size_ok = self.integer(
                    entry.get("size_bytes"),
                    entry_path + ".size_bytes",
                    minimum=1,
                )
                if path_ok and role_ok and hash_ok and entry_size_ok:
                    valid_entries.append(entry)
            if len(valid_entries) == len(files):
                paths = [entry["path"] for entry in files]
                if paths != sorted(paths):
                    self.error(
                        "CAD_ORDER_NOT_CANONICAL",
                        path + ".files",
                        "CAD entries must be sorted by Unicode path",
                    )
                actual_count = len(files)
                if count_ok and value.get("file_count") != actual_count:
                    self.error(
                        "CAD_COUNT_MISMATCH",
                        path + ".file_count",
                        "declared {} but inventory contains {}".format(
                            value.get("file_count"), actual_count
                        ),
                    )
                actual_size = sum(entry["size_bytes"] for entry in files)
                if size_ok and value.get("total_size_bytes") != actual_size:
                    self.error(
                        "CAD_SIZE_MISMATCH",
                        path + ".total_size_bytes",
                        "declared {} but inventory totals {}".format(
                            value.get("total_size_bytes"), actual_size
                        ),
                    )
                actual_snapshot = canonical_cad_inventory_sha256(files)
                declared_snapshot = value.get("source_snapshot_sha256")
                if (
                        type(declared_snapshot) is str
                        and HASH_PATTERN.fullmatch(declared_snapshot)
                        and declared_snapshot.lower() != actual_snapshot):
                    self.error(
                        "CAD_SNAPSHOT_HASH_MISMATCH",
                        path + ".source_snapshot_sha256",
                        "declared snapshot hash does not match file entries",
                    )
                assemblies = [
                    entry for entry in files
                    if entry.get("role") == "ASSEMBLY"
                ]
                if len(assemblies) != 1:
                    self.error(
                        "CAD_ASSEMBLY_COUNT_INVALID",
                        path + ".files",
                        "exactly one assembly entry is required",
                    )
                else:
                    assembly = assemblies[0]
                    if assembly_path != assembly["path"]:
                        self.error(
                            "CAD_ASSEMBLY_PATH_MISMATCH",
                            path + ".assembly_path",
                            "assembly path does not match assembly entry",
                        )
                    declared_hash = value.get("assembly_sha256")
                    if (
                            type(declared_hash) is str
                            and declared_hash.lower()
                            != assembly["sha256"].lower()):
                        self.error(
                            "CAD_ASSEMBLY_HASH_MISMATCH",
                            path + ".assembly_sha256",
                            "assembly hash does not match assembly entry",
                        )
        self.review("cad_sources", value.get("review"), path + ".review")

    def validate_units(self, value):
        path = "$.units"
        keys = tuple(EXPECTED_UNITS) + ("review",)
        if not self.exact_object(value, path, keys):
            return
        for key, expected in EXPECTED_UNITS.items():
            actual = value.get(key)
            if type(actual) is not str:
                self.error(
                    "TYPE_MISMATCH",
                    path + "." + key,
                    "unit must be a string",
                )
            elif actual != expected:
                self.error(
                    "UNIT_MISMATCH",
                    path + "." + key,
                    "unit must be exactly {}".format(expected),
                )
        self.review("units", value.get("review"), path + ".review")

    def validate_flange_tcp(self, value):
        path = "$.flange_tcp"
        keys = (
            "arm_flange_frame",
            "gripper_mount_frame",
            "gripper_tcp_frame",
            "flange_interface_drawing_sha256",
            "fastener_stack_specification_sha256",
            "flange_to_mount_transform",
            "mount_to_tcp_transform",
            "tcp_opening_dependency",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return set()
        frame_names = set()
        for key in (
                "arm_flange_frame", "gripper_mount_frame",
                "gripper_tcp_frame"):
            frame = value.get(key)
            if self.nullable_string(frame, path + "." + key):
                frame_names.add(frame)
        if len(frame_names) not in (0, 3):
            self.error(
                "DUPLICATE_FRAME_NAME",
                path,
                "all three frame names must be distinct",
            )
        self.hash_value(
            value.get("flange_interface_drawing_sha256"),
            path + ".flange_interface_drawing_sha256",
        )
        self.hash_value(
            value.get("fastener_stack_specification_sha256"),
            path + ".fastener_stack_specification_sha256",
        )
        self.transform(
            value.get("flange_to_mount_transform"),
            path + ".flange_to_mount_transform",
        )
        self.transform(
            value.get("mount_to_tcp_transform"),
            path + ".mount_to_tcp_transform",
        )
        dependency = value.get("tcp_opening_dependency")
        dependency_path = path + ".tcp_opening_dependency"
        if dependency is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                dependency_path,
                "opening-dependent TCP disposition is unknown",
            )
        elif self.exact_object(
                dependency,
                dependency_path,
                ("mode", "calibration_sha256", "valid_opening_range_m")):
            mode = dependency.get("mode")
            if self.required_string(mode, dependency_path + ".mode"):
                if mode not in ("FIXED", "OPENING_TABLE"):
                    self.error(
                        "INVALID_ENUM",
                        dependency_path + ".mode",
                        "TCP mode must be FIXED or OPENING_TABLE",
                    )
            self.hash_value(
                dependency.get("calibration_sha256"),
                dependency_path + ".calibration_sha256",
            )
            self.range_object(
                dependency.get("valid_opening_range_m"),
                dependency_path + ".valid_opening_range_m",
                minimum=0,
            )
        self.review("flange_tcp", value.get("review"), path + ".review")
        return frame_names

    def validate_motion_limits(self, value):
        path = "$.motion_limits"
        keys = (
            "native_command_range",
            "jaw_opening_range_m",
            "joints",
            "named_poses",
            "closing_force_limit_n",
            "command_to_opening_calibration_sha256",
            "hard_limit_evidence_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        native = value.get("native_command_range")
        native_path = path + ".native_command_range"
        if native is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                native_path,
                "native command range and direction are unknown",
            )
        elif self.exact_object(
                native,
                native_path,
                ("minimum", "maximum", "unit", "direction")):
            low_ok = self.number(
                native.get("minimum"), native_path + ".minimum"
            )
            high_ok = self.number(
                native.get("maximum"), native_path + ".maximum"
            )
            if low_ok and high_ok and native["minimum"] >= native["maximum"]:
                self.error(
                    "INVALID_RANGE",
                    native_path,
                    "native minimum must be below maximum",
                )
            self.required_string(native.get("unit"), native_path + ".unit")
            direction = native.get("direction")
            if self.required_string(direction, native_path + ".direction"):
                if direction not in (
                        "INCREASING_COMMAND_OPENS",
                        "INCREASING_COMMAND_CLOSES"):
                    self.error(
                        "INVALID_ENUM",
                        native_path + ".direction",
                        "opening direction must be explicit",
                    )
        self.range_object(
            value.get("jaw_opening_range_m"),
            path + ".jaw_opening_range_m",
            minimum=0,
        )
        joints = value.get("joints")
        joint_limits = {}
        if joints is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                path + ".joints",
                "joint axes and limits are unknown",
            )
        elif type(joints) is not list:
            self.error(
                "TYPE_MISMATCH", path + ".joints", "expected joint array"
            )
        elif not joints:
            self.error(
                "EMPTY_JOINT_LIST",
                path + ".joints",
                "at least one controlled joint is required",
            )
        else:
            joint_keys = (
                "name", "lower_rad", "upper_rad",
                "max_velocity_rad_s", "max_acceleration_rad_s2",
            )
            for index, joint in enumerate(joints):
                joint_path = "{}[{}]".format(path + ".joints", index)
                if not self.exact_object(joint, joint_path, joint_keys):
                    continue
                name = joint.get("name")
                name_ok = self.required_string(name, joint_path + ".name")
                low_ok = self.number(joint.get("lower_rad"),
                                     joint_path + ".lower_rad")
                high_ok = self.number(joint.get("upper_rad"),
                                      joint_path + ".upper_rad")
                velocity_ok = self.number(
                    joint.get("max_velocity_rad_s"),
                    joint_path + ".max_velocity_rad_s",
                    strictly_positive=True,
                )
                acceleration_ok = self.number(
                    joint.get("max_acceleration_rad_s2"),
                    joint_path + ".max_acceleration_rad_s2",
                    strictly_positive=True,
                )
                if (
                        low_ok and high_ok
                        and joint["lower_rad"] >= joint["upper_rad"]):
                    self.error(
                        "INVALID_RANGE",
                        joint_path,
                        "joint lower limit must be below upper limit",
                    )
                if name_ok:
                    if name in joint_limits:
                        self.error(
                            "DUPLICATE_JOINT_NAME",
                            joint_path + ".name",
                            "joint names must be unique",
                        )
                    elif (
                            low_ok and high_ok
                            and velocity_ok and acceleration_ok):
                        joint_limits[name] = (
                            joint["lower_rad"], joint["upper_rad"]
                        )
        named = value.get("named_poses")
        named_path = path + ".named_poses"
        if named is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                named_path,
                "open, mid, and closed poses are unknown",
            )
        elif self.exact_object(named, named_path, ("open", "mid", "closed")):
            for pose_name in ("open", "mid", "closed"):
                pose = named.get(pose_name)
                pose_path = named_path + "." + pose_name
                if type(pose) is not dict:
                    self.error(
                        "TYPE_MISMATCH",
                        pose_path,
                        "named pose must be a joint-value object",
                    )
                    continue
                if set(pose) != set(joint_limits):
                    self.error(
                        "NAMED_POSE_JOINT_MISMATCH",
                        pose_path,
                        "named pose must contain every and only declared "
                        "joint",
                    )
                for joint_name, position in pose.items():
                    position_path = pose_path + "." + joint_name
                    if not self.number(position, position_path):
                        continue
                    if joint_name in joint_limits:
                        lower, upper = joint_limits[joint_name]
                        if position < lower or position > upper:
                            self.error(
                                "NAMED_POSE_OUT_OF_LIMITS",
                                position_path,
                                "named pose lies outside joint limits",
                            )
        self.nullable_number(
            value.get("closing_force_limit_n"),
            path + ".closing_force_limit_n",
            strictly_positive=True,
        )
        self.hash_value(
            value.get("command_to_opening_calibration_sha256"),
            path + ".command_to_opening_calibration_sha256",
        )
        self.hash_value(
            value.get("hard_limit_evidence_sha256"),
            path + ".hard_limit_evidence_sha256",
        )
        self.review("motion_limits", value.get("review"), path + ".review")

    def validate_mass_properties(self, value, frame_names):
        path = "$.mass_properties"
        keys = (
            "installed_tool_mass_kg",
            "mass_measurement_uncertainty_kg",
            "center_of_mass",
            "inertia_tensor",
            "includes_adapter_fasteners_cable",
            "mass_property_report_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        mass_ok = self.nullable_number(
            value.get("installed_tool_mass_kg"),
            path + ".installed_tool_mass_kg",
            strictly_positive=True,
        )
        uncertainty_ok = self.nullable_number(
            value.get("mass_measurement_uncertainty_kg"),
            path + ".mass_measurement_uncertainty_kg",
            minimum=0,
        )
        if mass_ok and uncertainty_ok:
            if value["mass_measurement_uncertainty_kg"] >= value[
                    "installed_tool_mass_kg"]:
                self.error(
                    "INVALID_UNCERTAINTY",
                    path + ".mass_measurement_uncertainty_kg",
                    "mass uncertainty must be below measured mass",
                )
        com = value.get("center_of_mass")
        com_path = path + ".center_of_mass"
        if com is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN", com_path, "center of mass is unknown"
            )
        elif self.exact_object(com, com_path, ("frame", "xyz_m")):
            frame = com.get("frame")
            if self.required_string(frame, com_path + ".frame"):
                if frame not in frame_names:
                    self.error(
                        "UNKNOWN_FRAME",
                        com_path + ".frame",
                        "CoM frame must be a declared gripper frame",
                    )
            self.vector(com.get("xyz_m"), com_path + ".xyz_m", 3)
        inertia = value.get("inertia_tensor")
        inertia_path = path + ".inertia_tensor"
        inertia_keys = ("frame", "ixx", "iyy", "izz", "ixy", "ixz", "iyz")
        if inertia is None:
            self.block(
                "REQUIRED_VALUE_UNKNOWN",
                inertia_path,
                "six-term inertia tensor is unknown",
            )
        elif self.exact_object(inertia, inertia_path, inertia_keys):
            frame = inertia.get("frame")
            if self.required_string(frame, inertia_path + ".frame"):
                if frame not in frame_names:
                    self.error(
                        "UNKNOWN_FRAME",
                        inertia_path + ".frame",
                        "inertia frame must be a declared gripper frame",
                    )
            diagonal_ok = []
            for key in ("ixx", "iyy", "izz"):
                diagonal_ok.append(self.number(
                    inertia.get(key),
                    inertia_path + "." + key,
                    strictly_positive=True,
                ))
            for key in ("ixy", "ixz", "iyz"):
                self.number(inertia.get(key), inertia_path + "." + key)
            if all(diagonal_ok):
                ixx, iyy, izz = (
                    inertia["ixx"], inertia["iyy"], inertia["izz"]
                )
                if ixx > iyy + izz or iyy > ixx + izz or izz > ixx + iyy:
                    self.error(
                        "INVALID_INERTIA_TENSOR",
                        inertia_path,
                        "principal moments violate triangle inequalities",
                    )
        self.required_assertion(
            value.get("includes_adapter_fasteners_cable"),
            path + ".includes_adapter_fasteners_cable",
        )
        self.hash_value(
            value.get("mass_property_report_sha256"),
            path + ".mass_property_report_sha256",
        )
        self.review(
            "mass_properties", value.get("review"), path + ".review"
        )

    def validate_collision(self, value, frame_names):
        path = "$.collision_cable_envelope"
        keys = (
            "visual_mesh_manifest_sha256",
            "collision_mesh_manifest_sha256",
            "open_envelope",
            "mid_envelope",
            "closed_envelope",
            "cable_envelope",
            "cable_minimum_bend_radius_m",
            "cable_strain_relief_verified",
            "interference_review_passed",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "visual_mesh_manifest_sha256",
                "collision_mesh_manifest_sha256"):
            self.hash_value(value.get(key), path + "." + key)
        for key in (
                "open_envelope", "mid_envelope", "closed_envelope",
                "cable_envelope"):
            self.aabb(value.get(key), path + "." + key, frame_names)
        self.nullable_number(
            value.get("cable_minimum_bend_radius_m"),
            path + ".cable_minimum_bend_radius_m",
            strictly_positive=True,
        )
        self.required_assertion(
            value.get("cable_strain_relief_verified"),
            path + ".cable_strain_relief_verified",
        )
        self.required_assertion(
            value.get("interference_review_passed"),
            path + ".interference_review_passed",
        )
        self.review(
            "collision_cable_envelope",
            value.get("review"),
            path + ".review",
        )

    def validate_electrical(self, value):
        path = "$.electrical"
        keys = (
            "rated_supply_voltage_v",
            "absolute_supply_voltage_v",
            "idle_current_a",
            "startup_current_a",
            "rated_current_a",
            "peak_current_a",
            "stall_current_a",
            "conductor_cross_section_mm2",
            "fuse_or_current_limit_a",
            "connector_pinout_sha256",
            "polarity_and_grounding",
            "protection_specification_sha256",
            "hot_plug_policy",
            "energy_isolation_specification_sha256",
            "static_inspection_passed",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        rated = self.range_object(
            value.get("rated_supply_voltage_v"),
            path + ".rated_supply_voltage_v",
            minimum=0,
        )
        absolute = self.range_object(
            value.get("absolute_supply_voltage_v"),
            path + ".absolute_supply_voltage_v",
            minimum=0,
        )
        if rated is not None and absolute is not None:
            if (
                    absolute["minimum"] > rated["minimum"]
                    or absolute["maximum"] < rated["maximum"]):
                self.error(
                    "ELECTRICAL_RANGE_INCONSISTENT",
                    path,
                    "absolute voltage range must contain rated range",
                )
        currents = {}
        for key in (
                "idle_current_a", "startup_current_a", "rated_current_a",
                "peak_current_a", "stall_current_a"):
            if self.nullable_number(
                    value.get(key), path + "." + key, minimum=0):
                currents[key] = value[key]
        if all(key in currents for key in (
                "idle_current_a", "rated_current_a", "peak_current_a",
                "stall_current_a")):
            if not (
                    currents["idle_current_a"]
                    <= currents["rated_current_a"]
                    <= currents["peak_current_a"]
                    <= currents["stall_current_a"]):
                self.error(
                    "ELECTRICAL_CURRENT_ORDER_INVALID",
                    path,
                    "expected idle <= rated <= peak <= stall current",
                )
        if (
                "startup_current_a" in currents
                and "stall_current_a" in currents
                and currents["startup_current_a"]
                > currents["stall_current_a"]):
            self.error(
                "ELECTRICAL_CURRENT_ORDER_INVALID",
                path + ".startup_current_a",
                "startup current must not exceed stall current",
            )
        self.nullable_number(
            value.get("conductor_cross_section_mm2"),
            path + ".conductor_cross_section_mm2",
            strictly_positive=True,
        )
        self.nullable_number(
            value.get("fuse_or_current_limit_a"),
            path + ".fuse_or_current_limit_a",
            strictly_positive=True,
        )
        for key in (
                "connector_pinout_sha256", "protection_specification_sha256",
                "energy_isolation_specification_sha256"):
            self.hash_value(value.get(key), path + "." + key)
        self.nullable_string(
            value.get("polarity_and_grounding"),
            path + ".polarity_and_grounding",
        )
        hot_plug = value.get("hot_plug_policy")
        if self.nullable_string(hot_plug, path + ".hot_plug_policy"):
            if hot_plug not in (
                    "PROHIBITED", "PERMITTED_BY_CONTROLLED_SPECIFICATION"):
                self.error(
                    "INVALID_ENUM",
                    path + ".hot_plug_policy",
                    "hot-plug policy must be explicitly controlled",
                )
        self.required_assertion(
            value.get("static_inspection_passed"),
            path + ".static_inspection_passed",
        )
        self.review("electrical", value.get("review"), path + ".review")

    def validate_passive_power_loss_safety(self, value):
        path = "$.passive_power_loss_safety"
        keys = (
            "backdrivability",
            "brake",
            "self_locking",
            "loss_of_power_jaw_behavior",
            "object_drop_hazard",
            "secondary_retention_or_exclusion",
            "loss_of_power_hazard_analysis_sha256",
            "passive_safety_static_inspection_sha256",
            "controlled_review_passed",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        self.nullable_enum(
            value.get("backdrivability"),
            path + ".backdrivability",
            {
                "BACKDRIVABLE",
                "NOT_BACKDRIVABLE",
                "CONDITION_DEPENDENT",
            },
            code="PASSIVE_SAFETY_UNKNOWN",
        )
        self.nullable_enum(
            value.get("brake"),
            path + ".brake",
            {"PRESENT", "ABSENT"},
            code="PASSIVE_SAFETY_UNKNOWN",
        )
        self.nullable_enum(
            value.get("self_locking"),
            path + ".self_locking",
            {
                "SELF_LOCKING",
                "NOT_SELF_LOCKING",
                "CONDITION_DEPENDENT",
            },
            code="PASSIVE_SAFETY_UNKNOWN",
        )
        self.nullable_enum(
            value.get("loss_of_power_jaw_behavior"),
            path + ".loss_of_power_jaw_behavior",
            {
                "RELEASES",
                "RETAINS",
                "MOVES_TO_DEFINED_SAFE_POSITION",
            },
            code="PASSIVE_SAFETY_UNKNOWN",
        )
        for key in (
                "object_drop_hazard",
                "secondary_retention_or_exclusion"):
            self.nullable_string(
                value.get(key),
                path + "." + key,
                code="PASSIVE_SAFETY_UNKNOWN",
            )
        for key in (
                "loss_of_power_hazard_analysis_sha256",
                "passive_safety_static_inspection_sha256"):
            self.hash_value(
                value.get(key),
                path + "." + key,
                unknown_code="PASSIVE_SAFETY_EVIDENCE_UNKNOWN",
            )
        self.required_assertion(
            value.get("controlled_review_passed"),
            path + ".controlled_review_passed",
            code="PASSIVE_SAFETY_REVIEW_NOT_PASSED",
        )
        self.review(
            "passive_power_loss_safety",
            value.get("review"),
            path + ".review",
        )

    def validate_contact_human_safety(self, value):
        path = "$.contact_human_safety"
        keys = (
            "pad_material",
            "pad_compliance",
            "pad_retention",
            "allowable_contact_pressure",
            "cleaning_and_chemical_compatibility",
            "pinch_hazard_review_passed",
            "shear_hazard_review_passed",
            "crush_hazard_review_passed",
            "entanglement_hazard_review_passed",
            "sharp_edge_guarding_review_passed",
            "contact_interface_specification_sha256",
            "hazard_guarding_inspection_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "pad_material",
                "pad_compliance",
                "pad_retention",
                "allowable_contact_pressure",
                "cleaning_and_chemical_compatibility"):
            self.nullable_string(
                value.get(key),
                path + "." + key,
                code="CONTACT_HUMAN_SAFETY_UNKNOWN",
            )
        for key in (
                "pinch_hazard_review_passed",
                "shear_hazard_review_passed",
                "crush_hazard_review_passed",
                "entanglement_hazard_review_passed",
                "sharp_edge_guarding_review_passed"):
            self.required_assertion(
                value.get(key),
                path + "." + key,
                code="CONTACT_HUMAN_SAFETY_REVIEW_NOT_PASSED",
            )
        for key in (
                "contact_interface_specification_sha256",
                "hazard_guarding_inspection_sha256"):
            self.hash_value(
                value.get(key),
                path + "." + key,
                unknown_code="CONTACT_HUMAN_SAFETY_EVIDENCE_UNKNOWN",
            )
        self.review(
            "contact_human_safety",
            value.get("review"),
            path + ".review",
        )

    def validate_durability_maintenance(self, value):
        path = "$.durability_maintenance"
        keys = (
            "rated_cycle_life_cycles",
            "rated_duty_cycle",
            "gear_bearing_load_life_basis",
            "wear_limit_specification",
            "backlash_limit_specification",
            "lubrication_specification",
            "fastener_locking_and_torque_mark_policy",
            "inspection_interval",
            "replacement_criteria",
            "approved_spares_revision_control",
            "maintenance_plan_sha256",
            "initial_static_condition_sha256",
            "initial_static_inspection_passed",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        self.nullable_integer(
            value.get("rated_cycle_life_cycles"),
            path + ".rated_cycle_life_cycles",
            code="DURABILITY_MAINTENANCE_UNKNOWN",
            minimum=1,
        )
        for key in (
                "rated_duty_cycle",
                "gear_bearing_load_life_basis",
                "wear_limit_specification",
                "backlash_limit_specification",
                "lubrication_specification",
                "fastener_locking_and_torque_mark_policy",
                "inspection_interval",
                "replacement_criteria",
                "approved_spares_revision_control"):
            self.nullable_string(
                value.get(key),
                path + "." + key,
                code="DURABILITY_MAINTENANCE_UNKNOWN",
            )
        for key in (
                "maintenance_plan_sha256",
                "initial_static_condition_sha256"):
            self.hash_value(
                value.get(key),
                path + "." + key,
                unknown_code="DURABILITY_MAINTENANCE_EVIDENCE_UNKNOWN",
            )
        self.required_assertion(
            value.get("initial_static_inspection_passed"),
            path + ".initial_static_inspection_passed",
            code="DURABILITY_STATIC_INSPECTION_NOT_PASSED",
        )
        self.review(
            "durability_maintenance",
            value.get("review"),
            path + ".review",
        )

    def validate_backend_execution_safety(self, value):
        path = "$.backend_execution_safety"
        keys = (
            "release_binding",
            "motion_profile_binding",
            "method_deadlines_s",
            "method_timeout_handling",
            "stop_isolation",
            "backend_method_contract_sha256",
            "stop_isolation_architecture_sha256",
            "hung_command_stop_test_report_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        release_binding = value.get("release_binding")
        release_path = path + ".release_binding"
        release_id = None
        release_sha256 = None
        if self.exact_object(
                release_binding,
                release_path,
                ("runtime_release_id", "release_manifest_sha256")):
            if self.nullable_string(
                    release_binding.get("runtime_release_id"),
                    release_path + ".runtime_release_id",
                    code="BACKEND_RELEASE_BINDING_UNKNOWN"):
                release_id = release_binding["runtime_release_id"]
                if release_id != release_id.strip():
                    self.error(
                        "BACKEND_RELEASE_BINDING_NOT_EXACT",
                        release_path + ".runtime_release_id",
                        "runtime release ID must not contain surrounding "
                        "whitespace",
                    )
            if self.hash_value(
                    release_binding.get("release_manifest_sha256"),
                    release_path + ".release_manifest_sha256",
                    unknown_code="BACKEND_RELEASE_BINDING_UNKNOWN"):
                release_sha256 = release_binding[
                    "release_manifest_sha256"]
                if release_sha256 != release_sha256.lower():
                    self.error(
                        "BACKEND_RELEASE_BINDING_NOT_EXACT",
                        release_path + ".release_manifest_sha256",
                        "release manifest binding must be lowercase SHA-256",
                    )

        profile_binding = value.get("motion_profile_binding")
        profile_path = path + ".motion_profile_binding"
        if self.exact_object(
                profile_binding,
                profile_path,
                (
                    "profile_id",
                    "runtime_release_id",
                    "profile_manifest_sha256",
                    "approved_speed_grades",
                )):
            self.nullable_string(
                profile_binding.get("profile_id"),
                profile_path + ".profile_id",
                code="BACKEND_PROFILE_BINDING_UNKNOWN",
            )
            profile_runtime_id = profile_binding.get("runtime_release_id")
            if self.nullable_string(
                    profile_runtime_id,
                    profile_path + ".runtime_release_id",
                    code="BACKEND_PROFILE_BINDING_UNKNOWN"):
                if profile_runtime_id != profile_runtime_id.strip():
                    self.error(
                        "BACKEND_PROFILE_BINDING_NOT_EXACT",
                        profile_path + ".runtime_release_id",
                        "profile runtime release ID must not contain "
                        "surrounding whitespace",
                    )
                if release_id is not None and profile_runtime_id != release_id:
                    self.block(
                        "BACKEND_PROFILE_RUNTIME_MISMATCH",
                        profile_path + ".runtime_release_id",
                        "motion profile must bind to the exact backend runtime "
                        "release ID",
                    )
            profile_sha256 = profile_binding.get("profile_manifest_sha256")
            if self.hash_value(
                    profile_sha256,
                    profile_path + ".profile_manifest_sha256",
                    unknown_code="BACKEND_PROFILE_BINDING_UNKNOWN"):
                if profile_sha256 != profile_sha256.lower():
                    self.error(
                        "BACKEND_PROFILE_BINDING_NOT_EXACT",
                        profile_path + ".profile_manifest_sha256",
                        "motion profile binding must be lowercase SHA-256",
                    )
                if (
                        release_sha256 is not None
                        and profile_sha256 == release_sha256):
                    self.block(
                        "BACKEND_BINDING_HASH_REUSE",
                        profile_path + ".profile_manifest_sha256",
                        "runtime release and motion profile must be distinct "
                        "reviewed artifacts",
                    )
            grades = profile_binding.get("approved_speed_grades")
            grades_path = profile_path + ".approved_speed_grades"
            if grades is None:
                self.block(
                    "BACKEND_APPROVED_SPEED_GRADES_UNKNOWN",
                    grades_path,
                    "approved speed grades are unknown",
                )
            elif type(grades) is not list:
                self.error(
                    "TYPE_MISMATCH", grades_path,
                    "approved speed grades must be an array",
                )
            elif not grades:
                self.block(
                    "BACKEND_APPROVED_SPEED_GRADES_UNKNOWN",
                    grades_path,
                    "at least one approved speed grade is required",
                )
            else:
                grades_valid = True
                for index, grade in enumerate(grades):
                    grade_path = "{}[{}]".format(grades_path, index)
                    if not self.integer(grade, grade_path, minimum=1):
                        grades_valid = False
                    elif grade > 100:
                        grades_valid = False
                        self.error(
                            "VALUE_OUT_OF_RANGE", grade_path,
                            "approved speed grade must not exceed 100",
                        )
                if grades_valid and grades != sorted(set(grades)):
                    self.error(
                        "BACKEND_APPROVED_SPEED_GRADES_NOT_EXACT",
                        grades_path,
                        "approved speed grades must be unique and increasing",
                    )
        method_keys = (
            "read_state", "command_position", "stop", "close"
        )
        deadlines = value.get("method_deadlines_s")
        deadlines_path = path + ".method_deadlines_s"
        if deadlines is None:
            self.block(
                "BACKEND_METHOD_DEADLINES_UNKNOWN",
                deadlines_path,
                "every backend method requires a finite deadline",
            )
        elif self.exact_object(deadlines, deadlines_path, method_keys):
            for key in method_keys:
                self.nullable_number(
                    deadlines.get(key),
                    deadlines_path + "." + key,
                    code="BACKEND_METHOD_DEADLINES_UNKNOWN",
                    strictly_positive=True,
                )
        handling = value.get("method_timeout_handling")
        handling_path = path + ".method_timeout_handling"
        if handling is None:
            self.block(
                "BACKEND_METHOD_CANCELLATION_UNKNOWN",
                handling_path,
                "every backend method requires cancellation or bounded "
                "abandonment semantics",
            )
        elif self.exact_object(handling, handling_path, method_keys):
            for key in method_keys:
                self.nullable_enum(
                    handling.get(key),
                    handling_path + "." + key,
                    {"CANCELLABLE", "BOUNDED_ABANDONMENT"},
                    code="BACKEND_METHOD_CANCELLATION_UNKNOWN",
                )
        isolation = value.get("stop_isolation")
        isolation_path = path + ".stop_isolation"
        isolation_keys = (
            "independent_executor",
            "independent_lock_domain",
            "not_queued_behind_normal_commands",
            "hung_command_stop_deadline_s",
            "hung_command_stop_deadline_verified",
            "deadline_miss_fails_closed",
        )
        if isolation is None:
            self.block(
                "STOP_ISOLATION_UNKNOWN",
                isolation_path,
                "STOP scheduling and lock isolation are unknown",
            )
        elif self.exact_object(isolation, isolation_path, isolation_keys):
            for key in (
                    "independent_executor",
                    "independent_lock_domain",
                    "not_queued_behind_normal_commands",
                    "hung_command_stop_deadline_verified",
                    "deadline_miss_fails_closed"):
                self.required_assertion(
                    isolation.get(key),
                    isolation_path + "." + key,
                    code="STOP_ISOLATION_NOT_PROVEN",
                )
            self.nullable_number(
                isolation.get("hung_command_stop_deadline_s"),
                isolation_path + ".hung_command_stop_deadline_s",
                code="STOP_ISOLATION_UNKNOWN",
                strictly_positive=True,
            )
        for key in (
                "backend_method_contract_sha256",
                "stop_isolation_architecture_sha256",
                "hung_command_stop_test_report_sha256"):
            self.hash_value(
                value.get(key),
                path + "." + key,
                unknown_code="BACKEND_EXECUTION_EVIDENCE_UNKNOWN",
            )
        self.review(
            "backend_execution_safety",
            value.get("review"),
            path + ".review",
        )

    def validate_feedback_contract(self, value):
        """Require an explicit interface-to-feedback capability contract."""
        path = "$.feedback_contract"
        keys = (
            "field_capabilities",
            "source_timestamp_specification",
            "receive_timestamp_specification",
            "sequence_specification",
            "invalid_value_specification",
            "fault_dictionary_sha256",
            "fault_latch_and_recovery_specification",
            "command_feedback_correlation_specification",
            "controller_restart_specification",
            "normalized_position_command_supported",
            "jaw_opening_command_supported",
            "command_capability_specification_sha256",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        capabilities = value.get("field_capabilities")
        capabilities_path = path + ".field_capabilities"
        if self.exact_object(
                capabilities, capabilities_path, FEEDBACK_FIELD_NAMES):
            for field_name in FEEDBACK_FIELD_NAMES:
                field_path = capabilities_path + "." + field_name
                capability = capabilities.get(field_name)
                if not self.exact_object(
                        capability,
                        field_path,
                        (
                            "support", "unit", "encoding", "range",
                            "resolution", "update_rate_hz",
                            "validity_specification",
                        )):
                    continue
                support = capability.get("support")
                if support not in FEEDBACK_SUPPORT_VALUES:
                    if support is None:
                        self.block(
                            "FEEDBACK_FIELD_SUPPORT_UNKNOWN",
                            field_path + ".support",
                            "field support must be explicitly classified",
                        )
                    else:
                        self.error(
                            "INVALID_ENUM",
                            field_path + ".support",
                            "support must be SUPPORTED or UNSUPPORTED",
                        )
                    continue
                if (
                        field_name in MANDATORY_FEEDBACK_FIELDS
                        and support != "SUPPORTED"):
                    self.block(
                        "MANDATORY_FEEDBACK_FIELD_UNSUPPORTED",
                        field_path + ".support",
                        "release requires this safety feedback field",
                    )
                detail_keys = (
                    "unit", "encoding", "range", "resolution",
                    "update_rate_hz", "validity_specification",
                )
                if support == "SUPPORTED":
                    for key in detail_keys:
                        self.nullable_string(
                            capability.get(key),
                            field_path + "." + key,
                            code="FEEDBACK_FIELD_CONTRACT_UNKNOWN",
                        )
                else:
                    for key in detail_keys:
                        if capability.get(key) is not None:
                            self.error(
                                "UNSUPPORTED_FEEDBACK_HAS_CONTRACT",
                                field_path + "." + key,
                                "unsupported fields must not declare a "
                                "runtime contract",
                            )
        for key in (
                "source_timestamp_specification",
                "receive_timestamp_specification",
                "sequence_specification",
                "invalid_value_specification",
                "fault_latch_and_recovery_specification",
                "command_feedback_correlation_specification",
                "controller_restart_specification"):
            self.nullable_string(
                value.get(key),
                path + "." + key,
                code="FEEDBACK_CONTRACT_UNKNOWN",
            )
        self.hash_value(
            value.get("fault_dictionary_sha256"),
            path + ".fault_dictionary_sha256",
            unknown_code="FAULT_DICTIONARY_UNKNOWN",
        )
        self.required_assertion(
            value.get("normalized_position_command_supported"),
            path + ".normalized_position_command_supported",
            code="NORMALIZED_COMMAND_CAPABILITY_UNPROVEN",
        )
        jaw_supported = value.get("jaw_opening_command_supported")
        if self.boolean(
                jaw_supported, path + ".jaw_opening_command_supported"):
            jaw_feedback = (
                capabilities.get("jaw_opening_m")
                if type(capabilities) is dict else None)
            jaw_feedback_supported = (
                type(jaw_feedback) is dict
                and jaw_feedback.get("support") == "SUPPORTED")
            if jaw_supported and not jaw_feedback_supported:
                self.block(
                    "JAW_COMMAND_WITHOUT_FEEDBACK_CONTRACT",
                    path + ".jaw_opening_command_supported",
                    "jaw-opening commands require supported jaw-opening "
                    "feedback",
                )
        self.hash_value(
            value.get("command_capability_specification_sha256"),
            path + ".command_capability_specification_sha256",
            unknown_code="COMMAND_CAPABILITY_EVIDENCE_UNKNOWN",
        )
        self.review(
            "feedback_contract", value.get("review"), path + ".review"
        )

    def validate_stop_stationary_ack(self, value):
        path = "$.stop_stationary_ack"
        keys = ("stop", "stationary", "ack", "recovery", "review")
        if not self.exact_object(value, path, keys):
            return
        stop = value.get("stop")
        stop_path = path + ".stop"
        stop_keys = (
            "request_mechanism",
            "acknowledgement_mechanism",
            "ack_timeout_s",
            "safe_output_state",
            "latched_until_local_ack",
            "independent_energy_isolation_required",
            "software_stop_is_not_physical_estop",
        )
        if stop is None:
            self.block(
                "STOP_SEMANTICS_INCOMPLETE",
                stop_path,
                "STOP request and acknowledgement semantics are unknown",
            )
        elif self.exact_object(stop, stop_path, stop_keys):
            for key in (
                    "request_mechanism", "acknowledgement_mechanism",
                    "safe_output_state"):
                self.nullable_string(
                    stop.get(key),
                    stop_path + "." + key,
                    code="STOP_SEMANTICS_INCOMPLETE",
                )
            self.nullable_number(
                stop.get("ack_timeout_s"),
                stop_path + ".ack_timeout_s",
                code="STOP_SEMANTICS_INCOMPLETE",
                strictly_positive=True,
            )
            for key in (
                    "latched_until_local_ack",
                    "independent_energy_isolation_required",
                    "software_stop_is_not_physical_estop"):
                self.required_assertion(
                    stop.get(key),
                    stop_path + "." + key,
                    code="STOP_SEMANTICS_UNSAFE",
                )
        stationary = value.get("stationary")
        stationary_path = path + ".stationary"
        stationary_keys = (
            "feedback_signal",
            "feedback_unit",
            "position_tolerance_native",
            "minimum_consecutive_samples",
            "dwell_s",
            "sample_period_s",
            "timeout_s",
            "invalid_feedback_fails_closed",
        )
        if stationary is None:
            self.block(
                "STATIONARY_SEMANTICS_INCOMPLETE",
                stationary_path,
                "stationary detection semantics are unknown",
            )
        elif self.exact_object(
                stationary, stationary_path, stationary_keys):
            for key in ("feedback_signal", "feedback_unit"):
                self.nullable_string(
                    stationary.get(key),
                    stationary_path + "." + key,
                    code="STATIONARY_SEMANTICS_INCOMPLETE",
                )
            self.nullable_number(
                stationary.get("position_tolerance_native"),
                stationary_path + ".position_tolerance_native",
                code="STATIONARY_SEMANTICS_INCOMPLETE",
                strictly_positive=True,
            )
            samples = stationary.get("minimum_consecutive_samples")
            if samples is None:
                self.block(
                    "STATIONARY_SEMANTICS_INCOMPLETE",
                    stationary_path + ".minimum_consecutive_samples",
                    "stationary sample count is unknown",
                )
            else:
                self.integer(
                    samples,
                    stationary_path + ".minimum_consecutive_samples",
                    minimum=2,
                )
            timing_ok = {}
            for key in ("dwell_s", "sample_period_s", "timeout_s"):
                timing_ok[key] = self.nullable_number(
                    stationary.get(key),
                    stationary_path + "." + key,
                    code="STATIONARY_SEMANTICS_INCOMPLETE",
                    strictly_positive=True,
                )
            if timing_ok.get("dwell_s") and timing_ok.get("timeout_s"):
                if stationary["timeout_s"] <= stationary["dwell_s"]:
                    self.error(
                        "STATIONARY_TIMEOUT_INVALID",
                        stationary_path + ".timeout_s",
                        "stationary timeout must exceed dwell",
                    )
            self.required_assertion(
                stationary.get("invalid_feedback_fails_closed"),
                stationary_path + ".invalid_feedback_fails_closed",
                code="STATIONARY_SEMANTICS_UNSAFE",
            )
        ack = value.get("ack")
        ack_path = path + ".ack"
        ack_keys = (
            "matching_session_required",
            "matching_fault_required",
            "local_authorization_required",
            "requires_stationary",
            "may_initialize_controller",
            "may_enable_output",
            "may_clear_controller_fault",
            "may_resume_motion",
            "may_retry_command",
        )
        if ack is None:
            self.block(
                "ACK_SEMANTICS_INCOMPLETE",
                ack_path,
                "local ACK semantics are unknown",
            )
        elif self.exact_object(ack, ack_path, ack_keys):
            for key in (
                    "matching_session_required", "matching_fault_required",
                    "local_authorization_required", "requires_stationary"):
                self.required_assertion(
                    ack.get(key),
                    ack_path + "." + key,
                    code="ACK_SEMANTICS_UNSAFE",
                )
            for key in (
                    "may_initialize_controller", "may_enable_output",
                    "may_clear_controller_fault", "may_resume_motion",
                    "may_retry_command"):
                self.required_assertion(
                    ack.get(key),
                    ack_path + "." + key,
                    expected=False,
                    code="ACK_SEMANTICS_UNSAFE",
                )
        recovery = value.get("recovery")
        recovery_path = path + ".recovery"
        recovery_keys = (
            "new_command_id_required",
            "new_session_after_controller_restart_required",
            "no_automatic_reenable",
            "no_automatic_resume",
            "unresolved_stop_escalation",
            "software_stop_failure_requires_physical_isolation",
        )
        if recovery is None:
            self.block(
                "RECOVERY_SEMANTICS_INCOMPLETE",
                recovery_path,
                "error recovery semantics are unknown",
            )
        elif self.exact_object(recovery, recovery_path, recovery_keys):
            for key in (
                    "new_command_id_required",
                    "new_session_after_controller_restart_required",
                    "no_automatic_reenable", "no_automatic_resume",
                    "software_stop_failure_requires_physical_isolation"):
                self.required_assertion(
                    recovery.get(key),
                    recovery_path + "." + key,
                    code="RECOVERY_SEMANTICS_UNSAFE",
                )
            escalation = recovery.get("unresolved_stop_escalation")
            if self.nullable_string(
                    escalation,
                    recovery_path + ".unresolved_stop_escalation",
                    code="RECOVERY_SEMANTICS_INCOMPLETE"):
                if escalation != "PHYSICAL_ESTOP_REQUIRED":
                    self.block(
                        "RECOVERY_SEMANTICS_UNSAFE",
                        recovery_path + ".unresolved_stop_escalation",
                        "unresolved STOP must require physical emergency "
                        "response",
                    )
        self.review(
            "stop_stationary_ack", value.get("review"), path + ".review"
        )

    def validate_transport_owner(self, value):
        path = "$.transport_owner"
        keys = (
            "owner_identity",
            "ownership_scope",
            "arbitration_mechanism",
            "owner_lock_artifact_sha256",
            "ownership_evidence_sha256",
            "sole_owner_verified",
            "boot_session_identity_required",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "owner_identity", "ownership_scope", "arbitration_mechanism"):
            self.nullable_string(value.get(key), path + "." + key)
        for key in (
                "owner_lock_artifact_sha256", "ownership_evidence_sha256"):
            self.hash_value(value.get(key), path + "." + key)
        self.required_assertion(
            value.get("sole_owner_verified"),
            path + ".sole_owner_verified",
            code="TRANSPORT_OWNER_NOT_UNIQUE",
        )
        self.required_assertion(
            value.get("boot_session_identity_required"),
            path + ".boot_session_identity_required",
        )
        self.review(
            "transport_owner", value.get("review"), path + ".review"
        )

    def validate_legacy_policy(self, value):
        path = "$.legacy_input_policy"
        keys = (
            "ag_parameters_inherited",
            "generic_servo_parameters_inherited",
            "generated_staging_geometry_inherited",
            "historical_tcp_or_mass_inherited",
            "legacy_transport_fallback_present",
            "denylist_scan_passed",
            "review",
        )
        if not self.exact_object(value, path, keys):
            return
        for key in (
                "ag_parameters_inherited",
                "generic_servo_parameters_inherited",
                "generated_staging_geometry_inherited",
                "historical_tcp_or_mass_inherited",
                "legacy_transport_fallback_present"):
            self.required_assertion(
                value.get(key),
                path + "." + key,
                expected=False,
                code="LEGACY_INPUT_POLICY_UNSAFE",
            )
        self.required_assertion(
            value.get("denylist_scan_passed"),
            path + ".denylist_scan_passed",
            code="LEGACY_DENYLIST_NOT_PASSED",
        )
        self.review(
            "legacy_input_policy", value.get("review"), path + ".review"
        )

    def scan_legacy_inputs(self, manifest):
        def scan_value(value, path):
            if type(value) is dict:
                for key in sorted(value):
                    if type(key) is str:
                        scan_text(key, path + ".<key>")
                    scan_value(value[key], path + "." + key)
            elif type(value) is list:
                for index, item in enumerate(value):
                    scan_value(item, "{}[{}]".format(path, index))
            elif type(value) is str:
                scan_text(value, path)

        def scan_text(value, path):
            normalized = _normalize_legacy_scan_text(value)
            for label, pattern in LEGACY_STRING_PATTERNS:
                if pattern.search(normalized):
                    self.error(
                        "LEGACY_INPUT_DETECTED",
                        path,
                        "forbidden inherited input detected: {}".format(
                            label
                        ),
                    )
        scan_value(manifest, "$")
        motion = manifest.get("motion_limits")
        if type(motion) is dict:
            native = motion.get("native_command_range")
            if type(native) is dict:
                if native.get("minimum") == 0 and native.get("maximum") == 100:
                    self.error(
                        "LEGACY_INPUT_DETECTED",
                        "$.motion_limits.native_command_range",
                        "retired AG 0..100 command range is forbidden",
                    )
                if (
                        native.get("minimum") == 255
                        or native.get("maximum") == 255):
                    self.error(
                        "LEGACY_INPUT_DETECTED",
                        "$.motion_limits.native_command_range",
                        "retired 255 sentinel is forbidden",
                    )
            opening = motion.get("jaw_opening_range_m")
            if type(opening) is dict:
                if (
                        opening.get("minimum") == 0.02
                        and opening.get("maximum") == 0.045):
                    self.error(
                        "LEGACY_INPUT_DETECTED",
                        "$.motion_limits.jaw_opening_range_m",
                        "retired AG 20--45 mm opening is forbidden",
                    )
                if opening.get("maximum") in (0.06884, 0.03442):
                    self.error(
                        "LEGACY_INPUT_DETECTED",
                        "$.motion_limits.jaw_opening_range_m.maximum",
                        "generated staging geometry is forbidden",
                    )
        mass = manifest.get("mass_properties")
        if type(mass) is dict and mass.get("installed_tool_mass_kg") in (
                0.1, 0.115, 0.17):
            self.error(
                "LEGACY_INPUT_DETECTED",
                "$.mass_properties.installed_tool_mass_kg",
                "historical or generated mass assumption is forbidden",
            )
        flange = manifest.get("flange_tcp")
        if type(flange) is dict:
            transform = flange.get("mount_to_tcp_transform")
            if type(transform) is dict:
                translation = transform.get("translation_m")
                if translation == [0, 0.0931, 0.0025]:
                    self.error(
                        "LEGACY_INPUT_DETECTED",
                        "$.flange_tcp.mount_to_tcp_transform.translation_m",
                        "generated staging TCP is forbidden",
                    )

    def validate(self, manifest):
        if not self.exact_object(manifest, "$", TOP_LEVEL_KEYS):
            return self.result()
        schema_id = manifest.get("schema_id")
        if schema_id != SCHEMA_ID:
            self.error(
                "SCHEMA_ID_MISMATCH",
                "$.schema_id",
                "schema_id must be exactly {}".format(SCHEMA_ID),
            )
        version = manifest.get("schema_version")
        if type(version) is not int:
            self.error(
                "TYPE_MISMATCH",
                "$.schema_version",
                "schema version must be an integer",
            )
        elif version != SCHEMA_VERSION:
            self.error(
                "SCHEMA_VERSION_MISMATCH",
                "$.schema_version",
                "unsupported schema version",
            )
        self.nullable_string(manifest.get("manifest_id"), "$.manifest_id")
        self.nullable_string(
            manifest.get("manifest_revision"), "$.manifest_revision"
        )
        self.timestamp(manifest.get("created_at_utc"), "$.created_at_utc")
        requested = manifest.get("release_requested")
        approved = manifest.get("release_approved")
        if self.boolean(requested, "$.release_requested"):
            if not requested:
                self.block(
                    "RELEASE_NOT_REQUESTED",
                    "$.release_requested",
                    "release_requested must be true for release",
                )
        if self.boolean(approved, "$.release_approved"):
            if not approved:
                self.block(
                    "RELEASE_NOT_APPROVED",
                    "$.release_approved",
                    "release_approved must be true for release",
                )
            if approved and requested is False:
                self.error(
                    "APPROVAL_WITHOUT_REQUEST",
                    "$.release_approved",
                    "release cannot be approved before it is requested",
                )
        self.validate_evidence(manifest.get("evidence_records"))
        self.validate_tool_identity(manifest.get("tool_identity"))
        self.validate_controller_firmware(manifest.get("controller_firmware"))
        self.validate_transport_protocol(manifest.get("transport_protocol"))
        self.validate_cad_sources(manifest.get("cad_sources"))
        self.validate_units(manifest.get("units"))
        frame_names = self.validate_flange_tcp(manifest.get("flange_tcp"))
        if frame_names is None:
            frame_names = set()
        self.validate_motion_limits(manifest.get("motion_limits"))
        self.validate_mass_properties(
            manifest.get("mass_properties"), frame_names
        )
        self.validate_collision(
            manifest.get("collision_cable_envelope"), frame_names
        )
        self.validate_electrical(manifest.get("electrical"))
        self.validate_passive_power_loss_safety(
            manifest.get("passive_power_loss_safety")
        )
        self.validate_contact_human_safety(
            manifest.get("contact_human_safety")
        )
        self.validate_durability_maintenance(
            manifest.get("durability_maintenance")
        )
        self.validate_backend_execution_safety(
            manifest.get("backend_execution_safety")
        )
        self.validate_feedback_contract(manifest.get("feedback_contract"))
        self.validate_stop_stationary_ack(
            manifest.get("stop_stationary_ack")
        )
        self.validate_transport_owner(manifest.get("transport_owner"))
        self.validate_legacy_policy(manifest.get("legacy_input_policy"))
        self.validate_review_references()
        self.scan_legacy_inputs(manifest)
        identity = manifest.get("tool_identity")
        cad = manifest.get("cad_sources")
        if type(identity) is dict and type(cad) is dict:
            identity_hash = identity.get("assembly_sha256")
            cad_hash = cad.get("assembly_sha256")
            if (
                    type(identity_hash) is str
                    and type(cad_hash) is str
                    and HASH_PATTERN.fullmatch(identity_hash)
                    and HASH_PATTERN.fullmatch(cad_hash)
                    and identity_hash.lower() != cad_hash.lower()):
                self.error(
                    "ASSEMBLY_IDENTITY_MISMATCH",
                    "$.tool_identity.assembly_sha256",
                    "tool identity and CAD assembly hashes differ",
                )
        return self.result()

    def result(self):
        key = lambda item: (item.path, item.code, item.message)
        return ManifestValidationResult(
            errors=tuple(sorted(set(self.errors), key=key)),
            blockers=tuple(sorted(set(self.blockers), key=key)),
        )


def validate_manifest_structure(manifest):
    """Validate manifest declarations without claiming artifact binding."""
    return _Validator().validate(manifest)


def validate_manifest(manifest, artifact_root=None, cad_root=None):
    """Run the complete disconnected release gate, including file binding.

    Both roots are intentionally mandatory.  Call
    :func:`validate_manifest_structure` when a schema-only diagnostic is
    required; a structural pass alone must never be treated as release-ready.
    """
    return _merge_validation_results(
        validate_manifest_structure(manifest),
        validate_manifest_bindings(
            manifest,
            artifact_root=artifact_root,
            cad_root=cad_root,
        ),
    )


def main(argv=None):
    """Run the strict offline release gate and emit a JSON report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--cad-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        report = validate_manifest(
            manifest,
            artifact_root=args.artifact_root,
            cad_root=args.cad_root,
        ).as_dict()
    except ManifestLoadError as error:
        report = {
            "schema_id": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "schema_valid": False,
            "release_ready": False,
            "error_count": 1,
            "blocker_count": 0,
            "errors": [{
                "code": error.code,
                "path": "$",
                "message": error.message,
            }],
            "blockers": [],
        }
    output = json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    if args.report is not None:
        args.report.write_text(output, encoding="utf-8")
    sys.stdout.write(output)
    return 0 if report["release_ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
